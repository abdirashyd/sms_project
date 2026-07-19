from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import get_template
from xhtml2pdf import pisa
from decimal import Decimal
import json
import datetime
from students.models import Students
from academic.models import Classroom, Teacher
from accounts.models import User
from notification.models import Notification
from .mpesa_utility import stk_push
import requests
import base64
# finance/views.py - UPDATE IMPORTS
from accounts.models import User, School
from .models import (
    Payement, FeeStructure, ManualPayment, calculate_student_fee_balance,
    SchoolSubscription, SubscriptionPlan, SchoolSubscriptionChoice,
    SubscriptionPayment, SubscriptionInvoice, SubscriptionPauseHistory, SchoolMpesaConfig,
)

# ============================================================
# EXISTING: PAYMENT VIEWS (Keep as is)
# ============================================================

@login_required
def payement_detail(request):
    """View all payment records"""
    user = request.user
    
    if user.role == 'TEACHER':
        messages.info(request, "Finance section is not available for teachers.")
        return redirect('dashboard')
    
    if user.role == 'SUPER_ADMIN':
        payments = Payement.objects.all().select_related('student')
    elif user.role == 'ADMIN':
        payments = Payement.objects.filter(school=user.school).select_related('student')
    elif user.role == 'STUDENT':
        if hasattr(user, 'student_record_records'):
            payments = Payement.objects.filter(student=user.student_record_records).select_related('student')
        else:
            payments = Payement.objects.none()
    elif user.role == 'PARENT':
        children = Students.objects.filter(parents=user)
        payments = Payement.objects.filter(student__in=children).select_related('student')
    else:
        payments = Payement.objects.none()
    
    return render(request, 'finance/payement_detail.html', {'payments': payments})


@login_required
def process_payment(request):
    """Record a payment manually"""
    if request.user.role not in ['SUPER_ADMIN', 'ADMIN']:
        messages.error(request, "Only administrators can process payments.")
        return redirect('payement_detail')
    
    if request.method == 'POST':
        amount = request.POST.get('amount_paid')
        ref_code = request.POST.get('reference', '').upper()
        reg_number = request.POST.get('reg_number')
        month = request.POST.get('month')
        year = request.POST.get('year', 2026)
        
        if not all([amount, ref_code, reg_number, month]):
            messages.error(request, "Please fill all required fields.")
            return redirect('payement_detail')
        
        if Payement.objects.filter(reference=ref_code).exists():
            messages.error(request, f"Reference {ref_code} already exists!")
            return redirect('payement_detail')
        
        try:
            amount = float(amount)
        except ValueError:
            messages.error(request, "Invalid amount.")
            return redirect('payement_detail')
        
        student = Students.objects.filter(registration_number=reg_number).first()
        
        if not student:
            messages.error(request, f"Student '{reg_number}' not found!")
            return redirect('payement_detail')
        
        if request.user.role == 'ADMIN' and student.school != request.user.school:
            messages.error(request, "You can only record payments for students in your school.")
            return redirect('payement_detail')
        
        Payement.objects.create(
            student=student,
            amount_paid=amount,
            reference=ref_code,
            method=request.POST.get('method', 'M-Pesa'),
            month=int(month),
            year=int(year),
            recorded_by=request.user,
            school_id=student.school_id,
        )
        
        Notification.objects.create(
            sender=request.user,
            recipient=student.user,
            title="💰 Payment Received",
            message=f"KES {amount:,.2f} payment recorded. Reference: {ref_code}",
            notification_type='FEE'
        )
        
        if student.parents:
            Notification.objects.create(
                sender=request.user,
                recipient=student.parents,
                title=f"💰 Payment Received - {student.first_name}",
                message=f"KES {amount:,.2f} payment recorded. Reference: {ref_code}",
                notification_type='FEE'
            )
        
        messages.success(request, f"Payment of KES {amount:,.2f} recorded for {student.first_name} {student.last_name}!")
        return redirect('payement_detail')
    
    return redirect('payement_detail')


# ============================================================
# NEW: FEE STRUCTURE MANAGEMENT
# ============================================================

@login_required
def manage_fee_structure(request):
    """School Director manages fee structure"""
    
    # Only School Director (ADMIN) can manage fee structure
    if request.user.role != 'ADMIN':
        messages.error(request, "Only School Director can manage fee structures.")
        return redirect('dashboard')
    
    school = request.user.school
    classes = Classroom.objects.filter(school=school)
    
    # Get current fee structures
    fee_structures = FeeStructure.objects.filter(school=school).select_related('class_assigned')
    
    # Build class fee lookup
    class_fees = {}
    for classroom in classes:
        fee = FeeStructure.objects.filter(
            school=school,
            class_assigned=classroom,
            is_active=True
        ).first()
        class_fees[classroom.id] = fee
    
    if request.method == 'POST':
        class_id = request.POST.get('class_id')
        billing_cycle = request.POST.get('billing_cycle')
        amount = request.POST.get('amount')
        term = request.POST.get('term')
        year = request.POST.get('year')
        description = request.POST.get('description', '')
        
        if not all([class_id, billing_cycle, amount, term, year]):
            messages.error(request, "Please fill all required fields.")
            return redirect('manage_fee_structure')
        
        classroom = get_object_or_404(Classroom, id=class_id, school=school)
        
        try:
            amount = Decimal(amount)
        except:
            messages.error(request, "Invalid amount.")
            return redirect('manage_fee_structure')
        
        # Create or update fee structure
        fee_structure, created = FeeStructure.objects.update_or_create(
            school=school,
            class_assigned=classroom,
            billing_cycle=billing_cycle,
            term=term,
            year=int(year),
            defaults={
                'amount': amount,
                'description': description,
                'is_active': True
            }
        )
        
        # Deactivate other fee structures for this class/cycle/term/year
        FeeStructure.objects.filter(
            school=school,
            class_assigned=classroom,
            billing_cycle=billing_cycle,
            term=term,
            year=int(year)
        ).exclude(id=fee_structure.id).update(is_active=False)
        
        messages.success(request, f"Fee structure updated for {classroom.name}!")
        return redirect('manage_fee_structure')
    
    context = {
        'classes': classes,
        'class_fees': class_fees,
        'fee_structures': fee_structures,
    }
    return render(request, 'finance/manage_fee_structure.html', context)


# ============================================================
# NEW: MANUAL PAYMENT RECORDING (Head Teacher)
# ============================================================

@login_required
def record_manual_payment(request, student_id):
    """Head Teacher records payment from parent"""
    
    # Only Head Teacher, Admin, or Super Admin can record payments
    if request.user.role not in ['HEAD_TEACHER', 'ADMIN', 'SUPER_ADMIN']:
        messages.error(request, "You don't have permission to record payments.")
        return redirect('dashboard')
    
    student = get_object_or_404(Students, id=student_id)
    
    # Check permission for Head Teacher/Admin
    if request.user.role in ['HEAD_TEACHER', 'ADMIN']:
        if student.school != request.user.school:
            messages.error(request, "You can only record payments for students in your school.")
            return redirect('student_list')
    
    # Get fee balance
    balance_info = calculate_student_fee_balance(student)
    
    if request.method == 'POST':
        amount = request.POST.get('amount')
        payment_date = request.POST.get('payment_date')
        payment_method = request.POST.get('payment_method')
        reference_number = request.POST.get('reference_number', '')
        billing_cycle = request.POST.get('billing_cycle', 'MONTHLY')
        notes = request.POST.get('notes', '')
        
        if not all([amount, payment_date, payment_method]):
            messages.error(request, "Please fill all required fields.")
            return redirect('record_manual_payment', student_id=student.id)
        
        try:
            amount = Decimal(amount)
        except:
            messages.error(request, "Invalid amount.")
            return redirect('record_manual_payment', student_id=student.id)
        
        # Get fee amount from structure
        fee_amount = Decimal('0.00')
        fee_structure = FeeStructure.objects.filter(
            school=student.school,
            class_assigned=student.current_class,
            billing_cycle=billing_cycle,
            is_active=True
        ).first()
        
        if fee_structure:
            fee_amount = fee_structure.amount
        
        # Create manual payment
        payment = ManualPayment.objects.create(
            student=student,
            school=student.school,
            head_teacher=request.user,
            amount=amount,
            payment_date=payment_date,
            payment_method=payment_method,
            reference_number=reference_number,
            notes=notes,
            billing_cycle=billing_cycle,
            fee_amount=fee_amount,
            balance_before=balance_info['balance'],
            balance_after=balance_info['balance'] - amount,
            status='PENDING'
        )
        
        payment.receipt_number = payment.generate_receipt_number()
        payment.save()
        
        # Send notification to School Admin
        school_admins = User.objects.filter(role='ADMIN', school=student.school)
        for admin in school_admins:
            Notification.objects.create(
                sender=request.user,
                recipient=admin,
                title="💰 Payment Pending Approval",
                message=f"{student.first_name} {student.last_name} ({student.registration_number}) has submitted a payment of KES {amount:,.2f}. Please approve.",
                notification_type='FEE'
            )
        
        # Send notification to Parent
        if student.parents:
            Notification.objects.create(
                sender=request.user,
                recipient=student.parents,
                title="💰 Payment Submitted",
                message=f"Your payment of KES {amount:,.2f} for {student.first_name} {student.last_name} has been submitted for approval.",
                notification_type='FEE'
            )
        
        messages.success(request, f"Payment of KES {amount:,.2f} recorded! Waiting for Director approval.")
        return redirect('student_detail', pk=student.id)
    
    context = {
        'student': student,
        'balance_info': balance_info,
        'billing_cycles': FeeStructure.BILLING_CYCLE_CHOICES,
    }
    return render(request, 'finance/record_manual_payment.html', context)


# ============================================================
# NEW: APPROVE PAYMENT (School Director)
# ============================================================

@login_required
def approve_manual_payment(request, payment_id):
    """School Director approves or rejects a payment"""
    
    # Only School Director (ADMIN) can approve payments
    if request.user.role != 'ADMIN':
        messages.error(request, "Only School Director can approve payments.")
        return redirect('dashboard')
    
    payment = get_object_or_404(ManualPayment, id=payment_id, school=request.user.school)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'approve':
            payment.status = 'APPROVED'
            payment.school_admin = request.user
            payment.approved_at = timezone.now()
            payment.save()
            
            # Send notification to Parent
            if payment.student.parents:
                Notification.objects.create(
                    sender=request.user,
                    recipient=payment.student.parents,
                    title="✅ Payment Approved!",
                    message=f"Your payment of KES {payment.amount:,.2f} for {payment.student.first_name} {payment.student.last_name} has been approved.",
                    notification_type='FEE'
                )
            
            # Send notification to Head Teacher
            if payment.head_teacher:
                Notification.objects.create(
                    sender=request.user,
                    recipient=payment.head_teacher,
                    title="✅ Payment Approved",
                    message=f"Payment for {payment.student.first_name} {payment.student.last_name} has been approved.",
                    notification_type='FEE'
                )
            
            # Generate PDF receipt
            # receipt_path = generate_receipt_pdf(payment)
            # payment.receipt_pdf = receipt_path
            # payment.save()
            
            messages.success(request, f"Payment of KES {payment.amount:,.2f} approved successfully!")
            
        elif action == 'reject':
            payment.status = 'REJECTED'
            payment.school_admin = request.user
            payment.save()
            
            # Send notification to Parent
            if payment.student.parents:
                Notification.objects.create(
                    sender=request.user,
                    recipient=payment.student.parents,
                    title="❌ Payment Rejected",
                    message=f"Your payment of KES {payment.amount:,.2f} for {payment.student.first_name} {payment.student.last_name} has been rejected. Please contact the school.",
                    notification_type='FEE'
                )
            
            messages.warning(request, f"Payment of KES {payment.amount:,.2f} rejected.")
        
        return redirect('pending_manual_payments')
    
    context = {
        'payment': payment,
    }
    return render(request, 'finance/approve_manual_payment.html', context)


# ============================================================
# NEW: PENDING PAYMENTS LIST
# ============================================================

@login_required
def pending_manual_payments(request):
    """View all pending payments for School Director"""
    
    # Only School Director and Super Admin can view pending payments
    if request.user.role not in ['ADMIN', 'SUPER_ADMIN']:
        messages.error(request, "You don't have permission to view pending payments.")
        return redirect('dashboard')
    
    if request.user.role == 'SUPER_ADMIN':
        pending_payments = ManualPayment.objects.filter(status='PENDING').select_related('student', 'head_teacher')
    else:
        pending_payments = ManualPayment.objects.filter(
            status='PENDING',
            school=request.user.school
        ).select_related('student', 'head_teacher')
    
    return render(request, 'finance/pending_manual_payments.html', {
        'pending_payments': pending_payments
    })


# ============================================================
# NEW: PAYMENT HISTORY
# ============================================================

@login_required
def payment_history(request):
    """View payment history for school"""
    
    user = request.user
    
    if user.role == 'TEACHER':
        messages.info(request, "Finance section is not available for teachers.")
        return redirect('dashboard')
    
    if user.role == 'SUPER_ADMIN':
        payments = ManualPayment.objects.filter(status='APPROVED').select_related('student', 'head_teacher', 'school_admin')
    elif user.role == 'ADMIN':
        payments = ManualPayment.objects.filter(
            status='APPROVED',
            school=user.school
        ).select_related('student', 'head_teacher', 'school_admin')
    elif user.role == 'PARENT':
        children = Students.objects.filter(parents=user)
        payments = ManualPayment.objects.filter(
            student__in=children,
            status='APPROVED'
        ).select_related('student')
    elif user.role == 'STUDENT':
        if hasattr(user, 'student_record_records'):
            payments = ManualPayment.objects.filter(
                student=user.student_record_records,
                status='APPROVED'
            ).select_related('student')
        else:
            payments = ManualPayment.objects.none()
    else:
        payments = ManualPayment.objects.none()
    
    return render(request, 'finance/payment_history.html', {'payments': payments})


# ============================================================
# NEW: DOWNLOAD RECEIPT
# ============================================================

@login_required
def download_receipt(request, payment_id):
    """Download PDF receipt"""
    
    payment = get_object_or_404(ManualPayment, id=payment_id)
    user = request.user
    
    # Permission checks
    if user.role == 'ADMIN' and payment.school != user.school:
        messages.error(request, "Access denied.")
        return redirect('payment_history')
    
    if user.role == 'STUDENT' and payment.student.user != user:
        messages.error(request, "Access denied.")
        return redirect('payment_history')
    
    if user.role == 'PARENT' and payment.student.parents != user:
        messages.error(request, "Access denied.")
        return redirect('payment_history')
    
    context = {
        'payment': payment,
        'receipt_number': payment.receipt_number,
        'student': payment.student,
        'school': payment.school,
    }
    
    template = get_template('finance/pdf_receipt.html')
    html = template.render(context)
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{payment.receipt_number}.pdf"'
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    
    if pisa_status.err:
        return HttpResponse('PDF generation error', status=500)
    return response


# ============================================================
# NEW: FEE BALANCE VIEW
# ============================================================

@login_required
def student_fee_balance(request, student_id):
    """View student fee balance (for Parents and School Admin)"""
    
    student = get_object_or_404(Students, id=student_id)
    user = request.user
    
    # Permission checks
    if user.role == 'PARENT' and student.parents != user:
        messages.error(request, "You can only view your own children's fee balances.")
        return redirect('dashboard')
    
    if user.role == 'ADMIN' and student.school != user.school:
        messages.error(request, "You can only view students from your school.")
        return redirect('dashboard')
    
    if user.role == 'STUDENT' and user.student_record_records != student:
        messages.error(request, "You can only view your own fee balance.")
        return redirect('dashboard')
    
    if user.role == 'TEACHER':
        messages.error(request, "Teachers cannot view fee balances.")
        return redirect('dashboard')
    
    balance_info = calculate_student_fee_balance(student)
    
    # Get payment history
    payments = ManualPayment.objects.filter(
        student=student
    ).order_by('-submitted_at')
    
    context = {
        'student': student,
        'balance_info': balance_info,
        'payments': payments,
    }
    return render(request, 'finance/student_fee_balance.html', context)


# ============================================================
# NEW: FINANCE SUMMARY DASHBOARD (Updated)
# ============================================================

@login_required
def finance_summary(request):
    """Finance summary for School Director"""
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Only School Director can view finance summary.")
        return redirect('dashboard')
    
    school = request.user.school
    
    # Get all students
    students = Students.objects.filter(school=school, is_active=True)
    total_students = students.count()
    
    # Fee structures
    fee_structures = FeeStructure.objects.filter(school=school, is_active=True)
    
    # Fee summary
    fully_paid = 0
    partial = 0
    unpaid = 0
    
    for student in students:
        balance = calculate_student_fee_balance(student)
        if balance['status'] == 'PAID':
            fully_paid += 1
        elif balance['status'] == 'PARTIAL':
            partial += 1
        else:
            unpaid += 1
    
    # Payment statistics
    total_collected = ManualPayment.objects.filter(
        school=school,
        status='APPROVED'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    pending_approvals = ManualPayment.objects.filter(
        school=school,
        status='PENDING'
    ).count()
    
    # Revenue by class
    classrooms = Classroom.objects.filter(school=school)
    class_revenue = []
    
    for classroom in classrooms:
        class_students = Students.objects.filter(school=school, current_class=classroom)
        student_count = class_students.count()
        
        if student_count > 0:
            fee = FeeStructure.objects.filter(
                school=school,
                class_assigned=classroom,
                is_active=True
            ).first()
            
            expected = (fee.amount * student_count) if fee else 0
            collected = ManualPayment.objects.filter(
                school=school,
                student__in=class_students,
                status='APPROVED'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            
            percentage = round((collected / expected * 100), 1) if expected > 0 else 0
            
            class_revenue.append({
                'classroom': classroom,
                'student_count': student_count,
                'expected': expected,
                'collected': collected,
                'percentage': percentage,
            })
    
    # Recent transactions
    recent_payments = ManualPayment.objects.filter(
        school=school
    ).order_by('-submitted_at')[:10]
    
    context = {
        'total_students': total_students,
        'fully_paid': fully_paid,
        'partial': partial,
        'unpaid': unpaid,
        'total_collected': total_collected,
        'pending_approvals': pending_approvals,
        'class_revenue': class_revenue,
        'recent_payments': recent_payments,
        'fee_structures': fee_structures,
    }
    
    return render(request, 'finance/finance_summary.html', context)


# ============================================================
# EXISTING: MPESA PAYMENT (Keep for Subscription Only)
# ============================================================

@login_required
def mpesa_payment(request):
    """M-Pesa payment for SUBSCRIPTION ONLY"""
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        amount = request.POST.get('amount')
        reg_number = request.POST.get('reg_number')
        month = request.POST.get('month')
        
        student = Students.objects.filter(registration_number=reg_number).first()
        if not student:
            messages.error(request, "Student not found!")
            return redirect('payement_detail')
        
        pending_payment = Payement.objects.create(
            student=student,
            amount_paid=amount,
            reference=f"PENDING_{int(timezone.now().timestamp())}",
            method='M-Pesa',
            month=int(month),
            year=timezone.now().year,
            recorded_by=request.user,
            school=student.school,
        )
        
        result = stk_push(
            phone_number=phone_number,
            amount=amount,
            reg_number=reg_number,
            transaction_desc=f"Fee payment for {student.first_name}"
        )
        
        if result.get('ResponseCode') == '0':
            checkout_id = result.get('CheckoutRequestID')
            pending_payment.reference = checkout_id
            pending_payment.save()
            
            return render(request, 'finance/payment_loading.html', {
                'payment_id': pending_payment.id,
                'amount': amount,
                'phone_number': phone_number,
                'student_name': f"{student.first_name} {student.last_name}"
            })
        else:
            pending_payment.delete()
            messages.error(request, "Payment initiation failed.")
            return redirect('payement_detail')
    
    return redirect('payement_detail')


@csrf_exempt
def mpesa_callback(request):
    """M-Pesa callback for SUBSCRIPTION ONLY"""
    try:
        data = json.loads(request.body)
        stk_callback = data.get('Body', {}).get('stkCallback', {})
        result_code = stk_callback.get('ResultCode')
        checkout_request_id = stk_callback.get('CheckoutRequestID')
        
        if result_code == 0:
            items = stk_callback.get('CallbackMetadata', {}).get('Item', [])
            mpesa_receipt = None
            amount = None
            for item in items:
                if item.get('Name') == 'MpesaReceiptNumber':
                    mpesa_receipt = item.get('Value')
                elif item.get('Name') == 'Amount':
                    amount = item.get('Value')
            
            payment = Payement.objects.filter(reference=checkout_request_id).first()
            if payment:
                payment.reference = mpesa_receipt
                payment.save()
                
                if payment.student.user:
                    Notification.objects.create(
                        recipient=payment.student.user,
                        title="✅ Payment Successful",
                        message=f"KES {amount:,.2f} confirmed. Receipt: {mpesa_receipt}",
                        notification_type='FEE'
                    )
        
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Success"})
    except Exception as e:
        return JsonResponse({"ResultCode": 1, "ResultDesc": str(e)})


# ============================================================
# EXISTING: OTHER VIEWS (Keep as is)
# ============================================================

@login_required
def download_payment_receipt(request, payment_id):
    """Download PDF receipt for existing Payement"""
    payment = get_object_or_404(Payement, id=payment_id)
    user = request.user
    
    if user.role == 'ADMIN' and payment.school != user.school:
        messages.error(request, "Access denied.")
        return redirect('payement_detail')
    
    if user.role == 'STUDENT' and payment.student.user != user:
        messages.error(request, "Access denied.")
        return redirect('payement_detail')
    
    if user.role == 'PARENT' and payment.student.parents != user:
        messages.error(request, "Access denied.")
        return redirect('payement_detail')
    
    receipt_number = f"RCP-{payment.date_paid.year}-{payment.id:06d}"
    
    context = {
        'payment': payment,
        'receipt_number': receipt_number,
    }
    
    template = get_template('finance/pdf_receipt.html')
    html = template.render(context)
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{receipt_number}.pdf"'
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    
    if pisa_status.err:
        return HttpResponse('PDF generation error', status=500)
    return response


@login_required
def bank_payment_instructions(request):
    """Show bank payment instructions page"""
    user = request.user
    
    if user.role == 'PARENT':
        from students.models import Students
        children = Students.objects.filter(parents=user)
        student = children.first() if children.count() == 1 else None
    elif user.role == 'STUDENT':
        student = user.student_record_records if hasattr(user, 'student_record_records') else None
    else:
        student = None
    
    def generate_bank_reference(student):
        year = timezone.now().year
        return f"EDX{year}{student.id:06d}" if student else "EDX000000"
    
    bank_details = {
        'bank_name': 'Equity Bank Kenya',
        'account_name': 'EduNexus School Collection Account',
        'account_number': '1234567890',
        'branch': 'Moi Avenue Branch',
        'swift_code': 'EQBLKENA',
        'kra_pin': 'P051234567Z'
    }
    
    context = {
        'student': student,
        'bank_details': bank_details,
        'bank_reference': generate_bank_reference(student) if student else None,
        'minimum_payment': 5000,
    }
    
    return render(request, 'finance/bank_payment.html', context)


@login_required
def upload_payment_proof(request):
    """Handle upload of bank transfer receipt"""
    if request.method != 'POST':
        return redirect('payement_detail')
    
    student_id = request.POST.get('student_id')
    amount = request.POST.get('amount')
    reference = request.POST.get('reference')
    proof_file = request.FILES.get('proof_file')
    
    if not all([student_id, amount, reference, proof_file]):
        messages.error(request, "Please fill all fields and upload a file.")
        return redirect('payement_detail')
    
    student = get_object_or_404(Students, id=student_id)
    
    if request.user.role == 'ADMIN' and student.school != request.user.school:
        messages.error(request, "You can only upload payment proof for students in your school.")
        return redirect('payement_detail')
    
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile
    
    file_path = default_storage.save(
        f'payment_proofs/{student.registration_number}_{reference}.pdf',
        ContentFile(proof_file.read())
    )
    
    from notification.models import Notification
    from accounts.models import User
    
    admins = User.objects.filter(role='SUPER_ADMIN')
    for admin in admins:
        Notification.objects.create(
            sender=request.user,
            recipient=admin,
            title="💰 Bank Payment Proof Uploaded",
            message=f"Payment proof uploaded for {student.first_name} {student.last_name} (Ref: {reference}, Amount: KES {amount})",
            notification_type='FEE'
        )
    
    Payement.objects.create(
        student=student,
        amount_paid=amount,
        reference=reference,
        method='Bank',
        month=timezone.now().month,
        year=timezone.now().year,
        recorded_by=request.user,
        school_id=student.school_id,
    )
    
    messages.success(request, "Payment proof uploaded. School will verify within 24 hours.")
    return redirect('payement_detail')


@login_required
def check_payment_status(request, payment_id):
    """Check payment status"""
    from datetime import timedelta
    
    payment = get_object_or_404(Payement, id=payment_id)
    
    time_diff = timezone.now() - payment.date_paid
    if time_diff > timedelta(seconds=65):
        if payment.reference.startswith('PENDING_') or payment.reference.startswith('ws_'):
            payment.delete()
        return JsonResponse({'status': 'timeout'})
    
    is_completed = (
        payment.reference and 
        not payment.reference.startswith('ws_') and 
        not payment.reference.startswith('PENDING_') and
        '_' not in payment.reference and
        len(payment.reference) >= 8
    )
    
    if is_completed:
        return JsonResponse({'status': 'completed'})
    else:
        return JsonResponse({'status': 'pending'})


@csrf_exempt
@login_required
def delete_pending_payment(request, payment_id):
    """Delete pending payment record"""
    payment = get_object_or_404(Payement, id=payment_id)
    if payment.reference.startswith('PENDING_') or payment.reference.startswith('ws_'):
        payment.delete()
        return JsonResponse({'status': 'deleted'})
    return JsonResponse({'status': 'already_confirmed'})


@login_required
def finance_dashboard(request):
    """Unified finance dashboard for Super Admin, School Admin, and Bursar"""
    user = request.user
    
    # ===== SUPER ADMIN =====
    if user.role == 'SUPER_ADMIN':
        from accounts.models import School, SubscriptionPayment
        from students.models import Students
        from academic.models import Teacher
        from django.db.models import Sum
        
        schools = School.objects.all()
        school_data = []
        total_revenue = 0
        pending_payments = []
        overdue_schools = 0
        
        for school in schools:
            revenue = SubscriptionPayment.objects.filter(
                school=school,
                status='COMPLETED'
            ).aggregate(total=Sum('amount'))['total'] or 0
            total_revenue += revenue
            
            student_count = Students.objects.filter(school=school).count()
            
            school_data.append({
                'name': school.name,
                'id': school.id,
                'student_count': student_count,
                'revenue': revenue,
                'subscription': school.subscription,
            })
            
            if school.subscription.status == 'OVERDUE':
                overdue_schools += 1
        
        pending_payments = SubscriptionPayment.objects.filter(
            status='PENDING'
        ).select_related('school', 'subscription')
        
        context = {
            'total_revenue': total_revenue,
            'active_schools': School.objects.filter(is_active=True).count(),
            'pending_payments': pending_payments.count(),
            'overdue_schools': overdue_schools,
            'schools': school_data,
            'pending_payment_list': pending_payments,
        }
        return render(request, 'finance/finance_dashboard.html', context)
    
    # ===== SCHOOL ADMIN =====
    elif user.role == 'ADMIN':
        from students.models import Students
        from academic.models import Classroom
        from finance.models import Payement
        from django.db.models import Sum
        from django.utils import timezone
        
        school = user.school
        
        total_revenue = Payement.objects.filter(
            school=school
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        today = timezone.now()
        start_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_revenue = Payement.objects.filter(
            school=school,
            date_paid__gte=start_of_month
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        total_students = Students.objects.filter(school=school).count()
        fee_per_student = getattr(school, 'fee_per_student', 5000)
        
        classrooms = Classroom.objects.filter(school=school)
        class_revenue = []
        for classroom in classrooms:
            students = Students.objects.filter(school=school, current_class=classroom)
            student_count = students.count()
            expected = student_count * fee_per_student
            collected = Payement.objects.filter(
                school=school,
                student__in=students
            ).aggregate(total=Sum('amount_paid'))['total'] or 0
            pending = expected - collected
            percentage = round((collected / expected * 100), 1) if expected > 0 else 0
            
            class_revenue.append({
                'classroom': classroom,
                'student_count': student_count,
                'expected': expected,
                'collected': collected,
                'pending': pending,
                'percentage': percentage,
            })
        
        recent_payments = Payement.objects.filter(
            school=school
        ).order_by('-date_paid')[:5]
        
        context = {
            'total_revenue': total_revenue,
            'total_students': total_students,
            'monthly_revenue': monthly_revenue,
            'fee_per_student': fee_per_student,
            'class_revenue': class_revenue,
            'recent_payments': recent_payments,
        }
        return render(request, 'finance/finance_dashboard.html', context)
    
    # ===== BURSAR ===== (NEW - Same as Admin but with extra stats)
    elif user.role == 'BURSAR':
        from students.models import Students
        from academic.models import Classroom
        from finance.models import Payement
        from django.db.models import Sum
        from django.utils import timezone
        
        school = user.school
        
        # If Bursar has no school, redirect
        if not school:
            messages.error(request, "Your account is not associated with any school.")
            return redirect('dashboard')
        
        # Total revenue
        total_revenue = Payement.objects.filter(
            school=school
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        # This month
        today = timezone.now()
        start_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_revenue = Payement.objects.filter(
            school=school,
            date_paid__gte=start_of_month
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        # Total students
        total_students = Students.objects.filter(school=school).count()
        
        # Fee per student
        fee_per_student = getattr(school, 'fee_per_student', 5000)
        
        # Revenue by class
        classrooms = Classroom.objects.filter(school=school)
        class_revenue = []
        for classroom in classrooms:
            students = Students.objects.filter(school=school, current_class=classroom)
            student_count = students.count()
            expected = student_count * fee_per_student
            collected = Payement.objects.filter(
                school=school,
                student__in=students
            ).aggregate(total=Sum('amount_paid'))['total'] or 0
            pending = expected - collected
            percentage = round((collected / expected * 100), 1) if expected > 0 else 0
            
            class_revenue.append({
                'classroom': classroom,
                'student_count': student_count,
                'expected': expected,
                'collected': collected,
                'pending': pending,
                'percentage': percentage,
            })
        
        # Payment method breakdown
        mpesa_total = Payement.objects.filter(
            school=school,
            method='M-Pesa'
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        bank_total = Payement.objects.filter(
            school=school,
            method='Bank'
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        cash_total = Payement.objects.filter(
            school=school,
            method='Cash'
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        # Recent payments
        recent_payments = Payement.objects.filter(
            school=school
        ).order_by('-date_paid')[:10]
        
        # Pending payments (students with balance)
        pending_payments = []
        students_with_balance = Students.objects.filter(school=school)
        for student in students_with_balance[:10]:
            balance = student.get_fee_balance()
            if balance > 0:
                pending_payments.append({
                    'student': student,
                    'balance': balance
                })
        
        context = {
            'total_revenue': total_revenue,
            'monthly_revenue': monthly_revenue,
            'total_students': total_students,
            'fee_per_student': fee_per_student,
            'class_revenue': class_revenue,
            'recent_payments': recent_payments,
            'mpesa_total': mpesa_total,
            'bank_total': bank_total,
            'cash_total': cash_total,
            'pending_payments': pending_payments,
            'user_role': user.role,
        }
        return render(request, 'finance/finance_dashboard.html', context)
    
    else:
        messages.error(request, "You don't have permission to view this page.")
        return redirect('dashboard')
        
# ============================================================
# SUBSCRIPTION VIEWS (MOVED FROM accounts/views.py)
# ============================================================

from finance.forms import SchoolMpesaConfigForm
from finance.mpesa_utility import stk_push

@login_required
def subscription_dashboard(request):
    """School Admin - View subscription status and pay"""
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    subscription = request.user.school.subscription
    student_count = subscription.get_student_count()
    monthly_fee = subscription.calculate_monthly_fee()
    termly_fee = monthly_fee * 3
    annual_fee = monthly_fee * 9
    
    days_left = subscription.days_until_expiry() if hasattr(subscription, 'days_until_expiry') else 0
    
    if subscription.status == 'PENDING':
        status_msg = {
            'type': 'warning',
            'title': '⏳ Awaiting First Payment',
            'message': f'Please pay KES {subscription.get_current_fee():,.0f} to activate your subscription.',
        }
    elif subscription.status == 'ACTIVE':
        if days_left <= 3 and days_left > 0:
            status_msg = {
                'type': 'warning',
                'title': '⚠️ Subscription Ending Soon',
                'message': f'Your subscription ends in {days_left} days. Please renew.',
            }
        else:
            status_msg = {
                'type': 'success',
                'title': '✅ Subscription Active',
                'message': f'Next billing: {subscription.next_billing_date.strftime("%d/%m/%Y") if subscription.next_billing_date else "Not set"}',
            }
    elif subscription.status == 'OVERDUE':
        status_msg = {
            'type': 'danger',
            'title': '❌ Payment Overdue',
            'message': 'Your subscription payment is overdue. Please pay immediately.',
        }
    else:
        status_msg = {
            'type': 'critical',
            'title': '🚫 Subscription Suspended',
            'message': 'Your subscription has been suspended. Please contact support.',
        }
    
    payments = SubscriptionPayment.objects.filter(school=request.user.school).order_by('-created_at')[:10]
    
    context = {
        'subscription': subscription,
        'status_msg': status_msg,
        'student_count': student_count,
        'monthly_fee': monthly_fee,
        'termly_fee': termly_fee,
        'annual_fee': annual_fee,
        'payments': payments,
    }
    return render(request, 'finance/subscription_dashboard.html', context)


@login_required
def initiate_subscription_payment(request):
    """Initiate M-Pesa payment for subscription"""
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        billing_cycle = request.POST.get('billing_cycle')
        
        subscription = request.user.school.subscription
        
        if subscription.billing_cycle != billing_cycle:
            subscription.billing_cycle = billing_cycle
            subscription.save()
        
        amount = subscription.get_current_fee()
        
        payment = SubscriptionPayment.objects.create(
            subscription=subscription,
            school=request.user.school,
            amount=amount,
            billing_cycle=billing_cycle,
            period_start=subscription.current_period_end or timezone.now(),
            period_end=None,
            status='PENDING',
        )
        
        if phone_number.startswith('0'):
            phone_number = '254' + phone_number[1:]
        elif phone_number.startswith('+'):
            phone_number = phone_number[1:]
        
        result = stk_push(
            phone_number=phone_number,
            amount=amount,
            reg_number=request.user.school.code,
            transaction_desc=f"EduNexus Subscription - {request.user.school.name}"
        )
        
        if result.get('ResponseCode') == '0':
            checkout_id = result.get('CheckoutRequestID')
            payment.transaction_id = checkout_id
            payment.save()
            
            request.session['pending_subscription_payment'] = payment.id
            
            return render(request, 'finance/subscription_loading.html', {
                'payment_id': payment.id,
                'amount': amount,
                'phone_number': phone_number,
                'school_name': request.user.school.name,
            })
        else:
            payment.delete()
            messages.error(request, "Payment initiation failed. Please try again.")
            return redirect('subscription_dashboard')
    
    return redirect('finance/subscription_dashboard')


@login_required
def check_subscription_payment(request, payment_id):
    """Check subscription payment status (AJAX)"""
    payment = get_object_or_404(SubscriptionPayment, id=payment_id)
    return JsonResponse({'status': payment.status.lower()})


@csrf_exempt
def subscription_mpesa_callback(request):
    """M-Pesa callback for subscription payments"""
    try:
        data = json.loads(request.body)
        body = data.get('Body', {})
        stk_callback = body.get('stkCallback', {})
        result_code = stk_callback.get('ResultCode')
        checkout_request_id = stk_callback.get('CheckoutRequestID')
        
        if result_code == 0:
            callback_metadata = stk_callback.get('CallbackMetadata', {})
            items = callback_metadata.get('Item', [])
            
            mpesa_receipt = None
            for item in items:
                if item.get('Name') == 'MpesaReceiptNumber':
                    mpesa_receipt = item.get('Value')
            
            payment = SubscriptionPayment.objects.filter(transaction_id=checkout_request_id).first()
            if payment:
                payment.mark_completed(checkout_request_id, mpesa_receipt)
                
                SubscriptionInvoice.objects.create(
                    school=payment.school,
                    subscription=payment.subscription,
                    invoice_number=f"INV-{payment.school.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    amount=payment.amount,
                    status='PAID',
                    billing_period_start=payment.period_start,
                    billing_period_end=payment.subscription.current_period_end,
                    due_date=timezone.now(),
                    paid_date=timezone.now(),
                    student_count_at_billing=payment.subscription.get_student_count(),
                    fee_breakdown={'billing_cycle': payment.billing_cycle},
                )
                
                print(f"✅ Subscription payment completed for {payment.school.name}")
        
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Success"})
        
    except Exception as e:
        print(f"Callback error: {e}")
        return JsonResponse({"ResultCode": 1, "ResultDesc": str(e)})


@login_required
def manual_subscription_payment(request):
    """Handle manual subscription payment request"""
    if request.user.role != 'ADMIN':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "Access denied."})
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        billing_cycle = request.POST.get('billing_cycle')
        subscription = request.user.school.subscription
        
        subscription.billing_cycle = billing_cycle
        subscription.save()
        
        amount = subscription.get_current_fee()
        
        payment = SubscriptionPayment.objects.create(
            subscription=subscription,
            school=request.user.school,
            amount=amount,
            billing_cycle=billing_cycle,
            period_start=timezone.now(),
            period_end=None,
            status='PENDING',
        )
        
        from notification.models import Notification
        from accounts.models import User
        
        # ✅ Get ALL super admins
        super_admins = User.objects.filter(role='SUPER_ADMIN', is_active=True)
        school_name = request.user.school.name
        admin_name = request.user.get_full_name() or request.user.username
        
        # ✅ Create notification for EACH super admin
        for admin in super_admins:
            Notification.objects.create(
                sender=request.user,
                recipient=admin,
                title=" New Subscription Payment Request",
                message=f"{admin_name} from {school_name} requests to pay KES {amount:,.0f} for {billing_cycle} plan. Please confirm payment.",
                notification_type='FEE'
            )
        
        # ✅ Also create a pending payment notification in the system
        # The Super Admin can see this on their dashboard
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Request sent successfully'})
        
        plan_names = {
            'MONTHLY': 'Monthly Plan',
            'TERMLY': 'Termly Plan',
            'ANNUALLY': 'Annual Plan'
        }
        
        return render(request, 'finance/subscription_loading.html', {
            'payment_type': 'manual',
            'amount': amount,
            'plan_name': plan_names.get(billing_cycle, billing_cycle),
        })
    
    return redirect('subscription_dashboard')


@login_required
def confirm_subscription_payment(request, school_id):
    """Super Admin - Confirm manual payment and activate school"""
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can confirm payments.")
        return redirect('dashboard')
    
    school = get_object_or_404(School, id=school_id)
    subscription = school.subscription
    
    subscription.status = 'ACTIVE'
    subscription.is_first_month = False
    subscription.update_billing_dates()
    subscription.save()
    
    SubscriptionPayment.objects.filter(
        school=school,
        status='PENDING'
    ).update(status='COMPLETED', paid_at=timezone.now())
    
    from notification.models import Notification
    
    school_admins = User.objects.filter(role='ADMIN', school=school)
    
    for admin in school_admins:
        Notification.objects.create(
            sender=request.user,
            recipient=admin,
            title=" Subscription Activated",
            message=f"Your subscription payment has been confirmed. Your school is now active until {subscription.current_period_end.strftime('%d %b %Y')}.",
            notification_type='FEE'
        )
    
    messages.success(request, f"Subscription payment confirmed for {school.name}. School is now active.")
    return redirect('super_admin_school_detail', school_id=school_id)


@login_required
def super_admin_pending_payments(request):
    """Super Admin - View ALL pending subscription payments"""
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    pending_payments = SubscriptionPayment.objects.filter(
        status='PENDING'
    ).select_related('school', 'subscription').order_by('-created_at')
    
    overdue_schools = School.objects.filter(
        subscription__status='OVERDUE'
    ).select_related('subscription')
    
    return render(request, 'accounts/pending_payments.html', {
        'pending_payments': pending_payments,
        'overdue_schools': overdue_schools,
    })


@login_required
def school_payment_settings(request):
    from .forms import SchoolMpesaConfigForm

    """School Admin - Configure their M-Pesa settings"""

    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    school = request.user.school
    config, created = SchoolMpesaConfig.objects.get_or_create(school=school)

    if request.method == 'POST':
        form = SchoolMpesaConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "M-Pesa settings saved successfully!")
            return redirect('school_payment_settings')
    else:
        form = SchoolMpesaConfigForm(instance=config)

    context = {
        'form': form,
        'config': config,
        'school': school,
    }
    return render(request, 'finance/school_payment_settings.html', context)
@login_required
def test_mpesa_connection(request):
    """Test if school's M-Pesa credentials are valid"""
    
    if request.user.role != 'ADMIN':
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    school = request.user.school
    config = school.mpesa_config
    
    if not all([config.consumer_key, config.consumer_secret]):
        return JsonResponse({'success': False, 'message': 'Please enter Consumer Key and Consumer Secret first'})
    
    if config.environment == 'sandbox':
        api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    else:
        api_url = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    
    credentials = f"{config.consumer_key}:{config.consumer_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()
    
    headers = {'Authorization': f'Basic {encoded}'}
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            config.is_configured = True
            config.last_tested = timezone.now()
            config.test_response = "✅ Connection successful!"
            config.save()
            return JsonResponse({'success': True, 'message': 'Connection successful! Your M-Pesa is ready.'})
        else:
            config.is_configured = False
            config.test_response = f"❌ Error: {response.status_code}"
            config.save()
            return JsonResponse({'success': False, 'message': f'Invalid credentials. Error: {response.status_code}'})
            
    except Exception as e:
        config.is_configured = False
        config.test_response = f"❌ Error: {str(e)}"
        config.save()
        return JsonResponse({'success': False, 'message': f'Connection failed: {str(e)}'})

    
# finance/views.py - ADD THIS VIEW

# ============================================================
# SUPER ADMIN - SUBSCRIPTION SETTINGS
# ============================================================

# finance/views.py - Update the toggle_pause action

@login_required
def subscription_settings(request):
    """Super Admin - Configure subscription plans and manage schools"""
    
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    # Get or create global settings
    global_settings, created = SubscriptionPlan.objects.get_or_create(
        is_default=True,
        defaults={
            'name': 'Global Settings',
            'plan_type': 'TIERED',
            'description': 'Global default settings',
            'is_active': True,
            'is_default': True
        }
    )
    
    schools = School.objects.all().order_by('name')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # ===== UPDATE GLOBAL SETTINGS =====
        if action == 'update_global':
            global_settings.monthly_base_fee = Decimal(request.POST.get('monthly_base_fee', 2700))
            global_settings.termly_base_fee = Decimal(request.POST.get('termly_base_fee', 7290))
            global_settings.annual_base_fee = Decimal(request.POST.get('annual_base_fee', 19440))
            global_settings.tier1_price = Decimal(request.POST.get('tier1_price', 2500))
            global_settings.tier2_price = Decimal(request.POST.get('tier2_price', 2700))
            global_settings.tier3_price = Decimal(request.POST.get('tier3_price', 3000))
            global_settings.termly_discount_percent = Decimal(request.POST.get('termly_discount', 10))
            global_settings.annual_discount_percent = Decimal(request.POST.get('annual_discount', 20))
            global_settings.per_student_fee = Decimal(request.POST.get('parent_per_student_fee', 30))
            global_settings.free_first_month = request.POST.get('free_first_month') == 'on'
            global_settings.save()
            messages.success(request, "Global settings updated successfully!")
            return redirect('subscription_settings')
        
        # ===== UPDATE SCHOOL =====
        elif action == 'update_school':
            school_id = request.POST.get('school_id')
            billing_cycle = request.POST.get('billing_cycle')
            custom_fee = request.POST.get('custom_fee')
            
            school = get_object_or_404(School, id=school_id)
            subscription = school.subscription
            subscription.billing_cycle = billing_cycle
            subscription.save()
            
            if custom_fee and custom_fee.strip():
                subscription.base_fee = Decimal(custom_fee)
                subscription.save()
            
            messages.success(request, f"Updated settings for {school.name}")
            return redirect('subscription_settings')
        
        # ===== TOGGLE FREE ACCESS (PAUSE/RESUME) =====
        elif action == 'toggle_pause':
            school_id = request.POST.get('school_id')
            notes = request.POST.get('notes', '')
            
            school = get_object_or_404(School, id=school_id)
            subscription = school.subscription
            
            if subscription.status == 'FREE':
                # RESUME BILLING - Go back to ACTIVE
                subscription.status = 'ACTIVE'
                subscription.save()
                
                SubscriptionPauseHistory.objects.create(
                    school=school,
                    paused_by=request.user,
                    unpaused_at=timezone.now(),
                    notes=f"Resumed billing: {notes}",
                    previous_status='FREE'
                )
                messages.success(request, f"'{school.name}' billing resumed. They will now be charged.")
            else:
                # PAUSE BILLING - Make it FREE
                previous_status = subscription.status
                subscription.status = 'FREE'
                subscription.save()
                
                SubscriptionPauseHistory.objects.create(
                    school=school,
                    paused_by=request.user,
                    reason="Free access granted",
                    notes=f"Billing paused: {notes}",
                    previous_status=previous_status
                )
                messages.success(request, f"'{school.name}' is now FREE. Billing paused.")
            
            return redirect('subscription_settings')
    
    context = {
        'global_settings': global_settings,
        'schools': schools,
    }
    return render(request, 'finance/subscription_settings.html', context)

@login_required
def get_subscription_stats_api(request):
    """API endpoint for subscription stats (AJAX)"""
    
    if request.user.role != 'SUPER_ADMIN':
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    total_schools = School.objects.filter(is_active=True).count()
    active_subscriptions = SchoolSubscription.objects.filter(status='ACTIVE').count()
    paused_subscriptions = SchoolSubscription.objects.filter(status='SUSPENDED').count()
    pending_payments = SubscriptionPayment.objects.filter(status='PENDING').count()
    
    # Calculate total monthly revenue
    total_monthly_revenue = Decimal('0.00')
    for school in School.objects.filter(is_active=True):
        try:
            subscription = school.subscription
            student_count = subscription.get_student_count()
            
            # Get the school's plan choice
            choice = SchoolSubscriptionChoice.objects.filter(school=school).first()
            if choice:
                monthly_fee = choice.get_effective_fee(student_count, subscription.is_first_month)
            else:
                monthly_fee = subscription.calculate_monthly_fee()
            
            total_monthly_revenue += monthly_fee
        except:
            pass
    
    return JsonResponse({
        'total_schools': total_schools,
        'active_subscriptions': active_subscriptions,
        'paused_subscriptions': paused_subscriptions,
        'pending_payments': pending_payments,
        'total_monthly_revenue': float(total_monthly_revenue),
    })