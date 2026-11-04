"""Fail-closed local Ollama JSON client for research synthesis drafts.

This transport does not validate PIT evidence, persist syntheses, or attest model execution.
"""
from __future__ import annotations

import json
import math
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class OllamaResearchSynthesisError(RuntimeError):
    """Local inference failed or returned an invalid response."""


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OllamaResearchSynthesisError("Ollama no permite redirecciones HTTP.")


class OllamaResearchSynthesisClient:
    def __init__(
        self,
        *,
        endpoint: str = "http://127.0.0.1:11434",
        model: str = "qwen3:1.7b",
        timeout_seconds: int = 240,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port != 11434
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Ollama debe utilizar exclusivamente http://127.0.0.1:11434.")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("El modelo Ollama es obligatorio.")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 240:
            raise ValueError("timeout_seconds debe estar entre 1 y 240.")
        self._endpoint = "http://127.0.0.1:11434"
        self._model = model
        self._timeout = timeout_seconds

    def generate_json(self, *, prompt: str, required_fields: tuple[str, ...]) -> dict[str, Any]:
        """Generate an untrusted JSON object; domain validation must follow."""
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
            raise ValueError("El prompt debe ser texto no vacío de hasta 20000 caracteres.")
        if (
            not isinstance(required_fields, tuple)
            or not required_fields
            or any(not isinstance(field, str) or not field for field in required_fields)
            or len(set(required_fields)) != len(required_fields)
        ):
            raise ValueError("required_fields debe contener nombres únicos.")
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 700},
        }
        request = Request(
            self._endpoint + "/api/generate",
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with build_opener(ProxyHandler({}), _RejectRedirects()).open(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise OllamaResearchSynthesisError("Ollama devolvió un estado HTTP inesperado.")
                raw = response.read(131073)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise OllamaResearchSynthesisError("No se pudo completar la inferencia local.") from exc
        if len(raw) > 131072:
            raise OllamaResearchSynthesisError("Respuesta de Ollama demasiado grande.")
        try:
            envelope = json.loads(raw, parse_constant=self._reject_constant, object_pairs_hook=self._unique_object)
            if not isinstance(envelope, dict) or envelope.get("model") != self._model or envelope.get("done") is not True:
                raise ValueError("Sobre de inferencia incompleto o modelo distinto.")
            output = envelope["response"]
            if not isinstance(output, str) or not output.strip():
                raise ValueError("Salida de inferencia vacía.")
            result = json.loads(output, parse_constant=self._reject_constant, object_pairs_hook=self._unique_object)
            if not isinstance(result, dict) or any(field not in result for field in required_fields):
                raise ValueError("JSON de inferencia sin los campos obligatorios.")
            self._check_finite(result)
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            raise OllamaResearchSynthesisError("Ollama devolvió JSON inválido o incompleto.") from exc
        return result

    @staticmethod
    def _reject_constant(value: str) -> None:
        raise ValueError(f"Constante JSON no permitida: {value}")

    @staticmethod
    def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Claves JSON duplicadas.")
            result[key] = value
        return result

    @classmethod
    def _check_finite(cls, value: Any) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Número no finito.")
        if isinstance(value, dict):
            for item in value.values():
                cls._check_finite(item)
        elif isinstance(value, list):
            for item in value:
                cls._check_finite(item)
