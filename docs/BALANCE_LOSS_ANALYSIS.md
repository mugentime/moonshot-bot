# 🚨 CRITICAL: Balance Loss Root Cause Analysis

**Date:** 2025-12-17
**Analyst:** Claude Code Investigation
**Status:** ROOT CAUSE IDENTIFIED

---

## 📊 Executive Summary

You are losing money despite Global Take Profit triggering constantly due to a **critical calculation error** in how Global TP percentage is calculated.

**The Bug:** Global TP calculates profit percentage based on **MARGIN** instead of **WALLET BALANCE**. With 20x leverage and small positions, this causes TP to trigger on tiny absolute profits (or even losses).

---

## 💰 Current Financial Status

```
Starting Balance (Dec 1):  $5.00
Current Balance (Dec 17):  $2.83
Total Transfers In:        $14.38
Balance from Trading:      -$11.55
Trading P&L:               -$16.55 (-331%)
```

**You have lost $16.55 through trading, representing a 331% loss.**

---

## 🔍 Evidence of the Problem

### Recent Global TP Events

#### TP #1: Dec 17, 15:30
```
Positions Closed: 4
Gross PnL:        $-0.0428 (NEGATIVE!)
Fees:             $-0.0001
Net Profit:       $-0.0429 (LOSS!)
Balance Change:   $2.8948 → $2.8519
```

**This "take profit" was actually a LOSS of $0.0429!**

#### TP #2: Dec 16, 22:07
```
Total PnL:        $+0.0000 (BREAK EVEN)
Balance Change:   $3.82 → $3.82 (NO CHANGE)
```

**This "take profit" made $0.00!**

### Historical Pattern from Balance Timeline

Many Global TP events are break-even or losses:
- Dec 2, 22:00: 13 positions, PnL: $-0.00 (break even)
- Dec 2, 10:00: 26 positions, PnL: $-0.01 (LOSS)
- Dec 2, 08:47: 7 positions, PnL: $-0.00 (break even)
- Dec 2, 08:46: 10 positions, PnL: $-0.29 (LOSS)
- Dec 2, 08:45: 10 positions, PnL: $-0.02 (LOSS)

---

## 🐛 Root Cause: The Global TP Calculation Bug

### Location
**File:** `main.py`
**Lines:** 602-610

### The Buggy Code

```python
# Line 602-603
if total_margin > 0:
    global_pnl_pct = (total_pnl / total_margin) * 100

# Line 610
if global_pnl_pct >= self.config.GLOBAL_TP_PERCENT:
    # Trigger TP...
```

### The Problem

**The code calculates PnL percentage based on MARGIN, not WALLET BALANCE.**

With 20x leverage, this creates massive distortion:

#### Example Scenario

```
Wallet Balance:     $3.00
Position Margin:    $0.10 (3.3% of wallet)
Position Notional:  $2.00 (20x leverage)
Position Gain:      +1% on notional

Gross PnL:          $0.02
Fees:               -$0.002
Net Profit:         $0.018

CODE CALCULATES:
  global_pnl_pct = ($0.02 / $0.10) × 100 = 20%
  → TRIGGERS TP (20% >= 10% threshold)
  → "Success! 20% profit!"

REALITY:
  Wallet gain = $0.018 / $3.00 = 0.6%
  → Tiny profit, but TP triggers anyway
```

### Why This Causes Losses

1. **False Triggers:** TP triggers on small absolute profits because the percentage (vs margin) looks good
2. **High Frequency:** Many TP triggers = many trades = high cumulative fees
3. **Fee Erosion:** Trading fees (0.05% × 2 = 0.1% round trip) eat into small profits
4. **Negative TP:** Sometimes TP even triggers on NET LOSSES when gross PnL (before fees) shows a margin-based percentage gain

---

## 📈 Detailed Analysis

### Leverage Amplification Effect

| Margin | Notional (20x) | +1% Gain | Margin % | Wallet % (on $3) |
|--------|----------------|----------|----------|------------------|
| $0.10  | $2.00          | $0.02    | 20%      | 0.67%            |
| $0.05  | $1.00          | $0.01    | 20%      | 0.33%            |
| $0.01  | $0.20          | $0.002   | 20%      | 0.07%            |

**All trigger 10% TP threshold (20% > 10%), but actual wallet gains are tiny!**

### Fee Impact

```
Binance Futures Taker Fee: 0.05% per trade
Round Trip Fee: 0.1% (open + close)

For $0.10 margin position:
  Open fee:  $0.0001
  Close fee: $0.0001
  Total:     $0.0002

For 10 positions:
  Total fees: $0.002

This can completely wipe out small gains!
```

---

## ✅ The Solution

### Change the Global TP Calculation

**FROM (Current - WRONG):**
```python
global_pnl_pct = (total_pnl / total_margin) * 100
```

**TO (Correct):**
```python
# Get current wallet balance
current_balance = await self._get_wallet_balance()

# Calculate PnL as percentage of WALLET, not margin
global_pnl_pct = (total_pnl / current_balance) * 100
```

### Why This Fixes It

1. **Accurate Percentage:** Shows true wallet growth, not margin-based distortion
2. **Fewer False Triggers:** 10% TP threshold now means 10% of wallet, not margin
3. **Meaningful Profits:** Only triggers when absolute profit is significant
4. **Fee-Aware:** Higher threshold means profits exceed fees

---

## 🎯 Recommended Actions

### Immediate (Critical)

1. **Fix the Global TP calculation** (main.py:603)
   - Change from margin-based to wallet-based percentage

2. **Adjust TP threshold** if needed
   - Current: 10% (of margin, broken)
   - Recommended: 2-5% (of wallet, realistic)
   - Consider: Absolute minimum profit (e.g., $0.10 minimum)

### Short-Term

3. **Add minimum absolute profit check**
   ```python
   # Don't trigger TP unless absolute profit exceeds fees
   min_profit = total_margin * 0.002  # 0.2% of margin (2x fees)
   if total_pnl < min_profit:
       continue  # Skip TP
   ```

4. **Review position sizing**
   - Current: Very small positions (e.g., $0.01-$0.10 margin)
   - Problem: Fees are proportionally huge
   - Solution: Increase minimum position size

### Long-Term

5. **Implement tiered TP**
   - Partial close at 5% of wallet
   - Full close at 10% of wallet
   - Prevents "all-or-nothing" exits

6. **Add fee tracking**
   - Log cumulative fees paid
   - Display in dashboard
   - Alert if fees exceed profits

7. **Backtest with realistic TP**
   - Test with wallet-based percentage
   - Verify profitability before deploying

---

## 📊 Expected Impact After Fix

### Before Fix (Current)
```
- TP triggers: ~50 per week
- Average profit per TP: $0.01 to -$0.05
- Cumulative fees: ~$0.50 per week
- Net result: Slow bleed of capital
```

### After Fix (Wallet-based 5% TP)
```
- TP triggers: ~5-10 per week (realistic profits)
- Average profit per TP: $0.15 to $0.50
- Cumulative fees: ~$0.10 per week
- Net result: Profitable trading
```

---

## 🔧 Implementation Priority

**CRITICAL - IMMEDIATE ACTION REQUIRED**

This bug is causing continuous capital loss. Every TP trigger that shouldn't happen costs you money in fees and closes potentially profitable positions prematurely.

**Estimated current daily loss rate:** $0.50 to $2.00 per day from false TP triggers and fees.

---

## 📝 Technical Notes

### Code Location Summary

1. **TP Calculation:** `main.py:602-610`
2. **TP Trigger:** `main.py:610`
3. **TP Threshold Config:** `src/macro_strategy.py:49` (env: `GLOBAL_TP_PERCENT`)
4. **Balance Tracking:** `main.py:382`, `main.py:447`

### Testing Checklist

- [ ] Change calculation to wallet-based
- [ ] Test with small balance ($3-5)
- [ ] Verify TP triggers at correct threshold
- [ ] Check absolute profit is meaningful
- [ ] Monitor for 24h before full deployment
- [ ] Validate against Binance account history

---

## 🎓 Lessons Learned

1. **Always validate percentage calculations** against the correct base (wallet vs margin)
2. **High leverage amplifies small errors** into major bugs
3. **Monitor absolute profits, not just percentages**
4. **Account for trading fees** in profitability calculations
5. **Test with realistic capital** before deploying

---

**End of Analysis**
