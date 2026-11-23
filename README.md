# GI Producer ERP

A Flask + SQLite ERP for a GI (Geographical Indication) producer cooperative: members, products and
bills of materials, raw-material purchases, job-work orders, production batches with GI-spec
inspection, GST invoicing, consignments, payments and payouts. English and Hindi UI, no login.
The look follows the sibling GI Authentication Portal; approved batches can be exported in the
portal's 21-column format.

## Modules

dashboard, gi, members, products, inventory, purchases, work_orders, batches (incl. GI portal export),
sales, consignments, customers. See `CONTRACT.md` for endpoints and APIs.

## Run locally

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python seed.py
    .venv/bin/flask --app app run --port 5050

The database is `erp.db` in the project folder (override with the `ERP_DB` environment variable).
If it does not exist it is created from `schema.sql`.

## Deploy to Vercel

Push the repository (with `erp.db` committed) and import it in Vercel; `vercel.json` builds `app.py`
with `@vercel/python`. On Vercel the bundled `erp.db` is copied to `/tmp/erp.db` on first use.
Edits made on Vercel are stored in `/tmp` and reset whenever the instance restarts.
Set `SECRET_KEY` in the project environment.

## Sync with the GI portal
Publishing an approved batch (Batches → batch → Publish) also appends its row to the GI
portal's `database.xlsx` (default: `../GI-Authentication-Portal/database.xlsx`, override
with env `PORTAL_XLSX`). Rows are de-duplicated by Batch Number. If the file isn't
present (e.g. on Vercel) the step is skipped. After syncing, commit the portal's
`database.xlsx` and push so its Vercel deployment picks up the new rows.
Note: the portal shows the first row for an Application Number, so the first row added
per GI is the one buyers see.
