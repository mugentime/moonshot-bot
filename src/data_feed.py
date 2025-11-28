"""
Data Feed Module
Handles real-time data from Binance Futures via WebSocket and REST API

WebSocket streams for real-time data (primary):
- All-market ticker stream (!ticker@arr)
- Kline streams for active symbols
- Mark price stream with funding rates (!markPrice@arr@1s)

REST API as fallback when WebSocket data is stale or unavailable.
"""
import asyncio
from typing import Dict, List, Callable, Optional
from binance import AsyncClient, BinanceSocketManager
from binance.enums import *
from loguru import logger
import time
from dataclasses import dataclass, field
from collections import defaultdict

from config import BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_TESTNET


# =============================================================================
# WEBSOCKET CONFIGURATION
# =============================================================================

class WebSocketConfig:
    """WebSocket stream configuration"""
    # Cache freshness thresholds (seconds)
    TICKER_MAX_AGE = 3.0  # Use REST if ticker older than 3s
    KLINE_MAX_AGE = 5.0   # Use REST if kline older than 5s
    FUNDING_MAX_AGE = 10.0  # Funding updates every 8h, 10s cache is fine

    # Reconnection settings
    RECONNECT_DELAY_INITIAL = 1.0  # Start with 1 second
    RECONNECT_DELAY_MAX = 60.0     # Max 60 seconds between retries
    RECONNECT_DELAY_MULTIPLIER = 2.0  # Double delay each retry

    # Stream limits
    MAX_KLINE_SYMBOLS = 200  # Binance limit per connection
    KLINE_INTERVALS = ['1m', '5m']  # Intervals to stream

    # Timeouts
    STREAM_TIMEOUT = 30  # Seconds to wait for message before reconnecting


@dataclass
class TickerData:
    symbol: str
    price: float
    price_change_percent_24h: float
    volume_24h: float
    high_24h: float
    low_24h: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class KlineData:
    symbol: str
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: float


@dataclass
class OrderBookData:
    symbol: str
    bids: List[List[float]]  # [[price, quantity], ...]
    asks: List[List[float]]
    timestamp: float = field(default_factory=time.time)


@dataclass
class FundingRateData:
    symbol: str
    funding_rate: float
    next_funding_time: int
    timestamp: float = field(default_factory=time.time)


class DataFeed:
    """
    Manages all data streams from Binance Futures

    Uses WebSocket streams as primary data source with REST API fallback.
    """

    def __init__(self):
        self.client: Optional[AsyncClient] = None
        self.bsm: Optional[BinanceSocketManager] = None

        # Data storage
        self.tickers: Dict[str, TickerData] = {}
        self.klines: Dict[str, Dict[str, List[KlineData]]] = defaultdict(lambda: defaultdict(list))
        self.orderbooks: Dict[str, OrderBookData] = {}
        self.funding_rates: Dict[str, FundingRateData] = {}
        self.open_interest: Dict[str, float] = {}

        # Volume tracking for spike detection
        self.volume_history: Dict[str, List[float]] = defaultdict(list)
        self.price_history: Dict[str, List[Dict]] = defaultdict(list)

        # Callbacks
        self.on_ticker_update: Optional[Callable] = None
        self.on_kline_update: Optional[Callable] = None

        # State
        self._running = False
        self._sockets = []

        # WebSocket stream tasks
        self._ticker_stream_task: Optional[asyncio.Task] = None
        self._kline_stream_task: Optional[asyncio.Task] = None
        self._funding_stream_task: Optional[asyncio.Task] = None

        # WebSocket stream status
        self._streams_active = {
            'ticker': False,
            'kline': False,
            'funding': False
        }

        # Symbols subscribed to kline streams
        self._kline_subscribed_symbols: List[str] = []

        # REST API call counter (for monitoring)
        self._rest_calls = 0
        self._rest_calls_last_reset = time.time()
    
    async def initialize(self):
        """Initialize Binance client"""
        logger.info("Initializing Binance client...")
        
        if BINANCE_TESTNET:
            self.client = await AsyncClient.create(
                BINANCE_API_KEY,
                BINANCE_API_SECRET,
                testnet=True
            )
            logger.info("Connected to Binance TESTNET")
        else:
            self.client = await AsyncClient.create(
                BINANCE_API_KEY,
                BINANCE_API_SECRET
            )
            logger.info("Connected to Binance PRODUCTION")
        
        self.bsm = BinanceSocketManager(self.client)
    
    async def close(self):
        """Clean shutdown"""
        self._running = False

        # Stop WebSocket streams
        await self.stop_streams()

        # Close all sockets
        for socket in self._sockets:
            try:
                await socket.__aexit__(None, None, None)
            except:
                pass

        if self.client:
            await self.client.close_connection()

        logger.info("DataFeed closed")
    
    async def get_all_futures_symbols(self) -> List[str]:
        """Get all available USDT/USDC perpetual futures symbols"""
        exchange_info = await self.client.futures_exchange_info()
        
        symbols = []
        for s in exchange_info['symbols']:
            if s['contractType'] == 'PERPETUAL':
                if s['quoteAsset'] in ['USDT', 'USDC']:
                    if s['status'] == 'TRADING':
                        symbols.append(s['symbol'])
        
        logger.info(f"Found {len(symbols)} perpetual futures symbols")
        return symbols
    
    async def get_ticker(self, symbol: str) -> Optional[TickerData]:
        """
        Get current ticker for a symbol.

        Uses WebSocket cache first, falls back to REST API if:
        - No cached data exists
        - Cached data is stale (older than TICKER_MAX_AGE)
        """
        # Check WebSocket cache first
        if symbol in self.tickers:
            cached = self.tickers[symbol]
            age = time.time() - cached.timestamp
            if age < WebSocketConfig.TICKER_MAX_AGE:
                return cached

        # Fallback to REST API
        try:
            self._rest_calls += 1
            ticker = await self.client.futures_ticker(symbol=symbol)

            data = TickerData(
                symbol=symbol,
                price=float(ticker['lastPrice']),
                price_change_percent_24h=float(ticker['priceChangePercent']),
                volume_24h=float(ticker['quoteVolume']),
                high_24h=float(ticker['highPrice']),
                low_24h=float(ticker['lowPrice'])
            )

            self.tickers[symbol] = data
            return data

        except Exception as e:
            logger.error(f"Error getting ticker for {symbol}: {e}")
            # Return stale cache if REST fails
            return self.tickers.get(symbol)
    
    async def get_klines(self, symbol: str, interval: str = '5m', limit: int = 100) -> List[KlineData]:
        """
        Get historical klines.

        Uses WebSocket cache first for subscribed symbols, falls back to REST API.
        """
        # Check WebSocket cache first
        if symbol in self.klines and interval in self.klines[symbol]:
            cached = self.klines[symbol][interval]
            if cached:
                # Check if data is fresh (last candle updated recently)
                age = time.time() - cached[-1].timestamp
                # For 1m candles, allow up to 90 seconds; for 5m, up to 6 minutes
                max_age = 90 if interval == '1m' else 360
                if age < max_age and len(cached) >= min(limit, 20):
                    return cached[-limit:]

        # Fallback to REST API
        try:
            self._rest_calls += 1
            klines = await self.client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )

            result = []
            for k in klines:
                data = KlineData(
                    symbol=symbol,
                    interval=interval,
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    timestamp=k[0] / 1000
                )
                result.append(data)

            self.klines[symbol][interval] = result
            return result

        except Exception as e:
            logger.error(f"Error getting klines for {symbol}: {e}")
            # Return stale cache if REST fails
            return self.klines.get(symbol, {}).get(interval, [])
    
    async def get_orderbook(self, symbol: str, limit: int = 20) -> Optional[OrderBookData]:
        """Get order book depth"""
        try:
            self._rest_calls += 1
            depth = await self.client.futures_order_book(symbol=symbol, limit=limit)

            data = OrderBookData(
                symbol=symbol,
                bids=[[float(b[0]), float(b[1])] for b in depth['bids']],
                asks=[[float(a[0]), float(a[1])] for a in depth['asks']]
            )

            self.orderbooks[symbol] = data
            return data

        except Exception as e:
            logger.error(f"Error getting orderbook for {symbol}: {e}")
            return self.orderbooks.get(symbol)  # Return stale cache if REST fails
    
    async def get_funding_rate(self, symbol: str) -> Optional[FundingRateData]:
        """
        Get current funding rate.

        Uses WebSocket cache first (from mark price stream), falls back to REST API.
        """
        # Check WebSocket cache first
        if symbol in self.funding_rates:
            cached = self.funding_rates[symbol]
            age = time.time() - cached.timestamp
            if age < WebSocketConfig.FUNDING_MAX_AGE:
                return cached

        # Fallback to REST API
        try:
            self._rest_calls += 1
            funding = await self.client.futures_funding_rate(symbol=symbol, limit=1)

            if funding:
                data = FundingRateData(
                    symbol=symbol,
                    funding_rate=float(funding[-1]['fundingRate']),
                    next_funding_time=int(funding[-1]['fundingTime'])
                )
                self.funding_rates[symbol] = data
                return data

            return None

        except Exception as e:
            logger.error(f"Error getting funding rate for {symbol}: {e}")
            # Return stale cache if REST fails
            return self.funding_rates.get(symbol)
    
    async def get_open_interest(self, symbol: str) -> Optional[float]:
        """Get open interest"""
        try:
            self._rest_calls += 1
            oi = await self.client.futures_open_interest(symbol=symbol)
            value = float(oi['openInterest'])
            self.open_interest[symbol] = value
            return value

        except Exception as e:
            logger.error(f"Error getting open interest for {symbol}: {e}")
            return self.open_interest.get(symbol)  # Return stale cache if REST fails
    
    async def get_account_balance(self) -> float:
        """Get total account equity across all assets"""
        try:
            account = await self.client.futures_account()

            # Log all balances for debugging
            total_margin = float(account.get('totalMarginBalance', 0))
            total_wallet = float(account.get('totalWalletBalance', 0))
            available = float(account.get('availableBalance', 0))

            # Sum all asset balances (in case of multi-asset mode)
            total_from_assets = 0.0
            for asset in account.get('assets', []):
                margin_balance = float(asset.get('marginBalance', 0))
                if margin_balance > 0:
                    logger.debug(f"Asset {asset['asset']}: marginBalance=${margin_balance:.2f}")
                    total_from_assets += margin_balance

            logger.info(f"💰 Account balances - totalMargin: ${total_margin:.2f}, "
                       f"totalWallet: ${total_wallet:.2f}, available: ${available:.2f}, "
                       f"sumAssets: ${total_from_assets:.2f}")

            # Use totalMarginBalance (includes all assets + unrealized PnL)
            if total_margin > 0:
                return total_margin

            # Fallback to sum of all asset margin balances
            if total_from_assets > 0:
                return total_from_assets

            # Last fallback to totalWalletBalance
            return total_wallet

        except Exception as e:
            logger.error(f"Error getting account balance: {e}")
            return 0.0
    
    def get_volume_average(self, symbol: str, periods: int = 12) -> float:
        """Get average volume over last N periods (5min each = 1 hour for 12)"""
        if symbol not in self.klines or '5m' not in self.klines[symbol]:
            return 0.0
        
        klines = self.klines[symbol]['5m']
        if len(klines) < periods:
            return 0.0
        
        volumes = [k.volume for k in klines[-periods:]]
        return sum(volumes) / len(volumes)
    
    def get_price_change_percent(self, symbol: str, minutes: int = 5) -> float:
        """Get price change over last N minutes"""
        if symbol not in self.klines or '1m' not in self.klines[symbol]:
            return 0.0
        
        klines = self.klines[symbol]['1m']
        if len(klines) < minutes:
            return 0.0
        
        old_price = klines[-minutes].close
        new_price = klines[-1].close
        
        if old_price == 0:
            return 0.0
        
        return ((new_price - old_price) / old_price) * 100
    
    def get_orderbook_imbalance(self, symbol: str) -> float:
        """Get bid/ask imbalance ratio (0-1, higher = more bids)"""
        if symbol not in self.orderbooks:
            return 0.5
        
        ob = self.orderbooks[symbol]
        
        total_bids = sum(b[1] for b in ob.bids)
        total_asks = sum(a[1] for a in ob.asks)
        
        total = total_bids + total_asks
        if total == 0:
            return 0.5
        
        return total_bids / total
    
    async def subscribe_ticker_stream(self, symbols: List[str]):
        """Subscribe to ticker updates for multiple symbols"""
        logger.info(f"Subscribing to ticker stream for {len(symbols)} symbols")
        
        # Use futures multiplex socket
        streams = [f"{s.lower()}@ticker" for s in symbols]
        
        socket = self.bsm.futures_multiplex_socket(streams)
        self._sockets.append(socket)
        
        async with socket as stream:
            self._running = True
            while self._running:
                try:
                    msg = await asyncio.wait_for(stream.recv(), timeout=30)
                    
                    if msg and 'data' in msg:
                        data = msg['data']
                        symbol = data['s']
                        
                        ticker = TickerData(
                            symbol=symbol,
                            price=float(data['c']),
                            price_change_percent_24h=float(data['P']),
                            volume_24h=float(data['q']),
                            high_24h=float(data['h']),
                            low_24h=float(data['l'])
                        )
                        
                        self.tickers[symbol] = ticker
                        
                        if self.on_ticker_update:
                            await self.on_ticker_update(ticker)
                            
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error in ticker stream: {e}")
                    await asyncio.sleep(1)
    
    async def get_spread(self, symbol: str) -> float:
        """Get current bid-ask spread as percentage"""
        if symbol not in self.orderbooks:
            await self.get_orderbook(symbol)

        if symbol not in self.orderbooks:
            return 1.0  # Return high spread if can't get data

        ob = self.orderbooks[symbol]
        if not ob.bids or not ob.asks:
            return 1.0

        best_bid = ob.bids[0][0]
        best_ask = ob.asks[0][0]

        if best_bid == 0:
            return 1.0

        return ((best_ask - best_bid) / best_bid) * 100

    # =========================================================================
    # WEBSOCKET STREAM METHODS
    # =========================================================================

    async def start_all_streams(self, kline_symbols: Optional[List[str]] = None):
        """
        Start all WebSocket streams for real-time data.

        Args:
            kline_symbols: List of symbols to subscribe to kline streams (max 200)
        """
        logger.info("🔌 Starting WebSocket streams...")

        # IMPORTANT: Set running flag BEFORE starting stream tasks
        # Otherwise the while self._running loops will exit immediately
        self._running = True

        # Start all-market ticker stream
        self._ticker_stream_task = asyncio.create_task(
            self._run_ticker_stream_with_reconnect()
        )

        # Start mark price / funding stream
        self._funding_stream_task = asyncio.create_task(
            self._run_funding_stream_with_reconnect()
        )

        # Start kline streams for specified symbols
        if kline_symbols:
            symbols = kline_symbols[:WebSocketConfig.MAX_KLINE_SYMBOLS]
            self._kline_subscribed_symbols = symbols
            self._kline_stream_task = asyncio.create_task(
                self._run_kline_stream_with_reconnect(symbols)
            )

        # Wait for streams to start populating data
        await asyncio.sleep(2)

        active_count = sum(1 for v in self._streams_active.values() if v)
        logger.info(f"✅ WebSocket streams started: {active_count}/3 active")

    async def stop_streams(self):
        """Stop all WebSocket streams"""
        logger.info("Stopping WebSocket streams...")

        for task in [self._ticker_stream_task, self._kline_stream_task, self._funding_stream_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._streams_active = {'ticker': False, 'kline': False, 'funding': False}
        logger.info("WebSocket streams stopped")

    async def _run_ticker_stream_with_reconnect(self):
        """Run all-market ticker stream with auto-reconnection"""
        reconnect_delay = WebSocketConfig.RECONNECT_DELAY_INITIAL

        while self._running:
            try:
                logger.info("📡 Connecting to all-market ticker stream...")
                await self._all_market_ticker_stream()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ticker stream error: {e}")
                self._streams_active['ticker'] = False

                # Exponential backoff
                logger.info(f"Reconnecting ticker stream in {reconnect_delay:.1f}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(
                    reconnect_delay * WebSocketConfig.RECONNECT_DELAY_MULTIPLIER,
                    WebSocketConfig.RECONNECT_DELAY_MAX
                )

    async def _all_market_ticker_stream(self):
        """Subscribe to all futures tickers in one stream"""
        # Use futures_multiplex_socket with the all-market ticker stream
        streams = ['!ticker@arr']

        socket = self.bsm.futures_multiplex_socket(streams)
        self._sockets.append(socket)

        async with socket as stream:
            self._streams_active['ticker'] = True
            logger.info("✅ All-market ticker stream connected")

            while self._running:
                try:
                    msg = await asyncio.wait_for(
                        stream.recv(),
                        timeout=WebSocketConfig.STREAM_TIMEOUT
                    )

                    if msg and 'data' in msg:
                        data_list = msg['data'] if isinstance(msg['data'], list) else [msg['data']]

                        for ticker_data in data_list:
                            symbol = ticker_data.get('s')
                            if symbol:
                                self.tickers[symbol] = TickerData(
                                    symbol=symbol,
                                    price=float(ticker_data.get('c', 0)),
                                    price_change_percent_24h=float(ticker_data.get('P', 0)),
                                    volume_24h=float(ticker_data.get('q', 0)),
                                    high_24h=float(ticker_data.get('h', 0)),
                                    low_24h=float(ticker_data.get('l', 0))
                                )

                except asyncio.TimeoutError:
                    # No message received, but connection is still alive
                    continue

    async def _run_funding_stream_with_reconnect(self):
        """Run mark price / funding rate stream with auto-reconnection"""
        reconnect_delay = WebSocketConfig.RECONNECT_DELAY_INITIAL

        while self._running:
            try:
                logger.info("📡 Connecting to mark price / funding stream...")
                await self._mark_price_stream()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Funding stream error: {e}")
                self._streams_active['funding'] = False

                logger.info(f"Reconnecting funding stream in {reconnect_delay:.1f}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(
                    reconnect_delay * WebSocketConfig.RECONNECT_DELAY_MULTIPLIER,
                    WebSocketConfig.RECONNECT_DELAY_MAX
                )

    async def _mark_price_stream(self):
        """Subscribe to all mark prices (includes funding rate info)"""
        streams = ['!markPrice@arr@1s']

        socket = self.bsm.futures_multiplex_socket(streams)
        self._sockets.append(socket)

        async with socket as stream:
            self._streams_active['funding'] = True
            logger.info("✅ Mark price / funding stream connected")

            while self._running:
                try:
                    msg = await asyncio.wait_for(
                        stream.recv(),
                        timeout=WebSocketConfig.STREAM_TIMEOUT
                    )

                    if msg and 'data' in msg:
                        data_list = msg['data'] if isinstance(msg['data'], list) else [msg['data']]

                        for data in data_list:
                            symbol = data.get('s')
                            if symbol:
                                # Extract funding rate from mark price stream
                                funding_rate = float(data.get('r', 0))
                                next_funding_time = int(data.get('T', 0))

                                self.funding_rates[symbol] = FundingRateData(
                                    symbol=symbol,
                                    funding_rate=funding_rate,
                                    next_funding_time=next_funding_time
                                )

                except asyncio.TimeoutError:
                    continue

    async def _run_kline_stream_with_reconnect(self, symbols: List[str]):
        """Run kline streams with auto-reconnection"""
        reconnect_delay = WebSocketConfig.RECONNECT_DELAY_INITIAL

        while self._running:
            try:
                logger.info(f"📡 Connecting to kline streams for {len(symbols)} symbols...")
                await self._kline_stream(symbols)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Kline stream error: {e}")
                self._streams_active['kline'] = False

                logger.info(f"Reconnecting kline stream in {reconnect_delay:.1f}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(
                    reconnect_delay * WebSocketConfig.RECONNECT_DELAY_MULTIPLIER,
                    WebSocketConfig.RECONNECT_DELAY_MAX
                )

    async def _kline_stream(self, symbols: List[str]):
        """Subscribe to kline streams for specified symbols"""
        streams = []
        for symbol in symbols:
            for interval in WebSocketConfig.KLINE_INTERVALS:
                streams.append(f"{symbol.lower()}@kline_{interval}")

        socket = self.bsm.futures_multiplex_socket(streams)
        self._sockets.append(socket)

        async with socket as stream:
            self._streams_active['kline'] = True
            logger.info(f"✅ Kline streams connected ({len(streams)} streams)")

            while self._running:
                try:
                    msg = await asyncio.wait_for(
                        stream.recv(),
                        timeout=WebSocketConfig.STREAM_TIMEOUT
                    )

                    if msg and 'data' in msg:
                        data = msg['data']
                        symbol = data.get('s')
                        kline = data.get('k', {})
                        interval = kline.get('i')

                        if symbol and interval:
                            kline_data = KlineData(
                                symbol=symbol,
                                interval=interval,
                                open=float(kline.get('o', 0)),
                                high=float(kline.get('h', 0)),
                                low=float(kline.get('l', 0)),
                                close=float(kline.get('c', 0)),
                                volume=float(kline.get('v', 0)),
                                timestamp=kline.get('t', 0) / 1000
                            )

                            # Update kline buffer
                            buffer = self.klines[symbol][interval]

                            # Update current candle or append new
                            if buffer and abs(buffer[-1].timestamp - kline_data.timestamp) < 1:
                                buffer[-1] = kline_data
                            else:
                                buffer.append(kline_data)
                                # Keep only last 100 candles
                                if len(buffer) > 100:
                                    self.klines[symbol][interval] = buffer[-100:]

                except asyncio.TimeoutError:
                    continue

    def get_stream_status(self) -> Dict:
        """Get WebSocket stream status for monitoring"""
        # Calculate REST calls per minute
        elapsed = time.time() - self._rest_calls_last_reset
        calls_per_min = (self._rest_calls / elapsed * 60) if elapsed > 0 else 0

        return {
            'streams_active': self._streams_active.copy(),
            'ticker_cache_size': len(self.tickers),
            'kline_subscriptions': len(self._kline_subscribed_symbols),
            'funding_cache_size': len(self.funding_rates),
            'rest_calls_per_minute': round(calls_per_min, 1),
            'rest_calls_total': self._rest_calls
        }

    def reset_rest_call_counter(self):
        """Reset REST API call counter"""
        self._rest_calls = 0
        self._rest_calls_last_reset = time.time()
