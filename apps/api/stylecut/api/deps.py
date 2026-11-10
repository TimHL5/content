from uuid import UUID

from stylecut.settings import get_settings


def current_user_id() -> UUID:
    """Single-user mode until auth lands in Phase 7."""
    return get_settings().dev_user_id
