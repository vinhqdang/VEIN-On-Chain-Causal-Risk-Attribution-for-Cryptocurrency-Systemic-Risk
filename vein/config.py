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
import os

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

# ---------------------------------------------------------------------------
# Data backend and BigQuery rebuild (BQ_SPEC sections 1-2).
# VEIN_BACKEND=dune keeps the legacy Dune code path unchanged.
# ---------------------------------------------------------------------------
DATA_BACKEND = os.environ.get("VEIN_BACKEND", "bigquery")
if DATA_BACKEND not in ("bigquery", "dune"):
    raise ValueError(f"VEIN_BACKEND must be 'bigquery' or 'dune', got {DATA_BACKEND!r}")
BQ_SOURCE = "bigquery-public-data.crypto_ethereum"
BQ_DATASET = os.environ.get("VEIN_BQ_DATASET", "vein")
BQ_LOCATION = "US"
BQ_MAX_GIB_PER_QUERY = float(os.environ.get("VEIN_BQ_MAX_GIB_PER_QUERY", 150))
BQ_HARD_CAP_GIB = float(os.environ.get("VEIN_BQ_HARD_CAP_GIB", 800))
BQ_MONTHLY_CAP_GIB = float(os.environ.get("VEIN_BQ_MONTHLY_CAP_GIB", 950))
BQ_STORAGE_CAP_GIB = 9.0
TOKEN_DECIMALS = {"USDe": 18, "sUSDe": 18, "USDC": 6, "USDT": 6, "wBETH": 18, "WETH": 18}
ETH_DENOMINATED = {"wBETH", "WETH"}    # converted with daily ETH price; others $1/unit (sUSDe at $1: documented approximation)
BQ_EXTRACTS = {   # end exclusive
  "core_daily":   {"start": dt.date(2025,1,1),  "end": dt.date(2026,6,30), "tokens": ["USDe","sUSDe","wBETH"], "bucket": "day",  "chunk_days": 110, "epoch": "e2025"},
  "oct25_hourly": {"start": dt.date(2025,9,15), "end": dt.date(2025,10,25), "tokens": ["USDe","sUSDe","wBETH","USDC","USDT","WETH"], "bucket": "hour", "chunk_days": 40, "epoch": "e2025"},
  "ftx_hourly":   {"start": dt.date(2022,11,1), "end": dt.date(2022,11,16), "tokens": ["USDC","USDT","WETH"], "bucket": "hour", "chunk_days": 15, "epoch": "eftx"},
  "svb_hourly":   {"start": dt.date(2023,3,1),  "end": dt.date(2023,3,16),  "tokens": ["USDC","USDT","WETH"], "bucket": "hour", "chunk_days": 15, "epoch": "esvb"},
}
SWEEP_PARAMS = dict(tau=0.8, max_other_hot_share=0.05, max_out_cp=3, k_in=1, min_fwd=0.5,
                    max_fwd=1.25, max_in_from_hot_share=0.5, min_timed_share=0.8,
                    h_hours=24, min_sweep_usd=1000.0)
LABEL_REPOS = {"eth-labels": "https://github.com/dawsbot/eth-labels.git",
               "etherscan-labels": "https://github.com/brianleect/etherscan-labels.git"}
EXCHANGE_ALIASES = [  # (root, regex on lower-cased whitespace-collapsed name). FIRST match wins.
  ("Binance.US", r"^binance[\s.:]*us\b"), ("Binance", r"^binance\b"), ("Coinbase", r"^coinbase\b"),
  ("OKX", r"^(okx|okex)\b"), ("Bybit", r"^bybit\b"), ("Bitfinex", r"^bitfinex\b"),
  ("HTX", r"^(htx|huobi)\b"), ("Gate.io", r"^gate(\.io)?\b"), ("Crypto.com", r"^crypto\.com\b"),
  ("Bitget", r"^bitget\b"), ("Bullish", r"^bullish\b"), ("Kraken", r"^kraken\b"),
  ("KuCoin", r"^kucoin\b"), ("Gemini", r"^gemini\b"), ("Bitstamp", r"^bitstamp\b"),
  ("MEXC", r"^mexc\b"), ("Upbit", r"^upbit\b"), ("Bithumb", r"^bithumb\b"),
  ("Robinhood", r"^robinhood\b"), ("Poloniex", r"^poloniex\b"), ("FTX", r"^ftx(\.com)?\b"),
  ("Deribit", r"^deribit\b"), ("BitMEX", r"^bitmex\b"), ("Bittrex", r"^bittrex\b"),
  ("Bitvavo", r"^bitvavo\b"), ("Copper", r"^copper\b"), ("Ceffu", r"^ceffu\b"),
  ("FalconX", r"^falcon\s*x\b"),
  # Added after inspecting the open label repos (BQ_SPEC section 5): clear exchange
  # roots with wallet labels in eth-labels / etherscan-labels.
  ("AscendEX", r"^(ascendex|bitmax)\b"), ("BitMart", r"^bitmart\b"), ("CoinEx", r"^coinex\b"),
  ("bitFlyer", r"^bitflyer\b"), ("Coincheck", r"^coincheck\b"), ("Bitkub", r"^bitkub\b"),
  ("BigONE", r"^bigone\b"), ("Hotbit", r"^hotbit\b"), ("Indodax", r"^indodax\b"),
  ("Paribu", r"^paribu\b"), ("BtcTurk", r"^btcturk\b"), ("HitBTC", r"^hitbtc\b"),
  ("Coinone", r"^coinone\b"), ("Korbit", r"^korbit\b"), ("Bitbank", r"^bitbank\b"),
  ("Coinsbit", r"^coinsbit\b"), ("BTSE", r"^btse\b"), ("DigiFinex", r"^digifinex\b"),
  ("BloFin", r"^blofin\b"), ("Delta Exchange", r"^delta\s+exchange\b"),
]
LABEL_EXCLUDE = r"\b(token|deployer|bridge|router|commerce|airdrop|nft|governance|pool|vault|swap|exploit|phish|fake)\b"

# Label "kind". The open label repos hold ~24k per-user deposit addresses ("Binance Dep:
# 0x...", "Bitget Dep: 0x...") next to ~800 hot/cold/funder wallets. Deposit labels cover
# only the exchanges whose scrapers were run (Bitget 19,027 and Binance 5,012 of 24,040), so
# using them as entity labels would make Bitget the best-resolved exchange for reasons
# unrelated to its size. Only wallet-kind labels feed the entity table and the Tier-3 hot
# set H; deposit addresses are found uniformly for every exchange by Tier-0 sweep detection,
# and the deposit labels serve as an independent validation set for that detector.
DEPOSIT_LABEL_RE = r"\bdep:"
