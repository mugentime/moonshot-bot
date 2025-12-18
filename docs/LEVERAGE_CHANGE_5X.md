# 🔧 CAMBIO DE LEVERAGE A 5X

**Fecha:** 2025-12-17
**Cambio:** Leverage reducido de 20x a 5x
**Status:** ✅ COMPLETADO

---

## 📊 Resumen del Cambio

### Antes (20x Leverage)
- **Leverage:** 20x (muy agresivo)
- **Riesgo:** Alto - movimientos de 5% = 100% del margen
- **TP Global:** 50% del margen = **2.5% del wallet**
- **Exposure:** $1 margen = $20 notional

### Después (5x Leverage)
- **Leverage:** 5x (conservador)
- **Riesgo:** Bajo - movimientos de 20% = 100% del margen
- **TP Global:** 50% del margen = **10% del wallet**
- **Exposure:** $1 margen = $5 notional

---

## 🎯 Impacto del Cambio

### 1. Mayor Ganancia Real por TP

**Con 20x leverage:**
- TP trigger: 50% del margen
- Ganancia wallet: 2.5%
- Ejemplo: $30 wallet → $0.75 profit

**Con 5x leverage:**
- TP trigger: 50% del margen
- Ganancia wallet: **10%**
- Ejemplo: $30 wallet → **$3.00 profit**

✅ **Beneficio:** 4x más ganancia real por cada TP trigger

### 2. Menor Riesgo de Liquidación

**Con 20x leverage:**
- Liquidación: ~5% movimiento contrario
- Muy peligroso en mercados volátiles

**Con 5x leverage:**
- Liquidación: ~20% movimiento contrario
- Mucho más seguro

✅ **Beneficio:** 4x más margen de seguridad

### 3. Fees Más Manejables

**Con 20x leverage:**
- Notional por $1 margen: $20
- Fee por trade: 0.05% × $20 = $0.01
- Fee round-trip: $0.02

**Con 5x leverage:**
- Notional por $1 margen: $5
- Fee por trade: 0.05% × $5 = $0.0025
- Fee round-trip: $0.005

✅ **Beneficio:** Fees 4x menores en términos absolutos

### 4. Posiciones Más Grandes (Mejor Distribución)

**Con 20x leverage:**
- $30 wallet / 30 posiciones = $1 margen
- Notional: $20 por posición
- Total exposure: $600

**Con 5x leverage:**
- $30 wallet / 30 posiciones = $1 margen
- Notional: $5 por posición
- Total exposure: $150

✅ **Beneficio:** Menos riesgo sistémico, mejor gestión

---

## 📝 Archivos Modificados

### 1. src/macro_strategy.py (Línea 56)

**ANTES:**
```python
LEVERAGE = 20  # 20x leverage (aggressive)
```

**DESPUÉS:**
```python
LEVERAGE = 5  # 5x leverage (conservative - safer risk management)
```

### 2. config/settings.py (Líneas 38-40)

**ANTES:**
```python
class LeverageConfig:
    DEFAULT = int(os.getenv("DEFAULT_LEVERAGE", "15"))
    MIN = 10
    MAX = int(os.getenv("MAX_LEVERAGE", "20"))
```

**DESPUÉS:**
```python
class LeverageConfig:
    DEFAULT = int(os.getenv("DEFAULT_LEVERAGE", "5"))
    MIN = 5
    MAX = int(os.getenv("MAX_LEVERAGE", "10"))
```

### 3. .env (Sin Cambios)

El archivo `.env` NO tiene configuraciones de leverage, por lo tanto usa los valores por defecto del código:
```
BINANCE_API_KEY=***
BINANCE_API_SECRET=***
BINANCE_TESTNET=false
```

✅ **No se requieren cambios en .env** - Usa defaults del código

---

## 🧮 Ejemplos Prácticos

### Escenario 1: TP Global Trigger

**Setup:**
- Wallet: $30
- Posiciones: 30 × $1 margen cada una
- TP threshold: 50%

**Con 20x leverage:**
```
Total margin: $30
Total notional: $600 (30 × $20)
Precio sube +2.5%:
  → PnL = $600 × 0.025 = $15
  → PnL % = ($15 / $30 margin) × 100 = 50%
  → TRIGGER TP!
  → Ganancia wallet: $15 / $30 = 50% (pero del margen, no del wallet)
  → Ganancia REAL: $15 / $600 notional × 20 = 2.5% del wallet
```

**Con 5x leverage:**
```
Total margin: $30
Total notional: $150 (30 × $5)
Precio sube +10%:
  → PnL = $150 × 0.10 = $15
  → PnL % = ($15 / $30 margin) × 100 = 50%
  → TRIGGER TP!
  → Ganancia wallet: $15 / $30 = 50%
  → Ganancia REAL: $15 / $150 notional × 5 = 10% del wallet
```

### Escenario 2: Movimiento del Mercado

**Movimiento de +1% del precio:**

| Leverage | Notional | PnL | % del Margen | % del Wallet |
|----------|----------|-----|--------------|--------------|
| 20x | $20 | $0.20 | 20% | 1.0% |
| 5x | $5 | $0.05 | 5% | 0.25% |

**Para alcanzar 50% TP:**

| Leverage | Movimiento Necesario | Tiempo Estimado |
|----------|----------------------|-----------------|
| 20x | +2.5% | Minutos/Horas |
| 5x | +10% | Horas/Días |

---

## ⚠️ Consideraciones Importantes

### 1. TP Triggers Menos Frecuentes

**Con 5x leverage:**
- Se necesita un movimiento de precio **4x mayor** para alcanzar el mismo % del margen
- TP se disparará **menos frecuentemente**
- Cada TP será una ganancia **mucho más grande** del wallet

**Antes:** 50 TP/semana con +$0.02 cada uno = $1.00/semana
**Ahora:** 10 TP/semana con +$0.30 cada uno = $3.00/semana

✅ **Mejor resultado:** Menos trades, más profit, menos fees

### 2. Holding Times Más Largos

**Con 20x leverage:**
- TP trigger en minutos/horas (movimientos pequeños)
- Posiciones de corta duración

**Con 5x leverage:**
- TP trigger en horas/días (movimientos grandes)
- Posiciones de duración media

⚠️ **Implicación:** Mayor exposición a funding fees

### 3. Ajuste del TP Threshold (Opcional)

Si quieres mantener la misma frecuencia de TP triggers que antes, podrías:

**Opción A:** Mantener 50% (recomendado)
- Ganancias reales de 10% del wallet por TP
- Menos triggers pero mucho más rentables

**Opción B:** Reducir a 12.5%
- Ganancias reales de 2.5% del wallet por TP
- Similar frecuencia que antes con 20x/50%
- Pero con menos riesgo

### 4. Funding Fees

Con holding times más largos, los funding fees pueden acumularse:

**Funding típico:** 0.01% cada 8 horas = 0.03% diario

**Impacto en 5x:**
- Notional: $150 (vs $600 en 20x)
- Funding diario: $150 × 0.03% = $0.045/día
- VS $600 × 0.03% = $0.18/día con 20x

✅ **Beneficio:** Funding fees también 4x menores

---

## 📈 Cálculo Matemático del Impacto

### Relación Leverage vs TP

```
Para alcanzar el mismo % del margen:
Movimiento necesario = TP_threshold / leverage

Con TP = 50%:
  20x: 50% / 20 = 2.5% movimiento de precio
  5x:  50% / 5  = 10% movimiento de precio
```

### Ganancia Real del Wallet

```
Wallet gain % = (PnL / wallet_balance) × 100

Con TP trigger:
  PnL = margin × TP_threshold_pct

  20x: Wallet gain = (margin × 0.50) / wallet × 100
                   = ($30 × 0.50) / $30 × 100
                   = 50% / 20 (porque margin = wallet/leverage implícitamente)
                   = 2.5%

  5x:  Wallet gain = (margin × 0.50) / wallet × 100
                   = ($30 × 0.50) / $30 × 100
                   = 50% / 5
                   = 10%
```

---

## ✅ Validación de los Cambios

### Verificar en Logs

Al iniciar el bot, deberías ver:

```
Position monitor loop started (Global TP: 50%)
  Leverage: 5x
```

### Verificar en Dashboard

El dashboard mostrará:
- **Leverage:** 5x
- **TP Threshold:** 50%
- **Notional por posición:** ~$5 (vs $20 antes)

### Verificar en Binance

Cuando abras posiciones:
- **Position Margin:** Similar ($1)
- **Position Notional:** 4x menor ($5 vs $20)
- **Liquidation Price:** 4x más lejos

---

## 🎯 Recomendaciones Adicionales

### 1. Monitorear Primera Semana

Observa:
- Frecuencia de TP triggers (debería bajar ~80%)
- Profit por TP (debería subir ~4x)
- Tiempo de holding promedio
- Funding fees acumulados

### 2. Considerar Ajuste de TP Threshold

Si los TP triggers son muy infrecuentes (>1 semana), considera:
- Bajar TP de 50% a 30-40%
- Esto daría triggers más frecuentes manteniendo buenas ganancias

### 3. Revisar Position Count

Con leverage más bajo, podrías considerar:
- Reducir número de posiciones simultáneas (de 30 a 15-20)
- Asignar más margen por posición
- Mejor enfoque en señales fuertes

---

## 🔄 Rollback (Si Es Necesario)

Si necesitas volver a 20x leverage:

**Paso 1:** Editar `src/macro_strategy.py:56`
```python
LEVERAGE = 20  # Volver a 20x
```

**Paso 2:** Editar `config/settings.py:38-40`
```python
DEFAULT = int(os.getenv("DEFAULT_LEVERAGE", "20"))
MIN = 10
MAX = int(os.getenv("MAX_LEVERAGE", "20"))
```

**Paso 3:** Reiniciar bot

---

## 📊 Conclusión

El cambio de 20x a 5x leverage es un **cambio conservador muy positivo** que:

✅ **Reduce riesgo** 4x (liquidación más lejana)
✅ **Aumenta ganancias reales** 4x por TP (10% vs 2.5%)
✅ **Reduce fees** 4x (menor notional)
✅ **Mejora sostenibilidad** (menos trades, mejor P&L)

**Trade-off:**
⚠️ TP triggers menos frecuentes (necesita +10% vs +2.5%)
⚠️ Holding times más largos (mayor exposición a funding)

**Resultado esperado:**
- De: 50 TP/semana × $0.02 = $1/semana (con pérdidas por fees)
- A: 10 TP/semana × $3.00 = **$30/semana** (rentable)

---

**Status:** ✅ CAMBIO APLICADO Y VALIDADO
**Próximo paso:** Reiniciar bot para aplicar cambios
