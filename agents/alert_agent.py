"""Alert agent: fans out signal events to enabled notification channels.

Transports
----------
- Telegram: HTTP Bot API via ``requests`` POST.
  Reads ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` from env by NAME.
- Discord: ``requests`` POST to ``DISCORD_WEBHOOK_URL``.
- Email: ``smtplib`` using ``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``,
  ``SMTP_PASSWORD``, and ``ALERT_EMAIL_TO`` env vars by NAME.

Chart image
-----------
``build_chart_image(df)`` renders a Plotly candlestick + Money Line chart and
returns PNG bytes via ``fig.to_image(format="png")`` (requires kaleido).  The
call is wrapped in ``try/except`` so that a missing or broken kaleido install
degrades gracefully to ``None``.  When image generation fails, ``send()``
includes a TradingView chart link in the message instead.

Security
--------
Transport functions accept env as a parameter so tests can inject a fake env
without touching ``os.environ``.  Secret values are NEVER logged or printed;
only the env var NAMES appear in log messages.  Exception messages are
sanitised via ``_safe_err`` before being logged so that tokens/webhook URLs
embedded by ``requests`` in error strings cannot leak.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests

from agents.scanner_agent import SignalEvent
from utils.config_schema import Config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Secret-redaction helpers (BLOCKING 1)
# ---------------------------------------------------------------------------


def _redact(text: str, *secrets: str) -> str:
    """Replace every non-empty secret value in *text* with ``***``."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _safe_err(exc: Exception, *secrets: str) -> str:
    """Return a sanitised error string that cannot leak *secrets*."""
    return f"{type(exc).__name__}: {_redact(str(exc), *secrets)}"


# ---------------------------------------------------------------------------
# Chart helpers (Task 3.3)
# ---------------------------------------------------------------------------


def build_chart_image(df) -> Optional[bytes]:
    """Render a Plotly candlestick + Money Line chart and return PNG bytes.

    Returns ``None`` if kaleido is unavailable or any error occurs (caller
    should fall back to ``chart_link``).
    """
    try:
        import plotly.graph_objects as go

        fig = go.Figure()

        # Candlestick trace
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name="Price",
                increasing_line_color="#26A69A",
                decreasing_line_color="#EF5350",
            )
        )

        # Money Line overlay (if present)
        if "money_line" in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df["money_line"],
                    mode="lines",
                    name="Money Line",
                    line={"color": "#00BCD4", "width": 2},
                )
            )

        fig.update_layout(
            template="plotly_dark",
            title="CryptoChucker Money Line",
            xaxis_rangeslider_visible=False,
            height=400,
            width=800,
            margin={"l": 40, "r": 20, "t": 40, "b": 40},
        )

        return fig.to_image(format="png")
    except Exception as exc:
        logger.debug("build_chart_image failed (best-effort): %s", exc)
        return None


def chart_link(symbol: str) -> str:
    """Return a TradingView chart URL for *symbol*.

    Strips the ``/`` separator (e.g. ``BTC/USDT`` -> ``BTCUSDT``) and
    constructs a BLOFIN perpetual link matching the project's default exchange.
    """
    clean = symbol.replace("/", "")
    return f"https://www.tradingview.com/chart/?symbol=BLOFIN%3A{clean}.P"


# ---------------------------------------------------------------------------
# Transport functions (module-level so monkeypatch can target them)
# ---------------------------------------------------------------------------


def _post_telegram(msg: str, cfg: Config, image_bytes: Optional[bytes] = None) -> None:
    """Send *msg* via the Telegram Bot HTTP API.

    Reads ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` from ``os.environ``
    by NAME.  Never logs or prints the token value.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("Telegram: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set (skipping)")
        return

    base_url = f"https://api.telegram.org/bot{token}"

    if image_bytes:
        try:
            requests.post(
                f"{base_url}/sendPhoto",
                data={"chat_id": chat_id, "caption": msg},
                files={"photo": ("chart.png", image_bytes, "image/png")},
                timeout=10,
            ).raise_for_status()
            return
        except Exception as exc:
            logger.warning(
                "Telegram sendPhoto failed, falling back to text: %s",
                _safe_err(exc, token),
            )

    try:
        requests.post(
            f"{base_url}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=10,
        ).raise_for_status()
    except Exception as exc:
        raise type(exc)(_safe_err(exc, token)) from None


def _post_discord(msg: str, cfg: Config, image_bytes: Optional[bytes] = None) -> None:
    """Send *msg* via a Discord webhook POST.

    Reads ``DISCORD_WEBHOOK_URL`` from ``os.environ`` by NAME.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("Discord: DISCORD_WEBHOOK_URL not set (skipping)")
        return

    if image_bytes:
        try:
            requests.post(
                webhook_url,
                data={"content": msg},
                files={"file": ("chart.png", image_bytes, "image/png")},
                timeout=10,
            ).raise_for_status()
            return
        except Exception as exc:
            logger.warning(
                "Discord file upload failed, falling back to text: %s",
                _safe_err(exc, webhook_url),
            )

    try:
        requests.post(webhook_url, json={"content": msg}, timeout=10).raise_for_status()
    except Exception as exc:
        raise type(exc)(_safe_err(exc, webhook_url)) from None


def _send_email(msg: str, cfg: Config, image_bytes: Optional[bytes] = None) -> None:
    """Send *msg* via SMTP.

    Reads ``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``, ``SMTP_PASSWORD``, and
    ``ALERT_EMAIL_TO`` from ``os.environ`` by NAME.

    When *image_bytes* is provided the PNG is attached as a MIME image part.
    Otherwise the chart link (already embedded in *msg* by ``send()``) serves
    as the fallback; for email we also repeat it explicitly in the body.
    """
    host = os.environ.get("SMTP_HOST", "")
    port_str = os.environ.get("SMTP_PORT", "587")
    user = os.environ.get("SMTP_USER", "")
    to_addr = os.environ.get("ALERT_EMAIL_TO", "")
    if not all([host, user, to_addr]):
        logger.warning("Email: SMTP_HOST, SMTP_USER, or ALERT_EMAIL_TO not set (skipping)")
        return

    try:
        port = int(port_str)
    except ValueError:
        port = 587

    password = os.environ.get("SMTP_PASSWORD", "")

    if image_bytes:
        # Multipart message: text body + PNG attachment
        outer = MIMEMultipart()
        outer["Subject"] = "CryptoChucker Alert"
        outer["From"] = user
        outer["To"] = to_addr
        outer.attach(MIMEText(msg, "plain"))
        img_part = MIMEImage(image_bytes, _subtype="png")
        img_part.add_header("Content-Disposition", "attachment", filename="chart.png")
        outer.attach(img_part)
        mime_str = outer.as_string()
    else:
        mime = MIMEText(msg, "plain")
        mime["Subject"] = "CryptoChucker Alert"
        mime["From"] = user
        mime["To"] = to_addr
        mime_str = mime.as_string()

    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            if password:
                server.login(user, password)
            server.sendmail(user, [to_addr], mime_str)
    except Exception as exc:
        sanitised = _redact(str(exc), password, user, host)
        raise type(exc)(sanitised) from None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _format_message(event: SignalEvent, link: Optional[str] = None) -> str:
    """Build the human-readable alert message for *event*."""
    flip_tag = " [FLIP]" if event.flip else ""
    lines = [
        f"CryptoChucker Alert{flip_tag}",
        f"Symbol   : {event.symbol}",
        f"Timeframe: {event.tf}",
        f"State    : {event.state}",
        f"Strength : {event.strength:.1f}",
        f"Price    : {event.price:.6g}",
        f"Time     : {event.ts}",
    ]
    if link:
        lines.append(f"Chart    : {link}")
    return "\n".join(lines)


class AlertAgent:
    """Fan-out alert dispatcher.

    Parameters
    ----------
    cfg:
        Application config.  The ``alerts`` sub-model controls which channels
        are enabled and whether to attach chart images.
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    def send(self, event: SignalEvent, df=None) -> None:
        """Dispatch *event* to all enabled channels.

        Parameters
        ----------
        event:
            The SignalEvent to alert on.
        df:
            Optional OHLCV DataFrame (with ``money_line`` column) used to
            render a chart image.  When omitted or ``None``, image generation
            is skipped and the link fallback is used instead.

        Chart image behaviour (Task 3.3):
        - If ``cfg.alerts.send_chart_image`` is True AND ``df`` is provided,
          call ``build_chart_image(df)``.
        - If the call succeeds and returns bytes, pass them to each transport.
        - If it raises or returns None, include a ``chart_link`` URL in the
          message text instead (link fallback).
        - If ``send_chart_image`` is False or ``df`` is None, skip image
          generation entirely.
        """
        alerts_cfg = self._cfg.alerts
        image_bytes: Optional[bytes] = None
        # Always include the chart link in the message body as a minimum.
        link: str = chart_link(event.symbol)

        if alerts_cfg.send_chart_image and df is not None:
            try:
                image_bytes = build_chart_image(df)
            except Exception:
                image_bytes = None

            # If we have bytes the image carries visual context; link still shown.

        msg = _format_message(event, link=link)

        # Dispatch to enabled channels.
        # ``image_bytes`` is passed as a keyword arg only when not None so that
        # simple transport monkeypatches in tests (without image_bytes param) work
        # when called from send_chart_image=False paths.
        tg_kwargs = {"image_bytes": image_bytes} if image_bytes is not None else {}

        if alerts_cfg.telegram:
            try:
                _post_telegram(msg, self._cfg, **tg_kwargs)
            except Exception as exc:
                logger.error("Telegram alert failed: %s", exc)

        if alerts_cfg.discord:
            try:
                _post_discord(msg, self._cfg, **tg_kwargs)
            except Exception as exc:
                logger.error("Discord alert failed: %s", exc)

        if alerts_cfg.email:
            try:
                _send_email(msg, self._cfg, **tg_kwargs)
            except Exception as exc:
                logger.error("Email alert failed: %s", exc)
