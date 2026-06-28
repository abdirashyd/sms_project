from django.contrib import admin
from .models import Classroom, Subject, Exam, Results, Teacher
from .models import download_marks_sheet


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('name', 'stream', 'get_students_count', 'get_capacity_status')
    search_fields = ('name', 'stream')
    filter_horizontal = ('subjects',)

    def get_students_count(self, obj):
        return obj.get_students_count()  # ✅ FIXED
    get_students_count.short_description = 'Students Count'

    def get_capacity_status(self, obj):
        return obj.get_capacity_status()
    get_capacity_status.short_description = 'Status'


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code')
    search_fields = ('name', 'code')


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ('name', 'exam_type', 'date_started')
    list_filter = ('exam_type',)
    search_fields = ('name',)
    actions = ['download_marks_sheet_action']

    @admin.action(description='Download Marks Sheet Template (CSV)')
    def download_marks_sheet_action(self, request, queryset):
        return download_marks_sheet(self, request, queryset)


@admin.register(Results)
class ResultsAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'exam', 'marks_obtained', 'grades')
    list_filter = ('exam', 'subject')
    search_fields = ('student__first_name', 'student__last_name', 'subject__name')


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('name', 'tsc_number', 'phone')
    search_fields = ('name', 'tsc_number')