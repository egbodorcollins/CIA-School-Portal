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
    path('teacher/current-term/', views.set_current_term, name='set_current_term'),
    path('teacher/enter-scores/', views.enter_academic_scores, name='enter_academic_scores'),
    path('teacher/enter-behavior/', views.enter_behavioral_assessments, name='enter_behavioral_assessments'),
    path('teacher/manage-students/', views.manage_students, name='manage_students'),
    path('teacher/manage-students/promote-class/', views.promote_class, name='promote_class'),
    path('teacher/manage-students/promotions/<int:request_id>/approve/', views.approve_class_promotion, name='approve_class_promotion'),
    # Student IDs include slashes, so this route must accept path segments.
    path('teacher/manage-students/delete/<path:student_id>/', views.delete_student, name='delete_student'),
    path('student/dashboard/', views.student_dashboard, name='student_dashboard'),
    path('student/report/pdf/', views.report_card_pdf, name='report_card_pdf'),
]
