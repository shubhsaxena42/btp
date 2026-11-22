# GI Producer ERP — Build Contract (read fully before writing code)

A Flask + SQLite ERP for a GI (Geographical Indication) producer cooperative in Uttarakhand.
No login. English/Hindi UI. Visual design copied from the sibling project
`../GI-Authentication-Portal` (see its `styles.css`, `index.html`). Hosted on Vercel later.

Several engineers build this **in parallel**. Each owns specific files. **Never edit a file
you don't own.** If you need something from a shared file that is missing, work around it locally
in your own module and mention it in your final report.

- Python 3.12 compatible (Vercel). Dependencies: **Flask, openpyxl, segno only** (+ stdlib).
  No pandas, no Pillow, no ORM, no JS frameworks, **no CDN links** (must work offline).
  Small inline vanilla JS in templates is fine.
- Local venv: `.venv/bin/python` (Flask, openpyxl, segno installed).
- Never write the words "demo", "dummy", "sample", "test data", "lorem" in UI text or data.
- `schema.sql` is the database source of truth (owned by orchestrator). Read it. Use its views.

## Layout

```
app.py                      # Flask app factory + blueprint registration        [foundation]
core/__init__.py                                                                  [foundation]
core/db.py                  # connection + query helpers + numbering           [foundation]
core/stock.py               # stock movements, FIFO allocation, batch creation  [foundation]
core/invoicing.py           # invoice creation + GST split                      [foundation]
core/i18n.py                # t(), L(), language cookie                         [foundation]
core/filters.py             # Jinja filters                                     [foundation]
translations/__init__.py    # loader (auto-imports every module in this folder) [foundation]
translations/common.py      # common.*, nav.*, status.*, mode.*, ... keys       [foundation]
translations/<module>.py    # each module's own keys                            [that module]
templates/base.html         # layout                                            [foundation]
templates/_ui.html          # macros                                            [foundation]
templates/<module>/*.html   # module pages                                      [that module]
static/css/erp.css          # all styles                                        [foundation]
static/img/iit-logo.png, static/img/gi_image.jpeg                               [foundation]
modules/__init__.py                                                               [foundation]
modules/<module>.py         # one Blueprint named `bp` per module               [that module]
seed.py, data/*                                                                   [seed]
vercel.json, requirements.txt, .gitignore, README.md                             [foundation]
```

Modules (file `modules/<name>.py`, blueprint `bp = Blueprint('<name>', __name__, url_prefix=...)`):

| module        | url_prefix       | owner agent      |
|---------------|------------------|------------------|
| dashboard     | `/`              | dashboard        |
| gi            | `/gi`            | gi               |
| members       | `/members`       | members          |
| products      | `/products`      | products         |
| inventory     | `/inventory`     | inventory        |
| purchases     | `/purchases`     | purchases        |
| work_orders   | `/work-orders`   | work_orders      |
| batches       | `/batches`       | batches          |
| sales         | `/sales`         | sales            |
| consignments  | `/consignments`  | consignments     |
| customers     | `/customers`     | customers        |

`app.py` imports each of these; if one fails to import it is skipped (logged), so the app
still runs while others are unfinished.

## Required endpoints (others link to these — implement exactly these names & args)

```
dashboard.index                         GET  /
gi.index                                GET  /gi/
gi.detail(gi_id)                        GET  /gi/<int:gi_id>
gi.edit(gi_id)                          GET/POST /gi/<int:gi_id>/edit      (description, hi name, checklist)
members.index / members.new             GET  /members/   GET/POST /members/new
members.detail(member_id)               GET  /members/<int:member_id>      (profile, GIs, work orders, ledger)
members.edit(member_id)                 GET/POST
members.add_gi(member_id)               POST (link member to a GI as Authorised User)
members.payouts                         GET  /members/payouts              (all payouts + balances owed)
members.new_payout                      GET/POST /members/payouts/new      (?member_id= preselect)
products.index / products.new           GET, GET/POST
products.detail(product_id)             GET  (info, BOM, stock by batch, fair-price calculator)
products.edit(product_id)               GET/POST (incl. BOM rows)
inventory.index                         GET  /inventory/   (raw stock + finished stock by product & batch)
inventory.movements                     GET  /inventory/movements  (filterable stock_txn log)
inventory.adjust                        GET/POST /inventory/adjust
inventory.materials                     GET  /inventory/materials
inventory.new_material                  GET/POST
inventory.edit_material(material_id)    GET/POST
purchases.index / purchases.new         GET, GET/POST   (?member_id= / ?raw_material_id= preselect)
work_orders.index / work_orders.new     GET, GET/POST   (?member_id= / ?product_id= preselect)
work_orders.detail(wo_id)               GET
work_orders.receive(wo_id)              GET/POST  (completes WO, creates batch)
work_orders.cancel(wo_id)               POST
batches.index                           GET  (filter by status / gi / product)
batches.detail(batch_id)                GET  (info, checklist inspection form, stock, portal row, QR)
batches.inspect(batch_id)               POST (approve / reject with checklist)
batches.publish(batch_id)               POST (mark published_on)
batches.qr(batch_id)                    GET  -> image/svg+xml
batches.export_row(batch_id)            GET  -> .xlsx with the single portal row
batches.portal                          GET  /batches/portal  (all published rows table + download)
batches.portal_xlsx                     GET  -> .xlsx of all published rows
sales.index / sales.new                 GET, GET/POST  (?customer_id= preselect)
sales.detail(sale_id)                   GET  (invoice view + payments + add-payment form + WhatsApp share)
sales.print_invoice(sale_id)            GET  (print-optimised tax invoice, standalone page)
sales.add_payment(sale_id)              POST
sales.payments                          GET  /sales/payments
consignments.index / consignments.new   GET, GET/POST
consignments.detail(cn_id)              GET
consignments.record_sale(cn_id)         POST (qty sold per line -> creates invoice)
consignments.record_return(cn_id)       POST (qty returned per line -> stock back)
customers.index / customers.new         GET, GET/POST
customers.detail(customer_id)           GET  (info, invoices, consignments, balance)
customers.edit(customer_id)             GET/POST
```

Always build links with `url_for(...)`. To link to another module's page that may not exist
yet, use the Jinja global `safe_url(endpoint, **kw)` — returns `'#'` if the endpoint is missing.

## core/db.py API

```python
from core import db
db.get_db() -> sqlite3.Connection        # per-request (flask.g), row_factory=sqlite3.Row, FK on
db.query(sql, args=(), one=False)        # list[sqlite3.Row] | sqlite3.Row | None
db.scalar(sql, args=(), default=None)    # first column of first row
db.execute(sql, args=())  -> int         # returns lastrowid; does NOT commit
db.commit(); db.rollback()
db.setting(key, default=None) -> str
db.today() -> 'YYYY-MM-DD'
db.next_number(kind, date=None) -> str   # kind: 'purchase' PUR-0001 | 'work_order' WO-0001 |
                                         # 'consignment' CN-0001 | 'invoice' INV/2026-27/0001 (FY of date) |
                                         # 'member' M-001 | 'customer' C-001 | 'raw_material' RM-001
db.fy(date) -> '2026-27'
```
Uncommitted work is rolled back at request teardown. Pattern for a POST:
```python
try:
    ...db.execute(...)...; stock.add_txn(...)
    db.commit(); flash(t('common.saved'), 'success'); return redirect(...)
except stock.StockError as e:
    db.rollback(); flash(str(e), 'danger')
```

## core/stock.py API (use these for ALL stock writes)

```python
from core import stock
stock.StockError(Exception)                     # message is user-facing (already translated)
stock.add_txn(date, item_type, qty, ref_type, ref_id=None,
              raw_material_id=None, batch_id=None, product_id=None, note=None) -> int
stock.raw_on_hand(raw_material_id) -> float
stock.batch_on_hand(batch_id) -> float
stock.product_sellable(product_id) -> float     # approved batches only
stock.allocate_fifo(product_id, qty) -> list[tuple[batch_id, qty]]
    # from APPROVED batches with stock, oldest mfg_date first (expired batches skipped);
    # raises StockError if not enough. Does NOT write anything.
stock.issue_raw(date, raw_material_id, qty, ref_type, ref_id, note=None)
    # negative raw txn; raises StockError if qty > on hand
stock.create_batch(product_id, qty, mfg_date, member_id=None, work_order_id=None) -> batch_id
    # computes batch_no '{SHORT}-{YYMM}-{NNN}', serial_from/to, expiry from shelf_life_days,
    # status 'pending', inserts +qty 'production' stock txn. Does NOT commit.
```

## core/invoicing.py API (shared by sales + consignments)

```python
from core import invoicing
invoicing.create_invoice(date, customer_id, channel, lines, venue=None,
                         consignment_id=None, notes=None) -> sale_id
    # lines: list of dicts {product_id, batch_id, qty, rate, gst_rate}
    # computes taxable/tax/amount per line (2 dp), subtotal/tax_total/total,
    # is_interstate (customer.state_code != setting org_state_code), invoice_no via
    # db.next_number('invoice', date). Inserts sale + sale_lines. NO stock writes. Does NOT commit.
invoicing.tax_split(sale_row) -> dict(cgst, sgst, igst)   # amounts for display
```

## Environment

- `ERP_DB` env var overrides the DB path (default `<project>/erp.db`).
- On Vercel (`VERCEL` env set) the bundled `erp.db` is copied to `/tmp/erp.db` on first use.
- If the DB file doesn't exist it is created empty from `schema.sql`.

## i18n

- `translations/<module>.py` defines `STRINGS = {'key': ('English', 'हिन्दी'), ...}`.
  Keys are namespaced: `'<module>.<name>'` e.g. `'sales.new_invoice'`. Every key you use
  must exist in your file or in `translations/common.py`. Natural, simple Hindi (Devanagari).
- Python: `from core.i18n import t, L, current_lang`. Jinja globals: `t`, `L`, `lang`.
- `t('key', **fmt)` → string in current language, `.format(**fmt)` applied. Missing key → key.
- `L(row, 'name')` → `row['name_hi']` when lang is `hi` and non-empty, else `row['name']`.
  Use it for gi/product/raw_material/member names and gi/product descriptions, member skill.
- Language switch: `GET /lang/<en|hi>` (foundation) sets cookie and redirects back.
- Flash messages and StockError messages must go through `t()`.

### Keys guaranteed in translations/common.py (use freely; do not redefine)
```
app.title app.subtitle app.footer1 app.footer2 lang.en lang.hi
nav.dashboard nav.gi nav.members nav.products nav.purchases nav.inventory nav.work_orders
nav.batches nav.sales nav.consignments nav.customers nav.portal
common.save common.cancel common.add common.new common.edit common.view common.back
common.delete common.search common.filter common.all common.date common.qty common.rate
common.amount common.total common.status common.actions common.name common.phone common.notes
common.yes common.no common.print common.download common.details common.none_found
common.saved common.select common.from common.to common.unit common.price common.code
common.description common.district common.village common.block common.address common.balance
common.paid common.due common.mode common.reference common.submit common.gst common.hsn
common.member common.members common.product common.products common.customer common.gi
common.batch common.batches common.raw_material common.stock common.month common.type
common.invalid_input common.not_found common.insufficient_stock common.optional common.required
status.pending status.approved status.rejected status.issued status.completed status.cancelled
status.open status.settled status.paid status.partial status.unpaid status.published
status.overdue status.active status.inactive
mode.upi mode.cash mode.bank mode.cheque
channel.counter channel.fair channel.wholesale channel.online channel.consignment
ctype.retail ctype.wholesale ctype.outlet ctype.online ctype.individual
unit.pcs unit.pack unit.set unit.kg unit.g unit.litre unit.metre unit.sheet
ref.purchase ref.wo_issue ref.wo_return ref.production ref.sale ref.consignment_out
ref.consignment_return ref.adjustment
category.Agricultural category.Handicraft category.Manufactured category.Foodstuff category.Natural
```
Translate an enum value with e.g. `t('status.' ~ row.status)`, `t('unit.' ~ p.unit)`.

## Jinja filters / globals (core/filters.py)

- `{{ x|inr }}` → `₹1,23,456.50` (Indian digit grouping, 2 dp). `{{ x|inr0 }}` → no decimals.
- `{{ x|num }}` → quantity without trailing zeros (`12`, `2.5`), Indian grouping.
- `{{ d|dmy }}` → `22/11/2026` from ISO (empty string if None). Portal uses DD/MM/YYYY.
- `{{ s|fromjson }}` → parsed JSON.
- `{{ n|words }}` → amount in words, English, Indian system ("Rupees One Thousand Two Hundred Only").
- globals: `t`, `L`, `lang`, `safe_url`, `today` (ISO), `org` (dict of all settings), `now_fy`.

## Templates & UI

Every page: `{% extends 'base.html' %}`, `{% import '_ui.html' as ui %}`,
`{% block title %}...{% endblock %}`, `{% block content %}...{% endblock %}`,
optional `{% block scripts %}`. `base.html` renders header (IIT logo, app title, org name,
EN/हिन्दी toggle), tricolour strip, blue nav, flash messages, footer.

Macros in `_ui.html`:
```
ui.page_header(title, subtitle=None)         + {% call %} body for action buttons (optional)
ui.card(title=None, tone='primary')          used with {% call ui.card('Title') %}...{% endcall %}
ui.kpi(label, value, sub=None, tone='primary', href=None)   tone: primary|success|warning|danger|saffron
ui.badge(text, tone='neutral')               tone: success|warning|danger|info|neutral|saffron
ui.status_badge(status)                      maps status.* values to tone + translated label
ui.field(name, label, value='', type='text', required=False, options=None,
         step=None, min=None, help=None, placeholder=None, attrs='')
         # type: text|number|date|textarea|select|email|tel|hidden ; options = list of (value, label)
ui.empty(message=None)                       "nothing here" row/box
ui.bar_chart(rows, value_format='inr')       rows = list of (label, value) -> pure CSS horizontal bars
```
CSS classes (static/css/erp.css; palette from the portal: primary #003366, saffron #ec7c27,
green #1a7a3b, light grey #f4f6f9):
`.container` `.page-header` `.card` `.card-header` `.card-body` `.grid-2` `.grid-3` `.grid-4`
`.data-table` (+ `td.num`/`th.num` right aligned, `.row-link` clickable row) `.details-table`
`.btn` `.btn-primary` `.btn-success` `.btn-saffron` `.btn-outline` `.btn-danger` `.btn-sm`
`.form-grid` (responsive 2-col) `.form-row` `.form-actions` `.toolbar` (filter bar)
`.badge` `.badge-{tone}` `.kpi-grid` `.kpi` `.alert .alert-{success|warning|danger|info}`
`.muted` `.text-right` `.nowrap` `.mt-0` `.mb-0` `.no-print` `.tabs` `.tab` `.tab.active`
`.lines-table` (editable line-items table in forms) `.qr-box` `.stack` (vertical gap)

Forms: plain HTML POST forms, server-side validation, re-render with entered values + flash on
error. Use `<input type=date>` with ISO values. Money/qty inputs `type=number step=0.01|1`.
Line-item forms (sales, consignments, BOM): use a table of rows with names like
`product_id[]`, `qty[]` and a small vanilla-JS "Add row" button that clones the last row.

## Business rules

- Only `batch.status='approved'` stock is sellable / consignable / publishable.
- Stock never negative: check before writing (stock.issue_raw / allocate_fifo raise StockError).
- Work order receive: qty_received ≤ qty_ordered (>0); per material `qty_returned ≤ qty_issued`;
  `wage_amount = qty_received * wage_rate`; create batch via `stock.create_batch`; raw returns as
  `wo_return` txns; set status completed, received_on, batch_id.
- Sale: for each line allocate FIFO → one `sale_line` per (batch, qty) with `rate` and
  `gst_rate` from product (rate editable on the form); `-qty` 'sale' txn per batch.
  Interstate if customer.state_code != org_state_code.
- Consignment send: allocate FIFO → `consignment_line` per batch, `-qty` 'consignment_out' txn.
  Record sale: creates a `sale` (channel 'consignment', consignment_id set) for the sold qty,
  **no stock txn** (already out). Record return: `+qty` 'consignment_return' txn.
  When every line has sent == sold + returned → status 'settled'.
- Payment in: amount ≤ invoice due. Payout: any positive amount (warn if > member balance).
- Portal row (21 columns, exact header order of the portal's database.xlsx):
  `Application Number, Product Name, Manufacturer Name, Geographical Indications, Status,
  Serial Number, Batch Number, Manufacturing Date, Expiry Date, Applicant Name,
  Applicant Address, Date of Filing, Class, Goods, Geographical Area, Priority Country,
  Journal Number, Availability Date, Certificate Number, Certificate Date, Registration Valid Upto`
  — dates DD/MM/YYYY, all cells strings, Status = gi.status, Serial Number =
  `"{serial_from} to {serial_to}"`, Manufacturer Name = setting `portal_manufacturer_name`.
  QR encodes `{portal_url}/?id={application_number}` (same as the portal's own QR generator).

## Testing your part

1. `.venv/bin/python -m py_compile modules/<you>.py translations/<you>.py`
2. Parse your templates: `.venv/bin/python -c "import jinja2,glob;e=jinja2.Environment(loader=jinja2.FileSystemLoader('templates'));[e.parse(open(f).read()) for f in glob.glob('templates/<you>/*.html')]"`
3. If `core/db.py` and `erp.db` exist, run the app via Flask's test client and GET/POST every
   route you own, asserting 200/302 in both languages (`/lang/hi`). Use a COPY of erp.db
   (`ERP_DB=/tmp/<you>.db`) so you don't corrupt shared data. If foundation/seed aren't ready yet,
   steps 1–2 are enough; the orchestrator runs integration tests.

Final report (short): files created, endpoints implemented, anything you couldn't do or any
contract gap you worked around.
