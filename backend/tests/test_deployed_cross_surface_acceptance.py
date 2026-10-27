"""Contract regressions for the deployment-only acceptance probe."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "deployed_cross_surface_acceptance.py"
spec = importlib.util.spec_from_file_location("deployed_cross_surface_acceptance", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)

HASH = "a" * 64
NEWS_HASH = "b" * 64
INVESTORS_HASH = "c" * 64


def owners():
    return (module.TestOwner("a@test.invalid", "not-a-real-secret", 11, "EUR"),
            module.TestOwner("b@test.invalid", "not-a-real-secret", 22, "USD"))


def transport(*, mismatched_news=False, cross_owner=False, revoked_accepted=False,
              missing_athena=False, shared_extra_position=False,
              personalization_leak=False, personalization_escalation=False,
              fallback_market=False, empty_market=False):
    revoked = set()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "service": "athena-tyche-backend"})
        if path == "/api/v1/market/universe/status":
            return httpx.Response(200, json={"data": {
                "activeCount": 0 if empty_market else 2,
                "usingFallback": fallback_market,
            }})
        if path.endswith("/athena-synthesis/latest"):
            if missing_athena:
                return httpx.Response(404, json={"detail": "not ready"})
            return httpx.Response(200, json={"data": {
                "artifactBindingVerified": True, "cycleHash": HASH,
                "synthesis": {"inputFingerprint": HASH},
                "provenance": {"inputFingerprint": HASH, "news": {"artifactHash": NEWS_HASH},
                               "investors": {"artifactHash": INVESTORS_HASH}},
                "selection": {"presentationOnly": True, "recommendationInfluence": False,
                              "automaticTrading": False}}})
        if path.endswith("/news-synthesis/latest"):
            return httpx.Response(200, json={"data": {
                "cycleBindingVerified": True, "cycleHash": "f" * 64 if mismatched_news else HASH,
                "presentationOnly": True, "recommendationInfluence": False,
                "automaticTrading": False, "persistence": {"synthesisHash": NEWS_HASH}}})
        if path.endswith(f"/research-cycle/{HASH}/investors-synthesis"):
            return httpx.Response(200, json={"data": {
                "cycleBindingVerified": True, "cycleHash": HASH, "recommendationInfluence": False,
                "automaticTrading": False, "persistence": {"synthesisHash": INVESTORS_HASH}}})
        if path == "/api/v1/auth/token":
            return httpx.Response(200, json={"access_token": "ownerA-token-long-enough" if b"a%40test.invalid" in request.content else "ownerB-token-long-enough", "token_type": "bearer"})
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if path == "/api/v1/auth/logout":
            revoked.add(token)
            return httpx.Response(204)
        if token in revoked and not revoked_accepted:
            return httpx.Response(401, json={"detail": "revoked"})
        if token not in {"ownerA-token-long-enough", "ownerB-token-long-enough"}:
            return httpx.Response(401)
        is_a = token == "ownerA-token-long-enough"
        if path == "/api/v1/auth/me":
            return httpx.Response(200, json={"status": "authenticated", "account": {"id": 1 if is_a else 2}})
        if path == "/api/v1/user/profile/preferences":
            return httpx.Response(200, json={"status": "configured", "data": {"preferences": {"baseCurrency": "EUR" if is_a else "USD"}},
                                             "policy": {"ownerDerivedFromAuthenticatedToken": True,
                                                        "clientSuppliedOwnerAccepted": False, "automaticTrading": False}})
        if path == "/api/v1/user/profile/personalization":
            policy = {"presentationOnly": True, "recommendationScoringInfluence": False,
                      "canonicalWeightingInfluence": False, "automaticLearningPromotion": False,
                      "automaticTrading": False, "sensitiveValuesIncluded": False}
            if personalization_escalation:
                policy["automaticLearningPromotion"] = True
            projection = {"schema": "athena.user-personalization.v1", "fingerprint": HASH,
                          "presentation": {"detailLevel": "standard", "explanationStyle": "balanced",
                                           "riskEmphasis": "standard", "horizonEmphasis": "long_term",
                                           "liquidityEmphasis": "unspecified", "objectiveFocus": "long_term_growth"},
                          "policy": policy}
            if personalization_leak:
                projection["availableCapital"] = 100000
            return httpx.Response(200, json={"status": "configured", "data": projection})
        if path == "/api/v1/user/portfolio":
            ids = ([11, 33] if is_a else [22, 33]) if shared_extra_position else (
                [11, 22] if cross_owner else ([11] if is_a else [22]))
            return httpx.Response(200, json={"data": {"positions": [{"id": n} for n in ids], "positionCount": len(ids)},
                                             "policy": {"ownerDerivedFromAuthenticatedToken": True,
                                                        "clientSuppliedOwnerAccepted": False, "automaticTrading": False}})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def check(**kwargs):
    with httpx.Client(base_url="https://staging.example", transport=transport(**kwargs)) as client:
        return module.verify_deployed_api(client, *owners())


def test_two_owner_canonical_and_revocation_success():
    report = check()
    assert report["status"] == "passed"
    assert report["deployedApiContractsVerified"] is True
    assert report["deployedFlutterBrowserE2EVerified"] is False
    assert report["operationalHistory365DaysVerified"] is False
    assert report["ownerScopedPersonalizationVerified"] is True
    assert report["persistedMarketUniverseVerified"] is True


@pytest.mark.parametrize("fault", [
    "missing_athena", "mismatched_news", "cross_owner", "revoked_accepted",
    "shared_extra_position", "personalization_leak", "personalization_escalation",
    "fallback_market", "empty_market",
])
def test_deployed_acceptance_fails_closed(fault):
    with pytest.raises(module.AcceptanceFailure):
        check(**{fault: True})


def test_missing_test_owner_marker_fails_closed(monkeypatch):
    monkeypatch.delenv("ATHENA_ACCEPTANCE_A_EMAIL", raising=False)
    with pytest.raises(module.AcceptanceFailure):
        module._env_owner("A")


def test_deployment_url_must_be_https_and_never_contain_credentials(monkeypatch, capsys):
    for url in ("http://staging.example", "https://user:secret@staging.example", "https://staging.example/private"):
        monkeypatch.setenv("ATHENA_ACCEPTANCE_BASE_URL", url)
        assert module.main() == 2
        assert "secret" not in capsys.readouterr().out
