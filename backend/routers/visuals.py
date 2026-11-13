"""Serve stored map payloads to the chat map card (see utils/visual_tools.show_map)."""

from fastapi import APIRouter, Depends, HTTPException

from orgs.dependencies import get_current_context

router = APIRouter(prefix="/visuals", tags=["visuals"])


@router.get("/maps/{map_id}")
async def get_map(map_id: str, current_user: dict = Depends(get_current_context)):
    from osint.visuals import load_map

    owner = f"{current_user.get('organization_id')}:{current_user.get('id')}"
    payload = await load_map(map_id, owner)
    if payload is None:
        raise HTTPException(status_code=404, detail="Map not found or expired. Ask the assistant to draw it again.")
    return payload
