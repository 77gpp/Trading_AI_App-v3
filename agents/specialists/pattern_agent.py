"""
agents/specialists/pattern_agent.py — Specialista in Pattern Recognition.

Agente Agno V2 che analizza candlestick e formazioni grafiche usando le Skill
estratte dai libri di Steve Nison, Thomas Bulkowski e Joe Ross, caricate
direttamente dalla cartella skills_library/pattern_analyst/.
"""

import os
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.skills import Skills, LocalSkills
from loguru import logger
import Calibrazione
from agents.model_factory import get_model


class PatternAgent:
    """
    Specialista in Pattern Recognition (Candlestick e Formazioni Grafiche).

    Costruito secondo il framework Agno ufficiale con:
    - skills=[PATTERN_SKILL_DIR]: Accesso alle skill estratte da Nison, Bulkowski, Joe Ross
    - Storage SQLite locale per la memoria della sessione
    - Metodo analizza() sincrono, coerente con gli altri agenti del team
    """

    def __init__(self):
        logger.info("[PATTERN AGENT] Inizializzazione...")

        # --- 1. Modello AI (dal factory, supporta Gemini o Qwen/Groq) ---
        llm = get_model(
            Calibrazione.MODEL_TECH_SPECIALISTS,
            temperature=Calibrazione.TEMPERATURE_TECH_SPECIALISTS,
            agent_name="tech_specialists"
        )

        # --- 2. Storage locale opzionale ---
        storage = None
        if Calibrazione.STORAGE_LOCATION == "local":
            storage = SqliteDb(
                session_table="pattern_agent_session",
                db_file=Calibrazione.DATABASE_PATH
            )

        # --- 3. Caricamento Skills Agno dai 6 libri tecnici ---
        skills = Skills(loaders=[
            LocalSkills(os.path.abspath(d), validate=False)
            for d in Calibrazione.TECHNICAL_SKILLS_DIRS
        ])

        # --- 4. Creazione Agente Agno ---
        self.agent = Agent(
            name="Pattern Analyst",
            model=llm,
            description=(
                "Sei un esperto mondiale di Pattern Recognition nei mercati finanziari. "
                "La tua competenza integra la tradizione giapponese delle candele (Steve Nison), "
                "la statistica dei pattern grafici (Thomas Bulkowski — Encyclopedia of Chart Patterns) "
                "e i sistemi operativi di Joe Ross (1-2-3 Pattern, Hook of Ross, Power Bars). "
                "Il tuo compito è analizzare i dati OHLCV forniti, identificare tutti i pattern "
                "rilevanti e fornire una valutazione dell'affidabilità di ogni segnale nel "
                "contesto del sentiment macro ricevuto. "
                "Non fai previsioni di prezzo esatte — identifichi configurazioni di mercato "
                "con alta probabilità statistica di sviluppi specifici."
            ),
            instructions=[
                # ── ORDINE RISPOSTA ─────────────────────────────────────────
                "STRUTTURA RISPOSTA OBBLIGATORIA — rispetta quest'ordine esatto senza eccezioni: "
                "1. ## SINTESI OPERATIVA (PRIMA di tutto il resto — vedi campi obbligatori sotto) "
                "2. ## 🛠️ STRUMENTI UTILIZZATI "
                "3. Analisi dettagliata dei pattern per timeframe.",

                # ── SINTESI OPERATIVA ────────────────────────────────────────
                "## SINTESI OPERATIVA — CAMPI OBBLIGATORI (scrivi questa sezione per prima, "
                "con esattamente questi campi nell'ordine indicato, nessuno omesso): "
                "- **Bias**: Bullish / Bearish / Neutrale "
                "- **Struttura**: HH+HL / LH+LL / Laterale / Transizione "
                "- **Segnale Chiave**: [NomeTecnica — libro — timeframe] "
                "- **Affidabilità**: Alta / Media / Bassa + percentuale se disponibile "
                "- **Livello Entry**: [prezzo numerico oppure 'non disponibile'] "
                "- **Livello Stop Loss**: [prezzo numerico oppure 'non disponibile'] "
                "- **Livello Target 1**: [prezzo numerico oppure 'non disponibile'] "
                "- **Livello Target 2**: [prezzo numerico oppure 'non disponibile'] "
                "- **Qualità Segnale**: Alta / Media / Bassa "
                "- **Stato Volume**: Confermato / Incerto / Debole / Non applicabile "
                "- **Condizione di Invalidazione**: [condizione specifica che annulla il segnale] "
                "- **Motivo Finale**: [2 frasi massimo, concrete e operative] "
                "NON omettere nessun campo. NON cambiare il titolo della sezione. "
                "NON scrivere altro prima di questa sezione.",

                # ── STRUMENTI UTILIZZATI ─────────────────────────────────────
                "## 🛠️ STRUMENTI UTILIZZATI — dopo la SINTESI OPERATIVA, "
                "per OGNI tecnica della FOCUS SKILLS valutata produci UNA RIGA con ESATTAMENTE uno di questi 3 stati: "
                "'✅ NomeTecnica — [nota operativa breve]' → tecnica rilevata e applicata; "
                "'🔍 NomeTecnica — non rilevato' → tecnica applicabile a questo asset MA assente nei dati correnti (monitorare); "
                "'⛔ NomeTecnica — non applicabile' → tecnica non pertinente a questo asset o condizione. "
                "La distinzione tra 🔍 e ⛔ è critica: 🔍 = 'potrebbe apparire presto', ⛔ = 'irrilevante per questo contesto'. "
                "Elenca TUTTE le tecniche principali di ogni libro della FOCUS SKILLS.",

                # ── FOCUS SKILLS ─────────────────────────────────────────────
                "VINCOLO FONDAMENTALE: se la sezione 'FOCUS SKILLS' è presente nel prompt, "
                "devi analizzare TUTTE le tecniche elencate in essa (sono obbligatorie, non opzionali). "
                "Dopo averle analizzate tutte, puoi integrare con altri pattern e tecniche "
                "presenti nelle Skill caricate (libri di Nison, Bulkowski, Joe Ross) che ritieni utili.",

                # ── USO SKILL (5 LAYER) ──────────────────────────────────────
                "USO COMPLETO DELLE SKILL (5 layer): per ogni pattern identificato, applica l'intero "
                "processo professionale della Skill — non fermarti alla sola identificazione: "
                "(L1) spiega PERCHÉ questo pattern è psicologicamente/strutturalmente significativo "
                "in questo specifico contesto di mercato; "
                "(L2) verifica TUTTI i criteri operativi dalla Skill: proporzioni corpo/ombre, "
                "relazione con la candela precedente, posizione nel trend — il pattern è valido? "
                "(L3) collega il pattern con altri elementi del contesto: il pattern si forma "
                "su un livello S/R strutturale? C'è allineamento col trend del 4H? "
                "Ogni connessione aumenta il punteggio di affidabilità; "
                "(L4) verifica le condizioni di INVALIDAZIONE dalla Skill: se il pattern cade "
                "in un'anomalia (es. doji in laterale senza contesto, engulfing su volume basso), "
                "riduci esplicitamente l'affidabilità stimata e dichiaralo; "
                "(L5) applica il RAGIONAMENTO DELL'ANALISTA: qual è la storia che questo pattern "
                "racconta sul comportamento dei partecipanti al mercato in questo momento?",

                # ── ANALISI DATI ─────────────────────────────────────────────
                "Analizza i dati OHLCV su tutti i timeframe disponibili, partendo dal più lungo.",

                "Per ogni pattern identificato documenta: nome, libro di provenienza, timeframe, "
                "posizione strutturale (su S/R? fine di swing? in mezzo a range?), "
                "affidabilità stimata (%) secondo la statistica Bulkowski quando disponibile, "
                "indicazione operativa (LONG/SHORT/NEUTRO).",

                "Applica sempre il filtro volumetrico (L4): pattern senza conferma volumetrica = "
                "affidabilità RIDOTTA — calcola il target ma evidenzia il rischio.",

                "Per il target: usa il metodo specifico del libro di riferimento "
                "(es. Bulkowski: proietta l'altezza del pattern; Nison: stop sotto il minimo del pattern).",

                "Rispetta il Sentiment Macro ricevuto: se il macro è BEARISH, dai peso "
                "maggiore ai pattern ribassisti e tratta quelli rialzisti come potenziali "
                "rimbalzi tecnici con affidabilità ridotta.",

                # ── LINGUA ───────────────────────────────────────────────────
                "Rispondi in italiano in modo professionale e strutturato.",
            ],
            skills=skills,
            db=storage,
            num_history_messages=3,
            markdown=True,
        )
        logger.success(
            f"[PATTERN AGENT] Pronto con modello: {llm.id} | "
            f"Skills: {len(Calibrazione.TECHNICAL_SKILLS_DIRS)} libri caricati"
        )

    def analizza(self, data_summary: str, macro_sentiment: str = "Neutrale", skills_guidance: str = "") -> str:
        """
        Esegue l'analisi dei pattern sui dati OHLCV forniti.

        Args:
            data_summary:    Stringa con i dati OHLCV multi-timeframe del mercato.
            macro_sentiment: Il sentiment macro dell'AgnoMacroExpert (usato come contesto).
            skills_guidance: Istruzione su quali pattern/tecniche dai libri privilegiare.

        Returns:
            Stringa Markdown con l'analisi completa dei pattern.
        """
        logger.info("[PATTERN AGENT] Avvio analisi pattern...")

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
Esegui un'analisi completa dei pattern candlestick e delle formazioni grafiche.
Per ogni pattern rilevante applica tutti e 5 i layer della Skill (L1→L5).

ORDINE RISPOSTA OBBLIGATORIO (nessuna eccezione):
1. ## SINTESI OPERATIVA — tutti i campi obbligatori, PRIMA di qualsiasi altra sezione
2. ## 🛠️ STRUMENTI UTILIZZATI — stati ✅ / 🔍 / ⛔ per ogni tecnica della FOCUS SKILLS
3. Analisi dettagliata dei pattern per timeframe (con L1-L5 per ogni pattern rilevante)

Non scrivere nulla prima della ## SINTESI OPERATIVA.
"""
        try:
            response = self.agent.run(prompt)
            if not response.content:
                logger.error("[PATTERN AGENT] Risposta vuota dall'agente.")
                return "❌ ERRORE [Pattern Agent]: risposta vuota dal modello."
            return response.content
        except Exception as e:
            logger.error(f"[PATTERN AGENT] Errore durante l'analisi: {e}")
            raise