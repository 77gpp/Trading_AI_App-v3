"""
indicators_engine.py — Pre-calcola indicatori tecnici da DataFrame OHLCV.

Principio guida: misurazioni oggettive, non interpretazioni.
Gli agenti LLM ricevono numeri precisi; le Skill traducono i numeri in significato;
l'LLM decide basandosi su confluenze tra misurazioni e contesto OHLCV.

Cosa viene calcolato:
  Oscillatori  : RSI 14, MACD (12/26/9), Stochastic (14/3), Williams %R 14
  Medie Mobili : SMA 20/50/100/200, EMA 9/20/50/100
  Volatilità   : Bollinger Bands (20/2), ATR 14
  Volume       : OBV
  Struttura    : Swing Highs/Lows algoritmici (pivot detection)

Cosa NON viene calcolato qui (rimane raw OHLCV per gli agenti):
  Pattern candlestick, livelli S/R, formazioni grafiche
"""

import numpy as np
import pandas as pd
from loguru import logger


# ──────────────────────────────────────────────────────────────────────────────
# Entry point pubblico
# ──────────────────────────────────────────────────────────────────────────────

def compute(data_dict: dict) -> dict:
    """
    Calcola indicatori per ogni timeframe in data_dict.

    Args:
        data_dict: {"1h": df, "4h": df, "1d": df}

    Returns:
        {"1h": {name: pd.Series}, "4h": {...}, "1d": {...}}
    """
    result = {}
    for tf, df in data_dict.items():
        if df is None or df.empty or len(df) < 5:
            result[tf] = {}
            continue
        try:
            result[tf] = _compute_tf(df)
            logger.debug(f"[INDICATORS] {tf}: {len(result[tf])} serie calcolate")
        except Exception as e:
            logger.warning(f"[INDICATORS] Errore calcolo {tf}: {e}")
            result[tf] = {}
    return result


def swing_points(df: pd.DataFrame, lookback: int = None) -> dict:
    """
    Identifica swing highs/lows algoritmici recenti.

    Lookback adattivo: 5 per 1H, 4 per 4H, 3 per 1D.
    Ritorna gli ultimi 10 swing di ciascun tipo.

    Returns:
        {
            "swing_highs": [(date_str, price), ...],
            "swing_lows":  [(date_str, price), ...],
            "last_close":  float,
        }
    """
    if df is None or df.empty or len(df) < 15:
        return {}

    high  = df["High"].squeeze().astype(float)
    low   = df["Low"].squeeze().astype(float)
    close = df["Close"].squeeze().astype(float)
    n     = len(df)

    # Lookback adattivo basato sulla granularità del timeframe
    if lookback is None:
        lookback = 3

    sh_dates, sh_prices = [], []
    sl_dates, sl_prices = [], []

    for i in range(lookback, n - lookback):
        window_high = high.iloc[i - lookback: i + lookback + 1]
        window_low  = low.iloc[i  - lookback: i + lookback + 1]

        if high.iloc[i] == window_high.max():
            idx = df.index[i]
            date_str = str(idx.date()) if hasattr(idx, "date") else str(idx)
            sh_dates.append(date_str)
            sh_prices.append(round(float(high.iloc[i]), 4))

        if low.iloc[i] == window_low.min():
            idx = df.index[i]
            date_str = str(idx.date()) if hasattr(idx, "date") else str(idx)
            sl_dates.append(date_str)
            sl_prices.append(round(float(low.iloc[i]), 4))

    return {
        "swing_highs": list(zip(sh_dates[-10:], sh_prices[-10:])),
        "swing_lows":  list(zip(sl_dates[-10:], sl_prices[-10:])),
        "last_close":  round(float(close.iloc[-1]), 4),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Calcolo per singolo DataFrame
# ──────────────────────────────────────────────────────────────────────────────

def _compute_tf(df: pd.DataFrame) -> dict:
    close  = df["Close"].squeeze().astype(float)
    high   = df["High"].squeeze().astype(float)
    low    = df["Low"].squeeze().astype(float)
    volume = df["Volume"].squeeze().astype(float)

    ind = {}

    # ── RSI 14 ────────────────────────────────────────────────────────────────
    ind["rsi_14"] = _rsi(close, 14)

    # ── MACD (12, 26, 9) ──────────────────────────────────────────────────────
    ema12              = close.ewm(span=12, adjust=False).mean()
    ema26              = close.ewm(span=26, adjust=False).mean()
    ind["macd_line"]   = ema12 - ema26
    ind["macd_signal"] = ind["macd_line"].ewm(span=9, adjust=False).mean()
    ind["macd_hist"]   = ind["macd_line"] - ind["macd_signal"]

    # ── Stochastic (14, 3) ────────────────────────────────────────────────────
    low14          = low.rolling(14).min()
    high14         = high.rolling(14).max()
    denom          = (high14 - low14).replace(0, np.nan)
    ind["stoch_k"] = 100 * (close - low14) / denom
    ind["stoch_d"] = ind["stoch_k"].rolling(3).mean()

    # ── Williams %R 14 ────────────────────────────────────────────────────────
    ind["williams_r"] = -100 * (high14 - close) / denom

    # ── Medie Mobili Semplici ─────────────────────────────────────────────────
    for p in [20, 50, 100, 200]:
        ind[f"sma_{p}"] = close.rolling(p).mean()

    # ── Medie Mobili Esponenziali ─────────────────────────────────────────────
    for p in [9, 20, 50, 100]:
        ind[f"ema_{p}"] = close.ewm(span=p, adjust=False).mean()

    # ── Bollinger Bands (20, 2) ───────────────────────────────────────────────
    bb_mid              = close.rolling(20).mean()
    bb_std              = close.rolling(20).std(ddof=0)
    ind["bb_upper"]     = bb_mid + 2 * bb_std
    ind["bb_mid"]       = bb_mid
    ind["bb_lower"]     = bb_mid - 2 * bb_std
    bb_range            = (ind["bb_upper"] - ind["bb_lower"]).replace(0, np.nan)
    ind["bb_pct"]       = (close - ind["bb_lower"]) / bb_range  # 0=lower, 1=upper
    ind["bb_bandwidth"] = bb_range / bb_mid * 100               # % del prezzo

    # ── ATR 14 ────────────────────────────────────────────────────────────────
    ind["atr_14"] = _atr(high, low, close, 14)

    # ── OBV ───────────────────────────────────────────────────────────────────
    ind["obv"] = _obv(close, volume)

    return ind


# ──────────────────────────────────────────────────────────────────────────────
# Primitive di calcolo
# ──────────────────────────────────────────────────────────────────────────────

def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=period - 1, adjust=False).mean()
    avg_l = loss.ewm(com=period - 1, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()
