from django import template

register = template.Library()

@register.filter
def replace(value, arg):
    """
    Replace occurrences of the first character in arg with the second character.
    Usage: {{ value|replace:"_ " }}
    """
    if not value or not arg or len(arg) < 2:
        return value
    old, new = arg[0], arg[1:]
    return str(value).replace(old, new)