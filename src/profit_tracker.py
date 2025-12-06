"""
PROFIT TRACKER
Tracks all trades from the simplified strategy deployment
Provides real-time metrics and performance analysis
"""
import json
import os
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from loguru import logger

TRACKER_FILE = "data/profit_tracker.json"


@dataclass
class Trade:
    """Individual trade record"""
    id: str
    symbol: str
    direction: str  # LONG or SHORT
    entry_time: str
    entry_price: float
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # stop_loss, trailing_stop, manual
    pnl_percent: Optional[float] = None
    pnl_usd: Optional[float] = None
    leverage: int = 10
    margin_used: float = 0.0
    velocity_at_entry: float = 0.0
    peak_profit: float = 0.0  # Highest profit during trade
    duration_seconds: int = 0


@dataclass
class PerformanceMetrics:
    """Performance metrics for the strategy"""
    # Basic Stats
    total_trades: int = 0
    open_trades: int = 0
    closed_trades: int = 0

    # Win/Loss
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0

    # PnL
    total_pnl_usd: float = 0.0
    total_pnl_percent: float = 0.0
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0
    avg_win_percent: float = 0.0
    avg_loss_percent: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0

    # Risk
    profit_factor: float = 0.0  # gross profit / gross loss
    avg_risk_reward: float = 0.0

    # Exit Analysis
    stop_loss_exits: int = 0
    trailing_stop_exits: int = 0
    manual_exits: int = 0

    # Direction Analysis
    long_trades: int = 0
    short_trades: int = 0
    long_win_rate: float = 0.0
    short_win_rate: float = 0.0

    # Timing
    avg_trade_duration_minutes: float = 0.0
    avg_winner_duration_minutes: float = 0.0
    avg_loser_duration_minutes: float = 0.0

    # Peak Analysis
    avg_peak_profit: float = 0.0  # How much profit we left on table
    capture_efficiency: float = 0.0  # actual profit / peak profit


class ProfitTracker:
    """
    Tracks all trades and calculates performance metrics
    Persists to JSON file for analysis
    """

    def __init__(self, tracker_file: str = TRACKER_FILE):
        self.tracker_file = tracker_file
        self.trades: List[Trade] = []
        self.start_time = datetime.now().isoformat()
        self.start_balance = 0.0
        self._load()

    def _load(self):
        """Load existing trades from file"""
        try:
            os.makedirs(os.path.dirname(self.tracker_file), exist_ok=True)
            if os.path.exists(self.tracker_file):
                with open(self.tracker_file, 'r') as f:
                    data = json.load(f)
                    self.trades = [Trade(**t) for t in data.get('trades', [])]
                    self.start_time = data.get('start_time', self.start_time)
                    self.start_balance = data.get('start_balance', 0.0)
                    logger.info(f"Loaded {len(self.trades)} trades from tracker")
        except Exception as e:
            logger.error(f"Error loading tracker: {e}")
            self.trades = []

    def _save(self):
        """Save trades to file"""
        try:
            os.makedirs(os.path.dirname(self.tracker_file), exist_ok=True)
            with open(self.tracker_file, 'w') as f:
                json.dump({
                    'start_time': self.start_time,
                    'start_balance': self.start_balance,
                    'trades': [asdict(t) for t in self.trades]
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving tracker: {e}")

    def set_start_balance(self, balance: float):
        """Set starting balance for this tracking period"""
        self.start_balance = balance
        self.start_time = datetime.now().isoformat()
        self._save()
        logger.info(f"📊 Profit tracking started. Balance: ${balance:.2f}")

    def record_entry(self, symbol: str, direction: str, entry_price: float,
                     leverage: int, margin: float, velocity: float) -> str:
        """Record a new trade entry"""
        trade_id = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        trade = Trade(
            id=trade_id,
            symbol=symbol,
            direction=direction,
            entry_time=datetime.now().isoformat(),
            entry_price=entry_price,
            leverage=leverage,
            margin_used=margin,
            velocity_at_entry=velocity
        )

        self.trades.append(trade)
        self._save()

        logger.info(f"📝 Trade recorded: {trade_id} | {direction} {symbol} @ ${entry_price:.6f}")
        return trade_id

    def record_exit(self, symbol: str, exit_price: float, exit_reason: str,
                    pnl_percent: float, pnl_usd: float, peak_profit: float = 0.0):
        """Record trade exit"""
        # Find the open trade for this symbol
        for trade in reversed(self.trades):
            if trade.symbol == symbol and trade.exit_time is None:
                trade.exit_time = datetime.now().isoformat()
                trade.exit_price = exit_price
                trade.exit_reason = exit_reason
                trade.pnl_percent = pnl_percent
                trade.pnl_usd = pnl_usd
                trade.peak_profit = peak_profit

                # Calculate duration
                entry_dt = datetime.fromisoformat(trade.entry_time)
                exit_dt = datetime.fromisoformat(trade.exit_time)
                trade.duration_seconds = int((exit_dt - entry_dt).total_seconds())

                self._save()

                status = "✅" if pnl_usd > 0 else "❌"
                logger.info(f"{status} Trade closed: {symbol} | {exit_reason} | PnL: ${pnl_usd:+.2f} ({pnl_percent:+.2f}%)")
                return

        logger.warning(f"No open trade found for {symbol}")

    def update_peak_profit(self, symbol: str, current_profit: float):
        """Update peak profit for an open position"""
        for trade in reversed(self.trades):
            if trade.symbol == symbol and trade.exit_time is None:
                if current_profit > trade.peak_profit:
                    trade.peak_profit = current_profit
                return

    def get_metrics(self) -> PerformanceMetrics:
        """Calculate current performance metrics"""
        metrics = PerformanceMetrics()

        closed_trades = [t for t in self.trades if t.exit_time is not None]
        open_trades = [t for t in self.trades if t.exit_time is None]

        metrics.total_trades = len(self.trades)
        metrics.open_trades = len(open_trades)
        metrics.closed_trades = len(closed_trades)

        if not closed_trades:
            return metrics

        # Win/Loss
        wins = [t for t in closed_trades if t.pnl_usd and t.pnl_usd > 0]
        losses = [t for t in closed_trades if t.pnl_usd and t.pnl_usd <= 0]

        metrics.wins = len(wins)
        metrics.losses = len(losses)
        metrics.win_rate = (len(wins) / len(closed_trades) * 100) if closed_trades else 0

        # PnL
        metrics.total_pnl_usd = sum(t.pnl_usd for t in closed_trades if t.pnl_usd)
        metrics.total_pnl_percent = sum(t.pnl_percent for t in closed_trades if t.pnl_percent)

        if wins:
            metrics.avg_win_usd = sum(t.pnl_usd for t in wins) / len(wins)
            metrics.avg_win_percent = sum(t.pnl_percent for t in wins) / len(wins)
            metrics.largest_win = max(t.pnl_usd for t in wins)

        if losses:
            metrics.avg_loss_usd = sum(t.pnl_usd for t in losses) / len(losses)
            metrics.avg_loss_percent = sum(t.pnl_percent for t in losses) / len(losses)
            metrics.largest_loss = min(t.pnl_usd for t in losses)

        # Profit Factor
        gross_profit = sum(t.pnl_usd for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl_usd for t in losses)) if losses else 0
        metrics.profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

        # Exit Analysis
        metrics.stop_loss_exits = len([t for t in closed_trades if t.exit_reason == 'stop_loss'])
        metrics.trailing_stop_exits = len([t for t in closed_trades if t.exit_reason == 'trailing_stop'])
        metrics.manual_exits = len([t for t in closed_trades if t.exit_reason == 'manual'])

        # Direction Analysis
        longs = [t for t in closed_trades if t.direction == 'LONG']
        shorts = [t for t in closed_trades if t.direction == 'SHORT']

        metrics.long_trades = len(longs)
        metrics.short_trades = len(shorts)

        long_wins = [t for t in longs if t.pnl_usd and t.pnl_usd > 0]
        short_wins = [t for t in shorts if t.pnl_usd and t.pnl_usd > 0]

        metrics.long_win_rate = (len(long_wins) / len(longs) * 100) if longs else 0
        metrics.short_win_rate = (len(short_wins) / len(shorts) * 100) if shorts else 0

        # Timing
        durations = [t.duration_seconds for t in closed_trades if t.duration_seconds]
        if durations:
            metrics.avg_trade_duration_minutes = sum(durations) / len(durations) / 60

        winner_durations = [t.duration_seconds for t in wins if t.duration_seconds]
        if winner_durations:
            metrics.avg_winner_duration_minutes = sum(winner_durations) / len(winner_durations) / 60

        loser_durations = [t.duration_seconds for t in losses if t.duration_seconds]
        if loser_durations:
            metrics.avg_loser_duration_minutes = sum(loser_durations) / len(loser_durations) / 60

        # Peak Analysis (how much we left on table)
        peak_profits = [t.peak_profit for t in closed_trades if t.peak_profit > 0]
        if peak_profits:
            metrics.avg_peak_profit = sum(peak_profits) / len(peak_profits)

        actual_profits = [t.pnl_percent for t in closed_trades if t.pnl_percent and t.pnl_percent > 0 and t.peak_profit > 0]
        if actual_profits and metrics.avg_peak_profit > 0:
            avg_actual = sum(actual_profits) / len(actual_profits)
            metrics.capture_efficiency = (avg_actual / metrics.avg_peak_profit * 100)

        return metrics

    def print_report(self):
        """Print performance report"""
        m = self.get_metrics()

        report = f"""
================================================================================
                     PROFIT TRACKER REPORT
                     Started: {self.start_time}
                     Starting Balance: ${self.start_balance:.2f}
================================================================================

TRADE SUMMARY
-------------
Total Trades: {m.total_trades}
Open Trades: {m.open_trades}
Closed Trades: {m.closed_trades}

WIN/LOSS
--------
Wins: {m.wins} | Losses: {m.losses}
Win Rate: {m.win_rate:.1f}%

PNL
---
Total PnL: ${m.total_pnl_usd:+.2f} ({m.total_pnl_percent:+.2f}%)
Avg Win: ${m.avg_win_usd:+.2f} ({m.avg_win_percent:+.2f}%)
Avg Loss: ${m.avg_loss_usd:.2f} ({m.avg_loss_percent:.2f}%)
Largest Win: ${m.largest_win:+.2f}
Largest Loss: ${m.largest_loss:.2f}
Profit Factor: {m.profit_factor:.2f}

EXIT ANALYSIS
-------------
Stop Loss: {m.stop_loss_exits} ({m.stop_loss_exits/m.closed_trades*100 if m.closed_trades else 0:.1f}%)
Trailing Stop: {m.trailing_stop_exits} ({m.trailing_stop_exits/m.closed_trades*100 if m.closed_trades else 0:.1f}%)
Manual: {m.manual_exits} ({m.manual_exits/m.closed_trades*100 if m.closed_trades else 0:.1f}%)

DIRECTION
---------
Long Trades: {m.long_trades} (Win Rate: {m.long_win_rate:.1f}%)
Short Trades: {m.short_trades} (Win Rate: {m.short_win_rate:.1f}%)

TIMING
------
Avg Trade Duration: {m.avg_trade_duration_minutes:.1f} min
Avg Winner Duration: {m.avg_winner_duration_minutes:.1f} min
Avg Loser Duration: {m.avg_loser_duration_minutes:.1f} min

EFFICIENCY
----------
Avg Peak Profit: {m.avg_peak_profit:.2f}%
Capture Efficiency: {m.capture_efficiency:.1f}%
(How much of peak profit we actually captured)

================================================================================
"""
        print(report)
        logger.info(report)
        return report

    def get_open_trades(self) -> List[Trade]:
        """Get list of open trades"""
        return [t for t in self.trades if t.exit_time is None]

    def reset(self, new_balance: float = 0.0):
        """Reset tracker for new period"""
        self.trades = []
        self.start_time = datetime.now().isoformat()
        self.start_balance = new_balance
        self._save()
        logger.info(f"📊 Tracker reset. New starting balance: ${new_balance:.2f}")


# Global instance
profit_tracker = ProfitTracker()
