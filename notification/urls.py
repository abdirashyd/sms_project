from django.urls import path
from . import views

urlpatterns = [
    # ===== EXISTING =====
    path('', views.user_notifications, name='user_notifications'),
    path('send/', views.send_notification, name='send_notification'),
    path('mark-read/<int:pk>/', views.mark_as_read, name='mark_as_read'),
    path('mark-all-read/', views.mark_all_as_read, name='mark_all_as_read'),
    path('delete/<int:pk>/', views.delete_notification, name='delete_notification'),
    path('unread-count/', views.unread_count_api, name='unread_count_api'),
    path('latest/', views.latest_notifications_api, name='latest_notifications_api'),
    
    # ===== NEW: SCHOOL CALENDAR =====
    path('calendar/', views.school_calendar, name='school_calendar'),
    path('calendar/add/', views.add_event, name='add_event'),
    path('calendar/<int:event_id>/', views.event_detail, name='event_detail'),
    path('calendar/<int:event_id>/edit/', views.edit_event, name='edit_event'),
    path('calendar/<int:event_id>/delete/', views.delete_event, name='delete_event'),
    path('calendar/api/events/', views.get_calendar_events_api, name='calendar_api'),
]