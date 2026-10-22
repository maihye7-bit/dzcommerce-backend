"""
QwenAgentProvider: Integrates Qwen-Agent as the orchestration layer.
Connects our ToolRegistry to Qwen's function calling mechanism.
"""

import json
import os
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.providers.agent_provider import AgentProvider

# Note: In a real environment, you would install dashscope or qwen-agent
# pip install dashscope
try:
    from http import HTTPStatus

    import dashscope
except ImportError:
    dashscope = None


class QwenAgentProvider(AgentProvider):
    def __init__(self):
        self.api_key = os.environ.get("QWEN_API_KEY")
        self.model_name = os.environ.get("QWEN_MODEL", "qwen-max")

        if not self.api_key:
            print(
                "Warning: QWEN_API_KEY not set. QwenAgentProvider will fail on execution."
            )

    async def process_message(
        self,
        db: Session,
        store_id: uuid.UUID,
        customer_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user_message: str,
        history: list[dict],
        tools_schema: list[dict],
    ) -> dict:
        if not self.api_key or dashscope is None:
            raise RuntimeError("QWEN_API_KEY is missing or dashscope not installed.")

        dashscope.api_key = self.api_key
        messages = history + [{"role": "user", "content": user_message}]

        try:
            response = dashscope.Generation.call(
                model=self.model_name,
                messages=messages,
                tools=tools_schema,
                result_format="message",
            )

            if response.status_code == HTTPStatus.OK:
                output = response.output.choices[0].message

                if hasattr(output, "tool_calls") and output.tool_calls:
                    return {
                        "response": None,
                        "tool_calls": [
                            {
                                "name": tc.function.name,
                                "arguments": json.loads(tc.function.arguments),
                            }
                            for tc in output.tool_calls
                        ],
                    }
                else:
                    return {"response": output.content, "tool_calls": []}
            else:
                raise Exception(f"Qwen API Error: {response.code} - {response.message}")

        except Exception as e:
            return {"error": f"Qwen-Agent processing failed: {str(e)}"}
