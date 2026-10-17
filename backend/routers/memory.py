"""
Memory router — let users see and edit what the chat agent remembers about them.

These are the agent's long-term user memories (Agno, Postgres table
public.agent_memories). The agent writes them after each chat run and reads
them into its prompt; here the user can review, correct, add and delete them.

Memories are scoped per org: stored under "<org_id>:<user_id>" (see
LimitedMemoryManager). Every query below filters on that scoped id, so a user
can only ever reach their own memories in their active org.
"""

import asyncio
import time
from typing import Dict, List, Optional

from agno.db.schemas import UserMemory
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from clients.agent_memory import MAX_MEMORIES_PER_USER, get_memory_manager
from orgs.dependencies import get_current_context

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryIn(BaseModel):
    memory: str = Field(..., min_length=1, max_length=2000)
    topics: Optional[List[str]] = Field(default=None, max_length=10)


def _scope(context: Dict):
    mm = get_memory_manager(context["organization_id"])
    return mm, mm._scoped(context["id"])


def _out(m: UserMemory) -> Dict:
    return {
        "id": m.memory_id,
        "memory": m.memory,
        "topics": m.topics or [],
        "created_at": m.created_at,
        "updated_at": m.updated_at or m.created_at,
    }


def _clean_topics(topics: Optional[List[str]]) -> List[str]:
    return [t.strip()[:40] for t in topics or [] if t and t.strip()]


@router.get("")
async def list_memories(context: Dict = Depends(get_current_context)):
    """Everything the agent remembers about the current user, newest first."""
    mm, uid = _scope(context)
    rows = await asyncio.to_thread(
        mm.db.get_user_memories, user_id=uid, sort_by="updated_at", sort_order="desc"
    )
    return {"memories": [_out(m) for m in rows or []], "limit": MAX_MEMORIES_PER_USER}


@router.post("")
async def add_memory(payload: MemoryIn, context: Dict = Depends(get_current_context)):
    """Add a memory by hand (e.g. "I'm the S2 for 3rd Battalion")."""
    mm, _ = _scope(context)
    memory = UserMemory(memory=payload.memory.strip(), topics=_clean_topics(payload.topics))
    # Goes through the manager so the per-user cap applies.
    memory_id = await asyncio.to_thread(mm.add_user_memory, memory, context["id"])
    if not memory_id:
        raise HTTPException(status_code=500, detail="Could not save memory")
    saved = await asyncio.to_thread(mm.db.get_user_memory, memory_id, True, mm._scoped(context["id"]))
    return _out(saved) if saved else {"id": memory_id}


@router.put("/{memory_id}")
async def update_memory(memory_id: str, payload: MemoryIn, context: Dict = Depends(get_current_context)):
    """Edit a memory's text or topics."""
    mm, uid = _scope(context)
    existing = await asyncio.to_thread(mm.db.get_user_memory, memory_id, True, uid)
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")
    existing.memory = payload.memory.strip()
    if payload.topics is not None:
        existing.topics = _clean_topics(payload.topics)
    existing.updated_at = int(time.time())
    await asyncio.to_thread(mm.db.upsert_user_memory, existing)
    return _out(existing)


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, context: Dict = Depends(get_current_context)):
    mm, uid = _scope(context)
    existing = await asyncio.to_thread(mm.db.get_user_memory, memory_id, True, uid)
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")
    await asyncio.to_thread(mm.db.delete_user_memory, memory_id, uid)
    return {"deleted": memory_id}


@router.delete("")
async def clear_memories(context: Dict = Depends(get_current_context)):
    """Forget everything about the current user (in the active org)."""
    mm, uid = _scope(context)
    rows = await asyncio.to_thread(mm.db.get_user_memories, user_id=uid)
    ids = [m.memory_id for m in rows or [] if m.memory_id]
    if ids:
        await asyncio.to_thread(mm.db.delete_user_memories, ids, uid)
    return {"deleted": len(ids)}
