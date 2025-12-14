"""
MACRO INDEX STRATEGY - 24H TIMEFRAME
Composite indicator using 24-hour price changes for stable trend detection.

Strategy:
- Uses 24h price change data from Binance tickers (NOT 5-minute noise)
- Calculate macro score from 3 components:
  1. Majority vote (55%+ coins same direction on 24h)
  2. Leader-follower (top 10% movers direction)
  3. Aggregate velocity (average 24h change across all)
- Score >= +1 → LONG all coins
- Score <= -1 → SHORT all coins
- 1 HOUR COOLDOWN between direction changes to prevent whipsaws
- PER-POSITION 3% HARD STOP LOSS with exchange order
- TRAILING STOP: 10% distance, activates at +15% profit
- MACRO FLIP DOES NOT CLOSE POSITIONS - only SL/trailing stop can close
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum
from loguru import logger
import time


class MacroDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass
class MacroConfig:
    """Configuration for macro strategy - 24H TIMEFRAME"""
    # MACRO INDICATOR THRESHOLDS (24H based - relaxed for action)
    MAJORITY_THRESHOLD = 0.55  # 55% of coins must agree (lowered from 70%)
    LEADER_PERCENT = 0.10  # Top 10% are leaders
    AVG_VELOCITY_THRESHOLD = 1.0  # +/- 1% average 24h change (lowered from 2%)

    # TRIGGER THRESHOLDS (lowered to allow more trading)
    LONG_TRIGGER_SCORE = 1  # Score >= 1 to go LONG (was 2)
    SHORT_TRIGGER_SCORE = -1  # Score <= -1 to go SHORT (was -2)

    # DIRECTION CHANGE COOLDOWN (prevent whipsaws)
    DIRECTION_CHANGE_COOLDOWN_SECONDS = 3600  # 1 hour minimum between flips

    # EXIT PARAMETERS - Per-position stop loss with exchange order
    # With 20x leverage: 3% price move = 60% margin loss
    STOP_LOSS_PERCENT = 3.0  # 3% hard SL with exchange order
    TAKE_PROFIT_PERCENT = 999.0  # DISABLED - let macro direction decide exits for profits

    # TRAILING STOP - Lock in profits after big moves
    TRAILING_ACTIVATION_PERCENT = 15.0  # Activate trailing after +15% profit
    TRAILING_DISTANCE_PERCENT = 10.0  # Trail by 10% (if peak is +20%, exit at +10%)

    # POSITION SIZING
    LEVERAGE = 20  # 20x leverage (aggressive)
    MAX_POSITIONS = 61  # All coins

    # SCAN INTERVAL
    SCAN_INTERVAL = 30  # Calculate macro every 30 seconds


@dataclass
class MacroScore:
    """Result of macro indicator calculation"""
    total_score: int  # -3 to +3
    majority_score: int  # -1, 0, or +1
    leader_score: int  # -1, 0, or +1
    velocity_score: int  # -1, 0, or +1
    direction: MacroDirection
    coins_up: int
    coins_down: int
    avg_velocity: float
    leader_velocity: float
    timestamp: float


class MacroIndicator:
    """
    Calculates composite macro indicator using 24H TIMEFRAME data.

    Components (all based on 24h price changes):
    1. Majority Vote: 70%+ coins moving same direction on 24h
    2. Leader-Follower: Direction of top 10% movers on 24h
    3. Aggregate Velocity: Average 24h change across all coins

    Features:
    - Uses Binance 24h ticker data (stable, no 5m noise)
    - 1 hour cooldown between direction changes
    """

    def __init__(self, data_feed, config: MacroConfig = None):
        self.data_feed = data_feed
        self.config = config or MacroConfig()
        self.last_direction = MacroDirection.FLAT
        self.last_score: Optional[MacroScore] = None
        self.last_direction_change_time: float = 0  # Track when direction last changed

    async def calculate(self, symbols: List[str]) -> MacroScore:
        """
        Calculate the macro indicator using 24H price changes.

        Args:
            symbols: List of symbols to analyze (the whitelisted coins)

        Returns:
            MacroScore with direction and component scores
        """
        if not symbols:
            return MacroScore(
                total_score=0,
                majority_score=0,
                leader_score=0,
                velocity_score=0,
                direction=MacroDirection.FLAT,
                coins_up=0,
                coins_down=0,
                avg_velocity=0.0,
                leader_velocity=0.0,
                timestamp=time.time()
            )

        # Get 24H price changes for all symbols (from Binance tickers)
        velocities = await self._get_24h_changes(symbols)

        if not velocities:
            return MacroScore(
                total_score=0,
                majority_score=0,
                leader_score=0,
                velocity_score=0,
                direction=MacroDirection.FLAT,
                coins_up=0,
                coins_down=0,
                avg_velocity=0.0,
                leader_velocity=0.0,
                timestamp=time.time()
            )

        # Component 1: Majority Vote (24h)
        majority_score, coins_up, coins_down = self._calculate_majority(velocities)

        # Component 2: Leader-Follower (24h)
        leader_score, leader_velocity = self._calculate_leaders(velocities)

        # Component 3: Aggregate Velocity (24h average)
        velocity_score, avg_velocity = self._calculate_aggregate(velocities)

        # Calculate total score
        total_score = majority_score + leader_score + velocity_score

        # Determine raw direction from score
        if total_score >= self.config.LONG_TRIGGER_SCORE:
            raw_direction = MacroDirection.LONG
        elif total_score <= self.config.SHORT_TRIGGER_SCORE:
            raw_direction = MacroDirection.SHORT
        else:
            raw_direction = MacroDirection.FLAT

        # Apply cooldown - only allow direction change if cooldown has passed
        current_time = time.time()
        time_since_last_change = current_time - self.last_direction_change_time
        cooldown = self.config.DIRECTION_CHANGE_COOLDOWN_SECONDS

        if raw_direction != self.last_direction:
            if time_since_last_change >= cooldown:
                # Cooldown passed, allow direction change
                direction = raw_direction
                self.last_direction_change_time = current_time
                logger.info(f"{'='*60}")
                logger.info(f"24H MACRO DIRECTION CHANGE: {self.last_direction.value} -> {direction.value}")
                logger.info(f"Score: {total_score} (Majority: {majority_score}, Leaders: {leader_score}, Velocity: {velocity_score})")
                logger.info(f"Up: {coins_up} (24h), Down: {coins_down} (24h), Avg 24h: {avg_velocity:.2f}%")
                logger.info(f"{'='*60}")
                self.last_direction = direction
            else:
                # Cooldown not passed, keep old direction
                remaining = int(cooldown - time_since_last_change)
                logger.debug(f"Direction change blocked by cooldown. {remaining}s remaining. Raw: {raw_direction.value}, Keeping: {self.last_direction.value}")
                direction = self.last_direction
        else:
            direction = self.last_direction

        score = MacroScore(
            total_score=total_score,
            majority_score=majority_score,
            leader_score=leader_score,
            velocity_score=velocity_score,
            direction=direction,
            coins_up=coins_up,
            coins_down=coins_down,
            avg_velocity=avg_velocity,
            leader_velocity=leader_velocity,
            timestamp=time.time()
        )

        self.last_score = score
        return score

    async def _get_24h_changes(self, symbols: List[str]) -> Dict[str, float]:
        """Get 24-hour price change percent for all symbols from Binance tickers"""
        velocities = {}

        try:
            # Get all futures tickers at once (much faster than individual calls)
            tickers = await self.data_feed.client.futures_ticker()

            # Create lookup dict
            ticker_map = {t['symbol']: float(t['priceChangePercent']) for t in tickers}

            # Get 24h change for each whitelisted symbol
            for symbol in symbols:
                if symbol in ticker_map:
                    velocities[symbol] = ticker_map[symbol]

        except Exception as e:
            logger.error(f"Error getting 24h tickers: {e}")
            # Fallback to individual calls
            for symbol in symbols:
                try:
                    ticker = await self.data_feed.client.futures_ticker(symbol=symbol)
                    if ticker:
                        velocities[symbol] = float(ticker['priceChangePercent'])
                except Exception as e2:
                    logger.debug(f"Error getting 24h ticker for {symbol}: {e2}")
                    continue

        return velocities

    def _calculate_majority(self, velocities: Dict[str, float]) -> Tuple[int, int, int]:
        """
        Component 1: Majority Vote

        Returns:
            (score, coins_up, coins_down)
            score: +1 if 60%+ up, -1 if 60%+ down, 0 otherwise
        """
        if not velocities:
            return 0, 0, 0

        coins_up = sum(1 for v in velocities.values() if v > 0)
        coins_down = sum(1 for v in velocities.values() if v < 0)
        total = len(velocities)

        up_ratio = coins_up / total
        down_ratio = coins_down / total

        if up_ratio >= self.config.MAJORITY_THRESHOLD:
            return 1, coins_up, coins_down
        elif down_ratio >= self.config.MAJORITY_THRESHOLD:
            return -1, coins_up, coins_down
        else:
            return 0, coins_up, coins_down

    def _calculate_leaders(self, velocities: Dict[str, float]) -> Tuple[int, float]:
        """
        Component 2: Leader-Follower Detection

        Returns:
            (score, leader_avg_velocity)
            score: +1 if top 10% are positive, -1 if negative
        """
        if not velocities:
            return 0, 0.0

        # Sort by absolute velocity (biggest movers are leaders)
        sorted_velocities = sorted(velocities.items(), key=lambda x: abs(x[1]), reverse=True)

        # Get top 10% (leaders)
        leader_count = max(1, int(len(sorted_velocities) * self.config.LEADER_PERCENT))
        leaders = sorted_velocities[:leader_count]

        # Calculate average velocity of leaders
        leader_velocities = [v for _, v in leaders]
        avg_leader_velocity = sum(leader_velocities) / len(leader_velocities)

        # Direction based on leader average
        if avg_leader_velocity > 0:
            return 1, avg_leader_velocity
        elif avg_leader_velocity < 0:
            return -1, avg_leader_velocity
        else:
            return 0, avg_leader_velocity

    def _calculate_aggregate(self, velocities: Dict[str, float]) -> Tuple[int, float]:
        """
        Component 3: Aggregate Velocity

        Returns:
            (score, average_velocity)
            score: +1 if avg > +0.5%, -1 if avg < -0.5%
        """
        if not velocities:
            return 0, 0.0

        avg_velocity = sum(velocities.values()) / len(velocities)

        if avg_velocity >= self.config.AVG_VELOCITY_THRESHOLD:
            return 1, avg_velocity
        elif avg_velocity <= -self.config.AVG_VELOCITY_THRESHOLD:
            return -1, avg_velocity
        else:
            return 0, avg_velocity


class MacroExitManager:
    """
    Manages exits for positions.

    Exit conditions:
    1. Stop Loss: 3% - handled by EXCHANGE ORDER (not software)
    2. Trailing Stop: 10% distance, activates at +15% profit (software-based)
    """

    def __init__(self, config: MacroConfig = None):
        self.config = config or MacroConfig()

    def check_exit(self, direction: str, entry_price: float, current_price: float, peak_profit_pct: float = 0.0) -> Optional[Dict]:
        """
        Check if position should be exited based on Trailing Stop.

        NOTE: Stop Loss is handled by EXCHANGE ORDER (STOP_MARKET), not here.

        Exit conditions checked here:
        - Trailing Stop: If profit reached +15%, exit when it drops 10% from peak

        Returns:
            Dict with 'action': 'close' and 'reason' if exit triggered, None otherwise
        """
        if entry_price <= 0:
            return None

        # Calculate PnL percentage based on direction
        if direction == "LONG":
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:  # SHORT
            pnl_pct = ((entry_price - current_price) / entry_price) * 100

        # STOP LOSS is handled by exchange order - NOT checked here

        # Check TRAILING STOP - Lock in profits after big moves
        # Only active if we've reached the activation threshold
        if peak_profit_pct >= self.config.TRAILING_ACTIVATION_PERCENT:
            # Calculate trailing stop level (peak - distance)
            trailing_stop_level = peak_profit_pct - self.config.TRAILING_DISTANCE_PERCENT

            if pnl_pct <= trailing_stop_level:
                return {
                    'action': 'close',
                    'reason': 'trailing_stop',
                    'pnl_pct': pnl_pct,
                    'peak_pct': peak_profit_pct,
                    'trail_level': trailing_stop_level
                }

        return None
