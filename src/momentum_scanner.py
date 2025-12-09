"""
Momentum Scanner Module
Detects coins moving +1% in 60 seconds and tracks hot coins by activity.
"""
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set
from loguru import logger


@dataclass
class MomentumSignal:
    """A detected momentum signal"""
    symbol: str
    direction: str  # "LONG" or "SHORT"
    velocity: float  # % change in window
    price: float
    timestamp: float


class PriceBuffer:
    """
    Rolling price buffer for momentum detection.
    Stores last N seconds of prices for each symbol.
    """

    def __init__(self, window_seconds: int = 60):
        self.window = window_seconds
        self.prices: Dict[str, deque] = {}  # symbol -> deque of (timestamp, price)

    def update(self, symbol: str, price: float) -> None:
        """Add a price point and trim old entries"""
        now = time.time()

        if symbol not in self.prices:
            self.prices[symbol] = deque(maxlen=30)  # ~2 sec intervals for 60 sec

        self.prices[symbol].append((now, price))

        # Trim entries older than window
        while self.prices[symbol] and now - self.prices[symbol][0][0] > self.window:
            self.prices[symbol].popleft()

    def get_velocity(self, symbol: str) -> float:
        """
        Calculate % change over the buffer window.
        Returns 0 if not enough data.
        """
        if symbol not in self.prices or len(self.prices[symbol]) < 2:
            return 0.0

        oldest_ts, oldest_price = self.prices[symbol][0]
        newest_ts, newest_price = self.prices[symbol][-1]

        # Need at least 10 seconds of data for reliable velocity
        if newest_ts - oldest_ts < 10:
            return 0.0

        if oldest_price <= 0:
            return 0.0

        return ((newest_price - oldest_price) / oldest_price) * 100

    def get_data_age(self, symbol: str) -> float:
        """Get seconds of data we have for this symbol"""
        if symbol not in self.prices or len(self.prices[symbol]) < 2:
            return 0.0

        oldest_ts = self.prices[symbol][0][0]
        newest_ts = self.prices[symbol][-1][0]
        return newest_ts - oldest_ts

    def clear(self, symbol: str = None) -> None:
        """Clear price data for a symbol or all symbols"""
        if symbol:
            self.prices.pop(symbol, None)
        else:
            self.prices.clear()


class HotCoinsManager:
    """
    Manages the dynamic "hot coins" list.
    Refreshes every N hours based on volume * volatility.
    """

    def __init__(self, count: int = 50, refresh_hours: float = 4):
        self.count = count
        self.refresh_interval = refresh_hours * 3600  # Convert to seconds
        self.hot_coins: Set[str] = set()
        self.last_refresh: float = 0
        self.scores: Dict[str, float] = {}  # For debugging

    def needs_refresh(self) -> bool:
        """Check if we need to refresh the hot coins list"""
        return time.time() - self.last_refresh > self.refresh_interval

    async def refresh(self, client) -> List[str]:
        """
        Refresh the hot coins list based on volume * volatility.
        Returns the new list of hot coins.
        """
        try:
            tickers = await client.futures_ticker()

            scored = []
            for t in tickers:
                symbol = t['symbol']

                # Only USDT pairs
                if not symbol.endswith('USDT'):
                    continue

                # Skip stablecoins
                if symbol in ('USDCUSDT', 'TUSDUSDT', 'DAIUSDT', 'FDUSDUSDT'):
                    continue

                try:
                    volume = float(t.get('quoteVolume', 0))
                    volatility = abs(float(t.get('priceChangePercent', 0)))

                    # Score = volume * volatility (higher = more action)
                    score = volume * volatility

                    if score > 0:
                        scored.append((symbol, score))
                except (ValueError, TypeError):
                    continue

            # Sort by score descending
            scored.sort(key=lambda x: x[1], reverse=True)

            # Take top N
            self.hot_coins = set(s[0] for s in scored[:self.count])
            self.scores = {s[0]: s[1] for s in scored[:self.count]}
            self.last_refresh = time.time()

            logger.info(f"Refreshed hot coins: {len(self.hot_coins)} coins selected")
            logger.debug(f"Top 5: {[s[0] for s in scored[:5]]}")

            return list(self.hot_coins)

        except Exception as e:
            logger.error(f"Error refreshing hot coins: {e}")
            return list(self.hot_coins)

    def is_hot(self, symbol: str) -> bool:
        """Check if a symbol is in the hot coins list"""
        return symbol in self.hot_coins

    def get_list(self) -> List[str]:
        """Get the current hot coins list"""
        return list(self.hot_coins)


@dataclass
class Position:
    """Tracked position for exit management"""
    symbol: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    entry_time: float
    quantity: float
    peak_profit: float = 0.0  # For trailing stop
    trailing_active: bool = False


class PositionManager:
    """
    Manages open positions and exit logic.
    Tracks entries, applies SL/TP/trailing, handles cooldowns.
    """

    def __init__(self, config):
        self.config = config
        self.positions: Dict[str, Position] = {}  # symbol -> Position
        self.cooldowns: Dict[str, float] = {}  # symbol -> cooldown_until timestamp

    def has_position(self, symbol: str) -> bool:
        """Check if we have an open position on this symbol"""
        return symbol in self.positions

    def can_open(self, symbol: str) -> bool:
        """Check if we can open a new position on this symbol"""
        # Already have position?
        if self.has_position(symbol):
            return False

        # On cooldown?
        if symbol in self.cooldowns:
            if time.time() < self.cooldowns[symbol]:
                return False
            else:
                del self.cooldowns[symbol]

        # Max positions reached?
        if len(self.positions) >= self.config.MAX_POSITIONS:
            return False

        return True

    def add_position(self, symbol: str, direction: str, entry_price: float, quantity: float) -> None:
        """Record a new position"""
        self.positions[symbol] = Position(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            entry_time=time.time(),
            quantity=quantity
        )
        logger.info(f"Position added: {direction} {symbol} @ {entry_price}")

    def remove_position(self, symbol: str) -> Optional[Position]:
        """Remove and return a position, set cooldown"""
        pos = self.positions.pop(symbol, None)
        if pos:
            self.cooldowns[symbol] = time.time() + self.config.ENTRY_COOLDOWN_SECONDS
            logger.info(f"Position removed: {symbol}, cooldown {self.config.ENTRY_COOLDOWN_SECONDS}s")
        return pos

    def check_exit(self, symbol: str, current_price: float) -> Optional[str]:
        """
        Check if position should be exited.
        Returns exit reason or None.
        """
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        entry = pos.entry_price

        # Calculate PnL %
        if pos.direction == "LONG":
            pnl_pct = ((current_price - entry) / entry) * 100
        else:  # SHORT
            pnl_pct = ((entry - current_price) / entry) * 100

        # Update peak profit for trailing
        if pnl_pct > pos.peak_profit:
            pos.peak_profit = pnl_pct

        # Check stop loss
        if pnl_pct <= self.config.STOP_LOSS_PERCENT:
            return "stop_loss"

        # Check take profit
        if pnl_pct >= self.config.TAKE_PROFIT_PERCENT:
            return "take_profit"

        # Check trailing stop
        if pos.peak_profit >= self.config.TRAILING_ACTIVATE_PERCENT:
            pos.trailing_active = True
            trail_trigger = pos.peak_profit - self.config.TRAILING_DISTANCE_PERCENT
            if pnl_pct <= trail_trigger:
                return "trailing_stop"

        return None

    def get_pnl(self, symbol: str, current_price: float) -> float:
        """Get current PnL % for a position"""
        if symbol not in self.positions:
            return 0.0

        pos = self.positions[symbol]
        entry = pos.entry_price

        if pos.direction == "LONG":
            return ((current_price - entry) / entry) * 100
        else:
            return ((entry - current_price) / entry) * 100

    def get_all(self) -> List[Position]:
        """Get all open positions"""
        return list(self.positions.values())

    def count(self) -> int:
        """Get number of open positions"""
        return len(self.positions)


class MomentumDetector:
    """
    Main momentum detection engine.
    Combines price buffer + hot coins + signal generation.
    """

    def __init__(self, config):
        self.config = config
        self.price_buffer = PriceBuffer(window_seconds=config.PRICE_BUFFER_WINDOW)
        self.hot_coins = HotCoinsManager(
            count=config.HOT_COINS_COUNT,
            refresh_hours=config.HOT_COINS_REFRESH_HOURS
        )

    async def refresh_hot_coins(self, client) -> List[str]:
        """Refresh the hot coins list if needed"""
        if self.hot_coins.needs_refresh():
            return await self.hot_coins.refresh(client)
        return self.hot_coins.get_list()

    def update_prices(self, tickers: List[dict]) -> None:
        """Update price buffer from ticker data"""
        for t in tickers:
            symbol = t['symbol']
            if not self.hot_coins.is_hot(symbol):
                continue

            try:
                price = float(t['lastPrice'])
                self.price_buffer.update(symbol, price)
            except (ValueError, TypeError, KeyError):
                continue

    def scan_for_signals(self) -> List[MomentumSignal]:
        """
        Scan all hot coins for momentum signals.
        Returns list of signals that meet threshold.
        """
        signals = []

        for symbol in self.hot_coins.get_list():
            velocity = self.price_buffer.get_velocity(symbol)

            # Need sufficient data
            if self.price_buffer.get_data_age(symbol) < 30:  # At least 30 sec
                continue

            # Get current price
            if symbol not in self.price_buffer.prices or not self.price_buffer.prices[symbol]:
                continue
            current_price = self.price_buffer.prices[symbol][-1][1]

            # Check LONG signal
            if velocity >= self.config.LONG_VELOCITY_TRIGGER:
                signals.append(MomentumSignal(
                    symbol=symbol,
                    direction="LONG",
                    velocity=velocity,
                    price=current_price,
                    timestamp=time.time()
                ))

            # Check SHORT signal
            elif velocity <= self.config.SHORT_VELOCITY_TRIGGER:
                signals.append(MomentumSignal(
                    symbol=symbol,
                    direction="SHORT",
                    velocity=velocity,
                    price=current_price,
                    timestamp=time.time()
                ))

        # Sort by absolute velocity (strongest signals first)
        signals.sort(key=lambda s: abs(s.velocity), reverse=True)

        return signals
