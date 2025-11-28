"""
Position Tracker Module
Tracks all open positions and syncs with exchange
"""
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from loguru import logger
import time
import json
import redis.asyncio as redis

from config import REDIS_URL, REDIS_PREFIX


@dataclass
class TrackedPosition:
    symbol: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    quantity: float
    margin: float
    leverage: int
    entry_time: float
    order_id: str
    unrealized_pnl: float = 0.0
    current_price: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'direction': self.direction,
            'entry_price': self.entry_price,
            'quantity': self.quantity,
            'margin': self.margin,
            'leverage': self.leverage,
            'entry_time': self.entry_time,
            'order_id': self.order_id,
            'unrealized_pnl': self.unrealized_pnl,
            'current_price': self.current_price
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'TrackedPosition':
        return cls(**data)


class PositionTracker:
    """
    Tracks all open positions
    Persists to Redis for recovery after restart
    """
    
    def __init__(self, data_feed):
        self.data_feed = data_feed
        self.positions: Dict[str, TrackedPosition] = {}
        self.redis: Optional[redis.Redis] = None
        self._redis_key = f"{REDIS_PREFIX}positions"
    
    async def initialize(self):
        """Initialize Redis connection and load positions"""
        try:
            self.redis = redis.from_url(REDIS_URL, decode_responses=True)
            await self.redis.ping()
            logger.info("Redis connected for position tracking")
            
            # Load existing positions from Redis
            await self._load_from_redis()
            
            # Sync with exchange
            await self.sync_with_exchange()
            
        except Exception as e:
            logger.error(f"Error initializing Redis: {e}")
            self.redis = None
    
    async def _load_from_redis(self):
        """Load positions from Redis"""
        if not self.redis:
            return

        try:
            data = await self.redis.get(self._redis_key)
            if data:
                positions_data = json.loads(data)
                loaded = 0
                skipped = 0
                for symbol, pos_dict in positions_data.items():
                    # Validate position data before loading
                    entry_price = pos_dict.get('entry_price', 0)
                    leverage = pos_dict.get('leverage', 0)
                    if entry_price <= 0 or leverage <= 0:
                        logger.warning(f"Skipping invalid position from Redis: {symbol} (entry_price={entry_price}, leverage={leverage})")
                        skipped += 1
                        continue
                    self.positions[symbol] = TrackedPosition.from_dict(pos_dict)
                    loaded += 1

                logger.info(f"Loaded {loaded} positions from Redis (skipped {skipped} invalid)")

        except Exception as e:
            logger.error(f"Error loading positions from Redis: {e}")
    
    async def _save_to_redis(self):
        """Save positions to Redis"""
        if not self.redis:
            return
        
        try:
            data = {symbol: pos.to_dict() for symbol, pos in self.positions.items()}
            await self.redis.set(self._redis_key, json.dumps(data))
        except Exception as e:
            logger.error(f"Error saving positions to Redis: {e}")
    
    async def sync_with_exchange(self):
        """Sync local tracking with actual exchange positions"""
        try:
            # Get actual positions from exchange
            account = await self.data_feed.client.futures_position_information()
            
            exchange_positions = {}
            for p in account:
                if float(p['positionAmt']) != 0:
                    symbol = p['symbol']
                    entry_price = float(p['entryPrice'])
                    # Skip positions with invalid entry price (would cause division by zero)
                    if entry_price == 0:
                        logger.warning(f"Skipping {symbol} - entry price is 0")
                        continue
                    exchange_positions[symbol] = {
                        'quantity': abs(float(p['positionAmt'])),
                        'entry_price': entry_price,
                        'direction': 'LONG' if float(p['positionAmt']) > 0 else 'SHORT',
                        'unrealized_pnl': float(p['unRealizedProfit']),
                        'leverage': int(p['leverage'])
                    }
            
            # Update local tracking
            for symbol, ex_pos in exchange_positions.items():
                if symbol in self.positions:
                    # Update existing
                    self.positions[symbol].quantity = ex_pos['quantity']
                    self.positions[symbol].unrealized_pnl = ex_pos['unrealized_pnl']
                else:
                    # New position not tracked locally (maybe opened manually)
                    self.positions[symbol] = TrackedPosition(
                        symbol=symbol,
                        direction=ex_pos['direction'],
                        entry_price=ex_pos['entry_price'],
                        quantity=ex_pos['quantity'],
                        margin=0,  # Unknown
                        leverage=ex_pos['leverage'],
                        entry_time=time.time(),
                        order_id="SYNCED",
                        unrealized_pnl=ex_pos['unrealized_pnl']
                    )
                    logger.info(f"📥 Synced position from exchange: {symbol}")
            
            # Remove closed positions
            for symbol in list(self.positions.keys()):
                if symbol not in exchange_positions:
                    del self.positions[symbol]
                    logger.info(f"📤 Position no longer on exchange: {symbol}")
            
            # Save to Redis
            await self._save_to_redis()
            
            logger.debug(f"Synced {len(self.positions)} positions with exchange")
            
        except Exception as e:
            logger.error(f"Error syncing with exchange: {e}")
    
    async def add_position(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        quantity: float,
        margin: float,
        leverage: int,
        order_id: str
    ):
        """Add a new position to tracking"""
        position = TrackedPosition(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            quantity=quantity,
            margin=margin,
            leverage=leverage,
            entry_time=time.time(),
            order_id=order_id,
            current_price=entry_price
        )
        
        self.positions[symbol] = position
        await self._save_to_redis()
        
        logger.info(f"📍 Position tracked: {symbol} {direction} @ {entry_price}")
    
    async def update_position(self, symbol: str, current_price: float, unrealized_pnl: float):
        """Update position with current market data"""
        if symbol in self.positions:
            self.positions[symbol].current_price = current_price
            self.positions[symbol].unrealized_pnl = unrealized_pnl
    
    async def remove_position(self, symbol: str):
        """Remove a position from tracking"""
        if symbol in self.positions:
            del self.positions[symbol]
            await self._save_to_redis()
            logger.info(f"📤 Position removed from tracking: {symbol}")
    
    async def reduce_position(self, symbol: str, reduce_percent: float):
        """Reduce position quantity after partial close"""
        if symbol in self.positions:
            self.positions[symbol].quantity *= (1 - reduce_percent / 100)
            
            if self.positions[symbol].quantity <= 0:
                await self.remove_position(symbol)
            else:
                await self._save_to_redis()
    
    def has_position(self, symbol: str) -> bool:
        """Check if we have a position in a symbol"""
        return symbol in self.positions
    
    def get_position(self, symbol: str) -> Optional[TrackedPosition]:
        """Get a tracked position"""
        return self.positions.get(symbol)
    
    def get_all_positions(self) -> List[TrackedPosition]:
        """Get all tracked positions"""
        return list(self.positions.values())
    
    def get_position_count(self) -> int:
        """Get number of open positions"""
        return len(self.positions)
    
    def get_total_unrealized_pnl(self) -> float:
        """Get total unrealized P&L across all positions"""
        return sum(p.unrealized_pnl for p in self.positions.values())
    
    def get_symbols(self) -> List[str]:
        """Get list of symbols with open positions"""
        return list(self.positions.keys())
    
    def log_status(self):
        """Log current position status"""
        if not self.positions:
            logger.info("📊 No open positions")
            return
        
        logger.info(f"📊 Open positions: {len(self.positions)}")
        
        for pos in self.positions.values():
            pnl_emoji = "🟢" if pos.unrealized_pnl >= 0 else "🔴"
            logger.info(
                f"   {pnl_emoji} {pos.symbol} {pos.direction} | "
                f"Entry: {pos.entry_price:.6f} | "
                f"Current: {pos.current_price:.6f} | "
                f"P&L: ${pos.unrealized_pnl:.2f}"
            )
    
    async def close(self):
        """Clean shutdown"""
        if self.redis:
            await self._save_to_redis()
            await self.redis.close()
