"""
FEE TRACKER
Comprehensive fee tracking and monitoring for Binance Futures trading.
Captures actual fees from Binance API, tracks per trade, and provides analytics.
"""
import json
import os
import asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from loguru import logger

FEE_TRACKER_FILE = "data/fee_tracking.json"


@dataclass
class FeeRecord:
    """Individual fee record for a trade"""
    timestamp: str
    symbol: str
    side: str  # LONG or SHORT
    action: str  # OPEN or CLOSE
    notional_value: float
    fee_amount: float
    fee_asset: str
    fee_rate: float
    order_id: Optional[str] = None
    income_type: Optional[str] = None  # COMMISSION, FUNDING_FEE


@dataclass
class FeeStats:
    """Fee statistics and metrics"""
    total_fees: float = 0.0
    total_commission: float = 0.0
    total_funding: float = 0.0
    total_trades: int = 0
    avg_fee_per_trade: float = 0.0
    fee_as_percent_balance: float = 0.0
    expected_fee_rate: float = 0.0004  # 0.04% taker fee
    actual_avg_fee_rate: float = 0.0
    fee_efficiency: float = 100.0  # actual vs expected
    fees_today: float = 0.0
    fees_this_hour: float = 0.0
    hourly_fee_rate: float = 0.0  # fees per hour as % of balance


class FeeTracker:
    """
    Tracks all trading fees from Binance Futures.
    Fetches actual fees from futures_income_history API.
    Provides real-time monitoring and alerts.
    """

    def __init__(self, tracker_file: str = FEE_TRACKER_FILE, data_feed=None):
        self.tracker_file = tracker_file
        self.data_feed = data_feed
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_start = datetime.now().isoformat()
        self.total_fees = 0.0
        self.fee_records: List[FeeRecord] = []

        # Alert thresholds
        self.fee_percent_balance_alert = 2.0  # Alert if fees > 2% of balance per hour
        self.fee_rate_multiplier_alert = 2.0  # Alert if actual > 2x expected

        # Background task
        self._update_task = None
        self._running = False

        self._load()

    def _load(self):
        """Load existing fee records from file"""
        try:
            os.makedirs(os.path.dirname(self.tracker_file), exist_ok=True)
            if os.path.exists(self.tracker_file):
                with open(self.tracker_file, 'r') as f:
                    data = json.load(f)
                    self.session_id = data.get('session_id', self.session_id)
                    self.session_start = data.get('session_start', self.session_start)
                    self.total_fees = data.get('total_fees', 0.0)
                    self.fee_records = [FeeRecord(**r) for r in data.get('trades', [])]
                    logger.info(f"Loaded {len(self.fee_records)} fee records (${self.total_fees:.4f} total)")
        except Exception as e:
            logger.error(f"Error loading fee tracker: {e}")
            self.fee_records = []

    def _save(self):
        """Save fee records to file"""
        try:
            os.makedirs(os.path.dirname(self.tracker_file), exist_ok=True)
            with open(self.tracker_file, 'w') as f:
                json.dump({
                    'session_id': self.session_id,
                    'session_start': self.session_start,
                    'total_fees': self.total_fees,
                    'trades': [asdict(r) for r in self.fee_records]
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving fee tracker: {e}")

    async def fetch_recent_fees(self, lookback_minutes: int = 60) -> List[FeeRecord]:
        """
        Fetch recent fees from Binance futures_income_history.

        Args:
            lookback_minutes: How far back to fetch (default 60 minutes)

        Returns:
            List of FeeRecord objects
        """
        if not self.data_feed or not self.data_feed.client:
            logger.warning("No data_feed available for fee fetching")
            return []

        try:
            start_time = int((datetime.now() - timedelta(minutes=lookback_minutes)).timestamp() * 1000)

            # Fetch commission fees (trading fees)
            commission_income = await self.data_feed.client.futures_income_history(
                incomeType='COMMISSION',
                startTime=start_time,
                limit=1000
            )

            # Fetch funding fees
            funding_income = await self.data_feed.client.futures_income_history(
                incomeType='FUNDING_FEE',
                startTime=start_time,
                limit=1000
            )

            records = []

            # Process commission fees
            for item in commission_income:
                timestamp = datetime.fromtimestamp(int(item['time']) / 1000).isoformat()
                symbol = item.get('symbol', 'UNKNOWN')
                fee_amount = abs(float(item.get('income', 0)))  # Fees are negative
                asset = item.get('asset', 'USDT')

                # Try to determine notional from trade ID (if available)
                # For now, we'll estimate based on standard fee rate
                estimated_notional = fee_amount / 0.0004 if fee_amount > 0 else 0

                records.append(FeeRecord(
                    timestamp=timestamp,
                    symbol=symbol,
                    side='UNKNOWN',
                    action='UNKNOWN',
                    notional_value=estimated_notional,
                    fee_amount=fee_amount,
                    fee_asset=asset,
                    fee_rate=0.0004,  # Standard taker fee
                    income_type='COMMISSION'
                ))

            # Process funding fees
            for item in funding_income:
                timestamp = datetime.fromtimestamp(int(item['time']) / 1000).isoformat()
                symbol = item.get('symbol', 'UNKNOWN')
                fee_amount = abs(float(item.get('income', 0)))
                asset = item.get('asset', 'USDT')

                records.append(FeeRecord(
                    timestamp=timestamp,
                    symbol=symbol,
                    side='UNKNOWN',
                    action='FUNDING',
                    notional_value=0,
                    fee_amount=fee_amount,
                    fee_asset=asset,
                    fee_rate=0,
                    income_type='FUNDING_FEE'
                ))

            logger.debug(f"Fetched {len(records)} fee records from Binance")
            return records

        except Exception as e:
            logger.error(f"Error fetching fees from Binance: {e}")
            return []

    async def record_trade_fee(self, symbol: str, side: str, action: str,
                               notional_value: float, order_id: Optional[str] = None):
        """
        Record a fee for a trade. Fetches actual fee from Binance.

        Args:
            symbol: Trading symbol
            side: LONG or SHORT
            action: OPEN or CLOSE
            notional_value: Trade notional value in USDT
            order_id: Optional order ID to match with Binance records
        """
        try:
            # Fetch recent fees to find this trade
            recent_fees = await self.fetch_recent_fees(lookback_minutes=5)

            # Try to match this trade
            matched_fee = None
            for fee in recent_fees:
                if fee.symbol == symbol and fee.income_type == 'COMMISSION':
                    # This is our fee (most recent for this symbol)
                    matched_fee = fee
                    break

            if matched_fee:
                # Update with our metadata
                matched_fee.side = side
                matched_fee.action = action
                matched_fee.notional_value = notional_value
                matched_fee.order_id = order_id

                self.fee_records.append(matched_fee)
                self.total_fees += matched_fee.fee_amount

                logger.info(f"💰 Fee recorded: {symbol} {action} | ${matched_fee.fee_amount:.4f} ({matched_fee.fee_rate*100:.3f}%)")
            else:
                # Estimate fee if we can't find it
                estimated_fee = notional_value * 0.0004  # Taker fee
                fee_record = FeeRecord(
                    timestamp=datetime.now().isoformat(),
                    symbol=symbol,
                    side=side,
                    action=action,
                    notional_value=notional_value,
                    fee_amount=estimated_fee,
                    fee_asset='USDT',
                    fee_rate=0.0004,
                    order_id=order_id,
                    income_type='COMMISSION'
                )

                self.fee_records.append(fee_record)
                self.total_fees += estimated_fee

                logger.warning(f"💰 Fee estimated (not found in API): {symbol} {action} | ${estimated_fee:.4f}")

            self._save()

        except Exception as e:
            logger.error(f"Error recording fee: {e}")

    def get_stats(self, balance: float = 0) -> FeeStats:
        """
        Calculate fee statistics.

        Args:
            balance: Current account balance for percentage calculations

        Returns:
            FeeStats object with comprehensive metrics
        """
        stats = FeeStats()

        if not self.fee_records:
            return stats

        # Basic totals
        commission_fees = [r for r in self.fee_records if r.income_type == 'COMMISSION']
        funding_fees = [r for r in self.fee_records if r.income_type == 'FUNDING_FEE']

        stats.total_commission = sum(r.fee_amount for r in commission_fees)
        stats.total_funding = sum(r.fee_amount for r in funding_fees)
        stats.total_fees = stats.total_commission + stats.total_funding
        stats.total_trades = len(commission_fees)

        # Average fee per trade
        if stats.total_trades > 0:
            stats.avg_fee_per_trade = stats.total_commission / stats.total_trades

        # Fee as percent of balance
        if balance > 0:
            stats.fee_as_percent_balance = (stats.total_fees / balance) * 100

        # Actual average fee rate
        total_notional = sum(r.notional_value for r in commission_fees if r.notional_value > 0)
        if total_notional > 0:
            stats.actual_avg_fee_rate = stats.total_commission / total_notional

        # Fee efficiency (actual vs expected)
        if stats.actual_avg_fee_rate > 0:
            stats.fee_efficiency = (stats.expected_fee_rate / stats.actual_avg_fee_rate) * 100

        # Today's fees
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_fees = [r for r in self.fee_records
                      if datetime.fromisoformat(r.timestamp) >= today_start]
        stats.fees_today = sum(r.fee_amount for r in today_fees)

        # This hour's fees
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        hour_fees = [r for r in self.fee_records
                     if datetime.fromisoformat(r.timestamp) >= hour_start]
        stats.fees_this_hour = sum(r.fee_amount for r in hour_fees)

        # Hourly fee rate as % of balance
        if balance > 0:
            stats.hourly_fee_rate = (stats.fees_this_hour / balance) * 100

        return stats

    def check_alerts(self, balance: float) -> List[str]:
        """
        Check for fee-related alerts.

        Args:
            balance: Current account balance

        Returns:
            List of alert messages
        """
        alerts = []
        stats = self.get_stats(balance)

        # Alert 1: Hourly fees exceeding threshold
        if stats.hourly_fee_rate > self.fee_percent_balance_alert:
            alerts.append(
                f"⚠️ HIGH FEES: {stats.hourly_fee_rate:.2f}% of balance this hour "
                f"(${stats.fees_this_hour:.4f}) - threshold: {self.fee_percent_balance_alert}%"
            )

        # Alert 2: Actual fees significantly higher than expected
        if stats.fee_efficiency < 50:  # Actual fees > 2x expected
            alerts.append(
                f"⚠️ FEE RATE ANOMALY: Actual rate {stats.actual_avg_fee_rate*100:.4f}% "
                f"vs expected {stats.expected_fee_rate*100:.2f}% - efficiency: {stats.fee_efficiency:.1f}%"
            )

        return alerts

    def get_fee_breakdown_by_symbol(self) -> Dict[str, float]:
        """Get total fees grouped by symbol"""
        breakdown = {}
        for record in self.fee_records:
            if record.symbol not in breakdown:
                breakdown[record.symbol] = 0.0
            breakdown[record.symbol] += record.fee_amount

        # Sort by fees (highest first)
        return dict(sorted(breakdown.items(), key=lambda x: x[1], reverse=True))

    async def start_background_updates(self):
        """Start background task to periodically sync with Binance"""
        self._running = True
        self._update_task = asyncio.create_task(self._update_loop())
        logger.info("Fee tracker background updates started")

    async def stop_background_updates(self):
        """Stop background updates"""
        self._running = False
        if self._update_task:
            self._update_task.cancel()
        logger.info("Fee tracker background updates stopped")

    async def _update_loop(self):
        """Background loop to fetch and update fees every 5 minutes"""
        while self._running:
            try:
                # Fetch last 60 minutes of fees
                recent_fees = await self.fetch_recent_fees(lookback_minutes=60)

                # Add any new fees we haven't seen
                existing_timestamps = {r.timestamp for r in self.fee_records}
                new_fees = [r for r in recent_fees if r.timestamp not in existing_timestamps]

                if new_fees:
                    self.fee_records.extend(new_fees)
                    self.total_fees = sum(r.fee_amount for r in self.fee_records)
                    self._save()
                    logger.info(f"Added {len(new_fees)} new fee records from background sync")

                await asyncio.sleep(300)  # 5 minutes

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in fee tracker update loop: {e}")
                await asyncio.sleep(60)

    def reset_session(self):
        """Start a new tracking session"""
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_start = datetime.now().isoformat()
        self.fee_records = []
        self.total_fees = 0.0
        self._save()
        logger.info(f"Fee tracker session reset: {self.session_id}")


# Global instance
fee_tracker = FeeTracker()
