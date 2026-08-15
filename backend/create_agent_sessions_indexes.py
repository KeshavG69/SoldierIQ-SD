"""
Create indexes for agent_sessions collection to improve query performance

Run this script once to create optimal indexes for the agent_sessions collection.
This will significantly reduce query latency as the collection grows.
"""
import asyncio
from clients.mongodb_client import get_mongodb_client
from app.logger import logger

async def create_indexes():
    """Create indexes for agent_sessions collection"""
    mongodb = get_mongodb_client()
    collection = mongodb.async_db["agent_sessions"]

    logger.info("=" * 80)
    logger.info("CREATING INDEXES FOR agent_sessions COLLECTION")
    logger.info("=" * 80)

    # Get existing indexes
    existing_indexes = await collection.index_information()
    logger.info(f"\n📋 Existing indexes: {list(existing_indexes.keys())}")

    indexes_to_create = []

    # Index 1: session_id (unique) - for fast session lookup
    # Used by: get_chat_session, delete_chat_session, rename_chat_session
    if "session_id_1" not in existing_indexes:
        indexes_to_create.append({
            "keys": [("session_id", 1)],
            "name": "session_id_1",
            "unique": True,
            "description": "Unique index on session_id for fast session lookups"
        })

    # Index 2: user_id + updated_at (descending) - for list query with sorting
    # Used by: list_chat_sessions (sorted by updated_at DESC)
    if "user_id_1_updated_at_-1" not in existing_indexes:
        indexes_to_create.append({
            "keys": [("user_id", 1), ("updated_at", -1)],
            "name": "user_id_1_updated_at_-1",
            "description": "Compound index for user's sessions sorted by last updated"
        })

    # Index 3: session_id + user_id - for security checks
    # Used by: get_chat_session, delete_chat_session, rename_chat_session
    # (ensures user can only access their own sessions)
    if "session_id_1_user_id_1" not in existing_indexes:
        indexes_to_create.append({
            "keys": [("session_id", 1), ("user_id", 1)],
            "name": "session_id_1_user_id_1",
            "description": "Compound index for session + user validation"
        })

    if not indexes_to_create:
        logger.info("\n✅ All indexes already exist!")
        return

    # Create indexes
    logger.info(f"\n🔨 Creating {len(indexes_to_create)} new indexes...")

    for idx_config in indexes_to_create:
        try:
            logger.info(f"\n  Creating: {idx_config['name']}")
            logger.info(f"  Keys: {idx_config['keys']}")
            logger.info(f"  Description: {idx_config['description']}")

            # Create the index
            await collection.create_index(
                idx_config["keys"],
                name=idx_config["name"],
                unique=idx_config.get("unique", False)
            )

            logger.info(f"  ✅ Created successfully")

        except Exception as e:
            logger.error(f"  ❌ Failed to create index {idx_config['name']}: {str(e)}")

    # Show final index list
    logger.info("\n" + "=" * 80)
    logger.info("FINAL INDEX LIST")
    logger.info("=" * 80)

    final_indexes = await collection.index_information()
    for idx_name, idx_info in final_indexes.items():
        logger.info(f"\n📌 {idx_name}")
        logger.info(f"   Keys: {idx_info.get('key', [])}")
        if idx_info.get('unique'):
            logger.info(f"   Unique: True")

    logger.info("\n✅ Index creation complete!")

    # Show collection stats
    logger.info("\n" + "=" * 80)
    logger.info("COLLECTION STATISTICS")
    logger.info("=" * 80)

    stats = await mongodb.async_db.command("collStats", "agent_sessions")
    doc_count = stats.get("count", 0)
    avg_doc_size = stats.get("avgObjSize", 0)
    total_size = stats.get("size", 0)
    index_size = stats.get("totalIndexSize", 0)

    logger.info(f"\n📊 Documents: {doc_count:,}")
    logger.info(f"📊 Average document size: {avg_doc_size:,} bytes")
    logger.info(f"📊 Total collection size: {total_size / 1024 / 1024:.2f} MB")
    logger.info(f"📊 Total index size: {index_size / 1024 / 1024:.2f} MB")

    logger.info("\n" + "=" * 80)
    logger.info("PERFORMANCE IMPACT")
    logger.info("=" * 80)
    logger.info("""
✅ session_id index: O(log n) lookups instead of O(n) collection scans
✅ user_id + updated_at index: Fast sorted queries for session lists
✅ session_id + user_id index: Efficient security validation queries

Expected performance improvement:
• Small collections (< 1000 docs): 2-5x faster
• Medium collections (1000-10000 docs): 10-50x faster
• Large collections (> 10000 docs): 100-1000x faster
""")

if __name__ == "__main__":
    asyncio.run(create_indexes())
