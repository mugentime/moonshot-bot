# TRADING BOT BALANCE LOSS - IMPLEMENTATION ROADMAP

**CRITICAL ISSUE**: Bot loses ~$0.50-2.00 daily from false TP triggers caused by margin-based PnL calculations that don't account for fees.

**ROOT CAUSE**: Line 657 in main.py uses `global_pnl_pct = (total_pnl / total_margin) * 100` which triggers TP at +10% margin profit, but fees (~0.08% round-trip) mean the wallet LOSES money on small positions.

---

## PHASE 1: Emergency Fixes (Deploy TODAY - 2-4 hours)

**Priority**: CRITICAL - Stops active bleeding
**Risk**: Low - Wallet-based calculations are industry standard
**Validation**: Monitor /positions dashboard for 24h

### 1.1 Wallet-Based TP Calculation (HIGHEST PRIORITY)
**File**: `main.py`
**Lines**: 656-674 (monitor loop Global TP check)

**Current Code** (WRONG):
```python
# Lines 656-657
if total_margin > 0:
    global_pnl_pct = (total_pnl / total_margin) * 100  # ← BROKEN
```

**Fixed Code**:
```python
# Get wallet balance to calculate REAL profit
balance_now = await self._get_wallet_balance()
start_balance = profit_tracker.start_balance

if start_balance > 0:
    # TRUE profit = wallet change (includes fees automatically)
    wallet_change = balance_now - start_balance
    global_pnl_pct = (wallet_change / start_balance) * 100

    # Log both for comparison during transition
    margin_pnl_pct = (total_pnl / total_margin) * 100 if total_margin > 0 else 0
    logger.debug(f"TP Check: Wallet={global_pnl_pct:+.2f}% | Margin={margin_pnl_pct:+.2f}% | Diff={margin_pnl_pct - global_pnl_pct:.2f}%")
```

**Testing Checkpoint**:
- [ ] TP triggers ONLY when wallet actually gains 10%
- [ ] No false TPs on positions with $0.88 margin
- [ ] Log shows wallet vs margin PnL difference

**Success Metrics**:
- 0 false TP triggers in 24 hours
- Wallet balance increases or stays flat (no losses)

**Rollback Trigger**: If TP stops triggering on real 10% gains, revert and investigate

---

### 1.2 Minimum Absolute Profit Check
**File**: `main.py`
**Lines**: 664 (add BEFORE Global TP trigger)

**Add This Code**:
```python
# SAFETY: Don't trigger TP if absolute profit is too small (fees > profit)
MIN_PROFIT_TO_CLOSE = 0.50  # $0.50 minimum (covers fees for ~60 positions)

if global_pnl_pct >= self.config.GLOBAL_TP_PERCENT:
    wallet_change = balance_now - start_balance

    # Prevent triggering on tiny gains that become losses after fees
    if wallet_change < MIN_PROFIT_TO_CLOSE:
        logger.warning(f"TP blocked: {global_pnl_pct:+.2f}% gain only ${wallet_change:+.4f} (< ${MIN_PROFIT_TO_CLOSE} min)")
        await asyncio.sleep(5)
        continue

    # Safe to trigger TP - profit exceeds fee costs
    self.last_global_tp_time = time.time()
    logger.info(f"GLOBAL TP TRIGGERED: +{global_pnl_pct:.2f}% (${wallet_change:+.4f})")
```

**Testing Checkpoint**:
- [ ] TP blocked when profit < $0.50 even if percentage is high
- [ ] TP triggers normally when profit > $0.50

**Success Metrics**:
- No TP events with net loss after fees

---

### 1.3 Increase TP Threshold (TEMPORARY BAND-AID)
**File**: `src/macro_strategy.py`
**Lines**: 49

**Current Code**:
```python
GLOBAL_TP_PERCENT: float = float(os.getenv("GLOBAL_TP_PERCENT", "10.0"))
```

**Temporary Fix** (while testing wallet-based TP):
```python
# TEMPORARY: Higher threshold while we fix margin-based calculations
# With 60 positions × 0.08% fees = 4.8% total fee cost
# Need 15%+ margin profit to guarantee wallet profit
GLOBAL_TP_PERCENT: float = float(os.getenv("GLOBAL_TP_PERCENT", "15.0"))
```

**Environment Variable**:
```bash
# Railway: Set GLOBAL_TP_PERCENT=15.0 immediately
railway variables set GLOBAL_TP_PERCENT=15.0
```

**Testing Checkpoint**:
- [ ] No TP triggers for 4-6 hours (higher threshold)
- [ ] When TP does trigger, wallet shows actual profit

**Rollback**: Once wallet-based TP is validated, reduce back to 10%

---

## PHASE 2: Fee Integration (Deploy THIS WEEK - 4-8 hours)

**Priority**: HIGH - Makes TP decisions fee-aware
**Risk**: Medium - Changes core decision logic
**Validation**: Track fee metrics on /fees dashboard

### 2.1 Fee-Aware TP Triggering
**File**: `main.py`
**Lines**: 656-674 (enhance Phase 1.1 code)

**Enhanced Code**:
```python
# Get current fee totals
fee_stats = fee_tracker.get_stats(balance_now)
total_fees_paid = fee_stats.total_fees

# Calculate NET profit (PnL - fees)
gross_pnl = balance_now - start_balance
net_pnl = gross_pnl - total_fees_paid  # Real profit after fees

if start_balance > 0:
    gross_pnl_pct = (gross_pnl / start_balance) * 100
    net_pnl_pct = (net_pnl / start_balance) * 100

    # Log detailed breakdown every minute
    if check_count % 12 == 0:
        logger.info(
            f"TP Check: Gross={gross_pnl_pct:+.2f}% (${gross_pnl:+.4f}) | "
            f"Fees=${total_fees_paid:.4f} | "
            f"Net={net_pnl_pct:+.2f}% (${net_pnl:+.4f}) | "
            f"Threshold={self.config.GLOBAL_TP_PERCENT}%"
        )

    # Trigger TP based on NET profit (after fees)
    if net_pnl_pct >= self.config.GLOBAL_TP_PERCENT and net_pnl >= MIN_PROFIT_TO_CLOSE:
        logger.info(f"GLOBAL TP: Gross={gross_pnl_pct:+.2f}% | Net={net_pnl_pct:+.2f}% (after ${total_fees_paid:.4f} fees)")
        await self._close_all_positions_global_tp(...)
```

**Testing Checkpoint**:
- [ ] Monitor loop logs show gross vs net PnL every minute
- [ ] TP triggers only when NET PnL exceeds threshold
- [ ] /fees dashboard shows accurate fee totals

**Success Metrics**:
- TP events always result in wallet profit
- Fee costs visible in TP decision logs

---

### 2.2 Real-Time Fee Tracking in Monitor Loop
**File**: `src/fee_tracker.py`
**Enhancement**: Add fee projection method

**New Method**:
```python
def estimate_close_fees(self, positions_count: int, avg_notional: float) -> float:
    """
    Estimate fees for closing all positions.

    Args:
        positions_count: Number of positions to close
        avg_notional: Average notional value per position

    Returns:
        Estimated total fees in USDT
    """
    # 0.04% taker fee per close
    fee_per_position = avg_notional * 0.0004
    total_close_fees = fee_per_position * positions_count
    return total_close_fees
```

**Use in Monitor Loop** (main.py line 660):
```python
# Before checking TP threshold
positions = self.position_tracker.get_all_positions()
avg_notional = total_margin * self.config.LEVERAGE / len(positions) if positions else 0
estimated_close_fees = fee_tracker.estimate_close_fees(len(positions), avg_notional)

# Adjust threshold to account for fees we'll pay on close
fees_already_paid = fee_tracker.get_stats(balance_now).total_fees
total_fee_cost = fees_already_paid + estimated_close_fees

logger.debug(f"Fee Projection: Paid=${fees_already_paid:.4f} | EstClose=${estimated_close_fees:.4f} | Total=${total_fee_cost:.4f}")
```

**Testing Checkpoint**:
- [ ] Fee projections accurate within 10% of actual
- [ ] TP decisions account for closing costs

---

### 2.3 Dashboard Fee Metrics Enhancement
**File**: `main.py`
**Lines**: 1443-1524 (/fees endpoint)

**Add Fee Alerts to Dashboard**:
```python
# Add to fee dashboard HTML (line 1498)
alert_html = ""
if alerts:
    alert_list = "".join([f'<div style="margin:5px 0">⚠️ {alert}</div>' for alert in alerts])
    alert_html = f'<div style="background:#7f1d1d;border:1px solid #991b1b;border-radius:8px;padding:15px;margin-bottom:20px"><strong>ALERTS</strong>{alert_list}</div>'

# Add fee efficiency warning
if stats.fee_efficiency < 70:
    alert_html += f'<div style="background:#854d0e;border:1px solid #a16207;border-radius:8px;padding:10px;margin-bottom:10px">⚠️ Fee efficiency low: {stats.fee_efficiency:.1f}% (paying {stats.actual_avg_fee_rate*100:.4f}% vs expected {stats.expected_fee_rate*100:.2f}%)</div>'
```

**Testing Checkpoint**:
- [ ] Alerts appear when fees exceed thresholds
- [ ] Dashboard shows fee efficiency < 70% warnings

---

## PHASE 3: Position Sizing Overhaul (Deploy NEXT WEEK - 8-16 hours)

**Priority**: MEDIUM - Prevents future fee problems
**Risk**: HIGH - Changes capital allocation
**Validation**: Paper trade for 48h before deploying

### 3.1 Tiered Position Sizing
**File**: `main.py`
**Lines**: 536-539 (replace equal weight allocation)

**Current Code** (WRONG):
```python
# Equal weight - creates $0.88 positions that can't beat fees
margin_per_position = balance / len(self.whitelisted_symbols)
margin_per_position = max(margin_per_position, 1.0)  # Minimum $1
```

**Tiered System**:
```python
def _calculate_position_sizes(self, balance: float, num_positions: int) -> List[float]:
    """
    Calculate tiered position sizes based on confidence/volatility.

    Args:
        balance: Available balance
        num_positions: Number of positions to open

    Returns:
        List of margin allocations per position
    """
    # TIER 1: Minimum viable position (fees < 5% of position)
    # With 20x leverage, $0.88 margin = $17.60 notional
    # Fee = $17.60 × 0.0008 (open+close) = $0.014
    # Need $0.30 margin minimum to keep fees < 5%
    MIN_POSITION_MARGIN = 0.30

    # TIER 2: Standard position (fees < 2% of expected profit)
    # Target 10% TP → $1 margin = $20 notional = $2 profit @ 10% TP
    # Fees = $20 × 0.0008 = $0.016 (0.8% of profit)
    STANDARD_POSITION_MARGIN = 1.00

    # TIER 3: Large position (for high-conviction signals)
    # Cap at 5% of balance per position for risk management
    MAX_POSITION_MARGIN = balance * 0.05

    # Calculate base allocation
    base_allocation = balance / num_positions

    # Apply tiers
    if base_allocation < MIN_POSITION_MARGIN:
        logger.warning(f"Balance too low: ${balance:.2f} ÷ {num_positions} = ${base_allocation:.2f} < ${MIN_POSITION_MARGIN:.2f} min")
        return [MIN_POSITION_MARGIN] * num_positions
    elif base_allocation < STANDARD_POSITION_MARGIN:
        # Use minimum viable positions
        return [MIN_POSITION_MARGIN] * num_positions
    elif base_allocation > MAX_POSITION_MARGIN:
        # Cap at max position size
        return [MAX_POSITION_MARGIN] * num_positions
    else:
        # Standard equal weight
        return [base_allocation] * num_positions
```

**Testing Checkpoint**:
- [ ] All positions have margin >= $0.30
- [ ] No positions exceed 5% of balance
- [ ] Paper trade shows improved win rate

**Success Metrics**:
- Fees < 2% of position profit on TP
- Win rate improves (fewer fee-dominated trades)

---

### 3.2 Signal-Based Allocation (FUTURE ENHANCEMENT)
**File**: `main.py` (new method)

**Concept**:
```python
def _score_signal_strength(self, symbol: str, macro_score: MacroScore) -> float:
    """
    Rate signal strength 0.0-1.0 based on:
    - 24h velocity alignment with macro direction
    - Volume confirmation
    - Distance from 24h high/low

    Returns:
        0.0-1.0 confidence score
    """
    # Implementation after Phase 3.1 validates
    pass
```

**Integration**: Multiply base allocation by signal strength (0.5x to 2.0x)

**Not Implementing Yet**: Needs validation of tiered sizing first

---

### 3.3 Minimum Viable Position Enforcement
**File**: `main.py`
**Lines**: Add pre-open validation

**New Validation Method**:
```python
def _validate_position_profitability(self, margin: float, leverage: int) -> bool:
    """
    Check if position is large enough to beat fees.

    Args:
        margin: Position margin in USDT
        leverage: Leverage multiplier

    Returns:
        True if position can be profitable, False otherwise
    """
    notional = margin * leverage

    # Round-trip fees (open + close)
    round_trip_fee_pct = 0.0004 * 2  # 0.08%
    total_fees = notional * round_trip_fee_pct

    # Expected profit at TP threshold
    expected_profit_pct = self.config.GLOBAL_TP_PERCENT / 100
    expected_profit_usd = notional * expected_profit_pct

    # Fee ratio: fees as % of expected profit
    fee_ratio = total_fees / expected_profit_usd if expected_profit_usd > 0 else 999

    if fee_ratio > 0.05:  # Fees > 5% of expected profit
        logger.warning(
            f"Position too small: ${margin:.2f} margin → "
            f"${total_fees:.4f} fees ({fee_ratio*100:.1f}% of ${expected_profit_usd:.2f} expected profit)"
        )
        return False

    return True
```

**Use Before Opening** (line 547):
```python
# Validate position is profitable before opening
if not self._validate_position_profitability(margin_per_position, self.config.LEVERAGE):
    logger.warning(f"Skipping {symbol}: position too small to beat fees")
    continue
```

**Testing Checkpoint**:
- [ ] No positions open if fees > 5% of expected profit
- [ ] Validation logs show rejection reasons

---

## PHASE 4: Optimization (Deploy in 2-4 WEEKS)

**Priority**: LOW - Nice-to-have improvements
**Risk**: MEDIUM - Adds complexity
**Validation**: Extensive backtesting required

### 4.1 Partial TP System
**Concept**: Close 50% of positions at 5%, rest at 15%

**Benefits**:
- Lock in profits faster
- Reduce fee drag from full position round-trips
- Better risk-adjusted returns

**Implementation Complexity**: HIGH (8-12 hours)
**Not Implementing Now**: Phase 1-3 must stabilize first

---

### 4.2 Dynamic TP Threshold Adjustment
**Concept**: Adjust TP threshold based on total fee costs

**Formula**:
```python
# If fees are 4% of balance, need 14%+ TP to profit
min_tp_threshold = (total_fees / balance) * 100 * 1.5  # 1.5x fee safety margin
adjusted_tp = max(self.config.GLOBAL_TP_PERCENT, min_tp_threshold)
```

**Benefits**:
- Automatically adapts to high-fee environments
- Prevents loss-making TP triggers

**Implementation Complexity**: MEDIUM (4 hours)
**Not Implementing Now**: Phase 2.1 fee-aware TP is sufficient

---

### 4.3 Advanced Fee Optimization
**Strategies**:
1. Batch orders to reduce round-trips
2. Use POST-ONLY orders (maker fees: 0.02% vs taker 0.04%)
3. Fee rebate tier optimization

**Implementation Complexity**: VERY HIGH (20+ hours)
**Not Implementing**: Out of scope for now

---

## DEPENDENCY CHAIN

```
PHASE 1.1 (Wallet TP)
    ↓
PHASE 1.2 (Min Profit) ← Can run in parallel
    ↓
PHASE 1.3 (Higher Threshold) ← TEMPORARY only
    ↓
    ↓ [VALIDATE 24 HOURS]
    ↓
PHASE 2.1 (Fee-Aware TP) ← Requires 1.1 stable
    ↓
PHASE 2.2 (Fee Projection) ← Can run in parallel with 2.1
    ↓
PHASE 2.3 (Dashboard) ← UI only, no dependencies
    ↓
    ↓ [VALIDATE 48 HOURS]
    ↓
PHASE 3.1 (Tiered Sizing) ← Requires stable TP system
    ↓
PHASE 3.2 (Signal Allocation) ← Requires 3.1 validated
    ↓
PHASE 3.3 (Min Position Validation) ← Can run with 3.1
    ↓
    ↓ [PAPER TRADE 1 WEEK]
    ↓
PHASE 4.x (Optimizations) ← Future work
```

---

## ESTIMATED TIME PER PHASE

| Phase | Task | Time | Priority | Risk |
|-------|------|------|----------|------|
| 1.1 | Wallet-based TP | 1h | CRITICAL | LOW |
| 1.2 | Min profit check | 30m | CRITICAL | LOW |
| 1.3 | Raise threshold | 5m | CRITICAL | NONE |
| **Phase 1 Total** | | **~2h** | | |
| 2.1 | Fee-aware TP | 2h | HIGH | MED |
| 2.2 | Fee projection | 1h | HIGH | LOW |
| 2.3 | Dashboard alerts | 1h | MEDIUM | NONE |
| **Phase 2 Total** | | **~4h** | | |
| 3.1 | Tiered sizing | 4h | MEDIUM | HIGH |
| 3.2 | Signal allocation | 4h | LOW | HIGH |
| 3.3 | Min validation | 2h | MEDIUM | MED |
| **Phase 3 Total** | | **~10h** | | |
| **Phase 4 Total** | | **Future** | | |

---

## VALIDATION APPROACH

### Phase 1 Validation (24 hours)
**Metrics to Track**:
- [ ] TP events: Count, trigger %, wallet change
- [ ] False TP rate: Should be 0
- [ ] Wallet balance trend: Should not decrease
- [ ] Fee costs vs profit: Fees < 10% of profit

**Dashboard Monitoring**:
```bash
# Check every 4 hours
curl https://moonshot-bot.up.railway.app/exits | grep "GLOBAL TP"
curl https://moonshot-bot.up.railway.app/fees | grep "Total Fees"
```

**Success Criteria**:
- 0 false TP events in 24 hours
- 0 wallet losses on TP triggers
- Logs show correct wallet vs margin PnL calculation

**Rollback Triggers**:
- TP stops triggering on real 10% gains
- Wallet balance decreases > $0.50 in 24h
- Monitor loop crashes or errors

---

### Phase 2 Validation (48 hours)
**Metrics to Track**:
- [ ] Fee projection accuracy: Within 10% of actual
- [ ] Net PnL accuracy: Matches wallet change
- [ ] Alert triggers: Appropriate, not spammy
- [ ] Dashboard fee metrics: Real-time, accurate

**Testing Scenarios**:
1. Open 60 positions → close 30 → check fee estimates
2. Trigger TP → compare projected vs actual fees
3. High-fee period → verify alerts trigger

**Success Criteria**:
- Fee projections < 10% error
- TP decisions based on NET PnL
- Alerts trigger on fee anomalies

**Rollback Triggers**:
- Fee calculations cause TP to never trigger
- Dashboard shows incorrect metrics
- Performance degradation (> 100ms per check)

---

### Phase 3 Validation (1 week paper trading)
**Metrics to Track**:
- [ ] Position rejection rate: How many too small?
- [ ] Fee-to-profit ratio: Should be < 5%
- [ ] Win rate change: Should improve
- [ ] Average profit per TP: Should increase

**Paper Trading Setup**:
```python
# Enable paper trading mode
PAPER_TRADE_MODE = True  # Don't actually open positions

# Log what WOULD happen
logger.info(f"[PAPER] Would open {symbol}: ${margin:.2f} margin")
```

**Success Criteria**:
- 0 positions rejected for being too small (if balance adequate)
- Fees < 5% of position profit
- Win rate improves by 10%+

**Rollback Triggers**:
- Too many positions rejected (> 20%)
- Win rate decreases
- Balance grows slower than Phase 2

---

## RISK ASSESSMENT BY PHASE

### Phase 1 Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| TP never triggers | LOW | HIGH | Log both wallet & margin PnL for comparison |
| Wallet balance API error | MEDIUM | MEDIUM | Add try/catch, fallback to margin calc |
| Threshold too high (15%) | MEDIUM | LOW | Temporary, revert after wallet TP validated |

### Phase 2 Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Fee projection too conservative | MEDIUM | LOW | Test with historical data first |
| NET PnL calc errors | LOW | HIGH | Extensive logging, compare to wallet |
| Performance degradation | LOW | MEDIUM | Profile code, optimize fee stats query |

### Phase 3 Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Position sizing too conservative | MEDIUM | MEDIUM | Adjust MIN_POSITION_MARGIN down if needed |
| Capital not fully deployed | HIGH | MEDIUM | Scale positions up if too much idle capital |
| Signal scoring inaccurate | HIGH | HIGH | Don't implement until 3.1 stable |

---

## FILES TO CHANGE (COMPREHENSIVE LIST)

### Phase 1
```
main.py
├── Line 656-674: Monitor loop TP check (1.1, 1.2)
├── Line 372-520: _close_all_positions_global_tp logging

src/macro_strategy.py
└── Line 49: GLOBAL_TP_PERCENT default (1.3)

.env / Railway
└── GLOBAL_TP_PERCENT=15.0 (1.3)
```

### Phase 2
```
main.py
├── Line 656-674: Enhanced TP check with fees (2.1)
├── Line 660: Fee projection integration (2.2)
└── Line 1498: Dashboard alerts (2.3)

src/fee_tracker.py
└── New method: estimate_close_fees() (2.2)
```

### Phase 3
```
main.py
├── New method: _calculate_position_sizes() (3.1)
├── New method: _validate_position_profitability() (3.3)
├── Line 536-539: Replace equal weight (3.1)
└── Line 547: Add validation check (3.3)
```

---

## CODE SNIPPETS FOR KEY FIXES

### Critical Fix #1: Wallet-Based TP (Phase 1.1)

**Location**: main.py, line 656-674
**Replace**:
```python
if total_margin > 0:
    global_pnl_pct = (total_pnl / total_margin) * 100
```

**With**:
```python
# Get REAL wallet profit (includes fees automatically)
balance_now = await self._get_wallet_balance()
start_balance = profit_tracker.start_balance

if start_balance > 0:
    wallet_change = balance_now - start_balance
    global_pnl_pct = (wallet_change / start_balance) * 100

    # Debug: Compare wallet vs margin-based PnL
    margin_pnl_pct = (total_pnl / total_margin) * 100 if total_margin > 0 else 0
    logger.debug(f"TP: Wallet={global_pnl_pct:+.2f}% | Margin={margin_pnl_pct:+.2f}% | Diff={margin_pnl_pct - global_pnl_pct:.2f}%")
```

---

### Critical Fix #2: Minimum Profit Gate (Phase 1.2)

**Location**: main.py, line 664 (BEFORE TP trigger)
**Add**:
```python
MIN_PROFIT_TO_CLOSE = 0.50  # Don't TP if gain < $0.50

if global_pnl_pct >= self.config.GLOBAL_TP_PERCENT:
    wallet_change = balance_now - start_balance

    if wallet_change < MIN_PROFIT_TO_CLOSE:
        logger.warning(f"TP blocked: {global_pnl_pct:+.2f}% = ${wallet_change:+.4f} < ${MIN_PROFIT_TO_CLOSE} min")
        await asyncio.sleep(5)
        continue

    # Safe to trigger
    self.last_global_tp_time = time.time()
```

---

### Critical Fix #3: Fee-Aware TP (Phase 2.1)

**Location**: main.py, line 656-674 (enhances Fix #1)
**Replace entire TP check with**:
```python
# Calculate NET profit after fees
balance_now = await self._get_wallet_balance()
start_balance = profit_tracker.start_balance
fee_stats = fee_tracker.get_stats(balance_now)

if start_balance > 0:
    gross_pnl = balance_now - start_balance
    net_pnl = gross_pnl - fee_stats.total_fees

    gross_pnl_pct = (gross_pnl / start_balance) * 100
    net_pnl_pct = (net_pnl / start_balance) * 100

    # Log detailed breakdown every minute
    if check_count % 12 == 0:
        logger.info(
            f"TP: Gross={gross_pnl_pct:+.2f}% (${gross_pnl:+.4f}) | "
            f"Fees=${fee_stats.total_fees:.4f} | "
            f"Net={net_pnl_pct:+.2f}% (${net_pnl:+.4f})"
        )

    # Trigger on NET profit
    MIN_PROFIT = 0.50
    if net_pnl_pct >= self.config.GLOBAL_TP_PERCENT and net_pnl >= MIN_PROFIT:
        self.last_global_tp_time = time.time()
        logger.info(f"GLOBAL TP: Net={net_pnl_pct:+.2f}% after ${fee_stats.total_fees:.4f} fees")
        await self._close_all_positions_global_tp(
            trigger_percent=net_pnl_pct,
            total_margin=total_margin
        )
```

---

## DEPLOYMENT CHECKLIST

### Pre-Deployment (Phase 1)
- [ ] Read all current code (main.py, fee_tracker.py, config)
- [ ] Backup current Railway deployment state
- [ ] Test wallet balance API locally
- [ ] Verify profit_tracker.start_balance is set correctly

### Deployment Steps (Phase 1)
1. [ ] Set Railway env: `GLOBAL_TP_PERCENT=15.0`
2. [ ] Edit main.py lines 656-674 (wallet TP + min profit)
3. [ ] Commit: "fix: Use wallet-based TP calculation + min profit gate"
4. [ ] Push to Railway
5. [ ] Watch logs for 10 minutes (verify no errors)
6. [ ] Monitor /positions dashboard

### Post-Deployment (Phase 1)
- [ ] Check TP events in /exits every 4 hours
- [ ] Verify wallet balance trend (should not decrease)
- [ ] Compare wallet vs margin PnL in logs
- [ ] After 24h: Review metrics, proceed to Phase 2

### Deployment Steps (Phase 2)
1. [ ] Add estimate_close_fees() to fee_tracker.py
2. [ ] Enhance TP check with fee projection
3. [ ] Add dashboard alerts
4. [ ] Commit: "feat: Fee-aware TP triggering + projections"
5. [ ] Push to Railway
6. [ ] Monitor /fees dashboard

### Deployment Steps (Phase 3)
1. [ ] Enable paper trade mode
2. [ ] Implement tiered sizing + validation
3. [ ] Test for 48 hours paper trading
4. [ ] Review win rate and fee ratios
5. [ ] If successful: Disable paper mode, deploy live
6. [ ] Monitor for 1 week before Phase 4

---

## SUCCESS METRICS SUMMARY

### Phase 1 Success (24h)
- **Critical**: 0 false TP triggers
- **Critical**: 0 wallet losses
- **Important**: TP triggers on real 10% gains
- **Nice**: Logs show wallet vs margin diff

### Phase 2 Success (48h)
- **Critical**: NET PnL matches wallet change
- **Important**: Fee projections accurate
- **Important**: Alerts trigger appropriately
- **Nice**: Dashboard shows real-time fees

### Phase 3 Success (1 week)
- **Critical**: No unprofitable positions opened
- **Important**: Fees < 5% of profit
- **Important**: Win rate improves
- **Nice**: Average TP profit increases

---

## MONITORING COMMANDS

```bash
# Check TP events
curl -s https://moonshot-bot.up.railway.app/exits/json | jq '.events[] | select(.event_type=="GLOBAL_TP") | {timestamp, profit_usd, positions_closed}'

# Check fees
curl -s https://moonshot-bot.up.railway.app/api/fees | jq '.stats | {total_fees, fee_as_percent_balance, hourly_fee_rate}'

# Check positions
curl -s https://moonshot-bot.up.railway.app/positions | grep -o "Portfolio PnL.*%"

# Railway logs
railway logs --tail 100 | grep "GLOBAL TP\|TP Check\|Fee"
```

---

## CONCLUSION

**PRIORITY ORDER**:
1. **TODAY**: Deploy Phase 1.1, 1.2, 1.3 (2 hours)
2. **THIS WEEK**: Deploy Phase 2.1, 2.2, 2.3 (4 hours)
3. **NEXT WEEK**: Paper trade Phase 3.1, 3.3 (48h test)
4. **FOLLOWING WEEK**: Live deploy Phase 3 if paper trade successful
5. **FUTURE**: Consider Phase 4 optimizations

**CRITICAL PATH**: Phase 1 → validate 24h → Phase 2 → validate 48h → Phase 3 paper → validate 1wk → Phase 3 live

**ROLLBACK PLAN**: Each phase has clear success criteria and rollback triggers documented above.

**EXPECTED OUTCOME**:
- Immediate: Stop daily $0.50-2.00 losses
- Week 1: Fee-aware TP prevents all false triggers
- Week 2: Position sizing ensures all trades can beat fees
- Month 1: Bot becomes consistently profitable
