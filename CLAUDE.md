# CLAUDE.md

Questo file fornisce guida completa a Claude Code per lavorare con il codice di questa repository Trading_AI_App-v3 (Agno Desk V5).

## Avvio Applicazione

```bash
source .venv/bin/activate
python3 app.py
python3 frontend/app_web.py
python3 agents/supervisor_agent.py
```

## Dipendenze

```bash
pip install -r requirements.txt
```

Nota: il pacchetto openai è richiesto per il supporto Gemma 4 locale via API compatibile OpenAI ed è incluso nelle dipendenze.

## Environment Variables

Crea un file .env nella root del progetto solo se usi provider remoti.

```env
GEMINI_API_KEY=
GROQ_API_KEY=
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
```

Nota: con LLM_PROVIDER impostato a gemma4 non servono API key; Gemma 4 gira localmente su http://localhost:8080.

## Configurazione Centrale: Calibrazione.py

Tutto il comportamento del sistema è controllato da questo unico file. Non hardcodare mai modelli, path o flag altrove.

Controlli chiave:
- LLM_PROVIDER: gemma4, qwen, gemini
- GEMMA4_BASE_URL: endpoint locale Gemma 4
- MODEL_*: ID modello per i vari ruoli
- AGENT_*_ENABLED: flag on/off per ogni agente specialista
- TECH_*_CANDLES: numero di candele per timeframe
- TEMPERATURE_*: temperatura per ruolo
- TECHNICAL_SKILLS_DIRS: lista delle 6 directory skill tecniche
- QWEN_THINKING_ENABLED: abilita o disabilita il thinking mode di Qwen

## Architettura V5

Il sistema usa una pipeline multi-agente sequenziale orchestrata da SupervisorAgent. Ogni step esegue con throttling adattivo Groq che legge il tempo di attesa reale dagli header di risposta.

### Flusso di Esecuzione Sequenziale

```
DataFetcher.get_mtf_data()
   │  Dati OHLCV: 1H · 4H · 1D (Yahoo Finance)
   │
   ▼
SupervisorAgent.analizza_asset()
   │
   ├─ [Step 1] AgnoMacroExpert.analizza()
   │     ├─ YFinance: prezzi real-time, variazione %, volumi
   │     ├─ DuckDuckGo: news web, sentiment
   │     ├─ AlpacaNews: notizie istituzionali
   │     ├─ Skill: macro-strategist (framework Dalio/Soros/Murphy)
   │     └─ → macro_sentiment (testo Markdown con Regime/Bias)
   │
   ├─ [Step 1.5] SkillSelector.select_tools()
   │     ├─ Input: nome_asset · macro_sentiment · ultimi 5 candles
   │     ├─ Catalogo: 485 tecniche da 6 libri
   │     ├─ Output: chosen_tools {pattern[], trend[], sr[], volume[]}
   │     └─ → skills_guidance (istruzioni per ogni specialista)
   │
   ├─ [Step 2] ContextExpanderAgent.search_knowledge()
   │     ├─ Gemini File API: ricerca semantica nei PDF dei libri
   │     └─ → knowledge_context (estratti rilevanti per l’asset)
   │
   ├─ [Preparazione Indicatori Tecnici Obiettivi]
   │     ├─ indicators_engine.compute(data_dict)
   │     └─ → RSI, MACD, Stochastic, SMA, EMA, Bollinger, ATR, OBV
   │
   ├─ [Preparazione Contesti Specializzati]
   │     ├─ ContextBuilder differenzia il contesto per ciascun specialista
   │     ├─ Pattern: OHLCV + swing (NO medie, NO oscillatori)
   │     ├─ Trend: OHLCV + medie + oscillatori
   │     ├─ SR: OHLCV + Bollinger + ATR + POC
   │     └─ Volume: OHLCV + OBV + oscillatori (NO medie)
   │
   ├─ [Step 3] I 4 Specialisti Tecnici (in sequenza)
   │     ├─ PatternAgent.analizza(ctx_pattern, macro_sentiment, skills_guidance)
   │     ├─ TrendAgent.analizza(ctx_trend, macro_sentiment, skills_guidance)
   │     ├─ SRAgent.analizza(ctx_sr, macro_sentiment, skills_guidance)
   │     └─ VolumeAgent.analizza(ctx_volume, macro_sentiment, skills_guidance, output_altri_3)
   │           ↑ FILTRO FINALE: veto se volume ≠ movimento
   │
   ├─ [Step 4] AgnoMacroExpert.sintetizza_verdetto()
   │     ├─ Riceve: macro_sentiment + output dei 4 specialisti
   │     ├─ Skill: trading-verdict-synthesizer (7 fasi, 14 no-trade filters)
   │     └─ → Bias · Entry · SL · Target 1 · Target 2
   │
   └─ Assemblaggio report Markdown finale
```

### Organigramma degli Agenti

```
┌─────────────────────────────────────────────────────┐
│         SUPERVISOR AGENT (Controller)               │
│    agents/supervisor_agent.py · SupervisorAgent     │
└─────┬──────────┬─────────────┬──────────┬───────────┘
      │          │             │          │
      ▼ Step 1   ▼ Step 1.5    ▼ Step 2  ▼ Step 3
  MACRO      SKILL        CONTEXT     TECHNICAL
  EXPERT     SELECTOR     EXPANDER    DESK (4)
      │          │             │          │
      └─────────────────────────┴──────────┴──→ [Step 4] VERDETTO
```

## Indicators Engine

Il file `indicators_engine.py` pre-calcola misure tecniche obiettive da dati OHLCV. Viene richiamato dopo SkillSelector e prima della preparazione dei contesti specializzati.

**Indicatori calcolati:**
- RSI 14, MACD (12/26/9), Stochastic (14/3), Williams %R
- SMA (20/50/100/200), EMA (9/20/50/100)
- Bollinger Bands (20/2), ATR 14
- OBV (On-Balance Volume), Swing Highs/Lows

**Principio:** Calcola solo misure oggettive, non interpretazioni. I pattern grafici e i livelli S/R sono delegati agli agenti.

**Utilizzo:**
```python
from indicators_engine import compute
indicators = compute(data_dict)  # data_dict = {1h, 4h, 1d}
```

Ogni specialista riceve subset di questi indicatori in base al suo dominio, non tutti.

## Context Builder

Il file `context_builder.py` assembla contesti differenziati per ogni specialista. Preserva l'indipendenza di giudizio filtrando i dati rilevanti per ciascun dominio.

**Strategie di filtraggio per specialista:**
```python
_AGENT_BLOCKS = {
    "pattern": {"moving_averages": False, "oscillators": False, "bollinger_atr": False, ...},
    "trend":   {"moving_averages": True,  "oscillators": True,  "bollinger_atr": True,  ...},
    "sr":      {"moving_averages": True,  "oscillators": False, "bollinger_atr": True,  ...},
    "volume":  {"moving_averages": False, "oscillators": True,  "bollinger_atr": True,  ...},
}
```

**Benefici della differenziazione:**
1. **Pattern Analyst**: OHLCV + swing patterns → massima indipendenza (no medie, no oscillatori)
2. **Trend Analyst**: OHLCV + medie + oscillatori → valuta forza direzionale
3. **SR Analyst**: OHLCV + Bollinger + ATR → mappa livelli senza momentum
4. **Volume Analyst**: OHLCV + OBV + oscillatori → filtro finale che valida gli altri (NO medie per indipendenza)

**Utilizzo:**
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

## Throttling adattivo Groq

Il vecchio sleep fisso di 25 secondi è stato rimosso. Il sistema usa ora una logica adattiva per rispettare i rate limit Groq:
- legge gli header di risposta come remaining tokens e retry-after;
- applica retry esponenziale in caso di 429;
- non usa pause fisse tra le chiamate.

**Impatto:** Prima ~150s overhead anche con basso token count, ora attesa proporzionale al rate limit reale.

## Skills Library

Ogni sottocartella della skills_library contiene un file SKILL.md con frontmatter Agno valido.

Le 6 skill tecniche principali sono condivise dai 4 specialisti e coprono 485 tecniche totali con audit completo al 100%.

Audit:
```bash
python3 agents/audit_skills_mapping.py
python3 agents/audit_skills_mapping.py --verbose
```

## Due Implementazioni del Team Tecnico

Esistono due implementazioni parallele:
- agents/agno_technical_team.py: usata da SupervisorAgent, più semplice e veloce;
- agents/specialists/*.py: versioni standalone con skills caricate da Calibrazione.TECHNICAL_SKILLS_DIRS.

## Model Factory

Usa sempre get_model(model_id, temperature=...) da agents/model_factory.py.
La factory gestisce in modo trasparente il passaggio tra Gemma4, Groq/Qwen e Gemini in base a Calibrazione.LLM_PROVIDER.

## Web Frontend

Flask gira su porta 5001.

Endpoint principali:
- frontend/api/backtesting.py: job background e parsing di Entry/SL/TP dal report;
- frontend/api/data.py: recupero OHLCV e news.

Il parser numerico deve gestire sia notazione italiana sia anglosassone.

## Lingua

Tutti i prompt degli agenti devono includere la direttiva: Rispondi sempre in italiano.

Il report finale deve essere sempre in italiano.

## File Structure

| Componente | File Principali | Ruolo |
|---|---|---|
| Config | Calibrazione.py | Sorgente di verità unica |
| CLI | app.py | Entry point CLI |
| Core | agents/supervisor_agent.py | Controller principale |
| Macro | agents/agno_macro_expert.py | Step macro e sintesi verdetto |
| Skills | agents/skill_selector.py | Selezione tecniche e guidance |
| Indicators | indicators_engine.py | Pre-calcola RSI, MACD, SMA, EMA, Bollinger, ATR, OBV |
| Context | context_builder.py | Assembla contesti differenziati per ogni specialista |
| Search | agents/context_expander_agent.py | Ricerca semantica nei PDF |
| Specialists | agents/specialists/*.py | Pattern, Trend, SR, Volume |
| Skills Lib | skills_library/ | Skill Agno dei 6 libri |
| Frontend | frontend/app_web.py | Flask UI e backtesting |
| Storage | storage/memory/trading_system.db | Memoria SQLite |

Aggiornato: 2026-04-22. Architettura V5 con indicators_engine + context_builder, throttling adattivo Groq, skills audit 100%.