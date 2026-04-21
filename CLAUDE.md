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

Il sistema usa una pipeline multi-agente sequenziale orchestrata da SupervisorAgent.

```text
DataFetcher (Yahoo Finance OHLCV: 1H, 4H, 1D)
    ↓
SupervisorAgent (agents/supervisor_agent.py)
    ├── Step 1: AgnoMacroExpert → macro sentiment + news
    ├── Step 1.5: SkillSelector → sceglie libri e tecniche per l’asset
    ├── Step 2: ContextExpanderAgent → ricerca semantica nei PDF della skills_library
    └── Steps 3-5: AgnoTechnicalTeam.analizza_specialista() × 4
        ├── Pattern Analyst
        ├── Trend Analyst
        ├── SR Analyst
        └── Volume Analyst ← filtro finale e veto se i volumi divergono
    ↓
Step 4: AgnoMacroExpert.sintetizza_verdetto()
    ↓
Report finale Markdown con Bias / Entry / SL / Target 1 / Target 2 oppure NO TRADE
```

## Throttling adattivo Groq

Il vecchio sleep fisso di 25 secondi è stato rimosso. Il sistema usa ora una logica adattiva per rispettare i rate limit Groq:
- legge gli header di risposta come remaining tokens e retry-after;
- applica retry esponenziale in caso di 429;
- non usa pause fisse tra le chiamate.

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
| Search | agents/context_expander_agent.py | Ricerca semantica nei PDF |
| Specialists | agents/specialists/*.py | Pattern, Trend, SR, Volume |
| Skills Lib | skills_library/ | Skill Agno dei 6 libri |
| Frontend | frontend/app_web.py | Flask UI e backtesting |
| Storage | storage/memory/trading_system.db | Memoria SQLite |

Aggiornato: 2026-04-21. Architettura V5, throttling adattivo Groq, skills audit 100%.