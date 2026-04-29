from django.contrib.auth.decorators import user_passes_test


def _has_role(user, roles):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    # Treat Django staff users as privileged (allow access to teacher/admin views)
    if getattr(user, 'is_staff', False):
        return True
    profile = getattr(user, 'profile', None)
    if profile is None:
        try:
            from .models import Profile
            profile, _ = Profile.objects.get_or_create(user=user)
        except Exception:
            return False
    return profile.role in roles


def roles_required(roles):
    return user_passes_test(lambda u: _has_role(u, roles))


# Convenience decorators
admin_required = roles_required(['admin'])
class_teacher_or_admin_required = roles_required(['class_teacher', 'admin'])
teacher_or_admin_required = roles_required(['class_teacher', 'subject_teacher', 'admin'])
subject_teacher_or_admin_required = roles_required(['subject_teacher', 'admin'])
