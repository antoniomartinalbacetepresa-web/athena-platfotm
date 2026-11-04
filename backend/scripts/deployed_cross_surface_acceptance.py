"""Read-only deployed API cross-surface acceptance, plus disposable session revocation.

Never mutates positions or preferences, emits identities, or certifies Flutter UI,
market-history depth, investment performance, or production authorization.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class AcceptanceFailure(RuntimeError):
    """Safe-to-log acceptance failure with no HTTP response or credentials."""


@dataclass(frozen=True)
class TestOwner:
    username: str
    password: str
    position_id: int
    currency: str


@dataclass(frozen=True)
class OwnerSnapshot:
    owner_id: int
    position_ids: frozenset[int]
    preferences_sha256: str
    personalization_sha256: str
    positions_sha256: str


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise AcceptanceFailure(f"{label}: invalid object contract")
    return value


def _expect(condition: bool, label: str) -> None:
    if not condition:
        raise AcceptanceFailure(f"{label}: contract not satisfied")


def _require_sha256(value: object, label: str) -> str:
    """Reject absent or malformed canonical hashes before equality checks."""
    _expect(isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value)), label)
    return value


def _private_digest(value: object, label: str) -> str:
    """Compare private state without emitting its contents or fingerprints."""
    try:
        canonical = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError):
        raise AcceptanceFailure(f"{label}: non-canonical private state") from None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json(response: httpx.Response, label: str, *, status: int = 200) -> dict:
    if response.status_code != status:
        raise AcceptanceFailure(f"{label}: unexpected HTTP status {response.status_code}")
    try:
        return _object(response.json(), label)
    except (ValueError, UnicodeDecodeError):
        raise AcceptanceFailure(f"{label}: invalid JSON") from None


def _get(client: httpx.Client, path: str, label: str, *, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        return _json(client.get(path, headers=headers), label)
    except httpx.RequestError:
        raise AcceptanceFailure(f"{label}: transport unavailable") from None


def _post(client: httpx.Client, path: str, label: str, *, token: str | None = None,
          form: dict[str, str] | None = None, status: int = 200) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = client.post(path, headers=headers, data=form)
    except httpx.RequestError:
        raise AcceptanceFailure(f"{label}: transport unavailable") from None
    if response.status_code != status:
        raise AcceptanceFailure(f"{label}: unexpected HTTP status {response.status_code}")
    return response


def _login(client: httpx.Client, owner: TestOwner, label: str) -> str:
    result = _json(_post(client, "/api/v1/auth/token", label,
                         form={"username": owner.username, "password": owner.password}), label)
    token = result.get("access_token")
    _expect(isinstance(token, str) and len(token) > 20 and result.get("token_type") == "bearer", label)
    return token


def _owner_snapshot(client: httpx.Client, token: str, owner: TestOwner, label: str) -> OwnerSnapshot:
    account = _object(_get(client, "/api/v1/auth/me", label + " me", token=token).get("account"), label + " account")
    owner_id = account.get("id")
    _expect(type(owner_id) is int and owner_id > 0, label + " owner identity")
    profile = _get(client, "/api/v1/user/profile/preferences", label + " profile", token=token)
    _expect(profile.get("status") == "configured", label + " profile seeded")
    preferences = _object(_object(profile.get("data"), label + " profile data").get("preferences"), label + " preferences")
    _expect(preferences.get("baseCurrency") == owner.currency, label + " profile currency marker")
    policy = _object(profile.get("policy"), label + " profile policy")
    _expect(policy.get("ownerDerivedFromAuthenticatedToken") is True and
            policy.get("clientSuppliedOwnerAccepted") is False and
            policy.get("automaticTrading") is False, label + " profile policy")
    personalization_response = _get(
        client, "/api/v1/user/profile/personalization",
        label + " personalization", token=token,
    )
    _expect(personalization_response.get("status") == "configured", label + " personalization configured")
    personalization = _object(personalization_response.get("data"), label + " personalization")
    _expect(set(personalization) == {"schema", "fingerprint", "presentation", "policy"}
            and personalization.get("schema") == "athena.user-personalization.v1",
            label + " personalization contract")
    fingerprint = personalization.get("fingerprint")
    _expect(isinstance(fingerprint, str) and len(fingerprint) == 64
            and all(c in "0123456789abcdef" for c in fingerprint),
            label + " personalization fingerprint")
    presentation = _object(personalization.get("presentation"), label + " presentation")
    _expect(set(presentation) == {
        "detailLevel", "explanationStyle", "riskEmphasis", "horizonEmphasis",
        "liquidityEmphasis", "objectiveFocus",
    } and all(isinstance(value, str) for value in presentation.values()),
            label + " non-sensitive presentation")
    personalization_policy = _object(personalization.get("policy"), label + " personalization policy")
    _expect(
        personalization_policy.get("presentationOnly") is True
        and personalization_policy.get("recommendationScoringInfluence") is False
        and personalization_policy.get("canonicalWeightingInfluence") is False
        and personalization_policy.get("automaticLearningPromotion") is False
        and personalization_policy.get("automaticTrading") is False
        and personalization_policy.get("sensitiveValuesIncluded") is False,
        label + " personalization no-authority and privacy",
    )
    portfolio = _get(client, "/api/v1/user/portfolio", label + " portfolio", token=token)
    data = _object(portfolio.get("data"), label + " portfolio data")
    positions = data.get("positions")
    _expect(isinstance(positions, list) and data.get("positionCount") == len(positions), label + " positions")
    position_ids = set()
    for position in positions:
        item = _object(position, label + " position")
        identifier = item.get("id")
        _expect(type(identifier) is int and identifier > 0 and identifier not in position_ids, label + " position id")
        position_ids.add(identifier)
    _expect(owner.position_id in position_ids, label + " seeded position")
    policy = _object(portfolio.get("policy"), label + " portfolio policy")
    _expect(policy.get("ownerDerivedFromAuthenticatedToken") is True and
            policy.get("clientSuppliedOwnerAccepted") is False and
            policy.get("automaticTrading") is False, label + " portfolio policy")
    return OwnerSnapshot(
        owner_id=owner_id,
        position_ids=frozenset(position_ids),
        preferences_sha256=_private_digest(preferences, label + " preferences"),
        personalization_sha256=_private_digest(personalization, label + " personalization"),
        positions_sha256=_private_digest(
            sorted(positions, key=lambda item: item["id"]), label + " positions"
        ),
    )


def verify_deployed_api(
    client: httpx.Client, owner_a: TestOwner, owner_b: TestOwner, *, expected_sha: str,
) -> dict[str, object]:
    """Verify one deployed backend and two pre-seeded, authorized test accounts.

    A missing canonical artifact or missing owner-specific fixture means
    deployed acceptance is NOT complete.
    """
    _expect(bool(re.fullmatch(r"[0-9a-f]{40}", expected_sha)), "expected source SHA")
    health = _get(client, "/health", "health")
    _expect(health.get("status") == "ok" and health.get("service") == "athena-tyche-backend", "health")
    build = _get(client, "/api/v1/build", "backend build identity")
    _expect(set(build) == {"schema", "sourceSha"}
            and build.get("schema") == "athena.backend-build.v1"
            and build.get("sourceSha") == expected_sha,
            "deployed backend exact source SHA")
    market = _get(client, "/api/v1/market/universe/status", "market universe")
    universe = _object(market.get("data"), "market universe")
    _expect(type(universe.get("activeCount")) is int and universe["activeCount"] > 0
            and universe.get("usingFallback") is False,
            "persisted non-fallback market universe")
    root = "/api/v1/recommendations/professional-research"
    athena = _object(_get(client, root + "/athena-synthesis/latest", "athena").get("data"), "athena data")
    _expect(athena.get("artifactBindingVerified") is True, "athena canonical binding")
    selection = _object(athena.get("selection"), "athena selection")
    _expect(selection.get("presentationOnly") is True and selection.get("recommendationInfluence") is False
            and selection.get("automaticTrading") is False, "athena authority")
    cycle = _require_sha256(athena.get("cycleHash"), "athena cycle")
    synthesis = _object(athena.get("synthesis"), "athena synthesis")
    provenance = _object(athena.get("provenance"), "athena provenance")
    fingerprint = _require_sha256(synthesis.get("inputFingerprint"), "athena PIT fingerprint")
    _expect(fingerprint == _require_sha256(
        provenance.get("inputFingerprint"), "athena provenance PIT fingerprint"
    ), "athena PIT binding")
    news = _object(_get(client, root + "/news-synthesis/latest", "news").get("data"), "news data")
    _expect(news.get("cycleBindingVerified") is True and news.get("cycleHash") == cycle and
            news.get("presentationOnly") is True and news.get("recommendationInfluence") is False and
            news.get("automaticTrading") is False, "news canonical binding")
    news_hash = _require_sha256(
        _object(news.get("persistence"), "news persistence").get("synthesisHash"),
        "news synthesis hash",
    )
    _expect(_require_sha256(
        _object(provenance.get("news"), "athena news provenance").get("artifactHash"),
        "athena news provenance hash",
    ) == news_hash, "athena/news provenance binding")
    investors = _object(_get(client, root + f"/research-cycle/{cycle}/investors-synthesis", "investors").get("data"), "investors data")
    _expect(investors.get("cycleBindingVerified") is True and investors.get("cycleHash") == cycle and
            investors.get("recommendationInfluence") is False and investors.get("automaticTrading") is False,
            "investors canonical binding")
    investors_hash = _require_sha256(
        _object(investors.get("persistence"), "investors persistence").get("synthesisHash"),
        "investors synthesis hash",
    )
    _expect(_require_sha256(
        _object(provenance.get("investors"), "athena investors provenance").get("artifactHash"),
        "athena investors provenance hash",
    ) == investors_hash, "athena/investors provenance binding")

    # Anonymous requests must not see any owner-scoped surface, even before
    # the first disposable acceptance session is issued.
    for path, label in (
        ("/api/v1/auth/me", "anonymous identity"),
        ("/api/v1/user/profile/preferences", "anonymous preferences"),
        ("/api/v1/user/profile/personalization", "anonymous personalization"),
        ("/api/v1/user/portfolio", "anonymous portfolio"),
    ):
        try:
            response = client.get(path)
        except httpx.RequestError:
            raise AcceptanceFailure(f"{label}: transport unavailable") from None
        _expect(response.status_code == 401, label)

    token_a: str | None = None
    token_b: str | None = None
    try:
        token_a = _login(client, owner_a, "owner A login")
        token_b = _login(client, owner_b, "owner B login")
        snapshot_a = _owner_snapshot(client, token_a, owner_a, "owner A")
        snapshot_b = _owner_snapshot(client, token_b, owner_b, "owner B")
        _expect(snapshot_a.owner_id != snapshot_b.owner_id
                and owner_a.position_id != owner_b.position_id,
                "distinct owner fixtures")
        _expect(snapshot_a.position_ids.isdisjoint(snapshot_b.position_ids)
                and owner_b.position_id not in snapshot_a.position_ids
                and owner_a.position_id not in snapshot_b.position_ids,
                "complete owner position isolation")
        _post(client, "/api/v1/auth/logout", "owner A logout", token=token_a, status=204)
        for path, label in (("/api/v1/auth/me", "revoked me"),
                            ("/api/v1/user/profile/preferences", "revoked profile"),
                            ("/api/v1/user/profile/personalization", "revoked personalization"),
                            ("/api/v1/user/portfolio", "revoked portfolio")):
            try:
                response = client.get(path, headers={"Authorization": f"Bearer {token_a}"})
            except httpx.RequestError:
                raise AcceptanceFailure(f"{label}: transport unavailable") from None
            _expect(response.status_code == 401, label)
        # Revoking A must not corrupt B's identity, preferences or portfolio.
        snapshot_b_after = _owner_snapshot(
            client, token_b, owner_b, "owner B after A logout"
        )
        _expect(snapshot_b_after == snapshot_b,
                "owner B complete private state after A revocation")
        return {"status": "passed", "deployedApiContractsVerified": True,
                "deployedBackendBuildIdentityVerified": True,
                "persistedMarketUniverseVerified": True,
                "ownerScopedPersonalizationVerified": True,
                "deployedFlutterBrowserE2EVerified": False, "operationalHistory365DaysVerified": False,
                "crossSurfaceCanonicalBindingVerified": True, "twoOwnerIsolationAndRevocationVerified": True,
                "anonymousProtectedSurfacesVerified": True,
                "ownerBFullStateStableAfterRevocationVerified": True,
                "automaticTradingAuthorized": False}
    finally:
        # Never leave newly issued acceptance tokens live after a failed gate.
        # Cleanup is best-effort; failures must not conceal the original result.
        for token in (token_a, token_b):
            if token:
                try:
                    client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
                except httpx.RequestError:
                    pass


def _env_owner(suffix: str) -> TestOwner:
    prefix = "ATHENA_ACCEPTANCE_" + suffix + "_"
    username = os.environ.get(prefix + "EMAIL", "").strip()
    password = os.environ.get(prefix + "PASSWORD", "")
    currency = os.environ.get(prefix + "CURRENCY", "").strip().upper()
    try:
        position_id = int(os.environ.get(prefix + "POSITION_ID", ""))
    except ValueError:
        position_id = 0
    if not username or not password or position_id <= 0 or len(currency) != 3 or not currency.isalpha():
        raise AcceptanceFailure("Two seeded test owners with credentials, position IDs and currencies are required")
    return TestOwner(username=username, password=password, position_id=position_id, currency=currency)


def main() -> int:
    base = os.environ.get("ATHENA_ACCEPTANCE_BASE_URL", "").strip()
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        print(json.dumps({"status": "blocked", "reason": "HTTPS deployment base URL required"}))
        return 2
    try:
        owner_a, owner_b = _env_owner("A"), _env_owner("B")
        with httpx.Client(base_url=base, timeout=12.0, follow_redirects=False, trust_env=False) as client:
            result = verify_deployed_api(
                client, owner_a, owner_b, expected_sha=os.environ.get("GITHUB_SHA", ""),
            )
    except AcceptanceFailure as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
