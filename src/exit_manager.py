"""
Exit Manager Module
Manages all exit conditions: SL, TP, trailing, funding-based exits
"""
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger
import time

from config import (
    StopLossConfig, TakeProfitConfig, TrailingStopConfig, 
    FundingConfig, TimeLimitsConfig, LeverageConfig
)


class ExitReason(Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    FUNDING_EXIT = "funding_exit"
    MAX_HOLD_TIME = "max_hold_time"
    REGIME_CHANGE = "regime_change"
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


class ExitManager:
    """
    Manages all exit logic for positions:
    - Initial stop-loss
    - Escalonated take-profit
    - Trailing stop
    - Funding-based exits
    - Time-based exits
    - Regime change exits
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
    
    async def update_position(self, symbol: str, current_price: float) -> Optional[ExitAction]:
        """
        Update position state and check for exit conditions
        Call this on every tick for each position
        """
        if symbol not in self.positions:
            return None
        
        pos = self.positions[symbol]
        
        # Update highest/lowest price
        if pos.direction == "LONG":
            pos.highest_price = max(pos.highest_price, current_price)
            profit_percent = ((current_price - pos.entry_price) / pos.entry_price) * 100
        else:
            pos.lowest_price = min(pos.lowest_price, current_price)
            profit_percent = ((pos.entry_price - current_price) / pos.entry_price) * 100
        
        # CHECK 1: Stop-Loss
        if self._check_stop_loss_hit(pos, current_price):
            return ExitAction(
                type="CLOSE_ALL",
                symbol=symbol,
                reason=ExitReason.STOP_LOSS,
                close_percent=100,
                details={"price": current_price, "stop_loss": pos.stop_loss}
            )
        
        # CHECK 2: Funding rate
        funding_action = await self._check_funding_exit(pos, profit_percent)
        if funding_action:
            return funding_action
        
        # CHECK 3: Take-Profit levels
        tp_action = self._check_take_profit(pos, profit_percent)
        if tp_action:
            return tp_action
        
        # CHECK 4: Trailing stop
        if pos.trailing_active:
            trailing_action = self._check_trailing_stop(pos, current_price)
            if trailing_action:
                return trailing_action
        
        # CHECK 5: Max hold time
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
                
                return ExitAction(
                    type="CLOSE_PARTIAL",
                    symbol=pos.symbol,
                    reason=ExitReason.TAKE_PROFIT,
                    close_percent=level['close'],
                    details={
                        "level": level['profit'],
                        "action": action,
                        "new_sl": pos.stop_loss,
                        "trailing_active": pos.trailing_active
                    }
                )
        
        return None
    
    def _check_trailing_stop(self, pos: PositionState, current_price: float) -> Optional[ExitAction]:
        """Check trailing stop"""
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
