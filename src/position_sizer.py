"""
Position Sizer Module
Calculates position size with compound growth
"""
from typing import Optional
from dataclasses import dataclass
from loguru import logger
import time

from config import PositionSizingConfig, INITIAL_EQUITY


@dataclass
class SizingState:
    equity_snapshot: float
    current_margin: float
    last_recalc_time: float
    open_positions_count: int


class PositionSizer:
    """
    Calculates margin per trade using the hybrid floor compound method
    
    Formula: margin = max(MIN_MARGIN, min(equity / MAX_TRADES, equity * MAX_PERCENT))
    
    Recalculates when:
    - Equity changes ±10% from snapshot
    - All positions closed
    - 24 hours passed
    """
    
    def __init__(self, data_feed):
        self.data_feed = data_feed
        self.config = PositionSizingConfig
        
        self.equity_snapshot = INITIAL_EQUITY
        self.current_margin = self._calculate_margin(INITIAL_EQUITY)
        self.last_recalc_time = time.time()
        self.open_positions_count = 0
    
    def _calculate_margin(self, equity: float) -> float:
        """
        Calculate margin per trade
        
        Floor: Never less than MIN_MARGIN_USD ($1)
        Ceiling: Never more than MAX_MARGIN_PERCENT (5%) of equity
        Target: ~30 trades possible
        """
        min_margin = self.config.MIN_MARGIN_USD
        max_trades = self.config.MAX_CONCURRENT_TRADES
        max_percent = self.config.MAX_MARGIN_PERCENT / 100
        
        # Base margin to allow ~30 trades
        base_margin = equity / max_trades
        
        # Apply floor
        margin = max(base_margin, min_margin)
        
        # Apply ceiling
        margin = min(margin, equity * max_percent)
        
        return round(margin, 2)
    
    def should_recalculate(self, current_equity: float) -> bool:
        """Check if margin should be recalculated"""
        now = time.time()
        
        # Trigger 1: Equity changed ±10%
        if self.equity_snapshot > 0:
            change = abs(current_equity - self.equity_snapshot) / self.equity_snapshot
            if change >= self.config.RECALC_EQUITY_CHANGE_PERCENT / 100:
                return True
        
        # Trigger 2: All positions closed
        if self.open_positions_count == 0:
            return True
        
        # Trigger 3: 24 hours passed
        hours_passed = (now - self.last_recalc_time) / 3600
        if hours_passed >= self.config.RECALC_MAX_HOURS:
            return True
        
        return False
    
    async def get_margin_for_trade(self) -> float:
        """Get the margin to use for the next trade"""
        current_equity = await self.data_feed.get_account_balance()
        
        if current_equity <= 0:
            logger.warning("Could not get account balance, using cached margin")
            return self.current_margin
        
        if self.should_recalculate(current_equity):
            old_margin = self.current_margin
            self.current_margin = self._calculate_margin(current_equity)
            self.equity_snapshot = current_equity
            self.last_recalc_time = time.time()
            
            logger.info(f"📊 Position size recalculated: ${old_margin:.2f} → ${self.current_margin:.2f} "
                       f"(Equity: ${current_equity:.2f})")
        
        return self.current_margin
    
    def on_position_opened(self):
        """Call when a new position is opened"""
        self.open_positions_count += 1
        logger.debug(f"Position opened. Active: {self.open_positions_count}")
    
    def on_position_closed(self):
        """Call when a position is closed"""
        self.open_positions_count = max(0, self.open_positions_count - 1)
        logger.debug(f"Position closed. Active: {self.open_positions_count}")
    
    def get_state(self) -> SizingState:
        """Get current state for debugging/logging"""
        return SizingState(
            equity_snapshot=self.equity_snapshot,
            current_margin=self.current_margin,
            last_recalc_time=self.last_recalc_time,
            open_positions_count=self.open_positions_count
        )
    
    def can_open_new_position(self) -> bool:
        """Check if we can open more positions"""
        return self.open_positions_count < self.config.MAX_CONCURRENT_TRADES
    
    def get_max_positions(self) -> int:
        """Get maximum allowed positions"""
        return self.config.MAX_CONCURRENT_TRADES
    
    def get_available_slots(self) -> int:
        """Get number of available position slots"""
        return max(0, self.config.MAX_CONCURRENT_TRADES - self.open_positions_count)
    
    async def get_current_equity(self) -> float:
        """Get current account equity"""
        return await self.data_feed.get_account_balance()
    
    def estimate_position_value(self, leverage: int = 15) -> float:
        """Estimate the notional value of a position"""
        return self.current_margin * leverage
    
    def log_status(self):
        """Log current position sizing status"""
        state = self.get_state()
        logger.info(
            f"💰 Position Sizer Status:\n"
            f"   Equity Snapshot: ${state.equity_snapshot:.2f}\n"
            f"   Current Margin: ${state.current_margin:.2f}\n"
            f"   Open Positions: {state.open_positions_count}/{self.config.MAX_CONCURRENT_TRADES}\n"
            f"   Available Slots: {self.get_available_slots()}"
        )
