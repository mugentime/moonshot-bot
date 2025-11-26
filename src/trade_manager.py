"""
Trade Manager Module
Decides whether to enter trades based on signals, regime, and available slots
"""
from typing import Optional, Dict, List
from dataclasses import dataclass
from loguru import logger
import time

from config import LeverageConfig
from .moonshot_detector import MoonshotSignal
from .market_regime import MarketRegime


@dataclass
class TradeDecision:
    symbol: str
    direction: str  # "LONG" or "SHORT"
    margin: float
    leverage: int
    entry_price: float
    stop_loss: float
    approved: bool
    reason: str
    signal: Optional[MoonshotSignal] = None


class TradeManager:
    """
    Decides whether to execute trades based on:
    - Moonshot signals
    - Market regime
    - Available position slots
    - Existing positions
    """
    
    def __init__(self, data_feed, market_regime, position_sizer, position_tracker):
        self.data_feed = data_feed
        self.market_regime = market_regime
        self.position_sizer = position_sizer
        self.position_tracker = position_tracker
        
        self.config = LeverageConfig
        
        # Track recent entries to avoid duplicates
        self.recent_entries: Dict[str, float] = {}  # symbol -> timestamp
        self.entry_cooldown = 300  # 5 minutes cooldown per symbol
    
    async def evaluate_signal(self, signal: MoonshotSignal) -> TradeDecision:
        """Evaluate a moonshot signal and decide whether to trade"""
        symbol = signal.symbol
        direction = signal.direction
        
        # Check 1: Market regime allows this direction?
        regime_ok, regime_reason = self._check_regime(direction)
        if not regime_ok:
            return TradeDecision(
                symbol=symbol,
                direction=direction,
                margin=0,
                leverage=0,
                entry_price=0,
                stop_loss=0,
                approved=False,
                reason=regime_reason,
                signal=signal
            )
        
        # Check 2: Available slots?
        if not self.position_sizer.can_open_new_position():
            return TradeDecision(
                symbol=symbol,
                direction=direction,
                margin=0,
                leverage=0,
                entry_price=0,
                stop_loss=0,
                approved=False,
                reason="No available position slots",
                signal=signal
            )
        
        # Check 3: Already have position in this symbol?
        if self.position_tracker.has_position(symbol):
            return TradeDecision(
                symbol=symbol,
                direction=direction,
                margin=0,
                leverage=0,
                entry_price=0,
                stop_loss=0,
                approved=False,
                reason=f"Already have position in {symbol}",
                signal=signal
            )
        
        # Check 4: Entry cooldown?
        if self._in_cooldown(symbol):
            return TradeDecision(
                symbol=symbol,
                direction=direction,
                margin=0,
                leverage=0,
                entry_price=0,
                stop_loss=0,
                approved=False,
                reason=f"Entry cooldown active for {symbol}",
                signal=signal
            )
        
        # All checks passed - prepare trade
        margin = await self.position_sizer.get_margin_for_trade()
        leverage = self._select_leverage(signal)
        
        # Get current price
        ticker = self.data_feed.tickers.get(symbol)
        if not ticker:
            ticker = await self.data_feed.get_ticker(symbol)
        
        if not ticker:
            return TradeDecision(
                symbol=symbol,
                direction=direction,
                margin=0,
                leverage=0,
                entry_price=0,
                stop_loss=0,
                approved=False,
                reason="Could not get current price",
                signal=signal
            )
        
        entry_price = ticker.price
        stop_loss = self._calculate_stop_loss(entry_price, direction, leverage)
        
        return TradeDecision(
            symbol=symbol,
            direction=direction,
            margin=margin,
            leverage=leverage,
            entry_price=entry_price,
            stop_loss=stop_loss,
            approved=True,
            reason="All checks passed",
            signal=signal
        )
    
    def _check_regime(self, direction: str) -> tuple:
        """Check if current regime allows this trade direction"""
        regime = self.market_regime.current_regime
        
        # CHOPPY and EXTREME block all entries
        if regime == MarketRegime.CHOPPY:
            return False, "Market regime is CHOPPY - entries blocked"
        
        if regime == MarketRegime.EXTREME_VOLATILITY:
            return False, "Market regime is EXTREME VOLATILITY - entries blocked"
        
        # Check direction
        if direction == "LONG":
            if not self.market_regime.allows_long():
                return False, f"Regime {regime.value} does not allow LONG entries"
        
        if direction == "SHORT":
            if not self.market_regime.allows_short():
                return False, f"Regime {regime.value} does not allow SHORT entries"
        
        return True, "Regime OK"
    
    def _in_cooldown(self, symbol: str) -> bool:
        """Check if symbol is in entry cooldown"""
        if symbol not in self.recent_entries:
            return False
        
        elapsed = time.time() - self.recent_entries[symbol]
        return elapsed < self.entry_cooldown
    
    def _select_leverage(self, signal: MoonshotSignal) -> int:
        """Select leverage based on signal strength"""
        # Higher score = more confidence = can use higher leverage
        score = signal.score
        
        if score >= 6:
            return self.config.MAX
        elif score >= 5:
            return self.config.DEFAULT
        else:
            return self.config.MIN
    
    def _calculate_stop_loss(self, entry_price: float, direction: str, leverage: int) -> float:
        """Calculate stop loss price"""
        from config import StopLossConfig
        
        sl_percent = StopLossConfig.INITIAL_PERCENT / 100
        
        if direction == "LONG":
            return entry_price * (1 - sl_percent)
        else:
            return entry_price * (1 + sl_percent)
    
    def mark_entry(self, symbol: str):
        """Mark that we entered a position (for cooldown)"""
        self.recent_entries[symbol] = time.time()
    
    def clear_cooldown(self, symbol: str):
        """Clear cooldown for a symbol"""
        if symbol in self.recent_entries:
            del self.recent_entries[symbol]
    
    async def process_signals(self, signals: List[MoonshotSignal]) -> List[TradeDecision]:
        """Process multiple signals and return approved trades"""
        approved = []
        
        for signal in signals:
            decision = await self.evaluate_signal(signal)
            
            if decision.approved:
                approved.append(decision)
                logger.info(
                    f"✅ Trade approved: {signal.symbol} {signal.direction} | "
                    f"Score: {signal.score}/6 | Margin: ${decision.margin:.2f} | "
                    f"Leverage: {decision.leverage}x"
                )
            else:
                logger.debug(f"❌ Trade rejected: {signal.symbol} - {decision.reason}")
        
        return approved
    
    def get_status(self) -> Dict:
        """Get current trade manager status"""
        return {
            "regime": self.market_regime.current_regime.value,
            "allows_long": self.market_regime.allows_long(),
            "allows_short": self.market_regime.allows_short(),
            "allows_entries": self.market_regime.allows_new_entries(),
            "available_slots": self.position_sizer.get_available_slots(),
            "active_cooldowns": len(self.recent_entries)
        }
