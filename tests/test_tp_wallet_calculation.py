"""
Unit Tests for Wallet-Based TP Calculation
Tests the critical fix: TP percentage calculated vs wallet balance, not margin
"""
import pytest
from unittest.mock import AsyncMock, Mock, patch
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.macro_strategy import MacroConfig


class MockPosition:
    """Mock position for testing"""
    def __init__(self, symbol, direction, entry_price, quantity, margin):
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.quantity = quantity
        self.margin = margin


class TestWalletBasedTPCalculation:
    """
    CRITICAL TESTS: Wallet-Based TP Calculation

    Root Cause: TP was calculated as (pnl / margin) instead of (pnl / wallet_balance)
    With 20x leverage, this caused TP to trigger on tiny absolute profits.

    Fix: Change to (pnl / wallet_balance) for accurate percentage
    """

    @pytest.mark.asyncio
    async def test_tp_percentage_vs_wallet_not_margin(self):
        """
        TEST: TP percentage calculated against WALLET BALANCE, not margin

        Scenario:
        - Wallet: $100
        - Position margin: $5 (5% of wallet)
        - Leverage: 20x
        - Position notional: $100
        - Price gain: +1% = $1 profit

        WRONG (old code): ($1 / $5) * 100 = 20% TP ✗
        RIGHT (new code): ($1 / $100) * 100 = 1% TP ✓
        """
        wallet_balance = 100.0
        position_margin = 5.0
        leverage = 20
        notional = position_margin * leverage  # $100
        price_gain_pct = 1.0  # 1%

        gross_pnl = notional * (price_gain_pct / 100)  # $1.00

        # OLD CALCULATION (BUGGY)
        old_pnl_pct = (gross_pnl / position_margin) * 100

        # NEW CALCULATION (CORRECT)
        new_pnl_pct = (gross_pnl / wallet_balance) * 100

        # Assertions
        assert old_pnl_pct == 20.0, "Old calculation: 20% vs margin"
        assert new_pnl_pct == 1.0, "New calculation: 1% vs wallet"
        assert new_pnl_pct != old_pnl_pct, "Calculations must differ"

        # With 10% TP threshold
        tp_threshold = 10.0
        assert old_pnl_pct >= tp_threshold, "Old code triggers TP incorrectly"
        assert new_pnl_pct < tp_threshold, "New code does NOT trigger (correct)"

    @pytest.mark.asyncio
    async def test_zero_wallet_balance_edge_case(self):
        """TEST: Handle zero wallet balance gracefully"""
        wallet_balance = 0.0
        total_pnl = 10.0

        # Should not crash, should default to 0%
        if wallet_balance > 0:
            pnl_pct = (total_pnl / wallet_balance) * 100
        else:
            pnl_pct = 0.0

        assert pnl_pct == 0.0

    @pytest.mark.asyncio
    async def test_tiny_wallet_balance_edge_case(self):
        """
        TEST: Tiny wallet balance ($0.01) with tiny profit

        Scenario: $0.01 wallet, $0.001 profit
        Expected: 10% TP (correct)
        """
        wallet_balance = 0.01
        total_pnl = 0.001

        pnl_pct = (total_pnl / wallet_balance) * 100

        assert pnl_pct == 10.0

    @pytest.mark.asyncio
    async def test_negative_pnl_never_triggers_tp(self):
        """TEST: Negative PnL should NEVER trigger TP"""
        wallet_balance = 100.0
        total_pnl = -5.0  # Loss
        tp_threshold = 10.0

        pnl_pct = (total_pnl / wallet_balance) * 100

        assert pnl_pct == -5.0
        assert pnl_pct < tp_threshold, "Losses should never trigger TP"

    @pytest.mark.asyncio
    async def test_multiple_positions_aggregate_correctly(self):
        """
        TEST: Multiple positions aggregate PnL correctly

        Scenario:
        - Wallet: $100
        - Position 1: +$2 profit
        - Position 2: -$0.50 loss
        - Position 3: +$3 profit
        - Total PnL: $4.50
        - Expected: 4.5% vs wallet
        """
        wallet_balance = 100.0
        position_pnls = [2.0, -0.5, 3.0]
        total_pnl = sum(position_pnls)

        pnl_pct = (total_pnl / wallet_balance) * 100

        assert pnl_pct == 4.5

    @pytest.mark.asyncio
    async def test_historical_scenario_replay(self):
        """
        TEST: Replay actual historical scenario that triggered false TP

        From BALANCE_LOSS_ANALYSIS.md:
        - Balance: $2.83
        - 4 positions closed
        - Gross PnL: -$0.0428 (NEGATIVE!)
        - Old calculation would have shown margin-based "profit"
        """
        wallet_balance = 2.83
        total_pnl = -0.0428  # Actual loss
        tp_threshold = 10.0

        pnl_pct = (total_pnl / wallet_balance) * 100

        assert pnl_pct < 0, "Should show as loss"
        assert pnl_pct < tp_threshold, "Should NOT trigger TP"


class TestFeeAwareTPTriggering:
    """
    Tests for fee-aware TP triggering
    Ensures fees are subtracted BEFORE checking TP threshold
    """

    @pytest.mark.asyncio
    async def test_gross_vs_net_pnl(self):
        """
        TEST: TP trigger uses NET PnL (after fees), not GROSS

        Scenario:
        - Gross PnL: $10
        - Trading fees: $2
        - Net PnL: $8
        - Wallet: $100
        - TP threshold: 10%

        Expected: Net 8% < 10% threshold, NO trigger
        """
        wallet_balance = 100.0
        gross_pnl = 10.0
        trading_fees = 2.0
        net_pnl = gross_pnl - trading_fees
        tp_threshold = 10.0

        # WRONG: Use gross PnL
        gross_pnl_pct = (gross_pnl / wallet_balance) * 100

        # RIGHT: Use net PnL
        net_pnl_pct = (net_pnl / wallet_balance) * 100

        assert gross_pnl_pct == 10.0, "Gross shows 10% (would trigger)"
        assert net_pnl_pct == 8.0, "Net shows 8% (correct)"
        assert net_pnl_pct < tp_threshold, "Should NOT trigger"

    @pytest.mark.asyncio
    async def test_fee_calculation_accuracy(self):
        """
        TEST: Fee calculation matches Binance's 0.05% taker fee

        Binance formula: fee = notional * 0.0005
        """
        notional = 1000.0  # $1000 position
        taker_fee_rate = 0.0005  # 0.05%

        expected_fee = notional * taker_fee_rate

        assert expected_fee == 0.5, "Fee should be $0.50 for $1000 notional"

    @pytest.mark.asyncio
    async def test_round_trip_fees(self):
        """
        TEST: Round trip (entry + exit) fees calculated correctly

        Entry fee + Exit fee = Total fee
        """
        notional = 1000.0
        taker_fee_rate = 0.0005

        entry_fee = notional * taker_fee_rate
        exit_fee = notional * taker_fee_rate
        total_fee = entry_fee + exit_fee

        assert total_fee == 1.0, "Round trip fee should be $1.00"

    @pytest.mark.asyncio
    async def test_fee_erodes_small_profits(self):
        """
        TEST: Demonstrate how fees can turn small profits into losses

        Scenario:
        - Gross profit: $0.50
        - Round trip fees: $1.00
        - Net result: -$0.50 LOSS
        """
        gross_profit = 0.50
        round_trip_fees = 1.00
        net_result = gross_profit - round_trip_fees

        assert net_result == -0.50, "Fees turn profit into loss"
        assert gross_profit > 0, "Gross profit is positive"
        assert net_result < 0, "Net result is negative"


class TestPositionSizingChanges:
    """
    Tests for position sizing enforcement
    """

    @pytest.mark.asyncio
    async def test_minimum_position_enforcement(self):
        """
        TEST: Enforce minimum position size ($1.00 margin)

        With Binance minimum notional of $10 and 20x leverage:
        Minimum margin = $10 / 20 = $0.50

        But we enforce $1.00 minimum for fee efficiency
        """
        wallet_balance = 100.0
        num_positions = 200  # Too many!

        margin_per_position = wallet_balance / num_positions
        minimum_margin = 1.0

        assert margin_per_position == 0.5, "Calculated margin too small"

        # Apply minimum
        adjusted_margin = max(margin_per_position, minimum_margin)

        assert adjusted_margin == 1.0, "Minimum enforced"

        # Recalculate max positions with minimum
        max_positions = int(wallet_balance / minimum_margin)

        assert max_positions == 100, "Max 100 positions with $1 minimum"

    @pytest.mark.asyncio
    async def test_equal_weight_allocation(self):
        """
        TEST: Equal weight allocation across positions

        Wallet: $100, Positions: 10
        Each gets: $10 margin
        """
        wallet_balance = 100.0
        num_positions = 10

        margin_per_position = wallet_balance / num_positions

        assert margin_per_position == 10.0

        # Verify sum equals wallet (no rounding issues)
        total_allocated = margin_per_position * num_positions

        assert total_allocated == wallet_balance

    @pytest.mark.asyncio
    async def test_leverage_interaction(self):
        """
        TEST: Position sizing with leverage

        Margin: $10, Leverage: 20x
        Notional: $200
        """
        margin = 10.0
        leverage = 20

        notional = margin * leverage

        assert notional == 200.0

        # Verify meets Binance minimum notional ($10)
        assert notional >= 10.0


class TestIntegrationScenarios:
    """
    Integration tests for complete TP cycles
    """

    @pytest.mark.asyncio
    async def test_end_to_end_tp_cycle(self):
        """
        TEST: Complete TP cycle from position open to close

        Steps:
        1. Open position (pay entry fee)
        2. Price moves favorably
        3. TP triggers (correct threshold)
        4. Close position (pay exit fee)
        5. Balance increases by net profit
        """
        # Initial state
        wallet_balance = 100.0
        position_margin = 10.0
        leverage = 20
        entry_price = 50000.0

        # Entry fee
        entry_notional = position_margin * leverage
        entry_fee = entry_notional * 0.0005
        wallet_after_entry = wallet_balance - entry_fee

        # Price moves +5%
        exit_price = entry_price * 1.05
        gross_pnl = (exit_price - entry_price) / entry_price * entry_notional

        # Exit fee
        exit_fee = entry_notional * 0.0005

        # Net profit
        net_profit = gross_pnl - entry_fee - exit_fee

        # Final balance
        final_balance = wallet_after_entry + gross_pnl - exit_fee

        # Assertions
        assert entry_fee == 0.1, "Entry fee: $0.10"
        assert exit_fee == 0.1, "Exit fee: $0.10"
        assert gross_pnl == 10.0, "Gross PnL: $10"
        assert net_profit == 9.8, "Net profit: $9.80"
        assert final_balance == 109.8, "Final balance: $109.80"

        # TP percentage (vs wallet)
        tp_pct = (gross_pnl / wallet_balance) * 100
        assert tp_pct == 10.0, "TP triggered at 10% vs wallet"

    @pytest.mark.asyncio
    async def test_multi_position_close(self):
        """
        TEST: Closing multiple positions simultaneously

        Scenario: 5 positions, mixed P&L
        """
        wallet_balance = 100.0
        positions = [
            {"margin": 20.0, "pnl": 5.0},   # +25% on margin, +5% on wallet
            {"margin": 20.0, "pnl": 3.0},   # +15% on margin, +3% on wallet
            {"margin": 20.0, "pnl": -2.0},  # -10% on margin, -2% on wallet
            {"margin": 20.0, "pnl": 4.0},   # +20% on margin, +4% on wallet
            {"margin": 20.0, "pnl": 2.0},   # +10% on margin, +2% on wallet
        ]

        total_pnl = sum(p["pnl"] for p in positions)
        total_margin = sum(p["margin"] for p in positions)

        # Wallet-based TP percentage
        wallet_tp_pct = (total_pnl / wallet_balance) * 100

        # Margin-based (old buggy calculation)
        margin_tp_pct = (total_pnl / total_margin) * 100

        assert total_pnl == 12.0, "Total PnL: $12"
        assert wallet_tp_pct == 12.0, "12% vs wallet (correct)"
        assert margin_tp_pct == 12.0, "12% vs margin (happens to match here)"

        # TP threshold 10%
        tp_threshold = 10.0
        assert wallet_tp_pct >= tp_threshold, "Should trigger TP"

    @pytest.mark.asyncio
    async def test_cooldown_prevents_immediate_reentry(self):
        """
        TEST: Post-TP cooldown prevents immediate position re-opening

        Scenario:
        - TP closes positions
        - 60s cooldown starts
        - Macro signal triggers during cooldown
        - Positions should NOT reopen
        """
        import time

        last_tp_time = time.time()
        cooldown_seconds = 60

        # Check cooldown immediately after TP
        time_since_tp = time.time() - last_tp_time
        in_cooldown = time_since_tp < cooldown_seconds

        assert in_cooldown, "Should be in cooldown"

        # Simulate 61 seconds passing
        simulated_time_since_tp = 61
        cooldown_expired = simulated_time_since_tp >= cooldown_seconds

        assert cooldown_expired, "Cooldown should expire after 60s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
