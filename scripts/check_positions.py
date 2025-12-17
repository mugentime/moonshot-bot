"""
Position Monitor - Comprehensive trading dashboard
Shows ROI, risk levels, stop loss distance, and portfolio health
"""
import asyncio
from binance import AsyncClient
import os
import sys

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET

# Configuration (should match main bot settings)
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "10.0"))
TRAILING_STOP_ACTIVATION = 5.0  # Trailing stop activates at 5% profit
TRAILING_STOP_DISTANCE = 3.0    # Trail by 3%


def get_risk_indicator(roi_pct: float) -> str:
    """Get emoji indicator based on ROI"""
    if roi_pct >= TRAILING_STOP_ACTIVATION:
        return "🚀"  # Trailing stop active
    elif roi_pct >= 2.0:
        return "🟢"  # Good profit
    elif roi_pct >= 0:
        return "🟡"  # Small profit / breakeven
    elif roi_pct > -5.0:
        return "🟠"  # Minor loss
    elif roi_pct > -STOP_LOSS_PERCENT:
        return "🔴"  # Approaching SL
    else:
        return "💀"  # Past SL threshold


def calculate_liquidation_price(entry: float, leverage: int, side: str) -> float:
    """Estimate liquidation price (simplified)"""
    # Liquidation occurs around 100% loss of margin
    # For cross margin, this is approximate
    maint_margin_rate = 0.004  # ~0.4% for most pairs
    if side == "LONG":
        return entry * (1 - (1 / leverage) + maint_margin_rate)
    else:
        return entry * (1 + (1 / leverage) - maint_margin_rate)


async def check_positions():
    client = await AsyncClient.create(
        api_key=BINANCE_API_KEY,
        api_secret=BINANCE_API_SECRET
    )

    # Get positions
    positions = await client.futures_position_information()
    open_positions = [p for p in positions if float(p['positionAmt']) != 0]

    print("=" * 80)
    print(f"  POSITION MONITOR | SL: {STOP_LOSS_PERCENT}% | Trailing: {TRAILING_STOP_ACTIVATION}%/{TRAILING_STOP_DISTANCE}%")
    print("=" * 80)

    if open_positions:
        total_pnl = 0
        total_margin = 0
        winners = 0
        losers = 0
        at_risk = 0
        trailing_active = 0

        # Sort by ROI descending (best first)
        position_data = []
        for p in open_positions:
            amt = float(p['positionAmt'])
            entry = float(p['entryPrice'])
            mark = float(p['markPrice'])
            pnl = float(p['unRealizedProfit'])
            leverage = int(p['leverage'])
            liq_price = float(p['liquidationPrice'])

            notional = abs(amt * entry)
            margin = notional / leverage
            side = 'LONG' if amt > 0 else 'SHORT'

            # Calculate ROI %
            if side == 'LONG':
                roi_pct = ((mark - entry) / entry) * 100
            else:
                roi_pct = ((entry - mark) / entry) * 100

            position_data.append({
                'symbol': p['symbol'],
                'side': side,
                'entry': entry,
                'mark': mark,
                'qty': abs(amt),
                'margin': margin,
                'pnl': pnl,
                'roi_pct': roi_pct,
                'leverage': leverage,
                'liq_price': liq_price
            })

        # Sort by ROI
        position_data.sort(key=lambda x: x['roi_pct'], reverse=True)

        print(f"\n{'Symbol':<14} {'Side':<5} {'ROI':>8} {'PnL':>10} {'SL Dist':>8} {'Margin':>8} {'Liq Price':>12}")
        print("-" * 80)

        for p in position_data:
            indicator = get_risk_indicator(p['roi_pct'])
            sl_distance = STOP_LOSS_PERCENT + p['roi_pct']  # Distance to SL trigger

            # Track stats
            total_pnl += p['pnl']
            total_margin += p['margin']
            if p['roi_pct'] >= 0:
                winners += 1
            else:
                losers += 1
            if p['roi_pct'] <= -7.0:  # Within 3% of SL
                at_risk += 1
            if p['roi_pct'] >= TRAILING_STOP_ACTIVATION:
                trailing_active += 1

            # Format liquidation price
            liq_str = f"{p['liq_price']:.6f}" if p['liq_price'] > 0 else "N/A"

            print(f"{indicator} {p['symbol']:<12} {p['side']:<5} {p['roi_pct']:>+7.2f}% ${p['pnl']:>+8.2f} {sl_distance:>+7.1f}% ${p['margin']:>7.2f} {liq_str:>12}")

        print("-" * 80)

        # Portfolio Summary
        portfolio_roi = (total_pnl / total_margin * 100) if total_margin > 0 else 0

        print(f"\n📊 PORTFOLIO SUMMARY")
        print(f"   Positions: {len(open_positions)} ({winners}W / {losers}L)")
        print(f"   Total Margin: ${total_margin:.2f}")
        print(f"   Unrealized PnL: ${total_pnl:+.2f} ({portfolio_roi:+.2f}%)")

        # Risk Assessment
        print(f"\n⚠️  RISK ASSESSMENT")
        if at_risk > 0:
            print(f"   🔴 {at_risk} position(s) within 3% of stop loss!")
        else:
            print(f"   🟢 No positions near stop loss")

        if trailing_active > 0:
            print(f"   🚀 {trailing_active} position(s) have trailing stop active")

    else:
        print('\n   NO OPEN POSITIONS!')

    # Account Balance
    account = await client.futures_account()
    wallet_balance = float(account['totalWalletBalance'])
    margin_balance = float(account['totalMarginBalance'])
    available_balance = float(account['availableBalance'])
    unrealized_pnl = float(account['totalUnrealizedProfit'])

    print(f"\n💰 ACCOUNT")
    print(f"   Wallet: ${wallet_balance:.2f} | Margin: ${margin_balance:.2f} | Available: ${available_balance:.2f}")

    # Health indicator
    if margin_balance > 0:
        margin_usage = ((margin_balance - available_balance) / margin_balance) * 100
        health = "🟢 HEALTHY" if margin_usage < 70 else "🟡 MODERATE" if margin_usage < 90 else "🔴 HIGH RISK"
        print(f"   Margin Usage: {margin_usage:.1f}% | Status: {health}")

    print("=" * 80)

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(check_positions())
