"""LiveKit function tool for the voice knowledge agent.

Search goes to the SoldierIQ backend (see retriever.py), scoped by organization_id /
document_ids from the participant metadata (passed through AgentSession.userdata).
"""

import logging

from livekit.agents import Agent, RunContext, function_tool

from retriever import SearchUnavailable, search

logger = logging.getLogger("voice-agent.tools")

NO_RESULTS = "No relevant information found in the selected documents."


def _format_results(result: dict) -> str:
    """Render the backend's graph-search result for the LLM.

    Same information the chat agent receives — entities, graph facts and the source
    passages — laid out as text. Passage numbers `[n]` are internal; the prompt tells
    the model to cite by file name when speaking.
    """
    chunks = [c for c in (result.get("chunks") or []) if (c.get("text") or "").strip()]
    if not chunks:
        return NO_RESULTS

    names = result.get("file_names") or {}
    sections: list[str] = []

    anchors = result.get("anchors") or []
    if anchors:
        lines = [f"- {a.get('name')} ({a.get('type')})" for a in anchors]
        sections.append("## Key Entities\n" + "\n".join(lines))

    triples = result.get("triples") or []
    if triples:
        lines = [f"- {t.get('subject')} —[{t.get('predicate')}]→ {t.get('object')}" for t in triples]
        sections.append("## Knowledge Graph Facts\n" + "\n".join(lines))

    passages = []
    for idx, c in enumerate(chunks, start=1):
        file_name = names.get(c.get("document_id")) or "Unknown source"
        passages.append(f"[{c.get('n', idx)}] ({file_name})\n{c['text'].strip()}")
    sections.append("## Source Document Passages\n\n" + "\n\n".join(passages))

    return "\n\n".join(sections)


class KnowledgeAgent(Agent):
    """Voice agent that answers from the user's selected documents."""

    @function_tool()
    async def search_knowledge_base(
        self,
        context: RunContext,
        query: str,
    ) -> str:
        """Search the user's selected documents for information to answer their question.

        Args:
            query: A focused natural-language search query derived from the user's question.
                For a summary or overview, use a broad query such as
                "overview summary key points main topics".
        """
        ud = context.userdata or {}
        document_ids = ud.get("document_ids")

        if not document_ids:
            return (
                "No documents selected. Ask the user to select documents from the "
                "sidebar before asking knowledge questions."
            )

        organization_id = ud.get("organization_id")
        if not organization_id:
            logger.warning("Missing organization_id in userdata: %s", ud)
            return "Cannot search — user session is not authenticated."

        try:
            result = await search(
                query=query,
                organization_id=organization_id,
                document_ids=document_ids,
            )
        except SearchUnavailable:
            logger.exception("knowledge search unavailable")
            return (
                "The knowledge search is unavailable right now. Tell the user briefly "
                "and suggest they try again in a moment."
            )
        return _format_results(result)
