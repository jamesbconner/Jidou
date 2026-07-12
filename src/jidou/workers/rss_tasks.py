"""Celery tasks for RSS config import and publish operations."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.orchestrators.rss_import_orchestrator import RssImportOrchestrator
from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator
from jidou.services.progress import mark_task_timed_out
from jidou.services.sftp_service import SFTPService
from jidou.workers._harness import EventFn, ProgressFn, WorkflowResult, run_task_workflow

logger = logging.getLogger(__name__)


def _build_sftp() -> SFTPService:
    """Instantiate SFTPService from application settings."""
    return SFTPService(
        host=settings.sftp_host or "",
        port=settings.sftp_port,
        username=settings.sftp_username,
        password=settings.sftp_password,
        key_path=settings.sftp_key_path,
        known_hosts=None,
        max_workers=settings.sftp_max_workers,
        max_retries=settings.sftp_max_retries,
        retry_delay=settings.sftp_retry_delay,
    )


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def rss_import_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Download the remote YaRSS2 config and sync it into the database.

    Args:
        self: Celery request context.
        dry_run: Parse without writing to the database.

    Returns:
        The Celery task ID.
    """
    try:
        return asyncio.run(_rss_import(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _rss_import(celery_task_id: str, dry_run: bool) -> str:
    """Async implementation of the RSS import task."""

    async def _work(
        session: AsyncSession, on_progress: ProgressFn, on_event: EventFn
    ) -> WorkflowResult:
        sftp = _build_sftp()
        orchestrator = RssImportOrchestrator(
            session=session,
            sftp=sftp,
            remote_path=settings.rss_config_remote_path or "",
            dry_run=dry_run,
            on_event=on_event,
        )

        import_result = await orchestrator.run()

        if import_result.errors:
            error_summary = "; ".join(import_result.errors)
            return WorkflowResult(
                progress_current=0,
                progress_total=0,
                message=f"Import failed: {error_summary}",
                result_summary={"errors": import_result.errors, "dry_run": dry_run},
                errors=import_result.errors,
            )

        summary: dict[str, object] = {
            "feeds_created": import_result.feeds_created,
            "feeds_updated": import_result.feeds_updated,
            "subscriptions_created": import_result.subscriptions_created,
            "subscriptions_updated": import_result.subscriptions_updated,
            "subscriptions_remote_deleted": import_result.subscriptions_remote_deleted,
            "shows_linked": import_result.shows_linked,
            "snapshot_id": import_result.snapshot_id,
            "errors": import_result.errors,
            "dry_run": dry_run,
        }
        return WorkflowResult(
            progress_current=0,
            progress_total=0,
            message=(
                f"Done — {import_result.feeds_created} feeds created, "
                f"{import_result.subscriptions_created} subscriptions created, "
                f"{import_result.subscriptions_updated} updated"
            ),
            result_summary=summary,
        )

    return await run_task_workflow(
        celery_task_id,
        "rss_import",
        _work,
        progress_total=0,
        dry_run=dry_run,
        running_message="Downloading RSS config…",
    )


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def rss_publish_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Publish the Jidou RSS config back to the remote YaRSS2 config file.

    Args:
        self: Celery request context.
        dry_run: Plan the publish without uploading.

    Returns:
        The Celery task ID.
    """
    try:
        return asyncio.run(_rss_publish(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _rss_publish(celery_task_id: str, dry_run: bool) -> str:
    """Async implementation of the RSS publish task."""

    async def _work(
        session: AsyncSession, on_progress: ProgressFn, on_event: EventFn
    ) -> WorkflowResult:
        sftp = _build_sftp()
        orchestrator = RssPublishOrchestrator(
            session=session,
            sftp=sftp,
            remote_path=settings.rss_config_remote_path or "",
            dry_run=dry_run,
            on_event=on_event,
            deluge_stop_command=settings.deluge_stop_command,
            deluge_restart_command=settings.deluge_restart_command,
        )

        publish_result = await orchestrator.run()

        if publish_result.errors:
            error_summary = "; ".join(publish_result.errors)
            return WorkflowResult(
                progress_current=0,
                progress_total=0,
                message=f"Publish failed: {error_summary}",
                result_summary={"errors": publish_result.errors, "dry_run": dry_run},
                errors=publish_result.errors,
            )

        summary: dict[str, object] = {
            "feeds_published": publish_result.feeds_published,
            "subscriptions_published": publish_result.subscriptions_published,
            "new_keys_assigned": publish_result.new_keys_assigned,
            "snapshot_id": publish_result.snapshot_id,
            "backup_path": publish_result.backup_path,
            "dry_run": dry_run,
        }
        return WorkflowResult(
            progress_current=0,
            progress_total=0,
            message=(
                f"Done — {publish_result.subscriptions_published} subscriptions published, "
                f"{publish_result.new_keys_assigned} new keys assigned"
            ),
            result_summary=summary,
        )

    return await run_task_workflow(
        celery_task_id,
        "rss_publish",
        _work,
        progress_total=0,
        dry_run=dry_run,
        running_message="Publishing RSS config…",
    )
