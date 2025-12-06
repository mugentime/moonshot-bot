"""
SIMPLIFIED MOONSHOT STRATEGY
Based on analysis of top 30 moves (15 moonshots + 15 moondrops)

Strategy:
- Entry: 2% move in 5 minutes → enter in direction of move
- Stop Loss: 3% from entry (fixed)
- Trailing: Activate at 2% profit, 3% distance from peak
- No take-profit levels, just ride with trailing

Expected Performance (from backtesting top 30 moves):
- 3% trailing captures avg 51% per moonshot, 23% per moondrop
"""
import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Dict, List
from loguru import logger


@dataclass
class SimpleSignal:
    """Simple signal - just symbol, direction, and velocity"""
    symbol: str
    direction: str  # "LONG" or "SHORT"
    velocity_5m: float
    timestamp: float
    entry_price: float


@dataclass
class SimpleConfig:
    """Simplified strategy configuration"""
    # ENTRY
    ENTRY_VELOCITY_5M = 2.0  # 2% move in 5 min to enter

    # STOP LOSS
    STOP_LOSS_PERCENT = 3.0  # 3% fixed stop loss

    # TRAILING STOP
    TRAILING_ACTIVATION = 2.0  # Activate trailing at 2% profit
    TRAILING_DISTANCE = 3.0  # 3% distance from peak

    # POSITION
    MAX_POSITIONS = 10  # Max 10 positions at a time
    LEVERAGE = 10  # Fixed 10x leverage (safer)

    # COOLDOWNS
    ENTRY_COOLDOWN = 60  # 60 seconds between entries on same symbol
    SCAN_INTERVAL = 5  # Scan every 5 seconds


class SimpleDetector:
    """
    Simple moonshot/moondrop detector
    Just looks for 2% moves in 5 minutes
    """

    def __init__(self, data_feed, config: SimpleConfig = None):
        self.data_feed = data_feed
        self.config = config or SimpleConfig()
        self.last_entry_time: Dict[str, float] = {}

    async def scan(self, symbol: str) -> Optional[SimpleSignal]:
        """
        Scan for entry signal
        Returns signal if 2%+ move detected in last 5 minutes
        """
        try:
            # Check cooldown
            now = time.time()
            if symbol in self.last_entry_time:
                if now - self.last_entry_time[symbol] < self.config.ENTRY_COOLDOWN:
                    return None

            # Get 5-minute velocity
            await self.data_feed.get_klines(symbol, '1m', 10)
            velocity_5m = self.data_feed.get_price_change_percent(symbol, 5)

            if velocity_5m is None:
                return None

            # Check for entry signal
            if velocity_5m >= self.config.ENTRY_VELOCITY_5M:
                # LONG signal
                current_price = self.data_feed.get_current_price(symbol)
                logger.info(f"🚀 SIMPLE LONG SIGNAL: {symbol} +{velocity_5m:.2f}%")
                self.last_entry_time[symbol] = now
                return SimpleSignal(
                    symbol=symbol,
                    direction="LONG",
                    velocity_5m=velocity_5m,
                    timestamp=now,
                    entry_price=current_price
                )

            elif velocity_5m <= -self.config.ENTRY_VELOCITY_5M:
                # SHORT signal
                current_price = self.data_feed.get_current_price(symbol)
                logger.info(f"📉 SIMPLE SHORT SIGNAL: {symbol} {velocity_5m:.2f}%")
                self.last_entry_time[symbol] = now
                return SimpleSignal(
                    symbol=symbol,
                    direction="SHORT",
                    velocity_5m=velocity_5m,
                    timestamp=now,
                    entry_price=current_price
                )

            return None

        except Exception as e:
            logger.debug(f"Error scanning {symbol}: {e}")
            return None


class SimpleExitManager:
    """
    Simple exit manager
    - Fixed 3% stop loss
    - Trailing stop: activates at 2% profit, 3% distance
    """

    def __init__(self, config: SimpleConfig = None):
        self.config = config or SimpleConfig()
        self.peak_prices: Dict[str, float] = {}  # Track peak price per position
        self.trailing_active: Dict[str, bool] = {}  # Track if trailing is active

    def check_exit(self, symbol: str, direction: str, entry_price: float,
                   current_price: float) -> Optional[Dict]:
        """
        Check if position should be exited
        Returns exit action or None
        """
        # Calculate current profit %
        if direction == "LONG":
            profit_pct = ((current_price - entry_price) / entry_price) * 100
            # Update peak price
            if symbol not in self.peak_prices or current_price > self.peak_prices[symbol]:
                self.peak_prices[symbol] = current_price
        else:  # SHORT
            profit_pct = ((entry_price - current_price) / entry_price) * 100
            # Update peak (lowest for shorts)
            if symbol not in self.peak_prices or current_price < self.peak_prices[symbol]:
                self.peak_prices[symbol] = current_price

        # CHECK 1: Stop Loss (3%)
        if profit_pct <= -self.config.STOP_LOSS_PERCENT:
            logger.warning(f"🛑 STOP LOSS HIT: {symbol} {profit_pct:.2f}%")
            self._cleanup(symbol)
            return {
                "action": "close",
                "reason": "stop_loss",
                "profit_pct": profit_pct,
                "close_percent": 100
            }

        # CHECK 2: Trailing Stop
        # Activate trailing at 2% profit
        if profit_pct >= self.config.TRAILING_ACTIVATION:
            self.trailing_active[symbol] = True

        if self.trailing_active.get(symbol, False):
            peak = self.peak_prices.get(symbol, entry_price)

            if direction == "LONG":
                # For longs, exit if price drops 3% from peak
                drop_from_peak = ((peak - current_price) / peak) * 100
                if drop_from_peak >= self.config.TRAILING_DISTANCE:
                    logger.info(f"📈 TRAILING STOP: {symbol} +{profit_pct:.2f}% (dropped {drop_from_peak:.2f}% from peak)")
                    self._cleanup(symbol)
                    return {
                        "action": "close",
                        "reason": "trailing_stop",
                        "profit_pct": profit_pct,
                        "close_percent": 100
                    }
            else:  # SHORT
                # For shorts, exit if price rises 3% from trough
                rise_from_trough = ((current_price - peak) / peak) * 100
                if rise_from_trough >= self.config.TRAILING_DISTANCE:
                    logger.info(f"📉 TRAILING STOP: {symbol} +{profit_pct:.2f}% (bounced {rise_from_trough:.2f}% from trough)")
                    self._cleanup(symbol)
                    return {
                        "action": "close",
                        "reason": "trailing_stop",
                        "profit_pct": profit_pct,
                        "close_percent": 100
                    }

        return None

    def _cleanup(self, symbol: str):
        """Clean up tracking data for closed position"""
        self.peak_prices.pop(symbol, None)
        self.trailing_active.pop(symbol, None)

    def reset(self, symbol: str):
        """Reset tracking for a symbol"""
        self._cleanup(symbol)
