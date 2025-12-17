"""
VOLATILITY ANALYZER - Extract useful data from testnet
Tracks velocity alerts and analyzes which pairs have ideal volatility.

Usage:
    python scripts/volatility_analyzer.py [testnet_url]

Example:
    python scripts/volatility_analyzer.py https://moonshot-bot-testnet.up.railway.app
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance import AsyncClient
from config import BINANCE_API_KEY, BINANCE_API_SECRET

DATA_FILE = "data/volatility_data.json"


@dataclass
class VolatilityRecord:
    """Record of a pair's volatility at a point in time"""
    symbol: str
    timestamp: str
    velocity_1m: float
    velocity_5m: float
    velocity_15m: float
    price: float
    direction: str  # Based on 5m velocity


class VolatilityTracker:
    """Tracks and analyzes volatility patterns"""

    def __init__(self):
        self.records: List[Dict] = []
        self.alerts: List[Dict] = []
        self.pair_stats: Dict[str, Dict] = defaultdict(lambda: {
            'total_samples': 0,
            'avg_velocity_1m': 0,
            'avg_velocity_5m': 0,
            'max_velocity_5m': 0,
            'tier1_count': 0,
            'tier2_count': 0,
            'tier3_count': 0,
            'long_signals': 0,
            'short_signals': 0,
        })
        self._load_data()

    def _load_data(self):
        """Load existing data from file"""
        try:
            os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f:
                    data = json.load(f)
                    self.records = data.get('records', [])[-10000:]  # Keep last 10k
                    self.alerts = data.get('alerts', [])[-1000:]  # Keep last 1k
                    self.pair_stats = defaultdict(lambda: {
                        'total_samples': 0,
                        'avg_velocity_1m': 0,
                        'avg_velocity_5m': 0,
                        'max_velocity_5m': 0,
                        'tier1_count': 0,
                        'tier2_count': 0,
                        'tier3_count': 0,
                        'long_signals': 0,
                        'short_signals': 0,
                    }, data.get('pair_stats', {}))
                    print(f"Loaded {len(self.records)} records, {len(self.alerts)} alerts")
        except Exception as e:
            print(f"Error loading data: {e}")

    def _save_data(self):
        """Save data to file"""
        try:
            with open(DATA_FILE, 'w') as f:
                json.dump({
                    'last_updated': datetime.now().isoformat(),
                    'records': self.records[-10000:],
                    'alerts': self.alerts[-1000:],
                    'pair_stats': dict(self.pair_stats)
                }, f, indent=2)
        except Exception as e:
            print(f"Error saving data: {e}")

    def add_record(self, record: VolatilityRecord):
        """Add a volatility record and update stats"""
        self.records.append(asdict(record))

        # Update pair stats
        stats = self.pair_stats[record.symbol]
        n = stats['total_samples']

        # Running average
        stats['avg_velocity_1m'] = (stats['avg_velocity_1m'] * n + abs(record.velocity_1m)) / (n + 1)
        stats['avg_velocity_5m'] = (stats['avg_velocity_5m'] * n + abs(record.velocity_5m)) / (n + 1)
        stats['max_velocity_5m'] = max(stats['max_velocity_5m'], abs(record.velocity_5m))
        stats['total_samples'] = n + 1

        # Track direction
        if record.velocity_5m > 0.5:
            stats['long_signals'] += 1
        elif record.velocity_5m < -0.5:
            stats['short_signals'] += 1

        # Track tiers
        abs_vel = abs(record.velocity_5m)
        if abs_vel >= 2.5:
            stats['tier1_count'] += 1
            self.alerts.append({
                'timestamp': record.timestamp,
                'symbol': record.symbol,
                'tier': 1,
                'velocity': record.velocity_5m,
                'direction': record.direction
            })
        elif abs_vel >= 1.5:
            stats['tier2_count'] += 1
            self.alerts.append({
                'timestamp': record.timestamp,
                'symbol': record.symbol,
                'tier': 2,
                'velocity': record.velocity_5m,
                'direction': record.direction
            })
        elif abs(record.velocity_1m) >= 1.5:
            stats['tier3_count'] += 1

    def get_top_volatile_pairs(self, limit: int = 20) -> List[Dict]:
        """Get pairs with highest average volatility"""
        pairs = []
        for symbol, stats in self.pair_stats.items():
            if stats['total_samples'] >= 10:  # Min samples
                pairs.append({
                    'symbol': symbol,
                    'avg_velocity_5m': stats['avg_velocity_5m'],
                    'max_velocity_5m': stats['max_velocity_5m'],
                    'samples': stats['total_samples'],
                    'tier1': stats['tier1_count'],
                    'tier2': stats['tier2_count'],
                    'long_pct': stats['long_signals'] / stats['total_samples'] * 100 if stats['total_samples'] > 0 else 0
                })

        return sorted(pairs, key=lambda x: x['avg_velocity_5m'], reverse=True)[:limit]

    def get_most_active_pairs(self, limit: int = 20) -> List[Dict]:
        """Get pairs with most tier alerts"""
        pairs = []
        for symbol, stats in self.pair_stats.items():
            total_alerts = stats['tier1_count'] + stats['tier2_count'] + stats['tier3_count']
            if total_alerts > 0:
                pairs.append({
                    'symbol': symbol,
                    'total_alerts': total_alerts,
                    'tier1': stats['tier1_count'],
                    'tier2': stats['tier2_count'],
                    'tier3': stats['tier3_count'],
                    'avg_velocity': stats['avg_velocity_5m']
                })

        return sorted(pairs, key=lambda x: x['total_alerts'], reverse=True)[:limit]

    def print_report(self):
        """Print analysis report"""
        print("\n" + "=" * 70)
        print("                 VOLATILITY ANALYSIS REPORT")
        print("=" * 70)

        print(f"\nData: {len(self.records)} samples, {len(self.alerts)} alerts")
        print(f"Pairs tracked: {len(self.pair_stats)}")

        print("\n--- TOP 15 MOST VOLATILE PAIRS (by avg 5m velocity) ---")
        print(f"{'Symbol':<15} {'Avg 5m':<10} {'Max 5m':<10} {'Samples':<10} {'T1':<5} {'T2':<5}")
        print("-" * 60)

        for p in self.get_top_volatile_pairs(15):
            print(f"{p['symbol']:<15} {p['avg_velocity_5m']:.2f}%     {p['max_velocity_5m']:.2f}%     {p['samples']:<10} {p['tier1']:<5} {p['tier2']:<5}")

        print("\n--- TOP 15 MOST ACTIVE PAIRS (by alert count) ---")
        print(f"{'Symbol':<15} {'Alerts':<10} {'T1':<5} {'T2':<5} {'T3':<5} {'Avg Vel':<10}")
        print("-" * 60)

        for p in self.get_most_active_pairs(15):
            print(f"{p['symbol']:<15} {p['total_alerts']:<10} {p['tier1']:<5} {p['tier2']:<5} {p['tier3']:<5} {p['avg_velocity']:.2f}%")

        print("\n--- RECENT ALERTS (last 20) ---")
        print(f"{'Time':<20} {'Symbol':<15} {'Tier':<5} {'Velocity':<10} {'Dir':<6}")
        print("-" * 60)

        for alert in self.alerts[-20:]:
            print(f"{alert['timestamp'][:19]:<20} {alert['symbol']:<15} T{alert['tier']:<4} {alert['velocity']:+.2f}%    {alert['direction']:<6}")

        print("\n" + "=" * 70)


async def scan_volatility(client: AsyncClient, tracker: VolatilityTracker, symbols: List[str]):
    """Scan all symbols for current volatility"""
    try:
        # Get all tickers
        tickers = await client.futures_symbol_ticker()
        prices = {t['symbol']: float(t['price']) for t in tickers}

        # Get 24h price changes
        changes = await client.futures_ticker()
        change_map = {t['symbol']: float(t['priceChangePercent']) for t in changes}

        # Get recent klines for velocity calculation
        for symbol in symbols:
            if symbol not in prices:
                continue

            try:
                # Get 15m klines for velocity
                klines = await client.futures_klines(symbol=symbol, interval='1m', limit=15)

                if len(klines) >= 15:
                    price_now = float(klines[-1][4])  # Close
                    price_1m = float(klines[-2][4])
                    price_5m = float(klines[-6][4])
                    price_15m = float(klines[0][4])

                    velocity_1m = ((price_now - price_1m) / price_1m) * 100 if price_1m > 0 else 0
                    velocity_5m = ((price_now - price_5m) / price_5m) * 100 if price_5m > 0 else 0
                    velocity_15m = ((price_now - price_15m) / price_15m) * 100 if price_15m > 0 else 0

                    direction = "LONG" if velocity_5m > 0 else "SHORT"

                    record = VolatilityRecord(
                        symbol=symbol,
                        timestamp=datetime.now().isoformat(),
                        velocity_1m=velocity_1m,
                        velocity_5m=velocity_5m,
                        velocity_15m=velocity_15m,
                        price=price_now,
                        direction=direction
                    )

                    tracker.add_record(record)

                    # Print if significant
                    if abs(velocity_5m) >= 1.5:
                        tier = 1 if abs(velocity_5m) >= 2.5 else 2
                        emoji = "🚀🚀🚀" if tier == 1 else "🚀🚀"
                        print(f"{emoji} T{tier} {symbol}: {velocity_5m:+.2f}% (5m) | {velocity_1m:+.2f}% (1m)")

                await asyncio.sleep(0.1)  # Rate limit

            except Exception as e:
                continue

    except Exception as e:
        print(f"Error scanning: {e}")


async def main():
    """Main loop - continuously scan and analyze"""
    # Use testnet if specified
    testnet = len(sys.argv) > 1 and 'testnet' in sys.argv[1].lower()

    if testnet:
        print("🧪 TESTNET MODE")
        client = await AsyncClient.create(
            api_key=os.getenv('BINANCE_TESTNET_KEY', BINANCE_API_KEY),
            api_secret=os.getenv('BINANCE_TESTNET_SECRET', BINANCE_API_SECRET),
            testnet=True
        )
    else:
        print("💰 PRODUCTION MODE")
        client = await AsyncClient.create(
            api_key=BINANCE_API_KEY,
            api_secret=BINANCE_API_SECRET
        )

    tracker = VolatilityTracker()

    # Get symbols to track
    from config import PairFilterConfig
    symbols = PairFilterConfig.WHITELISTED_PAIRS
    print(f"Tracking {len(symbols)} symbols")

    scan_count = 0

    try:
        while True:
            print(f"\n--- Scan #{scan_count + 1} at {datetime.now().strftime('%H:%M:%S')} ---")

            await scan_volatility(client, tracker, symbols)

            scan_count += 1

            # Save and print report every 10 scans
            if scan_count % 10 == 0:
                tracker._save_data()
                tracker.print_report()

            # Wait before next scan
            await asyncio.sleep(60)  # 1 minute between scans

    except KeyboardInterrupt:
        print("\nStopping...")
        tracker._save_data()
        tracker.print_report()
    finally:
        await client.close_connection()


if __name__ == "__main__":
    print("=" * 50)
    print("   VOLATILITY ANALYZER")
    print("   Extracts useful volatility data")
    print("=" * 50)
    print("\nUsage: python scripts/volatility_analyzer.py [--testnet]")
    print("Press Ctrl+C to stop and see report\n")

    asyncio.run(main())
