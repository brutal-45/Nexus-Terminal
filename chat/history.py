"""Conversation history manager for Nexus.

Manages message history with token tracking, persistence, and export capabilities.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class ChatHistory:
    """Manages conversation history with token estimation, persistence, and search.

    Each message is a dict with at least 'role' and 'content' keys.
    Optional keys: 'tool_calls' (list), 'tool_call_id' (str), 'name' (str).

    Attributes:
        max_turns: Maximum number of conversation turns to keep.
        context_window: Maximum token budget for the full history.
        history_file: Optional path to a JSON file for persistence.
    """

    # Approximate characters per token across most LLM tokenizers
    CHARS_PER_TOKEN: int = 4

    def __init__(
        self,
        max_turns: int = 50,
        context_window: int = 8192,
        history_file: Optional[str] = None,
    ) -> None:
        self.max_turns = max_turns
        self.context_window = context_window
        self.history_file: Optional[str] = (
            os.path.expanduser(history_file) if history_file else None
        )
        self._messages: List[Dict[str, Any]] = []
        self._total_tokens: int = 0
        self._created_at: str = datetime.now().isoformat()
        self._updated_at: str = self._created_at

        # Try to load existing history
        if self.history_file:
            self.load()

    # ------------------------------------------------------------------
    # Core message operations
    # ------------------------------------------------------------------

    def add(
        self,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a message to the history.

        Args:
            role: One of 'system', 'user', 'assistant', 'tool'.
            content: The message text.
            tool_calls: Optional list of tool call dicts (for assistant messages).
            tool_call_id: Required for 'tool' role messages.
            name: Optional name field (often used with tool messages).

        Returns:
            The message dict that was added.
        """
        if role not in ("system", "user", "assistant", "tool"):
            raise ValueError(
                f"Invalid role '{role}'. Must be one of: system, user, assistant, tool"
            )

        message: Dict[str, Any] = {"role": role, "content": content}

        if tool_calls is not None:
            message["tool_calls"] = tool_calls
        if tool_call_id is not None:
            message["tool_call_id"] = tool_call_id
        if name is not None:
            message["name"] = name

        # Estimate tokens for this message
        message_tokens = self.estimate_tokens(self._message_to_text(message))
        self._total_tokens += message_tokens

        self._messages.append(message)
        self._updated_at = datetime.now().isoformat()

        # Enforce max_turns — trim oldest non-system messages
        self._enforce_max_turns()

        # Auto-save if persistence is enabled
        if self.history_file:
            self.save()

        return message

    def get_messages(self) -> List[Dict[str, Any]]:
        """Return all messages as a list of dicts."""
        return list(self._messages)

    def get_recent(self, n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return the last *n* messages (or all if *n* is None)."""
        if n is None or n >= len(self._messages):
            return list(self._messages)
        return list(self._messages[-n:])

    def clear(self) -> None:
        """Remove all messages and reset token counter."""
        self._messages.clear()
        self._total_tokens = 0
        self._updated_at = datetime.now().isoformat()
        if self.history_file:
            self.save()

    # ------------------------------------------------------------------
    # Length helpers
    # ------------------------------------------------------------------

    def len(self) -> int:
        """Return the number of messages in history."""
        return len(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> bool:
        """Save history to a JSON file.

        Returns:
            True if save succeeded, False otherwise.
        """
        if not self.history_file:
            return False

        try:
            path = Path(self.history_file)
            path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "created_at": self._created_at,
                "updated_at": self._updated_at,
                "total_tokens": self._total_tokens,
                "messages": self._messages,
            }

            # Write atomically via temp file
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            tmp_path.replace(path)
            return True

        except (OSError, json.JSONDecodeError, TypeError) as exc:
            print(f"[ChatHistory] Failed to save history: {exc}")
            return False

    def load(self) -> bool:
        """Load history from a JSON file.

        Returns:
            True if load succeeded, False otherwise.
        """
        if not self.history_file:
            return False

        try:
            path = Path(self.history_file)
            if not path.exists():
                return False

            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)

            self._messages = data.get("messages", [])
            self._created_at = data.get("created_at", self._created_at)
            self._updated_at = data.get("updated_at", self._updated_at)
            self._total_tokens = data.get("total_tokens", 0)

            # Recalculate tokens if missing / zero
            if self._total_tokens == 0 and self._messages:
                self._total_tokens = sum(
                    self.estimate_tokens(self._message_to_text(m))
                    for m in self._messages
                )
            return True

        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"[ChatHistory] Failed to load history: {exc}")
            return False

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        """Rough token count — approximately 4 characters per token.

        Args:
            text: The text to estimate tokens for.

        Returns:
            Estimated number of tokens.
        """
        if not text:
            return 0
        return max(1, len(text) // cls.CHARS_PER_TOKEN)

    def trim_to_fit(self, max_tokens: int) -> int:
        """Remove oldest messages (except system messages) to fit within *max_tokens*.

        Returns:
            The number of messages removed.
        """
        removed = 0

        while self._total_tokens > max_tokens and len(self._messages) > 1:
            # Find the oldest non-system message
            for idx, msg in enumerate(self._messages):
                if msg["role"] != "system":
                    msg_tokens = self.estimate_tokens(self._message_to_text(msg))
                    self._total_tokens -= msg_tokens
                    self._messages.pop(idx)
                    removed += 1
                    break
            else:
                break  # Only system messages remain

        if removed > 0:
            self._updated_at = datetime.now().isoformat()
            if self.history_file:
                self.save()

        return removed

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search history for a keyword (case-insensitive substring match).

        Args:
            query: The search string.

        Returns:
            List of matching message dicts, each annotated with a '_index' key.
        """
        if not query:
            return []

        query_lower = query.lower()
        results: List[Dict[str, Any]] = []

        for idx, msg in enumerate(self._messages):
            content = msg.get("content", "")
            if isinstance(content, str) and query_lower in content.lower():
                match = dict(msg)
                match["_index"] = idx
                results.append(match)

        return results

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export(self, fmt: str = "json") -> str:
        """Export the conversation history.

        Args:
            fmt: One of 'json', 'text', or 'markdown'.

        Returns:
            The exported string.

        Raises:
            ValueError: If the format is not recognised.
        """
        if fmt == "json":
            return json.dumps(
                {
                    "created_at": self._created_at,
                    "updated_at": self._updated_at,
                    "total_tokens": self._total_tokens,
                    "messages": self._messages,
                },
                indent=2,
                ensure_ascii=False,
            )

        if fmt == "text":
            lines: List[str] = []
            for msg in self._messages:
                role = msg["role"].upper()
                content = self._message_to_text(msg)
                lines.append(f"[{role}]\n{content}")
            return "\n\n".join(lines)

        if fmt == "markdown":
            lines = [
                "# Conversation History",
                f"**Created:** {self._created_at}",
                f"**Updated:** {self._updated_at}",
                f"**Messages:** {len(self._messages)}",
                f"**Estimated tokens:** {self._total_tokens}",
                "",
            ]
            role_labels = {
                "system": "**System**",
                "user": "**User**",
                "assistant": "**Assistant**",
                "tool": "**Tool**",
            }
            for msg in self._messages:
                label = role_labels.get(msg["role"], msg["role"].title())
                content = self._message_to_text(msg)
                lines.append(f"## {label}\n\n{content}\n")
            return "\n".join(lines)

        raise ValueError(f"Unsupported export format: '{fmt}'. Use json, text, or markdown.")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Return a short summary of the conversation.

        Includes turn count, estimated tokens, and brief topic extraction.
        """
        n_user = sum(1 for m in self._messages if m["role"] == "user")
        n_assistant = sum(1 for m in self._messages if m["role"] == "assistant")
        n_tool = sum(1 for m in self._messages if m["role"] == "tool")
        n_system = sum(1 for m in self._messages if m["role"] == "system")

        # Extract potential topic keywords from user messages
        user_texts = [
            m.get("content", "")
            for m in self._messages
            if m["role"] == "user" and isinstance(m.get("content"), str)
        ]

        # Simple keyword extraction: find frequent words (>3 chars, not stop words)
        stop_words = {
            "the", "and", "for", "are", "but", "not", "you", "all", "can",
            "had", "her", "was", "one", "our", "out", "has", "have", "this",
            "that", "with", "from", "they", "been", "will", "each", "make",
            "like", "just", "over", "such", "take", "than", "them", "very",
            "some", "could", "into", "also", "what", "how", "does", "did",
            "please", "would", "should", "could", "do", "is", "it", "to",
            "in", "of", "a", "an", "me", "my", "i", "we", "so", "if",
        }
        word_freq: Dict[str, int] = {}
        for text in user_texts:
            words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", text.lower())
            for word in words:
                if word not in stop_words:
                    word_freq[word] = word_freq.get(word, 0) + 1

        top_keywords = sorted(word_freq, key=word_freq.get, reverse=True)[:5]

        topic_str = ", ".join(top_keywords) if top_keywords else "no topics yet"

        return (
            f"Conversation summary: {n_user} user turns, {n_assistant} assistant "
            f"responses, {n_tool} tool calls, {n_system} system messages. "
            f"Estimated tokens: {self._total_tokens}. "
            f"Topics: {topic_str}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _message_to_text(msg: Dict[str, Any]) -> str:
        """Serialise a message dict to a plain-text representation for token estimation."""
        parts: List[str] = [msg.get("role", "unknown")]

        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            # Multi-part content (e.g. image + text)
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif item.get("type") == "image_url":
                        parts.append("[image]")
        else:
            parts.append(str(content))

        if msg.get("tool_calls"):
            parts.append(json.dumps(msg["tool_calls"]))

        return " ".join(parts)

    def _enforce_max_turns(self) -> None:
        """Remove oldest non-system messages to stay within *max_turns*."""
        # Count non-system messages
        non_system = [m for m in self._messages if m["role"] != "system"]
        while len(non_system) > self.max_turns:
            # Remove the oldest non-system message
            for idx, msg in enumerate(self._messages):
                if msg["role"] != "system":
                    msg_tokens = self.estimate_tokens(self._message_to_text(msg))
                    self._total_tokens -= msg_tokens
                    self._messages.pop(idx)
                    break
            non_system = [m for m in self._messages if m["role"] != "system"]
