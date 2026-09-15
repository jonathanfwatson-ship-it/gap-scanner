"""
scanner.py - pre-market gap scanner built around Ross Cameron's 5 criteria.

Data source: Yahoo Finance through the free `yfinance` library (no API key).
Everything that talks to Yahoo lives in the fetch_* functions. The rest is
plain Python you can test without an internet connection.

Ross's criteria (from warriortrading.com, "Watch List of the Best Stocks"):
  1. Up at least 10% from the previous day's close
  2. Relative volume of 5x or more (today's volume vs. the normal average)
  3. Price under $20 - he calls $2-$8 the sweet spot (this app: $1-$9)
  4. A news catalyst
  5. Float under 20 million shares

His beginner entry (bull flag): after a push up, wait for a pullback that
holds at least half the move, then buy the first candle that breaks the
previous candle's high. Stop = low of the pullback. Target = high of day.
Only take it if the reward is at least 2x the risk.
"""
from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")

# The SEC asks every program to identify itself with a contact address.
# Change the email here, or set the SEC_USER_AGENT environment variable / Streamlit secret.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "gap-scanner (contact: you@example.com)")

PRE_START = dtime(4, 0)
REG_START = dtime(9, 30)
REG_END = dtime(16, 0)
POST_END = dtime(20, 0)

# Yahoo's codes for NASDAQ (NMS / NGM / NCM), NYSE (NYQ) and NYSE American (ASE)
US_EXCHANGES = ["NMS", "NYQ", "ASE", "NGM", "NCM"]

ROSS_MIN_GAP = 10.0            # percent
ROSS_MIN_REL_VOL = 5.0         # regular-session rule
ROSS_MAX_FLOAT = 20_000_000    # shares
NEWS_FRESH_HOURS = 24


@dataclass(frozen=True)
class Settings:
    price_min: float = 1.0
    price_max: float = 9.0
    min_gap_pct: float = 10.0
    min_rel_vol: float = 1.0        # today's volume / 10-day average daily volume
    max_float: float = ROSS_MAX_FLOAT
    strict: bool = False            # also require the float and relative-volume rules
    max_results: int = 25


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def now_et() -> datetime:
    return datetime.now(ET)


def session_for(ts: datetime | None = None) -> str:
    """'pre', 'regular', 'post' or 'closed' for a US-market timestamp."""
    ts = ts or now_et()
    if ts.weekday() >= 5:
        return "closed"
    t = ts.time()
    if PRE_START <= t < REG_START:
        return "pre"
    if REG_START <= t < REG_END:
        return "regular"
    if REG_END <= t < POST_END:
        return "post"
    return "closed"


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------
def _num(x) -> float | None:
    """Return x as a float, or None if it is missing / not a real number."""
    try:
        if x is None:
            return None
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _retry(fn, tries: int = 3, wait: float = 2.0):
    last = None
    for attempt in range(tries):
        try:
            return fn()
        except Exception as exc:  # network hiccups, rate limits
            last = exc
            time.sleep(wait * (attempt + 1))
    raise last  # type: ignore[misc]


def fmt_shares(n: float | None) -> str:
    if n is None:
        return "?"
    if n >= 1e9:
        return f"{n / 1e9:.1f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.0f}K"
    return f"{n:.0f}"


_NOT_COMMON = re.compile(
    r"\b(warrant|warrants|right|rights|unit|units|preferred|depositary|note|notes)\b", re.I
)


def looks_like_common_stock(q: dict) -> bool:
    """Drop warrants, rights, units, preferreds and anything that is not a plain stock."""
    sym = str(q.get("symbol") or "")
    if not sym or q.get("quoteType", "EQUITY") != "EQUITY":
        return False
    if any(c in sym for c in "-^./="):
        return False
    if len(sym) == 5 and sym[-1] in "WRUP":   # NASDAQ 5th-letter codes
        return False
    name = str(q.get("shortName") or q.get("longName") or "")
    return not _NOT_COMMON.search(name)


# --------------------------------------------------------------------------
# Step 1 - universe: every US stock in the price range (one Yahoo screener call per 250 stocks)
# --------------------------------------------------------------------------
def fetch_universe(price_lo: float, price_hi: float, page_size: int = 250,
                   max_pages: int = 16, pause: float = 0.4) -> list[dict]:
    import yfinance as yf

    quotes: list[dict] = []
    try:
        from yfinance import EquityQuery as EQ

        query = EQ("and", [
            EQ("btwn", ["intradayprice", price_lo, price_hi]),
            EQ("eq", ["region", "us"]),
            EQ("is-in", ["exchange", *US_EXCHANGES]),
        ])
        for page in range(max_pages):
            offset = page * page_size
            res = _retry(lambda: yf.screen(query, offset=offset, size=page_size,
                                           sortField="percentchange", sortAsc=False))
            batch = (res or {}).get("quotes") or []
            quotes.extend(batch)
            if len(batch) < page_size:
                break
            time.sleep(pause)
    except Exception:
        quotes = []

    if not quotes:
        # Fallback: Yahoo's ready-made lists (regular-session based, but better than nothing)
        for name in ("small_cap_gainers", "day_gainers", "most_actives", "aggressive_small_caps"):
            try:
                try:
                    res = _retry(lambda: yf.screen(name, size=page_size))
                except TypeError:
                    res = _retry(lambda: yf.screen(name))
                quotes.extend((res or {}).get("quotes") or [])
            except Exception:
                continue

    seen: set[str] = set()
    out: list[dict] = []
    for q in quotes:
        s = q.get("symbol")
        if s and s not in seen:
            seen.add(s)
            out.append(q)
    return out


def quote_to_candidate(q: dict, session: str) -> dict | None:
    """Turn a Yahoo quote into one row with the price that matters for this session
    and its gap versus the previous regular close."""
    prev = _num(q.get("regularMarketPreviousClose"))
    reg = _num(q.get("regularMarketPrice"))
    pm = _num(q.get("preMarketPrice"))
    post = _num(q.get("postMarketPrice"))

    if session == "pre":
        price, basis = pm, "pre-market"
    elif session == "regular":
        price, basis = reg, "today"
    else:
        price, basis = (post, "after-hours") if post else (reg, "last close")

    if not price or price <= 0 or not prev or prev <= 0:
        return None

    return {
        "symbol": q.get("symbol"),
        "name": q.get("shortName") or q.get("longName") or "",
        "exchange": q.get("fullExchangeName") or q.get("exchange") or "",
        "price": price,
        "prev_close": prev,
        "gap_pct": (price / prev - 1.0) * 100.0,
        "basis": basis,
        "avg_vol_10d": _num(q.get("averageDailyVolume10Day")),
        "avg_vol_3m": _num(q.get("averageDailyVolume3Month")),
        "reg_volume": _num(q.get("regularMarketVolume")) or 0.0,
        "market_cap": _num(q.get("marketCap")),
        "shares_out": _num(q.get("sharesOutstanding")),
    }


# --------------------------------------------------------------------------
# Step 2 - 1-minute bars (pre-market volume, pre-market high, today's chart)
# --------------------------------------------------------------------------
def fetch_intraday_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    if not symbols:
        return {}
    data = _retry(lambda: yf.download(
        symbols, period="2d", interval="1m", prepost=True, group_by="ticker",
        auto_adjust=False, progress=False, threads=True,
    ))
    out: dict[str, pd.DataFrame] = {}
    if data is None or len(data) == 0:
        return out
    for s in symbols:
        try:
            df = data[s] if isinstance(data.columns, pd.MultiIndex) else data
        except KeyError:
            continue
        cleaned = clean_bars(df)
        if len(cleaned):
            out[s] = cleaned
    return out


def clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)
    df = df.dropna(subset=["Close"])
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(ET)
    return df


def premarket_stats(df: pd.DataFrame | None, day: date) -> dict:
    """Pre-market volume / high / low for `day`, plus today's regular-session bars."""
    empty = {"pm_volume": 0.0, "pm_high": None, "pm_low": None, "pm_last": None,
             "reg_volume": 0.0, "regular": None}
    if df is None or len(df) == 0:
        return empty
    today = df[df.index.date == day]
    if len(today) == 0:
        return empty
    times = today.index.time
    pm = today[times < REG_START]
    reg = today[(times >= REG_START) & (times < REG_END)]
    return {
        "pm_volume": float(pm["Volume"].sum()) if len(pm) else 0.0,
        "pm_high": float(pm["High"].max()) if len(pm) else None,
        "pm_low": float(pm["Low"].min()) if len(pm) else None,
        "pm_last": float(pm["Close"].iloc[-1]) if len(pm) else None,
        "reg_volume": float(reg["Volume"].sum()) if len(reg) else 0.0,
        "regular": reg if len(reg) else None,
    }


# --------------------------------------------------------------------------
# Step 3 - Ross's bull-flag entry, checked on today's 1-minute chart
# --------------------------------------------------------------------------
def bull_flag_check(reg: pd.DataFrame | None) -> dict | None:
    """Heuristic read of the current 1-minute chart. Stages:
    no_move      - nothing to work with yet
    pushing      - still making new highs, no pullback to buy
    pulling_back - pulled back less than half the move; waiting for a new high
    too_deep     - gave back more than half the move (Ross skips these)
    trigger      - last candle broke the previous candle's high: his entry
    """
    if reg is None or len(reg) < 5:
        return None

    highs = reg["High"].ffill()
    lows = reg["Low"].ffill()
    closes = reg["Close"].ffill()
    opens = reg["Open"].ffill()
    vols = reg["Volume"].fillna(0)

    typical = (highs + lows + closes) / 3.0
    cum_vol = float(vols.sum())
    vwap = float((typical * vols).sum() / cum_vol) if cum_vol > 0 else float(closes.iloc[-1])
    ema9 = float(closes.ewm(span=9, adjust=False).mean().iloc[-1])

    hod_pos = int(highs.to_numpy().argmax())
    hod = float(highs.iloc[hod_pos])
    price = float(closes.iloc[-1])

    out = {
        "hod": hod, "vwap": vwap, "ema9": ema9, "price": price,
        "above_vwap": price >= vwap, "above_ema9": price >= ema9,
    }

    move_low = float(lows.iloc[: hod_pos + 1].min())
    move = hod - move_low
    if move <= 0 or hod_pos < 2:
        out["stage"] = "no_move"
        return out

    after = reg.iloc[hod_pos + 1:]
    if len(after) < 2:
        out["stage"] = "pushing"
        return out

    pullback_low = float(after["Low"].min())
    retrace = (hod - pullback_low) / move
    out.update({"pullback_low": pullback_low, "retrace_pct": retrace * 100.0})
    if retrace > 0.5:
        out["stage"] = "too_deep"
        return out

    last, prev = reg.iloc[-1], reg.iloc[-2]
    broke_prev_high = float(last["High"]) > float(prev["High"])
    green = float(last["Close"]) >= float(last["Open"])

    entry = price
    risk = entry - pullback_low
    reward = hod - entry
    rr = (reward / risk) if risk > 0 else None
    out.update({
        "stage": "trigger" if (broke_prev_high and green) else "pulling_back",
        "entry": entry, "stop": pullback_low, "target": hod,
        "risk": risk, "reward": reward, "rr": rr,
        "rr_ok": bool(rr is not None and rr >= 2.0),
    })
    return out


# --------------------------------------------------------------------------
# Step 4 - float and news (one Yahoo call per stock, so only for the finalists)
# --------------------------------------------------------------------------
def fetch_float_and_news(symbol: str) -> dict:
    import yfinance as yf

    t = yf.Ticker(symbol)
    info: dict = {}
    try:
        info = t.info or {}
    except Exception:
        info = {}
    news = []
    try:
        raw = t.news or []
    except Exception:
        raw = []
    for item in raw[:5]:
        parsed = parse_news_item(item)
        if parsed:
            news.append(parsed)
    news.sort(key=lambda n: n["time"] or pd.Timestamp.min.tz_localize("UTC"), reverse=True)
    reverse_splits = []
    try:
        splits = t.splits
        if splits is not None and len(splits):
            for when, ratio in splits.items():
                r = _num(ratio)
                if r and 0 < r < 1:
                    reverse_splits.append({"date": pd.Timestamp(when), "ratio": r})
    except Exception:
        pass
    return {
        "float": _num(info.get("floatShares")),
        "shares_out": _num(info.get("sharesOutstanding")) or None,
        "long_name": info.get("longName"),
        "sector": info.get("sector"),
        "news": news,
        "reverse_splits": reverse_splits,
    }


def parse_news_item(item: dict) -> dict | None:
    """Handle both the new (item['content']) and old (flat) yfinance news formats."""
    if not isinstance(item, dict):
        return None
    content = item.get("content")
    ts = None
    if isinstance(content, dict):
        title = content.get("title")
        url = ((content.get("canonicalUrl") or {}).get("url")
               or (content.get("clickThroughUrl") or {}).get("url"))
        provider = (content.get("provider") or {}).get("displayName")
        pub = content.get("pubDate")
        if pub:
            try:
                ts = pd.to_datetime(pub, utc=True)
            except Exception:
                ts = None
    else:
        title = item.get("title")
        url = item.get("link")
        provider = item.get("publisher")
        pub = item.get("providerPublishTime")
        if pub:
            try:
                ts = pd.to_datetime(pub, unit="s", utc=True)
            except Exception:
                ts = None
    if not title:
        return None
    return {"title": title, "url": url, "provider": provider or "",
            "time": ts.tz_convert(ET) if ts is not None else None}


def news_age_hours(news: list[dict], now: datetime) -> float | None:
    times = [n["time"] for n in news if n.get("time") is not None]
    if not times:
        return None
    newest = max(times)
    return max(0.0, (pd.Timestamp(now) - newest).total_seconds() / 3600.0)


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def ross_checklist(row: dict, s: Settings) -> dict:
    rel = row.get("rel_vol")
    flt = row.get("float")
    age = row.get("news_age_h")
    return {
        "gap": row["gap_pct"] >= ROSS_MIN_GAP,
        "price": s.price_min <= row["price"] <= s.price_max,
        "rel_vol": rel is not None and rel >= s.min_rel_vol,
        "float": flt is not None and flt <= s.max_float,
        "news": age is not None and age <= NEWS_FRESH_HOURS,
    }


# --------------------------------------------------------------------------
# The whole scan
# --------------------------------------------------------------------------
def run_scan(s: Settings) -> dict:
    ts = now_et()
    session = session_for(ts)
    today = ts.date()

    # Screen a little below the minimum price so a $0.80 stock gapping to $1.10 is not missed.
    quotes = fetch_universe(min(s.price_min * 0.7, s.price_min), s.price_max)

    limited = False
    if session == "pre" and quotes and not any(_num(q.get("preMarketPrice")) for q in quotes):
        # Yahoo gave no pre-market prices in the screener: check bars for the most active names.
        limited = True
        by_change = sorted(quotes, key=lambda q: _num(q.get("regularMarketChangePercent")) or 0, reverse=True)[:120]
        by_volume = sorted(quotes, key=lambda q: _num(q.get("regularMarketVolume")) or 0, reverse=True)[:120]
        pool: dict[str, dict] = {q["symbol"]: q for q in by_change + by_volume if q.get("symbol")}
        bars = fetch_intraday_bars(list(pool))
        for sym, q in pool.items():
            stats = premarket_stats(bars.get(sym), today)
            if stats["pm_last"]:
                q["preMarketPrice"] = stats["pm_last"]

    candidates: list[dict] = []
    for q in quotes:
        if not looks_like_common_stock(q):
            continue
        row = quote_to_candidate(q, session)
        if row is None:
            continue
        if s.price_min <= row["price"] <= s.price_max and row["gap_pct"] >= s.min_gap_pct:
            candidates.append(row)
    candidates.sort(key=lambda r: r["gap_pct"], reverse=True)

    enrich_n = min(60, s.max_results * 2) if s.strict else s.max_results
    finalists = candidates[:enrich_n]

    bars = fetch_intraday_bars([r["symbol"] for r in finalists])
    for r in finalists:
        stats = premarket_stats(bars.get(r["symbol"]), today)
        r.update({k: stats[k] for k in ("pm_volume", "pm_high", "pm_low", "pm_last")})
        today_vol = stats["pm_volume"] if session == "pre" else max(stats["reg_volume"], r["reg_volume"])
        r["today_volume"] = today_vol
        base = r.get("avg_vol_10d") or r.get("avg_vol_3m")
        r["rel_vol"] = (today_vol / base) if base else None
        r["setup"] = bull_flag_check(stats["regular"]) if session in ("regular", "post") else None

    for r in finalists:
        r.update(fetch_float_and_news(r["symbol"]))
        r["news_age_h"] = news_age_hours(r["news"], ts)
        r["flags"] = danger_flags(r, ts)
        levels = {f["level"] for f in r["flags"]}
        r["danger"] = "red" if "red" in levels else "yellow" if "yellow" in levels else "ok"
        time.sleep(0.15)   # be polite to Yahoo

    if s.strict:
        finalists = [r for r in finalists
                     if (r.get("float") is not None and r["float"] <= s.max_float)
                     and (r.get("rel_vol") is not None and r["rel_vol"] >= s.min_rel_vol)]

    for r in finalists:
        r["checks"] = ross_checklist(r, s)
        r["score"] = sum(r["checks"].values())

    return {
        "as_of": ts,
        "session": session,
        "universe_size": len(quotes),
        "matches": len(candidates),
        "rows": finalists[: s.max_results],
        "limited": limited,
    }


# --------------------------------------------------------------------------
# Danger check - the ways these stocks hurt people: offerings, reverse splits,
# buyouts (price locked), exchange trouble. Sources: headlines, split history,
# and the company's own SEC filings (free, no key).
# --------------------------------------------------------------------------
OFFERING_WORDS = ("public offering", "registered direct", "private placement", "at-the-market",
                  "at the market offering", "securities purchase agreement", "pricing of",
                  "prices offering", "direct offering", "equity line", "warrant")
REVERSE_SPLIT_WORDS = ("reverse stock split", "reverse split", "share consolidation")
BUYOUT_WORDS = ("to be acquired", "acquired by", "merger agreement", "take-private",
                "go-private", "buyout", "tender offer")
COMPLIANCE_WORDS = ("going concern", "delist", "deficiency", "minimum bid price",
                    "compliance notice", "noncompliance", "non-compliance")

OFFERING_FORMS = {"424B1", "424B2", "424B3", "424B4", "424B5", "424B7", "S-1", "S-1/A",
                  "S-3", "S-3/A", "F-1", "F-1/A", "F-3", "F-3/A", "S-1MEF", "S-3MEF"}
SHELF_FORMS = {"S-3", "S-3/A", "F-3", "F-3/A"}

_SEC_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}
_CIK_MAP: dict | None = None


def sec_cik_map() -> dict:
    """Ticker -> SEC company number, downloaded once per process."""
    global _CIK_MAP
    if _CIK_MAP is None:
        import requests
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         headers=_SEC_HEADERS, timeout=20)
        r.raise_for_status()
        _CIK_MAP = {str(v["ticker"]).upper(): int(v["cik_str"]) for v in r.json().values()}
    return _CIK_MAP


def fetch_sec_filings(symbol: str, limit: int = 300) -> list[dict]:
    """Recent filings for one company from data.sec.gov (form, date, 8-K item codes)."""
    import requests
    cik = sec_cik_map().get(symbol.upper())
    if not cik:
        return []
    r = requests.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                     headers=_SEC_HEADERS, timeout=20)
    r.raise_for_status()
    recent = (r.json().get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    items = recent.get("items") or []
    out = []
    for i, form in enumerate(forms[:limit]):
        out.append({
            "form": str(form),
            "date": dates[i] if i < len(dates) else "",
            "items": str(items[i]) if i < len(items) else "",
        })
    time.sleep(0.12)   # SEC allows 10 requests per second
    return out


def sec_flags(filings: list[dict], now: datetime) -> list[dict]:
    flags: list[dict] = []
    seen: set[str] = set()
    today = now.date()
    for f in filings:
        try:
            d = date.fromisoformat(f["date"])
        except (TypeError, ValueError):
            continue
        age = (today - d).days
        form = f["form"].upper()
        key = None
        if age <= 90 and form in OFFERING_FORMS:
            key, level, text = f"offer-{form}", "red", f"Filed {form} on {d:%b %d} (share-offering paperwork)"
        elif age <= 90 and form.startswith("8-K"):
            codes = f.get("items") or ""
            if "3.02" in codes:
                key, level, text = "8k-3.02", "red", f"8-K on {d:%b %d}: sold shares privately (item 3.02)"
            elif "5.03" in codes:
                key, level, text = "8k-5.03", "yellow", f"8-K on {d:%b %d}: charter change (often a reverse split)"
        elif age <= 730 and form in SHELF_FORMS:
            key, level, text = "shelf", "yellow", f"Has a shelf registration ({form}, {d:%b %Y}): can sell new shares at any time"
        if key and key not in seen:
            seen.add(key)
            flags.append({"level": level, "text": text})
        if len(flags) >= 5:
            break
    return flags


def headline_flags(news: list[dict]) -> list[dict]:
    flags: list[dict] = []
    seen: set[str] = set()
    rules = (
        ("buyout", BUYOUT_WORDS, "red", "Buyout or merger news (if this company is the one being bought, the price is locked and Ross skips it)"),
        ("offering", OFFERING_WORDS, "red", "Headline mentions a share offering or warrants"),
        ("rsplit", REVERSE_SPLIT_WORDS, "yellow", "Headline mentions a reverse split"),
        ("compliance", COMPLIANCE_WORDS, "yellow", "Headline mentions exchange compliance or going-concern trouble"),
    )
    for n in news or []:
        title = str(n.get("title") or "")
        low = title.lower()
        for key, words, level, label in rules:
            if key not in seen and any(w in low for w in words):
                seen.add(key)
                flags.append({"level": level, "text": f"{label}: '{title[:90]}'"})
    return flags


def reverse_split_flags(splits: list[dict], now: datetime, days: int = 365) -> list[dict]:
    flags = []
    now_ts = pd.Timestamp(now)
    for sp in splits or []:
        when = pd.Timestamp(sp["date"])
        if when.tzinfo is None:
            when = when.tz_localize(ET)
        age = (now_ts - when.tz_convert(ET)).days
        if 0 <= age <= days and sp["ratio"] > 0:
            flags.append({"level": "yellow",
                          "text": f"Reverse split {1 / sp['ratio']:.0f}-for-1 on {when:%b %d, %Y}"})
    return flags


def danger_flags(row: dict, now: datetime) -> list[dict]:
    flags = headline_flags(row.get("news") or [])
    flags += reverse_split_flags(row.get("reverse_splits") or [], now)
    try:
        flags += sec_flags(fetch_sec_filings(row["symbol"]), now)
    except Exception:
        flags.append({"level": "info", "text": "Could not reach SEC filings (check SEC_USER_AGENT in scanner.py)"})
    return flags
