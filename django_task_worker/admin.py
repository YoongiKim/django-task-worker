from django.contrib import admin
from django_task_worker.models import DatabaseTask

admin.site.register(DatabaseTask)
