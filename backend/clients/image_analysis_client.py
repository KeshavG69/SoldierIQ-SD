"""
Image Analysis Client supporting multiple vision LLM providers
Supports: OpenRouter (Gemma) and Groq (Llama Vision)
Thread-safe implementation
"""

import base64
import threading
from typing import Optional
from pathlib import Path
from clients.ultimate_llm import get_llm
from app.logger import logger


class ImageAnalysisClient:
    """Thread-safe Image Analysis client supporting OpenRouter (Gemma) and Groq (Llama Vision)"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern with thread locking"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize Image Analysis client"""
        if not hasattr(self, '_initialized'):
            self._initialized = True
            logger.info("✅ Image Analysis client initialized")

    def analyze_image(self, file_content: bytes, filename: str) -> str:
        """
        Extract text and analyze image content using vision LLM

        Args:
            file_content: Image file content as bytes
            filename: Original filename

        Returns:
            Extracted text and description

        Raises:
            Exception: If analysis fails
        """
        try:
            # Encode image to base64
            image_base64 = base64.b64encode(file_content).decode('utf-8')

            # Get LLM from ultimate_llm (using OpenRouter)
            llm = get_llm(model="google/gemma-3-27b-it", provider="openrouter")

            # Create prompt with image
            from langchain_core.prompts import ChatPromptTemplate

            prompt = ChatPromptTemplate.from_messages([
                (
                    "system",
                    "Extract ALL information from this image with precise attention to structure and layout. "
                    "DO NOT include any opening statements, explanations, or closing remarks. "
                    "START AND END with the extracted content only. "
                    "\n\n"
                    "For text-based images:\n"
                    "- Maintain paragraph breaks, bullet points, and formatting\n"
                    "- For tables: preserve row/column structure using markdown table format\n"
                    "- For charts/diagrams: describe visual elements, explain relationships between components, identify trends, and extract all data points and labels\n"
                    "- For formulas/equations: reconstruct them accurately\n"
                    "- Always maintain the original spatial layout and reading order\n"
                    "- Identify headers, footers, page numbers, and other document elements\n"
                    "\n"
                    "For images with NO TEXT or minimal text:\n"
                    "- Provide an extremely detailed visual description of EVERYTHING you can see\n"
                    "- Describe objects, people, scenes, colors, composition, spatial relationships\n"
                    "- Include details about lighting, textures, backgrounds, foregrounds\n"
                    "- Describe any actions, emotions, or interactions visible\n"
                    "- Be thorough and comprehensive - leave nothing out\n"
                    "\n"
                    "This is a critical data extraction task - ensure ALL content (text or visual) is captured comprehensively."
                ),
                (
                    "user",
                    [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                )
            ])

            # Execute chain
            chain = prompt | llm
            response = chain.invoke({"image_data": image_base64})

            extracted_text = response.content
            logger.info(f"✅ Image analysis extracted {len(extracted_text)} chars from {filename}")
            return extracted_text

        except Exception as e:
            logger.error(f"❌ Image analysis failed for {filename}: {str(e)}")
            raise Exception(f"Image analysis failed: {str(e)}")

    @staticmethod
    def is_supported(extension: str) -> bool:
        """
        Check if file extension is supported for image analysis

        Args:
            extension: File extension with dot (e.g., '.png')

        Returns:
            True if supported
        """
        supported_formats = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".heic"]
        return extension.lower() in supported_formats


# Singleton instance
_image_analysis_client: Optional[ImageAnalysisClient] = None
_client_lock = threading.Lock()


def get_image_analysis_client() -> ImageAnalysisClient:
    """
    Get or create thread-safe ImageAnalysisClient singleton instance

    Returns:
        ImageAnalysisClient: Singleton client instance
    """
    global _image_analysis_client

    if _image_analysis_client is None:
        with _client_lock:
            if _image_analysis_client is None:
                _image_analysis_client = ImageAnalysisClient()

    return _image_analysis_client
