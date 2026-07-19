from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from datetime import datetime, timedelta
from .models import Notification, SchoolEvent, Reminder
from academic.models import Classroom, Teacher
from students.models import Students
from accounts.models import User
from django.core.mail import send_mail
from django.conf import settings # ← For complex queries
from accounts.models import School  # ← If you reference School

@login_required
def send_notification(request):
    user = request.user
    
    if user.role not in ['SUPER_ADMIN', 'ADMIN','HEAD_TEACHER', 'TEACHER']:
        messages.error(request, "You don't have permission to send notifications.")
        return redirect('dashboard')
    
    my_classes = []
    if user.role == 'TEACHER':
        try:
            teacher_record = Teacher.objects.get(user=user)
            my_classes = Classroom.objects.filter(class_teacher=user).distinct()
        except Teacher.DoesNotExist:
            my_classes = []
    
    if request.method == 'POST':
        title = request.POST.get('title')
        message_text = request.POST.get('message')
        notification_type = request.POST.get('notification_type')
        target_class_id = request.POST.get('target_class')
        
        if not title or not message_text:
            messages.error(request, "Please fill in both title and message.")
            return redirect('send_notification')
        
        try:
            with transaction.atomic():
                recipients_list = []
                
                if user.role == 'SUPER_ADMIN':
                    if notification_type == 'CLASS' and target_class_id:
                        target_class = Classroom.objects.get(id=target_class_id)
                        students = Students.objects.filter(current_class=target_class)
                        recipients_list = [student.user for student in students]
                    elif notification_type == 'ALL':
                        recipients_list = User.objects.filter(is_active=True)
                    elif notification_type == 'TEACHER':
                        recipients_list = User.objects.filter(role='TEACHER')
                    elif notification_type == 'PARENT':
                        recipients_list = User.objects.filter(role='PARENT')
                
                elif user.role == 'ADMIN':
                    school = user.school
                    if notification_type == 'CLASS' and target_class_id:
                        target_class = Classroom.objects.get(id=target_class_id, school=school)
                        students = Students.objects.filter(current_class=target_class, school=school)
                        recipients_list = [student.user for student in students]
                    elif notification_type == 'ALL':
                        recipients_list = User.objects.filter(is_active=True, school=school)
                    elif notification_type == 'TEACHER':
                        recipients_list = User.objects.filter(role='TEACHER', school=school)
                    elif notification_type == 'PARENT':
                        recipients_list = User.objects.filter(role='PARENT', school=school)
                    elif notification_type == 'STUDENT':
                        recipients_list = User.objects.filter(role='STUDENT', school=school)
                
                elif user.role == 'HEAD_TEACHER':
                    school = user.school
                    if notification_type == 'CLASS' and target_class_id:
                        target_class = Classroom.objects.get(id=target_class_id, school=school)
                        students = Students.objects.filter(current_class=target_class, school=school)
                        recipients_list = [student.user for student in students]
                    elif notification_type == 'TEACHER':
                        recipients_list = User.objects.filter(role='TEACHER', school=school)
                    elif notification_type == 'PARENT':
                        recipients_list = User.objects.filter(role='PARENT', school=school)
                    elif notification_type == 'STUDENT':
                        recipients_list = User.objects.filter(role='STUDENT', school=school)
                
                elif user.role == 'TEACHER':
                    if notification_type == 'CLASS' and target_class_id:
                        teacher_record = Teacher.objects.get(user=user)
                        target_class = Classroom.objects.get(
                            id=target_class_id,
                            class_teacher=user
                        )
                        students = Students.objects.filter(current_class=target_class)
                        recipients_list = [student.user for student in students]
                    else:
                        messages.error(request, "Teachers can only send notifications to their own classes.")
                        return redirect('send_notification')
                
                for recipient in recipients_list:
                    Notification.objects.create(
                        sender=user,
                        recipient=recipient,
                        title=title,
                        message=message_text,
                        notification_type=notification_type
                    )
                    
                    if recipient.email:
                        try:
                            send_mail(
                                subject=f"📢 EduNexus: {title}",
                                message=f"Dear {recipient.get_full_name() or recipient.username},\n\n{message_text}\n\n---\nLogin to view: {request.build_absolute_uri('/notifications/')}",
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                recipient_list=[recipient.email],
                                fail_silently=True,
                            )
                        except Exception as e:
                            print(f"Email failed for {recipient.email}: {e}")
                
                messages.success(request, f"✅ Notification sent to {len(recipients_list)} recipient(s)!")
                return redirect('send_notification')
                
        except Exception as e:
            messages.error(request, f"❌ Error sending notification: {e}")
    
    context = {
        'my_classes': my_classes,
        'user_role': user.role,
    }
    return render(request, 'notification/send.html', context)


@login_required
def user_notifications(request):
    notifications = Notification.objects.filter(recipient=request.user).select_related('sender')
    
    if request.GET.get('mark_all_read'):
        notifications.filter(is_read=False).update(is_read=True)
        messages.success(request, "✅ All notifications marked as read.")
        return redirect('user_notifications')
    
    notifications.filter(is_read=False).update(is_read=True)
    
    context = {
        'notifications': notifications,
        'unread_count': 0,
    }
    return render(request, 'notification/notification_list.html', context)


@login_required
def mark_as_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save()
    messages.success(request, "✅ Notification marked as read.")
    return redirect('user_notifications')


@login_required
def mark_all_as_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    messages.success(request, "✅ All notifications marked as read.")
    return redirect('user_notifications')


@login_required
def delete_notification(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.delete()
    messages.success(request, "🗑️ Notification deleted.")
    return redirect('user_notifications')


@login_required
def unread_count_api(request):
    count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({'unread_count': count})


@login_required
def latest_notifications_api(request):
    notifications = Notification.objects.filter(
        recipient=request.user, 
        is_read=False
    ).order_by('-created_at')[:5]
    
    data = []
    for notif in notifications:
        data.append({
            'id': notif.id,
            'title': notif.title,
            'message': notif.message,
            'created_at': notif.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    return JsonResponse(data, safe=False)


# ============================================================
# NEW: SCHOOL CALENDAR VIEWS
# ============================================================

@login_required
def school_calendar(request):
    from django.db import models  
    """View school calendar with events"""
    user = request.user
    
    # Get current month/year
    month = int(request.GET.get('month', timezone.now().month))
    year = int(request.GET.get('year', timezone.now().year))
    
    # Filter events by school
    if user.role == 'SUPER_ADMIN':
        events = SchoolEvent.objects.filter(status__in=['PUBLISHED', 'DRAFT'])
    elif user.role == 'ADMIN':
        events = SchoolEvent.objects.filter(school=user.school, status__in=['PUBLISHED', 'DRAFT'])
    elif user.role == 'HEAD_TEACHER':
        events = SchoolEvent.objects.filter(school=user.school, status__in=['PUBLISHED', 'DRAFT'])
    elif user.role == 'TEACHER':
        try:
            teacher = Teacher.objects.get(user=user)
            events = SchoolEvent.objects.filter(
                school=user.school,
                status__in=['PUBLISHED', 'DRAFT']
            ).filter(
                models.Q(target_class__isnull=True) |
                models.Q(target_class__class_teacher=user) |
                models.Q(target_class__subject_allocations__teacher=teacher)
            ).distinct()
        except Teacher.DoesNotExist:
            events = SchoolEvent.objects.filter(school=user.school, status='PUBLISHED')
    else:
        events = SchoolEvent.objects.filter(school=user.school, status='PUBLISHED')
    
    # Filter by month/year
    events = events.filter(
        start_date__year=year,
        start_date__month=month
    )
    
    # Group events by date
    events_by_date = {}
    for event in events:
        date_key = event.start_date.strftime('%Y-%m-%d')
        if date_key not in events_by_date:
            events_by_date[date_key] = []
        events_by_date[date_key].append(event)
    
    # Upcoming events (next 30 days)
    today = timezone.now().date()
    upcoming_events = SchoolEvent.objects.filter(
        school=user.school if user.role != 'SUPER_ADMIN' else models.Q(),
        status='PUBLISHED',
        start_date__gte=today,
        start_date__lte=today + timedelta(days=30)
    ).order_by('start_date')[:10]
    
    context = {
        'events_by_date': events_by_date,
        'upcoming_events': upcoming_events,
        'month': month,
        'year': year,
        'prev_month': month - 1 if month > 1 else 12,
        'prev_year': year - 1 if month == 1 else year,
        'next_month': month + 1 if month < 12 else 1,
        'next_year': year + 1 if month == 12 else year,
        'user_role': user.role,
    }
    return render(request, 'notification/school_calendar.html', context)


@login_required
def add_event(request):
    """Add a new school event"""
    user = request.user
    
    # Only Super Admin, Admin, and Head Teacher can add events
    if user.role not in ['SUPER_ADMIN', 'ADMIN', 'HEAD_TEACHER']:
        messages.error(request, "You don't have permission to add events.")
        return redirect('school_calendar')
    
    # Get classes for this school
    if user.role == 'SUPER_ADMIN':
        classes = Classroom.objects.all()
        schools = School.objects.filter(is_active=True)
    else:
        classes = Classroom.objects.filter(school=user.school)
        schools = None
    
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        event_type = request.POST.get('event_type')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')
        is_all_day = request.POST.get('is_all_day') == 'on'
        location = request.POST.get('location')
        target_class_id = request.POST.get('target_class')
        color = request.POST.get('color', '#2563eb')
        notify_before = request.POST.get('notify_before', 1)
        
        if not title or not start_date:
            messages.error(request, "Please fill in all required fields.")
            return redirect('add_event')
        
        try:
            # Determine school
            if user.role == 'SUPER_ADMIN':
                school_id = request.POST.get('school_id')
                if not school_id:
                    messages.error(request, "Please select a school.")
                    return redirect('add_event')
                school = get_object_or_404(School, id=school_id)
            else:
                school = user.school
            
            event = SchoolEvent.objects.create(
                school=school,
                created_by=user,
                title=title,
                description=description,
                event_type=event_type,
                start_date=start_date,
                end_date=end_date or start_date,
                start_time=start_time,
                end_time=end_time,
                is_all_day=is_all_day,
                location=location,
                target_class_id=target_class_id or None,
                color=color,
                notify_before=notify_before,
                status='PUBLISHED'
            )
            
            # Send notifications to parents/students
            if target_class_id:
                recipients = User.objects.filter(
                    role__in=['STUDENT', 'PARENT'],
                    school=school
                )
                # Filter to only those in the target class
                # (can be optimized based on your Student model)
                
                for recipient in recipients:
                    Notification.objects.create(
                        recipient=recipient,
                        sender=user,
                        title=f"📅 {event.title}",
                        message=f"Event: {event.title}\nDate: {event.date_range}\nLocation: {event.location}\n\n{event.description}",
                        notification_type='GENERAL',
                        object_id=event.id,
                        content_type='event'
                    )
            
            messages.success(request, f"✅ Event '{title}' created successfully!")
            return redirect('school_calendar')
            
        except Exception as e:
            messages.error(request, f"❌ Error creating event: {e}")
    
    context = {
        'classes': classes,
        'schools': schools,
        'event_types': SchoolEvent.EVENT_TYPES,
        'colors': [
            '#2563eb', '#10b981', '#ef4444', '#f59e0b', '#8b5cf6',
            '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#22c55e'
        ],
    }
    return render(request, 'notification/add_event.html', context)


@login_required
def event_detail(request, event_id):
    """View event details"""
    event = get_object_or_404(SchoolEvent, id=event_id)
    
    # Permission check
    user = request.user
    if user.role not in ['SUPER_ADMIN', 'ADMIN'] and event.school != user.school:
        if user.role == 'TEACHER':
            try:
                teacher = Teacher.objects.get(user=user)
                if not (event.target_class and event.target_class.class_teacher == user):
                    messages.error(request, "You don't have permission to view this event.")
                    return redirect('school_calendar')
            except Teacher.DoesNotExist:
                messages.error(request, "You don't have permission to view this event.")
                return redirect('school_calendar')
        else:
            messages.error(request, "You don't have permission to view this event.")
            return redirect('school_calendar')
    
    context = {'event': event}
    return render(request, 'notification/event_detail.html', context)


@login_required
def edit_event(request, event_id):
    """Edit an existing event"""
    event = get_object_or_404(SchoolEvent, id=event_id)
    user = request.user
    
    # Permission check
    if user.role == 'SUPER_ADMIN':
        pass
    elif user.role in ['ADMIN', 'HEAD_TEACHER'] and event.school == user.school:
        pass
    else:
        messages.error(request, "You don't have permission to edit this event.")
        return redirect('school_calendar')
    
    classes = Classroom.objects.filter(school=event.school)
    
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        event_type = request.POST.get('event_type')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')
        is_all_day = request.POST.get('is_all_day') == 'on'
        location = request.POST.get('location')
        target_class_id = request.POST.get('target_class')
        color = request.POST.get('color', '#2563eb')
        status = request.POST.get('status', 'PUBLISHED')
        
        if not title or not start_date:
            messages.error(request, "Please fill in all required fields.")
            return redirect('edit_event', event_id=event_id)
        
        try:
            event.title = title
            event.description = description
            event.event_type = event_type
            event.start_date = start_date
            event.end_date = end_date or start_date
            event.start_time = start_time
            event.end_time = end_time
            event.is_all_day = is_all_day
            event.location = location
            event.target_class_id = target_class_id or None
            event.color = color
            event.status = status
            event.save()
            
            messages.success(request, f"✅ Event '{title}' updated successfully!")
            return redirect('school_calendar')
            
        except Exception as e:
            messages.error(request, f"❌ Error updating event: {e}")
    
    context = {
        'event': event,
        'classes': classes,
        'event_types': SchoolEvent.EVENT_TYPES,
        'colors': [
            '#2563eb', '#10b981', '#ef4444', '#f59e0b', '#8b5cf6',
            '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#22c55e'
        ],
        'status_choices': SchoolEvent.STATUS_CHOICES,
    }
    return render(request, 'notification/edit_event.html', context)


@login_required
def delete_event(request, event_id):
    """Delete an event"""
    event = get_object_or_404(SchoolEvent, id=event_id)
    user = request.user
    
    if user.role == 'SUPER_ADMIN':
        pass
    elif user.role in ['ADMIN', 'HEAD_TEACHER'] and event.school == user.school:
        pass
    else:
        messages.error(request, "You don't have permission to delete this event.")
        return redirect('school_calendar')
    
    if request.method == 'POST':
        title = event.title
        event.delete()
        messages.success(request, f"🗑️ Event '{title}' deleted successfully!")
        return redirect('school_calendar')
    
    context = {'event': event}
    return render(request, 'notification/confirm_delete_event.html', context)


@login_required
def get_calendar_events_api(request):
    """API endpoint for calendar events (for AJAX/FullCalendar)"""
    user = request.user
    start = request.GET.get('start')
    end = request.GET.get('end')
    
    if user.role == 'SUPER_ADMIN':
        events = SchoolEvent.objects.filter(status='PUBLISHED')
    else:
        events = SchoolEvent.objects.filter(school=user.school, status='PUBLISHED')
    
    if start and end:
        events = events.filter(
            start_date__lte=end,
            end_date__gte=start
        )
    
    data = []
    for event in events:
        data.append({
            'id': event.id,
            'title': event.title,
            'start': event.start_date.isoformat(),
            'end': (event.end_date or event.start_date).isoformat(),
            'color': event.get_color(),
            'allDay': event.is_all_day,
            'url': f'/events/{event.id}/',
        })
    
    return JsonResponse(data, safe=False)


# ============================================================
# EXISTING VIEWS (Keep as is)
# ============================================================

# ... (rest of your existing views remain unchanged)