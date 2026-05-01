"""
api/performance.py — Performance Tracking System per Trading AI App.

Gestisce:
1. Persistenza su SQLite di ogni analisi AI completata
2. Trade Outcome Verifier: verifica se Entry/SL/TP sono stati toccati post end_date
3. Statistiche aggregate per valutare l'affidabilità del sistema predittivo
4. Classificazione asset per tipo di mercato

Tabelle:
  - analyses:      Una riga per ogni analisi AI completata
  - trade_outcomes: Esito verificato con dati reali post end_date (1:1 con analyses)

Endpoints:
  POST /api/performance/save              → salva un'analisi
  POST /api/performance/verify/<id>       → lancia il verifier per un'analisi
  GET  /api/performance/stats             → statistiche aggregate
  GET  /api/performance/list              → lista analisi (paginata)
  GET  /api/performance/<id>             → dettaglio singola analisi
  DELETE /api/performance/<id>           → elimina analisi
"""

import os
import re
import sys
import json
import sqlite3
import threading
from datetime import datetime, timedelta, date
from typing import Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from flask import Blueprint, request, jsonify
from loguru import logger

performance_bp = Blueprint("performance", __name__)

# ── Path DB ──────────────────────────────────────────────────────────────────
_DB_PATH = os.path.join(ROOT_DIR, "storage", "memory", "performance.db")
_db_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA DATABASE
# ══════════════════════════════════════════════════════════════════════════════

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id                  TEXT PRIMARY KEY,
    symbol              TEXT NOT NULL,
    market_type         TEXT NOT NULL DEFAULT 'unknown',
    start_date          TEXT,
    end_date            TEXT,
    analysis_date       TEXT NOT NULL,
    analysis_time       TEXT,
    direction           TEXT DEFAULT 'unknown',
    entry               REAL,
    stop_loss           REAL,
    take_profit_1       REAL,
    take_profit_2       REAL,
    last_price          REAL,
    ai_forecast_price   REAL,
    ai_forecast_upper   REAL,
    ai_forecast_lower   REAL,
    ai_forecast_bias    TEXT,
    ai_forecast_entry   REAL,
    ai_forecast_sl      REAL,
    ai_forecast_tp      REAL,
    projection_end_date TEXT,
    parse_error         INTEGER DEFAULT 0,
    llm_provider        TEXT,
    agents_used         TEXT,
    chosen_tools        TEXT,
    report_markdown     TEXT
);

CREATE TABLE IF NOT EXISTS trade_outcomes (
    analysis_id          TEXT PRIMARY KEY REFERENCES analyses(id) ON DELETE CASCADE,
    verified_at          TEXT NOT NULL,
    -- Contatto Entry
    entry_touched        INTEGER DEFAULT 0,
    entry_touch_date     TEXT,
    entry_touch_price    REAL,
    days_to_entry        INTEGER,
    -- Stop Loss
    sl_hit               INTEGER DEFAULT 0,
    sl_hit_date          TEXT,
    sl_hit_price         REAL,
    -- Take Profit 1
    tp1_hit              INTEGER DEFAULT 0,
    tp1_hit_date         TEXT,
    tp1_hit_price        REAL,
    -- Take Profit 2
    tp2_hit              INTEGER DEFAULT 0,
    tp2_hit_date         TEXT,
    tp2_hit_price        REAL,
    -- Esito finale
    outcome              TEXT,
    days_to_exit         INTEGER,
    pnl_percent          REAL,
    -- Accuratezza previsione AI
    real_price_at_end    REAL,
    forecast_error_pct   REAL,
    direction_correct    INTEGER,
    -- Meta
    real_candles_count   INTEGER,
    horizon_days         INTEGER
);
"""


def _get_db() -> sqlite3.Connection:
    """Apre (o crea) il database performance e inizializza lo schema."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    # ── Migrazione: aggiungi colonne introdotte dopo la creazione iniziale ─────
    for _col_sql in [
        "ALTER TABLE analyses ADD COLUMN report_markdown TEXT",
        "ALTER TABLE analyses ADD COLUMN analysis_time TEXT",
    ]:
        try:
            conn.execute(_col_sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Colonna già esistente
    return conn


# ══════════════════════════════════════════════════════════════════════════════
# CLASSIFICATORE TIPO DI MERCATO
# ══════════════════════════════════════════════════════════════════════════════

_COMMODITY_FUTURES = {
    "GC", "SI", "HG", "CL", "NG", "BZ",   # Precious metals, energy
    "ZW", "ZS", "ZC", "ZO", "ZR",          # Grains
    "KC", "CT", "CC", "OJ", "SB",          # Softs
    "LH", "LE", "GF",                       # Livestock
    "PA", "PL", "HO", "RB",                # Platinum, heating oil, gasoline
}

_KNOWN_ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VEA", "VWO",
    "GLD", "SLV", "USO", "UNG", "PDBC",
    "TLT", "IEF", "SHY", "LQD", "HYG", "JNK",
    "EEM", "EFA", "FXI", "EWJ", "EWZ", "EWG",
    "VXX", "UVXY", "SQQQ", "TQQQ", "SPXL", "SPXS",
    "ARKK", "ARKG", "ARKF", "ARKW",
    "XLF", "XLE", "XLK", "XLV", "XLI", "XLB", "XLU", "XLRE",
    "IBB", "XBI", "SMH", "SOXX",
    "GDX", "GDXJ", "SIL",
    "BNO", "UCO", "SCO",
}

_INDEX_PREFIXES = {"^"}
_KNOWN_INDICES = {
    "^GSPC", "^DJI", "^IXIC", "^RUT", "^VIX", "^TNX", "^TYX",
    "^FTSE", "^DAX", "^CAC40", "^STOXX50E", "^AEX", "^SMI",
    "^N225", "^HSI", "^AXJO", "^BSESN", "^NSEI",
    "^GDAXI", "^FCHI", "^IBEX",
}


def classify_market_type(symbol: str) -> str:
    """
    Classifica il simbolo nel suo tipo di mercato.
    Ritorna: 'commodity' | 'forex' | 'crypto' | 'index' | 'etf' | 'stock' | 'other'
    """
    s = symbol.upper().strip()

    # Futures commodity: suffisso =F e root presente nella lista
    if s.endswith("=F"):
        root = s[:-2]
        # Rimuovi mese/anno opzionale (es. GCZ25 → GC)
        base = re.sub(r'\d.*$', '', root)
        if base in _COMMODITY_FUTURES:
            return "commodity"
        return "other"

    # Forex: pattern XXXYYY=X oppure XXXYYY (6 lettere)
    if s.endswith("=X") or re.match(r'^[A-Z]{6}$', s):
        return "forex"

    # Crypto: -USD, -USDT, -BTC suffix
    if re.search(r'-(USD|USDT|BTC|ETH|EUR)$', s):
        return "crypto"

    # Indici
    if s in _KNOWN_INDICES or s.startswith("^"):
        return "index"

    # ETF noti
    if s in _KNOWN_ETFS:
        return "etf"

    # Azioni: 1-5 lettere uppercase senza caratteri speciali
    if re.match(r'^[A-Z]{1,5}$', s):
        return "stock"

    return "other"


_MARKET_LABELS = {
    "commodity": "Materie Prime",
    "forex":     "Forex",
    "crypto":    "Crypto",
    "index":     "Indici",
    "etf":       "ETF",
    "stock":     "Azioni",
    "other":     "Altro",
}


# ══════════════════════════════════════════════════════════════════════════════
# TRADE OUTCOME VERIFIER
# ══════════════════════════════════════════════════════════════════════════════

def verify_trade_outcome(analysis_id: str) -> dict:
    """
    Scarica i dati OHLCV reali successivi a end_date e verifica se Entry/SL/TP
    sono stati toccati. Aggiorna la tabella trade_outcomes.

    Logica:
    ─────────────────────────────────────────────────────────────
    1. Recupera i dati dell'analisi dal DB
    2. Scarica OHLCV da (end_date+1) fino a (projection_end_date o +90gg)
    3. Per ogni candela, in ordine cronologico:
       a. Se l'entry non è ancora stata toccata:
          → il range [low, high] include l'entry? → entry touched
       b. Se entry già toccata:
          → Bullish: sl_hit se Low <= SL, tp1_hit se High >= TP1, tp2_hit se High >= TP2
          → Bearish: sl_hit se High >= SL, tp1_hit se Low <= TP1
       c. Primo evento vince (SL o TP1 chiude il trade)
    4. Calcola forecast accuracy: paragona ai_forecast_price al prezzo reale
       alla data projection_end_date
    ─────────────────────────────────────────────────────────────
    """
    import yfinance as yf
    import pandas as pd

    with _db_lock:
        conn = _get_db()
        row = conn.execute(
            "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
        conn.close()

    if not row:
        return {"error": "Analisi non trovata"}

    row = dict(row)
    symbol    = row["symbol"]
    end_date  = row["end_date"]
    direction = row["direction"]           # bullish / bearish / neutral / unknown
    entry     = row["entry"]
    sl        = row["stop_loss"]
    tp1       = row["take_profit_1"]
    tp2       = row["take_profit_2"]
    ai_fcst   = row["ai_forecast_price"]
    proj_end  = row["projection_end_date"]

    # Calcola finestra di verifica
    try:
        end_dt  = datetime.strptime(end_date, "%Y-%m-%d").date()
    except Exception:
        return {"error": f"end_date non valida: {end_date}"}

    real_start = end_dt + timedelta(days=1)

    if proj_end:
        try:
            proj_end_dt = datetime.strptime(proj_end, "%Y-%m-%d").date()
        except Exception:
            proj_end_dt = end_dt + timedelta(days=90)
    else:
        proj_end_dt = end_dt + timedelta(days=90)

    # Clamp al giorno corrente
    today = date.today()
    real_end = min(proj_end_dt, today)

    horizon_days = (proj_end_dt - end_dt).days

    if real_start >= today:
        outcome_data = _build_outcome(
            analysis_id, horizon_days, 0, outcome="no_data",
            note="end_date è nel futuro, dati reali non disponibili"
        )
        _save_outcome(outcome_data)
        return outcome_data

    # Download dati reali
    logger.info(f"[VERIFIER] Scaricamento dati reali {symbol}: {real_start} → {real_end}")
    try:
        df = yf.download(
            symbol,
            start=real_start.isoformat(),
            end=(real_end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
        if hasattr(df.columns, "get_level_values"):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
    except Exception as e:
        logger.error(f"[VERIFIER] Errore download {symbol}: {e}")
        return {"error": str(e)}

    if df.empty:
        outcome_data = _build_outcome(
            analysis_id, horizon_days, 0, outcome="no_data",
            note="Nessun dato OHLCV disponibile per la finestra di verifica"
        )
        _save_outcome(outcome_data)
        return outcome_data

    candles = []
    for idx, row_df in df.iterrows():
        dt = idx.date() if hasattr(idx, "date") else idx
        candles.append({
            "date":  dt,
            "open":  float(row_df["Open"]),
            "high":  float(row_df["High"]),
            "low":   float(row_df["Low"]),
            "close": float(row_df["Close"]),
        })

    candle_count = len(candles)

    # ── NO TRADE: solo accuratezza forecast ───────────────────────────────────
    if direction in ("neutral", "unknown") or entry is None:
        real_at_end, fcst_err, dir_ok = _compute_forecast_accuracy(
            candles, proj_end_dt, ai_fcst, row.get("last_price"), direction,
            row.get("ai_forecast_bias")
        )
        outcome_data = _build_outcome(
            analysis_id, horizon_days, candle_count,
            outcome="no_trade",
            real_price_at_end=real_at_end,
            forecast_error_pct=fcst_err,
            direction_correct=dir_ok,
        )
        _save_outcome(outcome_data)
        return outcome_data

    # ── TRADE CON ENTRY/SL/TP ─────────────────────────────────────────────────
    is_long = direction == "bullish"

    entry_touched      = False
    entry_touch_date   = None
    entry_touch_price  = None
    days_to_entry      = None

    sl_hit             = False
    sl_hit_date        = None
    sl_hit_price       = None

    tp1_hit            = False
    tp1_hit_date       = None
    tp1_hit_price      = None

    tp2_hit            = False
    tp2_hit_date       = None
    tp2_hit_price      = None

    outcome            = "open"
    days_to_exit       = None
    pnl_percent        = None

    for i, c in enumerate(candles):
        days_elapsed = (c["date"] - end_dt).days

        if not entry_touched:
            # Entry toccata se il range include il prezzo di entry
            if c["low"] <= entry <= c["high"]:
                entry_touched     = True
                entry_touch_date  = c["date"].isoformat()
                entry_touch_price = entry  # consideriamo eseguito al livello esatto
                days_to_entry     = days_elapsed
        else:
            # Dopo l'entry: monitora SL e TP
            if is_long:
                # Stop Loss per long: prezzo scende sotto SL
                if sl and c["low"] <= sl:
                    sl_hit      = True
                    sl_hit_date = c["date"].isoformat()
                    sl_hit_price= sl
                    outcome      = "loss_sl"
                    days_to_exit = days_elapsed - days_to_entry
                    pnl_percent  = round((sl - entry) / entry * 100, 2)
                    break

                # TP1
                if tp1 and not tp1_hit and c["high"] >= tp1:
                    tp1_hit      = True
                    tp1_hit_date = c["date"].isoformat()
                    tp1_hit_price= tp1
                    outcome       = "win_tp1"
                    days_to_exit  = days_elapsed - days_to_entry
                    pnl_percent   = round((tp1 - entry) / entry * 100, 2)

                # TP2 (solo se TP1 già raggiunto)
                if tp2 and tp1_hit and c["high"] >= tp2:
                    tp2_hit      = True
                    tp2_hit_date = c["date"].isoformat()
                    tp2_hit_price= tp2
                    outcome       = "win_tp2"
                    days_to_exit  = days_elapsed - days_to_entry
                    pnl_percent   = round((tp2 - entry) / entry * 100, 2)
                    break

            else:  # SHORT / BEARISH
                # Stop Loss per short: prezzo sale sopra SL
                if sl and c["high"] >= sl:
                    sl_hit      = True
                    sl_hit_date = c["date"].isoformat()
                    sl_hit_price= sl
                    outcome      = "loss_sl"
                    days_to_exit = days_elapsed - days_to_entry
                    pnl_percent  = round((entry - sl) / entry * 100 * -1, 2)
                    break

                # TP1 per short: prezzo scende sotto TP1
                if tp1 and not tp1_hit and c["low"] <= tp1:
                    tp1_hit      = True
                    tp1_hit_date = c["date"].isoformat()
                    tp1_hit_price= tp1
                    outcome       = "win_tp1"
                    days_to_exit  = days_elapsed - days_to_entry
                    pnl_percent   = round((entry - tp1) / entry * 100, 2)

                # TP2 per short
                if tp2 and tp1_hit and c["low"] <= tp2:
                    tp2_hit      = True
                    tp2_hit_date = c["date"].isoformat()
                    tp2_hit_price= tp2
                    outcome       = "win_tp2"
                    days_to_exit  = days_elapsed - days_to_entry
                    pnl_percent   = round((entry - tp2) / entry * 100, 2)
                    break

    if not entry_touched:
        outcome = "no_entry"

    # Accuratezza forecast AI
    real_at_end, fcst_err, dir_ok = _compute_forecast_accuracy(
        candles, proj_end_dt, ai_fcst, row.get("last_price"), direction,
        row.get("ai_forecast_bias")
    )

    outcome_data = _build_outcome(
        analysis_id, horizon_days, candle_count,
        entry_touched=entry_touched,
        entry_touch_date=entry_touch_date,
        entry_touch_price=entry_touch_price,
        days_to_entry=days_to_entry,
        sl_hit=sl_hit,
        sl_hit_date=sl_hit_date,
        sl_hit_price=sl_hit_price,
        tp1_hit=tp1_hit,
        tp1_hit_date=tp1_hit_date,
        tp1_hit_price=tp1_hit_price,
        tp2_hit=tp2_hit,
        tp2_hit_date=tp2_hit_date,
        tp2_hit_price=tp2_hit_price,
        outcome=outcome,
        days_to_exit=days_to_exit,
        pnl_percent=pnl_percent,
        real_price_at_end=real_at_end,
        forecast_error_pct=fcst_err,
        direction_correct=dir_ok,
    )

    _save_outcome(outcome_data)
    logger.success(f"[VERIFIER] Outcome per {symbol}: {outcome} | P&L: {pnl_percent}%")
    return outcome_data


def _compute_forecast_accuracy(candles, proj_end_dt, ai_fcst, last_price, direction, ai_bias):
    """
    Calcola accuratezza della previsione AI:
    - real_price_at_end: ultimo prezzo disponibile nella finestra di verifica
    - forecast_error_pct: |ai_forecast - real| / real * 100
    - direction_correct: 1 se il movimento reale concorda con la direzione predetta
    """
    if not candles:
        return None, None, None

    # Prezzo reale più vicino alla data di fine proiezione
    best = candles[-1]  # default: ultimo disponibile
    for c in reversed(candles):
        if c["date"] <= proj_end_dt:
            best = c
            break
    real_at_end = best["close"]

    # Errore forecast
    fcst_err = None
    if ai_fcst and real_at_end:
        fcst_err = round(abs(ai_fcst - real_at_end) / real_at_end * 100, 2)

    # Direzione corretta
    dir_ok = None
    if last_price and real_at_end:
        actual_move = "bullish" if real_at_end > last_price else "bearish"
        predicted   = direction if direction in ("bullish", "bearish") else ai_bias
        if predicted in ("bullish", "bearish"):
            dir_ok = 1 if actual_move == predicted else 0

    return real_at_end, fcst_err, dir_ok


def _build_outcome(analysis_id: str, horizon_days: int, candle_count: int,
                   outcome: str = "open", note: str = None, **kwargs) -> dict:
    """Costruisce il dizionario outcome da salvare."""
    data = {
        "analysis_id":       analysis_id,
        "verified_at":       datetime.utcnow().isoformat(),
        "horizon_days":      horizon_days,
        "real_candles_count":candle_count,
        "outcome":           outcome,
        "entry_touched":     kwargs.get("entry_touched", False),
        "entry_touch_date":  kwargs.get("entry_touch_date"),
        "entry_touch_price": kwargs.get("entry_touch_price"),
        "days_to_entry":     kwargs.get("days_to_entry"),
        "sl_hit":            kwargs.get("sl_hit", False),
        "sl_hit_date":       kwargs.get("sl_hit_date"),
        "sl_hit_price":      kwargs.get("sl_hit_price"),
        "tp1_hit":           kwargs.get("tp1_hit", False),
        "tp1_hit_date":      kwargs.get("tp1_hit_date"),
        "tp1_hit_price":     kwargs.get("tp1_hit_price"),
        "tp2_hit":           kwargs.get("tp2_hit", False),
        "tp2_hit_date":      kwargs.get("tp2_hit_date"),
        "tp2_hit_price":     kwargs.get("tp2_hit_price"),
        "days_to_exit":      kwargs.get("days_to_exit"),
        "pnl_percent":       kwargs.get("pnl_percent"),
        "real_price_at_end": kwargs.get("real_price_at_end"),
        "forecast_error_pct":kwargs.get("forecast_error_pct"),
        "direction_correct": kwargs.get("direction_correct"),
    }
    if note:
        data["_note"] = note
    return data


def _save_outcome(data: dict):
    """Inserisce o aggiorna la riga in trade_outcomes."""
    clean = {k: v for k, v in data.items() if not k.startswith("_")}
    cols  = ", ".join(clean.keys())
    placeholders = ", ".join("?" for _ in clean)
    updates = ", ".join(f"{k}=excluded.{k}" for k in clean if k != "analysis_id")
    sql = f"""
        INSERT INTO trade_outcomes ({cols}) VALUES ({placeholders})
        ON CONFLICT(analysis_id) DO UPDATE SET {updates}
    """
    with _db_lock:
        conn = _get_db()
        conn.execute(sql, list(clean.values()))
        conn.commit()
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# SALVATAGGIO ANALISI
# ══════════════════════════════════════════════════════════════════════════════

def save_analysis(job_id: str, symbol: str, start: str, end: str,
                  trade_setup: dict, chosen_tools: dict = None,
                  projection_end_date: str = None,
                  report_markdown: str = None) -> bool:
    """
    Persiste un'analisi completata nel DB.
    Viene chiamata da _run_analysis_thread in backtesting.py.
    """
    import Calibrazione

    if trade_setup.get("parse_error") and not trade_setup.get("direction"):
        logger.warning(f"[PERF] Analisi {job_id} saltata: parse_error senza direction.")
        return False

    market_type = classify_market_type(symbol)

    agents_used = json.dumps({
        "macro":   getattr(Calibrazione, "AGENT_MACRO_ENABLED", True),
        "pattern": getattr(Calibrazione, "AGENT_PATTERN_ENABLED", True),
        "trend":   getattr(Calibrazione, "AGENT_TREND_ENABLED", True),
        "sr":      getattr(Calibrazione, "AGENT_SR_ENABLED", True),
        "volume":  getattr(Calibrazione, "AGENT_VOLUME_ENABLED", True),
    })

    now = datetime.utcnow()
    analysis_dt = now.isoformat()
    analysis_time = now.strftime("%H:%M:%S")

    row = {
        "id":                 job_id,
        "symbol":             symbol,
        "market_type":        market_type,
        "start_date":         start,
        "end_date":           end,
        "analysis_date":      analysis_dt,
        "analysis_time":      analysis_time,
        "direction":          trade_setup.get("direction", "unknown"),
        "entry":              trade_setup.get("entry"),
        "stop_loss":          trade_setup.get("stop_loss"),
        "take_profit_1":      trade_setup.get("take_profit_1"),
        "take_profit_2":      trade_setup.get("take_profit_2"),
        "last_price":         trade_setup.get("last_price"),
        "ai_forecast_price":  trade_setup.get("ai_forecast_price"),
        "ai_forecast_upper":  trade_setup.get("ai_forecast_upper"),
        "ai_forecast_lower":  trade_setup.get("ai_forecast_lower"),
        "ai_forecast_bias":   trade_setup.get("ai_forecast_bias"),
        "ai_forecast_entry":  trade_setup.get("ai_forecast_entry"),
        "ai_forecast_sl":     trade_setup.get("ai_forecast_sl"),
        "ai_forecast_tp":     trade_setup.get("ai_forecast_tp"),
        "projection_end_date":projection_end_date,
        "parse_error":        int(trade_setup.get("parse_error", False)),
        "llm_provider":       getattr(Calibrazione, "LLM_PROVIDER", "unknown"),
        "agents_used":        agents_used,
        "chosen_tools":       json.dumps(chosen_tools) if chosen_tools else None,
        "report_markdown":    report_markdown,
    }

    cols  = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    updates = ", ".join(f"{k}=excluded.{k}" for k in row if k != "id")
    sql = f"""
        INSERT INTO analyses ({cols}) VALUES ({placeholders})
        ON CONFLICT(id) DO UPDATE SET {updates}
    """
    try:
        with _db_lock:
            conn = _get_db()
            conn.execute(sql, list(row.values()))
            conn.commit()
            conn.close()
        logger.success(f"[PERF] Analisi {job_id} ({symbol}) salvata — {market_type} — {row['direction']}")
        return True
    except Exception as e:
        logger.error(f"[PERF] Errore salvataggio analisi {job_id}: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# STATISTICHE AGGREGATE
# ══════════════════════════════════════════════════════════════════════════════

def _compute_stats() -> dict:
    """
    Calcola le statistiche aggregate dal DB.
    Restituisce un dizionario strutturato per il frontend.
    """
    with _db_lock:
        conn = _get_db()

        # ── Totali globali ─────────────────────────────────────────────────────
        total_row = conn.execute("SELECT COUNT(*) as n FROM analyses").fetchone()
        total_analyses = total_row["n"]

        verified_row = conn.execute(
            "SELECT COUNT(*) as n FROM trade_outcomes"
        ).fetchone()
        total_verified = verified_row["n"]

        # ── Outcome distribution ───────────────────────────────────────────────
        outcome_rows = conn.execute("""
            SELECT outcome, COUNT(*) as cnt
            FROM trade_outcomes
            GROUP BY outcome
        """).fetchall()
        outcome_dist = {r["outcome"]: r["cnt"] for r in outcome_rows}

        wins   = (outcome_dist.get("win_tp2", 0) +
                  outcome_dist.get("win_tp1", 0))
        losses = outcome_dist.get("loss_sl", 0)
        total_closed = wins + losses
        win_rate = round(wins / total_closed * 100, 1) if total_closed > 0 else None

        # ── P&L medio ─────────────────────────────────────────────────────────
        pnl_row = conn.execute("""
            SELECT AVG(pnl_percent) as avg_pnl,
                   MAX(pnl_percent) as max_pnl,
                   MIN(pnl_percent) as min_pnl
            FROM trade_outcomes
            WHERE pnl_percent IS NOT NULL
        """).fetchone()

        # ── Accuratezza previsione ─────────────────────────────────────────────
        fcst_row = conn.execute("""
            SELECT AVG(forecast_error_pct) as avg_err,
                   AVG(direction_correct)  as dir_accuracy
            FROM trade_outcomes
            WHERE forecast_error_pct IS NOT NULL
        """).fetchone()

        # ── Tempi medi ────────────────────────────────────────────────────────
        times_row = conn.execute("""
            SELECT AVG(days_to_entry) as avg_days_entry,
                   AVG(days_to_exit)  as avg_days_exit
            FROM trade_outcomes
            WHERE days_to_entry IS NOT NULL
        """).fetchone()

        # ── Per tipo di mercato ────────────────────────────────────────────────
        by_market_rows = conn.execute("""
            SELECT
                a.market_type,
                COUNT(DISTINCT a.id)                              AS total,
                COUNT(DISTINCT t.analysis_id)                     AS verified,
                SUM(CASE WHEN t.outcome IN ('win_tp1','win_tp2') THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN t.outcome = 'loss_sl' THEN 1 ELSE 0 END)              AS losses,
                SUM(CASE WHEN t.outcome = 'no_entry' THEN 1 ELSE 0 END)             AS no_entry,
                SUM(CASE WHEN t.outcome = 'open' THEN 1 ELSE 0 END)                 AS open_trades,
                SUM(CASE WHEN t.outcome IN ('no_trade','no_data') THEN 1 ELSE 0 END) AS no_trade,
                AVG(t.pnl_percent)          AS avg_pnl,
                AVG(t.days_to_entry)        AS avg_days_entry,
                AVG(t.days_to_exit)         AS avg_days_exit,
                AVG(t.forecast_error_pct)   AS avg_forecast_err,
                AVG(t.direction_correct)    AS dir_accuracy
            FROM analyses a
            LEFT JOIN trade_outcomes t ON a.id = t.analysis_id
            GROUP BY a.market_type
            ORDER BY total DESC
        """).fetchall()

        by_market = []
        for r in by_market_rows:
            mt     = r["market_type"]
            closed = (r["wins"] or 0) + (r["losses"] or 0)
            wr     = round((r["wins"] or 0) / closed * 100, 1) if closed > 0 else None
            by_market.append({
                "market_type":    mt,
                "label":          _MARKET_LABELS.get(mt, mt),
                "total":          r["total"],
                "verified":       r["verified"],
                "wins":           r["wins"] or 0,
                "losses":         r["losses"] or 0,
                "no_entry":       r["no_entry"] or 0,
                "open_trades":    r["open_trades"] or 0,
                "no_trade":       r["no_trade"] or 0,
                "win_rate":       wr,
                "avg_pnl":        _round(r["avg_pnl"]),
                "avg_days_entry": _round(r["avg_days_entry"]),
                "avg_days_exit":  _round(r["avg_days_exit"]),
                "avg_forecast_err":_round(r["avg_forecast_err"]),
                "dir_accuracy":   _round((r["dir_accuracy"] or 0) * 100),
            })

        # ── Per direzione ──────────────────────────────────────────────────────
        by_direction = conn.execute("""
            SELECT
                a.direction,
                COUNT(DISTINCT a.id)                              AS total,
                SUM(CASE WHEN t.outcome IN ('win_tp1','win_tp2') THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN t.outcome = 'loss_sl' THEN 1 ELSE 0 END)              AS losses,
                AVG(t.pnl_percent)        AS avg_pnl,
                AVG(t.days_to_exit)       AS avg_days_exit,
                AVG(t.forecast_error_pct) AS avg_forecast_err
            FROM analyses a
            LEFT JOIN trade_outcomes t ON a.id = t.analysis_id
            GROUP BY a.direction
        """).fetchall()

        direction_stats = []
        for r in by_direction:
            closed = (r["wins"] or 0) + (r["losses"] or 0)
            wr     = round((r["wins"] or 0) / closed * 100, 1) if closed > 0 else None
            direction_stats.append({
                "direction": r["direction"],
                "total":     r["total"],
                "wins":      r["wins"] or 0,
                "losses":    r["losses"] or 0,
                "win_rate":  wr,
                "avg_pnl":   _round(r["avg_pnl"]),
                "avg_days_exit": _round(r["avg_days_exit"]),
                "avg_forecast_err": _round(r["avg_forecast_err"]),
            })

        # ── Per LLM Provider ───────────────────────────────────────────────────
        by_provider = conn.execute("""
            SELECT
                a.llm_provider,
                COUNT(*) AS total,
                SUM(CASE WHEN t.outcome IN ('win_tp1','win_tp2') THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN t.outcome = 'loss_sl' THEN 1 ELSE 0 END)              AS losses,
                AVG(t.forecast_error_pct) AS avg_forecast_err,
                AVG(t.direction_correct)  AS dir_accuracy
            FROM analyses a
            LEFT JOIN trade_outcomes t ON a.id = t.analysis_id
            GROUP BY a.llm_provider
        """).fetchall()

        provider_stats = []
        for r in by_provider:
            closed = (r["wins"] or 0) + (r["losses"] or 0)
            wr     = round((r["wins"] or 0) / closed * 100, 1) if closed > 0 else None
            provider_stats.append({
                "provider":    r["llm_provider"] or "N/D",
                "total":       r["total"],
                "wins":        r["wins"] or 0,
                "losses":      r["losses"] or 0,
                "win_rate":    wr,
                "avg_forecast_err": _round(r["avg_forecast_err"]),
                "dir_accuracy": _round((r["dir_accuracy"] or 0) * 100),
            })

        # ── Distribuzione giorni all'entry ─────────────────────────────────────
        entry_dist = conn.execute("""
            SELECT
                CASE
                    WHEN days_to_entry <= 5  THEN '1-5gg'
                    WHEN days_to_entry <= 10 THEN '6-10gg'
                    WHEN days_to_entry <= 20 THEN '11-20gg'
                    WHEN days_to_entry <= 30 THEN '21-30gg'
                    ELSE '>30gg'
                END as bucket,
                COUNT(*) as cnt
            FROM trade_outcomes
            WHERE days_to_entry IS NOT NULL
            GROUP BY bucket
            ORDER BY MIN(days_to_entry)
        """).fetchall()

        conn.close()

    return {
        "total_analyses":   total_analyses,
        "total_verified":   total_verified,
        "win_rate":         win_rate,
        "wins":             wins,
        "losses":           losses,
        "outcome_dist":     outcome_dist,
        "avg_pnl":          _round(pnl_row["avg_pnl"] if pnl_row else None),
        "max_pnl":          _round(pnl_row["max_pnl"] if pnl_row else None),
        "min_pnl":          _round(pnl_row["min_pnl"] if pnl_row else None),
        "avg_forecast_err": _round(fcst_row["avg_err"] if fcst_row else None),
        "dir_accuracy":     _round((fcst_row["dir_accuracy"] or 0) * 100 if fcst_row else None),
        "avg_days_to_entry":_round(times_row["avg_days_entry"] if times_row else None),
        "avg_days_to_exit": _round(times_row["avg_days_exit"] if times_row else None),
        "by_market":        by_market,
        "by_direction":     direction_stats,
        "by_provider":      provider_stats,
        "entry_time_dist":  [{"bucket": r["bucket"], "count": r["cnt"]} for r in entry_dist],
    }


def _compute_filtered_stats(analysis_ids: list) -> dict:
    """
    Calcola le statistiche per un sottoinsieme di analisi.
    Accetta una lista di analysis_id e restituisce statistiche aggregate solo per quegli ID.
    """
    if not analysis_ids:
        return {
            "total_analyses": 0,
            "total_verified": 0,
            "win_rate": None,
            "wins": 0,
            "losses": 0,
            "avg_pnl": None,
            "max_pnl": None,
            "min_pnl": None,
            "avg_forecast_err": None,
            "dir_accuracy": None,
        }

    placeholders = ",".join("?" for _ in analysis_ids)

    with _db_lock:
        conn = _get_db()

        # ── Totali per gli ID forniti ─────────────────────────────────────────
        total_row = conn.execute(
            f"SELECT COUNT(*) as n FROM analyses WHERE id IN ({placeholders})",
            analysis_ids
        ).fetchone()
        total_analyses = total_row["n"]

        verified_row = conn.execute(
            f"SELECT COUNT(*) as n FROM trade_outcomes WHERE analysis_id IN ({placeholders})",
            analysis_ids
        ).fetchone()
        total_verified = verified_row["n"]

        # ── Outcome distribution ───────────────────────────────────────────────
        outcome_rows = conn.execute(f"""
            SELECT outcome, COUNT(*) as cnt
            FROM trade_outcomes
            WHERE analysis_id IN ({placeholders})
            GROUP BY outcome
        """, analysis_ids).fetchall()
        outcome_dist = {r["outcome"]: r["cnt"] for r in outcome_rows}

        wins   = (outcome_dist.get("win_tp2", 0) +
                  outcome_dist.get("win_tp1", 0))
        losses = outcome_dist.get("loss_sl", 0)
        total_closed = wins + losses
        win_rate = round(wins / total_closed * 100, 1) if total_closed > 0 else None

        # ── P&L medio ─────────────────────────────────────────────────────────
        pnl_row = conn.execute(f"""
            SELECT AVG(pnl_percent) as avg_pnl,
                   MAX(pnl_percent) as max_pnl,
                   MIN(pnl_percent) as min_pnl
            FROM trade_outcomes
            WHERE analysis_id IN ({placeholders}) AND pnl_percent IS NOT NULL
        """, analysis_ids).fetchone()

        # ── Accuratezza previsione ─────────────────────────────────────────────
        fcst_row = conn.execute(f"""
            SELECT AVG(forecast_error_pct) as avg_err,
                   AVG(direction_correct)  as dir_accuracy
            FROM trade_outcomes
            WHERE analysis_id IN ({placeholders}) AND forecast_error_pct IS NOT NULL
        """, analysis_ids).fetchone()

        # ── Tempi medi ────────────────────────────────────────────────────────
        times_row = conn.execute(f"""
            SELECT AVG(days_to_entry) as avg_days_entry,
                   AVG(days_to_exit)  as avg_days_exit
            FROM trade_outcomes
            WHERE analysis_id IN ({placeholders}) AND days_to_entry IS NOT NULL
        """, analysis_ids).fetchone()

        # ── Distribuzione giorni all'entry ─────────────────────────────────────
        entry_dist = conn.execute(f"""
            SELECT
                CASE
                    WHEN days_to_entry <= 5  THEN '1-5gg'
                    WHEN days_to_entry <= 10 THEN '6-10gg'
                    WHEN days_to_entry <= 20 THEN '11-20gg'
                    WHEN days_to_entry <= 30 THEN '21-30gg'
                    ELSE '>30gg'
                END as bucket,
                COUNT(*) as cnt
            FROM trade_outcomes
            WHERE analysis_id IN ({placeholders}) AND days_to_entry IS NOT NULL
            GROUP BY bucket
            ORDER BY MIN(days_to_entry)
        """, analysis_ids).fetchall()

        conn.close()

    return {
        "total_analyses":    total_analyses,
        "total_verified":    total_verified,
        "win_rate":          win_rate,
        "wins":              wins,
        "losses":            losses,
        "outcome_dist":      outcome_dist,
        "avg_pnl":           _round(pnl_row["avg_pnl"] if pnl_row else None),
        "max_pnl":           _round(pnl_row["max_pnl"] if pnl_row else None),
        "min_pnl":           _round(pnl_row["min_pnl"] if pnl_row else None),
        "avg_forecast_err":  _round(fcst_row["avg_err"] if fcst_row else None),
        "dir_accuracy":      _round((fcst_row["dir_accuracy"] or 0) * 100 if fcst_row else None),
        "avg_days_to_entry": _round(times_row["avg_days_entry"] if times_row else None),
        "avg_days_to_exit":  _round(times_row["avg_days_exit"] if times_row else None),
        "entry_time_dist":   [{"bucket": r["bucket"], "count": r["cnt"]} for r in entry_dist],
    }


def _round(v, digits=1):
    if v is None:
        return None
    try:
        return round(float(v), digits)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS FLASK
# ══════════════════════════════════════════════════════════════════════════════

@performance_bp.route("/save", methods=["POST"])
def api_save():
    """Salva un'analisi completata (chiamata da backtesting.py)."""
    body = request.get_json() or {}
    ok = save_analysis(
        job_id              = body.get("job_id", ""),
        symbol              = body.get("symbol", ""),
        start               = body.get("start", ""),
        end                 = body.get("end", ""),
        trade_setup         = body.get("trade_setup", {}),
        chosen_tools        = body.get("chosen_tools"),
        projection_end_date = body.get("projection_end_date"),
    )
    return jsonify({"saved": ok})


@performance_bp.route("/verify/<analysis_id>", methods=["POST"])
def api_verify(analysis_id: str):
    """Lancia il Trade Outcome Verifier per un'analisi specifica."""
    result = verify_trade_outcome(analysis_id)
    return jsonify(result)


@performance_bp.route("/stats", methods=["GET"])
def api_stats():
    """Statistiche aggregate."""
    try:
        stats = _compute_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"[PERF STATS] Errore: {e}")
        return jsonify({"error": str(e)}), 500


@performance_bp.route("/stats/filtered", methods=["POST"])
def api_stats_filtered():
    """Statistiche filtrate per una lista di analysis_id."""
    body = request.get_json() or {}
    analysis_ids = body.get("analysis_ids", [])

    try:
        stats = _compute_filtered_stats(analysis_ids)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"[PERF STATS FILTERED] Errore: {e}")
        return jsonify({"error": str(e)}), 500


@performance_bp.route("/list", methods=["GET"])
def api_list():
    """Lista analisi con paginazione e filtri opzionali."""
    page     = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    mtype    = request.args.get("market_type")
    symbol   = request.args.get("symbol")
    outcome  = request.args.get("outcome")

    offset = (page - 1) * per_page
    filters, params = [], []

    if mtype:
        filters.append("a.market_type = ?")
        params.append(mtype)
    if symbol:
        filters.append("a.symbol LIKE ?")
        params.append(f"%{symbol.upper()}%")
    if outcome:
        filters.append("t.outcome = ?")
        params.append(outcome)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    with _db_lock:
        conn = _get_db()

        count_row = conn.execute(
            f"SELECT COUNT(*) as n FROM analyses a LEFT JOIN trade_outcomes t ON a.id=t.analysis_id {where}",
            params
        ).fetchone()

        rows = conn.execute(f"""
            SELECT
                a.id, a.symbol, a.market_type, a.start_date, a.end_date,
                a.analysis_date, a.analysis_time, a.direction, a.entry, a.stop_loss,
                a.take_profit_1, a.take_profit_2, a.last_price,
                a.ai_forecast_price, a.ai_forecast_bias,
                a.projection_end_date, a.parse_error, a.llm_provider,
                t.outcome, t.pnl_percent, t.days_to_entry, t.days_to_exit,
                t.entry_touched, t.sl_hit, t.tp1_hit, t.tp2_hit,
                t.forecast_error_pct, t.direction_correct,
                t.real_price_at_end, t.verified_at
            FROM analyses a
            LEFT JOIN trade_outcomes t ON a.id = t.analysis_id
            {where}
            ORDER BY a.analysis_date DESC
            LIMIT ? OFFSET ?
        """, params + [per_page, offset]).fetchall()

        conn.close()

    items = [dict(r) for r in rows]
    return jsonify({
        "total":    count_row["n"],
        "page":     page,
        "per_page": per_page,
        "items":    items,
    })


@performance_bp.route("/all", methods=["GET"])
def api_all():
    """Lista tutte le analisi con i dettagli (per il panel della performance page)."""
    with _db_lock:
        conn = _get_db()

        rows = conn.execute("""
            SELECT
                a.id, a.symbol, a.market_type, a.start_date, a.end_date,
                a.analysis_date, a.analysis_time, a.direction, a.entry, a.stop_loss,
                a.take_profit_1, a.take_profit_2, a.last_price,
                a.ai_forecast_price, a.ai_forecast_bias,
                a.projection_end_date, a.parse_error, a.llm_provider,
                t.outcome, t.pnl_percent, t.days_to_entry, t.days_to_exit,
                t.entry_touched, t.sl_hit, t.tp1_hit, t.tp2_hit,
                t.forecast_error_pct, t.direction_correct,
                t.real_price_at_end, t.verified_at
            FROM analyses a
            LEFT JOIN trade_outcomes t ON a.id = t.analysis_id
            ORDER BY a.analysis_date DESC, a.analysis_time DESC
        """).fetchall()

        conn.close()

    items = [dict(r) for r in rows]
    return jsonify({"items": items, "total": len(items)})


@performance_bp.route("/<analysis_id>", methods=["GET"])
def api_detail(analysis_id: str):
    """Dettaglio completo di una singola analisi."""
    with _db_lock:
        conn = _get_db()
        a = conn.execute("SELECT * FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        t = conn.execute("SELECT * FROM trade_outcomes WHERE analysis_id=?", (analysis_id,)).fetchone()
        conn.close()

    if not a:
        return jsonify({"error": "Analisi non trovata"}), 404

    result = dict(a)
    result["outcome"] = dict(t) if t else None
    return jsonify(result)


@performance_bp.route("/<analysis_id>", methods=["DELETE"])
def api_delete(analysis_id: str):
    """Elimina un'analisi e il suo outcome."""
    with _db_lock:
        conn = _get_db()
        conn.execute("DELETE FROM analyses WHERE id=?", (analysis_id,))
        conn.commit()
        conn.close()
    return jsonify({"deleted": True})


@performance_bp.route("/delete-batch", methods=["POST"])
def api_delete_batch():
    """Elimina più analisi contemporaneamente."""
    body = request.get_json() or {}
    analysis_ids = body.get("analysis_ids", [])

    if not analysis_ids:
        return jsonify({"error": "Nessun ID fornito"}), 400

    try:
        placeholders = ",".join("?" for _ in analysis_ids)
        with _db_lock:
            conn = _get_db()
            conn.execute(f"DELETE FROM analyses WHERE id IN ({placeholders})", analysis_ids)
            conn.commit()
            conn.close()
        logger.info(f"[PERF DELETE] Eliminate {len(analysis_ids)} analisi")
        return jsonify({"deleted_count": len(analysis_ids)})
    except Exception as e:
        logger.error(f"[PERF DELETE BATCH] Errore: {e}")
        return jsonify({"error": str(e)}), 500


@performance_bp.route("/market-types", methods=["GET"])
def api_market_types():
    """Lista dei tipi di mercato presenti nel DB."""
    with _db_lock:
        conn = _get_db()
        rows = conn.execute(
            "SELECT DISTINCT market_type FROM analyses ORDER BY market_type"
        ).fetchall()
        conn.close()
    return jsonify([r["market_type"] for r in rows])
