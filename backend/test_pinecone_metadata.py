"""
Test script to query Pinecone and verify file_key metadata
Checks that file_key and keyframe_file_key are properly stored
"""

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from clients.pinecone_client import get_pinecone_client
from app.logger import logger


def test_pinecone_metadata():
    """Query Pinecone and display metadata for video chunks"""

    logger.info("=" * 80)
    logger.info("🔍 PINECONE METADATA TEST")
    logger.info("=" * 80)

    # Initialize Pinecone client
    logger.info("\n📌 Initializing Pinecone client...")
    pinecone_client = get_pinecone_client()

    # From your ingestion logs:
    DOCUMENT_ID = "69822473b0da425b8515a25b"
    NAMESPACE = "69822473b0da425b8515a25a"  # organization_id
    FILE_NAME = "Instructional VSAT Setup.mp4"

    logger.info(f"\n📋 Query Parameters:")
    logger.info(f"   - Document ID: {DOCUMENT_ID}")
    logger.info(f"   - Namespace: {NAMESPACE}")
    logger.info(f"   - File Name: {FILE_NAME}")

    # Query Pinecone with filter
    logger.info(f"\n🔎 Querying Pinecone for video chunks...")

    try:
        # Use similarity_search_with_score to get results with metadata
        results = pinecone_client.similarity_search_with_score(
            query="VSAT setup",  # Simple query to get results
            k=5,  # Get first 5 chunks
            filter={"document_id": DOCUMENT_ID},
            namespace=NAMESPACE
        )

        logger.info(f"\n✅ Query successful! Found {len(results)} chunks")

        # Display metadata for each chunk
        logger.info("\n" + "=" * 80)
        logger.info("📊 CHUNK METADATA SAMPLES")
        logger.info("=" * 80)

        for idx, (document, score) in enumerate(results, 1):
            logger.info(f"\n[Chunk {idx}]")
            logger.info(f"   Score: {score:.4f}")

            metadata = document.metadata

            # Check for file_key fields
            logger.info(f"\n   📁 File Keys:")
            logger.info(f"      file_key: {metadata.get('file_key', 'NOT FOUND ❌')}")
            logger.info(f"      keyframe_file_key: {metadata.get('keyframe_file_key', 'NOT FOUND ❌')}")

            # Video-specific metadata
            logger.info(f"\n   🎬 Video Metadata:")
            logger.info(f"      file_name: {metadata.get('file_name')}")
            logger.info(f"      folder_name: {metadata.get('folder_name')}")
            logger.info(f"      clip_start: {metadata.get('clip_start')}s")
            logger.info(f"      clip_end: {metadata.get('clip_end')}s")
            logger.info(f"      duration: {metadata.get('duration')}s")
            logger.info(f"      key_frame_timestamp: {metadata.get('key_frame_timestamp')}s")
            logger.info(f"      scene_id: {metadata.get('scene_id')}")

            # Other metadata
            logger.info(f"\n   📝 Other Metadata:")
            logger.info(f"      document_id: {metadata.get('document_id')}")
            logger.info(f"      video_id: {metadata.get('video_id')}")
            logger.info(f"      video_name: {metadata.get('video_name')}")

            # Show a preview of the text
            text_preview = document.page_content[:150] if document.page_content else "No content"
            logger.info(f"\n   📄 Text Preview:")
            logger.info(f"      {text_preview}...")

        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("📊 VERIFICATION SUMMARY")
        logger.info("=" * 80)

        file_key_count = sum(1 for doc, _ in results if doc.metadata.get('file_key'))
        keyframe_key_count = sum(1 for doc, _ in results if doc.metadata.get('keyframe_file_key'))

        logger.info(f"\n✅ Total chunks queried: {len(results)}")
        logger.info(f"✅ Chunks with file_key: {file_key_count}/{len(results)}")
        logger.info(f"✅ Chunks with keyframe_file_key: {keyframe_key_count}/{len(results)}")

        if file_key_count == len(results):
            logger.info(f"\n🎉 SUCCESS: All chunks have file_key stored!")
        else:
            logger.error(f"\n❌ ERROR: Some chunks missing file_key!")

        if keyframe_key_count == len(results):
            logger.info(f"🎉 SUCCESS: All chunks have keyframe_file_key stored!")
        else:
            logger.error(f"❌ ERROR: Some chunks missing keyframe_file_key!")

        logger.info("\n" + "=" * 80)

        return results

    except Exception as e:
        logger.error(f"\n❌ Query failed: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    logger.info("🚀 Starting Pinecone metadata verification test\n")

    try:
        results = test_pinecone_metadata()
        logger.info("\n✅ TEST PASSED - Metadata verification complete")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ TEST FAILED: {str(e)}")
        sys.exit(1)
