"""
Mind Map Service - JSON-based for Frontend Rendering
Supports multiple documents (like NotebookLM)
Returns mind map data as JSON for React component visualization
"""

import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from langchain_core.prompts import ChatPromptTemplate

from models.mindmap import MindMap, DocumentSummary
from clients.postgres_client import get_postgres_client
from app.logger import logger
from clients.ultimate_llm import get_llm

class MindMapService:
    """Service for generating mind maps from multiple documents"""

    def __init__(self):
        """Initialize the mind map service"""
        self.llm = get_llm(model="google/gemini-3-flash-preview",provider="openrouter")

        # Structured output - forces LLM to return valid objects
        self.structured_llm = self.llm.with_structured_output(MindMap)
        self.summary_llm = self.llm.with_structured_output(DocumentSummary)

        self.postgres_client = get_postgres_client()

    async def generate_from_documents(
        self,
        document_ids: List[str],
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate mind map from multiple documents (like NotebookLM)
        Returns JSON data structure for frontend rendering

        Flow:
        1. Fetch multiple documents from MongoDB
        2. Combine content intelligently
        3. Extract unified summary & key points using LLM
        4. Generate mind map structure using LLM
        5. Return JSON data (no HTML generation)
        6. Save to MongoDB

        Args:
            document_ids: List of MongoDB document IDs
            user_id: Optional user ID
            organization_id: Optional organization ID

        Returns:
            Dict with mind map JSON data
        """
        logger.info(f"🧠 Generating mind map for {len(document_ids)} documents")

        try:
            # Step 1: Fetch all documents from PostgreSQL
            documents = []
            for doc_id in document_ids:
                document = await self.postgres_client.find_document_by_id(doc_id)
                if document:
                    documents.append(document)
                else:
                    logger.warning(f"⚠️ Document not found: {doc_id}")

            if not documents:
                raise ValueError("No valid documents found")

            logger.info(f"✅ Fetched {len(documents)} documents")

            # Step 2: Combine content from all documents
            combined_content = self._combine_documents(documents)
            logger.info(f"📄 Combined content length: {len(combined_content)} chars")

            # Step 3: Extract summary and key points using LLM
            logger.info("📝 Extracting unified summary and key points...")
            doc_summary = await self._extract_summary(combined_content)
            logger.info(f"✅ Summary extracted: {len(doc_summary.key_points)} key points")

            # Step 4: Generate mind map structure using LLM
            logger.info("🎨 Generating mind map structure...")
            mind_map = await self._generate_mindmap(
                summary=doc_summary.summary,
                key_points=doc_summary.key_points,
                document_count=len(documents)
            )
            logger.info(f"✅ Mind map: {len(mind_map.nodes)} nodes, {len(mind_map.edges)} edges")

            # Convert to JSON-serializable format
            mind_map_data = {
                "nodes": [node.model_dump() for node in mind_map.nodes],
                "edges": [edge.model_dump() for edge in mind_map.edges]
            }

            # Step 5: Save to PostgreSQL workflows table
            mind_map_id = str(uuid.uuid4())

            workflow_doc = {
                "id": mind_map_id,
                "type": "mindmap",
                "document_ids": document_ids,  # Already UUIDs
                "user_id": user_id,  # Keycloak UUID string
                "organization_id": organization_id,  # UUID string
                "status": "completed",
                "data": {
                    "summary": doc_summary.summary,
                    "key_points": doc_summary.key_points,
                    "nodes": mind_map_data["nodes"],
                    "edges": mind_map_data["edges"],
                    "document_count": len(documents)
                },
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }

            await self.postgres_client.insert_workflow(workflow_doc)

            logger.info(f"✅ Mind map saved to PostgreSQL: {mind_map_id}")

            return {
                "mind_map_id": str(mind_map_id),
                "document_ids": document_ids,
                "summary": doc_summary.summary,
                "key_points": doc_summary.key_points,
                "mind_map": mind_map_data,  # Frontend will render this
                "node_count": len(mind_map.nodes),
                "edge_count": len(mind_map.edges)
            }

        except Exception as e:
            logger.error(f"❌ Mind map generation failed: {str(e)}")
            raise

    def _combine_documents(self, documents: List[Dict[str, Any]]) -> str:
        """
        Intelligently combine content from multiple documents

        Args:
            documents: List of document dicts from PostgreSQL

        Returns:
            Combined content string
        """
        combined_parts = []

        for i, doc in enumerate(documents, 1):
            filename = doc.get("file_name", f"Document {i}")
            content = doc.get("raw_content", "")

            if content:
                # Add document separator with metadata
                combined_parts.append(f"\n\n{'='*60}")
                combined_parts.append(f"DOCUMENT {i}: {filename}")
                combined_parts.append(f"{'='*60}\n")
                combined_parts.append(content)

        combined = "\n".join(combined_parts)
        logger.info(f"📄 Combined content: {len(combined)} chars from {len(documents)} documents")

        return combined

    async def get_mindmap(self, mind_map_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve mind map by ID from workflows table

        Args:
            mind_map_id: PostgreSQL workflow ID (UUID)

        Returns:
            Mind map document with JSON data
        """
        try:
            workflow = await self.postgres_client.find_workflow_by_id(
                workflow_id=mind_map_id,
                workflow_type="mindmap"
            )

            if workflow:
                # Extract data from nested structure
                data = workflow.get("data", {})

                # Format for frontend (flatten structure)
                return {
                    "mind_map_id": workflow["id"],
                    "document_ids": workflow.get("document_ids", []),
                    "user_id": workflow.get("user_id"),
                    "organization_id": workflow.get("organization_id"),
                    "status": workflow.get("status"),
                    "summary": data.get("summary", ""),
                    "key_points": data.get("key_points", []),
                    "mind_map": {
                        "nodes": data.get("nodes", []),
                        "edges": data.get("edges", [])
                    },
                    "created_at": workflow.get("created_at"),
                    "updated_at": workflow.get("updated_at")
                }

            return None

        except Exception as e:
            logger.error(f"❌ Failed to get mind map: {str(e)}")
            return None

    async def list_mindmaps_by_user(self, user_id: str, organization_id: str) -> List[Dict[str, Any]]:
        """
        List all mind maps for a specific user and organization from workflows table

        Args:
            user_id: User ID (UUID)
            organization_id: Organization ID (UUID)

        Returns:
            List of mind maps
        """
        try:
            workflows = await self.postgres_client.find_workflows_by_user(
                workflow_type="mindmap",
                user_id=user_id,
                organization_id=organization_id
            )

            mindmaps = []
            for workflow in workflows:
                # Extract data from nested structure
                data = workflow.get("data", {})

                # Format for frontend (flatten structure)
                mindmaps.append({
                    "mind_map_id": workflow["id"],
                    "document_ids": workflow.get("document_ids", []),
                    "user_id": workflow.get("user_id"),
                    "organization_id": workflow.get("organization_id"),
                    "status": workflow.get("status"),
                    "summary": data.get("summary", ""),
                    "key_points": data.get("key_points", []),
                    "mind_map": {
                        "nodes": data.get("nodes", []),
                        "edges": data.get("edges", [])
                    },
                    "created_at": workflow.get("created_at"),
                    "updated_at": workflow.get("updated_at")
                })

            logger.info(f"✅ Found {len(mindmaps)} mind maps for user {user_id}")
            return mindmaps

        except Exception as e:
            logger.error(f"❌ Failed to list mind maps: {str(e)}")
            return []

    async def _extract_summary(self, content: str) -> DocumentSummary:
        """Extract summary and key points from content using LLM"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert at analyzing documents and finding connections.
            Extract key information in a structured format:

            - Provide a concise overall summary (2-3 sentences) that captures the main themes
            - List 5-10 key highlights (bullet points) that represent the most important concepts

            When analyzing multiple documents, focus on:
            - Common themes and patterns
            - Key concepts that connect across documents
            - Main ideas and important details"""),
            ("user", "Analyze this content:\n\n{content}")
        ])

        messages = prompt.format_messages(content=content)
        doc_summary: DocumentSummary = await self.summary_llm.ainvoke(messages)

        return doc_summary

    async def _generate_mindmap(
        self,
        summary: str,
        key_points: List[str],
        document_count: int = 1
    ) -> MindMap:
        """Generate mind map structure using LLM with structured output"""

        context = f"across {document_count} documents" if document_count > 1 else "from this document"

        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert at creating mind maps that visualize complex information.
            Generate a hierarchical mind map that shows key concepts and their relationships.

            CRITICAL RULES FOR NODE IDs vs CONTENT:
            - Each node has TWO separate fields: 'id' and 'content'
            - Node 'id': Simple letters like "A", "B", "C", "D", etc.
            - Node 'content': The actual text/concept (max 5 words)
            - Edges MUST use node IDs (A, B, C), NEVER use content text

            Example of CORRECT structure:
            - Node: {{"id": "A", "content": "Main Topic"}}
            - Node: {{"id": "B", "content": "Subtopic One"}}
            - Edge: {{"from_id": "A", "to_id": "B"}}  ← Uses IDs, not content!

            Example of WRONG structure (DO NOT DO THIS):
            - Edge: {{"from_id": "Main Topic", "to_id": "Subtopic One"}}  ← WRONG! Uses content instead of IDs

            General Rules:
            - Keep node content concise (max 5 words per node)
            - Create a clear hierarchy with a central root node
            - Connect related concepts with edges (from parent to children)
            - Organize from general (root) to specific (leaves)
            - Create at least 10-25 nodes for a comprehensive visualization
            - Show how concepts relate and connect
            - Ensure all connections are valid and form a tree structure

            When working with multiple documents:
            - Find common themes and connections
            - Show how concepts from different sources relate
            - Create a unified view of the knowledge"""),
            ("user", """Create a mind map for this content {context}:

Summary: {summary}

Key Points:
{key_points}

Generate nodes and edges that show the relationships between concepts.
The root node should represent the main overarching topic.

REMEMBER: Edges must use node IDs (like "A", "B", "C"), NOT the node content text!""")
        ])

        # Format key points
        key_points_text = "\n".join([f"- {point}" for point in key_points])

        messages = prompt.format_messages(
            context=context,
            summary=summary,
            key_points=key_points_text
        )

        mind_map: MindMap = await self.structured_llm.ainvoke(messages)

        return mind_map


# Singleton instance
_mindmap_service = None


def get_mindmap_service() -> MindMapService:
    """Get or create MindMapService singleton"""
    global _mindmap_service
    if _mindmap_service is None:
        _mindmap_service = MindMapService()
    return _mindmap_service
