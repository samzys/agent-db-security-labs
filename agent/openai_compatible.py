"""Model-independent OpenAI-compatible tool-call request/response contract."""

from __future__ import annotations

from typing import Any

from gateway.catalog import catalog_for_profile


def build_request(profile_id: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for tool in catalog_for_profile(profile_id)
    ]
    return {
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0,
    }


def parse_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("response has no choices")
    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls", [])
    if not isinstance(tool_calls, list):
        raise ValueError("tool_calls must be a list")
    return tool_calls
