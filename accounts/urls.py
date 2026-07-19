from django.urls import path
from .views import (
    # ===== EXISTING VIEWS (KEPT) =====
    dashboard_view, 
    login_view, 
    logout_view,
    user_list_view, 
    admin_reset_password, 
    check_toast, 
    edit_profile, 
    offline_page, 
    register_page, 
    delete_user,
    change_password, 
    super_admin_schools_list, 
    super_admin_add_school,
    super_admin_school_detail, 
    super_admin_delete_school, 
    register_admin_view,
    profile_view, 
    check_auth, 
    landing_page, 
    register_head_teacher,
    register_admin_view,
    register_bursar,
    register_secretary,
   
    # ===== NEW VIEWS (ADDED) =====
    bulk_upload_students, 
    bulk_upload_teachers, 
    bulk_upload_status,
)

urlpatterns = [
    # ===== LANDING & AUTH =====
    path('', landing_page, name='landing'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    
    # ===== REGISTRATION (Admin Only) =====
    path('register/', register_page, name='register_page'),
    path('register-admin/', register_admin_view, name='register_admin'),
    path('register-head-teacher/', register_head_teacher, name='register_head_teacher'),
    path('register-admin/', register_admin_view, name='register_admin'),
    path('register/secretary/', register_secretary, name='register_secretary'),  # ✅ NEW
    path('register/bursar/', register_bursar, name='register_bursar'),
    # ===== NEW: BULK UPLOAD =====
    path('bulk-upload/students/', bulk_upload_students, name='bulk_upload_students'),
    path('bulk-upload/teachers/', bulk_upload_teachers, name='bulk_upload_teachers'),
    path('bulk-upload/status/<int:upload_id>/', bulk_upload_status, name='bulk_upload_status'),
    
    
    # ===== USER MANAGEMENT =====
    path('user-list/', user_list_view, name='user_list'),
    path('reset-password/<int:user_id>/', admin_reset_password, name='admin_reset_password'),
    path('delete-user/<int:user_id>/', delete_user, name='delete_user'),
    path('change-password/', change_password, name='change_password'),
    
    # ===== SCHOOL MANAGEMENT =====
    path('schools/', super_admin_schools_list, name='super_admin_schools'),
    path('schools/add/', super_admin_add_school, name='super_admin_add_school'),
    path('schools/<int:school_id>/', super_admin_school_detail, name='super_admin_school_detail'),
    path('schools/delete/<int:school_id>/', super_admin_delete_school, name='super_admin_delete_school'),
    
    # ===== PROFILE =====
    path('edit-profile/', edit_profile, name='edit_profile'),
    path('profile/', profile_view, name='profile'),
    
    # ===== API =====
    path('api/check-auth/', check_auth, name='check_auth'),
    path('check-toast/', check_toast, name='check_toast'),
    
    # ===== OFFLINE =====
    path('offline/', offline_page, name='offline_page'),
]