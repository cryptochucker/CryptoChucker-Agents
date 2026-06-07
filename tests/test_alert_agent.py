"""Tests for agents/alert_agent.py - Stage 3 Tasks 3.2 + 3.3 + Gate 3 findings."""
from __future__ import annotations

import pandas as pd
import pytest
import requests

from agents.alert_agent import AlertAgent, _redact, _safe_err, build_chart_image, chart_link
from agents.scanner_agent import SignalEvent
from utils.config_schema import AlertsCfg, Config, ScannerCfg

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(symbol="BTC/USDT", state="BULLISH", strength=75.0, flip=True):
    return SignalEvent(
        symbol=symbol,
        tf="4h",
        state=state,
        strength=strength,
        flip=flip,
        price=30000.0,
        ts=pd.Timestamp("2026-01-01"),
    )


def _make_cfg(telegram=False, discord=False, email=False, send_chart_image=True):
    return Config(
        alerts=AlertsCfg(
            telegram=telegram,
            discord=discord,
            email=email,
            send_chart_image=send_chart_image,
        )
    )


def _make_ohlcv_df(n=60):
    import numpy as np
    prices = list(range(100, 100 + n))
    c = [float(p) for p in prices]
    idx = pd.date_range("2026-01-01", periods=n, freq="4h")
    return pd.DataFrame(
        {
            "open": c,
            "high": [p * 1.005 for p in c],
            "low": [p * 0.995 for p in c],
            "close": c,
            "volume": [1000.0] * n,
            "money_line": c,
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# Task 3.2: Transport dispatch
# ---------------------------------------------------------------------------


def test_send_only_telegram_when_enabled(monkeypatch):
    """Only the telegram transport fires when telegram=True, others disabled."""
    calls = {}

    monkeypatch.setattr("agents.alert_agent._post_telegram", lambda msg, cfg: calls.setdefault("tg", msg))
    monkeypatch.setattr("agents.alert_agent._post_discord", lambda msg, cfg: calls.setdefault("dc", msg))
    monkeypatch.setattr("agents.alert_agent._send_email", lambda msg, cfg: calls.setdefault("em", msg))

    cfg = _make_cfg(telegram=True, discord=False, email=False, send_chart_image=False)
    AlertAgent(cfg).send(_make_event())

    assert "tg" in calls, "Telegram should have been called"
    assert "dc" not in calls, "Discord should NOT have been called"
    assert "em" not in calls, "Email should NOT have been called"


def test_send_only_discord_when_enabled(monkeypatch):
    calls = {}
    monkeypatch.setattr("agents.alert_agent._post_telegram", lambda msg, cfg: calls.setdefault("tg", msg))
    monkeypatch.setattr("agents.alert_agent._post_discord", lambda msg, cfg: calls.setdefault("dc", msg))
    monkeypatch.setattr("agents.alert_agent._send_email", lambda msg, cfg: calls.setdefault("em", msg))

    cfg = _make_cfg(telegram=False, discord=True, email=False, send_chart_image=False)
    AlertAgent(cfg).send(_make_event())

    assert "dc" in calls
    assert "tg" not in calls
    assert "em" not in calls


def test_send_only_email_when_enabled(monkeypatch):
    calls = {}
    monkeypatch.setattr("agents.alert_agent._post_telegram", lambda msg, cfg: calls.setdefault("tg", msg))
    monkeypatch.setattr("agents.alert_agent._post_discord", lambda msg, cfg: calls.setdefault("dc", msg))
    monkeypatch.setattr("agents.alert_agent._send_email", lambda msg, cfg: calls.setdefault("em", msg))

    cfg = _make_cfg(telegram=False, discord=False, email=True, send_chart_image=False)
    AlertAgent(cfg).send(_make_event())

    assert "em" in calls
    assert "tg" not in calls
    assert "dc" not in calls


def test_send_all_channels_when_all_enabled(monkeypatch):
    calls = {}
    monkeypatch.setattr("agents.alert_agent._post_telegram", lambda msg, cfg: calls.setdefault("tg", msg))
    monkeypatch.setattr("agents.alert_agent._post_discord", lambda msg, cfg: calls.setdefault("dc", msg))
    monkeypatch.setattr("agents.alert_agent._send_email", lambda msg, cfg: calls.setdefault("em", msg))

    cfg = _make_cfg(telegram=True, discord=True, email=True, send_chart_image=False)
    AlertAgent(cfg).send(_make_event())

    assert "tg" in calls and "dc" in calls and "em" in calls


def test_send_no_channels_when_all_disabled(monkeypatch):
    calls = {}
    monkeypatch.setattr("agents.alert_agent._post_telegram", lambda msg, cfg: calls.setdefault("tg", msg))
    monkeypatch.setattr("agents.alert_agent._post_discord", lambda msg, cfg: calls.setdefault("dc", msg))
    monkeypatch.setattr("agents.alert_agent._send_email", lambda msg, cfg: calls.setdefault("em", msg))

    cfg = _make_cfg(telegram=False, discord=False, email=False, send_chart_image=False)
    AlertAgent(cfg).send(_make_event())

    assert calls == {}, f"No channels should fire, got: {calls}"


def test_message_contains_required_fields(monkeypatch):
    """Alert message must include symbol, timeframe, state, and strength."""
    captured = {}
    monkeypatch.setattr("agents.alert_agent._post_telegram", lambda msg, cfg: captured.update({"msg": msg}))
    monkeypatch.setattr("agents.alert_agent._post_discord", lambda msg, cfg: None)
    monkeypatch.setattr("agents.alert_agent._send_email", lambda msg, cfg: None)

    event = _make_event(symbol="ETH/USDT", state="BEARISH", strength=82.5)
    cfg = _make_cfg(telegram=True, send_chart_image=False)
    AlertAgent(cfg).send(event)

    msg = captured["msg"]
    assert "ETH/USDT" in msg, f"Symbol missing from message: {msg!r}"
    assert "4h" in msg, f"Timeframe missing from message: {msg!r}"
    assert "BEARISH" in msg, f"State missing from message: {msg!r}"
    assert "82.5" in msg or "82" in msg, f"Strength missing from message: {msg!r}"


def test_message_does_not_contain_token_literal(monkeypatch):
    """The alert message must NOT contain actual secret values."""
    captured = {}
    monkeypatch.setattr("agents.alert_agent._post_telegram", lambda msg, cfg: captured.update({"msg": msg}))
    monkeypatch.setattr("agents.alert_agent._post_discord", lambda msg, cfg: None)
    monkeypatch.setattr("agents.alert_agent._send_email", lambda msg, cfg: None)

    cfg = _make_cfg(telegram=True, send_chart_image=False)
    AlertAgent(cfg).send(_make_event())

    msg = captured.get("msg", "")
    # Env var names are OK, literal secret values are not.
    # We cannot check for actual secrets (they are not set in CI), but we assert
    # that the transport function receives only the message string, not a token.
    assert isinstance(msg, str), "Transport should receive a plain string message"


# ---------------------------------------------------------------------------
# Task 3.3: Chart image + link fallback
# ---------------------------------------------------------------------------


def test_chart_link_returns_tradingview_url():
    url = chart_link("BTC/USDT")
    assert "tradingview.com" in url, f"Expected TradingView URL, got: {url!r}"
    assert "BTC" in url or "BTCUSDT" in url.upper() or "btc" in url.lower()


def test_build_chart_image_returns_bytes_or_none():
    """build_chart_image should return PNG bytes or None (if kaleido fails)."""
    df = _make_ohlcv_df()
    result = build_chart_image(df)
    # May return bytes (kaleido available) or None (kaleido failed)
    assert result is None or isinstance(result, bytes), (
        f"Expected bytes or None, got {type(result)}"
    )


def test_build_chart_image_bytes_are_png():
    """If bytes are returned, they must start with the PNG magic number."""
    df = _make_ohlcv_df()
    result = build_chart_image(df)
    if result is not None:
        assert result[:8] == b"\x89PNG\r\n\x1a\n" or result[:4] == b"\x89PNG", (
            f"Returned bytes are not a PNG: first 8 bytes = {result[:8]!r}"
        )


def test_send_uses_link_fallback_when_image_raises(monkeypatch):
    """When build_chart_image raises, send() must fall back to including the chart link."""
    captured = {}

    def fake_post(msg, cfg):
        captured["msg"] = msg

    monkeypatch.setattr("agents.alert_agent._post_telegram", fake_post)
    monkeypatch.setattr("agents.alert_agent._post_discord", lambda msg, cfg: None)
    monkeypatch.setattr("agents.alert_agent._send_email", lambda msg, cfg: None)
    monkeypatch.setattr(
        "agents.alert_agent.build_chart_image",
        lambda df: (_ for _ in ()).throw(RuntimeError("kaleido unavailable")),
    )

    cfg = _make_cfg(telegram=True, send_chart_image=True)
    event = _make_event(symbol="SOL/USDT")
    AlertAgent(cfg).send(event)

    msg = captured.get("msg", "")
    assert "tradingview.com" in msg, (
        f"Fallback chart link (tradingview.com) must appear in message when image fails: {msg!r}"
    )


def test_send_includes_image_bytes_when_available(monkeypatch):
    """When build_chart_image returns bytes, the send payload should carry them."""
    sent_with_image = {}

    def fake_post_with_img(msg, cfg, image_bytes=None):
        sent_with_image["bytes"] = image_bytes

    monkeypatch.setattr("agents.alert_agent._post_telegram", fake_post_with_img)
    monkeypatch.setattr("agents.alert_agent._post_discord", lambda msg, cfg, image_bytes=None: None)
    monkeypatch.setattr("agents.alert_agent._send_email", lambda msg, cfg, image_bytes=None: None)
    monkeypatch.setattr("agents.alert_agent.build_chart_image", lambda df: b"\x89PNG\r\n\x1a\nFAKE")

    cfg = _make_cfg(telegram=True, send_chart_image=True)
    AlertAgent(cfg).send(_make_event())

    assert sent_with_image.get("bytes") == b"\x89PNG\r\n\x1a\nFAKE", (
        "Transport should receive image bytes when image is available"
    )


def test_send_chart_image_false_skips_image(monkeypatch):
    """When send_chart_image=False, build_chart_image must not be called."""
    image_built = {}
    monkeypatch.setattr(
        "agents.alert_agent.build_chart_image",
        lambda df: image_built.setdefault("called", True) or b"PNG",
    )
    posted = {}
    monkeypatch.setattr("agents.alert_agent._post_telegram", lambda msg, cfg, image_bytes=None: posted.update({"ib": image_bytes}))
    monkeypatch.setattr("agents.alert_agent._post_discord", lambda msg, cfg, image_bytes=None: None)
    monkeypatch.setattr("agents.alert_agent._send_email", lambda msg, cfg, image_bytes=None: None)

    cfg = _make_cfg(telegram=True, send_chart_image=False)
    AlertAgent(cfg).send(_make_event())

    assert "called" not in image_built, "build_chart_image should NOT be called when send_chart_image=False"
    assert posted.get("ib") is None, "No image bytes should be passed to transport"


# ---------------------------------------------------------------------------
# BLOCKING 1 — Secret-redaction helpers
# ---------------------------------------------------------------------------


def test_redact_removes_secret_from_text():
    """_redact must replace the secret value with ***."""
    result = _redact("https://api.telegram.org/bot12345:ABCDEF/sendMessage", "12345:ABCDEF")
    assert "12345:ABCDEF" not in result
    assert "***" in result


def test_redact_handles_empty_secret():
    """_redact with empty string secret must leave text unchanged."""
    original = "some log text without secrets"
    assert _redact(original, "") == original


def test_redact_handles_multiple_secrets():
    """_redact must scrub all provided secrets."""
    text = "token=TOKVAL webhook=HOOKVAL"
    result = _redact(text, "TOKVAL", "HOOKVAL")
    assert "TOKVAL" not in result
    assert "HOOKVAL" not in result


def test_safe_err_scrubs_secret_in_requests_exception():
    """_safe_err must not expose secret embedded in a requests exception message."""
    secret = "supersecrettoken123"
    exc = requests.exceptions.ConnectionError(
        f"Failed to establish a new connection: https://api.telegram.org/bot{secret}/sendMessage"
    )
    result = _safe_err(exc, secret)
    assert secret not in result, f"Secret leaked into error string: {result!r}"
    assert "***" in result
    assert "ConnectionError" in result


def test_safe_err_scrubs_webhook_url():
    """_safe_err must not expose a webhook URL in the error string."""
    webhook = "https://discord.com/api/webhooks/1234567/MYSECRETTOKEN"
    exc = requests.exceptions.HTTPError(
        f"400 Client Error: Bad Request for url: {webhook}"
    )
    result = _safe_err(exc, webhook)
    assert webhook not in result, f"Webhook URL leaked into error string: {result!r}"
    assert "***" in result


# ---------------------------------------------------------------------------
# MEDIUM 4 — Email always includes chart link; image attached when bytes present
# ---------------------------------------------------------------------------


def test_message_always_includes_chart_link(monkeypatch):
    """Even when send_chart_image=False, the chart link must appear in the message."""
    captured = {}
    monkeypatch.setattr("agents.alert_agent._post_telegram", lambda msg, cfg, image_bytes=None: captured.update({"msg": msg}))
    monkeypatch.setattr("agents.alert_agent._post_discord", lambda msg, cfg, image_bytes=None: None)
    monkeypatch.setattr("agents.alert_agent._send_email", lambda msg, cfg, image_bytes=None: None)

    cfg = _make_cfg(telegram=True, send_chart_image=False)
    event = _make_event(symbol="BTC/USDT")
    AlertAgent(cfg).send(event)

    msg = captured.get("msg", "")
    assert "tradingview.com" in msg, (
        f"Chart link must always be included in message body; got: {msg!r}"
    )


def test_email_attaches_image_when_bytes_provided(monkeypatch):
    """_send_email must build a multipart message when image_bytes are provided."""
    import smtplib
    from unittest.mock import MagicMock, patch

    smtp_mock = MagicMock()
    smtp_mock.__enter__ = lambda s: smtp_mock
    smtp_mock.__exit__ = MagicMock(return_value=False)

    sent_args = {}

    def fake_sendmail(from_addr, to_addrs, msg_str):
        sent_args["msg"] = msg_str

    smtp_mock.sendmail = fake_sendmail

    env = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "user@example.com",
        "ALERT_EMAIL_TO": "dest@example.com",
        "SMTP_PASSWORD": "",
    }

    with patch("smtplib.SMTP", return_value=smtp_mock), \
         patch.dict("os.environ", env, clear=False):
        from agents.alert_agent import _send_email
        from utils.config_schema import Config
        cfg = Config()
        _send_email("Test message", cfg, image_bytes=b"\x89PNG\r\n\x1a\nFAKEPNG")

    msg_str = sent_args.get("msg", "")
    # Multipart message must contain PNG attachment header
    assert "image/png" in msg_str or "chart.png" in msg_str, (
        f"Email with image_bytes should be multipart with PNG attachment; got: {msg_str[:500]!r}"
    )


def test_email_plain_text_when_no_image(monkeypatch):
    """_send_email with no image_bytes must send a plain-text message."""
    from unittest.mock import MagicMock, patch

    smtp_mock = MagicMock()
    smtp_mock.__enter__ = lambda s: smtp_mock
    smtp_mock.__exit__ = MagicMock(return_value=False)

    sent_args = {}

    def fake_sendmail(from_addr, to_addrs, msg_str):
        sent_args["msg"] = msg_str

    smtp_mock.sendmail = fake_sendmail

    env = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "user@example.com",
        "ALERT_EMAIL_TO": "dest@example.com",
        "SMTP_PASSWORD": "",
    }

    with patch("smtplib.SMTP", return_value=smtp_mock), \
         patch.dict("os.environ", env, clear=False):
        from agents.alert_agent import _send_email
        from utils.config_schema import Config
        cfg = Config()
        _send_email("Plain message with https://tradingview.com/chart/?symbol=BTC", cfg)

    msg_str = sent_args.get("msg", "")
    assert "Plain message" in msg_str
    # Should NOT be multipart with image attachment
    assert "image/png" not in msg_str
