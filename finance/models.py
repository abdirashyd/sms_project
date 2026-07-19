from django.db import models
from django.conf import settings
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta
import math
from accounts.models import School


class Payement(models.Model):
    """Payment records (existing - keep as is)"""
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    
    METHODS = [
        ('M-Pesa', 'M-Pesa'),
        ('Bank', 'Bank Transfer'),
        ('Cash', 'Cash')
    ]
    
    student = models.ForeignKey('students.Students', on_delete=models.CASCADE, related_name="payments")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=100)
    method = models.CharField(max_length=20, choices=METHODS, default='M-Pesa')
    date_paid = models.DateTimeField(auto_now_add=True)
    month = models.IntegerField(null=True, blank=True)
    year = models.IntegerField(default=2026, null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.student.first_name} - KES {self.amount_paid} ({self.reference})"
    
    class Meta:
        ordering = ['-date_paid']


# ========== FEE STRUCTURE MODEL ==========
class FeeStructure(models.Model):
    """
    Fee structure set by School Director
    Can be Monthly, Termly, or Yearly
    """
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='fee_structures')
    class_assigned = models.ForeignKey('academic.Classroom', on_delete=models.CASCADE, related_name='fee_structures')
    
    BILLING_CYCLE_CHOICES = (
        ('MONTHLY', 'Monthly'),
        ('TERMLY', 'Termly (3 months)'),
        ('ANNUALLY', 'Annually (9 months)'),
    )
    
    TERM_CHOICES = (
        ('TERM_1', 'Term 1'),
        ('TERM_2', 'Term 2'),
        ('TERM_3', 'Term 3'),
    )
    
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CYCLE_CHOICES, default='MONTHLY')
    term = models.CharField(max_length=20, choices=TERM_CHOICES, default='TERM_1')
    year = models.IntegerField(default=2026)
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Fee amount per student")
    description = models.TextField(blank=True, help_text="e.g., Tuition fees for Term 1 2024")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['school', 'class_assigned', 'billing_cycle', 'term', 'year']
    
    def __str__(self):
        return f"{self.class_assigned.name} - {self.get_billing_cycle_display()} - KES {self.amount}"


# ========== MANUAL PAYMENT MODEL ==========
class ManualPayment(models.Model):
    """
    Manual payment confirmation system
    Head Teacher records payment → Director approves
    """
    student = models.ForeignKey('students.Students', on_delete=models.CASCADE, related_name='manual_payments')
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='school_manual_payments')
    
    # Who recorded and approved
    head_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='submitted_payments'
    )
    school_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='approved_payments'
    )
    
    # Payment details
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    payment_method = models.CharField(
        max_length=20,
        choices=[
            ('M-PESA', 'M-Pesa'),
            ('BANK', 'Bank Transfer'),
            ('CASH', 'Cash'),
            ('CHEQUE', 'Cheque'),
            ('OTHER', 'Other')
        ]
    )
    reference_number = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    
    # Which billing cycle this payment covers
    billing_cycle = models.CharField(
        max_length=20,
        choices=FeeStructure.BILLING_CYCLE_CHOICES,
        default='MONTHLY'
    )
    
    # Fee amount from structure (auto-calculated)
    fee_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="The fee amount from the fee structure"
    )
    
    # Balance tracking
    balance_before = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Status
    STATUS_CHOICES = (
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled')
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    # Receipt
    receipt_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    receipt_pdf = models.FileField(upload_to='receipts/', null=True, blank=True)
    
    # Timestamps
    submitted_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.student.registration_number} - KES {self.amount} ({self.status})"
    
    def generate_receipt_number(self):
        import datetime
        year = datetime.datetime.now().year
        count = ManualPayment.objects.filter(
            school=self.school,
            submitted_at__year=year,
            status='APPROVED'
        ).count() + 1
        return f"RCP-{year}-{count:04d}"
    
    def get_fee_amount(self):
        """Get fee amount from the active fee structure"""
        if not self.student.current_class:
            return Decimal('0.00')
        
        fee_structure = FeeStructure.objects.filter(
            school=self.school,
            class_assigned=self.student.current_class,
            billing_cycle=self.billing_cycle,
            is_active=True
        ).first()
        
        if fee_structure:
            return fee_structure.amount
        return Decimal('0.00')


# ========== FEE CALCULATION FUNCTION ==========
def calculate_student_fee_balance(student):
    """
    Calculate student's fee balance based on:
    - Fee structure set by Director
    - Total paid (approved manual payments)
    """
    # Total fees from structure
    total_fees = FeeStructure.objects.filter(
        school=student.school,
        class_assigned=student.current_class,
        is_active=True
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    # Total paid from approved manual payments
    total_paid = ManualPayment.objects.filter(
        student=student,
        status='APPROVED'
    ).aggregate(total=Sum('amount'))['amount'] or Decimal('0.00')
    
    # Also include existing Payement records (for backward compatibility)
    existing_paid = Payement.objects.filter(
        student=student
    ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    
    total_paid += existing_paid
    
    balance = total_fees - total_paid
    
    return {
        'total_fees': total_fees,
        'total_paid': total_paid,
        'balance': balance,
        'status': 'PAID' if balance <= 0 else 'PARTIAL' if total_paid > 0 else 'UNPAID'
    }


# ========== SCHOOL SUBSCRIPTION MODEL ==========
class SchoolSubscription(models.Model):
    """School subscription and billing information"""
    
    BILLING_CYCLE_CHOICES = (
        ('MONTHLY', 'Monthly'),
        ('TERMLY', 'Termly (3 months)'),
        ('ANNUALLY', 'Annually (9 months)'),
    )
    
    STATUS_CHOICES = (
        ('ACTIVE', 'Active - Paid'),
        ('PENDING', 'Pending Payment'),
        ('OVERDUE', 'Overdue'),
        ('FREE','Free access'),
        ('SUSPENDED', 'Suspended'),
        ('CANCELLED', 'Cancelled'),
    )
    
    school = models.OneToOneField('accounts.School', on_delete=models.CASCADE, related_name='subscription')
    
    # Subscription status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CYCLE_CHOICES, default='MONTHLY')
    
    # First month flag (special KES 2,700 onboarding)
    is_first_month = models.BooleanField(default=True)
    
    # Pricing configuration
    small_school_fee = models.DecimalField(max_digits=10, decimal_places=2, default=2500)  # 0-149 students
    base_fee = models.DecimalField(max_digits=10, decimal_places=2, default=2700)  # 150 students
    block_size = models.IntegerField(default=7)  # 7 students per block
    block_increase_percent = models.DecimalField(max_digits=5, decimal_places=2, default=2.0)  # 2% per block
    
    # Dates
    subscription_start = models.DateTimeField(auto_now_add=True)
    current_period_start = models.DateTimeField(auto_now_add=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    next_billing_date = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def days_until_expiry(self):
        """Returns number of days until subscription expires"""
        if not self.current_period_end:
            return 0
        from django.utils import timezone
        delta = self.current_period_end - timezone.now()
        return max(0, delta.days)
    
    def get_student_count(self):
        """Get current active student count for this school"""
        from students.models import Students
        return Students.objects.filter(school=self.school, is_active=True).count()
    
    def calculate_monthly_fee(self, student_count=None):
        """Calculate monthly fee based on student count"""
        if self.is_first_month:
            return Decimal('2700.00')
        
        if student_count is None:
            student_count = self.get_student_count()
        
        if student_count < 150:
            return self.small_school_fee
        
        students_above_150 = student_count - 150
        blocks = math.ceil(students_above_150 / self.block_size)
        
        multiplier = (1 + (self.block_increase_percent / 100)) ** blocks
        fee = self.base_fee * Decimal(str(multiplier))
        
        return round(fee, 2)
    
    def calculate_termly_fee(self, student_count=None):
        monthly = self.calculate_monthly_fee(student_count)
        return monthly * 3
    
    def calculate_annual_fee(self, student_count=None):
        monthly = self.calculate_monthly_fee(student_count)
        return monthly * 9
    
    def get_current_fee(self, student_count=None):
        if self.billing_cycle == 'MONTHLY':
            return self.calculate_monthly_fee(student_count)
        elif self.billing_cycle == 'TERMLY':
            return self.calculate_termly_fee(student_count)
        else:
            return self.calculate_annual_fee(student_count)
    
    def update_billing_dates(self):
        from django.utils import timezone
        from datetime import timedelta
        
        if self.billing_cycle == 'MONTHLY':
            duration = timedelta(days=30)
        elif self.billing_cycle == 'TERMLY':
            duration = timedelta(days=90)
        else:
            duration = timedelta(days=270)
        
        self.current_period_end = timezone.now() + duration
        self.next_billing_date = timezone.now() + duration
        self.save()
    
    def can_access_system(self):
        if self.status == 'ACTIVE':
            return True
        if self.status == 'FREE':
            return True
        if self.status == 'OVERDUE':
            if self.current_period_end:
                grace_end = self.current_period_end + timedelta(days=7)
                return timezone.now() <= grace_end
        return False
    
    def __str__(self):
        return f"{self.school.name} - {self.status}"


# ========== SUBSCRIPTION PAYMENT MODEL ==========
class SubscriptionPayment(models.Model):
    """Record of subscription payments made by school"""
    
    PAYMENT_STATUS = (
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    )
    
    subscription = models.ForeignKey(SchoolSubscription, on_delete=models.CASCADE, related_name='payments')
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='subscription_payments')
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    billing_cycle = models.CharField(max_length=20, choices=SchoolSubscription.BILLING_CYCLE_CHOICES)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField(null=True, blank=True)
    
    transaction_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    mpesa_receipt = models.CharField(max_length=100, blank=True, null=True)
    
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='PENDING')
    paid_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def mark_completed(self, transaction_id, mpesa_receipt=None):
        from django.utils import timezone
        self.status = 'COMPLETED'
        self.transaction_id = transaction_id
        self.mpesa_receipt = mpesa_receipt
        self.paid_at = timezone.now()
        self.save()
        
        # Update subscription dates
        self.subscription.update_billing_dates()
    
    def __str__(self):
        return f"{self.school.name} - KES {self.amount} - {self.status}"


# ========== MPESA CONFIGURATION MODEL ==========
class SchoolMpesaConfig(models.Model):
    """M-Pesa configuration for each school"""
    
    ENV_CHOICES = (
        ('sandbox', 'Sandbox (Testing)'),
        ('production', 'Production (Live)'),
    )
    
    school = models.OneToOneField('accounts.School', on_delete=models.CASCADE, related_name='mpesa_config')
    
    # M-Pesa Credentials
    shortcode = models.CharField(max_length=50, blank=True, null=True, help_text="Paybill/Till Number")
    consumer_key = models.CharField(max_length=200, blank=True, null=True)
    consumer_secret = models.CharField(max_length=200, blank=True, null=True)
    passkey = models.CharField(max_length=200, blank=True, null=True)
    
    # Environment
    environment = models.CharField(max_length=20, choices=ENV_CHOICES, default='sandbox')
    
    # Status
    is_configured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_tested = models.DateTimeField(null=True, blank=True)
    test_response = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        status = "✅ Configured" if self.is_configured else "❌ Not configured"
        return f"{self.school.name} - {status}"


# ========== SUBSCRIPTION INVOICE MODEL ==========
class SubscriptionInvoice(models.Model):
    """Invoice for each billing period"""
    
    INVOICE_STATUS = (
        ('DRAFT', 'Draft'),
        ('SENT', 'Sent'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
        ('CANCELLED', 'Cancelled'),
    )
    
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='invoices')
    subscription = models.ForeignKey(SchoolSubscription, on_delete=models.CASCADE, related_name='invoices')
    
    invoice_number = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=INVOICE_STATUS, default='DRAFT')
    
    billing_period_start = models.DateTimeField()
    billing_period_end = models.DateTimeField()
    due_date = models.DateTimeField()
    paid_date = models.DateTimeField(null=True, blank=True)
    
    student_count_at_billing = models.IntegerField()
    fee_breakdown = models.JSONField(default=dict)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def mark_as_paid(self):
        from django.utils import timezone
        self.status = 'PAID'
        self.paid_date = timezone.now()
        self.save()
        self.subscription.status = 'ACTIVE'
        self.subscription.save()
    
    def is_overdue(self):
        from django.utils import timezone
        return self.status != 'PAID' and timezone.now() > self.due_date
    
    def __str__(self):
        return f"{self.invoice_number} - {self.school.name} - KES {self.amount}"


# ========== SUBSCRIPTION PLAN MODELS ==========
class SubscriptionPlan(models.Model):
    """
    Subscription plan types that schools can choose from
    """
    PLAN_TYPES = (
        ('INSTITUTIONAL', 'Institutional (2% per 7 students above 150)'),
        ('TIERED', 'Tiered (Fixed pricing tiers)'),
        ('PARENT_DECENTRALIZED', 'Parent Pay (KSh 30 per student)'),
    )
    
    BILLING_CYCLES = (
        ('MONTHLY', 'Monthly'),
        ('TERMLY', 'Termly (3 months)'),
        ('ANNUALLY', 'Annually (9 months)'),
    )
    
    name = models.CharField(max_length=50)
    plan_type = models.CharField(max_length=30, choices=PLAN_TYPES)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    
    # Billing cycle
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CYCLES, default='MONTHLY')
    
    # ===== INSTITUTIONAL SETTINGS (plan_type = 'INSTITUTIONAL') =====
    first_month_fee = models.DecimalField(max_digits=10, decimal_places=2, default=2500, 
                                          help_text="First month fee for all schools")
    small_school_fee = models.DecimalField(max_digits=10, decimal_places=2, default=2500, 
                                           help_text="0-149 students")
    base_fee = models.DecimalField(max_digits=10, decimal_places=2, default=2700, 
                                   help_text="Base fee at 150 students")
    block_size = models.IntegerField(default=7, 
                                     help_text="Number of students per block above 150")
    block_increase_percent = models.DecimalField(max_digits=5, decimal_places=2, default=2.00, 
                                                 help_text="Percentage increase per block")
    
    # ===== TIERED SETTINGS (plan_type = 'TIERED') =====
    tier1_max = models.IntegerField(default=50, help_text="Max students for tier 1")
    tier1_price = models.DecimalField(max_digits=10, decimal_places=2, default=2500, 
                                      help_text="Price for tier 1")
    tier2_max = models.IntegerField(default=150, help_text="Max students for tier 2")
    tier2_price = models.DecimalField(max_digits=10, decimal_places=2, default=2700, 
                                      help_text="Price for tier 2")
    tier3_price = models.DecimalField(max_digits=10, decimal_places=2, default=3000, 
                                      help_text="Price for tier 3 (151+ students)")
    
    # ===== PARENT DECENTRALIZED SETTINGS (plan_type = 'PARENT_DECENTRALIZED') =====
    per_student_fee = models.DecimalField(max_digits=10, decimal_places=2, default=30, 
                                          help_text="Fee per student per month")
    parent_payment_description = models.CharField(
        max_length=255, 
        default="EduNexus School Management Fee",
        help_text="Description shown to parents"
    )
    
    # ===== DISCOUNTS (All plans) =====
    termly_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=10.00, 
                                                  help_text="Discount for termly billing")
    annual_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=20.00, 
                                                  help_text="Discount for annual billing")
    free_first_month = models.BooleanField(default=True, 
                                           help_text="Free first month for new schools")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, 
                                   blank=True, related_name='updated_plans')
    
    class Meta:
        ordering = ['name']
        verbose_name_plural = "Subscription Plans"
    
    def __str__(self):
        return f"{self.name} ({self.get_plan_type_display()})"
    
    def calculate_fee(self, student_count, is_first_month=False):
        """
        Calculate the monthly fee based on the plan type and student count
        """
        if is_first_month and self.free_first_month:
            return Decimal('0.00')
        
        if is_first_month:
            return self.first_month_fee
        
        if self.plan_type == 'INSTITUTIONAL':
            return self._calculate_institutional_fee(student_count)
        elif self.plan_type == 'TIERED':
            return self._calculate_tiered_fee(student_count)
        elif self.plan_type == 'PARENT_DECENTRALIZED':
            return self._calculate_parent_fee(student_count)
        
        return Decimal('0.00')
    
    def _calculate_institutional_fee(self, student_count):
        """Calculate fee using the institutional model (2% per 7 students above 150)"""
        if student_count < 150:
            return self.small_school_fee
        
        students_above_150 = student_count - 150
        blocks = math.ceil(students_above_150 / self.block_size)
        
        increase_percent = blocks * self.block_increase_percent
        increase_amount = self.base_fee * (increase_percent / 100)
        
        return round(self.base_fee + increase_amount, 2)
    
    def _calculate_tiered_fee(self, student_count):
        """Calculate fee using the tiered model"""
        if student_count <= self.tier1_max:
            return self.tier1_price
        elif student_count <= self.tier2_max:
            return self.tier2_price
        else:
            return self.tier3_price
    
    def _calculate_parent_fee(self, student_count):
        """Calculate fee using the parent decentralized model"""
        return self.per_student_fee * student_count
    
    def get_discounted_fee(self, student_count, billing_cycle, is_first_month=False):
        """Calculate the fee with discounts applied for termly/annual billing"""
        base_fee = self.calculate_fee(student_count, is_first_month)
        
        if billing_cycle == 'TERMLY':
            discount = self.termly_discount_percent / 100
            return base_fee * 3 * (1 - discount)
        elif billing_cycle == 'ANNUALLY':
            discount = self.annual_discount_percent / 100
            return base_fee * 9 * (1 - discount)
        
        return base_fee


class SchoolSubscriptionChoice(models.Model):
    """
    Which subscription plan a school has chosen
    """
    school = models.OneToOneField('accounts.School', on_delete=models.CASCADE, 
                                  related_name='subscription_choice')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, 
                            related_name='school_choices')
    
    # Custom overrides for this school (optional)
    custom_tier1_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    custom_tier2_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    custom_tier3_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    custom_base_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    custom_per_student_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Custom discounts
    custom_termly_discount = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    custom_annual_discount = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    # When this choice was made
    chosen_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "School Subscription Choices"
    
    def __str__(self):
        return f"{self.school.name} → {self.plan.name}"
    
    def get_effective_fee(self, student_count, is_first_month=False):
        """Get the fee with any custom overrides applied"""
        if self.plan.plan_type == 'INSTITUTIONAL':
            return self._get_effective_institutional_fee(student_count, is_first_month)
        elif self.plan.plan_type == 'TIERED':
            return self._get_effective_tiered_fee(student_count, is_first_month)
        elif self.plan.plan_type == 'PARENT_DECENTRALIZED':
            return self._get_effective_parent_fee(student_count, is_first_month)
        return Decimal('0.00')
    
    def _get_effective_institutional_fee(self, student_count, is_first_month=False):
        if is_first_month and self.plan.free_first_month:
            return Decimal('0.00')
        if is_first_month:
            return self.plan.first_month_fee
        
        if student_count < 150:
            return self.plan.small_school_fee
        
        students_above_150 = student_count - 150
        blocks = math.ceil(students_above_150 / self.plan.block_size)
        
        # Use custom base fee if set, otherwise use plan's base fee
        base_fee = self.custom_base_fee if self.custom_base_fee else self.plan.base_fee
        
        increase_percent = blocks * self.plan.block_increase_percent
        increase_amount = base_fee * (increase_percent / 100)
        
        return round(base_fee + increase_amount, 2)
    
    def _get_effective_tiered_fee(self, student_count, is_first_month=False):
        if is_first_month and self.plan.free_first_month:
            return Decimal('0.00')
        if is_first_month:
            return self.plan.first_month_fee
        
        if student_count <= self.plan.tier1_max:
            return self.custom_tier1_price if self.custom_tier1_price else self.plan.tier1_price
        elif student_count <= self.plan.tier2_max:
            return self.custom_tier2_price if self.custom_tier2_price else self.plan.tier2_price
        else:
            return self.custom_tier3_price if self.custom_tier3_price else self.plan.tier3_price
    
    def _get_effective_parent_fee(self, student_count, is_first_month=False):
        if is_first_month and self.plan.free_first_month:
            return Decimal('0.00')
        if is_first_month:
            return self.plan.first_month_fee
        
        per_student = self.custom_per_student_fee if self.custom_per_student_fee else self.plan.per_student_fee
        return per_student * student_count
    
    def get_effective_discounted_fee(self, student_count, billing_cycle, is_first_month=False):
        """Get discounted fee with custom discounts applied"""
        base_fee = self.get_effective_fee(student_count, is_first_month)
        
        if billing_cycle == 'TERMLY':
            discount = self.custom_termly_discount if self.custom_termly_discount else self.plan.termly_discount_percent
            return base_fee * 3 * (1 - discount / 100)
        elif billing_cycle == 'ANNUALLY':
            discount = self.custom_annual_discount if self.custom_annual_discount else self.plan.annual_discount_percent
            return base_fee * 9 * (1 - discount / 100)
        
        return base_fee


class SubscriptionPauseHistory(models.Model):
    """
    Track when schools have been paused/unpaused
    """
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, 
                              related_name='pause_history')
    paused_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, 
                                  related_name='paused_subscriptions')
    paused_at = models.DateTimeField(auto_now_add=True)
    unpaused_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    
    # What was the status before pause
    previous_status = models.CharField(max_length=20)
    
    class Meta:
        ordering = ['-paused_at']
        verbose_name_plural = "Subscription Pause History"
    
    def __str__(self):
        return f"{self.school.name} - Paused at {self.paused_at.strftime('%Y-%m-%d %H:%M')}"


# ========== SIGNAL TO CREATE SUBSCRIPTION WHEN SCHOOL IS CREATED ==========
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=School)
def create_school_subscription(sender, instance, created, **kwargs):
    """Auto-create subscription when a new school is created"""
    if created:
        SchoolSubscription.objects.create(school=instance)