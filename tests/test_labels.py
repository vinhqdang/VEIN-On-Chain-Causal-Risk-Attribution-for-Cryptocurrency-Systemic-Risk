"""Tests for vein/labels.py: parsing, exchange roots, conflicts, merge and fingerprint.

Fixtures in tests/fixtures/labels: a.csv (CSV), b.json (address-keyed dict),
c.json (list with chainId). Addresses are synthetic apart from Binance 14.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from vein import config, entity_resolution as er
from vein import labels as lb

FIX = Path(__file__).parent / "fixtures" / "labels"
BINANCE14 = "0x28c6c06298d514db089934071355e5743bf21d60"
SB_FIX = FIX / "spellbook_sample.sql"          # synthetic six-row file, not the real list
SB_BIN1 = "0x" + "1" * 40                      # Binance 1
SB_CB_DEP = "0x" + "2" * 40                    # Coinbase Prime Deposit 1
SB_GATE = "0x" + "abcdef" * 6 + "abcd"         # Gate.io 1 (cex_name 'Gate', upper-case in file)
SB_CHARITY = "0x" + "4" * 40                   # Binance Charity (not a wallet)
SB_KAIA = "0x" + "5" * 40                      # Bithumb 1 kaia (other chain)
SB_UNKNOWN = "0x" + "6" * 40                   # Unknown Venue 1 (no exchange)


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


# --- third source: Dune Spellbook CEX list (BSL 1.1, pinned, never redistributed) ---------
def _spellbook_dir(tmp_path, sub="spellbook"):
    """A spellbook checkout as clone_label_repos leaves it: the SQL file and LICENSE only."""
    d = tmp_path / sub
    (d / Path(config.SPELLBOOK_SQL).parent).mkdir(parents=True)
    shutil.copy(SB_FIX, d / config.SPELLBOOK_SQL)
    (d / "LICENSE").write_text("Business Source License 1.1\n")
    return d


def test_config_pins_spellbook_to_a_full_sha_with_sparse_paths():
    assert re.fullmatch(r"[0-9a-f]{40}", config.SPELLBOOK_COMMIT)
    assert config.LABEL_REPOS["spellbook"] == "https://github.com/duneanalytics/spellbook.git"
    assert config.LABEL_PINNED["spellbook"] == {"commit": config.SPELLBOOK_COMMIT,
                                                "sparse": config.SPELLBOOK_SPARSE}
    assert "LICENSE" in config.SPELLBOOK_SPARSE and config.SPELLBOOK_SQL in config.SPELLBOOK_SPARSE


def test_spellbook_parser_reads_every_row_with_fields():
    recs = list(lb.iter_spellbook_records(SB_FIX))
    assert len(recs) == 6
    by = {r["address"]: r for r in recs}
    assert set(by) == {SB_BIN1, SB_CB_DEP, SB_GATE, SB_CHARITY, SB_KAIA, SB_UNKNOWN}
    assert by[SB_BIN1]["category"] == "Binance" and by[SB_BIN1]["name"] == "Binance 1"
    assert by[SB_CB_DEP]["category"] == "Coinbase Prime"
    assert by[SB_KAIA]["chain"] == "kaia" and by[SB_BIN1]["chain"] == ""
    assert all(r["source_file"].endswith("spellbook_sample.sql") for r in recs)


def test_spellbook_parser_lowercases_and_skips_sql_comments(tmp_path):
    p = tmp_path / "x.sql"
    p.write_text("-- , (0x9999999999999999999999999999999999999999, 'Binance', 'Binance 9', 'a', date '2020-01-01')\n"
                 "FROM (VALUES\n"
                 "    (0xABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCD, 'Binance', 'Binance 2', 'a', date '2020-01-01')\n")
    recs = list(lb.iter_spellbook_records(p))
    assert [r["address"] for r in recs] == ["0x" + "abcdef" * 6 + "abcd"]


def test_spellbook_deposit_kind_detection():
    assert lb.spellbook_kind("Coinbase Prime Deposit 1") == "deposit"
    assert lb.spellbook_kind("Binance Wintermute Deposit 1") == "deposit"
    assert lb.spellbook_kind("Binance 1") == "wallet"
    assert lb.spellbook_kind("Binance: Hot Wallet 3") == "wallet"
    kinds = {r["address"]: r["kind"] for r in lb.iter_spellbook_records(SB_FIX)}
    assert kinds[SB_CB_DEP] == "deposit" and kinds[SB_BIN1] == "wallet"


def test_spellbook_root_uses_cex_name_then_distinct_name():
    assert lb.spellbook_root("Coinbase Prime", "Coinbase Prime Deposit 1") == "Coinbase"
    assert lb.spellbook_root("Gate", "Gate.io 1") == "Gate.io"
    assert lb.spellbook_root("Unknown Venue", "Bybit 3") == "Bybit"      # fallback
    assert lb.spellbook_root("Binance", "Binance Charity") is None        # not a wallet
    assert lb.spellbook_root("Unknown Venue", "Unknown Venue 1") is None


def test_build_counts_spellbook_exclusions_and_kinds(tmp_path):
    df, rep = lb.build_open_label_table([_spellbook_dir(tmp_path)])
    sb = rep["sources"]["spellbook"]
    assert (sb["records"], sb["excluded_other_chain"], sb["excluded_non_wallet"],
            sb["unmapped_names"]) == (6, 1, 1, 1)
    assert dict(zip(df.address, df.entity)) == {SB_BIN1: "Binance", SB_CB_DEP: "Coinbase",
                                                SB_GATE: "Gate.io"}
    assert dict(zip(df.address, df.kind))[SB_CB_DEP] == "deposit"
    assert rep["addresses_per_root_wallet"] == {"Binance": 1, "Gate.io": 1}
    assert rep["addresses_per_root_deposit"] == {"Coinbase": 1}
    assert rep["unmapped_spellbook_names"] == [("Unknown Venue", 1)]


def test_spellbook_conflict_with_open_source_is_dropped(tmp_path):
    mit = tmp_path / "eth"
    mit.mkdir()
    (mit / "x.csv").write_text(f"Address,Name Tag,Label\n{SB_BIN1},Bybit 9,exchange\n")
    sb = _spellbook_dir(tmp_path)
    df, rep = lb.build_open_label_table([mit, sb])
    assert SB_BIN1 not in set(df.address)
    assert rep["conflicts"] == 1 and rep["conflicts_involving_spellbook"] == 1
    pub, _ = lb.public_table([mit, sb])
    assert dict(zip(pub.address, pub.entity))[SB_BIN1] == "Bybit"


def test_public_table_excludes_spellbook_rows_and_tags(tmp_path):
    sb = _spellbook_dir(tmp_path)
    mit = tmp_path / "eth"
    mit.mkdir()
    (mit / "x.csv").write_text(f"Address,Name Tag,Label\n{SB_GATE},Gate.io 9,exchange\n")
    full, _ = lb.build_open_label_table([mit, sb])
    pub, prep = lb.public_table([mit, sb])
    assert SB_BIN1 in set(full.address) and SB_BIN1 not in set(pub.address)
    assert SB_CB_DEP not in set(pub.address)
    assert "spellbook" not in prep["sources"] and "spellbook" not in prep["licence"]
    # A row also present in an MIT source keeps the MIT tag only.
    assert dict(zip(pub.address, pub.source)) == {SB_GATE: "eth"}
    assert full.loc[full.address == SB_GATE, "source"].item() == "eth+spellbook"
    mit_only, _ = lb.build_open_label_table([mit])
    pd.testing.assert_frame_equal(pub, mit_only)
    # The file that would be redistributed contains no trace of the spellbook list.
    out = tmp_path / "public.csv.gz"
    pub.to_csv(out, index=False, compression="gzip")
    import gzip
    assert b"spellbook" not in gzip.open(out).read().lower()
    assert b"Binance 1" not in gzip.open(out).read()


def _git_commit(repo, msg):
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=test", "-c",
                    "user.email=test@example.com", "commit", "-q", "-m", msg],
                   check=True, capture_output=True)


def test_clone_pinned_checks_out_only_the_pinned_commit(tmp_path):
    up = tmp_path / "upstream"
    up.mkdir()
    subprocess.run(["git", "init", "-q", str(up)], check=True)
    (up / "sub").mkdir()
    (up / "LICENSE").write_text("Business Source License 1.1\n")
    (up / "sub" / "keep.sql").write_text("v1\n")
    (up / "other.txt").write_text("x\n")
    _git_commit(up, "one")
    c1 = lb._git(up, "rev-parse", "HEAD")
    (up / "sub" / "keep.sql").write_text("v2\n")
    _git_commit(up, "two")
    c2 = lb._git(up, "rev-parse", "HEAD")
    lb._git(up, "config", "uploadpack.allowFilter", "true")
    lb._git(up, "config", "uploadpack.allowAnySHA1InWant", "true")

    dest = tmp_path / "clone"
    sparse = ["LICENSE", "sub/keep.sql"]
    assert lb._clone_pinned(up.as_uri(), dest, c1, sparse) == c1
    assert (dest / "sub" / "keep.sql").read_text() == "v1\n"
    assert not (dest / "other.txt").exists()                  # outside the sparse set
    assert lb._licence(dest) == "Business Source License 1.1"
    # A second call re-pins the existing checkout to the other commit.
    assert lb._clone_pinned(up.as_uri(), dest, c2, sparse) == c2
    assert (dest / "sub" / "keep.sql").read_text() == "v2\n"


# ---------------------------------------------------------------- aToken / PSM / stETH seeds
NEW_SEEDS = {
    "Aave": ["0x98c23e9d8f34fefb1b7bd6a91b7ff122f4e16f5c", "0x23878914efe38d27c4d67ab83ed1b93a74d4086a",
             "0x4f5923fc5fd4a93352581b38b7cd26943012decf", "0x4579a27af00a62c0eb156349f31b345c08386419",
             "0x4d5f47fa6a74757f35c14fd3a6ef8e3c9bc514e8", "0xbcca60bb61934080951369a648fb03df4f96263c",
             "0x3ed3b47dd13ec9a98b44e6204a523e766b225811", "0x030ba81f1c18d280636f32af80b9aad02cf0854e"],
    "MakerSky": ["0x37305b1cd40574e4c5ce33f8e8306be057fd7341", "0xf6e72db5454dd049d0788e411b06cfaf16853042",
                 "0x0a59649758aa4d66e25f08dd01271e891fe52199", "0x89b78cfa322f6c5de0abceecab66aee45393cc5a",
                 "0xa188eec8f81263234da3622a406892f3d630f98c"],
}


def test_new_seeds_present_with_correct_entity():
    seed = lb.seed_label_table()
    lookup = dict(zip(seed.address, seed.entity))
    for entity, addrs in NEW_SEEDS.items():
        for a in addrs:
            assert lookup[a] == entity
            assert config.ALL_ADDRESSES[a] == entity


def test_seed_addresses_are_unique_across_entities():
    seed = lb.seed_label_table()
    assert seed.address.is_unique
    assert all(re.fullmatch(r"0x[0-9a-f]{40}", a) for a in seed.address)


def test_protocol_address_is_not_an_entity_seed():
    q = config.PROTOCOL_ADDRESSES["lido_withdrawal_queue"]
    assert q == "0x889edc2edab5f40e902b864ad4d7ade8e412f9b1"
    assert q not in set(lb.seed_label_table().address)


def test_refresh_seeds_promotes_new_seed_and_keeps_other_rows():
    seed = lb.seed_label_table()
    cached = pd.DataFrame([
        # an address that is now an Aave seed but was cached as an open label
        {"address": NEW_SEEDS["Aave"][0], "entity": "Bitfinex", "src": "label", "etype": "CEX",
         "raw_name": "Old", "source": "open", "kind": "wallet"},
        # an unrelated sweep row must stay as it is
        {"address": "0x" + "9" * 40, "entity": "OKX", "src": "sweep", "etype": "CEX",
         "raw_name": "OKX", "source": "sweeps", "kind": "wallet"},
    ])
    merged = pd.concat([seed, cached], ignore_index=True)
    merged = merged.drop_duplicates("address", keep="last")
    out = lb.refresh_seeds(merged)
    row = out[out.address == NEW_SEEDS["Aave"][0]].iloc[0]
    assert row.src == "seed" and row.entity == "Aave"
    other = out[out.address == "0x" + "9" * 40].iloc[0]
    assert other.src == "sweep" and other.entity == "OKX"
    assert out.address.is_unique
    assert len(out) == len(set(out.address))


def test_refresh_seeds_is_idempotent():
    seed = lb.seed_label_table()
    once = lb.refresh_seeds(seed)
    twice = lb.refresh_seeds(once)
    pd.testing.assert_frame_equal(once.reset_index(drop=True), twice.reset_index(drop=True))
