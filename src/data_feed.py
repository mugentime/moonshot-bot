"""
Data Feed Module
Handles real-time data from Binance Futures via WebSocket and REST API
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
        """Get current ticker for a symbol"""
        try:
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
            return None
    
    async def get_klines(self, symbol: str, interval: str = '5m', limit: int = 100) -> List[KlineData]:
        """Get historical klines"""
        try:
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
            return []
    
    async def get_orderbook(self, symbol: str, limit: int = 20) -> Optional[OrderBookData]:
        """Get order book depth"""
        try:
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
            return None
    
    async def get_funding_rate(self, symbol: str) -> Optional[FundingRateData]:
        """Get current funding rate"""
        try:
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
            return None
    
    async def get_open_interest(self, symbol: str) -> Optional[float]:
        """Get open interest"""
        try:
            oi = await self.client.futures_open_interest(symbol=symbol)
            value = float(oi['openInterest'])
            self.open_interest[symbol] = value
            return value
            
        except Exception as e:
            logger.error(f"Error getting open interest for {symbol}: {e}")
            return None
    
    async def get_account_balance(self) -> float:
        """Get USDT balance"""
        try:
            account = await self.client.futures_account()
            
            for asset in account['assets']:
                if asset['asset'] == 'USDT':
                    return float(asset['walletBalance'])
            
            return 0.0
            
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
