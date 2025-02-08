from django.core.management.base import BaseCommand
from worker.worker import run_worker

class Command(BaseCommand):
    help = "Run the background worker loop for tasks."

    def handle(self, *args, **options):
        run_worker()
