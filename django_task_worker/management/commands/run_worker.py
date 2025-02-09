from django.core.management.base import BaseCommand
from django_task_worker.worker import run_worker

class Command(BaseCommand):
    help = "Run the background worker loop for tasks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--retry",
            type=int,
            default=0,
            help="Maximum number of retries for failed tasks (default: 0).",
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=1,
            help="Number of concurrent workers (default: 1).",
        )

    def handle(self, *args, **options):
        retry = options["retry"]
        concurrency = options["concurrency"]
        assert retry >= 0, "Retry count must be non-negative."
        assert concurrency > 0, "Concurrency must be positive."

        run_worker(max_retries=retry, worker_concurrency=concurrency)
