"""
agents/supervisor_agent.py — Controller Multi-Agente V5 (Ibrido: Gemini + Qwen).
"""

import os
import re
import sys
import time
import datetime

# Fix path before importing Calibrazione
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from loguru import logger
import Calibrazione

# Import dei componenti Agno V5
from agents.agno_macro_expert import AgnoMacroExpert
from agents.context_expander_agent import ContextExpanderAgent
from agents.skill_selector import SkillSelector, TECHNIQUE_OVERLAY_MAP, AVAILABLE_TOOLS
from agents.specialists.pattern_agent import PatternAgent
from agents.specialists.trend_agent import TrendAgent
from agents.specialists.sr_agent import SRAgent
from agents.specialists.volume_agent import VolumeAgent
import indicators_engine
from context_builder import ContextBuilder

load_dotenv()


def _smart_sleep(error_message: str, fallback: int = 30) -> None:
    """
    Legge il tempo di attesa reale dal messaggio di errore Groq (rate limit)
    e aspetta esattamente il necessario + 2s di margine.
    """
    match_s = re.search(r"try again in ([\d.]+)s", error_message)
    if match_s:
        wait = float(match_s.group(1)) + 2
        logger.info(f"[RATE LIMIT] Attesa smart: {wait:.1f}s (da errore Groq)")
        time.sleep(wait)
        return

    match_ms = re.search(r"try again in (\d+)m([\d.]+)s", error_message)
    if match_ms:
        wait = int(match_ms.group(1)) * 60 + float(match_ms.group(2)) + 2
        logger.info(f"[RATE LIMIT] Attesa smart: {wait:.1f}s (da errore Groq)")
        time.sleep(wait)
        return

    logger.info(f"[RATE LIMIT] Tempo non estraibile — attesa fallback: {fallback}s")
    time.sleep(fallback)


def _call_with_retry(fn, *args, max_retries: int = 3, fallback: int = 30, **kwargs):
    """
    Esegue fn(*args, **kwargs) con retry automatico in caso di rate limit Groq.
    Dopo max_retries tentativi falliti rilancia l'eccezione.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = (
                "rate_limit" in err_str or
                "rate limit" in err_str or
                "429" in err_str or
                "try again in" in err_str or
                "too many requests" in err_str
            )
            if is_rate_limit and attempt < max_retries:
                logger.warning(f"[RATE LIMIT] Tentativo {attempt}/{max_retries} — {e}")
                _smart_sleep(str(e), fallback=fallback)
            else:
                raise


def _log_specialist_output(nome: str, testo: str) -> None:
    """
    Diagnostica post-analisi per ogni specialista:
    verifica presenza ## SINTESI OPERATIVA e logga tail per debug.
    """
    if not isinstance(testo, str) or not testo:
        logger.error(f"[SUPERVISORE] {nome}: output vuoto o non stringa.")
        return
    has_sintesi = "## SINTESI OPERATIVA" in testo.upper()
    if has_sintesi:
        logger.debug(
            f"[SUPERVISORE] {nome} — ✅ SINTESI OPERATIVA trovata | "
            f"Lunghezza output: {len(testo)} chars"
        )
    else:
        logger.error(
            f"[SUPERVISORE] {nome} — ❌ SINTESI OPERATIVA NON TROVATA | "
            f"Lunghezza output: {len(testo)} chars | "
            f"Tail:\n{testo[-400:]}"
        )


class SupervisorAgent:
    """
    Controller Multi-Agente V5 (Ibrido: Gemini + Qwen).
    Gestisce il flusso tra:
    - Analisi Macro (Gemini) — guida strategica per tutto il team
    - Selezione Skill (Llama) — sceglie quali tecniche dai libri applicare
    - Ricerca Libri/Knowledge (Gemini Agentic Search)
    - 4 Specialisti Tecnici Standalone (Qwen) — ognuno con le proprie Skill
    - Verdetto Finale (Qwen) — sintesi operativa con Bias, Entry, SL, TP
    """

    def __init__(self):
        self.provider = Calibrazione.LLM_PROVIDER
        self.storage_location = Calibrazione.STORAGE_LOCATION
        self.db_path = Calibrazione.DATABASE_PATH

        # Agenti di alto livello
        self.macro_expert     = AgnoMacroExpert()
        self.knowledge_expert = ContextExpanderAgent()

        # 4 Specialisti Tecnici Standalone (con Skill dai libri)
        self.pattern_agent = PatternAgent()
        self.trend_agent   = TrendAgent()
        self.sr_agent      = SRAgent()
        self.volume_agent  = VolumeAgent()

        logger.success("[AGNO SUPERVISOR] Sistema V5 IBRIDO pronto (Gemini + Qwen).")

    def analizza_asset(
        self,
        data_dict,
        nome_asset,
        start_date=None,
        end_date=None,
        context_extra="",
        projection_end_date=None,
        volume_profile=None,
        last_price=None,
    ):
        """
        Master Flow V5 (Modalità Sequenziale Salva-Quota).
        Restituisce una tupla (report_markdown, chosen_tools).

        Flusso:
          1. MacroExpert → sentiment macro e guida strategica
          1.5 SkillSelector → sceglie strumenti e produce skills_guidance per specialista
          2. ContextExpander → ricerca conoscenza nei libri (Gemini)
          3. 4 Specialisti tecnici standalone → analisi con Skill e guidance
          4. Verdetto Finale → sintesi operativa
        """
        logger.info(
            f"\n{'='*60}\n"
            f"AVVIO ANALISI SEQUENZIALE su {nome_asset}\n"
            f"Periodo: {start_date} -> {end_date}\n"
            f"{'='*60}"
        )

        # ── Step 1: Analisi Macro ─────────────────────────────────────
        if Calibrazione.AGENT_MACRO_ENABLED:
            query_macro = f"{nome_asset} news and global macro sentiment"
            macro_sentiment = _call_with_retry(
                self.macro_expert.analizza,
                query_macro,
                start_date=start_date,
                end_date=end_date,
                symbol=nome_asset,
                last_price=last_price,
            )
            logger.success("Sentiment Macro ottenuto.")
            logger.debug(
                f"[SUPERVISORE] Macro sentiment tail:\n"
                f"{macro_sentiment[-600:] if isinstance(macro_sentiment, str) else macro_sentiment}"
            )
        else:
            logger.info("[SUPERVISORE] Analisi Macro disattivata. Salto lo Step 1.")
            macro_sentiment = "ANALISI MACRO DISATTIVATA — bias direzionale non disponibile."

        # ── Step 1.5: Selezione Strumenti e Skills Guidance ──────────
        logger.info(f"[SUPERVISORE] Selezione strumenti tecnici per {nome_asset}...")
        skill_selector = SkillSelector()
        chosen_tools = skill_selector.select_tools(nome_asset, macro_sentiment, data_dict)
        if not chosen_tools.get("success", True):
            raise RuntimeError(
                f"[SUPERVISORE] Selezione strumenti AI fallita: "
                f"{chosen_tools.get('error', 'Unknown error')}. "
                "Verifica la risposta del modello SkillSelector nei log."
            )
        logger.success("[SUPERVISORE] Strumenti selezionati con successo.")

        # ── Step 2: Ricerca Biblioteca Gemini ────────────────────────
        logger.info(f"[SUPERVISORE] Interrogazione Biblioteca Gemini per {nome_asset}...")
        query_knowledge = (
            f"Quali sono le migliori strategie di trading e i pattern più affidabili "
            f"descritti nei libri per l'asset {nome_asset} "
            f"in un mercato con sentiment {macro_sentiment}?"
        )
        knowledge_context = self.knowledge_expert.search_knowledge(query_knowledge)

        # ── Preparazione contesto dati (1H + 4H + 1D) ───────────────
        logger.info("[SUPERVISORE] Calcolo indicatori tecnici pre-calcolati...")
        indicators_dict = indicators_engine.compute(data_dict)

        ctx_builder = ContextBuilder(
            data_dict        = data_dict,
            indicators_dict  = indicators_dict,
            knowledge_context= knowledge_context,
            macro_sentiment  = macro_sentiment,
            start_date       = start_date,
            end_date         = end_date,
            volume_profile   = volume_profile,
        )

        ctx_per_agent = {
            "pattern": ctx_builder.build("pattern"),
            "trend":   ctx_builder.build("trend"),
            "sr":      ctx_builder.build("sr"),
            "volume":  ctx_builder.build("volume"),
        }

        if context_extra:
            for k in ctx_per_agent:
                ctx_per_agent[k] += f"\n\n{context_extra}"

        # ── Step 3: Analisi Tecnica Sequenziale (4 Specialisti) ──────
        skills_guidance = chosen_tools.get("skills_guidance", {})

        specialist_config = [
            ("Pattern Analyst", Calibrazione.AGENT_PATTERN_ENABLED, self.pattern_agent, "pattern"),
            ("Trend Analyst",   Calibrazione.AGENT_TREND_ENABLED,   self.trend_agent,   "trend"),
            ("SR Analyst",      Calibrazione.AGENT_SR_ENABLED,       self.sr_agent,      "sr"),
            ("Volume Analyst",  Calibrazione.AGENT_VOLUME_ENABLED,   self.volume_agent,  "volume"),
        ]

        results_tech = {}
        logger.info("Inizio analisi tecnica sequenziale (4 specialisti)...")

        for nome, attivo, agente, guidance_key in specialist_config:
            if not attivo:
                results_tech[nome] = "Analisi Disattivata"
                logger.info(f"[SUPERVISORE] {nome}: disattivato in Calibrazione.")
                continue

            guidance  = skills_guidance.get(guidance_key, "")
            agent_ctx = ctx_per_agent[guidance_key]
            logger.info(f"Interrogazione {nome}...")

            try:
                if nome == "Volume Analyst":
                    altri_risultati = {
                        k: v for k, v in results_tech.items()
                        if v not in ("Analisi Disattivata", "N/D", "")
                    }
                    results_tech[nome] = _call_with_retry(
                        agente.analizza,
                        agent_ctx,
                        macro_sentiment,
                        skills_guidance=guidance,
                        other_analyses=altri_risultati,
                    )
                else:
                    results_tech[nome] = _call_with_retry(
                        agente.analizza,
                        agent_ctx,
                        macro_sentiment,
                        skills_guidance=guidance,
                    )
                logger.success(f"Risposta {nome} ricevuta.")

            except Exception as e:
                logger.error(f"[SUPERVISORE] Errore {nome}: {e}")
                results_tech[nome] = f"❌ ERRORE [{nome}]: {e}"

            # ── Diagnostica struttura output ──────────────────────────
            _log_specialist_output(nome, results_tech[nome])

        # ── Classificazione tecniche applicate vs. consultate ────────
        _domain_to_specialist = {
            "pattern": "Pattern Analyst",
            "trend":   "Trend Analyst",
            "sr":      "SR Analyst",
            "volume":  "Volume Analyst",
        }
        _domain_valid_ids: dict[str, set] = {
            d: {t["id"] for t in tools}
            for d, tools in AVAILABLE_TOOLS.items()
        }
        _domain_valid_ids["volume"] = (
            _domain_valid_ids.get("oscillator", set()) | {"volume_vsa"}
        )

        _techniques_pd = chosen_tools.get("techniques_per_domain", {})
        applied_per_domain: dict = {}

        _generic_skip = {
            "trend", "volume", "pattern", "price", "market", "trading",
            "candle", "candela", "chart", "grafico", "analisi", "scale",
            "scala", "open", "close", "high", "low",
        }

        for _domain, _specialist in _domain_to_specialist.items():
            _text    = results_tech.get(_specialist, "")
            _applied: list[dict] = []
            _seen_ids: set       = set()

            # ── L1: Strumenti AI-selezionati ──────────────────────────
            _llm_key = "oscillator" if _domain == "volume" else _domain
            for _tool in chosen_tools.get(_llm_key, []):
                _oid  = _tool.get("id")
                _name = _tool.get("name", _oid or "")
                if _oid and _oid not in _seen_ids:
                    _seen_ids.add(_oid)
                    _applied.append({"name": _name, "overlay_id": _oid})

            if isinstance(_text, str) and _text:
                _text_lower = _text.lower()
                _valid_ids  = _domain_valid_ids.get(_domain, set())

                # ── L1.5: Scan sezione '🛠️ STRUMENTI UTILIZZATI' ─────
                _sect_match = re.search(
                    r'STRUMENTI UTILIZZATI[^\n]*\n([\s\S]*?)(?=\n##\s|\Z)',
                    _text
                )
                if _sect_match:
                    for _line in _sect_match.group(1).split('\n'):
                        _ls = _line.strip()
                        if '✅' not in _ls:
                            continue
                        _tm = re.match(r'.*✅\s*(.+?)(?:\s*[—–\-]|$)', _ls)
                        if not _tm:
                            continue
                        _tech_name = _tm.group(1).strip()
                        if not _tech_name:
                            continue
                        for _kw, _oid in TECHNIQUE_OVERLAY_MAP:
                            if _oid in _seen_ids or _oid not in _valid_ids:
                                continue
                            if re.search(r'\b' + re.escape(_kw) + r'\b', _tech_name.lower()):
                                _seen_ids.add(_oid)
                                _applied.append({"name": _tech_name, "overlay_id": _oid})
                                break

                # ── L2: Keyword scan TECHNIQUE_OVERLAY_MAP ────────────
                for _kw, _oid in TECHNIQUE_OVERLAY_MAP:
                    if _oid in _seen_ids or _oid not in _valid_ids:
                        continue
                    if re.search(r'\b' + re.escape(_kw) + r'\b', _text_lower):
                        _seen_ids.add(_oid)
                        _applied.append({"name": _kw.title(), "overlay_id": _oid})

                # ── L3: Nomi SKILL.md → badge concettuali ─────────────
                for _book_techs in _techniques_pd.get(_domain, {}).values():
                    for _tech in _book_techs:
                        _tname   = _tech["name"] if isinstance(_tech, dict) else str(_tech)
                        _overlay = _tech.get("overlay_id") if isinstance(_tech, dict) else None
                        if _overlay:
                            continue
                        _clean = re.sub(r'\s*\([^)]*\)', '', _tname.lower()).strip()
                        _ms    = _clean if len(_clean.split()) >= 2 else _tname.lower()
                        if len(_ms.split()) == 1 and _ms in _generic_skip:
                            continue
                        if re.search(r'\b' + re.escape(_ms) + r'\b', _text_lower):
                            _applied.append({"name": _tname, "overlay_id": None})

            applied_per_domain[_domain] = _applied

        chosen_tools["applied_techniques_per_domain"] = applied_per_domain
        logger.info(
            "[SUPERVISORE] Tecniche applicate — "
            + ", ".join(f"{d}: {len(applied_per_domain[d])}" for d in _domain_to_specialist)
        )

        # ── Step 4: Verdetto Finale ───────────────────────────────────
        logger.info("Generazione verdetto finale (MacroExpert + trading-verdict-synthesizer)...")

        # Diagnostica pre-verdetto: verifica che tutti gli specialisti
        # abbiano prodotto ## SINTESI OPERATIVA prima di passare al verdict agent.
        mancanti = [
            nome for nome, testo in results_tech.items()
            if isinstance(testo, str)
            and testo not in ("Analisi Disattivata", "N/D")
            and "## SINTESI OPERATIVA" not in testo.upper()
            and not testo.startswith("❌")
        ]
        if mancanti:
            logger.warning(
                f"[SUPERVISORE] Specialisti senza ## SINTESI OPERATIVA: {mancanti}. "
                f"Il verdict agent riceverà messaggi di errore espliciti per questi agenti."
            )

        verdetto_finale = _call_with_retry(
            self.macro_expert.sintetizza_verdetto,
            nome_asset,
            macro_sentiment,
            results_tech,
            projection_end_date=projection_end_date,
        )
        logger.success("Verdetto finale generato.")

        # ── Assemblaggio Report Finale ────────────────────────────────
        if chosen_tools.get("success"):
            skills_list  = ", ".join(chosen_tools.get("raw_skills_used", [])) or "Skills Library"
            tools_section = f"**Fonti di conoscenza applicate:** {skills_list}\n\n{chosen_tools['summary']}"
        else:
            tools_section = (
                f"> [!CAUTION]\n"
                f"> **FALLIMENTO SELEZIONE DINAMICA AI**: L'intelligenza artificiale non è riuscita a "
                f"personalizzare gli strumenti tecnici per {nome_asset} "
                f"({chosen_tools.get('error', 'Unknown Error')})."
            )

        specialist_map = [
            ("Pattern Analyst", "🔍"),
            ("Trend Analyst",   "📈"),
            ("SR Analyst",      "🎯"),
            ("Volume Analyst",  "🌊"),
        ]
        tech_sections = ""
        for nome_spec, emoji in specialist_map:
            contenuto = results_tech.get(nome_spec, "")
            if contenuto and contenuto not in ("Analisi Disattivata", "N/D"):
                tech_sections += f"\n### {emoji} {nome_spec}\n{contenuto}\n"

        oggi = datetime.date.today().strftime("%d/%m/%Y")

        report_definitivo = f"""# REPORT TRADING AI: {nome_asset} — {oggi}

Questo report è il risultato dell'analisi coordinata dal **SupervisorAgent V5**, integrando dati macroeconomici, notizie real-time e l'analisi tecnica specialistica di 4 agenti IA con accesso alle Skill dai libri di trading.

---

## 🌎 ANALISI MACROECONOMICA E NEWS

{macro_sentiment}

---

## 📖 CONTESTO DALLA LIBRERIA (Strategie Master)

{knowledge_context}

---

## 🛠️ STRUMENTI SELEZIONATI DALL'AI

{tools_section}

---

## 📊 ANALISI TEAM TECNICO
{tech_sections}
---

## 🚀 VERDETTO FINALE E SETUP

{verdetto_finale}
"""

        return report_definitivo, chosen_tools


if __name__ == "__main__":
    from data_fetcher import DataFetcher

    def test_v5():
        supervisore = SupervisorAgent()
        data = DataFetcher.get_mtf_data("GC=F", days=60)
        report, _ = supervisore.analizza_asset(data, "GC=F")
        print("\n--- REPORT TRADING V5 ---")
        print(report)

    test_v5()