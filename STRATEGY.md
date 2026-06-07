# Money Line Signal Strategy

## Overview

The Money Line is a **volume-weighted, EMA-smoothed trend-line** that classifies
market state as BULLISH or BEARISH and emits flip signals when the trend reverses.
It is an **independent implementation** built from first principles using well-known
public-domain signal-processing building blocks (VWMA, EMA, ATR, MFI, RSI, ADX).

This file documents the mathematics transparently so the strategy can be audited,
reproduced, and reasoned about without reading the source code. The indicator is
not a clone of any proprietary product and makes no trademark or certification
claims.

---

## Step 1 -- Typical Price

```
tp[i] = (high[i] + low[i] + close[i]) / 3
```

The typical price is the standard anchor used in volume-weighted metrics
(see also: VWAP, MFI). It gives equal weight to the high, low, and close.

---

## Step 2 -- Volume-Weighted Moving Average (VWMA)

```
vwma[i] = sum(tp[j] * volume[j], j = i-length+1 .. i)
          / sum(volume[j],       j = i-length+1 .. i)
```

Parameter: `length` (default 8 bars).

This is a plain rolling VWMA. Bars with high volume pull the average toward
their typical price, giving the line a natural sensitivity to institutional
activity while filtering low-volume noise.

---

## Step 3 -- EMA Smoothing

```
ml[i] = EMA(vwma, span=smooth)[i]
```

Parameter: `smooth` (default 14 bars, exponential span).

The EMA removes high-frequency jitter from the VWMA so that state
classifications are stable. The span is applied with `adjust=False`
(recursive formula), matching the Pine v6 `ta.ema` definition.

---

## Step 4 -- Slope and State

```
slope[i] = SMA(ml[i] - ml[i-1], slope_len)[i]
state[i] = "BULLISH" if slope[i] >= 0 else "BEARISH"
```

Parameter: `slope_len` (default 3 bars).

The slope is the short-window average of first differences of the money
line. Using a short SMA rather than the raw difference reduces one-bar
reversals caused by rounding or data noise.

---

## Step 5 -- Flip Detection

```
flip_detected[i] = (state[i] != state[i-1])
```

A flip is recorded on the first bar where the state changes. This is the
primary entry/exit signal for the executor.

---

## Step 6 -- Signal Strength (0-100)

The composite strength score combines three normalized sub-signals:

### 6a. Slope normalized by ATR

```
atr[i]        = EWM(TR, alpha=1/14)[i]   # Wilder ATR
slope_norm[i] = |slope[i]| / atr[i]
contrib_slope = 40 * tanh(slope_norm * 8)
```

ATR normalization makes the slope unitless so that the contribution is
comparable across different-priced assets and volatility regimes. The
`tanh` squashes large values so the score saturates gracefully.

### 6b. Volume surge

```
vol_surge[i]   = volume[i] / SMA(volume, 20)[i]
contrib_volume = 30 * tanh(vol_surge - 1)
```

A surge value of 1 (flat volume) contributes 0. Bars with double the
average volume contribute close to 30, rewarding confirmation by
participation.

### 6c. Money Flow Index distance from 50

```
pos_mf[i]  = tp[i]*volume[i]  if tp[i] > tp[i-1]  else 0
neg_mf[i]  = tp[i]*volume[i]  if tp[i] < tp[i-1]  else 0
MFR[i]     = sum(pos_mf, 14) / sum(neg_mf, 14)
MFI[i]     = 100 - 100/(1 + MFR[i])
contrib_mfi = 30 * |MFI[i] - 50| / 50
```

MFI near 50 (balanced money flow) contributes 0. MFI at extremes (0 or
100) contributes the full 30, indicating strong directional money flow.

### 6d. Combination

```
raw[i]             = contrib_slope + contrib_volume + contrib_mfi
signal_strength[i] = clip(raw[i], 0, 100)
```

Maximum theoretical score is 100 (all three components maxed). A strength
above 55 is considered actionable for scanner ranking (configurable via
`scanner.min_strength`).

---

## Optional Gating Filters

These filters are applied at the `latest_signal()` layer (post-compute):

- **RSI filter** (`use_rsi_filter=True`): if RSI(14) >= `rsi_overbought` (default 70),
  the state is downgraded to BEARISH regardless of the money line direction.
  This avoids chasing extended rallies.

- **ADX filter** (`use_adx_filter=True`): if ADX(14) < `adx_min` (default 20),
  the state is downgraded to BEARISH. This requires a confirmed trend before
  classifying a bullish signal.

Both filters default to OFF so the raw money line signal is used by default.

---

## Multi-Timeframe Confirmation

`confirm(primary_df, confirm_df)` returns True only when both the primary and
confirmation timeframe DataFrames have a BULLISH state on their latest bar.
This reduces false flips in choppy markets.

---

## Pine v6 Equivalence

The file `indicators/money_line_pine.txt` implements Steps 1-5 faithfully in
Pine v6 using built-in functions:

| Python                  | Pine v6                          |
|-------------------------|----------------------------------|
| VWMA (rolling sum)      | `math.sum(tp*volume, n) / math.sum(volume, n)` |
| EMA (ewm span)          | `ta.ema(vwma, smooth)`           |
| slope SMA               | `ta.sma(ta.change(ml), slopeLen)` |
| flip up                 | `bull and not bull[1]`           |
| flip down               | `(not bull) and bull[1]`        |

The strength score (Step 6) is not rendered in the Pine indicator to keep
the overlay uncluttered; it is computed in Python for the scanner ranking
and paper executor.

---

## Parameter Guidance

| Parameter          | Default | Lower bound effect         | Upper bound effect          |
|--------------------|---------|----------------------------|-----------------------------|
| `length` (VWMA)    | 8       | More reactive, more noise  | Slower, misses quick moves  |
| `smooth` (EMA)     | 14      | Choppier line              | Very lagged                 |
| `slope_len`        | 3       | Faster flips               | Fewer, more filtered flips  |

All three are configurable in `config.yaml` under the `signal:` section.
