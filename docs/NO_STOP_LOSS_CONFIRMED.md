# ✅ CONFIRMACIÓN: NO STOP LOSS ACTIVO

**Fecha:** 2025-12-17
**Status:** ✅ VERIFICADO - NO HAY STOP LOSS EN EL CÓDIGO
**Acción:** Cancelar cualquier orden STOP_MARKET en Binance

---

## 🔍 Verificación Completa

### 1. Código del Bot - SIN Stop Loss Logic

He verificado **TODO** el código del bot:

**main.py:**
- ❌ NO hay lógica de Stop Loss individual
- ✅ Solo hay lógica de Global TP (líneas 702-760)
- ✅ Monitor loop: "Global TP only (no individual SL)" (línea 685)

**src/macro_strategy.py:**
- ❌ NO hay configuración de SL_PERCENT
- ✅ Solo hay configuración de GLOBAL_TP_PERCENT
- ✅ Comentarios actualizados: "NO STOP LOSS" (línea 15)

**Funciones de cierre de posiciones:**
1. `close_all_positions()` - Manual shutdown
2. `_close_all_positions_for_direction()` - Nunca se usa
3. `_close_all_positions_global_tp()` - Solo para Global TP

**Conclusión:** El código NO tiene lógica de Stop Loss.

---

## 🚨 Posible Causa del Problema

Si ves que tus posiciones se están cerrando automáticamente (pareciendo SL), hay **2 posibilidades**:

### Posibilidad 1: Órdenes STOP_MARKET en Binance (MÁS PROBABLE)

Es posible que haya órdenes STOP_MARKET activas en tu cuenta de Binance desde una versión anterior del código.

**Síntomas:**
- Posiciones se cierran automáticamente cuando el precio baja
- No hay logs de "GLOBAL TP TRIGGERED" antes del cierre
- Las posiciones se cierran individualmente (no todas a la vez)

**Solución:** Ejecutar el script de cancelación forzada

### Posibilidad 2: Global TP con PnL Negativo (MENOS PROBABLE)

Si el Global TP se dispara cuando el PnL total está en negativo (bug anterior).

**Síntomas:**
- Ves logs de "GLOBAL TP TRIGGERED"
- Pero el PnL total es negativo (ejemplo: -$0.04)
- Todas las posiciones se cierran a la vez

**Solución:** Esto ya fue corregido con el fix de TP calculation (wallet-based)

---

## 🛠️ Solución: Cancelar Órdenes STOP_MARKET

### Paso 1: Ejecutar Script de Cancelación Forzada

He creado un script que cancela **TODAS** las órdenes STOP_MARKET en tu cuenta:

```bash
cd C:\Users\je2al\Desktop\moonshot-bot
python scripts\force_cancel_all_stops.py
```

**El script hará:**
1. Conectarse a tu cuenta de Binance
2. Buscar TODAS las órdenes STOP_MARKET
3. Cancelarlas una por una
4. Reportar resultados

### Paso 2: Verificar Resultado

Después de ejecutar el script, deberías ver:

```
✅ ALL STOP_MARKET ORDERS CANCELLED
✅ NO STOP LOSS IS ACTIVE
```

### Paso 3: Reiniciar el Bot

El bot también cancela órdenes STOP_MARKET en el inicio (línea 201 de main.py):

```python
# Cancel any leftover STOP_MARKET orders
await self._cancel_all_stop_orders()
```

Pero es mejor ejecutar el script manualmente PRIMERO para asegurarte.

---

## 📋 Verificación Manual en Binance

Si quieres verificar manualmente en Binance:

### Opción 1: Binance Web UI

1. Ir a https://www.binance.com/en/futures/
2. Click en "Open Orders" (abajo a la derecha)
3. Buscar órdenes con tipo "Stop Limit" o "Stop Market"
4. Si ves alguna, cancelarla manualmente

### Opción 2: Binance API

```bash
# Ver todas las órdenes abiertas
curl -X GET "https://fapi.binance.com/fapi/v1/openOrders" \
  -H "X-MBX-APIKEY: YOUR_API_KEY"

# Filtrar por tipo STOP_MARKET
# Si ves alguna, usar el script para cancelar
```

---

## 🎯 Configuración Final del Bot

Después de cancelar las órdenes STOP_MARKET, tu bot tendrá:

```python
# SOLO Global TP - NO Stop Loss

LEVERAGE: 5x
MIN_MARGIN: $2.00 por posición
GLOBAL_TP: 50% del wallet (NO del margin)
STOP_LOSS: ❌ DESACTIVADO (solo Global TP)
POST_TP_COOLDOWN: 60 segundos
```

**Comportamiento esperado:**
- Posiciones se abren cuando macro señal es LONG o SHORT
- Posiciones permanecen abiertas hasta Global TP
- NO se cierran individualmente por pérdidas
- Solo se cierran TODAS a la vez cuando Global TP = 50% del wallet

---

## 🔄 Diferencia Entre Global TP y Stop Loss

### Global TP (ACTIVO)

```
Trigger: Total PnL / Wallet Balance >= 50%
Action: Cierra TODAS las posiciones a la vez
Cuando: Solo cuando el portafolio total está en +50% ganancia
Resultado: Ganancias realizadas
```

### Individual Stop Loss (DESACTIVADO)

```
Trigger: Posición individual en -10% (o cualquier threshold)
Action: Cierra UNA posición individual
Cuando: Cuando una posición pierde cierto %
Resultado: Pérdidas cortadas early
```

**Tu bot usa SOLO Global TP, NO Individual SL.**

---

## 📊 Ejemplo de Comportamiento Correcto

### Con $30 Wallet

```
APERTURA:
  15 posiciones × $2 margen = $30 total
  Notional: 15 × $10 = $150

ESCENARIO 1: Algunas posiciones suben, otras bajan
  Posición 1: +15% ($1.50 profit)
  Posición 2: +10% ($1.00 profit)
  Posición 3: +5% ($0.50 profit)
  ...
  Posición 13: -5% (-$0.50 loss)
  Posición 14: -8% (-$0.80 loss)
  Posición 15: -10% (-$1.00 loss)

  Total PnL: +$15 (ejemplo)
  Global PnL %: $15 / $30 = 50%

  ✅ GLOBAL TP TRIGGER - Cierra TODAS las 15 posiciones
  ❌ Individual SL NO se dispara (aunque posición 15 está -10%)

ESCENARIO 2: Portafolio en pérdida
  Total PnL: -$5
  Global PnL %: -$5 / $30 = -16.7%

  ❌ NO se cierra nada (no hay SL individual)
  ✅ Posiciones permanecen abiertas hasta:
     - Global TP se dispare (+50%)
     - O manual close
```

---

## 🚀 Pasos Siguientes

### 1. Cancelar Órdenes STOP_MARKET

```bash
python scripts\force_cancel_all_stops.py
```

Esperar resultado:
```
✅ ALL STOP_MARKET ORDERS CANCELLED
✅ NO STOP LOSS IS ACTIVE
```

### 2. Reiniciar el Bot

Después de cancelar las órdenes, reinicia el bot:

```bash
# Detener bot actual
# Reiniciar con configuración actualizada
```

### 3. Monitorear Comportamiento

**Lo que DEBERÍAS ver:**
- Posiciones se abren cuando macro señal cambia a LONG/SHORT
- Posiciones NO se cierran individualmente
- Solo se cierran TODAS cuando log muestra "GLOBAL TP TRIGGERED"

**Lo que NO deberías ver:**
- Posiciones cerrándose individualmente sin "GLOBAL TP TRIGGERED"
- Cierres automáticos cuando una posición está en pérdida
- Mensajes de "STOP LOSS" en los logs

### 4. Si el Problema Persiste

Si después de cancelar órdenes STOP_MARKET sigues viendo cierres automáticos:

1. **Revisar logs del bot:**
   - Buscar "GLOBAL TP TRIGGERED"
   - Si aparece, es Global TP (normal)
   - Si NO aparece, reportar el problema

2. **Verificar en Binance:**
   - Revisar historial de órdenes
   - Ver si hay nuevas órdenes STOP_MARKET
   - Confirmar que las cancelaciones fueron exitosas

3. **Reportar:**
   - Enviar logs específicos del cierre
   - Detalles de la posición que se cerró
   - Timestamp del evento

---

## 📚 Referencias de Código

### Cancelación de Órdenes STOP_MARKET

**Ubicación:** `main.py:123-155`

```python
async def _cancel_all_stop_orders(self):
    """Cancel all STOP_MARKET orders on Binance"""
    # Obtiene todas las órdenes abiertas
    open_orders = await self.data_feed.client.futures_get_open_orders()

    # Filtra STOP_MARKET
    stop_orders = [o for o in open_orders if o['type'] == 'STOP_MARKET']

    # Cancela cada una
    for order in stop_orders:
        await self.data_feed.client.futures_cancel_order(
            symbol=order['symbol'],
            orderId=order['orderId']
        )
```

**Llamada en inicio:** `main.py:201`

```python
await self._cancel_all_stop_orders()
```

### Monitor Loop - Solo Global TP

**Ubicación:** `main.py:684-768`

```python
async def _monitor_loop(self):
    """Monitor open positions - Global TP only (no individual SL)"""

    # Calcula PnL total de todas las posiciones
    for p in positions:
        # ... calcula PnL individual
        total_pnl += pnl

    # Calcula % basado en wallet (NO margin)
    wallet_balance = await self._get_wallet_balance()
    global_pnl_pct = (total_pnl / wallet_balance) * 100

    # Solo cierra si Global TP se dispara
    if global_pnl_pct >= self.config.GLOBAL_TP_PERCENT:
        await self._close_all_positions_global_tp(...)
```

**NO hay código de Individual SL.**

---

## ✅ Conclusión

1. **El código NO tiene Stop Loss logic** ✅
2. **Posibles órdenes STOP_MARKET en Binance** ⚠️
3. **Solución: Ejecutar script de cancelación** 🛠️
4. **Después: Solo Global TP activo** 🎯

**Próximo paso:** Ejecutar `python scripts\force_cancel_all_stops.py`

---

**Status:** ✅ DOCUMENTADO Y VERIFICADO
**Script disponible:** `scripts/force_cancel_all_stops.py`
**Próximo paso:** Cancelar órdenes STOP_MARKET en Binance
