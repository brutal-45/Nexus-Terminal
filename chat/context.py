"""Context window manager for Nexus.

Builds the message payload sent to the LLM, ensuring it fits within
the model's context window by prioritising the system prompt and
recent messages.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# Characters per token — kept in sync with ChatHistory
CHARS_PER_TOKEN: int = 4


class ContextManager:
    """Manages the context window for LLM API calls.

    Responsibilities:
    - Build the message list that fits within the context window.
    - Ensure the system prompt is always included.
    - Detect when history summarisation is needed.
    - Format tool results to a bounded length.
    """

    def __init__(self, context_window: int = 8192) -> None:
        self.context_window = context_window

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def build_context(
        self,
        system_prompt: str,
        history: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Build the message list that fits within the context window.

        The system prompt is always included (if it fits).  Recent messages
        are added newest-first until the token budget is exhausted.

        Args:
            system_prompt: The system prompt text.
            history: Full conversation history (list of message dicts).
            max_tokens: Override for the context window size.

        Returns:
            A list of message dicts ready for the LLM API.
        """
        budget = max_tokens if max_tokens is not None else self.context_window

        # Always start with the system prompt
        system_msg: Dict[str, Any] = {"role": "system", "content": system_prompt}
        system_tokens = self.estimate_message_tokens(system_msg)

        if system_tokens > budget:
            # System prompt alone exceeds budget — truncate it
            overflow = system_tokens - budget + 1  # leave room for at least 1 token
            truncate_chars = overflow * CHARS_PER_TOKEN
            system_msg["content"] = system_prompt[truncate_chars:]
            remaining = 0
        else:
            remaining = budget - system_tokens

        messages: List[Dict[str, Any]] = [system_msg]

        # Add messages from history, newest first, skipping existing system msgs
        filtered = [m for m in history if m.get("role") != "system"]

        for msg in reversed(filtered):
            msg_tokens = self.estimate_message_tokens(msg)
            if msg_tokens > remaining:
                # Try to fit a truncated version of user/assistant messages
                if msg.get("role") in ("user", "assistant") and msg_tokens > 0:
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        available_chars = max(1, remaining * CHARS_PER_TOKEN)
                        truncated = content[:available_chars]
                        trimmed_msg: Dict[str, Any] = {"role": msg["role"], "content": truncated + "… [truncated]"}
                        trimmed_tokens = self.estimate_message_tokens(trimmed_msg)
                        if trimmed_tokens <= remaining:
                            messages.append(trimmed_msg)
                            remaining -= trimmed_tokens
                break

            messages.append(msg)
            remaining -= msg_tokens

        # Reverse so messages are in chronological order
        messages.reverse()
        return messages

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_message_tokens(message: Dict[str, Any]) -> int:
        """Estimate the token count for a single message dict.

        Handles string content, list content (multi-part), and tool_calls.
        """
        total_chars = 0

        # Role overhead (~2 tokens)
        total_chars += 8

        content = message.get("content")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    part_type = part.get("type", "")
                    if part_type == "text":
                        total_chars += len(part.get("text", ""))
                    elif part_type == "image_url":
                        # Image tokens are highly variable; use a rough estimate
                        total_chars += 85 * CHARS_PER_TOKEN  # ~85 tokens per small image
                    else:
                        total_chars += len(json.dumps(part))
                elif isinstance(part, str):
                    total_chars += len(part)
        elif content is not None:
            total_chars += len(str(content))

        # Account for tool_calls
        tool_calls = message.get("tool_calls")
        if tool_calls:
            total_chars += len(json.dumps(tool_calls))

        # tool_call_id
        tool_call_id = message.get("tool_call_id")
        if tool_call_id:
            total_chars += len(tool_call_id) + 10

        # name field
        name = message.get("name")
        if name:
            total_chars += len(name) + 5

        return max(1, total_chars // CHARS_PER_TOKEN)

    @classmethod
    def calculate_remaining(
        cls, messages: List[Dict[str, Any]], max_tokens: int
    ) -> int:
        """Calculate how many tokens are left in the budget.

        Args:
            messages: Current message list.
            max_tokens: Total token budget.

        Returns:
            Remaining tokens (may be negative if over budget).
        """
        used = sum(cls.estimate_message_tokens(m) for m in messages)
        return max_tokens - used

    # ------------------------------------------------------------------
    # Summarisation helpers
    # ------------------------------------------------------------------

    @classmethod
    def should_summarize(
        cls,
        history: List[Dict[str, Any]],
        threshold_ratio: float = 0.8,
        max_tokens: Optional[int] = None,
    ) -> bool:
        """Determine if the history is large enough to warrant summarisation.

        Returns True when the history uses more than *threshold_ratio* of
        the context window.

        Args:
            history: Full conversation history.
            threshold_ratio: Fraction of context_window that triggers summarisation.
            max_tokens: Override for the context window size.

        Returns:
            Whether summarisation is recommended.
        """
        if not history:
            return False

        total = sum(cls.estimate_message_tokens(m) for m in history)
        budget = max_tokens if max_tokens is not None else 8192
        return total > budget * threshold_ratio

    @classmethod
    def summarize_history(
        cls,
        history: List[Dict[str, Any]],
        keep_first: int = 1,
        keep_last: int = 6,
    ) -> List[Dict[str, Any]]:
        """Create a compressed summary of older messages.

        Strategy (simple extractive summarisation):
        - Keep the first *keep_first* messages (usually the system prompt area).
        - Keep the last *keep_last* messages (recent context).
        - Summarise everything in between into a single system-level message.

        Args:
            history: Full conversation history.
            keep_first: Number of leading messages to preserve verbatim.
            keep_last: Number of trailing messages to preserve verbatim.

        Returns:
            A new, shorter message list.
        """
        if len(history) <= keep_first + keep_last:
            return list(history)

        # Separate system messages from the beginning (keep them)
        system_msgs: List[Dict[str, Any]] = []
        non_system_start: int = 0
        for i, msg in enumerate(history):
            if msg.get("role") == "system":
                system_msgs.append(msg)
                non_system_start = i + 1
            else:
                break

        # Body messages (the ones we summarise)
        body = history[non_system_start : len(history) - keep_last]
        tail = history[len(history) - keep_last :]

        # Build a summary of the body
        summary_parts: List[str] = []
        user_count = 0
        assistant_count = 0
        tool_count = 0
        topics: List[str] = []

        for msg in body:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                if role == "user":
                    user_count += 1
                    # Extract a short excerpt
                    excerpt = content.strip().split("\n")[0][:120]
                    topics.append(f"User asked about: {excerpt}")
                elif role == "assistant":
                    assistant_count += 1
                elif role == "tool":
                    tool_count += 1

        summary_lines = [
            "[Previous conversation summary]",
            f"Earlier in the conversation there were {user_count} user messages, "
            f"{assistant_count} assistant responses, and {tool_count} tool calls.",
        ]
        if topics:
            # Show up to 8 topic excerpts
            for topic in topics[:8]:
                summary_lines.append(f"- {topic}")
            if len(topics) > 8:
                summary_lines.append(f"- … and {len(topics) - 8} more exchanges")

        summary_text = "\n".join(summary_lines)
        summary_msg: Dict[str, Any] = {
            "role": "system",
            "content": summary_text,
        }

        # Reassemble: system msgs + summary + tail
        result = list(system_msgs) + [summary_msg] + list(tail)
        return result

    # ------------------------------------------------------------------
    # Tool result formatting
    # ------------------------------------------------------------------

    @classmethod
    def format_tool_result(cls, result: Any, max_chars: int = 4000) -> str:
        """Format a tool result to fit within a character budget.

        Args:
            result: The raw tool result (any type).
            max_chars: Maximum characters to return.

        Returns:
            A string representation of the result, truncated if necessary.
        """
        text: str

        if result is None:
            text = "(no output)"
        elif isinstance(result, str):
            text = result
        elif isinstance(result, (dict, list)):
            text = json.dumps(result, indent=2, ensure_ascii=False)
        else:
            text = str(result)

        if len(text) <= max_chars:
            return text

        # Truncate with an indicator
        keep = max_chars - 80  # leave room for the truncation notice
        head = text[:keep]
        tail = text[-40:] if len(text) > keep + 40 else ""
        truncated = f"{head}\n\n… [truncated: {len(text)} total chars, showing first {keep}]"
        if tail:
            truncated += f"\n… [last 40 chars: {tail}]"
        return truncated
