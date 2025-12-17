"""
GLOBAL TAKE PROFIT TRACKER
Tracks all Global TP events with balance before/after and position details.
Uses Redis for persistence across deploys.
"""
import json
import os
import asyncio
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import List, Optional
from loguru import logger

TRACKER_FILE = "data/global_tp_tracker.json"
REDIS_KEY = "global_tp_tracker"


@dataclass
class PositionClose:
    """Individual position closed in a Global TP event"""
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    pnl_usd: float
    pnl_percent: float
    margin: float


@dataclass
class GlobalTPEvent:
    """A Global TP trigger event"""
    id: str
    timestamp: str
    trigger_percent: float  # The portfolio % that triggered TP
    threshold_percent: float  # The configured threshold
    balance_before: float
    balance_after: float
    profit_usd: float
    positions_closed: int
    positions: List[dict] = field(default_factory=list)
    total_margin: float = 0.0
    duration_seconds: int = 0  # How long positions were held


class GlobalTPTracker:
    """
    Tracks all Global Take Profit events.
    Persists to Redis (primary) and JSON file (backup).
    """

    def __init__(self, tracker_file: str = TRACKER_FILE):
        self.tracker_file = tracker_file
        self.events: List[GlobalTPEvent] = []
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
                logger.info(f"TP Tracker initialized with Redis ({len(self.events)} events)")
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
                    self.events = [GlobalTPEvent(**e) for e in data.get('events', [])]
                    logger.info(f"Loaded {len(self.events)} Global TP events from file")
        except Exception as e:
            logger.error(f"Error loading TP tracker from file: {e}")
            self.events = []

    async def _load_from_redis(self):
        """Load events from Redis"""
        if not self.redis:
            return

        try:
            data = await self.redis.get(REDIS_KEY)
            if data:
                parsed = json.loads(data)
                self.events = [GlobalTPEvent(**e) for e in parsed.get('events', [])]
                logger.info(f"Loaded {len(self.events)} Global TP events from Redis")
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
                'total_profit': sum(e.profit_usd for e in self.events),
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
                    'total_profit': sum(e.profit_usd for e in self.events),
                    'events': [asdict(e) for e in self.events]
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving TP tracker to file: {e}")

    async def _save(self):
        """Save to both Redis and file"""
        if self.redis:
            await self._save_to_redis()
        self._save_to_file()

    def record_tp(
        self,
        trigger_percent: float,
        threshold_percent: float,
        balance_before: float,
        balance_after: float,
        positions: List[dict],
        total_margin: float = 0.0
    ) -> str:
        """
        Record a Global TP event.

        Args:
            trigger_percent: The portfolio PnL % that triggered TP
            threshold_percent: The configured TP threshold
            balance_before: Wallet balance before closing positions
            balance_after: Wallet balance after closing positions
            positions: List of position details [{symbol, direction, entry_price, exit_price, pnl_usd, pnl_percent, margin}]
            total_margin: Total margin used by all positions

        Returns:
            Event ID
        """
        event_id = f"TP_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        profit = balance_after - balance_before

        event = GlobalTPEvent(
            id=event_id,
            timestamp=datetime.now().isoformat(),
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

        # Save async - fire and forget
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._save())
            else:
                loop.run_until_complete(self._save())
        except Exception as e:
            logger.error(f"Error scheduling save: {e}")
            self._save_to_file()  # Fallback to sync file save

        logger.info(f"{'='*60}")
        logger.info(f"GLOBAL TP RECORDED: {event_id}")
        logger.info(f"Trigger: {trigger_percent:.2f}% (threshold: {threshold_percent:.2f}%)")
        logger.info(f"Balance: ${balance_before:.2f} -> ${balance_after:.2f}")
        logger.info(f"PROFIT: ${profit:+.2f}")
        logger.info(f"Positions: {len(positions)}")
        logger.info(f"{'='*60}")

        return event_id

    def get_stats(self) -> dict:
        """Get summary statistics"""
        if not self.events:
            return {
                'total_events': 0,
                'total_profit': 0,
                'avg_profit': 0,
                'best_tp': 0,
                'worst_tp': 0,
                'avg_trigger_percent': 0,
                'avg_positions': 0
            }

        profits = [e.profit_usd for e in self.events]
        triggers = [e.trigger_percent for e in self.events]
        positions = [e.positions_closed for e in self.events]

        return {
            'total_events': len(self.events),
            'total_profit': sum(profits),
            'avg_profit': sum(profits) / len(profits),
            'best_tp': max(profits),
            'worst_tp': min(profits),
            'avg_trigger_percent': sum(triggers) / len(triggers),
            'avg_positions': sum(positions) / len(positions),
            'win_rate': len([p for p in profits if p > 0]) / len(profits) * 100
        }

    def print_report(self):
        """Print summary report"""
        stats = self.get_stats()

        report = f"""
================================================================================
                    GLOBAL TAKE PROFIT TRACKER REPORT
================================================================================

SUMMARY
-------
Total TP Events:     {stats['total_events']}
Total Profit:        ${stats['total_profit']:+.2f}
Average Profit:      ${stats['avg_profit']:+.2f}
Best TP:             ${stats['best_tp']:+.2f}
Worst TP:            ${stats['worst_tp']:+.2f}
Win Rate:            {stats.get('win_rate', 0):.1f}%
Avg Trigger %:       {stats['avg_trigger_percent']:.2f}%
Avg Positions:       {stats['avg_positions']:.1f}

ALL EVENTS
----------"""
        print(report)

        for event in self.events:
            print(f"""
{event.timestamp[:19]}
  Trigger:        {event.trigger_percent:.2f}% (threshold: {event.threshold_percent:.2f}%)
  Positions:      {event.positions_closed}
  Balance BEFORE: ${event.balance_before:.2f}
  Balance AFTER:  ${event.balance_after:.2f}
  PROFIT:         ${event.profit_usd:+.2f}""")

            # Show individual positions
            if event.positions:
                print("  Positions:")
                for p in event.positions:
                    status = "WIN" if p.get('pnl_usd', 0) > 0 else "LOSS"
                    print(f"    {p.get('symbol', 'N/A'):15} {p.get('direction', ''):5} ${p.get('pnl_usd', 0):+.4f} {status}")

        print("\n" + "=" * 80)

    def get_last_event(self) -> Optional[GlobalTPEvent]:
        """Get the most recent TP event"""
        return self.events[-1] if self.events else None

    def get_events_since(self, hours: int = 24) -> List[GlobalTPEvent]:
        """Get events from the last N hours"""
        cutoff = datetime.now().timestamp() - (hours * 3600)
        return [
            e for e in self.events
            if datetime.fromisoformat(e.timestamp).timestamp() > cutoff
        ]


# Global instance
tp_tracker = GlobalTPTracker()
