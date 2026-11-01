"""Contract tests for the local-only Ollama research transport."""
import io
import json
from unittest.mock import patch

import pytest

from app.services.ollama_research_synthesis_client import (
    OllamaResearchSynthesisClient,
    OllamaResearchSynthesisError,
)


class FakeResponse:
    status = 200

    def __init__(self, body):
        self._buffer = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit):
        return self._buffer.read(limit)


def response(output='{"summary":"Validado","uncertainties":["sin corroboración"]}', *, model="qwen3:1.7b", done=True):
    return json.dumps({"model": model, "done": done, "response": output}).encode()


def test_local_json_success_and_transport_options():
    client = OllamaResearchSynthesisClient()
    with patch("app.services.ollama_research_synthesis_client.urlopen", return_value=FakeResponse(response())) as mocked:
        result = client.generate_json(prompt="Prueba", required_fields=("summary", "uncertainties"))
    assert result["summary"] == "Validado"
    request = mocked.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:11434/api/generate"
    body = json.loads(request.data)
    assert body["stream"] is False and body["think"] is False
    assert body["options"]["temperature"] == 0
    assert mocked.call_args.kwargs["timeout"] == 240


@pytest.mark.parametrize("endpoint", [
    "http://localhost:11434", "https://127.0.0.1:11434",
    "http://127.0.0.1:11435", "http://evil.example:11434",
    "http://127.0.0.1:11434/redirect", "http://127.0.0.1:11434?x=1",
    "http://user:pass@127.0.0.1:11434",
])
def test_noncanonical_endpoints_rejected(endpoint):
    with pytest.raises(ValueError):
        OllamaResearchSynthesisClient(endpoint=endpoint)


@pytest.mark.parametrize("output", [
    "not json", "[]", '{"summary":"x"}',
    '{"summary":"x","summary":"y","uncertainties":[]}',
    '{"summary":"x","uncertainties":[],"score":NaN}',
    '{"summary":"x","uncertainties":[],"score":1e999}',
])
def test_invalid_model_outputs_fail_closed(output):
    client = OllamaResearchSynthesisClient()
    with patch("app.services.ollama_research_synthesis_client.urlopen", return_value=FakeResponse(response(output))):
        with pytest.raises(OllamaResearchSynthesisError):
            client.generate_json(prompt="Prueba", required_fields=("summary", "uncertainties"))


@pytest.mark.parametrize("body", [
    response(model="other"), response(done=False),
    b'{"model":"qwen3:1.7b","done":true,"response":"{}","response":"{}"}',
])
def test_invalid_envelopes_fail_closed(body):
    client = OllamaResearchSynthesisClient()
    with patch("app.services.ollama_research_synthesis_client.urlopen", return_value=FakeResponse(body)):
        with pytest.raises(OllamaResearchSynthesisError):
            client.generate_json(prompt="Prueba", required_fields=("summary",))


def test_connection_failure_fails_closed():
    from urllib.error import URLError
    client = OllamaResearchSynthesisClient()
    with patch("app.services.ollama_research_synthesis_client.urlopen", side_effect=URLError("offline")):
        with pytest.raises(OllamaResearchSynthesisError):
            client.generate_json(prompt="Prueba", required_fields=("summary",))


def test_rejects_invalid_prompts_and_fields():
    client = OllamaResearchSynthesisClient()
    with pytest.raises(ValueError):
        client.generate_json(prompt="", required_fields=("summary",))
    with pytest.raises(ValueError):
        client.generate_json(prompt="Prueba", required_fields=("summary", "summary"))
