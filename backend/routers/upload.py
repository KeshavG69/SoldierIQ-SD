"""
Upload Router - Document ingestion endpoints
"""

from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from pydantic import BaseModel
import base64
import uuid
from services.ingestion_service import get_ingestion_service
from clients.youtube_downloader import get_youtube_downloader
from tasks.ingestion_tasks import process_document_ids_task, process_youtube_document_task
from app.logger import logger
from auth.keycloak_auth import get_current_user_keycloak
from orgs.dependencies import get_current_context, require_org_admin  # ingestion=admin, reads=member
from clients.kg.rbac import RBACManager  # per-document access filtering
from utils.file_utils import sanitize_filename, get_file_size_mb,get_file_extension

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/documents")
async def upload_documents(
    files: List[UploadFile] = File(..., description="Multiple files to upload"),
    folder_name: str = Form(..., description="Folder name for organization"),
    current_user: dict = Depends(require_org_admin)  # ingestion = admin only
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
    current_user: dict = Depends(require_org_admin)  # ingestion = admin only
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

        # Add YouTube URL to metadata
        additional_metadata = {
            "source": "youtube",
            "youtube_url": request.youtube_url,
        }

        # Create document record (without file_key initially)
        document_id = await ingestion_service._create_document_with_status(
            file_name=filename,
            folder_name=request.folder_name.strip(),
            file_key=None,  # Will be set by worker after download
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

        # Per-document RBAC: members see only documents granted to them; admins
        # (who manage the org) see all documents in the org.
        if current_user.get("role") != "admin":
            allowed = set(
                await RBACManager(current_user["organization_id"]).accessible_document_ids(
                    current_user.get("email") or ""
                )
            )
            documents = [d for d in documents if str(d.get("id")) in allowed]

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
    current_user: dict = Depends(require_org_admin)  # write = admin only
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
    current_user: dict = Depends(require_org_admin)  # write = admin only
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
    current_user: dict = Depends(require_org_admin)  # write = admin only
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
