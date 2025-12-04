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
    - Moonshot signals (3-TIER VELOCITY SYSTEM)
    - Market regime (bypassed for Tier 1/2)
    - Available position slots
    - Existing positions

    TIER BYPASS RULES:
    - Tier 1: Bypasses ALL checks (regime, cooldown) - 30s cooldown
    - Tier 2: Bypasses regime checks - 60s cooldown
    - Tier 3: Normal checks - 120s cooldown
    - Legacy: Normal checks - 300s cooldown
    """

    def __init__(self, data_feed, market_regime, position_sizer, position_tracker):
        self.data_feed = data_feed
        self.market_regime = market_regime
        self.position_sizer = position_sizer
        self.position_tracker = position_tracker

        self.config = LeverageConfig

        # Track recent entries to avoid duplicates
        self.recent_entries: Dict[str, float] = {}  # symbol -> timestamp
        self.entry_cooldown = 300  # Default 5 minutes cooldown (legacy signals)

        # Tier-based cooldowns (in seconds)
        self.tier_cooldowns = {
            1: 30,   # Tier 1: 30 seconds
            2: 60,   # Tier 2: 60 seconds
            3: 120,  # Tier 3: 120 seconds
            0: 300   # Legacy: 300 seconds
        }
    
    async def evaluate_signal(self, signal: MoonshotSignal) -> TradeDecision:
        """
        Evaluate a moonshot signal and decide whether to trade.

        TIER BYPASS LOGIC:
        - Tier 1: Bypasses regime AND cooldown checks
        - Tier 2: Bypasses regime checks only
        - Tier 3+: Normal checks apply
        """
        symbol = signal.symbol
        direction = signal.direction

        # Get tier info from signal
        tier = getattr(signal, 'tier', 0)
        bypass_checks = getattr(signal, 'bypass_checks', False)
        is_mega = getattr(signal, 'is_mega_signal', False)
        is_peak = getattr(signal, 'is_peak_hour', False)

        # Log tier information
        tier_label = f"TIER {tier}" if tier > 0 else "LEGACY"
        if tier == 1:
            logger.warning(f"🚀🚀🚀 {tier_label} INSTANT ENTRY: {symbol} {direction} (ALL CHECKS BYPASSED)")
        elif tier == 2:
            logger.warning(f"🚀🚀 {tier_label} FAST ENTRY: {symbol} {direction} (regime bypassed)")
        elif is_mega:
            logger.warning(f"🔥 MEGA-SIGNAL: {symbol} {direction} (regime bypassed)")

        # Check 1: Market regime allows this direction?
        # Tier 1, Tier 2, and MEGA-SIGNALS bypass regime checks
        if bypass_checks or is_mega:
            regime_ok, regime_reason = True, f"{tier_label}: regime bypassed"
        else:
            regime_ok, regime_reason = self._check_regime(direction, signal)

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
            available = self.position_sizer.get_available_slots()
            max_pos = self.position_sizer.get_max_positions()
            current = self.position_sizer.open_positions_count
            logger.warning(f"❌ NO SLOTS: {symbol} | Current: {current}, Available: {available}, Max: {max_pos}")
            return TradeDecision(
                symbol=symbol,
                direction=direction,
                margin=0,
                leverage=0,
                entry_price=0,
                stop_loss=0,
                approved=False,
                reason=f"No available position slots ({current}/{max_pos})",
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

        # Check 4: Entry cooldown? (Tier 1 has shortest cooldown, Tier 2 medium)
        # Use tier-specific cooldown
        cooldown = self._get_tier_cooldown(signal)
        if self._in_cooldown_with_duration(symbol, cooldown):
            # Tier 1 can still bypass even cooldown if velocity is extreme
            if tier == 1 and is_peak:
                logger.info(f"Tier 1 + Peak hour: bypassing cooldown for {symbol}")
            else:
                return TradeDecision(
                    symbol=symbol,
                    direction=direction,
                    margin=0,
                    leverage=0,
                    entry_price=0,
                    stop_loss=0,
                    approved=False,
                    reason=f"Entry cooldown active ({cooldown}s) for {symbol}",
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
    
    def _check_regime(self, direction: str, signal: Optional[MoonshotSignal] = None) -> tuple:
        """Check if current regime allows this trade direction"""
        regime = self.market_regime.current_regime

        # CHOPPY: Allow entries for high-scoring signals (4+/6) or mega-signals
        # FIX: Return immediately to bypass direction check that would reject CHOPPY
        if regime == MarketRegime.CHOPPY:
            if signal is not None:
                is_mega = getattr(signal, 'is_mega_signal', False)
                if is_mega or signal.score >= 4:
                    logger.info(f"Allowing CHOPPY entry for {signal.symbol} (score={signal.score}, mega={is_mega})")
                    return True, "High confidence signal bypassing CHOPPY"  # FIXED: Return immediately
                else:
                    return False, "Market regime is CHOPPY - need score >= 4 or mega-signal"
            else:
                return False, "Market regime is CHOPPY - entries blocked"

        if regime == MarketRegime.EXTREME_VOLATILITY:
            return False, "Market regime is EXTREME VOLATILITY - entries blocked"

        # Check direction (only for non-CHOPPY regimes)
        if direction == "LONG":
            if not self.market_regime.allows_long():
                return False, f"Regime {regime.value} does not allow LONG entries"

        if direction == "SHORT":
            if not self.market_regime.allows_short():
                return False, f"Regime {regime.value} does not allow SHORT entries"

        return True, "Regime OK"
    
    def _in_cooldown(self, symbol: str) -> bool:
        """Check if symbol is in entry cooldown (using default cooldown)"""
        if symbol not in self.recent_entries:
            return False

        elapsed = time.time() - self.recent_entries[symbol]
        return elapsed < self.entry_cooldown

    def _in_cooldown_with_duration(self, symbol: str, cooldown_seconds: int) -> bool:
        """Check if symbol is in entry cooldown with specific duration"""
        if symbol not in self.recent_entries:
            return False

        elapsed = time.time() - self.recent_entries[symbol]
        return elapsed < cooldown_seconds

    def _get_tier_cooldown(self, signal: MoonshotSignal) -> int:
        """Get cooldown duration based on signal tier"""
        tier = getattr(signal, 'tier', 0)

        # Use signal's entry_cooldown if available, otherwise use tier defaults
        if hasattr(signal, 'entry_cooldown') and signal.entry_cooldown:
            return signal.entry_cooldown

        return self.tier_cooldowns.get(tier, self.entry_cooldown)
    
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
                # Log rejections at INFO level for Tier 1/2 signals to help diagnose issues
                tier = getattr(signal, 'tier', 0)
                if tier in [1, 2]:
                    logger.warning(f"❌ TIER {tier} REJECTED: {signal.symbol} - {decision.reason}")
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
