import sys
from pathlib import Path

import pytest

# Allow `import core` when pytest is invoked from any directory.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def samples_dir() -> Path:
    return ROOT / "data" / "samples"
