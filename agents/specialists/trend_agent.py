"""
agents/specialists/trend_agent.py — Specialista in Trend e Momentum.

Agente Agno V2 che analizza trend direzionale e momentum usando le Skill
estratte dai libri di John Murphy, Brian Shannon e Larry Williams,
caricate direttamente dalla cartella skills_library/trend_analyst/.
"""

import os
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.skills import Skills, LocalSkills
from loguru import logger
import Calibrazione
from agents.model_factory import get_model


class TrendAgent:
    """
    Specialista in Trend e Momentum (Medie Mobili, RSI, MACD, Multi-Timeframe).

    Costruito secondo il framework Agno ufficiale con:
    - skills=[TREND_SKILL_DIR]: Accesso alle skill estratte da Murphy, Shannon, Williams
    - Storage SQLite locale per la memoria della sessione
    - Metodo analizza() sincrono, coerente con gli altri agenti del team
    """

    def __init__(self):
        logger.info("[TREND AGENT] Inizializzazione...")

        # --- 1. Modello AI ---
        llm = get_model(Calibrazione.MODEL_TECH_SPECIALISTS, temperature=Calibrazione.TEMPERATURE_TECH_SPECIALISTS, agent_name="tech_specialists")

        # --- 2. Storage locale opzionale ---
        storage = None
        if Calibrazione.STORAGE_LOCATION == "local":
            storage = SqliteDb(
                session_table="trend_agent_session",
                db_file=Calibrazione.DATABASE_PATH
            )

        # --- 3. Caricamento Skills Agno dai 6 libri tecnici ---
        skills = Skills(loaders=[LocalSkills(os.path.abspath(d), validate=False) for d in Calibrazione.TECHNICAL_SKILLS_DIRS])

        # --- 4. Creazione Agente Agno ---
        self.agent = Agent(
            name="Trend Analyst",
            model=llm,
            description=(
                "Sei un esperto di Trend Analysis e Momentum applicati ai mercati finanziari. "
                "La tua competenza integra l'analisi classica del trend di John Murphy "
                "(medie mobili, MACD, RSI, trendline), l'analisi multi-timeframe di Brian Shannon "
                "(allineamento top-down da weekly a 1H) e l'analisi del momentum di Larry Williams "
                "(%R, divergenze, overbought/oversold). "
                "Il tuo compito è determinare la direzione del trend su ogni timeframe, "
                "valutare il momentum corrente, identificare eventuali divergenze e "
                "fornire stop loss logici basati sulla struttura del mercato. "
                "Non esegui analisi di pattern grafici (ci pensa il Pattern Analyst). "
                "Non entri nei dettagli di supporti e resistenze statici (ci pensa il SR Analyst). "
                "Il tuo focus è esclusivamente la DIREZIONE e la FORZA del trend."
            ),
            instructions=[
                "Inizia SEMPRE la tua risposta con la sezione '## SINTESI OPERATIVA' (vedi campi obbligatori). "
                "Scrivi la SINTESI OPERATIVA IMMEDIATAMENTE come prima sezione — prima di qualsiasi analisi dettagliata. "
                "Dopo la SINTESI OPERATIVA, scrivi la sezione '## 🛠️ STRUMENTI UTILIZZATI'. "
                "Per OGNI tecnica della FOCUS SKILLS valutata, produci UNA RIGA usando ESATTAMENTE uno di questi 3 stati: "
                "'✅ NomeTecnica — [nota operativa breve]' → tecnica rilevata e applicata ai dati correnti; "
                "'🔍 NomeTecnica — non rilevato' → tecnica applicabile a questo asset/contesto MA assente nei dati correnti (monitorare); "
                "'⛔ NomeTecnica — non applicabile' → tecnica non pertinente a questo asset o condizione di mercato (es. indicatore di volume su asset senza dati volume affidabili, tecnica azionaria su crypto, ecc.). "
                "La distinzione tra 🔍 e ⛔ è critica: 🔍 significa 'potrebbe apparire presto e va monitorato', ⛔ significa 'irrilevante per questo contesto, non influenza il verdetto'. "
                "Elenca TUTTE le tecniche principali di ogni libro della FOCUS SKILLS. "
                "Poi prosegui con l'analisi dettagliata.",

                "VINCOLO FONDAMENTALE: se la sezione 'FOCUS SKILLS' è presente nel prompt, "
                "devi analizzare TUTTE le tecniche elencate in essa (sono obbligatorie, non opzionali). "
                "Dopo averle analizzate tutte, puoi integrare con altri indicatori e metodi "
                "presenti nelle Skill caricate (Murphy, Shannon, Williams) che ritieni utili.",

                "USO COMPLETO DELLE SKILL (5 layer): per ogni tecnica applicata, non limitarti ai "
                "criteri di identificazione (L2). Applica l'intero processo professionale: "
                "(L1) spiega PERCHÉ la tecnica è significativa in questo specifico contesto di mercato; "
                "(L2) verifica i criteri operativi numerici dalla Skill; "
                "(L3) esplora le CONNESSIONI con le altre tecniche presenti nel contesto — "
                "come questa tecnica si collega a quanto visto su altri timeframe o da altri indicatori? "
                "(L4) verifica se si applicano anomalie o casi limite che riducono l'affidabilità del segnale — "
                "se sì, dichiaralo esplicitamente; "
                "(L5) applica il RAGIONAMENTO DELL'ANALISTA dalla Skill: qual è la narrativa di mercato "
                "che questi dati raccontano? Cosa implicano per il prossimo movimento?",

                "VINCOLO ANTI-RIDONDANZA: i valori numerici RSI, MACD, medie mobili, EMA, SMA "
                "sono già precalcolati nel contesto che ricevi. NON rielencarli come se li avessi "
                "calcolati tu — il tuo valore aggiunto è l'INTERPRETAZIONE PROFESSIONALE: "
                "cosa dicono questi numeri INSIEME? Come si combinano in una narrativa coerente? "
                "Quale fase di mercato descrivono? Dove il momentum accelera o esaurisce?",

                "Analizza il trend su 3 livelli: Primario (1D/1W), Secondario (4H), Terziario (1H). "
                "Documenta esplicitamente la struttura: stai vedendo HH+HL (uptrend), "
                "LH+LL (downtrend), o una struttura mista (laterale/inversione)?",

                "Verifica il momentum con le tecniche selezionate: esistono divergenze da segnalare? "
                "Applica la lettura multi-timeframe di Shannon: il momentum sul 1H è in fase con il 4H? "
                "Il 4H è in fase con il 1D? L'allineamento o la divergenza tra TF è il tuo segnale più forte.",

                "ATTENZIONE ALLE ANOMALIE (L4): se un segnale si presenta in condizioni storicamente "
                "fallaci (es. divergenza RSI in trend forte prolungato, crossover MA in laterale), "
                "riduci il peso del segnale e dichiaralo esplicitamente.",

                "Rispetta il Sentiment Macro ricevuto: usa il bias macro come filtro direzionale.",
                "Fornisci stop loss logici basati sulla struttura di mercato (ultimo swing HH/HL o LH/LL).",

                "PRIMA SEZIONE OBBLIGATORIA — '## SINTESI OPERATIVA' con esattamente questi campi (scrivila PRIMA di STRUMENTI UTILIZZATI e dell'analisi dettagliata): "
                "- **Trend Primario (1D)**: BULLISH / BEARISH / LATERALE "
                "- **Trend Secondario (4H)**: BULLISH / BEARISH / LATERALE "
                "- **Trend Esecutivo (1H)**: BULLISH / BEARISH / LATERALE "
                "- **Allineamento MTF**: ALLINEATO / PARZIALE / DIVERGENTE "
                "- **Momentum**: FORTE / MODERATO / DEBOLE — con eventuale divergenza nominata "
                "- **Stop Loss Strutturale**: [prezzo esatto] (ragione strutturale) "
                "- **Narrativa di Mercato**: 2-3 frasi che spiegano PERCHÉ il mercato si comporta così "
                "- **Confidence**: Alto / Medio / Basso",

                "Rispondi in italiano in modo professionale e strutturato.",
            ],
            skills=skills,
            db=storage,
            num_history_messages=3,
            markdown=True,
        )
        logger.success(f"[TREND AGENT] Pronto con modello: {llm.id} | Skills: {len(Calibrazione.TECHNICAL_SKILLS_DIRS)} libri caricati")

    def analizza(self, data_summary: str, macro_sentiment: str = "Neutrale", skills_guidance: str = "") -> str:
        """
        Esegue l'analisi del trend e del momentum sui dati OHLCV forniti.

        Args:
            data_summary:    Stringa con i dati OHLCV multi-timeframe del mercato.
            macro_sentiment: Il sentiment macro dell'AgnoMacroExpert.
            skills_guidance: Istruzione su quali indicatori/tecniche dai libri privilegiare.

        Returns:
            Stringa Markdown con l'analisi completa del trend e momentum.
        """
        logger.info("[TREND AGENT] Avvio analisi trend e momentum...")

        focus_section = f"\nFOCUS SKILLS (tecniche OBBLIGATORIE — analizzale TUTTE, poi integra con altre Skill):\n{skills_guidance}\n" if skills_guidance else ""

        prompt = f"""
DATI MERCATO (OHLCV Multi-Timeframe):
{data_summary}

SENTIMENT MACRO DA RISPETTARE (fornito dall'agente Macro Strategist):
{macro_sentiment}
{focus_section}
Esegui un'analisi completa del trend e del momentum.
Segui la procedura top-down (Weekly → Daily → 4H → 1H) come da Skill.

STRUTTURA RISPOSTA OBBLIGATORIA (rispetta quest'ordine esatto):
1. ## SINTESI OPERATIVA — sezione strutturata con i campi obbligatori (PRIMA di tutto)
2. ## 🛠️ STRUMENTI UTILIZZATI — 3 stati: ✅ rilevato / 🔍 non rilevato (monitorare) / ⛔ non applicabile
3. Analisi dettagliata per timeframe (applica i 5 layer della Skill per ogni tecnica rilevante)
"""
        try:
            response = self.agent.run(prompt)
            return response.content if response.content else "Errore: risposta vuota dall'agente."
        except Exception as e:
            logger.error(f"[TREND AGENT] Errore durante l'analisi: {e}")
            return f"❌ Errore nell'analisi del trend: {e}"
