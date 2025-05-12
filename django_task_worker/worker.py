import importlib
import json
import random
import signal
import time
from datetime import timedelta

import redis
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from stopit import ThreadingTimeout
import concurrent.futures

from .logger import logger
from .models import DatabaseTask

from sentry_sdk import capture_exception
import sys

RUNNING = True

REDIS_URL = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
REDIS_PASSWORD = getattr(settings, "REDIS_PASSWORD", None)

REDIS_CHANNEL = "task_events"

def handle_shutdown_signal(signum, frame):
    global RUNNING
    RUNNING = False

def run_worker(max_retries=0, worker_concurrency=1):
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

    logger.info(f"Started task worker with Redis URL: {REDIS_URL}")

    redis_client = redis.Redis.from_url(REDIS_URL, password=REDIS_PASSWORD)
    pubsub = redis_client.pubsub()
    pubsub.subscribe(REDIS_CHANNEL)

    logger.info("Connected to Redis server and subscribed to channel.")

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=worker_concurrency)

    global RUNNING
    while RUNNING:
        try:
            # 0) Housekeeping for 'PROGRESS' tasks that have exceeded their timeout
            _mark_stale_progress_tasks(max_retries=max_retries)

            # 1) Process all PENDING tasks
            pending_tasks = DatabaseTask.objects.filter(status="PENDING").order_by("created_at")
            for task in pending_tasks:
                if not RUNNING:
                    break
                executor.submit(_process_task_by_id, task.id, redis_client, max_retries)

            # 2) Process FAILED tasks that haven't exceeded MAX_RETRIES
            failed_retryable = DatabaseTask.objects.filter(status="FAILED", retry_count__lt=max_retries).order_by("created_at")
            for task in failed_retryable:
                if not RUNNING:
                    break
                executor.submit(_process_task_by_id, task.id, redis_client, max_retries)

            # 3) Listen for Pub/Sub 'task_created' messages
            message = pubsub.get_message(timeout=2, ignore_subscribe_messages=True)
            if message and message["type"] == "message":
                data = message["data"]
                try:
                    payload = json.loads(data)
                    event = payload.get("event")
                    task_id = payload.get("task_id")

                    if event == "task_created" and task_id is not None:
                        executor.submit(_process_task_by_id, task_id, redis_client, max_retries)
                except json.JSONDecodeError:
                    logger.error("Invalid JSON message received.")

        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            time.sleep(2)

    logger.info("Stopping gracefully...")
    pubsub.close()
    executor.shutdown(wait=False)

def _mark_stale_progress_tasks(max_retries: int):
    """
    Find tasks in PROGRESS whose (started_at + timeout) is in the past, forcibly mark them FAILED.
    This covers the scenario where a worker died mid-task.
    """
    now = timezone.now()
    # Filter tasks that are PROGRESS, started_at is not null, and have a positive timeout
    progress_tasks = DatabaseTask.objects.filter(
        status="PROGRESS",
        started_at__isnull=False,
        timeout__gt=0
    )

    for task in progress_tasks:
        cutoff = task.started_at + timedelta(seconds=task.timeout)
        if cutoff < now:
            # The task has exceeded its allocated time
            _force_fail_stale_task(task, max_retries)

def _force_fail_stale_task(task: DatabaseTask, max_retries: int):
    """
    Safely mark a stale in-progress task as FAILED inside a transaction.
    Optionally increment retry_count so it can be retried if below MAX_RETRIES.
    """
    try:
        with transaction.atomic():
            fresh = DatabaseTask.objects.select_for_update().get(id=task.id)
            # Double-check it's still PROGRESS
            if fresh.status == "PROGRESS":
                # Timeout exceeded
                fresh.retry_count += 1
                fresh.finished_at = timezone.now()
                fresh.duration = (fresh.finished_at - fresh.started_at).total_seconds()
                fresh.error = "Task was stale (worker died?), forcibly marking FAILED."

                if fresh.retry_count < max_retries:
                    fresh.status = "PENDING"
                    logger.warning(f"Task {fresh.id} was stale in PROGRESS. Retrying (retry_count={fresh.retry_count}).")
                    fresh.save()
                    _publish_event("task_requeued", fresh.id)
                else:
                    fresh.status = "FAILED"
                    logger.warning(f"Task {fresh.id} final FAILURE after stale. Error: {fresh.error}")
                    fresh.save()
                    _publish_event("task_failed", fresh.id)
    except DatabaseTask.DoesNotExist:
        # Might have been deleted or changed concurrently
        pass
    except Exception as e:
        logger.error(f"Could not force-fail stale task {task.id}: {e}")

def _process_task_by_id(task_id, redis_client, max_retries: int):
    logger.info(f"Processing task {task_id}...")

    # Random short delay to reduce simultaneous lock attempts
    time.sleep(random.uniform(0, 0.1))

    lock_key = f"task_lock:{task_id}"
    acquired_lock = redis_client.set(lock_key, 1, ex=30, nx=True)
    if not acquired_lock:
        # Another worker is already processing
        return

    skip = False
    try:
        with transaction.atomic():
            fresh_task = DatabaseTask.objects.select_for_update().get(id=task_id)

            if fresh_task.status in ("PROGRESS", "COMPLETED"):
                # Task already in progress or completed
                skip = True
            elif fresh_task.status == "FAILED" and fresh_task.retry_count >= max_retries:
                # Task finally failed
                skip = True
            elif fresh_task.next_attempt_at and fresh_task.next_attempt_at > timezone.now():
                # Not yet time to retry
                skip = True
            else:
                fresh_task.status = "PROGRESS"
                fresh_task.error = None
                fresh_task.result = None
                fresh_task.started_at = timezone.now()
                fresh_task.save()

        if skip:
            return

        start_time = time.time()
        task_timeout = fresh_task.timeout or 300
        with ThreadingTimeout(task_timeout) as to_ctx:
            result = _execute_task(fresh_task)

        if to_ctx.state == to_ctx.EXECUTED:
            _mark_completed(fresh_task, result, start_time)
        else:
            _mark_failed(fresh_task, "Task timed out", start_time, max_retries)

    except Exception as exc:
        try:
            _mark_failed(fresh_task, str(exc), time.time(), max_retries, exc=exc)
        except Exception as e:
            logger.error(f"Could not mark task {task_id} as failed: {exc} by {e}")
    finally:
        _release_redis_lock(redis_client, lock_key)

def _execute_task(task: DatabaseTask):
    """
    Dynamically import, refresh, and call the function specified by `task.name`.
    Assumes the module path starts with 'worker.tasks', and task.name is formatted as 'module_name.function_name'.
    """
    logger.info(f"Running task {task.id}: {task.name}")
    try:
        module_name, func_name = task.name.rsplit(".", 1)
    except ValueError:
        raise ValueError(f'The task name "{task.name}" is not formatted correctly')

    try:
        module = importlib.import_module(module_name)
        module = importlib.reload(module)
        func = getattr(module, func_name)
        return func(*task.args, **task.kwargs)
    except ModuleNotFoundError as e:
        raise e
    except AttributeError as e:
        raise ImportError(f'Function "{func_name}" not found in "{module_name}". '
                          f'Error: {e} '
                          f'name should be like "module_name.function_name". '
                          f'Base import paths are {sys.path}.')
    except Exception as e:
        raise ImportError(f"Error while executing task '{task.name}': {e}")

def _mark_completed(task: DatabaseTask, result, start_time: float):
    duration = time.time() - start_time
    with transaction.atomic():
        fresh = DatabaseTask.objects.select_for_update().get(id=task.id)
        fresh.status = "COMPLETED"
        fresh.finished_at = timezone.now()
        fresh.duration = duration
        fresh.result = str(result)
        fresh.save()

    logger.info(f"Task {task.id} completed successfully.")
    _publish_event("task_finished", task.id)

def _mark_failed(task: DatabaseTask, error_msg: str, start_time: float, max_retries: int, exc=None):
    duration = time.time() - start_time

    if exc:
        capture_exception(exc)

    with transaction.atomic():
        fresh = DatabaseTask.objects.select_for_update().get(id=task.id)
        fresh.retry_count += 1
        fresh.finished_at = timezone.now()
        fresh.duration = duration
        fresh.error = error_msg

        if fresh.retry_count < max_retries:
            backoff_seconds = 2 ** fresh.retry_count
            fresh.next_attempt_at = timezone.now() + timedelta(seconds=backoff_seconds)

            fresh.status = "FAILED"
            logger.warning(f"Task {fresh.id} failed. Retrying (retry_count={fresh.retry_count}).")
            fresh.save()
            _publish_event("task_requeued", fresh.id)
        else:
            fresh.status = "FAILED"
            logger.warning(f"Task {fresh.id} final FAILURE after {fresh.retry_count} attempts. Error: {error_msg}")
            fresh.save()
            _publish_event("task_failed", fresh.id)

def _release_redis_lock(redis_client, lock_key: str):
    try:
        redis_client.delete(lock_key)
    except Exception as e:
        logger.error(f"Error releasing Redis lock {lock_key}: {e}")

def _publish_event(event_name: str, task_id: int):
    payload = {"event": event_name, "task_id": task_id}
    r = redis.Redis.from_url(REDIS_URL, password=REDIS_PASSWORD)
    r.publish(REDIS_CHANNEL, json.dumps(payload))
