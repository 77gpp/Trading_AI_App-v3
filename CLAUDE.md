# CLAUDE.md — Trading_AI_App-v3 (Agno Desk V5)

## Avvio

```bash
source .venv/bin/activate
python3 app.py
python3 frontend/app_web.py
python3 agents/supervisor_agent.py
```

## Setup

```bash
pip install -r requirements.txt
```

.env (solo provider remoti):
```env
GEMINI_API_KEY=
GROQ_API_KEY=
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
```

Gemma4 locale @ http://localhost:8080 — no API key needed.

## Configurazione: Calibrazione.py

Sorgente verità unica. Controlli chiave:
- `LLM_PROVIDER`: gemma4 | qwen | gemini
- `GEMMA4_BASE_URL`: endpoint locale
- `MODEL_*`: ID modello per ruoli
- `AGENT_*_ENABLED`: on/off specialisti
- `TECH_*_CANDLES`: candele per timeframe
- `TEMPERATURE_*`: temperatura per ruolo
- `TECHNICAL_SKILLS_DIRS`: 6 directory skill
- `QWEN_THINKING_ENABLED`: toggle thinking mode

## Architettura V5

```
DataFetcher.get_mtf_data() → OHLCV: 1H · 4H · 1D
   ↓
SupervisorAgent.analizza_asset()
   ├─ [1] AgnoMacroExpert.analizza() → macro_sentiment
   ├─ [1.5] SkillSelector.select_tools() → skills_guidance
   ├─ [2] ContextExpanderAgent.search_knowledge() → knowledge_context
   ├─ [Indicatori] indicators_engine.compute() → RSI, MACD, SMA, EMA, Bollinger, ATR, OBV
   ├─ [Contesti] ContextBuilder → differenziati per specialista
   ├─ [3] 4 Specialisti (sequenza):
   │    ├─ PatternAgent (OHLCV + swing, no medie/oscillatori)
   │    ├─ TrendAgent (OHLCV + medie + oscillatori)
   │    ├─ SRAgent (OHLCV + Bollinger + ATR)
   │    └─ VolumeAgent (OHLCV + OBV + oscillatori, veto finale)
   └─ [4] AgnoMacroExpert.sintetizza_verdetto() → Bias · Entry · SL · TP1 · TP2
```

**Throttling Groq**: lettura header risposta (remaining tokens, retry-after). No fixed sleep 25s. Retry esponenziale su 429.

## Indicators Engine

```python
from indicators_engine import compute
indicators = compute(data_dict)  # {1h, 4h, 1d}
```

Indicatori: RSI 14, MACD (12/26/9), Stochastic (14/3), Williams %R, SMA (20/50/100/200), EMA (9/20/50/100), Bollinger (20/2), ATR 14, OBV, Swing.

Solo misure oggettive. Pattern + S/R → agenti.

## Context Builder

Filtri per specialista via `_AGENT_BLOCKS`:
```python
"pattern": {moving_averages: False, oscillators: False, ...}
"trend":   {moving_averages: True,  oscillators: True,  ...}
"sr":      {moving_averages: True,  oscillators: False, ...}
"volume":  {moving_averages: False, oscillators: True,  ...}
```

Uso:
```python
from context_builder import ContextBuilder
ctx_builder = ContextBuilder(data_dict, indicators)
ctx_per_agent = {
    "pattern": ctx_builder.build("pattern"),
    "trend":   ctx_builder.build("trend"),
    "sr":      ctx_builder.build("sr"),
    "volume":  ctx_builder.build("volume"),
}
```

## Skills Library

6 tech skills dirs. 485 tecniche audit 100%.

```bash
python3 agents/audit_skills_mapping.py
python3 agents/audit_skills_mapping.py --verbose
```

Due impl parallele:
- `agents/agno_technical_team.py`: fast (SupervisorAgent)
- `agents/specialists/*.py`: standalone + skills da Calibrazione

## Model Factory

```python
from agents/model_factory import get_model
get_model(model_id, temperature=...)
```

Gestisce Gemma4 · Groq/Qwen · Gemini trasparente.

## Frontend (Flask 5001)

- `frontend/api/backtesting.py`: job background, parse Entry/SL/TP
- `frontend/api/data.py`: OHLCV + news

Parser numerico: Italian + English notation.

## Lingua

Prompt agenti: "Rispondi sempre in italiano."
Report finale: italiano.

## File Structure

| Componente | File | Ruolo |
|---|---|---|
| Config | Calibrazione.py | Verità unica |
| CLI | app.py | Entry point |
| Core | agents/supervisor_agent.py | Controller |
| Macro | agents/agno_macro_expert.py | Macro + verdict |
| Skills | agents/skill_selector.py | Selezione + guidance |
| Indicators | indicators_engine.py | RSI, MACD, SMA, EMA, Bollinger, ATR, OBV |
| Context | context_builder.py | Contesti differenziati |
| Search | agents/context_expander_agent.py | Ricerca semantica PDF |
| Specialists | agents/specialists/*.py | Pattern, Trend, SR, Volume |
| Skills Lib | skills_library/ | 6 libri skill Agno |
| Frontend | frontend/app_web.py | Flask UI + backtesting |
| Storage | storage/memory/trading_system.db | SQLite |

---
Aggiornato: 2026-04-22. V5: indicators_engine + context_builder, throttling adattivo, audit 100%. 