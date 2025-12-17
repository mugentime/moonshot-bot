"""
Simple Position Monitor Web UI
Separate service - does NOT interfere with main bot
"""
import asyncio
import os
from flask import Flask, Response
from binance import AsyncClient

app = Flask(__name__)

# Read directly from environment variables (standalone - no config import)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

# Configuration
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "10.0"))
TRAILING_STOP_ACTIVATION = 5.0
TRAILING_STOP_DISTANCE = 3.0


def get_indicator(roi_pct: float) -> tuple:
    """Get emoji and color based on ROI"""
    if roi_pct >= TRAILING_STOP_ACTIVATION:
        return "🚀", "#22c55e"
    elif roi_pct >= 2.0:
        return "🟢", "#22c55e"
    elif roi_pct >= 0:
        return "🟡", "#eab308"
    elif roi_pct > -5.0:
        return "🟠", "#f97316"
    elif roi_pct > -STOP_LOSS_PERCENT:
        return "🔴", "#ef4444"
    else:
        return "💀", "#dc2626"


async def get_positions_data():
    """Fetch position data from Binance"""
    client = await AsyncClient.create(
        api_key=BINANCE_API_KEY,
        api_secret=BINANCE_API_SECRET
    )

    try:
        positions = await client.futures_position_information()
        open_positions = [p for p in positions if float(p['positionAmt']) != 0]

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

            if side == 'LONG':
                roi_pct = ((mark - entry) / entry) * 100
            else:
                roi_pct = ((entry - mark) / entry) * 100

            position_data.append({
                'symbol': p['symbol'],
                'side': side,
                'entry': entry,
                'mark': mark,
                'margin': margin,
                'pnl': pnl,
                'roi_pct': roi_pct,
                'leverage': leverage,
                'liq_price': liq_price,
                'sl_dist': STOP_LOSS_PERCENT + roi_pct
            })

        position_data.sort(key=lambda x: x['roi_pct'], reverse=True)

        # Account data
        account = await client.futures_account()
        account_data = {
            'wallet': float(account['totalWalletBalance']),
            'margin': float(account['totalMarginBalance']),
            'available': float(account['availableBalance']),
            'unrealized': float(account['totalUnrealizedProfit'])
        }

        return position_data, account_data
    finally:
        await client.close_connection()


def generate_html(positions, account):
    """Generate HTML dashboard"""
    total_pnl = sum(p['pnl'] for p in positions)
    total_margin = sum(p['margin'] for p in positions)
    winners = sum(1 for p in positions if p['roi_pct'] >= 0)
    losers = len(positions) - winners
    portfolio_roi = (total_pnl / total_margin * 100) if total_margin > 0 else 0

    margin_usage = ((account['margin'] - account['available']) / account['margin'] * 100) if account['margin'] > 0 else 0

    # Build position rows
    rows = ""
    for p in positions:
        emoji, color = get_indicator(p['roi_pct'])
        rows += f"""
        <tr style="border-bottom: 1px solid #333;">
            <td style="padding: 12px;">{emoji} {p['symbol']}</td>
            <td style="padding: 12px;">{p['side']}</td>
            <td style="padding: 12px; color: {color}; font-weight: bold;">{p['roi_pct']:+.2f}%</td>
            <td style="padding: 12px; color: {color};">${p['pnl']:+.2f}</td>
            <td style="padding: 12px;">{p['sl_dist']:+.1f}%</td>
            <td style="padding: 12px;">${p['margin']:.2f}</td>
            <td style="padding: 12px; font-size: 11px;">{p['liq_price']:.6f}</td>
        </tr>
        """

    if not positions:
        rows = '<tr><td colspan="7" style="padding: 40px; text-align: center; color: #888;">No open positions</td></tr>'

    # Health color
    health_color = "#22c55e" if margin_usage < 70 else "#eab308" if margin_usage < 90 else "#ef4444"
    health_text = "HEALTHY" if margin_usage < 70 else "MODERATE" if margin_usage < 90 else "HIGH RISK"

    pnl_color = "#22c55e" if total_pnl >= 0 else "#ef4444"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Position Monitor</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="10">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', system-ui, sans-serif;
                background: #0a0a0a;
                color: #e5e5e5;
                padding: 20px;
            }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                padding-bottom: 15px;
                border-bottom: 1px solid #333;
            }}
            .title {{ font-size: 24px; font-weight: 600; }}
            .refresh {{ color: #666; font-size: 12px; }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 20px;
            }}
            .card {{
                background: #171717;
                border-radius: 8px;
                padding: 16px;
                border: 1px solid #262626;
            }}
            .card-label {{ color: #888; font-size: 12px; margin-bottom: 4px; }}
            .card-value {{ font-size: 24px; font-weight: 600; }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: #171717;
                border-radius: 8px;
                overflow: hidden;
            }}
            th {{
                background: #262626;
                padding: 12px;
                text-align: left;
                font-weight: 500;
                font-size: 13px;
                color: #888;
            }}
            .status {{
                display: inline-block;
                padding: 4px 12px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="title">📊 Position Monitor</div>
                <div class="refresh">Auto-refresh: 10s | SL: {STOP_LOSS_PERCENT}%</div>
            </div>

            <div class="cards">
                <div class="card">
                    <div class="card-label">Positions</div>
                    <div class="card-value">{len(positions)} <span style="font-size: 14px; color: #888;">({winners}W / {losers}L)</span></div>
                </div>
                <div class="card">
                    <div class="card-label">Portfolio PnL</div>
                    <div class="card-value" style="color: {pnl_color};">${total_pnl:+.2f} <span style="font-size: 14px;">({portfolio_roi:+.1f}%)</span></div>
                </div>
                <div class="card">
                    <div class="card-label">Wallet Balance</div>
                    <div class="card-value">${account['wallet']:.2f}</div>
                </div>
                <div class="card">
                    <div class="card-label">Margin Usage</div>
                    <div class="card-value" style="color: {health_color};">{margin_usage:.1f}% <span class="status" style="background: {health_color}20; color: {health_color};">{health_text}</span></div>
                </div>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>ROI</th>
                        <th>PnL</th>
                        <th>SL Dist</th>
                        <th>Margin</th>
                        <th>Liq Price</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>

            <div style="margin-top: 20px; color: #666; font-size: 12px; text-align: center;">
                Available: ${account['available']:.2f} | Margin Balance: ${account['margin']:.2f}
            </div>
        </div>
    </body>
    </html>
    """
    return html


@app.route('/')
def index():
    """Main dashboard"""
    try:
        positions, account = asyncio.run(get_positions_data())
        html = generate_html(positions, account)
        return Response(html, mimetype='text/html')
    except Exception as e:
        return Response(f"<h1>Error</h1><pre>{str(e)}</pre>", mimetype='text/html')


@app.route('/health')
def health():
    """Health check endpoint"""
    return "OK"


if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
