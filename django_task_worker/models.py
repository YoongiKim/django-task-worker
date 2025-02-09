from django.db import models
from shortuuid.django_fields import ShortUUIDField
from django.utils import timezone
from datetime import timedelta


class DatabaseTask(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROGRESS", "Progress"),
        ("COMPLETED", "Completed"),
        ("FAILED", "Failed"),
    ]
    id = ShortUUIDField(primary_key=True, editable=False)
    name = models.CharField(max_length=255)
    args = models.JSONField(blank=True, null=True)
    kwargs = models.JSONField(blank=True, null=True)
    timeout = models.IntegerField(blank=True, null=True, default=300)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    result = models.TextField(blank=True, null=True)
    error = models.TextField(blank=True, null=True)

    retry_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(blank=True, null=True, default=None)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(blank=True, null=True, default=None)
    finished_at = models.DateTimeField(blank=True, null=True, default=None)
    duration = models.FloatField(blank=True, null=True, default=None)

    def __str__(self):
        return f"Task {self.id}: {self.name} ({self.status})"
