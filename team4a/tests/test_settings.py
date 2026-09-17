"""Smoke tests for Task 1.1: configuration loads with defaults and honors
environment-variable overrides.
"""

from app.config.settings import Settings, get_settings


def test_defaults_match_official_requirements():
    settings = Settings(_env_file=None)

    assert settings.chunk_size == 512
    assert settings.chunk_overlap == 50
    assert settings.embedding_batch_size == 32
    assert settings.embedding_model_name == "all-MiniLM-L6-v2"
    assert settings.embedding_dimensions == 384
    assert settings.keyframe_interval_seconds == 30
    assert settings.publisher_retry_count == 3
    assert settings.publisher_initial_backoff_seconds == 2.0
    assert settings.pdf_max_size_mb == 200
    assert settings.pdf_max_pages == 5000
    assert settings.video_max_size_gb == 2
    assert settings.video_max_duration_hours == 4
    assert settings.youtube_default_language == "en"
    assert settings.celery_worker_concurrency == 10
    assert settings.celery_visibility_timeout_seconds == 60
    assert settings.qdrant_publish_batch_size == 100


def test_env_var_overrides(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE", "256")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "16")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.internal:6333")
    monkeypatch.setenv("REDIS_BROKER_URL", "redis://redis.internal:6379/0")

    settings = Settings(_env_file=None)

    assert settings.chunk_size == 256
    assert settings.embedding_batch_size == 16
    assert settings.qdrant_url == "http://qdrant.internal:6333"
    assert settings.redis_broker_url == "redis://redis.internal:6379/0"


def test_get_settings_is_cached():
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second
