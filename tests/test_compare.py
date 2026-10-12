"""Curated path resolution and comparison flags (run_compare.py).

The comparison never searches for a value: a path either resolves or is reported."""
import json

import pytest

import run_compare as rc


OBJ = {
    "n_entities": 17,
    "oc_covar_ranking": [{"entity": "Coinbase", "exported_risk": 4.0},
                         {"entity": "Binance", "exported_risk": 2.5},
                         {"entity": "Binance", "exported_risk": 9.0, "venue": "perp"}],
    "attribution": {"channels": [{"i": "Binance", "j": "Bybit", "share": 0.07,
                                  "share_ci95": [0.01, 0.12]},
                                 {"i": "Ethena", "j": "Aave", "share": 0.0,
                                  "share_ci95": [-0.1, 0.1]}]},
    "H1": {"bootstrap": {"granger": {"ci95": [-0.2, 0.4]}}},
}


def test_dict_key_and_nested_path():
    assert rc.resolve(OBJ, ["n_entities"]) == 17
    assert rc.resolve(OBJ, ["H1", "bootstrap", "granger", "ci95", "hi"]) == 0.4


def test_selector_picks_unique_list_element():
    assert rc.resolve(OBJ, ["oc_covar_ranking", {"entity": "Coinbase"}, "exported_risk"]) == 4.0
    got = rc.resolve(OBJ, ["attribution", "channels", {"i": "Binance", "j": "Bybit"}, "share"])
    assert got == 0.07


def test_selector_with_no_match_raises():
    with pytest.raises(KeyError):
        rc.resolve(OBJ, ["oc_covar_ranking", {"entity": "Kraken"}, "exported_risk"])


def test_ambiguous_selector_raises():
    with pytest.raises(ValueError, match="ambiguous"):
        rc.resolve(OBJ, ["oc_covar_ranking", {"entity": "Binance"}, "exported_risk"])


def test_positional_index_raises():
    with pytest.raises(ValueError, match="positional index not allowed"):
        rc.resolve(OBJ, ["oc_covar_ranking", 0, "exported_risk"])


def test_lo_hi_only_after_ci95():
    assert rc.resolve(OBJ, ["attribution", "channels", {"i": "Binance", "j": "Bybit"},
                            "share_ci95", "lo"]) == 0.01
    assert rc.resolve({"x": {"lo": 1.0}}, ["x", "lo"]) == 1.0      # not after ci95: ordinary key
    with pytest.raises(TypeError):
        rc.resolve({"x": [0.1, 0.2]}, ["x", "lo"])
    with pytest.raises(ValueError):
        rc.resolve({"ci95": [1.0, 2.0, 3.0]}, ["ci95", "lo"])


def test_missing_key_raises_instead_of_matching_a_value():
    # 4.0 exists in the object, but not under this path: no value search happens
    with pytest.raises(KeyError):
        rc.resolve(OBJ, ["n_entity"])


def test_printed_match_is_on_the_displayed_scale():
    assert rc.printed_matches(0.0716, "7.2", "pct")
    assert rc.printed_matches(1.5e9, "1.5", "usd_bn")
    assert not rc.printed_matches(1.66, "1.663", "num")


def _write(tmp_path, name, obj):
    d = tmp_path / name
    d.mkdir()
    return d


def test_compare_flags(tmp_path):
    old = _write(tmp_path, "old", {})
    new = _write(tmp_path, "new", {})
    (old / "f.json").write_text(json.dumps({"a": 2.0, "b": 1.0, "r": {"ci95": [-0.1, 0.2]}}))
    (new / "f.json").write_text(json.dumps({"a": -3.0, "b": 1.1, "r": {"ci95": [0.1, 0.2]}}))
    stale = rc.compare_entry({"id": "A", "file": "f.json", "path": ["a"], "printed": "2.0",
                              "fmt": "num"}, old, new)
    assert "sign flip" in stale["flags"] and "MANUSCRIPT_STALE" in stale["flags"]
    assert stale["matches"] is False
    small = rc.compare_entry({"id": "B", "file": "f.json", "path": ["b"], "printed": "1.1",
                              "fmt": "num"}, old, new)
    assert small["flags"] == [] and small["matches"] is True
    ci = rc.compare_entry({"id": "C", "file": "f.json", "path": ["r", "ci95", "lo"],
                           "ci_path": ["r", "ci95"]}, old, new)
    assert ci["status"] == "ok" and ci["new"] == 0.1
    assert "CI zero inclusion change" in ci["flags"]


def test_pending_and_structure_changed(tmp_path):
    old = _write(tmp_path, "old", {})
    new = _write(tmp_path, "new", {})
    (new / "f.json").write_text(json.dumps({"a": 1.0}))
    pend = rc.compare_entry({"id": "P", "file": "missing.json", "path": ["x"], "pending": True,
                             "note": "later"}, old, new)
    assert pend["status"] == "PENDING" and pend["note"] == "later"
    changed = rc.compare_entry({"id": "S", "file": "f.json", "path": ["b"]}, old, new)
    assert changed["status"] == "STRUCTURE_CHANGED"


def test_map_file_is_valid_and_ids_unique():
    entries = rc.load_map(rc.MAP_PATH)
    assert len(entries) >= 20
    assert len({e["id"] for e in entries}) == len(entries)
    for e in entries:
        assert e.get("fmt", "num") in rc.FORMATS
        assert e["file"] and isinstance(e["path"], list)
