# Vehicle period form

One Google Form with three dropdowns: **Customer**, **Vehicle number** and **Period**.
Each time it is submitted, a Google Sheet is updated: the **Tracker** tab gets one row per
customer + vehicle + period (stamped with the date and time, and a count of how often it was
submitted), and the **Log** tab gets a line for every single submission.

The dropdown choices live in the same sheet, on the **Customers**, **Vehicles** and
**Periods** tabs. Change the lists, press one menu item, and the form is rebuilt. The form
link never changes.

## Files

| File | What it does |
|---|---|
| `Code.gs` | The script that creates the form, the tabs, and updates the sheet on every submission |
| `README.md` | This guide |

## One-time setup (about 10 minutes)

Do this once, on a computer if you can. It also works on an iPad in Safari if you tap the
**aA** button in the address bar and choose **Request Desktop Website** before step 2; the
Google Sheets app itself cannot open the script editor.

**1. Make the sheet**

1. Go to sheets.new (while signed in to Google). A blank spreadsheet opens.
2. Click the name **Untitled spreadsheet** at the top left and call it something like
   `Vehicle periods`.

**2. Put the script in**

1. In the menu choose **Extensions**, then **Apps Script**. A new tab opens with a file
   called `Code.gs` that holds a few lines of sample code.
2. Select everything in that editor (click in it, then Ctrl+A on Windows or Cmd+A on Mac)
   and delete it.
3. Open `Code.gs` from this folder, copy all of it, and paste it into the editor.
4. Press the **Save** icon (the floppy disk) or Ctrl+S / Cmd+S.

**3. Run the setup**

1. In the toolbar above the code there is a dropdown that says a function name (it may say
   `onOpen`). Open it and choose **setup**.
2. Press **Run**.
3. A window says **Authorization required**. Press **Review permissions**, choose your
   Google account.
4. Google shows **Google hasn't verified this app**. This is normal for a script you pasted
   yourself. Click **Advanced**, then **Go to Untitled project (unsafe)**, then **Allow**.
   It asks for permission to see and edit your forms and spreadsheets and to run when the
   form is submitted. That is everything the script needs.
5. Wait about 10 seconds. The log under the code says `Setup finished`.

If you missed the authorization window, just choose **setup** and press **Run** again.

**4. Look at the sheet**

Go back to the spreadsheet tab. It now has these tabs:

| Tab | What is in it |
|---|---|
| **Settings** | The form title, the form link, and notes from the last rebuild |
| **Customers** | One customer per row |
| **Vehicles** | One vehicle per row, with an optional customer |
| **Periods** | One period per row (filled with the next 12 months) |
| **Tracker** | The sheet that the form updates |
| **Log** | Every submission, one line each |

Each list tab starts with a couple of example rows so you can see the shape.

**5. Fill in your own lists, then rebuild the form**

1. Replace the example customers, vehicles and periods with your own (see *The three
   lists* below).
2. Reload the spreadsheet page once, so the **Vehicle form** menu appears next to
   **Help**.
3. Choose **Vehicle form**, then **Rebuild form from the lists**. A small message in the
   bottom corner confirms it and says how many customers, vehicles and periods went in.

**6. Try it**

1. Choose **Vehicle form**, then **Show form link**. Open the form link.
2. Pick a customer, a vehicle and a period, press **Submit**.
3. Back in the spreadsheet, open **Tracker**. The row is there. Submit the same three
   choices again and the row's **Last updated** changes and **Times submitted** becomes 2.

Save the form link to your phone or iPad home screen: open it in Safari, tap Share, then
**Add to Home Screen**.

## The three lists

**Customers** – column A, one name per row. The dropdown shows them in this order.

**Vehicles** – column A is the vehicle number, column B is the customer it belongs to.

- If column B is filled in for *any* vehicle, the form becomes two steps: first the customer,
  then a page with only that customer's vehicles. A vehicle whose column B is blank is
  offered to every customer.
- If column B is blank for *every* vehicle, the form is a single page and every vehicle is
  offered for every customer.
- A customer named in column B that is missing from the Customers tab is added to the
  dropdown automatically.
- Column A is set to plain text, so a number like `0042` keeps its zeros.

**Periods** – column A, one per row. The setup fills in the next 12 months as `2026-10`,
`2026-11` and so on. Replace them with whatever a period means to you: weeks, quarters,
`Oct 2026`, anything. Keep adding rows as time goes on.

After any change: **Vehicle form**, then **Rebuild form from the lists**. Until you do, the
form still shows the old lists.

## How the Tracker is updated

Every submission looks for a Tracker row with the same customer, vehicle number and
period (capital letters and spaces around the words do not matter).

- Found: **Last updated**, **Updated by** and **Times submitted** are updated on that row.
- Not found: a new row is added at the bottom.

So the Tracker is a running list of which vehicle was recorded for which customer in which
period, and when that last happened. Sort or filter it like any sheet, but keep the first
three columns as they are because the script matches on them.

The **Log** tab is never changed, only added to, so it is the full history. Each line has
the form's own response ID, which also stops the same submission being counted twice.

## The Settings tab

| Setting | What it does |
|---|---|
| Form title, Form description | What people see at the top of the form. Rebuild after changing |
| Collect respondent email (Yes/No) | `Yes` makes people sign in to Google before they can submit and puts their address in **Updated by**. `No` (the default) lets anyone with the link submit |
| Form link (share this one) | The link to open or share. Filled in by the script |
| Form edit link | Opens the form in the Google Forms editor, only for changing colours or wording. Questions you add there are wiped by the next rebuild |
| Form last rebuilt, Notes | Filled in by the script, so you can see what went into the form |

Change the values in column B only. Do not rename the labels in column A.

## Things to know

- The form lives in your Google Drive, in **My Drive**, with the title from the Settings
  tab. Do not delete it. If you do by accident, restore it from the Drive **Bin**. If it is
  gone for good, open the script editor, run **forgetForm**, then run **setup** again: a
  new form is made and the Tracker and Log are kept.
- Only one person should run the setup: the owner of the sheet. The form submissions are
  processed under that account, and the sheet can then be shared with anyone who should
  read the Tracker.
- Whoever has the form link can submit, unless **Collect respondent email** is `Yes`.
  Google Workspace (company) accounts may also restrict the form to people in the company;
  that is the **Responses** settings inside the form editor.
- Rebuilding the form removes its questions and adds them back. Old submissions are still
  listed inside the form editor under **Responses**, and the Tracker and Log are untouched.
- The per-customer layout makes one page per customer inside the form. That is fine for a
  few dozen customers. With hundreds, leave column B on the Vehicles tab blank so the form
  stays on one page.
- If a submission fails to update the sheet, Google emails the owner a daily summary of
  failed script runs, and the script editor shows the details under **Executions** (the
  clock icon on the left). The usual cause is a form rebuilt while someone had the old
  version open; they just submit again.
- Everything runs in Google's own cloud, for free. Nothing needs to be installed.
