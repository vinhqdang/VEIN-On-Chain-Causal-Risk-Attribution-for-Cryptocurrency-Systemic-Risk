"""VEIN configuration: entity universe, real mainnet addresses, time windows.

All addresses are real Ethereum mainnet addresses. The entity map below is the
hand-curated, label-seeded backbone of the resolution pipeline (algorithm.md
Section 2.2, Tier 3 "known-label seeding"). It is intentionally small and
high-precision: every address here is publicly attributed (Etherscan public
labels / protocol docs), so these are the nodes we can trust without ML
resolution. Unlabeled counterparties collapse into the aggregate
"retail/unknown" node, exactly as Section 2.2 prescribes.
"""
from __future__ import annotations

import datetime as dt

# ---------------------------------------------------------------------------
# Time windows (algorithm.md Section 3.4)
# ---------------------------------------------------------------------------
ESTIMATION_START = dt.date(2024, 1, 1)
ESTIMATION_END = dt.date(2025, 9, 30)        # fit f_i under "normal" regime
EVENT_START = dt.date(2025, 10, 8)
EVENT_END = dt.date(2025, 10, 14)            # Oct 10-11 cascading liquidation
REGIME_START = dt.date(2025, 10, 1)
REGIME_END = dt.date(2026, 6, 30)            # sustained bear-market deleveraging

# Full span we pull market data for.
FULL_START = ESTIMATION_START
FULL_END = REGIME_END

# ---------------------------------------------------------------------------
# Entity universe (algorithm.md Section 3.2)
# Each entity: type, the CoinGecko id of its "primary" stress asset (if any),
# and the set of real mainnet addresses that resolve to it.
# ---------------------------------------------------------------------------

# Token contracts (used both as flow assets and, for stablecoins, as peg refs)
TOKENS = {
    "USDe":  "0x4c9edd5852cd905f086c759e8383e09bff1e68b3",   # Ethena USDe
    "sUSDe": "0x9d39a5de30e57443bff2a8307a4256c8797a3497",   # Ethena staked USDe
    "USDC":  "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "USDT":  "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "wBETH": "0xa2e3356610840701bdf5611a53974510ae27e2e1",   # Binance staked ETH
    "WETH":  "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
}

# entity -> dict(type, coingecko_id (peg/price ref or None), addresses[list])
ENTITIES = {
    "Binance": {
        "type": "CEX",
        "coingecko_id": None,
        "addresses": [
            "0x28c6c06298d514db089934071355e5743bf21d60",  # Binance 14
            "0x21a31ee1afc51d94c2efccaa2092ad1028285549",  # Binance 15
            "0xdfd5293d8e347dfe59e90efd55b2956a1343963d",  # Binance 16
            "0x56eddb7aa87536c09ccc2793473599fd21a8b17f",  # Binance 17
            "0x9696f59e4d72e237be84ffd425dcad154bf96976",  # Binance 18
            "0x4976a4a02f38326660d17bf34b431dc6e2eb2327",  # Binance 20
            "0xf977814e90da44bfa03b6295a0616a897441acec",  # Binance 8 (cold)
        ],
    },
    "Ethena": {
        "type": "STABLECOIN_ISSUER",
        "coingecko_id": "ethena-usde",   # peg deviation reference
        "addresses": [
            "0xf2fa332bd83149c66b09b45670bce64746c6b439",  # Ethena: minting
            "0x71e4f98e8f20c88112489de3dd2a6f650eb45bde",  # Ethena: reserve/treasury (labeled)
        ],
    },
    "Aave": {
        "type": "LENDING",
        "coingecko_id": "aave",
        "addresses": [
            "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2",  # Aave v3 Pool
            "0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9",  # Aave v2 LendingPool
        ],
    },
    "Lido": {
        "type": "LST",
        "coingecko_id": "staked-ether",
        "addresses": [
            "0xae7ab96520de3a18e5e111b5eaab095312d7fe84",  # stETH
        ],
    },
    "MakerSky": {
        "type": "STABLECOIN_ISSUER",
        "coingecko_id": "dai",
        "addresses": [
            "0x83f20f44975d03b1b09e64809b757c47f942beea",  # sDAI
        ],
    },
}

# CoinGecko ids for the broader market universe (price/return data, benchmarks)
MARKET_ASSETS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "AAVE": "aave",
    "stETH": "staked-ether",
    "USDe": "ethena-usde",
    "ENA": "ethena",
    "DAI": "dai",
    "USDC": "usd-coin",
}

# DefiLlama protocol slugs for TVL-based stress proxies (Section 3.3)
DEFILLAMA_PROTOCOLS = {
    "Aave": "aave-v3",
    "Ethena": "ethena",
    "Lido": "lido",
}

# Stablecoins whose stress proxy is peg deviation rather than TVL
STABLE_PEG_REF = {"Ethena": "ethena-usde", "MakerSky": "dai"}

# ---------------------------------------------------------------------------
# Known, documented composability / collateral edges (algorithm.md Section 3.2).
# These are *priors* used only for the H5 "edge present vs absent" labelling and
# as a sanity check on the data-derived graph; the causal graph itself is built
# from observed flows in onchain_graph.py.
# ---------------------------------------------------------------------------
DOCUMENTED_EDGES = [
    ("Ethena", "Binance"),   # USDe/sUSDe used as collateral on Binance -> Oct'25 depeg channel
    ("Ethena", "Aave"),      # sUSDe/USDe listed as Aave collateral
    ("Lido", "Aave"),        # stETH is major Aave collateral
    ("Binance", "Ethena"),   # Binance custody/flows into Ethena mint-redeem
]

ALL_ADDRESSES = {addr.lower(): name for name, e in ENTITIES.items() for addr in e["addresses"]}
