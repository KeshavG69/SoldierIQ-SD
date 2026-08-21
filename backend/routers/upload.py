"""
Upload Router - Document ingestion endpoints
"""

from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, status
from pydantic import BaseModel
import base64
import math
import uuid
from services.ingestion_service import get_ingestion_service
from clients.youtube_downloader import get_youtube_downloader
from clients.idrivee2_client import get_idrivee2_client
from tasks.ingestion_tasks import process_document_ids_task, process_youtube_document_task, process_uploaded_file_task
from app.logger import logger
from auth.keycloak_auth import get_current_user_keycloak
from orgs.dependencies import get_current_context, require_uploader  # ingestion=admin/system_owner, reads=everyone
from utils.file_utils import sanitize_filename, get_file_size_mb,get_file_extension

router = APIRouter(prefix="/upload", tags=["upload"])


class PresignUploadRequest(BaseModel):
    """Request a presigned iDrive PUT URL for one file, before any bytes move."""
    filename: str
    folder_name: str
    content_type: Optional[str] = None


@router.post("/presign")
async def presign_upload(
    payload: PresignUploadRequest,
    current_user: dict = Depends(require_uploader)  # ingestion = admin/system_owner
):
    """
    Step 1 of the direct-to-iDrive upload flow: create the document record
    (status="processing") and hand back a presigned URL the BROWSER uploads
    to directly — the backend never touches the file bytes. This is what
    fixes large-video upload timeouts: the old path read the whole file into
    backend memory, base64-encoded it, and pushed that blob through Celery/
    Redis, all before the HTTP response could return.
    """
    user_id = current_user.get("id")
    organization_id = current_user.get("organization_id")

    if not payload.filename or not payload.filename.strip():
        raise HTTPException(status_code=400, detail="Filename is required")
    if not payload.folder_name or not payload.folder_name.strip():
        raise HTTPException(status_code=400, detail="Folder name is required")
    if not organization_id:
        raise HTTPException(status_code=400, detail="User must belong to an organization")

    folder_name = payload.folder_name.strip()
    document_id = str(uuid.uuid4())
    extension = get_file_extension(payload.filename)
    file_key = f"{organization_id}/{folder_name}/{document_id}{extension}"

    ingestion_service = get_ingestion_service()
    await ingestion_service._create_document_with_status(
        file_name=payload.filename,
        folder_name=folder_name,
        file_key=file_key,
        file_size_mb=0,  # unknown until the direct upload finishes
        user_id=user_id,
        organization_id=organization_id,
        additional_metadata={"id": document_id},
    )

    upload_url = await get_idrivee2_client().generate_presigned_put_url(file_key)

    logger.info(f"🔑 Presigned upload for {payload.filename} -> {file_key}")

    return {
        "success": True,
        "data": {
            "document_id": document_id,
            "file_key": file_key,
            "upload_url": upload_url,
            "folder_name": folder_name,
        },
    }


class ConfirmUploadRequest(BaseModel):
    """Sent once the browser's direct PUT to iDrive finishes."""
    document_id: str
    file_key: str
    filename: str
    folder_name: str
    content_type: Optional[str] = None
    file_size_mb: Optional[float] = None


@router.post("/confirm")
async def confirm_upload(
    payload: ConfirmUploadRequest,
    current_user: dict = Depends(require_uploader)  # ingestion = admin/system_owner
):
    """
    Step 2 of the direct-to-iDrive upload flow: the browser already PUT the
    bytes to iDrive itself, so this just dispatches the Celery task to
    download-and-ingest — no file content passes through this request.
    """
    user_id = current_user.get("id")
    organization_id = current_user.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=400, detail="User must belong to an organization")

    task = process_uploaded_file_task.delay(
        document_id=payload.document_id,
        file_key=payload.file_key,
        filename=payload.filename,
        content_type=payload.content_type or "application/octet-stream",
        folder_name=payload.folder_name,
        user_id=user_id,
        organization_id=organization_id,
    )

    logger.info(f"✅ Upload confirmed, dispatched Celery task {task.id} for {payload.filename}")

    return {
        "success": True,
        "data": {
            "document_id": payload.document_id,
            "task_id": task.id,
            "status": "processing",
        },
    }


# Each part costs ~20MB to re-send on failure instead of the whole file —
# big enough to keep part counts sane for multi-GB videos, small enough that
# a single flaky part doesn't waste much on retry.
MULTIPART_PART_SIZE_BYTES = 20 * 1024 * 1024


class PresignMultipartRequest(BaseModel):
    """Request a multipart upload session for one (large) file."""
    filename: str
    folder_name: str
    content_type: Optional[str] = None
    file_size_bytes: int


@router.post("/presign-multipart")
async def presign_multipart_upload(
    payload: PresignMultipartRequest,
    current_user: dict = Depends(require_uploader)  # ingestion = admin/system_owner
):
    """
    Step 1 of the multipart direct-to-iDrive flow: create the document
    record, start an S3 multipart upload session, and hand back one
    presigned PUT URL per part. The browser uploads each part directly to
    iDrive with its own retry — a single failed part only costs re-sending
    that part, not the whole file (unlike the single-PUT flow, which loses
    everything on any interruption for a large video).
    """
    user_id = current_user.get("id")
    organization_id = current_user.get("organization_id")

    if not payload.filename or not payload.filename.strip():
        raise HTTPException(status_code=400, detail="Filename is required")
    if not payload.folder_name or not payload.folder_name.strip():
        raise HTTPException(status_code=400, detail="Folder name is required")
    if not organization_id:
        raise HTTPException(status_code=400, detail="User must belong to an organization")
    if payload.file_size_bytes <= 0:
        raise HTTPException(status_code=400, detail="file_size_bytes must be positive")

    folder_name = payload.folder_name.strip()
    document_id = str(uuid.uuid4())
    extension = get_file_extension(payload.filename)
    file_key = f"{organization_id}/{folder_name}/{document_id}{extension}"

    ingestion_service = get_ingestion_service()
    await ingestion_service._create_document_with_status(
        file_name=payload.filename,
        folder_name=folder_name,
        file_key=file_key,
        file_size_mb=payload.file_size_bytes / (1024 * 1024),
        user_id=user_id,
        organization_id=organization_id,
        additional_metadata={"id": document_id},
    )

    idrive = get_idrivee2_client()
    upload_id = await idrive.create_multipart_upload(file_key, content_type=payload.content_type)

    total_parts = max(1, math.ceil(payload.file_size_bytes / MULTIPART_PART_SIZE_BYTES))
    part_urls = [
        {
            "part_number": part_number,
            "url": await idrive.generate_presigned_part_url(file_key, upload_id, part_number),
        }
        for part_number in range(1, total_parts + 1)
    ]

    logger.info(
        f"🔑 Multipart presign for {payload.filename} -> {file_key} "
        f"({total_parts} parts, upload_id={upload_id[:12]}…)"
    )

    return {
        "success": True,
        "data": {
            "document_id": document_id,
            "file_key": file_key,
            "upload_id": upload_id,
            "part_size_bytes": MULTIPART_PART_SIZE_BYTES,
            "total_parts": total_parts,
            "part_urls": part_urls,
            "folder_name": folder_name,
        },
    }


class MultipartPart(BaseModel):
    part_number: int
    etag: str


class CompleteMultipartRequest(BaseModel):
    """Sent once every part has uploaded successfully."""
    document_id: str
    file_key: str
    upload_id: str
    filename: str
    folder_name: str
    content_type: Optional[str] = None
    file_size_mb: Optional[float] = None
    parts: List[MultipartPart]


@router.post("/complete-multipart")
async def complete_multipart_upload_endpoint(
    payload: CompleteMultipartRequest,
    current_user: dict = Depends(require_uploader)  # ingestion = admin/system_owner
):
    """
    Step 2: finalize the S3 multipart upload (stitches the parts together
    into one object) and dispatch ingestion — same as the single-PUT confirm
    endpoint from here on.
    """
    user_id = current_user.get("id")
    organization_id = current_user.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=400, detail="User must belong to an organization")
    if not payload.parts:
        raise HTTPException(status_code=400, detail="No parts provided")

    idrive = get_idrivee2_client()
    try:
        await idrive.complete_multipart_upload(
            payload.file_key,
            payload.upload_id,
            [{"PartNumber": p.part_number, "ETag": p.etag} for p in payload.parts],
        )
    except Exception as e:
        logger.error(f"❌ Failed to complete multipart upload for {payload.filename}: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not finalize upload: {e}")

    task = process_uploaded_file_task.delay(
        document_id=payload.document_id,
        file_key=payload.file_key,
        filename=payload.filename,
        content_type=payload.content_type or "application/octet-stream",
        folder_name=payload.folder_name,
        user_id=user_id,
        organization_id=organization_id,
    )

    logger.info(f"✅ Multipart upload completed, dispatched Celery task {task.id} for {payload.filename}")

    return {
        "success": True,
        "data": {
            "document_id": payload.document_id,
            "task_id": task.id,
            "status": "processing",
        },
    }


class AbortMultipartRequest(BaseModel):
    """Sent if a part fails past all retries — cleans up the orphaned S3
    session and marks the document failed instead of leaving it stuck on
    'processing' forever."""
    document_id: str
    file_key: str
    upload_id: str


@router.post("/abort-multipart")
async def abort_multipart_upload_endpoint(
    payload: AbortMultipartRequest,
    current_user: dict = Depends(require_uploader)  # ingestion = admin/system_owner
):
    idrive = get_idrivee2_client()
    try:
        await idrive.abort_multipart_upload(payload.file_key, payload.upload_id)
    except Exception as e:
        logger.warning(f"⚠️ Abort multipart cleanup warning: {e}")

    ingestion_service = get_ingestion_service()
    try:
        await ingestion_service._update_document_status(
            document_id=payload.document_id,
            status="failed",
            stage="failed",
            stage_description="Upload failed after retries — please try again",
            error="Multipart upload aborted by client after part upload failures",
            organization_id=current_user.get("organization_id"),
            user_id=current_user.get("id"),
        )
    except Exception as e:
        logger.warning(f"⚠️ Could not mark document failed after abort: {e}")

    return {"success": True, "message": "Upload aborted"}


@router.post("/documents")
async def upload_documents(
    files: List[UploadFile] = File(..., description="Multiple files to upload"),
    folder_name: str = Form(..., description="Folder name for organization"),
    current_user: dict = Depends(require_uploader)  # ingestion = admin/system_owner
):
    """
    Upload multiple documents for ingestion (Celery background processing)

    This endpoint:
    1. Extracts user_id and organization_id from Keycloak token
    2. Validates input
    3. Creates document records with status="processing" in PostgreSQL
    4. Returns immediately with document_ids for frontend tracking
    5. Dispatches Celery tasks to process each document:
       - Uploads files to iDrive E2
       - Extracts raw content
       - Stores in PostgreSQL
       - Chunks content semantically
       - Stores chunks in pgvector
       - Extracts entities/relationships to Apache AGE graph
       - Updates status to "completed" or "failed"

    Args:
        files: List of files to upload
        folder_name: Folder name for organization and filtering
        current_user: Authenticated user from Keycloak (contains user_id and organization_id)

    Returns:
        Document IDs and Celery task ID for tracking
    """
    try:
        # Extract user info from Keycloak token
        user_id = current_user.get("id")  # Keycloak UUID string
        organization_id = current_user.get("organization_id")  # Organization UUID string
        username = current_user.get("username")

        # Validate input
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")

        if not folder_name or not folder_name.strip():
            raise HTTPException(status_code=400, detail="Folder name is required")

        if not organization_id:
            raise HTTPException(status_code=400, detail="User must belong to an organization")

        logger.info(f"📤 Upload from {username} (user={user_id[:8]}..., org={organization_id[:8]}...): {len(files)} files, folder={folder_name}")

        # Create document records with status="processing" FIRST (before Celery task)
        ingestion_service = get_ingestion_service()

        documents_data = []
        for file in files:
            # Read file content
            content = await file.read()

            # Encode to base64 for Celery JSON serialization
            content_b64 = base64.b64encode(content).decode('utf-8')

            file_size_mb = get_file_size_mb(content)

            # Generate document_id first
            document_id = str(uuid.uuid4())

            # Build file_key using document_id and original extension
            extension = get_file_extension(file.filename)
            if organization_id:
                file_key = f"{organization_id}/{folder_name.strip()}/{document_id}{extension}"
            else:
                file_key = f"{folder_name.strip()}/{document_id}{extension}"

            # Create document record with status="processing" (WITH file_key)
            await ingestion_service._create_document_with_status(
                file_name=file.filename,
                folder_name=folder_name.strip(),
                file_key=file_key,  # Now we have the correct file_key
                file_size_mb=file_size_mb,
                user_id=user_id,
                organization_id=organization_id,
                additional_metadata={"id": document_id}  # Pass the document_id
            )

            documents_data.append({
                "document_id": document_id,
                "file_key": file_key,
                "content_b64": content_b64,
                "filename": file.filename,
                "content_type": file.content_type
            })

            logger.info(f"📝 Created document record: {document_id} for {file.filename}")

        # Dispatch Celery task (will create individual worker tasks for each document)
        task = process_document_ids_task.delay(
            documents_data=documents_data,
            folder_name=folder_name.strip(),
            user_id=user_id,
            organization_id=organization_id
        )

        logger.info(f"✅ Created {len(documents_data)} document records and dispatched Celery task: {task.id}")

        return {
            "success": True,
            "message": f"Ingestion started for {len(files)} files",
            "data": {
                "total_files": len(files),
                "document_ids": [doc["document_id"] for doc in documents_data],
                "file_names": [doc["filename"] for doc in documents_data],
                "file_keys": [doc["file_key"] for doc in documents_data],
                "folder_name": folder_name.strip(),
                "task_id": task.id,
                "status": "processing"
            }
        }

    except Exception as e:
        logger.error(f"❌ Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


class YouTubeIngestionRequest(BaseModel):
    """Request model for YouTube URL ingestion"""
    youtube_url: str
    folder_name: str


@router.post("/youtube")
async def ingest_youtube_video(
    request: YouTubeIngestionRequest,
    current_user: dict = Depends(require_uploader)  # ingestion = admin/system_owner
):
    """
    Ingest YouTube video by URL (Celery background processing)

    This endpoint:
    1. Extracts user_id and organization_id from Keycloak token
    2. Validates YouTube URL format
    3. Creates document record with status="processing" in PostgreSQL (fast!)
    4. Returns immediately with document_id for frontend tracking
    5. Dispatches Celery task to:
       - Download video from YouTube
       - Extract metadata and update document
       - Upload to iDrive E2
       - Extract frames and transcription
       - Chunk content semantically
       - Store chunks in pgvector
       - Extract entities/relationships to Apache AGE graph
       - Update status to "completed" or "failed"

    Args:
        request: YouTubeIngestionRequest with URL and folder_name
        current_user: Authenticated user from Keycloak (contains user_id and organization_id)

    Returns:
        Document ID and Celery task ID for tracking
    """
    try:
        # Extract user info from Keycloak token
        user_id = current_user.get("id")
        organization_id = current_user.get("organization_id")
        username = current_user.get("username")

        # Validate input
        if not request.youtube_url or not request.youtube_url.strip():
            raise HTTPException(status_code=400, detail="YouTube URL is required")

        if not request.folder_name or not request.folder_name.strip():
            raise HTTPException(status_code=400, detail="Folder name is required")

        if not organization_id:
            raise HTTPException(status_code=400, detail="User must belong to an organization")

        # Validate YouTube URL
        youtube_downloader = get_youtube_downloader()
        if not youtube_downloader.validate_youtube_url(request.youtube_url):
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")

        logger.info(f"📺 YouTube ingestion from {username}: {request.youtube_url}, folder={request.folder_name}")

        # Create document record with status="processing" (fast - just DB write)
        ingestion_service = get_ingestion_service()

        # Use YouTube URL as placeholder filename initially
        filename = f"YouTube Video - {request.youtube_url.split('=')[-1][:11]}"

        # Generate the document_id up front so we can build a placeholder
        # file_key. The documents.file_key column is NOT NULL, and the real
        # key (with the downloaded video's actual extension) isn't known until
        # the worker downloads it — so we seed a placeholder here and the
        # worker overwrites it after download.
        document_id = str(uuid.uuid4())
        folder = request.folder_name.strip()
        placeholder_file_key = f"{organization_id}/{folder}/{document_id}.mp4"

        # Add YouTube URL to metadata
        additional_metadata = {
            "id": document_id,
            "source": "youtube",
            "youtube_url": request.youtube_url,
        }

        # Create document record with a placeholder file_key (worker updates it).
        await ingestion_service._create_document_with_status(
            file_name=filename,
            folder_name=folder,
            file_key=placeholder_file_key,
            file_size_mb=0,  # Unknown initially, will be updated by worker
            user_id=user_id,
            organization_id=organization_id,
            additional_metadata=additional_metadata
        )

        logger.info(f"📝 Created document record: {document_id} for YouTube URL")

        # Dispatch Celery task (worker will download, process, and update document)
        task = process_youtube_document_task.delay(
            document_id=document_id,
            youtube_url=request.youtube_url,
            folder_name=request.folder_name.strip(),
            user_id=user_id,
            organization_id=organization_id
        )

        logger.info(f"✅ YouTube video dispatched to Celery (task_id: {task.id})")

        return {
            "success": True,
            "message": f"YouTube video ingestion started",
            "data": {
                "document_id": document_id,
                "file_name": filename,
                "folder_name": request.folder_name.strip(),
                "task_id": task.id,
                "status": "processing"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ YouTube ingestion failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"YouTube ingestion failed: {str(e)}")


@router.get("/documents/{document_id}")
async def get_document(document_id: str, current_user: dict = Depends(get_current_context)):
    """
    Get document by ID

    Args:
        document_id: Document UUID

    Returns:
        Document data
    """
    try:
        # Extract user info from Keycloak token
        user_id = current_user.get("id")
        organization_id = current_user.get("organization_id")

        # Validate document_id is a valid UUID
        try:
            uuid.UUID(document_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid document_id format: {document_id}")

        ingestion_service = get_ingestion_service()
        document = await ingestion_service.get_document(
            document_id=document_id,
            organization_id=organization_id,
            user_id=user_id
        )

        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        return {
            "success": True,
            "data": document
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get document failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get document: {str(e)}")


@router.get("/documents")
async def list_documents(
    folder_name: Optional[str] = None,
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
    current_user: dict = Depends(get_current_context)
):
    """
    List documents with optional filters

    Args:
        folder_name: Optional folder name filter
        user_id: Optional user ID filter (Keycloak UUID)
        organization_id: Optional organization ID filter (Keycloak UUID)
        limit: Maximum number of documents to return (default: 100)
        skip: Number of documents to skip (default: 0)

    Returns:
        List of documents
    """
    try:
        ingestion_service = get_ingestion_service()
        documents = await ingestion_service.list_documents(
            folder_name=folder_name,
            user_id=user_id,
            organization_id=organization_id,
            limit=limit,
            skip=skip
        )

        # Every org member (Admin, System Owner, or User) sees every document
        # in the org — no per-document access filtering.

        return {
            "success": True,
            "data": documents,
            "count": len(documents)
        }

    except Exception as e:
        logger.error(f"❌ List documents failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    delete_from_storage: bool = True,
    current_user: dict = Depends(require_uploader)  # write = admin/system_owner
):
    """
    Delete document and its chunks from all systems (PostgreSQL, pgvector, Apache AGE, iDrive E2)

    Args:
        document_id: Document UUID
        delete_from_storage: Whether to delete from iDrive E2 (default: True)

    Returns:
        Deletion result
    """
    try:
        # Extract user info from Keycloak token
        user_id = current_user.get("id")
        organization_id = current_user.get("organization_id")

        # Validate document_id is a valid UUID
        try:
            uuid.UUID(document_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid document_id format: {document_id}")

        ingestion_service = get_ingestion_service()
        result = await ingestion_service.delete_document(
            document_id=document_id,
            organization_id=organization_id,
            user_id=user_id,
            delete_from_storage=delete_from_storage
        )

        return {
            "success": True,
            "message": "Document deleted successfully",
            "data": result
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Delete document failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")


@router.get("/folders")
async def list_folders(
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    current_user: dict = Depends(get_current_context)
):
    """
    List all unique folder names (knowledge bases)

    Args:
        user_id: Optional user ID filter (Keycloak UUID)
        organization_id: Optional organization ID filter (Keycloak UUID)

    Returns:
        List of folder names
    """
    try:
        ingestion_service = get_ingestion_service()
        folders = await ingestion_service.list_folders(
            user_id=user_id,
            organization_id=organization_id
        )

        return {
            "success": True,
            "data": folders,
            "count": len(folders)
        }

    except Exception as e:
        logger.error(f"❌ List folders failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list folders: {str(e)}")


@router.delete("/folders/{folder_name}")
async def delete_folder(
    folder_name: str,
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    delete_from_storage: bool = True,
    current_user: dict = Depends(require_uploader)  # write = admin/system_owner
):
    """
    Delete entire folder and all its documents from all systems
    (PostgreSQL + pgvector + Apache AGE + iDrive E2)

    Args:
        folder_name: Folder name to delete
        user_id: Optional user ID filter (Keycloak UUID)
        organization_id: Optional organization ID filter (Keycloak UUID)
        delete_from_storage: Whether to delete from iDrive E2 (default: True)

    Returns:
        Deletion result with count
    """
    try:
        ingestion_service = get_ingestion_service()
        result = await ingestion_service.delete_folder(
            folder_name=folder_name,
            user_id=user_id,
            organization_id=organization_id,
            delete_from_storage=delete_from_storage
        )

        return {
            "success": True,
            "message": f"Folder '{folder_name}' deleted successfully",
            "data": result
        }

    except Exception as e:
        logger.error(f"❌ Delete folder failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete folder: {str(e)}")


@router.put("/folders/{folder_name}")
async def rename_folder(
    folder_name: str,
    new_folder_name: str = Form(..., description="New folder name"),
    user_id: Optional[str] = Form(None, description="Optional user ID"),
    organization_id: Optional[str] = Form(None, description="Optional organization ID"),
    current_user: dict = Depends(require_uploader)  # write = admin/system_owner
):
    """
    Rename folder in PostgreSQL
    (pgvector and Apache AGE don't store folder_name)

    Args:
        folder_name: Current folder name
        new_folder_name: New folder name
        user_id: Optional user ID filter (Keycloak UUID)
        organization_id: Optional organization ID filter (Keycloak UUID)

    Returns:
        Rename result with counts
    """
    try:
        # Validate input
        if not new_folder_name or not new_folder_name.strip():
            raise HTTPException(status_code=400, detail="New folder name is required")

        ingestion_service = get_ingestion_service()
        result = await ingestion_service.rename_folder(
            old_folder_name=folder_name,
            new_folder_name=new_folder_name.strip(),
            user_id=user_id,
            organization_id=organization_id
        )

        return {
            "success": True,
            "message": f"Folder renamed from '{folder_name}' to '{new_folder_name}' successfully",
            "data": result
        }

    except Exception as e:
        logger.error(f"❌ Rename folder failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to rename folder: {str(e)}")
