"""
Script to check all documents in MongoDB for debugging
"""
import asyncio
from clients.mongodb_client import get_mongodb_client
from bson import ObjectId

async def check_documents():
    mongodb_client = get_mongodb_client()

    user_id = "507f1f77bcf86cd799439011"
    org_id = "507f191e810c19729de860ea"

    print(f"🔍 Checking documents for user_id={user_id}, org_id={org_id}")
    print("="*80)

    # Query 1: All documents for this user/org (no folder filter)
    print("\n📋 ALL DOCUMENTS (no folder filter):")
    all_docs = await mongodb_client.async_find_documents(
        collection="documents",
        query={
            "user_id": ObjectId(user_id),
            "organization_id": ObjectId(org_id)
        },
        projection={
            "file_name": 1,
            "folder_name": 1,
            "created_at": 1,
            "user_id": 1,
            "organization_id": 1
        }
    )

    if not all_docs:
        print("❌ No documents found!")
    else:
        print(f"✅ Found {len(all_docs)} documents:")
        for doc in all_docs:
            print(f"  - {doc.get('file_name')} (folder: {doc.get('folder_name')}, created: {doc.get('created_at')})")
            print(f"    _id: {doc.get('_id')}")
            print(f"    user_id: {doc.get('user_id')}")
            print(f"    organization_id: {doc.get('organization_id')}")

    # Query 2: Get distinct folder names
    print("\n📁 DISTINCT FOLDERS:")
    folders = await mongodb_client.async_distinct(
        collection="documents",
        field="folder_name",
        query={
            "user_id": ObjectId(user_id),
            "organization_id": ObjectId(org_id)
        }
    )

    if not folders:
        print("❌ No folders found!")
    else:
        print(f"✅ Found {len(folders)} folders:")
        for folder in folders:
            print(f"  - {folder}")

    # Query 3: Check recent uploads (last 10 minutes)
    from datetime import datetime, timedelta
    ten_minutes_ago = datetime.utcnow() - timedelta(minutes=10)

    print(f"\n⏰ RECENT DOCUMENTS (last 10 minutes, after {ten_minutes_ago}):")
    recent_docs = await mongodb_client.async_find_documents(
        collection="documents",
        query={
            "user_id": ObjectId(user_id),
            "organization_id": ObjectId(org_id),
            "created_at": {"$gte": ten_minutes_ago}
        },
        projection={
            "file_name": 1,
            "folder_name": 1,
            "created_at": 1
        }
    )

    if not recent_docs:
        print("❌ No recent documents found!")
    else:
        print(f"✅ Found {len(recent_docs)} recent documents:")
        for doc in recent_docs:
            print(f"  - {doc.get('file_name')} (folder: {doc.get('folder_name')}, created: {doc.get('created_at')})")

    # Query 4: Check ingestion tasks (recent)
    print(f"\n📤 RECENT INGESTION TASKS (last 10 minutes):")
    recent_tasks = await mongodb_client.async_find_documents(
        collection="ingestion_tasks",
        query={
            "user_id": ObjectId(user_id),
            "organization_id": ObjectId(org_id),
            "created_at": {"$gte": ten_minutes_ago}
        }
    )

    if not recent_tasks:
        print("❌ No recent tasks found!")
    else:
        print(f"✅ Found {len(recent_tasks)} recent tasks:")
        for task in recent_tasks:
            print(f"  - Task ID: {task.get('_id')}")
            print(f"    Status: {task.get('status')}")
            print(f"    Folder: {task.get('folder_name')}")
            print(f"    Files: {task.get('file_names')}")
            print(f"    Created: {task.get('created_at')}")
            print(f"    Updated: {task.get('updated_at')}")
            if task.get('status') == 'failed':
                print(f"    ❌ Error: {task.get('error')}")
            print()

    print("\n" + "="*80)
    print("✅ Check complete!")

if __name__ == "__main__":
    asyncio.run(check_documents())
