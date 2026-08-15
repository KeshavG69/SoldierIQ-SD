"""
Test script for video ingestion pipeline
Tests the complete flow: video processing → MongoDB → Pinecone
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Dict, Any
from bson import ObjectId

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.logger import logger
from services.ingestion_service import get_ingestion_service
from fastapi import UploadFile
import io


async def test_video_ingestion(video_path: str, folder_name: str = "test_videos") -> Dict[str, Any]:
    """
    Test video ingestion pipeline

    Args:
        video_path: Path to video file
        folder_name: Folder name for organization

    Returns:
        Dict with test results
    """
    logger.info("=" * 80)
    logger.info("🎬 VIDEO INGESTION TEST STARTED")
    logger.info("=" * 80)
    logger.info(f"📹 Video: {video_path}")
    logger.info(f"📁 Folder: {folder_name}")

    start_time = time.time()

    try:
        # Read video file
        logger.info("📂 Reading video file...")
        video_path_obj = Path(video_path)

        if not video_path_obj.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        with open(video_path, 'rb') as f:
            file_content = f.read()

        file_size_mb = len(file_content) / (1024 * 1024)
        logger.info(f"✅ Video file read: {file_size_mb:.2f} MB")

        # Create UploadFile object
        logger.info("📦 Creating UploadFile object...")
        upload_file = UploadFile(
            filename=video_path_obj.name,
            file=io.BytesIO(file_content)
        )

        # Get ingestion service
        logger.info("🔧 Initializing ingestion service...")
        ingestion_service = get_ingestion_service()
        logger.info("✅ Ingestion service initialized")

        # Generate valid ObjectIds for testing
        test_user_id = str(ObjectId())
        test_org_id = str(ObjectId())

        logger.info(f"📝 Generated test IDs:")
        logger.info(f"   - User ID: {test_user_id}")
        logger.info(f"   - Organization ID: {test_org_id}")

        # Test video processing
        logger.info("=" * 80)
        logger.info("🎬 STARTING VIDEO INGESTION")
        logger.info("=" * 80)

        result = await ingestion_service.ingest_documents(
            files=[upload_file],
            folder_name=folder_name,
            user_id=test_user_id,
            organization_id=test_org_id,
            additional_metadata={"test": True}
        )

        # Calculate timing
        elapsed_time = time.time() - start_time

        # Print results
        logger.info("=" * 80)
        logger.info("✅ VIDEO INGESTION TEST COMPLETED")
        logger.info("=" * 80)
        logger.info(f"⏱️  Total time: {elapsed_time:.2f}s")
        logger.info(f"📊 Results:")
        logger.info(f"   - Total files: {result['total_files']}")
        logger.info(f"   - Successful: {result['successful_files']}")
        logger.info(f"   - Failed: {result['failed_files']}")
        logger.info(f"   - Total chunks: {result['statistics']['total_chunks']}")
        logger.info(f"   - Processing time: {result['statistics']['processing_time']:.2f}s")

        if result['successful_files'] > 0:
            doc = result['documents'][0]
            logger.info(f"   - Document ID: {doc['document_id']}")
            logger.info(f"   - File name: {doc['file_name']}")
            logger.info(f"   - Total chunks: {doc['total_chunks']}")

        if result['errors']:
            logger.error(f"❌ Errors encountered:")
            for error in result['errors']:
                logger.error(f"   - {error['file_name']}: {error['error']}")

        return result

    except KeyboardInterrupt:
        logger.warning("⚠️  Test interrupted by user (Ctrl+C)")
        raise
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error("=" * 80)
        logger.error(f"❌ VIDEO INGESTION TEST FAILED after {elapsed_time:.2f}s")
        logger.error("=" * 80)
        logger.error(f"Error: {str(e)}", exc_info=True)
        raise


async def test_with_timeout(video_path: str, timeout_seconds: int = 300):
    """
    Run test with timeout to catch hangs

    Args:
        video_path: Path to video file
        timeout_seconds: Timeout in seconds (default: 5 minutes)
    """
    try:
        result = await asyncio.wait_for(
            test_video_ingestion(video_path),
            timeout=timeout_seconds
        )
        return result
    except asyncio.TimeoutError:
        logger.error("=" * 80)
        logger.error(f"❌ TEST TIMED OUT after {timeout_seconds}s")
        logger.error("=" * 80)
        logger.error("The ingestion process appears to be hanging.")
        logger.error("Check the logs above to see where it got stuck.")
        raise


if __name__ == "__main__":
    # Configuration
    VIDEO_PATH = "/Users/keshav/Downloads/Instructional VSAT Setup.mp4"
    FOLDER_NAME = "test_ingestion"
    TIMEOUT_SECONDS = 3000  # 50 minutes (10x original)

    logger.info("🚀 Starting video ingestion test script")
    logger.info(f"📹 Video: {VIDEO_PATH}")
    logger.info(f"⏱️  Timeout: {TIMEOUT_SECONDS}s")

    try:
        result = asyncio.run(test_with_timeout(VIDEO_PATH, TIMEOUT_SECONDS))
        logger.info("=" * 80)
        logger.info("✅ TEST PASSED")
        logger.info("=" * 80)
        sys.exit(0)
    except KeyboardInterrupt:
        logger.warning("⚠️  Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error("=" * 80)
        logger.error("❌ TEST FAILED")
        logger.error("=" * 80)
        logger.error(f"Error: {str(e)}")
        sys.exit(1)
