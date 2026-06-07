# Money Scanner Pine v6 - compile verification

- **Indicator:** `CryptoChucker - Money Scanner v1` (`indicators/money_scanner_pine.txt`)
- **Tool:** TradingView server-side compiler via MCP `pine_check` (non-destructive: validates source without
  opening the editor or touching any saved script).

## Finding + fix
The first committed Money Scanner used **`math.tanh`**, which does **not exist in Pine v6** (`pine_check` error:
"Could not find ... 'math.tanh'" at the strength line). It would have failed on first paste. It also recomputed the
full Money Line chain 3-4x inside each of 30 `request.security` calls (heavy / near the per-indicator budget).

**Rewrite (now committed):**
- `tanh` implemented via `math.exp` with overflow clamping (`_tanh`).
- ONE `request.security` per symbol returning `[slope, atr]` (chain computed once), then bull/strength/flip derived
  on the chart side. 30 securities (within budget).
- Table rendered via a `for` loop over arrays instead of 150 hand-written `table.cell` lines.

## Result
`pine_check` => `compiled: true, error_count: 0, warning_count: 0`. **Money Scanner compiles clean.**
(Money Line `indicators/money_line_pine.txt` also re-verified clean: 0 errors, 0 warnings.)

Both indicators ship as committed, compile-verified source. They are added to TradingView via the manual paste steps
in the README (auto-deploy intentionally avoided after it previously overwrote an existing script slot).
