# 50/50 Simple Earn + Loan Rebalancing Strategy

## Strategy Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    YOUR STRATEGY DIAGRAM                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│                        STARTING CAPITAL                             │
│                           $10,000                                   │
│                              │                                      │
│                    ┌─────────┴─────────┐                           │
│                    │                   │                           │
│                    ▼                   ▼                           │
│            ┌───────────────┐   ┌───────────────┐                   │
│            │   SIDE A      │   │   SIDE B      │                   │
│            │   $5,000      │   │   $5,000      │                   │
│            └───────┬───────┘   └───────┬───────┘                   │
│                    │                   │                           │
│                    ▼                   ▼                           │
│         ┌─────────────────┐   ┌─────────────────┐                  │
│         │  Convert to     │   │  Keep as        │                  │
│         │  ASSET A (ETH)  │   │  ASSET B (BTC)  │                  │
│         │                 │   │                 │                  │
│         │  Deposit to     │   │  Deposit to     │                  │
│         │  Simple Earn    │   │  Simple Earn    │                  │
│         │  (Earn ~2% APY) │   │  (Earn ~0.3%APY)│                  │
│         │                 │   │                 │                  │
│         │  Borrow BTC     │   │  Borrow ETH     │                  │
│         │  against ETH    │   │  against BTC    │                  │
│         └────────┬────────┘   └────────┬────────┘                  │
│                  │                     │                           │
│                  ▼                     ▼                           │
│         ┌─────────────────┐   ┌─────────────────┐                  │
│         │ SIDE A HOLDS:   │   │ SIDE B HOLDS:   │                  │
│         │                 │   │                 │                  │
│         │ + ETH (lending) │   │ + BTC (lending) │                  │
│         │ + BTC (borrowed)│   │ + ETH (borrowed)│                  │
│         │                 │   │                 │                  │
│         │ NET: Long ETH   │   │ NET: Long BTC   │                  │
│         │      Short BTC  │   │      Short ETH  │                  │
│         └────────┬────────┘   └────────┬────────┘                  │
│                  │                     │                           │
│                  └──────────┬──────────┘                           │
│                             │                                      │
│                             ▼                                      │
│                  ┌─────────────────────┐                           │
│                  │    REBALANCING      │                           │
│                  │                     │                           │
│                  │ When LTV differs    │                           │
│                  │ significantly:      │                           │
│                  │                     │                           │
│                  │ Side A LTV high →   │                           │
│                  │   ETH dropped vs BTC│                           │
│                  │   (repay some BTC)  │                           │
│                  │                     │                           │
│                  │ Side B LTV high →   │                           │
│                  │   BTC dropped vs ETH│                           │
│                  │   (repay some ETH)  │                           │
│                  │                     │                           │
│                  │ PROFIT: You sell    │                           │
│                  │ high, buy low       │                           │
│                  └─────────────────────┘                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Current Binance Rates (Approximate - Dec 2025)

### Simple Earn Rates (Lending/Earning)
| Asset | Flexible APY | Locked (30d) APY | Locked (120d) APY |
|-------|--------------|------------------|-------------------|
| BTC   | 0.27%        | 0.5%             | 1.0%              |
| ETH   | 1.0%         | 2.0%             | 3.5%              |
| SOL   | 5.0%         | 7.0%             | 8.9%              |
| BNB   | 1.0%         | 3.0%             | 5.0%              |
| USDT  | 3.9%         | 5.0%             | 6.0%              |

### Loan Borrow Rates (Approximate)
| Borrow Asset | Borrow Rate (APR) | Notes |
|--------------|-------------------|-------|
| USDT         | 5-8%              | Variable, updates every minute |
| BTC          | 1-3%              | Lower demand |
| ETH          | 2-4%              | Medium demand |
| SOL          | 5-10%             | Higher volatility premium |

### LTV Ratios
| Collateral | Initial LTV | Margin Call | Liquidation |
|------------|-------------|-------------|-------------|
| BTC        | 65-78%      | 75%         | 83-91%      |
| ETH        | 65-78%      | 75%         | 83-91%      |
| BNB        | 60-70%      | 75%         | 83-91%      |
| SOL        | 50-65%      | 75%         | 83-91%      |

## Best Pair Analysis

### Option 1: BTC/ETH (Safest)
```
┌─────────────────────────────────────────────────────────────────┐
│  PAIR: BTC / ETH                                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SIDE A: Deposit ETH → Earn ~1% APY → Borrow BTC (pay ~2%)     │
│  SIDE B: Deposit BTC → Earn ~0.3% APY → Borrow ETH (pay ~3%)   │
│                                                                 │
│  NET INTEREST: Slightly negative (-2% to -3%)                  │
│  REBALANCING PROFIT: ~8-15% APY (from ETH/BTC volatility)      │
│  TOTAL EXPECTED: ~5-12% APY                                    │
│                                                                 │
│  RISK: LOW (both blue chips)                                   │
│  CORRELATION: HIGH (0.85) - less rebalancing opportunities     │
└─────────────────────────────────────────────────────────────────┘
```

### Option 2: ETH/SOL (Higher Yield)
```
┌─────────────────────────────────────────────────────────────────┐
│  PAIR: ETH / SOL                                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SIDE A: Deposit SOL → Earn ~5% APY → Borrow ETH (pay ~3%)     │
│  SIDE B: Deposit ETH → Earn ~1% APY → Borrow SOL (pay ~7%)     │
│                                                                 │
│  NET INTEREST: ~-2% (SOL earns more but costs more to borrow) │
│  REBALANCING PROFIT: ~30-50% APY (from SOL/ETH volatility)     │
│  TOTAL EXPECTED: ~25-45% APY                                   │
│                                                                 │
│  RISK: MEDIUM (SOL more volatile)                              │
│  CORRELATION: MEDIUM (0.72) - more rebalancing opportunities   │
└─────────────────────────────────────────────────────────────────┘
```

### Option 3: BTC/SOL (Best Risk-Adjusted)
```
┌─────────────────────────────────────────────────────────────────┐
│  PAIR: BTC / SOL                                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SIDE A: Deposit SOL → Earn ~5% APY → Borrow BTC (pay ~2%)     │
│  SIDE B: Deposit BTC → Earn ~0.3% APY → Borrow SOL (pay ~7%)   │
│                                                                 │
│  NET INTEREST:                                                  │
│    Side A: +5% - 2% = +3%                                      │
│    Side B: +0.3% - 7% = -6.7%                                  │
│    Average: -1.85%                                              │
│                                                                 │
│  REBALANCING PROFIT: ~30-50% APY (BTC/SOL decorrelation)       │
│  TOTAL EXPECTED: ~28-48% APY                                   │
│                                                                 │
│  RISK: MEDIUM                                                  │
│  CORRELATION: LOW (0.65) - BEST for rebalancing                │
└─────────────────────────────────────────────────────────────────┘
```

## RECOMMENDED STRATEGY

```
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║   RECOMMENDED: BTC / SOL (50/50)                                 ║
║                                                                   ║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║   SIDE A ($5,000):                                               ║
║   ┌─────────────────────────────────────────────────────────┐    ║
║   │  1. Buy $5,000 SOL                                      │    ║
║   │  2. Deposit SOL to Simple Earn Flexible (earn ~5% APY)  │    ║
║   │  3. Borrow BTC against SOL (pay ~2% APR)               │    ║
║   │  4. Borrow at 50% LTV (safe margin)                    │    ║
║   │                                                         │    ║
║   │  Result: Long SOL, Short BTC                           │    ║
║   │  Net yield: +3% APY                                    │    ║
║   └─────────────────────────────────────────────────────────┘    ║
║                                                                   ║
║   SIDE B ($5,000):                                               ║
║   ┌─────────────────────────────────────────────────────────┐    ║
║   │  1. Buy $5,000 BTC                                      │    ║
║   │  2. Deposit BTC to Simple Earn Flexible (earn ~0.3% APY)│    ║
║   │  3. Borrow SOL against BTC (pay ~7% APR)               │    ║
║   │  4. Borrow at 50% LTV (safe margin)                    │    ║
║   │                                                         │    ║
║   │  Result: Long BTC, Short SOL                           │    ║
║   │  Net yield: -6.7% APY                                  │    ║
║   └─────────────────────────────────────────────────────────┘    ║
║                                                                   ║
║   COMBINED:                                                       ║
║   ├── Interest: -1.85% APY (cost)                                ║
║   ├── Rebalancing: +30-50% APY (profit)                          ║
║   └── TOTAL: ~28-48% APY expected                                ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
```

## Rebalancing Rules

### When to Rebalance

```
┌─────────────────────────────────────────────────────────────────┐
│  TRIGGER CONDITIONS (check daily or when notified):            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. LTV DIVERGENCE:                                            │
│     Side A LTV > 60% AND Side B LTV < 45%                      │
│     OR                                                          │
│     Side B LTV > 60% AND Side A LTV < 45%                      │
│                                                                 │
│  2. VALUE DRIFT:                                                │
│     One side worth >55% of total                               │
│     (means one asset outperformed by >10%)                     │
│                                                                 │
│  3. WEEKLY REBALANCE:                                          │
│     Even without triggers, check weekly                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### How to Rebalance

```
SCENARIO: SOL pumped 20%, BTC flat
- Side A (SOL collateral): LTV dropped to 40% (healthy)
- Side B (BTC collateral): LTV increased to 60% (approaching margin call)

ACTION:
1. On Side B: Repay some of the borrowed SOL
   - Use profits from Side A or add capital
   - This reduces LTV on Side B

2. On Side A: Borrow more BTC
   - Your collateral (SOL) is now worth more
   - Borrow additional BTC to bring LTV back to 50%

3. Convert:
   - Sell the borrowed BTC for SOL
   - Add SOL to Side A collateral
   - OR use to repay Side B's SOL loan

RESULT: Both sides back to 50% LTV
PROFIT: You effectively sold SOL high (via borrowing more BTC)
        and bought SOL low (to repay Side B)
```

## Risk Management

### LTV Safety Zones
```
┌────────────────────────────────────────────────────────────────┐
│  LTV %     │  STATUS          │  ACTION                       │
├────────────────────────────────────────────────────────────────┤
│  < 40%     │  VERY SAFE       │  Can borrow more             │
│  40-50%    │  SAFE            │  Target zone                 │
│  50-60%    │  CAUTION         │  Monitor closely             │
│  60-70%    │  WARNING         │  Consider rebalancing        │
│  70-75%    │  DANGER          │  Rebalance immediately       │
│  > 75%     │  MARGIN CALL     │  Add collateral NOW          │
│  > 83%     │  LIQUIDATION     │  Position closed, 2% fee     │
└────────────────────────────────────────────────────────────────┘
```

### Position Sizing
```
RECOMMENDED: Start at 50% LTV (not the max 78%)

Why 50%?
- 25% buffer before margin call (75%)
- 33% buffer before liquidation (83%)
- Room to absorb 30% crash without liquidation
- Still captures most of the yield
```

## Expected Returns Summary

| Component | Return |
|-----------|--------|
| SOL Simple Earn | +5% APY |
| BTC Simple Earn | +0.3% APY |
| Borrow BTC (Side A) | -2% APR |
| Borrow SOL (Side B) | -7% APR |
| **Net Interest** | **-1.85% APY** |
| **Rebalancing Profit** | **+30-50% APY** |
| **TOTAL EXPECTED** | **~28-48% APY** |

## Quick Start Checklist

- [ ] Decide capital amount (e.g., $10,000)
- [ ] Buy $5,000 SOL
- [ ] Buy $5,000 BTC
- [ ] Deposit SOL to Simple Earn Flexible
- [ ] Deposit BTC to Simple Earn Flexible
- [ ] Borrow BTC against SOL at 50% LTV
- [ ] Borrow SOL against BTC at 50% LTV
- [ ] Set calendar reminder to check LTV daily
- [ ] Rebalance when LTV diverges >10%

---

*Sources: [Binance Simple Earn](https://www.binance.com/en/earn/simple-earn), [Binance Loans](https://www.binance.com/en/loan), [Binance Loan Data](https://www.binance.com/en/loan/data)*
