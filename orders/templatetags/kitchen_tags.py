"""Template filters for the kitchen screen.

The kitchen queue escalates a ticket's elapsed-time indicator once it has been
waiting too long. That decision is made while rendering
``orders/_kitchen_queue.html``, which is served by two different views (the
full page and the polling endpoint), so it lives in a filter rather than in a
context variable — neither view needs to know about it.
"""
from django.template import Library
from django.utils import timezone

register = Library()


@register.filter
def minutes_since(value):
    """Whole minutes elapsed between ``value`` (a datetime) and now.

    ``timezone.now()`` already matches the awareness of model datetimes under
    the project's ``USE_TZ`` setting. Missing values and timestamps in the
    future both collapse to ``0`` so the template can compare the result
    against a threshold without guarding.
    """
    if not value:
        return 0

    elapsed = (timezone.now() - value).total_seconds()
    return max(0, int(elapsed // 60))
