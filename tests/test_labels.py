"""Tests for vein/labels.py: parsing, exchange roots, conflicts, merge and fingerprint.

Fixtures in tests/fixtures/labels: a.csv (CSV), b.json (address-keyed dict),
c.json (list with chainId). Addresses are synthetic apart from Binance 14.
"""
import shutil
from pathlib import Path

import pandas as pd
import pytest

from vein import config, entity_resolution as er
from vein import labels as lb

FIX = Path(__file__).parent / "fixtures" / "labels"
BINANCE14 = "0x28c6c06298d514db089934071355e5743bf21d60"


@pytest.fixture
def bigquery_backend(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "bigquery")


def _copy(tmp_path, *names, sub="repo"):
    d = tmp_path / sub
    d.mkdir()
    for n in names:
        shutil.copy(FIX / n, d / n)
    return d


@pytest.mark.parametrize("name,cat,root", [
    ("Binance 14", "exchange", "Binance"),
    ("Binance: Hot Wallet 20", "", "Binance"),
    ("Binance US 3", "", "Binance.US"),
    ("OKX 3", "", "OKX"),
    ("OKEx 7", "", "OKX"),
    ("Huobi 10", "", "HTX"),
    ("Coinbase 10", "", "Coinbase"),
    ("Gate.io 1", "", "Gate.io"),
    ("Crypto.com 2", "", "Crypto.com"),
    ("FTX Exchange", "", "FTX"),
    ("Bitfinex: Hot Wallet", "", "Bitfinex"),
    ("CoinEx 3", "", "CoinEx"),
    ("Binance Dep: 0x0004975B5560875BCd66E27770d5874152BAe212", "bilaxy", "Binance"),
])
def test_normalize_exchange_roots(name, cat, root):
    assert lb.normalize_exchange(name, cat) == root


@pytest.mark.parametrize("name,cat", [
    ("Binance: BUSD Token", ""),
    ("Uniswap V3: Router", ""),
    ("Coinbase: Commerce", ""),
    ("Binance Pool", "mining"),
    ("Binance Charity: Ukraine Emergency Relief Fund", "binance-charity"),
    ("Bybit Exploiter 33", "bybit-exploit"),
])
def test_normalize_exchange_rejects_non_wallets(name, cat):
    assert lb.normalize_exchange(name, cat) is None


def test_iter_label_records_reads_all_three_formats(tmp_path):
    repo = _copy(tmp_path, "a.csv", "b.json", "c.json")
    recs = list(lb.iter_label_records(repo))
    addrs = {r["address"] for r in recs}
    assert BINANCE14 in addrs                      # CSV, upper-case input lower-cased
    assert "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in addrs   # list of dicts, chainId 1
    assert "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" not in addrs  # chainId 56 dropped
    assert "0xnotanaddress" not in addrs           # invalid address dropped
    b14 = [r for r in recs if r["address"] == BINANCE14 and r["source_file"].endswith("b.json")][0]
    assert b14["name"] == "Binance 14" and b14["category"] == "exchange"
    csv_row = [r for r in recs if r["address"] == BINANCE14 and r["source_file"].endswith("a.csv")][0]
    assert csv_row["name"] == "Binance 14"


def test_iter_label_records_skips_other_chain_folders_and_tokens(tmp_path):
    repo = tmp_path / "repo"
    (repo / "data" / "bscscan" / "accounts").mkdir(parents=True)
    (repo / "data" / "etherscan" / "tokens").mkdir(parents=True)
    (repo / "data" / "etherscan" / "accounts").mkdir(parents=True)
    row = "0x5555555555555555555555555555555555555555,OKX 3,exchange\n"
    (repo / "data" / "bscscan" / "accounts" / "okx.csv").write_text("Address,Name Tag,Label\n" + row)
    (repo / "data" / "etherscan" / "tokens" / "okx.csv").write_text("Address,Name Tag,Label\n" + row)
    (repo / "data" / "etherscan" / "accounts" / "okx.csv").write_text("Address,Name Tag,Label\n" + row)
    recs = list(lb.iter_label_records(repo))
    assert len(recs) == 1
    assert recs[0]["source_file"].endswith("accounts/okx.csv")


def test_build_open_label_table_drops_conflicts(tmp_path):
    a = _copy(tmp_path, "a.csv", sub="r1")
    b = _copy(tmp_path, "b.json", sub="r2")
    df, rep = lb.build_open_label_table([a, b])
    # 0x7777... is "Bybit 1" in a.csv and "Kraken 3" in b.json -> dropped as a conflict
    assert "0x7777777777777777777777777777777777777777" not in set(df.address)
    assert rep["conflicts"] == 1
    assert "0x7777777777777777777777777777777777777777" in rep["conflict_examples"]
    # Binance 14 appears in both files with the same root -> kept once
    b14 = df[df.address == BINANCE14]
    assert len(b14) == 1 and b14.entity.iloc[0] == "Binance"
    assert set(df.etype) == {"CEX"} and set(df.src) == {"label"}
    assert rep["addresses_total"] == len(df)


def test_merge_labels_seed_overrides_open_and_is_one_row_per_address():
    seed = lb.seed_label_table()
    open_ = pd.DataFrame([
        {"address": BINANCE14, "entity": "OKX", "src": "label", "etype": "CEX", "raw_name": "x", "source": "t"},
        {"address": "0x5555555555555555555555555555555555555555", "entity": "OKX", "src": "label",
         "etype": "CEX", "raw_name": "OKX 3", "source": "t"},
    ])
    sweeps = pd.DataFrame([
        {"address": "0x5555555555555555555555555555555555555555", "entity": "Bybit", "src": "sweep",
         "etype": "CEX", "raw_name": "Bybit", "source": "s"},
        {"address": "0x6666666666666666666666666666666666666666", "entity": "Bybit", "src": "sweep",
         "etype": "CEX", "raw_name": "Bybit", "source": "s"},
    ])
    m = lb.merge_labels(seed, open_, sweeps)
    assert m.address.is_unique
    row = m[m.address == BINANCE14].iloc[0]
    assert row.src == "seed" and row.entity == "Binance"
    assert m[m.address == "0x5555555555555555555555555555555555555555"].src.iloc[0] == "label"
    assert m[m.address == "0x6666666666666666666666666666666666666666"].src.iloc[0] == "sweep"


def test_label_fingerprint_is_order_independent_and_sensitive():
    df = pd.DataFrame({"address": ["0x1", "0x2"], "entity": ["A", "B"], "src": ["label", "seed"]})
    shuffled = df.iloc[::-1].reset_index(drop=True)
    assert lb.label_fingerprint(df) == lb.label_fingerprint(shuffled)
    changed = df.assign(entity=["A", "C"])
    assert lb.label_fingerprint(df) != lb.label_fingerprint(changed)
    assert len(lb.label_fingerprint(df)) == 12


def test_to_bq_frame_converts_addresses_to_bytes():
    df = pd.DataFrame({"address": [BINANCE14], "entity": ["Binance"], "src": ["seed"],
                       "etype": ["CEX"], "raw_name": ["Binance 14"], "source": ["config"]})
    out = lb.to_bq_frame(df)
    assert out.address.iloc[0] == bytes.fromhex(BINANCE14[2:])
    assert len(out.address.iloc[0]) == 20
    assert list(out.columns) == ["address", "entity", "src", "etype", "raw_name", "source"]


def test_seed_table_covers_config_addresses():
    seed = lb.seed_label_table()
    assert seed.address.is_unique
    assert len(seed) == sum(len(m["addresses"]) for m in config.ENTITIES.values())
    assert seed.loc[seed.address == BINANCE14, "entity"].iloc[0] == "Binance"
    assert set(seed.loc[seed.entity == "Ethena", "etype"]) == {"STABLECOIN_ISSUER"}


def test_normalize_entity_idempotent_on_roots_and_retail(bigquery_backend):
    for root in ["Binance", "Binance.US", "Gate.io", "Crypto.com", "FTX", "HTX", "FalconX",
                 "Ethena", "Aave", "Lido", "MakerSky", "retail"]:
        assert er.normalize_entity(root) == root
        assert er.normalize_entity(er.normalize_entity(root)) == root


def test_normalize_entity_collapses_sub_wallets(bigquery_backend):
    assert er.normalize_entity("Binance Hot 1") == "Binance"
    assert er.normalize_entity("OKEx 7") == "OKX"


def test_normalize_entity_dune_path_unchanged(monkeypatch):
    # The Dune path keeps the legacy token strip, so "Binance US 3" stays "Binance US".
    monkeypatch.setattr(config, "DATA_BACKEND", "dune")
    assert er.normalize_entity("Binance US 3") == "Binance US"


# --- label kind: wallets versus per-user deposit addresses ---------------------------
def test_label_kind_splits_deposit_addresses_from_wallets():
    assert lb.label_kind("Bitget Dep: 0x000483C56FE99127fbd62da5D8b899a159116dc1") == "deposit"
    assert lb.label_kind("Binance Dep: 0x000f9f5F6db6d63bB64bb55d58272A1ce660fD90") == "deposit"
    for n in ("Binance 14", "Binance: Deposit Funder 3", "Bitget: Hot Wallet 2", "Coinbase 10"):
        assert lb.label_kind(n) == "wallet"


def test_wallet_and_deposit_filters_and_old_tables_without_kind():
    df = pd.DataFrame({
        "address": ["0x" + "a" * 40, "0x" + "b" * 40], "entity": ["Bitget", "Bitget"],
        "src": ["label"] * 2, "etype": ["CEX"] * 2,
        "raw_name": ["Bitget Dep: 0x" + "a" * 40, "Bitget: Hot Wallet 1"], "source": ["t"] * 2})
    assert lb.wallet_labels(df).address.tolist() == ["0x" + "b" * 40]
    assert lb.deposit_labels(df).address.tolist() == ["0x" + "a" * 40]


def test_seed_labels_are_wallet_kind():
    assert set(lb.seed_label_table()["kind"]) == {"wallet"}
