
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from decimal import Decimal
import math
from django.utils import timezone
from datetime import timedelta
from django.conf import settings


# ========== SCHOOL MODEL ==========
class School(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    address = models.TextField(blank=True, null=True)
    logo = models.ImageField(upload_to='school_logos/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_schools')
    
    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['name']


# ========== USER MODEL ==========
class UserManager(BaseUserManager):
    def create_user(self, email, username, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set!")
        email = self.normalize_email(email)
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'SUPER_ADMIN')
        extra_fields.setdefault('is_approved', True)
        return self.create_user(email, username, password, **extra_fields)


class User(AbstractUser):
    ROLE_CHOICES = (
        ('SUPER_ADMIN', 'super_Admin'),
        ('ADMIN', 'admin'),
        ('HEAD_TEACHER', 'Head Teacher'), 
        ('BURSAR','Bursar'),
        ('SECRETARY', 'Secretary'),   
        ('TEACHER', 'teacher'),
        ('STUDENT', 'student'),
        ('PARENT', 'parent')
    )
    objects = UserManager()
    
    login_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    admin_id = models.CharField(max_length=20, blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='STUDENT')
    is_approved = models.BooleanField(default=False)
    school = models.ForeignKey('School', on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)
    
    # NEW FIELDS for self-registration
    id_number = models.CharField(max_length=20, blank=True, null=True)
    admission_number = models.CharField(max_length=20, blank=True, null=True)
    tsc_number = models.CharField(max_length=20, blank=True, null=True)
    is_first_login = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
    def generate_login_id(self):
        """Generate login ID = Firstname Lastname (no numbers)"""
        return f"{self.first_name} {self.last_name}".strip()
    
    def save(self, *args, **kwargs):
        # Auto-generate login_id if not set
        if not self.login_id:
            self.login_id = self.generate_login_id()
        # Set username to login_id
        self.username = self.login_id
        super().save(*args, **kwargs)

# ========== BULK UPLOAD MODEL (NEW) ==========
class BulkUpload(models.Model):
    """
    Track bulk uploads for students, teachers, and parents
    """
    UPLOAD_TYPES = (
        ('STUDENTS', 'Students'),
        ('TEACHERS', 'Teachers'),
        ('PARENTS', 'Parents'),
    )
    
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('VALIDATION_ERROR', 'Validation Error'),
    )
    
    school = models.ForeignKey(
        'School', 
        on_delete=models.CASCADE, 
        related_name='bulk_uploads'
    )
    
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='uploaded_files'
    )
    
    upload_type = models.CharField(max_length=20, choices=UPLOAD_TYPES)
    file = models.FileField(upload_to='bulk_uploads/%Y/%m/%d/')
    file_name = models.CharField(max_length=255)
    file_size = models.IntegerField(help_text="File size in bytes")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    total_records = models.IntegerField(default=0)
    successful_records = models.IntegerField(default=0)
    failed_records = models.IntegerField(default=0)
    
    validation_errors = models.JSONField(default=list, blank=True)
    upload_summary = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.get_upload_type_display()} - {self.file_name} ({self.status})"
