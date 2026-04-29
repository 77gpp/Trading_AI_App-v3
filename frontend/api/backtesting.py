"""
api/backtesting.py — Endpoint Flask per il Backtesting AI.

Questo modulo gestisce il flusso principale del backtesting:
1. POST /api/backtest/run    → Avvia l'analisi in background (restituisce un job_id)
2. GET  /api/backtest/status → Controlla lo stato (running/done) e recupera il report
3. POST /api/backtest/projection → Calcola la proiezione statistica futura

L'analisi viene eseguita in un thread separato per non bloccare il server.
Un dizionario in memoria (JOBS) mantiene lo stato di ogni analisi avviata.
"""

import sys
import os
import re
import uuid
import threading
import json
import time
from datetime import datetime, timedelta

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from flask import Blueprint, request, jsonify
from loguru import logger
from .data import calculate_volume_profile
import Calibrazione

backtesting_bp = Blueprint("backtesting", __name__)

# ------------------------------------------------------------------
# Storage in-memory degli job avviati
# job_id → {status, report, error, started_at, config}
# ------------------------------------------------------------------
JOBS: dict = {}
CANCELLED_JOBS: set = set()

# ------------------------------------------------------------------
# ENDPOINT 1: Avvio Analisi Backtesting
# ------------------------------------------------------------------
@backtesting_bp.route("/run", methods=["POST"])
def run_backtest():
    """
    Body JSON:
      {
        "symbol":           "GC=F",
        "start":            "2025-01-01",
        "end":              "2025-03-28",
        "projection_days":  Calibrazione.DEFAULT_PROJECTION_DAYS,
        "interval":         "1d",
        "calibrazione": {
          "LLM_PROVIDER":            "gemma4",
          "MACRO_ANALYSIS_DAYS":     10,
          "ALPACA_NEWS_LIMIT":       15,
          "DUCKDUCKGO_NEWS_LIMIT":   10,
          "AGENT_MACRO_ENABLED":     true,
          "AGENT_PATTERN_ENABLED":   true,
          "AGENT_TREND_ENABLED":     true,
          "AGENT_SR_ENABLED":        true,
          "AGENT_VOLUME_ENABLED":    true
        }
      }

    Restituisce:
      { "job_id": "uuid-...", "status": "started" }
    """
    body = request.get_json()
    if not body:
        return jsonify({"error": "Body JSON richiesto"}), 400

    symbol          = body.get("symbol", "GC=F")
    start           = body.get("start", "")
    end             = body.get("end", "")
    projection_days = int(body.get("projection_days", Calibrazione.DEFAULT_PROJECTION_DAYS))
    interval        = body.get("interval", "1d")
    calibrazione    = body.get("calibrazione", {})

    if not start or not end:
        return jsonify({"error": "Parametri start e end obbligatori"}), 400

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status":     "running",
        "report":     None,
        "error":      None,
        "started_at": datetime.now().isoformat(),
        "config": {
            "symbol":          symbol,
            "start":           start,
            "end":             end,
            "projection_days": projection_days,
            "interval":        interval
        }
    }

    thread = threading.Thread(
        target=_run_analysis_thread,
        args=(job_id, symbol, start, end, projection_days, calibrazione),
        daemon=True
    )
    thread.start()

    logger.info(f"[BACKTEST] Job {job_id} avviato per {symbol} ({start}→{end})")
    return jsonify({"job_id": job_id, "status": "started"})


# ------------------------------------------------------------------
# ENDPOINT 2: Stato del Job
# ------------------------------------------------------------------
@backtesting_bp.route("/status/<job_id>", methods=["GET"])
def get_status(job_id: str):
    """
    Restituisce lo stato corrente del job:
      - running : analisi in corso
      - done    : analisi completata
      - error   : qualcosa è andato storto
    """
    if job_id not in JOBS:
        return jsonify({"error": "Job non trovato"}), 404

    job = JOBS[job_id]
    response = {
        "job_id": job_id,
        "status": job["status"],
    }

    if job["status"] == "done":
        response["report"]         = job["report"]
        response["projection"]     = job.get("projection", {})
        response["config"]         = job["config"]
        response["trade_setup"]    = job.get("trade_setup", {})
        response["chosen_tools"]   = job.get("chosen_tools", {})
        response["outcome_result"] = job.get("outcome_result")  # None se verifica ancora in corso

    if job["status"] == "error":
        response["error"] = job["error"]

    return jsonify(response)


# ------------------------------------------------------------------
# ENDPOINT 2.5: Cancellazione Job
# ------------------------------------------------------------------
@backtesting_bp.route("/cancel/<job_id>", methods=["POST"])
def cancel_job(job_id: str):
    if job_id not in JOBS:
        return jsonify({"error": "Job non trovato"}), 404

    if JOBS[job_id]["status"] not in ["running"]:
        return jsonify({"info": "Il job non è in esecuzione", "status": JOBS[job_id]["status"]})

    CANCELLED_JOBS.add(job_id)
    JOBS[job_id]["status"] = "cancelled"

    logger.warning(f"[BACKTEST] Job {job_id} annullato dall'utente.")
    return jsonify({"job_id": job_id, "status": "cancelled"})


# ------------------------------------------------------------------
# ENDPOINT 3: Proiezione Statistica (Lightweight, no AI)
# ------------------------------------------------------------------
@backtesting_bp.route("/projection", methods=["POST"])
def get_projection():
    """
    Calcola una proiezione statistica del prezzo usando EMA + deviazione standard.

    Body JSON:
      { "symbol": "GC=F", "end": "2025-03-28", "days": 30, "interval": "1d" }
    """
    body   = request.get_json()
    symbol = body.get("symbol", "GC=F")
    end    = body.get("end", "")
    days   = int(body.get("days", Calibrazione.DEFAULT_PROJECTION_DAYS))

    try:
        import yfinance as yf
        import numpy as np
        import pandas as pd

        df = yf.download(symbol, period="90d", interval="1d", auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        closes = df["Close"].values.flatten().astype(float)
        if len(closes) < 10:
            return jsonify({"error": "Dati insufficienti per la proiezione"}), 400

        alpha   = 2 / (20 + 1)
        ema     = closes[-1]
        ema_arr = []
        for c in closes[-20:]:
            ema = alpha * c + (1 - alpha) * ema
            ema_arr.append(ema)

        last_ema   = ema_arr[-1]
        trend_step = (ema_arr[-1] - ema_arr[0]) / len(ema_arr)
        std_dev    = float(np.std(closes[-20:]))
        last_dt    = df.index[-1].to_pydatetime()

        projection = []
        for i in range(1, days + 1):
            proj_dt    = last_dt + timedelta(days=i)
            proj_price = last_ema + trend_step * i
            projection.append({
                "time":  int(proj_dt.timestamp()),
                "value": round(float(proj_price), 4),
                "upper": round(float(proj_price + std_dev * 1.5), 4),
                "lower": round(float(proj_price - std_dev * 1.5), 4)
            })

        return jsonify({"projection": projection})

    except Exception as e:
        logger.error(f"[PROJECTION] Errore: {e}")
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# LISTA JOB (per debug)
# ------------------------------------------------------------------
@backtesting_bp.route("/jobs", methods=["GET"])
def list_jobs():
    return jsonify({
        jid: {
            "status":     j["status"],
            "started_at": j["started_at"],
            "config":     j["config"]
        } for jid, j in JOBS.items()
    })


# ------------------------------------------------------------------
# STORICO ANALISI — Carica un'analisi dal performance DB per la UI
# ------------------------------------------------------------------
@backtesting_bp.route("/history", methods=["GET"])
def list_history():
    """Lista delle analisi storiche salvate (max 50 più recenti)."""
    import sqlite3 as _sqlite3
    db_path = os.path.join(ROOT_DIR, "storage", "memory", "performance.db")
    if not os.path.exists(db_path):
        return jsonify({"items": [], "total": 0})
    try:
        conn = _sqlite3.connect(db_path)
        conn.row_factory = _sqlite3.Row
        rows = conn.execute("""
            SELECT a.id, a.symbol, a.market_type, a.start_date, a.end_date,
                   a.analysis_date, a.direction, a.entry, a.stop_loss,
                   a.take_profit_1, a.take_profit_2, a.last_price,
                   a.parse_error, a.llm_provider,
                   t.outcome, t.pnl_percent, t.days_to_entry, t.days_to_exit,
                   t.forecast_error_pct, t.direction_correct
            FROM analyses a
            LEFT JOIN trade_outcomes t ON a.id = t.analysis_id
            ORDER BY a.analysis_date DESC
            LIMIT 50
        """).fetchall()
        total = conn.execute("SELECT COUNT(*) as n FROM analyses").fetchone()["n"]
        conn.close()
        return jsonify({"items": [dict(r) for r in rows], "total": total})
    except Exception as e:
        logger.error(f"[HISTORY] Errore lista: {e}")
        return jsonify({"items": [], "total": 0, "error": str(e)})


@backtesting_bp.route("/history/<analysis_id>", methods=["GET"])
def get_historical_analysis(analysis_id: str):
    """
    Restituisce i dati completi di un'analisi storica per il ricaricamento nella UI.
    Include: report_markdown, trade_setup ricostruito, proiezione ricalcolata, outcome.
    """
    import sqlite3 as _sqlite3
    db_path = os.path.join(ROOT_DIR, "storage", "memory", "performance.db")
    if not os.path.exists(db_path):
        return jsonify({"error": "Nessun dato storico disponibile"}), 404

    try:
        conn = _sqlite3.connect(db_path)
        conn.row_factory = _sqlite3.Row
        row     = conn.execute("SELECT * FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        outcome = conn.execute("SELECT * FROM trade_outcomes WHERE analysis_id=?", (analysis_id,)).fetchone()
        conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not row:
        return jsonify({"error": "Analisi non trovata"}), 404

    row = dict(row)

    trade_setup = {
        "direction":         row.get("direction"),
        "entry":             row.get("entry"),
        "stop_loss":         row.get("stop_loss"),
        "take_profit_1":     row.get("take_profit_1"),
        "take_profit_2":     row.get("take_profit_2"),
        "last_price":        row.get("last_price"),
        "ai_forecast_price": row.get("ai_forecast_price"),
        "ai_forecast_upper": row.get("ai_forecast_upper"),
        "ai_forecast_lower": row.get("ai_forecast_lower"),
        "ai_forecast_bias":  row.get("ai_forecast_bias"),
        "ai_forecast_entry": row.get("ai_forecast_entry"),
        "ai_forecast_sl":    row.get("ai_forecast_sl"),
        "ai_forecast_tp":    row.get("ai_forecast_tp"),
        "parse_error":       bool(row.get("parse_error", 0)),
    }

    proj_days = 30
    if row.get("projection_end_date") and row.get("end_date"):
        try:
            proj_days = (
                datetime.strptime(row["projection_end_date"], "%Y-%m-%d") -
                datetime.strptime(row["end_date"], "%Y-%m-%d")
            ).days
        except Exception:
            proj_days = 30

    projection = {}
    try:
        import yfinance as yf
        import pandas as pd
        symbol = row["symbol"]
        df_1d = yf.download(
            symbol,
            start=row["start_date"],
            end=row["end_date"],
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
        if isinstance(df_1d.columns, pd.MultiIndex):
            df_1d.columns = df_1d.columns.get_level_values(0)
        if not df_1d.empty:
            ai_price = trade_setup.get("ai_forecast_price") or trade_setup.get("ai_forecast_tp")
            projection = _compute_projection(
                df_1d, proj_days,
                ai_price=ai_price,
                ai_upper=trade_setup.get("ai_forecast_upper"),
                ai_lower=trade_setup.get("ai_forecast_lower"),
            )
    except Exception as e:
        logger.warning(f"[HISTORY] Proiezione non disponibile per {analysis_id}: {e}")

    return jsonify({
        "analysis_id": analysis_id,
        "report":      row.get("report_markdown"),
        "trade_setup": trade_setup,
        "projection":  projection,
        "outcome":     dict(outcome) if outcome else None,
        "config": {
            "symbol":          row["symbol"],
            "start":           row.get("start_date", ""),
            "end":             row.get("end_date", ""),
            "projection_days": proj_days,
            "market_type":     row.get("market_type", ""),
            "llm_provider":    row.get("llm_provider", ""),
            "analysis_date":   row.get("analysis_date", ""),
        }
    })


# ------------------------------------------------------------------
# FUNZIONE INTERNA: Thread di Analisi
# ------------------------------------------------------------------
def _run_analysis_thread(job_id: str, symbol: str, start: str, end: str,
                          projection_days: int, calibrazione_override: dict):
    """
    Eseguita in un thread separato. Flusso:
    1. Download OHLCV  (yfinance)
    2. Volume Profile
    3. SupervisorAgent → report_markdown + chosen_tools
    4. _extract_trade_setup (con last_price per validazione interna)
    5. _compute_projection  (ancorata all'AI se il prezzo è plausibile)
    6. save_analysis        (persistenza su performance.db)
    7. verify_trade_outcome (in background: verifica Entry/SL/TP con dati reali)
    """
    try:
        import Calibrazione
        _apply_calibrazione_override(calibrazione_override)

        logger.info(f"[BACKTEST THREAD] Avvio analisi {symbol} ({start}→{end})")

        import yfinance as yf
        import pandas as pd

        df_1d = yf.download(symbol, start=start, end=end, interval="1d", auto_adjust=True)

        if job_id in CANCELLED_JOBS:
            logger.info(f"[BACKTEST THREAD] Job {job_id} interrotto prima del download 1h.")
            return

        df_1h = yf.download(symbol, start=start, end=end, interval="1h", auto_adjust=True)

        if isinstance(df_1d.columns, pd.MultiIndex):
            df_1d.columns = df_1d.columns.get_level_values(0)
        if isinstance(df_1h.columns, pd.MultiIndex):
            df_1h.columns = df_1h.columns.get_level_values(0)

        df_4h = df_1h.resample("4h").agg({
            "Open": "first", "High": "max",
            "Low": "min", "Close": "last", "Volume": "sum"
        }).dropna()

        data_dict = {"1h": df_1h, "4h": df_4h, "1d": df_1d}

        # Proiezione statistica (fallback iniziale)
        projection = _compute_projection(df_1d, projection_days)
        last_price = projection.get("last_price", 0)

        projection_end_date = (
            datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=projection_days)
        ).isoformat()

        if job_id in CANCELLED_JOBS:
            logger.info(f"[BACKTEST THREAD] Job {job_id} interrotto prima del SupervisorAgent.")
            return

        vol_profile = calculate_volume_profile(df_1d)

        from agents.supervisor_agent import SupervisorAgent
        supervisore = SupervisorAgent()
        report_markdown, chosen_tools = supervisore.analizza_asset(
            data_dict,
            symbol,
            start_date=start,
            end_date=end,
            projection_end_date=projection_end_date,
            volume_profile=vol_profile,
        )

        # Estrazione setup con last_price per validazione interna dei prezzi AI
        trade_setup = _extract_trade_setup(report_markdown, last_price=last_price)

        # Selezione prezzo AI: prima Prezzo Centrale, poi Target Proiezione come fallback.
        # Entrambi già validati internamente in _extract_trade_setup, quindi se sono presenti
        # sono già stati considerati plausibili rispetto a last_price.
        ai_price_raw = trade_setup.get("ai_forecast_price") or trade_setup.get("ai_forecast_tp")
        if ai_price_raw:
            logger.info(
                f"[BACKTEST THREAD] Previsione AI trovata: {ai_price_raw} "
                f"(last_price={last_price}) — ricalcolo proiezione ancorata."
            )
            projection = _compute_projection(
                df_1d, projection_days,
                ai_price=ai_price_raw,
                ai_upper=trade_setup.get("ai_forecast_upper"),
                ai_lower=trade_setup.get("ai_forecast_lower"),
            )
        else:
            logger.info(
                f"[BACKTEST THREAD] Previsione AI non trovata o scartata — "
                "mantengo proiezione statistica."
            )

        # ── Aggiunge last_price nel trade_setup per il frontend ──────────────
        trade_setup["last_price"] = last_price

        JOBS[job_id].update({
            "status":         "done",
            "report":         report_markdown,
            "projection":     projection,
            "volume_profile": vol_profile,
            "trade_setup":    trade_setup,
            "chosen_tools":   chosen_tools
        })

        logger.success(f"[BACKTEST THREAD] Job {job_id} completato!")

        # ── Step 6: Salvataggio su Performance DB ─────────────────────────────
        try:
            from api.performance import save_analysis, verify_trade_outcome
            saved = save_analysis(
                job_id              = job_id,
                symbol              = symbol,
                start               = start,
                end                 = end,
                trade_setup         = trade_setup,
                chosen_tools        = chosen_tools,
                projection_end_date = projection_end_date,
                report_markdown     = report_markdown,
            )

            # ── Step 7: Verifica outcome in thread separato ───────────────────
            # La verifica scarica dati reali post end_date → non blocca il job
            if saved:
                verify_thread = threading.Thread(
                    target=_verify_outcome_background,
                    args=(job_id, symbol),
                    daemon=True
                )
                verify_thread.start()
        except Exception as e:
            logger.warning(f"[BACKTEST THREAD] Performance save/verify non critico: {e}")

    except Exception as e:
        logger.error(f"[BACKTEST THREAD] Errore nel job {job_id}: {e}")
        JOBS[job_id].update({"status": "error", "error": str(e)})


def _verify_outcome_background(job_id: str, symbol: str):
    """
    Esegue il Trade Outcome Verifier in background e aggiorna il job
    con il risultato (outcome_result) quando disponibile.
    """
    try:
        from api.performance import verify_trade_outcome
        logger.info(f"[VERIFIER BG] Avvio verifica outcome per {symbol} ({job_id})")
        result = verify_trade_outcome(job_id)
        # Aggiorna il job in-memory con l'esito
        if job_id in JOBS:
            JOBS[job_id]["outcome_result"] = result
            logger.success(
                f"[VERIFIER BG] Outcome per {symbol}: "
                f"{result.get('outcome','N/D')} | P&L: {result.get('pnl_percent','N/D')}%"
            )
    except Exception as e:
        logger.warning(f"[VERIFIER BG] Errore non critico per {job_id}: {e}")


_AGENT_MODEL_MAP = {
    "macro_expert":      "MODEL_MACRO_EXPERT",
    "tech_orchestrator": "MODEL_TECH_ORCHESTRATOR",
    "tech_specialists":  "MODEL_TECH_SPECIALISTS",
    "skill_selector":    "MODEL_SKILL_SELECTOR",
    "knowledge_search":  "MODEL_KNOWLEDGE_SEARCH",
}

_CALIB_SCALAR_MAP = {
    "LLM_PROVIDER":              "LLM_PROVIDER",
    "QWEN_THINKING_ENABLED":     "QWEN_THINKING_ENABLED",
    "DEFAULT_PROJECTION_DAYS":   "DEFAULT_PROJECTION_DAYS",
    "ALPACA_NEWS_LIMIT":         "ALPACA_NEWS_LIMIT",
    "DUCKDUCKGO_NEWS_LIMIT":     "DUCKDUCKGO_NEWS_LIMIT",
    "AGENT_MACRO_ENABLED":       "AGENT_MACRO_ENABLED",
    "AGENT_PATTERN_ENABLED":     "AGENT_PATTERN_ENABLED",
    "AGENT_TREND_ENABLED":       "AGENT_TREND_ENABLED",
    "AGENT_SR_ENABLED":          "AGENT_SR_ENABLED",
    "AGENT_VOLUME_ENABLED":      "AGENT_VOLUME_ENABLED",
    "TEMPERATURE_KNOWLEDGE_SEARCH":  "TEMPERATURE_KNOWLEDGE_SEARCH",
    "TEMPERATURE_MACRO_EXPERT":      "TEMPERATURE_MACRO_EXPERT",
    "TEMPERATURE_TECH_ORCHESTRATOR": "TEMPERATURE_TECH_ORCHESTRATOR",
    "TEMPERATURE_TECH_SPECIALISTS":  "TEMPERATURE_TECH_SPECIALISTS",
    "TEMPERATURE_SKILL_SELECTOR":    "TEMPERATURE_SKILL_SELECTOR",
}


def _save_calibrazione_to_file(override: dict):
    """Persiste i parametri dell'override in Calibrazione.py."""
    calib_path = os.path.join(ROOT_DIR, "Calibrazione.py")
    try:
        with open(calib_path, "r", encoding="utf-8") as f:
            content = f.read()

        def _replace_var(text, var_name, value):
            if isinstance(value, str):
                new_val = f'"{value}"'
            elif isinstance(value, bool):
                new_val = str(value)
            elif isinstance(value, float):
                new_val = str(value)
            else:
                new_val = str(value)
            pattern = rf'^({re.escape(var_name)}\s*=\s*)[^#\n]*(#[^\n]*)?$'
            def _sub(m):
                comment = (m.group(2) or "").strip()
                return f'{m.group(1)}{new_val}  {comment}'.rstrip() if comment else f'{m.group(1)}{new_val}'
            return re.sub(pattern, _sub, text, flags=re.MULTILINE)

        for ui_key, cal_key in _CALIB_SCALAR_MAP.items():
            if ui_key in override:
                content = _replace_var(content, cal_key, override[ui_key])

        agent_llm = override.get("AGENT_LLM_CONFIG", {})
        for agent_key, cal_key in _AGENT_MODEL_MAP.items():
            model = (agent_llm.get(agent_key) or {}).get("model", "")
            if model:
                content = _replace_var(content, cal_key, model)

        with open(calib_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        logger.warning(f"[CALIBRAZIONE] Impossibile salvare su file: {e}")


def _apply_calibrazione_override(override: dict):
    """Aggiorna i parametri di Calibrazione in memoria e li persiste su file."""
    import Calibrazione
    for ui_key, cal_key in _CALIB_SCALAR_MAP.items():
        if ui_key in override:
            setattr(Calibrazione, cal_key, override[ui_key])

    # Configurazione LLM per-agente: aggiorna AGENT_LLM_CONFIG e MODEL_* in sync
    if "AGENT_LLM_CONFIG" in override:
        setattr(Calibrazione, "AGENT_LLM_CONFIG", override["AGENT_LLM_CONFIG"])
        for agent_key, cal_key in _AGENT_MODEL_MAP.items():
            model = (override["AGENT_LLM_CONFIG"].get(agent_key) or {}).get("model", "")
            if model:
                setattr(Calibrazione, cal_key, model)

    _save_calibrazione_to_file(override)


def _compute_projection(df_1d, days: int,
                        ai_price: float = None,
                        ai_upper: float = None,
                        ai_lower: float = None) -> dict:
    """
    Calcola la proiezione del prezzo per i prossimi `days` giorni.

    Modalità AI-anchored (quando ai_price è fornito):
      Interpolazione lineare dal last_price al prezzo AI target.
      Le bande convergono verso ai_upper/ai_lower (o ±1.5σ come fallback).
    Modalità statistica (fallback, quando ai_price è None):
      Regressione lineare sugli ultimi 20 giorni + bande ±1.5σ.
    """
    import numpy as np

    closes     = df_1d["Close"].values.flatten().astype(float)
    if len(closes) < 5:
        return {}

    last_price = float(closes[-1])
    last_dt    = df_1d.index[-1].to_pydatetime()
    std_dev    = float(np.std(closes[-min(20, len(closes)):]))
    projection_candles = []

    if ai_price is not None and days > 0:
        price_step   = (ai_price - last_price) / days
        upper_target = ai_upper if ai_upper else ai_price + std_dev * 1.5
        lower_target = ai_lower if ai_lower else ai_price - std_dev * 1.5
        upper_step   = (upper_target - (last_price + std_dev * 1.5)) / days
        lower_step   = (lower_target - (last_price - std_dev * 1.5)) / days

        for i in range(1, days + 1):
            proj_dt    = last_dt + timedelta(days=i)
            proj_price = last_price + price_step * i
            projection_candles.append({
                "time":  int(proj_dt.timestamp()),
                "value": round(proj_price, 4),
                "upper": round((last_price + std_dev * 1.5) + upper_step * i, 4),
                "lower": round((last_price - std_dev * 1.5) + lower_step * i, 4),
            })
        trend       = "bullish" if ai_price > last_price else "bearish"
        slope       = round((ai_price - last_price) / days, 4)
        ai_anchored = True
    else:
        n      = min(20, len(closes))
        coeffs = np.polyfit(range(n), closes[-n:], 1)
        m      = float(coeffs[0])

        for i in range(1, days + 1):
            proj_dt    = last_dt + timedelta(days=i)
            proj_price = last_price + m * i
            projection_candles.append({
                "time":  int(proj_dt.timestamp()),
                "value": round(proj_price, 4),
                "upper": round(proj_price + std_dev * 1.5, 4),
                "lower": round(proj_price - std_dev * 1.5, 4),
            })
        trend       = "bullish" if m > 0 else "bearish"
        slope       = round(m, 4)
        ai_anchored = False

    return {
        "candles":     projection_candles,
        "trend":       trend,
        "slope":       slope,
        "last_price":  round(last_price, 4),
        "ai_anchored": ai_anchored,
        "upper_bound": round(projection_candles[-1]["upper"], 4) if projection_candles else None,
        "lower_bound": round(projection_candles[-1]["lower"], 4) if projection_candles else None,
    }


def _is_plausible_price(value: float, last_price: float, tolerance: float = 0.50) -> bool:
    """
    Verifica che `value` sia plausibile rispetto a `last_price`.
    Tollera variazioni fino a `tolerance` (default 50%) in entrambe le direzioni.
    Restituisce sempre True se last_price è 0 o None (nessun riferimento disponibile).
    """
    if not last_price or last_price <= 0:
        return True
    deviation = abs(value - last_price) / last_price
    return deviation <= tolerance


def _extract_trade_setup(report_markdown: str, last_price: float = None) -> dict:
    """
    Estrae i livelli di Entry, Stop Loss e Take Profit dal VERDETTO FINALE del report AI.

    Parametri
    ----------
    report_markdown : str
        Il report completo prodotto dal SupervisorAgent.
    last_price : float, optional
        L'ultimo prezzo storico del periodo analizzato.
        Se fornito, i prezzi AI estratti vengono validati internamente:
        valori che deviano più del 50% vengono scartati con un warning,
        prevenendo che artefatti del parsing (date, ratio, livelli storici lontani)
        inquinino la proiezione futura.

    Note sul parsing dei prezzi
    ----------------------------
    _parse_number() gestisce sia la notazione italiana (punto = migliaia, virgola = decimale:
    "3.100" → 3100, "4.850,50" → 4850.5) sia quella anglosassone ("3,100" → 3100,
    "4,850.50" → 4850.5). La regola chiave: punto seguito da ESATTAMENTE 3 cifre = migliaia.
    """
    import re

    setup = {
        "entry":             None,
        "stop_loss":         None,
        "take_profit_1":     None,
        "take_profit_2":     None,
        "direction":         "unknown",
        "ai_forecast_price": None,
        "ai_forecast_upper": None,
        "ai_forecast_lower": None,
        "ai_forecast_entry": None,
        "ai_forecast_sl":    None,
        "ai_forecast_tp":    None,
        "ai_forecast_bias":  None,
        "parse_error":       False,
        "parse_error_msg":   ""
    }

    def _parse_number(s: str) -> float:
        """
        Converte una stringa numerica in float gestendo notazione italiana e anglosassone.

        Regola critica: punto singolo seguito da ESATTAMENTE 3 cifre = separatore delle
        migliaia in italiano. Es: "3.100" → 3100, "2.980" → 2980.
        """
        s = s.strip().lstrip("$€ ")
        if "." in s and "," in s:
            if s.rfind(".") > s.rfind(","):
                return float(s.replace(",", ""))
            else:
                return float(s.replace(".", "").replace(",", "."))
        elif "," in s:
            parts = s.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                return float(s.replace(",", "."))
            else:
                return float(s.replace(",", ""))
        elif "." in s:
            parts = s.split(".")
            if len(parts) > 2:
                return float(s.replace(".", ""))
            if (len(parts) == 2 and len(parts[1]) == 3
                    and parts[1].isdigit() and parts[0].isdigit()):
                return float(parts[0] + parts[1])
            return float(s)
        else:
            return float(s)

    num = r'\$?\s*([\d][.\d]*[\d](?:[,.]\d+)?|\d+(?:[,.]\d+)?)'

    def _find_price_after_label(text, label_re, window=500):
        """
        Trova il label nel testo e restituisce il primo numero che NON sia:
        - una percentuale (seguito da %)
        - un ratio (seguito da :)
        - un componente di data (preceduto da -)
        - un valore < 10 (ratio R:R, score, ecc.)

        La ricerca si ferma alla prossima intestazione di campo markdown
        per evitare di catturare numeri del campo successivo.
        """
        m = re.search(label_re, text, re.IGNORECASE)
        if not m:
            return None
        area = text[m.end(): m.end() + window]
        next_field = re.search(r'\n\s*(?:-\s*)?\*\*[A-Za-zÀ-ÿ]', area)
        if next_field:
            area = area[:next_field.start()]
        for nm in re.finditer(num, area):
            if nm.start() > 0 and area[nm.start() - 1] == '-':
                continue
            suffix = area[nm.end(): nm.end() + 2].strip()
            if suffix.startswith('%') or suffix.startswith(':') or suffix.startswith('-'):
                continue
            val = nm.group(1)
            try:
                if _parse_number(val) < 10:
                    continue
            except ValueError:
                pass
            return val
        return None

    def _extract_validated_price(label_re, field_name: str,
                                  plausible: bool = False) -> float | None:
        """
        Estrae un prezzo dal testo dopo `label_re` e, se `plausible=True` e
        `last_price` è disponibile, valida che il valore sia entro il 50%
        di last_price. Valori implausibili vengono scartati con warning.
        """
        raw = _find_price_after_label(search_text, label_re)
        if raw is None:
            return None
        try:
            val = round(_parse_number(raw), 4)
        except ValueError as e:
            logger.error(f"[EXTRACT] Impossibile parsare {field_name} '{raw}': {e}")
            return None
        if plausible and last_price and not _is_plausible_price(val, last_price):
            deviation = abs(val - last_price) / last_price
            logger.warning(
                f"[EXTRACT] {field_name}={val} scartato: deviazione "
                f"{deviation:.0%} da last_price={last_price}. "
                "Probabile artefatto del parsing (data, livello storico lontano, ratio)."
            )
            return None
        logger.info(f"[EXTRACT] {field_name} estratto: {val}")
        return val

    # ── Localizza VERDETTO FINALE ─────────────────────────────────────────────
    verdetto_match = re.search(
        r'(?:VERDETTO\s+FINALE[^#\n]*|🚀\s*VERDETTO\s+FINALE[^#\n]*)(.+)',
        report_markdown, re.IGNORECASE | re.DOTALL
    )
    if not verdetto_match:
        setup["parse_error"]     = True
        setup["parse_error_msg"] = (
            "Sezione VERDETTO FINALE non trovata nel report. "
            "Il sintetizzatore potrebbe non aver prodotto output "
            "o aver usato un titolo diverso."
        )
        logger.error(f"[EXTRACT] {setup['parse_error_msg']}")
        return setup

    search_text = verdetto_match.group(0)

    # ── Entry ─────────────────────────────────────────────────────────────────
    entry_label = r'(?:[Ee]ntry\s+[Ss]uggerita|[Ee]ntry\s+[Cc]onsigliata|[Ee]ntry|[Ii]ngresso\s+[Ss]uggerit\w*)'
    setup["entry"] = _extract_validated_price(entry_label, "Entry")
    if setup["entry"] is None:
        logger.warning("[EXTRACT] Campo 'Entry Suggerita' non trovato nel VERDETTO FINALE.")

    # ── Stop Loss ─────────────────────────────────────────────────────────────
    sl_label = r'(?:[Ss]top\s*[Ll]oss|[Ss]top)'
    setup["stop_loss"] = _extract_validated_price(sl_label, "Stop Loss")
    if setup["stop_loss"] is None:
        logger.warning("[EXTRACT] Campo 'Stop Loss' non trovato nel VERDETTO FINALE.")

    # ── Target 1 ──────────────────────────────────────────────────────────────
    tp1_label = r'(?:[Tt]arget\s*1|[Tt]ake\s*[Pp]rofit\s*1|[Tt][Pp]1|[Oo]biettivo\s*1)'
    setup["take_profit_1"] = _extract_validated_price(tp1_label, "Target 1")
    if setup["take_profit_1"] is None:
        logger.warning("[EXTRACT] Campo 'Target 1' non trovato nel VERDETTO FINALE.")

    # ── Target 2 ──────────────────────────────────────────────────────────────
    tp2_label = r'(?:[Tt]arget\s*2|[Tt]ake\s*[Pp]rofit\s*2|[Tt][Pp]2|[Oo]biettivo\s*2)'
    setup["take_profit_2"] = _extract_validated_price(tp2_label, "Target 2")

    # ── Bias Primario (direzione) ─────────────────────────────────────────────
    m_bias_label = re.search(r'Bias\s+Primario', search_text, re.IGNORECASE)
    if m_bias_label:
        bias_area = search_text[m_bias_label.start(): m_bias_label.start() + 200]
        m_bias_kw = re.search(
            r'\b(Bullish|Bearish|Neutrale|Neutral|Rialzista|Ribassista|NO\s*TRADE|Long|Short)\b',
            bias_area, re.IGNORECASE
        )
        if m_bias_kw:
            bias_val = m_bias_kw.group(1).lower()
            logger.info(f"[EXTRACT] Bias Primario raw: '{bias_val}'")
            if any(w in bias_val for w in ("bullish", "rialzista", "long", "buy", "positivo", "rialzo")):
                setup["direction"] = "bullish"
            elif any(w in bias_val for w in ("bearish", "ribassista", "short", "sell", "negativo", "ribasso")):
                setup["direction"] = "bearish"
            elif any(w in bias_val for w in ("neutrale", "neutral", "no trade", "wait")):
                setup["direction"] = "neutral"
            else:
                setup["direction"] = "unknown"
                logger.warning(f"[EXTRACT] Valore 'Bias Primario' non riconosciuto: '{bias_val}'")
        else:
            logger.warning(
                f"[EXTRACT] Keyword direzione non trovata dopo 'Bias Primario'. "
                f"Testo area: {bias_area[:100]!r}"
            )
    else:
        logger.warning("[EXTRACT] Riga 'Bias Primario' non trovata nel VERDETTO FINALE.")

    # ── Prezzo Centrale (proiezione AI) — validazione plausibilità OBBLIGATORIA ──
    forecast_label = r'(?:[Pp]rezzo\s+[Cc]entrale|[Pp]revisione\s+[Cc]entrale|[Pp]rezzo\s+[Pp]revisto)'
    setup["ai_forecast_price"] = _extract_validated_price(
        forecast_label, "ai_forecast_price", plausible=True
    )

    # ── Entry Proiezione ──────────────────────────────────────────────────────
    setup["ai_forecast_entry"] = _extract_validated_price(
        r'[Ee]ntry\s+[Pp]roiezione', "ai_forecast_entry", plausible=True
    )

    # ── Stop Loss Proiezione ──────────────────────────────────────────────────
    setup["ai_forecast_sl"] = _extract_validated_price(
        r'[Ss]top\s+[Ll]oss\s+[Pp]roiezione', "ai_forecast_sl", plausible=True
    )

    # ── Target Proiezione ─────────────────────────────────────────────────────
    # Validazione plausibilità attiva: questo è il fallback di ai_forecast_price,
    # quindi un valore implausibile qui causerebbe una proiezione errata.
    setup["ai_forecast_tp"] = _extract_validated_price(
        r'[Tt]arget\s+[Pp]roiezione', "ai_forecast_tp", plausible=True
    )

    # ── Scenario Rialzista/Ribassista ─────────────────────────────────────────
    setup["ai_forecast_upper"] = _extract_validated_price(
        r'[Ss]cenario\s+[Rr]ialzista', "ai_forecast_upper", plausible=True
    )
    setup["ai_forecast_lower"] = _extract_validated_price(
        r'[Ss]cenario\s+[Rr]ibassista', "ai_forecast_lower", plausible=True
    )

    # ── Bias Proiezione ───────────────────────────────────────────────────────
    bias_proj_match = re.search(
        r'[Bb]ias\s+[Pp]roiezione[^A-Za-z\n]*([A-Za-z]+(?:\s+[A-Za-z]+)?)',
        search_text, re.IGNORECASE
    )
    if bias_proj_match:
        bpv = bias_proj_match.group(1).strip().lower()
        if any(w in bpv for w in ("bullish", "rialzista", "long", "buy", "rialzo")):
            setup["ai_forecast_bias"] = "bullish"
        elif any(w in bpv for w in ("bearish", "ribassista", "short", "sell", "ribasso")):
            setup["ai_forecast_bias"] = "bearish"
        else:
            setup["ai_forecast_bias"] = "neutral"
        logger.info(f"[EXTRACT] ai_forecast_bias estratto: {setup['ai_forecast_bias']}")

    # ── Segnala i campi critici mancanti ─────────────────────────────────────
    # Con NO TRADE (direction == "neutral") entry/SL/TP sono legittimamente assenti.
    is_no_trade = setup["direction"] == "neutral"
    if is_no_trade:
        missing = []
        logger.info("[EXTRACT] Verdetto NO TRADE — campi trade non obbligatori.")
    else:
        missing = [k for k in ("entry", "stop_loss", "take_profit_1") if setup[k] is None]
    if setup["direction"] == "unknown":
        missing.append("direction")
    if missing:
        setup["parse_error"]     = True
        setup["parse_error_msg"] = (
            f"Campi non estratti dal VERDETTO FINALE: {', '.join(missing)}. "
            "Verifica che il sintetizzatore abbia usato le etichette corrette "
            "('Entry Suggerita', 'Stop Loss', 'Target 1', 'Bias Primario')."
        )
        logger.error(f"[EXTRACT] {setup['parse_error_msg']}")
        logger.warning(
            f"[EXTRACT] Testo VERDETTO FINALE (primi 800 char):\n{search_text[:800]}"
        )

    return setup
