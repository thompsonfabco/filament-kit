"""Fake Anthropic client for tests: records `client.beta.messages.create(**kw)` calls and replies like the SDK."""
from __future__ import annotations

import json
from types import SimpleNamespace


class _Messages:
    def __init__(self, owner: "FakeClaude"):
        self._owner = owner

    def create(self, **kw):
        o = self._owner
        o.calls.append(kw)
        if o.raises is not None:
            raise o.raises
        text = o.reply if isinstance(o.reply, str) else json.dumps(o.reply)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            stop_reason=o.stop_reason,
            model=o.model,
            usage=SimpleNamespace(input_tokens=o.input_tokens, output_tokens=o.output_tokens,
                                  cache_read_input_tokens=o.cache_read, cache_creation_input_tokens=o.cache_create),
        )


class FakeClaude:
    """`reply` is a dict (JSON-encoded) or a string; set `raises` to an exception to make create() raise it."""

    def __init__(self, reply=None, *, raises: BaseException | None = None, stop_reason: str = "end_turn",
                 model: str = "claude-opus-5-5", input_tokens: int = 1200, output_tokens: int = 300,
                 cache_read: int = 0, cache_create: int = 500):
        self.reply, self.raises, self.stop_reason, self.model = reply, raises, stop_reason, model
        self.input_tokens, self.output_tokens = input_tokens, output_tokens
        self.cache_read, self.cache_create = cache_read, cache_create
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=_Messages(self))
