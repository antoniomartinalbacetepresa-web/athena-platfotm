"""Data-only research inference. Deployment supplies a pinned, reviewed artifact.

No default coefficients, training, provider calls, promotion or skill claims.
Feature paths address exact materialized content, never executable expressions.
"""
from __future__ import annotations

import json
import math


class ResearchLinearTotalReturnRunner:
    def predict(self, *, model_bytes: bytes, inputs: list[dict]) -> dict:
        if not isinstance(model_bytes, bytes) or not 0 < len(model_bytes) <= 10_000_000:
            raise ValueError("Invalid model bytes")
        model = json.loads(model_bytes, object_pairs_hook=self._unique)
        if not isinstance(model, dict) or set(model) != {
            "runnerVersion", "name", "version", "metric", "horizonSeconds", "intercept", "features"
        }:
            raise ValueError("Explicit linear artifact required")
        if model["runnerVersion"] != "research-linear-total-return-v1" or model["metric"] != "total_return":
            raise ValueError("Unsupported runner/metric")
        if any(not isinstance(model[k], str) or not model[k].strip() for k in ("name", "version")):
            raise ValueError("Explicit model identity required")
        horizon = model["horizonSeconds"]
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
            raise ValueError("Invalid horizon")
        if not isinstance(inputs, list) or not 1 <= len(inputs) <= 200:
            raise ValueError("Explicit materialized inputs required")
        by_ref = {}
        for item in inputs:
            ref = item["evidence"]["sourceRef"]
            if not isinstance(ref, str) or not ref or ref in by_ref:
                raise ValueError("Invalid or duplicated input reference")
            by_ref[ref] = item["content"]
        features = model["features"]
        if not isinstance(features, list) or not 1 <= len(features) <= 200:
            raise ValueError("Explicit features required")
        terms = [self._number(model["intercept"])]
        used, identities = set(), set()
        for feature in features:
            if not isinstance(feature, dict) or set(feature) != {"sourceRef", "path", "offset", "scale", "coefficient"}:
                raise ValueError("Explicit feature contract required")
            ref, path = feature["sourceRef"], feature["path"]
            if not isinstance(ref, str) or ref not in by_ref:
                raise ValueError("Missing feature input")
            if not isinstance(path, list) or not 1 <= len(path) <= 8 or any(not isinstance(k, str) or not k for k in path):
                raise ValueError("Feature path must contain literal object keys")
            identity = (ref, tuple(path))
            if identity in identities:
                raise ValueError("Duplicated feature")
            identities.add(identity)
            used.add(ref)
            value = by_ref[ref]
            for key in path:
                if not isinstance(value, dict) or key not in value:
                    raise ValueError("Missing numeric feature path")
                value = value[key]
            offset, scale = self._number(feature["offset"]), self._number(feature["scale"])
            if scale <= 0:
                raise ValueError("Feature scale must be positive")
            term = (self._number(value) - offset) / scale * self._number(feature["coefficient"])
            terms.append(self._number(term))
        if used != set(by_ref):
            raise ValueError("Artifact must explicitly bind every materialized input")
        try:
            result = math.fsum(terms)
        except OverflowError as exc:
            raise ValueError("Non-finite inference") from exc
        return {"metric": "total_return", "expectedValue": self._number(result)}

    @staticmethod
    def _number(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Finite numeric value required")
        try:
            result = float(value)
        except OverflowError as exc:
            raise ValueError("Finite numeric value required") from exc
        if not math.isfinite(result):
            raise ValueError("Finite numeric value required")
        return result

    @staticmethod
    def _unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicated JSON key")
            result[key] = value
        return result
