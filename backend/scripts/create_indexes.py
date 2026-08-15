#!/usr/bin/env python3
"""
MongoDB Index Creation Script

Run this script to create all required indexes for the application.
This should be run once during deployment or when new indexes are added.

Usage:
    python scripts/create_indexes.py
"""

import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from pymongo import ASCENDING, DESCENDING
from clients.mongodb_client import get_mongodb_client
from app.logger import logger


def create_documents_indexes(db):
    """Create indexes for documents collection

    Note: user_id is now a Keycloak UUID string (not MongoDB ObjectId)
    """
    logger.info("📊 Creating indexes for 'documents' collection...")

    documents_collection = db["documents"]
    existing_indexes = documents_collection.index_information()

    indexes_to_create = [
        ("user_id_1", [("user_id", ASCENDING)]),
        ("organization_id_1", [("organization_id", ASCENDING)]),
        ("folder_name_1", [("folder_name", ASCENDING)]),
        ("created_at_-1", [("created_at", DESCENDING)]),
        ("file_name_1", [("file_name", ASCENDING)]),
        ("file_key_1", [("file_key", ASCENDING)]),
        ("organization_id_1_folder_name_1", [("organization_id", ASCENDING), ("folder_name", ASCENDING)]),
        ("organization_id_1_user_id_1", [("organization_id", ASCENDING), ("user_id", ASCENDING)]),
        ("organization_id_1_created_at_-1", [("organization_id", ASCENDING), ("created_at", DESCENDING)]),
        ("user_id_1_created_at_-1", [("user_id", ASCENDING), ("created_at", DESCENDING)])
    ]

    created_count = 0
    skipped_count = 0

    for index_name, index_keys in indexes_to_create:
        if index_name not in existing_indexes:
            documents_collection.create_index(index_keys, name=index_name)
            logger.info(f"  ✅ Created index: {index_name}")
            created_count += 1
        else:
            logger.info(f"  ⏭️  Index already exists: {index_name}")
            skipped_count += 1

    logger.info(f"📊 Documents collection: {created_count} created, {skipped_count} skipped\n")


def create_ingestion_tasks_indexes(db):
    """Create indexes for ingestion_tasks collection

    Note: user_id is now a Keycloak UUID string (not MongoDB ObjectId)
    """
    logger.info("📊 Creating indexes for 'ingestion_tasks' collection...")

    tasks_collection = db["ingestion_tasks"]
    existing_indexes = tasks_collection.index_information()

    indexes_to_create = [
        ("status_1", [("status", ASCENDING)]),
        ("user_id_1", [("user_id", ASCENDING)]),
        ("organization_id_1", [("organization_id", ASCENDING)]),
        ("created_at_-1", [("created_at", DESCENDING)]),
        ("updated_at_-1", [("updated_at", DESCENDING)]),
        ("organization_id_1_status_1", [("organization_id", ASCENDING), ("status", ASCENDING)]),
        ("user_id_1_status_1", [("user_id", ASCENDING), ("status", ASCENDING)])
    ]

    created_count = 0
    skipped_count = 0

    for index_name, index_keys in indexes_to_create:
        if index_name not in existing_indexes:
            tasks_collection.create_index(index_keys, name=index_name)
            logger.info(f"  ✅ Created index: {index_name}")
            created_count += 1
        else:
            logger.info(f"  ⏭️  Index already exists: {index_name}")
            skipped_count += 1

    logger.info(f"📊 Ingestion tasks collection: {created_count} created, {skipped_count} skipped\n")


def create_agent_sessions_indexes(db):
    """Create indexes for agent_sessions collection

    Note: user_id is now a Keycloak UUID string (not MongoDB ObjectId)
    """
    logger.info("📊 Creating indexes for 'agent_sessions' collection...")

    collection = db["agent_sessions"]
    existing_indexes = collection.index_information()

    indexes_to_create = [
        ("session_id_1", [("session_id", ASCENDING)], {"unique": True}),
        ("user_id_1", [("user_id", ASCENDING)], {}),
        ("user_id_1_updated_at_-1", [("user_id", ASCENDING), ("updated_at", DESCENDING)], {}),
        ("session_id_1_user_id_1", [("session_id", ASCENDING), ("user_id", ASCENDING)], {}),
        ("created_at_-1", [("created_at", DESCENDING)], {})
    ]

    created_count = 0
    skipped_count = 0

    for index_config in indexes_to_create:
        index_name, index_keys = index_config[0], index_config[1]
        index_options = index_config[2] if len(index_config) > 2 else {}

        if index_name not in existing_indexes:
            collection.create_index(index_keys, name=index_name, **index_options)
            logger.info(f"  ✅ Created index: {index_name}")
            created_count += 1
        else:
            logger.info(f"  ⏭️  Index already exists: {index_name}")
            skipped_count += 1

    logger.info(f"📊 Agent sessions collection: {created_count} created, {skipped_count} skipped\n")


def create_workflows_indexes(db):
    """Create indexes for workflows collection (used by reports, mindmaps, flashcards)

    Note: user_id is now a Keycloak UUID string (not MongoDB ObjectId)
    """
    logger.info("📊 Creating indexes for 'workflows' collection...")

    collection = db["workflows"]
    existing_indexes = collection.index_information()

    indexes_to_create = [
        ("user_id_1", [("user_id", ASCENDING)]),
        ("organization_id_1", [("organization_id", ASCENDING)]),
        ("created_at_-1", [("created_at", DESCENDING)]),
        ("workflow_type_1", [("workflow_type", ASCENDING)]),
        ("organization_id_1_user_id_1", [("organization_id", ASCENDING), ("user_id", ASCENDING)]),
        ("organization_id_1_workflow_type_1", [("organization_id", ASCENDING), ("workflow_type", ASCENDING)]),
        ("user_id_1_workflow_type_1", [("user_id", ASCENDING), ("workflow_type", ASCENDING)]),
        ("organization_id_1_created_at_-1", [("organization_id", ASCENDING), ("created_at", DESCENDING)])
    ]

    created_count = 0
    skipped_count = 0

    for index_name, index_keys in indexes_to_create:
        if index_name not in existing_indexes:
            collection.create_index(index_keys, name=index_name)
            logger.info(f"  ✅ Created index: {index_name}")
            created_count += 1
        else:
            logger.info(f"  ⏭️  Index already exists: {index_name}")
            skipped_count += 1

    logger.info(f"📊 Workflows collection: {created_count} created, {skipped_count} skipped\n")


def create_podcasts_indexes(db):
    """Create indexes for podcasts collection"""
    logger.info("📊 Creating indexes for 'podcasts' collection...")

    collection = db["podcasts"]
    existing_indexes = collection.index_information()

    indexes_to_create = [
        ("organization_id_1", [("organization_id", ASCENDING)]),
        ("created_at_-1", [("created_at", DESCENDING)]),
        ("status_1", [("status", ASCENDING)]),
        ("organization_id_1_created_at_-1", [("organization_id", ASCENDING), ("created_at", DESCENDING)]),
        ("organization_id_1_status_1", [("organization_id", ASCENDING), ("status", ASCENDING)])
    ]

    created_count = 0
    skipped_count = 0

    for index_name, index_keys in indexes_to_create:
        if index_name not in existing_indexes:
            collection.create_index(index_keys, name=index_name)
            logger.info(f"  ✅ Created index: {index_name}")
            created_count += 1
        else:
            logger.info(f"  ⏭️  Index already exists: {index_name}")
            skipped_count += 1

    logger.info(f"📊 Podcasts collection: {created_count} created, {skipped_count} skipped\n")


def main():
    """Main function to create all indexes"""
    try:
        logger.info("🚀 Starting MongoDB index creation...\n")
        logger.info("ℹ️  Note: user_id is now a Keycloak UUID string (not MongoDB ObjectId)\n")

        # Get MongoDB client
        mongodb_client = get_mongodb_client()
        db = mongodb_client.sync_db

        # Create indexes for each collection
        create_documents_indexes(db)
        create_ingestion_tasks_indexes(db)
        create_agent_sessions_indexes(db)
        create_workflows_indexes(db)
        create_podcasts_indexes(db)

        logger.info("✅ All indexes created successfully!")
        return 0

    except Exception as e:
        logger.error(f"❌ Failed to create indexes: {str(e)}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
