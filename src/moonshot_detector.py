"""
Moonshot Detector Module
Detects potential moonshot opportunities using 6 signals
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from loguru import logger
import time

from config import MoonshotDetectionConfig


@dataclass
class MoonshotSignal:
    symbol: str
    direction: str  # "LONG" or "SHORT"
    score: int  # Out of 6
    confidence: float
    signals: Dict[str, bool]
    details: Dict[str, float]
    timestamp: float
    is_mega_signal: bool = False  # True if price moved >5% in 5min (bypasses regime)


class MoonshotDetector:
    """
    Detects moonshot opportunities based on 6 key signals:
    1. Volume spike
    2. Price acceleration
    3. Open Interest surge
    4. Favorable funding rate
    5. Breakout/Breakdown
    6. Order book imbalance
    """
    
    def __init__(self, data_feed):
        self.data_feed = data_feed
        self.config = MoonshotDetectionConfig
        
        # Cache for OI tracking
        self._oi_history: Dict[str, List[Tuple[float, float]]] = {}  # symbol -> [(timestamp, oi)]
        
        # Detected moonshots
        self.active_moonshots: Dict[str, MoonshotSignal] = {}
    
    async def scan_for_long(self, symbol: str) -> Optional[MoonshotSignal]:
        """Scan a symbol for LONG moonshot signals"""
        try:
            signals = {}
            details = {}
            
            # Signal 1: Volume spike
            vol_spike, vol_ratio = await self._check_volume_spike(symbol)
            signals['volume'] = vol_spike
            details['volume_ratio'] = vol_ratio
            
            # Signal 2: Price acceleration
            price_acc, price_change = await self._check_price_acceleration_long(symbol)
            signals['price'] = price_acc
            details['price_change_5m'] = price_change
            
            # Signal 3: Open Interest surge
            oi_surge, oi_change = await self._check_oi_surge(symbol)
            signals['oi'] = oi_surge
            details['oi_change_15m'] = oi_change
            
            # Signal 4: Funding favorable for long
            funding_ok, funding_rate = await self._check_funding_for_long(symbol)
            signals['funding'] = funding_ok
            details['funding_rate'] = funding_rate
            
            # Signal 5: Breakout
            breakout, breakout_strength = await self._check_breakout(symbol)
            signals['breakout'] = breakout
            details['breakout_strength'] = breakout_strength
            
            # Signal 6: Order book imbalance (bids > asks)
            ob_imbalance, imbalance_ratio = await self._check_orderbook_long(symbol)
            signals['orderbook'] = ob_imbalance
            details['orderbook_imbalance'] = imbalance_ratio
            
            # Calculate score
            score = sum(signals.values())

            # Check for MEGA-SIGNAL: if price moved >5% in 5min, lower the threshold
            is_mega = abs(price_change) >= getattr(self.config, 'MEGA_SIGNAL_VELOCITY', 5.0)
            min_signals = getattr(self.config, 'MEGA_SIGNAL_MIN_SIGNALS', 2) if is_mega else self.config.MIN_SIGNALS_REQUIRED

            if score >= min_signals:
                signal = MoonshotSignal(
                    symbol=symbol,
                    direction="LONG",
                    score=score,
                    confidence=score / 6,
                    signals=signals,
                    details=details,
                    timestamp=time.time(),
                    is_mega_signal=is_mega
                )

                self.active_moonshots[symbol] = signal
                if is_mega:
                    logger.warning(f"🔥 MEGA MOONSHOT LONG detected: {symbol} (+{price_change:.1f}% in 5min, score: {score}/6)")
                else:
                    logger.info(f"🚀 MOONSHOT LONG detected: {symbol} (score: {score}/6)")

                return signal

            return None

        except Exception as e:
            logger.error(f"Error scanning {symbol} for long: {e}")
            return None
    
    async def scan_for_short(self, symbol: str) -> Optional[MoonshotSignal]:
        """Scan a symbol for SHORT moonshot signals"""
        try:
            signals = {}
            details = {}
            
            # Signal 1: Volume spike (same for both)
            vol_spike, vol_ratio = await self._check_volume_spike(symbol)
            signals['volume'] = vol_spike
            details['volume_ratio'] = vol_ratio
            
            # Signal 2: Price dump
            price_dump, price_change = await self._check_price_acceleration_short(symbol)
            signals['price'] = price_dump
            details['price_change_5m'] = price_change
            
            # Signal 3: Open Interest surge
            oi_surge, oi_change = await self._check_oi_surge(symbol)
            signals['oi'] = oi_surge
            details['oi_change_15m'] = oi_change
            
            # Signal 4: Funding overleveraged (high = squeeze incoming)
            funding_high, funding_rate = await self._check_funding_for_short(symbol)
            signals['funding'] = funding_high
            details['funding_rate'] = funding_rate
            
            # Signal 5: Breakdown
            breakdown, breakdown_strength = await self._check_breakdown(symbol)
            signals['breakdown'] = breakdown
            details['breakdown_strength'] = breakdown_strength
            
            # Signal 6: Order book imbalance (asks > bids)
            ob_imbalance, imbalance_ratio = await self._check_orderbook_short(symbol)
            signals['orderbook'] = ob_imbalance
            details['orderbook_imbalance'] = imbalance_ratio
            
            # Calculate score
            score = sum(signals.values())

            # Check for MEGA-SIGNAL: if price moved >5% in 5min (either direction), lower the threshold
            is_mega = abs(price_change) >= getattr(self.config, 'MEGA_SIGNAL_VELOCITY', 5.0)
            min_signals = getattr(self.config, 'MEGA_SIGNAL_MIN_SIGNALS', 2) if is_mega else self.config.MIN_SIGNALS_REQUIRED

            if score >= min_signals:
                signal = MoonshotSignal(
                    symbol=symbol,
                    direction="SHORT",
                    score=score,
                    confidence=score / 6,
                    signals=signals,
                    details=details,
                    timestamp=time.time(),
                    is_mega_signal=is_mega
                )

                self.active_moonshots[symbol] = signal
                if is_mega:
                    logger.warning(f"🔥 MEGA MOONSHOT SHORT detected: {symbol} ({price_change:.1f}% in 5min, score: {score}/6)")
                else:
                    logger.info(f"📉 MOONSHOT SHORT detected: {symbol} (score: {score}/6)")

                return signal

            return None

        except Exception as e:
            logger.error(f"Error scanning {symbol} for short: {e}")
            return None
    
    async def scan(self, symbol: str) -> Optional[MoonshotSignal]:
        """Scan for both long and short opportunities"""
        # Try long first
        long_signal = await self.scan_for_long(symbol)
        if long_signal:
            return long_signal
        
        # Then try short
        short_signal = await self.scan_for_short(symbol)
        return short_signal
    
    async def _check_volume_spike(self, symbol: str) -> Tuple[bool, float]:
        """Check if volume is spiking"""
        try:
            await self.data_feed.get_klines(symbol, '5m', 20)
            
            avg_vol = self.data_feed.get_volume_average(symbol, 12)  # 1 hour avg
            
            klines = self.data_feed.klines.get(symbol, {}).get('5m', [])
            if not klines:
                return False, 0.0
            
            current_vol = klines[-1].volume
            
            if avg_vol == 0:
                return False, 0.0
            
            ratio = current_vol / avg_vol
            
            return ratio >= self.config.VOLUME_SPIKE_5M, ratio
            
        except Exception as e:
            logger.debug(f"Error checking volume for {symbol}: {e}")
            return False, 0.0
    
    async def _check_price_acceleration_long(self, symbol: str) -> Tuple[bool, float]:
        """Check if price is accelerating upward"""
        try:
            await self.data_feed.get_klines(symbol, '1m', 10)
            
            change_5m = self.data_feed.get_price_change_percent(symbol, 5)
            change_1m = self.data_feed.get_price_change_percent(symbol, 1)
            
            velocity_ok = change_5m >= self.config.PRICE_VELOCITY_5M_LONG
            accelerating = change_1m >= self.config.PRICE_VELOCITY_1M
            
            return velocity_ok and accelerating, change_5m
            
        except Exception as e:
            logger.debug(f"Error checking price for {symbol}: {e}")
            return False, 0.0
    
    async def _check_price_acceleration_short(self, symbol: str) -> Tuple[bool, float]:
        """Check if price is accelerating downward"""
        try:
            await self.data_feed.get_klines(symbol, '1m', 10)
            
            change_5m = self.data_feed.get_price_change_percent(symbol, 5)
            change_1m = self.data_feed.get_price_change_percent(symbol, 1)
            
            velocity_ok = change_5m <= self.config.PRICE_VELOCITY_5M_SHORT
            accelerating = change_1m <= -self.config.PRICE_VELOCITY_1M
            
            return velocity_ok and accelerating, change_5m
            
        except Exception as e:
            logger.debug(f"Error checking price for {symbol}: {e}")
            return False, 0.0
    
    async def _check_oi_surge(self, symbol: str) -> Tuple[bool, float]:
        """Check if Open Interest is surging"""
        try:
            current_oi = await self.data_feed.get_open_interest(symbol)
            if not current_oi:
                return False, 0.0
            
            now = time.time()
            
            # Initialize history if needed
            if symbol not in self._oi_history:
                self._oi_history[symbol] = []
            
            # Add current reading
            self._oi_history[symbol].append((now, current_oi))
            
            # Clean old readings (keep last 30 min)
            self._oi_history[symbol] = [
                (t, oi) for t, oi in self._oi_history[symbol]
                if now - t < 1800
            ]
            
            # Need at least 2 readings 15 min apart
            history = self._oi_history[symbol]
            if len(history) < 2:
                return False, 0.0
            
            # Find reading ~15 min ago
            old_oi = None
            for t, oi in history:
                if now - t >= 900:  # 15 min ago
                    old_oi = oi
                    break
            
            if not old_oi or old_oi == 0:
                return False, 0.0
            
            change_percent = ((current_oi - old_oi) / old_oi) * 100
            
            return change_percent >= self.config.OI_SURGE_15M, change_percent
            
        except Exception as e:
            logger.debug(f"Error checking OI for {symbol}: {e}")
            return False, 0.0
    
    async def _check_funding_for_long(self, symbol: str) -> Tuple[bool, float]:
        """Check if funding rate is favorable for long"""
        try:
            funding = await self.data_feed.get_funding_rate(symbol)
            if not funding:
                return True, 0.0  # Assume OK if can't get data
            
            rate = funding.funding_rate
            
            # Favorable: Not too high (not crowded) and not too negative
            favorable = -0.0002 <= rate <= self.config.FUNDING_MAX_FOR_LONG
            
            return favorable, rate
            
        except Exception as e:
            logger.debug(f"Error checking funding for {symbol}: {e}")
            return True, 0.0
    
    async def _check_funding_for_short(self, symbol: str) -> Tuple[bool, float]:
        """Check if funding is overleveraged (good for short)"""
        try:
            funding = await self.data_feed.get_funding_rate(symbol)
            if not funding:
                return False, 0.0
            
            rate = funding.funding_rate
            
            # High funding = everyone is long = squeeze potential
            overleveraged = rate >= self.config.FUNDING_MIN_FOR_SHORT
            
            return overleveraged, rate
            
        except Exception as e:
            logger.debug(f"Error checking funding for {symbol}: {e}")
            return False, 0.0
    
    async def _check_breakout(self, symbol: str) -> Tuple[bool, float]:
        """Check for price breakout above resistance"""
        try:
            klines = await self.data_feed.get_klines(symbol, '1h', 24)
            if not klines or len(klines) < 20:
                return False, 0.0
            
            # Find resistance (highest high in last 24h excluding last candle)
            resistance = max(k.high for k in klines[:-1])
            
            # Calculate ATR
            import numpy as np
            highs = np.array([k.high for k in klines])
            lows = np.array([k.low for k in klines])
            closes = np.array([k.close for k in klines])
            
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(
                    np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:] - closes[:-1])
                )
            )
            atr = np.mean(tr[-14:])
            
            # Current price
            current_price = klines[-1].close
            
            # Breakout level
            breakout_level = resistance + (atr * self.config.ATR_MULTIPLIER)
            
            is_breakout = current_price > breakout_level
            strength = (current_price - resistance) / atr if atr > 0 else 0
            
            return is_breakout, strength
            
        except Exception as e:
            logger.debug(f"Error checking breakout for {symbol}: {e}")
            return False, 0.0
    
    async def _check_breakdown(self, symbol: str) -> Tuple[bool, float]:
        """Check for price breakdown below support"""
        try:
            klines = await self.data_feed.get_klines(symbol, '1h', 24)
            if not klines or len(klines) < 20:
                return False, 0.0
            
            # Find support (lowest low in last 24h excluding last candle)
            support = min(k.low for k in klines[:-1])
            
            # Calculate ATR
            import numpy as np
            highs = np.array([k.high for k in klines])
            lows = np.array([k.low for k in klines])
            closes = np.array([k.close for k in klines])
            
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(
                    np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:] - closes[:-1])
                )
            )
            atr = np.mean(tr[-14:])
            
            # Current price
            current_price = klines[-1].close
            
            # Breakdown level
            breakdown_level = support - (atr * self.config.ATR_MULTIPLIER)
            
            is_breakdown = current_price < breakdown_level
            strength = (support - current_price) / atr if atr > 0 else 0
            
            return is_breakdown, strength
            
        except Exception as e:
            logger.debug(f"Error checking breakdown for {symbol}: {e}")
            return False, 0.0
    
    async def _check_orderbook_long(self, symbol: str) -> Tuple[bool, float]:
        """Check order book imbalance for long (bids > asks)"""
        try:
            await self.data_feed.get_orderbook(symbol)
            
            imbalance = self.data_feed.get_orderbook_imbalance(symbol)
            
            is_favorable = imbalance >= self.config.IMBALANCE_THRESHOLD
            
            return is_favorable, imbalance
            
        except Exception as e:
            logger.debug(f"Error checking orderbook for {symbol}: {e}")
            return False, 0.5
    
    async def _check_orderbook_short(self, symbol: str) -> Tuple[bool, float]:
        """Check order book imbalance for short (asks > bids)"""
        try:
            await self.data_feed.get_orderbook(symbol)
            
            imbalance = self.data_feed.get_orderbook_imbalance(symbol)
            ask_ratio = 1 - imbalance
            
            is_favorable = ask_ratio >= self.config.IMBALANCE_THRESHOLD
            
            return is_favorable, ask_ratio
            
        except Exception as e:
            logger.debug(f"Error checking orderbook for {symbol}: {e}")
            return False, 0.5
    
    def get_active_moonshots(self) -> List[MoonshotSignal]:
        """Get all currently active moonshot signals"""
        # Filter out stale signals (older than 5 minutes)
        now = time.time()
        active = []
        
        for symbol, signal in list(self.active_moonshots.items()):
            if now - signal.timestamp < 300:  # 5 minutes
                active.append(signal)
            else:
                del self.active_moonshots[symbol]
        
        return active
    
    def rank_moonshots(self, signals: List[MoonshotSignal]) -> List[MoonshotSignal]:
        """Rank moonshots by score and other factors"""
        def score_key(signal: MoonshotSignal) -> float:
            score = signal.score
            
            # Bonus for negative funding (potential squeeze)
            if signal.details.get('funding_rate', 0) < 0 and signal.direction == "LONG":
                score += 0.5
            
            # Bonus for high volume
            vol_ratio = signal.details.get('volume_ratio', 0)
            if vol_ratio > 5:
                score += 0.3
            
            return score
        
        return sorted(signals, key=score_key, reverse=True)
