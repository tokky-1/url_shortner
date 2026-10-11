from fastapi import FastAPI

from core.config import get_settings
from core.log_config import RequestLoggingMiddleware, setup_logging


def create_app() -> FastAPI:
    setup_logging(get_settings().LOG_LEVEL)

    from routes.health import health_router
    from routes.urls import router

    app = FastAPI(title="URL Shortener")
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(health_router)
    app.include_router(router)
    return app


app = create_app()
