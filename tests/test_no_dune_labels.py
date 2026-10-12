"""The BigQuery-era scripts must not present the legacy Dune backend as their data source.

Legacy Dune text is allowed in run_evaluation.py only between the DATA_SOURCE_TEXT markers,
and in the historical modules (vein/dune.py, entity_resolution.py, onchain_graph.py, ...)."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NO_DUNE = ["run_best.py", "run_multievent.py", "run_intraday_a3.py", "run_revision.py",
           "run_revision2.py", "run_revision3.py", "run_validation.py", "run_uncertainty.py",
           "run_topk.py"]


@pytest.mark.parametrize("name", NO_DUNE)
def test_no_dune_mentions(name):
    path = ROOT / name
    if not path.exists():
        pytest.skip(f"{name} not present yet")
    text = path.read_text()
    hits = [i + 1 for i, line in enumerate(text.splitlines()) if re.search(r"dune", line, re.I)]
    assert not hits, f"{name} mentions Dune on lines {hits}"


def test_run_evaluation_dune_text_only_between_markers():
    lines = (ROOT / "run_evaluation.py").read_text().splitlines()
    begin = lines.index("# DATA_SOURCE_TEXT begin")
    end = lines.index("# DATA_SOURCE_TEXT end")
    assert begin < end
    outside = [i + 1 for i, line in enumerate(lines)
               if re.search(r"dune", line, re.I) and not (begin <= i <= end)]
    assert not outside, f"Dune mentioned outside DATA_SOURCE_TEXT on lines {outside}"
