from agno.agent import Agent, RunEvent
from agno.tools.hackernews import HackerNewsTools
from clients.ultimate_llm import get_llm_agno


# Get cached model instances from ultimate_llm
primary_llm = get_llm_agno(model="functiongemma:270m", provider="functiongemma")
output_llm = get_llm_agno(model="google/gemma-3-4b-it", provider="openrouter")

agent = Agent(
    # FunctionGemma handles reasoning + tool calls (slow, hidden)
    model=primary_llm,
    # Gemma 3 27B writes the final response (fast, visible)
    output_model=output_llm,
    tools=[HackerNewsTools()],
    debug_mode=True
)




stream = agent.run("What are the top stories on HackerNews?", stream=True, stream_events=True)
for chunk in stream:
    # Only show the output_model's response, skip primary model's intermediate output
    if chunk.event == RunEvent.run_content:
        print(chunk.content, end="", flush=True)
    # Skip RunEvent.run_intermediate_content (primary model's output)