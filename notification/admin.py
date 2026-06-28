from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'sender', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('title', 'message', 'sender__username')
    list_editable = ('is_read',)
    readonly_fields = ('created_at',)
    
    fieldsets = (
        ('Notification Details', {
            'fields': ('sender', 'title', 'message', 'notification_type')
        }),
        ('Target (if applicable)', {
            'fields': ('recipient', 'target_class')
        }),
        ('Status', {
            'fields': ('is_read', 'created_at')
        }),
    )