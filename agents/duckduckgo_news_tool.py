from ddgs import DDGS
from loguru import logger
import Calibrazione

# Dizionario per mappare asset non azionari (future, indici, materie prime, forex)
# nelle loro query di ricerca ottimizzate per DuckDuckGo in linguaggio naturale.
# A differenza di Alpaca (che vuole ticker ETF), DuckDuckGo funziona meglio
# con termini descrittivi in inglese. I valori sono stringhe di query pronte all'uso.
DDG_QUERY_MAP = {
    # ── Oro / Gold ────────────────────────────────────────────────────────────
    "oro": "gold price market news",
    "gold": "gold price market news",
    "gc=f": "gold price market news", "xauusd": "gold price market news", "gc": "gold price market news",

    # ── Argento / Silver ──────────────────────────────────────────────────────
    "argento": "silver price market news",
    "silver": "silver price market news", "si=f": "silver price news", "xagusd": "silver price news", "si": "silver price news",

    # ── Petrolio / Crude Oil ──────────────────────────────────────────────────
    "petrolio": "crude oil price market news",
    "oil": "crude oil price market news", "crude oil": "crude oil price market news",
    "wti": "WTI crude oil price news", "brent": "Brent crude oil price news",
    "cl=f": "crude oil price news", "cl": "crude oil price news",

    # ── Gas Naturale ──────────────────────────────────────────────────────────
    "gas naturale": "natural gas price market news",
    "natural gas": "natural gas price market news", "ng=f": "natural gas price news", "ng": "natural gas price news",

    # ── S&P 500 ───────────────────────────────────────────────────────────────
    "sp500": "S&P 500 stock market news",
    "s&p 500": "S&P 500 stock market news", "s&p500": "S&P 500 stock market news",
    "^gspc": "S&P 500 stock market news", "es=f": "S&P 500 futures market news",

    # ── Nasdaq ────────────────────────────────────────────────────────────────
    "nasdaq": "Nasdaq technology stock market news", "^ixic": "Nasdaq market news", "nq=f": "Nasdaq futures market news",

    # ── Dow Jones ─────────────────────────────────────────────────────────────
    "dow jones": "Dow Jones industrial average market news", "dj": "Dow Jones market news",
    "^dji": "Dow Jones market news", "ym=f": "Dow Jones futures market news",

    # ── Russell 2000 ──────────────────────────────────────────────────────────
    "russell 2000": "Russell 2000 small cap market news", "rut": "Russell 2000 market news", "^rut": "Russell 2000 market news",

    # ── Crypto ────────────────────────────────────────────────────────────────
    "bitcoin": "Bitcoin price crypto market news",
    "btc": "Bitcoin price market news", "btc-usd": "Bitcoin price news", "btcusd": "Bitcoin price news",
    "ethereum": "Ethereum price crypto market news",
    "eth": "Ethereum price market news", "eth-usd": "Ethereum price news", "ethusd": "Ethereum price news",

    # ── Forex ─────────────────────────────────────────────────────────────────
    "eurusd": "EUR/USD euro dollar forex news", "eurusd=x": "EUR/USD forex news", "euro": "euro dollar exchange rate news",
    "dollaro": "US dollar DXY index news", "dollar": "US dollar index news", "usd": "US dollar index news",
    "dxy": "US dollar DXY index news", "dx-y.nyb": "US dollar index news",
    "gbpusd": "GBP/USD pound dollar forex news", "gbp": "British pound forex news",
    "usdjpy": "USD/JPY dollar yen forex news", "jpy": "Japanese yen forex news", "yen": "Japanese yen forex news",
    "usdchf": "USD/CHF dollar franc forex news", "chf": "Swiss franc forex news",

    # ── Bond / Tassi ──────────────────────────────────────────────────────────
    "treasury": "US Treasury bonds yield market news",
    "bond": "US Treasury bonds market news", "bonds": "US bonds market news",
    "10y treasury": "10-year Treasury yield market news", "tnote": "Treasury note yield news",
    "^tnx": "10-year Treasury yield news", "zn=f": "Treasury note futures news",

    # ── Materie prime / Commodities ───────────────────────────────────────────
    "rame": "copper price commodity market news",
    "copper": "copper price commodity news", "hg=f": "copper price futures news",
    "frumento": "wheat price commodity news", "wheat": "wheat price commodity news",
    "mais": "corn price commodity news", "corn": "corn price commodity news",
    "soia": "soybean price commodity news", "soybean": "soybean price commodity news",
    "materie prime": "commodities market news", "commodities": "commodities market news",

    # ── Volatilità ────────────────────────────────────────────────────────────
    "vix": "VIX volatility index market news", "^vix": "VIX volatility market news",

    # ── Mercati emergenti ──────────────────────────────────────────────────────
    "emerging markets": "emerging markets stocks news", "em": "emerging markets news",

    # ── High Yield / Credit ───────────────────────────────────────────────────
    "high yield": "high yield bonds credit market news", "hy": "high yield bonds news",

    # ── Settori ───────────────────────────────────────────────────────────────
    "energia": "energy sector stocks news", "energy": "energy sector stocks news",
    "tecnologia": "technology sector stocks news", "tech": "technology sector market news",
    "finanza": "financial sector banking stocks news", "financials": "financial sector news",
    "difesa": "defense sector stocks news", "defense": "defense sector stocks news",
}


def get_duckduckgo_news(query: str) -> str:
    """
    Ottiene le ultime notizie web per un asset tramite DuckDuckGo.

    Converte automaticamente nomi comuni, simboli o ticker in query di ricerca ottimizzate
    in linguaggio naturale. Il timelimit è fisso a 'w' (ultima settimana) per garantire
    la rilevanza temporale dei risultati.

    IMPORTANTE: Passa il nome comune dell'asset in italiano o inglese (es. 'gold', 'oro',
    'oil', 'bitcoin', 'sp500', 'eurusd', 'nasdaq') oppure una query libera in linguaggio
    naturale (es. 'gold price market outlook'). Il tool converte automaticamente ticker
    con caratteri speciali (es. 'GC=F', 'CL=F', '^GSPC') nella query corretta.

    Args:
        query (str): Nome comune, simbolo o query libera dell'asset.
                     Esempi corretti: 'gold', 'oil', 'bitcoin', 'sp500', 'eurusd', 'AAPL'.
                     Accettati ma convertiti: 'GC=F', 'CL=F', '^GSPC'.

    Returns:
        str: Una stringa formattata con i titoli delle notizie e i link alle fonti.
             In caso di errore, restituisce un messaggio di errore esplicito.
    """
    original_query = query
    query_lower = query.strip().lower()

    # Se il termine è nella mappa, usiamo la query DDG ottimizzata
    if query_lower in DDG_QUERY_MAP:
        search_query = DDG_QUERY_MAP[query_lower]
        logger.info(f"[DDG TOOL] Mapping '{original_query}' -> query: '{search_query}'")
    else:
        # Fallback: puliamo il ticker dallo stile Yahoo Finance e lo usiamo come query diretta
        cleaned = query.split("=")[0].split("-")[0].replace("^", "").strip()
        search_query = f"{cleaned} price market news"
        logger.info(f"[DDG TOOL] Nessun mapping per '{original_query}', uso query diretta: '{search_query}'")

    max_results = getattr(Calibrazione, "DUCKDUCKGO_NEWS_LIMIT", 10)
    timelimit = "w"
    region = "us-en"

    logger.info(f"[DDG TOOL] Ricerca news: '{search_query}' | max_results={max_results} | timelimit={timelimit}")

    try:
        with DDGS(timeout=15, verify=True) as ddgs:
            results = ddgs.news(
                query=search_query,
                max_results=max_results,
                timelimit=timelimit,
                region=region,
            )

        if not results:
            logger.warning(f"[DDG TOOL] Nessun risultato per query: '{search_query}'")
            return f"Nessuna notizia trovata su DuckDuckGo per '{original_query}' (query: '{search_query}', periodo: ultima settimana)."

        logger.success(f"[DDG TOOL] {len(results)} notizie trovate per '{original_query}' [{search_query}]")

        formatted = [f"### Notizie Web DuckDuckGo per {original_query} [{search_query}]:"]
        for item in results:
            title = item.get("title", "Titolo non disponibile")
            url = item.get("url", "")
            source = item.get("source", "Fonte sconosciuta")
            date = item.get("date", "Data sconosciuta")
            formatted.append(f"- **{title}** ({date}) - [Leggi Fonte]({url}) [Fonte: {source}]")

        return "\n".join(formatted)

    except Exception as e:
        logger.error(f"[DDG TOOL] ERRORE: {e}")
        return f"ERRORE nel recupero news DuckDuckGo per '{original_query}': {str(e)}"


def get_duckduckgo_news_raw(query: str) -> list:
    """
    Versione strutturata di get_duckduckgo_news per uso nel frontend.
    Restituisce una lista di dizionari compatibili con il formato news API:
    [{time, date, headline, summary, url, source, symbols, provider}, ...]
    """
    import dateutil.parser as dtparser

    original_query = query
    query_lower = query.strip().lower()

    if query_lower in DDG_QUERY_MAP:
        search_query = DDG_QUERY_MAP[query_lower]
    else:
        cleaned = query.split("=")[0].split("-")[0].replace("^", "").strip()
        search_query = f"{cleaned} price market news"

    max_results = getattr(Calibrazione, "DUCKDUCKGO_NEWS_LIMIT", 10)

    logger.info(f"[DDG RAW] Ricerca: '{search_query}' | max_results={max_results}")

    try:
        with DDGS(timeout=15, verify=True) as ddgs:
            results = ddgs.news(
                query=search_query,
                max_results=max_results,
                timelimit="w",
                region="us-en",
            )

        if not results:
            logger.warning(f"[DDG RAW] Nessun risultato per '{search_query}'")
            return []

        news_list = []
        for item in results:
            date_str = item.get("date", "")
            try:
                dt = dtparser.parse(date_str)
                ts = int(dt.timestamp())
                date_fmt = dt.strftime("%Y-%m-%d")
            except Exception:
                ts = 0
                date_fmt = date_str[:10] if date_str else ""

            news_list.append({
                "time":     ts,
                "date":     date_fmt,
                "headline": item.get("title", ""),
                "summary":  item.get("body", ""),
                "url":      item.get("url", ""),
                "source":   item.get("source", "DuckDuckGo"),
                "symbols":  [original_query],
                "provider": "duckduckgo",
            })

        logger.success(f"[DDG RAW] {len(news_list)} notizie strutturate per '{original_query}'")
        return news_list

    except Exception as e:
        logger.error(f"[DDG RAW] ERRORE: {e}")
        return []


if __name__ == "__main__":
    print(get_duckduckgo_news("gold"))
