"""
EXIT EVENT TRACKER
Tracks all exit events (Global TP and Individual SL) with balance details.
Uses Redis for persistence across deploys.
"""
import json
import os
import asyncio
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Literal
from loguru import logger

TRACKER_FILE = "data/exit_tracker.json"
REDIS_KEY = "exit_tracker_v2"


@dataclass
class ExitEvent:
    """An exit event (TP or SL)"""
    id: str
    timestamp: str
    event_type: str  # "GLOBAL_TP" or "STOP_LOSS"
    symbol: str  # For SL, the specific symbol. For TP, "ALL"
    trigger_percent: float  # Portfolio % for TP, Position % for SL
    threshold_percent: float  # Configured threshold
    balance_before: float
    balance_after: float
    profit_usd: float
    positions_closed: int
    positions: List[dict] = field(default_factory=list)
    total_margin: float = 0.0


class ExitTracker:
    """
    Tracks all exit events (Global TP and Stop Loss).
    Persists to Redis (primary) and JSON file (backup).
    """

    def __init__(self, tracker_file: str = TRACKER_FILE):
        self.tracker_file = tracker_file
        self.events: List[ExitEvent] = []
        self.redis = None
        self._redis_url = os.getenv('REDIS_URL')
        self._initialized = False

    async def initialize(self):
        """Initialize Redis connection and load data"""
        if self._initialized:
            return

        # Try Redis first
        if self._redis_url:
            try:
                import redis.asyncio as redis
                self.redis = redis.from_url(self._redis_url, decode_responses=True)
                await self._load_from_redis()
                self._initialized = True
                logger.info(f"Exit Tracker initialized with Redis ({len(self.events)} events)")
                return
            except Exception as e:
                logger.warning(f"Redis init failed, falling back to file: {e}")
                self.redis = None

        # Fall back to file
        self._load_from_file()
        self._initialized = True

    def _load_from_file(self):
        """Load existing events from file"""
        try:
            os.makedirs(os.path.dirname(self.tracker_file), exist_ok=True)
            if os.path.exists(self.tracker_file):
                with open(self.tracker_file, 'r') as f:
                    data = json.load(f)
                    self.events = [ExitEvent(**e) for e in data.get('events', [])]
                    logger.info(f"Loaded {len(self.events)} exit events from file")
        except Exception as e:
            logger.error(f"Error loading exit tracker from file: {e}")
            self.events = []

    async def _load_from_redis(self):
        """Load events from Redis"""
        if not self.redis:
            return

        try:
            data = await self.redis.get(REDIS_KEY)
            if data:
                parsed = json.loads(data)
                self.events = [ExitEvent(**e) for e in parsed.get('events', [])]
                logger.info(f"Loaded {len(self.events)} exit events from Redis")
            else:
                # No data in Redis, try loading from file and migrate
                self._load_from_file()
                if self.events:
                    await self._save_to_redis()
                    logger.info(f"Migrated {len(self.events)} events from file to Redis")
        except Exception as e:
            logger.error(f"Error loading from Redis: {e}")
            self._load_from_file()

    async def _save_to_redis(self):
        """Save events to Redis"""
        if not self.redis:
            return

        try:
            data = {
                'last_updated': datetime.now().isoformat(),
                'total_events': len(self.events),
                'events': [asdict(e) for e in self.events]
            }
            await self.redis.set(REDIS_KEY, json.dumps(data))
        except Exception as e:
            logger.error(f"Error saving to Redis: {e}")

    def _save_to_file(self):
        """Save events to file (backup)"""
        try:
            os.makedirs(os.path.dirname(self.tracker_file), exist_ok=True)
            with open(self.tracker_file, 'w') as f:
                json.dump({
                    'last_updated': datetime.now().isoformat(),
                    'total_events': len(self.events),
                    'events': [asdict(e) for e in self.events]
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving exit tracker to file: {e}")

    def record_global_tp(
        self,
        trigger_percent: float,
        threshold_percent: float,
        balance_before: float,
        balance_after: float,
        positions: List[dict],
        total_margin: float = 0.0
    ) -> str:
        """Record a Global TP event"""
        event_id = f"TP_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        profit = balance_after - balance_before

        event = ExitEvent(
            id=event_id,
            timestamp=datetime.now().isoformat(),
            event_type="GLOBAL_TP",
            symbol="ALL",
            trigger_percent=trigger_percent,
            threshold_percent=threshold_percent,
            balance_before=balance_before,
            balance_after=balance_after,
            profit_usd=profit,
            positions_closed=len(positions),
            positions=positions,
            total_margin=total_margin
        )

        self.events.append(event)
        self._save_to_file()

        # Async Redis save
        try:
            if self.redis:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._save_to_redis())
        except Exception as e:
            logger.error(f"Error saving to Redis: {e}")

        logger.info(f"{'='*60}")
        logger.info(f"GLOBAL TP RECORDED: {event_id}")
        logger.info(f"Trigger: {trigger_percent:.2f}% | Profit: ${profit:+.2f}")
        logger.info(f"{'='*60}")

        return event_id

    def record_stop_loss(
        self,
        symbol: str,
        trigger_percent: float,
        threshold_percent: float,
        balance_before: float,
        balance_after: float,
        position_details: dict
    ) -> str:
        """Record a Stop Loss event"""
        event_id = f"SL_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{symbol}"
        profit = balance_after - balance_before

        event = ExitEvent(
            id=event_id,
            timestamp=datetime.now().isoformat(),
            event_type="STOP_LOSS",
            symbol=symbol,
            trigger_percent=trigger_percent,
            threshold_percent=threshold_percent,
            balance_before=balance_before,
            balance_after=balance_after,
            profit_usd=profit,
            positions_closed=1,
            positions=[position_details],
            total_margin=position_details.get('margin', 0)
        )

        self.events.append(event)
        self._save_to_file()

        # Async Redis save
        try:
            if self.redis:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._save_to_redis())
        except Exception as e:
            logger.error(f"Error saving to Redis: {e}")

        logger.info(f"SL RECORDED: {symbol} | Loss: ${profit:.2f}")

        return event_id

    def get_stats(self) -> dict:
        """Get summary statistics"""
        if not self.events:
            return {
                'total_events': 0,
                'tp_events': 0,
                'sl_events': 0,
                'total_profit': 0,
                'tp_profit': 0,
                'sl_loss': 0,
                'avg_tp_profit': 0,
                'avg_sl_loss': 0,
                'tp_win_rate': 0,
                'sl_positions': 0
            }

        tp_events = [e for e in self.events if e.event_type == "GLOBAL_TP"]
        sl_events = [e for e in self.events if e.event_type == "STOP_LOSS"]

        tp_profits = [e.profit_usd for e in tp_events]
        sl_profits = [e.profit_usd for e in sl_events]

        return {
            'total_events': len(self.events),
            'tp_events': len(tp_events),
            'sl_events': len(sl_events),
            'total_profit': sum(tp_profits) + sum(sl_profits),
            'tp_profit': sum(tp_profits),
            'sl_loss': sum(sl_profits),
            'avg_tp_profit': sum(tp_profits) / len(tp_profits) if tp_profits else 0,
            'avg_sl_loss': sum(sl_profits) / len(sl_profits) if sl_profits else 0,
            'tp_win_rate': len([p for p in tp_profits if p > 0]) / len(tp_profits) * 100 if tp_profits else 0,
            'sl_positions': len(sl_events)
        }

    def get_recent_events(self, limit: int = 20) -> List[ExitEvent]:
        """Get most recent events"""
        return sorted(self.events, key=lambda x: x.timestamp, reverse=True)[:limit]

    def get_tp_events(self) -> List[ExitEvent]:
        """Get all TP events"""
        return [e for e in self.events if e.event_type == "GLOBAL_TP"]

    def get_sl_events(self) -> List[ExitEvent]:
        """Get all SL events"""
        return [e for e in self.events if e.event_type == "STOP_LOSS"]


# Global instance
exit_tracker = ExitTracker()
