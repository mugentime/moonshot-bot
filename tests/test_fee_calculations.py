"""
Unit Tests for Fee Calculations and Tracking
Tests fee calculation accuracy, tracking, and impact on profitability
"""
import pytest
from unittest.mock import AsyncMock, Mock, patch
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.fee_tracker import FeeTracker, FeeRecord, FeeStats


class TestFeeCalculations:
    """Test core fee calculation logic"""

    def test_taker_fee_calculation(self):
        """TEST: Binance taker fee (0.05%) calculated correctly"""
        notional = 1000.0
        taker_rate = 0.0005

        fee = notional * taker_rate

        assert fee == 0.5, "0.05% of $1000 = $0.50"

    def test_maker_fee_calculation(self):
        """TEST: Binance maker fee (0.02%) calculated correctly"""
        notional = 1000.0
        maker_rate = 0.0002

        fee = notional * maker_rate

        assert fee == 0.2, "0.02% of $1000 = $0.20"

    def test_round_trip_taker_fees(self):
        """
        TEST: Round trip fees (entry + exit) with taker orders

        Most common scenario: market orders (taker)
        """
        notional = 1000.0
        taker_rate = 0.0005

        entry_fee = notional * taker_rate
        exit_fee = notional * taker_rate
        total = entry_fee + exit_fee

        assert total == 1.0, "Round trip taker: $1.00"
        assert total / notional == 0.001, "0.1% total"

    def test_fee_on_leveraged_position(self):
        """
        TEST: Fees calculated on NOTIONAL, not margin

        Critical: With leverage, fees are on full position size
        """
        margin = 50.0
        leverage = 20
        notional = margin * leverage
        taker_rate = 0.0005

        # WRONG: Fee on margin
        wrong_fee = margin * taker_rate

        # RIGHT: Fee on notional
        correct_fee = notional * taker_rate

        assert wrong_fee == 0.025, "Wrong calculation: $0.025"
        assert correct_fee == 0.5, "Correct calculation: $0.50"
        assert correct_fee > wrong_fee, "Leverage amplifies fees"

    def test_funding_fee_estimation(self):
        """
        TEST: Funding fee estimation (8-hour rate)

        Binance funding rate: ~0.01% every 8 hours
        Daily: ~0.03% (3 funding periods)
        """
        notional = 10000.0
        funding_rate = 0.0001  # 0.01% per 8h
        hours_held = 24

        # Funding periods (every 8 hours)
        periods = hours_held // 8

        total_funding = notional * funding_rate * periods

        assert periods == 3, "3 funding periods in 24h"
        assert total_funding == 3.0, "Total funding: $3.00"

    def test_fee_impact_on_small_profit(self):
        """
        TEST: Demonstrate how fees can eliminate small profits

        Scenario: 0.5% profit on $1000 notional
        """
        notional = 1000.0
        profit_pct = 0.5  # 0.5%
        gross_profit = notional * (profit_pct / 100)

        # Round trip taker fees
        total_fees = notional * 0.001  # 0.1%

        net_profit = gross_profit - total_fees
        net_pct = (net_profit / notional) * 100

        assert gross_profit == 5.0, "Gross profit: $5.00"
        assert total_fees == 1.0, "Fees: $1.00"
        assert net_profit == 4.0, "Net profit: $4.00"
        assert net_pct == 0.4, "Net 0.4% (from 0.5% gross)"


class TestFeeTracker:
    """Test FeeTracker functionality"""

    @pytest.fixture
    def tracker(self, tmp_path):
        """Create a temporary FeeTracker instance"""
        tracker_file = tmp_path / "test_fees.json"
        return FeeTracker(tracker_file=str(tracker_file))

    def test_fee_record_creation(self, tracker):
        """TEST: Create fee record with all required fields"""
        record = FeeRecord(
            timestamp=datetime.now().isoformat(),
            symbol="BTCUSDT",
            side="LONG",
            action="OPEN",
            notional_value=1000.0,
            fee_amount=0.5,
            fee_asset="USDT",
            fee_rate=0.0005,
            order_id="12345",
            income_type="COMMISSION"
        )

        assert record.symbol == "BTCUSDT"
        assert record.fee_amount == 0.5
        assert record.income_type == "COMMISSION"

    def test_fee_stats_calculation(self, tracker):
        """TEST: Fee stats calculated correctly from records"""
        # Add test records
        tracker.fee_records = [
            FeeRecord(
                timestamp=datetime.now().isoformat(),
                symbol="BTCUSDT",
                side="LONG",
                action="OPEN",
                notional_value=1000.0,
                fee_amount=0.5,
                fee_asset="USDT",
                fee_rate=0.0005,
                income_type="COMMISSION"
            ),
            FeeRecord(
                timestamp=datetime.now().isoformat(),
                symbol="ETHUSDT",
                side="SHORT",
                action="CLOSE",
                notional_value=500.0,
                fee_amount=0.25,
                fee_asset="USDT",
                fee_rate=0.0005,
                income_type="COMMISSION"
            ),
        ]

        stats = tracker.get_stats(balance=100.0)

        assert stats.total_commission == 0.75, "Total commission: $0.75"
        assert stats.total_trades == 2, "2 trades"
        assert stats.avg_fee_per_trade == 0.375, "Avg: $0.375"

    def test_fee_breakdown_by_symbol(self, tracker):
        """TEST: Fee breakdown groups correctly by symbol"""
        tracker.fee_records = [
            FeeRecord(
                timestamp=datetime.now().isoformat(),
                symbol="BTCUSDT",
                side="LONG",
                action="OPEN",
                notional_value=1000.0,
                fee_amount=1.0,
                fee_asset="USDT",
                fee_rate=0.0005,
                income_type="COMMISSION"
            ),
            FeeRecord(
                timestamp=datetime.now().isoformat(),
                symbol="BTCUSDT",
                side="LONG",
                action="CLOSE",
                notional_value=1000.0,
                fee_amount=1.0,
                fee_asset="USDT",
                fee_rate=0.0005,
                income_type="COMMISSION"
            ),
            FeeRecord(
                timestamp=datetime.now().isoformat(),
                symbol="ETHUSDT",
                side="SHORT",
                action="OPEN",
                notional_value=500.0,
                fee_amount=0.25,
                fee_asset="USDT",
                fee_rate=0.0005,
                income_type="COMMISSION"
            ),
        ]

        breakdown = tracker.get_fee_breakdown_by_symbol()

        assert breakdown["BTCUSDT"] == 2.0, "BTC total: $2.00"
        assert breakdown["ETHUSDT"] == 0.25, "ETH total: $0.25"

    def test_hourly_fee_rate_alert(self, tracker):
        """
        TEST: Alert triggers when hourly fees exceed threshold

        Threshold: 2% of balance per hour
        """
        balance = 100.0

        # Add fees for this hour totaling $2.50
        now = datetime.now()
        tracker.fee_records = [
            FeeRecord(
                timestamp=now.isoformat(),
                symbol="BTCUSDT",
                side="LONG",
                action="OPEN",
                notional_value=5000.0,
                fee_amount=2.5,
                fee_asset="USDT",
                fee_rate=0.0005,
                income_type="COMMISSION"
            ),
        ]

        alerts = tracker.check_alerts(balance)

        # 2.5% > 2% threshold
        assert len(alerts) > 0, "Should have alert"
        assert "HIGH FEES" in alerts[0]


class TestFeeImpactScenarios:
    """Test real-world fee impact scenarios"""

    def test_death_spiral_small_account(self):
        """
        TEST: "Death spiral" with small account and many positions

        From ACTUAL_ROOT_CAUSE.md:
        - Balance: $2.72
        - 34 positions
        - Margin per position: $0.08
        - Fees kill profitability
        """
        balance = 2.72
        num_positions = 34
        leverage = 20

        margin_per = balance / num_positions
        notional_per = margin_per * leverage

        # Round trip fees per position
        fee_per = notional_per * 0.001  # 0.1% round trip
        total_fees = fee_per * num_positions

        fee_as_pct_balance = (total_fees / balance) * 100

        assert margin_per == pytest.approx(0.08, abs=0.01)
        assert notional_per == pytest.approx(1.6, abs=0.01)
        assert fee_per == pytest.approx(0.0016, abs=0.0001)
        assert total_fees == pytest.approx(0.054, abs=0.01)
        assert fee_as_pct_balance > 1.5, "Fees >1.5% of balance per cycle"

    def test_optimal_position_count(self):
        """
        TEST: Optimal position count for fee efficiency

        Goal: Fees < 0.5% of balance per round trip
        """
        balance = 100.0
        leverage = 20
        target_fee_pct = 0.5  # 0.5% max

        # Work backwards from fee target
        max_total_fees = balance * (target_fee_pct / 100)

        # Fee per position (round trip)
        # fee_per_position = (balance / num_positions) * leverage * 0.001
        # total_fees = fee_per_position * num_positions = balance * leverage * 0.001

        total_fees = balance * leverage * 0.001

        # This is INDEPENDENT of position count!
        # Each position has same % fee regardless of size

        assert total_fees == 2.0, "Fixed $2 fees for $100 balance, 20x leverage"

        # So fee optimization is about:
        # 1. Reducing leverage
        # 2. Increasing profit per trade
        # 3. Reducing trade frequency

    def test_minimum_profit_to_cover_fees(self):
        """
        TEST: Minimum profit percentage needed to cover fees

        Break-even: Gross profit = Fees
        """
        notional = 1000.0
        round_trip_fee_pct = 0.1  # 0.1%

        # Minimum profit to break even
        min_profit_pct = round_trip_fee_pct
        min_profit_usd = notional * (min_profit_pct / 100)

        fees = notional * (round_trip_fee_pct / 100)

        assert min_profit_usd == fees, "Break-even profit equals fees"
        assert min_profit_pct == 0.1, "Need 0.1% profit to break even"

        # Recommendation: 2x fees minimum
        recommended_min_profit_pct = round_trip_fee_pct * 2

        assert recommended_min_profit_pct == 0.2, "Recommend 0.2% minimum profit"


class TestValidationHelpers:
    """Helper functions for test validation"""

    def test_calculate_expected_fees(self):
        """
        TEST: Helper to calculate expected fees for validation
        """
        def calculate_expected_fees(positions, leverage, taker_rate=0.0005):
            """Calculate expected round trip fees"""
            total_fees = 0.0

            for pos in positions:
                margin = pos["margin"]
                notional = margin * leverage
                entry_fee = notional * taker_rate
                exit_fee = notional * taker_rate
                total_fees += (entry_fee + exit_fee)

            return total_fees

        positions = [
            {"margin": 10.0},
            {"margin": 15.0},
            {"margin": 5.0},
        ]

        expected = calculate_expected_fees(positions, leverage=20)

        # Manual calculation:
        # Pos 1: $10 * 20 = $200 notional → $0.10 fees
        # Pos 2: $15 * 20 = $300 notional → $0.15 fees
        # Pos 3: $5 * 20 = $100 notional → $0.05 fees
        # Total: $0.30

        assert expected == 0.3, "Expected fees: $0.30"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
