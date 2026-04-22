# Context Filtering Guide

**Aggiornato:** 2026-04-22  
**Responsabile:** context_builder.py

---

## Introduzione

Nella Architettura V5, ogni specialista riceve un **contesto personalizzato**, non identico. Questo preserva l'indipendenza di giudizio e riduce i bias derivanti da strumenti non rilevanti al suo dominio.

Il filtraggio è gestito da `context_builder.py` tramite la tabella `_AGENT_BLOCKS`.

---

## La Tabella _AGENT_BLOCKS

```python
_AGENT_BLOCKS = {
    "pattern": {
        "moving_averages": False,    # NO medie mobili
        "oscillators": False,         # NO oscillatori (RSI, MACD, etc.)
        "bollinger_atr": False,      # NO Bollinger, ATR
        "volume_metrics": False,      # NO OBV, POC
        "swing_structure": True,      # SI swing points (indipendenza massima)
    },
    
    "trend": {
        "moving_averages": True,      # SI medie (SMA, EMA)
        "oscillators": True,          # SI oscillatori (RSI, MACD, Stochastic)
        "bollinger_atr": True,       # SI Bollinger, ATR
        "volume_metrics": False,      # NO medie peso volume (indipendenza)
        "swing_structure": True,      # SI swing points
    },
    
    "sr": {
        "moving_averages": True,      # SI medie (per Pivots, Fibonacci)
        "oscillators": False,         # NO oscillatori (indipendenza dai livelli)
        "bollinger_atr": True,       # SI Bollinger, ATR
        "volume_metrics": True,      # SI POC (Point of Control)
        "swing_structure": True,      # SI swing points
    },
    
    "volume": {
        "moving_averages": False,     # NO medie (massima indipendenza)
        "oscillators": True,          # SI oscillatori (per validare momentum)
        "bollinger_atr": True,       # SI Bollinger, ATR
        "volume_metrics": True,      # SI OBV, POC (core del dominio)
        "swing_structure": False,     # NO swing (focus su effort)
    },
}
```

---

## Strategie di Filtraggio Dettagliate

### Pattern Analyst — Minimalista

**Dati Ricevuti:**
```
├─ OHLCV (prezzi apertura/high/low/chiusura/volume)
├─ Swing Highs/Lows (punti di inversione principale)
└─ Niente altro
```

**Logica:**
- Identifica **solo** candele e pattern grafici puri
- Non vede oscillatori che potrebbero condizionare il giudizio
- Non vede medie che potrebbero distogliere dal pattern

**Esempio di contesto ricevuto:**
```
Ultimo 50 candles:
Date     Open   High   Low    Close  Volume
2026-04-22 100.5  102.3  100.2  101.8  1.2M
2026-04-21 101.0  101.5  99.8   100.5  0.9M
...

Swing Points:
- High: 102.8 (2026-04-20)
- Low: 99.5 (2026-04-21)
```

**Benefici:**
✓ Massima indipendenza da indicatori condizionanti  
✓ Analisi puramente tecnica su formazioni grafiche  
✓ Riduci viés da medie mobili


### Trend Analyst — Full Indicators

**Dati Ricevuti:**
```
├─ OHLCV
├─ Moving Averages (SMA 20/50/100/200, EMA 9/20/50/100)
├─ Oscillatori (RSI 14, MACD, Stochastic)
├─ Bollinger Bands (20/2), ATR 14
├─ Swing Highs/Lows
└─ Niente volume metrics
```

**Logica:**
- Valuta **struttura direzionale** e **momentum** primario
- Vede tutti gli strumenti per trend
- NON vede OBV/POC (delegato al Volume Analyst)

**Esempio di contesto ricevuto:**
```
Technical Indicators:
- SMA 200: 99.5 (prezzo SOPRA → rialzista)
- RSI 14: 72.3 (ipercomprato)
- MACD: positivo con momentum in calo

Struttura:
- Trend primario: Rialzista (prezzo > SMA 200)
- Momentum: In perdita di forza (RSI alto, MACD momentum calo)
```

**Benefici:**
✓ Completa visione del trend primario  
✓ Momentum oscillatori per confermare forza  
✓ Validazione multi-timeframe via medie mobili


### SR Analyst — Supporti e Resistenze

**Dati Ricevuti:**
```
├─ OHLCV
├─ Moving Averages (per Fibonacci, Pivot, livelli dinamici)
├─ Bollinger Bands, ATR, POC (Point of Control)
├─ Swing Highs/Lows
└─ NON oscillatori (indipendenza da momentum)
```

**Logica:**
- Mappa **livelli statici e dinamici** di supporto/resistenza
- Utilizza Fibonacci, Pivot Points, Zone di domanda/offerta
- NON vede oscillatori (per evitare contaminazione da momentum)

**Esempio di contesto ricevuto:**
```
Support/Resistance Levels:
- Fibonacci 61.8%: 99.2 (resist)
- Pivot Weekly: 100.0 (support)
- Bollinger Upper: 102.1 (resist)
- Swing High: 102.8 (resist critica)
- POC (Volume Profile): 100.3 (support dinamico)

Confluenza (3+ metodi): 
- 100.0-100.3: SUPPORTO CRITICO
- 102.1-102.8: RESISTENZA CRITICA
```

**Benefici:**
✓ Mappa completa livelli senza distorsione da oscillatori  
✓ Confluenza multi-metodo per validare criticalità  
✓ Utilizzo POC per zone di volume


### Volume Analyst — Filtro Finale (VETO Power)

**Dati Ricevuti:**
```
├─ OHLCV
├─ Volume Metrics (OBV, POC, profilo volume)
├─ Oscillatori (per validare momentum sforzo)
├─ Bollinger Bands, ATR
└─ NON Moving Averages (massima indipendenza)
```

**Input Speciali:**
```
├─ Output REALI di Pattern Analyst
├─ Output REALI di Trend Analyst
├─ Output REALI di SR Analyst
└─ (non solo i nomi, ma il testo completo)
```

**Logica:**
- Valida se i segnali degli altri 3 specialisti sono **supportati da volume**
- Se MOVIMENTO ≠ SFORZO → **RISCHIO ELEVATO** (bandiera rossa)
- Ha **veto power** sugli altri: può dichiarare "NO TRADE"

**Esempio di contesto ricevuto:**
```
Pattern Analyst dice: Engulfing rialzista rilevato
Trend Analyst dice: SMA 200 rialzista, RSI 72

Volume Analysis:
- OBV: CALO (divergenza!) ← RISCHIO
- POC: 100.3 (volume concentrato al supporto)
- Sforzo: BASSO rispetto al movimento

VERDETTO VOLUME: ⚠️ RISCHIO ELEVATO
"Il pattern e il trend concordano, ma il volume non supporta.
Divergenza sforzo/movimento = ingegneria ribassista potenziale."
```

**Benefici:**
✓ Filtro finale che evita false breakouts  
✓ Validazione incrociata vs altri specialisti  
✓ Indipendenza da medie mobili


---

## Pattern di Filtraggio Logico

### Indipendenza Reciproca

```
Pattern        ← OHLCV + Swing (NO contamination)
   ↑
   │ (verifica con)
   │
Volume ← OHLCV + Volume metrics + Output degli altri
   │
   ├─ vede Pattern output ma NON è condizionato da medie
   └─ può dichiare RISCHIO se sforzo ≠ movimento
   
Trend          ← OHLCV + Medie + Oscillatori (NO volume)
   ↑
   │ (valida con)
   │
SR             ← OHLCV + Livelli + Bollinger + POC (NO osc)
```

### Regola del "NO Medie per Volume"

Perché Volume Analyst **non vede medie mobili**?

1. **Indipendenza:** Volume Analyst valuta lo **sforzo reale**, non la **direzione percepita**
2. **Evita Bias:** Medie mobili colorerebbero il giudizio del volume (trend-biased)
3. **Filtro Obiettivo:** OBV e POC sono sufficienti per validare

Esempio pratico:
```
Scenario A: Trend rialzista (SMA 200 up), ma OBV cala
→ Pattern/Trend dicono "compra", ma Volume dice "divergenza"
→ Volume può dichiarare RISCHIO

Se Volume vedesse la SMA 200 up, potrebbe essere influenced
a ignorare la divergenza OBV. Quindi: NO medie per Volume.
```

---

## Implementazione in context_builder.py

```python
class ContextBuilder:
    def __init__(self, data_dict, indicators):
        self.data_dict = data_dict  # {1h, 4h, 1d} OHLCV
        self.indicators = indicators  # RSI, MACD, SMA, EMA, etc.
    
    def build(self, domain):
        """Assembla contesto differenziato per dominio."""
        base_context = self._build_ohlcv(self.data_dict)
        
        blocks = _AGENT_BLOCKS[domain]
        if blocks["moving_averages"]:
            base_context += self._extract_moving_averages()
        if blocks["oscillators"]:
            base_context += self._extract_oscillators()
        if blocks["bollinger_atr"]:
            base_context += self._extract_bollinger_atr()
        if blocks["volume_metrics"]:
            base_context += self._extract_volume_metrics()
        if blocks["swing_structure"]:
            base_context += self._extract_swing_structure()
        
        return base_context
```

---

## Checklist per Nuovi Specialisti

Se si aggiunge un nuovo specialista (es. Market Profile Analyst), definire:

1. **Dati che riceve** (specificare _AGENT_BLOCKS)
2. **Dati che NON riceve** (specificare l'indipendenza)
3. **Input speciali** (es. output di altri)
4. **Ruolo nel verdetto finale** (supporta, valida, ha veto?)

Esempio:
```python
"market_profile": {
    "moving_averages": False,      # Indipendenza
    "oscillators": False,           # Indipendenza
    "bollinger_atr": False,        # Indipendenza
    "volume_metrics": True,        # Core del dominio
    "swing_structure": True,       # Livelli grafici
}
```

---

## Validazione

Eseguire audit per verificare coerenza filtraggio:

```bash
python3 agents/audit_context_filtering.py
```

Output atteso:
```
✅ Pattern Analyst: OHLCV + swing (NO medie, NO osc)
✅ Trend Analyst: OHLCV + medie + oscillatori
✅ SR Analyst: OHLCV + medie (NO osc) + Bollinger + ATR + POC
✅ Volume Analyst: OHLCV + medie (NO) + oscillatori + volume metrics
✅ Indipendenza reciproca: VERIFICATA
```

---

**Principio Fondamentale:**  
Ogni specialista riceve SOLO i dati rilevanti al suo dominio, preservando l'indipendenza di giudizio e riducendo i bias.
