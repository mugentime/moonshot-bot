# Testing Quick Reference Guide
## One-Page Testing Cheat Sheet

**Last Updated:** 2025-12-17

---

## 🚀 Quick Start

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_tp_wallet_calculation.py -v

# Run with coverage
pytest --cov=src --cov-report=html

# Run validation scripts
python tests/validation_scripts/historical_backtest.py
python tests/validation_scripts/fee_impact_calculator.py
```

---

## ✅ Test Categories

| Category | Files | Purpose | Command |
|----------|-------|---------|---------|
| **TP Calculation** | `test_tp_wallet_calculation.py` | Wallet-based TP logic | `pytest tests/test_tp_wallet_calculation.py -v` |
| **Fee Calculations** | `test_fee_calculations.py` | Fee accuracy & impact | `pytest tests/test_fee_calculations.py -v` |
| **Integration** | `integration/test_tp_integration.py` | End-to-end TP cycles | `pytest tests/integration/ -v` |
| **Validation** | `validation_scripts/*.py` | Historical & scenarios | `python tests/validation_scripts/<script>.py` |

---

## 🎯 Critical Test Cases

### 1. Wallet-Based TP Calculation
```python
# OLD (BUGGY): (pnl / margin) * 100
# NEW (CORRECT): (pnl / wallet_balance) * 100

wallet = $100, margin = $5, pnl = $1
OLD: ($1 / $5) * 100 = 20% ✗ (FALSE TRIGGER)
NEW: ($1 / $100) * 100 = 1% ✓ (CORRECT)
```

**Test:** `test_tp_percentage_vs_wallet_not_margin()`

### 2. Fee-Aware Triggering
```python
# Gross profit: $10.50 (10.5% would trigger)
# Fees: $1.00
# Net profit: $9.50 (9.5% doesn't trigger)

# WRONG: Check gross
# RIGHT: Check net (after fees)
```

**Test:** `test_gross_vs_net_pnl()`

### 3. Position Sizing
```python
# Minimum margin: $1.00
# Max positions = balance / $1.00

balance = $100
max_positions = 100 (not 200+)
```

**Test:** `test_minimum_position_enforcement()`

---

## 📊 Success Metrics

| Metric | Target | Current (Before Fix) | After Fix |
|--------|--------|---------------------|-----------|
| **TP Triggers/Week** | 5-10 | ~50 | ~5 ✅ |
| **Avg TP Profit** | >$0.50 | $0.01-$0.05 | >$0.50 ✅ |
| **False TP on Loss** | 0 | ~10/week | 0 ✅ |
| **Fee % of Profits** | <25% | ~75% | <25% ✅ |
| **Win Rate** | >80% | ~50% | >80% ✅ |

---

## 🧪 Test Scenarios

### Scenario 1: Small Account Death Spiral
```python
Balance: $2.72
Positions: 34
Margin/pos: $0.08
Result: UNPROFITABLE (fees>profits)
```
**Fix:** Max 5 positions, $1.00 min margin

### Scenario 2: Tiny Profit False TP
```python
Wallet: $100
Margin: $5
Profit: $1
Old calc: 20% TP ✗
New calc: 1% TP ✓
```
**Fix:** Wallet-based calculation

### Scenario 3: Loss Triggers TP
```python
Balance: $2.89
Gross PnL: -$0.04 (LOSS)
Old behavior: TP triggered ✗
New behavior: No trigger ✓
```
**Fix:** Fee-aware, net PnL check

---

## 🔧 Key Test Files

### `test_tp_wallet_calculation.py`
- ✅ `test_tp_percentage_vs_wallet_not_margin()` - Core fix validation
- ✅ `test_zero_wallet_balance_edge_case()` - Edge case handling
- ✅ `test_negative_pnl_never_triggers_tp()` - Loss protection
- ✅ `test_historical_scenario_replay()` - Regression prevention

### `test_fee_calculations.py`
- ✅ `test_taker_fee_calculation()` - 0.05% accuracy
- ✅ `test_round_trip_fees()` - Entry + exit fees
- ✅ `test_fee_erodes_small_profits()` - Fee impact demo
- ✅ `test_death_spiral_small_account()` - Real-world scenario

### `test_tp_integration.py`
- ✅ `test_successful_tp_cycle_wallet_based()` - Complete cycle
- ✅ `test_aggregate_pnl_calculation()` - Multi-position
- ✅ `test_cooldown_prevents_reentry()` - Cooldown enforcement
- ✅ `test_balance_increase_after_tp()` - Primary success metric

---

## 🎬 Validation Scripts

### Historical Backtest
```bash
python tests/validation_scripts/historical_backtest.py
```
**Output:**
- OLD vs NEW calculation comparison
- False positive detection
- TP trigger differences

### Fee Impact Calculator
```bash
python tests/validation_scripts/fee_impact_calculator.py
```
**Output:**
- Fee % of profits
- Profitability verdict
- Scenario comparisons

---

## 📋 Testnet Checklist

- [ ] All unit tests pass (100%)
- [ ] Historical backtest: 0 false positives
- [ ] Fee calculator: Predicts profitability
- [ ] Deploy to testnet
- [ ] Monitor first TP event
- [ ] 24-hour soak test
- [ ] Performance benchmarks met
- [ ] Ready for production

---

## 🚨 Acceptance Criteria

### Must Pass:
- ✅ TP calculated vs wallet balance (not margin)
- ✅ TP uses NET PnL (after fees)
- ✅ Minimum $1.00 margin enforced
- ✅ All historical scenarios pass
- ✅ Balance increases after each TP
- ✅ Zero false TP on losses

### Performance Targets:
- ✅ TP triggers: <10/week
- ✅ Avg TP profit: >$0.50
- ✅ Fee %: <25% of profits
- ✅ Win rate: >80%

---

## 🛠️ Common Test Commands

```bash
# Run tests with markers
pytest -m "integration" -v

# Run specific test
pytest tests/test_tp_wallet_calculation.py::TestWalletBasedTPCalculation::test_tp_percentage_vs_wallet_not_margin -v

# Run with output
pytest -v -s

# Generate coverage report
pytest --cov=src --cov-report=term-missing

# Run and stop on first failure
pytest -x

# Re-run failed tests
pytest --lf
```

---

## 📈 Monitoring Commands

```bash
# Check TP events
curl http://localhost:8050/tp-tracker/json | jq

# Check fees
curl http://localhost:8050/api/fees | jq

# Check positions
curl http://localhost:8050/positions

# Health check
curl http://localhost:8050/health
```

---

## 🔄 Rollback Triggers

**Immediately rollback if:**
- 3+ consecutive TP events with net loss
- Balance drops >20% in 1 hour
- False TP triggers on losses
- Critical errors in logs

---

## 📚 Related Documents

- Full Strategy: `docs/TESTING_STRATEGY.md`
- Root Cause: `docs/BALANCE_LOSS_ANALYSIS.md`
- Fee Review: `docs/FEE_HANDLING_REVIEW.md`
- TP Tracker: `docs/FEE_TRACKER_TESTING.md`

---

**Quick Reference Version:** 1.0
**For:** Trading Bot TP Fix Validation
