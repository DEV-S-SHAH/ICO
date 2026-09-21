"""Tests for LLM and agent framework adapters."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from intelligent_cache import (
    IntelligentCache,
    wrap_openai,
    wrap_anthropic,
    wrap_gemini,
    IntelligentCacheLangChain,
    IntelligentCacheLlamaIndex,
    AgentCache,
)


def test_openai_adapter_sync():
    local_cache = IntelligentCache(similarity_threshold=0.80)
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Paris"))]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    calls = []
    def mock_create(*args, **kwargs):
        calls.append(1)
        return mock_resp

    mock_client.chat.completions.create = mock_create
    client = wrap_openai(mock_client, cache_instance=local_cache)

    # First call -> calls underlying mock
    r1 = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "What is the capital of France?"}],
    )
    assert r1.choices[0].message.content == "Paris"
    assert len(calls) == 1

    # Second call -> hits cache, underlying mock NOT called
    r2 = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "What is the capital of France?"}],
    )
    assert r2.choices[0].message.content == "Paris"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_openai_adapter_async():
    local_cache = IntelligentCache(similarity_threshold=0.80)
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Async Paris"))]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    calls = []
    async def mock_async_create(*args, **kwargs):
        calls.append(1)
        return mock_resp

    mock_client.chat.completions.create = mock_async_create
    client = wrap_openai(mock_client, cache_instance=local_cache)

    r1 = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Async question"}],
    )
    assert r1.choices[0].message.content == "Async Paris"
    assert len(calls) == 1

    # Second call hits cache
    r2 = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Async question"}],
    )
    assert r2.choices[0].message.content == "Async Paris"
    assert len(calls) == 1


def test_anthropic_adapter_sync():
    local_cache = IntelligentCache(similarity_threshold=0.80)
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Claude response")]
    mock_msg.usage = MagicMock(input_tokens=15, output_tokens=25)

    calls = []
    def mock_create(*args, **kwargs):
        calls.append(1)
        return mock_msg

    mock_client.messages.create = mock_create
    client = wrap_anthropic(mock_client, cache_instance=local_cache)

    r1 = client.messages.create(
        model="claude-3-5-sonnet",
        messages=[{"role": "user", "content": "Explain relativity"}],
    )
    assert r1.content[0].text == "Claude response"
    assert len(calls) == 1

    r2 = client.messages.create(
        model="claude-3-5-sonnet",
        messages=[{"role": "user", "content": "Explain relativity"}],
    )
    assert r2.content[0].text == "Claude response"
    assert len(calls) == 1


def test_gemini_adapter_sync():
    local_cache = IntelligentCache(similarity_threshold=0.80)
    mock_model = MagicMock()
    mock_model.model_name = "gemini-1.5-pro"
    mock_resp = MagicMock()
    mock_resp.text = "Gemini response text"
    mock_resp.usage_metadata.prompt_token_count = 12
    mock_resp.usage_metadata.candidates_token_count = 20

    calls = []
    def mock_gen(*args, **kwargs):
        calls.append(1)
        return mock_resp

    mock_model.generate_content = mock_gen
    wrapped = wrap_gemini(mock_model, cache_instance=local_cache)

    r1 = wrapped.generate_content("What is photosynthesis?")
    assert r1.text == "Gemini response text"
    assert len(calls) == 1

    r2 = wrapped.generate_content("What is photosynthesis?")
    assert r2.text == "Gemini response text"
    assert len(calls) == 1


def test_langchain_adapter():
    local_cache = IntelligentCache(similarity_threshold=0.80)
    lc_cache = IntelligentCacheLangChain(cache_instance=local_cache, namespace="lc_test")

    # Initial lookup is None
    assert lc_cache.lookup("prompt 1", "llm_key") is None

    # Update
    lc_cache.update("prompt 1", "llm_key", "return text")

    # Second lookup is hit
    assert lc_cache.lookup("prompt 1", "llm_key") == "return text"

    # Clear
    lc_cache.clear()
    assert lc_cache.lookup("prompt 1", "llm_key") is None


def test_llamaindex_adapter():
    local_cache = IntelligentCache(similarity_threshold=0.80)
    adapter = IntelligentCacheLlamaIndex(cache_instance=local_cache)

    calls = []
    def mock_complete(*args, **kwargs):
        calls.append(1)
        return "llama response"

    mock_llm = MagicMock()
    mock_llm.complete = mock_complete
    wrapped = adapter.wrap_llm(mock_llm)

    res1 = wrapped.complete("Explain RAG")
    assert res1 == "llama response"
    assert len(calls) == 1

    res2 = wrapped.complete("Explain RAG")
    assert res2 == "llama response"
    assert len(calls) == 1


def test_agent_intermediate_step_cache():
    local_cache = IntelligentCache()
    agent_cache = AgentCache(cache_instance=local_cache)
    step_calls = 0

    @agent_cache.step(step_name="plan_generation", inputs="plan for trip to Japan")
    def generate_plan():
        nonlocal step_calls
        step_calls += 1
        return ["Day 1: Tokyo", "Day 2: Kyoto"]

    p1 = generate_plan()
    assert len(p1) == 2
    assert step_calls == 1

    p2 = generate_plan()
    assert len(p2) == 2
    assert step_calls == 1
