from contextvars import ContextVar


_current_admin_actor_id: ContextVar[str | None] = ContextVar("current_admin_actor_id", default=None)


def current_admin_actor_id() -> str | None:
    return _current_admin_actor_id.get()


def set_current_admin_actor(actor_id: str | None) -> None:
    _current_admin_actor_id.set(actor_id)


def clear_current_admin_actor() -> None:
    _current_admin_actor_id.set(None)
