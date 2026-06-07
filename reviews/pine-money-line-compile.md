# Money Line Pine v6 - compile verification

- **Indicator:** `CryptoChucker - Money Line v1`
- **Source:** `indicators/money_line_pine.txt` (committed)
- **Compile result (TradingView MCP `pine_smart_compile`):** `has_errors: false`, `errors: []` -> **COMPILES CLEAN**.
- **Chart add:** `study_added: false` (the known 2026 floating-dialog caveat; not auto-added to chart).

## Deployment decision (user, 2026-06-07)
Auto-new-slot deploy (`pine_new` + `pine_smart_compile`) proved unreliable: the save landed on an existing script slot
("JMS AI - Crypto Empire Conor v1") instead of creating a new slot, overwriting it. Per the user's decision, both
CryptoChucker Pine indicators **ship as compile-verified committed source + manual-add instructions in the README**.
No further automated writes to the user's TradingView scripts. The user restores the affected script via TradingView
version history.

## Manual-add steps (to go in README)
1. Pine Editor -> open a new script (or the name menu -> "New blank indicator").
2. Paste the contents of `indicators/money_line_pine.txt`.
3. Save (Ctrl+S), name it `CryptoChucker - Money Line v1`.
4. "Add to chart". It works on any symbol/timeframe.
