"""
Order Executor Module
Executes orders on Binance Futures
"""
from typing import Optional, Dict
from dataclasses import dataclass
from loguru import logger
from binance.enums import *

from config import LeverageConfig


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str]
    symbol: str
    side: str
    quantity: float
    price: float
    error: Optional[str] = None


class OrderExecutor:
    """
    Executes orders on Binance Futures
    Handles market orders, stop-losses, and position management
    """
    
    def __init__(self, data_feed):
        self.data_feed = data_feed
        self.client = None  # Will be set after data_feed initializes
    
    async def initialize(self):
        """Initialize with the Binance client"""
        self.client = self.data_feed.client
    
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol"""
        try:
            await self.client.futures_change_leverage(
                symbol=symbol,
                leverage=leverage
            )
            logger.debug(f"Leverage set to {leverage}x for {symbol}")
            return True
        except Exception as e:
            # Leverage might already be set
            if "No need to change leverage" in str(e):
                return True
            logger.error(f"Error setting leverage for {symbol}: {e}")
            return False
    
    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> bool:
        """Set margin type (ISOLATED or CROSSED)"""
        try:
            await self.client.futures_change_margin_type(
                symbol=symbol,
                marginType=margin_type
            )
            logger.debug(f"Margin type set to {margin_type} for {symbol}")
            return True
        except Exception as e:
            # Margin type might already be set
            if "No need to change margin type" in str(e):
                return True
            logger.error(f"Error setting margin type for {symbol}: {e}")
            return False
    
    async def get_symbol_precision(self, symbol: str) -> tuple:
        """Get quantity and price precision for a symbol"""
        try:
            exchange_info = await self.client.futures_exchange_info()
            
            for s in exchange_info['symbols']:
                if s['symbol'] == symbol:
                    quantity_precision = s['quantityPrecision']
                    price_precision = s['pricePrecision']
                    
                    # Get min quantity
                    min_qty = 0.001
                    for f in s['filters']:
                        if f['filterType'] == 'LOT_SIZE':
                            min_qty = float(f['minQty'])
                            break
                    
                    return quantity_precision, price_precision, min_qty
            
            return 3, 2, 0.001
            
        except Exception as e:
            logger.error(f"Error getting precision for {symbol}: {e}")
            return 3, 2, 0.001
    
    async def calculate_quantity(self, symbol: str, margin: float, leverage: int, price: float) -> float:
        """Calculate order quantity from margin amount"""
        try:
            qty_precision, _, min_qty = await self.get_symbol_precision(symbol)
            
            # Notional value = margin * leverage
            notional = margin * leverage
            
            # Quantity = notional / price
            quantity = notional / price
            
            # Round to precision
            quantity = round(quantity, qty_precision)
            
            # Ensure minimum
            quantity = max(quantity, min_qty)
            
            return quantity
            
        except Exception as e:
            logger.error(f"Error calculating quantity for {symbol}: {e}")
            return 0.0
    
    async def open_long(
        self, 
        symbol: str, 
        margin: float, 
        leverage: int,
        stop_loss: Optional[float] = None
    ) -> OrderResult:
        """Open a long position"""
        try:
            # Set leverage
            await self.set_leverage(symbol, leverage)
            await self.set_margin_type(symbol, "ISOLATED")
            
            # Get current price
            ticker = await self.data_feed.get_ticker(symbol)
            if not ticker:
                return OrderResult(
                    success=False, order_id=None, symbol=symbol,
                    side="BUY", quantity=0, price=0,
                    error="Could not get current price"
                )
            
            price = ticker.price
            quantity = await self.calculate_quantity(symbol, margin, leverage, price)
            
            if quantity <= 0:
                return OrderResult(
                    success=False, order_id=None, symbol=symbol,
                    side="BUY", quantity=0, price=price,
                    error="Invalid quantity"
                )
            
            # Place market order
            order = await self.client.futures_create_order(
                symbol=symbol,
                side=SIDE_BUY,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            
            logger.info(f"🟢 LONG opened: {symbol} | Qty: {quantity} | Price: ~{price}")

            # Set stop-loss if provided
            if stop_loss:
                await self._set_stop_loss(symbol, "LONG", quantity, stop_loss)

            # Get actual entry price from position (avgPrice in response is often 0)
            actual_price = float(order.get('avgPrice', 0))
            if actual_price <= 0:
                # Query position to get real entry price
                try:
                    positions = await self.client.futures_position_information(symbol=symbol)
                    for p in positions:
                        if p['symbol'] == symbol and float(p['positionAmt']) != 0:
                            actual_price = float(p['entryPrice'])
                            break
                except Exception:
                    pass
                # Fallback to ticker price
                if actual_price <= 0:
                    actual_price = price

            return OrderResult(
                success=True,
                order_id=str(order['orderId']),
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                price=actual_price
            )
            
        except Exception as e:
            logger.error(f"Error opening long {symbol}: {e}")
            return OrderResult(
                success=False, order_id=None, symbol=symbol,
                side="BUY", quantity=0, price=0,
                error=str(e)
            )
    
    async def open_short(
        self, 
        symbol: str, 
        margin: float, 
        leverage: int,
        stop_loss: Optional[float] = None
    ) -> OrderResult:
        """Open a short position"""
        try:
            # Set leverage
            await self.set_leverage(symbol, leverage)
            await self.set_margin_type(symbol, "ISOLATED")
            
            # Get current price
            ticker = await self.data_feed.get_ticker(symbol)
            if not ticker:
                return OrderResult(
                    success=False, order_id=None, symbol=symbol,
                    side="SELL", quantity=0, price=0,
                    error="Could not get current price"
                )
            
            price = ticker.price
            quantity = await self.calculate_quantity(symbol, margin, leverage, price)
            
            if quantity <= 0:
                return OrderResult(
                    success=False, order_id=None, symbol=symbol,
                    side="SELL", quantity=0, price=price,
                    error="Invalid quantity"
                )
            
            # Place market order
            order = await self.client.futures_create_order(
                symbol=symbol,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            
            logger.info(f"🔴 SHORT opened: {symbol} | Qty: {quantity} | Price: ~{price}")

            # Set stop-loss if provided
            if stop_loss:
                await self._set_stop_loss(symbol, "SHORT", quantity, stop_loss)

            # Get actual entry price from position (avgPrice in response is often 0)
            actual_price = float(order.get('avgPrice', 0))
            if actual_price <= 0:
                # Query position to get real entry price
                try:
                    positions = await self.client.futures_position_information(symbol=symbol)
                    for p in positions:
                        if p['symbol'] == symbol and float(p['positionAmt']) != 0:
                            actual_price = float(p['entryPrice'])
                            break
                except Exception:
                    pass
                # Fallback to ticker price
                if actual_price <= 0:
                    actual_price = price

            return OrderResult(
                success=True,
                order_id=str(order['orderId']),
                symbol=symbol,
                side="SELL",
                quantity=quantity,
                price=actual_price
            )
            
        except Exception as e:
            logger.error(f"Error opening short {symbol}: {e}")
            return OrderResult(
                success=False, order_id=None, symbol=symbol,
                side="SELL", quantity=0, price=0,
                error=str(e)
            )
    
    async def _set_stop_loss(self, symbol: str, direction: str, quantity: float, stop_price: float) -> bool:
        """Set a stop-loss order with verification"""
        try:
            _, price_precision, _ = await self.get_symbol_precision(symbol)
            stop_price = round(stop_price, price_precision)

            side = SIDE_SELL if direction == "LONG" else SIDE_BUY

            order = await self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=FUTURE_ORDER_TYPE_STOP_MARKET,
                stopPrice=stop_price,
                closePosition=True
            )

            # Verify order was accepted
            if order and 'orderId' in order:
                logger.info(f"✅ Stop-loss confirmed for {symbol} at {stop_price} (Order: {order['orderId']})")
                return True
            else:
                logger.critical(f"🚨 STOP-LOSS NOT CONFIRMED for {symbol} - response: {order}")
                return False

        except Exception as e:
            logger.critical(f"🚨 STOP-LOSS FAILED for {symbol}: {e} - POSITION AT RISK")
            # Try to close position if SL cannot be set
            try:
                await self.close_position(symbol, percent=100)
                logger.warning(f"⚠️ Position {symbol} closed due to SL failure")
            except Exception as close_error:
                logger.critical(f"🚨 CRITICAL: Could not close {symbol} after SL failure: {close_error}")
            return False
    
    async def close_position(self, symbol: str, percent: float = 100) -> OrderResult:
        """Close a position (fully or partially)"""
        try:
            # Get current position
            positions = await self.client.futures_position_information(symbol=symbol)
            
            position = None
            for p in positions:
                if p['symbol'] == symbol and float(p['positionAmt']) != 0:
                    position = p
                    break
            
            if not position:
                return OrderResult(
                    success=False, order_id=None, symbol=symbol,
                    side="", quantity=0, price=0,
                    error="No position found"
                )
            
            position_amt = float(position['positionAmt'])
            
            # Calculate quantity to close
            close_qty = abs(position_amt) * (percent / 100)
            
            # Round to precision
            qty_precision, _, min_qty = await self.get_symbol_precision(symbol)
            close_qty = round(close_qty, qty_precision)
            close_qty = max(close_qty, min_qty)
            
            # Determine side (opposite of position)
            if position_amt > 0:
                side = SIDE_SELL
                direction = "LONG"
            else:
                side = SIDE_BUY
                direction = "SHORT"
            
            # Close position
            order = await self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=close_qty,
                reduceOnly=True
            )
            
            logger.info(f"📤 Position closed: {symbol} {direction} | {percent}% | Qty: {close_qty}")
            
            return OrderResult(
                success=True,
                order_id=str(order['orderId']),
                symbol=symbol,
                side=side,
                quantity=close_qty,
                price=float(order.get('avgPrice', 0))
            )
            
        except Exception as e:
            logger.error(f"Error closing position {symbol}: {e}")
            return OrderResult(
                success=False, order_id=None, symbol=symbol,
                side="", quantity=0, price=0,
                error=str(e)
            )
    
    async def cancel_all_orders(self, symbol: str):
        """Cancel all open orders for a symbol"""
        try:
            await self.client.futures_cancel_all_open_orders(symbol=symbol)
            logger.debug(f"All orders cancelled for {symbol}")
        except Exception as e:
            logger.error(f"Error cancelling orders for {symbol}: {e}")
    
    async def update_stop_loss(self, symbol: str, new_stop: float):
        """Update stop-loss price for a position"""
        try:
            # Cancel existing stop orders
            await self.cancel_all_orders(symbol)
            
            # Get position
            positions = await self.client.futures_position_information(symbol=symbol)
            
            for p in positions:
                if p['symbol'] == symbol:
                    position_amt = float(p['positionAmt'])
                    
                    if position_amt > 0:
                        direction = "LONG"
                    elif position_amt < 0:
                        direction = "SHORT"
                    else:
                        return
                    
                    await self._set_stop_loss(symbol, direction, abs(position_amt), new_stop)
                    break
                    
        except Exception as e:
            logger.error(f"Error updating stop-loss for {symbol}: {e}")
    
    async def get_open_positions(self) -> list:
        """Get all open positions"""
        try:
            positions = await self.client.futures_position_information()
            
            open_positions = []
            for p in positions:
                if float(p['positionAmt']) != 0:
                    open_positions.append({
                        'symbol': p['symbol'],
                        'side': 'LONG' if float(p['positionAmt']) > 0 else 'SHORT',
                        'quantity': abs(float(p['positionAmt'])),
                        'entry_price': float(p['entryPrice']),
                        'unrealized_pnl': float(p['unRealizedProfit']),
                        'leverage': int(p['leverage'])
                    })
            
            return open_positions
            
        except Exception as e:
            logger.error(f"Error getting open positions: {e}")
            return []
