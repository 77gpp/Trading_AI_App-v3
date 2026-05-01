"""
agents/agno_technical_team.py — Team Tecnico V5.

Wrapper che espone i 4 specialisti standalone (PatternAgent, TrendAgent,
SRAgent, VolumeAgent) in modalità Team Agno per compatibilità con il
codice che chiama analizza_specialista() o analizza_asset().
I 4 agenti sono istanziati dai loro file dedicati — nessuna ridefinizione inline.
"""

import re
from agno.team import Team
from agno.db.sqlite import SqliteDb
from loguru import logger
import Calibrazione

from agents.specialists.pattern_agent import PatternAgent
from agents.specialists.trend_agent import TrendAgent
from agents.specialists.sr_agent import SRAgent
from agents.specialists.volume_agent import VolumeAgent
from agents.model_factory import get_model


def _rimuovi_intro_inglese(testo: str, marker: str | None = None) -> str:
    """
    Rimuove i blocchi di ragionamento in inglese che i modelli Qwen/Groq
    producono prima dell'analisi vera (es. 'Okay, let's start...').

    Strategia in cascata:
    1. Se `marker` è specificato, cerca quella stringa esatta e taglia tutto prima.
    2. Altrimenti cerca il primo heading/emoji italiano noto (🛠️, ##, **Bias).
    3. Fallback: rimuove righe iniziali che contengono parole-spia inglesi.
    """
    if not testo:
        return testo

    righe = testo.splitlines()

    # --- Passo 1: marker esplicito ---
    if marker:
        for i, riga in enumerate(righe):
            if marker in riga:
                return "\n".join(righe[i:]).strip()

    # --- Passo 2: prima riga con marcatore italiano noto ---
    MARCATORI = re.compile(
        r"^(🛠️|##|###|####|\*\*Bias|\*\*Strumenti|---)",
        re.UNICODE,
    )
    for i, riga in enumerate(righe):
        stripped = riga.strip()
        if stripped and MARCATORI.match(stripped):
            return "\n".join(righe[i:]).strip()

    # --- Passo 3: fallback — salta righe con parole-spia inglesi ---
    INGLESE = re.compile(
        r"\b(okay|let'?s|first|now|looking|i need|i will|i must|i want|the user"
        r"|next|finally|putting|starting|checking|trying|understand|going to"
        r"|also|then|wait|need to|here|so |this |these |those |they |there )\b",
        re.IGNORECASE,
    )
    for i, riga in enumerate(righe):
        stripped = riga.strip()
        if not stripped:
            continue
        if not INGLESE.search(stripped):
            return "\n".join(righe[i:]).strip()

    return testo


class AgnoTechnicalTeam:
    """
    Team Tecnico V5 — wrapper sui 4 specialisti standalone.

    Non ridefinisce gli agenti inline: istanzia PatternAgent, TrendAgent,
    SRAgent e VolumeAgent dai loro file dedicati, garantendo che tutte le
    istruzioni, i campi ## SINTESI OPERATIVA e i sistemi di verdetto
    siano identici sia in modalità SupervisorAgent che in modalità Team.
    """

    def __init__(self):
        self.db_path = Calibrazione.DATABASE_PATH

        # --- 1. Istanzia i 4 specialisti dai file dedicati ---
        # Le istruzioni, i campi SINTESI OPERATIVA e i sistemi di verdetto
        # sono definiti nei file specialisti — nessuna ridefinizione qui.
        self._pattern = PatternAgent() if Calibrazione.AGENT_PATTERN_ENABLED else None
        self._trend   = TrendAgent()   if Calibrazione.AGENT_TREND_ENABLED   else None
        self._sr      = SRAgent()      if Calibrazione.AGENT_SR_ENABLED       else None
        self._volume  = VolumeAgent()  if Calibrazione.AGENT_VOLUME_ENABLED   else None

        # Mappa nome → istanza (usata da analizza_specialista)
        self._specialist_map: dict = {}
        if self._pattern: self._specialist_map["Pattern Analyst"] = self._pattern
        if self._trend:   self._specialist_map["Trend Analyst"]   = self._trend
        if self._sr:      self._specialist_map["SR Analyst"]       = self._sr
        if self._volume:  self._specialist_map["Volume Analyst"]   = self._volume

        if not self._specialist_map:
            logger.warning("[AGNO TEAM] Nessun agente tecnico attivo in Calibrazione.py.")

        # --- 2. Storage condiviso per il Team orchestrator ---
        storage = None
        if Calibrazione.STORAGE_LOCATION == "local":
            storage = SqliteDb(
                session_table="technical_team_session",
                db_file=self.db_path,
            )

        # --- 3. Modello orchestratore Team ---
        llm_desk = get_model(
            Calibrazione.MODEL_TECH_ORCHESTRATOR,
            temperature=Calibrazione.TEMPERATURE_TECH_ORCHESTRATOR,
            agent_name="tech_orchestrator",
        )

        # --- 4. Team Agno — usa gli agenti .agent degli specialisti come membri ---
        active_members = [
            spec.agent
            for spec in self._specialist_map.values()
        ]

        self.team = Team(
            name="Technical Trading Desk",
            members=active_members,
            model=llm_desk,
            description=(
                "Sei il Capo del Technical Trading Desk. "
                "Coordini i 4 specialisti tecnici (Pattern, Trend, SR, Volume) "
                "e sintetizzi le loro analisi in un verdetto operativo unificato. "
                "Il Volume Analyst è il filtro finale: se dichiara RISCHIO ELEVATO, "
                "il verdetto è NO TRADE indipendentemente dagli altri. "
                "Se dichiara INCERTO, riduci la confidence ma non bloccare automaticamente."
            ),
            instructions=[
                "LINGUA OBBLIGATORIA: Italiano. Scrivi TUTTO in italiano. "
                "Non usare mai l'inglese, nemmeno per frasi introduttive.",

                "Ricevi i dati OHLCV e il Macro Sentiment, poi interroga gli specialisti.",

                "Usa il Macro Sentiment come bussola direzionale, non come veto assoluto: "
                "se 3+ specialisti tecnici convergono in direzione opposta al macro, "
                "dichiara 'CONTRADDIZIONE MACRO-TECNICA' e riduci la confidence.",

                "GERARCHIA VETO VOLUME: "
                "se il Volume Analyst dichiara esplicitamente 'RISCHIO ELEVATO' o 'VETO OPERATIVO' "
                "→ verdetto NO TRADE obbligatorio. "
                "Se dichiara 'INCERTO' o 'NEUTRO' → riduci confidence, trade ancora possibile.",

                "Il verdetto finale deve includere sempre: "
                "Bias (Bullish/Bearish/NO TRADE), Entry, Stop Loss, Target 1, Target 2 "
                "con prezzi numerici reali e fonte tra parentesi quadre. "
                "Se un livello non è disponibile scrivi '[nessun agente ha fornito questo livello]'.",

                "Struttura la risposta in sezioni markdown con titoli in italiano.",
            ],
            db=storage,
            num_history_messages=3,
            markdown=True,
        )
        logger.success(
            f"[AGNO TEAM] Team Tecnico pronto — "
            f"specialisti attivi: {list(self._specialist_map.keys())} | "
            f"orchestrator: {llm_desk.id}"
        )

    def analizza_specialista(
        self,
        nome_specialista: str,
        data_summary: str,
        macro_sentiment: str = "Neutrale",
        skills_guidance: str = "",
        other_analyses: dict = None,
    ) -> str:
        """
        Esegue l'analisi di un singolo specialista standalone.
        Usa il metodo analizza() del file dedicato — stesso comportamento
        del SupervisorAgent sequenziale.

        Args:
            nome_specialista: "Pattern Analyst" / "Trend Analyst" / "SR Analyst" / "Volume Analyst"
            data_summary:     Dati OHLCV multi-timeframe.
            macro_sentiment:  Sentiment macro dell'AgnoMacroExpert.
            skills_guidance:  Tecniche OBBLIGATORIE dalla FOCUS SKILLS.
            other_analyses:   Dict {nome: testo} degli altri specialisti (solo per Volume Analyst).

        Returns:
            Stringa Markdown con l'analisi completa.
        """
        logger.info(f"[AGNO TEAM] Interrogazione specialistica: {nome_specialista}")

        spec = self._specialist_map.get(nome_specialista)
        if not spec:
            logger.error(f"[AGNO TEAM] Specialista '{nome_specialista}' non trovato o disattivato.")
            raise ValueError(
                f"❌ ERRORE [AgnoTechnicalTeam]: specialista '{nome_specialista}' "
                f"non trovato o disattivato in Calibrazione.py."
            )

        if nome_specialista == "Volume Analyst":
            return spec.analizza(
                data_summary,
                macro_sentiment,
                skills_guidance=skills_guidance,
                other_analyses=other_analyses or {},
            )
        return spec.analizza(
            data_summary,
            macro_sentiment,
            skills_guidance=skills_guidance,
        )

    def analizza_asset(self, data_summary: str, macro_sentiment: str = "Neutrale") -> str:
        """
        Esegue l'analisi coordinata del team completo (modalità Team Agno).
        Mantenuto per compatibilità con il codice che chiama questo metodo direttamente.
        """
        logger.info(f"[AGNO TEAM] Avvio analisi team con Macro Sentiment: {macro_sentiment[:80]}...")

        query = f"""
DATI MERCATO ATTUALI (OHLCV Multi-Timeframe):
{data_summary}

SENTIMENT MACRO (bussola direzionale — fornito dall'AgnoMacroExpert):
{macro_sentiment}

Interroga tutti gli specialisti e fornisci il verdetto unificato.
Ordine obbligatorio: Pattern Analyst → Trend Analyst → SR Analyst → Volume Analyst → Verdetto.
"""
        try:
            response = self.team.run(query)
            if not response.content:
                logger.error("[AGNO TEAM] Risposta vuota dal team orchestrator.")
                return "❌ ERRORE [AgnoTechnicalTeam]: risposta vuota dal team orchestrator."
            return response.content
        except Exception as e:
            logger.error(f"[AGNO TEAM] Errore durante l'analisi team: {e}")
            raise