"""
Ultimate LLM Implementation - Simplified Multi-Provider Integration

This module provides a unified LLM implementation with:
- Support for OpenAI, OpenRouter, Groq, and FunctionGemma (Railway Ollama) providers
- Dual framework support (LangChain + Agno)
- Thread-safe singleton pattern
- Simple caching per provider

Author: Claude
"""

import threading
from typing import Optional, Literal
from langchain_openai import ChatOpenAI
from agno.models.openai import OpenAIChat
from app.logger import logger
from app.settings import settings

ProviderType = Literal["openai", "openrouter", "groq", "functiongemma"]


class UltimateLLM:
    """
    Simplified Ultimate LLM Implementation with Multi-Provider Support

    Features:
    - Support for OpenAI, OpenRouter, Groq, and FunctionGemma (Railway Ollama) providers
    - Dual framework support (LangChain + Agno)
    - Thread-safe singleton
    - Simple instance caching per provider
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        """Initialize UltimateLLM with multi-provider support"""
        if not hasattr(self, '_initialized'):
            # Provider configurations
            self.provider_configs = {
                "openai": {
                    "api_key": settings.OPENAI_API_KEY,
                    "base_url": None  # Use OpenAI default
                },
                "openrouter": {
                    "api_key": settings.OPENROUTER_API_KEY,
                    "base_url": "https://openrouter.ai/api/v1"
                },
                "groq": {
                    "api_key": settings.GROQ_API_KEY,
                    "base_url": "https://api.groq.com/openai/v1"
                },
                "functiongemma": {
                    "api_key": settings.FUNCTION_API_KEY,  # Dummy key for Railway Ollama
                    "base_url": "https://function-gemma-production.up.railway.app/v1"
                }
            }

            # Cache for instances per provider
            self._langchain_instances = {}
            self._agno_instances = {}
            self._instance_lock = threading.Lock()

            self._initialized = True
            logger.info("✅ UltimateLLM initialized with OpenAI, OpenRouter, Groq, and FunctionGemma support")

    def __new__(cls):
        """Singleton pattern with thread safety"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(UltimateLLM, cls).__new__(cls)
        return cls._instance

    def get_llm(
        self,
        model: str = "google/gemma-3-27b-it",
        provider: ProviderType = "openrouter"
    ) -> ChatOpenAI:
        """
        Get LangChain ChatOpenAI instance with specified provider

        Args:
            model: Model name (default: google/gemma-3-27b-it)
            provider: Provider to use ("openai", "openrouter", "groq", or "functiongemma", default: "openrouter")

        Returns:
            ChatOpenAI instance configured for the specified provider
        """
        if provider not in self.provider_configs:
            raise ValueError(f"Unsupported provider: {provider}. Choose 'openai', 'openrouter', 'groq', or 'functiongemma'")

        config = self.provider_configs[provider]
        if not config["api_key"]:
            raise ValueError(f"{provider.upper()}_API_KEY not configured in settings")

        cache_key = f"{provider}:{model}"

        with self._instance_lock:
            if cache_key not in self._langchain_instances:
                # Groq has lower max_tokens limit (8192)
                max_tokens = 8192 if provider == "groq" else 20000

                self._langchain_instances[cache_key] = ChatOpenAI(
                    model=model,
                    openai_api_key=config["api_key"],
                    openai_api_base=config["base_url"],
                    temperature=0,
                    max_tokens=max_tokens
                )
                logger.info(f"✅ Created LangChain instance: provider={provider}, model={model}, max_tokens={max_tokens}")

            return self._langchain_instances[cache_key]

    def get_llm_agno(
        self,
        model: str = "google/gemma-3-27b-it",
        provider: ProviderType = "openrouter"
    ) -> OpenAIChat:
        """
        Get Agno OpenAIChat instance with specified provider

        Args:
            model: Model name (default: google/gemma-3-27b-it)
            provider: Provider to use ("openai", "openrouter", "groq", or "functiongemma", default: "openrouter")

        Returns:
            OpenAIChat instance configured for the specified provider
        """
        if provider not in self.provider_configs:
            raise ValueError(f"Unsupported provider: {provider}. Choose 'openai', 'openrouter', 'groq', or 'functiongemma'")

        config = self.provider_configs[provider]
        if not config["api_key"]:
            raise ValueError(f"{provider.upper()}_API_KEY not configured in settings")

        cache_key = f"{provider}:{model}"

        with self._instance_lock:
            if cache_key not in self._agno_instances:
                # Groq has lower max_tokens limit (8192)
                max_tokens = 8192 if provider == "groq" else 10000

                # FunctionGemma on Railway CPU is very slow, needs longer timeout
                timeout = 300.0 if provider == "functiongemma" else 60.0  # 5 minutes for FunctionGemma

                self._agno_instances[cache_key] = OpenAIChat(
                    id=model,
                    api_key=config["api_key"],
                    base_url=config["base_url"],
                    temperature=0,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    retries=5,
                    exponential_backoff=True
                )
                logger.info(f"✅ Created Agno instance: provider={provider}, model={model}, max_tokens={max_tokens}, timeout={timeout}s")

            return self._agno_instances[cache_key]

    def clear_cache(self) -> None:
        """Clear cached instances"""
        with self._instance_lock:
            self._langchain_instances = {}
            self._agno_instances = {}
            logger.info("Cleared UltimateLLM instance cache")


# Global singleton instance
ultimate_llm = UltimateLLM()


# Convenience functions
def get_llm(
    model: str = "google/gemma-3-27b-it",
    provider: ProviderType = "openrouter"
) -> ChatOpenAI:
    """
    Get LangChain ChatOpenAI instance

    Args:
        model: Model name (default: google/gemma-3-27b-it)
        provider: Provider to use ("openai", "openrouter", "groq", or "functiongemma", default: "openrouter")

    Returns:
        ChatOpenAI instance
    """
    return ultimate_llm.get_llm(model=model, provider=provider)


def get_llm_agno(
    model: str = "google/gemma-3-27b-it",
    provider: ProviderType = "openrouter"
) -> OpenAIChat:
    """
    Get Agno OpenAIChat instance

    Args:
        model: Model name (default: google/gemma-3-27b-it)
        provider: Provider to use ("openai", "openrouter", "groq", or "functiongemma", default: "openrouter")

    Returns:
        OpenAIChat instance
    """
    return ultimate_llm.get_llm_agno(model=model, provider=provider)
