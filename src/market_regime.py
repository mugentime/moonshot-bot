"""
Market Regime Detector Module
Determines the current market state: TRENDING, CHOPPY, EXTREME, etc.
"""
import asyncio
from enum import Enum
from typing import Optional, Dict, List
from dataclasses import dataclass
from loguru import logger
import time
import numpy as np

from config import MarketRegimeConfig


class MarketRegime(Enum):
    MOONSHOT = "MOONSHOT"  # Explosive move in specific pair
    TRENDING_UP = "TRENDING_UP"  # Clear bullish trend
    TRENDING_DOWN = "TRENDING_DOWN"  # Clear bearish trend
    CHOPPY = "CHOPPY"  # No direction, noise
    EXTREME_VOLATILITY = "EXTREME_VOLATILITY"  # Wild swings
    LOW_VOLATILITY = "LOW_VOLATILITY"  # Market sleeping


@dataclass
class RegimeState:
    regime: MarketRegime
    confidence: float
    btc_trend: str  # "UP", "DOWN", "NEUTRAL"
    adx_value: float
    atr_ratio: float  # Current ATR vs average
    timestamp: float


class MarketRegimeDetector:
    """
    Detects the overall market regime based on BTC/ETH behavior
    """
    
    def __init__(self, data_feed):
        self.data_feed = data_feed
        self.config = MarketRegimeConfig
        
        self.current_regime = MarketRegime.LOW_VOLATILITY
        self.regime_history: List[RegimeState] = []
        
        # Cache for calculations
        self._adx_cache: Dict[str, float] = {}
        self._atr_cache: Dict[str, float] = {}
        self._ema_cache: Dict[str, float] = {}
        
        # Callbacks
        self.on_regime_change = None
    
    async def evaluate(self) -> RegimeState:
        """Evaluate current market regime"""
        try:
            # Get data for reference pairs
            btc_state = await self._analyze_pair("BTCUSDT")
            eth_state = await self._analyze_pair("ETHUSDT")
            
            if not btc_state:
                return RegimeState(
                    regime=MarketRegime.LOW_VOLATILITY,
                    confidence=0.5,
                    btc_trend="NEUTRAL",
                    adx_value=0,
                    atr_ratio=1.0,
                    timestamp=time.time()
                )
            
            # Determine regime based on indicators
            regime = self._determine_regime(btc_state, eth_state)
            
            state = RegimeState(
                regime=regime,
                confidence=btc_state.get('confidence', 0.7),
                btc_trend=btc_state.get('trend', 'NEUTRAL'),
                adx_value=btc_state.get('adx', 0),
                atr_ratio=btc_state.get('atr_ratio', 1.0),
                timestamp=time.time()
            )
            
            # Check for regime change
            if regime != self.current_regime:
                old_regime = self.current_regime
                self.current_regime = regime
                
                logger.warning(f"⚠️ REGIME CHANGE: {old_regime.value} → {regime.value}")
                
                if self.on_regime_change:
                    await self.on_regime_change(old_regime, regime)
            
            self.regime_history.append(state)
            
            # Keep only last 100 states
            if len(self.regime_history) > 100:
                self.regime_history = self.regime_history[-100:]
            
            return state
            
        except Exception as e:
            logger.error(f"Error evaluating market regime: {e}")
            return RegimeState(
                regime=self.current_regime,
                confidence=0.5,
                btc_trend="NEUTRAL",
                adx_value=0,
                atr_ratio=1.0,
                timestamp=time.time()
            )
    
    async def _analyze_pair(self, symbol: str) -> Optional[Dict]:
        """Analyze a single pair for regime detection"""
        try:
            # Get klines
            klines_1h = await self.data_feed.get_klines(symbol, '1h', 50)
            klines_4h = await self.data_feed.get_klines(symbol, '4h', 20)
            
            if not klines_1h or len(klines_1h) < 30:
                return None
            
            closes = np.array([k.close for k in klines_1h])
            highs = np.array([k.high for k in klines_1h])
            lows = np.array([k.low for k in klines_1h])
            
            # Calculate ADX
            adx = self._calculate_adx(highs, lows, closes, self.config.ADX_PERIOD)
            
            # Calculate ATR
            atr = self._calculate_atr(highs, lows, closes, self.config.ATR_PERIOD)
            atr_avg = np.mean([self._calculate_atr(highs[:i+14], lows[:i+14], closes[:i+14], 14) 
                             for i in range(14, len(closes)-14)])
            atr_ratio = atr / atr_avg if atr_avg > 0 else 1.0
            
            # Calculate EMA20
            ema20 = self._calculate_ema(closes, 20)
            current_price = closes[-1]
            
            # Determine trend
            if current_price > ema20:
                trend = "UP"
            elif current_price < ema20:
                trend = "DOWN"
            else:
                trend = "NEUTRAL"
            
            # Check EMA crosses in last 24h (24 1h candles)
            ema_crosses = 0
            for i in range(-24, -1):
                if i >= -len(closes) and i+1 < 0:
                    ema_at_i = self._calculate_ema(closes[:i], 20)
                    ema_at_i1 = self._calculate_ema(closes[:i+1], 20)
                    
                    if (closes[i] > ema_at_i and closes[i+1] < ema_at_i1) or \
                       (closes[i] < ema_at_i and closes[i+1] > ema_at_i1):
                        ema_crosses += 1
            
            return {
                'adx': adx,
                'atr': atr,
                'atr_ratio': atr_ratio,
                'ema20': ema20,
                'current_price': current_price,
                'trend': trend,
                'ema_crosses': ema_crosses,
                'confidence': min(0.9, 0.5 + (adx / 100))
            }
            
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            return None
    
    def _determine_regime(self, btc_state: Dict, eth_state: Optional[Dict]) -> MarketRegime:
        """Determine market regime based on analysis"""
        adx = btc_state['adx']
        atr_ratio = btc_state['atr_ratio']
        trend = btc_state['trend']
        ema_crosses = btc_state.get('ema_crosses', 0)
        
        # EXTREME VOLATILITY: ATR > 3x normal
        if atr_ratio > self.config.ATR_EXTREME_MULTIPLIER:
            return MarketRegime.EXTREME_VOLATILITY
        
        # CHOPPY: Low ADX and many EMA crosses
        if adx < self.config.ADX_CHOPPY_THRESHOLD or ema_crosses >= 3:
            return MarketRegime.CHOPPY
        
        # TRENDING: High ADX
        if adx > self.config.ADX_TRENDING_THRESHOLD:
            if trend == "UP":
                return MarketRegime.TRENDING_UP
            elif trend == "DOWN":
                return MarketRegime.TRENDING_DOWN
        
        # LOW VOLATILITY: Low ATR
        if atr_ratio < 0.8:
            return MarketRegime.LOW_VOLATILITY
        
        # Default to current or neutral
        return self.current_regime if self.current_regime != MarketRegime.MOONSHOT else MarketRegime.LOW_VOLATILITY
    
    def _calculate_adx(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """Calculate Average Directional Index"""
        try:
            if len(highs) < period + 1:
                return 0.0
            
            # True Range
            tr1 = highs[1:] - lows[1:]
            tr2 = np.abs(highs[1:] - closes[:-1])
            tr3 = np.abs(lows[1:] - closes[:-1])
            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            
            # Directional Movement
            up_move = highs[1:] - highs[:-1]
            down_move = lows[:-1] - lows[1:]
            
            plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
            minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
            
            # Smoothed averages
            atr = self._smooth(tr, period)
            plus_di = 100 * self._smooth(plus_dm, period) / atr
            minus_di = 100 * self._smooth(minus_dm, period) / atr
            
            # ADX
            dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
            adx = self._smooth(dx, period)
            
            return float(adx[-1]) if len(adx) > 0 else 0.0
            
        except Exception as e:
            logger.error(f"Error calculating ADX: {e}")
            return 0.0
    
    def _calculate_atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """Calculate Average True Range"""
        try:
            if len(highs) < period + 1:
                return 0.0
            
            tr1 = highs[1:] - lows[1:]
            tr2 = np.abs(highs[1:] - closes[:-1])
            tr3 = np.abs(lows[1:] - closes[:-1])
            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            
            atr = self._smooth(tr, period)
            return float(atr[-1]) if len(atr) > 0 else 0.0
            
        except Exception as e:
            logger.error(f"Error calculating ATR: {e}")
            return 0.0
    
    def _calculate_ema(self, data: np.ndarray, period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(data) < period:
            return float(np.mean(data)) if len(data) > 0 else 0.0
        
        multiplier = 2 / (period + 1)
        ema = [np.mean(data[:period])]
        
        for price in data[period:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
        
        return ema[-1]
    
    def _smooth(self, data: np.ndarray, period: int) -> np.ndarray:
        """Wilder's smoothing method"""
        if len(data) < period:
            return data
        
        smoothed = np.zeros(len(data))
        smoothed[period-1] = np.mean(data[:period])
        
        for i in range(period, len(data)):
            smoothed[i] = (smoothed[i-1] * (period - 1) + data[i]) / period
        
        return smoothed[period-1:]
    
    def allows_long(self) -> bool:
        """Check if current regime allows long entries"""
        return self.current_regime in [
            MarketRegime.MOONSHOT,
            MarketRegime.TRENDING_UP,
            MarketRegime.LOW_VOLATILITY
        ]
    
    def allows_short(self) -> bool:
        """Check if current regime allows short entries"""
        return self.current_regime in [
            MarketRegime.MOONSHOT,
            MarketRegime.TRENDING_DOWN
        ]
    
    def allows_new_entries(self) -> bool:
        """Check if current regime allows any new entries"""
        return self.current_regime not in [
            MarketRegime.CHOPPY,
            MarketRegime.EXTREME_VOLATILITY
        ]
    
    def should_close_all(self) -> bool:
        """Check if regime requires closing all positions"""
        return self.current_regime == MarketRegime.CHOPPY
