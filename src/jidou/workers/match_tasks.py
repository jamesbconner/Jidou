"""Celery tasks for parsing downloaded filenames and matching them to shows."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import TaskStatus
from jidou.orchestrators.parse_orchestrator import ParseOrchestrator
from jidou.services.llm_service import LLMService
from jidou.services.progress import (
    TaskCancelledError,
    check_task_cancelled,
    create_task_record,
    emit_progress,
    mark_task_timed_out,
    update_task_status,
)

logger = logging.getLogger(__name__)


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def match_files_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Parse DOWNLOADED filenames and match them to shows.

    Args:
        self: Celery request context for retries.
        dry_run: Simulate without actually updating the DB.

    Returns:
        The celery task ID.
    """
    try:
        return asyncio.run(_match_files(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _match_files(
    celery_task_id: str,
    dry_run: bool = False,
) -> str:
    """Async implementation of the parse/match task."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            task = await create_task_record(
                session, celery_task_id, "match", progress_total=0, dry_run=dry_run
            )
            if task.status in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            }:
                logger.info("Task %s already %s; skipping redelivery", celery_task_id, task.status)
                return celery_task_id

            llm = LLMService(
                provider=settings.llm_provider,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                cache_ttl=settings.llm_cache_ttl,
                timeout=settings.llm_timeout,
            )

            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.RUNNING,
                progress_message="Parsing and matching files...",
            )

            async def on_progress(current: int, total: int, message: str) -> None:
                await check_task_cancelled(session, celery_task_id)
                await update_task_status(
                    session,
                    celery_task_id,
                    TaskStatus.RUNNING,
                    progress_current=current,
                    progress_total=total,
                    progress_message=message,
                )
                await emit_progress(
                    {
                        "celery_task_id": celery_task_id,
                        "type": "progress",
                        "data": {"current": current, "total": total, "message": message},
                    }
                )

            result = await ParseOrchestrator(session, llm).run(
                dry_run=dry_run, on_progress=on_progress
            )

            total_processed = result.files_processed
            completed = await update_task_status(
                session,
                celery_task_id,
                TaskStatus.COMPLETED,
                progress_current=total_processed,
                progress_total=total_processed,
                progress_message=f"Parse complete: {result.files_matched} matched",
                result_summary={
                    "files_processed": result.files_processed,
                    "files_matched": result.files_matched,
                    "files_unmatched": result.files_unmatched,
                    "files_failed": result.files_failed,
                    "dry_run": dry_run,
                },
            )
            if completed is not None and completed.status == TaskStatus.COMPLETED.value:
                await emit_progress(
                    {
                        "celery_task_id": celery_task_id,
                        "type": "complete",
                        "data": {
                            "summary": {
                                "files_matched": result.files_matched,
                                "dry_run": dry_run,
                            }
                        },
                    }
                )

        return celery_task_id

    except TaskCancelledError:
        logger.info("Match task cancelled")
        async with session_factory() as session:
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.CANCELLED,
                progress_message="Task cancelled",
            )
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "cancelled",
                    "data": {},
                }
            )
        return celery_task_id
    except Exception as exc:
        logger.exception("Match task failed")
        async with session_factory() as session:
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.FAILED,
                progress_message=str(exc),
            )
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "error",
                    "data": {"error": str(exc)},
                }
            )
        raise
    finally:
        await engine.dispose()
