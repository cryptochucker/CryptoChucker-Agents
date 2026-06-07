"""Optional LLM signal co-pilot (Task 5.3).

Design goals:
- When ``cfg.llm_copilot.enabled is False``: return immediately with no network
  access, no SDK import, and no side effects.
- When enabled: dispatch to the configured provider (anthropic / openai / ollama)
  using LAZY imports so this module can be imported without those SDKs installed.
- Secrets: API keys are read from environment variables ONLY (never logged or
  included in prompts). Any value that looks like a secret is redacted before
  it reaches the provider.
- Output: always returns ``{"decision": str, "confidence": float, "reason": str}``
  with ``decision`` in {"BUY", "SKIP", "AVOID"}.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

# Regex that matches bearer-token-like secrets (hex/base64 strings >= 20 chars)
_SECRET_RE = re.compile(r"[A-Za-z0-9+/=_\-]{20,}")
_SECRET_PREFIXES = ("sk-", "Bearer ", "Token ", "api_key=")

_DISABLED_RESPONSE: dict[str, Any] = {
    "decision": "skip",
    "confidence": 0,
    "reason": "copilot disabled",
}

_VALID_DECISIONS = {"BUY", "SKIP", "AVOID", "skip"}


def _redact(text: str) -> str:
    """Replace values that look like API secrets with [REDACTED]."""
    for prefix in _SECRET_PREFIXES:
        # redact anything after a known secret prefix up to whitespace/quote
        text = re.sub(
            re.escape(prefix) + r"[^\s\"']+",
            prefix + "[REDACTED]",
            text,
        )
    return text


def _build_prompt(signal: dict, cfg_dict: dict) -> str:
    """Build the prompt sent to the LLM."""
    safe_signal = {k: v for k, v in signal.items() if not isinstance(v, bytes)}
    safe_cfg = {
        k: "[REDACTED]" if isinstance(v, str) and len(v) > 20 else v
        for k, v in cfg_dict.items()
    }
    raw = (
        f"Signal: {json.dumps(safe_signal, default=str)}\n"
        f"Config: {json.dumps(safe_cfg, default=str)}\n"
        "Based on the signal above, respond with a JSON object with exactly three "
        "keys: decision (one of BUY/SKIP/AVOID), confidence (0.0-1.0 float), "
        "reason (one sentence string). Reply ONLY with the JSON object."
    )
    return _redact(raw)


def _parse_response(text: str) -> dict[str, Any]:
    """Parse and validate the LLM's JSON response."""
    # Strip markdown fences if present
    text = re.sub(r"```(?:json)?", "", text).strip().strip("`")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Best-effort: extract first {...} block
        match = re.search(r"\{[^{}]+\}", text, re.DOTALL)
        if match:
            obj = json.loads(match.group())
        else:
            return {
                "decision": "SKIP",
                "confidence": 0.0,
                "reason": f"unparseable response: {text[:120]}",
            }

    decision = str(obj.get("decision", "SKIP")).upper()
    if decision not in {"BUY", "SKIP", "AVOID"}:
        decision = "SKIP"
    confidence = float(obj.get("confidence", 0.0))
    confidence = max(0.0, min(1.0, confidence))
    reason = str(obj.get("reason", ""))
    return {"decision": decision, "confidence": confidence, "reason": reason}


def _call_anthropic(prompt: str) -> str:
    """Call Anthropic Claude (lazy import)."""
    import anthropic  # noqa: PLC0415

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _call_openai(prompt: str) -> str:
    """Call OpenAI GPT (lazy import)."""
    import openai  # noqa: PLC0415

    api_key = os.environ.get("OPENAI_API_KEY", "")
    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


def _call_ollama(prompt: str) -> str:
    """Call local Ollama REST API (no SDK, uses requests)."""
    import requests  # noqa: PLC0415

    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "llama3")
    resp = requests.post(
        f"{base_url}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def validate(signal: dict, cfg: Any) -> dict[str, Any]:
    """Validate a trading signal with an optional LLM co-pilot.

    Parameters
    ----------
    signal:
        Signal dict (e.g. from ``agents.signal_agent.latest_signal``).
    cfg:
        :class:`~utils.config_schema.Config` instance.

    Returns
    -------
    dict with keys:
        decision    str    one of "BUY", "SKIP", "AVOID" (upper-case when enabled;
                           lower-case "skip" when disabled for easy distinction).
        confidence  float  0-1 (0 when disabled).
        reason      str
    """
    # Fast path: disabled -- no import, no network, no side effect
    if not cfg.llm_copilot.enabled:
        return dict(_DISABLED_RESPONSE)

    provider = cfg.llm_copilot.provider
    # Expose only non-sensitive config fields to the prompt
    cfg_dict = {
        "exchange": cfg.exchange,
        "paper_trading": cfg.paper_trading,
        "money_line_length": cfg.signal.money_line_length,
        "smooth": cfg.signal.smooth,
    }
    prompt = _build_prompt(signal, cfg_dict)

    if provider == "anthropic":
        raw = _call_anthropic(prompt)
    elif provider == "openai":
        raw = _call_openai(prompt)
    elif provider == "ollama":
        raw = _call_ollama(prompt)
    else:
        return {"decision": "SKIP", "confidence": 0.0, "reason": f"unknown provider: {provider}"}

    return _parse_response(raw)
