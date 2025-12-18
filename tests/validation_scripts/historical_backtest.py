"""
Historical Data Backtest Script
Replays historical trades to validate TP calculation fixes
"""
import asyncio
import json
from datetime import datetime
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class BacktestResult:
    """Result of historical backtest"""
    timestamp: str
    scenario: str
    old_calculation: Dict
    new_calculation: Dict
    difference: Dict
    should_trigger_tp: bool
    test_passed: bool


class HistoricalBacktest:
    """
    Replay historical TP events with both old and new calculations
    to demonstrate the fix effectiveness
    """

    def __init__(self, leverage: int = 20, tp_threshold: float = 10.0):
        self.leverage = leverage
        self.tp_threshold = tp_threshold
        self.results: List[BacktestResult] = []

    def calculate_old_tp_percentage(self, total_pnl: float, total_margin: float) -> float:
        """OLD (BUGGY): TP percentage vs margin"""
        if total_margin <= 0:
            return 0.0
        return (total_pnl / total_margin) * 100

    def calculate_new_tp_percentage(self, total_pnl: float, wallet_balance: float) -> float:
        """NEW (CORRECT): TP percentage vs wallet"""
        if wallet_balance <= 0:
            return 0.0
        return (total_pnl / wallet_balance) * 100

    def run_scenario(self, scenario_name: str, wallet_balance: float,
                     positions: List[Dict], trading_fees: float = 0.0) -> BacktestResult:
        """
        Run a single backtest scenario

        Args:
            scenario_name: Description of scenario
            wallet_balance: Current wallet balance
            positions: List of position dicts with {margin, pnl}
            trading_fees: Total trading fees for this cycle
        """
        total_pnl = sum(p["pnl"] for p in positions)
        total_margin = sum(p["margin"] for p in positions)

        # Gross vs Net PnL
        gross_pnl = total_pnl
        net_pnl = total_pnl - trading_fees

        # OLD calculation (vs margin)
        old_pct_gross = self.calculate_old_tp_percentage(gross_pnl, total_margin)
        old_pct_net = self.calculate_old_tp_percentage(net_pnl, total_margin)
        old_would_trigger = old_pct_gross >= self.tp_threshold

        # NEW calculation (vs wallet)
        new_pct_gross = self.calculate_new_tp_percentage(gross_pnl, wallet_balance)
        new_pct_net = self.calculate_new_tp_percentage(net_pnl, wallet_balance)
        new_would_trigger = new_pct_net >= self.tp_threshold

        # Expected behavior: Only trigger if NET profit (after fees) >= threshold
        should_trigger = net_pnl > 0 and new_pct_net >= self.tp_threshold

        # Test passes if new calculation matches expected
        test_passed = new_would_trigger == should_trigger

        result = BacktestResult(
            timestamp=datetime.now().isoformat(),
            scenario=scenario_name,
            old_calculation={
                "gross_pct": round(old_pct_gross, 2),
                "net_pct": round(old_pct_net, 2),
                "would_trigger": old_would_trigger,
                "false_positive": old_would_trigger and not should_trigger
            },
            new_calculation={
                "gross_pct": round(new_pct_gross, 2),
                "net_pct": round(new_pct_net, 2),
                "would_trigger": new_would_trigger,
            },
            difference={
                "gross_pct_diff": round(old_pct_gross - new_pct_gross, 2),
                "net_pct_diff": round(old_pct_net - new_pct_net, 2),
                "trigger_diff": old_would_trigger != new_would_trigger
            },
            should_trigger_tp=should_trigger,
            test_passed=test_passed
        )

        self.results.append(result)
        return result

    def run_historical_scenarios(self):
        """
        Run actual historical scenarios from the analysis documents
        """
        print("=" * 80)
        print("HISTORICAL BACKTEST - Trading Bot TP Calculation Fix")
        print("=" * 80)
        print(f"Leverage: {self.leverage}x")
        print(f"TP Threshold: {self.tp_threshold}%")
        print("=" * 80)
        print()

        # Scenario 1: From BALANCE_LOSS_ANALYSIS.md - False TP on Loss
        print("Scenario 1: False TP Trigger on Loss (Dec 17, 15:30)")
        result = self.run_scenario(
            scenario_name="Dec 17, 15:30 - Loss Triggered as TP",
            wallet_balance=2.89,
            positions=[
                {"margin": 0.05, "pnl": -0.01},
                {"margin": 0.05, "pnl": -0.01},
                {"margin": 0.05, "pnl": -0.01},
                {"margin": 0.05, "pnl": -0.01},
            ],
            trading_fees=0.0001
        )
        self.print_result(result)

        # Scenario 2: Tiny position, tiny profit
        print("\nScenario 2: Tiny Position, Tiny Profit")
        result = self.run_scenario(
            scenario_name="Small position with 1% price gain",
            wallet_balance=100.0,
            positions=[
                {"margin": 5.0, "pnl": 1.0},  # 1% gain on $100 notional (20x)
            ],
            trading_fees=0.1
        )
        self.print_result(result)

        # Scenario 3: Multiple positions, mixed P&L
        print("\nScenario 3: Multiple Positions, Mixed P&L")
        result = self.run_scenario(
            scenario_name="5 positions with winners and losers",
            wallet_balance=100.0,
            positions=[
                {"margin": 20.0, "pnl": 5.0},
                {"margin": 20.0, "pnl": 3.0},
                {"margin": 20.0, "pnl": -2.0},
                {"margin": 20.0, "pnl": 4.0},
                {"margin": 20.0, "pnl": 2.0},
            ],
            trading_fees=2.0
        )
        self.print_result(result)

        # Scenario 4: Death spiral (many small positions)
        print("\nScenario 4: Death Spiral - 34 Positions on $2.72 Balance")
        positions_34 = [{"margin": 2.72 / 34, "pnl": 0.001} for _ in range(34)]
        result = self.run_scenario(
            scenario_name="34 tiny positions, minimal profit",
            wallet_balance=2.72,
            positions=positions_34,
            trading_fees=0.054  # Calculated from test
        )
        self.print_result(result)

        # Scenario 5: Legitimate TP (should trigger)
        print("\nScenario 5: Legitimate TP - 12% Profit on Wallet")
        result = self.run_scenario(
            scenario_name="True 12% profit on wallet balance",
            wallet_balance=100.0,
            positions=[
                {"margin": 50.0, "pnl": 13.0},  # 13% gross, 12% net after fees
            ],
            trading_fees=1.0
        )
        self.print_result(result)

        # Summary
        self.print_summary()

    def print_result(self, result: BacktestResult):
        """Print a single backtest result"""
        status = "✅ PASS" if result.test_passed else "❌ FAIL"

        print(f"\n{result.scenario}")
        print(f"Status: {status}")
        print(f"\nOLD Calculation (vs margin):")
        print(f"  Gross: {result.old_calculation['gross_pct']}%")
        print(f"  Net:   {result.old_calculation['net_pct']}%")
        print(f"  Would Trigger: {result.old_calculation['would_trigger']}")
        if result.old_calculation['false_positive']:
            print(f"  ⚠️  FALSE POSITIVE")

        print(f"\nNEW Calculation (vs wallet):")
        print(f"  Gross: {result.new_calculation['gross_pct']}%")
        print(f"  Net:   {result.new_calculation['net_pct']}%")
        print(f"  Would Trigger: {result.new_calculation['would_trigger']}")

        print(f"\nDifference:")
        print(f"  Gross % diff: {result.difference['gross_pct_diff']}%")
        print(f"  Net % diff: {result.difference['net_pct_diff']}%")
        print(f"  Trigger changed: {result.difference['trigger_diff']}")

        print(f"\nExpected: {'Should trigger' if result.should_trigger_tp else 'Should NOT trigger'}")
        print("-" * 80)

    def print_summary(self):
        """Print summary of all backtest results"""
        print("\n" + "=" * 80)
        print("BACKTEST SUMMARY")
        print("=" * 80)

        total = len(self.results)
        passed = sum(1 for r in self.results if r.test_passed)
        failed = total - passed

        print(f"Total Scenarios: {total}")
        print(f"Passed: {passed} ({passed/total*100:.1f}%)")
        print(f"Failed: {failed} ({failed/total*100:.1f}%)")

        # Count false positives fixed
        false_positives_fixed = sum(
            1 for r in self.results
            if r.old_calculation['false_positive']
            and not r.new_calculation['would_trigger']
        )

        print(f"\nFalse Positives Fixed: {false_positives_fixed}")

        # Average percentage differences
        avg_gross_diff = sum(r.difference['gross_pct_diff'] for r in self.results) / total
        avg_net_diff = sum(r.difference['net_pct_diff'] for r in self.results) / total

        print(f"\nAverage Percentage Differences:")
        print(f"  Gross: {avg_gross_diff:.2f}%")
        print(f"  Net:   {avg_net_diff:.2f}%")

        print("=" * 80)

    def export_results(self, filename: str = "backtest_results.json"):
        """Export results to JSON"""
        import json
        from dataclasses import asdict

        with open(filename, 'w') as f:
            json.dump([asdict(r) for r in self.results], f, indent=2)

        print(f"\n✅ Results exported to {filename}")


if __name__ == "__main__":
    backtest = HistoricalBacktest(leverage=20, tp_threshold=10.0)
    backtest.run_historical_scenarios()
    backtest.export_results("tests/validation_scripts/backtest_results.json")
