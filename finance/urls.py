from django.urls import path
from . import views

urlpatterns = [
    # ===== EXISTING =====
    path('payment/', views.payement_detail, name='payement_detail'),
    path('process-payment/', views.process_payment, name='process_payment'),
    
    # ===== NEW: FEE STRUCTURE =====
    path('fee-structure/', views.manage_fee_structure, name='manage_fee_structure'),
    
    # ===== NEW: MANUAL PAYMENT =====
    path('manual-payment/record/<int:student_id>/', views.record_manual_payment, name='record_manual_payment'),
    path('manual-payment/approve/<int:payment_id>/', views.approve_manual_payment, name='approve_manual_payment'),
    path('manual-payment/pending/', views.pending_manual_payments, name='pending_manual_payments'),
    path('manual-payment/history/', views.payment_history, name='payment_history'),
    path('manual-payment/receipt/<int:payment_id>/', views.download_receipt, name='download_receipt'),
    
    # ===== NEW: FEE BALANCE =====
    path('fee-balance/<int:student_id>/', views.student_fee_balance, name='student_fee_balance'),
    path('finance-summary/', views.finance_summary, name='finance_summary'),
    
    # ===== MPESA (Subscription Only) =====
    path('mpesa/pay/', views.mpesa_payment, name='mpesa_payment'),
    path('mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),
    
    # ===== EXISTING =====
    path('receipt/<int:payment_id>/', views.download_payment_receipt, name='download_payment_receipt'),
    path('bank-payment/', views.bank_payment_instructions, name='bank_payment_instructions'),
    path('upload-proof/', views.upload_payment_proof, name='upload_payment_proof'),
    path('check-payment-status/<int:payment_id>/', views.check_payment_status, name='check_payment_status'),
    path('delete-pending-payment/<int:payment_id>/', views.delete_pending_payment, name='delete_pending_payment'),
    path('finance-dashboard/', views.finance_dashboard, name='finance_dashboard'),

    path('', views.subscription_dashboard, name='subscription_dashboard'),

    
    path('initiate/', views.initiate_subscription_payment, name='initiate_subscription_payment'),
    path('check/<int:payment_id>/', views.check_subscription_payment, name='check_subscription_payment'),
    path('callback/', views.subscription_mpesa_callback, name='subscription_mpesa_callback'),
    path('manual/', views.manual_subscription_payment, name='manual_subscription_payment'),
    path('confirm/<int:school_id>/', views.confirm_subscription_payment, name='confirm_subscription_payment'),
    path('pending/', views.super_admin_pending_payments, name='super_admin_pending_payments'),
    path('settings/', views.school_payment_settings, name='school_payment_settings'),
    path('test/', views.test_mpesa_connection, name='test_mpesa_connection'),
    path('subscription-settings/', views.subscription_settings, name='subscription_settings'),
    path('subscription-stats-api/', views.get_subscription_stats_api, name='subscription_stats_api'),
]