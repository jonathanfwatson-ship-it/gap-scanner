"""
app.py - Pre-market gap scanner web page (Streamlit).

Open it on your iPad before the market opens. It finds stocks priced $1-$9
that are up 10%+ from yesterday's close and shows how each one measures up
against Ross Cameron's 5 criteria, plus his entry plan once the market opens.
"""
import math
import os
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# The SEC wants a contact address on every request. Set SEC_USER_AGENT in Streamlit secrets
# (or edit the default in scanner.py). This must happen before scanner is imported.
try:
    if "SEC_USER_AGENT" in st.secrets:
        os.environ["SEC_USER_AGENT"] = str(st.secrets["SEC_USER_AGENT"])
except Exception:
    pass

import scanner as sc          # noqa: E402
import scorecard as scb       # noqa: E402

st.set_page_config(
    page_title="Gap Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.2rem; padding-bottom: 3rem; }
      div[data-testid="stExpander"] summary { font-size: 1.05rem; }
      .check { line-height: 1.7; }
    </style>
    """,
    unsafe_allow_html=True,
)

SESSION_LABEL = {
    "pre": "Pre-market (4:00 to 9:30 AM ET)",
    "regular": "Market open",
    "post": "After hours",
    "closed": "Market closed",
}

now = sc.now_et()
session = sc.session_for(now)

st.title("Pre-market gap scanner")
st.caption(f"{now:%A, %b %d} at {now:%I:%M %p} ET · {SESSION_LABEL[session]}")

# ---------------------------------------------------------------- filters
with st.expander("Filters", expanded=False):
    c1, c2 = st.columns(2)
    price_min = c1.number_input("Lowest price ($)", min_value=0.5, max_value=50.0, value=1.0, step=0.5)
    price_max = c2.number_input("Highest price ($)", min_value=1.0, max_value=100.0, value=9.0, step=0.5)
    min_gap = st.slider(
        "Minimum gap (%)", 5, 50, 10,
        help="How far the stock is up from yesterday's close. Ross wants at least 10%.",
    )
    strict = st.toggle(
        "Ross strict mode", value=False,
        help="Only keep stocks that also pass his float rule (under 20 million shares) "
             "and the relative-volume rule below.",
    )
    min_rel = st.slider(
        "Minimum relative volume", 0.5, 10.0, 1.0, 0.5,
        help="Shares traded so far today divided by the stock's normal full-day average. "
             "Before the open, 1.0 already means it traded a whole day's worth. "
             "Ross's 5x rule is for the regular session.",
    )
    max_results = st.slider("Stocks to show", 5, 50, 25)
    auto = st.toggle("Auto-refresh every 5 minutes", value=False)

with st.expander("Your account (for position sizing)", expanded=False):
    a1, a2 = st.columns(2)
    account = a1.number_input("Account size ($)", min_value=100.0, max_value=10_000_000.0,
                              value=5000.0, step=500.0)
    risk_pct = a2.number_input("Risk per trade (%)", min_value=0.1, max_value=5.0, value=1.0, step=0.25,
                               help="How much of the account you are willing to lose on one trade if the stop is hit. "
                                    "1% is a common starting point.")
    daily_loss_pct = st.number_input("Stop trading for the day after losing (%)", min_value=0.5, max_value=20.0,
                                     value=3.0, step=0.5,
                                     help="Ross's advice: when you hit your daily max loss, walk away.")

risk_dollars = account * risk_pct / 100.0
daily_loss_dollars = account * daily_loss_pct / 100.0
st.caption(f"Risk per trade ${risk_dollars:,.0f} · stop trading for the day at -${daily_loss_dollars:,.0f}"
           + ("  ·  under $25,000, Schwab margin accounts get 3 day trades per 5 business days" if account < 25000 else ""))

if price_max <= price_min:
    st.error("Highest price must be above lowest price.")
    st.stop()


@st.cache_data(ttl=120, show_spinner=False)
def cached_scan(price_min, price_max, min_gap, min_rel, strict, max_results):
    settings = sc.Settings(
        price_min=float(price_min), price_max=float(price_max),
        min_gap_pct=float(min_gap), min_rel_vol=float(min_rel),
        strict=bool(strict), max_results=int(max_results),
    )
    return sc.run_scan(settings)


if st.button("Scan now", type="primary"):
    cached_scan.clear()


# ---------------------------------------------------------------- helpers
def fmt_price(x):
    return "?" if x is None else f"${x:,.2f}"


def news_label(age_h):
    if age_h is None:
        return "none found"
    if age_h < 1:
        return "under 1 hr ago"
    if age_h < 24:
        return f"{age_h:.0f} hrs ago"
    return f"{age_h / 24:.0f} days ago"


def mark(ok, unknown=False):
    if unknown:
        return "❔"
    return "✅" if ok else "❌"


def flag_summary(r):
    d = r.get("danger", "ok")
    if d == "red":
        return "🔴 " + ", ".join(sorted({short_flag(f) for f in r["flags"] if f["level"] == "red"}))
    if d == "yellow":
        return "🟡 " + ", ".join(sorted({short_flag(f) for f in r["flags"] if f["level"] == "yellow"}))
    return ""


def short_flag(f):
    t = f["text"].lower()
    if "buyout" in t or "merger" in t:
        return "buyout"
    if "reverse split" in t or "charter change" in t:
        return "rev. split"
    if "shelf" in t:
        return "shelf"
    if "offering" in t or "sold shares" in t or "warrant" in t:
        return "offering"
    if "compliance" in t or "going-concern" in t:
        return "compliance"
    return "flag"


def position_size(r):
    """Shares to buy so that a stop-out loses about risk_dollars, capped by the account (no margin)."""
    price = r["price"]
    setup = r.get("setup") or {}
    if setup.get("stop"):
        stop, label = float(setup["stop"]), "the pullback low"
    elif r.get("pm_low"):
        stop, label = float(r["pm_low"]), "the pre-market low"
    else:
        stop, label = price * 0.95, "5% below the price"
    per_share = price - stop
    if per_share <= 0:
        return None
    shares = math.floor(risk_dollars / per_share)
    capped = False
    if shares * price > account:
        shares, capped = math.floor(account / price), True
    if shares <= 0:
        return None
    return {"shares": shares, "stop": stop, "label": label, "cost": shares * price,
            "risk": shares * per_share, "capped": capped}


STAGE_TEXT = {
    "no_move": "No clear push up yet today. Nothing to trade from this pattern.",
    "pushing": "Still making new highs with no pullback. Ross waits for the pullback instead of chasing.",
    "pulling_back": "Pulling back. Watch for the first candle to break the previous candle's high.",
    "too_deep": "Gave back more than half the move. Ross skips this one.",
    "trigger": "Last candle broke the previous candle's high: this is his entry trigger.",
}


def render_setup(setup):
    if not setup:
        return
    st.markdown("**Entry check (1-minute chart, Ross's bull flag)**")
    st.write(STAGE_TEXT.get(setup.get("stage"), ""))
    bits = [
        f"High of day {fmt_price(setup.get('hod'))}",
        f"VWAP {fmt_price(setup.get('vwap'))} ({'above' if setup.get('above_vwap') else 'below'})",
        f"9 EMA {fmt_price(setup.get('ema9'))} ({'above' if setup.get('above_ema9') else 'below'})",
    ]
    st.caption(" · ".join(bits))
    if setup.get("stage") in ("pulling_back", "trigger"):
        rr = setup.get("rr")
        rr_txt = "?" if rr is None else f"{rr:.1f} to 1"
        verdict = "meets his 2-to-1 rule" if setup.get("rr_ok") else "does NOT meet his 2-to-1 rule, so he would pass"
        st.write(
            f"Plan: buy near {fmt_price(setup.get('entry'))}, stop at the pullback low "
            f"{fmt_price(setup.get('stop'))}, target the high of day {fmt_price(setup.get('target'))}. "
            f"Reward-to-risk is {rr_txt}, which {verdict}."
        )


def render_row(r):
    checks = r["checks"]
    badge = {"red": "🔴 ", "yellow": "🟡 "}.get(r.get("danger"), "")
    title = f"{badge}{r['symbol']}  ·  {fmt_price(r['price'])}  ·  +{r['gap_pct']:.1f}%  ·  Ross {r['score']}/5"
    with st.expander(title):
        st.write(f"{r.get('long_name') or r['name']}  ({r['exchange']})")

        red = [f["text"] for f in r.get("flags", []) if f["level"] == "red"]
        yellow = [f["text"] for f in r.get("flags", []) if f["level"] == "yellow"]
        info = [f["text"] for f in r.get("flags", []) if f["level"] == "info"]
        if red:
            st.error("Danger: " + " | ".join(red))
        if yellow:
            st.warning("Caution: " + " | ".join(yellow))
        if info:
            st.caption(" | ".join(info))

        rel = r.get("rel_vol")
        rel_txt = "?" if rel is None else f"{rel:.1f}x"
        lines = [
            f"{mark(checks['gap'])} Up {r['gap_pct']:.1f}% from yesterday's close of {fmt_price(r['prev_close'])} (rule: 10%+)",
            f"{mark(checks['price'])} Price {fmt_price(r['price'])} ({r['basis']})",
            f"{mark(checks['rel_vol'], rel is None)} Relative volume {rel_txt} "
            f"({sc.fmt_shares(r.get('today_volume'))} traded vs. {sc.fmt_shares(r.get('avg_vol_10d'))} on a normal day)",
            f"{mark(checks['float'], r.get('float') is None)} Float {sc.fmt_shares(r.get('float'))} shares (rule: under 20M)",
            f"{mark(checks['news'], r.get('news_age_h') is None)} News: {news_label(r.get('news_age_h'))}",
        ]
        st.markdown("<div class='check'>" + "<br>".join(lines) + "</div>", unsafe_allow_html=True)

        if r.get("pm_high"):
            st.write(
                f"Pre-market high {fmt_price(r['pm_high'])}, low {fmt_price(r['pm_low'])}. "
                f"A break above the pre-market high after the open is his gap-and-go trigger."
            )
        if r.get("market_cap"):
            st.caption(f"Market cap {sc.fmt_shares(r['market_cap'])}")

        if r.get("news"):
            st.markdown("**Latest headlines**")
            for n in r["news"][:3]:
                when = n["time"].strftime("%b %d, %I:%M %p ET") if n.get("time") is not None else ""
                src = f" — {n['provider']}" if n.get("provider") else ""
                if n.get("url"):
                    st.markdown(f"- [{n['title']}]({n['url']}){src} {when}")
                else:
                    st.markdown(f"- {n['title']}{src} {when}")
        else:
            st.write("No headline found. Ross is wary of stocks that spike with no news.")

        render_setup(r.get("setup"))

        ps = position_size(r)
        if ps:
            note = " (limited by account size, no margin)" if ps["capped"] else ""
            st.write(
                f"Position size: risking ${ps['risk']:,.0f} with a stop at {fmt_price(ps['stop'])} "
                f"({ps['label']}) = {ps['shares']:,} shares, about ${ps['cost']:,.0f} of stock{note}."
            )

        sym = r["symbol"]
        st.markdown(
            f"[Yahoo chart](https://finance.yahoo.com/chart/{sym}) · "
            f"[TradingView](https://www.tradingview.com/chart/?symbol={sym}) · "
            f"[Latest news](https://finance.yahoo.com/quote/{sym}/news)"
        )


# ---------------------------------------------------------------- results
def render_results():
    with st.spinner("Scanning every US stock in your price range. This takes about 30 to 90 seconds."):
        try:
            result = cached_scan(price_min, price_max, min_gap, min_rel, strict, max_results)
        except Exception as exc:
            st.error(
                "Could not get data from Yahoo Finance. It sometimes blocks a burst of requests. "
                "Wait a minute and tap Scan now again."
            )
            st.caption(f"Details: {type(exc).__name__}: {exc}")
            return

    rows = result["rows"]
    as_of = result["as_of"]
    session = result["session"]
    if result["universe_size"] == 0:
        st.error("Could not load the stock list from Yahoo Finance. Wait a minute and tap Scan now again. "
                 "If it keeps happening, the yfinance package may need updating.")
        return
    st.write(
        f"Checked {result['universe_size']:,} stocks priced up to ${price_max:.2f}. "
        f"{result['matches']} are up {min_gap}% or more. Showing {len(rows)}. "
        f"Data as of {as_of:%I:%M %p} ET."
    )

    if result.get("limited"):
        st.warning("Yahoo did not return pre-market prices for the full list, so this scan only "
                   "checked the most active names. Try again in a few minutes.")
    if session == "pre" and as_of.hour < 7:
        st.info("It is early. Most stocks do not trade before about 7 AM ET, so the list fills in between 8:00 and 9:25.")
    if session == "closed":
        st.info("The market is closed, so gaps are measured from the last close. "
                "Check back between 7:00 and 9:25 AM ET for the real pre-market list.")

    if not rows:
        st.info("No stocks match right now. Try a lower minimum gap, or check again closer to the open.")
        return

    table = pd.DataFrame([{
        "Symbol": r["symbol"],
        "Price": r["price"],
        "Gap %": r["gap_pct"],
        "Volume": sc.fmt_shares(r.get("today_volume")),
        "Rel vol": r.get("rel_vol"),
        "Float": sc.fmt_shares(r.get("float")),
        "News": news_label(r.get("news_age_h")),
        "Ross": f"{r['score']}/5",
        "Flags": flag_summary(r),
    } for r in rows])

    st.dataframe(
        table,
        hide_index=True,
        column_config={
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Gap %": st.column_config.NumberColumn(format="%+.1f%%"),
            "Rel vol": st.column_config.NumberColumn(format="%.1fx"),
        },
    )

    st.markdown("Tap a stock for the checklist, headlines and entry plan.")
    for r in rows:
        render_row(r)


if auto:
    st.fragment(run_every=timedelta(minutes=5))(render_results)()
else:
    render_results()

# ---------------------------------------------------------------- scorecard
with st.expander("Scorecard: how past picks did"):
    csv_path = Path(__file__).resolve().parent / "data" / "scorecard.csv"
    summary = None
    if csv_path.exists():
        try:
            summary = scb.summarize(pd.read_csv(csv_path))
        except Exception as exc:
            st.caption(f"Could not read the scorecard: {exc}")
    if not summary:
        st.write("Nothing recorded yet. Once the GitHub schedule is on (see README), each morning's list "
                 "is saved here and graded after the close.")
    elif summary["graded"] == 0:
        st.write(f"{summary['picks']} picks recorded over {summary['days']} day(s). Grades appear after the close.")
    else:
        st.write(f"{summary['graded']} picks graded over {summary['days']} trading day(s).")
        m1, m2, m3 = st.columns(3)
        m1.metric("Rose 10%+ from the open", f"{summary['pct_up_10']:.0f}%")
        m2.metric("Broke the pre-market high", f"{summary['pct_broke_pm_high']:.0f}%")
        m3.metric("Closed above the open", f"{summary['pct_closed_up']:.0f}%")
        st.write(
            f"Typical pick: went up {summary['median_high']:+.1f}% at best, down {summary['median_low']:+.1f}% "
            f"at worst, and finished {summary['median_close']:+.1f}% from the open. "
            f"{summary['pct_up_5']:.0f}% rose at least 5%, {summary['pct_up_20']:.0f}% rose at least 20%."
        )
        st.caption("Best days")
        st.dataframe(summary["best"], hide_index=True)
        st.caption("Worst days")
        st.dataframe(summary["worst"], hide_index=True)

# ---------------------------------------------------------------- footer
with st.expander("The rules this scanner uses"):
    st.markdown(
        """
**Ross Cameron's 5 criteria** (from warriortrading.com)

1. Up at least 10% from yesterday's close
2. Relative volume of 5x or more in the regular session
3. Price under $20, sweet spot $2 to $8 (this app uses your $1 to $9 range)
4. A news catalyst
5. Float under 20 million shares

**His beginner entry: the bull flag**

After a fast push up, wait for a pullback that holds at least half of the move.
Buy the first candle that breaks the previous candle's high. Your stop is the low
of the pullback and your target is the high of day. Only take the trade if the
reward is at least twice the risk. He uses the 9 EMA, 20 EMA and VWAP as support
levels on 1-minute and 5-minute charts.

**Before the open**, the number to watch is the pre-market high: a break above it
after 9:30 is his gap-and-go setup.
        """
    )

st.caption(
    "Data from Yahoo Finance, delayed a minute or two. For education only, not investment "
    "advice. Most day traders lose money. Practice in a simulator before risking real money."
)
