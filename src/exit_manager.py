"""
Exit Manager Module
Manages all exit conditions: SL, TP, trailing, funding-based exits

AGGRESSIVE EXIT STRATEGY (For Maximum Catch Mode + Pump-and-Dump Protection):
- Early trailing stop activation at +2% profit
- Tiered trailing distances (2% -> 3% -> 5%)
- Velocity reversal detection for pump-and-dump protection
- Time-based exits for instant pumps
"""
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger
import time

from config import (
    StopLossConfig, TakeProfitConfig, TrailingStopConfig,
    FundingConfig, TimeLimitsConfig, LeverageConfig, VelocityExitConfig
)


class ExitReason(Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    FUNDING_EXIT = "funding_exit"
    MAX_HOLD_TIME = "max_hold_time"
    REGIME_CHANGE = "regime_change"
    VELOCITY_REVERSAL = "velocity_reversal"  # NEW: Pump-and-dump protection
    INSTANT_PUMP_EXIT = "instant_pump_exit"  # NEW: Time-based for fast pumps
    MANUAL = "manual"


@dataclass
class ExitAction:
    type: str  # "CLOSE_ALL", "CLOSE_PARTIAL"
    symbol: str
    reason: ExitReason
    close_percent: float  # 100 for full close
    details: Dict = field(default_factory=dict)


@dataclass
class PositionState:
    symbol: str
    direction: str
    entry_price: float
    margin: float
    leverage: int
    stop_loss: float
    highest_price: float
    lowest_price: float
    tp_levels_hit: List[str] = field(default_factory=list)
    trailing_active: bool = False
    trailing_tight: bool = False
    entry_time: float = field(default_factory=time.time)
    remaining_percent: float = 100.0
    # NEW: Velocity tracking for pump-and-dump protection
    peak_profit_percent: float = 0.0  # Track highest profit reached
    last_velocity_1m: float = 0.0  # Track 1m velocity for reversal detection
    velocity_partial_closed: bool = False  # Track if partial close happened on reversal
    instant_pump_closed: bool = False  # Track if instant pump partial close happened


class ExitManager:
    """
    Manages all exit logic for positions:
    - Initial stop-loss
    - Escalonated take-profit
    - AGGRESSIVE TIERED trailing stop (early activation at +2%)
    - Funding-based exits
    - Time-based exits
    - Regime change exits
    - NEW: Velocity reversal detection (pump-and-dump protection)
    - NEW: Instant pump time-based exits

    AGGRESSIVE EXIT STRATEGY:
    - Trailing activates at +2% (not waiting for +10%)
    - Tiered distances: 2% (profit 2-5%), 3% (5-20%), 5% (20%+)
    - Velocity reversal: Close 50% on -2% drop from peak, 100% on -3%
    - Instant pump: Close 50% if +5% profit within 10 minutes
    """

    def __init__(self, data_feed):
        self.data_feed = data_feed

        self.positions: Dict[str, PositionState] = {}

        # Configs
        self.sl_config = StopLossConfig
        self.tp_levels = TakeProfitConfig.LEVELS
        self.trailing_config = TrailingStopConfig
        self.funding_config = FundingConfig
        self.time_config = TimeLimitsConfig
        self.velocity_exit_config = VelocityExitConfig  # NEW: Pump-and-dump protection
    
    def initialize_position(
        self, 
        symbol: str, 
        direction: str, 
        entry_price: float, 
        margin: float, 
        leverage: int
    ) -> PositionState:
        """Initialize tracking for a new position"""
        
        stop_loss = self._calculate_initial_stop_loss(entry_price, direction, leverage)
        
        state = PositionState(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            margin=margin,
            leverage=leverage,
            stop_loss=stop_loss,
            highest_price=entry_price,
            lowest_price=entry_price,
            entry_time=time.time()
        )
        
        self.positions[symbol] = state
        
        logger.info(f"📍 Position initialized: {symbol} {direction} @ {entry_price} | SL: {stop_loss:.6f}")
        
        return state
    
    def _calculate_initial_stop_loss(self, entry_price: float, direction: str, leverage: int) -> float:
        """Calculate initial stop-loss considering liquidation"""

        # Guard against division by zero
        if leverage <= 0:
            leverage = 10  # Default to 10x if invalid

        # Liquidation price
        if direction == "LONG":
            liquidation = entry_price * (1 - (1 / leverage))
        else:
            liquidation = entry_price * (1 + (1 / leverage))
        
        # SL from config
        sl_percent = self.sl_config.INITIAL_PERCENT / 100
        buffer = self.sl_config.BUFFER_BEFORE_LIQUIDATION / 100
        
        if direction == "LONG":
            sl_from_config = entry_price * (1 - sl_percent)
            sl_from_liq = liquidation * (1 + buffer)
            stop_loss = max(sl_from_config, sl_from_liq)
        else:
            sl_from_config = entry_price * (1 + sl_percent)
            sl_from_liq = liquidation * (1 - buffer)
            stop_loss = min(sl_from_config, sl_from_liq)
        
        return stop_loss
    
    async def update_position(
        self, symbol: str, current_price: float, velocity_1m: float = 0.0
    ) -> Optional[ExitAction]:
        """
        Update position state and check for exit conditions
        Call this on every tick for each position

        Args:
            symbol: Trading pair symbol
            current_price: Current market price
            velocity_1m: 1-minute price velocity (optional, for reversal detection)
        """
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]

        # Guard against division by zero
        if pos.entry_price <= 0:
            logger.warning(f"Invalid entry_price for {symbol}: {pos.entry_price}")
            return None

        # Update highest/lowest price
        if pos.direction == "LONG":
            pos.highest_price = max(pos.highest_price, current_price)
            profit_percent = ((current_price - pos.entry_price) / pos.entry_price) * 100
        else:
            pos.lowest_price = min(pos.lowest_price, current_price)
            profit_percent = ((pos.entry_price - current_price) / pos.entry_price) * 100

        # Update peak profit tracking
        pos.peak_profit_percent = max(pos.peak_profit_percent, profit_percent)
        pos.last_velocity_1m = velocity_1m

        # AGGRESSIVE EARLY TRAILING ACTIVATION (at +2% instead of waiting for TP levels)
        if profit_percent >= self.trailing_config.ACTIVATION_PROFIT and not pos.trailing_active:
            pos.trailing_active = True
            # Move SL to breakeven immediately
            pos.stop_loss = pos.entry_price
            logger.info(f"📍 {symbol}: Early trailing activated at +{profit_percent:.1f}% (SL->breakeven)")

        # CHECK 1: Stop-Loss
        if self._check_stop_loss_hit(pos, current_price):
            return ExitAction(
                type="CLOSE_ALL",
                symbol=symbol,
                reason=ExitReason.STOP_LOSS,
                close_percent=100,
                details={"price": current_price, "stop_loss": pos.stop_loss}
            )

        # CHECK 2: Velocity reversal (PUMP-AND-DUMP PROTECTION) - High priority
        reversal_action = self._check_velocity_reversal(pos, profit_percent, velocity_1m)
        if reversal_action:
            return reversal_action

        # CHECK 3: Instant pump time-based exit
        instant_pump_action = self._check_instant_pump_exit(pos, profit_percent)
        if instant_pump_action:
            return instant_pump_action

        # CHECK 4: Funding rate
        funding_action = await self._check_funding_exit(pos, profit_percent)
        if funding_action:
            return funding_action

        # CHECK 5: Take-Profit levels
        tp_action = self._check_take_profit(pos, profit_percent)
        if tp_action:
            return tp_action

        # CHECK 6: Tiered trailing stop (aggressive distances)
        if pos.trailing_active:
            trailing_action = self._check_tiered_trailing_stop(pos, current_price, profit_percent)
            if trailing_action:
                return trailing_action

        # CHECK 7: Max hold time
        if self._check_max_hold_time(pos):
            return ExitAction(
                type="CLOSE_ALL",
                symbol=symbol,
                reason=ExitReason.MAX_HOLD_TIME,
                close_percent=100,
                details={"held_hours": (time.time() - pos.entry_time) / 3600}
            )

        return None
    
    def _check_stop_loss_hit(self, pos: PositionState, current_price: float) -> bool:
        """Check if stop-loss is hit"""
        if pos.direction == "LONG":
            return current_price <= pos.stop_loss
        else:
            return current_price >= pos.stop_loss
    
    async def _check_funding_exit(self, pos: PositionState, profit_percent: float) -> Optional[ExitAction]:
        """Check if should exit due to high funding rate"""
        funding = await self.data_feed.get_funding_rate(pos.symbol)
        
        if not funding:
            return None
        
        rate = abs(funding.funding_rate)
        
        if rate < self.funding_config.MAX_RATE:
            return None
        
        # High funding detected
        if profit_percent > 5:
            # In profit - close partial
            return ExitAction(
                type="CLOSE_PARTIAL",
                symbol=pos.symbol,
                reason=ExitReason.FUNDING_EXIT,
                close_percent=self.funding_config.PARTIAL_CLOSE_PERCENT,
                details={"funding_rate": funding.funding_rate, "profit": profit_percent}
            )
        elif profit_percent < 2:
            # Not in profit - close all
            return ExitAction(
                type="CLOSE_ALL",
                symbol=pos.symbol,
                reason=ExitReason.FUNDING_EXIT,
                close_percent=100,
                details={"funding_rate": funding.funding_rate, "profit": profit_percent}
            )
        
        return None
    
    def _check_take_profit(self, pos: PositionState, profit_percent: float) -> Optional[ExitAction]:
        """Check and execute take-profit levels"""
        for level in self.tp_levels:
            level_id = f"tp_{level['profit']}"
            
            if level_id in pos.tp_levels_hit:
                continue
            
            if profit_percent >= level['profit']:
                pos.tp_levels_hit.append(level_id)
                
                # Execute action
                action = level['action']
                
                if action == "move_sl_breakeven":
                    pos.stop_loss = pos.entry_price
                    logger.info(f"📍 {pos.symbol}: SL moved to breakeven @ {pos.entry_price}")
                
                elif action == "activate_trailing":
                    pos.trailing_active = True
                    logger.info(f"📍 {pos.symbol}: Trailing stop activated")
                
                elif action == "tighten_trailing":
                    pos.trailing_tight = True
                    logger.info(f"📍 {pos.symbol}: Trailing stop tightened to {self.trailing_config.TIGHT_DISTANCE}%")
                
                details = {
                    "level": level['profit'],
                    "action": action,
                    "trailing_active": pos.trailing_active
                }

                # Only include new_sl when stop-loss actually moved
                if action == "move_sl_breakeven":
                    details["new_sl"] = pos.stop_loss

                return ExitAction(
                    type="CLOSE_PARTIAL",
                    symbol=pos.symbol,
                    reason=ExitReason.TAKE_PROFIT,
                    close_percent=level['close'],
                    details=details
                )
        
        return None
    
    def _check_trailing_stop(self, pos: PositionState, current_price: float) -> Optional[ExitAction]:
        """Check trailing stop (legacy - use _check_tiered_trailing_stop instead)"""
        distance = self.trailing_config.TIGHT_DISTANCE if pos.trailing_tight else self.trailing_config.INITIAL_DISTANCE
        distance_ratio = distance / 100

        if pos.direction == "LONG":
            trailing_stop = pos.highest_price * (1 - distance_ratio)

            if current_price <= trailing_stop:
                return ExitAction(
                    type="CLOSE_ALL",
                    symbol=pos.symbol,
                    reason=ExitReason.TRAILING_STOP,
                    close_percent=pos.remaining_percent,
                    details={
                        "highest": pos.highest_price,
                        "trailing_stop": trailing_stop,
                        "trigger_price": current_price
                    }
                )
        else:
            trailing_stop = pos.lowest_price * (1 + distance_ratio)

            if current_price >= trailing_stop:
                return ExitAction(
                    type="CLOSE_ALL",
                    symbol=pos.symbol,
                    reason=ExitReason.TRAILING_STOP,
                    close_percent=pos.remaining_percent,
                    details={
                        "lowest": pos.lowest_price,
                        "trailing_stop": trailing_stop,
                        "trigger_price": current_price
                    }
                )

        return None

    def _check_tiered_trailing_stop(
        self, pos: PositionState, current_price: float, profit_percent: float
    ) -> Optional[ExitAction]:
        """
        AGGRESSIVE TIERED TRAILING STOP

        Trailing distances based on profit level:
        - 2-5% profit: 2% trailing distance
        - 5-10% profit: 3% trailing distance
        - 10-20% profit: 3% trailing distance
        - 20%+ profit: 5% trailing distance (let winners run)
        """
        # Determine trailing distance based on profit tier
        if profit_percent >= self.trailing_config.TIER4_PROFIT:
            distance = self.trailing_config.TIER4_DISTANCE  # 5%
        elif profit_percent >= self.trailing_config.TIER3_PROFIT:
            distance = self.trailing_config.TIER3_DISTANCE  # 3%
        elif profit_percent >= self.trailing_config.TIER2_PROFIT:
            distance = self.trailing_config.TIER2_DISTANCE  # 3%
        else:
            distance = self.trailing_config.TIER1_DISTANCE  # 2%

        distance_ratio = distance / 100

        if pos.direction == "LONG":
            trailing_stop = pos.highest_price * (1 - distance_ratio)

            if current_price <= trailing_stop:
                return ExitAction(
                    type="CLOSE_ALL",
                    symbol=pos.symbol,
                    reason=ExitReason.TRAILING_STOP,
                    close_percent=pos.remaining_percent,
                    details={
                        "highest": pos.highest_price,
                        "trailing_stop": trailing_stop,
                        "trigger_price": current_price,
                        "distance_percent": distance,
                        "profit_tier": self._get_profit_tier_name(profit_percent)
                    }
                )
        else:
            trailing_stop = pos.lowest_price * (1 + distance_ratio)

            if current_price >= trailing_stop:
                return ExitAction(
                    type="CLOSE_ALL",
                    symbol=pos.symbol,
                    reason=ExitReason.TRAILING_STOP,
                    close_percent=pos.remaining_percent,
                    details={
                        "lowest": pos.lowest_price,
                        "trailing_stop": trailing_stop,
                        "trigger_price": current_price,
                        "distance_percent": distance,
                        "profit_tier": self._get_profit_tier_name(profit_percent)
                    }
                )

        return None

    def _get_profit_tier_name(self, profit_percent: float) -> str:
        """Get human-readable profit tier name"""
        if profit_percent >= 20:
            return "TIER4 (20%+)"
        elif profit_percent >= 10:
            return "TIER3 (10-20%)"
        elif profit_percent >= 5:
            return "TIER2 (5-10%)"
        else:
            return "TIER1 (2-5%)"

    def _check_velocity_reversal(
        self, pos: PositionState, profit_percent: float, velocity_1m: float
    ) -> Optional[ExitAction]:
        """
        VELOCITY REVERSAL EXIT - Pump-and-dump protection

        Catches fast reversals that indicate pump-and-dump patterns:
        - Partial close (50%) on -2% velocity drop from peak
        - Full close on -3% velocity drop
        """
        # Only check if in profit (don't add to losses)
        if profit_percent <= 0:
            return None

        # Calculate velocity drop from peak
        # For LONG: negative velocity means price dropping
        # For SHORT: positive velocity means price rising (bad)
        if pos.direction == "LONG":
            reversal_velocity = velocity_1m  # Negative = dropping
        else:
            reversal_velocity = -velocity_1m  # Invert for shorts

        # Check for severe reversal (full close)
        if reversal_velocity <= self.velocity_exit_config.FULL_CLOSE_VELOCITY:
            logger.warning(
                f"🚨 VELOCITY REVERSAL [{pos.symbol}]: {velocity_1m:+.1f}% velocity drop - FULL CLOSE"
            )
            return ExitAction(
                type="CLOSE_ALL",
                symbol=pos.symbol,
                reason=ExitReason.VELOCITY_REVERSAL,
                close_percent=pos.remaining_percent,
                details={
                    "velocity_1m": velocity_1m,
                    "peak_profit": pos.peak_profit_percent,
                    "current_profit": profit_percent,
                    "reversal_type": "SEVERE"
                }
            )

        # Check for partial reversal (partial close)
        if reversal_velocity <= self.velocity_exit_config.PARTIAL_CLOSE_VELOCITY:
            if not pos.velocity_partial_closed:
                pos.velocity_partial_closed = True
                close_pct = self.velocity_exit_config.PARTIAL_CLOSE_PERCENT
                logger.warning(
                    f"⚠️ VELOCITY REVERSAL [{pos.symbol}]: {velocity_1m:+.1f}% velocity - PARTIAL CLOSE {close_pct}%"
                )
                return ExitAction(
                    type="CLOSE_PARTIAL",
                    symbol=pos.symbol,
                    reason=ExitReason.VELOCITY_REVERSAL,
                    close_percent=close_pct,
                    details={
                        "velocity_1m": velocity_1m,
                        "peak_profit": pos.peak_profit_percent,
                        "current_profit": profit_percent,
                        "reversal_type": "PARTIAL"
                    }
                )

        return None

    def _check_instant_pump_exit(
        self, pos: PositionState, profit_percent: float
    ) -> Optional[ExitAction]:
        """
        INSTANT PUMP TIME-BASED EXIT

        For fast pumps (29% of moonshots are 0h duration):
        - If +5% profit within 10 minutes, close 50% to lock in gains
        - Rationale: TRADOORUSDT-style pumps dump fast
        """
        # Already did instant pump close?
        if pos.instant_pump_closed:
            return None

        # Check if within instant pump window
        time_held = time.time() - pos.entry_time
        window_seconds = self.velocity_exit_config.INSTANT_PUMP_WINDOW_SECONDS

        if time_held > window_seconds:
            return None  # Outside window

        # Check if profit threshold reached
        if profit_percent >= self.velocity_exit_config.INSTANT_PUMP_PROFIT:
            pos.instant_pump_closed = True
            close_pct = self.velocity_exit_config.INSTANT_PUMP_CLOSE_PERCENT
            minutes_held = time_held / 60

            logger.warning(
                f"⚡ INSTANT PUMP [{pos.symbol}]: +{profit_percent:.1f}% in {minutes_held:.1f}min - "
                f"LOCKING {close_pct}% profits"
            )
            return ExitAction(
                type="CLOSE_PARTIAL",
                symbol=pos.symbol,
                reason=ExitReason.INSTANT_PUMP_EXIT,
                close_percent=close_pct,
                details={
                    "profit_percent": profit_percent,
                    "time_held_seconds": time_held,
                    "time_held_minutes": minutes_held,
                    "threshold_profit": self.velocity_exit_config.INSTANT_PUMP_PROFIT,
                    "threshold_window": window_seconds
                }
            )

        return None
    
    def _check_max_hold_time(self, pos: PositionState) -> bool:
        """Check if position exceeded max hold time"""
        hours_held = (time.time() - pos.entry_time) / 3600
        return hours_held >= self.time_config.MAX_HOLD_HOURS
    
    def on_regime_change_to_choppy(self) -> List[ExitAction]:
        """Close all positions when regime changes to CHOPPY"""
        actions = []
        
        for symbol, pos in self.positions.items():
            actions.append(ExitAction(
                type="CLOSE_ALL",
                symbol=symbol,
                reason=ExitReason.REGIME_CHANGE,
                close_percent=100,
                details={"regime": "CHOPPY"}
            ))
        
        if actions:
            logger.warning(f"🚨 REGIME CHOPPY: Closing {len(actions)} positions")
        
        return actions
    
    def update_remaining_percent(self, symbol: str, closed_percent: float):
        """Update remaining position percentage after partial close"""
        if symbol in self.positions:
            self.positions[symbol].remaining_percent -= closed_percent
            
            if self.positions[symbol].remaining_percent <= 0:
                del self.positions[symbol]
    
    def remove_position(self, symbol: str):
        """Remove position from tracking"""
        if symbol in self.positions:
            del self.positions[symbol]
    
    def get_position_state(self, symbol: str) -> Optional[PositionState]:
        """Get current state of a position"""
        return self.positions.get(symbol)
    
    def get_all_positions(self) -> List[PositionState]:
        """Get all tracked positions"""
        return list(self.positions.values())
