from django.contrib import admin
from .models import Payement


@admin.register(Payement)
class PayementAdmin(admin.ModelAdmin):
    list_display = (
        'student', 
        'amount_paid', 
        'reference', 
        'method', 
        'date_paid', 
        'month', 
        'year'
    )
    search_fields = ('student__first_name', 'student__registration_number', 'reference')
    list_filter = ('method', 'month', 'year')
    readonly_fields = ('date_paid',)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('student')