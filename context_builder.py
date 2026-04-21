"""
context_builder.py — Assembla il contesto per-agente combinando OHLCV raw
e misurazioni oggettive pre-calcolate.

Architettura a tre blocchi:
  Blocco 1 — OHLCV Raw          : invariato, identico per tutti gli agenti
  Blocco 2 — Misurazioni Oggettive: pre-calcolate, filtrate per dominio agente
  Blocco 3 — Struttura Swing    : pivot algoritmici, filtrati per dominio agente

Tabella di filtraggio per dominio:
  ┌──────────────────┬─────────┬───────┬────┬────────┐
  │ Blocco           │ Pattern │ Trend │ SR │ Volume │
  ├──────────────────┼─────────┼───────┼────┼────────┤
  │ OHLCV raw        │    ✅   │  ✅   │ ✅ │   ✅   │
  │ Medie Mobili     │    ❌   │  ✅   │ ✅ │   ❌   │
  │ Oscillatori      │    ❌   │  ✅   │ ❌ │   ✅   │
  │ Bollinger + ATR  │    ❌   │  ✅   │ ✅ │   ✅   │
  │ Volume Profile   │    ❌   │  ❌   │ ✅ │   ✅   │
  │ Swing Structure  │    ✅   │  ✅   │ ✅ │   ❌   │
  └──────────────────┴─────────┴───────┴────┴────────┘

Il Pattern Agent non vede oscillatori — mantiene indipendenza di giudizio.
Il Volume Agent non vede medie mobili — si concentra su VSA/Wyckoff puro.
"""

import pandas as pd
import indicators_engine
from loguru import logger


# ──────────────────────────────────────────────────────────────────────────────
# Tabella di filtraggio blocchi per dominio agente
# ──────────────────────────────────────────────────────────────────────────────

_AGENT_BLOCKS = {
    "pattern": {
        "moving_averages": False,
        "oscillators":     False,
        "bollinger_atr":   False,
        "volume_metrics":  False,
        "swing_structure": True,
    },
    "trend": {
        "moving_averages": True,
        "oscillators":     True,
        "bollinger_atr":   True,
        "volume_metrics":  False,
        "swing_structure": True,
    },
    "sr": {
        "moving_averages": True,
        "oscillators":     False,
        "bollinger_atr":   True,
        "volume_metrics":  True,
        "swing_structure": True,
    },
    "volume": {
        "moving_averages": False,
        "oscillators":     True,
        "bollinger_atr":   True,
        "volume_metrics":  True,
        "swing_structure": False,
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# ContextBuilder
# ──────────────────────────────────────────────────────────────────────────────

class ContextBuilder:
    """
    Assembla contesti per-agente da OHLCV raw + indicatori pre-calcolati.

    Ogni chiamata a build(domain) restituisce una stringa formattata
    con il sottoinsieme di dati appropriato per quel dominio.
    """

    def __init__(
        self,
        data_dict: dict,
        indicators_dict: dict,
        knowledge_context: str,
        macro_sentiment: str,
        start_date: str,
        end_date: str,
        volume_profile: dict = None,
    ):
        self.data_dict        = data_dict
        self.indicators_dict  = indicators_dict
        self.knowledge_context = knowledge_context
        self.macro_sentiment   = macro_sentiment
        self.start_date        = start_date
        self.end_date          = end_date
        self.volume_profile    = volume_profile or {}

        # Pre-calcola strutture swing (lookback adattivo per timeframe)
        _lookback = {"1d": 3, "4h": 4, "1h": 5}
        self._swings = {}
        for tf, df in data_dict.items():
            if df is not None and not df.empty and len(df) >= 15:
                try:
                    self._swings[tf] = indicators_engine.swing_points(
                        df, lookback=_lookback.get(tf, 3)
                    )
                except Exception as e:
                    logger.warning(f"[CTX BUILDER] Swing {tf} fallito: {e}")
                    self._swings[tf] = {}

    def build(self, agent_domain: str) -> str:
        """
        Costruisce il data_summary completo per un agente specifico.

        Args:
            agent_domain: "pattern" | "trend" | "sr" | "volume"

        Returns:
            Stringa Markdown formattata pronta per l'LLM.
        """
        blocks = _AGENT_BLOCKS.get(agent_domain, {})
        parts  = []

        # ── Header comune ────────────────────────────────────────────────────
        parts.append(f"PERIODO ANALISI: dal {self.start_date or 'N/D'} al {self.end_date or 'N/D'}")
        parts.append("")
        parts.append("CONTESTO STRATEGICO (DAI LIBRI):")
        parts.append(self.knowledge_context)
        parts.append("")
        parts.append("GUIDA MACRO (dal Macro Strategist — usa questa come bussola direzionale):")
        parts.append(self.macro_sentiment)
        parts.append("")

        # ── Blocco 1: OHLCV Raw (identico per tutti gli agenti) ──────────────
        parts.append(self._build_ohlcv_block())

        # ── Blocco 2 + 3: Misurazioni filtrate per dominio ───────────────────
        measurements = self._build_measurements_block(agent_domain, blocks)
        if measurements:
            parts.append("")
            parts.append(measurements)

        return "\n".join(parts)

    # ──────────────────────────────────────────────────────────────────────────
    # Blocco 1 — OHLCV Raw
    # ──────────────────────────────────────────────────────────────────────────

    def _build_ohlcv_block(self) -> str:
        lines  = []
        df_1h  = self.data_dict.get("1h")
        df_4h  = self.data_dict.get("4h")
        df_1d  = self.data_dict.get("1d")

        # 1H: riepilogo giornaliero + raw recenti
        if df_1h is not None and not df_1h.empty:
            df_1h_daily  = df_1h.resample("D").agg(
                {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
            ).dropna()
            df_1h_recent = df_1h.tail(72)
            lines.append(f"DATI 1H — BREVE TERMINE ({len(df_1h)} candele totali nel periodo):")
            lines.append(f"Riepilogo Giornaliero — intero periodo ({len(df_1h_daily)} giorni):")
            lines.append(df_1h_daily.to_string())
            lines.append("")
            lines.append(f"Dettaglio Raw Recente (ultime {len(df_1h_recent)} candele 1H ~3 giorni):")
            lines.append(df_1h_recent.to_string())

        # 4H: riepilogo settimanale + raw recenti
        if df_4h is not None and not df_4h.empty:
            df_4h_weekly = df_4h.resample("W").agg(
                {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
            ).dropna()
            df_4h_recent = df_4h.tail(90)
            lines.append("")
            lines.append(f"DATI 4H — MEDIO TERMINE ({len(df_4h)} candele totali nel periodo):")
            lines.append(f"Riepilogo Settimanale — intero periodo ({len(df_4h_weekly)} settimane):")
            lines.append(df_4h_weekly.to_string())
            lines.append("")
            lines.append(
                f"Dettaglio Raw Recente (ultime {len(df_4h_recent)} candele 4H "
                f"~{len(df_4h_recent) // 6} giorni):"
            )
            lines.append(df_4h_recent.to_string())

        # 1D: intero periodo
        if df_1d is not None and not df_1d.empty:
            lines.append("")
            lines.append(f"DATI 1D — LUNGO TERMINE ({len(df_1d)} giorni — intero periodo selezionato):")
            lines.append(df_1d.to_string())

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # Blocco 2 + 3 — Misurazioni Oggettive + Struttura Swing
    # ──────────────────────────────────────────────────────────────────────────

    def _build_measurements_block(self, agent_domain: str, blocks: dict) -> str:
        sections = []

        for tf in ["1d", "4h", "1h"]:
            ind = self.indicators_dict.get(tf, {})
            df  = self.data_dict.get(tf)
            if not ind or df is None or df.empty:
                continue

            tf_label  = {"1d": "LUNGO TERMINE (1D)", "4h": "MEDIO TERMINE (4H)", "1h": "BREVE TERMINE (1H)"}[tf]
            close_last = float(df["Close"].iloc[-1])
            tf_lines   = []

            # Medie Mobili
            if blocks.get("moving_averages"):
                ma_section = self._fmt_moving_averages(ind, close_last, tf_label)
                if ma_section:
                    tf_lines.append(ma_section)

            # Oscillatori
            if blocks.get("oscillators"):
                osc_section = self._fmt_oscillators(ind, tf_label)
                if osc_section:
                    tf_lines.append(osc_section)

            # Bollinger + ATR
            if blocks.get("bollinger_atr"):
                bb_section = self._fmt_bollinger_atr(ind, close_last, tf_label)
                if bb_section:
                    tf_lines.append(bb_section)

            # Metriche Volume / POC
            if blocks.get("volume_metrics"):
                vol_section = self._fmt_volume_metrics(ind, tf, tf_label)
                if vol_section:
                    tf_lines.append(vol_section)

            if tf_lines:
                sections.append("\n".join(tf_lines))

        # Struttura Swing (non dipende dal timeframe, è un blocco unico)
        if blocks.get("swing_structure"):
            swing_section = self._fmt_swing_structure()
            if swing_section:
                sections.append(swing_section)

        if not sections:
            return ""

        sep    = "═" * 60
        header = f"{sep}\nBLOCCO 2 — MISURAZIONI OGGETTIVE PRE-CALCOLATE\n(Misurazioni, non interpretazioni. Le Skill traducono i numeri in significato.)\n{sep}"
        return header + "\n\n" + "\n\n".join(sections)

    # ── Formattatori sezione ──────────────────────────────────────────────────

    def _fmt_moving_averages(self, ind: dict, close_last: float, tf_label: str) -> str:
        lines = [f"── Medie Mobili {tf_label} ──"]
        added = False

        ma_map = [
            ("sma_20",  "SMA 20"),
            ("sma_50",  "SMA 50"),
            ("sma_100", "SMA 100"),
            ("sma_200", "SMA 200"),
            ("ema_9",   "EMA 9"),
            ("ema_20",  "EMA 20"),
            ("ema_50",  "EMA 50"),
            ("ema_100", "EMA 100"),
        ]
        for key, label in ma_map:
            val = _last(ind.get(key))
            if val is None:
                continue
            pos      = "SOPRA" if close_last > val else "SOTTO"
            dist_pct = abs(close_last - val) / val * 100
            lines.append(f"  {label}: {val:.2f} | Prezzo {pos} ({dist_pct:.1f}% distanza)")
            added = True

        return "\n".join(lines) if added else ""

    def _fmt_oscillators(self, ind: dict, tf_label: str) -> str:
        lines = [f"── Oscillatori {tf_label} ──"]
        added = False

        # RSI
        rsi = _last(ind.get("rsi_14"))
        if rsi is not None:
            if rsi < 30:
                zone = "IPERVENDUTO (<30)"
            elif rsi > 70:
                zone = "IPERCOMPRATO (>70)"
            else:
                zone = f"NEUTRALE ({rsi:.0f}/100)"
            lines.append(f"  RSI 14: {rsi:.1f} | Zona: {zone}")
            added = True

        # MACD
        ml = _last(ind.get("macd_line"))
        ms = _last(ind.get("macd_signal"))
        mh = _last(ind.get("macd_hist"))
        mh_prev = _prev(ind.get("macd_hist"))
        if ml is not None and ms is not None:
            cross    = "RIALZISTA (line>signal)" if ml > ms else "RIBASSISTA (line<signal)"
            hist_dir = ""
            if mh is not None and mh_prev is not None:
                hist_dir = (
                    " | Istogramma ESPANDENTE" if abs(mh) > abs(mh_prev)
                    else " | Istogramma CONTRAENTE"
                )
            lines.append(f"  MACD: Line={ml:.4f} | Signal={ms:.4f} | {cross}{hist_dir}")
            added = True

        # Stochastic
        sk = _last(ind.get("stoch_k"))
        sd = _last(ind.get("stoch_d"))
        if sk is not None and sd is not None:
            if sk < 20:
                zone = "IPERVENDUTO (<20)"
            elif sk > 80:
                zone = "IPERCOMPRATO (>80)"
            else:
                zone = "NEUTRALE (20-80)"
            cross = "K>D rialzista" if sk > sd else "K<D ribassista"
            lines.append(f"  Stochastic: %K={sk:.1f} | %D={sd:.1f} | {zone} | {cross}")
            added = True

        # Williams %R
        wr = _last(ind.get("williams_r"))
        if wr is not None:
            if wr < -80:
                zone = "IPERVENDUTO (<-80)"
            elif wr > -20:
                zone = "IPERCOMPRATO (>-20)"
            else:
                zone = "NEUTRALE"
            lines.append(f"  Williams %R: {wr:.1f} | Zona: {zone}")
            added = True

        return "\n".join(lines) if added else ""

    def _fmt_bollinger_atr(self, ind: dict, close_last: float, tf_label: str) -> str:
        lines = [f"── Bollinger Bands + ATR {tf_label} ──"]
        added = False

        bu = _last(ind.get("bb_upper"))
        bm = _last(ind.get("bb_mid"))
        bl = _last(ind.get("bb_lower"))
        bp = _last(ind.get("bb_pct"))
        bw = _last(ind.get("bb_bandwidth"))

        if bu is not None and bm is not None and bl is not None:
            if close_last > bu:
                pos = "SOPRA upper band (possibile estensione)"
            elif close_last < bl:
                pos = "SOTTO lower band (possibile oversold)"
            else:
                pct_str = f"{(bp or 0) * 100:.0f}%" if bp is not None else "—"
                pos = f"{pct_str} nella banda (0%=lower, 100%=upper)"
            lines.append(f"  BB Upper: {bu:.2f} | Mid: {bm:.2f} | Lower: {bl:.2f}")
            lines.append(f"  Prezzo: {close_last:.2f} ({pos})")
            if bw is not None:
                lines.append(f"  Larghezza banda: {bw:.1f}% del prezzo")
            added = True

        atr = _last(ind.get("atr_14"))
        if atr is not None:
            atr_pct = atr / close_last * 100 if close_last else 0
            lines.append(f"  ATR 14: {atr:.2f} ({atr_pct:.1f}% del prezzo — volatilità unitaria)")
            added = True

        return "\n".join(lines) if added else ""

    def _fmt_volume_metrics(self, ind: dict, tf: str, tf_label: str) -> str:
        lines = [f"── Metriche Volume {tf_label} ──"]
        added = False

        obv_last = _last(ind.get("obv"))
        obv_prev = _prev(ind.get("obv"), n=4)
        if obv_last is not None and obv_prev is not None:
            obv_dir = "CRESCENTE (pressione acquisto)" if obv_last > obv_prev else "DECRESCENTE (pressione vendita)"
            lines.append(f"  OBV: {obv_last:,.0f} | Tendenza ultime 5 barre: {obv_dir}")
            added = True

        # Volume Profile POC (solo per 1D, dal dict pre-calcolato)
        if tf == "1d" and self.volume_profile:
            poc     = self.volume_profile.get("poc")
            max_vol = self.volume_profile.get("max_volume")
            if poc:
                lines.append(f"  Volume Profile POC: {poc}")
                added = True
            if max_vol:
                lines.append(f"  Livello Max Volume: {max_vol}")
                added = True

        return "\n".join(lines) if added else ""

    def _fmt_swing_structure(self) -> str:
        lines = ["── Struttura di Mercato — Swing Algoritmici (Blocco 3) ──"]
        added = False

        for tf in ["1d", "4h", "1h"]:
            sw = self._swings.get(tf, {})
            if not sw:
                continue
            tf_label = {"1d": "1D", "4h": "4H", "1h": "1H"}[tf]

            sh = sw.get("swing_highs", [])
            sl = sw.get("swing_lows", [])

            if sh:
                sh_str = "  |  ".join(f"{d}: {p}" for d, p in sh[-5:])
                lines.append(f"  Swing Highs {tf_label}: {sh_str}")
                added = True
            if sl:
                sl_str = "  |  ".join(f"{d}: {p}" for d, p in sl[-5:])
                lines.append(f"  Swing Lows  {tf_label}: {sl_str}")
                added = True

        return "\n".join(lines) if added else ""


# ──────────────────────────────────────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────────────────────────────────────

def _last(series) -> float | None:
    """Ultimo valore valido di una Series."""
    if series is None:
        return None
    try:
        val = series.dropna().iloc[-1] if hasattr(series, "dropna") else float(series)
        return round(float(val), 4)
    except (IndexError, TypeError, ValueError):
        return None


def _prev(series, n: int = 1) -> float | None:
    """Penultimo (o n-esimo dal fondo) valore valido di una Series."""
    if series is None:
        return None
    try:
        clean = series.dropna()
        if len(clean) < n + 1:
            return None
        return round(float(clean.iloc[-(n + 1)]), 4)
    except (IndexError, TypeError, ValueError):
        return None
