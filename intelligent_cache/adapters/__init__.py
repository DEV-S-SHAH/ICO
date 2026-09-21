"""Adapters for LLMs, frameworks, and agent tools."""

from intelligent_cache.adapters.openai import wrap_openai
from intelligent_cache.adapters.anthropic import wrap_anthropic
from intelligent_cache.adapters.gemini import wrap_gemini
from intelligent_cache.adapters.langchain import IntelligentCacheLangChain
from intelligent_cache.adapters.llamaindex import IntelligentCacheLlamaIndex
from intelligent_cache.adapters.tool import AgentCache

__all__ = [
    "wrap_openai",
    "wrap_anthropic",
    "wrap_gemini",
    "IntelligentCacheLangChain",
    "IntelligentCacheLlamaIndex",
    "AgentCache",
]
