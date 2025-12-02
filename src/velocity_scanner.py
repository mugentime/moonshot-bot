"""
Velocity Scanner Module
Real-time velocity detection from WebSocket ticker stream.
Catches moonshots the MOMENT they start moving.
"""
import time
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict
from loguru import logger


@dataclass
class VelocityAlert:
    """Alert when velocity threshold is exceeded"""
    symbol: str
    velocity: float  # % change
    timeframe: str  # "1min", "5min", "15min"
    direction: str  # "LONG" or "SHORT"
    priority: str  # "HIGH", "MEDIUM", "LOW"
    timestamp: float


class VelocityScanner:
    """
    Real-time velocity detection from WebSocket ticker stream.
    Catches moonshots the MOMENT they start moving.

    Key difference from MoonshotDetector:
    - MoonshotDetector uses REST API klines (delayed, rate-limited)
    - VelocityScanner uses live WebSocket prices (instant, no limits)
    """

    def __init__(self):
        # Track price snapshots: symbol -> [(timestamp, price), ...]
        self.price_snapshots: Dict[str, List[Tuple[float, float]]] = defaultdict(list)

        # Alert thresholds (LOWERED for 80% moondrop capture rate)
        # Based on analysis of 6,392 moondrops - p20 thresholds to catch 80%+
        self.VELOCITY_1MIN = 1.5      # 1.5% in 1 minute = HIGH priority (was 3.0%)
        self.VELOCITY_5MIN = 2.0      # 2.0% in 5 minutes = MEDIUM priority (was 8.0%)
        self.VELOCITY_15MIN = 4.0     # 4.0% in 15 minutes = LOW priority (was 15.0%)

        # Early warning thresholds (for watchlist)
        self.VELOCITY_1MIN_EARLY = 0.8   # 0.8% in 1 min = early warning
        self.VELOCITY_5MIN_EARLY = 1.2   # 1.2% in 5 min = early warning

        # Cooldown tracking: symbol -> last_alert_time
        self.last_alerts: Dict[str, float] = {}
        self.ALERT_COOLDOWN = 60  # Don't re-alert same symbol for 60 seconds

        # Stats
        self.alerts_generated = 0
        self.snapshots_processed = 0

    def on_ticker_update(self, symbol: str, price: float) -> Optional[VelocityAlert]:
        """
        Called on every WebSocket ticker update.
        Returns VelocityAlert if threshold exceeded, None otherwise.
        """
        if price <= 0:
            return None

        now = time.time()
        self.snapshots_processed += 1

        # Store snapshot
        self.price_snapshots[symbol].append((now, price))

        # Keep only last 15 minutes of data (900 seconds)
        cutoff = now - 900
        self.price_snapshots[symbol] = [
            (t, p) for t, p in self.price_snapshots[symbol] if t > cutoff
        ]

        # Check cooldown
        if symbol in self.last_alerts:
            if now - self.last_alerts[symbol] < self.ALERT_COOLDOWN:
                return None

        # Calculate velocities for different timeframes
        velocity_1m = self._calculate_velocity(symbol, 60)
        velocity_5m = self._calculate_velocity(symbol, 300)
        velocity_15m = self._calculate_velocity(symbol, 900)

        # Check thresholds (most urgent first)
        alert = None

        if abs(velocity_1m) >= self.VELOCITY_1MIN:
            direction = "LONG" if velocity_1m > 0 else "SHORT"
            alert = VelocityAlert(
                symbol=symbol,
                velocity=velocity_1m,
                timeframe="1min",
                direction=direction,
                priority="HIGH",
                timestamp=now
            )
            logger.warning(f"🔥 VELOCITY ALERT [{symbol}]: {velocity_1m:+.1f}% in 1min - {direction}")

        elif abs(velocity_5m) >= self.VELOCITY_5MIN:
            direction = "LONG" if velocity_5m > 0 else "SHORT"
            alert = VelocityAlert(
                symbol=symbol,
                velocity=velocity_5m,
                timeframe="5min",
                direction=direction,
                priority="MEDIUM",
                timestamp=now
            )
            logger.info(f"⚡ VELOCITY ALERT [{symbol}]: {velocity_5m:+.1f}% in 5min - {direction}")

        elif abs(velocity_15m) >= self.VELOCITY_15MIN:
            direction = "LONG" if velocity_15m > 0 else "SHORT"
            alert = VelocityAlert(
                symbol=symbol,
                velocity=velocity_15m,
                timeframe="15min",
                direction=direction,
                priority="LOW",
                timestamp=now
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
            "symbols_in_cooldown": len([s for s, t in self.last_alerts.items()
                                        if time.time() - t < self.ALERT_COOLDOWN])
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
