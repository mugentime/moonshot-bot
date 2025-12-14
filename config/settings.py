"""
Moonshot Bot Configuration
All parameters defined in the planning phase
"""
import os
from typing import List, Dict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# ACCOUNT CONFIGURATION
# =============================================================================

INITIAL_EQUITY = float(os.getenv("INITIAL_EQUITY", "30.0"))
CURRENCY = "USDT"

# =============================================================================
# POSITION SIZING
# =============================================================================

class PositionSizingConfig:
    # MINIMUM $10 NOTIONAL per trade (Binance requirement)
    # With CROSSED margin, we can open more positions with shared margin
    MIN_NOTIONAL_USD = 10.0  # $10 minimum notional per trade (Binance min)
    MIN_MARGIN_USD = float(os.getenv("MIN_MARGIN_USD", "0.50"))  # Margin calculated from notional/leverage
    MAX_MARGIN_PERCENT = float(os.getenv("MAX_MARGIN_PERCENT", "15.0"))  # 15% max per trade (more aggressive)
    MAX_CONCURRENT_TRADES = int(os.getenv("MAX_CONCURRENT_TRADES", "34"))  # All coins
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
    # ==========================================================================
    # 3-TIER VELOCITY SYSTEM (90%+ CATCH RATE - Based on 183 moonshot analysis)
    # ==========================================================================

    # TIER 1 - INSTANT ENTRY (No confirmation needed, bypasses ALL checks)
    TIER1_VELOCITY_5M = 2.5  # +2.5% in 5min = IMMEDIATE entry (catches 90.7%)

    # TIER 2 - FAST ENTRY (Volume confirmation only)
    TIER2_VELOCITY_5M = 1.5  # +1.5% in 5min with volume spike
    TIER2_VOLUME_SPIKE = 1.3  # 1.3x average volume required

    # TIER 3 - MICRO DETECTION (1-minute candle tracking)
    TIER3_VELOCITY_1M = 1.5  # +1.5% in 1min (3 consecutive green candles)
    TIER3_CONSECUTIVE_CANDLES = 3  # Number of green candles needed

    # MOMENTUM STACK (catches slow builders like PIPPINUSDT +91.6%)
    MOMENTUM_1H_VELOCITY = 2.0  # +2% in 1 hour
    MOMENTUM_15M_VELOCITY = 1.0  # +1% in 15 min
    MOMENTUM_5M_VELOCITY = 0.5  # +0.5% in 5 min

    # ==========================================================================
    # PEAK HOUR OPTIMIZATION (53% of moonshots start 18:00-00:00 UTC)
    # ==========================================================================
    PEAK_HOURS_UTC = [(18, 24), (0, 1)]  # 18:00-00:00 and 00:00-01:00 UTC
    PEAK_HOUR_THRESHOLD_REDUCTION = 0.25  # Reduce thresholds by 25% during peak

    # ==========================================================================
    # COOLDOWNS (Aggressive for faster re-entry)
    # ==========================================================================
    ENTRY_COOLDOWN_TIER1 = 30   # 30 seconds for instant entries
    ENTRY_COOLDOWN_TIER2 = 60   # 60 seconds for fast entries
    ENTRY_COOLDOWN_TIER3 = 120  # 120 seconds for micro entries
    ALERT_COOLDOWN = 15  # 15 seconds between alerts (was 60)

    # ==========================================================================
    # SCAN FREQUENCY (Faster detection)
    # ==========================================================================
    SCAN_INTERVAL_ALL = 20      # 20 seconds for all 533 pairs
    SCAN_INTERVAL_TOP100 = 5    # 5 seconds for top movers

    # ==========================================================================
    # MOONDROP DETECTION (80%+ CAPTURE RATE - Based on 6,392 moondrop analysis)
    # ==========================================================================

    # TIER 1 - EXTREME MOONDROP (instant trigger)
    MOONDROP_EXTREME_VELOCITY_1M = -2.0  # -2% in 1 min = instant SHORT
    MOONDROP_EXTREME_VELOCITY_5M = -4.0  # -4% in 5 min = instant SHORT

    # TIER 2 - HIGH PRIORITY MOONDROP
    MOONDROP_HIGH_VELOCITY_5M = -1.5  # -1.5% in 5 min
    MOONDROP_HIGH_WICK_DROP = 3.0  # 3% wick drop

    # TIER 3 - MEDIUM MOONDROP (80% capture)
    MOONDROP_MEDIUM_VELOCITY_5M = -0.8  # -0.8% in 5 min (catches 80%+)
    MOONDROP_MEDIUM_WICK_DROP = 2.0  # 2% wick drop (catches 97%)
    MOONDROP_MEDIUM_BODY_DROP = 0.8  # 0.8% bearish body
    MOONDROP_MEDIUM_RANGE_EXP = 1.3  # 1.3x range expansion

    # TIER 4 - EARLY DETECTION (watchlist only)
    MOONDROP_EARLY_WICK_DROP = 1.5  # 1.5% wick drop
    MOONDROP_EARLY_VOL_SPIKE = 1.2  # 1.2x volume spike

    # ==========================================================================
    # LEGACY SIGNALS (Still used for Tier 2/3 confirmation)
    # ==========================================================================
    MIN_SIGNALS_REQUIRED = 3  # Out of 6 (bypassed for Tier 1)

    # Volume - LOWERED for 80% capture
    VOLUME_SPIKE_5M = 1.3  # 1.3x average (was 2x) - p25 is 1.06x
    VOLUME_SPIKE_1H = 2.0  # 2x average (was 3x)

    # Price velocity - LOWERED for 80% capture
    PRICE_VELOCITY_5M_LONG = 0.8  # +0.8% (was 1.5%)
    PRICE_VELOCITY_5M_SHORT = -0.8  # -0.8% (was -1.5%) - catches 80%+
    PRICE_VELOCITY_1M = 0.3  # +0.3% (was 0.5%)

    # NEW: Wick drop detection (catches 97% of moondrops at 2.0%)
    WICK_DROP_THRESHOLD = 2.0  # 2% wick = moondrop signal
    BODY_DROP_MIN = 0.5  # 0.5% bearish body

    # NEW: Range expansion (catches 80% at 1.1x)
    RANGE_EXPANSION_MIN = 1.1  # 1.1x average range = volatility spike

    # Open Interest
    OI_SURGE_15M = 5.0  # +5%
    OI_SURGE_1H = 10.0  # +10%

    # Funding
    FUNDING_MAX_FOR_LONG = 0.003  # 0.3%
    FUNDING_MIN_FOR_SHORT = 0.002  # 0.2%

    # Breakout
    ATR_MULTIPLIER = 1.5

    # Order Book
    IMBALANCE_THRESHOLD = 0.65  # 65%

    # MEGA-SIGNAL OVERRIDE - LOWERED for 80% capture
    MEGA_SIGNAL_VELOCITY = 2.0  # +2% in 5 min (was 3%)
    MEGA_SIGNAL_MIN_SIGNALS = 1  # Only need 1/6 signals

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

    # ==========================================================================
    # ALLOWED COINS - ONLY trade valid Binance Futures perpetual contracts
    # Set to None to allow all coins, or a set of symbols to restrict
    # Updated: 2025-12-07 - Removed 27 invalid/delisted symbols
    # ==========================================================================
    ALLOWED_COINS = {
        # VALID MOONSHOTS (verified active on Binance Futures)
        "USTCUSDT", "MOODENGUSDT", "LUNA2USDT",
        "SWARMSUSDT", "DOODUSDT", "BEATUSDT",
        "NOTUSDT", "SYNUSDT",
        "RONINUSDT", "HEMIUSDT", "POWERUSDT", "MUBARAKUSDT", "1000LUNCUSDT",
        "BULLAUSDT", "HMSTRUSDT", "GOATUSDT", "C98USDT",
        "FETUSDT", "MEWUSDT", "SUIUSDT", "ZENUSDT", "SHELLUSDT",
        "RIFUSDT", "LPTUSDT",
        # VALID MOONDROPS (verified active on Binance Futures)
        "PIPPINUSDT", "HUSDT", "SKATEUSDT",
        "PNUTUSDT", "PUFFERUSDT", "ZEREBROUSDT", "STABLEUSDT",
        "ARIAUSDT", "BIOUSDT", "WLDUSDT",
    }

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


# =============================================================================
# MOMENTUM HUNTER STRATEGY
# =============================================================================

class MomentumConfig:
    """
    Momentum Hunter Strategy Configuration
    Detects coins moving +1% in 60 seconds and rides the momentum.
    """
    # Hot coins refresh
    HOT_COINS_REFRESH_HOURS = 4  # Refresh every 4 hours
    HOT_COINS_COUNT = 50  # Top 50 by volume * volatility

    # Scanning
    SCAN_INTERVAL_SECONDS = 5  # Scan every 5 seconds
    PRICE_BUFFER_WINDOW = 60  # 60-second rolling window

    # Entry thresholds
    LONG_VELOCITY_TRIGGER = 1.0   # +1% in 60 sec = LONG
    SHORT_VELOCITY_TRIGGER = -1.0  # -1% in 60 sec = SHORT

    # Position sizing
    MAX_POSITIONS = 5  # Max concurrent trades
    POSITION_SIZE_USD = 10.0  # $10 per trade (minimum notional)
    LEVERAGE = 20  # 20x leverage

    # Exit thresholds
    STOP_LOSS_PERCENT = -3.0  # -3% = close
    TAKE_PROFIT_PERCENT = 10.0  # +10% = close
    TRAILING_ACTIVATE_PERCENT = 5.0  # Activate trailing after +5%
    TRAILING_DISTANCE_PERCENT = 2.0  # Trail by 2%

    # Cooldowns
    ENTRY_COOLDOWN_SECONDS = 60  # 60 sec after exit before re-entry
