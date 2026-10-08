import json
from pathlib import Path


SCENARIOS_ROOT = (
    Path(__file__).resolve().parents[2] / "data" / "scenarios"
)
DEFAULT_SCENARIO_DIR = SCENARIOS_ROOT / "checkout_regression"


def read_fixture(filename: str, data_dir: Path):
    with (data_dir / filename).open(encoding="utf-8") as source:
        return json.load(source)
