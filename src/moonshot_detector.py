"""
Moonshot Detector Module
3-TIER VELOCITY SYSTEM for 90%+ Catch Rate (Based on 183 moonshot analysis)

TIER 1: Instant Entry (2.5%+ velocity, bypasses ALL checks)
TIER 2: Fast Entry (1.5%+ velocity + volume confirmation)
TIER 3: Micro Entry (1.5%+ 1m velocity, consecutive candles)
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
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
    # NEW: 3-Tier System Fields
    tier: int = 0  # 1, 2, or 3 (0 = legacy signal)
    bypass_checks: bool = False  # True for Tier 1 (bypass regime, cooldown, etc.)
    entry_cooldown: int = 120  # Seconds before can re-enter (30s Tier1, 60s Tier2, 120s Tier3)
    is_momentum_stack: bool = False  # True if multi-timeframe momentum detected
    is_peak_hour: bool = False  # True if detected during peak hours (18:00-00:00 UTC)


class MoonshotDetector:
    """
    Detects moonshot opportunities using 3-TIER VELOCITY SYSTEM:

    TIER 1: INSTANT ENTRY (>=2.5% in 5min)
        - Bypasses ALL checks (regime, signals, cooldown)
        - 30-second cooldown for re-entry
        - Catches 90.7% of moonshots (166/183)

    TIER 2: FAST ENTRY (>=1.5% in 5min + 1.3x volume)
        - Bypasses signal requirements
        - 60-second cooldown
        - Catches additional 5%

    TIER 3: MICRO ENTRY (>=1.5% in 1min, 3 consecutive candles)
        - Catches early-stage moonshots
        - 120-second cooldown

    LEGACY: 6-signal detection for lower velocity moves
    """

    def __init__(self, data_feed):
        self.data_feed = data_feed
        self.config = MoonshotDetectionConfig

        # Cache for OI tracking
        self._oi_history: Dict[str, List[Tuple[float, float]]] = {}  # symbol -> [(timestamp, oi)]

        # Detected moonshots
        self.active_moonshots: Dict[str, MoonshotSignal] = {}

        # NEW: 1-minute candle tracking for Tier 3 micro-detection
        self._consecutive_green: Dict[str, int] = {}  # symbol -> count of consecutive green 1m candles
        self._last_1m_close: Dict[str, float] = {}  # symbol -> last 1m close price

    def _is_peak_hour(self) -> bool:
        """Check if current UTC hour is in peak moonshot window (18:00-00:00 UTC)"""
        current_hour = datetime.utcnow().hour
        peak_ranges = getattr(self.config, 'PEAK_HOURS_UTC', [(18, 24), (0, 1)])
        for start, end in peak_ranges:
            if start <= current_hour < end:
                return True
        return False

    def _get_adjusted_threshold(self, base_threshold: float) -> float:
        """Reduce threshold by 25% during peak hours"""
        if self._is_peak_hour():
            reduction = getattr(self.config, 'PEAK_HOUR_THRESHOLD_REDUCTION', 0.25)
            return base_threshold * (1 - reduction)
        return base_threshold

    async def _check_tier1_signal(self, symbol: str, direction: str = "LONG") -> Optional[MoonshotSignal]:
        """
        TIER 1: INSTANT ENTRY
        Condition: 5m velocity >= 2.5% (adjusted for peak hours)
        Action: IMMEDIATE market entry, bypass ALL checks
        """
        try:
            await self.data_feed.get_klines(symbol, '1m', 10)
            change_5m = self.data_feed.get_price_change_percent(symbol, 5)

            # Get threshold (adjusted for peak hours)
            tier1_threshold = self._get_adjusted_threshold(
                getattr(self.config, 'TIER1_VELOCITY_5M', 2.5)
            )

            # Check direction
            if direction == "LONG" and change_5m >= tier1_threshold:
                is_peak = self._is_peak_hour()
                logger.warning(f"🚀🚀🚀 TIER 1 INSTANT LONG: {symbol} +{change_5m:.2f}% (threshold: {tier1_threshold:.2f}%{' PEAK HOUR' if is_peak else ''})")

                return MoonshotSignal(
                    symbol=symbol,
                    direction="LONG",
                    score=6,  # Max score for Tier 1
                    confidence=1.0,
                    signals={'tier1_velocity': True, 'volume': True, 'price': True, 'oi': True, 'funding': True, 'breakout': True},
                    details={'price_change_5m': change_5m, 'tier': 1, 'threshold': tier1_threshold},
                    timestamp=time.time(),
                    is_mega_signal=True,
                    tier=1,
                    bypass_checks=True,  # Bypass ALL checks
                    entry_cooldown=getattr(self.config, 'ENTRY_COOLDOWN_TIER1', 30),
                    is_peak_hour=is_peak
                )

            elif direction == "SHORT" and change_5m <= -tier1_threshold:
                is_peak = self._is_peak_hour()
                logger.warning(f"📉📉📉 TIER 1 INSTANT SHORT: {symbol} {change_5m:.2f}% (threshold: -{tier1_threshold:.2f}%{' PEAK HOUR' if is_peak else ''})")

                return MoonshotSignal(
                    symbol=symbol,
                    direction="SHORT",
                    score=6,
                    confidence=1.0,
                    signals={'tier1_velocity': True, 'volume': True, 'price': True, 'oi': True, 'funding': True, 'breakdown': True},
                    details={'price_change_5m': change_5m, 'tier': 1, 'threshold': -tier1_threshold},
                    timestamp=time.time(),
                    is_mega_signal=True,
                    tier=1,
                    bypass_checks=True,
                    entry_cooldown=getattr(self.config, 'ENTRY_COOLDOWN_TIER1', 30),
                    is_peak_hour=is_peak
                )

            return None

        except Exception as e:
            logger.debug(f"Tier 1 check error for {symbol}: {e}")
            return None

    async def _check_tier2_signal(self, symbol: str, direction: str = "LONG") -> Optional[MoonshotSignal]:
        """
        TIER 2: FAST ENTRY
        Condition: 5m velocity >= 1.5% AND volume_spike >= 1.3x
        Action: Entry within same candle, bypass signal requirements
        """
        try:
            await self.data_feed.get_klines(symbol, '1m', 10)
            change_5m = self.data_feed.get_price_change_percent(symbol, 5)

            tier2_threshold = self._get_adjusted_threshold(
                getattr(self.config, 'TIER2_VELOCITY_5M', 1.5)
            )

            # Check velocity first
            velocity_ok = (direction == "LONG" and change_5m >= tier2_threshold) or \
                         (direction == "SHORT" and change_5m <= -tier2_threshold)

            if not velocity_ok:
                return None

            # Check volume spike
            vol_ok, vol_ratio = await self._check_volume_spike(symbol)
            tier2_vol_threshold = getattr(self.config, 'TIER2_VOLUME_SPIKE', 1.3)

            if vol_ratio < tier2_vol_threshold:
                return None

            is_peak = self._is_peak_hour()

            if direction == "LONG":
                logger.warning(f"🚀🚀 TIER 2 FAST LONG: {symbol} +{change_5m:.2f}% | Vol: {vol_ratio:.1f}x{' PEAK HOUR' if is_peak else ''}")
            else:
                logger.warning(f"📉📉 TIER 2 FAST SHORT: {symbol} {change_5m:.2f}% | Vol: {vol_ratio:.1f}x{' PEAK HOUR' if is_peak else ''}")

            return MoonshotSignal(
                symbol=symbol,
                direction=direction,
                score=5,  # High score for Tier 2
                confidence=0.9,
                signals={'tier2_velocity': True, 'volume': True, 'price': True, 'oi': False, 'funding': False, 'breakout': False},
                details={'price_change_5m': change_5m, 'volume_ratio': vol_ratio, 'tier': 2, 'threshold': tier2_threshold},
                timestamp=time.time(),
                is_mega_signal=True,
                tier=2,
                bypass_checks=True,  # Still bypass most checks
                entry_cooldown=getattr(self.config, 'ENTRY_COOLDOWN_TIER2', 60),
                is_peak_hour=is_peak
            )

        except Exception as e:
            logger.debug(f"Tier 2 check error for {symbol}: {e}")
            return None

    async def _check_tier3_signal(self, symbol: str, direction: str = "LONG") -> Optional[MoonshotSignal]:
        """
        TIER 3: MICRO ENTRY
        Condition: 1m velocity >= 1.5% (3 consecutive green candles for LONG)
        Action: Entry on 4th candle confirmation
        """
        try:
            klines = await self.data_feed.get_klines(symbol, '1m', 5)
            if not klines or len(klines) < 4:
                return None

            tier3_threshold = self._get_adjusted_threshold(
                getattr(self.config, 'TIER3_VELOCITY_1M', 1.5)
            )
            consecutive_required = getattr(self.config, 'TIER3_CONSECUTIVE_CANDLES', 3)

            # Check 1m velocity
            change_1m = self.data_feed.get_price_change_percent(symbol, 1)

            # Count consecutive green/red candles
            consecutive = 0
            for k in klines[-consecutive_required:]:
                if direction == "LONG" and k.close > k.open:
                    consecutive += 1
                elif direction == "SHORT" and k.close < k.open:
                    consecutive += 1

            velocity_ok = (direction == "LONG" and change_1m >= tier3_threshold) or \
                         (direction == "SHORT" and change_1m <= -tier3_threshold)

            if velocity_ok and consecutive >= consecutive_required:
                is_peak = self._is_peak_hour()

                if direction == "LONG":
                    logger.info(f"🚀 TIER 3 MICRO LONG: {symbol} +{change_1m:.2f}% | {consecutive} green candles{' PEAK HOUR' if is_peak else ''}")
                else:
                    logger.info(f"📉 TIER 3 MICRO SHORT: {symbol} {change_1m:.2f}% | {consecutive} red candles{' PEAK HOUR' if is_peak else ''}")

                return MoonshotSignal(
                    symbol=symbol,
                    direction=direction,
                    score=4,
                    confidence=0.75,
                    signals={'tier3_velocity': True, 'consecutive_candles': True, 'price': True, 'oi': False, 'funding': False, 'breakout': False},
                    details={'price_change_1m': change_1m, 'consecutive_candles': consecutive, 'tier': 3, 'threshold': tier3_threshold},
                    timestamp=time.time(),
                    is_mega_signal=False,
                    tier=3,
                    bypass_checks=False,  # Tier 3 doesn't bypass all checks
                    entry_cooldown=getattr(self.config, 'ENTRY_COOLDOWN_TIER3', 120),
                    is_peak_hour=is_peak
                )

            return None

        except Exception as e:
            logger.debug(f"Tier 3 check error for {symbol}: {e}")
            return None

    async def _check_momentum_stack(self, symbol: str, direction: str = "LONG") -> Optional[MoonshotSignal]:
        """
        MOMENTUM STACK: Multi-timeframe momentum detection
        Catches slow builders like PIPPINUSDT (+91.6%)
        Condition: 1h velocity >= 2% AND 15m velocity >= 1% AND 5m velocity >= 0.5%
        """
        try:
            # Get 1h klines
            klines_1h = await self.data_feed.get_klines(symbol, '1h', 2)
            if not klines_1h or len(klines_1h) < 2:
                return None

            change_1h = ((klines_1h[-1].close - klines_1h[-2].close) / klines_1h[-2].close) * 100

            # Get 5m klines for 15m and 5m velocity
            await self.data_feed.get_klines(symbol, '5m', 4)
            change_5m = self.data_feed.get_price_change_percent(symbol, 5)

            # Approximate 15m velocity from 5m klines
            klines_5m = self.data_feed.klines.get(symbol, {}).get('5m', [])
            if len(klines_5m) >= 3:
                change_15m = ((klines_5m[-1].close - klines_5m[-3].open) / klines_5m[-3].open) * 100
            else:
                return None

            # Thresholds
            mom_1h = getattr(self.config, 'MOMENTUM_1H_VELOCITY', 2.0)
            mom_15m = getattr(self.config, 'MOMENTUM_15M_VELOCITY', 1.0)
            mom_5m = getattr(self.config, 'MOMENTUM_5M_VELOCITY', 0.5)

            if direction == "LONG":
                if change_1h >= mom_1h and change_15m >= mom_15m and change_5m >= mom_5m:
                    is_peak = self._is_peak_hour()
                    logger.warning(f"📈 MOMENTUM STACK LONG: {symbol} | 1h: +{change_1h:.1f}% | 15m: +{change_15m:.1f}% | 5m: +{change_5m:.1f}%{' PEAK HOUR' if is_peak else ''}")

                    return MoonshotSignal(
                        symbol=symbol,
                        direction="LONG",
                        score=5,
                        confidence=0.85,
                        signals={'momentum_stack': True, 'volume': False, 'price': True, 'oi': False, 'funding': False, 'breakout': False},
                        details={'change_1h': change_1h, 'change_15m': change_15m, 'change_5m': change_5m, 'momentum_stack': True},
                        timestamp=time.time(),
                        is_mega_signal=True,
                        tier=2,  # Treat as Tier 2
                        bypass_checks=True,
                        entry_cooldown=60,
                        is_momentum_stack=True,
                        is_peak_hour=is_peak
                    )

            elif direction == "SHORT":
                if change_1h <= -mom_1h and change_15m <= -mom_15m and change_5m <= -mom_5m:
                    is_peak = self._is_peak_hour()
                    logger.warning(f"📉 MOMENTUM STACK SHORT: {symbol} | 1h: {change_1h:.1f}% | 15m: {change_15m:.1f}% | 5m: {change_5m:.1f}%{' PEAK HOUR' if is_peak else ''}")

                    return MoonshotSignal(
                        symbol=symbol,
                        direction="SHORT",
                        score=5,
                        confidence=0.85,
                        signals={'momentum_stack': True, 'volume': False, 'price': True, 'oi': False, 'funding': False, 'breakdown': False},
                        details={'change_1h': change_1h, 'change_15m': change_15m, 'change_5m': change_5m, 'momentum_stack': True},
                        timestamp=time.time(),
                        is_mega_signal=True,
                        tier=2,
                        bypass_checks=True,
                        entry_cooldown=60,
                        is_momentum_stack=True,
                        is_peak_hour=is_peak
                    )

            return None

        except Exception as e:
            logger.debug(f"Momentum stack check error for {symbol}: {e}")
            return None
    
    async def scan_for_long(self, symbol: str) -> Optional[MoonshotSignal]:
        """
        Scan for LONG moonshot signals using 3-TIER VELOCITY SYSTEM

        Priority Order:
        1. TIER 1: Instant entry (2.5%+ velocity) - bypasses ALL checks
        2. TIER 2: Fast entry (1.5%+ velocity + volume)
        3. MOMENTUM STACK: Multi-timeframe momentum
        4. TIER 3: Micro entry (1.5%+ 1m velocity, consecutive candles)
        5. LEGACY: 6-signal detection system
        """
        try:
            # ================================================================
            # TIER 1: INSTANT ENTRY (bypasses ALL checks)
            # ================================================================
            tier1_signal = await self._check_tier1_signal(symbol, "LONG")
            if tier1_signal:
                self.active_moonshots[symbol] = tier1_signal
                return tier1_signal

            # ================================================================
            # TIER 2: FAST ENTRY (velocity + volume)
            # ================================================================
            tier2_signal = await self._check_tier2_signal(symbol, "LONG")
            if tier2_signal:
                self.active_moonshots[symbol] = tier2_signal
                return tier2_signal

            # ================================================================
            # MOMENTUM STACK: Multi-timeframe momentum (catches slow builders)
            # ================================================================
            momentum_signal = await self._check_momentum_stack(symbol, "LONG")
            if momentum_signal:
                self.active_moonshots[symbol] = momentum_signal
                return momentum_signal

            # ================================================================
            # TIER 3: MICRO ENTRY (1m velocity + consecutive candles)
            # ================================================================
            tier3_signal = await self._check_tier3_signal(symbol, "LONG")
            if tier3_signal:
                self.active_moonshots[symbol] = tier3_signal
                return tier3_signal

            # ================================================================
            # LEGACY: 6-signal detection system (for lower velocity moves)
            # ================================================================

            # Get ticker for 24h change check
            ticker = await self.data_feed.get_ticker(symbol)

            # MOONSHOT MEGA-SIGNAL: If 24h change >= +20%, check if still pumping
            if ticker and ticker.price_change_percent_24h >= 20:
                await self.data_feed.get_klines(symbol, '1m', 10)
                velocity_5m = self.data_feed.get_price_change_percent(symbol, 5)

                if velocity_5m > 1.0:  # Still pumping more than +1% in last 5min
                    is_peak = self._is_peak_hour()
                    signal = MoonshotSignal(
                        symbol=symbol,
                        direction="LONG",
                        score=5,
                        confidence=0.8,
                        signals={'volume': True, 'price': True, 'oi': True, 'funding': True, 'breakout': True, 'orderbook': False},
                        details={'price_change_24h': ticker.price_change_percent_24h, 'price_change_5m': velocity_5m, 'mega_pump': True},
                        timestamp=time.time(),
                        is_mega_signal=True,
                        tier=2,  # Treat as Tier 2
                        bypass_checks=True,
                        entry_cooldown=60,
                        is_peak_hour=is_peak
                    )
                    self.active_moonshots[symbol] = signal
                    logger.warning(f"🚀 MEGA-PUMP: {symbol} (+{ticker.price_change_percent_24h:.1f}% 24h, +{velocity_5m:.1f}%/5min)")
                    return signal

            # Standard 6-signal check
            signals = {}
            details = {}

            vol_spike, vol_ratio = await self._check_volume_spike(symbol)
            signals['volume'] = vol_spike
            details['volume_ratio'] = vol_ratio

            price_acc, price_change = await self._check_price_acceleration_long(symbol)
            signals['price'] = price_acc
            details['price_change_5m'] = price_change

            oi_surge, oi_change = await self._check_oi_surge(symbol)
            signals['oi'] = oi_surge
            details['oi_change_15m'] = oi_change

            funding_ok, funding_rate = await self._check_funding_for_long(symbol)
            signals['funding'] = funding_ok
            details['funding_rate'] = funding_rate

            breakout, breakout_strength = await self._check_breakout(symbol)
            signals['breakout'] = breakout
            details['breakout_strength'] = breakout_strength

            ob_imbalance, imbalance_ratio = await self._check_orderbook_long(symbol)
            signals['orderbook'] = ob_imbalance
            details['orderbook_imbalance'] = imbalance_ratio

            score = sum(signals.values())

            is_mega = abs(price_change) >= getattr(self.config, 'MEGA_SIGNAL_VELOCITY', 2.0)
            min_signals = getattr(self.config, 'MEGA_SIGNAL_MIN_SIGNALS', 1) if is_mega else self.config.MIN_SIGNALS_REQUIRED

            if score >= min_signals:
                is_peak = self._is_peak_hour()
                signal = MoonshotSignal(
                    symbol=symbol,
                    direction="LONG",
                    score=score,
                    confidence=score / 6,
                    signals=signals,
                    details=details,
                    timestamp=time.time(),
                    is_mega_signal=is_mega,
                    tier=0,  # Legacy signal
                    bypass_checks=is_mega,  # Bypass if mega signal
                    entry_cooldown=120,
                    is_peak_hour=is_peak
                )
                self.active_moonshots[symbol] = signal

                if is_mega:
                    logger.warning(f"🔥 MEGA MOONSHOT LONG: {symbol} (+{price_change:.1f}%, score: {score}/6)")
                else:
                    logger.info(f"🚀 MOONSHOT LONG: {symbol} (score: {score}/6)")

                return signal

            return None

        except Exception as e:
            logger.error(f"Error scanning {symbol} for long: {e}")
            return None
    
    async def scan_for_short(self, symbol: str) -> Optional[MoonshotSignal]:
        """
        Scan for SHORT moonshot signals using ENHANCED MOONDROP DETECTION

        Priority Order:
        1. MOONDROP V2: Enhanced detection with 80%+ capture rate (wick, body, range)
        2. TIER 1: Instant entry (-2.5%+ velocity) - bypasses ALL checks
        3. TIER 2: Fast entry (-1.5%+ velocity + volume)
        4. MOMENTUM STACK: Multi-timeframe momentum (bearish)
        5. TIER 3: Micro entry (-1.5%+ 1m velocity, consecutive candles)
        6. LEGACY: 6-signal detection system
        """
        try:
            # ================================================================
            # MOONDROP V2: Enhanced detection (80%+ capture rate)
            # Uses wick drop, body drop, range expansion - catches more moondrops
            # ================================================================
            moondrop_signal = await self.scan_for_moondrop_v2(symbol)
            if moondrop_signal:
                self.active_moonshots[symbol] = moondrop_signal
                return moondrop_signal

            # ================================================================
            # TIER 1: INSTANT ENTRY (bypasses ALL checks)
            # ================================================================
            tier1_signal = await self._check_tier1_signal(symbol, "SHORT")
            if tier1_signal:
                self.active_moonshots[symbol] = tier1_signal
                return tier1_signal

            # ================================================================
            # TIER 2: FAST ENTRY (velocity + volume)
            # ================================================================
            tier2_signal = await self._check_tier2_signal(symbol, "SHORT")
            if tier2_signal:
                self.active_moonshots[symbol] = tier2_signal
                return tier2_signal

            # ================================================================
            # MOMENTUM STACK: Multi-timeframe momentum (catches slow drops)
            # ================================================================
            momentum_signal = await self._check_momentum_stack(symbol, "SHORT")
            if momentum_signal:
                self.active_moonshots[symbol] = momentum_signal
                return momentum_signal

            # ================================================================
            # TIER 3: MICRO ENTRY (1m velocity + consecutive candles)
            # ================================================================
            tier3_signal = await self._check_tier3_signal(symbol, "SHORT")
            if tier3_signal:
                self.active_moonshots[symbol] = tier3_signal
                return tier3_signal

            # ================================================================
            # LEGACY: 6-signal detection system (for lower velocity moves)
            # ================================================================

            # Get ticker for 24h change check
            ticker = await self.data_feed.get_ticker(symbol)

            # MOONDROP MEGA-SIGNAL: If 24h change <= -20%, check if still dropping
            if ticker and ticker.price_change_percent_24h <= -20:
                await self.data_feed.get_klines(symbol, '1m', 10)
                velocity_5m = self.data_feed.get_price_change_percent(symbol, 5)

                if velocity_5m < -1.0:  # Still dropping
                    is_peak = self._is_peak_hour()
                    signal = MoonshotSignal(
                        symbol=symbol,
                        direction="SHORT",
                        score=5,
                        confidence=0.8,
                        signals={'volume': True, 'price': True, 'oi': True, 'funding': True, 'breakdown': True, 'orderbook': False},
                        details={'price_change_24h': ticker.price_change_percent_24h, 'price_change_5m': velocity_5m, 'moondrop': True},
                        timestamp=time.time(),
                        is_mega_signal=True,
                        tier=2,
                        bypass_checks=True,
                        entry_cooldown=60,
                        is_peak_hour=is_peak
                    )
                    self.active_moonshots[symbol] = signal
                    logger.warning(f"🌑 MOONDROP: {symbol} ({ticker.price_change_percent_24h:.1f}% 24h, {velocity_5m:.1f}%/5min)")
                    return signal

            # Standard 6-signal check
            signals = {}
            details = {}

            vol_spike, vol_ratio = await self._check_volume_spike(symbol)
            signals['volume'] = vol_spike
            details['volume_ratio'] = vol_ratio

            price_dump, price_change = await self._check_price_acceleration_short(symbol)
            signals['price'] = price_dump
            details['price_change_5m'] = price_change

            oi_surge, oi_change = await self._check_oi_surge(symbol)
            signals['oi'] = oi_surge
            details['oi_change_15m'] = oi_change

            funding_high, funding_rate = await self._check_funding_for_short(symbol)
            signals['funding'] = funding_high
            details['funding_rate'] = funding_rate

            breakdown, breakdown_strength = await self._check_breakdown(symbol)
            signals['breakdown'] = breakdown
            details['breakdown_strength'] = breakdown_strength

            ob_imbalance, imbalance_ratio = await self._check_orderbook_short(symbol)
            signals['orderbook'] = ob_imbalance
            details['orderbook_imbalance'] = imbalance_ratio

            score = sum(signals.values())

            is_mega = abs(price_change) >= getattr(self.config, 'MEGA_SIGNAL_VELOCITY', 2.0)
            min_signals = getattr(self.config, 'MEGA_SIGNAL_MIN_SIGNALS', 1) if is_mega else self.config.MIN_SIGNALS_REQUIRED

            if score >= min_signals:
                is_peak = self._is_peak_hour()
                signal = MoonshotSignal(
                    symbol=symbol,
                    direction="SHORT",
                    score=score,
                    confidence=score / 6,
                    signals=signals,
                    details=details,
                    timestamp=time.time(),
                    is_mega_signal=is_mega,
                    tier=0,
                    bypass_checks=is_mega,
                    entry_cooldown=120,
                    is_peak_hour=is_peak
                )
                self.active_moonshots[symbol] = signal

                if is_mega:
                    logger.warning(f"🔥 MEGA MOONSHOT SHORT: {symbol} ({price_change:.1f}%, score: {score}/6)")
                else:
                    logger.info(f"📉 MOONSHOT SHORT: {symbol} (score: {score}/6)")

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
        """Check if price is accelerating upward - ENHANCED with OR logic for strong moves"""
        try:
            await self.data_feed.get_klines(symbol, '1m', 10)

            change_5m = self.data_feed.get_price_change_percent(symbol, 5)
            change_1m = self.data_feed.get_price_change_percent(symbol, 1)

            velocity_ok = change_5m >= self.config.PRICE_VELOCITY_5M_LONG
            accelerating = change_1m >= self.config.PRICE_VELOCITY_1M

            # BALANCED FIX: OR logic for strong moves
            # If 5m velocity is very strong (>5%), bypass 1m requirement entirely
            if change_5m >= 5.0:
                return True, change_5m
            # If 5m velocity is strong (>3%), only require weak 1m confirmation (0.2%)
            if change_5m >= 3.0 and change_1m >= 0.2:
                return True, change_5m

            return velocity_ok and accelerating, change_5m

        except Exception as e:
            logger.debug(f"Error checking price for {symbol}: {e}")
            return False, 0.0
    
    async def _check_price_acceleration_short(self, symbol: str) -> Tuple[bool, float]:
        """Check if price is accelerating downward - ENHANCED with OR logic for strong moves"""
        try:
            await self.data_feed.get_klines(symbol, '1m', 10)

            change_5m = self.data_feed.get_price_change_percent(symbol, 5)
            change_1m = self.data_feed.get_price_change_percent(symbol, 1)

            velocity_ok = change_5m <= self.config.PRICE_VELOCITY_5M_SHORT
            accelerating = change_1m <= -self.config.PRICE_VELOCITY_1M

            # BALANCED FIX: OR logic for strong moves
            # If 5m velocity is very strong (<-5%), bypass 1m requirement entirely
            if change_5m <= -5.0:
                return True, change_5m
            # If 5m velocity is strong (<-3%), only require weak 1m confirmation (-0.2%)
            if change_5m <= -3.0 and change_1m <= -0.2:
                return True, change_5m

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

    # =========================================================================
    # MOONDROP DETECTION METHODS (80%+ capture rate based on 6,392 moondrops)
    # =========================================================================

    def _get_wick_drop(self, klines) -> float:
        """
        Calculate wick drop percentage (high to low).
        Catches 97% of moondrops at 2.0% threshold.
        """
        if not klines:
            return 0.0
        current = klines[-1]
        if current.high <= 0:
            return 0.0
        wick_drop = ((current.high - current.low) / current.high) * 100
        return wick_drop

    def _get_body_drop(self, klines) -> float:
        """
        Calculate body drop percentage (open to close for bearish candles).
        Only returns positive value if candle is bearish.
        """
        if not klines:
            return 0.0
        current = klines[-1]
        if current.open <= 0:
            return 0.0
        if current.close < current.open:
            body_drop = ((current.open - current.close) / current.open) * 100
            return body_drop
        return 0.0

    def _get_range_expansion(self, klines) -> float:
        """
        Calculate range expansion vs recent average.
        Catches 80% of moondrops at 1.1x threshold.
        """
        if not klines or len(klines) < 12:
            return 1.0

        current = klines[-1]
        if current.high <= 0:
            return 1.0

        current_range = (current.high - current.low) / current.high * 100

        # Calculate average range from previous 12 candles
        prev_ranges = []
        for k in klines[-13:-1]:
            if k.high > 0:
                r = (k.high - k.low) / k.high * 100
                prev_ranges.append(r)

        if not prev_ranges:
            return 1.0

        avg_range = sum(prev_ranges) / len(prev_ranges)
        if avg_range <= 0:
            return 1.0

        return current_range / avg_range

    async def scan_for_moondrop_v2(self, symbol: str) -> Optional[MoonshotSignal]:
        """
        Enhanced moondrop detection with 80%+ capture rate.
        Based on analysis of 6,392 moondrops across all 598 Binance pairs.

        TIERED DETECTION SYSTEM:
        - TIER 1 (EXTREME): velocity_1m <= -2% OR velocity_5m <= -4% → Instant entry
        - TIER 2 (HIGH): velocity_5m <= -1.5% OR wick_drop >= 3% → Fast entry
        - TIER 3 (MEDIUM): wick_drop >= 2% OR velocity_5m <= -0.8% → Standard entry
        - TIER 4 (EARLY): wick_drop >= 1.5% AND vol_spike >= 1.2x → Watchlist
        """
        try:
            klines = await self.data_feed.get_klines(symbol, '5m', 15)
            if not klines or len(klines) < 12:
                return None

            # Calculate moondrop indicators
            wick_drop = self._get_wick_drop(klines)
            body_drop = self._get_body_drop(klines)
            range_exp = self._get_range_expansion(klines)
            velocity_5m = self.data_feed.get_price_change_percent(symbol, 5)
            velocity_1m = self.data_feed.get_price_change_percent(symbol, 1)

            # Get volume spike
            vol_ok, vol_ratio = await self._check_volume_spike(symbol)

            is_peak = self._is_peak_hour()

            # ================================================================
            # TIER 1: EXTREME MOONDROP (instant trigger)
            # ================================================================
            extreme_vel_1m = getattr(self.config, 'MOONDROP_EXTREME_VELOCITY_1M', -2.0)
            extreme_vel_5m = getattr(self.config, 'MOONDROP_EXTREME_VELOCITY_5M', -4.0)

            if velocity_1m <= extreme_vel_1m or velocity_5m <= extreme_vel_5m:
                logger.warning(f"🌑🌑🌑 TIER 1 EXTREME MOONDROP: {symbol} | 1m: {velocity_1m:.2f}% | 5m: {velocity_5m:.2f}% | wick: {wick_drop:.1f}%{' PEAK' if is_peak else ''}")
                return MoonshotSignal(
                    symbol=symbol,
                    direction="SHORT",
                    score=6,
                    confidence=1.0,
                    signals={'extreme_velocity': True, 'wick_drop': True, 'volume': True, 'range_expansion': True, 'body_drop': True, 'moondrop_v2': True},
                    details={
                        'velocity_1m': velocity_1m, 'velocity_5m': velocity_5m,
                        'wick_drop': wick_drop, 'body_drop': body_drop,
                        'range_expansion': range_exp, 'volume_ratio': vol_ratio,
                        'tier': 1, 'detection': 'EXTREME_MOONDROP'
                    },
                    timestamp=time.time(),
                    is_mega_signal=True,
                    tier=1,
                    bypass_checks=True,
                    entry_cooldown=getattr(self.config, 'ENTRY_COOLDOWN_TIER1', 30),
                    is_peak_hour=is_peak
                )

            # ================================================================
            # TIER 2: HIGH PRIORITY MOONDROP (fast entry)
            # ================================================================
            high_vel_5m = getattr(self.config, 'MOONDROP_HIGH_VELOCITY_5M', -1.5)
            high_wick = getattr(self.config, 'MOONDROP_HIGH_WICK_DROP', 3.0)

            if velocity_5m <= high_vel_5m or wick_drop >= high_wick:
                logger.warning(f"🌑🌑 TIER 2 HIGH MOONDROP: {symbol} | 5m: {velocity_5m:.2f}% | wick: {wick_drop:.1f}% | vol: {vol_ratio:.1f}x{' PEAK' if is_peak else ''}")
                return MoonshotSignal(
                    symbol=symbol,
                    direction="SHORT",
                    score=5,
                    confidence=0.9,
                    signals={'high_velocity': True, 'wick_drop': wick_drop >= 2.0, 'volume': vol_ok, 'range_expansion': range_exp >= 1.3, 'body_drop': body_drop >= 0.8, 'moondrop_v2': True},
                    details={
                        'velocity_1m': velocity_1m, 'velocity_5m': velocity_5m,
                        'wick_drop': wick_drop, 'body_drop': body_drop,
                        'range_expansion': range_exp, 'volume_ratio': vol_ratio,
                        'tier': 2, 'detection': 'HIGH_MOONDROP'
                    },
                    timestamp=time.time(),
                    is_mega_signal=True,
                    tier=2,
                    bypass_checks=True,
                    entry_cooldown=getattr(self.config, 'ENTRY_COOLDOWN_TIER2', 60),
                    is_peak_hour=is_peak
                )

            # ================================================================
            # TIER 3: MEDIUM MOONDROP (80% capture - standard entry with confirmation)
            # ================================================================
            med_vel_5m = getattr(self.config, 'MOONDROP_MEDIUM_VELOCITY_5M', -0.8)
            med_wick = getattr(self.config, 'MOONDROP_MEDIUM_WICK_DROP', 2.0)
            med_body = getattr(self.config, 'MOONDROP_MEDIUM_BODY_DROP', 0.8)
            med_range = getattr(self.config, 'MOONDROP_MEDIUM_RANGE_EXP', 1.3)

            # Primary conditions (OR logic)
            primary_trigger = (
                wick_drop >= med_wick or
                velocity_5m <= med_vel_5m or
                (body_drop >= med_body and range_exp >= med_range)
            )

            if primary_trigger:
                # Require 1 confirmation signal
                confirmations = sum([
                    vol_ratio >= 1.3,
                    range_exp >= 1.5,
                    body_drop >= 1.0,
                    wick_drop >= 2.5
                ])

                if confirmations >= 1:
                    logger.info(f"🌑 TIER 3 MEDIUM MOONDROP: {symbol} | 5m: {velocity_5m:.2f}% | wick: {wick_drop:.1f}% | confirms: {confirmations}{' PEAK' if is_peak else ''}")
                    return MoonshotSignal(
                        symbol=symbol,
                        direction="SHORT",
                        score=4,
                        confidence=0.8,
                        signals={'medium_velocity': velocity_5m <= med_vel_5m, 'wick_drop': wick_drop >= med_wick, 'volume': vol_ok, 'range_expansion': range_exp >= 1.3, 'body_drop': body_drop >= 0.8, 'moondrop_v2': True},
                        details={
                            'velocity_1m': velocity_1m, 'velocity_5m': velocity_5m,
                            'wick_drop': wick_drop, 'body_drop': body_drop,
                            'range_expansion': range_exp, 'volume_ratio': vol_ratio,
                            'confirmations': confirmations, 'tier': 3, 'detection': 'MEDIUM_MOONDROP'
                        },
                        timestamp=time.time(),
                        is_mega_signal=False,
                        tier=3,
                        bypass_checks=False,
                        entry_cooldown=getattr(self.config, 'ENTRY_COOLDOWN_TIER3', 120),
                        is_peak_hour=is_peak
                    )

            # TIER 4: EARLY DETECTION (watchlist only - don't create signal)
            early_wick = getattr(self.config, 'MOONDROP_EARLY_WICK_DROP', 1.5)
            early_vol = getattr(self.config, 'MOONDROP_EARLY_VOL_SPIKE', 1.2)

            if wick_drop >= early_wick and vol_ratio >= early_vol:
                logger.debug(f"👀 EARLY MOONDROP WATCH: {symbol} | wick: {wick_drop:.1f}% | vol: {vol_ratio:.1f}x")
                # Don't return signal for early detection - just log for monitoring

            return None

        except Exception as e:
            logger.debug(f"Moondrop v2 check error for {symbol}: {e}")
            return None
