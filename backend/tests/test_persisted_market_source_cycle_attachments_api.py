"""Private canonical source attachments, without fetching external evidence."""
from datetime import timedelta
import pytest
from test_persisted_market_research_cycle_api import setup, counts, NOW, POST
from app.api import recommendation_professional_research_cycle as api
from app.main import app


def source(payload, *, owner=17, category="news", journal="source", as_of=NOW, count=1):
    context = api.ProfessionalResearchCycleRequest(
        instrumentId=str(payload["instrumentId"]), symbol="SYNTH", asOf=as_of,
        recordedAt=as_of, journalId=f"__athena_private_owner_{owner}__:{journal}",
        revisionId="r1", thesis="Synthetic source research",
        radarEvidence=[{
            "evidenceId": "original", "category": category, "urgency": "material",
            "summary": "Synthetic metadata; no licensed or real provider claim.",
            "availableAt": (as_of - timedelta(days=1)).isoformat(),
            "publishedAt": (as_of - timedelta(days=2)).isoformat(),
            "provider": "synthetic_fixture", "publisher": "Synthetic publisher",
            "source": "synthetic_fixture", "sourceRef": f"https://example.invalid/fixture/{category}",
        }], journalReferences=payload["journalReferences"],
        contradictoryEvidence=payload["contradictoryEvidence"],
    )
    if count > 1:
        template = context.radarEvidence[0]
        context.radarEvidence = [template.model_copy(update={
            "evidenceId": f"original-{index}", "sourceRef": f"{template.sourceRef}/{index}",
        }) for index in range(count)]
    return api._persist_professional_research_cycle(context, owner_id=owner)["data"]["integrity"]["cycleHash"]


def test_attaches_deduplicates_and_retries(setup):
    database, payload, client = setup
    first = source(payload)
    duplicate = source(payload, journal="same-content")
    investor = source(payload, category="investors", journal="investor")
    payload["sourceCycleHashes"] = [investor, first, duplicate, first]
    response = client.post(POST, json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["productionEligible"] is data["policy"]["automaticTrading"] is False
    record = api.cycle_repository.get_by_hash(cycle_hash=data["integrity"]["cycleHash"], owner_id=17)
    evidence = record["package"]["radar"]["candidates"][0]["evidence"]
    assert len(evidence) == 3
    assert {item["category"] for item in evidence} == {"news", "investors", "data_quality"}
    assert all(item.get("provider") == "synthetic_fixture" and item.get("publishedAt")
               for item in evidence if item["category"] != "data_quality")
    refs = record["package"]["journal"]["references"]
    assert {item["sourceRef"] for item in refs if item["referenceId"].startswith("source-cycle:")} == {
        f"urn:athena:research-cycle:{digest}" for digest in (first, duplicate, investor)
    }
    retry = client.post(POST, json=payload)
    assert retry.status_code == 200 and retry.json() == response.json()
    payload["sourceCycleHashes"] = [first, duplicate, investor]
    assert client.post(POST, json=payload).json() == response.json()
    assert counts(database) == [1, 4, 4]


@pytest.mark.parametrize("owner", [18, None])
def test_other_owner_and_public_source_no_writes(setup, owner):
    database, payload, client = setup
    digest = source(payload, owner=owner or 17)
    if owner is None:
        with database.connect() as connection:
            connection.execute("DELETE FROM athena_professional_research_cycle_owners WHERE cycle_hash = ?", (digest,))
    before = counts(database)
    payload["sourceCycleHashes"] = [digest]
    assert client.post(POST, json=payload).status_code == 404
    assert counts(database) == before


def test_owner_revalidated_inside_write_transaction(setup, monkeypatch):
    database, payload, client = setup
    digest = source(payload)
    payload["sourceCycleHashes"] = [digest]
    before = counts(database)
    original = api.cycle_service.bind
    def mutate(**kwargs):
        result = original(**kwargs)
        with database.connect() as connection:
            connection.execute("UPDATE athena_professional_research_cycle_owners SET owner_id = 18 WHERE cycle_hash = ?", (digest,))
        return result
    monkeypatch.setattr(api.cycle_service, "bind", mutate)
    assert client.post(POST, json=payload).status_code == 404
    assert counts(database) == before


@pytest.mark.parametrize("hashes", [["A" * 64], [1], ["a" * 63], ["a" * 64] * 6, "a" * 64])
def test_strict_source_hashes(setup, hashes):
    database, payload, client = setup
    payload["sourceCycleHashes"] = hashes
    assert client.post(POST, json=payload).status_code == 422
    assert counts(database) == [0, 0, 0]


@pytest.mark.parametrize("field", ["journalReferences", "contradictoryEvidence"])
@pytest.mark.parametrize("uri", ["urn:athena:research-cycle:" + "a" * 64, " URN:ATHENA:RESEARCH-CYCLE:fake", "urn%3Aathena%3Aresearch-cycle%3Afake", "urn&#58;athena&#58;research-cycle&#58;fake"])
def test_caller_source_namespace_forbidden(setup, field, uri):
    database, payload, client = setup
    payload[field][0]["sourceRef"] = uri
    assert client.post(POST, json=payload).status_code == 400
    assert counts(database) == [0, 0, 0]


def test_source_after_destination_cutoff_rejected(setup):
    database, payload, client = setup
    digest = source(payload, as_of=NOW + timedelta(hours=1))
    before = counts(database)
    payload["sourceCycleHashes"] = [digest]
    assert client.post(POST, json=payload).status_code == 400
    assert counts(database) == before


def test_source_identity_mismatch_no_writes(setup):
    database, payload, client = setup
    payload["sourceCycleHashes"] = [source(payload)]
    before = counts(database)
    payload["symbol"] = "OTHER"
    assert client.post(POST, json=payload).status_code == 400
    assert counts(database) == before


def test_source_package_revalidated_inside_write_transaction(setup, monkeypatch):
    database, payload, client = setup
    digest = source(payload)
    payload["sourceCycleHashes"] = [digest]
    before = counts(database)
    original = api.cycle_service.bind
    def corrupt(**kwargs):
        result = original(**kwargs)
        with database.connect() as connection:
            connection.execute("UPDATE athena_professional_research_cycles SET package_json = '{}' WHERE cycle_hash = ?", (digest,))
        return result
    monkeypatch.setattr(api.cycle_service, "bind", corrupt)
    assert client.post(POST, json=payload).status_code == 400
    assert counts(database) == before


def test_source_owner_authorized_before_deserializing(setup, monkeypatch):
    database, payload, client = setup
    payload["sourceCycleHashes"] = [source(payload, owner=18)]
    def unexpected(*args, **kwargs):
        pytest.fail("A different owner's package was deserialized")
    monkeypatch.setattr(api.cycle_repository, "_row", unexpected)
    assert client.post(POST, json=payload).status_code == 404


def test_existing_cycle_without_news_or_investors_is_not_a_source(setup):
    database, payload, client = setup
    original = client.post(POST, json=payload)
    assert original.status_code == 200
    before = counts(database)
    payload["journalId"] = "second"
    payload["sourceCycleHashes"] = [original.json()["data"]["integrity"]["cycleHash"]]
    assert client.post(POST, json=payload).status_code == 400
    assert counts(database) == before


def test_market_plus_source_evidence_limit_no_silent_truncation(setup):
    database, payload, client = setup
    payload["sourceCycleHashes"] = [source(payload, count=200)]
    before = counts(database)
    assert client.post(POST, json=payload).status_code == 400
    assert counts(database) == before


def test_combined_journal_limit_no_writes(setup):
    database, payload, client = setup
    payload["sourceCycleHashes"] = [source(payload)]
    before = counts(database)
    template = payload["journalReferences"][0]
    payload["journalReferences"] = [{**template, "referenceId": f"human-{index}",
        "sourceRef": f"urn:human:{index}"} for index in range(199)]
    assert client.post(POST, json=payload).status_code == 400
    assert counts(database) == before


def test_authentication_precedes_any_source_access(setup, monkeypatch):
    database, payload, client = setup
    payload["sourceCycleHashes"] = ["a" * 64]
    monkeypatch.delitem(app.dependency_overrides, api.current_account)
    def unexpected(*args, **kwargs):
        pytest.fail("Unauthenticated request reached source selection")
    monkeypatch.setattr(api, "_source_attachments", unexpected)
    assert client.post(POST, json=payload).status_code == 401
    assert counts(database) == [0, 0, 0]
