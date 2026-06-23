from django.conf import settings
from django.http import HttpResponseRedirect


class LocalhostRedirectMiddleware:
    """Use localhost as the canonical local dev host.

    Browsers keep separate cookies for localhost and 127.0.0.1, so the same
    page can appear different if one host is logged in and the other is not.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host()
        hostname, separator, port = host.partition(':')

        if getattr(settings, 'DEBUG', False) and hostname == '127.0.0.1':
            canonical_host = 'localhost'
            if separator:
                canonical_host = f'{canonical_host}:{port}'
            return HttpResponseRedirect(
                f'{request.scheme}://{canonical_host}{request.get_full_path()}'
            )

        return self.get_response(request)
