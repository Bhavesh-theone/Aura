import pytest

from aura.agents.llm.ollama_check import list_models, ollama_available
from aura.config import get_settings


def test_ollama_is_running_with_the_expected_model():
    base = get_settings().ollama_base_url
    if not ollama_available(base):
        pytest.skip("Ollama is not running - start it with `ollama serve`")
    assert any("qwen3.5:4b" in m for m in list_models(base)), \
        "Run: ollama pull qwen3.5:4b"
