"""Tests for utils/llm_copilot.py (Task 5.3)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from utils.config_schema import Config
from utils.llm_copilot import _parse_response, _redact, validate

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def disabled_cfg():
    """Config with LLM co-pilot disabled (default)."""
    cfg = Config()
    assert cfg.llm_copilot.enabled is False
    return cfg


@pytest.fixture
def enabled_anthropic_cfg():
    """Config with LLM co-pilot enabled, provider=anthropic."""
    cfg = Config()
    cfg.llm_copilot.enabled = True
    cfg.llm_copilot.provider = "anthropic"
    return cfg


@pytest.fixture
def enabled_openai_cfg():
    """Config with LLM co-pilot enabled, provider=openai."""
    cfg = Config()
    cfg.llm_copilot.enabled = True
    cfg.llm_copilot.provider = "openai"
    return cfg


@pytest.fixture
def enabled_ollama_cfg():
    """Config with LLM co-pilot enabled, provider=ollama."""
    cfg = Config()
    cfg.llm_copilot.enabled = True
    cfg.llm_copilot.provider = "ollama"
    return cfg


SAMPLE_SIGNAL = {
    "state": "BULLISH",
    "strength": 78.5,
    "flip": True,
    "price": 65432.10,
}


# ---------------------------------------------------------------------------
# Disabled path
# ---------------------------------------------------------------------------


def test_disabled_returns_skip_decision(disabled_cfg):
    result = validate(SAMPLE_SIGNAL, disabled_cfg)
    assert result["decision"] == "skip"


def test_disabled_returns_zero_confidence(disabled_cfg):
    result = validate(SAMPLE_SIGNAL, disabled_cfg)
    assert result["confidence"] == 0


def test_disabled_returns_copilot_disabled_reason(disabled_cfg):
    result = validate(SAMPLE_SIGNAL, disabled_cfg)
    assert "disabled" in result["reason"]


def test_disabled_makes_no_network_call(disabled_cfg):
    """Disabled path must not call any provider (no network, no import side-effects)."""
    with patch("utils.llm_copilot._call_anthropic") as mock_a, \
         patch("utils.llm_copilot._call_openai") as mock_o, \
         patch("utils.llm_copilot._call_ollama") as mock_l:
        validate(SAMPLE_SIGNAL, disabled_cfg)
        mock_a.assert_not_called()
        mock_o.assert_not_called()
        mock_l.assert_not_called()


def test_disabled_result_has_required_keys(disabled_cfg):
    result = validate(SAMPLE_SIGNAL, disabled_cfg)
    assert set(result.keys()) >= {"decision", "confidence", "reason"}


# ---------------------------------------------------------------------------
# Enabled path -- mocked providers
# ---------------------------------------------------------------------------

_VALID_JSON = '{"decision": "BUY", "confidence": 0.85, "reason": "Strong bullish signal."}'


def test_enabled_anthropic_returns_validated_dict(enabled_anthropic_cfg):
    with patch("utils.llm_copilot._call_anthropic", return_value=_VALID_JSON):
        result = validate(SAMPLE_SIGNAL, enabled_anthropic_cfg)
    assert result["decision"] in {"BUY", "SKIP", "AVOID"}
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(result["reason"], str)


def test_enabled_openai_returns_validated_dict(enabled_openai_cfg):
    with patch("utils.llm_copilot._call_openai", return_value=_VALID_JSON):
        result = validate(SAMPLE_SIGNAL, enabled_openai_cfg)
    assert result["decision"] in {"BUY", "SKIP", "AVOID"}
    assert 0.0 <= result["confidence"] <= 1.0


def test_enabled_ollama_returns_validated_dict(enabled_ollama_cfg):
    with patch("utils.llm_copilot._call_ollama", return_value=_VALID_JSON):
        result = validate(SAMPLE_SIGNAL, enabled_ollama_cfg)
    assert result["decision"] in {"BUY", "SKIP", "AVOID"}


def test_enabled_calls_correct_provider_anthropic(enabled_anthropic_cfg):
    with patch("utils.llm_copilot._call_anthropic", return_value=_VALID_JSON) as mock_a, \
         patch("utils.llm_copilot._call_openai") as mock_o, \
         patch("utils.llm_copilot._call_ollama") as mock_l:
        validate(SAMPLE_SIGNAL, enabled_anthropic_cfg)
        mock_a.assert_called_once()
        mock_o.assert_not_called()
        mock_l.assert_not_called()


def test_enabled_calls_correct_provider_openai(enabled_openai_cfg):
    with patch("utils.llm_copilot._call_openai", return_value=_VALID_JSON) as mock_o, \
         patch("utils.llm_copilot._call_anthropic") as mock_a:
        validate(SAMPLE_SIGNAL, enabled_openai_cfg)
        mock_o.assert_called_once()
        mock_a.assert_not_called()


def test_enabled_calls_correct_provider_ollama(enabled_ollama_cfg):
    with patch("utils.llm_copilot._call_ollama", return_value=_VALID_JSON) as mock_l, \
         patch("utils.llm_copilot._call_anthropic") as mock_a:
        validate(SAMPLE_SIGNAL, enabled_ollama_cfg)
        mock_l.assert_called_once()
        mock_a.assert_not_called()


# ---------------------------------------------------------------------------
# Schema validation (_parse_response)
# ---------------------------------------------------------------------------


def test_parse_response_valid_json():
    result = _parse_response(_VALID_JSON)
    assert result["decision"] == "BUY"
    assert result["confidence"] == pytest.approx(0.85)
    assert "bullish" in result["reason"].lower()


def test_parse_response_clamps_confidence_above_1():
    raw = '{"decision": "BUY", "confidence": 1.5, "reason": "test"}'
    result = _parse_response(raw)
    assert result["confidence"] == pytest.approx(1.0)


def test_parse_response_clamps_confidence_below_0():
    raw = '{"decision": "AVOID", "confidence": -0.3, "reason": "test"}'
    result = _parse_response(raw)
    assert result["confidence"] == pytest.approx(0.0)


def test_parse_response_invalid_decision_becomes_skip():
    raw = '{"decision": "HOLD", "confidence": 0.5, "reason": "test"}'
    result = _parse_response(raw)
    assert result["decision"] == "SKIP"


def test_parse_response_markdown_fence():
    raw = "```json\n" + _VALID_JSON + "\n```"
    result = _parse_response(raw)
    assert result["decision"] == "BUY"


def test_parse_response_unparseable_returns_skip():
    result = _parse_response("this is not json at all, sorry")
    assert result["decision"] == "SKIP"
    assert "unparseable" in result["reason"]


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def test_redact_removes_sk_prefix_secrets():
    text = "key=sk-abc123XYZveryLongSecret9876 done"
    redacted = _redact(text)
    assert "sk-abc123XYZveryLongSecret9876" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_leaves_short_strings_intact():
    text = "price=12345"
    result = _redact(text)
    assert result == text


def test_redact_bare_40char_hex_token():
    """BLOCKING 3 -- _SECRET_RE must catch bare long tokens without a prefix."""
    bare_secret = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"  # 40-char hex
    assert len(bare_secret) == 40
    signal = {"state": "BULLISH", "api_token": bare_secret}
    # Build the prompt text the same way _build_prompt would
    import json
    prompt_text = f"Signal: {json.dumps(signal)}"
    redacted = _redact(prompt_text)
    assert bare_secret not in redacted, (
        "Bare 40-char hex token should be redacted by _SECRET_RE"
    )
    assert "***" in redacted or "[REDACTED]" in redacted


def test_redact_bare_token_via_validate(enabled_anthropic_cfg):
    """End-to-end: bare secret in signal must be redacted before reaching provider."""
    from unittest.mock import patch as _patch

    bare_secret = "deadbeef1234567890abcdef1234567890abcdef"
    assert len(bare_secret) == 40

    captured: list[str] = []

    def fake_anthropic(prompt: str) -> str:
        captured.append(prompt)
        return '{"decision": "SKIP", "confidence": 0.5, "reason": "test"}'

    signal_with_secret = {**SAMPLE_SIGNAL, "raw_key": bare_secret}
    with _patch("utils.llm_copilot._call_anthropic", side_effect=fake_anthropic):
        validate(signal_with_secret, enabled_anthropic_cfg)

    assert captured, "Provider was not called"
    assert bare_secret not in captured[0], (
        "Bare secret reached the provider -- _SECRET_RE not applied in _redact()"
    )


# ---------------------------------------------------------------------------
# LOW 7 -- no SDK import when copilot is disabled
# ---------------------------------------------------------------------------


def test_no_sdk_import_when_disabled(disabled_cfg):
    """Calling validate() with copilot disabled must not import anthropic or openai."""
    import sys

    # Remove SDKs from sys.modules if they happen to be cached
    for mod in ("anthropic", "openai"):
        sys.modules.pop(mod, None)

    validate(SAMPLE_SIGNAL, disabled_cfg)

    assert "anthropic" not in sys.modules, "anthropic was imported despite copilot being disabled"
    assert "openai" not in sys.modules, "openai was imported despite copilot being disabled"
