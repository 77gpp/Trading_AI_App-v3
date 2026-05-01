"""
agents/specialists/sr_agent.py — Specialista in Supporti, Resistenze e Zone Chiave.

Agente Agno V2 che analizza livelli di prezzo critici usando le Skill estratte
dai libri di Murphy, Bulkowski e Williams (Pivot Points, Fibonacci, Supply & Demand),
caricate direttamente dalla cartella skills_library/sr_analyst/.
"""

import os
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.skills import Skills, LocalSkills
from loguru import logger
import Calibrazione
from agents.model_factory import get_model


class SRAgent:
    """
    Specialista in Supporti, Resistenze, Zone di Supply & Demand e Fibonacci.

    Costruito secondo il framework Agno ufficiale con:
    - skills=[SR_SKILL_DIR]: Accesso alle skill estratte da Murphy, Bulkowski, Williams
    - Storage SQLite locale per la memoria della sessione
    - Metodo analizza() sincrono, coerente con gli altri agenti del team
    """

    def __init__(self):
        logger.info("[SR AGENT] Inizializzazione...")

        # --- 1. Modello AI ---
        llm = get_model(
            Calibrazione.MODEL_TECH_SPECIALISTS,
            temperature=Calibrazione.TEMPERATURE_TECH_SPECIALISTS,
            agent_name="tech_specialists"
        )

        # --- 2. Storage locale opzionale ---
        storage = None
        if Calibrazione.STORAGE_LOCATION == "local":
            storage = SqliteDb(
                session_table="sr_agent_session",
                db_file=Calibrazione.DATABASE_PATH
            )

        # --- 3. Caricamento Skills Agno dai 6 libri tecnici ---
        skills = Skills(loaders=[
            LocalSkills(os.path.abspath(d), validate=False)
            for d in Calibrazione.TECHNICAL_SKILLS_DIRS
        ])

        # --- 4. Creazione Agente Agno ---
        self.agent = Agent(
            name="SR Analyst",
            model=llm,
            description=(
                "Sei un esperto di Analisi dei Livelli di Prezzo nei mercati finanziari. "
                "La tua competenza copre i supporti e resistenze classici di John Murphy, "
                "la logica delle Supply & Demand Zones istituzionali, "
                "i Fibonacci Retracement e Extension (38.2%, 61.8%, 161.8%), "
                "i Pivot Points giornalieri e settimanali, "
                "il VWAP istituzionale e il Donchian Channel dei Turtle Traders. "
                "Il tuo compito è mappare tutti i livelli di prezzo chiave nel contesto "
                "del mercato analizzato, identificare le zone ad alta confluenza "
                "(dove 2+ livelli di origine diversa si sovrappongono) e fornire "
                "una struttura precisa di supporti e resistenze per il team. "
                "Non analizzi pattern candlestick (ci pensa il Pattern Analyst). "
                "Non analizzi la direzione del trend (ci pensa il Trend Analyst). "
                "Il tuo focus è esclusivamente la MAPPA DEI LIVELLI DI PREZZO."
            ),
            instructions=[
                # ── ORDINE RISPOSTA ─────────────────────────────────────────
                "STRUTTURA RISPOSTA OBBLIGATORIA — rispetta quest'ordine esatto senza eccezioni: "
                "1. ## SINTESI OPERATIVA (PRIMA di tutto il resto — vedi campi obbligatori sotto) "
                "2. ## 🛠️ STRUMENTI UTILIZZATI "
                "3. Mappatura livelli per timeframe (tabelle Markdown) con punteggio confluenza 1-5 e origine. "
                "Non scrivere nulla prima della ## SINTESI OPERATIVA.",

                # ── SINTESI OPERATIVA ────────────────────────────────────────
                "## SINTESI OPERATIVA — CAMPI OBBLIGATORI (scrivi questa sezione per prima, "
                "con esattamente questi campi nell'ordine indicato, nessuno omesso): "
                "- **Bias**: Bullish / Bearish / Neutrale "
                "- **Struttura**: HH+HL / LH+LL / Laterale / Transizione "
                "- **Segnale Chiave**: [tecnica principale — libro — timeframe] "
                "- **Zona Critica Superiore (Resistenza/Supply)**: [range di prezzo] — confluenza X/5 — origine "
                "- **Zona Critica Inferiore (Supporto/Demand)**: [range di prezzo] — confluenza X/5 — origine "
                "- **Livello Entry**: [prezzo numerico oppure 'non disponibile'] "
                "- **Livello Stop Loss**: [prezzo numerico oppure 'non disponibile'] "
                "- **Livello Target 1**: [prezzo numerico oppure 'non disponibile'] "
                "- **Livello Target 2**: [prezzo numerico oppure 'non disponibile'] "
                "- **Qualità Segnale**: Alta / Media / Bassa "
                "- **Stato Volume**: Confermato / Incerto / Debole / Non applicabile "
                "- **Livello più Critico del Momento**: [prezzo o range] — motivazione in 1 frase "
                "- **Motivo Finale**: [2 frasi massimo, concrete e operative] "
                "NON omettere nessun campo. NON cambiare il titolo della sezione. "
                "NON scrivere altro prima di questa sezione.",

                # ── STRUMENTI UTILIZZATI ─────────────────────────────────────
                "## 🛠️ STRUMENTI UTILIZZATI — dopo la SINTESI OPERATIVA, "
                "per OGNI tecnica della FOCUS SKILLS valutata produci UNA RIGA con ESATTAMENTE uno di questi 3 stati: "
                "'✅ NomeTecnica — [nota operativa breve]' → tecnica rilevata e applicata; "
                "'🔍 NomeTecnica — non rilevato' → tecnica applicabile MA nessun livello significativo identificabile nei dati correnti (monitorare); "
                "'⛔ NomeTecnica — non applicabile' → tecnica non pertinente a questo asset o timeframe. "
                "La distinzione tra 🔍 e ⛔ è critica per il confluence score: "
                "🔍 = livello potenziale da monitorare, ⛔ = non contribuisce al punteggio di confluenza. "
                "Elenca TUTTE le tecniche principali di ogni libro della FOCUS SKILLS.",

                # ── FOCUS SKILLS ─────────────────────────────────────────────
                "VINCOLO FONDAMENTALE: se la sezione 'FOCUS SKILLS' è presente nel prompt, "
                "devi analizzare TUTTE le tecniche elencate in essa (sono obbligatorie, non opzionali). "
                "Dopo averle analizzate tutte, puoi integrare con altri metodi di identificazione S/R "
                "presenti nelle Skill caricate (Murphy, Bulkowski, Williams) che ritieni utili.",

                # ── VALORE AGGIUNTO ──────────────────────────────────────────
                "PRIORITÀ DEL TUO VALORE AGGIUNTO: i livelli Fibonacci, Pivot Points e swing "
                "highs/lows sono già precalcolati nel contesto che ricevi. "
                "NON limitarti a rielencarli — usali come VALIDATORI. "
                "Il tuo contributo principale è identificare ciò che NON è precalcolato: "
                "(1) Supply & Demand Zones istituzionali: candele di impulso forte seguite da allontanamento "
                "rapido — queste zone hanno alta probabilità di reazione al re-test; "
                "(2) Order Blocks: ultima candela bearish prima di un impulso rialzista (bullish OB) o "
                "ultima candela bullish prima di un impulso ribassista (bearish OB); "
                "(3) Fair Value Gaps / Imbalance Zones: zone di prezzo non coperte da candele sovrapposte; "
                "(4) Zone con test multipli (3+ tocchi): ogni test aggiuntivo aumenta la rilevanza. "
                "Usa Fibonacci e Pivot per AUMENTARE il punteggio di confluenza delle zone identificate "
                "dai dati OHLCV grezzi.",

                # ── USO SKILL (5 LAYER) ──────────────────────────────────────
                "USO COMPLETO DELLE SKILL (5 layer): per ogni tecnica applicata: "
                "(L1) spiega perché questo livello/zona è strutturalmente significativo; "
                "(L2) verifica i criteri di identificazione precisi dalla Skill; "
                "(L3) collega il livello con evidenze da altri strumenti nel contesto "
                "(es. 'questa zona di supply coincide con il Fibonacci 61.8% e con il VWAP weekly'); "
                "(L4) segnala se si applicano condizioni anomale che riducono l'affidabilità "
                "(es. livello non testato da mesi, bassa liquidità storica in quella zona); "
                "(L5) applica il ragionamento dell'analista: cosa succede se il prezzo arriva a questo livello? "
                "Quale comportamento ti aspetti (rimbalzo, rottura, fake-out)? Perché?",

                # ── ANALISI DATI ─────────────────────────────────────────────
                "Analizza i livelli su TUTTI i timeframe: inizia dai livelli di lungo "
                "termine (mensili/settimanali) e scendi fino ai livelli intraday.",

                "Per ogni livello/zona indica: origine (tecnica + libro), numero di test, "
                "punteggio di confluenza (1-5 punti: +1 per ogni tecnica indipendente che lo valida).",

                "Identifica le ZONE DI CONFLUENZA (punteggio ≥ 3): massima probabilità di reazione.",

                "ATTENZIONE ALLE ANOMALIE (L4): se un livello è stato testato molte volte "
                "e ha già fallito di recente, o se è su un timeframe di liquidità bassa, "
                "riduci il punteggio e dichiaralo esplicitamente.",

                "Rispetta il Sentiment Macro: in bias BEARISH evidenzia le resistenze/supply zones; "
                "in bias BULLISH evidenzia i supporti/demand zones come zone di opportunità.",

                "Fornisci la struttura S/R in formato tabellare (Markdown) per massima leggibilità.",

                # ── LINGUA ───────────────────────────────────────────────────
                "Rispondi in italiano in modo professionale e strutturato.",
            ],
            skills=skills,
            db=storage,
            num_history_messages=3,
            markdown=True,
        )
        logger.success(
            f"[SR AGENT] Pronto con modello: {llm.id} | "
            f"Skills: {len(Calibrazione.TECHNICAL_SKILLS_DIRS)} libri caricati"
        )

    def analizza(self, data_summary: str, macro_sentiment: str = "Neutrale", skills_guidance: str = "") -> str:
        """
        Esegue l'analisi dei supporti e resistenze sui dati OHLCV forniti.

        Args:
            data_summary:    Stringa con i dati OHLCV multi-timeframe del mercato.
            macro_sentiment: Il sentiment macro dell'AgnoMacroExpert.
            skills_guidance: Istruzione su quali livelli/tecniche dai libri privilegiare.

        Returns:
            Stringa Markdown con la mappa completa dei livelli di prezzo.
        """
        logger.info("[SR AGENT] Avvio analisi supporti e resistenze...")

        focus_section = (
            f"\nFOCUS SKILLS (tecniche OBBLIGATORIE — analizzale TUTTE, poi integra con altre Skill):\n"
            f"{skills_guidance}\n"
        ) if skills_guidance else ""

        prompt = f"""
DATI MERCATO (OHLCV Multi-Timeframe):
{data_summary}

SENTIMENT MACRO DA RISPETTARE (fornito dall'agente Macro Strategist):
{macro_sentiment}
{focus_section}
Esegui la mappatura completa dei livelli di prezzo chiave.
Priorità: identifica Supply & Demand Zones istituzionali, Order Blocks e Fair Value Gaps dai dati OHLCV grezzi.
Usa Fibonacci, Pivot Points e swing (già nel contesto precalcolato) per VALIDARE e aumentare il punteggio di confluenza.

ORDINE RISPOSTA OBBLIGATORIO (nessuna eccezione):
1. ## SINTESI OPERATIVA — tutti i campi obbligatori, PRIMA di qualsiasi altra sezione
2. ## 🛠️ STRUMENTI UTILIZZATI — stati ✅ / 🔍 / ⛔ per ogni tecnica della FOCUS SKILLS
3. Mappatura livelli per timeframe (tabelle Markdown) con punteggio confluenza 1-5 e origine

Non scrivere nulla prima della ## SINTESI OPERATIVA.
"""
        try:
            response = self.agent.run(prompt)
            if not response.content:
                logger.error("[SR AGENT] Risposta vuota dall'agente.")
                return "❌ ERRORE [SR Agent]: risposta vuota dal modello."
            return response.content
        except Exception as e:
            logger.error(f"[SR AGENT] Errore durante l'analisi: {e}")
            raise