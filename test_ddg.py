from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agents.model_factory import get_model
import Calibrazione

llm = get_model('qwen/qwen3-32b', temperature=0.7, agent_name='macro_expert')

agent = Agent(
    model=llm,
    tools=[
        DuckDuckGoTools(
            enable_search=False,
            enable_news=True,
            fixed_max_results=3,
            timelimit='w',
            region='us-en',
            timeout=15,
        )
    ],
    instructions=['Chiama SUBITO duckduckgo_news con query gold price. Mostra i risultati.'],
    markdown=False,
)

response = agent.run('Cerca notizie su gold price usando duckduckgo_news.')
print('RESPONSE:', response.content)
