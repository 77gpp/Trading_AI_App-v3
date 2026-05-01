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
        llm = get_model(
            Calibrazione.MODEL_TECH_SPECIALISTS,
            temperature=Calibrazione.TEMPERATURE_TECH_SPECIALISTS,
            agent_name="tech_specialists"
        )

        # --- 2. Storage locale opzionale ---
        storage = None
        if Calibrazione.STORAGE_LOCATION == "local":
            storage = SqliteDb(
                session_table="volume_agent_session",
                db_file=Calibrazione.DATABASE_PATH
            )

        # --- 3. Caricamento Skills Agno dai 6 libri tecnici ---
        skills = Skills(loaders=[
            LocalSkills(os.path.abspath(d), validate=False)
            for d in Calibrazione.TECHNICAL_SKILLS_DIRS
        ])

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
                "Principio fondamentale: il volume misura lo SFORZO, il prezzo misura il RISULTATO. "
                "Se Sforzo ≠ Risultato, il mercato sta mentendo — dichiaralo sempre. "
                "Il RISCHIO ELEVATO è riservato esclusivamente a divergenze volumetriche "
                "esplicite e verificabili sui dati OHLCV+Volume forniti. "
                "Non dichiarare RISCHIO ELEVATO per assenza di certezza o per prudenza generica: "
                "in quel caso il verdetto corretto è INCERTO."
            ),
            instructions=[
                # ── ORDINE RISPOSTA ─────────────────────────────────────────
                "STRUTTURA RISPOSTA OBBLIGATORIA — rispetta quest'ordine esatto senza eccezioni: "
                "1. ## SINTESI OPERATIVA (PRIMA di tutto il resto — vedi campi obbligatori sotto) "
                "2. ## 🛠️ STRUMENTI UTILIZZATI "
                "3. Analisi VSA bar-by-bar (ultime 5-20 barre per timeframe) "
                "4. Fase Wyckoff e narrativa istituzionale. "
                "Non scrivere nulla prima della ## SINTESI OPERATIVA.",

                # ── SINTESI OPERATIVA ────────────────────────────────────────
                "## SINTESI OPERATIVA — CAMPI OBBLIGATORI (scrivi questa sezione per prima, "
                "con esattamente questi campi nell'ordine indicato, nessuno omesso): "
                "- **Bias**: Bullish / Bearish / Neutrale "
                "- **Struttura**: HH+HL / LH+LL / Laterale / Transizione "
                "- **Fase Wyckoff**: Accumulazione / Markup / Distribuzione / Markdown / Transizione "
                "- **Segnale VSA Dominante**: [NomeTecnica — libro — timeframe] "
                "- **Segnale Chiave**: [tecnica principale — libro — timeframe] "
                "- **Livello Entry**: [prezzo numerico oppure 'non disponibile'] "
                "- **Livello Stop Loss**: [prezzo numerico oppure 'non disponibile'] "
                "- **Livello Target 1**: [prezzo numerico oppure 'non disponibile'] "
                "- **Livello Target 2**: [prezzo numerico oppure 'non disponibile'] "
                "- **Qualità Segnale**: Alta / Media / Bassa "
                "- **Stato Volume**: Confermato / Incerto / Debole / Rischio Elevato "
                "- **Validazione Specialisti**: CONFERMA / INCERTO / DIVERGENZA "
                "- **Livello di Rischio**: NORMALE / INCERTO / ELEVATO "
                "- **Motivazione** (OBBLIGATORIA se INCERTO o ELEVATO): spiegazione precisa in 2-3 frasi "
                "- **Condizione per Rivalutazione** (OBBLIGATORIA se ELEVATO): "
                "[condizione volumetrica specifica che cambierebbe il giudizio — "
                "es. 'chiusura 4H sopra X con volume > media × 1.5'] "
                "- **Motivo Finale**: [2 frasi massimo, concrete e operative] "
                "NON omettere nessun campo. NON cambiare il titolo della sezione. "
                "NON scrivere altro prima di questa sezione.",

                # ── STRUMENTI UTILIZZATI ─────────────────────────────────────
                "## 🛠️ STRUMENTI UTILIZZATI — dopo la SINTESI OPERATIVA, "
                "per OGNI tecnica della FOCUS SKILLS valutata produci UNA RIGA con ESATTAMENTE uno di questi 3 stati: "
                "'✅ NomeTecnica — [nota operativa breve]' → segnale VSA/Wyckoff identificato e applicato; "
                "'🔍 NomeTecnica — non rilevato' → tecnica applicabile MA il segnale specifico non è presente nei dati correnti (da monitorare); "
                "'⛔ NomeTecnica — non applicabile' → tecnica non pertinente a questo asset/contesto. "
                "La distinzione è fondamentale: 🔍 contribuisce al contesto 'potenziale', ⛔ viene escluso dall'analisi. "
                "Elenca TUTTE le tecniche principali di ogni libro della FOCUS SKILLS.",

                # ── FOCUS SKILLS ─────────────────────────────────────────────
                "VINCOLO FONDAMENTALE: se la sezione 'FOCUS SKILLS' è presente nel prompt, "
                "devi analizzare TUTTE le tecniche elencate in essa (sono obbligatorie, non opzionali). "
                "Dopo averle analizzate tutte, puoi integrare con altri segnali VSA/Wyckoff "
                "presenti nelle Skill caricate (Tom Williams, Wyckoff, Larry Williams) che ritieni utili.",

                # ── USO SKILL (5 LAYER) ──────────────────────────────────────
                "USO COMPLETO DELLE SKILL (5 layer): per ogni segnale VSA/Wyckoff identificato: "
                "(L1) spiega la logica istituzionale dietro il segnale — chi sta comprando/vendendo e perché? "
                "(L2) verifica i criteri esatti dalla Skill: percentuale di variazione volume, "
                "posizione della chiusura nel range, relazione spread/volume; "
                "(L3) collega il segnale VSA con la fase Wyckoff e con i segnali degli altri specialisti — "
                "un segnale VSA che coincide con un pattern candlestick E con un livello S/R chiave "
                "ha peso triplo — dichiaralo esplicitamente; "
                "(L4) segnala anomalie che riducono l'affidabilità: orari di bassa liquidità, "
                "asset con volume strutturalmente basso, divergenze ambigue in laterale prolungato; "
                "(L5) applica il ragionamento dell'analista: il volume sta raccontando accumulazione furtiva "
                "o distribuzione travestita da forza? Cosa ci dicono le ultime 5-10 barre volumetriche "
                "sulla vera intenzione dei partecipanti istituzionali?",

                # ── ANALISI BAR-BY-BAR ───────────────────────────────────────
                "ANALISI BAR-BY-BAR: non limitarti all'OBV summary già nel contesto — "
                "analizza le ultime 5-20 barre OHLCV+Volume raw per identificare segnali VSA specifici. "
                "Otto tipi di segnale da cercare: "
                "Barra di Domanda (rialzista + ampiezza ampia + volume alto + chiusura vicina al max), "
                "Barra di Offerta (ribassista + ampiezza ampia + volume alto + chiusura vicina al min), "
                "No Demand (rialzista + ampiezza stretta + volume basso), "
                "No Supply (ribassista + ampiezza stretta + volume basso), "
                "Stopping Volume (volume ultra + chiusura opposta al trend), "
                "Assorbimento (volume ultra + ampiezza stretta = sforzo senza risultato), "
                "Change of Character (ampiezza max 20 barre + volume quasi max + direzione opposta al trend), "
                "Divergenza Sforzo vs Risultato (volume alto ma movimento di prezzo ridotto). "
                "Questi segnali non sono precalcolati — sono il tuo contributo unico.",

                # ── SISTEMA VERDETTO A 3 LIVELLI ─────────────────────────────
                "SISTEMA DI VERDETTO A 3 LIVELLI — scegli UNO solo in base ai dati oggettivi: "
                "• NORMALE: volume conferma chiaramente i segnali degli altri specialisti — "
                "Sforzo e Risultato coerenti, nessuna divergenza rilevata sui dati OHLCV+Volume. "
                "• INCERTO: dati volumetrici insufficienti, ambigui o segnali misti — "
                "non è possibile confermare né smentire con certezza. "
                "Usa INCERTO quando: dati scarsi, volume neutro senza segnali VSA chiari, "
                "fase Wyckoff non identificabile, oppure segnali VSA contraddittori tra timeframe. "
                "INCERTO non blocca il trade — riduce solo la confidence del verdetto finale. "
                "• ELEVATO: divergenza volumetrica confermata e verificabile sui dati — "
                "Sforzo e Risultato esplicitamente incoerenti, segnali VSA di distribuzione o "
                "assorbimento mentre il prezzo simula forza/debolezza. "
                "REGOLA: ELEVATO è riservato a divergenze concrete sui dati, non a incertezza generica. "
                "Se sei incerto sulla diagnosi, il verdetto è INCERTO, non ELEVATO. "
                "ELEVATO trigghera NO TRADE automatico nel sistema — usalo con rigore.",

                # ── REGOLE AGGIUNTIVE ────────────────────────────────────────
                "Applica la legge di Sforzo vs Risultato: candele ad alto volume "
                "producono movimenti ampi nella stessa direzione? Se no → ALERT assorbimento.",

                "Identifica la FASE WYCKOFF attiva: Accumulazione / Markup / Distribuzione / Markdown.",

                "Verifica il Volume Profile se i dati lo permettono: POC, VAH, VAL, zone HVN/LVN.",

                "Rispetta il Sentiment Macro come contesto aggiuntivo.",

                # ── LINGUA ───────────────────────────────────────────────────
                "Rispondi in italiano in modo professionale e strutturato.",
            ],
            skills=skills,
            db=storage,
            num_history_messages=3,
            markdown=True,
        )
        logger.success(
            f"[VOLUME AGENT] Pronto con modello: {llm.id} | "
            f"Skills: {len(Calibrazione.TECHNICAL_SKILLS_DIRS)} libri caricati"
        )

    def analizza(self, data_summary: str, macro_sentiment: str = "Neutrale",
                 skills_guidance: str = "", other_analyses: dict = None) -> str:
        """
        Esegue l'analisi volumetrica VSA/Wyckoff sui dati OHLCV forniti.

        Args:
            data_summary:    Stringa con i dati OHLCV multi-timeframe del mercato.
            macro_sentiment: Il sentiment macro dell'AgnoMacroExpert.
            skills_guidance: Istruzione su quali segnali degli altri specialisti validare.
            other_analyses:  Dict {nome_agente: testo_analisi} degli altri 3 specialisti.
                             Permette al Volume Agent di validare i segnali effettivi.

        Returns:
            Stringa Markdown con l'analisi volumetrica completa e il verdetto finale.
        """
        logger.info("[VOLUME AGENT] Avvio analisi volumetrica VSA/Wyckoff...")

        focus_section = (
            f"\nFOCUS SKILLS (tecniche OBBLIGATORIE — analizzale TUTTE, poi integra con altre Skill):\n"
            f"{skills_guidance}\n"
        ) if skills_guidance else ""

        other_section = ""
        if other_analyses:
            _chars_limit = Calibrazione.VOLUME_AGENT_CHARS_PER_SPECIALIST
            parts = []
            for nome, testo in other_analyses.items():
                if testo and testo not in ("Analisi Disattivata", "N/D"):
                    if _chars_limit is not None and len(testo) > _chars_limit:
                        estratto = testo[:_chars_limit] + "…"
                        logger.debug(
                            f"[VOLUME AGENT] {nome}: testo troncato a {_chars_limit} chars "
                            f"(originale: {len(testo)})"
                        )
                    else:
                        estratto = testo
                    parts.append(f"=== {nome} ===\n{estratto}")
            if parts:
                other_section = (
                    "\n\nANALISI DEGLI ALTRI SPECIALISTI (da validare con i volumi):\n"
                    + "\n\n".join(parts)
                    + "\n\nIL TUO COMPITO: per ciascun segnale sopra, verifica se il volume CONFERMA o DIVERGE. "
                    "Dichiara RISCHIO ELEVATO SOLO se hai evidenza volumetrica esplicita di divergenza "
                    "sui dati OHLCV+Volume. Se i dati non sono sufficienti per confermare né smentire, "
                    "il verdetto è INCERTO — non ELEVATO.\n"
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

RICORDA: ELEVATO è riservato a divergenze concrete e verificabili sui dati.
L'incertezza va dichiarata come INCERTO — non come ELEVATO.

ORDINE RISPOSTA OBBLIGATORIO (nessuna eccezione):
1. ## SINTESI OPERATIVA — tutti i campi obbligatori, PRIMA di qualsiasi altra sezione
2. ## 🛠️ STRUMENTI UTILIZZATI — stati ✅ / 🔍 / ⛔ per ogni tecnica della FOCUS SKILLS
3. Analisi VSA bar-by-bar (ultime 5-20 barre per timeframe)
4. Fase Wyckoff e narrativa istituzionale

Non scrivere nulla prima della ## SINTESI OPERATIVA.
"""
        try:
            response = self.agent.run(prompt)
            if not response.content:
                logger.error("[VOLUME AGENT] Risposta vuota dall'agente.")
                return "❌ ERRORE [Volume Agent]: risposta vuota dal modello."
            return response.content
        except Exception as e:
            logger.error(f"[VOLUME AGENT] Errore durante l'analisi: {e}")
            raise