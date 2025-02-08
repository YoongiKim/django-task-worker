# django-simple-task-worker

A simple Django-based task worker that uses the database as a persistent queue and Redis for Pub/Sub messaging. This project is designed to solve common issues with traditional task queues like Celery by offering a lightweight, reliable, and cost-effective solution.

---

## **Motivation**

Traditional task queues like [Celery](https://docs.celeryproject.org/) rely on external message brokers (e.g., Redis, RabbitMQ) to persist task queues and results. While this approach is powerful, it comes with significant challenges:

1. **Single Point of Failure**: The message broker (e.g., Redis) becomes a critical dependency. Restarting it can lead to task loss if not properly configured.
2. **Cluster Complexity**: Setting up a high-availability cluster for Redis or RabbitMQ is complex and resource-intensive.
3. **Cost**: Cloud-hosted Redis instances are expensive, especially for small-scale projects that only need basic task queuing.

### **Why django-simple-task-worker?**

This project aims to address these issues by:

- **Persisting the task queue in Django's database**: Tasks are stored reliably in the database, ensuring no data is lost even if Redis is restarted or stopped.
- **Using Redis only for Pub/Sub**: Redis is used exclusively for real-time job creation and completion notifications. Redis can be safely flushed or restarted without affecting task data.
- **Simplifying deployment**: By eliminating the need for complex message broker setups, this worker integrates seamlessly with Django projects.

---

## **Features**

- **Database-Backed Queue**: Tasks are stored persistently in a Django model (`DatabaseTask`), ensuring no data loss even if Redis is restarted or flushed. This eliminates the need for Redis persistence.
- **Redis Pub/Sub for Real-Time Notifications**: Redis is used exclusively for lightweight Pub/Sub messaging, sending notifications for task creation and completion. The task queue itself is stored and managed in the database.
- **Task Status Management**: The system uses four statuses to track task progress:
   - **`PENDING`**: Task is waiting to be processed.
   - **`PROGRESS`**: Task is currently being processed by a worker.
   - **`COMPLETED`**: Task has been successfully processed.
   - **`FAILED`**: Task has failed due to an error or timeout.
- **Timeout Handling**: Tasks can have a configurable `timeout` (default: 300 seconds). If a task exceeds its timeout, it is forcefully terminated to prevent it from hanging indefinitely and marked as `FAILED`.
- **Retry Logic**: Failed tasks are retried automatically up to a configurable maximum retry count (`MAX_RETRIES`). Once retries are exhausted, the task is permanently marked as `FAILED`.
- **Stale Task Detection**: If a worker crashes while processing a task (`PROGRESS`), the system detects and marks it as `FAILED` or re-queues it for retry based on its retry count. This ensures no task is left incomplete.
- **Race Condition Prevention for Clusters**: Multiple workers can run in parallel in a clustered setup, with safeguards to prevent race conditions:
   - Redis-based locks ensure only one worker processes a task at a time.
   - Database `select_for_update()` locks prevent concurrent updates to task rows.
- **Graceful Shutdown**: Workers listen for termination signals (e.g., `SIGINT`, `SIGTERM`) and shut down gracefully. Pending tasks are finished before stopping, ensuring no interruptions during processing.
- **Execution Order**: After a worker restart, all **`PENDING`** tasks are processed first, followed by retryable **`FAILED`** tasks. This ensures new tasks receive immediate attention while failed tasks are retried in order.
- **Task Execution Insights**: Each task includes the following timestamps for transparency and debugging:
   - **`created_at`**: When the task was created.
   - **`started_at`**: When the task started processing.
   - **`finished_at`**: When the task finished processing.
   - **`duration`**: Total time (in seconds) spent processing the task.

---

## **Use Cases**

1. **Resilient Task Queue Without Broker Persistence**  
   Unlike Celery, which requires Redis or RabbitMQ to persist task queues, `django-simple-task-worker` stores all tasks in the database. This eliminates dependency on Redis persistence, ensuring no data loss during Redis flushes, restarts, or unavailability.

2. **Graceful Recovery from Worker Crashes**  
   If a worker crashes while processing a task (`status="PROGRESS"`), the system automatically detects these stale tasks during a housekeeping step. If the task’s timeout has elapsed, it is:
   - Marked as `FAILED` with an error message (e.g., `Task was stale. Worker crashed.`).
   - Optionally re-queued for retry if retries are still available.

   This ensures no task remains stuck in `PROGRESS` indefinitely.

3. **Cluster-Friendly Task Execution**  
   For setups with multiple workers:
   - Redis-based locks (`task_lock:{id}`) prevent more than one worker from processing the same task concurrently.
   - Database `select_for_update()` ensures safe updates to task status and prevents race conditions during retries or housekeeping.
   - Workers can operate independently without interfering with one another.

4. **Graceful Shutdown for Running Workers**  
   Workers gracefully handle termination signals (`SIGINT`, `SIGTERM`):
   - No new tasks are picked up after receiving a signal.
   - Tasks already in `PROGRESS` are allowed to finish before the worker shuts down.
   - This ensures tasks are never abandoned mid-execution.

5. **Timeout Prevention for Long-Running Tasks**  
   Tasks with an unexpected delay or stuck processing are terminated forcefully after their timeout. This prevents the system from hanging indefinitely on problematic tasks.

6. **Execution Order After Restart**  
   After a worker restart, all **`PENDING`** tasks are processed first, ensuring new tasks are executed promptly. Retryable **`FAILED`** tasks are processed next, adhering to the task creation order.

7. **Detailed Task Insights**  
   Each task includes metadata to help track and debug its lifecycle:
   - `created_at`: When the task was added to the queue.
   - `started_at`: When processing began.
   - `finished_at`: When processing finished (or failed).
   - `duration`: Total execution time (in seconds).
     This makes it easy to measure performance and identify issues during execution.

---

## **Installation**

1. Install the package:

   ```bash
   pip install django-simple-task-worker
   ```

2. Add `worker` to your `INSTALLED_APPS` in `settings.py`:

   ```python
   INSTALLED_APPS = [
       ...,
       "worker",
   ]
   ```

3. Configure Redis in your `settings.py`:

   ```python
   REDIS_URL = "redis://localhost:6379/0"  # Update this to match your Redis setup
   ```

4. Run migrations to create the `DatabaseTask` table:

   ```bash
   python manage.py makemigrations worker
   python manage.py migrate
   ```

---

## **Usage**

### **1. Define Tasks**

Tasks are Python functions stored in the `worker/tasks/` directory. For example:

```python
# worker/tasks/example_task.py

def example_function(a, b):
    return a + b
```

### **2. Create Tasks**

Create tasks in your application code using the `create_task` function:

```python
from worker.client import create_task

task = create_task(
    name="example_task.example_function",  # Task's module and function
    args=[1, 2],                           # Positional arguments
    kwargs={},                             # Keyword arguments
    timeout=300                            # Task timeout in seconds (optional)
)
```

This queues the task in the database and sends a `task_created` event via Redis Pub/Sub.

### **3. Run the Worker**

Start the worker using the management command:

```bash
python manage.py run_worker
```

The worker will:

- Process tasks from the database queue.
- Receive new task events in real-time via Redis Pub/Sub.
- Automatically retry failed tasks and handle timeouts.

### **4. Wait for Task Completion (Optional)**

If you need to wait for a task to finish, use the `wait_for_completion` function:

```python
from worker.client import wait_for_completion

result = wait_for_completion(task_id=task.id, timeout=60)

if result is None:
    print("Task did not finish in time!")
else:
    print(f"Task finished with status: {result.status}")
    print(f"Task result: {result.result}")
    print(f"Task error (if any): {result.error}")
```

---

## **Configuration**

### **Settings**

- **`REDIS_URL`**: Redis connection URL. Default: `"redis://localhost:6379/0"`.
- **`MAX_RETRIES`**: Maximum number of retries for a failed task. Default: `2`.

### **Task Timeouts**

Set a timeout for tasks during creation. Tasks that exceed their timeout will be marked as `FAILED`.

```python
task = create_task("example_task.example_function", args=[1, 2], timeout=120)
```

---

## **Examples**

### **Example Task**

Define a simple task in `worker/tasks/math.py`:

```python
def add(a, b):
    return a + b
```

### **Queue and Process the Task**

```python
from worker.client import create_task, wait_for_completion

# Create a task
task = create_task("math.add", args=[3, 5])

# Wait for the task to complete
result = wait_for_completion(task_id=task.id, timeout=60)

if result and result.status == "COMPLETED":
    print(f"Task completed successfully: {result.result}")  # Output: Task completed successfully: 8
```
