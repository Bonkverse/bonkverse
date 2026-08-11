# skins/events.py
import logging
from .models import UserEvent

logger = logging.getLogger(__name__)

def log_event(user, event_type, skin=None, **metadata):
    try:
        UserEvent.objects.create(
            user=user if getattr(user, "is_authenticated", False) else None,
            event_type=event_type,
            skin=skin,
            metadata=metadata or None,
        )
    except Exception:
        logger.exception("Failed to log event: %s", event_type)