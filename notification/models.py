from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta


class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('ALL', 'All Users'),
        ('CLASS', 'Specific Class'),
        ('STUDENT', 'Specific Student'),
        ('TEACHER', 'Specific Teacher'),
        ('PARENT', 'Specific Parent'),
        ('FEE', 'Fee Reminder'),
        ('RESULT', 'Result Published'),
        
        # NEW: Payment-related
        ('PAYMENT_SUBMITTED', 'Payment Submitted'),
        ('PAYMENT_APPROVED', 'Payment Approved'),
        ('PAYMENT_REJECTED', 'Payment Rejected'),
        ('FEE_BALANCE_UPDATE', 'Fee Balance Update'),
        ('FEES_CLEARED', 'Fees Cleared'),
        ('RECEIPT_READY', 'Receipt Ready'),
        
        # NEW: Account-related
        ('ACCOUNT_CREATED', 'Account Created'),
        ('ACCOUNT_ACTIVATED', 'Account Activated'),
        ('PASSWORD_RESET', 'Password Reset'),
        ('PASSWORD_CHANGED', 'Password Changed'),
        
        # NEW: Registration-related
        ('STUDENT_REGISTERED', 'Student Registered'),
        ('PARENT_REGISTERED', 'Parent Registered'),
        ('TEACHER_REGISTERED', 'Teacher Registered'),
        ('BULK_UPLOAD_COMPLETE', 'Bulk Upload Complete'),
        ('BULK_UPLOAD_FAILED', 'Bulk Upload Failed'),
        
        # NEW: Academic-related
        ('RESULTS_SUBMITTED', 'Results Submitted'),
        ('RESULTS_APPROVED', 'Results Approved'),
        ('RESULTS_REJECTED', 'Results Rejected'),
        ('RESULTS_PUBLISHED', 'Results Published'),
        ('EXAM_CREATED', 'Exam Created'),
        ('CLASS_ASSIGNED', 'Class Assigned'),
        
        # NEW: System-related
        ('SUBSCRIPTION_EXPIRING', 'Subscription Expiring'),
        ('SUBSCRIPTION_ACTIVATED', 'Subscription Activated'),
        ('SUBSCRIPTION_EXPIRED', 'Subscription Expired'),
        ('SYSTEM_UPDATE', 'System Update'),
        ('MAINTENANCE', 'Maintenance'),
        ('GENERAL', 'General'),
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
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES, default='ALL')
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Link to related object
    object_id = models.CharField(max_length=50, null=True, blank=True)
    content_type = models.CharField(max_length=50, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['recipient', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.created_at.strftime('%Y-%m-%d')}"
    
    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()


# ============================================================
# NEW: SCHOOL CALENDAR / PLANNING MODELS
# ============================================================

class SchoolEvent(models.Model):
    """
    School calendar events - exams, holidays, meetings, activities
    """
    EVENT_TYPES = (
        ('EXAM', 'Examination'),
        ('HOLIDAY', 'Holiday'),
        ('HALF_TERM', 'Half Term Break'),
        ('MEETING', 'Staff Meeting'),
        ('PARENT_MEETING', 'Parent Meeting'),
        ('SPORTS', 'Sports Event'),
        ('GRADUATION', 'Graduation'),
        ('OPEN_DAY', 'Open Day'),
        ('CLOSING', 'School Closing'),
        ('OPENING', 'School Opening'),
        ('WORKSHOP', 'Workshop/Training'),
        ('FIELD_TRIP', 'Field Trip'),
        ('OTHER', 'Other'),
    )
    
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='events')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_events')
    
    # Event details
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, default='OTHER')
    
    # Date and time
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    
    # All day event
    is_all_day = models.BooleanField(default=False)
    
    # For exams - link to exam
    exam = models.ForeignKey('academic.Exam', on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    
    # For specific classes (optional)
    target_class = models.ForeignKey(
        'academic.Classroom',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events'
    )
    
    # Status
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('PUBLISHED', 'Published'),
        ('CANCELLED', 'Cancelled'),
        ('COMPLETED', 'Completed'),
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    # Location
    location = models.CharField(max_length=200, blank=True)
    
    # Color for calendar display
    color = models.CharField(max_length=7, default='#2563eb', help_text="Hex color code")
    
    # Notifications
    notify_before = models.IntegerField(default=1, help_text="Days before to send notification")
    notification_sent = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['start_date']
    
    def __str__(self):
        return f"{self.title} ({self.get_event_type_display()})"
    
    @property
    def date_range(self):
        """Get date range as string"""
        if self.start_date == self.end_date or not self.end_date:
            return self.start_date.strftime('%d %b %Y')
        return f"{self.start_date.strftime('%d %b %Y')} - {self.end_date.strftime('%d %b %Y')}"
    
    @property
    def time_range(self):
        """Get time range as string"""
        if self.is_all_day:
            return "All Day"
        if self.start_time and self.end_time:
            return f"{self.start_time.strftime('%I:%M %p')} - {self.end_time.strftime('%I:%M %p')}"
        if self.start_time:
            return self.start_time.strftime('%I:%M %p')
        return "No time set"
    
    def is_active(self):
        """Check if event is currently active"""
        today = timezone.now().date()
        if self.start_date <= today <= (self.end_date or self.start_date):
            return True
        return False
    
    def days_until(self):
        """Days until event starts"""
        today = timezone.now().date()
        if self.start_date > today:
            return (self.start_date - today).days
        return 0
    
    def get_color(self):
        """Get color based on event type"""
        colors = {
            'EXAM': '#ef4444',
            'HOLIDAY': '#10b981',
            'HALF_TERM': '#10b981',
            'MEETING': '#3b82f6',
            'PARENT_MEETING': '#8b5cf6',
            'SPORTS': '#f59e0b',
            'GRADUATION': '#ec4899',
            'OPEN_DAY': '#14b8a6',
            'CLOSING': '#ef4444',
            'OPENING': '#22c55e',
            'WORKSHOP': '#6366f1',
            'FIELD_TRIP': '#f97316',
            'OTHER': '#64748b',
        }
        return colors.get(self.event_type, '#2563eb')


class Reminder(models.Model):
    """
    Reminders for events - sent to users
    """
    event = models.ForeignKey(SchoolEvent, on_delete=models.CASCADE, related_name='reminders')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reminders')
    sent_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='sent_reminders')
    
    class Meta:
        unique_together = ['event', 'recipient']
    
    def __str__(self):
        return f"Reminder for {self.event.title} → {self.recipient.username}"


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def create_event_notification(event, recipients):
    """
    Send notifications for a school event
    """
    notification_type = 'GENERAL'
    
    if event.event_type == 'EXAM':
        notification_type = 'EXAM_CREATED'
        title = f"📝 Exam: {event.title}"
    elif event.event_type in ['HOLIDAY', 'HALF_TERM', 'CLOSING', 'OPENING']:
        notification_type = 'SYSTEM_UPDATE'
        title = f"📅 Holiday: {event.title}"
    else:
        title = f"📅 Event: {event.title}"
    
    message = f"{event.title}\n\nDate: {event.date_range}\nTime: {event.time_range}\nLocation: {event.location}\n\n{event.description}"
    
    for recipient in recipients:
        Notification.objects.create(
            recipient=recipient,
            title=title,
            message=message,
            notification_type=notification_type,
            object_id=event.id,
            content_type='event'
        )
    
    # Mark notification as sent
    event.notification_sent = True
    event.save()