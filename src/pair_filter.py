"""
Pair Filter Module
Filters and categorizes trading pairs by tier for scanning priority
"""
from enum import Enum
from typing import List, Dict, Optional, Set
from dataclasses import dataclass
from loguru import logger
import time

from config import PairFilterConfig


class PairTier(Enum):
    TIER_1_HOT = 1  # New listings, volume exploding
    TIER_2_ACTIVE = 2  # High volume, volatile
    TIER_3_NORMAL = 3  # Normal pairs
    TIER_4_LOW = 4  # Low priority


@dataclass
class PairInfo:
    symbol: str
    tier: PairTier
    volume_24h: float
    listing_age_hours: float
    spread_percent: float
    last_scan: float = 0
    scan_interval: int = 10  # seconds


class PairFilter:
    """
    Filters pairs and assigns scanning tiers based on activity
    """
    
    def __init__(self, data_feed):
        self.data_feed = data_feed
        self.config = PairFilterConfig
        
        self.pairs: Dict[str, PairInfo] = {}
        self.excluded_pairs: Set[str] = set()
        
        # Special watchlists
        self.memecoins = {"DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "BONKUSDT", "FLOKIUSDT", 
                         "WIFUSDT", "MEMEUSDT", "BOMEUSDT"}
        self.ai_sector = {"FETUSDT", "AGIXUSDT", "RNDRUSDT", "TAOUSDT", "ARKMUSDT"}
        self.new_listings: Set[str] = set()
    
    async def initialize(self) -> List[str]:
        """Initialize pair list and categorize"""
        logger.info("Initializing pair filter...")

        # Log whitelist status
        if hasattr(self.config, 'ALLOWED_COINS') and self.config.ALLOWED_COINS:
            logger.info(f"🔒 WHITELIST MODE: Only {len(self.config.ALLOWED_COINS)} coins allowed")

        all_symbols = await self.data_feed.get_all_futures_symbols()

        valid_pairs = []
        for symbol in all_symbols:
            if await self._passes_filters(symbol):
                valid_pairs.append(symbol)

        logger.info(f"Filtered to {len(valid_pairs)} valid pairs from {len(all_symbols)} total")
        
        # Categorize pairs
        await self._categorize_pairs(valid_pairs)
        
        return valid_pairs
    
    async def _passes_filters(self, symbol: str) -> bool:
        """Check if symbol passes all inclusion/exclusion filters"""

        # WHITELIST CHECK - If ALLOWED_COINS is set, ONLY allow those coins
        if hasattr(self.config, 'ALLOWED_COINS') and self.config.ALLOWED_COINS:
            if symbol not in self.config.ALLOWED_COINS:
                return False

        # Exclusion: Stablecoins
        if symbol in self.config.STABLECOINS:
            return False

        # Exclusion: Quote asset check
        quote_valid = False
        for quote in self.config.QUOTE_ASSETS:
            if symbol.endswith(quote):
                quote_valid = True
                break

        if not quote_valid:
            return False

        try:
            # Get ticker data
            ticker = await self.data_feed.get_ticker(symbol)
            if not ticker:
                return False

            # MEGA-MOVER BYPASS: If 24h change > 20%, ALWAYS include regardless of volume/spread
            if abs(ticker.price_change_percent_24h) > 20:
                logger.debug(f"🔥 Mega-mover bypass for {symbol}: {ticker.price_change_percent_24h:.1f}% 24h change")
                return True

            # HOT MOVER BYPASS: If 24h change > 10%, relax volume/spread requirements
            if abs(ticker.price_change_percent_24h) > 10:
                # Only require $50K volume for hot movers
                if ticker.volume_24h >= 50_000:
                    return True

            # Normal volume filter
            if ticker.volume_24h < self.config.MIN_VOLUME_24H_USD:
                return False

            # Spread filter (relaxed for volatile coins)
            spread = await self.data_feed.get_spread(symbol)
            if spread > self.config.MAX_SPREAD_PERCENT:
                return False

            return True

        except Exception as e:
            logger.debug(f"Error checking filters for {symbol}: {e}")
            return False
    
    async def _categorize_pairs(self, symbols: List[str]):
        """Categorize pairs into tiers"""
        for symbol in symbols:
            tier = await self._determine_tier(symbol)
            
            ticker = self.data_feed.tickers.get(symbol)
            spread = await self.data_feed.get_spread(symbol)
            
            self.pairs[symbol] = PairInfo(
                symbol=symbol,
                tier=tier,
                volume_24h=ticker.volume_24h if ticker else 0,
                listing_age_hours=0,  # Would need historical data
                spread_percent=spread,
                scan_interval=self._get_scan_interval(tier)
            )
        
        # Log tier distribution
        tier_counts = {t: 0 for t in PairTier}
        for p in self.pairs.values():
            tier_counts[p.tier] += 1
        
        logger.info(f"Pair tiers: T1={tier_counts[PairTier.TIER_1_HOT]}, "
                   f"T2={tier_counts[PairTier.TIER_2_ACTIVE]}, "
                   f"T3={tier_counts[PairTier.TIER_3_NORMAL]}, "
                   f"T4={tier_counts[PairTier.TIER_4_LOW]}")
    
    async def _determine_tier(self, symbol: str) -> PairTier:
        """Determine the tier for a symbol"""
        
        # TIER 1: New listings or in special watchlists
        if symbol in self.new_listings:
            return PairTier.TIER_1_HOT
        
        if symbol in self.memecoins or symbol in self.ai_sector:
            return PairTier.TIER_1_HOT
        
        ticker = self.data_feed.tickers.get(symbol)
        if not ticker:
            return PairTier.TIER_3_NORMAL
        
        # TIER 2: High volume + volatility
        if ticker.volume_24h > 50_000_000:  # $50M+
            if abs(ticker.price_change_percent_24h) > 5:
                return PairTier.TIER_2_ACTIVE
        
        # TIER 4: Low volume
        if ticker.volume_24h < 10_000_000:  # <$10M
            return PairTier.TIER_4_LOW
        
        # Default: TIER 3
        return PairTier.TIER_3_NORMAL
    
    def _get_scan_interval(self, tier: PairTier) -> int:
        """Get scan interval in seconds for a tier"""
        intervals = {
            PairTier.TIER_1_HOT: self.config.TIER_1_INTERVAL,
            PairTier.TIER_2_ACTIVE: self.config.TIER_2_INTERVAL,
            PairTier.TIER_3_NORMAL: self.config.TIER_3_INTERVAL,
            PairTier.TIER_4_LOW: self.config.TIER_4_INTERVAL,
        }
        return intervals.get(tier, 10)
    
    def get_pairs_to_scan(self) -> List[str]:
        """Get pairs that need scanning based on their interval"""
        now = time.time()
        to_scan = []
        
        for symbol, info in self.pairs.items():
            if now - info.last_scan >= info.scan_interval:
                to_scan.append(symbol)
        
        return to_scan
    
    def mark_scanned(self, symbol: str):
        """Mark a pair as just scanned"""
        if symbol in self.pairs:
            self.pairs[symbol].last_scan = time.time()
    
    def add_new_listing(self, symbol: str):
        """Add a new listing to hot tier"""
        self.new_listings.add(symbol)
        
        if symbol in self.pairs:
            self.pairs[symbol].tier = PairTier.TIER_1_HOT
            self.pairs[symbol].scan_interval = self.config.TIER_1_INTERVAL
        
        logger.info(f"🆕 New listing added to TIER 1: {symbol}")
    
    def upgrade_to_hot(self, symbol: str):
        """Upgrade a pair to hot tier (e.g., when moonshot detected)"""
        if symbol in self.pairs:
            self.pairs[symbol].tier = PairTier.TIER_1_HOT
            self.pairs[symbol].scan_interval = self.config.TIER_1_INTERVAL
    
    async def refresh_categories(self):
        """Refresh pair categories (call periodically)"""
        for symbol in list(self.pairs.keys()):
            try:
                # Re-check filters
                if not await self._passes_filters(symbol):
                    del self.pairs[symbol]
                    self.excluded_pairs.add(symbol)
                    continue
                
                # Re-categorize
                tier = await self._determine_tier(symbol)
                self.pairs[symbol].tier = tier
                self.pairs[symbol].scan_interval = self._get_scan_interval(tier)
                
                # Update volume
                ticker = self.data_feed.tickers.get(symbol)
                if ticker:
                    self.pairs[symbol].volume_24h = ticker.volume_24h
                    
            except Exception as e:
                logger.debug(f"Error refreshing {symbol}: {e}")
    
    def get_tier_1_pairs(self) -> List[str]:
        """Get all tier 1 (hot) pairs"""
        return [s for s, p in self.pairs.items() if p.tier == PairTier.TIER_1_HOT]
    
    def get_tier_2_pairs(self) -> List[str]:
        """Get all tier 2 (active) pairs"""
        return [s for s, p in self.pairs.items() if p.tier == PairTier.TIER_2_ACTIVE]
    
    def get_all_active_pairs(self) -> List[str]:
        """Get all pairs (tier 1-4)"""
        return list(self.pairs.keys())

    def get_hot_movers(self) -> List[str]:
        """Get symbols with >10% 24h change - always scan these first"""
        hot = []
        for symbol, ticker in self.data_feed.tickers.items():
            if abs(ticker.price_change_percent_24h) > 10:
                hot.append(symbol)
        return sorted(hot, key=lambda s: abs(self.data_feed.tickers[s].price_change_percent_24h), reverse=True)

    def get_mega_movers(self) -> List[str]:
        """Get symbols with >20% 24h change - top priority"""
        mega = []
        for symbol, ticker in self.data_feed.tickers.items():
            if abs(ticker.price_change_percent_24h) > 20:
                mega.append(symbol)
        return sorted(mega, key=lambda s: abs(self.data_feed.tickers[s].price_change_percent_24h), reverse=True)

    def get_all_symbols_sorted_by_movement(self) -> List[str]:
        """Get ALL symbols from WebSocket cache sorted by absolute 24h change"""
        all_symbols = list(self.data_feed.tickers.keys())

        # Filter out stablecoins
        filtered = [s for s in all_symbols if s not in self.config.STABLECOINS]

        # Sort by absolute 24h change (biggest movers first)
        return sorted(
            filtered,
            key=lambda s: abs(self.data_feed.tickers[s].price_change_percent_24h),
            reverse=True
        )
