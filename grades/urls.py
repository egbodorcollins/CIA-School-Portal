from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.RateLimitedLoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/student/', views.register_student, name='register_student'),
    path('register/teacher/', views.register_teacher, name='register_teacher'),
    path(
        'password/change/',
        auth_views.PasswordChangeView.as_view(
            template_name='grades/password_change_form.html',
            success_url=reverse_lazy('password_change_done'),
        ),
        name='password_change',
    ),
    path(
        'password/change/done/',
        auth_views.PasswordChangeDoneView.as_view(
            template_name='grades/password_change_done.html',
        ),
        name='password_change_done',
    ),
    path('teacher/dashboard/', views.teacher_dashboard, name='teacher_dashboard'),
    path('teacher/analytics/', views.class_analytics, name='class_analytics'),
    path('teacher/current-term/', views.set_current_term, name='set_current_term'),
    path('admin-staff/announcements/', views.manage_announcements, name='manage_announcements'),
    path('teacher/enter-scores/', views.enter_academic_scores, name='enter_academic_scores'),
    path('teacher/enter-behavior/', views.enter_behavioral_assessments, name='enter_behavioral_assessments'),
    path('teacher/results/', views.staff_results, name='staff_results'),
    path('teacher/results/<int:student_pk>/session-summary/', views.session_summary_entry, name='session_summary_entry'),
    path('teacher/results/<int:student_pk>/pdf/', views.staff_report_pdf, name='staff_report_pdf'),
    path('portal/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/dashboard/', views.admin_dashboard, name='portal_admin_dashboard'),
    path('admin/classes/', views.admin_classes, name='admin_classes'),
    path('admin/classes/<path:class_name>/', views.admin_class_detail, name='admin_class_detail'),
    path('admin/subjects/', views.admin_subjects, name='admin_subjects'),
    path('admin/subjects/<int:subject_id>/', views.admin_subject_detail, name='admin_subject_detail'),
    path('admin/students/', views.admin_students, name='admin_students'),
    path('admin/students/<int:student_id>/', views.admin_student_detail, name='admin_student_detail'),
    path('admin/staff/', views.admin_staff, name='admin_staff'),
    path('admin/staff/<int:staff_id>/', views.admin_staff_detail, name='admin_staff_detail'),
    path('admin/staff/new/', views.register_teacher, name='admin_staff_new'),
    path('admin/promotion/', views.admin_promotion, name='admin_promotion'),
    path('admin/promotion/<path:class_name>/', views.admin_promotion_class, name='admin_promotion_class'),
    path('admin/results/', views.admin_results, name='admin_results'),
    path('admin/settings/', views.admin_settings, name='admin_settings'),
    path('admin/settings/academic-session/', views.set_current_term, name='admin_academic_session'),
    path('admin-staff/result-releases/', views.result_publications, name='result_publications'),
    path('teacher/manage-students/', views.manage_students, name='manage_students'),
    path('teacher/manage-students/promote-class/', views.promote_class, name='promote_class'),
    path('teacher/manage-students/promotions/<int:request_id>/approve/', views.approve_class_promotion, name='approve_class_promotion'),
    # Student IDs include slashes, so this route must accept path segments.
    path('teacher/manage-students/delete/<path:student_id>/', views.delete_student, name='delete_student'),
    path('student/dashboard/', views.student_dashboard, name='student_dashboard'),
    path('student/report/pdf/', views.report_card_pdf, name='report_card_pdf'),
]
