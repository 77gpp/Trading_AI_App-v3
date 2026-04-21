import sys

# Add project root to path
project_root = "/Users/gpp/Programmazione/Trading/In lavorazione/Trading_AI_App v3"
sys.path.insert(0, project_root)

from ddgs import DDGS
from agents.duckduckgo_news_tool import get_duckduckgo_news, get_duckduckgo_news_raw

try:
    print("--- RAW DDGS RESPONSE ATTRIBUTES ---")
    with DDGS(timeout=15, verify=True) as ddgs:
        raw_results = ddgs.news(
            query="gold price market news",
            max_results=5,
            timelimit="w",
            region="us-en",
        )
    print(f"Tipo risultato: {type(raw_results)}")
    print(f"Numero risultati: {len(raw_results)}")
    if raw_results:
        print(f"Chiavi primo risultato: {list(raw_results[0].keys())}")
        print(f"Primo risultato raw:\n{raw_results[0]}")

    print("\n--- Testing formatted wrapper (get_duckduckgo_news) ---")
    output = get_duckduckgo_news("gold")
    lines = output.splitlines()
    print(f"Wrapper output lines: {len(lines)}")
    if lines:
        print("Prime 3 righe:")
        for line in lines[:3]:
            print(f"> {line}")

    print("\n--- Testing structured wrapper (get_duckduckgo_news_raw) ---")
    structured = get_duckduckgo_news_raw("GC=F")
    print(f"Numero articoli strutturati: {len(structured)}")
    if structured:
        print("Primo articolo strutturato:")
        for k, v in structured[0].items():
            print(f"  {k}: {v}")

    print("\n--- Testing query mapping (simboli speciali) ---")
    for query in ["GC=F", "^GSPC", "BTC-USD", "AAPL"]:
        result = get_duckduckgo_news_raw(query)
        print(f"  '{query}' → {len(result)} notizie")

except Exception as e:
    print(f"Errore: {e}")
    import traceback
    traceback.print_exc()
