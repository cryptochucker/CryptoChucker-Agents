# Codex Gate 3 verdict (Stage 3: scanner + alerts + Money Scanner Pine)

Reviewer: Codex CLI (`gpt-5.5`), read-only, reviewing `git diff <gate-2-commit>..HEAD`. Three rounds.

## Round 1 -> CHANGES_REQUIRED
- BLOCKING: Telegram/Discord exception logging could leak the token/webhook (they live in the request URL).
- BLOCKING: scanner emitted events regardless of flip (would spam stale states) instead of fresh Money Line flips.
- BLOCKING: incomplete per-symbol error isolation (one malformed symbol could abort the whole scan).
- MEDIUM: email never attached image/link; duplicate `UNIUSDT.P` in Pine; vacuous scanner tests; untyped blacklist/whitelist.
- FIXED (commit c84918c): redaction helpers + sanitized re-raise; flip-only gate; single per-symbol try/except;
  email link always included + MIME image; Pine deduped; deterministic scanner tests; `list[str]`.

## Round 2 -> CHANGES_REQUIRED
- BLOCKING: email/SMTP path still logged raw exceptions (SMTP_PASSWORD could leak).
- MEDIUM: `build_chart_image` ran even when df is None; fallback test didn't exercise the real path.
- MEDIUM: Money Scanner Pine declared user functions inside `if barstate.islast` (Pine needs them at global scope; would fail manual-add).
- LOW: volume filter used `<` (equality passed) instead of strict `>`.
- FIXED (commit 7a43ef8): `_send_email` catches + re-raises sanitized; skip image when df None + fixed tests; Pine
  functions moved to global scope; strict `>` volume filter + boundary test.

## Round 3 -> VERDICT: PASS
- All four secret-leak/scanner blockers confirmed resolved; no committed secret values.
- MEDIUM (fixed post-pass, commit a995553): scanner now honors `Config.signal` params (money_line_length/smooth/
  slope_len/RSI/ADX) and adds the spec'd VWAP price-position filter (`use_vwap_filter`, `vwap_length`).
- LOW: Codex could not run pytest (read-only sandbox); controller verified locally: 109 passed, ruff clean.

**RESULT: PASS - Stage 3 advances to Stage 4.**
