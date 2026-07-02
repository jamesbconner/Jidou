"""Entry point for the Jidou application."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from jidou.api import health
from jidou.api.dependencies import verify_api_key
from jidou.api.routes import (
    admin,
    config,
    export_routes,
    files,
    import_routes,
    orphans,
    rss,
    shows,
    tasks,
    watchlist,
)
from jidou.api.websocket import ws_router
from jidou.config import settings
from jidou.database import close_db, init_db
from jidou.services.pubsub_subscriber import pubsub_subscriber

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Manage application startup and shutdown events.

    Args:
        app: The FastAPI application instance.

    Yields:
        None while the application is running.
    """
    # Startup
    logger.info("Starting %s...", settings.app_name)
    if settings.debug:
        try:
            await init_db()
            logger.info("Database initialized successfully (dev mode)")
        except Exception as exc:
            logger.warning("Database initialization skipped (DB unavailable): %s", exc)

    # Start Redis PubSub subscriber for WebSocket progress
    try:
        await pubsub_subscriber.start()
    except Exception as exc:
        logger.warning("PubSub subscriber failed to start: %s", exc)

    yield

    # Shutdown
    await pubsub_subscriber.stop()
    await close_db()
    logger.info("Database connections closed")


def create_app() -> FastAPI:
    """Factory function to create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _auth = [Depends(verify_api_key)]

    # Register routers — health and WebSocket are intentionally unauthenticated.
    app.include_router(health.router, prefix="/api")
    app.include_router(shows.router, prefix="/api", dependencies=_auth)
    app.include_router(files.router, prefix="/api", dependencies=_auth)
    app.include_router(orphans.router, prefix="/api", dependencies=_auth)
    app.include_router(tasks.router, prefix="/api", dependencies=_auth)
    app.include_router(config.router, prefix="/api", dependencies=_auth)
    app.include_router(admin.router, prefix="/api", dependencies=_auth)
    app.include_router(watchlist.router, prefix="/api", dependencies=_auth)
    app.include_router(rss.router, prefix="/api", dependencies=_auth)
    app.include_router(import_routes.router, prefix="/api", dependencies=_auth)
    app.include_router(export_routes.router, prefix="/api", dependencies=_auth)
    app.include_router(ws_router)

    # Exception handlers for client errors
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        """Convert ValueError from service layer to 400 Bad Request."""
        logger.warning("Client error: %s", exc)
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return app


# App instance for Uvicorn
app = create_app()


def main() -> None:
    """Run the Jidou application via CLI."""
    import uvicorn

    logger.info("Starting %s on port 8192", settings.app_name)
    uvicorn.run("jidou.main:app", host="0.0.0.0", port=8192, reload=settings.debug)  # nosec B104 — intentional: container listens on all interfaces, network isolation via Docker


if __name__ == "__main__":
    main()  # pragma: no cover
