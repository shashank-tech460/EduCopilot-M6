"""Unit tests for app/core/config.py (Task 1.1 scope only).

These tests verify the configuration foundation itself -- default values,
environment-variable overrides, validation, and caching behavior. They do
not test any route, service, or domain model, since none exist yet
(Task 1.1 is scaffolding/config only).
"""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings


class TestDefaults:
    """Defaults must match the approved Final Architecture/Contract Checkpoint."""

    def test_qdrant_defaults_match_checkpoint(self):
        settings = Settings(_env_file=None)
        assert settings.qdrant_url == "http://localhost:6333"
        assert settings.qdrant_collection_name == "team4b_shared_production_chunks"
        assert settings.embedding_dimensions == 384
        assert settings.embedding_distance == "Cosine"
        assert settings.embedding_model_name == "all-MiniLM-L6-v2"

    def test_retrieval_config_defaults_match_official_spec(self):
        # Requirement 7.1: top_k default 5, score_threshold default 0.3,
        # search_mode default "hybrid".
        settings = Settings(_env_file=None)
        assert settings.default_top_k == 5
        assert settings.default_score_threshold == 0.3
        assert settings.default_search_mode == "hybrid"

    def test_conversation_defaults_match_official_spec(self):
        # Requirement 4.6: 30-minute default TTL. Requirement 5.3: last 5
        # turns by default.
        settings = Settings(_env_file=None)
        assert settings.session_ttl_minutes == 30
        assert settings.conversation_window_size == 5

    def test_evaluation_defaults_match_official_spec(self):
        # Requirement 8.2: batches up to 50 within 60 seconds.
        # Requirement 8.4: faithfulness < 0.5 flagged.
        settings = Settings(_env_file=None)
        assert settings.evaluation_batch_max_size == 50
        assert settings.evaluation_batch_timeout_seconds == 60.0
        assert settings.faithfulness_flag_threshold == 0.5

    def test_llm_and_redis_defaults(self):
        settings = Settings(_env_file=None)
        assert settings.ollama_url == "http://localhost:11434"
        assert settings.ollama_model_name == "llama3"
        assert settings.llm_generation_timeout_seconds == 15.0
        assert settings.redis_url == "redis://localhost:6379/0"

    def test_rrf_k_default(self):
        # Requirement 2.2 / Property 5 default k=60.
        settings = Settings(_env_file=None)
        assert settings.rrf_k == 60

    def test_vector_store_retry_defaults(self):
        # Requirement 1.5: retry up to 3 times with exponential backoff.
        settings = Settings(_env_file=None)
        assert settings.vector_store_retry_count == 3
        assert settings.vector_store_initial_backoff_seconds == 2.0


class TestEnvironmentOverrides:
    """Every setting must be overridable via environment variable."""

    def test_qdrant_url_overridable(self, monkeypatch):
        monkeypatch.setenv("QDRANT_URL", "http://qdrant.internal:6333")
        settings = Settings(_env_file=None)
        assert settings.qdrant_url == "http://qdrant.internal:6333"

    def test_qdrant_collection_name_overridable(self, monkeypatch):
        # Exercises the exact mechanism the approved checkpoint relies on:
        # Team 4A points its own QDRANT_COLLECTION_NAME env var at
        # whatever name Team 4B provisions, with no code change to either
        # service. This test only verifies Team 4B's side is overridable.
        monkeypatch.setenv("QDRANT_COLLECTION_NAME", "some_other_shared_name")
        settings = Settings(_env_file=None)
        assert settings.qdrant_collection_name == "some_other_shared_name"

    def test_embedding_dimensions_overridable_to_768(self, monkeypatch):
        # The official Team 4B spec permits 384 or 768; 384 is only the
        # default, not the only accepted value.
        monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
        settings = Settings(_env_file=None)
        assert settings.embedding_dimensions == 768

    def test_default_top_k_overridable(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_TOP_K", "10")
        settings = Settings(_env_file=None)
        assert settings.default_top_k == 10

    def test_case_insensitive_env_vars(self, monkeypatch):
        monkeypatch.setenv("qdrant_url", "http://lowercase-env:6333")
        settings = Settings(_env_file=None)
        assert settings.qdrant_url == "http://lowercase-env:6333"


class TestValidation:
    """Invalid configuration must fail fast at Settings construction."""

    def test_default_top_k_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            Settings(_env_file=None, default_top_k=0)

    def test_default_top_k_above_max_rejected(self):
        with pytest.raises(ValueError):
            Settings(_env_file=None, default_top_k=51)

    def test_default_score_threshold_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            Settings(_env_file=None, default_score_threshold=1.5)

    def test_default_score_threshold_negative_rejected(self):
        with pytest.raises(ValueError):
            Settings(_env_file=None, default_score_threshold=-0.1)

    def test_invalid_search_mode_rejected(self):
        with pytest.raises(ValueError):
            Settings(_env_file=None, default_search_mode="fuzzy")

    def test_invalid_distance_metric_rejected(self):
        with pytest.raises(ValueError):
            Settings(_env_file=None, embedding_distance="Manhattan")

    def test_invalid_log_level_rejected(self):
        with pytest.raises(ValueError):
            Settings(_env_file=None, log_level="VERBOSE")

    def test_log_level_normalized_to_uppercase(self):
        settings = Settings(_env_file=None, log_level="debug")
        assert settings.log_level == "DEBUG"

    def test_non_positive_embedding_dimensions_rejected(self):
        with pytest.raises(ValueError):
            Settings(_env_file=None, embedding_dimensions=0)

    def test_negative_vector_store_retry_count_rejected(self):
        with pytest.raises(ValueError):
            Settings(_env_file=None, vector_store_retry_count=-1)

    def test_evaluation_batch_max_size_must_be_positive(self):
        with pytest.raises(ValueError):
            Settings(_env_file=None, evaluation_batch_max_size=0)


class TestGetSettingsCaching:
    """get_settings() must cache, per its own documented contract."""

    def test_get_settings_returns_same_instance(self):
        get_settings.cache_clear()
        first = get_settings()
        second = get_settings()
        assert first is second

    def test_get_settings_cache_clear_allows_refetch(self, monkeypatch):
        get_settings.cache_clear()
        first = get_settings()

        monkeypatch.setenv("QDRANT_COLLECTION_NAME", "cache_test_collection")
        get_settings.cache_clear()
        second = get_settings()

        assert second.qdrant_collection_name == "cache_test_collection"
        assert first is not second

        get_settings.cache_clear()
