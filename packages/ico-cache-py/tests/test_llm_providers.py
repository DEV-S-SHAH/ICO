import pytest
from unittest.mock import MagicMock, patch
from ico_cache.rag.pipeline import RAGPipeline, validate_model_spec

class DummyEmbedder:
    def embed(self, text: str):
        return [0.1] * 384

class DummyVectorStore:
    async def search(self, collection: str, vector, query_filter, limit: int, score_threshold: float, **kwargs):
        class Hit:
            def __init__(self, payload):
                self.payload = payload
        return [
            Hit({"page_or_section": "Item 1A", "text": "Apple faces supply chain disruption risks.", "source_file": "AAPL_10-K_2025.htm"}),
            Hit({"page_or_section": "Item 7", "text": "Net sales increased 4% year-over-year.", "source_file": "AAPL_10-Q_2026.htm"}),
        ]

def test_model_validation():
    # Valid models
    validate_model_spec("ollama/qwen2.5:3b")
    validate_model_spec("gpt-4o-mini")
    validate_model_spec("anthropic/claude-3-haiku")

    # Invalid models
    with pytest.raises(ValueError):
        validate_model_spec("")
    with pytest.raises(ValueError):
        validate_model_spec("   ")

@pytest.mark.asyncio
async def test_provider_ollama():
    pipeline = RAGPipeline(
        dense_embedder=DummyEmbedder(),
        vector_store=DummyVectorStore(),
        model="ollama/qwen2.5:3b",
        api_base="http://localhost:11434"
    )

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="Supply chain disruptions are primary risks."))]

    with patch("litellm.completion", return_value=fake_resp) as mock_comp:
        ans, t_ret, t_gen, score, citations = await pipeline.generate("What are Apple's risks?")
        assert ans == "Supply chain disruptions are primary risks."
        assert len(citations) == 2
        assert "AAPL_10-K_2025.htm" in citations
        assert mock_comp.called
        assert mock_comp.call_args.kwargs["model"] == "ollama/qwen2.5:3b"
        assert mock_comp.call_args.kwargs["api_base"] == "http://localhost:11434"

@pytest.mark.asyncio
async def test_provider_gemini_defaults():
    pipeline = RAGPipeline(
        dense_embedder=DummyEmbedder(),
        vector_store=DummyVectorStore(),
        model="gemini/gemini-flash-latest",
        api_key="AQ.test-key",
        timeout=42.0,
        num_retries=5,
    )

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="Gemini grounded answer."))]

    with patch("litellm.completion", return_value=fake_resp) as mock_comp:
        ans, *_ = await pipeline.generate("What are Apple's risks?")
        assert ans == "Gemini grounded answer."
        kwargs = mock_comp.call_args.kwargs
        assert kwargs["model"] == "gemini/gemini-flash-latest"
        assert kwargs["api_key"] == "AQ.test-key"
        assert kwargs["timeout"] == 42.0
        assert kwargs["num_retries"] == 5


@pytest.mark.asyncio
async def test_provider_hosted_openai():
    pipeline = RAGPipeline(
        dense_embedder=DummyEmbedder(),
        vector_store=DummyVectorStore(),
        model="gpt-4o-mini",
        api_key="sk-test-key-mock"
    )

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="Hosted LLM answer grounded in SEC filings."))]

    with patch("litellm.completion", return_value=fake_resp) as mock_comp:
        ans, t_ret, t_gen, score, citations = await pipeline.generate("Summarize performance")
        assert ans == "Hosted LLM answer grounded in SEC filings."
        assert len(citations) == 2
        assert "AAPL_10-Q_2026.htm" in citations
        assert mock_comp.called
        assert mock_comp.call_args.kwargs["model"] == "gpt-4o-mini"
        assert mock_comp.call_args.kwargs["api_key"] == "sk-test-key-mock"
