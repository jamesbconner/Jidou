"""API routes that scan and link local files for a show."""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jidou.api.dependencies import get_llm_service
from jidou.api.lookups import get_show_or_404
from jidou.database import get_session
from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.schemas.file_schema import EpisodeBrief, FileRead
from jidou.schemas.show_schema import (
    LinkMovieFileRequest,
    ScannedFileMatch,
)
from jidou.services.episode_file_matching import match_entry_to_episode
from jidou.services.file_reconciliation import reconcile_local_file_existence
from jidou.services.llm_service import LLMService
from jidou.services.path_parser import path_comparison_key, scan_show_directory
from jidou.services.path_transport import decode_path_bytes, decode_path_bytes_for_display
from jidou.services.synthetic_file import create_synthetic_import_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shows", tags=["shows"])


@router.post(
    "/{show_id}/scan-local-files",
    response_model=list[ScannedFileMatch],
)
async def scan_show_local_files(
    show_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
    llm: LLMService = Depends(get_llm_service),  # noqa: B008
) -> list[ScannedFileMatch]:
    """List and auto-match media files found under a show's own local directory.

    An alternative to bulk text-file import for episodes whose files are
    already sitting at their final on-disk location — e.g. picking up
    stragglers a prior import missed, or files that predate Jidou entirely.
    The same matching pipeline bulk path-import uses (regex heuristics,
    episode_group remap, LLM fallback — see
    :func:`~jidou.services.episode_file_matching.match_entry_to_episode`)
    resolves each file to a proposed episode.

    Side effect: before building proposals, this also reconciles the show's
    existing ``downloaded_files`` rows against disk — any row whose
    ``local_path`` no longer exists (renamed/moved/deleted outside the app)
    is flagged ``missing``, and any previously-flagged row found present
    again is restored — see
    :func:`~jidou.services.file_reconciliation.reconcile_local_file_existence`.
    Aside from that status housekeeping, matching itself is read-only:
    nothing is written until a proposal is confirmed via
    ``link-file``.

    Files whose path matches an already-recorded ``DownloadedFile`` for this
    show (a prior import or download — compared via
    :func:`~jidou.services.path_parser.path_comparison_key`, since a prior
    bulk-import path string and this scan's live-filesystem path string can
    differ in format while referring to the same file) are skipped entirely.
    Everything else is returned with a status:

    - ``matched``: proposed episode is untracked and not claimed by an
      earlier row in this same scan; ready to confirm via
      ``POST /shows/{show_id}/episodes/{episode_id}/link-file``.
    - ``unmatched``: no episode could be resolved.
    - ``conflict``: the proposed episode is already tracked by a different
      file, or was already claimed by an earlier row in this scan (e.g. a
      duplicate file) — confirming needs either picking a different episode,
      or passing ``replace=true`` to ``link-file`` to unlink whatever
      currently tracks the proposed episode first.

    Args:
        show_id: Database primary key of the show.
        db_session: DB session (injected).
        llm: LLM service (injected) — used as a fallback when regex parsing
            can't resolve a filename; matching still works without one.

    Returns:
        One :class:`ScannedFileMatch` per file found, sorted by path.

    Raises:
        HTTPException: 404 if the show is not found.
        HTTPException: 422 if the show has no local path configured.
    """
    show = await get_show_or_404(db_session, show_id)
    if not show.local_path:
        raise HTTPException(status_code=422, detail="Show has no local path configured")

    await reconcile_local_file_existence(db_session, show_id)

    # Filesystem I/O is synchronous — run it off the event loop so a large or
    # slow-mounted show directory doesn't stall every other concurrent request.
    entries = await asyncio.to_thread(scan_show_directory, show.local_path)

    existing_paths_stmt = select(DownloadedFile.local_path).where(DownloadedFile.show_id == show_id)
    existing_keys = {
        path_comparison_key(p)
        for (p,) in (await db_session.execute(existing_paths_stmt)).all()
        if p
    }

    results: list[ScannedFileMatch] = []
    # Tracks episodes already claimed by an earlier row in this same scan, so
    # two files resolving to the same untracked episode (e.g. a duplicate)
    # are never both reported "matched" — only the first (by sort order).
    claimed_episode_ids: set[int] = set()
    for entry in entries:
        if path_comparison_key(entry.raw_path) in existing_keys:
            continue

        ep, season, episode_number = await match_entry_to_episode(
            db_session, llm, show_id, show.title, entry, show.episode_group_map
        )

        if ep is None:
            status: Literal["matched", "unmatched", "conflict"] = "unmatched"
        elif ep.file_tracked or ep.id in claimed_episode_ids:
            status = "conflict"
        else:
            status = "matched"
            claimed_episode_ids.add(ep.id)

        results.append(
            ScannedFileMatch(
                path=entry.raw_path,
                # Display-only: decode_path_bytes_for_display is lossy (any
                # non-UTF-8 byte becomes U+FFFD) so it reads naturally, unlike
                # `path` above which stays byte-exact for the confirm/link
                # round trip — see path_transport.py.
                filename=Path(decode_path_bytes_for_display(entry.raw_path)).name,
                season=season,
                episode_number=episode_number,
                episode=EpisodeBrief.model_validate(ep) if ep is not None else None,
                status=status,
            )
        )

    return results


@router.post(
    "/{show_id}/scan-local-movie-file",
    response_model=list[ScannedFileMatch],
)
async def scan_show_local_movie_file(
    show_id: int,
    replace: bool = Query(
        default=False,
        description=(
            "When True, files are 'matched' even if this movie already has a "
            "linked file (the caller intends to replace it via link-movie-file "
            "with replace=True), instead of coming back 'conflict'."
        ),
    ),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ScannedFileMatch]:
    """List media files found directly under a movie's local directory.

    Movie counterpart to ``scan-local-files``: a movie has no ``Episode``
    rows to resolve a file against, so there is nothing to match — every
    file found directly under ``show.local_path`` that isn't already linked
    to some show is ``matched`` (the user picks the right one by filename
    via the "Link" button), or ``conflict`` if this movie already has a
    linked file and *replace* is False. ``unmatched`` never occurs here, and
    ``season``/``episode_number``/``episode`` are always null. Read-only:
    nothing is written. Confirm a proposed match via
    ``POST /shows/{show_id}/link-movie-file``.

    ``show.local_path`` defaults to the shared movies root (see
    :func:`~jidou.services.path_resolution.resolve_show_local_path`), not a
    directory exclusive to this movie, so the scan is non-recursive (top
    level only), excludes any file already linked to *any* show (not just
    this one), and — unlike the old one-candidate-per-scan behavior — marks
    every remaining untracked file as ``matched`` rather than just the
    first: a flat shared root routinely surfaces several other untracked
    titles in the same scan, and picking only the first would make it
    impossible to link anything but whichever title happens to sort first.

    Args:
        show_id: Database primary key of the show.
        replace: See the parameter description above.
        db_session: DB session (injected).

    Returns:
        One :class:`ScannedFileMatch` per file found, sorted by path.

    Raises:
        HTTPException: 404 if the show is not found.
        HTTPException: 422 if the show is not a movie, or has no local path
            configured.
    """
    show = await get_show_or_404(db_session, show_id)
    if (show.content_type or show.media_type) != "movie":
        raise HTTPException(
            status_code=422,
            detail="This endpoint is for movies only; use scan-local-files instead",
        )
    if not show.local_path:
        raise HTTPException(status_code=422, detail="Show has no local path configured")

    # Filesystem I/O is synchronous — run it off the event loop so a large or
    # slow-mounted show directory doesn't stall every other concurrent request.
    # recursive=False: local_path is typically the shared movies root, not a
    # directory exclusive to this movie, so descending into subdirectories
    # would surface other movies' (and their own subfolders') files too.
    entries = await asyncio.to_thread(scan_show_directory, show.local_path, recursive=False)

    # Every file already linked to ANY show (not just this one) is excluded —
    # local_path is commonly shared across every movie, so scoping this check
    # to show_id alone would offer up every other already-tracked movie in
    # the shared root as a false candidate.
    linked_paths_stmt = select(DownloadedFile.show_id, DownloadedFile.local_path).where(
        DownloadedFile.local_path.is_not(None)
    )
    linked_to_this_show: set[str] = set()
    linked_to_other_show: set[str] = set()
    for linked_show_id, path in (await db_session.execute(linked_paths_stmt)).all():
        key = path_comparison_key(path)
        (linked_to_this_show if linked_show_id == show_id else linked_to_other_show).add(key)

    # Any already-linked file at all means this movie is already tracked —
    # unlike episodes, there's no per-file slot to disambiguate against, so
    # every remaining candidate is blocked (unless replace=True, meaning the
    # caller intends to swap out the existing link) until it's cleared. When
    # this movie has no link yet, every remaining candidate is "matched"
    # (not just the first) -- local_path is commonly shared across every
    # movie, so a flat library legitimately surfaces multiple other
    # untracked titles in the same scan; the user picks the right one by
    # filename via the "Link" button.
    already_linked = bool(linked_to_this_show) and not replace

    results: list[ScannedFileMatch] = []
    for entry in entries:
        key = path_comparison_key(entry.raw_path)
        if key in linked_to_this_show or key in linked_to_other_show:
            continue

        status: Literal["matched", "unmatched", "conflict"] = (
            "conflict" if already_linked else "matched"
        )

        results.append(
            ScannedFileMatch(
                path=entry.raw_path,
                filename=Path(decode_path_bytes_for_display(entry.raw_path)).name,
                season=None,
                episode_number=None,
                episode=None,
                status=status,
            )
        )

    return results


@router.post(
    "/{show_id}/link-movie-file",
    response_model=FileRead,
)
async def link_movie_file(
    show_id: int,
    payload: LinkMovieFileRequest,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DownloadedFile:
    """Manually link an on-disk file path to a movie.

    Movie counterpart to ``episodes/{episode_id}/link-file``: a movie has no
    ``Episode`` row to attach tracking state to, so "already tracked" here
    means the show already has any linked ``DownloadedFile`` row, and the
    resulting synthetic record's ``episode_id`` is left ``NULL``.

    Args:
        show_id: Database primary key of the show.
        payload: Contains ``path`` — the absolute on-disk path of the file,
            as returned verbatim by ``scan-local-movie-file`` (or typed
            directly by the user) — and ``replace``: when True and the movie
            already has a linked file, that file is unlinked (``show_id``,
            ``episode_id``, ``matched_by`` cleared — the row itself is left
            in place, same as the generic ``PATCH /files/{id}`` correction
            path) before the new one is linked, instead of raising 422.
        db_session: DB session (injected).

    A pre-existing ``DownloadedFile`` already at this exact path (e.g. one
    orphaned by an earlier ``replace``) is re-linked to this show rather
    than left untouched, since ``remote_path``-keyed idempotency would
    otherwise silently no-op and leave the movie unlinked.

    Returns:
        The created, re-linked, or pre-existing ``DownloadedFile`` record.

    Raises:
        HTTPException: 404 if the show is not found.
        HTTPException: 422 if the show is not a movie, has no local path
            configured, already has a linked file and *replace* is False,
            *path* does not point to an existing file, or *path* is already
            linked to a different show.
    """
    # Locked so two concurrent link-movie-file calls targeting the same show
    # can't both read "no linked file yet" before either commit lands.
    show = await get_show_or_404(db_session, show_id, for_update=True)
    if (show.content_type or show.media_type) != "movie":
        raise HTTPException(status_code=422, detail="This endpoint is for movies only")
    if not show.local_path:
        raise HTTPException(status_code=422, detail="Show has no local path configured")

    existing_stmt = select(DownloadedFile).where(DownloadedFile.show_id == show_id)
    existing_files = list((await db_session.execute(existing_stmt)).scalars().all())
    if existing_files:
        if not payload.replace:
            raise HTTPException(
                status_code=422,
                detail="Movie already has a linked file. Unlink it before linking a new one.",
            )
        for existing_file in existing_files:
            existing_file.show_id = None
            existing_file.episode_id = None
            existing_file.matched_by = None
        await db_session.flush()

    if not Path(decode_path_bytes(payload.path)).is_file():
        raise HTTPException(
            status_code=422,
            detail=f"No file exists at path: {decode_path_bytes_for_display(payload.path)}",
        )

    # Look up every DownloadedFile already sitting at this exact on-disk path
    # -- by local_path (path_comparison_key, same format-agnostic comparison
    # scan-local-movie-file uses), not just a synthetic-import remote_path
    # match. A file already tracked by another show via the normal SFTP
    # pipeline (a real remote_path, not synthetic-import://) must be
    # rejected too, or a manual path entry would create a second row for
    # the same on-disk file and let two shows claim it simultaneously.
    target_key = path_comparison_key(payload.path)
    local_path_matches_stmt = select(DownloadedFile).where(DownloadedFile.local_path.is_not(None))
    matches = [
        f
        for f in (await db_session.execute(local_path_matches_stmt)).scalars().all()
        if f.local_path is not None and path_comparison_key(f.local_path) == target_key
    ]

    conflict = next((f for f in matches if f.show_id not in (None, show_id)), None)
    if conflict is not None:
        raise HTTPException(
            status_code=422,
            detail="This file is already linked to a different show.",
        )

    # create_synthetic_import_file is keyed on remote_path alone, so it's a
    # silent no-op (returns the existing row unchanged) when one already
    # exists for this exact path -- including a row that was orphaned by an
    # earlier replace above (show_id cleared). Without this check, re-linking
    # a previously-replaced-out path (or the very path this movie was just
    # unlinked from) would report success while leaving the movie unlinked,
    # and that row would stay permanently un-relinkable since a null show_id
    # sorts as "linked to some other show" for scan-local-movie-file too.
    synthetic_remote_path = f"synthetic-import://{payload.path}"
    orphaned_synthetic = next(
        (f for f in matches if f.remote_path == synthetic_remote_path and f.show_id is None),
        None,
    )
    if orphaned_synthetic is not None:
        orphaned_synthetic.show_id = show_id
        orphaned_synthetic.episode_id = None
        orphaned_synthetic.matched_by = None
        orphaned_synthetic.status = FileStatus.ROUTED
    else:
        await create_synthetic_import_file(db_session, show_id, None, payload.path)
    await db_session.commit()

    refreshed = (
        await db_session.execute(
            select(DownloadedFile)
            .where(DownloadedFile.remote_path == synthetic_remote_path)
            .options(selectinload(DownloadedFile.show), selectinload(DownloadedFile.episode))
        )
    ).scalar_one()
    logger.info("Linked file path=%r to movie show id=%d", payload.path, show_id)
    return refreshed
