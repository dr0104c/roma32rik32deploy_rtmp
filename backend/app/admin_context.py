from contextvars import ContextVar, Token


_current_admin_actor_id: ContextVar[str | None] = ContextVar("current_admin_actor_id", default=None)


def current_admin_actor_id() -> str | None:
    return _current_admin_actor_id.get()


def set_current_admin_actor(actor_id: str | None) -> Token:
    return _current_admin_actor_id.set(actor_id)


def reset_current_admin_actor(token: Token) -> None:
    _current_admin_actor_id.reset(token)
