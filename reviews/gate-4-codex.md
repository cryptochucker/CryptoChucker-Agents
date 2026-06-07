# Codex Gate 4 verdict (Stage 4: paper executor + fail-closed live-trading safety)

Reviewer: Codex CLI (`gpt-5.5`), read-only, reviewing `git diff <gate-3-commit>..HEAD`. Three rounds (safety-critical).
Controller also ran an independent live-gate probe each round.

## Round 1 -> CHANGES_REQUIRED
- BLOCKING: gate matched `true`/`false` case-insensitively, so `False`/`True` (capitalized) would enable live.
- BLOCKING: paper-mode paths copied env wholesale, materializing API keys before the gate decision.
- MEDIUM: exposure checked pre-entry not post-entry; `use_dip_filter` documented but not enforced; `FeesCfg` unvalidated.
- LOW: live-order test didn't assert `create_order` un-called.
- FIXED (commits ffdee59): exact lowercase match; credential reads moved to live branch; post-entry exposure;
  dip filter enforced (with df); FeesCfg validated via `_ExchangeFeeCfg`; hardened live-order test.

## Round 2 -> CHANGES_REQUIRED
- BLOCKING: credential isolation STILL violated on the default `env=None` path (`dict(os.environ)` copy loaded secrets in paper mode); tests only covered injected env.
- MEDIUM: net-of-fees profit-target exit slightly under target (fee applied to entry not exit notional).
- LOW: two partly-vacuous tests.
- FIXED (commit 7e41495): removed all `dict(os.environ)` copies; `live_enabled`/`make_exchange_client` read only the two
  gate keys by default and the 3 secret keys ONLY in the live branch; added default-path guard tests (a mapping that
  raises if a secret key is accessed in paper mode); corrected exit price to `entry*(1+target+t)/(1-t)`; hardened tests.

## Round 3 -> VERDICT: PASS
- No BLOCKING. Codex confirmed: double gate exact-lowercase only; default env reads only the two gate keys; paper client
  constructs with no credentials; `_live_order` calls `guard_live()` before `create_order`; tests non-vacuous with
  secret-access guards and `create_order.call_count == 0` assertions.
- MEDIUM (fixed post-pass, commit 360b17a): default config sizing (~33% notional) exceeded `max_exposure_pct` (15%) and
  would refuse every paper entry. Executor now CAPS position size to fit max exposure (sizes down, never up; skips only
  when no room) so paper trading actually fires for the Stage 6 smoke test. + precise net-PnL assertion.

Controller independent safety probe (each round): exact-lowercase gate, capitalized/garbage -> paper, paper client
unauthenticated, live client loads key only when both gates set, `guard_live` blocks when disabled - ALL PASS.

**RESULT: PASS - Stage 4 advances to Stage 5.**
