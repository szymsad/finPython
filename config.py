# config.py

IKZE_CONFIG = {
    "limit_roczny": 11304,
    "short_span": 12,
    "long_span": 26,
    "signal_span": 9,
}

IKZE_BANKI = {
    "PKO.WA": {"nazwa": "PKO Bank Polski", "procent": 25, "tier": "🟢 TOP"},
    "MBK.WA": {"nazwa": "mBank", "procent": 25, "tier": "🟢 TOP"},
    "PEO.WA": {"nazwa": "Bank Pekao", "procent": 20, "tier": "🔵 MID"},
    "EBP.WA": {"nazwa": "Bank BPH", "procent": 15, "tier": "⚪ NIŻ"},
    "ING.WA": {"nazwa": "ING Bank Śląski", "procent": 15, "tier": "⚪ NIŻ"},
}

WATCHLIST_FILE = "watchlist.txt"
DEFAULT_TICKERS = "PKN.WA, DNP.WA, PKO.WA, KGH.WA, XTB.WA"