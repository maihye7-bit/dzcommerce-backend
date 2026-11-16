"""
FreeLLM Provider – thin wrapper around AsyncOpenAI that points to FreeLLMAPI.
"""
import asyncio
import json
import logging
import time
from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from app.agent.providers.base import LLMMessage, LLMProvider, LLMResponse
from app.core.config import (
    FREE_LLM_API_KEY,
    FREE_LLM_BASE_URL,
    FREE_LLM_MODEL,
    FREE_LLM_TIMEOUT,
)

logger = logging.getLogger(__name__)


class FreeLLMProvider(LLMProvider):
    provider_name = "freellm"

    def __init__(self):
        if not FREE_LLM_API_KEY:
            raise ValueError("FREE_LLM_API_KEY is not set.")

        self.client = AsyncOpenAI(
            api_key=FREE_LLM_API_KEY,
            base_url=FREE_LLM_BASE_URL,
            timeout=float(FREE_LLM_TIMEOUT),
        )
        self.model = FREE_LLM_MODEL
        # Max retries for transient errors (429, 500s)
        self.max_retries = 3

    def _build_openai_messages(self, messages: list[LLMMessage]) -> list[dict]:
        """Convert internal LLMMessage list to OpenAI-compatible format."""
        openai_messages = []
        for m in messages:
            msg: dict = {"role": m.role}

            if m.role == "assistant" and m.tool_calls:
                msg["content"] = m.content if m.content else None
                msg["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                        },
                    }
                    for tc in m.tool_calls
                ]
            elif m.role == "tool":
                msg["content"] = m.content or ""
                msg["tool_call_id"] = m.tool_call_id or ""
            else:
                msg["content"] = m.content or ""

            openai_messages.append(msg)
        return openai_messages

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        system_prompt: str | None = None,
        session_id: str | None = None,
    ) -> LLMResponse:
        start_time = time.time()
        openai_messages = self._build_openai_messages(messages)

        if system_prompt and not any(m["role"] == "system" for m in openai_messages):
            openai_messages.insert(0, {"role": "system", "content": system_prompt})

        # Map tools to OpenAI format (handling both flat and nested structures)
        openai_tools = None
        if tools:
            openai_tools = []
            for t in tools:
                if "type" in t and t["type"] == "function" and "function" in t:
                    openai_tools.append(t)
                elif "name" in t:
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "parameters": t.get("parameters", {}),
                        },
                    })

        last_exception = None

        # Prepare extra headers for FreeLLMAPI sticky sessions
        extra_headers = {}
        if session_id:
            extra_headers["X-Session-Id"] = session_id

        # Retry Loop
        for attempt in range(self.max_retries + 1):
            try:
                # Use with_raw_response to capture headers like X-Routed-Via
                raw_response = await self.client.chat.completions.with_raw_response.create(
                    model=self.model,
                    messages=openai_messages,
                    tools=openai_tools,
                    tool_choice="auto" if openai_tools else None,
                    extra_headers=extra_headers or None,
                )

                response = raw_response.parse()
                latency_ms = int((time.time() - start_time) * 1000)
                choice = response.choices[0]
                msg = choice.message
                reported_model = getattr(response, "model", None)
                request_id = getattr(response, "id", None)

                # Capture X-Routed-Via for observability
                routed_via = raw_response.headers.get("X-Routed-Via")
                if routed_via:
                    logger.info(
                        "FreeLLM routed via model: %s (session_id=%s)",
                        routed_via,
                        session_id[:8] if session_id else "none",
                    )

                usage_data = response.usage
                input_tokens = usage_data.prompt_tokens if usage_data else 0
                output_tokens = usage_data.completion_tokens if usage_data else 0
                response_metadata = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": latency_ms,
                    "reported_model": (
                        reported_model if isinstance(reported_model, str) else None
                    ),
                    "requested_model": self.model,
                    "request_id": request_id if isinstance(request_id, str) else None,
                    "routed_via": routed_via,
                }

                # Handle Tool Calls
                if msg.tool_calls:
                    tool_calls = []
                    for tc in msg.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        tool_calls.append({
                            "name": tc.function.name,
                            "arguments": args,
                            "id": tc.id,
                        })

                    return LLMResponse(
                        content=msg.content,
                        tool_calls=tool_calls,
                        finish_reason="tool_calls",
                        usage=response_metadata,
                    )

                # Normal text response
                return LLMResponse(
                    content=msg.content or "",
                    finish_reason=choice.finish_reason,
                    usage=response_metadata,
                )

            except (RateLimitError, APITimeoutError, APIError) as e:
                last_exception = e
                error_code = getattr(e, 'status_code', None)

                # Only retry on 429 (Rate Limit) or 5xx (Server Error) or Timeout
                should_retry = (
                    isinstance(e, RateLimitError) or
                    isinstance(e, APITimeoutError) or
                    error_code in {408, 425, 429} or
                    (isinstance(error_code, int) and error_code >= 500)
                )

                if should_retry and attempt < self.max_retries:
                    wait_time = (attempt + 1) * 2  # Simple linear backoff: 2s, 4s, 6s
                    logger.warning(
                        "FreeLLM request failed; retrying "
                        "(attempt=%s/%s, error_type=%s)",
                        attempt + 1,
                        self.max_retries,
                        type(e).__name__,
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    # Non-retryable error or max retries reached
                    break
            except Exception as e:
                last_exception = e
                break # Unexpected error, don't retry blindly

        # If we reach here, all attempts failed
        logger.error(
            "FreeLLM request failed after %s attempts (error_type=%s, "
            "status_code=%s, request_id=%s)",
            self.max_retries + 1,
            type(last_exception).__name__ if last_exception else "unknown",
            getattr(last_exception, "status_code", None),
            getattr(last_exception, "request_id", None) or "unavailable",
        )

        return LLMResponse(
            content="",
            finish_reason="error",
            usage={
                "latency_ms": int((time.time() - start_time) * 1000),
                "requested_model": self.model,
                "request_id": getattr(last_exception, "request_id", None),
                "error_type": (
                    type(last_exception).__name__ if last_exception else "unknown"
                ),
                "status_code": getattr(last_exception, "status_code", None),
            },
        )