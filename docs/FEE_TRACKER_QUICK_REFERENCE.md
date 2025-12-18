# Fee Tracker Quick Reference

## Access Points

### Web Dashboards
- **Fee Dashboard**: http://localhost:8050/fees
- **JSON API**: http://localhost:8050/api/fees

### Navigation
Available from all dashboards:
- Positions → Exits → **Fees** → Health

## Dashboard Features

### 📊 Statistics Cards (12 total)
1. **Total Fees** - Cumulative fees paid (red)
2. **Commission** - Trading fees only
3. **Funding** - Funding fees only
4. **Total Trades** - Number of trades executed
5. **Avg Fee/Trade** - Average fee per trade
6. **Fee % Balance** - Total fees as % of account
7. **Fee Efficiency** - Actual vs expected rate (color-coded)
   - Green: >90% (good)
   - Yellow: 70-90% (acceptable)
   - Red: <70% (high fees)
8. **Fees Today** - Fees paid today
9. **Fees This Hour** - Fees in current hour
10. **Hourly Fee Rate** - Fees/hour as % of balance (color-coded)
    - Green: <1%
    - Yellow: 1-2%
    - Red: >2% (alert threshold)
11. **Actual Fee Rate** - Real average fee rate
12. **Expected Rate** - 0.04% (standard taker)

### 📋 Recent Fees Table
Shows last 10 fee records:
- Timestamp
- Symbol
- Action (OPEN/CLOSE/FUNDING)
- Fee Amount (red if positive)
- Fee Rate (%)
- Notional Value

### 📊 Symbol Breakdown
Top 20 symbols by total fees paid

### ⚠️ Alert Banner
Displays when:
- Hourly fees > 2% of balance
- Actual fee rate > 2x expected

## JSON API Response

```json
{
  "session_id": "20251217_123456",
  "session_start": "2025-12-17T12:34:56",
  "balance": 100.00,
  "stats": {
    "total_fees": 0.50,
    "total_commission": 0.45,
    "total_funding": 0.05,
    "total_trades": 25,
    "avg_fee_per_trade": 0.018,
    "fee_as_percent_balance": 0.50,
    "expected_fee_rate": 0.0004,
    "actual_avg_fee_rate": 0.00041,
    "fee_efficiency": 97.56,
    "fees_today": 0.30,
    "fees_this_hour": 0.05,
    "hourly_fee_rate": 0.05
  },
  "breakdown_by_symbol": {
    "BTCUSDT": 0.25,
    "ETHUSDT": 0.15,
    "SOLUSDT": 0.10
  },
  "alerts": [],
  "total_records": 50
}
```

## Alert Thresholds

### 1. High Hourly Fee Rate
- **Threshold**: 2% of balance per hour
- **Trigger**: `hourly_fee_rate > 2.0`
- **Message**: "⚠️ HIGH FEES: X.XX% of balance this hour ($X.XXXX)"

### 2. Fee Rate Anomaly
- **Threshold**: Efficiency < 50% (actual > 2x expected)
- **Trigger**: `fee_efficiency < 50`
- **Message**: "⚠️ FEE RATE ANOMALY: Actual rate X.XX% vs expected 0.04%"

## Data Files

### Storage Location
`data/fee_tracking.json`

### Structure
```json
{
  "session_id": "20251217_123456",
  "session_start": "2025-12-17T12:34:56",
  "total_fees": 0.50,
  "trades": [
    {
      "timestamp": "2025-12-17T12:35:00",
      "symbol": "BTCUSDT",
      "side": "LONG",
      "action": "OPEN",
      "notional_value": 150.00,
      "fee_amount": 0.06,
      "fee_asset": "USDT",
      "fee_rate": 0.0004,
      "order_id": "123456",
      "income_type": "COMMISSION"
    }
  ]
}
```

## Background Sync

### Automatic Updates
- **Frequency**: Every 5 minutes
- **Lookback**: Last 60 minutes
- **Source**: Binance `futures_income_history` API
- **Batch Size**: Up to 1000 records

### Process
1. Fetches COMMISSION and FUNDING_FEE income
2. Filters for new records (not already tracked)
3. Adds to fee_records list
4. Updates total_fees
5. Saves to JSON file

## Fee Calculation

### Trading Fees (Commission)
- **Expected Rate**: 0.04% (taker fee)
- **Calculation**: `notional_value * 0.0004`
- **When Charged**: On every trade (open/close)

### Funding Fees
- **Frequency**: Every 8 hours (00:00, 08:00, 16:00 UTC)
- **Direction**: Pay if long in contango, earn if short
- **Tracked**: Automatically captured from API

## Integration with Bot

### Automatic Recording
Fees are recorded automatically on:
1. **Position Open** - In `_open_all_positions()`
2. **Position Close** - In `_close_all_positions_global_tp()`

### No Manual Action Required
The fee tracker:
- Starts automatically on bot initialization
- Syncs in background every 5 minutes
- Saves data persistently
- Stops gracefully on bot shutdown

## Interpreting Metrics

### Fee Efficiency
- **100%**: Paying exactly expected fees (perfect)
- **90-100%**: Good efficiency
- **70-90%**: Acceptable
- **<70%**: High fees, may indicate VIP tier issue

### Hourly Fee Rate
- **<1%**: Normal trading activity
- **1-2%**: High activity, monitor closely
- **>2%**: Very high fees, consider reducing frequency

### Fee % Balance
- **<5%**: Healthy fee ratio
- **5-10%**: Moderate fees
- **>10%**: High cumulative fees

## Troubleshooting

### No Fees Showing
1. Check if trades executed: `/positions`
2. Verify bot is running: `/health`
3. Check Binance API connection
4. Wait 5 minutes for background sync

### Fees Not Matching Expected
1. Check if using maker orders (lower fees)
2. Verify VIP level on Binance
3. Check actual vs expected rate in dashboard
4. Review fee efficiency metric

### Alerts Not Triggering
1. Verify balance > 0
2. Check alert thresholds in code
3. Review actual fee rates
4. Wait for hourly/daily aggregation

## Command Line Access

### Python Script Example
```python
from src.fee_tracker import fee_tracker

# Get stats
stats = fee_tracker.get_stats(balance=100.0)
print(f"Total fees: ${stats.total_fees:.4f}")
print(f"Fee efficiency: {stats.fee_efficiency:.1f}%")

# Get breakdown
breakdown = fee_tracker.get_fee_breakdown_by_symbol()
for symbol, fees in list(breakdown.items())[:5]:
    print(f"{symbol}: ${fees:.4f}")

# Check alerts
alerts = fee_tracker.check_alerts(balance=100.0)
for alert in alerts:
    print(alert)
```

## Best Practices

### Monitoring
1. Check fee dashboard daily
2. Review fee efficiency weekly
3. Monitor hourly rate during high activity
4. Track symbol breakdown for optimization

### Optimization
1. Consider maker orders if efficiency low
2. Reduce trading frequency if hourly rate high
3. Focus on high-efficiency symbols
4. Monitor funding fees for long positions

### Data Management
1. Backup `data/fee_tracking.json` regularly
2. Archive old sessions monthly
3. Review cumulative fees quarterly
4. Track fee trends over time

## Support & Documentation

- **Full Implementation**: `docs/FEE_TRACKER_IMPLEMENTATION.md`
- **Source Code**: `src/fee_tracker.py`
- **Main Integration**: `main.py` (search for `fee_tracker`)
- **Dashboard Route**: `/fees` endpoint in `main.py`

## Key Takeaways

✅ Automatic fee tracking on every trade
✅ Real-time dashboard with 12 metrics
✅ Alerts for high fees (>2% balance/hour)
✅ Symbol breakdown for cost analysis
✅ Background sync every 5 minutes
✅ Persistent storage in JSON
✅ Non-blocking performance
✅ JSON API for custom analysis
