"""Check actual profit from last Global TP"""
import asyncio
from binance import AsyncClient
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    # Get recent income (realized PnL, fees, funding)
    income = await client.futures_income_history(limit=100)
    income = sorted(income, key=lambda x: int(x.get('time', 0)), reverse=True)

    # Find batches of trades (Global TP closes multiple positions in quick succession)
    # Group by minute
    batches = {}
    for i in income:
        ts = int(i.get('time', 0))
        minute = ts // 60000
        if minute not in batches:
            batches[minute] = []
        batches[minute].append(i)

    # Find most recent batch with 3+ REALIZED_PNL trades with DIFFERENT symbols (Global TP)
    recent_tp = None
    for minute in sorted(batches.keys(), reverse=True):
        pnl_trades = [t for t in batches[minute] if t.get('incomeType') == 'REALIZED_PNL']
        unique_symbols = set(t.get('symbol') for t in pnl_trades)
        if len(unique_symbols) >= 3:  # Multiple different symbols = Global TP
            recent_tp = (minute, batches[minute])
            break

    # If no multi-symbol batch found, show all recent batches for analysis
    if not recent_tp:
        print("Looking for Global TP batches (3+ different symbols closed)...\n")
        for minute in sorted(batches.keys(), reverse=True)[:10]:
            pnl_trades = [t for t in batches[minute] if t.get('incomeType') == 'REALIZED_PNL']
            unique_symbols = set(t.get('symbol') for t in pnl_trades)
            ts = datetime.fromtimestamp(minute * 60)
            print(f"  {ts}: {len(pnl_trades)} trades, {len(unique_symbols)} symbols: {list(unique_symbols)[:5]}")

    if not recent_tp:
        print("No recent Global TP found (batch of 2+ position closes)")
        await client.close_connection()
        return

    minute, trades = recent_tp
    ts = datetime.fromtimestamp(minute * 60)

    print("=" * 70)
    print(f"  LAST GLOBAL TP: {ts.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    # Separate by type
    realized_pnl = [t for t in trades if t.get('incomeType') == 'REALIZED_PNL']
    fees = [t for t in trades if t.get('incomeType') == 'COMMISSION']
    funding = [t for t in trades if t.get('incomeType') == 'FUNDING_FEE']

    # Calculate totals
    total_pnl = sum(float(t.get('income', 0)) for t in realized_pnl)
    total_fees = sum(float(t.get('income', 0)) for t in fees)
    total_funding = sum(float(t.get('income', 0)) for t in funding)

    print(f"\nPositions Closed: {len(realized_pnl)}")
    print("-" * 70)

    winners = 0
    losers = 0
    for t in realized_pnl:
        sym = t.get('symbol', 'N/A')
        pnl = float(t.get('income', 0))
        if pnl >= 0:
            winners += 1
            status = "WIN"
        else:
            losers += 1
            status = "LOSS"
        print(f"  {sym:15} ${pnl:+.4f}  {status}")

    print("-" * 70)
    print(f"\nGross PnL:         ${total_pnl:+.4f}")
    print(f"Fees:              ${total_fees:+.4f}")
    print(f"Funding:           ${total_funding:+.4f}")

    net_profit = total_pnl + total_fees + total_funding
    print(f"\nNET PROFIT:        ${net_profit:+.4f}")
    print(f"Winners/Losers:    {winners}W / {losers}L")

    # Calculate balance before/after using income since TP
    income_since_tp = sum(
        float(i.get('income', 0))
        for i in income
        if int(i.get('time', 0)) // 60000 > minute
    )

    acc = await client.futures_account()
    current_wallet = float(acc['totalWalletBalance'])
    current_margin = float(acc['totalMarginBalance'])

    balance_after_tp = current_wallet - income_since_tp
    balance_before_tp = balance_after_tp - net_profit

    print(f"\nBalance BEFORE TP: ${balance_before_tp:.4f}")
    print(f"Balance AFTER TP:  ${balance_after_tp:.4f}")
    print(f"NET CHANGE:        ${net_profit:+.4f}")

    # Is 1% TP profitable?
    print("\n" + "=" * 70)
    if net_profit > 0:
        print(f"  1% TP WAS PROFITABLE: +${net_profit:.4f}")
    else:
        print(f"  1% TP WAS NOT PROFITABLE: ${net_profit:.4f}")
    print("=" * 70)

    print(f"\nCurrent Wallet:  ${current_wallet:.4f}")
    print(f"Current Equity:  ${current_margin:.4f}")

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
