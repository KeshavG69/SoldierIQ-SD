"""
Mind Map Pydantic Models
Defines data structures for mind map generation and storage
"""

from pydantic import BaseModel, Field, model_validator
from typing import List, Optional
from typing_extensions import Self


class Node(BaseModel):
    """Represents a single node in the mind map"""
    id: str = Field(description="Unique identifier for the node")
    content: str = Field(
        description="Concise content of the node (max 5 words)",
        max_length=100
    )


class Edge(BaseModel):
    """Represents a connection between two nodes"""
    from_id: str = Field(description="Source node ID")
    to_id: str = Field(description="Target node ID")


class MindMap(BaseModel):
    """Complete mind map structure"""
    nodes: List[Node] = Field(
        description="List of nodes in the mind map",
        min_length=1
    )
    edges: List[Edge] = Field(
        description="Connections between nodes"
    )

    @model_validator(mode="after")
    def validate_edges(self) -> Self:
        """Ensure all edges reference existing nodes"""
        node_ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.from_id not in node_ids:
                raise ValueError(f"Edge references non-existent source node: {edge.from_id}")
            if edge.to_id not in node_ids:
                raise ValueError(f"Edge references non-existent target node: {edge.to_id}")
        return self


class DocumentSummary(BaseModel):
    """Summary data extracted from a document"""
    summary: str = Field(description="Overall summary of the document")
    key_points: List[str] = Field(
        description="3-10 key points from the document",
        min_length=3,
        max_length=10
    )


class MindMapRequest(BaseModel):
    """Request model for mind map generation"""
    document_ids: List[str] = Field(
        description="List of MongoDB document IDs to generate mind map from",
        min_length=1
    )


class MindMapResponse(BaseModel):
    """Response model for mind map generation"""
    success: bool
    mind_map_id: Optional[str] = Field(default=None, description="ID of saved mind map")
    html_url: Optional[str] = Field(default=None, description="URL to view the mind map")
    summary: Optional[str] = Field(default=None, description="Document summary")
    key_points: Optional[List[str]] = Field(default=None, description="Key points")
    node_count: Optional[int] = Field(default=None, description="Number of nodes")
    edge_count: Optional[int] = Field(default=None, description="Number of edges")
    error: Optional[str] = Field(default=None, description="Error message if generation failed")
