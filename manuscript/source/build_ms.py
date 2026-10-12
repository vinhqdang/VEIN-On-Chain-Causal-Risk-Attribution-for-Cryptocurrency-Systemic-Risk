#!/usr/bin/env python3
"""Fill the VEIN manuscript template from results/*.json and write the numbers map.

Every printed number is a token @@ID@@ (or a table cell generated here). Each token is
resolved through run_compare.resolve on a JSON path, or computed from JSON with a stated
formula (class D), or is a code/source constant (class S). Writes:
  manuscript/vein_manuscript.tex
  manuscript/cover_letter.tex          (from cover template)
  results/manuscript_numbers_map.json  (version 1: entries + manual_entries)
"""
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RES = REPO / "results"
SCR = Path(__file__).resolve().parent   # templates live next to this script
sys.path.insert(0, str(REPO))
import run_compare as rc  # noqa: E402  (same path semantics as the comparison tool)

CACHE = {}


def J(name):
    if name not in CACHE:
        CACHE[name] = json.loads((RES / name).read_text())
    return CACHE[name]


FTX = {"event": "FTX_Nov2022"}
SVB = {"event": "USDC_SVB_Mar2023"}
EXTRACTS = ["oct25_hourly", "ftx_hourly", "svb_hourly", "core_daily"]

# ---------------------------------------------------------------- registry
ENTRIES = []          # path-based map entries
MANUAL = []           # class S / D / P manual entries
VALUES = {}           # token -> (printed plain string)
TOKEN_RENDER = {}     # token -> tex string
_ids = set()


def scale(v, fmt):
    if fmt == "pct":
        return v * 100.0
    if fmt == "usd_bn":
        return v / 1e9
    return v


def fmt_plain(x, dec):
    s = f"{x:.{dec}f}"
    if s.startswith("-") and float(s) == 0:
        s = s[1:]
    return s


def tex_of(plain, dec, group=True):
    s = plain
    neg = s.startswith("-")
    digits = s.lstrip("-")
    if group and dec == 0 and len(digits) >= 4:
        digits = f"{int(digits):,}".replace(",", "{,}")
    s = ("-" if neg else "") + digits
    if s.startswith("-"):
        return "$-$" + s[1:]
    return s


def add_entry(eid, file, path, fmt, dec, ci=None, value_plain=None, value_raw=None):
    if eid in _ids:
        raise RuntimeError(f"duplicate id {eid}")
    _ids.add(eid)
    ent = {"id": eid, "tex_anchor": "", "printed": value_plain, "fmt": fmt,
           "file": file, "path": path}
    if ci is not None:
        ent["ci_path"] = ci
    ENTRIES.append(ent)
    return ent


def reg_path(eid, file, path, fmt="num", dec=2, ci=None):
    """Register a numeric path-based entry (if new) and return its tex string."""
    if eid in VALUES:
        return VALUES[eid][1]
    raw = rc.resolve(J(file), path)
    if not rc._is_num(raw):
        raise ValueError(f"{eid}: {file} {path} is not numeric: {raw!r}")
    x = scale(float(raw), fmt)
    plain = fmt_plain(x, dec)
    tex = tex_of(plain, dec)
    add_entry(eid, file, path, fmt, dec, ci, value_plain=plain)
    VALUES[eid] = (plain, tex, dec)
    return tex


def reg_manual(eid, cls, printed_plain, dec_tex, file, location, calc, tex=None, group=True):
    if eid in VALUES:
        return VALUES[eid][1]
    t = tex if tex is not None else tex_of(printed_plain, dec_tex, group=group)
    MANUAL.append({"id": eid, "tex_anchor": "", "printed": printed_plain,
                   "source_class": cls, "file": file, "path_or_location": location, "calc": calc})
    VALUES[eid] = (printed_plain, t, dec_tex)
    return t


def reg_string(eid, cls, text, file, location):
    if eid in VALUES:
        return VALUES[eid][1]
    MANUAL.append({"id": eid, "tex_anchor": "", "printed": text, "source_class": cls,
                   "file": file, "path_or_location": location, "calc": "string from JSON"})
    VALUES[eid] = (text, text, 0)
    return text


def san(name):
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


# ---------------------------------------------------------------- path-based specs
SPEC = []


def S(eid, file, path, fmt="num", dec=2, ci=None):
    SPEC.append((eid, file, path, fmt, dec, ci))


FIN, UNC, OOS = "final_results.json", "uncertainty.json", "oos_r2.json"
REV, REV3, TK = "revision.json", "revision3.json", "topk_sensitivity.json"
MEV, DBD, RES_J = "multievent.json", "data_build.json", "results.json"
COV, ANA, ABD = "coverage.json", "analytics.json", "abduction_lesson.json"
V1, V2, IAD = "v1_dune/final_results.json", "v2_bq_initial/final_results.json", "intraday_a3.json"

# setup and samples
S("N_ENTITIES", FIN, ["n_entities"], "num", 0)
S("N_FIT_HOURS", FIN, ["n_fit_hours"], "num", 0)
S("N_EVENT_HOURS", FIN, ["n_event_hours"], "num", 0)
S("GRAPH_EDGES", FIN, ["graph_edges"], "num", 0)
S("N_CUSTODIAL", REV, ["edge_type_falsification", "n_custodial_edges"], "num", 0)
S("N_COMPOS", REV, ["edge_type_falsification", "n_composability_edges"], "num", 0)
S("N_SIMS", FIN, ["settings", "n_sims"], "num", 0)
S("SEED_POINT", FIN, ["settings", "seed"], "num", 0)
S("S_STAR_Q", FIN, ["settings", "s_star_quantile"], "num", 2)
S("S_STAR_ROWS", FIN, ["settings", "s_star_window_rows"], "num", 0)
S("BLOCK_LEN", FIN, ["settings", "block_len"], "num", 0)
S("H1_BLOCK", FIN, ["settings", "h1_bootstrap", "block_len"], "num", 0)
S("H1_B", FIN, ["settings", "h1_bootstrap", "B"], "num", 0)
S("MC_NREP", UNC, ["ranking", "mc_error", "n_rep"], "num", 0)
S("MC_NSIMS", UNC, ["ranking", "mc_error", "n_sims"], "num", 0)
S("N_BOOT", UNC, ["settings", "n_boot"], "num", 0)
S("N_SIMS_BOOT", UNC, ["settings", "n_sims"], "num", 0)
S("SEED_BOOT", UNC, ["settings", "seed_boot"], "num", 0)
S("SEED_ATTR", UNC, ["settings", "seed_attr"], "num", 0)
S("Q", UNC, ["settings", "q"], "num", 2)
S("TOPK_MAIN", TK, ["main_k"], "num", 0)
S("TS_B", FIN, ["placebo", "time_shift", "B"], "num", 0)
S("TS_SEED", FIN, ["placebo", "time_shift", "seed"], "num", 0)
S("BLOCK8", OOS, ["bootstrap", "block_len_sensitivity"], "num", 0)
S("ME_FTX_N_FIT", MEV, ["events", FTX, "n_fit_rows"], "num", 0)
S("ME_SVB_N_FIT", MEV, ["events", SVB, "n_fit_rows"], "num", 0)
S("ME_FTX_DAILY_FIT", MEV, ["events", {"event": "FTX_Nov2022"}, "daily_robustness", "n_fit_rows"], "num", 0)
S("ME_SVB_DAILY_FIT", MEV, ["events", {"event": "USDC_SVB_Mar2023"}, "daily_robustness", "n_fit_rows"], "num", 0)
S("ME_FTX_N_EV", MEV, ["events", FTX, "n_event_rows"], "num", 0)
S("ME_FTX_N_ENT", MEV, ["events", FTX, "n_entities"], "num", 0)
S("ME_FTX_N_EDGES", MEV, ["events", FTX, "n_edges"], "num", 0)
S("ME_SVB_N_EV", MEV, ["events", SVB, "n_event_rows"], "num", 0)
S("ME_SVB_N_ENT", MEV, ["events", SVB, "n_entities"], "num", 0)
S("ME_SVB_N_EDGES", MEV, ["events", SVB, "n_edges"], "num", 0)
S("COV_FTX", COV, ["ftx_ext", "panel_tokens", "named_distinct_share_of_touching"], "pct", 1)
S("COV_SVB", COV, ["svb_ext", "panel_tokens", "named_distinct_share_of_touching"], "pct", 1)
S("ME_DAILY_MIN", MEV, ["events", FTX, "daily_robustness", "min_rows_required"], "num", 0)

# data
S("BQ_BILLED_GIB", DBD, ["ledger", "cumulative_billed_gib"], "num", 0)
S("LABELS_OPEN", DBD, ["labels", "open_addresses"], "num", 0)
S("LABELS_PUBLIC", DBD, ["labels", "public_addresses"], "num", 0)
S("LABELS_CONFLICTS", DBD, ["labels", "conflicts"], "num", 0)
S("BASE_ROWS", DBD, ["labels", "base_rows"], "num", 0)
S("DEP_BITGET", DBD, ["labels", "open_per_root_deposit", "Bitget"], "num", 0)
S("DEP_BINANCE", DBD, ["labels", "open_per_root_deposit", "Binance"], "num", 0)
for eid, ent in [("SEED_AAVE", "Aave"), ("SEED_MAKER", "MakerSky"), ("SEED_ETHENA", "Ethena"), ("SEED_LIDO", "Lido")]:
    S(eid, DBD, ["labels", "paper_entities", {"entity": ent}, "seed"], "num", 0)
S("TAU", DBD, ["sweeps", "validation", "oct25_hourly", "default", "params", "tau"], "num", 1)
S("MAX_OUT_CP", DBD, ["sweeps", "validation", "oct25_hourly", "default", "params", "max_out_cp"], "num", 0)
S("H_HOURS", DBD, ["sweeps", "validation", "oct25_hourly", "default", "params", "h_hours"], "num", 0)
S("MIN_SWEEP_USD", DBD, ["sweeps", "validation", "oct25_hourly", "default", "params", "min_sweep_usd"], "num", 0)
S("TAU_TIGHT", DBD, ["sweeps", "validation", "ftx_hourly", "tightened", "params", "tau"], "num", 1)
S("MAX_OUT_CP_TIGHT", DBD, ["sweeps", "validation", "ftx_hourly", "tightened", "params", "max_out_cp"], "num", 0)
S("SWEPT_OCT_BN", DBD, ["sweeps", "per_extract", "oct25_hourly", "swept_usd"], "usd_bn", 1)
S("COV_OCT_PANEL", COV, ["oct25_hourly", "panel_tokens", "named_distinct_share_of_touching"], "pct", 1)
S("COV_MODEL", REV, ["resolution_coverage", "frac_volume_named_both_sides"], "pct", 1)
S("COV_MODEL_TOTAL_BN", REV, ["resolution_coverage", "total_usd"], "usd_bn", 0)
S("USDE_TOL", DBD, ["usde_daily_check", "tolerance"], "pct", 0)
S("USDE_1010", DBD, ["usde_daily", {"day": "2025-10-10"}, "usde_bn"], "num", 2)
S("USDE_1011", DBD, ["usde_daily", {"day": "2025-10-11"}, "usde_bn"], "num", 2)
S("LIDO_GROSS", FIN, ["fit_gross_usd", "Lido"], "usd_bn", 2)
S("ETHENA_GROSS_BN", FIN, ["fit_gross_usd", "Ethena"], "usd_bn", 2)

# explained stress
S("R2_RETAIL", UNC, ["attribution", "r2_in_sample", "retail", "point"], "num", 3)
S("R2C_RETAIL", UNC, ["attribution", "r2_in_sample", "retail", "point_optimism_corrected"], "num", 3)
S("R2C_RETAIL_LO", UNC, ["attribution", "r2_in_sample", "retail", "optimism_corrected_ci95", "lo"], "num", 3,
  ci=["attribution", "r2_in_sample", "retail", "optimism_corrected_ci95"])
S("R2C_RETAIL_HI", UNC, ["attribution", "r2_in_sample", "retail", "optimism_corrected_ci95", "hi"], "num", 3,
  ci=["attribution", "r2_in_sample", "retail", "optimism_corrected_ci95"])
S("OOS_AR_R2", OOS, ["pooled", "ar", "r2_os"], "num", 3, ci=["pooled", "ar", "ci95"])
S("OOS_AR_R2_LO", OOS, ["pooled", "ar", "ci95", "lo"], "num", 3)
S("OOS_AR_R2_HI", OOS, ["pooled", "ar", "ci95", "hi"], "num", 3)
S("OOS_NET_R2", OOS, ["pooled", "network", "r2_os"], "num", 3, ci=["pooled", "network", "ci95"])
S("OOS_NET_R2_LO", OOS, ["pooled", "network", "ci95", "lo"], "num", 3)
S("OOS_NET_R2_HI", OOS, ["pooled", "network", "ci95", "hi"], "num", 3)
S("OOS_AR_MACRO", OOS, ["pooled", "ar", "macro_mean_r2_os"], "num", 3)
S("OOS_NET_MACRO", OOS, ["pooled", "network", "macro_mean_r2_os"], "num", 3)
S("OOS_GAIN_NET", OOS, ["increment_over_ar", "network", "gain"], "pct", 1, ci=["increment_over_ar", "network", "ci95"])
S("OOS_GAIN_NET_LO", OOS, ["increment_over_ar", "network", "ci95", "lo"], "pct", 1)
S("OOS_GAIN_NET_HI", OOS, ["increment_over_ar", "network", "ci95", "hi"], "pct", 1)
S("OOS_GAIN_ARNET", OOS, ["increment_over_ar", "ar_network", "gain"], "pct", 1, ci=["increment_over_ar", "ar_network", "ci95"])
S("OOS_GAIN_ARNET_LO", OOS, ["increment_over_ar", "ar_network", "ci95", "lo"], "pct", 1)
S("OOS_GAIN_ARNET_HI", OOS, ["increment_over_ar", "ar_network", "ci95", "hi"], "pct", 1)
S("OOS_RETAIL_ARNET_VS_AR", OOS, ["by_entity", "retail", "ar_network_vs_ar"], "pct", 1)
S("OOS_COINBASE_ARNET_VS_AR", OOS, ["by_entity", "Coinbase", "ar_network_vs_ar"], "pct", 1)
S("OOS_AAVE_AR", OOS, ["by_entity", "Aave", "ar"], "num", 3)

# attribution
S("MAX_SHARE", UNC, ["attribution", "max_share", "point"], "pct", 1, ci=["attribution", "max_share", "ci95"])
S("MAX_SHARE_LO", UNC, ["attribution", "max_share", "ci95", "lo"], "pct", 1)
S("MAX_SHARE_HI", UNC, ["attribution", "max_share", "ci95", "hi"], "pct", 1)
CHANNELS = {"BB": ("Binance", "Bybit"), "EA": ("Ethena", "Aave"), "EB": ("Ethena", "Binance"),
            "LA": ("Lido", "Aave"), "CB": ("Crypto.com", "Binance"), "BO": ("Binance", "OKX"),
            "KB": ("Kraken", "Bitfinex"), "MR": ("MakerSky", "retail")}
for P, (I, Jn) in CHANNELS.items():
    sel = {"i": I, "j": Jn}
    S(f"{P}_SHARE", UNC, ["attribution", "channels", sel, "share"], "pct", 1)
    S(f"{P}_ATTR", UNC, ["attribution", "channels", sel, "attribution"], "num", 2)
    S(f"{P}_LO", UNC, ["attribution", "channels", sel, "share_ci95", "lo"], "pct", 1,
      ci=["attribution", "channels", sel, "share_ci95"])
    S(f"{P}_HI", UNC, ["attribution", "channels", sel, "share_ci95", "hi"], "pct", 1,
      ci=["attribution", "channels", sel, "share_ci95"])
    S(f"{P}_PPOS", UNC, ["attribution", "channels", sel, "p_positive"], "num", 2)
S("V1_BB_SHARE", V1, ["counterfactual_attribution", {"i": "Binance", "j": "Bybit"}, "attribution_share"], "pct", 1)
S("V1_BB_LOBS", V1, ["counterfactual_attribution", {"i": "Binance", "j": "Bybit"}, "L_observed"], "num", 2)
S("LEGACY_BB_SHARE", ABD, ["modes", {"abduction": "legacy_zero"}, "binance_to_bybit", "share"], "pct", 1)
S("LEGACY_BB_LOBS", ABD, ["modes", {"abduction": "legacy_zero"}, "bybit_L_observed"], "num", 2)
S("V3_BB_SHARE", ABD, ["modes", {"abduction": "full"}, "binance_to_bybit", "share"], "pct", 1)
S("V3_BB_LOBS", ABD, ["modes", {"abduction": "full"}, "bybit_L_observed"], "num", 2)
for pl in ["BIN", "COI", "BFX"]:
    pass
S("SH_BIN", UNC, ["attribution", "shapley_bybit", "point", "Binance"], "num", 2)
S("SH_COI", UNC, ["attribution", "shapley_bybit", "point", "Coinbase"], "num", 2)
S("SH_BFX", UNC, ["attribution", "shapley_bybit", "point", "Bitfinex"], "num", 2)
S("AS_BB_SD", REV, ["attribution_sensitivity", "Binance->Bybit", "sd"], "pct", 2)

# ranking
S("RANK_BINANCE", UNC, ["ranking", "point", {"entity": "Binance"}, "rank"], "num", 0)
S("RCI_BIN_LO", UNC, ["ranking", "by_entity", "Binance", "rank_ci95", "lo"], "num", 0)
S("RCI_BIN_HI", UNC, ["ranking", "by_entity", "Binance", "rank_ci95", "hi"], "num", 0)
S("P3_RETAIL", UNC, ["ranking", "by_entity", "retail", "p_top3"], "num", 2)
S("P3_MAKER", UNC, ["ranking", "by_entity", "MakerSky", "p_top3"], "num", 2)
S("SP_MEAN", UNC, ["ranking", "spearman_vs_point", "mean"], "num", 3)
S("SP_LO", UNC, ["ranking", "spearman_vs_point", "q025"], "num", 3)
S("SP_HI", UNC, ["ranking", "spearman_vs_point", "q975"], "num", 3)
S("NR_BIN", REV, ["no_retail_ranking", {"entity": "Binance"}, "exported_risk"], "num", 2)
S("NR_CRO", REV, ["no_retail_ranking", {"entity": "Crypto.com"}, "exported_risk"], "num", 2)
S("NR_KRA", REV, ["no_retail_ranking", {"entity": "Kraken"}, "exported_risk"], "num", 2)
S("RANK_ETHENA", UNC, ["ranking", "point", {"entity": "Ethena"}, "rank"], "num", 0)

# diagnostics
S("H1_OBS", FIN, ["H1", "scores", {"model": "observed_onchain"}, "rmse"], "num", 4)
S("H1_GR", FIN, ["H1", "scores", {"model": "estimated_granger"}, "rmse"], "num", 4)
S("H1_PC", FIN, ["H1", "scores", {"model": "estimated_partial_corr"}, "rmse"], "num", 4)
S("H1_N", FIN, ["H1", "scores", {"model": "observed_onchain"}, "n"], "num", 0)
S("H1_GR_DIFF", FIN, ["H1", "bootstrap", "granger", "mean_diff"], "num", 4)
S("H1_GR_LO", FIN, ["H1", "bootstrap", "granger", "ci95", "lo"], "num", 4, ci=["H1", "bootstrap", "granger", "ci95"])
S("H1_GR_HI", FIN, ["H1", "bootstrap", "granger", "ci95", "hi"], "num", 4, ci=["H1", "bootstrap", "granger", "ci95"])
S("H1_PC_DIFF", FIN, ["H1", "bootstrap", "partial_corr", "mean_diff"], "num", 4)
S("H1_PC_LO", FIN, ["H1", "bootstrap", "partial_corr", "ci95", "lo"], "num", 4, ci=["H1", "bootstrap", "partial_corr", "ci95"])
S("H1_PC_HI", FIN, ["H1", "bootstrap", "partial_corr", "ci95", "hi"], "num", 4, ci=["H1", "bootstrap", "partial_corr", "ci95"])
S("H1_LAG_OBS", REV, ["lagged_flow", "observed_wrmse"], "num", 4)
S("H1_LAG_GR", REV, ["lagged_flow", "granger_wrmse"], "num", 4)
S("F_TRUE", FIN, ["falsification", {"model": "true_direction"}, "rmse"], "num", 4)
S("F_REV", FIN, ["falsification", {"model": "reversed_edges"}, "rmse"], "num", 4)
S("F_SYM", FIN, ["falsification", {"model": "symmetric"}, "rmse"], "num", 4)
S("F_RMT_LO", FIN, ["falsification_ci", "reversed_minus_true", "ci95", "lo"], "num", 4,
  ci=["falsification_ci", "reversed_minus_true", "ci95"])
S("F_RMT_HI", FIN, ["falsification_ci", "reversed_minus_true", "ci95", "hi"], "num", 4,
  ci=["falsification_ci", "reversed_minus_true", "ci95"])
S("A3_RMT_LO", IAD, ["paired_bootstrap", "reversed_minus_true", "ci95", "lo"], "num", 4,
  ci=["paired_bootstrap", "reversed_minus_true", "ci95"])
S("A3_RMT_HI", IAD, ["paired_bootstrap", "reversed_minus_true", "ci95", "hi"], "num", 4,
  ci=["paired_bootstrap", "reversed_minus_true", "ci95"])
S("A3_SMT_LO", IAD, ["paired_bootstrap", "symmetric_minus_true", "ci95", "lo"], "num", 4,
  ci=["paired_bootstrap", "symmetric_minus_true", "ci95"])
S("A3_SMT_HI", IAD, ["paired_bootstrap", "symmetric_minus_true", "ci95", "hi"], "num", 4,
  ci=["paired_bootstrap", "symmetric_minus_true", "ci95"])
S("ET_CUST", REV, ["edge_type_falsification", "reverse_custodial"], "num", 4)
S("ET_COMP", REV, ["edge_type_falsification", "reverse_composability"], "num", 4)
S("ET_TRUE", REV, ["edge_type_falsification", "true"], "num", 4)

# multi-event
S("ME_FTX_ROLL_P", MEV, ["events", FTX, "placebo_rolling", "p_value"], "num", 3)
S("ME_SVB_ROLL_P", MEV, ["events", SVB, "placebo_rolling", "p_value"], "num", 3)
S("ME_FTX_OC_FTX_RLO", MEV, ["events", FTX, "oc_ranking", {"entity": "FTX"}, "rank_ci95", "lo"], "num", 0)
S("ME_FTX_OC_FTX_RHI", MEV, ["events", FTX, "oc_ranking", {"entity": "FTX"}, "rank_ci95", "hi"], "num", 0)
S("ME_FTX_OC_FTX_P3", MEV, ["events", FTX, "oc_ranking", {"entity": "FTX"}, "p_top3"], "num", 2)

# placebos and external validity
S("ROLL_P", FIN, ["placebo", "rolling_temporal", "p_value"], "num", 3)
S("ROLL_N", FIN, ["placebo", "rolling_temporal", "n_windows"], "num", 0)
S("TS_P", FIN, ["placebo", "time_shift", "p_value"], "num", 4)
S("SZ_CONN", FIN, ["placebo", "structural_zero_check", "n_connected_pairs"], "num", 0)
S("SZ_UNCONN", FIN, ["placebo", "structural_zero_check", "n_unconnected_pairs"], "num", 0)
S("EV_CONC", FIN, ["external_validity", "pairwise_concordance"], "num", 2)
S("EV_SEP", FIN, ["external_validity", "separation"], "num", 2)
S("EV_PALL", UNC, ["ranking", "external_validity", "p_all_transmitters_above_absorbers"], "num", 2)
S("EV_MCONC", UNC, ["ranking", "external_validity", "mean_concordance"], "num", 2)

# robustness
S("TK10_SP", TK, ["vs_main", "10", "spearman_common"], "num", 3)
S("TK15_SP", TK, ["vs_main", "15", "spearman_common"], "num", 3)
S("TK10_T3", TK, ["vs_main", "10", "top3_overlap"], "num", 0)
S("TK15_T3", TK, ["vs_main", "15", "top3_overlap"], "num", 0)
for k in ["10", "12", "15"]:
    S(f"TK{k}_CH", TK, ["by_k", k, "top_channels", {"i": "MakerSky", "j": "retail"}, "share"], "pct", 1)
S("RV_MR", FIN, ["confounding_sensitivity", "edges", {"edge": "MakerSky->retail"}, "robustness_value"], "num", 3)
S("RV_NDROP", REV3, ["drop_low_rv", "n_dropped"], "num", 0)
S("RV_DROP_SP", REV3, ["drop_low_rv", "ranking_spearman_vs_base"], "num", 3)
S("LS_MOD", REV3, ["latent_shock", "moderate", "ranking_spearman_vs_base"], "num", 3)
S("LS_STR", REV3, ["latent_shock", "strong", "ranking_spearman_vs_base"], "num", 3)
S("LS_T3", REV3, ["latent_shock", "moderate", "top3_overlap"], "num", 2)
S("RES_SP", FIN, ["resolution_robustness", "spearman"], "num", 3)
S("RES_P", FIN, ["resolution_robustness", "p_value"], "num", 3)
S("RES_N", FIN, ["resolution_robustness", "n_common"], "num", 0)
S("H3_SP", FIN, ["ranking_agreement", "spearman_oc_vs_deltacovar"], "num", 3)

# analytics (daily)
S("AN_T", ANA, ["T"], "num", 0)
S("AN_N", ANA, ["n_entities"], "num", 0)
S("AN_RHO", ANA, ["spectral_radius"], "num", 3)
S("AN_VIOL", ANA, ["n_violations"], "num", 0)
S("AN_NZERO", ANA, ["n_zero_predicted"], "num", 0)
S("AN_SUB13", ANA, ["evaluation_counts", {"p": 13}, "subsets"], "num", 0)
S("AN_PERM13", ANA, ["evaluation_counts", {"p": 13}, "permutations"], "num", 0)
S("ANA_P", ANA, ["retail_subset_timing_seconds", "p"], "num", 0)
S("AN_TIME", ANA, ["retail_subset_timing_seconds", "seconds"], "num", 2)
S("AN_SEED", ANA, ["shapley_verification", "seed"], "num", 0)
S("AN_EPS_RA", ANA, ["certified_radius", "pairs", {"pair": ["retail", "Aave"]}, "eps_star"], "num", 3)
S("AN_EPS_AL", ANA, ["certified_radius", "pairs", {"pair": ["Aave", "Lido"]}, "eps_star"], "num", 3)
S("AN_EPS_LM", ANA, ["certified_radius", "pairs", {"pair": ["Lido", "MakerSky"]}, "eps_star"], "num", 3)
S("AN_EPS_MC", ANA, ["certified_radius", "pairs", {"pair": ["MakerSky", "Copper"]}, "eps_star"], "num", 3)

# backtests
S("BT_BTC_KUP", FIN, ["backtests", "BTC", "kupiec", "p_value"], "num", 3)
S("BT_ETH_KUP", FIN, ["backtests", "ETH", "kupiec", "p_value"], "num", 3)
S("BT_BTC_CC", FIN, ["backtests", "BTC", "christoffersen", "p_value_cc"], "num", 3)
S("BT_ETH_CC", FIN, ["backtests", "ETH", "christoffersen", "p_value_cc"], "num", 3)
S("BT_N", FIN, ["backtests", "BTC", "kupiec", "n"], "num", 0)
S("BTD_N", RES_J, ["backtests", "BTC", "kupiec", "n"], "num", 0)
S("BTD_BTC_KUP", RES_J, ["backtests", "BTC", "kupiec", "p_value"], "num", 3)
S("BTD_ETH_KUP", RES_J, ["backtests", "ETH", "kupiec", "p_value"], "num", 3)

# Tier-1/2
ERV = ["entity_resolution_validation"]
S("T1_N", RES_J, ERV + ["n_addresses"], "num", 0)
S("T1_NCEX", RES_J, ERV + ["n_cex_labeled"], "num", 0)
S("T1_BASE", RES_J, ERV + ["tier1_classifier", "base_rate"], "pct", 1)
S("T1_AUC", RES_J, ERV + ["tier1_classifier", "test_auc"], "num", 2)
S("T1_AP", RES_J, ERV + ["tier1_classifier", "test_avg_precision"], "num", 2)
S("T1_PREC", RES_J, ERV + ["tier1_classifier", "precision_at_bestF1"], "num", 2)
S("T1_REC", RES_J, ERV + ["tier1_classifier", "recall_at_bestF1"], "num", 2)
S("T1_VPREC", RES_J, ERV + ["tier1_classifier", "vol_weighted_precision_at_bestF1"], "num", 2)
S("T1_VREC", RES_J, ERV + ["tier1_classifier", "vol_weighted_recall_at_bestF1"], "num", 2)
S("T2_HOM", RES_J, ERV + ["tier2_embedding", "cex_cluster_homogeneity"], "num", 2)


def spec_by_id(eid):
    for s in SPEC:
        if s[0] == eid:
            return s
    return None


def render_spec(eid):
    s = spec_by_id(eid)
    if s is None:
        raise KeyError(eid)
    _, file, path, fmt, dec, ci = s
    return reg_path(eid, file, path, fmt, dec, ci)


# ---------------------------------------------------------------- derived (class D) and constants (class S)
def derived(eid):
    """Return tex for derived numbers, registering manual entries."""
    if eid in VALUES:
        return VALUES[eid][1]
    unc, oos, fin = J(UNC), J(OOS), J(FIN)
    if eid == "R2_MIN":
        r2 = {k: v["point"] for k, v in unc["attribution"]["r2_in_sample"].items()}
        ent, val = min(r2.items(), key=lambda kv: kv[1])
        return reg_manual(eid, "D", fmt_plain(val, 3), 3, UNC,
                          "attribution/r2_in_sample/*/point, minimum", f"min over 15 entities ({ent})")
    if eid == "R2_MIN_ENT":
        r2 = {k: v["point"] for k, v in unc["attribution"]["r2_in_sample"].items()}
        ent = min(r2.items(), key=lambda kv: kv[1])[0]
        return reg_string(eid, "D", ent, UNC, "attribution/r2_in_sample/*/point argmin")
    if eid == "OOS_GAIN_NET_ABS":
        raise KeyError
    if eid == "AAVE_SSE_SHARE":
        sse = {k: v["sse_mean"] for k, v in oos["by_entity"].items()}
        total = sum(sse.values())
        val = 100.0 * sse["Aave"] / total
        return reg_manual(eid, "D", fmt_plain(val, 1), 1, OOS,
                          "by_entity/*/sse_mean; pooled SSE sum",
                          f"100 * by_entity/Aave/sse_mean / sum over 15 entities of sse_mean = {val:.4f}")
    if eid in ("OOS_OTHER_MIN", "OOS_OTHER_MAX"):
        others = {k: 100.0 * v["ar_network_vs_ar"] for k, v in oos["by_entity"].items()
                  if k not in ("retail", "Coinbase")}
        if eid == "OOS_OTHER_MIN":
            k, val = min(others.items(), key=lambda kv: kv[1])
        else:
            k, val = max(others.items(), key=lambda kv: kv[1])
        return reg_manual(eid, "D", fmt_plain(val, 1), 1, OOS,
                          "by_entity/*/ar_network_vs_ar excluding retail and Coinbase",
                          f"{'min' if eid.endswith('MIN') else 'max'} over 13 entities (argmax/argmin {k})")
    if eid in ("PW_MIN_3TO6", "PW_MAX_3TO6"):
        pw = unc["ranking"]["pairwise_top6"]
        names = pw["entities"]
        block = [i for i, n in enumerate(names) if n in ("Bitfinex", "Coinbase", "Kraken", "Crypto.com")]
        vals = [pw["p_row_above_col"][i][j] for i in block for j in block if i != j]
        val = min(vals) if eid.endswith("MIN_3TO6") else max(vals)
        return reg_manual(eid, "D", fmt_plain(val, 2), 2, UNC,
                          "ranking/pairwise_top6/p_row_above_col, off-diagonal entries with row and column in ranks 3-6",
                          f"{'min' if 'MIN' in eid else 'max'} over {len(vals)} off-diagonal cells")
    if eid in ("RV_MIN", "RV_MAX"):
        vals = [e["robustness_value"] for e in fin["confounding_sensitivity"]["edges"]]
        val = min(vals) if eid == "RV_MIN" else max(vals)
        return reg_manual(eid, "D", fmt_plain(val, 3), 3, FIN,
                          "confounding_sensitivity/edges/*/robustness_value",
                          f"{'min' if eid == 'RV_MIN' else 'max'} over {len(vals)} edges")
    if eid == "RECVOL_MAX":
        vals = [J(DBD)["sweeps"]["validation"][x][J(DBD)["sweeps"]["validation"][x]["chosen"]]["recall_volume"]
                for x in EXTRACTS]
        return reg_manual(eid, "D", fmt_plain(100 * max(vals), 1), 1, DBD,
                          "sweeps/validation/*/<chosen>/recall_volume",
                          "100 * max over the four extracts")
    if eid in ("COV_MIN", "COV_MAX"):
        cov = J(COV)
        vals = [cov[x]["panel_tokens"]["named_distinct_share_of_touching"] for x in cov
                if isinstance(cov[x], dict) and "panel_tokens" in cov[x]]
        val = min(vals) if eid == "COV_MIN" else max(vals)
        return reg_manual(eid, "D", fmt_plain(100 * val, 1), 1, COV,
                          "*/panel_tokens/named_distinct_share_of_touching",
                          f"100 * {'min' if eid == 'COV_MIN' else 'max'} over {len(vals)} extracts")
    if eid == "USDE_MAXREL":
        val = max(abs(x["rel_diff"]) for x in J(DBD)["usde_daily"])
        return reg_manual(eid, "D", fmt_plain(100 * val, 2), 2, DBD,
                          "usde_daily/*/rel_diff", "100 * max |rel_diff| over six days")
    if eid == "H3_N":
        return reg_manual(eid, "D", str(len(fin["ranking_agreement"]["entities"])), 0, FIN,
                          "ranking_agreement/entities", "length of the entity list")
    if eid == "TS_FLOOR":
        B = fin["placebo"]["time_shift"]["B"]
        return reg_manual(eid, "D", fmt_plain(1.0 / (B + 1), 4), 4, FIN,
                          "placebo/time_shift/B", f"1/(B+1) with B={B}")
    if eid == "PL_START":
        return reg_manual(eid, "S", "72", 0, "vein/validation.py",
                          "rolling_temporal_placebo: roll=48 (line 366) plus gap=24 (line 366)", "48 + 24")
    # --- class S code constants and parsed strings
    if eid == "RIDGE_ALPHA":
        m = re.search(r"alpha=([0-9.]+)", unc["settings"]["coefficients"])
        return reg_manual(eid, "S", m.group(1), 0, UNC, "settings/coefficients (string)", "parsed alpha",
                          group=False)
    if eid == "PL_STEP":
        return reg_manual(eid, "S", "24", 0, "vein/validation.py", "rolling_temporal_placebo step=24 (line 365)", "code constant")
    if eid == "PL_GAP":
        return reg_manual(eid, "S", "24", 0, "vein/validation.py", "rolling_temporal_placebo gap=24 (line 366)", "code constant")
    if eid == "TS_MIN":
        return reg_manual(eid, "S", "72", 0, "vein/validation.py", "time_shift_placebo min_shift=72 (line 406)", "code constant")
    if eid == "PL_THRESH":
        return reg_manual(eid, "S", "0.10", 2, "vein/validation.py", "rolling_temporal_placebo pass rule p<=0.10 (line 401)", "code constant")
    if eid == "TS_THRESH":
        return reg_manual(eid, "S", "0.05", 2, "vein/validation.py", "time_shift_placebo pass rule p<=0.05 (line 438)", "code constant")
    if eid == "ROLL":
        return reg_manual(eid, "S", "48", 0, "vein/hourly_stress.py", "ROLL = 48 (line 29)", "code constant")
    if eid == "MINP":
        return reg_manual(eid, "S", "6", 0, "vein/hourly_stress.py", "zscore min_periods=6 (line 34)", "code constant")
    if eid == "W_NET":
        return reg_manual(eid, "S", "0.6", 1, "vein/hourly_stress.py", "flow component weight (line 45)", "code constant")
    if eid == "W_TOT":
        return reg_manual(eid, "S", "0.4", 1, "vein/hourly_stress.py", "flow component weight (line 45)", "code constant")
    if eid == "RMSE_EPS":
        return reg_manual(eid, "S", "0.1", 1, "vein/validation.py", "weight |y|+0.1 (line 327)", "code constant")
    if eid == "SD_PERT":
        return reg_manual(eid, "S", "0.15", 2, "run_revision.py", "relative coefficient noise (line 169)", "code constant")
    if eid in ("PREC_ACCEPT", "OVL_MIN"):
        acc = J(DBD)["sweeps"]["validation"]["oct25_hourly"]["acceptance"]
        m = re.search(r"precision >= ([0-9.]+) on >= (\d+)", acc)
        val = m.group(1) if eid == "PREC_ACCEPT" else m.group(2)
        return reg_manual(eid, "S", val, 1 if eid == "PREC_ACCEPT" else 0, DBD,
                          "sweeps/validation/oct25_hourly/acceptance (string)", "parsed acceptance rule")
    if eid in ("SHA_ETHLABELS", "SHA_ETHERSCAN", "SHA_SPELLBOOK"):
        key = {"SHA_ETHLABELS": "eth-labels", "SHA_ETHERSCAN": "etherscan-labels", "SHA_SPELLBOOK": "spellbook"}[eid]
        sha = J(DBD)["labels"]["revisions"][key]
        return reg_string(eid, "S", sha, DBD, f"labels/revisions/{key}")
    if eid.startswith("SH_") and eid.endswith(("_LO", "_HI")):
        player = {"SH_BIN": "Binance", "SH_COI": "Coinbase", "SH_BFX": "Bitfinex"}[eid[:-3]]
        lo_hi = unc["attribution"]["shapley_bybit"]["ci95"][player]
        val = lo_hi[0] if eid.endswith("_LO") else lo_hi[1]
        return reg_manual(eid, "S", fmt_plain(val, 2), 2, UNC,
                          f"attribution/shapley_bybit/ci95/{player}[{0 if eid.endswith('_LO') else 1}]",
                          "string key then position; not expressible as a list path")
    if eid == "PW_RETAIL_MAKER":
        pw = unc["ranking"]["pairwise_top6"]
        i, j = pw["entities"].index("retail"), pw["entities"].index("MakerSky")
        val = pw["p_row_above_col"][i][j]
        return reg_manual(eid, "P", fmt_plain(val, 2), 2, UNC,
                          f"ranking/pairwise_top6/p_row_above_col row retail (index {i}), column MakerSky (index {j})",
                          "nested-list element")
    raise KeyError(f"no derived rule for {eid}")


# ---------------------------------------------------------------- table generators (cells registered)
CELL_N = {"n": 0}


def cell(prefix, file, path, fmt="num", dec=2, ci=None):
    CELL_N["n"] += 1
    eid = f"{prefix}_{CELL_N['n']:04d}"
    return reg_path(eid, file, path, fmt, dec, ci)


def status_label(status, base_name):
    return {"observed_better": "base better", "estimated_better": "alt better",
            "inconclusive": "inconclusive"}.get(status, status)


def ent_rows_sorted(d, key):
    return sorted(d.items(), key=key)


def tbl_samples():
    fin, mev, cov = J(FIN), J(MEV), J(COV)
    rows = []
    rows.append(("Oct 2025 (hourly)",
                 cell("SAMP", FIN, ["n_fit_hours"], "num", 0),
                 cell("SAMP", FIN, ["n_event_hours"], "num", 0),
                 cell("SAMP", FIN, ["n_entities"], "num", 0),
                 cell("SAMP", FIN, ["graph_edges"], "num", 0),
                 cell("SAMP", COV, ["oct25_hourly", "panel_tokens", "named_distinct_share_of_touching"], "pct", 1)))
    for ev, cov_key, label in [(FTX, "ftx_ext", "FTX, Nov 2022 (hourly)"), (SVB, "svb_ext", "USDC/SVB, Mar 2023 (hourly)")]:
        rows.append((label,
                     cell("SAMP", MEV, ["events", ev, "n_fit_rows"], "num", 0),
                     cell("SAMP", MEV, ["events", ev, "n_event_rows"], "num", 0),
                     cell("SAMP", MEV, ["events", ev, "n_entities"], "num", 0),
                     cell("SAMP", MEV, ["events", ev, "n_edges"], "num", 0),
                     cell("SAMP", COV, [cov_key, "panel_tokens", "named_distinct_share_of_touching"], "pct", 1)))
    return "\n".join(f"{a} & {b} & {c} & {d} & {e} & {f} \\\\" for a, b, c, d, e, f in rows)


def tbl_explained():
    unc = J(UNC)
    r2 = unc["attribution"]["r2_in_sample"]
    order = sorted(r2.keys(), key=lambda e: -r2[e]["point"])
    out = []
    for e in order:
        p = f"T2{san(e)}"
        a = cell(p + "R2", UNC, ["attribution", "r2_in_sample", e, "point"], "num", 3)
        ci_lo = cell(p + "C", UNC, ["attribution", "r2_in_sample", e, "optimism_corrected_ci95", "lo"], "num", 3)
        ci_hi = cell(p + "C", UNC, ["attribution", "r2_in_sample", e, "optimism_corrected_ci95", "hi"], "num", 3)
        c_pt = cell(p + "O", UNC, ["attribution", "r2_in_sample", e, "point_optimism_corrected"], "num", 3)
        ar = cell(p + "A", OOS, ["by_entity", e, "ar"], "num", 3)
        net = cell(p + "N", OOS, ["by_entity", e, "network"], "num", 3)
        arnet = cell(p + "G", OOS, ["by_entity", e, "ar_network_vs_ar"], "pct", 1)
        name = e.replace("&", "\\&")
        out.append(f"{name} & {a} & {c_pt} [{ci_lo}, {ci_hi}] & {ar} & {net} & {arnet} \\\\")
    pa = cell("T2POOL", OOS, ["pooled", "ar", "r2_os"], "num", 3)
    pn = cell("T2POOL", OOS, ["pooled", "network", "r2_os"], "num", 3)
    pg = cell("T2POOL", OOS, ["increment_over_ar", "ar_network", "gain"], "pct", 1)
    out.append("\\midrule")
    out.append(f"Pooled (out of sample) & -- & -- & {pa} & {pn} & {pg} \\\\")
    return "\n".join(out)


def tbl_abduction():
    v1 = J(V1)["counterfactual_attribution"]
    v2 = J(V2)["counterfactual_attribution"]
    sel = {"i": "Binance", "j": "Bybit"}
    rows = []
    rows.append(("v1 (earlier extract)", "zero-shock",
                 cell("ABD", V1, ["counterfactual_attribution", sel, "L_observed"], "num", 2),
                 cell("ABD", V1, ["counterfactual_attribution", sel, "attribution"], "num", 2),
                 cell("ABD", V1, ["counterfactual_attribution", sel, "attribution_share"], "pct", 1)))
    rows.append(("v3 (current build)", "zero-shock",
                 cell("ABD", ABD, ["modes", {"abduction": "legacy_zero"}, "bybit_L_observed"], "num", 2),
                 cell("ABD", ABD, ["modes", {"abduction": "legacy_zero"}, "binance_to_bybit", "attribution"], "num", 2),
                 cell("ABD", ABD, ["modes", {"abduction": "legacy_zero"}, "binance_to_bybit", "share"], "pct", 1)))
    rows.append(("v3 (current build)", "full",
                 cell("ABD", ABD, ["modes", {"abduction": "full"}, "bybit_L_observed"], "num", 2),
                 cell("ABD", ABD, ["modes", {"abduction": "full"}, "binance_to_bybit", "attribution"], "num", 2),
                 cell("ABD", ABD, ["modes", {"abduction": "full"}, "binance_to_bybit", "share"], "pct", 1)))
    rows.append(("v2 (earlier BigQuery build)", "full",
                 cell("ABD", V2, ["counterfactual_attribution", sel, "L_observed"], "num", 2),
                 cell("ABD", V2, ["counterfactual_attribution", sel, "attribution"], "num", 2),
                 cell("ABD", V2, ["counterfactual_attribution", sel, "attribution_share"], "pct", 1)))
    return "\n".join(f"{a} & {b} & {c} & {d} & {e} \\\\" for a, b, c, d, e in rows)


def tbl_channels():
    unc = J(UNC)
    chans = unc["attribution"]["channels"]
    out = []
    for idx, c in enumerate(chans):
        i, j = c["i"], c["j"]
        sel = {"i": i, "j": j}
        typ = "named$\\to$named" if (i != "retail" and j != "retail") else ("$\\to$retail" if j == "retail" else "retail$\\to$")
        if i == "retail" and j != "retail":
            typ = "retail$\\to$"
        attr = cell("CH", UNC, ["attribution", "channels", sel, "attribution"], "num", 2)
        sh = cell("CH", UNC, ["attribution", "channels", sel, "share"], "pct", 1)
        lo = cell("CH", UNC, ["attribution", "channels", sel, "share_ci95", "lo"], "pct", 1,
                  ci=["attribution", "channels", sel, "share_ci95"])
        hi = cell("CH", UNC, ["attribution", "channels", sel, "share_ci95", "hi"], "pct", 1,
                  ci=["attribution", "channels", sel, "share_ci95"])
        pp = cell("CH", UNC, ["attribution", "channels", sel, "p_positive"], "num", 2)
        out.append(f"{i}$\\to${j} & {typ} & {attr} & {sh} & [{lo}, {hi}] & {pp} \\\\")
        if idx == 9:
            out.append("\\midrule")
    return "\n".join(out)


def tbl_rank():
    unc = J(UNC)
    pts = sorted(unc["ranking"]["point"], key=lambda p: p["rank"])
    out = []
    for p in pts:
        e = p["entity"]
        sel = {"entity": e}
        rk = cell("RK", UNC, ["ranking", "point", sel, "rank"], "num", 0)
        er = cell("RK", UNC, ["ranking", "point", sel, "exported_risk"], "num", 2)
        se = cell("RK", UNC, ["ranking", "point", sel, "mc_se"], "num", 2)
        rl = cell("RK", UNC, ["ranking", "by_entity", e, "exported_risk_ci95", "lo"], "num", 2,
                  ci=["ranking", "by_entity", e, "exported_risk_ci95"])
        rh = cell("RK", UNC, ["ranking", "by_entity", e, "exported_risk_ci95", "hi"], "num", 2,
                  ci=["ranking", "by_entity", e, "exported_risk_ci95"])
        kl = cell("RK", UNC, ["ranking", "by_entity", e, "rank_ci95", "lo"], "num", 0)
        kh = cell("RK", UNC, ["ranking", "by_entity", e, "rank_ci95", "hi"], "num", 0)
        p1 = cell("RK", UNC, ["ranking", "by_entity", e, "p_top1"], "num", 2)
        p3 = cell("RK", UNC, ["ranking", "by_entity", e, "p_top3"], "num", 2)
        out.append(f"{rk} & {e} & {er} & {se} & [{rl}, {rh}] & [{kl}, {kh}] & {p1} & {p3} \\\\")
    return "\n".join(out)


def tbl_diagnostics():
    fin, rev, mev, iad = J(FIN), J(REV), J(MEV), J(IAD)
    out = []

    def h1_row(label, model_key, boot_key):
        n = cell("DG", FIN, ["H1", "scores", {"model": "observed_onchain"}, "n"], "num", 0)
        b = cell("DG", FIN, ["H1", "scores", {"model": "observed_onchain"}, "rmse"], "num", 4)
        a = cell("DG", FIN, ["H1", "scores", {"model": model_key}, "rmse"], "num", 4)
        md = cell("DG", FIN, ["H1", "bootstrap", boot_key, "mean_diff"], "num", 4)
        lo = cell("DG", FIN, ["H1", "bootstrap", boot_key, "ci95", "lo"], "num", 4, ci=["H1", "bootstrap", boot_key, "ci95"])
        hi = cell("DG", FIN, ["H1", "bootstrap", boot_key, "ci95", "hi"], "num", 4, ci=["H1", "bootstrap", boot_key, "ci95"])
        st = status_label(fin["H1"]["bootstrap"][boot_key]["status"], "observed")
        return f"{label} & Oct 2025 & {n} & {b} & {a} & {md} & [{lo}, {hi}] & {st} \\\\"

    out.append(h1_row("H1: observed vs Granger", "estimated_granger", "granger"))
    out.append(h1_row("H1: observed vs partial correlation", "estimated_partial_corr", "partial_corr"))
    out.append("\\midrule")

    # Oct main
    def falrow(label, window, file, base, alt, ci_file, ci_prefix, nfile, npath, ci_name, status_obj_fn):
        n = cell("DG", nfile, npath, "num", 0)
        b = cell("DG", file, base[0], "num", 4)
        a = cell("DG", file, alt[0], "num", 4)
        md = cell("DG", ci_file, ci_prefix + [ci_name, "mean_diff"], "num", 4)
        lo = cell("DG", ci_file, ci_prefix + [ci_name, "ci95", "lo"], "num", 4, ci=ci_prefix + [ci_name, "ci95"])
        hi = cell("DG", ci_file, ci_prefix + [ci_name, "ci95", "hi"], "num", 4, ci=ci_prefix + [ci_name, "ci95"])
        st = status_label(status_obj_fn()["status"], "base")
        return f"{label} & {window} & {n} & {b} & {a} & {md} & [{lo}, {hi}] & {st} \\\\"

    out.append(falrow("Reversed vs true", "Oct 2025", FIN, [["falsification", {"model": "true_direction"}, "rmse"]],
                      [["falsification", {"model": "reversed_edges"}, "rmse"]], FIN, ["falsification_ci"],
                      FIN, ["falsification", {"model": "true_direction"}, "n"], "reversed_minus_true",
                      lambda: fin["falsification_ci"]["reversed_minus_true"]))
    out.append(falrow("Symmetric vs true", "Oct 2025", FIN, [["falsification", {"model": "true_direction"}, "rmse"]],
                      [["falsification", {"model": "symmetric"}, "rmse"]], FIN, ["falsification_ci"],
                      FIN, ["falsification", {"model": "true_direction"}, "n"], "symmetric_minus_true",
                      lambda: fin["falsification_ci"]["symmetric_minus_true"]))
    out.append("\\midrule")
    # intraday
    n_iad = "n_predictions"
    for label, key, ci_name in [("Reversed vs true", "reversed_edges", "reversed_minus_true"),
                                ("Symmetric vs true", "symmetric", "symmetric_minus_true")]:
        n = cell("DG", IAD, ["n_predictions"], "num", 0)
        b = cell("DG", IAD, ["falsification", {"model": "true_direction"}, "rmse"], "num", 4)
        a = cell("DG", IAD, ["falsification", {"model": key}, "rmse"], "num", 4)
        md = cell("DG", IAD, ["paired_bootstrap", ci_name, "mean_diff"], "num", 4)
        lo = cell("DG", IAD, ["paired_bootstrap", ci_name, "ci95", "lo"], "num", 4, ci=["paired_bootstrap", ci_name, "ci95"])
        hi = cell("DG", IAD, ["paired_bootstrap", ci_name, "ci95", "hi"], "num", 4, ci=["paired_bootstrap", ci_name, "ci95"])
        st = status_label(iad["paired_bootstrap"][ci_name]["status"], "base")
        out.append(f"{label} & Intraday A3 & {n} & {b} & {a} & {md} & [{lo}, {hi}] & {st} \\\\")
    out.append("\\midrule")
    for ev_key, ev_label in [(FTX, "FTX, Nov 2022"), (SVB, "USDC/SVB, Mar 2023")]:
        for model, ci_name, label in [("reversed_edges", "reversed_minus_true", "Reversed vs true"),
                                      ("symmetric", "symmetric_minus_true", "Symmetric vs true")]:
            n = cell("DG", MEV, ["events", ev_key, "falsification", {"model": "true_direction"}, "n"], "num", 0)
            b = cell("DG", MEV, ["events", ev_key, "falsification", {"model": "true_direction"}, "rmse"], "num", 4)
            a = cell("DG", MEV, ["events", ev_key, "falsification", {"model": model}, "rmse"], "num", 4)
            md = cell("DG", MEV, ["events", ev_key, "falsification_ci", ci_name, "mean_diff"], "num", 4)
            lo = cell("DG", MEV, ["events", ev_key, "falsification_ci", ci_name, "ci95", "lo"], "num", 4,
                      ci=[ev_key, "falsification_ci", ci_name, "ci95"])
            hi = cell("DG", MEV, ["events", ev_key, "falsification_ci", ci_name, "ci95", "hi"], "num", 4,
                      ci=[ev_key, "falsification_ci", ci_name, "ci95"])
            st = status_label(
                next(e for e in mev["events"] if e["event"] == ev_key["event"])["falsification_ci"][ci_name]["status"], "base")
            out.append(f"{label} & {ev_label} & {n} & {b} & {a} & {md} & [{lo}, {hi}] & {st} \\\\")
    return "\n".join(out)


def tbl_events():
    unc, mev, fin = J(UNC), J(MEV), J(FIN)
    out = []

    def top3_uncert():
        pts = sorted(unc["ranking"]["point"], key=lambda p: p["rank"])[:3]
        parts = []
        for p in pts:
            e = p["entity"]
            lo = cell("EV", UNC, ["ranking", "by_entity", e, "rank_ci95", "lo"], "num", 0)
            hi = cell("EV", UNC, ["ranking", "by_entity", e, "rank_ci95", "hi"], "num", 0)
            pp = cell("EV", UNC, ["ranking", "by_entity", e, "p_top3"], "num", 2)
            parts.append(f"{e} rank [{lo}, {hi}], $P$ = {pp}")
        return "; ".join(parts)

    def top3_event(ev_key):
        ev = next(e for e in mev["events"] if e["event"] == ev_key)
        ranked = sorted(ev["oc_ranking"], key=lambda r: -r["exported_risk"])[:3]
        parts = []
        for r in ranked:
            e = r["entity"]
            lo = cell("EV", MEV, ["events", {"event": ev_key}, "oc_ranking", {"entity": e}, "rank_ci95", "lo"], "num", 0)
            hi = cell("EV", MEV, ["events", {"event": ev_key}, "oc_ranking", {"entity": e}, "rank_ci95", "hi"], "num", 0)
            pp = cell("EV", MEV, ["events", {"event": ev_key}, "oc_ranking", {"entity": e}, "p_top3"], "num", 2)
            parts.append(f"{e} rank [{lo}, {hi}], $P$ = {pp}")
        return "; ".join(parts)

    # Oct
    p = cell("EV", FIN, ["placebo", "rolling_temporal", "p_value"], "num", 3)
    n = cell("EV", FIN, ["placebo", "rolling_temporal", "n_windows"], "num", 0)
    rv = fin["falsification_ci"]["reversed_minus_true"]["status"]
    sy = fin["falsification_ci"]["symmetric_minus_true"]["status"]
    out.append(f"Oct 2025 & {top3_uncert()} & {p} ({n}) & {status_label(rv, 'base')} & {status_label(sy, 'base')} \\\\")
    for ev_key, label in [("FTX_Nov2022", "FTX, Nov 2022"), ("USDC_SVB_Mar2023", "USDC/SVB, Mar 2023")]:
        ev = next(e for e in mev["events"] if e["event"] == ev_key)
        p = cell("EV", MEV, ["events", {"event": ev_key}, "placebo_rolling", "p_value"], "num", 3)
        n = cell("EV", MEV, ["events", {"event": ev_key}, "placebo_rolling", "n_windows"], "num", 0)
        rvs = ev["falsification_ci"]["reversed_minus_true"]["status"]
        sys_ = ev["falsification_ci"]["symmetric_minus_true"]["status"]
        out.append(f"{label} & {top3_event(ev_key)} & {p} ({n}) & {status_label(rvs, 'base')} & {status_label(sys_, 'base')} \\\\")
    return "\n".join(out)


def tbl_tier0():
    v = J(DBD)["sweeps"]["validation"]
    labels = {"oct25_hourly": "Oct 2025 (hourly)", "ftx_hourly": "FTX (hourly)",
              "svb_hourly": "USDC/SVB (hourly)", "core_daily": "Daily core"}
    out = []
    for x in EXTRACTS:
        ch = v[x]["chosen"]
        base = f"{v[x]['chosen']}"
        pref = f"T0{san(x)}"
        ho = cell(pref, DBD, ["sweeps", "validation", x, "holdout_addresses"], "num", 0)
        tau = cell(pref, DBD, ["sweeps", "validation", x, ch, "params", "tau"], "num", 1)
        ov = cell(pref, DBD, ["sweeps", "validation", x, ch, "overlap"], "num", 0)
        wr = cell(pref, DBD, ["sweeps", "validation", x, ch, "wrong_root"], "num", 0)
        pr = cell(pref, DBD, ["sweeps", "validation", x, ch, "precision"], "num", 2)
        rc_ = cell(pref, DBD, ["sweeps", "validation", x, ch, "recall_count"], "pct", 1)
        rv = cell(pref, DBD, ["sweeps", "validation", x, ch, "recall_volume"], "pct", 1)
        out.append(f"{labels[x]} & {ch} & {tau} & {ho} & {ov} & {wr} & {pr} & {rc_} & {rv} \\\\")
    return "\n".join(out)


def tbl_resval():
    rows = [("Addresses (USDe window, sentinel excluded)", "T1_N", None),
            ("CEX-labelled addresses (base rate, \\%)", "T1_NCEX", "T1_BASE"),
            ("Held-out ROC-AUC", "T1_AUC", None),
            ("Average precision", "T1_AP", None),
            ("Best-$F_1$ precision / recall (by count)", "T1_PREC", "T1_REC"),
            ("Precision / recall at the same threshold (by USD volume)", "T1_VPREC", "T1_VREC"),
            ("Tier-2 cluster homogeneity", "T2_HOM", None)]
    out = []
    for label, a, b in rows:
        ta = render_spec(a)
        if b is None:
            out.append(f"{label} & {ta} \\\\")
        else:
            tb = render_spec(b)
            out.append(f"{label} & {ta} / {tb} \\\\")
    return "\n".join(out)


def tbl_bounds():
    an = J(ANA)
    out = []
    bounded = [b for b in an["bounds"] if b["status"] == "bounded"]
    bounded.sort(key=lambda b: -b["stored_E"])
    for b in bounded:
        e = b["entity"]
        se = cell("BD", ANA, ["bounds", {"entity": e}, "stored_E"], "num", 3)
        bp = cell("BD", ANA, ["bounds", {"entity": e}, "B_plus_per_unit"], "num", 3)
        im = cell("BD", ANA, ["bounds", {"entity": e}, "implied_min_s_star"], "num", 2)
        mu = cell("BD", ANA, ["bounds", {"entity": e}, "infinite_horizon_multiplier"], "num", 3)
        out.append(f"{e} & {se} & {bp} & {im} & {mu} \\\\")
    return "\n".join(out)


def entity_list_text():
    fin = J(FIN)
    names = sorted([r["entity"] for r in fin["oc_covar_ranking"]], key=lambda s: s.lower())
    if len(names) < 2:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


TABLES = {
    "TBL_SAMPLES": tbl_samples, "TBL_EXPLAINED": tbl_explained, "TBL_ABDUCTION": tbl_abduction,
    "TBL_CHANNELS": tbl_channels, "TBL_RANK": tbl_rank, "TBL_DIAGNOSTICS": tbl_diagnostics,
    "TBL_EVENTS": tbl_events, "TBL_TIER0": tbl_tier0, "TBL_RESVAL": tbl_resval, "TBL_BOUNDS": tbl_bounds,
}

STRINGS = {"ENTITY_LIST": lambda: entity_list_text()}

DERIVED_IDS = {"R2_MIN", "R2_MIN_ENT", "AAVE_SSE_SHARE", "OOS_OTHER_MIN", "OOS_OTHER_MAX",
               "PW_MIN_3TO6", "PW_MAX_3TO6", "RV_MIN", "RV_MAX", "RECVOL_MAX", "COV_MIN", "COV_MAX",
               "USDE_MAXREL", "H3_N", "TS_FLOOR", "PL_START", "RIDGE_ALPHA", "PL_STEP", "PL_GAP", "TS_MIN",
               "PL_THRESH", "TS_THRESH", "ROLL", "MINP", "W_NET", "W_TOT", "RMSE_EPS", "SD_PERT",
               "PREC_ACCEPT", "OVL_MIN", "SHA_ETHLABELS", "SHA_ETHERSCAN", "SHA_SPELLBOOK",
               "SH_BIN_LO", "SH_BIN_HI", "SH_COI_LO", "SH_COI_HI", "SH_BFX_LO", "SH_BFX_HI", "PW_RETAIL_MAKER"}


def token_value(eid):
    if eid in TABLES or eid in STRINGS:
        raise KeyError(eid)
    if eid in DERIVED_IDS:
        return derived(eid)
    if eid in VALUES:
        return VALUES[eid][1]
    if spec_by_id(eid) is not None:
        return render_spec(eid)
    # per-extract Tier-0 tokens
    m = re.fullmatch(r"(OVL|PREC|RECVOL|RECCNT|DET|HOLDOUT)_(oct25_hourly|ftx_hourly|svb_hourly|core_daily)", eid)
    if m:
        kind, x = m.groups()
        chosen = J(DBD)["sweeps"]["validation"][x]["chosen"]
        field = {"OVL": ("overlap", "num", 0), "PREC": ("precision", "num", 2),
                 "RECVOL": ("recall_volume", "pct", 1), "RECCNT": ("recall_count", "pct", 1),
                 "DET": ("detections", "num", 0), "HOLDOUT": (None, "num", 0)}[kind]
        if field[0] is None:
            return reg_path(eid, DBD, ["sweeps", "validation", x, "holdout_addresses"], "num", 0)
        return reg_path(eid, DBD, ["sweeps", "validation", x, chosen, field[0]], field[1], field[2])
    raise KeyError(f"unknown token {eid}")


# ---------------------------------------------------------------- templating
TOK = re.compile(r"@@([A-Za-z0-9_]+)@@")


def render_text(template):
    missing = []

    def sub(m):
        eid = m.group(1)
        if eid in TABLES:
            return TABLES[eid]()
        if eid in STRINGS:
            return STRINGS[eid]()
        try:
            return token_value(eid)
        except KeyError as ex:
            missing.append(eid)
            return f"<<MISSING {eid}>>"

    out = TOK.sub(sub, template)
    if missing:
        raise SystemExit(f"unresolved tokens: {sorted(set(missing))}")
    return out


def anchors_for(template):
    """Tex anchor: up to 8 words around the first occurrence of each token, with printed value."""
    plain_src = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^{}]*\})?", " ", template)
    plain_src = plain_src.replace("$", " ").replace("{", " ").replace("}", " ").replace("~", " ")
    res = {}
    words = re.split(r"\s+", plain_src)
    joined = []
    for w in words:
        joined.append(w)
    for idx, w in enumerate(words):
        for m in TOK.finditer(w):
            eid = m.group(1)
            if eid in res or eid in TABLES or eid in STRINGS:
                continue
            lo = max(0, idx - 4)
            hi = min(len(words), idx + 4)
            span = " ".join(words[lo:hi])
            span = re.sub(r"@@([A-Za-z0-9_]+)@@", lambda mm: VALUES.get(mm.group(1), ("?", "?"))[0]
                          if mm.group(1) in VALUES else mm.group(0), span)
            res[eid] = span.strip()
    return res


def fill_anchor_entries(template_for_anchor):
    anc = anchors_for(template_for_anchor)
    for ent in ENTRIES:
        if ent["id"] in anc:
            ent["tex_anchor"] = anc[ent["id"]]
    for man in MANUAL:
        if man["id"] in anc:
            man["tex_anchor"] = anc[man["id"]]
        else:
            man["tex_anchor"] = man["id"].replace("_", " ").lower()


TABLE_PREFIX = [("T2POOL", "tab:explained pooled"), ("T2", "tab:explained"), ("ABD", "tab:abduction"),
                ("CH", "tab:channels"), ("RK", "tab:rank"), ("DG", "tab:diagnostics"), ("EV", "tab:events"),
                ("T0", "tab:tier0"), ("BD", "tab:bounds"), ("SAMP", "tab:samples")]


def table_anchor(ent):
    """Anchor for a table cell: table label plus the selector values and last key of its path."""
    eid = ent["id"]
    for pre, label in TABLE_PREFIX:
        if re.fullmatch(pre + r"[A-Z0-9]*_\d{4}", eid):
            words = [label]
            for p in ent["path"]:
                if isinstance(p, dict):
                    words += [str(v) for v in p.values()]
                elif isinstance(p, str) and p not in ("events",):
                    words.append(p)
            words = [w for w in words if w not in ("ci95",)]
            return " ".join(words[:8])
    if re.fullmatch(r"T1_[A-Z]+|T2_HOM", eid):
        return "tab:resval " + eid
    return eid.replace("_", " ").lower()


def main():
    tpl_path = SCR / "ms_template.tex"
    template = tpl_path.read_text()
    # resolve everything first (fills registries)
    out = render_text(template)
    # table-cell anchors are row/column descriptors
    fill_anchor_entries(template)
    for ent in ENTRIES:
        if not ent["tex_anchor"]:
            ent["tex_anchor"] = table_anchor(ent)
    manuscript = REPO / "manuscript" / "vein_manuscript.tex"
    manuscript.write_text(out)

    # cover letter
    cover_t = (SCR / "cover_template.tex").read_text()
    cover = render_text(cover_t)
    (REPO / "manuscript" / "cover_letter.tex").write_text(cover)

    # numbers map (version 1): all entries and manual entries
    for ent in ENTRIES:
        if ent["printed"] is None:
            raise SystemExit(f"no printed value for {ent['id']}")
    doc = {"version": 1, "entries": ENTRIES, "manual_entries": MANUAL}
    (RES / "manuscript_numbers_map.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {manuscript}")
    print(f"wrote {REPO / 'manuscript' / 'cover_letter.tex'}")
    print(f"map: {len(ENTRIES)} path entries, {len(MANUAL)} manual entries")


if __name__ == "__main__":
    main()
