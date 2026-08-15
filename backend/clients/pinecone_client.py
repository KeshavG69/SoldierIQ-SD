"""
Pinecone Vector Database Client
Uses LangChain for vector storage and retrieval operations
"""

from typing import Optional, List, Dict, Any
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from pinecone.grpc import PineconeGRPC as Pinecone  # Use gRPC to avoid thread pools
from pinecone import ServerlessSpec  # ServerlessSpec is in main module
from app.settings import settings
from app.logger import logger
from clients.ultimate_llm import get_llm


class PineconeClient:
    """Client for Pinecone vector database operations using LangChain"""

    def __init__(self):
        """Initialize Pinecone client with gRPC (no threading issues)"""
        self.api_key = settings.PINECONE_API_KEY
        self.index_name = settings.PINECONE_INDEX_NAME
        self.embedding_model = settings.OPENAI_API_KEY

        if not self.api_key:
            raise ValueError("PINECONE_API_KEY not configured")
        if not self.index_name:
            raise ValueError("PINECONE_INDEX_NAME not configured")
        if not self.embedding_model:
            raise ValueError("OPENAI_API_KEY not configured for embeddings")

        # Initialize Pinecone with gRPC (avoids ThreadPool issues in Celery)
        self.pc = Pinecone(api_key=self.api_key)

        logger.info("✅ Pinecone gRPC client initialized (no threading issues)")

        # Initialize OpenAI embeddings
        self.embeddings = OpenAIEmbeddings(
            openai_api_key=self.embedding_model,
            model="text-embedding-3-small"
        )

        # Check if index exists, create if not
        self._ensure_index_exists()

        # Initialize LangChain vector store
        self.vector_store = PineconeVectorStore(
            index_name=self.index_name,
            embedding=self.embeddings
        )

        logger.info(f"✅ Pinecone client initialized with index: {self.index_name}")

    def cleanup(self):
        """Clean up Pinecone client resources (gRPC handles cleanup automatically)"""
        try:
            # gRPC client handles cleanup automatically, no manual intervention needed
            logger.info("✅ Cleaned up Pinecone client")
        except Exception as e:
            logger.warning(f"Error cleaning up Pinecone client: {str(e)}")

    def _summarize_large_text(self, text: str, max_bytes: int = 30000) -> str:
        """
        Summarize text using LLM when it's too large for Pinecone metadata

        Args:
            text: The text to summarize
            max_bytes: Max byte size before summarization (default: 30KB, leaves 10KB buffer)

        Returns:
            Summarized text or original if under max_bytes
        """
        text_bytes = len(text.encode('utf-8'))

        # Only summarize if text exceeds 30KB (Pinecone has 40KB limit, we use 30KB for safety)
        if text_bytes <= max_bytes:
            return text

        try:
            # Use gpt-4.1-mini for fast, cheap summarization
            llm = get_llm(model="gpt-4.1-mini", provider="openai")

            prompt = f"""Summarize the following text concisely while preserving key information and context.
Keep the summary under 3000 characters.

Text:
{text}
...
"""

            response = llm.invoke(prompt)
            summary = response.content

            logger.info(f"✅ Summarized text from {text_bytes} bytes ({len(text)} chars) to {len(summary.encode('utf-8'))} bytes ({len(summary)} chars) using LLM")
            return summary

        except Exception as e:
            logger.error(f"❌ Failed to summarize text with LLM: {str(e)}")
            # Fallback to truncation if LLM summarization fails
            logger.warning("⚠️  Falling back to text truncation")
            # Truncate at byte level to fit within limit
            truncated_bytes = text.encode('utf-8')[:max_bytes]
            return truncated_bytes.decode('utf-8', errors='ignore')

    def _ensure_index_exists(self):
        """Ensure Pinecone index exists, create if not"""
        try:
            existing_indexes = [index.name for index in self.pc.list_indexes()]

            if self.index_name not in existing_indexes:
                logger.info(f"Creating new Pinecone index: {self.index_name}")

                # Create index with serverless spec
                self.pc.create_index(
                    name=self.index_name,
                    dimension=1536,  # OpenAI text-embedding-3-small dimension
                    metric="cosine",
                    spec=ServerlessSpec(
                        cloud="aws",
                        region="us-east-1"
                    )
                )

                logger.info(f"✅ Pinecone index created: {self.index_name}")
            else:
                logger.info(f"✅ Pinecone index exists: {self.index_name}")

        except Exception as e:
            logger.error(f"❌ Failed to ensure index exists: {str(e)}")
            raise

    def add_documents(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: Optional[List[str]] = None,
        namespace: Optional[str] = None
    ) -> List[str]:
        """
        Add documents to Pinecone using direct gRPC client (bypasses LangChain's REST API)

        Args:
            texts: List of text chunks to embed and store
            metadatas: List of metadata dicts for each text chunk
            ids: Optional list of IDs for each document
            namespace: Optional namespace for multi-tenancy (e.g., organization_id)

        Returns:
            List[str]: List of document IDs

        Raises:
            Exception: If adding documents fails
        """
        try:
            import uuid

            # Generate IDs if not provided
            if not ids:
                ids = [str(uuid.uuid4()) for _ in texts]

            # Generate embeddings using OpenAI
            logger.info(f"Generating embeddings for {len(texts)} documents...")
            embeddings = self.embeddings.embed_documents(texts)

            # Get gRPC index directly (no ThreadPool creation)
            index = self.pc.Index(self.index_name)

            # Prepare vectors for upsert with text stored in metadata
            # NOTE: Pinecone has a 40KB limit for metadata per vector
            # We use LLM summarization for large texts, but the FULL text was already
            # used to generate the embedding, so semantic search quality is not affected
            vectors = []
            for doc_id, text, embedding, metadata in zip(ids, texts, embeddings, metadatas):
                # Summarize text if it's too large for Pinecone metadata (40KB limit)
                # Use 30KB threshold to leave 10KB buffer for other metadata
                processed_text = self._summarize_large_text(text, max_bytes=30000)

                # Store the processed text in metadata for LangChain compatibility
                metadata_with_text = {**metadata, "text": processed_text}

                vectors.append({
                    "id": doc_id,
                    "values": embedding,
                    "metadata": metadata_with_text
                })

            # Batch upsert to avoid gRPC 4MB message size limit
            batch_size = 100  # Upsert 100 vectors at a time
            total_vectors = len(vectors)

            logger.info(f"Upserting {total_vectors} vectors to Pinecone via gRPC (batch size: {batch_size})...")

            for i in range(0, total_vectors, batch_size):
                batch = vectors[i:i + batch_size]
                index.upsert(
                    vectors=batch,
                    namespace=namespace or ""
                )
                logger.info(f"  ✓ Upserted batch {i // batch_size + 1}/{(total_vectors + batch_size - 1) // batch_size} ({len(batch)} vectors)")

            logger.info(f"✅ Added {len(ids)} documents to Pinecone via gRPC (namespace: {namespace or 'default'})")
            return ids

        except Exception as e:
            logger.error(f"❌ Failed to add documents to Pinecone: {str(e)}")
            raise Exception(f"Failed to add documents: {str(e)}")

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None
    ) -> List[Document]:
        """
        Search for similar documents using semantic similarity

        Args:
            query: Query text
            k: Number of results to return
            filter: Optional metadata filter
            namespace: Optional namespace for multi-tenancy

        Returns:
            List[Document]: List of similar documents with metadata

        Raises:
            Exception: If search fails
        """
        try:
            # Create vector store with namespace if provided
            if namespace:
                vector_store = PineconeVectorStore(
                    index_name=self.index_name,
                    embedding=self.embeddings,
                    namespace=namespace
                )
            else:
                vector_store = self.vector_store

            if filter:
                results = vector_store.similarity_search(
                    query,
                    k=k,
                    filter=filter
                )
            else:
                results = vector_store.similarity_search(query, k=k)

            logger.info(f"✅ Found {len(results)} similar documents (namespace: {namespace or 'default'})")
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
            namespace: Optional namespace for multi-tenancy

        Returns:
            List[tuple]: List of (Document, score) tuples

        Raises:
            Exception: If search fails
        """
        try:
            # Ensure k is a valid integer
            if k is None or k < 1:
                k = 5
                logger.warning(f"Invalid k value, using default: {k}")

            logger.debug(f"Similarity search: query='{query[:50]}...', k={k}, filter={filter}, namespace={namespace}")

            # Create vector store with namespace if provided
            if namespace:
                vector_store = PineconeVectorStore(
                    index_name=self.index_name,
                    embedding=self.embeddings,
                    namespace=namespace
                )
            else:
                vector_store = self.vector_store

            if filter:
                results = vector_store.similarity_search_with_score(
                    query,
                    k=k,
                    filter=filter
                )
            else:
                results = vector_store.similarity_search_with_score(query, k=k)

            logger.info(f"✅ Found {len(results)} similar documents with scores (namespace: {namespace or 'default'})")
            return results

        except Exception as e:
            logger.error(f"❌ Similarity search with score failed: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Similarity search failed: {str(e)}")

    def delete_documents(
        self,
        ids: Optional[List[str]] = None,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None
    ) -> bool:
        """
        Delete documents from Pinecone by IDs or filter

        Args:
            ids: Optional list of document IDs to delete
            filter: Optional metadata filter for deletion
            namespace: Optional namespace for multi-tenancy

        Returns:
            bool: True if deletion was successful

        Raises:
            Exception: If deletion fails
        """
        try:
            index = self.pc.Index(self.index_name)

            if ids:
                if namespace:
                    index.delete(ids=ids, namespace=namespace)
                else:
                    index.delete(ids=ids)
                logger.info(f"✅ Deleted {len(ids)} documents from Pinecone (namespace: {namespace or 'default'})")
            elif filter:
                if namespace:
                    index.delete(filter=filter, namespace=namespace)
                else:
                    index.delete(filter=filter)
                logger.info(f"✅ Deleted documents matching filter from Pinecone (namespace: {namespace or 'default'})")
            else:
                raise ValueError("Either ids or filter must be provided")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to delete documents from Pinecone: {str(e)}")
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
            return self.delete_documents(filter={"kb_name": kb_name})
        except Exception as e:
            logger.error(f"❌ Failed to delete KB {kb_name}: {str(e)}")
            raise

    def delete_by_document_id(self, document_id: str) -> bool:
        """
        Delete all chunks belonging to a document

        Args:
            document_id: Document ID

        Returns:
            bool: True if deletion was successful
        """
        try:
            return self.delete_documents(filter={"document_id": document_id})
        except Exception as e:
            logger.error(f"❌ Failed to delete document {document_id}: {str(e)}")
            raise

    def get_retriever(self, k: int = 5, filter: Optional[Dict[str, Any]] = None):
        """
        Get a LangChain retriever for RAG applications

        Args:
            k: Number of documents to retrieve
            filter: Optional metadata filter

        Returns:
            VectorStoreRetriever: LangChain retriever object
        """
        search_kwargs = {"k": k}
        if filter:
            search_kwargs["filter"] = filter

        retriever = self.vector_store.as_retriever(
            search_kwargs=search_kwargs
        )

        logger.info(f"✅ Created retriever with k={k}")
        return retriever

    def update_metadata_by_filter(
        self,
        filter: Dict[str, Any],
        new_metadata: Dict[str, Any],
        namespace: Optional[str] = None
    ) -> int:
        """
        Update metadata for all vectors matching a filter

        Args:
            filter: Metadata filter to find vectors (e.g., {"folder_name": "old_name"})
            new_metadata: New metadata to set (e.g., {"folder_name": "new_name"})
            namespace: Optional namespace

        Returns:
            int: Number of vectors updated
        """
        try:
            index = self.pc.Index(self.index_name)

            # Query to get all matching vector IDs
            # We need to do a dummy query with high top_k to get IDs
            # Pinecone doesn't have a direct "list by filter" API, so we query with a zero vector

            logger.info(f"Querying Pinecone with filter: {filter}")

            # Create a dummy zero vector for querying
            dummy_vector = [0.0] * 1536  # text-embedding-3-small dimension

            # Query with filter to get matching IDs
            # Use very high top_k to get all matches
            query_response = index.query(
                vector=dummy_vector,
                filter=filter,
                top_k=10000,  # Pinecone max
                namespace=namespace,
                include_metadata=False  # We only need IDs
            )

            matches = query_response.get('matches', [])
            vector_ids = [match['id'] for match in matches]

            if not vector_ids:
                logger.warning(f"No vectors found matching filter: {filter}")
                return 0

            logger.info(f"Found {len(vector_ids)} vectors to update")

            # Update each vector's metadata
            updated_count = 0
            for vec_id in vector_ids:
                try:
                    index.update(
                        id=vec_id,
                        set_metadata=new_metadata,
                        namespace=namespace
                    )
                    updated_count += 1
                except Exception as e:
                    logger.error(f"Failed to update vector {vec_id}: {str(e)}")

            logger.info(f"✅ Updated metadata for {updated_count} vectors in Pinecone")
            return updated_count

        except Exception as e:
            logger.error(f"❌ Failed to update metadata by filter: {str(e)}")
            raise Exception(f"Failed to update metadata: {str(e)}")


def get_pinecone_client() -> PineconeClient:
    """
    Create a fresh PineconeClient instance (no caching to avoid multiprocessing issues in Celery)

    Returns:
        PineconeClient: Fresh client instance
    """
    return PineconeClient()
