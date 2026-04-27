from django.utils import timezone

from .models import TERM_CHOICES, TermSetting


def portal_globals(request):
    current_term = TermSetting.get_current_term()
    current_term_display = dict(TERM_CHOICES).get(
        current_term,
        current_term.replace('_', ' ').title(),
    )

    return {
        'portal_current_term': current_term,
        'portal_current_term_display': current_term_display,
        'portal_current_date': timezone.localdate(),
    }
