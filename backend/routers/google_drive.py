"""
Google Drive connector — OAuth + file ingestion endpoints.

Endpoints
---------
GET  /api/google-drive/connect       Start OAuth: returns the Google consent URL.
GET  /api/google-drive/callback      OAuth callback: stores tokens, redirects to UI.
GET  /api/google-drive/status        Is this user connected? Returns {connected, email}.
POST /api/google-drive/ingest        Ingest the files the user picked via Google Picker.
DELETE /api/google-drive/disconnect  Wipe stored tokens.

The frontend opens the Google Picker, which returns a list of selected file
ids + mime types. The frontend POSTs that list to /ingest; we queue one
Celery task per file. Each task downloads from Drive (using the stored
refresh token to mint an access token if needed) then runs the existing
ingestion pipeline. Documents show up in the sidebar with the same
processing-stage indicator as direct uploads.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.logger import logger
from app.settings import settings
from auth.keycloak_auth import get_current_user_keycloak
from orgs.dependencies import require_uploader  # ingestion = admin/system_owner
from clients.google_drive_composio import (
    GoogleDriveComposioClient,
    GoogleDriveError,
    get_google_drive_client,
)
from services.ingestion_service import get_ingestion_service
from tasks.ingestion_tasks import discover_drive_files_task, process_drive_file_task
from utils.file_utils import get_file_extension


router = APIRouter(prefix="/google-drive", tags=["google-drive"])


def _client(current_user: dict) -> GoogleDriveComposioClient:
    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User missing id")
    try:
        return get_google_drive_client(user_id)
    except GoogleDriveError as e:
        raise HTTPException(status_code=503, detail=str(e))


async def _require_connected(current_user: dict) -> GoogleDriveComposioClient:
    client = _client(current_user)
    status = await asyncio.to_thread(client.connection_status)
    if not status.get("connected"):
        raise HTTPException(status_code=400, detail="Google Drive is not connected. Hit /connect first.")
    return client


# ---------------------------------------------------------------------------
# 1. Connect — returns the Composio-hosted OAuth URL (no tokens on our side)
# ---------------------------------------------------------------------------

class ConnectRequest(BaseModel):
    # Where Composio redirects the browser after consent completes. The
    # frontend passes `${origin}/oauth-callback`.
    callback_url: Optional[str] = Field(default=None)


@router.post("/connect")
async def connect(
    body: ConnectRequest,
    current_user: dict = Depends(require_uploader),
) -> Dict[str, Any]:
    """Start the Composio-hosted Google OAuth flow; returns the auth URL the
    frontend opens. Composio owns the OAuth + token refresh — we store nothing.
    The frontend polls /status until it flips to connected."""
    client = _client(current_user)
    try:
        result = await asyncio.to_thread(client.initiate_connection, body.callback_url)
    except GoogleDriveError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # pragma: no cover - Composio surface
        logger.error(f"Google Drive connect failed: {e}")
        raise HTTPException(status_code=502, detail=f"Composio error: {e}")

    if not result.get("auth_url"):
        raise HTTPException(status_code=502, detail="Composio did not return an auth URL")
    logger.info(f"🔗 Drive connect URL issued for user={current_user.get('id','')[:8]}…")
    return {"success": True, "auth_url": result["auth_url"], "connection_id": result.get("connection_id")}


# ---------------------------------------------------------------------------
# 2. Status — is this user connected?
# ---------------------------------------------------------------------------

@router.get("/status")
async def status_endpoint(
    current_user: dict = Depends(require_uploader),
) -> Dict[str, Any]:
    client = _client(current_user)
    try:
        status = await asyncio.to_thread(client.connection_status)
    except Exception as e:
        logger.warning(f"Drive status check failed: {e}")
        return {"connected": False, "status": None, "needs_reconnect": False}
    return {
        "connected": bool(status.get("connected")),
        "status": status.get("status"),
        "connection_id": status.get("connection_id"),
        "needs_reconnect": False,
    }


# ---------------------------------------------------------------------------
# 4. Ingest — frontend hands us the file list Picker returned
# ---------------------------------------------------------------------------

class DrivePickedFile(BaseModel):
    """One file as returned by Google Picker."""
    id: str = Field(..., description="Google Drive file id")
    name: str = Field(..., description="File name as shown in Drive")
    mime_type: str = Field(..., description="MIME type Picker reported")
    size: Optional[int] = Field(default=None, description="Size in bytes if known")


class DriveIngestRequest(BaseModel):
    folder_name: str = Field(default="Google Drive", description="Folder to file ingested docs under")
    files: List[DrivePickedFile] = Field(..., min_length=1)


@router.post("/ingest")
async def ingest(
    body: DriveIngestRequest,
    current_user: dict = Depends(require_uploader),
) -> Dict[str, Any]:
    """Queue one Celery task per picked file. Returns the doc ids it created.

    Mirrors the regular /upload flow: we create document rows in PostgreSQL
    with status='processing' first, then fan out per-file Celery tasks. The
    UI's existing IngestionPipeline component picks up the stages as the
    documents move through the pipeline.
    """
    user_id = current_user.get("id")
    organization_id = current_user.get("organization_id")
    if not user_id or not organization_id:
        raise HTTPException(status_code=400, detail="User missing id or organization_id")

    # Ensure the user has an ACTIVE Composio Drive connection
    await _require_connected(current_user)

    folder_name = body.folder_name.strip() or "Google Drive"
    ingestion_service = get_ingestion_service()

    document_ids: List[str] = []
    for f in body.files:
        document_id = str(uuid.uuid4())
        extension = get_file_extension(f.name)
        file_key = f"{organization_id}/{folder_name}/{document_id}{extension}"

        await ingestion_service._create_document_with_status(
            file_name=f.name,
            folder_name=folder_name,
            file_key=file_key,
            file_size_mb=(f.size or 0) / (1024 * 1024) if f.size else 0.0,
            user_id=user_id,
            organization_id=organization_id,
            additional_metadata={
                "id": document_id,
                "source": "google_drive",
                "drive_file_id": f.id,
                "drive_mime_type": f.mime_type,
                "drive_file_name": f.name,
            },
        )

        process_drive_file_task.delay(
            document_id=document_id,
            drive_file_id=f.id,
            drive_mime_type=f.mime_type,
            file_name=f.name,
            file_key=file_key,
            folder_name=folder_name,
            user_id=user_id,
            organization_id=organization_id,
        )
        document_ids.append(document_id)

    logger.info(
        f"📥 Drive ingest queued: user={user_id[:8]}… {len(document_ids)} files → folder={folder_name}"
    )
    return {
        "success": True,
        "document_ids": document_ids,
        "folder_name": folder_name,
        "queued_count": len(document_ids),
    }


# ---------------------------------------------------------------------------
# 5. List files — paginated, backs our own custom file picker modal
# ---------------------------------------------------------------------------

@router.get("/files")
async def list_files_paged(
    page_token: Optional[str] = None,
    page_size: int = 50,
    search: Optional[str] = None,
    current_user: dict = Depends(require_uploader),
) -> Dict[str, Any]:
    """Paginated file list for the in-app file picker.

    Returns one page at a time so the picker stays responsive on big drives.
    `page_token` from a previous response → next page. `search` does a
    substring name match server-side via Drive's `name contains '...'`.
    """
    client = await _require_connected(current_user)
    try:
        return await client.list_files_page(
            page_token=page_token,
            page_size=page_size,
            search=search,
        )
    except GoogleDriveError as e:
        raise HTTPException(status_code=502, detail=f"Drive API error: {e}")


# ---------------------------------------------------------------------------
# 5b. List folders + ingest-by-folder — the post-connect folder picker
# ---------------------------------------------------------------------------

@router.get("/folders")
async def list_folders(
    current_user: dict = Depends(require_uploader),
) -> Dict[str, Any]:
    """Return every folder in the user's Drive (with computed paths).

    Backs the folder-picker UI shown right after connecting, so the user
    chooses which folders to ingest instead of slurping the whole drive.
    """
    client = await _require_connected(current_user)
    try:
        folders = await client.list_folders()
    except GoogleDriveError as e:
        raise HTTPException(status_code=502, detail=f"Drive API error: {e}")
    return {"folders": folders}


class IngestFolderSpec(BaseModel):
    id: str = Field(..., description="Drive folder (or shared-drive) id")
    name: str = Field(..., description="Folder name — used as the KB folder")


class IngestFoldersRequest(BaseModel):
    folders: List[IngestFolderSpec] = Field(..., min_length=1)


@router.post("/ingest-folders")
async def ingest_folders(
    body: IngestFoldersRequest,
    current_user: dict = Depends(require_uploader),
) -> Dict[str, Any]:
    """Ingest every supported file under the selected Drive folders.

    Each selected folder's files (recursively, including subfolders) land in a
    KB folder named after that Drive folder — so "HR" / "Services" show up as
    separate folders in the sidebar instead of one big "Google Drive" bucket.
    Files already ingested are skipped via dedup.
    """
    user_id = current_user.get("id")
    organization_id = current_user.get("organization_id")
    await _require_connected(current_user)
    folders = [{"id": f.id, "name": f.name} for f in body.folders]
    discover_drive_files_task.delay(
        organization_id=organization_id,
        user_id=user_id,
        folders=folders,
    )
    logger.info(
        f"📂 Drive folder ingest queued: user={user_id[:8]}… "
        f"{len(folders)} folder(s)"
    )
    return {
        "success": True,
        "message": f"Ingesting {len(folders)} folder(s)",
        "folder_count": len(folders),
    }


# ---------------------------------------------------------------------------
# 6. Sync — manually re-discover (e.g. user added new files to Drive)
# ---------------------------------------------------------------------------

@router.post("/sync")
async def sync(
    folder_name: str = "Google Drive",
    current_user: dict = Depends(require_uploader),
) -> Dict[str, Any]:
    """Re-run discovery for an already-connected user.

    Idempotent: files that were already ingested are skipped by
    metadata.drive_file_id dedup; only genuinely new files get queued.
    """
    user_id = current_user.get("id")
    organization_id = current_user.get("organization_id")
    await _require_connected(current_user)
    discover_drive_files_task.delay(
        organization_id=organization_id,
        user_id=user_id,
        folder_name=folder_name.strip() or "Google Drive",
    )
    return {"success": True, "message": "Discovery queued"}


# ---------------------------------------------------------------------------
# 7. Disconnect — remove the Composio connection(s)
# ---------------------------------------------------------------------------

@router.delete("/disconnect")
async def disconnect(
    current_user: dict = Depends(require_uploader),
) -> Dict[str, Any]:
    client = _client(current_user)
    try:
        removed = await asyncio.to_thread(client.disconnect)
    except Exception as e:
        logger.warning(f"Drive disconnect failed: {e}")
        removed = 0
    return {"success": True, "removed": removed}
