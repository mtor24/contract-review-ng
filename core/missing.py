"""Contract-type auto-detection and missing-expected-clause findings."""

from core.classify import LABEL_NAMES
from core.rules import load_rules

# Title words are deliberate; body words can appear incidentally.
TITLE_WEIGHT = 5
# Missing clauses that expose a party to serious legal risk.
HIGH_SEVERITY = {"governing_law", "dispute_resolution", "termination", "data_protection"}
# Fallback when no keyword scores: most generic commercial contract.
DEFAULT_TYPE = "supply"


def _checklists() -> dict:
    return load_rules("checklists")


def detect_type(text: str) -> str:
    """Score each contract type by keyword hits; title lines count 5x."""
    lines = text.split("\n")
    title = "\n".join([ln for ln in lines if ln.strip()][:3]).lower()
    body = text.lower()
    best, best_score = DEFAULT_TYPE, 0
    # dict order is YAML order, so first-wins breaks ties deterministically.
    for type_id, spec in _checklists()["contract_types"].items():
        score = 0
        for kw in spec["detect_keywords"]:
            score += TITLE_WEIGHT * title.count(kw)
            score += body.count(kw)
        if score > best_score:
            best, best_score = type_id, score
    return best


def contract_types() -> dict[str, str]:
    """id -> human-readable name, for the UI selectbox."""
    return {
        type_id: spec["name"]
        for type_id, spec in _checklists()["contract_types"].items()
    }


def find_missing(labels: list[str], contract_type: str) -> list[dict]:
    """Return a finding for each expected clause absent from labels."""
    checks = _checklists()
    expected = checks["contract_types"][contract_type]["expected_clauses"]
    why = checks["why_expected"]
    present = set(labels)
    findings = []
    for label in expected:
        if label in present:
            continue
        findings.append(
            {
                "kind": "missing",
                "label": label,
                # Human name so reports never show the snake_case id.
                "name": LABEL_NAMES[label],
                "severity": "High" if label in HIGH_SEVERITY else "Medium",
                "reason": f"{LABEL_NAMES[label]} clause not found. " + why[label],
                "excerpt": "",
                "clause_seq": None,
                "char_start": None,
                "char_end": None,
            }
        )
    return findings
