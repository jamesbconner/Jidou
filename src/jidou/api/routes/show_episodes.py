"""API routes for a show's episodes: listing, watched state, tracking and file links."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.api.lookups import get_or_404, get_show_or_404
from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.episode import Episode
from jidou.schemas.episode_schema import BackingFile, BulkWatchedRequest, EpisodeList
from jidou.schemas.file_schema import FileRead
from jidou.schemas.show_schema import (
    AssignImportRequest,
    LinkFileRequest,
)
from jidou.services.episode_tracking import clear_episode_tracking, mark_episode_tracked
from jidou.services.episode_watching import clear_episode_watched, mark_episode_watched
from jidou.services.path_transport import decode_path_bytes, decode_path_bytes_for_display
from jidou.services.synthetic_file import (
    SYNTHETIC_IMPORT_SCHEME,
    create_synthetic_import_file,
    is_synthetic_remote_path,
    synthetic_remote_path,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shows", tags=["shows"])


@router.get("/{show_id}/episodes", response_model=list[EpisodeList])
async def list_episodes(
    show_id: int,
    season: int | None = None,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[EpisodeList]:
    """List episodes for a show, optionally filtered by season number.

    Args:
        show_id: Database primary key of the show.
        season: If provided, return only episodes from this season.
        db_session: DB session (injected).

    Returns:
        List of episodes ordered by season and episode number, each including
        ``backing_file_id`` if a DownloadedFile is linked to that episode.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    await get_show_or_404(db_session, show_id)

    ep_stmt = select(Episode).where(Episode.show_id == show_id)
    if season is not None:
        ep_stmt = ep_stmt.where(Episode.season_number == season)
    ep_stmt = ep_stmt.order_by(Episode.season_number, Episode.episode_number)
    episodes = list((await db_session.execute(ep_stmt)).scalars().all())

    # Fetch all DownloadedFiles linked to these episodes in one query.
    episode_ids = [ep.id for ep in episodes]
    files_by_episode: dict[int, list[BackingFile]] = {}
    if episode_ids:
        files_stmt = (
            select(
                DownloadedFile.episode_id,
                DownloadedFile.id,
                DownloadedFile.original_filename,
            )
            .where(
                DownloadedFile.episode_id.in_(episode_ids),
                # Exclude pending synthetic rows so a cancelled Fix Match on an
                # imported episode doesn't flip the chip from Imported → Matched.
                ~DownloadedFile.remote_path.like(f"{SYNTHETIC_IMPORT_SCHEME}%"),
            )
            .order_by(DownloadedFile.id)
        )
        for ep_id, file_id, filename in (await db_session.execute(files_stmt)).all():
            files_by_episode.setdefault(ep_id, []).append(
                BackingFile(id=file_id, filename=filename or "")
            )

    result: list[EpisodeList] = []
    for ep in episodes:
        el = EpisodeList.model_validate(ep, from_attributes=True)
        el.backing_files = files_by_episode.get(ep.id, [])
        result.append(el)
    return result


async def _get_episode_or_404(db_session: AsyncSession, show_id: int, episode_id: int) -> Episode:
    """Fetch an episode scoped to *show_id*, or raise 404.

    Args:
        db_session: DB session (injected).
        show_id: Database primary key of the show.
        episode_id: Database primary key of the episode.

    Returns:
        The matching :class:`Episode` record.

    Raises:
        HTTPException: 404 if the show or episode is not found.
    """
    await get_show_or_404(db_session, show_id)

    return await get_or_404(
        db_session,
        Episode,
        Episode.id == episode_id,
        Episode.show_id == show_id,
        detail="Episode not found",
    )


async def _get_show_episodes_or_404(
    db_session: AsyncSession, show_id: int, season_number: int | None
) -> list[Episode]:
    """Fetch a show's episodes (optionally scoped to one season), or raise 404.

    Args:
        db_session: DB session (injected).
        show_id: Database primary key of the show.
        season_number: If given, only episodes from this season are returned.

    Returns:
        Episodes ordered by season and episode number.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    await get_show_or_404(db_session, show_id)

    ep_stmt = select(Episode).where(Episode.show_id == show_id)
    if season_number is not None:
        ep_stmt = ep_stmt.where(Episode.season_number == season_number)
    ep_stmt = ep_stmt.order_by(Episode.season_number, Episode.episode_number)
    return list((await db_session.execute(ep_stmt)).scalars().all())


@router.post("/{show_id}/episodes/{episode_id}/watched", response_model=EpisodeList)
async def set_episode_watched(
    show_id: int,
    episode_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Episode:
    """Mark a single episode as watched.

    Args:
        show_id: Database primary key of the show.
        episode_id: Database primary key of the episode.
        db_session: DB session (injected).

    Returns:
        The updated :class:`Episode` record.

    Raises:
        HTTPException: 404 if the show or episode is not found.
    """
    ep = await _get_episode_or_404(db_session, show_id, episode_id)
    mark_episode_watched(ep)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(ep)
    return ep


@router.delete("/{show_id}/episodes/{episode_id}/watched", response_model=EpisodeList)
async def clear_episode_watched_route(
    show_id: int,
    episode_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Episode:
    """Clear the watched flag on a single episode.

    Args:
        show_id: Database primary key of the show.
        episode_id: Database primary key of the episode.
        db_session: DB session (injected).

    Returns:
        The updated :class:`Episode` record.

    Raises:
        HTTPException: 404 if the show or episode is not found.
    """
    ep = await _get_episode_or_404(db_session, show_id, episode_id)
    clear_episode_watched(ep)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(ep)
    return ep


@router.post("/{show_id}/episodes/watched", response_model=list[EpisodeList])
async def bulk_set_episodes_watched(
    show_id: int,
    payload: BulkWatchedRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[Episode]:
    """Mark every episode in a show (or one season) as watched.

    Args:
        show_id: Database primary key of the show.
        payload: ``season_number`` scopes the update to one season; omit to
            apply it to the whole show.
        db_session: DB session (injected).

    Returns:
        The updated episodes, ordered by season and episode number.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    episodes = await _get_show_episodes_or_404(db_session, show_id, payload.season_number)

    for ep in episodes:
        mark_episode_watched(ep)
    await db_session.flush()
    await db_session.commit()
    return episodes


@router.delete("/{show_id}/episodes/watched", response_model=list[EpisodeList])
async def bulk_clear_episodes_watched(
    show_id: int,
    payload: BulkWatchedRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[Episode]:
    """Clear the watched flag on every episode in a show (or one season).

    Args:
        show_id: Database primary key of the show.
        payload: ``season_number`` scopes the update to one season; omit to
            apply it to the whole show.
        db_session: DB session (injected).

    Returns:
        The updated episodes, ordered by season and episode number.

    Raises:
        HTTPException: 404 if the show is not found.
    """
    episodes = await _get_show_episodes_or_404(db_session, show_id, payload.season_number)

    for ep in episodes:
        clear_episode_watched(ep)
    await db_session.flush()
    await db_session.commit()
    return episodes


@router.post(
    "/{show_id}/episodes/{episode_id}/begin-rematch",
    response_model=FileRead,
)
async def begin_episode_rematch(
    show_id: int,
    episode_id: int,
    file_id: int | None = Query(default=None),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DownloadedFile:
    """Prepare a downloaded episode's backing file for re-matching.

    Episode tracking is **not** cleared here — it is only cleared once the
    route task successfully completes, so cancelling the re-match modal leaves
    the episode showing as tracked.

    Only valid for episodes backed by a :class:`DownloadedFile`.  Imported
    episodes (tracked via path-import with no backing file) must use
    ``POST /shows/{show_id}/episodes/{episode_id}/assign-import`` instead.

    Args:
        show_id: Database primary key of the show.
        episode_id: Database primary key of the episode.
        file_id: Optional ID of a specific backing file to re-match when the
            episode has multiple tracked files.
        db_session: DB session (injected).

    Returns:
        A ``FileRead`` ready to be passed to the re-match modal.

    Raises:
        HTTPException: 404 if the show, episode, or specified file is not found.
        HTTPException: 422 if the episode is not tracked or has no backing file.
    """
    await get_show_or_404(db_session, show_id)

    ep_stmt = select(Episode).where(Episode.id == episode_id, Episode.show_id == show_id)
    ep = (await db_session.execute(ep_stmt)).scalar_one_or_none()
    if ep is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    if not ep.file_tracked:
        raise HTTPException(status_code=422, detail="Episode is not tracked")

    backing: DownloadedFile | None = None

    if file_id is not None:
        # Caller specified which file to re-match (multiple-file episode).
        specific_stmt = (
            select(DownloadedFile)
            .where(
                DownloadedFile.id == file_id,
                DownloadedFile.episode_id == episode_id,
            )
            .options(
                selectinload(DownloadedFile.show),
                selectinload(DownloadedFile.episode),
            )
        )
        backing = (await db_session.execute(specific_stmt)).scalar_one_or_none()
        if backing is None:
            raise HTTPException(status_code=404, detail="File not found for this episode")
    else:
        # Look for any backing DownloadedFile — handles downloaded and legacy
        # pre-migration episodes where tracked_source is null.
        any_stmt = (
            select(DownloadedFile)
            .where(DownloadedFile.episode_id == episode_id)
            .options(
                selectinload(DownloadedFile.show),
                selectinload(DownloadedFile.episode),
            )
            .limit(1)
        )
        backing = (await db_session.execute(any_stmt)).scalar_one_or_none()

    if backing is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Episode has no backing file. "
                "Use POST /shows/{show_id}/episodes/{episode_id}/assign-import "
                "to reassign imported episode tracking."
            ),
        )

    # Leave status unchanged — resetting to DOWNLOADED would enroll the file
    # in the match orchestrator while the RematchModal is still open, creating
    # a race where auto-match re-links the episode before the user confirms.
    # The user's confirmation (POST /files/{id}/match) sets status=MATCHED,
    # which the route orchestrator picks up to move the file.
    return backing


async def _detach_episode_tracking(db_session: AsyncSession, ep: Episode) -> None:
    """Unlink every ``DownloadedFile`` backing *ep* and clear its tracking fields.

    The single place that can fully unlink an episode regardless of how it's
    tracked — unlike ``PATCH /files/{id}`` (only reaches download-backed
    episodes, one file at a time) or ``assign-import``'s displacement branch
    (only clears an import-tracked episode as a side effect of handing its
    filename to a different episode). Used by both the ``replace`` branch of
    ``link-file`` and the standalone clear-tracking endpoint below.

    Real (non-synthetic) backing files are reset to ``UNMATCHED`` so they
    resurface on the Files page for manual re-triage, mirroring the status
    change the frontend's "Clear assignment" already makes via
    ``PATCH /files/{id}``. Synthetic-import rows are deleted outright rather
    than orphaned: they're pure display markers (see
    ``create_synthetic_import_file``), not real downloaded data, and merely
    clearing ``episode_id`` on one would leave it permanently stuck — still
    keyed to this show, so ``scan-local-files``'s existing-path dedup check
    (by ``show_id``, not ``episode_id``) would hide the file from every
    future scan, and ``create_synthetic_import_file``'s remote_path-keyed
    idempotency would hand back this same stale, still-unlinked row instead
    of creating a fresh one on a later ``link-file`` call. Deleting it lets
    the file be rediscovered at its unchanged on-disk path and re-linked
    with a fresh, correctly-linked row.

    Args:
        db_session: Active async DB session.
        ep: Episode ORM object to detach and clear tracking on, in place.
    """
    backing_stmt = select(DownloadedFile).where(DownloadedFile.episode_id == ep.id)
    for backing_file in (await db_session.execute(backing_stmt)).scalars().all():
        if is_synthetic_remote_path(backing_file.remote_path):
            await db_session.delete(backing_file)
        else:
            backing_file.episode_id = None
            backing_file.matched_by = None
            backing_file.status = FileStatus.UNMATCHED
    clear_episode_tracking(ep)


@router.delete("/{show_id}/episodes/{episode_id}/tracking", response_model=EpisodeList)
async def clear_episode_file_tracking(
    show_id: int,
    episode_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Episode:
    """Unlink an episode from whatever file currently tracks it.

    Works uniformly for download-backed episodes (nulls the backing
    ``DownloadedFile.episode_id``) and import-tracked episodes (nulls the
    synthetic ``DownloadedFile.episode_id`` and the ``Episode`` tracking
    fields) — see ``_detach_episode_tracking``. Gives import-tracked episodes
    a way to be freed that doesn't exist today: ``assign-import`` can only
    clear one as a side effect of handing its filename to a different
    episode, and only when such a filename exists in the show's import pool.

    Args:
        show_id: Database primary key of the show.
        episode_id: Database primary key of the episode.
        db_session: DB session (injected).

    Returns:
        The updated :class:`Episode` record, now untracked.

    Raises:
        HTTPException: 404 if the show or episode is not found.
        HTTPException: 422 if the episode is not currently tracked.
    """
    ep = await _get_episode_or_404(db_session, show_id, episode_id)
    if not ep.file_tracked:
        raise HTTPException(status_code=422, detail="Episode is not tracked")
    await _detach_episode_tracking(db_session, ep)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(ep)
    return ep


@router.post(
    "/{show_id}/episodes/{episode_id}/assign-import",
    status_code=200,
)
async def assign_import_episode(
    show_id: int,
    episode_id: int,
    payload: AssignImportRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, bool]:
    """Reassign an imported episode's tracked filename to a different episode.

    Atomically moves ``payload.filename`` from whichever episode currently
    holds it to ``episode_id``.  Both sides of the transfer are updated in
    the same transaction — no :class:`DownloadedFile` is created and no route
    task is triggered, because the file is already at its final location on
    disk.

    This endpoint handles arbitrary permutations of imported filenames across
    episodes in the same show, including cases where the target episode already
    tracks a different file (the displaced file is simply cleared).

    Args:
        show_id: Database primary key of the show.
        episode_id: Database primary key of the target episode.
        payload: Contains ``filename`` — one of the show's existing tracked
            filenames (taken from any episode's ``tracked_filename`` field).
        db_session: DB session (injected).

    Returns:
        ``{"ok": true}`` on success.

    Raises:
        HTTPException: 404 if the show or target episode is not found.
        HTTPException: 422 if ``payload.filename`` is not currently tracked
            by any episode in this show.
    """
    await get_show_or_404(db_session, show_id)

    target_stmt = select(Episode).where(Episode.id == episode_id, Episode.show_id == show_id)
    target_ep = (await db_session.execute(target_stmt)).scalar_one_or_none()
    if target_ep is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    # Find the import-tracked episode that currently holds this filename.
    # Filenames tracked via 'match' (download-backed) are not in the import pool —
    # moving them would desync the Episode from its DownloadedFile row.
    source_stmt = select(Episode).where(
        Episode.show_id == show_id,
        Episode.tracked_filename == payload.filename,
        Episode.tracked_source == "import",
    )
    source_ep = (await db_session.execute(source_stmt)).scalar_one_or_none()
    if source_ep is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Filename {payload.filename!r} is not in this show's import pool. "
                "Only filenames tracked via path-import can be reassigned here."
            ),
        )

    # Refuse to overwrite a download-backed episode's tracking — that episode's
    # DownloadedFile row would be left inconsistently linked.
    if target_ep.file_tracked and target_ep.tracked_source != "import":
        raise HTTPException(
            status_code=422,
            detail=(
                "Target episode is backed by a downloaded file. "
                "Use POST /shows/{show_id}/episodes/{episode_id}/begin-rematch to reassign it."
            ),
        )

    if source_ep.id != target_ep.id:
        # Capture the filename target currently holds before overwriting it.
        # If target held a different import filename, swap it back to source so it
        # stays in the pool.  If target was untracked (None), source is cleared.
        displaced = target_ep.tracked_filename

        if displaced and displaced != payload.filename:
            mark_episode_tracked(source_ep, displaced, "import")
            await _resync_synthetic_file_episode(
                db_session,
                displaced,
                source_ep.id,
                season_number=source_ep.season_number,
                episode_number=source_ep.episode_number,
            )
        else:
            clear_episode_tracking(source_ep)

    # Assign the filename to the target episode.
    mark_episode_tracked(target_ep, payload.filename, "import")
    await _resync_synthetic_file_episode(
        db_session,
        payload.filename,
        target_ep.id,
        season_number=target_ep.season_number,
        episode_number=target_ep.episode_number,
    )

    await db_session.flush()
    await db_session.commit()
    return {"ok": True}


@router.post(
    "/{show_id}/episodes/{episode_id}/link-file",
    response_model=FileRead,
)
async def link_episode_file(
    show_id: int,
    episode_id: int,
    payload: LinkFileRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DownloadedFile:
    """Manually link an on-disk file path to an episode.

    For files that already sit at their final library location but were never
    downloaded or path-imported by Jidou, so no ``DownloadedFile`` row exists
    yet. Creates a display-only, already-ROUTED record using the same
    ``synthetic-import://`` convention as bulk path-import, and marks the
    episode tracked with ``tracked_source="import"`` — this keeps it in the
    ``assign-import`` reassignment pool and existing "Imported" UI treatment
    rather than introducing a third tracking source.

    To link a file Jidou already knows about (an ``unmatched`` DownloadedFile
    row), use ``PATCH /api/files/{file_id}`` instead.

    Args:
        show_id: Database primary key of the show.
        episode_id: Database primary key of the episode.
        payload: Contains ``path`` — the absolute on-disk path of the file,
            as returned verbatim by ``scan-local-files`` (may be
            percent-encoded via :mod:`~jidou.services.path_transport` if the
            filename contains non-UTF-8 bytes) — and ``replace``: when True
            and the episode is already tracked, whatever currently tracks it
            (a download-backed ``DownloadedFile`` or an import-tracked
            filename) is unlinked first via ``_detach_episode_tracking``,
            instead of raising 422. Handles the "file got moved/consolidated
            into the correct season directory after the episode was already
            tracked from its old location" case that neither ``begin-rematch``
            (only changes which file a fixed row points to, never its path)
            nor ``assign-import`` (can only reassign among already-imported
            filenames) can resolve.
        db_session: DB session (injected).

    Returns:
        The created (or pre-existing) ``DownloadedFile`` record.

    Raises:
        HTTPException: 404 if the show or episode is not found.
        HTTPException: 422 if the episode is already tracked and *replace* is
            False, or *path* does not point to an existing file.
    """
    await get_show_or_404(db_session, show_id)

    # Locked so two concurrent link-file calls targeting the same episode
    # (e.g. a bulk "Confirm All Matched" batch) can't both read
    # file_tracked=False before either commits — the second request blocks
    # here until the first's transaction ends, then sees the now-tracked
    # state and 422s below instead of double-linking.
    ep_stmt = (
        select(Episode)
        .where(Episode.id == episode_id, Episode.show_id == show_id)
        .with_for_update()
    )
    ep = (await db_session.execute(ep_stmt)).scalar_one_or_none()
    if ep is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    if ep.file_tracked:
        if not payload.replace:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Episode is already tracked. Use begin-rematch or assign-import "
                    "to reassign it, or pass replace=true to overwrite."
                ),
            )
        await _detach_episode_tracking(db_session, ep)

    # payload.path is the (possibly percent-encoded, see path_transport)
    # value echoed back verbatim from a scan-local-files response; decode it
    # back to the exact on-disk bytes before touching the filesystem. Every
    # other use of the path below (DB storage, logging) keeps the encoded
    # form, since that's what's always safe to store/return as JSON.
    if not Path(decode_path_bytes(payload.path)).is_file():
        raise HTTPException(
            status_code=422,
            detail=f"No file exists at path: {decode_path_bytes_for_display(payload.path)}",
        )

    mark_episode_tracked(ep, payload.path, "import")
    await create_synthetic_import_file(
        db_session,
        show_id,
        episode_id,
        payload.path,
        parsed_season=ep.season_number,
        parsed_episode=ep.episode_number,
    )
    await db_session.commit()

    remote_path = synthetic_remote_path(payload.path)
    refreshed = (
        await db_session.execute(
            select(DownloadedFile)
            .where(DownloadedFile.remote_path == remote_path)
            .options(selectinload(DownloadedFile.show), selectinload(DownloadedFile.episode))
        )
    ).scalar_one()
    logger.info(
        "Linked file path=%r to episode id=%d (show id=%d)", payload.path, episode_id, show_id
    )
    return refreshed


async def _resync_synthetic_file_episode(
    db_session: AsyncSession,
    filename: str,
    episode_id: int,
    *,
    season_number: int,
    episode_number: int,
) -> None:
    """Repoint a path-imported file's synthetic DownloadedFile at its new episode.

    Path-import creates a display-only ``DownloadedFile(status=ROUTED)`` row
    for each tracked filename (see ``PathImportOrchestrator``), keyed by a
    ``synthetic-import://<filename>`` ``remote_path``. ``assign_import_episode``
    only moved ``Episode.tracked_filename``/``tracked_source`` between rows —
    without this, the synthetic file's ``episode_id`` would still point at
    whichever episode held the filename before the reassignment, so the Files
    page would list it under the wrong (or no longer tracked) episode.

    ``parsed_season``/``parsed_episode`` must move with ``episode_id`` too: a
    later show-rematch's orphan-relink pass (see
    ``ShowRematchOrchestrator._restore_tracking_and_relink``) keys its lookup
    on those fields, not ``episode_id`` — leaving them stale here would make a
    future rematch silently relink this file to the wrong episode instead of
    correctly orphaning it.

    A no-op if no such row exists yet (e.g. data imported before this
    convention existed).

    Args:
        db_session: DB session (injected).
        filename: The raw path used as both ``Episode.tracked_filename`` and
            the synthetic file's ``remote_path`` suffix.
        episode_id: The episode the file should now be linked to.
        season_number: The new episode's season number.
        episode_number: The new episode's episode number.
    """
    stmt = select(DownloadedFile).where(
        DownloadedFile.remote_path == synthetic_remote_path(filename)
    )
    synthetic_file = (await db_session.execute(stmt)).scalar_one_or_none()
    if synthetic_file is not None:
        synthetic_file.episode_id = episode_id
        synthetic_file.parsed_season = season_number
        synthetic_file.parsed_episode = episode_number
