"""Redis PubSub subscriber that bridges task progress to WebSocket clients."""

import asyncio
import contextlib
import json
import logging

import redis.asyncio as aioredis

from jidou.api.websocket.task_progress import manager
from jidou.config import settings

logger = logging.getLogger(__name__)

REDIS_CHANNEL = "task_progress"


class PubSubSubscriber:
    """Background subscriber that reads Redis PubSub and forwards to WebSocket."""

    def __init__(self) -> None:
        """Initialize the subscriber."""
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start the subscriber loop.

        The listen task is stored internally so ``stop()`` can cancel it
        cleanly on shutdown.
        """
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(REDIS_CHANNEL)
        self._running = True
        self._listen_task = asyncio.create_task(self._listen(), name="pubsub-listen")
        logger.info("PubSub subscriber started on channel %s", REDIS_CHANNEL)

    async def stop(self) -> None:
        """Stop the subscriber loop and cancel the background listen task."""
        self._running = False
        if self._listen_task is not None:
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task
            self._listen_task = None
        if self._pubsub is not None:
            await self._pubsub.unsubscribe(REDIS_CHANNEL)
        if self._redis is not None:
            await self._redis.aclose()
        logger.info("PubSub subscriber stopped")

    async def _listen(self) -> None:
        """Blockingly listen for messages while running."""
        if self._pubsub is None:
            logger.error("PubSub not initialized")
            return
        try:
            while self._running:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    continue
                if message["type"] != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON in PubSub message: %s", message["data"])
                    continue

                celery_task_id = data.get("celery_task_id")
                if celery_task_id is None:
                    logger.warning("PubSub message missing celery_task_id")
                    continue

                await manager.broadcast_to_task(celery_task_id, data)
        except Exception:
            logger.exception("PubSub subscriber loop failed")


# Module-level instance for lifespan injection
pubsub_subscriber = PubSubSubscriber()
