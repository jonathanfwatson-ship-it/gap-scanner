"""
scorecard.py - records what the scanner picked each morning, then grades every
pick after the close. Over a few weeks this shows, with real numbers, how often
the filter finds stocks that keep running after the open.

Run by GitHub Actions (see .github/workflows/scorecard.yml):
    python scorecard.py snapshot   # about 9:05 AM ET: save today's list
    python scorecard.py grade      # after 4 PM ET: fill in open/high/low/close
    python scorecard.py auto       # picks snapshot or grade from the clock

Results live in data/scorecard.csv, which the web page reads.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

import pandas as pd

import scanner as sc

DATA = Path(__file__).resolve().parent / "data" / "scorecard.csv"

COLUMNS = [
    "date", "snapshot_time_et", "session", "symbol", "price_at_snapshot", "prev_close",
    "gap_pct_at_snapshot", "pm_high", "pm_volume", "rel_vol", "float", "score", "danger",
    "open", "high", "low", "close", "open_to_high_pct", "open_to_low_pct",
    "open_to_close_pct", "broke_pm_high", "graded",
]

SNAPSHOT_WINDOW = (dtime(8, 30), dtime(9, 45))   # ET
GRADE_AFTER = dtime(16, 5)                        # ET


def load() -> pd.DataFrame:
    if DATA.exists():
        df = pd.read_csv(DATA)
        for c in COLUMNS:
            if c not in df.columns:
                df[c] = None
        return df[COLUMNS]
    return pd.DataFrame(columns=COLUMNS)


def save(df: pd.DataFrame) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA, index=False)


def snapshot(force: bool = False) -> int:
    now = sc.now_et()
    if now.weekday() >= 5:
        print("Weekend, nothing to record.")
        return 0
    if not force and not (SNAPSHOT_WINDOW[0] <= now.time() <= SNAPSHOT_WINDOW[1]):
        print(f"{now:%I:%M %p} ET is outside the snapshot window; skipping.")
        return 0
    df = load()
    today = now.date().isoformat()
    if (df["date"].astype(str) == today).any():
        print("Already have a snapshot for today.")
        return 0

    result = sc.run_scan(sc.Settings(max_results=25))
    rows = []
    for r in result["rows"]:
        rows.append({
            "date": today,
            "snapshot_time_et": now.strftime("%H:%M"),
            "session": result["session"],
            "symbol": r["symbol"],
            "price_at_snapshot": round(r["price"], 4),
            "prev_close": round(r["prev_close"], 4),
            "gap_pct_at_snapshot": round(r["gap_pct"], 2),
            "pm_high": r.get("pm_high"),
            "pm_volume": r.get("pm_volume"),
            "rel_vol": None if r.get("rel_vol") is None else round(r["rel_vol"], 2),
            "float": r.get("float"),
            "score": r.get("score"),
            "danger": r.get("danger"),
            "graded": False,
        })
    if not rows:
        print("Scanner found nothing this morning.")
        return 0
    save(pd.concat([df, pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True))
    print(f"Recorded {len(rows)} picks for {today}.")
    return len(rows)


def fetch_daily_ohlc(symbols: list[str], day: date) -> dict[str, dict]:
    """Open/high/low/close for one trading day, per symbol."""
    import yfinance as yf

    if not symbols:
        return {}
    data = yf.download(symbols, start=day.isoformat(), end=(day + timedelta(days=1)).isoformat(),
                       interval="1d", group_by="ticker", auto_adjust=False,
                       progress=False, threads=True)
    out: dict[str, dict] = {}
    if data is None or len(data) == 0:
        return out
    for s in symbols:
        try:
            df = data[s] if isinstance(data.columns, pd.MultiIndex) else data
        except KeyError:
            continue
        df = df.dropna(subset=["Close"])
        if len(df) == 0:
            continue
        bar = df.iloc[-1]
        out[s] = {k: float(bar[k]) for k in ("Open", "High", "Low", "Close")}
    return out


def grade() -> int:
    now = sc.now_et()
    df = load().astype(object)   # empty columns load as numbers; we write text and True/False into them
    if len(df) == 0:
        print("Nothing recorded yet.")
        return 0
    pending = df[df["graded"].astype(str).str.lower() != "true"]
    graded = 0
    for day_str, group in pending.groupby("date"):
        day = date.fromisoformat(str(day_str))
        if day == now.date() and now.time() < GRADE_AFTER:
            continue   # market still open
        if day > now.date():
            continue
        bars = fetch_daily_ohlc(sorted(set(group["symbol"].astype(str))), day)
        for idx, row in group.iterrows():
            b = bars.get(str(row["symbol"]))
            if not b or b["Open"] <= 0:
                continue
            o, h, l, c = b["Open"], b["High"], b["Low"], b["Close"]
            df.loc[idx, ["open", "high", "low", "close"]] = [o, h, l, c]
            df.loc[idx, "open_to_high_pct"] = round((h / o - 1) * 100, 2)
            df.loc[idx, "open_to_low_pct"] = round((l / o - 1) * 100, 2)
            df.loc[idx, "open_to_close_pct"] = round((c / o - 1) * 100, 2)
            pm_high = pd.to_numeric(row.get("pm_high"), errors="coerce")
            df.loc[idx, "broke_pm_high"] = bool(pd.notna(pm_high) and h > pm_high)
            df.loc[idx, "graded"] = True
            graded += 1
    if graded:
        save(df)
    print(f"Graded {graded} picks.")
    return graded


def summarize(df: pd.DataFrame) -> dict | None:
    """Plain-language stats for the web page."""
    if df is None or len(df) == 0:
        return None
    g = df[df["graded"].astype(str).str.lower() == "true"].copy()
    if len(g) == 0:
        return {"days": df["date"].nunique(), "picks": len(df), "graded": 0}
    for c in ("open_to_high_pct", "open_to_low_pct", "open_to_close_pct"):
        g[c] = pd.to_numeric(g[c], errors="coerce")
    g["broke_pm_high"] = g["broke_pm_high"].astype(str).str.lower() == "true"
    n = len(g)
    return {
        "days": df["date"].nunique(),
        "picks": len(df),
        "graded": n,
        "pct_up_5": round(100 * (g["open_to_high_pct"] >= 5).mean(), 0),
        "pct_up_10": round(100 * (g["open_to_high_pct"] >= 10).mean(), 0),
        "pct_up_20": round(100 * (g["open_to_high_pct"] >= 20).mean(), 0),
        "pct_closed_up": round(100 * (g["open_to_close_pct"] > 0).mean(), 0),
        "pct_broke_pm_high": round(100 * g["broke_pm_high"].mean(), 0),
        "median_high": round(g["open_to_high_pct"].median(), 1),
        "median_low": round(g["open_to_low_pct"].median(), 1),
        "median_close": round(g["open_to_close_pct"].median(), 1),
        "best": g.sort_values("open_to_high_pct", ascending=False).head(5)[
            ["date", "symbol", "gap_pct_at_snapshot", "open_to_high_pct", "open_to_close_pct"]],
        "worst": g.sort_values("open_to_low_pct").head(5)[
            ["date", "symbol", "gap_pct_at_snapshot", "open_to_low_pct", "open_to_close_pct"]],
    }


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode == "snapshot":
        snapshot(force="--force" in sys.argv)
    elif mode == "grade":
        grade()
    else:
        now = sc.now_et()
        if now.time() < dtime(12, 0):
            snapshot()
        else:
            grade()
