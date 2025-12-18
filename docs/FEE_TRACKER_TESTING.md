# Fee Tracker Testing & Validation Guide

## Pre-Flight Checklist

### 1. Verify Installation
```bash
# Check syntax
python -m py_compile src/fee_tracker.py
python -m py_compile main.py

# Test import
python -c "from src.fee_tracker import fee_tracker; print('✅ Import successful')"

# Verify data directory
ls -la data/
```

### 2. Expected Output
```
✅ Import successful
drwxr-xr-x  data/
```

## Testing Procedures

### Test 1: Manual Fee Recording

```python
import asyncio
from src.fee_tracker import FeeTracker
from src.data_feed import DataFeed

async def test_manual_recording():
    # Initialize
    data_feed = DataFeed()
    await data_feed.initialize()

    tracker = FeeTracker(data_feed=data_feed)

    # Record a test fee
    await tracker.record_trade_fee(
        symbol="BTCUSDT",
        side="LONG",
        action="OPEN",
        notional_value=100.0,
        order_id="test_123"
    )

    # Check results
    stats = tracker.get_stats(balance=1000.0)
    print(f"Total fees: ${stats.total_fees:.4f}")
    print(f"Total trades: {stats.total_trades}")

    assert stats.total_trades > 0, "No trades recorded"
    print("✅ Test passed: Manual fee recording")

asyncio.run(test_manual_recording())
```

**Expected Output:**
```
💰 Fee recorded: BTCUSDT OPEN | $0.0400 (0.040%)
Total fees: $0.0400
Total trades: 1
✅ Test passed: Manual fee recording
```

### Test 2: API Fee Fetching

```python
import asyncio
from src.fee_tracker import FeeTracker
from src.data_feed import DataFeed

async def test_api_fetching():
    data_feed = DataFeed()
    await data_feed.initialize()

    tracker = FeeTracker(data_feed=data_feed)

    # Fetch recent fees
    recent_fees = await tracker.fetch_recent_fees(lookback_minutes=60)

    print(f"Fetched {len(recent_fees)} fee records")

    if recent_fees:
        for fee in recent_fees[:3]:
            print(f"  {fee.timestamp[:19]} | {fee.symbol} | ${fee.fee_amount:.4f}")
        print("✅ Test passed: API fetching")
    else:
        print("⚠️ No fees found (no recent trades)")

asyncio.run(test_api_fetching())
```

**Expected Output (with trades):**
```
Fetched 5 fee records
  2025-12-17 12:34:56 | BTCUSDT | $0.0400
  2025-12-17 12:35:12 | ETHUSDT | $0.0300
  2025-12-17 12:36:01 | SOLUSDT | $0.0250
✅ Test passed: API fetching
```

### Test 3: Statistics Calculation

```python
from src.fee_tracker import FeeTracker, FeeRecord
from datetime import datetime

def test_statistics():
    tracker = FeeTracker()

    # Add test records
    test_fees = [
        FeeRecord(
            timestamp=datetime.now().isoformat(),
            symbol="BTCUSDT",
            side="LONG",
            action="OPEN",
            notional_value=100.0,
            fee_amount=0.04,
            fee_asset="USDT",
            fee_rate=0.0004,
            income_type="COMMISSION"
        ),
        FeeRecord(
            timestamp=datetime.now().isoformat(),
            symbol="ETHUSDT",
            side="LONG",
            action="CLOSE",
            notional_value=150.0,
            fee_amount=0.06,
            fee_asset="USDT",
            fee_rate=0.0004,
            income_type="COMMISSION"
        )
    ]

    tracker.fee_records = test_fees
    tracker.total_fees = sum(r.fee_amount for r in test_fees)

    # Calculate stats
    stats = tracker.get_stats(balance=1000.0)

    print(f"Total fees: ${stats.total_fees:.4f}")
    print(f"Total trades: {stats.total_trades}")
    print(f"Avg fee/trade: ${stats.avg_fee_per_trade:.4f}")
    print(f"Fee % balance: {stats.fee_as_percent_balance:.2f}%")
    print(f"Fee efficiency: {stats.fee_efficiency:.1f}%")

    assert stats.total_fees == 0.10, "Total fees incorrect"
    assert stats.total_trades == 2, "Trade count incorrect"
    print("✅ Test passed: Statistics calculation")

test_statistics()
```

**Expected Output:**
```
Total fees: $0.1000
Total trades: 2
Avg fee/trade: $0.0500
Fee % balance: 0.01%
Fee efficiency: 100.0%
✅ Test passed: Statistics calculation
```

### Test 4: Alert System

```python
from src.fee_tracker import FeeTracker, FeeRecord
from datetime import datetime

def test_alerts():
    tracker = FeeTracker()

    # Set up high fees scenario
    high_fees = [
        FeeRecord(
            timestamp=datetime.now().isoformat(),
            symbol="BTCUSDT",
            side="LONG",
            action="OPEN",
            notional_value=1000.0,
            fee_amount=5.0,  # Very high fee
            fee_asset="USDT",
            fee_rate=0.005,  # 0.5% (very high)
            income_type="COMMISSION"
        )
    ]

    tracker.fee_records = high_fees
    tracker.total_fees = 5.0

    # Check alerts with small balance
    alerts = tracker.check_alerts(balance=100.0)

    print(f"Alerts triggered: {len(alerts)}")
    for alert in alerts:
        print(f"  {alert}")

    assert len(alerts) > 0, "Expected alerts but got none"
    print("✅ Test passed: Alert system")

test_alerts()
```

**Expected Output:**
```
Alerts triggered: 2
  ⚠️ HIGH FEES: 5.00% of balance this hour ($5.0000) - threshold: 2.0%
  ⚠️ FEE RATE ANOMALY: Actual rate 0.5000% vs expected 0.04% - efficiency: 8.0%
✅ Test passed: Alert system
```

### Test 5: Symbol Breakdown

```python
from src.fee_tracker import FeeTracker, FeeRecord
from datetime import datetime

def test_symbol_breakdown():
    tracker = FeeTracker()

    # Add multiple trades for different symbols
    test_records = [
        ("BTCUSDT", 0.10),
        ("BTCUSDT", 0.12),
        ("ETHUSDT", 0.08),
        ("SOLUSDT", 0.05),
        ("BTCUSDT", 0.15),
    ]

    tracker.fee_records = [
        FeeRecord(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            side="LONG",
            action="OPEN",
            notional_value=100.0,
            fee_amount=fee,
            fee_asset="USDT",
            fee_rate=0.0004,
            income_type="COMMISSION"
        )
        for symbol, fee in test_records
    ]

    # Get breakdown
    breakdown = tracker.get_fee_breakdown_by_symbol()

    print("Fee breakdown by symbol:")
    for symbol, fees in breakdown.items():
        print(f"  {symbol}: ${fees:.4f}")

    assert "BTCUSDT" in breakdown, "BTCUSDT not in breakdown"
    assert breakdown["BTCUSDT"] == 0.37, "BTCUSDT fees incorrect"
    print("✅ Test passed: Symbol breakdown")

test_symbol_breakdown()
```

**Expected Output:**
```
Fee breakdown by symbol:
  BTCUSDT: $0.3700
  ETHUSDT: $0.0800
  SOLUSDT: $0.0500
✅ Test passed: Symbol breakdown
```

## Live Testing with Bot

### Test 6: End-to-End Integration

1. **Start the bot:**
```bash
python main.py
```

2. **Wait for initialization:**
Look for these log messages:
```
Fee tracker ready
✅ Automatic fee tracking enabled
```

3. **Wait for trades:**
Monitor the bot for position opens/closes

4. **Check fee dashboard:**
Navigate to: http://localhost:8050/fees

5. **Verify fee recording:**
Look for log messages like:
```
💰 Fee recorded: BTCUSDT OPEN | $0.0400 (0.040%)
💰 Fee recorded: ETHUSDT CLOSE | $0.0350 (0.040%)
```

6. **Check JSON API:**
```bash
curl http://localhost:8050/api/fees | jq
```

**Expected JSON structure:**
```json
{
  "session_id": "20251217_143256",
  "balance": 100.50,
  "stats": {
    "total_fees": 0.35,
    "total_trades": 8
  },
  "breakdown_by_symbol": {
    "BTCUSDT": 0.20
  }
}
```

### Test 7: Background Sync Verification

1. **Note current fee count:**
```bash
curl -s http://localhost:8050/api/fees | jq '.total_records'
# Output: 10
```

2. **Wait 5 minutes** (background sync interval)

3. **Check if new fees added:**
```bash
curl -s http://localhost:8050/api/fees | jq '.total_records'
# Output: 15 (if trades occurred)
```

4. **Verify file updated:**
```bash
cat data/fee_tracking.json | jq '.trades | length'
# Should match total_records
```

## Validation Checklist

### ✅ Functionality Tests
- [ ] Fee tracker imports successfully
- [ ] Manual fee recording works
- [ ] API fee fetching works
- [ ] Statistics calculated correctly
- [ ] Alerts trigger appropriately
- [ ] Symbol breakdown accurate
- [ ] File persistence works
- [ ] Background sync runs every 5 minutes

### ✅ Integration Tests
- [ ] Bot initializes fee tracker on startup
- [ ] Fees recorded on position open
- [ ] Fees recorded on position close
- [ ] Dashboard displays at /fees
- [ ] JSON API returns data at /api/fees
- [ ] Navigation links work
- [ ] Auto-refresh every 30s

### ✅ Error Handling Tests
- [ ] Graceful handling when no data_feed
- [ ] Estimates fee if API fails
- [ ] Continues on Binance API errors
- [ ] Saves data even if partial errors

### ✅ Performance Tests
- [ ] Fee recording adds <10ms overhead
- [ ] Dashboard loads in <1s
- [ ] Background sync doesn't block trading
- [ ] File I/O doesn't impact latency

## Common Issues & Solutions

### Issue 1: No Fees Showing
**Symptoms:**
- Dashboard shows 0 fees
- Empty breakdown

**Diagnosis:**
```python
# Check if trades executed
curl http://localhost:8050/api/fees | jq '.stats.total_trades'

# Check if data_feed connected
# Look for log: "Fee tracker ready"
```

**Solution:**
- Verify bot is running and trading
- Check Binance API credentials
- Wait for first trade execution

### Issue 2: API Fetch Failures
**Symptoms:**
- Logs show "Fee estimated (not found in API)"
- Actual rate different from expected

**Diagnosis:**
```python
# Check Binance API status
curl https://fapi.binance.com/fapi/v1/ping

# Verify API key permissions
# Check logs for API errors
```

**Solution:**
- Verify API key has futures permissions
- Check rate limits (2400 req/min)
- Increase lookback_minutes if needed

### Issue 3: Alerts Not Triggering
**Symptoms:**
- High fees but no alert banner
- Empty alerts array in API

**Diagnosis:**
```python
# Check thresholds
curl -s http://localhost:8050/api/fees | jq '.stats.hourly_fee_rate'
# Should be > 2.0 for alert

curl -s http://localhost:8050/api/fees | jq '.stats.fee_efficiency'
# Should be < 50 for alert
```

**Solution:**
- Verify balance > 0
- Check if fees actually exceed thresholds
- Review alert configuration in code

### Issue 4: Background Sync Not Working
**Symptoms:**
- Fee count doesn't increase over time
- Only manual recordings show up

**Diagnosis:**
```bash
# Check if background task started
# Look for log: "Fee tracker background updates started"

# Check for errors in logs
grep -i "error in fee tracker" logs/*.log
```

**Solution:**
- Verify async task is running
- Check for exceptions in logs
- Restart bot if task crashed

## Performance Benchmarks

### Expected Performance
- **Fee recording**: <10ms per trade
- **API fetch (100 records)**: 200-500ms
- **Stats calculation**: <5ms
- **Dashboard render**: <1s
- **Background sync**: <2s (1000 records)

### Memory Usage
- **Per fee record**: ~500 bytes
- **1000 records**: ~500 KB
- **Total overhead**: <5 MB

### File Size
- **Per record**: ~200 bytes JSON
- **1000 records**: ~200 KB
- **Daily average**: ~50 KB (assuming 250 trades/day)

## Success Criteria

### Minimum Requirements (All Must Pass)
1. ✅ Fee tracker initializes without errors
2. ✅ Records fees on every trade (open/close)
3. ✅ Dashboard displays current stats
4. ✅ JSON API returns valid data
5. ✅ Alerts trigger when thresholds exceeded
6. ✅ Data persists to file
7. ✅ Background sync adds new fees

### Optimal Performance
1. ✅ Fee efficiency >95%
2. ✅ No API fetch failures
3. ✅ Dashboard loads <1s
4. ✅ Background sync completes <2s
5. ✅ Zero missed fee records

## Next Steps After Testing

1. **Monitor in Production**
   - Track fees daily for first week
   - Verify accuracy against Binance UI
   - Tune alert thresholds if needed

2. **Data Validation**
   - Compare total fees with Binance account history
   - Verify breakdown matches per-symbol totals
   - Check funding fee accuracy

3. **Optimization**
   - Review fee efficiency metric
   - Consider maker orders if efficiency low
   - Adjust trading frequency based on hourly rate

4. **Reporting**
   - Export fee data monthly
   - Calculate total fees vs profit
   - Track fee trends over time

## Conclusion

If all tests pass and validation checklist complete:
- ✅ Fee tracking system is fully operational
- ✅ Ready for production use
- ✅ Monitoring and alerts active
- ✅ Data persistence verified

For issues or questions, refer to:
- Implementation: `docs/FEE_TRACKER_IMPLEMENTATION.md`
- Quick Reference: `docs/FEE_TRACKER_QUICK_REFERENCE.md`
- Source Code: `src/fee_tracker.py`
