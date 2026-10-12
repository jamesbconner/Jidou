"""Redis PubSub subscriber that bridges task progress to WebSocket clients."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis

from jidou.config import settings
from jidou.services.redis_conn import TASK_PROGRESS_CHANNEL

logger = logging.getLogger(__name__)

# Delivers a decoded progress message to the clients of one task. Injected by
# the application so this service does not import the API layer above it.
Broadcast = Callable[[str, dict[str, Any]], Awaitable[None]]


class PubSubSubscriber:
    """Background subscriber that reads Redis PubSub and forwards to WebSocket."""

    def __init__(self) -> None:
        """Initialize the subscriber."""
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._broadcast: Broadcast | None = None
        self._running = False

    async def start(self, broadcast: Broadcast) -> None:
        """Start the subscriber loop.

        The listen task is stored internally so ``stop()`` can cancel it
        cleanly on shutdown.

        Args:
            broadcast: Async callback ``(celery_task_id, payload)`` invoked for
                every valid progress message.
        """
        self._broadcast = broadcast
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(TASK_PROGRESS_CHANNEL)
        self._running = True
        self._listen_task = asyncio.create_task(self._listen(), name="pubsub-listen")
        logger.info("PubSub subscriber started on channel %s", TASK_PROGRESS_CHANNEL)

    async def stop(self) -> None:
        """Stop the subscriber loop and cancel the background listen task."""
        self._running = False
        if self._listen_task is not None:
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task
            self._listen_task = None
        if self._pubsub is not None:
            await self._pubsub.unsubscribe(TASK_PROGRESS_CHANNEL)
        if self._redis is not None:
            await self._redis.aclose()
        logger.info("PubSub subscriber stopped")

    async def _listen(self) -> None:
        """Blockingly listen for messages while running.

        The outer loop ensures that an unexpected exception does not kill the
        subscriber permanently — after logging the error we reconnect and
        continue listening.
        """
        if self._redis is None or self._pubsub is None:
            logger.error("PubSub not initialized")
            return
        pubsub = self._pubsub

        while self._running:
            try:
                while self._running:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    await self._handle_message(message)
            except asyncio.CancelledError:
                logger.info("PubSub subscriber loop cancelled")
                raise
            except Exception:
                logger.exception("PubSub subscriber loop failed — retrying in 5 seconds")
                await self._recover(pubsub)

    @staticmethod
    async def _recover(pubsub: aioredis.client.PubSub) -> None:
        """Back off for 5 seconds, then re-subscribe so the listen loop can resume.

        A failed re-subscribe is logged, not raised: the next loop iteration
        will fail again and retry, which keeps the subscriber alive.

        Args:
            pubsub: The PubSub connection to re-subscribe.
        """
        await asyncio.sleep(5)
        try:
            await pubsub.subscribe(TASK_PROGRESS_CHANNEL)
        except Exception:
            logger.exception("Failed to re-subscribe to Redis channel")

    async def _handle_message(self, message: dict[str, Any] | None) -> None:
        """Parse one PubSub message and forward it to the broadcast callback.

        Malformed or irrelevant messages are logged/skipped, never raised, so a
        single bad payload cannot interrupt the listen loop.

        Args:
            message: Raw message from ``get_message`` (``None`` on timeout).
        """
        if message is None or message["type"] != "message":
            return

        try:
            data = json.loads(message["data"])
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in PubSub message: %s", message["data"])
            return

        celery_task_id = data.get("celery_task_id")
        if celery_task_id is None:
            logger.warning("PubSub message missing celery_task_id")
            return

        if self._broadcast is None:
            logger.error("PubSub broadcast callback not set")
            return
        await self._broadcast(celery_task_id, data)


# Module-level instance for lifespan injection
pubsub_subscriber = PubSubSubscriber()
