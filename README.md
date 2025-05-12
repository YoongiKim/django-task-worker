# django-task-worker

A Django-based task worker that uses the database as a persistent queue and Redis for Pub/Sub messaging. This project is designed to solve common issues with traditional task queues like Celery by offering a lightweight, reliable, and cost-effective solution.

---

## **Motivation**

Traditional task queues like [Celery](https://docs.celeryproject.org/) rely on external message brokers (e.g., Redis, RabbitMQ) to persist task queues and results. While this approach is powerful, it comes with significant challenges:

1. **Single Point of Failure**: The message broker (e.g., Redis) becomes a critical dependency. Restarting it can lead to task loss if not properly configured.
2. **Cluster Complexity**: Setting up a high-availability cluster for Redis or RabbitMQ is complex and resource-intensive.
3. **Cost**: Cloud-hosted Redis instances are expensive, especially for small-scale projects that only need basic task queuing.

### **Why django-task-worker?**

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

## **Installation**

1. Install the package:

    ```bash
    pip install django-task-worker
    ```

2. Add `worker` to your `INSTALLED_APPS` in `settings.py`:

    ```python
    INSTALLED_APPS = [
       ...,
       "django_task_worker",
    ]
    ```

3. Configure Redis in your `settings.py`:

    ```python
    import os
    ...
    # Worker settings
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', None)
    ```

4. Run migrations to create the `DatabaseTask` table:

    ```bash
    python manage.py makemigrations django_task_worker
    python manage.py migrate
    ```

5. Start the worker process using the management command:

    ```bash
    python manage.py run_worker --retry 1 --concurrency 2
    ```
    - `--retry`: Maximum number of retries for failed tasks (default: 0).
    - `--concurrency`: Number of threads to process tasks concurrently (default: 1).

---
## **Usage**

### **How Task Functions are Executed**

The worker dynamically imports and executes the task functions specified in the `name` field of the task. The `name` must be in the format:

```
module_name.function_name
```

The worker assumes all modules are accessible from the Django project's root directory.

---

### **Directory Structure Example**

Your Django project should be organized as follows:

```
your_project/
├── config/
│   ├── settings.py          # Django settings file
│   └── wsgi.py
├── manage.py                # Django management script
├── your_app/
│   ├── __init__.py          # __init__.py must be present
│   ├── your_tasks.py        # Define task functions here
│   └── models.py
└── django_task_worker/  # Which is installed via pip
    ├── models.py            # Includes DatabaseTask
    ├── client.py            # Provides create_task and wait_for_completion
    └── worker.py            # Worker logic
```

Define task functions in a module like `your_app/your_tasks.py`.

#### **Example Task Definition**
```
# your_app/your_tasks.py

def add_numbers(a, b):
    return a + b
```

---

### **How to Create and Run a Task**

#### **1. Create a Task**

Use `create_task` to add a task to the database and notify the worker:

```
from django_task_worker.client import create_task

task = create_task(
    name="your_app.your_tasks.add_numbers",  # Function path
    args=[10, 20],                           # Positional arguments
    kwargs={},                               # Keyword arguments
    timeout=300                              # Timeout in seconds
)

print(f"Task {task.id} created with status: {task.status}")
```

---

#### **2. Run the Worker**

Start the worker using the Django management command:

```
python manage.py run_worker
```

The worker will process tasks in the background.

---

#### **3. Wait for Task Completion**

Use `wait_for_completion` to wait for a task to finish:

```
from django_task_worker.client import wait_for_completion

result = wait_for_completion(task_id=task.id, timeout=10)

if result:
    print(f"Task {result.id} completed with status: {result.status}")
    print(f"Result: {result.result}")
else:
    print("Task did not complete within the timeout.")
```

---

### **API Reference**

#### **`create_task`**
```
def create_task(name, args=None, kwargs=None, timeout=300) -> DatabaseTask:
    """
    Create a task in the database and notify the worker via Redis.

    Args:
        name (str): Function to execute (e.g., 'module_name.function_name').
        args (list, optional): Positional arguments for the function. Defaults to an empty list.
        kwargs (dict, optional): Keyword arguments for the function. Defaults to an empty dict.
        timeout (int, optional): Task timeout in seconds. Defaults to 300.

    Returns:
        DatabaseTask: The created task object.
    """
```

#### **`wait_for_completion`**
```
def wait_for_completion(task_id, timeout=300) -> DatabaseTask | None:
    """
    Wait for a task to complete or fail within the given timeout.

    Args:
        task_id (int): The ID of the task to wait for.
        timeout (int, optional): Maximum time to wait in seconds. Defaults to 300.

    Returns:
        DatabaseTask: The task object if completed successfully.
        None: If the task does not complete within the timeout.
    """
```

---

### **Task Model**

All tasks are stored in the database using the `DatabaseTask` model:

```
from django_task_worker.models import DatabaseTask
```

#### **DatabaseTask Fields**:
- `id` (str): Short UUID for the task.
- `name` (str): The task function in the format `module_name.function_name`.
- `args` (JSON): Positional arguments for the task.
- `kwargs` (JSON): Keyword arguments for the task.
- `timeout` (int): Time in seconds before the task times out.
- `status` (str): Current status (`PENDING`, `PROGRESS`, `COMPLETED`, or `FAILED`).
- `result` (str): Task result after completion.
- `error` (str): Error message if the task fails.
- `retry_count` (int): Number of times the task has been retried.'
- `created_at` (DateTime): Task creation timestamp.
- `updated_at` (DateTime): Task last update timestamp.
- `started_at` (DateTime): Task start timestamp.
- `finished_at` (DateTime): Task finish timestamp.
- `duration` (float): Total time spent processing the task (in seconds).

---

### **Quick Example**

1. **Define a Task** in `app/tasks.py`:
    ```
    def multiply_numbers(a, b):
       return a * b
    ```

2. **Create and Run the Task**:
    ```
    from django_task_worker.client import create_task, wait_for_completion
    
    # Create a task
    task = create_task("app.tasks.multiply_numbers", args=[2, 3])
    
    # Wait for completion
    result = wait_for_completion(task.id, timeout=10)
    if result:
       print(f"Task Result: {result.result}")
    ```

3. **Run the Worker**:
    ```
    python manage.py run_worker
    ```

4. **Test using Django Shell**:
    ```
    python manage.py shell
    ```
    ```
    from django_task_worker.client import create_task, wait_for_completion
    task = create_task("app.tasks.multiply_numbers", args=[2, 3])
    result = wait_for_completion(task.id, timeout=10)
    print(result)  # Task srzm5AdyjhEGJVeL3WZiWN: app.tasks.multiply_numbers (COMPLETED)
    print(result.result)  # "6"
    ```

---

### **Example docker-compose configuration**

docker-compose.yml
```yaml
services:
  db:
    image: postgres:latest
    restart: always
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: ${DB_NAME}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    stop_grace_period: 30s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "1"

  redis:
    image: redis:latest
    restart: always
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
    stop_grace_period: 30s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "1"

  backend:
    build:
      context: .
      dockerfile: Dockerfile
    restart: always
    environment:
      DB_HOST: db
      DB_PORT: ${DB_PORT}
      DB_USER: ${DB_USER}
      DB_PASSWORD: ${DB_PASSWORD}
      DB_NAME: ${DB_NAME}
      REDIS_URL: ${REDIS_URL}
      SECRET_KEY: ${SECRET_KEY}
    networks:
      - default
    stop_grace_period: 30s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "1"
    depends_on:
      - db
      - redis

  worker:
    build:
      context: .
      dockerfile: Dockerfile
    command: ["python", "manage.py", "run_worker"]
    restart: always
    environment:
      DB_HOST: db
      DB_PORT: 5432
      DB_USER: ${DB_USER}
      DB_PASSWORD: ${DB_PASSWORD}
      DB_NAME: ${DB_NAME}
      REDIS_URL: ${REDIS_URL}
      SECRET_KEY: ${SECRET_KEY}
    networks:
      - default
    stop_grace_period: 300s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "1"
    depends_on:
      - db
      - redis

networks:
  default:
    driver: bridge

volumes:
  postgres_data:
  redis_data:
```

Dockerfile
```Dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl nano git

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

EXPOSE 8000

CMD ["gunicorn", "-b", "0.0.0.0:8000", "config.wsgi:application"]
```

### **TODO List**
- [x] Redis Authentication
- [x] Concurrency
- [x] Exponential back-offs
- [ ] Scheduled tasks
- [ ] Advanced django admin
- [ ] Detailed error logging
