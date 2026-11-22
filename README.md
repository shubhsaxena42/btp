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
