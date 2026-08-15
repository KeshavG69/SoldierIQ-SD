#!/usr/bin/env python3
"""
Generate comprehensive training data for FunctionGemma in TxT360-3efforts format.

Includes examples with:
- 0 tool calls (greetings, general chat, questions not needing tools)
- 1 tool call (each tool individually)
- 2 tool calls (parallel execution of 2 tools)
- 3 tool calls (parallel execution of 3 tools)
- 4 tool calls (all tools in parallel)
"""

import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any
import asyncio

# Add backend to path for imports
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from clients.ultimate_llm import get_llm
from app.settings import Settings


TOOLS_SCHEMA = [
    {
        "name": "search_knowledge_base",
        "description": "Search the knowledge base using semantic search. Use this tool to find information from uploaded documents, PDFs, videos, and images. Returns relevant documents with similarity scores.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query to find relevant documents"},
                "num_documents": {"type": "integer", "description": "Maximum number of results to return", "default": 10}
            },
            "required": ["query"]
        }
    },
    {
        "name": "place_tak_marker",
        "description": "Place a marker on the TAK network at specified coordinates. Use this when the user wants to mark a location, place a point of interest, or share coordinates with the team on TAK/ATAK.",
        "parameters": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Latitude coordinate (-90 to 90)"},
                "longitude": {"type": "number", "description": "Longitude coordinate (-180 to 180)"},
                "callsign": {"type": "string", "description": "Display name/label for the marker"},
                "message": {"type": "string", "description": "Optional message or remarks to attach to marker"}
            },
            "required": ["latitude", "longitude", "callsign"]
        }
    },
    {
        "name": "send_tak_message",
        "description": "Send a chat message to the TAK network (broadcast to all users). Use this when the user wants to broadcast a message or alert to all TAK users on the network.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message text to send"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "create_tak_route",
        "description": "Create a route on the TAK network with multiple waypoints. Use this when the user wants to plan a route, show a path, or define a movement corridor with multiple points.",
        "parameters": {
            "type": "object",
            "properties": {
                "waypoints": {
                    "type": "array",
                    "description": "List of waypoint dicts with 'lat' and 'lon' keys",
                    "items": {"type": "object", "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}}, "required": ["lat", "lon"]},
                    "minItems": 2
                },
                "route_name": {"type": "string", "description": "Display name for the route"}
            },
            "required": ["waypoints", "route_name"]
        }
    }
]


# Prompts for different scenarios

PROMPT_NO_TOOLS = """Generate {num_examples} diverse examples where NO tools should be used.

These are normal conversations that don't require any tools:
- Greetings: "Hello", "Hi", "Good morning", "Hey there"
- Farewells: "Goodbye", "See you later", "Thanks, bye"
- General questions about the assistant: "What can you do?", "How can you help me?", "What are your capabilities?"
- Small talk: "How are you?", "What's your name?", "Nice to meet you"
- General knowledge that doesn't need the knowledge base: "What is AI?", "Explain machine learning", "What's the capital of France?"
- Meta questions: "Can you help me?", "Are you an AI?", "Who created you?"

Return JSON array:
[
  {{
    "user_query": "Hello!",
    "thinking": "The user is greeting me. This is a simple greeting that doesn't require any tool usage. I should respond warmly and let them know I'm here to help.",
    "assistant_response": "Hello! I'm here to help you with your knowledge base and TAK operations. How can I assist you today?"
  }},
  ...
]
"""

PROMPT_SINGLE_TOOL = """Generate {num_examples} examples for single tool usage: {tool_name}

Tool: {tool_name}
Description: {tool_description}
Parameters: {tool_parameters}

Make queries diverse and realistic for military/tactical context.

Return JSON array:
[
  {{
    "user_query": "...",
    "thinking": "Detailed reasoning about understanding intent, choosing tool, extracting parameters (3-5 sentences)",
    "tool_call": {{
      "name": "{tool_name}",
      "arguments": "JSON string"
    }}
  }},
  ...
]
"""

PROMPT_MULTI_TOOLS = """Generate {num_examples} examples where the user needs {num_tools} tools used IN PARALLEL.

Tools to use: {tool_names}

Context: Military/tactical system. User requests should naturally require all {num_tools} tools at once.

Examples of multi-tool scenarios:
- Search knowledge + place marker + send message: "Find intel on area X, mark it, and alert the team"
- Search + create route + send message: "Find patrol procedures, plan route from A to B, notify team"
- Place marker + send message: "Mark enemy position at coordinates and alert everyone"
- All 4 tools: "Search for mission brief, mark objective coordinates, create route, and broadcast mission start"

Return JSON array:
[
  {{
    "user_query": "...",
    "thinking": "Detailed reasoning about why all {num_tools} tools are needed and how to execute them in parallel (4-6 sentences)",
    "tool_calls": [
      {{"name": "tool1", "arguments": "JSON string"}},
      {{"name": "tool2", "arguments": "JSON string"}},
      ...
    ]
  }},
  ...
]
"""


async def generate_no_tool_examples(num_examples: int, llm) -> List[Dict[str, Any]]:
    """Generate examples with no tool calls."""
    print(f"\nGenerating {num_examples} examples with NO TOOLS...")

    prompt = PROMPT_NO_TOOLS.format(num_examples=num_examples)

    try:
        response = llm.invoke(prompt)
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        generated_data = json.loads(content)

        examples = []
        for item in generated_data:
            messages = [
                {"role": "system", "content": "", "tools": TOOLS_SCHEMA},
                {"role": "user", "content": item["user_query"], "tool_calls": []},
                {"role": "assistant", "think": item["thinking"], "content": item["assistant_response"], "tool_calls": []}
            ]
            examples.append({"messages": json.dumps(messages)})

        print(f"✓ Generated {len(examples)} no-tool examples")
        return examples
    except Exception as e:
        print(f"✗ Error: {e}")
        return []


async def generate_single_tool_examples(tool_schema: Dict, num_examples: int, llm) -> List[Dict[str, Any]]:
    """Generate examples with 1 tool call."""
    tool_name = tool_schema["name"]
    print(f"\nGenerating {num_examples} examples with 1 TOOL: {tool_name}...")

    prompt = PROMPT_SINGLE_TOOL.format(
        num_examples=num_examples,
        tool_name=tool_name,
        tool_description=tool_schema["description"],
        tool_parameters=json.dumps(tool_schema["parameters"], indent=2)
    )

    try:
        response = llm.invoke(prompt)
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        generated_data = json.loads(content)

        examples = []
        for item in generated_data:
            messages = [
                {"role": "system", "content": "", "tools": TOOLS_SCHEMA},
                {"role": "user", "content": item["user_query"], "tool_calls": []},
                {"role": "assistant", "think": item["thinking"], "tool_calls": [{"name": item["tool_call"]["name"], "arguments": item["tool_call"]["arguments"]}]}
            ]
            examples.append({"messages": json.dumps(messages)})

        print(f"✓ Generated {len(examples)} single-tool examples for {tool_name}")
        return examples
    except Exception as e:
        print(f"✗ Error: {e}")
        return []


async def generate_multi_tool_examples(tool_names: List[str], num_examples: int, llm) -> List[Dict[str, Any]]:
    """Generate examples with multiple parallel tool calls."""
    num_tools = len(tool_names)
    print(f"\nGenerating {num_examples} examples with {num_tools} TOOLS: {', '.join(tool_names)}...")

    prompt = PROMPT_MULTI_TOOLS.format(
        num_examples=num_examples,
        num_tools=num_tools,
        tool_names=", ".join(tool_names)
    )

    try:
        response = llm.invoke(prompt)
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        generated_data = json.loads(content)

        examples = []
        for item in generated_data:
            messages = [
                {"role": "system", "content": "", "tools": TOOLS_SCHEMA},
                {"role": "user", "content": item["user_query"], "tool_calls": []},
                {"role": "assistant", "think": item["thinking"], "tool_calls": item["tool_calls"]}
            ]
            examples.append({"messages": json.dumps(messages)})

        print(f"✓ Generated {len(examples)} multi-tool examples ({num_tools} tools)")
        return examples
    except Exception as e:
        print(f"✗ Error: {e}")
        return []


async def main():
    """Main generation pipeline."""
    print("=" * 80)
    print("Comprehensive FunctionGemma Training Data Generation")
    print("=" * 80)
    print("\nDataset will include:")
    print("  • No tool calls (greetings, general chat)")
    print("  • 1 tool call (each tool individually)")
    print("  • 2 tool calls (parallel execution)")
    print("  • 3 tool calls (parallel execution)")
    print("  • 4 tool calls (all tools parallel)")
    print("=" * 80)

    # Initialize LLM
    print("\nInitializing Claude Haiku 4.5...")
    llm = get_llm(
        model="anthropic/claude-haiku-4.5",
        provider="openrouter"
    )

    all_examples = []

    # 1. No tool calls (30 examples)
    examples = await generate_no_tool_examples(30, llm)
    all_examples.extend(examples)
    await asyncio.sleep(2)

    # 2. Single tool calls (40 examples per tool = 160 total)
    for tool_schema in TOOLS_SCHEMA:
        examples = await generate_single_tool_examples(tool_schema, 40, llm)
        all_examples.extend(examples)
        await asyncio.sleep(2)

    # 3. Two tool calls (20 examples each combination)
    two_tool_combinations = [
        ["search_knowledge_base", "place_tak_marker"],
        ["search_knowledge_base", "send_tak_message"],
        ["search_knowledge_base", "create_tak_route"],
        ["place_tak_marker", "send_tak_message"],
        ["place_tak_marker", "create_tak_route"],
        ["send_tak_message", "create_tak_route"]
    ]
    for combo in two_tool_combinations:
        examples = await generate_multi_tool_examples(combo, 15, llm)
        all_examples.extend(examples)
        await asyncio.sleep(2)

    # 4. Three tool calls (15 examples each combination)
    three_tool_combinations = [
        ["search_knowledge_base", "place_tak_marker", "send_tak_message"],
        ["search_knowledge_base", "place_tak_marker", "create_tak_route"],
        ["search_knowledge_base", "send_tak_message", "create_tak_route"],
        ["place_tak_marker", "send_tak_message", "create_tak_route"]
    ]
    for combo in three_tool_combinations:
        examples = await generate_multi_tool_examples(combo, 10, llm)
        all_examples.extend(examples)
        await asyncio.sleep(2)

    # 5. All four tools (20 examples)
    examples = await generate_multi_tool_examples(
        ["search_knowledge_base", "place_tak_marker", "send_tak_message", "create_tak_route"],
        20,
        llm
    )
    all_examples.extend(examples)

    # Summary
    print(f"\n{'='*80}")
    print("Generation Complete!")
    print(f"{'='*80}")
    print(f"Total examples: {len(all_examples)}")

    # Count by number of tool calls
    tool_call_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for example in all_examples:
        messages = json.loads(example["messages"])
        for msg in messages:
            if msg["role"] == "assistant":
                num_calls = len(msg.get("tool_calls", []))
                tool_call_counts[num_calls] = tool_call_counts.get(num_calls, 0) + 1
                break

    print("\nDistribution by number of tool calls:")
    print(f"  • 0 tools (no tool calls): {tool_call_counts[0]}")
    print(f"  • 1 tool: {tool_call_counts[1]}")
    print(f"  • 2 tools (parallel): {tool_call_counts[2]}")
    print(f"  • 3 tools (parallel): {tool_call_counts[3]}")
    print(f"  • 4 tools (parallel): {tool_call_counts[4]}")

    # Save files
    output_dir = Path(__file__).parent.parent / "training_data"
    output_dir.mkdir(exist_ok=True)

    training_file = output_dir / "functiongemma_training.jsonl"
    print(f"\nSaving to: {training_file}")
    with open(training_file, "w") as f:
        for example in all_examples:
            f.write(json.dumps(example) + "\n")

    schema_file = output_dir / "tools_schema.json"
    with open(schema_file, "w") as f:
        json.dump(TOOLS_SCHEMA, f, indent=2)

    readable_file = output_dir / "training_examples_readable.json"
    with open(readable_file, "w") as f:
        readable = [{"messages": json.loads(ex["messages"])} for ex in all_examples[:10]]
        json.dump(readable, f, indent=2)

    print(f"\n{'='*80}")
    print("Files created:")
    print(f"  • {training_file.name}")
    print(f"  • {schema_file.name}")
    print(f"  • {readable_file.name} (first 10 examples)")
    print(f"{'='*80}")


if __name__ == "__main__":
    asyncio.run(main())
