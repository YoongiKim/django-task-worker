import json
import time
import redis
from django.conf import settings
from django_task_worker.models import DatabaseTask

REDIS_URL = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
REDIS_CHANNEL = "task_events"

r = redis.Redis.from_url(REDIS_URL)

def create_task(name, args=None, kwargs=None, timeout=300) -> DatabaseTask:
    """
    Create a new task in the database and publish a 'task_created' event.
    """
    task = DatabaseTask.objects.create(
        name=name,
        args=args or [],
        kwargs=kwargs or {},
        timeout=timeout,
        status="PENDING"
    )
    payload = {"event": "task_created", "task_id": task.id}
    r.publish(REDIS_CHANNEL, json.dumps(payload))
    return task


def wait_for_completion(task_id, timeout=300) -> DatabaseTask | None:
    """
    Wait up to 'timeout' seconds for a task to finish or fail.

    Returns:
        DatabaseTask: The final state of the task if finished/failed in time.
        None: If the task doesn't finish within 'timeout' seconds.
    """
    pubsub = r.pubsub()
    pubsub.subscribe(REDIS_CHANNEL)

    start_time = time.time()
    try:
        while time.time() - start_time < timeout:
            # Check if the task is already finished
            task = DatabaseTask.objects.get(id=task_id)
            if task.status in ("SUCCESS", "FAILURE"):
                return task

            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
            if message:
                if message["type"] == "message":
                    payload = json.loads(message["data"])
                    event = payload.get("event")
                    msg_task_id = payload.get("task_id")

                    # Check if this message is about our specific task
                    if msg_task_id == task_id and event in ("task_finished", "task_failed"):
                        # Task ended (success or fail). Return current DB state.
                        return DatabaseTask.objects.get(id=task_id)
            else:
                # No message received in this iteration; keep waiting
                pass

        # If we exit the loop, it means we timed out
        return None

    finally:
        # Clean up subscription
        pubsub.unsubscribe(REDIS_CHANNEL)
        pubsub.close()
