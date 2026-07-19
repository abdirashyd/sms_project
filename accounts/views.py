from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from .models import User, School, BulkUpload
from academic.models import Classroom, Teacher, Subject
from students.models import Students, ParentStudentLink
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.db import models
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from finance.models import Payement
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import timedelta
import json
import base64
import requests
#import  pd
from io import BytesIO
from .models import User, School, BulkUpload



# ============================================================
# KEPT: EXISTING VIEWS (Unchanged)
# ============================================================

@login_required
def check_auth(request):
    """API endpoint to check if user is authenticated"""
    return JsonResponse({
        'is_authenticated': request.user.is_authenticated,
        'username': request.user.username if request.user.is_authenticated else None,
    })


def landing_page(request):
    """Landing page - Shows when user is not logged in"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    from django.db.models import Count
    from students.models import Students
    from academic.models import Teacher, Classroom
    from .models import School
    
    total_schools = School.objects.filter(is_active=True).count()
    total_students = Students.objects.filter(is_active=True).count()
    total_teachers = Teacher.objects.count()
    
    context = {
        'total_schools': total_schools,
        'total_students': total_students,
        'total_teachers': total_teachers,
    }
    
    return render(request, 'accounts/landing.html', context)


@login_required
def edit_profile(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'profile':
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            email = request.POST.get('email')
            phone_number = request.POST.get('phone_number')
            
            if not first_name or not last_name or not email:
                messages.error(request, "First name, last name, and email are required.")
                return redirect('edit_profile')
            
            if User.objects.exclude(id=request.user.id).filter(email=email).exists():
                messages.error(request, "Email is already in use by another account.")
                return redirect('edit_profile')
            
            request.user.first_name = first_name
            request.user.last_name = last_name
            request.user.email = email
            request.user.phone_number = phone_number
            request.user.save()
            
            messages.success(request, "Your profile has been updated successfully!")
            return redirect('edit_profile')
        
        elif action == 'password':
            old_password = request.POST.get('old_password')
            new_password = request.POST.get('new_password')
            confirm_password = request.POST.get('confirm_password')
            
            if not request.user.check_password(old_password):
                messages.error(request, "Current password is incorrect.")
            elif new_password != confirm_password:
                messages.error(request, "New passwords do not match.")
            elif len(new_password) < 6:
                messages.error(request, "Password must be at least 6 characters.")
            else:
                request.user.set_password(new_password)
                request.user.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, "Password changed successfully!")
            
            return redirect('edit_profile')
    
    return render(request, 'accounts/edit_profile.html', {'user': request.user})


def check_toast(request):
    """Return any toast message stored in session and clear it"""
    message = request.session.pop('toast_message', None)
    toast_type = request.session.pop('toast_type', 'success')
    toast_title = request.session.pop('toast_title', 'Notification')
    
    return JsonResponse({
        'message': message,
        'type': toast_type,
        'title': toast_title
    })


@login_required
def dashboard_view(request):
    from students.models import Students
    from academic.models import Classroom, Teacher, Subject, Results, Exam, SubjectAllocation
    from students.models import Attendance
    from django.db.models import Avg, Count, Q, Sum
    from django.utils import timezone
    from datetime import timedelta
    from finance.models import Payement
    from finance.models import SubscriptionPayment
    from notification.models import SchoolEvent  # ✅ ADD THIS
    
    user = request.user
    today = timezone.now().date()
    next_30_days = today + timedelta(days=30)
    
    # ============================================================
    # SUPER ADMIN DASHBOARD
    # ============================================================
    if user.role == 'SUPER_ADMIN':
        subjects = Subject.objects.all()
        improvements = []
      
        for subject in subjects:
            result = Results.objects.filter(subject=subject).aggregate(avg=Avg('marks_obtained'))
            avg_marks = result.get('avg')

            if avg_marks:
                percentage = round(avg_marks)
                improvements.append({
                    'name': subject.name,
                    'percentage': percentage,
                    'color': 'fill-blue'
                })
            else:
                improvements.append({
                    'name': subject.name,
                    'percentage': 0,
                    'color': 'fill-blue'
                })
            
            if len(improvements) >= 5:
                break
        
        student_count = Students.objects.count()
        teacher_count = Teacher.objects.count()
        class_count = Classroom.objects.count()
        recent_students = Students.objects.all().order_by('-id')[:5]
        top_subjects = Subject.objects.all()[:5]
        
        classrooms = Classroom.objects.all()
        chart_data = []
        
        for classroom in classrooms:
            boys = Students.objects.filter(current_class=classroom, gender='MALE').count()
            girls = Students.objects.filter(current_class=classroom, gender='FEMALE').count()
            chart_data.append({
                'class_name': f"{classroom.name} {classroom.stream}" if classroom.stream else classroom.name,
                'boys': boys,
                'girls': girls,
            })
        
        total_revenue = SubscriptionPayment.objects.filter(
            status='COMPLETED'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        recent_payments = SubscriptionPayment.objects.filter(
            status='COMPLETED'
        ).order_by('-created_at')[:5]

        pending_payments = SubscriptionPayment.objects.filter(
            status='PENDING'
        ).select_related('school', 'subscription').order_by('-created_at')

        schools = School.objects.all().order_by('-created_at')
        for school in schools:
            school.student_count = Students.objects.filter(school=school).count()
            school.teacher_count = Teacher.objects.filter(school=school).count()
            school.payment_total = SubscriptionPayment.objects.filter(
                school=school, 
                status='COMPLETED'
            ).aggregate(total=Sum('amount'))['total'] or 0
        
        # ✅ Calendar: Upcoming events for Super Admin
        upcoming_events = SchoolEvent.objects.filter(
            status='PUBLISHED',
            start_date__gte=today,
            start_date__lte=next_30_days
        ).order_by('start_date')[:5]
        
        context = {
            'total_schools': schools.count(),
            'total_students': student_count,
            'total_teachers': teacher_count,
            'total_revenue': total_revenue,
            'recent_students': recent_students,
            'recent_payments': recent_payments,
            'top_subjects': top_subjects,
            'chart_data': chart_data,
            'school_plan': 'Basic',
            'plan_expiry': '01/05/2024',
            'improvements': improvements,
            'schools': schools,
            'pending_payments': pending_payments,
            'upcoming_events': upcoming_events,  # ✅ ADDED
        }
        return render(request, 'dashboard.html', context)
    
    # ============================================================
    # ADMIN (SCHOOL DIRECTOR) DASHBOARD
    # ============================================================
    elif user.role == 'ADMIN':
        if not user.school:
            messages.error(request, "Your account is not associated with any school. Please contact Super Admin.")
            return render(request, 'dashboard.html', {'error': 'No school assigned'})

        school = user.school
        school_classrooms = Classroom.objects.filter(school=school)
        subjects = Subject.objects.all()
        improvements = []

        for subject in subjects:
            result = Results.objects.filter(
                subject=subject,
                school=school
            ).aggregate(avg=Avg('marks_obtained'))
            
            avg_marks = result.get('avg')

            if avg_marks:
                percentage = round(avg_marks)
                improvements.append({
                    'name': subject.name,
                    'percentage': percentage,
                    'color': 'fill-blue'
                })
            else:
                improvements.append({
                    'name': subject.name,
                    'percentage': 0,
                    'color': 'fill-blue'
                })
            
            if len(improvements) >= 5:
                break

        student_count = Students.objects.filter(school=school).count()
        teacher_count = Teacher.objects.filter(school=school).count()
        class_count = school_classrooms.count()
        recent_students = Students.objects.filter(school=school).order_by('-id')[:5]
        top_subjects = Subject.objects.all()[:5]

        chart_data = []
        for classroom in school_classrooms:
            boys = Students.objects.filter(current_class=classroom, gender='MALE', school=school).count()
            girls = Students.objects.filter(current_class=classroom, gender='FEMALE', school=school).count()
            chart_data.append({
                'class_name': f"{classroom.name} {classroom.stream}" if classroom.stream else classroom.name,
                'boys': boys,
                'girls': girls,
            })
        
        total_revenue = Payement.objects.filter(
            school=school
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        recent_payments = Payement.objects.filter(
            school=school
        ).order_by('-date_paid')[:5]
        
        upcoming_events = SchoolEvent.objects.filter(
            school=school,
            status='PUBLISHED',
            start_date__gte=today,
            start_date__lte=next_30_days
        ).order_by('start_date')[:5]

        context = {
            'total_students': student_count,
            'total_teachers': teacher_count,
            'total_classes': class_count,
            'total_revenue': total_revenue,
            'recent_students': recent_students,
            'recent_payments': recent_payments,
            'top_subjects': top_subjects,
            'chart_data': chart_data,
            'school_plan': 'Basic',
            'plan_expiry': '01/05/2024',
            'improvements': improvements,
            'upcoming_events': upcoming_events,
        }
        return render(request, 'dashboard.html', context)
    # ============================================================
    # HEAD TEACHER DASHBOARD
    # ============================================================
    elif user.role == 'HEAD_TEACHER':
        school = user.school
        
        if not school:
            messages.error(request, "Your account is not associated with any school.")
            return render(request, 'dashboard.html', {'error': 'No school assigned'})
        
        total_students = Students.objects.filter(school=school, is_active=True).count()
        total_teachers = Teacher.objects.filter(school=school).count()
        total_classes = Classroom.objects.filter(school=school).count()
        
        today = timezone.now().date()
        today_attendance = Attendance.objects.filter(
            student__school=school,
            date=today
        )
        present_today = today_attendance.filter(status='Present').count()
        absent_today = today_attendance.filter(status='Absent').count()
        attendance_percentage = round((present_today / today_attendance.count() * 100), 1) if today_attendance.count() > 0 else 0
        
        pending_results = Results.objects.filter(
            school=school,
            status='PENDING'
        ).count()
        
        week_ago = timezone.now() - timedelta(days=7)
        recent_students = Students.objects.filter(
            school=school,
            date_enrolled__gte=week_ago
        ).order_by('-date_enrolled')[:5]
        
        month_from_now = timezone.now() + timedelta(days=30)
        upcoming_exams = Exam.objects.filter(
            school=school,
            date_started__gte=timezone.now(),
            date_started__lte=month_from_now
        ).order_by('date_started')[:5]
        
        classes = Classroom.objects.filter(school=school)
        class_data = []
        for classroom in classes:
            student_count = Students.objects.filter(current_class=classroom).count()
            class_data.append({
                'name': str(classroom),
                'count': student_count
            })
        
        subjects = Subject.objects.all()
        subject_performance = []
        for subject in subjects[:5]:
            result = Results.objects.filter(
                subject=subject,
                school=school
            ).aggregate(avg=Avg('marks_obtained'))
            avg_marks = result.get('avg') or 0
            subject_performance.append({
                'name': subject.name,
                'avg': round(avg_marks, 1)
            })
        
        # ✅ Calendar: Upcoming events for Head Teacher
        upcoming_events = SchoolEvent.objects.filter(
            school=school,
            status='PUBLISHED',
            start_date__gte=today,
            start_date__lte=next_30_days
        ).order_by('start_date')[:5]
        
        context = {
            'total_students': total_students,
            'total_teachers': total_teachers,
            'total_classes': total_classes,
            'present_today': present_today,
            'absent_today': absent_today,
            'attendance_percentage': attendance_percentage,
            'pending_results': pending_results,
            'recent_students': recent_students,
            'upcoming_exams': upcoming_exams,
            'class_data': class_data,
            'subject_performance': subject_performance,
            'user_role': user.role,
            'upcoming_events': upcoming_events,  # ✅ ADDED
        }
        return render(request, 'dashboard.html', context)
    # ============================================================
    # SECRETARY DASHBOARD
    # ============================================================
    elif user.role == 'SECRETARY':
        if not user.school:
            messages.error(request, "Your account is not associated with any school.")
            return render(request, 'dashboard.html', {'error': 'No school assigned'})

        school = user.school
        school_classrooms = Classroom.objects.filter(school=school)
        
        student_count = Students.objects.filter(school=school).count()
        teacher_count = Teacher.objects.filter(school=school).count()
        class_count = school_classrooms.count()
        recent_students = Students.objects.filter(school=school).order_by('-id')[:5]
        
        # Statistics
        total_students = student_count
        total_teachers = teacher_count
        total_classes = class_count
        
        # Chart data
        chart_data = []
        for classroom in school_classrooms:
            boys = Students.objects.filter(current_class=classroom, gender='MALE', school=school).count()
            girls = Students.objects.filter(current_class=classroom, gender='FEMALE', school=school).count()
            chart_data.append({
                'class_name': f"{classroom.name} {classroom.stream}" if classroom.stream else classroom.name,
                'boys': boys,
                'girls': girls,
            })
        
        # Subject performance
        improvements = []
        subjects = Subject.objects.all()
        for subject in subjects[:5]:
            result = Results.objects.filter(
                subject=subject,
                school=school
            ).aggregate(avg=Avg('marks_obtained'))
            avg_marks = result.get('avg')
            improvements.append({
                'name': subject.name,
                'percentage': round(avg_marks) if avg_marks else 0,
                'color': 'fill-blue'
            })
        
        upcoming_events = SchoolEvent.objects.filter(
            school=school,
            status='PUBLISHED',
            start_date__gte=today,
            start_date__lte=next_30_days
        ).order_by('start_date')[:5]
        
        context = {
            'total_students': total_students,
            'total_teachers': total_teachers,
            'total_classes': total_classes,
            'chart_data': chart_data,
            'improvements': improvements,
            'recent_students': recent_students,
            'upcoming_events': upcoming_events,
            'user_role': user.role,
        }
        return render(request, 'dashboard.html', context)

    
    # ============================================================
    # TEACHER DASHBOARD
    # ============================================================
    elif user.role == 'TEACHER':
        try:
            teacher_record = Teacher.objects.get(user=user)
            school = user.school
            
            assigned_classroom_ids = SubjectAllocation.objects.filter(
                teacher=teacher_record
            ).values_list('classroom_id', flat=True).distinct()
            
            class_teacher_ids = Classroom.objects.filter(
                class_teacher=user
            ).values_list('id', flat=True)
            
            all_classroom_ids = set(assigned_classroom_ids) | set(class_teacher_ids)
            my_classes = Classroom.objects.filter(id__in=all_classroom_ids)
            
            total_students = Students.objects.filter(current_class__in=my_classes).count()
            
            my_subjects_count = SubjectAllocation.objects.filter(
                teacher=teacher_record
            ).values('subject_id').distinct().count()
            
            subject_performance = []
            subjects_taught = Subject.objects.filter(
                allocations__teacher=teacher_record
            ).distinct()
            
            for subject in subjects_taught:
                avg_data = Results.objects.filter(
                    subject=subject
                ).aggregate(Avg('marks_obtained'))
                
                avg_marks = avg_data.get('marks_obtained__avg') or 0
                subject_performance.append({
                    'name': subject.name,
                    'avg': round(avg_marks, 1)
                })
            
            recent_students = Students.objects.filter(
                current_class__in=my_classes
            ).order_by('-date_enrolled')[:5]
            
            # ✅ Calendar: Upcoming events for Teacher (only their school)
            upcoming_events = SchoolEvent.objects.filter(
                school=school,
                status='PUBLISHED',
                start_date__gte=today,
                start_date__lte=next_30_days
            ).order_by('start_date')[:5]
            
            context = {
                'my_classes': my_classes,
                'total_students': total_students,
                'my_subjects': my_subjects_count,
                'pending_results': 0,
                'subject_performance': subject_performance,
                'recent_students': recent_students,
                'upcoming_events': upcoming_events,  # ✅ ADDED
                'user_role': user.role,
            }
            return render(request, 'dashboard.html', context)
            
        except Teacher.DoesNotExist:
            context = {
                'my_classes': [],
                'total_students': 0,
                'my_subjects': 0,
                'pending_results': 0,
                'subject_performance': [],
                'recent_students': [],
                'upcoming_events': [],  # ✅ ADDED
                'user_role': user.role,
            }
            return render(request, 'dashboard.html', context)
    
    # ============================================================
    # STUDENT DASHBOARD
    # ============================================================
    elif user.role == 'STUDENT':
        try:
            student = user.student_record_records
            
            total_days = student.attendances.count()
            present_days = student.attendances.filter(status='Present').count()
            attendance_percent = round((present_days / total_days * 100) if total_days > 0 else 0)
            
            recent_results = student.results.all().select_related('subject', 'exam').order_by('-exam__date_started')[:5]
            recent_attendance = student.attendances.all().order_by('-date')[:5]
            
            subject_scores = []
            unique_subjects = student.results.values('subject__id', 'subject__name').distinct()
            for sub in unique_subjects:
                latest_result = student.results.filter(subject_id=sub['subject__id']).order_by('-exam__date_started').first()
                if latest_result:
                    subject_scores.append({
                        'name': sub['subject__name'],
                        'marks': latest_result.marks_obtained
                    })
            
            context = {
                'student': student,
                'attendance_percent': attendance_percent,
                'total_marks': student.get_total_marks(),
                'mean_score': round(student.get_mean_marks(), 1),
                'class_rank': student.get_rank(),
                'fee_balance': student.get_fee_balance(),
                'recent_results': recent_results,
                'recent_attendance': recent_attendance,
                'subject_scores': subject_scores,
            }
            return render(request, 'dashboard.html', context)
            
        except Exception as e:
            messages.error(request, f"Error loading student profile: {e}")
            return render(request, 'dashboard.html', {'error': 'Student profile not found'})
    
    # ============================================================
    # PARENT DASHBOARD
    # ============================================================
    elif user.role == 'PARENT':
        children = Students.objects.filter(parents=user).select_related('current_class')
        children_count = children.count()
        
        if children_count == 1:
            student = children.first()
            
            total_days = student.attendances.count()
            present_days = student.attendances.filter(status='Present').count()
            attendance_percent = round((present_days / total_days * 100) if total_days > 0 else 0)
            
            recent_results = student.results.all().select_related('subject', 'exam').order_by('-exam__date_started')[:5]
            
            subject_scores = []
            unique_subjects = student.results.values('subject__id', 'subject__name').distinct()
            for sub in unique_subjects:
                latest_result = student.results.filter(subject_id=sub['subject__id']).order_by('-exam__date_started').first()
                if latest_result:
                    subject_scores.append({
                        'name': sub['subject__name'],
                        'marks': latest_result.marks_obtained
                    })
            
            context = {
                'student': student,
                'children_count': children_count,
                'children': children,
                'attendance_percent': attendance_percent,
                'total_marks': student.get_total_marks(),
                'mean_score': round(student.get_mean_marks(), 1),
                'class_rank': student.get_rank(),
                'fee_balance': student.get_fee_balance(),
                'recent_results': recent_results,
                'subject_scores': subject_scores,
                'is_single_child': True,
            }
            return render(request, 'dashboard.html', context)
        
        else:
            context = {
                'children': children,
                'children_count': children_count,
                'is_multiple_children': True,
            }
            return render(request, 'dashboard.html', context)
    
    return render(request, 'dashboard.html', {'error': 'Role not recognized'})


def login_view(request):
    if request.method == 'POST':
        login_identifier = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        user = None
        
        # ✅ Try to find user by login_id (Full Name)
        try:
            user = User.objects.get(login_id=login_identifier)
        except User.DoesNotExist:
            pass
        
        # Fallback: try by username
        if not user:
            try:
                user = User.objects.get(username=login_identifier)
            except User.DoesNotExist:
                pass
        
        # Fallback: try by email
        if not user:
            try:
                user = User.objects.get(email=login_identifier)
            except User.DoesNotExist:
                pass
        
        if user:
            authenticated_user = authenticate(request, username=user.username, password=password)
            
            if authenticated_user is not None:
                if not authenticated_user.is_approved:
                    messages.error(request, "Your account is pending approval. Please contact the administrator.")
                    return render(request, 'accounts/login.html')
                
                login(request, authenticated_user)
                messages.success(request, f"Welcome back, {authenticated_user.first_name}!")
                
                # ✅ Redirect based on role
                if authenticated_user.role == 'BURSAR':
                    return redirect('finance_dashboard')
                else:
                    return redirect('dashboard')
            else:
                messages.error(request, "Invalid password. Please try again.")
        else:
            messages.error(request, "User not found. Please check your name.")
    
    return render(request, 'accounts/login.html')

@login_required
def logout_view(request):
    logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect('login')


@login_required
def profile_view(request):
    user = request.user
    context = {'user': user}
    
    if user.role == 'SUPER_ADMIN':
        from students.models import Students
        from academic.models import Teacher, Classroom
        from .models import School
        from finance.models import  SubscriptionPayment
        from django.db.models import Sum
        
        schools = School.objects.all()
        for school in schools:
            school.student_count = Students.objects.filter(school=school).count()
            school.teacher_count = Teacher.objects.filter(school=school).count()
            school.payment_total = SubscriptionPayment.objects.filter(
                school=school, status='COMPLETED'
            ).aggregate(total=Sum('amount'))['total'] or 0
        
        context.update({
            'total_schools': schools.count(),
            'total_students': Students.objects.count(),
            'total_teachers': Teacher.objects.count(),
            'total_revenue': SubscriptionPayment.objects.filter(status='COMPLETED').aggregate(total=Sum('amount'))['total'] or 0,
            'schools': schools,
        })
    
    elif user.role == 'ADMIN':
        from students.models import Students
        from academic.models import Teacher, Classroom
        from finance.models import Payement
        from django.db.models import Sum
        
        school = user.school
        context.update({
            'student_count': Students.objects.filter(school=school).count(),
            'teacher_count': Teacher.objects.filter(school=school).count(),
            'class_count': Classroom.objects.filter(school=school).count(),
            'revenue': Payement.objects.filter(school=school).aggregate(total=Sum('amount_paid'))['total'] or 0,
            'recent_students': Students.objects.filter(school=school).order_by('-id')[:5],
        })
    
    elif user.role == 'HEAD_TEACHER':
        from students.models import Students, Attendance
        from academic.models import Teacher, Classroom, Results
        from django.utils import timezone
        
        school = user.school
        today = timezone.now().date()
        today_attendance = Attendance.objects.filter(student__school=school, date=today)
        present_today = today_attendance.filter(status='Present').count()
        
        context.update({
            'student_count': Students.objects.filter(school=school, is_active=True).count(),
            'teacher_count': Teacher.objects.filter(school=school).count(),
            'class_count': Classroom.objects.filter(school=school).count(),
            'attendance_percentage': round((present_today / today_attendance.count() * 100), 1) if today_attendance.count() > 0 else 0,
            'pending_results': Results.objects.filter(school=school, status='PENDING').count(),
            'recent_students': Students.objects.filter(school=school).order_by('-id')[:5],
        })
    
    elif user.role == 'TEACHER':
        from academic.models import Teacher as TeacherModel, SubjectAllocation, Classroom, Subject, Results
        from students.models import Students
        from django.db.models import Avg
        
        try:
            teacher = TeacherModel.objects.get(user=user)
            
            assigned_classroom_ids = SubjectAllocation.objects.filter(
                teacher=teacher
            ).values_list('classroom_id', flat=True).distinct()
            class_teacher_ids = Classroom.objects.filter(class_teacher=user).values_list('id', flat=True)
            all_classroom_ids = set(assigned_classroom_ids) | set(class_teacher_ids)
            my_classes = Classroom.objects.filter(id__in=all_classroom_ids)
            
            subjects_taught = Subject.objects.filter(allocations__teacher=teacher).distinct()
            
            subject_performance = []
            for subject in subjects_taught:
                avg_data = Results.objects.filter(subject=subject).aggregate(Avg('marks_obtained'))
                subject_performance.append({
                    'name': subject.name,
                    'avg': round(avg_data.get('marks_obtained__avg') or 0, 1)
                })
            
            context.update({
                'my_classes': my_classes.count(),
                'my_students': Students.objects.filter(current_class__in=my_classes).count(),
                'my_subjects': subjects_taught.count(),
                'pending_results': 0,
                'subject_performance': subject_performance,
            })
        except TeacherModel.DoesNotExist:
            context.update({
                'my_classes': 0,
                'my_students': 0,
                'my_subjects': 0,
                'pending_results': 0,
                'subject_performance': [],
            })
    
    elif user.role == 'STUDENT':
        student = user.student_record_records if hasattr(user, 'student_record_records') else None
        if student:
            total_days = student.attendances.count()
            present_days = student.attendances.filter(status='Present').count()
            context.update({
                'student': student,
                'attendance_percent': round((present_days / total_days * 100) if total_days > 0 else 0),
                'fee_balance': student.get_fee_balance(),
            })
    
    elif user.role == 'PARENT':
        from students.models import Students
        
        children = Students.objects.filter(parents=user)
        total_balance = sum(child.get_fee_balance() for child in children)
        total_results = sum(child.results.count() for child in children)
        
        context.update({
            'children': children,
            'children_results': total_results,
            'children_attendance': 0,
            'total_fee_balance': total_balance,
        })
    
    return render(request, 'profile.html', context)


# ============================================================
# SCHOOL MANAGEMENT VIEWS (Keep)
# ============================================================

@login_required
def super_admin_schools_list(request):
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can access this page.")
        return redirect('dashboard')
    
    from django.db import models
    from students.models import Students
    from academic.models import Teacher
    from finance.models import Payement
    
    schools = School.objects.all().order_by('-created_at')
    
    for school in schools:
        school.student_count = Students.objects.filter(school=school).count()
        school.teacher_count = Teacher.objects.filter(school=school).count()
        school.payment_total = Payement.objects.filter(school=school).aggregate(total=models.Sum('amount_paid'))['total'] or 0
    
    return render(request, 'accounts/schools_list.html', {'schools': schools})


@login_required
def super_admin_add_school(request):
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can add schools.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        name = request.POST.get('name')
        code = request.POST.get('code')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        address = request.POST.get('address', '')
        
        if not all([name, code, email, phone]):
            messages.error(request, "Please fill all required fields.")
            return redirect('super_admin_add_school')
        
        if School.objects.filter(code=code).exists():
            messages.error(request, f"School code '{code}' already exists.")
            return redirect('super_admin_add_school')
        
        try:
            school = School.objects.create(
                name=name,
                code=code.lower(),
                email=email,
                phone=phone,
                address=address,
                created_by=request.user,
                is_active=True
            )
            messages.success(request, f"School '{name}' created successfully!")
            return redirect('super_admin_schools')
        except Exception as e:
            messages.error(request, f"Error: {e}")
    
    return render(request, 'accounts/add_school.html')


@login_required
def super_admin_school_detail(request, school_id):
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can access this page.")
        return redirect('dashboard')
    
    from django.db import models
    from students.models import Students
    from academic.models import Teacher, Classroom
    from finance.models import Payement
    
    school = get_object_or_404(School, id=school_id)
    
    context = {
        'school': school,
        'student_count': Students.objects.filter(school=school).count(),
        'teacher_count': Teacher.objects.filter(school=school).count(),
        'classroom_count': Classroom.objects.filter(school=school).count(),
        'payment_total': Payement.objects.filter(school=school).aggregate(total=models.Sum('amount_paid'))['total'] or 0,
        'recent_students': Students.objects.filter(school=school).order_by('-id')[:10],
    }
    return render(request, 'accounts/school_detail.html', context)


@login_required
def super_admin_delete_school(request, school_id):
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can delete schools.")
        return redirect('dashboard')
    
    from students.models import Students
    from academic.models import Teacher
    from finance.models import Payement
    from accounts.models import User
    
    school = get_object_or_404(School, id=school_id)
    
    if request.method == 'POST':
        school_name = school.name
        
        User.objects.filter(school=school).delete()
        Students.objects.filter(school=school).delete()
        Teacher.objects.filter(school=school).delete()
        Payement.objects.filter(school=school).delete()
        school.delete()
        
        messages.success(request, f"School '{school_name}' and all its users have been deleted successfully!")
        return redirect('super_admin_schools')
    
    return render(request, 'accounts/confirm_delete_school.html', {'school': school})

@login_required
def register_admin_view(request):
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can register school admins.")
        return redirect('dashboard')
    
    if request.method == "POST":
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone_number')
        school_id = request.POST.get('school_id')
        
        if not all([first_name, last_name, email, school_id]):
            messages.error(request, "Please fill all required fields.")
            return redirect('register_page')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, f"Email '{email}' already exists.")
            return redirect('register_page')
        
        try:
            school = School.objects.get(id=school_id)
            
            # ✅ Generate Admin ID
            import re
            base_code = re.sub(r'[^a-zA-Z0-9]', '', school.code).upper()[:8]
            admin_count = User.objects.filter(role='ADMIN', school=school).count() + 1
            admin_id = f"{base_code}-{admin_count:03d}"
            
            # ✅ Login = Full Name
            login_id = f"{first_name} {last_name}".strip()
            
            user = User.objects.create_user(
                email=email,
                username=login_id,
                password=admin_id,
                first_name=first_name,
                last_name=last_name,
                role='ADMIN',
                phone_number=phone,
                school=school,
                login_id=login_id,
                admin_id=admin_id,
                is_approved=True,
                is_first_login=True
            )
            messages.success(request, f" School Admin '{first_name} {last_name}' created for {school.name}!")
            messages.info(request, f"Login: {login_id} | Password: {admin_id}")
            return redirect('user_list')
        except Exception as e:
            messages.error(request, f"Error creating admin: {e}")
    
    return redirect('register_page')
# ============================================================
# REGISTER SECRETARY VIEW
# ============================================================
@login_required
def register_secretary(request):
    """Register a Secretary - School Admin or Super Admin can register"""
    if request.user.role not in ['ADMIN', 'SUPER_ADMIN']:
        messages.error(request, "You don't have permission to register secretaries.")
        return redirect('dashboard')
    
    if request.method == "POST":
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone_number')
        
        if not all([first_name, last_name, email]):
            messages.error(request, "Please fill all required fields.")
            return redirect('register_page')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, f"Email '{email}' already exists.")
            return redirect('register_page')
        
        try:
            # Get school
            if request.user.role == 'SUPER_ADMIN':
                school_id = request.POST.get('school_id')
                school = get_object_or_404(School, id=school_id)
            else:
                school = request.user.school
            
            if not school:
                messages.error(request, "No school associated with this account.")
                return redirect('register_page')
            
            # ✅ Generate Secretary ID
            import re
            base_code = re.sub(r'[^a-zA-Z0-9]', '', school.code).upper()[:8] if school else 'SCH'
            sec_count = User.objects.filter(role='SECRETARY', school=school).count() + 1
            secretary_id = f"{base_code}-SEC-{sec_count:03d}"
            
            # ✅ Login = Full Name (no numbers)
            login_id = f"{first_name} {last_name}".strip()
            
            # ✅ Create user
            user = User.objects.create_user(
                email=email,
                username=login_id,
                password=secretary_id,  # Password = Secretary ID
                first_name=first_name,
                last_name=last_name,
                role='SECRETARY',
                phone_number=phone,
                school=school,
                login_id=login_id,
                admin_id=secretary_id,  # ✅ Store Secretary ID in admin_id
                is_approved=True,
                is_first_login=True
            )
            
            messages.success(request, f" Secretary '{first_name} {last_name}' registered successfully!")
            messages.info(request, f" Login: {login_id} | Password: {secretary_id}")
            return redirect('user_list')
            
        except Exception as e:
            messages.error(request, f"Error registering secretary: {str(e)}")
            return redirect('register_page')
    
    return redirect('register_page')


# ============================================================
# REGISTER BURSAR VIEW
# ============================================================
@login_required
def register_bursar(request):
    """Register a Bursar - School Admin or Super Admin can register"""
    if request.user.role not in ['ADMIN', 'SUPER_ADMIN']:
        messages.error(request, "You don't have permission to register bursars.")
        return redirect('dashboard')
    
    if request.method == "POST":
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone_number')
        
        if not all([first_name, last_name, email]):
            messages.error(request, "Please fill all required fields.")
            return redirect('register_page')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, f"Email '{email}' already exists.")
            return redirect('register_page')
        
        try:
            # Get school
            if request.user.role == 'SUPER_ADMIN':
                school_id = request.POST.get('school_id')
                school = get_object_or_404(School, id=school_id)
            else:
                school = request.user.school
            
            if not school:
                messages.error(request, "No school associated with this account.")
                return redirect('register_page')
            
            # ✅ Generate Bursar ID
            import re
            base_code = re.sub(r'[^a-zA-Z0-9]', '', school.code).upper()[:8] if school else 'SCH'
            bursar_count = User.objects.filter(role='BURSAR', school=school).count() + 1
            bursar_id = f"{base_code}-BUR-{bursar_count:03d}"
            
            # ✅ Login = Full Name (no numbers)
            login_id = f"{first_name} {last_name}".strip()
            
            # ✅ Create user
            user = User.objects.create_user(
                email=email,
                username=login_id,
                password=bursar_id,  # Password = Bursar ID
                first_name=first_name,
                last_name=last_name,
                role='BURSAR',
                phone_number=phone,
                school=school,
                login_id=login_id,
                admin_id=bursar_id,  # ✅ Store Bursar ID in admin_id
                is_approved=True,
                is_first_login=True
            )
            
            messages.success(request, f"Bursar '{first_name} {last_name}' registered successfully!")
            messages.info(request, f"Login: {login_id} | Password: {bursar_id}")
            return redirect('user_list')
            
        except Exception as e:
            messages.error(request, f"Error registering bursar: {str(e)}")
            return redirect('register_page')
    
    return redirect('register_page')

@user_passes_test(lambda u: u.is_staff or u.role in ['ADMIN', 'SUPER_ADMIN', 'HEAD_TEACHER'])
def admin_reset_password(request, user_id):
    if request.user.role == 'SUPER_ADMIN':
        pass
    elif request.user.role in ['ADMIN', 'HEAD_TEACHER']:
        user_to_reset = get_object_or_404(User, id=user_id)
        if user_to_reset.school != request.user.school:
            messages.error(request, "You can only reset passwords for users in your school.")
            return redirect('user_list')
        if request.user.role == 'HEAD_TEACHER' and user_to_reset.role == 'ADMIN':
            messages.error(request, "Head Teacher cannot reset Admin passwords.")
            return redirect('user_list')
    else:
        messages.error(request, "You don't have permission to reset passwords.")
        return redirect('dashboard')
    
    user_to_reset = get_object_or_404(User, id=user_id)
    default_pass = settings.DEFAULT_PASSWORD
    user_to_reset.set_password(default_pass)
    user_to_reset.save()
    
    messages.success(request, f"Password for {user_to_reset.username} reset to: {default_pass}")
    return redirect('user_list')


@login_required
def register_head_teacher(request):
    if request.user.role != 'ADMIN':
        messages.error(request, "Only School Admin can register head teachers.")
        return redirect('dashboard')
    
    if request.method == "POST":
        email = request.POST.get('email')
        tsc_number = request.POST.get('tsc_number')
        f_name = request.POST.get('first_name')
        l_name = request.POST.get('last_name')
        phone = request.POST.get('phone')
        
        tsc_number = tsc_number.strip().upper()
        
        if User.objects.filter(email=email).exists():
            messages.error(request, f"Email {email} is already registered!")
            return redirect('register_page')
        
        try:
            with transaction.atomic():
                school = request.user.school
                
                if not school:
                    messages.error(request, "No school associated with your account.")
                    return redirect('register_page')
                
                # ✅ Login = Full Name
                login_id = f"{f_name} {l_name}".strip()
                
                user = User.objects.create_user(
                    email=email,
                    username=login_id,
                    password=tsc_number,
                    first_name=f_name,
                    last_name=l_name,
                    role='HEAD_TEACHER',
                    is_approved=True,
                    phone_number=phone,
                    school=school,
                    tsc_number=tsc_number,
                    login_id=login_id,
                    is_first_login=True
                )
                
                from academic.models import Teacher
                teacher = Teacher.objects.create(
                    user=user,
                    name=f"{f_name} {l_name}",
                    tsc_number=tsc_number,
                    phone=phone,
                    school=school,
                )
                
                messages.success(request, f" Head Teacher {f_name} {l_name} registered!")
                messages.info(request, f"Login: {login_id} | Password: {tsc_number}")
                return redirect('user_list')
                
        except Exception as e:
            messages.error(request, f"Error: {e}")
    
    return redirect('register_page')

@login_required
def user_list_view(request):
    if request.user.role not in ['ADMIN', 'SUPER_ADMIN', 'HEAD_TEACHER']:
        messages.error(request, "You don't have permission to view user list.")
        return redirect('dashboard')
    
    role_filter = request.GET.get('role')
    search_query = request.GET.get('search', '')
    
    if request.user.role == 'SUPER_ADMIN':
        if role_filter:
            all_users = User.objects.filter(role=role_filter).order_by('-date_joined')
        else:
            all_users = User.objects.all().order_by('-date_joined')
    elif request.user.role == 'HEAD_TEACHER':
        if role_filter:
            all_users = User.objects.filter(role=role_filter, school=request.user.school).order_by('-date_joined')
        else:
            all_users = User.objects.filter(school=request.user.school).order_by('-date_joined')
    else:
        if role_filter:
            all_users = User.objects.filter(role=role_filter, school=request.user.school).order_by('-date_joined')
        else:
            all_users = User.objects.filter(school=request.user.school).order_by('-date_joined')
    
    if search_query:
        all_users = all_users.filter(
            models.Q(username__icontains=search_query) |
            models.Q(first_name__icontains=search_query) |
            models.Q(last_name__icontains=search_query) |
            models.Q(email__icontains=search_query)
        )
    
    return render(request, 'accounts/user_list.html', {
        'users': all_users,
        'search_query': search_query,
        'role_filter': role_filter,
    })


@login_required
def change_password(request):
    if request.method == 'POST':
        old_password = request.POST.get('old_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if not request.user.check_password(old_password):
            messages.error(request, "Current password is incorrect.")
        elif new_password != confirm_password:
            messages.error(request, "New passwords do not match.")
        elif len(new_password) < 6:
            messages.error(request, "Password must be at least 6 characters.")
        else:
            request.user.set_password(new_password)
            request.user.save()
            messages.success(request, "Password changed successfully! Please login again.")
            return redirect('login')
    
    return render(request, 'accounts/change_password.html')


@login_required
def delete_user(request, user_id):
    if request.user.role not in ['SUPER_ADMIN', 'ADMIN']:
        messages.error(request, "You don't have permission to delete users.")
        return redirect('user_list')
    
    user_to_delete = get_object_or_404(User, id=user_id)
    
    if request.user.role == 'ADMIN' and request.user.school:
        if user_to_delete.school != request.user.school:
            messages.error(request, "You can only delete users in your school.")
            return redirect('user_list')
        if user_to_delete.role == 'ADMIN':
            messages.error(request, "School Admin cannot delete another Admin.")
            return redirect('user_list')
    
    username = user_to_delete.username
    
    if user_to_delete.role == 'STUDENT':
        Students.objects.filter(user=user_to_delete).delete()
    elif user_to_delete.role == 'TEACHER':
        Teacher.objects.filter(user=user_to_delete).delete()
    
    user_to_delete.delete()
    
    messages.success(request, f"User '{username}' has been deleted successfully!")
    return redirect('user_list')


def register_page(request):
    from academic.models import Classroom, Subject
    from accounts.models import User, School
    
    if request.user.is_authenticated and request.user.role not in ['SUPER_ADMIN', 'ADMIN', 'HEAD_TEACHER', 'TEACHER']:
        messages.error(request, "You don't have permission to register users.")
        return redirect('dashboard')
    
    my_classes = []
    if request.user.role == 'TEACHER':
        my_classes = Classroom.objects.filter(class_teacher=request.user)
    
    if request.user.role == 'SUPER_ADMIN':
        classrooms = Classroom.objects.all()
        parents = User.objects.filter(role='PARENT')
        subjects = Subject.objects.all()
        schools = School.objects.filter(is_active=True)
        
    elif request.user.role == 'ADMIN':
        school = request.user.school
        classrooms = Classroom.objects.filter(school=school)
        parents = User.objects.filter(role='PARENT', school=school)
        subjects = Subject.objects.all()
        schools = None
        
    elif request.user.role == 'HEAD_TEACHER':
        school = request.user.school
        classrooms = Classroom.objects.filter(school=school)
        parents = User.objects.filter(role='PARENT', school=school)
        subjects = Subject.objects.all()
        schools = None
        
    else:
        school = request.user.school
        classrooms = my_classes
        parents = User.objects.filter(role='PARENT', school=school)
        subjects = Subject.objects.all()
        schools = None
    
    context = {
        'classrooms': classrooms,
        'subjects': subjects,
        'parents': parents,
        'schools': schools,
        'user_role': request.user.role,
        'my_classes': my_classes,
    }
    return render(request, 'accounts/register_form.html', context)


def offline_page(request):
    return render(request, 'accounts/offline_page.html')

# ===========================================================
# NEW: BULK UPLOAD VIEWS
# ============================================================

@login_required
def bulk_upload_students(request):
    if request.user.role not in ['HEAD_TEACHER', 'ADMIN', 'SUPER_ADMIN']:
        messages.error(request, "You don't have permission to bulk upload students.")
        return redirect('dashboard')
    
    if request.user.role == 'SUPER_ADMIN':
        school_id = request.GET.get('school_id') or request.POST.get('school_id')
        if school_id:
            school = get_object_or_404(School, id=school_id)
        else:
            school = None
    else:
        school = request.user.school
    
    if request.method == 'POST':
        uploaded_file = request.FILES.get('file')
        
        if not uploaded_file:
            messages.error(request, "Please select a file to upload.")
            return redirect('bulk_upload_students')
        
        if not uploaded_file.name.endswith(('.xlsx', '.xls')):
            messages.error(request, "Invalid file format. Please upload an Excel file.")
            return redirect('bulk_upload_students')
        
        if not school and request.user.role == 'SUPER_ADMIN':
            school_id = request.POST.get('school_id')
            if not school_id:
                messages.error(request, "Please select a school.")
                return redirect('bulk_upload_students')
            school = get_object_or_404(School, id=school_id)
        
        if not school:
            messages.error(request, "No school associated with your account.")
            return redirect('bulk_upload_students')
        
        try:
            bulk_upload = BulkUpload.objects.create(
                school=school,
                uploaded_by=request.user,
                upload_type='STUDENTS',
                file=uploaded_file,
                file_name=uploaded_file.name,
                file_size=uploaded_file.size,
                status='PROCESSING'
            )
            
            result = process_student_bulk_upload(bulk_upload.id)
            
            if result['success']:
                messages.success(
                    request, 
                    f"✅ Upload complete! {result['successful']} students added successfully. "
                    f"{result['failed']} records had errors."
                )
                
                # Show login info
                messages.info(
                    request,
                    f"🔑 Students login with their Full Name and password = Admission Number. "
                    f"Parents login with Parent Name and password = Parent ID Number."
                )
                
                if result.get('errors'):
                    messages.warning(request, f"Errors: {', '.join(result['errors'][:5])}")
            else:
                messages.error(request, f"Upload failed: {result['error']}")
            
            return redirect('bulk_upload_students')
            
        except Exception as e:
            messages.error(request, f"Error processing upload: {e}")
            return redirect('bulk_upload_students')
    
    context = {
        'school': school,
        'schools': School.objects.filter(is_active=True) if request.user.role == 'SUPER_ADMIN' else None,
        'upload_type': 'STUDENTS',
    }
    return render(request, 'accounts/bulk_upload.html', context)

def bulk_upload_teachers(upload_id):
    upload = get_object_or_404(BulkUpload, id=upload_id)
    
    try:
        import pandas as pd
        df = pd.read_excel(upload.file.path)
        
        required_columns = ['tsc_number', 'first_name', 'last_name', 'email', 'phone', 'is_class_teacher']
        
        for col in required_columns:
            if col not in df.columns:
                upload.status = 'FAILED'
                upload.validation_errors = [f"Missing column: {col}"]
                upload.save()
                return {'success': False, 'error': f"Missing column: {col}"}
        
        successful = 0
        failed = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                tsc_number = str(row['tsc_number']).strip().upper()
                first_name = str(row['first_name']).strip()
                last_name = str(row['last_name']).strip()
                email = str(row['email']).strip()
                phone = str(row['phone']).strip()
                is_class_teacher = str(row['is_class_teacher']).strip().upper()
                
                # Check if teacher already exists
                existing_teacher = Teacher.objects.filter(tsc_number=tsc_number).first()
                if existing_teacher:
                    failed += 1
                    errors.append(f"Row {index+2}: TSC number {tsc_number} already exists")
                    continue
                
                # ✅ Create Teacher
                teacher = Teacher.objects.create(
                    school=upload.school,
                    name=f"{first_name} {last_name}",
                    tsc_number=tsc_number,
                    phone=phone,
                    email=email,
                )
                
                # ✅ Create Teacher User
                teacher_login_id = f"{first_name} {last_name}".strip()
                existing_user = User.objects.filter(login_id=teacher_login_id).first()
                if existing_user:
                    teacher_login_id = f"{first_name} {last_name} {tsc_number}".strip()
                
                user = User.objects.create_user(
                    username=teacher_login_id,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    role='TEACHER',
                    school=upload.school,
                    tsc_number=tsc_number,
                    login_id=teacher_login_id,
                    phone_number=phone,
                    is_approved=True,
                    is_first_login=True,
                    password=tsc_number
                )
                
                teacher.user = user
                teacher.save()
                
                # ✅ Check if this teacher is a Class Teacher
                if is_class_teacher == 'YES' or is_class_teacher == 'Y':
                    class_name = str(row.get('class_name', '')).strip()
                    class_stream = str(row.get('class_stream', '')).strip()
                    
                    if class_name:
                        # Create or get classroom
                        classroom, created = Classroom.objects.get_or_create(
                            school=upload.school,
                            name=class_name,
                            stream=class_stream if class_stream else None
                        )
                        
                        # Assign as class teacher
                        classroom.class_teacher = user
                        classroom.save()
                        
                        if created:
                            errors.append(f"Row {index+2}: Created new class '{class_name} {class_stream}' with class teacher {first_name} {last_name}")
                        else:
                            # Update existing class teacher
                            errors.append(f"Row {index+2}: Updated class '{class_name} {class_stream}' with class teacher {first_name} {last_name}")
                    else:
                        errors.append(f"Row {index+2}: Class teacher marked YES but no class_name provided")
                
                # ✅ Assign subjects (optional - from existing logic)
                if 'subjects' in row and row['subjects']:
                    subject_names = [s.strip() for s in str(row['subjects']).split(',')]
                    for subject_name in subject_names:
                        subject = Subject.objects.filter(name=subject_name).first()
                        if subject:
                            from academic.models import TeacherSubject
                            TeacherSubject.objects.get_or_create(
                                teacher=teacher,
                                subject=subject,
                                school=upload.school
                            )
                        else:
                            errors.append(f"Row {index+2}: Subject '{subject_name}' not found")
                
                successful += 1
                
            except Exception as e:
                failed += 1
                errors.append(f"Row {index+2}: {str(e)}")
        
        upload.total_records = len(df)
        upload.successful_records = successful
        upload.failed_records = failed
        upload.validation_errors = errors[:20]
        upload.status = 'COMPLETED'
        upload.processed_at = timezone.now()
        upload.save()
        
        return {
            'success': True,
            'successful': successful,
            'failed': failed,
            'errors': errors
        }
        
    except Exception as e:
        upload.status = 'FAILED'
        upload.validation_errors = [str(e)]
        upload.save()
        return {'success': False, 'error': str(e)}
    
@login_required
def bulk_upload_status(request, upload_id):
    upload = get_object_or_404(BulkUpload, id=upload_id)
    return JsonResponse({
        'status': upload.status,
        'total_records': upload.total_records,
        'successful_records': upload.successful_records,
        'failed_records': upload.failed_records,
        'validation_errors': upload.validation_errors[:10] if upload.validation_errors else [],
    })


# ============================================================
# BULK UPLOAD PROCESSING FUNCTIONS
# ============================================================

def process_student_bulk_upload(upload_id):
    upload = get_object_or_404(BulkUpload, id=upload_id)
    
    try:
        df = pd.read_excel(upload.file.path)
        
        required_columns = [
            'admission_number', 'first_name', 'last_name', 'class_name',
            'parent_id_number', 'parent_name', 'parent_phone', 'parent_email'
        ]
        
        for col in required_columns:
            if col not in df.columns:
                upload.status = 'FAILED'
                upload.validation_errors = [f"Missing column: {col}"]
                upload.save()
                return {'success': False, 'error': f"Missing column: {col}"}
        
        successful = 0
        failed = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                admission_number = str(row['admission_number']).strip().upper()
                
                existing_student = Students.objects.filter(
                    school=upload.school,
                    registration_number=admission_number
                ).first()
                
                if existing_student:
                    failed += 1
                    errors.append(f"Row {index+2}: Admission number {admission_number} already exists")
                    continue
                
                class_name = str(row['class_name']).strip()
                classroom = Classroom.objects.filter(
                    school=upload.school,
                    name=class_name
                ).first()
                
                if not classroom:
                    failed += 1
                    errors.append(f"Row {index+2}: Class '{class_name}' not found")
                    continue
                
                student = Students.objects.create(
                    school=upload.school,
                    registration_number=admission_number,
                    first_name=str(row['first_name']).strip(),
                    last_name=str(row['last_name']).strip(),
                    current_class=classroom,
                    parent_id_number=str(row['parent_id_number']).strip(),
                    parent_name=str(row['parent_name']).strip(),
                    parent_phone=str(row['parent_phone']).strip(),
                    parent_email=str(row['parent_email']).strip(),
                    is_active=True,
                    is_enrolled=True
                )
                
                user = User.objects.create_user(
                    username=admission_number,
                    email=student.parent_email or f"{admission_number}@school.com",
                    first_name=student.first_name,
                    last_name=student.last_name,
                    role='STUDENT',
                    school=upload.school,
                    admission_number=admission_number,
                    is_approved=True,
                    is_first_login=True
                )
                
                student.user = user
                student.save()
                
                if student.parent_id_number:
                    parent = User.objects.filter(id_number=student.parent_id_number).first()
                    if parent:
                        ParentStudentLink.objects.get_or_create(
                            parent=parent,
                            student=student,
                            school=upload.school,
                            defaults={'relationship': 'PARENT'}
                        )
                
                successful += 1
                
            except Exception as e:
                failed += 1
                errors.append(f"Row {index+2}: {str(e)}")
        
        upload.total_records = len(df)
        upload.successful_records = successful
        upload.failed_records = failed
        upload.validation_errors = errors[:20]
        upload.status = 'COMPLETED'
        upload.processed_at = timezone.now()
        upload.save()
        
        return {
            'success': True,
            'successful': successful,
            'failed': failed,
            'errors': errors
        }
        
    except Exception as e:
        upload.status = 'FAILED'
        upload.validation_errors = [str(e)]
        upload.save()
        return {'success': False, 'error': str(e)}


def process_teacher_bulk_upload(upload_id):
    upload = get_object_or_404(BulkUpload, id=upload_id)
    
    try:
        df = pd.read_excel(upload.file.path)
        
        required_columns = ['tsc_number', 'first_name', 'last_name', 'email', 'phone', 'subjects']
        
        for col in required_columns:
            if col not in df.columns:
                upload.status = 'FAILED'
                upload.validation_errors = [f"Missing column: {col}"]
                upload.save()
                return {'success': False, 'error': f"Missing column: {col}"}
        
        successful = 0
        failed = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                tsc_number = str(row['tsc_number']).strip().upper()
                
                existing_teacher = Teacher.objects.filter(tsc_number=tsc_number).first()
                if existing_teacher:
                    failed += 1
                    errors.append(f"Row {index+2}: TSC number {tsc_number} already exists")
                    continue
                
                teacher = Teacher.objects.create(
                    school=upload.school,
                    name=f"{str(row['first_name']).strip()} {str(row['last_name']).strip()}",
                    tsc_number=tsc_number,
                    phone=str(row['phone']).strip(),
                    email=str(row['email']).strip(),
                )
                
                user = User.objects.create_user(
                    username=tsc_number,
                    email=str(row['email']).strip(),
                    first_name=str(row['first_name']).strip(),
                    last_name=str(row['last_name']).strip(),
                    role='TEACHER',
                    school=upload.school,
                    tsc_number=tsc_number,
                    phone_number=str(row['phone']).strip(),
                    is_approved=True,
                    is_first_login=True
                )
                
                teacher.user = user
                teacher.save()
                
                if 'subjects' in row and row['subjects']:
                    subject_names = [s.strip() for s in str(row['subjects']).split(',')]
                    for subject_name in subject_names:
                        subject = Subject.objects.filter(name=subject_name).first()
                        if subject:
                            from academic.models import TeacherSubject
                            TeacherSubject.objects.get_or_create(
                                teacher=teacher,
                                subject=subject,
                                school=upload.school
                            )
                
                successful += 1
                
            except Exception as e:
                failed += 1
                errors.append(f"Row {index+2}: {str(e)}")
        
        upload.total_records = len(df)
        upload.successful_records = successful
        upload.failed_records = failed
        upload.validation_errors = errors[:20]
        upload.status = 'COMPLETED'
        upload.processed_at = timezone.now()
        upload.save()
        
        return {
            'success': True,
            'successful': successful,
            'failed': failed,
            'errors': errors
        }
        
    except Exception as e:
        upload.status = 'FAILED'
        upload.validation_errors = [str(e)]
        upload.save()
        return {'success': False, 'error': str(e)}
    
