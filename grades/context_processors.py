from django.utils import timezone

from .models import TERM_CHOICES, TermSetting


def _build_initials(display_name, fallback_username):
    source = display_name or fallback_username or 'User'
    parts = [part for part in source.split() if part]
    if len(parts) >= 2:
        initials = parts[0][0] + parts[1][0]
    else:
        initials = source[:2]
    return initials.upper()


def portal_globals(request):
    current_term = TermSetting.get_current_term()
    current_term_display = dict(TERM_CHOICES).get(
        current_term,
        current_term.replace('_', ' ').title(),
    )

    user_display_name = ''
    user_initials = 'U'
    profile = None
    if getattr(request, 'user', None) and request.user.is_authenticated:
        user_display_name = request.user.get_full_name().strip() or request.user.username
        user_initials = _build_initials(user_display_name, request.user.username)
        try:
            profile = request.user.profile
        except Exception:
            profile = None

    return {
        'portal_current_term': current_term,
        'portal_current_term_display': current_term_display,
        'portal_current_date': timezone.localdate(),
        'portal_user_display_name': user_display_name,
        'portal_user_initials': user_initials,
        'portal_user_profile': profile,
    }
