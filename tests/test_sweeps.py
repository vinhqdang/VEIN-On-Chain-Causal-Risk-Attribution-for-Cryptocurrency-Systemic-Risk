"""Tests for the pandas mirror of the Tier-0 sweep query (vein/sweeps.py).

Scenario addresses are synthetic. Binance and OKX hot wallets are labelled; each
scenario tests one rule of the classifier, and the expected outcome is in the name.
"""
import pandas as pd

from vein import config, labels as lb, sweeps as sw

B_HOT = "0x" + "b1" * 20
O_HOT = "0x" + "0c" * 20
T0 = pd.Timestamp("2025-10-08 00:00:00")
NULL = "0x" + "00" * 20


def _h(n):
    return "0x" + f"{n:040x}"


def _labels(extra=()):
    rows = [
        {"address": B_HOT, "entity": "Binance", "src": "label", "etype": "CEX"},
        {"address": O_HOT, "entity": "OKX", "src": "label", "etype": "CEX"},
        *extra,
    ]
    return pd.DataFrame(rows)


class Flows:
    def __init__(self):
        self.rows = []

    def add(self, hour, frm, to, amount, token="USDe"):
        self.rows.append({"bucket": T0 + pd.Timedelta(hours=hour), "token": token,
                          "from_a": frm, "to_a": to, "amount": float(amount), "n_tx": 1})

    def frame(self):
        return pd.DataFrame(self.rows)


def _detect(flows, labels=None, usd=None):
    usd = usd or {"USDe": 1.0, "WETH": 3000.0}
    return sw.detect_sweeps_frame(flows.frame(), labels if labels is not None else _labels(),
                                  usd, config.SWEEP_PARAMS)


S1, S2, S3 = _h(0x51), _h(0x52), _h(0x53)
D1, D2, R, W, L, SM, F, K = (_h(x) for x in (0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8))


def _scenario():
    """All scenarios in one frame; each deposit address is tested in isolation by
    giving it its own senders and counterparties."""
    f = Flows()
    # D1 accepted: two non-hot senders, 90% of the outflow swept to Binance within hours.
    f.add(0, S1, D1, 5000); f.add(1, S2, D1, 5000)
    f.add(2, D1, B_HOT, 9000)
    # D2 rejected: 50/50 split between Binance and OKX.
    f.add(0, S1, D2, 4000); f.add(1, D2, B_HOT, 2000); f.add(1, D2, O_HOT, 2000)
    # R rejected: five distinct outbound counterparties.
    f.add(0, S1, R, 5000); f.add(0, S2, R, 5000)
    f.add(2, R, B_HOT, 8000)
    for i, x in enumerate((0x61, 0x62, 0x63, 0x64)):
        f.add(3, R, _h(x), 500)
    # W rejected: funded entirely by Binance hot, no non-hot inflow.
    f.add(0, B_HOT, W, 3000); f.add(1, W, B_HOT, 3000)
    # L rejected: sweep 48 hours after the only deposit (no inflow in the 24h window).
    f.add(0, S1, L, 5000); f.add(48, L, B_HOT, 4500)
    # SM rejected: $500 total sweep, below the $1,000 floor.
    f.add(0, S2, SM, 500); f.add(1, SM, B_HOT, 450)
    # F rejected: forwards only 30% of inflow to Binance, rest to another wallet.
    f.add(0, S2, F, 4000); f.add(1, F, B_HOT, 1200); f.add(2, F, _h(0x71), 2800)
    # K labelled: never a candidate even though it looks like a deposit.
    f.add(0, S1, K, 5000); f.add(1, K, B_HOT, 4500)
    # Null address: never a candidate.
    f.add(0, S1, NULL, 5000); f.add(1, NULL, B_HOT, 4500)
    return f


def test_deposit_accepted_and_others_rejected():
    labels = _labels([{"address": K, "entity": "Binance", "src": "label", "etype": "CEX"}])
    out = _detect(_scenario(), labels)
    assert set(out.address) == {D1}
    row = out.iloc[0]
    assert row.entity == "Binance"
    assert abs(row.sweep_ratio - 1.0) < 1e-12      # all of D1's outflow goes to Binance
    assert abs(row.out_usd - 9000.0) < 1e-9 and abs(row.in_usd - 10000.0) < 1e-9
    assert row.n_senders_nonhot == 2


def test_rejections_one_rule_at_a_time():
    labels = _labels([{"address": K, "entity": "Binance", "src": "label", "etype": "CEX"}])
    out = _detect(_scenario(), labels)
    for name, addr in [("D2 split", D2), ("R counterparties", R), ("W hot-funded", W),
                       ("L late sweep", L), ("SM tiny", SM), ("F partial", F), ("K labelled", K),
                       ("null", NULL)]:
        assert addr not in set(out.address), name


def test_labelled_address_never_candidate_even_when_qualifying():
    # Without a label on K it would look like a deposit; with the label it must not appear.
    f = Flows()
    f.add(0, S1, K, 5000); f.add(1, S2, K, 5000); f.add(2, K, B_HOT, 9000)
    labelled = _detect(f, _labels([{"address": K, "entity": "Binance", "src": "seed", "etype": "CEX"}]))
    unlabelled = _detect(f, _labels())
    assert K in set(unlabelled.address)
    assert K not in set(labelled.address)


def test_null_address_never_candidate():
    f = Flows()
    f.add(0, S1, NULL, 5000); f.add(1, S2, NULL, 5000); f.add(2, NULL, B_HOT, 9000)
    assert NULL not in set(_detect(f).address)


def test_eth_token_usd_conversion():
    # 1.0 WETH in and 0.9 WETH out: below the $1,000 floor at $1 per unit, detected at ETH price.
    f = Flows()
    f.add(0, S1, _h(0xE1), 1.0, token="WETH")
    f.add(1, _h(0xE1), B_HOT, 0.9, token="WETH")
    assert _detect(f, usd={"WETH": 1.0}).empty
    det = _detect(f, usd={"WETH": 3000.0})
    assert list(det.address) == [_h(0xE1)]
    assert abs(det.iloc[0].to_x_usd - 2700.0) < 1e-6


def test_tokens_missing_from_price_map_are_dropped():
    f = Flows()
    f.add(0, S1, D1, 5000, token="USDe"); f.add(1, S2, D1, 5000, token="USDe")
    f.add(2, D1, B_HOT, 9000, token="USDe")
    assert _detect(f, usd={"WETH": 3000.0}).empty


def test_output_columns_and_empty_input():
    out = _detect(_scenario())
    assert list(out.columns) == sw.OUT_COLS
    empty = sw.detect_sweeps_frame(pd.DataFrame(columns=["bucket", "token", "from_a", "to_a", "amount", "n_tx"]),
                                   _labels(), {"USDe": 1.0}, config.SWEEP_PARAMS)
    assert list(empty.columns) == sw.OUT_COLS and empty.empty


def test_seed_labels_are_valid_sweep_inputs():
    # The seed table is what the BigQuery sweep query receives as hot wallets and known addresses.
    seed = lb.seed_label_table()
    assert {"src", "etype", "entity", "address"} <= set(seed.columns)
    assert set(seed.src) == {"seed"}
