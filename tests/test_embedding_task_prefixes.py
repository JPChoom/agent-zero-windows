"""Tests for models.py's embedding task-prefix handling.

Some embedding models are trained with task-instruction prefixes and
produce poorly-discriminated embeddings without them. Confirmed live with
nomic-embed-text-v1.5 via LM Studio: a completely unrelated query ("what
is the capital of France?") scored 0.69 similarity against a stored
memory about CSS gradients - nearly as high as genuinely related
queries - because raw, unprefixed text was being sent to the embedding
endpoint. Nomic's docs require "search_document: " when embedding
content for storage and "search_query: " when embedding a search query,
for every nomic-embed-* model.
"""

from __future__ import annotations

import models


def test_nomic_model_names_get_detected_regardless_of_provider_prefix():
    assert models._embedding_task_prefixes("lm_studio/text-embedding-nomic-embed-text-v1.5") == (
        "search_document: ",
        "search_query: ",
    )
    assert models._embedding_task_prefixes("nomic-embed-text-v1") == (
        "search_document: ",
        "search_query: ",
    )
    assert models._embedding_task_prefixes("NOMIC-EMBED-TEXT-V1.5") == (
        "search_document: ",
        "search_query: ",
    )


def test_unrelated_models_get_no_prefix():
    assert models._embedding_task_prefixes("huggingface/sentence-transformers/all-MiniLM-L6-v2") is None
    assert models._embedding_task_prefixes("openai/text-embedding-3-small") is None


def test_embed_documents_prepends_document_prefix_for_nomic(monkeypatch):
    captured = {}

    class _FakeItem:
        def __init__(self, vec):
            self.embedding = vec

    class _FakeResp:
        data = [_FakeItem([0.1, 0.2]), _FakeItem([0.3, 0.4])]

    def fake_embedding(model, input, **kwargs):
        captured["input"] = input
        return _FakeResp()

    monkeypatch.setattr(models, "embedding", fake_embedding)
    monkeypatch.setattr(models, "apply_rate_limiter_sync", lambda *a, **k: None)

    wrapper = models.LiteLLMEmbeddingWrapper(
        model="text-embedding-nomic-embed-text-v1.5", provider="lm_studio"
    )
    result = wrapper.embed_documents(["first doc", "second doc"])

    assert captured["input"] == ["search_document: first doc", "search_document: second doc"]
    assert result == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_query_prepends_query_prefix_for_nomic(monkeypatch):
    captured = {}

    class _FakeItem:
        embedding = [0.5, 0.6]

    class _FakeResp:
        data = [_FakeItem()]

    def fake_embedding(model, input, **kwargs):
        captured["input"] = input
        return _FakeResp()

    monkeypatch.setattr(models, "embedding", fake_embedding)
    monkeypatch.setattr(models, "apply_rate_limiter_sync", lambda *a, **k: None)

    wrapper = models.LiteLLMEmbeddingWrapper(
        model="text-embedding-nomic-embed-text-v1.5", provider="lm_studio"
    )
    result = wrapper.embed_query("hello")

    assert captured["input"] == ["search_query: hello"]
    assert result == [0.5, 0.6]


def test_embed_query_unchanged_for_models_without_known_prefixes(monkeypatch):
    captured = {}

    class _FakeItem:
        embedding = [0.7, 0.8]

    class _FakeResp:
        data = [_FakeItem()]

    def fake_embedding(model, input, **kwargs):
        captured["input"] = input
        return _FakeResp()

    monkeypatch.setattr(models, "embedding", fake_embedding)
    monkeypatch.setattr(models, "apply_rate_limiter_sync", lambda *a, **k: None)

    wrapper = models.LiteLLMEmbeddingWrapper(
        model="sentence-transformers/all-MiniLM-L6-v2", provider="huggingface"
    )
    wrapper.embed_query("hello")

    # No known prefix for this model - text must pass through unchanged.
    assert captured["input"] == ["hello"]
