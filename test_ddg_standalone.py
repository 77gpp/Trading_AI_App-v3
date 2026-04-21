"""
Test standalone per DuckDuckGo news tool.
Verifica che la funzione get_duckduckgo_news restituisca risultati corretti.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.duckduckgo_news_tool import get_duckduckgo_news

TEST_QUERIES = ["gold", "GC=F", "bitcoin", "sp500", "oil", "AAPL"]

for query in TEST_QUERIES:
    print(f"\n{'='*60}")
    print(f"Query: '{query}'")
    print('='*60)
    result = get_duckduckgo_news(query)
    lines = result.split("\n")
    print(f"Righe restituite: {len(lines)}")
    print(result[:500])
    print("...")
