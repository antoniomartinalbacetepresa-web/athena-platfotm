"""Conservative, auditable ATHENA completion inventory; no production inference."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

INVENTORY = Path(__file__).resolve().parents[2] / "docs" / "ACCEPTANCE_INVENTORY.json"
LEVELS = {"pending": 0, "blocked": 0, "implemented_ci": 1, "real_data": 2, "deployed": 3}
REQUIRED = {"implemented_ci": 1, "real_data": 2, "deployed": 3}
SCOPES = ("core", "product")
REQUIRED_AREAS = {
    "architecture_backend", "welcome_navigation", "dashboard", "market", "news",
    "portfolio", "profile_auth", "athena_ai", "market_history",
    "continuous_learning", "personalization", "security", "testing_ci",
}


def validate(data: dict) -> None:
    if data.get("schema") != "athena.acceptance-inventory.v1":
        raise ValueError("Unsupported inventory schema")
    if not isinstance(data.get("scopeMappingReviewed"), dict) or set(data["scopeMappingReviewed"]) != set(SCOPES):
        raise ValueError("Both scopes need explicit mapping review")
    if any(type(data["scopeMappingReviewed"][scope]) is not bool for scope in SCOPES):
        raise ValueError("Mapping review flags must be boolean")
    rows = data.get("criteria")
    if not isinstance(rows, list) or not rows:
        raise ValueError("No acceptance criteria")
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid criterion")
        ident = row.get("id")
        if not isinstance(ident, str) or not ident or ident in ids:
            raise ValueError("Duplicate or missing criterion ID")
        ids.add(ident)
        if not isinstance(row.get("module"), str) or not row["module"]:
            raise ValueError("Criterion has no module")
        scopes = row.get("scopes")
        if not isinstance(scopes, list) or not scopes or len(scopes) != len(set(scopes)) or not set(scopes) <= set(SCOPES):
            raise ValueError("Invalid or duplicated scope")
        if type(row.get("weight")) is not int or not 1 <= row["weight"] <= 5:
            raise ValueError("Weight must be an integer from 1 to 5")
        if not all(isinstance(row.get(key), str) and row[key].strip() for key in ("weightRationale", "acceptance")):
            raise ValueError("Criterion needs acceptance and weight rationale")
        status = row.get("status")
        if status not in LEVELS or row.get("requiredLevel") not in REQUIRED:
            raise ValueError("Invalid evidence status or required level")
        if type(row.get("reviewed")) is not bool:
            raise ValueError("Criterion review must be explicit")
        evidence = row.get("evidence")
        if not isinstance(evidence, list):
            raise ValueError("Evidence must be a list")
        if status in ("implemented_ci", "real_data", "deployed") and not evidence:
            raise ValueError("Progress without evidence")
        if status == "blocked" and not row.get("blockers"):
            raise ValueError("Blocked criterion needs a reason")
        for ev in evidence:
            if not isinstance(ev, dict) or ev.get("kind") not in ("ci", "real_data", "deployment"):
                raise ValueError("Invalid evidence kind")
            if not isinstance(ev.get("sha"), str) or len(ev["sha"]) != 40 or any(ch not in "0123456789abcdef" for ch in ev["sha"]):
                raise ValueError("Evidence needs exact commit SHA")
            if not isinstance(ev.get("url"), str) or not ev["url"].startswith("https://github.com/"):
                raise ValueError("Evidence needs an approved GitHub reference")
            if ev["kind"] == "ci" and not ev.get("path"):
                raise ValueError("CI evidence needs tested source path")
        if status in ("real_data", "deployed") and not any(ev["kind"] == ("real_data" if status == "real_data" else "deployment") for ev in evidence):
            raise ValueError("Operational status requires operational evidence")
        if not isinstance(row.get("dependencies"), list):
            raise ValueError("Dependencies must be a list")
    for row in rows:
        if any(dep not in ids or dep == row["id"] for dep in row["dependencies"]):
            raise ValueError("Unknown or self dependency")
    if not REQUIRED_AREAS <= {row["module"] for row in rows}:
        raise ValueError("Roadmap area missing from inventory")
    if not any("core" in row["scopes"] for row in rows) or not any("product" in row["scopes"] for row in rows):
        raise ValueError("Core and product both required")
    gates = data.get("mandatoryGates")
    if not isinstance(gates, list) or not gates or len({g.get("id") for g in gates}) != len(gates):
        raise ValueError("Missing or duplicate mandatory gates")
    if any(type(g.get("verified")) is not bool or (g["verified"] and not g.get("evidence")) for g in gates):
        raise ValueError("Gate needs explicit verified evidence")


def summarize(data: dict) -> dict:
    validate(data)
    output = {"schema": "athena.acceptance-progress.v1", "baselineCommit": data["baselineCommit"], "scopes": {}}
    for scope in SCOPES:
        rows = [r for r in data["criteria"] if scope in r["scopes"]]
        reviewed = sum(bool(r["reviewed"]) for r in rows)
        total_weight = sum(r["weight"] for r in rows)
        weighted = sum(
            r["weight"] * min(LEVELS[r["status"]] / REQUIRED[r["requiredLevel"]], 1)
            for r in rows
        )
        gates_ok = all(g["verified"] for g in data["mandatoryGates"])
        certifiable = bool(data["scopeMappingReviewed"][scope]) and reviewed == len(rows)
        completed = all(LEVELS[r["status"]] >= REQUIRED[r["requiredLevel"]] for r in rows)
        output["scopes"][scope] = {
            "criteria": len(rows),
            "reviewed": reviewed,
            "statusCounts": dict(sorted(Counter(r["status"] for r in rows).items())),
            "mappingReviewed": data["scopeMappingReviewed"][scope],
            "percent": round(100 * weighted / total_weight, 2) if certifiable else None,
            "certifiable": certifiable,
            "complete": bool(certifiable and completed and gates_ok),
            "pendingMandatoryGates": [g["id"] for g in data["mandatoryGates"] if not g["verified"]],
            "reason": None if certifiable else "Inventario sin revisión completa: porcentaje actual no certificable",
        }
    return output


def main() -> None:
    print(json.dumps(summarize(json.loads(INVENTORY.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
