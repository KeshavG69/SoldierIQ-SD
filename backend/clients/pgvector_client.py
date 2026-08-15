
"""
PGVector Client
Vector database operations using PostgreSQL + pgvector extension
Replaces Pinecone for vector embeddings and similarity search
"""

from typing import Optional, List, Dict, Any
from langchain_postgres import PGVector
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from app.settings import settings
from app.logger import logger
from clients.ultimate_llm import get_llm
import uuid


class PGVectorClient:
    """Client for pgvector operations using LangChain"""

    def __init__(self):
        """Initialize pgvector client with LangChain"""
        self.connection_string = settings.POSTGRES_VECTOR_URL
        self.embedding_model = settings.OPENAI_API_KEY

        if not self.connection_string:
            raise ValueError("POSTGRES_VECTOR_URL not configured")
        if not self.embedding_model:
            raise ValueError("OPENAI_API_KEY not configured for embeddings")

        # Initialize OpenAI embeddings (same as Pinecone)
        self.embeddings = OpenAIEmbeddings(
            openai_api_key=self.embedding_model,
            model="text-embedding-3-small"
        )

        # Initialize LangChain PGVector store with connection pooling
        from sqlalchemy import create_engine
        self._engine = create_engine(
            self.connection_string,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,      # Auto-reconnect stale connections
            pool_recycle=300,         # Recycle connections every 5 min (Railway idle timeout)
            connect_args={
                "connect_timeout": 10,
                "options": "-c statement_timeout=30000",  # 30s query timeout
            },
        )

        self.vector_store = PGVector(
            embeddings=self.embeddings,
            collection_name="vector_embeddings",
            connection=self._engine,
            use_jsonb=True
        )

        logger.info(f"✅ PGVector client initialized with table: vector_embeddings")

    def _summarize_large_text(self, text: str, max_bytes: int = 30000) -> str:
        """
        Summarize text using LLM when it's too large for metadata

        Args:
            text: The text to summarize
            max_bytes: Max byte size before summarization (default: 30KB)

        Returns:
            Summarized text or original if under max_bytes
        """
        text_bytes = len(text.encode('utf-8'))

        if text_bytes <= max_bytes:
            return text

        try:
            llm = get_llm(model="gpt-4.1-mini", provider="openai")

            prompt = f"""Summarize the following text concisely while preserving key information and context.
Keep the summary under 3000 characters.

Text:
{text}
...
"""

            response = llm.invoke(prompt)
            summary = response.content

            logger.info(f"✅ Summarized text from {text_bytes} bytes to {len(summary.encode('utf-8'))} bytes using LLM")
            return summary

        except Exception as e:
            logger.error(f"❌ Failed to summarize text with LLM: {str(e)}")
            # Fallback to truncation
            logger.warning("⚠️  Falling back to text truncation")
            truncated_bytes = text.encode('utf-8')[:max_bytes]
            return truncated_bytes.decode('utf-8', errors='ignore')

    def add_documents(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: Optional[List[str]] = None,
        namespace: Optional[str] = None  # Now mapped to organization_id filtering
    ) -> List[str]:
        """
        Add documents to pgvector

        Args:
            texts: List of text chunks to embed and store
            metadatas: List of metadata dicts for each text chunk
            ids: Optional list of IDs for each document
            namespace: Optional namespace (maps to organization_id filter)

        Returns:
            List[str]: List of document IDs

        Raises:
            Exception: If adding documents fails
        """
        try:
            # Generate IDs if not provided
            if not ids:
                ids = [str(uuid.uuid4()) for _ in texts]

            # Process texts for storage (summarize if needed)
            processed_texts = []
            for text in texts:
                processed_text = self._summarize_large_text(text, max_bytes=30000)
                processed_texts.append(processed_text)

            # Create LangChain Document objects
            documents = []
            for doc_id, text, metadata in zip(ids, processed_texts, metadatas):
                # Add ID to metadata
                metadata_with_id = {**metadata, "id": doc_id}

                # If namespace provided, add as organization_id filter
                if namespace:
                    metadata_with_id["organization_id"] = namespace

                doc = Document(
                    page_content=text,
                    metadata=metadata_with_id
                )
                documents.append(doc)

            # Add to vector store (LangChain handles embedding generation)
            self.vector_store.add_documents(documents, ids=ids)

            logger.info(f"✅ Added {len(ids)} documents to pgvector")
            return ids

        except Exception as e:
            logger.error(f"❌ Failed to add documents to pgvector: {str(e)}")
            raise Exception(f"Failed to add documents: {str(e)}")

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None  # Maps to organization_id
    ) -> List[Document]:
        """
        Search for similar documents using semantic similarity

        Args:
            query: Query text
            k: Number of results to return
            filter: Optional metadata filter (uses LangChain filter syntax)
            namespace: Optional namespace (organization_id)

        Returns:
            List[Document]: List of similar documents with metadata

        Raises:
            Exception: If search fails
        """
        try:
            # Add namespace to filter if provided
            search_filter = filter.copy() if filter else {}
            if namespace:
                search_filter["organization_id"] = {"$eq": namespace}

            if search_filter:
                results = self.vector_store.similarity_search(
                    query,
                    k=k,
                    filter=search_filter
                )
            else:
                results = self.vector_store.similarity_search(query, k=k)

            logger.info(f"✅ Found {len(results)} similar documents")
            return results

        except Exception as e:
            logger.error(f"❌ Similarity search failed: {str(e)}")
            raise Exception(f"Similarity search failed: {str(e)}")

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None
    ) -> List[tuple]:
        """
        Search for similar documents with relevance scores

        Args:
            query: Query text
            k: Number of results to return
            filter: Optional metadata filter
            namespace: Optional namespace (organization_id)

        Returns:
            List[tuple]: List of (Document, score) tuples

        Raises:
            Exception: If search fails
        """
        # Ensure k is valid
        if k is None or k < 1:
            k = 5

        # Add namespace to filter if provided
        search_filter = filter.copy() if filter else {}
        if namespace:
            search_filter["organization_id"] = {"$eq": namespace}

        # Retry once on connection errors
        for attempt in range(2):
            try:
                if search_filter:
                    results = self.vector_store.similarity_search_with_score(
                        query, k=k, filter=search_filter
                    )
                else:
                    results = self.vector_store.similarity_search_with_score(query, k=k)

                logger.info(f"✅ Found {len(results)} similar documents with scores")
                return results

            except Exception as e:
                err_msg = str(e).lower()
                is_connection_error = any(kw in err_msg for kw in ["timed out", "closed", "connection", "server closed", "operational"])

                if is_connection_error and attempt == 0:
                    logger.warning(f"⚠️ PGVector connection error, retrying... ({e})")
                    # Dispose stale connections and let pool_pre_ping create fresh ones
                    self._engine.dispose()
                    continue

                logger.error(f"❌ Similarity search failed: {str(e)}")
                raise Exception(f"Similarity search failed: {str(e)}")

    def delete_documents(
        self,
        ids: Optional[List[str]] = None,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None
    ) -> bool:
        """
        Delete documents from pgvector by IDs or metadata filter.
        Uses direct SQL for filter-based deletion (fast and reliable).

        Args:
            ids: Optional list of document IDs to delete
            filter: Optional metadata filter for deletion (e.g. {"document_id": {"$eq": "..."}})
            namespace: Optional namespace (organization_id)

        Returns:
            bool: True if deletion was successful
        """
        try:
            if ids:
                self.vector_store.delete(ids=ids)
                logger.info(f"✅ Deleted {len(ids)} documents from pgvector")
            elif filter:
                # Direct SQL delete on langchain_pg_embedding using JSONB metadata filters
                # Much faster than the old approach (similarity_search with empty query + delete by IDs)
                from sqlalchemy import text

                # Build WHERE clauses from filter dict
                conditions = []
                params = {}

                # Add namespace to filter if provided
                if namespace:
                    filter["organization_id"] = {"$eq": namespace}

                for i, (key, value) in enumerate(filter.items()):
                    if isinstance(value, dict) and "$eq" in value:
                        param_name = f"val_{i}"
                        conditions.append(f"cmetadata->>'{key}' = :{param_name}")
                        params[param_name] = value["$eq"]

                if not conditions:
                    raise ValueError("Filter produced no valid conditions")

                # Get the collection UUID for this collection_name
                where_clause = " AND ".join(conditions)
                sql = text(f"""
                    DELETE FROM langchain_pg_embedding
                    WHERE collection_id = (
                        SELECT uuid FROM langchain_pg_collection
                        WHERE name = :collection_name
                    )
                    AND {where_clause}
                """)
                params["collection_name"] = self.vector_store.collection_name

                # Execute via the vector store's engine
                with self.vector_store._make_sync_session() as session:
                    result = session.execute(sql, params)
                    deleted_count = result.rowcount
                    session.commit()

                logger.info(f"✅ Deleted {deleted_count} embeddings from pgvector (direct SQL)")
            else:
                raise ValueError("Either ids or filter must be provided")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to delete documents from pgvector: {str(e)}")
            raise Exception(f"Failed to delete documents: {str(e)}")

    def delete_by_knowledge_base(self, kb_name: str) -> bool:
        """
        Delete all documents belonging to a knowledge base

        Args:
            kb_name: Knowledge base name

        Returns:
            bool: True if deletion was successful
        """
        try:
            return self.delete_documents(filter={"kb_name": {"$eq": kb_name}})
        except Exception as e:
            logger.error(f"❌ Failed to delete KB {kb_name}: {str(e)}")
            raise

    def delete_by_document_id(self, document_id: str, organization_id: Optional[str] = None) -> bool:
        """
        Delete all chunks belonging to a document

        Args:
            document_id: Document ID
            organization_id: Optional organization ID for filtering

        Returns:
            bool: True if deletion was successful
        """
        try:
            filter_dict = {"document_id": {"$eq": document_id}}
            if organization_id:
                filter_dict["organization_id"] = {"$eq": organization_id}

            return self.delete_documents(filter=filter_dict)
        except Exception as e:
            logger.error(f"❌ Failed to delete document {document_id}: {str(e)}")
            raise

    def get_retriever(
        self,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None
    ):
        """
        Get a LangChain retriever for RAG applications

        Args:
            k: Number of documents to retrieve
            filter: Optional metadata filter
            namespace: Optional namespace (organization_id)

        Returns:
            VectorStoreRetriever: LangChain retriever object
        """
        search_kwargs = {"k": k}

        # Add filter with namespace if provided
        search_filter = filter.copy() if filter else {}
        if namespace:
            search_filter["organization_id"] = {"$eq": namespace}

        if search_filter:
            search_kwargs["filter"] = search_filter

        retriever = self.vector_store.as_retriever(
            search_kwargs=search_kwargs
        )

        logger.info(f"✅ Created retriever with k={k}")
        return retriever


_pgvector_client = None

def get_pgvector_client() -> PGVectorClient:
    """
    Get or create PGVectorClient singleton instance.

    Returns:
        PGVectorClient: Singleton client instance
    """
    global _pgvector_client
    if _pgvector_client is None:
        _pgvector_client = PGVectorClient()
    return _pgvector_client
