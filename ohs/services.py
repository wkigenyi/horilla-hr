"""Domain rules for OHS (Uganda-first)."""

from ohs.models import OshEvent, OshNotification


def has_complete_authority_notification(event: OshEvent) -> bool:
    """Uganda WC s.10: initial notice plus written report."""
    return event.notifications.filter(
        notified_at__isnull=False, written_report_at__isnull=False
    ).exists()


def can_close_event(event: OshEvent, *, compensable=None) -> tuple[bool, str]:
    """Return (ok, error_message). compensable overrides the instance when provided."""
    is_compensable = event.compensable if compensable is None else compensable
    if not is_compensable:
        return True, ""
    if has_complete_authority_notification(event):
        return True, ""
    return (
        False,
        "Compensable events require a labour-officer notification with "
        "both notified_at and written_report_at before closing "
        "(Uganda Workers Compensation Act s.10).",
    )


def notification_complete_for_event(event_id: int) -> bool:
    return OshNotification.objects.filter(
        event_id=event_id,
        notified_at__isnull=False,
        written_report_at__isnull=False,
    ).exists()
