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
    MIN_SIGNALS_REQUIRED = 3  # Out of 6 (AGGRESSIVE: was 4)

    # Volume - LOWERED for more sensitivity
    VOLUME_SPIKE_5M = 2.0  # 2x average (was 3x)
    VOLUME_SPIKE_1H = 3.0  # 3x average (was 5x)

    # Price velocity - LOWERED to catch earlier
    PRICE_VELOCITY_5M_LONG = 1.5  # +1.5% (was 2%)
    PRICE_VELOCITY_5M_SHORT = -1.5  # -1.5% (was -2%)
    PRICE_VELOCITY_1M = 0.5  # +0.5% (was 0.8%)

    # Open Interest
    OI_SURGE_15M = 5.0  # +5%
    OI_SURGE_1H = 10.0  # +10%

    # Funding (AGGRESSIVE: widened from 0.05%/0.08%)
    FUNDING_MAX_FOR_LONG = 0.003  # 0.3% - allow entry during hype
    FUNDING_MIN_FOR_SHORT = 0.002  # 0.2% - more squeeze opportunities

    # Breakout
    ATR_MULTIPLIER = 1.5

    # Order Book
    IMBALANCE_THRESHOLD = 0.65  # 65%

    # MEGA-SIGNAL OVERRIDE: If price moves >3% in 5min, bypass normal requirements
    MEGA_SIGNAL_VELOCITY = 3.0  # +3% in 5 min = confirmed moonshot (was 5%)
    MEGA_SIGNAL_MIN_SIGNALS = 1  # Only need 1/6 signals for mega-moves (was 2)

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
    MIN_VOLUME_24H_USD = 100_000  # ULTRA-AGGRESSIVE: $100K to catch small caps before moon
    MIN_LISTING_AGE_HOURS = 0  # Scan immediately on listing
    MAX_SPREAD_PERCENT = 0.5  # Allow wider spreads for moonshots (was 0.15)
    MIN_ORDERBOOK_DEPTH_USD = 50_000  # Lower depth requirement (was 200K)
    MIN_LEVERAGE_AVAILABLE = 10

    # Exclusions
    STABLECOINS = ["USDCUSDT", "TUSDUSDT", "DAIUSDT", "FDUSDUSDT"]

    # Scan intervals by tier (seconds) - AGGRESSIVE: faster scanning
    TIER_1_INTERVAL = 2  # Hot pairs (was 3)
    TIER_2_INTERVAL = 3  # Active pairs (was 5)
    TIER_3_INTERVAL = 5  # Normal pairs (was 10)
    TIER_4_INTERVAL = 10  # Low priority (was 30)

    # TIER 1 HOT SYMBOLS - Memecoins, AI, and recent moonshots
    TIER_1_SYMBOLS = [
        # Classic memecoins
        "DOGE", "SHIB", "PEPE", "BONK", "FLOKI", "WIF", "MEME", "BOME",
        # AI sector
        "FET", "AGIX", "RNDR", "TAO", "ARKM",
        # Recent top moonshots (last 5 days)
        "TAC", "PIPPIN", "RVV", "TRUST", "AIA", "MERL", "TANSSI", "TRADOOR",
        "PARTI", "RATS", "MON", "PARTIVERSE", "BANANAS31", "ARC", "BOB"
    ]

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
