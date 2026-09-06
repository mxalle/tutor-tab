"""Handler routers, in the order the dispatcher should try them."""

from aiogram import Router

from bot.handlers import parent, start, tutor


def build_router() -> Router:
    """One root router with every handler group attached."""
    router = Router(name="root")
    router.include_router(start.router)
    router.include_router(tutor.router)
    router.include_router(parent.router)
    return router
