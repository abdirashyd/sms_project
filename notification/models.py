from django.db import models
from django.conf import settings


class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('ALL', 'All Users'),
        ('CLASS', 'Specific Class'),
        ('STUDENT', 'Specific Student'),
        ('TEACHER', 'Specific Teacher'),
        ('PARENT', 'Specific Parent'),
        ('FEE', 'Fee Reminder'),
        ('RESULT', 'Result Published'),
    )
    
    # Who sent the notification
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_notifications',
        null=True,
        blank=True
    )
    
    # Who receives the notification (can be null for type-based)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_notifications',
        null=True,
        blank=True
    )
    
    # For class-based notifications
    target_class = models.ForeignKey(
        'academic.Classroom',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications'
    )
    
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='ALL')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.created_at.strftime('%Y-%m-%d')}"