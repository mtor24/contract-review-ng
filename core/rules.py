"""Load clause-classification rules from the editable rules/ directory."""

import functools
from pathlib import Path

import yaml

# Rules live next to core/, not inside it, so non-developers can find them easily.
RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


@functools.lru_cache(maxsize=None)
def load_rules(name: str) -> dict:
    """Load rules/<name>.yaml; cached so repeated classify() calls read disk once."""
    path = RULES_DIR / f"{name}.yaml"
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
