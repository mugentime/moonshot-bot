"""
Moonshot Bot Configuration
All parameters defined in the planning phase
"""
import os
from typing import List, Dict

# =============================================================================
# ACCOUNT CONFIGURATION
# =============================================================================

INITIAL_EQUITY = float(os.getenv("INITIAL_EQUITY", "30.0"))
CURRENCY = "USDT"

# =============================================================================
# POSITION SIZING
# =============================================================================

class PositionSizingConfig:
    MIN_MARGIN_USD = float(os.getenv("MIN_MARGIN_USD", "1.0"))
    MAX_MARGIN_PERCENT = float(os.getenv("MAX_MARGIN_PERCENT", "5.0"))
    MAX_CONCURRENT_TRADES = int(os.getenv("MAX_CONCURRENT_TRADES", "30"))
    RECALC_EQUITY_CHANGE_PERCENT = 10.0  # Recalculate when equity changes ±10%
    RECALC_MAX_HOURS = 24  # Force recalculate every 24 hours

# =============================================================================
# LEVERAGE
# =============================================================================

class LeverageConfig:
    DEFAULT = int(os.getenv("DEFAULT_LEVERAGE", "15"))
    MIN = 10
    MAX = int(os.getenv("MAX_LEVERAGE", "20"))

# =============================================================================
# FEES
# =============================================================================

class FeesConfig:
    MAKER = 0.0002  # 0.02%
    TAKER = 0.0005  # 0.05%

# =============================================================================
# FUNDING MONITORING
# =============================================================================

class FundingConfig:
    CHECK_INTERVAL_MINUTES = 30
    MAX_RATE = 0.001  # 0.1%
    PARTIAL_CLOSE_PERCENT = 50
    CLOSE_ALL_IF_NO_PROFIT = True

# =============================================================================
# MOONSHOT DETECTION
# =============================================================================

class MoonshotDetectionConfig:
    MIN_SIGNALS_REQUIRED = 4  # Out of 6
    
    # Volume
    VOLUME_SPIKE_5M = 3.0  # 3x average
    VOLUME_SPIKE_1H = 5.0  # 5x average
    
    # Price velocity
    PRICE_VELOCITY_5M_LONG = 2.0  # +2%
    PRICE_VELOCITY_5M_SHORT = -2.0  # -2%
    PRICE_VELOCITY_1M = 0.8  # +0.8%
    
    # Open Interest
    OI_SURGE_15M = 5.0  # +5%
    OI_SURGE_1H = 10.0  # +10%
    
    # Funding
    FUNDING_MAX_FOR_LONG = 0.0005  # 0.05%
    FUNDING_MIN_FOR_SHORT = 0.0008  # 0.08% (overleveraged)
    
    # Breakout
    ATR_MULTIPLIER = 1.5
    
    # Order Book
    IMBALANCE_THRESHOLD = 0.65  # 65%

# =============================================================================
# STOP-LOSS
# =============================================================================

class StopLossConfig:
    INITIAL_PERCENT = 3.5  # -3.5% from entry
    BUFFER_BEFORE_LIQUIDATION = 1.5  # %
    MOVE_TO_BREAKEVEN_AT = 5.0  # When profit reaches +5%

# =============================================================================
# TAKE-PROFIT
# =============================================================================

class TakeProfitConfig:
    LEVELS: List[Dict] = [
        {"profit": 5.0, "close": 30, "action": "move_sl_breakeven"},
        {"profit": 10.0, "close": 25, "action": "activate_trailing"},
        {"profit": 20.0, "close": 25, "action": "tighten_trailing"},
        {"profit": 50.0, "close": 20, "action": "let_ride"},
    ]

# =============================================================================
# TRAILING STOP
# =============================================================================

class TrailingStopConfig:
    ACTIVATION_PROFIT = 10.0  # Activate after +10%
    INITIAL_DISTANCE = 3.0  # 3% behind highest
    TIGHT_DISTANCE = 2.0  # 2% after +20%
    TIGHTEN_AT_PROFIT = 20.0

# =============================================================================
# PAIR FILTERS
# =============================================================================

class PairFilterConfig:
    QUOTE_ASSETS = ["USDT", "USDC"]
    CONTRACT_TYPE = "PERPETUAL"
    MIN_VOLUME_24H_USD = 5_000_000
    MIN_LISTING_AGE_HOURS = 48
    MAX_SPREAD_PERCENT = 0.15
    MIN_ORDERBOOK_DEPTH_USD = 200_000
    MIN_LEVERAGE_AVAILABLE = 10
    
    # Exclusions
    STABLECOINS = ["USDCUSDT", "TUSDUSDT", "DAIUSDT", "FDUSDUSDT"]
    
    # Scan intervals by tier (seconds)
    TIER_1_INTERVAL = 3  # Hot pairs
    TIER_2_INTERVAL = 5  # Active pairs
    TIER_3_INTERVAL = 10  # Normal pairs
    TIER_4_INTERVAL = 30  # Low priority

# =============================================================================
# MARKET REGIME
# =============================================================================

class MarketRegimeConfig:
    REFERENCE_PAIRS = ["BTCUSDT", "ETHUSDT"]
    ADX_PERIOD = 14
    ADX_TRENDING_THRESHOLD = 25
    ADX_CHOPPY_THRESHOLD = 20
    ATR_PERIOD = 14
    ATR_EXTREME_MULTIPLIER = 3.0
    EVALUATION_INTERVAL_MINUTES = 5

# =============================================================================
# REDIS
# =============================================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_PREFIX = "msb:"  # moonshot-bot prefix

# =============================================================================
# BINANCE
# =============================================================================

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() == "true"

# =============================================================================
# LOGGING
# =============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
BOT_TIMEZONE = os.getenv("BOT_TIMEZONE", "UTC")

# =============================================================================
# SERVER
# =============================================================================

PORT = int(os.getenv("PORT", "8050"))

# =============================================================================
# TIME LIMITS
# =============================================================================

class TimeLimitsConfig:
    MAX_HOLD_HOURS = 168  # 7 days maximum
