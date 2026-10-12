"""Entry point for the Jidou application."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from jidou import __version__
from jidou.api import health
from jidou.api.dependencies import verify_api_key
from jidou.api.routes import (
    admin,
    config,
    dashboard,
    export_routes,
    files,
    images,
    import_routes,
    orphans,
    rss_feeds,
    rss_publish,
    rss_subscriptions,
    show_episodes,
    show_local_files,
    shows,
    tasks,
    tmdb_proxy,
    watchlist,
)
from jidou.api.routes import (
    settings as settings_routes,
)
from jidou.api.websocket import ws_router
from jidou.api.websocket.task_progress import manager
from jidou.config import settings
from jidou.database import close_db, init_db
from jidou.orchestrators.errors import (
    InvalidRequestError,
    NotFoundError,
    OrchestratorError,
    UpstreamError,
)
from jidou.services.llm_service import create_llm_service
from jidou.services.pubsub_subscriber import pubsub_subscriber

logger = logging.getLogger(__name__)

# The one place orchestrator domain errors become HTTP statuses. To map a new error class, add
# a subclass of OrchestratorError in ``jidou.orchestrators.errors`` and one line here.
_ORCHESTRATOR_ERROR_STATUS: dict[type[OrchestratorError], int] = {
    NotFoundError: 404,
    InvalidRequestError: 422,
    UpstreamError: 502,
}


async def orchestrator_error_handler(request: Request, exc: OrchestratorError) -> JSONResponse:
    """Render an orchestrator domain error as the JSON body ``HTTPException`` would produce.

    Args:
        request: The failing request (unused; required by the handler signature).
        exc: The domain error raised by an orchestrator.

    Returns:
        A response with the mapped status code and ``{"detail": exc.detail}``.
    """
    # Walk the MRO so a subclass of a mapped error inherits its parent's status; an unmapped
    # error is a programming mistake, so it surfaces as a 500 rather than a guessed client error.
    status_code = next(
        (
            _ORCHESTRATOR_ERROR_STATUS[cls]
            for cls in type(exc).__mro__
            if cls in _ORCHESTRATOR_ERROR_STATUS
        ),
        500,
    )
    return JSONResponse({"detail": exc.detail}, status_code=status_code)


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
    app.state.llm_service = create_llm_service(settings)
    logger.info(
        "LLM service initialised (provider=%s model=%s)",
        settings.llm_provider,
        settings.llm_model or "<none>",
    )
    if settings.debug:
        try:
            await init_db()
            logger.info("Database initialized successfully (dev mode)")
        except Exception as exc:
            logger.warning("Database initialization skipped (DB unavailable): %s", exc)

    # Start Redis PubSub subscriber for WebSocket progress
    try:
        await pubsub_subscriber.start(manager.broadcast_to_task)
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
        version=__version__,
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

    # Register routers — health, WebSocket, and images are intentionally
    # unauthenticated: plain <img src> tags can't send an X-API-Key header,
    # and TMDB poster/backdrop images aren't sensitive data.
    app.include_router(health.router, prefix="/api")
    app.include_router(images.router, prefix="/api")
    app.include_router(tmdb_proxy.router, prefix="/api", dependencies=_auth)
    app.include_router(shows.router, prefix="/api", dependencies=_auth)
    app.include_router(show_episodes.router, prefix="/api", dependencies=_auth)
    app.include_router(show_local_files.router, prefix="/api", dependencies=_auth)
    app.include_router(files.router, prefix="/api", dependencies=_auth)
    app.include_router(orphans.router, prefix="/api", dependencies=_auth)
    app.include_router(tasks.router, prefix="/api", dependencies=_auth)
    app.include_router(config.router, prefix="/api", dependencies=_auth)
    app.include_router(settings_routes.router, prefix="/api", dependencies=_auth)
    app.include_router(admin.router, prefix="/api", dependencies=_auth)
    app.include_router(dashboard.router, prefix="/api", dependencies=_auth)
    app.include_router(watchlist.router, prefix="/api", dependencies=_auth)
    app.include_router(rss_feeds.router, prefix="/api", dependencies=_auth)
    app.include_router(rss_subscriptions.router, prefix="/api", dependencies=_auth)
    app.include_router(rss_publish.router, prefix="/api", dependencies=_auth)
    app.include_router(import_routes.router, prefix="/api", dependencies=_auth)
    app.include_router(export_routes.router, prefix="/api", dependencies=_auth)
    app.include_router(ws_router)

    app.add_exception_handler(OrchestratorError, orchestrator_error_handler)  # type: ignore[arg-type]

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
    # Intentional: container listens on all interfaces, network isolation via Docker.
    uvicorn.run("jidou.main:app", host="0.0.0.0", port=8192, reload=settings.debug)  # nosec B104


if __name__ == "__main__":
    main()  # pragma: no cover
