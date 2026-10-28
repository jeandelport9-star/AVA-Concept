# AVA – rentals without the agent fees

With AVA, one portfolio manager can run hundreds of rental homes. The app does the routine agent work and shows the manager only the exceptions.

It combines three things:
- **Property24 / Private Property:** the public portal – map search, listings, alerts.
- **WeConnectU:** trust accounting, leases, maintenance and inspections.
- **Site Inspect:** 360° capture, used for rental ingoing/outgoing inspections and construction snag lists.

It's built from the AVA documents: features scope, pricing sheet (Aug 2024), maintenance module quotation, Portfolio Director brief and "Who is AVA".

> **Maintenance is switched off for now.** Repairs, contractor quotes, maintenance companies and the job map run in **Fixit**, a separate app. The code stays in AVA behind one setting: **Admin → Settings & fees → Modules → Maintenance in AVA**. With it off:
> - menus, pages and API for repairs are hidden;
> - the virtual agent points tenants and owners to Fixit (set the *Fixit link* in the same place) and still gives emergency safety steps;
> - repairs found at an inspection go to the portfolio manager as one to-do, so the owner can decide which to do.
>
> Construction snag lists stay in AVA – they belong to inspections.

## Start

Windows: double-click **`start.bat`**. The first run does two things:
1. It installs the requirements (Python 3.11+).
2. It loads the demo portfolio.

The browser then opens at http://localhost:8780.

**After an update:** close the window titled *AVA server* and double-click `start.bat` again. When a newer demo ships, the demo data is rebuilt automatically. `reset_demo.bat` rebuilds the demo whenever you want a clean slate.

By hand:

```
pip install -r requirements.txt
python -m server.seed          # demo data (add --reset to rebuild)
python run.py                  # http://localhost:8780
```

**Phones:** the console prints a LAN address (e.g. `http://192.168.1.20:8780`). Open it on a phone on the same Wi-Fi, then use *Add to Home screen*. The app installs like a native app: it's a PWA with an offline shell.

### Demo logins (password `demo1234`)

The sign-in page also has one-tap buttons for these accounts.

| Who | Email | Try |
|---|---|---|
| Portfolio manager | thandi@ava.co.za | Command centre, Money → Owner payouts, Maintenance board, Inspections, Snag lists, AI & virtual agent |
| Landlord | emgee@example.co.za · sarah@example.co.za | Statements, savings vs an agent, inspections. *(With maintenance on: Sarah chooses one of 3 quotes; Emgee extends the range for the Dullstroom farm.)* |
| Tenant (moving out) | lerato@example.com | Pay, outgoing inspection, deposit, virtual agent |
| Tenant | johan@example.com | Report a problem and watch the AI triage |
| Contractor | plumbfix@example.co.za | Snags to mark fixed with an 'after' photo. *(With maintenance on:* *Browse jobs* map – apply to quote on nearby repairs; R250/month listing, "Job done" photo button, "Report an issue" with a voice note, ratings and replies*)* |
| AVA admin | admin@ava.co.za | **Trust accounts** – trial balance, reconcile & lock last month, release payment batches, debit orders, deposit investments; users, settings |

The demo house **Jacaranda House** uses the real BLK360 G2 panoramas from Site Inspect's Troye House capture. Both its public 360° tour and its ingoing/outgoing inspection use them; the outgoing panoramas have simulated damage.

## Search (Property24 filter set)

**Location:** several suburbs, cities or provinces at once, shown as chips with type-ahead suggestions.

**Main filters:**
- property type: house, apartment/flat, townhouse, cottage, room, farm, retirement, commercial
- price minimum and maximum
- bedrooms

**More filters:**
- bathrooms
- parking or garages
- floor size and erf size
- furnished or unfurnished
- listed within the last 24 hours to 30 days
- available-by date
- keywords
- pets allowed
- 360° tour
- 15 features with counts: garden, pool, flatlet, security estate, backup power, backup water, fibre, study, staff quarters, aircon, fireplace, braai, gym, wheelchair access, garage

**Sorting:** featured, newest, price, size, availability, bedrooms.

**Results:** active-filter chips with one-tap remove, a list/map split view with price pins, and a shareable URL. *Save search* turns the full filter set into an alert, matched by the same query whenever a listing goes live.

The demo has 50 listings across all nine provinces. Every rent is between **R15 000 and R30 000** and is worked out per home: floor area × the going rate per m² for that town and suburb, adjusted for the type of home and its features. Size, bedrooms, bathrooms, parking and erf size all match the rent, each with its own photos (free Unsplash images, loaded online, with a local fallback), plus regional portfolio managers.

## What one agent no longer has to do

| Stage | What AVA does automatically | When the PM is involved |
|---|---|---|
| **List** | AI listing copy; rent check against comparables (median + R/m²); photos and a 360° tour; area alerts to renters who saved that map area | Publishing |
| **Viewings** | Renters pick open slots; auto-confirmed with directions, calendar file and reminder | – |
| **Virtual agent** | Answers prospects 24/7 from the listing data (costs, pets, solar, size, area). It pre-qualifies on income, books viewings, starts applications and finds similar homes | Hand-overs only ("speak to a person", unknown questions) |
| **Vet** | AVA score from affordability (rent ≤ ⅓ income), credit, documents and TPN history; one-click bureau check (stub) | Approve / decline |
| **Lease** | Lease generated (RHA, CPA s14, PIE, ECT Act clauses), e-signed on the phone. Move-in invoice: deposit, key deposit, 50% inspection fee. Ingoing inspection booked | – |
| **Collect** | Rent charged monthly; payments matched by reference (PayFast, or bank CSV import); allocated deposit → fees → tenant-liable repairs → rent. Annual escalation applied. Deposit interest accrued | – |
| **Arrears** | Reminder on day 1, final reminder on day 5, letter of demand on day 10 | After day 10 |
| **Repairs** | AI triage (trade, urgency, liability, safety advice); emergencies dispatched under the auto-approve limit; quotes from 3 listed companies within 10 km (owner extends the range if nobody is near); owner chooses; photo = done; issues by photo/voice note; auto-close after 72 h; multi-criteria rating; cost deducted from the payout | Stalled jobs, no quotes |
| **Inspections** | Room-by-room C1–C5, photos, 360° per room (photo or a frame from 360° video), pins on the 360°. Outgoing opens next to the ingoing with synced 360° views. Charges become a deposit reconciliation and refund deadline (7 / 14 / 21 days) | Doing the walk-through |
| **Renewals** | Renewal risk score; offer 60 days out; no admin fee on renewal; outgoing inspection booked if not renewing | High-risk tenants |
| **Payouts** | Owner statement per property: rent in, AVA tier fee, PM commission, insurance, repairs → payout | Release button |
| **Compliance** | "No steps missed" checklist on every lease; AVA Learn explains RHA / CPA / PIE / POPIA in plain language | – |

## Maintenance marketplace (module – off while maintenance runs in Fixit)

- **Listing:** maintenance companies list themselves for **R250/month** at *#/pros/join*, with a 30-day free trial. They pin their base on a map, and AVA vets them (CIPC, ID, references) before they get work. A lapsed listing stops receiving requests, and a reminder goes out 5 days before expiry.
- **3 quotes within 10 km:** every repair request goes to the 3 best-matched, paid-up companies within 10 km of the property, ranked on rating, distance and workload. Emergencies under the auto-approve limit are dispatched to the best company straight away.
- **Nobody in range:** the job shows a map of companies around the property. The owner or PM taps *Extend range* (15 / 25 / 50 / 100 km), and AVA highlights the smallest step that reaches someone. `auto_widen_km` lets AVA widen by itself.
- **The owner chooses:** quotes are compared side by side on price, rating, distance, days, jobs done, years in business, vetted and insured. One tap books the job; the other companies are thanked automatically.
- **Minimal input on site:**
  - *Job done* opens the camera; the photo is the proof of completion.
  - *Report an issue* covers extra work, waiting for parts, no access, safety or other, with a photo and/or a **voice note**. AVA routes it: extra work becomes a one-tap approval for the owner, no access asks the tenant to rebook, safety alerts the PM.
- **Close and pay:** the job closes itself 72 h after the photo unless the tenant taps *Not fixed*. The company is paid from trust and the cost comes off the owner's payout.
- **Ratings:** tenants and owners rate overall, plus quality, on time, fair price and communication. Ratings below 3 are moderated, and companies can reply publicly. Public directory with a map: *#/pros*.
- **Browse jobs (the job map):** a company sees every open repair in its trade within its working area on a map and a list. Each job shows the suburb, distance, urgency, photos and how many quotes are in.
  - It can tap **Apply to quote** on jobs that still have room: the 3 invited companies plus up to 2 that apply (`max_quotes_per_job`).
  - Before the owner books it, the company sees only the suburb. No street address, exact pin, tenant name or phone number.
  - Handyman companies are never offered electrical, gas or solar work.
  - Maintenance companies don't see the rental portal: the home page and search go to *Browse jobs*.
- The demo has 58 companies across all nine provinces: one with a lapsed listing, one awaiting vetting.

## Construction snag lists – better measures

Every snag gets:
- a reference (`SN-`, `NCR-` or `HS-`)
- a category, trade, responsible contractor and priority
- a **measured quantity × unit × rate** (cost to rectify)
- a due date from the priority (Urgent 2 days, High 7, Medium 14, Low 21)
- a pin on the room's 360°, with a 'before' photo cut from the 360° automatically

To close a snag:
1. The contractor marks it fixed. An **'after' photo is required**.
2. At the re-inspection (round 2, 3…) the PM closes it, or rejects it for rework.

Measures, per project and per contractor:
- close-out rate
- overdue count
- average days to close
- **first-time-right %** (snags closed without rework)
- open cost to rectify
- snag density per 100 m²
- severity index
- a breakdown by trade

Excel export is under Reports.

## Trust accounting (Admin → Trust accounts)

AVA runs the agency's three bank accounts next to its ledger: the **trust account**, the **deposit trust** (one interest-bearing investment per tenant) and the **business account**.

- **Trust trial balance:** proves to the rand that trust cash equals what is owed to owners plus fees, insurance and contractors not yet paid out. The deposit trust is checked the same way, against deposits plus interest owed to tenants.
- **Bank feeds:**
  - every day the feed brings in the bank's lines and matches them to the cashbook;
  - rent paid with an `AVA00012` reference is allocated by itself;
  - you can also import OFX or CSV statements from any SA bank.
  - Without bank API keys (*Settings → Trust accounting & banking*) the feed is simulated.
- **Reconciliation:** each month, explain every bank line: rent from a tenant, bank charges (the business account refunds trust), or an unidentified receipt (to suspense, allocated later). Then sign off and **lock the month**. Locked months can't change; corrections are **journals** in an open month, with a reason, and they must balance.
- **Payment batches:** money only leaves trust through a batch.
  - Owner payouts are queued automatically.
  - *Prepare fee transfer* moves AVA fees and PM commission to the business account, and pays the insurer and contractors.
  - Each batch is prepared, then authorised (optionally by a second person), then released.
  - Every batch produces a bank file for online banking.
- **Debit orders:**
  - tenants set up a DebiCheck mandate under *Pay rent* and approve it in their banking app;
  - AVA collects the amount due on the debit day through Netcash (batch file included);
  - unpaids go straight to arrears with the bank's reason.
- **Deposits:** each deposit gets its own investment account, opened automatically. Interest is credited monthly and refunded with the deposit.
- **Year-end:** closing the financial year (default: February) locks every month and keeps the trial balance for the auditor (Fidelity Fund certificate).
- **Demo:**
  - a year of payouts and fee transfers;
  - every month up to two months ago reconciled and locked;
  - the March 2025 – February 2026 year closed;
  - nine tenants on debit order, one with an unpaid;
  - last month open, with an R186 bank charge and an unidentified R2 500 to explain.

Before going live, connect the real FNB feed and Netcash keys, check the Netcash batch-file layout against their current spec, and map the payout bank file in your online banking. Account numbers in the demo are made up.

## FICA & POPIA (staff: FICA & POPIA · everyone: Identity & privacy)

- **FICA identity check.** Tenants and owners enter their SA ID or passport and upload an ID copy, a selfie and proof of address. AVA checks these itself:
  - the ID number's check digit, date of birth and citizenship;
  - age (18 or older);
  - proof of address is under 3 months old;
  - the same ID or phone number on another account.
- **Provider checks.** Home Affairs, the selfie face-match and sanctions/PEP screening go to the verification provider. They are simulated until a provider key is set.
- **Result.** Each check is *verified*, *needs a look* or *failed*.
  - A PM approves or rejects a check with a written reason, which the FICA register keeps.
  - A lease can't be approved until the tenant is verified, unless the PM records why (setting `fica_required`).
  - Owner payouts can be held until the owner is verified (setting `fica_hold_payouts`).
- **POPIA consent register.** Each consent is recorded per purpose (service, credit check, FICA, marketing, prospecting), with when, how and which notice version. People change their consents themselves.
- **Data-subject requests.** People can:
  - download all their data as JSON;
  - ask for a correction;
  - object to marketing, which takes effect immediately;
  - ask for deletion.

  The admin answers within 30 days, with reminders. Deletion is refused while a lease is active. Otherwise the profile, contact details, documents and selfie are removed, and lease, payment and FICA records are kept for 5 years.
- **Public notice.** The privacy notice is at `#/privacy-notice`.

## Growth & marketing (PM: Growth & marketing)

- **Owner prospecting.** Searching a suburb pulls the erven from LOOM: owner, owner type, last sale, estimated value and likely rent. Owners who live elsewhere, trusts and companies are flagged as likely investors.
  - Revealing a contact uses one LOOM credit.
  - Prospects move through a pipeline: new → contacted → report sent → interested → signed.
  - "Do not contact" is recorded as a POPIA objection.
  - Demo data is used until a LOOM login is set.
- **"What your home could earn" report.** A branded public page at `#/r/<token>` shows:
  - the likely rent, adjusted for condition, with comparable homes;
  - a traditional agent's fee against AVA's;
  - the monthly payout;
  - the PM's profile;
  - a "call me" form that records consent and creates a PM task.

  The PM sees when the report is opened. Owners can also make their own report at `#/earn`.
- **Condition & finish score (C1–C6).** The score adjusts the rent check: +6%, +3%, 0, −4%, −8% or −12%.
  - With an Anthropic key, Claude scores the home from its photos.
  - Without one, the score comes from the last inspection, or the PM sets it by hand.
  - Capturing the condition belongs in Inspektr; AVA uses the score.
- **Property24 & Private Property syndication.** A live, ready listing is sent with one tick.
  - Each portal reads AVA's feed: `/api/feeds/property24.xml?key=…` and `/api/feeds/privateproperty.xml?key=…`.
  - A listing is withdrawn everywhere when it is let or taken off the market.
  - Portal enquiries land in the leads inbox, where a viewing can be booked.
  - Views and enquiries are simulated until the agency IDs and feed keys are set.
- **Email & SMS campaigns.** Merge fields such as `{first_name}`, `{property}`, `{rent}` and `{brochure}` are filled in per person.
  - *Service* messages go to current tenants and owners.
  - *Marketing* goes only to people who opted in, always with an unsubscribe link or "reply STOP".
  - Preview shows who is left out and why.
  - Sending uses SMTP and BulkSMS when those are set up; otherwise messages are recorded as simulated sends.
- **Automatic greetings.** Birthday messages use the date of birth from the ID number. On a lease anniversary the tenant gets a message and the PM gets a check-in task.
- **PM brochure.** A printable public profile at `#/pm/<id>`: bio, homes, occupancy, on-time rent, fees and live listings.

## Money – how the numbers work

- **Whole rands:** every amount is rounded off (half up) when it is recorded. Ledgers, statements and payouts therefore always add up to the rand.
- **Rent:**
  - A lease's first and last months are **pro rata** when the tenant moves in or out mid-month.
  - Rent escalates by 8% on each anniversary, and the property then shows the new rent.
- **Owner statement:** rent received − AVA platform fee − PM commission − insurance (if taken) − repairs = payout, paid on the 7th.
- **Landlord savings** (owner dashboard): per let home, a traditional agent's 10% + VAT compared with AVA's platform fee + PM commission, per month and per year. It also shows what has already been saved on paid statements. Insurance is optional cover, so it is left out of both sides.
- **PM commission** (*My earnings*): per home, rent × tier % plus the R50 finder's fee, per month and per year. It also shows what the PM would earn if every vacant home were let, and how much more the next tier would pay. The *For agents* page has a calculator for prospective PMs.

## AVA pricing (from AVA_Pricing_20240827.xlsx)

Every number is a setting (Admin → Settings & fees).

- **Tenant**
  - deposit: 1 × rent
  - key deposit: R500
  - inspection: R500 for up to 2 bed + 1 bath, plus R125 per extra room, split 50/50 with the landlord
  - vetting: R450 (the sheet says TBD)
- **Landlord**
  - admin fee: R500 per new contract
  - AVA platform fee per let home, on a sliding scale by homes managed on AVA: R399 (1–5 homes), R349 (6–20), R299 (21–50), R249 (more than 50)
  - insurance: R250/month
  - own administrator: R50
- **Portfolio manager**
  - commission: tiered 3% (first 20 homes), 4% (21–50), 5% (50+); or "chosen" mode, where the PM picks 3–5%
  - finder's fee: R50 per rented listing per month
  - salary targets are shown on *My earnings*

## AI

The AI runs offline with transparent rules: triage, scoring, pricing, sentiment, renewal risk, anomaly detection, quote ranking and the virtual agent.

Add an Anthropic API key under Settings → AI to have Claude write the agent's replies and the listing copy. Claude works from the same facts and falls back to the rules if the call fails.

## Payments

**PayFast:** enter the merchant ID, key and passphrase under Settings → Payments, plus the public URL so the ITN callback can reach the server. Signature and ITN handling are built in. Without them, card payments are simulated and allocated exactly like real ones.

**EFT:** import the CSV from online banking (Money → Import bank CSV). Lines with an `AVA00012`-style reference are matched automatically.

## Turning it into the phone app

The web app already runs as an installable PWA:
- bottom tabs on phones
- camera capture
- signature pad
- 360° viewer

To publish to the stores, wrap `web/` with **Capacitor** (`npx cap add android ios`). The API base then points to the hosted server, and the same code ships on Play Store and App Store.

## Before going live

- Host the API (any VPS or Azure).
- Move SQLite to Postgres or Supabase. The SQL is plain, and AVA's existing app already uses Supabase.
- Connect real **TPN / XDS** credit and rental-history checks. `credit_check` in `server/api.py` is a stub.
- Add WhatsApp next to in-app notifications. Email and SMS go out through SMTP and BulkSMS once set in Settings.
- Sign up with a FICA verification provider (Home Affairs, face match, sanctions/PEP), and register the Information Officer with the Information Regulator.
- Get a LOOM API account, plus Property24 and Private Property agency feed IDs.
- Integrate the trust account bank.
- Do the PPRA / FFC paperwork. The POPIA privacy notice at `#/privacy-notice` needs a legal review.
- Set up off-site backups of `data/`.
- Optional: plug Site Inspect's SAM 3 auto-detection into the inspection rooms. The 360 data model is the same.

## Folders

```
run.py              start the server            start.bat   Windows launcher
server/main.py      FastAPI app                 server/api.py   all HTTP routes (scoped per role)
server/services.py  leases, ledger & payouts, maintenance flow, inspections, snags
server/automation.py  Autopilot (idempotent; runs every 10 min and on demand)
server/ai.py        triage, scoring, pricing, risk, anomalies    server/agent.py  virtual agent
server/compliance.py FICA checks, POPIA consents & requests   server/prospect.py  prospecting, earnings reports, condition score
server/syndicate.py Property24 / Private Property feeds & leads  server/crm.py  campaigns, greetings   server/api_growth.py  their routes
server/fees.py      AVA pricing model           server/marketplace.py  maintenance companies, 10 km matching, ratings           server/seed.py  demo portfolio
web/                front end (plain HTML/CSS/JS, no build step) – js/pano.js is Site Inspect's 360 viewer
demo/panos/         BLK360 G2 panoramas used by the demo
tests/test_flow.py  end-to-end test of the whole life cycle:  python tests/test_flow.py
data/               created on first run: database + uploads (back this up; move with AVA_DATA)
```
