# 🚀 Moonshot Bot

Automated trading bot for Binance Futures that detects and captures moonshot opportunities (explosive price movements of +20% to +1000%).

## Features

- **6-Signal Moonshot Detection**: Volume spike, price acceleration, OI surge, funding rate, breakout, order book imbalance
- **Market Regime Detection**: Automatically adapts to TRENDING, CHOPPY, EXTREME conditions
- **Dynamic Position Sizing**: Compound growth with $1 minimum margin
- **Escalonated Take-Profit**: 4 levels with trailing stop activation
- **Funding Rate Monitoring**: Exits positions when funding becomes excessive
- **24/7 Operation**: Scans all USDT/USDC perpetual pairs continuously

## Quick Start

### Prerequisites

- Python 3.11+
- Binance Futures account with API keys
- Redis instance

### Environment Variables

```env
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
BINANCE_TESTNET=false
REDIS_URL=redis://localhost:6379
LOG_LEVEL=INFO
PORT=8050
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python main.py
```

### Deploy to Railway

1. Connect your GitHub repo to Railway
2. Add environment variables
3. Add Redis plugin
4. Deploy!

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      MOONSHOT BOT                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Data Feed ──► Market Regime ──► Trade Manager               │
│      │              │                  │                     │
│      ▼              ▼                  ▼                     │
│  Pair Filter  Moonshot Detector  Position Sizer              │
│      │              │                  │                     │
│      └──────────────┴──────────────────┘                     │
│                     │                                        │
│                     ▼                                        │
│              Order Executor ◄── Exit Manager                 │
│                     │                                        │
│                     ▼                                        │
│              Position Tracker (Redis)                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

All parameters are in `config/settings.py`:

### Position Sizing
- `MIN_MARGIN_USD`: $1 (minimum per trade)
- `MAX_CONCURRENT_TRADES`: 30
- `MAX_MARGIN_PERCENT`: 5%

### Leverage
- `DEFAULT_LEVERAGE`: 15x
- `MIN_LEVERAGE`: 10x
- `MAX_LEVERAGE`: 20x

### Moonshot Detection
- `MIN_SIGNALS_REQUIRED`: 4 out of 6
- `VOLUME_SPIKE_5M`: 3x average
- `PRICE_VELOCITY_5M`: 2%

### Stop-Loss
- `INITIAL_PERCENT`: 3.5%

### Take-Profit Levels
1. +5% → Close 30%, SL to breakeven
2. +10% → Close 25%, activate trailing
3. +20% → Close 25%, tighten trailing
4. +50% → Close 20%

## API Endpoints

- `GET /health` - Health check
- `GET /status` - Bot status
- `GET /positions` - Open positions
- `POST /stop` - Stop the bot

## Risk Warning

⚠️ **This bot trades with leverage. You can lose more than your initial investment.**

- Start with testnet
- Use only funds you can afford to lose
- Monitor positions regularly
- Understand the risks of leveraged trading

## License

MIT
