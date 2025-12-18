"""
Fee Impact Calculator
Calculates and simulates fee impact on profitability
"""
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class TradingScenario:
    """Trading scenario for fee impact analysis"""
    name: str
    wallet_balance: float
    num_positions: int
    leverage: int
    avg_profit_pct: float  # Average profit % per position
    trade_frequency_per_day: int
    days: int = 30


class FeeImpactCalculator:
    """Calculate fee impact on trading profitability"""

    def __init__(self, taker_fee_rate: float = 0.0005, maker_fee_rate: float = 0.0002):
        self.taker_fee_rate = taker_fee_rate
        self.maker_fee_rate = maker_fee_rate

    def calculate_single_trade_fees(self, notional: float, use_maker: bool = False) -> float:
        """
        Calculate fees for a single round trip trade

        Args:
            notional: Position notional value
            use_maker: If True, use maker fee; else taker
        """
        fee_rate = self.maker_fee_rate if use_maker else self.taker_fee_rate

        entry_fee = notional * fee_rate
        exit_fee = notional * fee_rate

        return entry_fee + exit_fee

    def analyze_scenario(self, scenario: TradingScenario) -> Dict:
        """
        Analyze a trading scenario for fee impact

        Returns comprehensive analysis including:
        - Total fees
        - Gross profit
        - Net profit
        - Fee % of profits
        - Fee % of balance
        """
        # Position sizing
        margin_per_position = scenario.wallet_balance / scenario.num_positions
        notional_per_position = margin_per_position * scenario.leverage

        # Single position profit
        gross_profit_per_position = notional_per_position * (scenario.avg_profit_pct / 100)

        # Single position fees (taker)
        fees_per_position = self.calculate_single_trade_fees(notional_per_position, use_maker=False)

        # Net profit per position
        net_profit_per_position = gross_profit_per_position - fees_per_position

        # Total trades over period
        total_trades = scenario.trade_frequency_per_day * scenario.days
        total_positions_traded = total_trades * scenario.num_positions

        # Cumulative metrics
        total_gross_profit = gross_profit_per_position * total_positions_traded
        total_fees = fees_per_position * total_positions_traded
        total_net_profit = total_gross_profit - total_fees

        # Percentages
        fee_pct_of_gross = (total_fees / total_gross_profit * 100) if total_gross_profit > 0 else 0
        fee_pct_of_balance = (total_fees / scenario.wallet_balance * 100)
        net_roi = (total_net_profit / scenario.wallet_balance * 100)

        return {
            "scenario": scenario.name,
            "config": {
                "wallet_balance": scenario.wallet_balance,
                "num_positions": scenario.num_positions,
                "leverage": scenario.leverage,
                "margin_per_position": margin_per_position,
                "notional_per_position": notional_per_position,
                "avg_profit_pct": scenario.avg_profit_pct,
                "trade_frequency": scenario.trade_frequency_per_day,
                "days": scenario.days
            },
            "per_trade": {
                "gross_profit": gross_profit_per_position,
                "fees": fees_per_position,
                "net_profit": net_profit_per_position,
                "net_profit_pct": (net_profit_per_position / notional_per_position * 100)
            },
            "cumulative": {
                "total_trades": total_trades,
                "total_positions": total_positions_traded,
                "gross_profit": total_gross_profit,
                "total_fees": total_fees,
                "net_profit": total_net_profit,
                "fee_pct_of_gross": fee_pct_of_gross,
                "fee_pct_of_balance": fee_pct_of_balance,
                "net_roi": net_roi
            },
            "verdict": {
                "profitable": total_net_profit > 0,
                "fees_sustainable": fee_pct_of_gross < 50,
                "recommendation": self._get_recommendation(total_net_profit, fee_pct_of_gross)
            }
        }

    def _get_recommendation(self, net_profit: float, fee_pct: float) -> str:
        """Get recommendation based on analysis"""
        if net_profit <= 0:
            return "STOP: Strategy is unprofitable. Fees exceed profits."
        elif fee_pct > 75:
            return "CRITICAL: Fees consume >75% of profits. Reduce trade frequency or increase profit target."
        elif fee_pct > 50:
            return "WARNING: Fees consume >50% of profits. Consider optimization."
        elif fee_pct > 25:
            return "CAUTION: Fees are significant (>25%). Monitor carefully."
        else:
            return "OK: Fees are reasonable (<25% of profits)."

    def compare_scenarios(self, scenarios: List[TradingScenario]):
        """Compare multiple scenarios side-by-side"""
        print("=" * 120)
        print("FEE IMPACT ANALYSIS - Scenario Comparison")
        print("=" * 120)

        results = []
        for scenario in scenarios:
            result = self.analyze_scenario(scenario)
            results.append(result)
            self.print_scenario(result)

        # Print comparison summary
        self.print_comparison_summary(results)

    def print_scenario(self, result: Dict):
        """Print analysis result for a scenario"""
        print(f"\n{'=' * 120}")
        print(f"SCENARIO: {result['scenario']}")
        print(f"{'=' * 120}")

        cfg = result['config']
        print(f"\nConfiguration:")
        print(f"  Wallet Balance:    ${cfg['wallet_balance']:.2f}")
        print(f"  Positions:         {cfg['num_positions']}")
        print(f"  Leverage:          {cfg['leverage']}x")
        print(f"  Margin/Position:   ${cfg['margin_per_position']:.2f}")
        print(f"  Notional/Position: ${cfg['notional_per_position']:.2f}")
        print(f"  Avg Profit:        {cfg['avg_profit_pct']}% per trade")
        print(f"  Trade Frequency:   {cfg['trade_frequency']}x per day")
        print(f"  Period:            {cfg['days']} days")

        per_trade = result['per_trade']
        print(f"\nPer Position Trade:")
        print(f"  Gross Profit:      ${per_trade['gross_profit']:.4f}")
        print(f"  Fees:              ${per_trade['fees']:.4f}")
        print(f"  Net Profit:        ${per_trade['net_profit']:.4f} ({per_trade['net_profit_pct']:.2f}%)")

        cum = result['cumulative']
        print(f"\nCumulative ({cfg['days']} days):")
        print(f"  Total Trades:      {cum['total_trades']}")
        print(f"  Total Positions:   {cum['total_positions']}")
        print(f"  Gross Profit:      ${cum['gross_profit']:.2f}")
        print(f"  Total Fees:        ${cum['total_fees']:.2f}")
        print(f"  Net Profit:        ${cum['net_profit']:.2f}")
        print(f"  Fees % of Gross:   {cum['fee_pct_of_gross']:.1f}%")
        print(f"  Fees % of Balance: {cum['fee_pct_of_balance']:.1f}%")
        print(f"  Net ROI:           {cum['net_roi']:.1f}%")

        verdict = result['verdict']
        status = "✅" if verdict['profitable'] else "❌"
        print(f"\n{status} VERDICT: {verdict['recommendation']}")

    def print_comparison_summary(self, results: List[Dict]):
        """Print summary comparison table"""
        print(f"\n{'=' * 120}")
        print("COMPARISON SUMMARY")
        print(f"{'=' * 120}")

        print(f"\n{'Scenario':<30} {'Positions':>10} {'Trades/Day':>12} {'Net ROI':>10} {'Fees %':>10} {'Status':>10}")
        print("-" * 120)

        for result in results:
            scenario = result['scenario'][:28]
            positions = result['config']['num_positions']
            frequency = result['config']['trade_frequency']
            roi = result['cumulative']['net_roi']
            fees_pct = result['cumulative']['fee_pct_of_gross']
            status = "✅" if result['verdict']['profitable'] else "❌"

            print(f"{scenario:<30} {positions:>10} {frequency:>12} {roi:>9.1f}% {fees_pct:>9.1f}% {status:>10}")

        print("=" * 120)


def run_fee_impact_analysis():
    """Run comprehensive fee impact analysis"""
    calculator = FeeImpactCalculator()

    # Define scenarios to compare
    scenarios = [
        # Scenario 1: Current problematic setup
        TradingScenario(
            name="Current (Broken)",
            wallet_balance=2.72,
            num_positions=34,
            leverage=20,
            avg_profit_pct=0.5,  # 0.5% per trade
            trade_frequency_per_day=10,  # 10 TP triggers per day
            days=30
        ),

        # Scenario 2: Reduced positions
        TradingScenario(
            name="Fixed - 5 Positions",
            wallet_balance=2.72,
            num_positions=5,
            leverage=20,
            avg_profit_pct=1.0,  # Higher profit target
            trade_frequency_per_day=3,  # Less frequent
            days=30
        ),

        # Scenario 3: Larger balance
        TradingScenario(
            name="Larger Balance - $50",
            wallet_balance=50.0,
            num_positions=10,
            leverage=15,
            avg_profit_pct=1.5,
            trade_frequency_per_day=2,
            days=30
        ),

        # Scenario 4: Optimal setup
        TradingScenario(
            name="Optimal - $100",
            wallet_balance=100.0,
            num_positions=5,
            leverage=10,
            avg_profit_pct=2.0,
            trade_frequency_per_day=1,
            days=30
        ),

        # Scenario 5: High frequency but higher profits
        TradingScenario(
            name="High Frequency, High Profit",
            wallet_balance=100.0,
            num_positions=3,
            leverage=20,
            avg_profit_pct=3.0,  # 3% per trade
            trade_frequency_per_day=5,
            days=30
        ),
    ]

    calculator.compare_scenarios(scenarios)


if __name__ == "__main__":
    run_fee_impact_analysis()
