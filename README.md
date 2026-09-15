# Pre-market gap scanner

A web page you open on your iPad before the market opens. It checks every US stock
priced $1 to $9, keeps the ones up 10% or more from yesterday's close, and grades each
one against Ross Cameron's 5 criteria (gap, price, relative volume, float, news). It
also warns you about the ways these stocks hurt people, sizes your position, and keeps a
scorecard of how its own picks turned out.

It runs for free in the cloud, so nothing needs to be installed on the iPad and no
computer needs to be on. Prices come from Yahoo Finance (free, delayed a minute or two);
filings come straight from the SEC.

## Files

| File | What it does |
|---|---|
| `app.py` | The web page |
| `scanner.py` | Scanning, the strategy checks and the danger check |
| `scorecard.py` | Records each morning's list and grades it after the close |
| `.github/workflows/scorecard.yml` | The twice-a-day schedule that runs the scorecard |
| `data/scorecard.csv` | Where the scorecard results are kept (starts empty) |
| `requirements.txt` | The Python packages the cloud needs to install |

## One-time setup (about 20 minutes, all doable from the iPad in Safari)

**1. Put the files on GitHub** (a free site that stores code)

1. Go to github.com and create a free account.
2. Tap the **+** in the top right, then **New repository**. Name it `gap-scanner`,
   leave it Public, tap **Create repository**.
3. Tap **Add file**, then **Upload files**. Upload `app.py`, `scanner.py`,
   `scorecard.py`, `requirements.txt` and this README. Tap **Commit changes**.
4. Two files need to go into folders, which the upload button can't do. For each one,
   tap **Add file**, then **Create new file**, type the full path as the file name, paste
   the file's contents, and commit:
   - `.github/workflows/scorecard.yml`
   - `data/scorecard.csv` (its contents are just the single header line)

**2. Turn it into a live web page** (Streamlit Community Cloud, free)

1. Go to share.streamlit.io and sign in with your GitHub account.
2. Tap **Create app** (or **Deploy an app**), choose the `gap-scanner` repository,
   branch `main`, main file `app.py`.
3. Open **Advanced settings** and in the Secrets box paste one line with your email
   (the SEC asks every program to identify itself):
   `SEC_USER_AGENT = "gap-scanner you@example.com"`
4. Tap **Deploy** and wait 2 to 3 minutes. You get a web address that ends in
   `.streamlit.app`.

**3. Put it on your iPad home screen**

Open that address in Safari, tap the Share button, then **Add to Home Screen**.

**4. Switch on the scorecard schedule**

In your GitHub repository tap **Actions**. If it asks you to enable workflows, say yes.
From then on it records the list at about 9:05 AM ET and grades it at about 4:20 PM ET
every weekday, on its own. Tap **Scorecard**, then **Run workflow**, to test it by hand.
Also add your email there so the SEC check works in the schedule too: **Settings**,
**Secrets and variables**, **Actions**, **New repository secret**, name
`SEC_USER_AGENT`, value `gap-scanner you@example.com`.

## Each morning

- Open it between **7:00 and 9:25 AM ET**. Pre-market is quiet before 7; the list
  fills in from about 8:00.
- The scan takes 30 to 90 seconds. Tap **Scan now** to refresh, or turn on
  **Auto-refresh** in Filters and leave it open.
- Fill in **Your account** once so the position sizes are right for you.
- Tap a stock to see its checklist, warnings, pre-market high, headlines, position size
  and links to a chart.
- After 9:30, each stock also shows an entry check based on Ross's bull flag rules.

## What the columns mean

- **Gap %** – how far the stock is above yesterday's close.
- **Volume** – shares traded so far today (pre-market only, before 9:30).
- **Rel vol** – that volume divided by the stock's normal full-day average. Before the
  open, 1.0x already means it has traded a whole day's worth of shares.
- **Float** – shares available to trade. Ross wants under 20 million.
- **News** – how old the newest headline is. He wants a fresh reason for the move.
- **Ross** – how many of his 5 criteria the stock passes.
- **Flags** – the danger check (below). Red means think twice, yellow means be careful.

## The danger check

- **Offering** (red): the company filed share-offering paperwork with the SEC in the last
  90 days, sold shares privately, or a headline mentions an offering or warrants. Small
  companies often announce an offering the same morning the stock spikes, and the price
  collapses.
- **Buyout** (red): buyout or merger news. If this company is the one being bought, the
  price is locked near the deal price and there is no move to trade. Ross skips these.
- **Rev. split** (yellow): a reverse split in the last year, or a recent charter change
  that is often one. A sign of a company that has been losing value.
- **Shelf** (yellow): the company has a standing registration that lets it sell new
  shares at any time.
- **Compliance** (yellow): exchange warning letters or going-concern language.

## The scorecard

Every morning the schedule saves the top 25 picks. After the close it looks up what each
one did: how far it rose from the open at best, how far it fell at worst, where it closed,
and whether it broke its pre-market high (Ross's gap-and-go trigger). Open **Scorecard**
on the web page to see the running numbers. Give it a month before drawing conclusions.

## Things to know

- The free app goes to sleep when nobody has used it for a while. If you see a
  "wake up" button, tap it and wait about a minute.
- Yahoo occasionally blocks a burst of requests. If you get a data error, wait a minute
  and tap **Scan now** again.
- Yahoo's pre-market volume can be thin early in the morning, so relative volume is
  most trustworthy after about 8:30 AM.
- GitHub pauses a schedule if nothing in the repository changes for 60 days; the daily
  scorecard commits keep it alive, but if it stops, re-enable it in the Actions tab.
- The page restarts for about 30 seconds when the scorecard saves (9:05 AM and 4:20 PM).
- Ross's own live scanner uses paid real-time data. If you outgrow this one, the two
  upgrade paths are a paid data feed (Polygon, Alpaca's paid plan) or Schwab's Trader
  API, which needs a developer account and a login refresh every 7 days.
- This is for education. Most day traders lose money. Ross himself says to trade in a
  simulator until you can prove you are profitable; since you have Schwab, thinkorswim's
  paperMoney is a free one with real-time data.
