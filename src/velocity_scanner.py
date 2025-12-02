"""
Velocity Scanner Module
Real-time velocity detection from WebSocket ticker stream.
Catches moonshots the MOMENT they start moving.

TIER SYSTEM (aligned with MoonshotDetector):
- Tier 1: 2.5%+ in 5min = INSTANT entry (bypasses all checks)
- Tier 2: 1.5%+ in 5min = FAST entry (volume confirmation)
- Tier 3: 1.5%+ in 1min = MICRO entry (consecutive candles)
"""
import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict
from loguru import logger

from config import MoonshotDetectionConfig


@dataclass
class VelocityAlert:
    """Alert when velocity threshold is exceeded"""
    symbol: str
    velocity: float  # % change
    timeframe: str  # "1min", "5min", "15min"
    direction: str  # "LONG" or "SHORT"
    priority: str  # "HIGH", "MEDIUM", "LOW"
    timestamp: float
    tier: int = 0  # 1, 2, or 3 (0 = legacy)
    bypass_checks: bool = False  # True for Tier 1
    is_peak_hour: bool = False


class VelocityScanner:
    """
    Real-time velocity detection from WebSocket ticker stream.
    Catches moonshots the MOMENT they start moving.

    Key difference from MoonshotDetector:
    - MoonshotDetector uses REST API klines (delayed, rate-limited)
    - VelocityScanner uses live WebSocket prices (instant, no limits)

    TIER SYSTEM (90%+ catch rate):
    - Tier 1: 2.5%+ in 5min = INSTANT (bypasses ALL checks)
    - Tier 2: 1.5%+ in 5min = FAST entry
    - Tier 3: 1.5%+ in 1min = MICRO entry
    """

    def __init__(self):
        # Track price snapshots: symbol -> [(timestamp, price), ...]
        self.price_snapshots: Dict[str, List[Tuple[float, float]]] = defaultdict(list)

        # TIER-ALIGNED THRESHOLDS (from MoonshotDetectionConfig)
        # Tier 1: Instant entry - bypasses all checks
        self.TIER1_VELOCITY_5MIN = MoonshotDetectionConfig.TIER1_VELOCITY_5M  # 2.5%
        # Tier 2: Fast entry
        self.TIER2_VELOCITY_5MIN = MoonshotDetectionConfig.TIER2_VELOCITY_5M  # 1.5%
        # Tier 3: Micro detection
        self.TIER3_VELOCITY_1MIN = MoonshotDetectionConfig.TIER3_VELOCITY_1M  # 1.5%

        # Legacy thresholds (for backwards compatibility)
        self.VELOCITY_1MIN = 1.5      # 1.5% in 1 minute = HIGH priority
        self.VELOCITY_5MIN = 2.0      # 2.0% in 5 minutes = MEDIUM priority
        self.VELOCITY_15MIN = 4.0     # 4.0% in 15 minutes = LOW priority

        # Early warning thresholds (for watchlist)
        self.VELOCITY_1MIN_EARLY = 0.8   # 0.8% in 1 min = early warning
        self.VELOCITY_5MIN_EARLY = 1.2   # 1.2% in 5 min = early warning

        # Peak hours (53% of moonshots start 18:00-00:00 UTC)
        self.PEAK_HOURS_UTC = MoonshotDetectionConfig.PEAK_HOURS_UTC
        self.PEAK_THRESHOLD_REDUCTION = MoonshotDetectionConfig.PEAK_HOUR_THRESHOLD_REDUCTION

        # Cooldown tracking: symbol -> last_alert_time
        self.last_alerts: Dict[str, float] = {}
        self.ALERT_COOLDOWN = MoonshotDetectionConfig.ALERT_COOLDOWN  # 15 seconds (was 60)

        # Stats
        self.alerts_generated = 0
        self.snapshots_processed = 0
        self.tier1_alerts = 0
        self.tier2_alerts = 0
        self.tier3_alerts = 0

    def _is_peak_hour(self) -> bool:
        """Check if current time is in peak moonshot hours (18:00-00:00 UTC)"""
        current_hour = datetime.now(timezone.utc).hour
        for start, end in self.PEAK_HOURS_UTC:
            if start <= current_hour < end:
                return True
        return False

    def _get_adjusted_threshold(self, base_threshold: float) -> float:
        """Reduce threshold during peak hours"""
        if self._is_peak_hour():
            return base_threshold * (1 - self.PEAK_THRESHOLD_REDUCTION)
        return base_threshold

    def on_ticker_update(self, symbol: str, price: float) -> Optional[VelocityAlert]:
        """
        Called on every WebSocket ticker update.
        Returns VelocityAlert if threshold exceeded, None otherwise.

        TIER PRIORITY (highest first):
        1. Tier 1: 2.5%+ in 5min = INSTANT entry (bypasses ALL checks)
        2. Tier 2: 1.5%+ in 5min = FAST entry
        3. Tier 3: 1.5%+ in 1min = MICRO entry
        4. Legacy thresholds for backwards compatibility
        """
        if price <= 0:
            return None

        now = time.time()
        self.snapshots_processed += 1
        is_peak = self._is_peak_hour()

        # Store snapshot
        self.price_snapshots[symbol].append((now, price))

        # Keep only last 15 minutes of data (900 seconds)
        cutoff = now - 900
        self.price_snapshots[symbol] = [
            (t, p) for t, p in self.price_snapshots[symbol] if t > cutoff
        ]

        # Check cooldown (reduced to 15s for faster re-alerts)
        if symbol in self.last_alerts:
            if now - self.last_alerts[symbol] < self.ALERT_COOLDOWN:
                return None

        # Calculate velocities for different timeframes
        velocity_1m = self._calculate_velocity(symbol, 60)
        velocity_5m = self._calculate_velocity(symbol, 300)
        velocity_15m = self._calculate_velocity(symbol, 900)

        # Get adjusted thresholds (reduced during peak hours)
        tier1_threshold = self._get_adjusted_threshold(self.TIER1_VELOCITY_5MIN)
        tier2_threshold = self._get_adjusted_threshold(self.TIER2_VELOCITY_5MIN)
        tier3_threshold = self._get_adjusted_threshold(self.TIER3_VELOCITY_1MIN)

        # Check TIER 1: INSTANT ENTRY (2.5%+ in 5min, bypasses ALL checks)
        alert = None

        if abs(velocity_5m) >= tier1_threshold:
            direction = "LONG" if velocity_5m > 0 else "SHORT"
            alert = VelocityAlert(
                symbol=symbol,
                velocity=velocity_5m,
                timeframe="5min",
                direction=direction,
                priority="CRITICAL",
                timestamp=now,
                tier=1,
                bypass_checks=True,
                is_peak_hour=is_peak
            )
            self.tier1_alerts += 1
            logger.warning(f"🚀🚀🚀 TIER 1 INSTANT [{symbol}]: {velocity_5m:+.1f}% in 5min - {direction} (BYPASS ALL)")

        # Check TIER 2: FAST ENTRY (1.5%+ in 5min)
        elif abs(velocity_5m) >= tier2_threshold:
            direction = "LONG" if velocity_5m > 0 else "SHORT"
            alert = VelocityAlert(
                symbol=symbol,
                velocity=velocity_5m,
                timeframe="5min",
                direction=direction,
                priority="HIGH",
                timestamp=now,
                tier=2,
                bypass_checks=False,
                is_peak_hour=is_peak
            )
            self.tier2_alerts += 1
            logger.warning(f"🚀🚀 TIER 2 FAST [{symbol}]: {velocity_5m:+.1f}% in 5min - {direction}")

        # Check TIER 3: MICRO ENTRY (1.5%+ in 1min)
        elif abs(velocity_1m) >= tier3_threshold:
            direction = "LONG" if velocity_1m > 0 else "SHORT"
            alert = VelocityAlert(
                symbol=symbol,
                velocity=velocity_1m,
                timeframe="1min",
                direction=direction,
                priority="HIGH",
                timestamp=now,
                tier=3,
                bypass_checks=False,
                is_peak_hour=is_peak
            )
            self.tier3_alerts += 1
            logger.info(f"🚀 TIER 3 MICRO [{symbol}]: {velocity_1m:+.1f}% in 1min - {direction}")

        # Legacy thresholds (for backwards compatibility)
        elif abs(velocity_15m) >= self.VELOCITY_15MIN:
            direction = "LONG" if velocity_15m > 0 else "SHORT"
            alert = VelocityAlert(
                symbol=symbol,
                velocity=velocity_15m,
                timeframe="15min",
                direction=direction,
                priority="LOW",
                timestamp=now,
                tier=0,
                bypass_checks=False,
                is_peak_hour=is_peak
            )
            logger.info(f"📈 VELOCITY ALERT [{symbol}]: {velocity_15m:+.1f}% in 15min - {direction}")

        if alert:
            self.last_alerts[symbol] = now
            self.alerts_generated += 1

        return alert

    def _calculate_velocity(self, symbol: str, seconds: int) -> float:
        """Calculate price velocity over specified seconds"""
        snapshots = self.price_snapshots.get(symbol, [])

        if len(snapshots) < 2:
            return 0.0

        now = time.time()
        cutoff = now - seconds

        # Find oldest price within timeframe
        old_price = None
        for t, p in snapshots:
            if t >= cutoff:
                old_price = p
                break

        if not old_price or old_price <= 0:
            return 0.0

        # Current price is the latest snapshot
        current_price = snapshots[-1][1]

        # Calculate percentage change
        velocity = ((current_price - old_price) / old_price) * 100

        return velocity

    def get_hot_symbols(self, min_velocity: float = 5.0) -> List[Tuple[str, float]]:
        """Get all symbols currently moving fast (for priority scanning)"""
        hot = []

        for symbol in self.price_snapshots.keys():
            velocity_5m = abs(self._calculate_velocity(symbol, 300))
            if velocity_5m >= min_velocity:
                hot.append((symbol, velocity_5m))

        # Sort by velocity (highest first)
        return sorted(hot, key=lambda x: x[1], reverse=True)

    def get_stats(self) -> dict:
        """Get scanner statistics"""
        return {
            "symbols_tracked": len(self.price_snapshots),
            "snapshots_processed": self.snapshots_processed,
            "alerts_generated": self.alerts_generated,
            "tier1_alerts": self.tier1_alerts,
            "tier2_alerts": self.tier2_alerts,
            "tier3_alerts": self.tier3_alerts,
            "symbols_in_cooldown": len([s for s, t in self.last_alerts.items()
                                        if time.time() - t < self.ALERT_COOLDOWN]),
            "is_peak_hour": self._is_peak_hour(),
            "alert_cooldown": self.ALERT_COOLDOWN
        }

    def clear_old_data(self):
        """Clear data for symbols with no recent updates"""
        now = time.time()
        stale_cutoff = now - 1800  # 30 minutes

        stale_symbols = []
        for symbol, snapshots in self.price_snapshots.items():
            if not snapshots or snapshots[-1][0] < stale_cutoff:
                stale_symbols.append(symbol)

        for symbol in stale_symbols:
            del self.price_snapshots[symbol]
            if symbol in self.last_alerts:
                del self.last_alerts[symbol]

        if stale_symbols:
            logger.debug(f"Cleared {len(stale_symbols)} stale symbols from velocity scanner")
