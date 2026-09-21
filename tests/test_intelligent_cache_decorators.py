"""Tests for decorators: @cache, @cache_tool, @cache_embeddings."""

import asyncio
import pytest
from intelligent_cache import (
    IntelligentCache,
    cache,
    cache_tool,
    cache_embeddings,
    CacheResult,
)


def test_sync_function_cache():
    local_cache = IntelligentCache(similarity_threshold=0.75)
    call_count = 0

    @cache(cache_instance=local_cache, namespace="test_sync_fn")
    def ask_llm(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"Response to: {prompt}"

    # First call -> compute
    res1 = ask_llm("What is Kubernetes?")
    assert call_count == 1
    assert "Kubernetes" in res1

    # Exact call -> hit
    res2 = ask_llm("What is Kubernetes?")
    assert call_count == 1
    assert res2 == res1

    # Semantic call -> hit
    res3 = ask_llm("What is kubernetes?")
    assert call_count == 1
    assert res3 == res1

    # Bypass cache -> compute
    res4 = ask_llm("What is Kubernetes?", bypass_cache=True)
    assert call_count == 2


@pytest.mark.asyncio
async def test_async_function_cache():
    local_cache = IntelligentCache(similarity_threshold=0.75)
    call_count = 0

    @cache(cache_instance=local_cache, namespace="test_async_fn")
    async def ask_llm_async(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"Async response to: {prompt}"

    res1 = await ask_llm_async("Explain neural networks")
    assert call_count == 1

    res2 = await ask_llm_async("Explain neural networks")
    assert call_count == 1
    assert res2 == res1

    res3 = await ask_llm_async("Explain neural networks", force_refresh=True)
    assert call_count == 2


def test_method_caching():
    local_cache = IntelligentCache(similarity_threshold=0.75)

    class LLMAssistant:
        def __init__(self, name: str):
            self.name = name
            self.calls = 0

        @cache(cache_instance=local_cache, namespace="assistant_methods")
        def query(self, prompt: str) -> str:
            self.calls += 1
            return f"[{self.name}] Answer: {prompt}"

    bot = LLMAssistant("Bot1")
    ans1 = bot.query("Hello")
    assert bot.calls == 1

    ans2 = bot.query("Hello")
    assert bot.calls == 1
    assert ans2 == ans1


def test_return_result_obj():
    local_cache = IntelligentCache(similarity_threshold=0.75)

    @cache(cache_instance=local_cache, return_result_obj=True)
    def generate(prompt: str) -> str:
        return "Generated answer"

    # First call (miss) returns CacheResult with is_hit=False
    r1 = generate("Prompt 1")
    assert isinstance(r1, CacheResult)
    assert r1.is_hit is False
    assert r1.value == "Generated answer"

    # Second call (hit) returns CacheResult with is_hit=True
    r2 = generate("Prompt 1")
    assert isinstance(r2, CacheResult)
    assert r2.is_hit is True
    assert r2.value == "Generated answer"


def test_cache_tool_deterministic():
    local_cache = IntelligentCache()
    calc_calls = 0

    @cache_tool(deterministic=True, cache_instance=local_cache)
    def calculator(expr: str) -> int:
        nonlocal calc_calls
        calc_calls += 1
        return eval(expr)  # safe in controlled test

    res1 = calculator("2 + 2")
    assert res1 == 4
    assert calc_calls == 1

    res2 = calculator("2 + 2")
    assert res2 == 4
    assert calc_calls == 1

    res3 = calculator("3 * 5")
    assert res3 == 15
    assert calc_calls == 2


def test_cache_embeddings_decorator():
    local_cache = IntelligentCache()
    embed_calls = 0

    @cache_embeddings(cache_instance=local_cache, model_name="mock_model")
    def mock_embed(text: str) -> list[float]:
        nonlocal embed_calls
        embed_calls += 1
        return [float(len(text)), 1.0, 0.0]

    v1 = mock_embed("Sample input text")
    assert embed_calls == 1

    v2 = mock_embed("Sample input text")
    assert embed_calls == 1
    assert v1 == v2
