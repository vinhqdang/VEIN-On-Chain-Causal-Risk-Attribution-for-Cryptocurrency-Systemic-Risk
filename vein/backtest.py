"""VaR backtests (algorithm.md Section 4.2): Kupiec POF, Christoffersen.

These are the standard statistical-validity tests for a VaR forecast. We apply
them to a rolling historical VaR on real return series as the interventional/
standard risk-measure validity check.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def rolling_historical_var(returns: pd.Series, window: int = 100, q: float = 0.05) -> pd.Series:
    """One-day-ahead historical VaR at level q (left tail)."""
    return returns.rolling(window).quantile(q).shift(1)


def kupiec_pof(violations: np.ndarray, q: float = 0.05) -> dict:
    """Kupiec unconditional coverage (proportion-of-failures) test."""
    n = len(violations)
    x = int(np.sum(violations))
    if n == 0:
        return {"n": 0, "failures": 0, "rate": np.nan, "LR_pof": np.nan, "p_value": np.nan}
    pi = x / n
    eps = 1e-12
    ll_null = x * np.log(q + eps) + (n - x) * np.log(1 - q + eps)
    ll_alt = x * np.log(pi + eps) + (n - x) * np.log(1 - pi + eps)
    lr = -2 * (ll_null - ll_alt)
    p = 1 - stats.chi2.cdf(lr, df=1)
    return {"n": n, "failures": x, "rate": pi, "expected_rate": q,
            "LR_pof": float(lr), "p_value": float(p)}


def christoffersen(violations: np.ndarray, q: float = 0.05) -> dict:
    """Christoffersen independence + conditional coverage tests."""
    v = np.asarray(violations).astype(int)
    n = len(v)
    if n < 2:
        return {"LR_ind": np.nan, "LR_cc": np.nan, "p_value_cc": np.nan}
    n00 = n01 = n10 = n11 = 0
    for t in range(1, n):
        a, b = v[t - 1], v[t]
        if a == 0 and b == 0: n00 += 1
        elif a == 0 and b == 1: n01 += 1
        elif a == 1 and b == 0: n10 += 1
        else: n11 += 1
    eps = 1e-12
    pi01 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) else 0.0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)
    ll_ind = ((n00 + n10) * np.log(1 - pi + eps) + (n01 + n11) * np.log(pi + eps))
    ll_alt = (n00 * np.log(1 - pi01 + eps) + n01 * np.log(pi01 + eps)
              + n10 * np.log(1 - pi11 + eps) + n11 * np.log(pi11 + eps))
    lr_ind = -2 * (ll_ind - ll_alt)
    pof = kupiec_pof(v, q)
    lr_cc = pof["LR_pof"] + lr_ind
    return {"LR_ind": float(lr_ind), "p_value_ind": float(1 - stats.chi2.cdf(lr_ind, 1)),
            "LR_cc": float(lr_cc), "p_value_cc": float(1 - stats.chi2.cdf(lr_cc, 2))}


def backtest_var(returns: pd.Series, window: int = 100, q: float = 0.05) -> dict:
    var = rolling_historical_var(returns, window, q)
    aligned = pd.concat([returns, var], axis=1, keys=["r", "var"]).dropna()
    violations = (aligned["r"] < aligned["var"]).values
    return {"kupiec": kupiec_pof(violations, q),
            "christoffersen": christoffersen(violations, q)}
