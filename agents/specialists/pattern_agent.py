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
        llm = get_model(Calibrazione.MODEL_TECH_SPECIALISTS, temperature=Calibrazione.TEMPERATURE_TECH_SPECIALISTS, agent_name="tech_specialists")

        # --- 2. Storage locale opzionale ---
        storage = None
        if Calibrazione.STORAGE_LOCATION == "local":
            storage = SqliteDb(
                session_table="pattern_agent_session",
                db_file=Calibrazione.DATABASE_PATH
            )

        # --- 3. Caricamento Skills Agno dai 6 libri tecnici ---
        skills = Skills(loaders=[LocalSkills(os.path.abspath(d), validate=False) for d in Calibrazione.TECHNICAL_SKILLS_DIRS])

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
                "Inizia SEMPRE la tua risposta con la sezione '## SINTESI OPERATIVA' (vedi campi obbligatori). "
                "Scrivi la SINTESI OPERATIVA IMMEDIATAMENTE come prima sezione — prima di qualsiasi analisi dettagliata. "
                "Dopo la SINTESI OPERATIVA, scrivi la sezione '## 🛠️ STRUMENTI UTILIZZATI'. "
                "Per OGNI tecnica della FOCUS SKILLS valutata, produci UNA RIGA usando ESATTAMENTE uno di questi 3 stati: "
                "'✅ NomeTecnica — [nota operativa breve]' → tecnica rilevata e applicata ai dati correnti; "
                "'🔍 NomeTecnica — non rilevato' → tecnica applicabile a questo asset/contesto MA assente nei dati correnti (monitorare); "
                "'⛔ NomeTecnica — non applicabile' → tecnica non pertinente a questo asset o condizione di mercato (es. tecnica azionaria su forex, tecnica volume su asset senza volume affidabile). "
                "La distinzione tra 🔍 e ⛔ è critica: 🔍 significa 'potrebbe apparire presto', ⛔ significa 'irrilevante per questo contesto'. "
                "Elenca TUTTE le tecniche principali di ogni libro della FOCUS SKILLS. "
                "Poi prosegui con l'analisi dettagliata.",

                "VINCOLO FONDAMENTALE: se la sezione 'FOCUS SKILLS' è presente nel prompt, "
                "devi analizzare TUTTE le tecniche elencate in essa (sono obbligatorie, non opzionali). "
                "Dopo averle analizzate tutte, puoi integrare con altri pattern e tecniche "
                "presenti nelle Skill caricate (libri di Nison, Bulkowski, Joe Ross) che ritieni utili.",

                "USO COMPLETO DELLE SKILL (5 layer): per ogni pattern identificato, applica l'intero "
                "processo professionale della Skill — non fermarti alla sola identificazione: "
                "(L1) spiega PERCHÉ questo pattern è psicologicamente/strutturalmente significativo "
                "in questo specifico contesto di mercato (non in astratto); "
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

                "PRIMA SEZIONE OBBLIGATORIA — '## SINTESI OPERATIVA' con esattamente questi campi (scrivila PRIMA di STRUMENTI UTILIZZATI e dell'analisi dettagliata): "
                "- **Segnale Dominante**: LONG / SHORT / NEUTRO "
                "- **Pattern Principale**: [NomeTecnica — libro — timeframe] "
                "- **Affidabilità**: Alta / Media / Bassa + percentuale se disponibile "
                "- **Conferma Volume**: SÌ / NO / PARZIALE "
                "- **Stop Loss Strutturale**: [prezzo esatto] (ragione: sotto/sopra cosa?) "
                "- **Target Pattern**: [prezzo] — R:R stimato X:Y "
                "- **Condizione di Invalidazione**: [condizione specifica che annulla il segnale]",

                "Rispondi in italiano in modo professionale e strutturato.",
            ],
            skills=skills,
            db=storage,
            num_history_messages=3,
            markdown=True,
        )
        logger.success(f"[PATTERN AGENT] Pronto con modello: {llm.id} | Skills: {len(Calibrazione.TECHNICAL_SKILLS_DIRS)} libri caricati")

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

        focus_section = f"\nFOCUS SKILLS (tecniche OBBLIGATORIE — analizzale TUTTE, poi integra con altre Skill):\n{skills_guidance}\n" if skills_guidance else ""

        prompt = f"""
DATI MERCATO (OHLCV Multi-Timeframe):
{data_summary}

SENTIMENT MACRO DA RISPETTARE (fornito dall'agente Macro Strategist):
{macro_sentiment}
{focus_section}
Esegui un'analisi completa dei pattern candlestick e delle formazioni grafiche.
Per ogni pattern: applica tutti e 5 i layer della Skill (L1→L5), non solo i criteri di identificazione.

STRUTTURA RISPOSTA OBBLIGATORIA (rispetta quest'ordine esatto):
1. ## SINTESI OPERATIVA — sezione strutturata con i campi obbligatori (PRIMA di tutto)
2. ## 🛠️ STRUMENTI UTILIZZATI — 3 stati: ✅ rilevato / 🔍 non rilevato (monitorare) / ⛔ non applicabile
3. Analisi pattern per timeframe (con L1-L5 per ogni pattern rilevante)
"""
        try:
            response = self.agent.run(prompt)
            return response.content if response.content else "Errore: risposta vuota dall'agente."
        except Exception as e:
            logger.error(f"[PATTERN AGENT] Errore durante l'analisi: {e}")
            return f"❌ Errore nell'analisi dei pattern: {e}"
