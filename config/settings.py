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
# STOP-LOSS - HARD 2% STOP (ACCOUNT PROTECTION)
# =============================================================================

class StopLossConfig:
    INITIAL_PERCENT = 2.0  # -2% HARD STOP (was 3.5% - killing account)
    BUFFER_BEFORE_LIQUIDATION = 1.0  # %
    MOVE_TO_BREAKEVEN_AT = 5.0  # When profit reaches +5%, move SL to breakeven

# =============================================================================
# TAKE-PROFIT - 10% TARGET WITH 5% TRAILING
# =============================================================================

class TakeProfitConfig:
    LEVELS: List[Dict] = [
        {"profit": 5.0, "close": 30, "action": "move_sl_breakeven"},  # At +5%: Lock 30%, SL to breakeven
        {"profit": 10.0, "close": 50, "action": "activate_trailing"}, # At +10%: Take 50%, activate 5% trailing
    ]

# =============================================================================
# TRAILING STOP - 5% TRAILING AFTER 10% PROFIT
# =============================================================================

class TrailingStopConfig:
    # ==========================================================================
    # SIMPLIFIED TRAILING: 5% DISTANCE AFTER 10% PROFIT
    # ==========================================================================

    # ACTIVATION - Only after TP hit
    ACTIVATION_PROFIT = 10.0  # Activate trailing at +10% profit (after TP1)

    # SINGLE 5% TRAILING DISTANCE (simplified)
    TIER1_DISTANCE = 5.0      # 5% trailing stop distance
    TIER2_DISTANCE = 5.0      # 5% trailing (same)
    TIER3_DISTANCE = 5.0      # 5% trailing (same)
    TIER4_DISTANCE = 5.0      # 5% trailing (same)

    # PROFIT THRESHOLDS (all use same 5% distance)
    TIER2_PROFIT = 15.0
    TIER3_PROFIT = 20.0
    TIER4_PROFIT = 30.0

    # LEGACY (backwards compat)
    INITIAL_DISTANCE = 5.0    # 5% behind highest
    TIGHT_DISTANCE = 5.0      # 5% always
    TIGHTEN_AT_PROFIT = 30.0


class VelocityExitConfig:
    """
    Velocity Reversal Exit - Catches pump-and-dump reversals fast.
    Based on 183 moonshot analysis: 11% are pump-and-dumps that reverse fast.
    """
    # PARTIAL CLOSE ON VELOCITY REVERSAL
    PARTIAL_CLOSE_VELOCITY = -2.0  # Close 50% if 1m velocity drops -2% from peak
    PARTIAL_CLOSE_PERCENT = 50     # Close 50% of position

    # FULL CLOSE ON SEVERE REVERSAL
    FULL_CLOSE_VELOCITY = -3.0     # Close remaining if 1m velocity drops -3%

    # TIME-BASED EXIT (for instant pumps - 29% of moonshots are 0h duration)
    INSTANT_PUMP_PROFIT = 5.0       # If +5% profit within 10 min
    INSTANT_PUMP_WINDOW_SECONDS = 600  # 10 minutes
    INSTANT_PUMP_CLOSE_PERCENT = 50  # Close 50% to lock in profits

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
    # ALLOWED COINS - ONLY trade these 61 coins (10%+ movers in last 24h)
    # Set to None to allow all coins, or a set of symbols to restrict
    # ==========================================================================
    ALLOWED_COINS = {
        # MOONSHOTS (33 gainers 10%+)
        "ALPACAUSDT", "USTCUSDT", "BNXUSDT", "MOODENGUSDT", "LUNA2USDT",
        "ALPHAUSDT", "SWARMSUSDT", "DOODUSDT", "BEATUSDT",
        "NOTUSDT", "SYNUSDT", "OCEANUSDT", "DGBUSDT", "AGIXUSDT",
        "RONINUSDT", "HEMIUSDT", "POWERUSDT", "MUBARAKUSDT", "1000LUNCUSDT",
        "BULLAUSDT", "LINAUSDT", "HMSTRUSDT", "GOATUSDT", "C98USDT",
        "FETUSDT", "MEWUSDT", "SUIUSDT", "ZENUSDT", "SHELLUSDT",
        "RIFUSDT", "SXPUSDT", "LPTUSDT",
        # MOONDROPS (28 losers 10%+)
        "PORT3USDT", "BSWUSDT", "NEIROETHUSDT", "VIDTUSDT", "TROYUSDT",
        "BAKEUSDT", "AMBUSDT", "KDAUSDT", "FLMUSDT", "MEMEFIUSDT",
        "PIPPINUSDT", "NULSUSDT", "PERPUSDT", "HUSDT", "SKATEUSDT",
        "HIFIUSDT", "OBOLUSDT", "MILKUSDT", "LEVERUSDT", "1000XUSDT",
        "MYROUSDT", "PNUTUSDT", "PUFFERUSDT", "ZEREBROUSDT", "STABLEUSDT",
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
