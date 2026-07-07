"""Shared mock helpers and test utilities for OpenAI SDK migration tests."""
import importlib.util
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def load_agent_module(service_dir: str, module_file: str = "agent.py"):
    """Load a module from a hyphenated service directory by file path."""
    module_path = os.path.join(REPO_ROOT, "services", service_dir, module_file)
    safe_name = f"agent_{service_dir.replace('-', '_')}"
    if safe_name in sys.modules:
        return sys.modules[safe_name]
    spec = importlib.util.spec_from_file_location(safe_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[safe_name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class MockFunction:
    name: Optional[str] = None
    arguments: Optional[str] = None


@dataclass
class MockToolCall:
    function: MockFunction = field(default_factory=MockFunction)


@dataclass
class MockDelta:
    content: Optional[str] = None
    tool_calls: Optional[list] = None


@dataclass
class MockChoice:
    index: int = 0
    delta: MockDelta = field(default_factory=MockDelta)
    finish_reason: Optional[str] = None


@dataclass
class MockChunk:
    id: str = "test-chunk"
    model: str = "test-model"
    choices: list = field(default_factory=list)


@dataclass
class MockMessage:
    content: Optional[str] = None
    role: str = "assistant"


@dataclass
class MockCompletionChoice:
    index: int = 0
    message: MockMessage = field(default_factory=MockMessage)
    finish_reason: str = "stop"


@dataclass
class MockCompletion:
    id: str = "test-completion"
    model: str = "test-model"
    choices: list = field(default_factory=list)


def make_content_chunks(texts: list[str]) -> list[MockChunk]:
    """Create mock streaming chunks from a list of text fragments."""
    chunks = []
    for text in texts:
        chunk = MockChunk(
            choices=[MockChoice(delta=MockDelta(content=text))]
        )
        chunks.append(chunk)
    chunks.append(MockChunk(choices=[MockChoice(delta=MockDelta(), finish_reason="stop")]))
    return chunks


def make_tool_call_chunks(tool_name: str, arg_fragments: list[str]) -> list[MockChunk]:
    """Create mock streaming chunks for a tool call response."""
    chunks = []
    chunks.append(MockChunk(
        choices=[MockChoice(delta=MockDelta(
            tool_calls=[MockToolCall(function=MockFunction(name=tool_name, arguments=arg_fragments[0]))]
        ))]
    ))
    for frag in arg_fragments[1:]:
        chunks.append(MockChunk(
            choices=[MockChoice(delta=MockDelta(
                tool_calls=[MockToolCall(function=MockFunction(name=None, arguments=frag))]
            ))]
        ))
    chunks.append(MockChunk(choices=[MockChoice(delta=MockDelta(), finish_reason="stop")]))
    return chunks


def make_empty_stream_chunks() -> list[MockChunk]:
    """Create a stream with no content or tool calls."""
    return [MockChunk(choices=[MockChoice(delta=MockDelta(), finish_reason="stop")])]


def make_completion(content: str) -> MockCompletion:
    """Create a mock non-streaming completion response."""
    return MockCompletion(
        choices=[MockCompletionChoice(message=MockMessage(content=content))]
    )


class MockAsyncStream:
    """Async iterator that yields mock chunks, mimicking AsyncOpenAI stream."""
    def __init__(self, chunks):
        self._chunks = chunks
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


SAMPLE_THEME_CONFIG = {
    "primary_color": "#0F172A",
    "secondary_color": "#1E293B",
    "accent_color": "#D4AF37",
    "text_color": "#F8FAFC",
    "button_color": "#D4AF37",
    "button_text": "#0F172A",
}
