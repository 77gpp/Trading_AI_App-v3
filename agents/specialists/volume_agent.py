"""
agents/specialists/volume_agent.py — Specialista in Analisi Volumetrica VSA/Wyckoff.

Agente Agno V2 che analizza i volumi usando le Skill estratte dai libri di
Tom Williams (VSA), Richard Wyckoff e Larry Williams, caricate direttamente
dalla cartella skills_library/volume_analyst/.

RUOLO CRITICO: È il FILTRO FINALE del team. Se i volumi non confermano
il segnale tecnico degli altri agenti, il verdetto è RISCHIO ELEVATO.
"""

import os
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.skills import Skills, LocalSkills
from loguru import logger
import Calibrazione
from agents.model_factory import get_model


class VolumeAgent:
    """
    Specialista in Analisi dei Volumi, VSA (Volume Spread Analysis) e Wyckoff.

    Costruito secondo il framework Agno ufficiale con:
    - skills=[VOLUME_SKILL_DIR]: Accesso alle skill estratte da Williams, Wyckoff, Ross
    - Storage SQLite locale per la memoria della sessione
    - Metodo analizza() sincrono, coerente con gli altri agenti del team

    NOTA: Il Volume Analyst è il filtro finale del Technical Trading Desk.
    """

    def __init__(self):
        logger.info("[VOLUME AGENT] Inizializzazione...")

        # --- 1. Modello AI ---
        llm = get_model(Calibrazione.MODEL_TECH_SPECIALISTS, temperature=Calibrazione.TEMPERATURE_TECH_SPECIALISTS, agent_name="tech_specialists")

        # --- 2. Storage locale opzionale ---
        storage = None
        if Calibrazione.STORAGE_LOCATION == "local":
            storage = SqliteDb(
                session_table="volume_agent_session",
                db_file=Calibrazione.DATABASE_PATH
            )

        # --- 3. Caricamento Skills Agno dai 6 libri tecnici ---
        skills = Skills(loaders=[LocalSkills(os.path.abspath(d), validate=False) for d in Calibrazione.TECHNICAL_SKILLS_DIRS])

        # --- 4. Creazione Agente Agno ---
        self.agent = Agent(
            name="Volume Analyst",
            model=llm,
            description=(
                "Sei un Maestro di Volume Spread Analysis (VSA) e dell'analisi di Wyckoff. "
                "La tua competenza si basa su Tom Williams (Master the Markets — VSA), "
                "Richard Wyckoff (le 4 fasi del ciclo di mercato: Accumulazione, Markup, "
                "Distribuzione, Markdown) e Larry Williams (analisi volumetrica operativa). "
                "Il tuo ruolo nel team è il più critico: sei il FILTRO FINALE. "
                "Il tuo compito è verificare se il volume CONFERMA o DIVERGE dai segnali "
                "tecnici degli altri specialisti (pattern, trend, S/R). "
                "Principio fondamentale: Il volume misura lo SFORZO. Il prezzo misura il RISULTATO. "
                "Se Sforzo ≠ Risultato, il mercato sta mentendo. Dichiaralo sempre. "
                "Se i volumi non confermano il segnale, devi dichiarare RISCHIO ELEVATO "
                "indipendentemente da cosa dicono gli altri agenti."
            ),
            instructions=[
                "Inizia SEMPRE la tua risposta con la sezione '## SINTESI OPERATIVA' (vedi campi obbligatori). "
                "Scrivi la SINTESI OPERATIVA IMMEDIATAMENTE come prima sezione — prima di qualsiasi analisi dettagliata. "
                "Dopo la SINTESI OPERATIVA, scrivi la sezione '## 🛠️ STRUMENTI UTILIZZATI'. "
                "Per OGNI tecnica della FOCUS SKILLS valutata, produci UNA RIGA usando ESATTAMENTE uno di questi 3 stati: "
                "'✅ NomeTecnica — [nota operativa breve]' → segnale VSA/Wyckoff identificato e applicato; "
                "'🔍 NomeTecnica — non rilevato' → tecnica applicabile MA il segnale specifico non è presente nei dati correnti (da monitorare); "
                "'⛔ NomeTecnica — non applicabile' → tecnica non pertinente a questo asset/contesto (es. Volume Profile su asset senza tick data, Wyckoff Spring su asset in trend fortissimo senza laterale, ecc.). "
                "La distinzione è fondamentale: 🔍 contribuisce al contesto 'potenziale', ⛔ viene escluso dall'analisi. "
                "Elenca TUTTE le tecniche principali di ogni libro della FOCUS SKILLS. "
                "Poi prosegui con l'analisi dettagliata.",

                "VINCOLO FONDAMENTALE: se la sezione 'FOCUS SKILLS' è presente nel prompt, "
                "devi analizzare TUTTE le tecniche elencate in essa (sono obbligatorie, non opzionali). "
                "Dopo averle analizzate tutte, puoi integrare con altri segnali VSA/Wyckoff "
                "presenti nelle Skill caricate (Tom Williams, Wyckoff, Larry Williams) che ritieni utili.",

                "USO COMPLETO DELLE SKILL (5 layer): per ogni segnale VSA/Wyckoff identificato: "
                "(L1) spiega la logica istituzionale dietro il segnale — chi sta comprando/vendendo e perché? "
                "(L2) verifica i criteri esatti dalla Skill: percentuale di variazione volume, "
                "posizione della chiusura nel range, relazione spread/volume; "
                "(L3) collega il segnale VSA con la fase Wyckoff e con i segnali degli altri specialisti — "
                "un segnale VSA che coincide con un pattern candlestick E con un livello S/R chiave "
                "ha peso triplo; dichiaralo esplicitamente; "
                "(L4) segnala anomalie che riducono l'affidabilità: orari di bassa liquidità, "
                "asset con volume strutturalmente basso, divergenze ambigue in laterale prolungato; "
                "(L5) applica il ragionamento dell'analista: il volume sta raccontando accumulazione furtiva "
                "o distribuzione travestita da forza? Cosa ci dicono le ultime 5-10 barre volumetriche "
                "sulla vera intenzione dei partecipanti istituzionali?",

                "ANALISI BAR-BY-BAR: non limitarti all'OBV summary già nel contesto — "
                "analizza le ultime 5-20 barre OHLCV+Volume raw per identificare segnali VSA specifici "
                "(Up-thrust, No Demand, Stopping Volume, Test, No Supply, Climactic Action). "
                "Questi segnali sono il tuo contributo unico — non sono precalcolati.",

                "Applica la legge di Sforzo vs Risultato: candele ad alto volume "
                "producono movimenti ampi nella stessa direzione? Se no → ALERT assorbimento.",
                "Identifica la FASE WYCKOFF attiva: Accumulazione / Markup / Distribuzione / Markdown.",
                "Verifica il Volume Profile se i dati lo permettono: POC, VAH, VAL, zone HVN/LVN.",

                "SISTEMA DI VERDETTO A 3 LIVELLI — scegli UNO solo: "
                "• NORMALE: volume conferma chiaramente i segnali degli altri specialisti — "
                "Sforzo e Risultato coerenti, nessuna divergenza rilevata; "
                "• INCERTO: dati volumetrici insufficienti, ambigui o in conflitto interno — "
                "non è possibile confermare né smentire con certezza (es. dati scarsi, "
                "volume neutro senza segnali VSA chiari, fase Wyckoff non identificabile); "
                "• ELEVATO: divergenza volumetrica confermata — Sforzo e Risultato incoerenti, "
                "segnali VSA di distribuzione o assorbimento mentre il prezzo simula forza/debolezza. "
                "REGOLA ASSOLUTA: ELEVATO è inappellabile e non dipende dal voto degli altri specialisti.",

                "PRIMA SEZIONE OBBLIGATORIA — '## SINTESI OPERATIVA' con esattamente questi campi (scrivila PRIMA di STRUMENTI UTILIZZATI e dell'analisi dettagliata): "
                "- **Fase Wyckoff**: Accumulazione / Markup / Distribuzione / Markdown / Transizione "
                "- **Segnale VSA Dominante**: [NomeTecnica — libro — timeframe] "
                "- **Validazione Specialisti**: CONFERMA / INCERTO / DIVERGENZA "
                "- **Livello di Rischio**: NORMALE / INCERTO / ELEVATO "
                "- **Motivazione** (se INCERTO o ELEVATO): spiegazione precisa in 2-3 frasi "
                "- **Condizione per Rivalutazione** (se ELEVATO): [condizione volumetrica specifica "
                "che cambierebbe il giudizio — es. 'chiusura 4H sopra X con volume > media × 1.5']",

                "Rispetta il Sentiment Macro come contesto aggiuntivo.",
                "Rispondi in italiano in modo professionale e strutturato.",
            ],
            skills=skills,
            db=storage,
            num_history_messages=3,
            markdown=True,
        )
        logger.success(f"[VOLUME AGENT] Pronto con modello: {llm.id} | Skills: {len(Calibrazione.TECHNICAL_SKILLS_DIRS)} libri caricati")

    def analizza(self, data_summary: str, macro_sentiment: str = "Neutrale",
                 skills_guidance: str = "", other_analyses: dict = None) -> str:
        """
        Esegue l'analisi volumetrica VSA/Wyckoff sui dati OHLCV forniti.

        Args:
            data_summary:    Stringa con i dati OHLCV multi-timeframe del mercato.
            macro_sentiment: Il sentiment macro dell'AgnoMacroExpert.
            skills_guidance: Istruzione su quali segnali degli altri specialisti validare.
            other_analyses:  Dict {nome_agente: testo_analisi} degli altri 3 specialisti.
                             Permette al Volume Agent di validare i segnali effettivi, non solo i nomi.

        Returns:
            Stringa Markdown con l'analisi volumetrica completa e il verdetto finale.
        """
        logger.info("[VOLUME AGENT] Avvio analisi volumetrica VSA/Wyckoff...")

        focus_section = f"\nFOCUS SKILLS (tecniche OBBLIGATORIE — analizzale TUTTE, poi integra con altre Skill):\n{skills_guidance}\n" if skills_guidance else ""

        # Sezione con i segnali effettivi degli altri specialisti da validare
        other_section = ""
        if other_analyses:
            # Limite caratteri per specialista — configurabile in Calibrazione.py.
            # None = nessun limite (consigliato con provider locali come Gemma4).
            # Valore numerico = tronca a N chars per non saturare il context window
            # (es. 8000 chars ≈ 1500-2000 token, sicuro con Groq qwen3-32b 32k window).
            _chars_limit = Calibrazione.VOLUME_AGENT_CHARS_PER_SPECIALIST
            parts = []
            for nome, testo in other_analyses.items():
                if testo and testo not in ("Analisi Disattivata", "N/D"):
                    if _chars_limit is not None and len(testo) > _chars_limit:
                        estratto = testo[:_chars_limit] + "…"
                        logger.debug(f"[VOLUME AGENT] {nome}: testo troncato a {_chars_limit} chars (originale: {len(testo)})")
                    else:
                        estratto = testo
                    parts.append(f"=== {nome} ===\n{estratto}")
            if parts:
                other_section = (
                    "\n\nANALISI DEGLI ALTRI SPECIALISTI (da validare con i volumi):\n"
                    + "\n\n".join(parts)
                    + "\n\nIL TUO COMPITO: per ciascun segnale sopra, verifica se il volume CONFERMA o DIVERGE. "
                    "Se i volumi non confermano → dichiarare RISCHIO ELEVATO per quel segnale.\n"
                )

        prompt = f"""
DATI MERCATO (OHLCV Multi-Timeframe — incluso Volume):
{data_summary}

SENTIMENT MACRO DA RISPETTARE (fornito dall'agente Macro Strategist):
{macro_sentiment}
{focus_section}{other_section}
Esegui un'analisi volumetrica profonda usando VSA e il framework di Wyckoff.
Segui la checklist in 6 passi della tua Skill: Volume assoluto → Sforzo vs Risultato →
Chiusura nel range → Segnali VSA bar-by-bar → Fase Wyckoff → Volume Profile.
Applica i 5 layer della Skill (L1-L5) per ogni segnale VSA rilevante.

STRUTTURA RISPOSTA OBBLIGATORIA (rispetta quest'ordine esatto):
1. ## SINTESI OPERATIVA — sezione strutturata con i campi obbligatori (PRIMA di tutto, incluso NORMALE/INCERTO/ELEVATO)
2. ## 🛠️ STRUMENTI UTILIZZATI — 3 stati: ✅ rilevato / 🔍 non rilevato (monitorare) / ⛔ non applicabile
3. Analisi VSA bar-by-bar (ultime 5-20 barre per timeframe)
4. Fase Wyckoff e narrativa istituzionale
"""
        try:
            response = self.agent.run(prompt)
            return response.content if response.content else "Errore: risposta vuota dall'agente."
        except Exception as e:
            logger.error(f"[VOLUME AGENT] Errore durante l'analisi: {e}")
            return f"❌ Errore nell'analisi volumetrica: {e}"
