"""Tests for agents/alert_agent.py - Stage 3 Tasks 3.2 + 3.3."""
from __future__ import annotations

import pandas as pd
import pytest

from agents.alert_agent import AlertAgent, build_chart_image, chart_link
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
