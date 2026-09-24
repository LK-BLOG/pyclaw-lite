"""Config schema handling, capability tables and the request-shaping rules."""

from __future__ import annotations

import json

import pytest

from pyclaw import providers
from pyclaw.config import Config, validate


def test_config_seeds_itself_when_missing(tmp_path):
    path = tmp_path / "pyclaw.json"
    config = Config(path, tmp_path / "missing.example")
    assert path.exists()
    assert config.get("PORT") == 2469
    assert config.is_ready() is False


def test_legacy_keys_still_load(tmp_path):
    path = tmp_path / "pyclaw.json"
    path.write_text(json.dumps({"WEBUI_PORT": 9999, "WEBUI_EXEC_BLOCKED": ["curl | sh"],
                                "API_KEY": "k", "ENDPOINT": "https://x/v1"}), encoding="utf-8")
    config = Config(path)
    assert config.get("PORT") == 9999
    assert config.get("BLOCKED_EXTRA") == ["curl | sh"]
    assert config.is_ready() is True


def test_comments_are_allowed_in_the_example(tmp_path):
    example = tmp_path / "pyclaw.json.example"
    example.write_text('{\n  // a comment\n  "PORT": 1234, /* inline */ "MODEL": "m"\n}\n', encoding="utf-8")
    config = Config(tmp_path / "pyclaw.json", example)
    assert config.get("PORT") == 1234 and config.get("MODEL") == "m"


def test_update_persists_and_validates(tmp_path):
    config = Config(tmp_path / "pyclaw.json", tmp_path / "missing")
    config.update({"MODEL": "deepseek-flash", "COMPACT_THRESHOLD": 0.75})
    assert json.loads((tmp_path / "pyclaw.json").read_text(encoding="utf-8"))["MODEL"] == "deepseek-flash"
    with pytest.raises(ValueError):
        config.update({"APPROVAL_MODE": "whatever"})
    with pytest.raises(ValueError):
        config.update({"PORT": "not-a-number"})


def test_validate_checks_choices():
    assert validate("LANGUAGE", "en-US") == "en-US"
    with pytest.raises(ValueError):
        validate("LANGUAGE", "fr-FR")


def test_public_schema_is_localised(tmp_path):
    config = Config(tmp_path / "pyclaw.json", tmp_path / "missing")
    zh = {row["key"]: row for row in config.public("zh-CN")}
    en = {row["key"]: row for row in config.public("en-US")}
    assert zh["PORT"]["label"] == "端口" and en["PORT"]["label"] == "Port"
    assert "secret" in zh["API_KEY"]["flags"]


def test_alias_and_window_lookup():
    assert providers.canonical_model("deepseek-v4-flash") == "deepseek-flash"
    assert providers.context_window("deepseek-flash") == 1048576
    assert providers.context_window("deepseek-v4-flash-0731") == 1310720
    assert providers.context_window("kimi-k2.5") == 262144
    assert providers.context_window("totally-unknown") == providers.UNKNOWN_CONTEXT_WINDOW
    assert providers.context_window("whatever", configured=12345) == 12345


def test_deepseek_effort_mapping_matches_the_api_docs():
    tiers, mapping = providers.effort_tiers("deepseek")
    assert tiers == ["minimal", "low", "medium", "high", "xhigh", "max", "ultra"]
    assert mapping["minimal"] == "low" and mapping["medium"] == "high"
    assert mapping["xhigh"] == "high" and mapping["ultra"] == "max"
    assert providers.effort_tiers("none") == ([], {})


def test_thinking_payload_never_sends_off_as_reasoning_effort():
    class FakeProvider(providers.Provider):
        def __init__(self, mode):
            self.thinking_mode = mode

    extra, effort = FakeProvider("deepseek")._thinking_payload("off")
    assert extra == {"thinking": {"type": "disabled"}} and effort is None
    extra, effort = FakeProvider("deepseek")._thinking_payload("ultra")
    assert extra == {"thinking": {"type": "enabled"}} and effort == "max"
    assert FakeProvider("openai")._thinking_payload("high") == ({}, "high")
    assert FakeProvider("none")._thinking_payload("high") == ({}, None)


def test_reasoning_content_is_backfilled_for_deepseek():
    messages = [{"role": "assistant", "content": "x"}, {"role": "user", "content": "y"}]
    prepared = providers.Provider.prepare_messages(messages, "deepseek")
    assert prepared[0]["reasoning_content"] == ""
    assert providers.Provider.prepare_messages(messages, "none")[0].get("reasoning_content") is None


def test_error_classification():
    class Err(Exception):
        def __init__(self, status, message):
            super().__init__(message)
            self.status_code = status
            self.message = message

    assert providers.classify(Err(401, "bad key")).kind == "auth"
    assert providers.classify(Err(429, "slow down")).retryable is True
    assert providers.classify(Err(503, "down")).retryable is True
    overflow = providers.classify(Err(400, "This model's maximum context length is 65536 tokens"))
    assert overflow.overflow is True
    effort = providers.classify(Err(400, "UNSUPPORTED_REASONING_EFFORT"))
    assert effort.unsupported_effort is True
    assert providers.classify(Err(400, "bad field")).retryable is False


def test_usage_dict_normalises_cache_fields():
    class Usage:
        prompt_tokens = 100
        completion_tokens = 20
        prompt_cache_hit_tokens = 60
        prompt_tokens_details = None

    assert providers._usage_dict(Usage()) == {"prompt_tokens": 100, "completion_tokens": 20,
                                              "cache_hit_tokens": 60}
