-- GI Producer ERP — SQLite schema (source of truth; owned by orchestrator, do not edit)
-- Conventions: dates are ISO strings 'YYYY-MM-DD'; money is REAL rupees; qty REAL.

PRAGMA foreign_keys = ON;

-- Key/value settings for the producer organisation.
-- Keys: org_name, org_name_hi, org_address, org_address_hi, org_district, org_state,
--       org_state_code ('05' = Uttarakhand), org_gstin, org_phone, org_email, org_upi,
--       org_bank, portal_url ('https://gi-authentication-portal.vercel.app'),
--       portal_manufacturer_name (value written to the portal's "Manufacturer Name" column)
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS gi (
    id                 INTEGER PRIMARY KEY,
    application_number TEXT NOT NULL UNIQUE,
    name               TEXT NOT NULL,
    name_hi            TEXT,
    short_code         TEXT NOT NULL UNIQUE,      -- 3-4 uppercase letters, used in batch numbers (e.g. AIP)
    category           TEXT,                      -- Agricultural | Handicraft | Manufactured | Foodstuff | Natural
    applicant_name     TEXT,
    applicant_address  TEXT,
    date_of_filing     TEXT,
    class              TEXT,
    goods              TEXT,
    geographical_area  TEXT,
    priority_country   TEXT DEFAULT 'India',
    journal_number     TEXT,
    availability_date  TEXT,
    certificate_number TEXT,
    certificate_date   TEXT,
    valid_upto         TEXT,
    status             TEXT,                      -- e.g. 'Registered'
    description        TEXT,
    description_hi     TEXT,
    checklist          TEXT NOT NULL DEFAULT '[]', -- JSON: [{"en": "...", "hi": "..."}, ...] GI-spec checks for batch inspection
    source_urls        TEXT NOT NULL DEFAULT '[]'  -- JSON list of URLs
);

CREATE TABLE IF NOT EXISTS member (
    id           INTEGER PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,            -- 'M-001'
    name         TEXT NOT NULL,
    name_hi      TEXT,
    gender       TEXT,                            -- 'F' | 'M' | 'O'
    phone        TEXT,
    village      TEXT,
    block        TEXT,
    district     TEXT,
    shg_name     TEXT,                            -- self-help group
    skill        TEXT,
    skill_hi     TEXT,
    upi_id       TEXT,
    bank_account TEXT,
    ifsc         TEXT,
    joined_on    TEXT,
    active       INTEGER NOT NULL DEFAULT 1,
    notes        TEXT
);

-- Which GI a member is an Authorised User (AU) of.
CREATE TABLE IF NOT EXISTS member_gi (
    id               INTEGER PRIMARY KEY,
    member_id        INTEGER NOT NULL REFERENCES member(id),
    gi_id            INTEGER NOT NULL REFERENCES gi(id),
    au_number        TEXT,
    au_registered_on TEXT,
    au_valid_upto    TEXT,
    UNIQUE (member_id, gi_id)
);

CREATE TABLE IF NOT EXISTS raw_material (
    id            INTEGER PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,           -- 'RM-001'
    name          TEXT NOT NULL,
    name_hi       TEXT,
    unit          TEXT NOT NULL,                  -- kg | g | litre | metre | sheet | pcs
    cost_per_unit REAL NOT NULL DEFAULT 0,
    reorder_level REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS product (
    id              INTEGER PRIMARY KEY,
    sku             TEXT NOT NULL UNIQUE,         -- e.g. 'AIP-WP12'
    name            TEXT NOT NULL,
    name_hi         TEXT,
    gi_id           INTEGER NOT NULL REFERENCES gi(id),
    unit            TEXT NOT NULL,                -- pcs | pack | set  (always whole numbers)
    hsn             TEXT,
    gst_rate        REAL NOT NULL DEFAULT 5,      -- percent
    price           REAL NOT NULL,                -- selling price per unit, EXCLUDING GST
    piece_rate      REAL NOT NULL DEFAULT 0,      -- wage paid to the member per unit produced
    material_cost   REAL NOT NULL DEFAULT 0,      -- fair-price calculator inputs (per unit)
    labour_hours    REAL NOT NULL DEFAULT 0,
    labour_rate     REAL NOT NULL DEFAULT 0,      -- rupees per hour
    overhead_pct    REAL NOT NULL DEFAULT 10,
    margin_pct      REAL NOT NULL DEFAULT 20,
    shelf_life_days INTEGER,                      -- NULL = non-perishable
    description     TEXT,
    description_hi  TEXT,
    active          INTEGER NOT NULL DEFAULT 1
);

-- Bill of materials: raw material needed per ONE unit of product.
CREATE TABLE IF NOT EXISTS product_material (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES product(id),
    raw_material_id INTEGER NOT NULL REFERENCES raw_material(id),
    qty_per_unit    REAL NOT NULL,
    UNIQUE (product_id, raw_material_id)
);

-- Raw material coming in. Supplier is EITHER a member (e.g. farmer supplying raw rajma —
-- amount is credited to that member's ledger) OR an outside vendor (supplier_name; paid on the spot).
CREATE TABLE IF NOT EXISTS purchase (
    id              INTEGER PRIMARY KEY,
    purchase_no     TEXT NOT NULL UNIQUE,         -- 'PUR-0001'
    date            TEXT NOT NULL,
    raw_material_id INTEGER NOT NULL REFERENCES raw_material(id),
    qty             REAL NOT NULL,
    rate            REAL NOT NULL,
    amount          REAL NOT NULL,                -- qty * rate
    member_id       INTEGER REFERENCES member(id),
    supplier_name   TEXT,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS customer (
    id             INTEGER PRIMARY KEY,
    code           TEXT NOT NULL UNIQUE,          -- 'C-001'
    name           TEXT NOT NULL,
    type           TEXT NOT NULL,                 -- retail | wholesale | outlet | online | individual
    contact_person TEXT,
    phone          TEXT,
    email          TEXT,
    gstin          TEXT,
    address        TEXT,
    city           TEXT,
    state          TEXT NOT NULL DEFAULT 'Uttarakhand',
    state_code     TEXT NOT NULL DEFAULT '05',
    notes          TEXT
);

-- Job work: raw material issued to a member who makes product at home.
CREATE TABLE IF NOT EXISTS work_order (
    id           INTEGER PRIMARY KEY,
    wo_no        TEXT NOT NULL UNIQUE,            -- 'WO-0001'
    member_id    INTEGER NOT NULL REFERENCES member(id),
    product_id   INTEGER NOT NULL REFERENCES product(id),
    qty_ordered  REAL NOT NULL,
    issued_on    TEXT NOT NULL,
    due_on       TEXT,
    status       TEXT NOT NULL DEFAULT 'issued',  -- issued | completed | cancelled
    qty_received REAL,
    received_on  TEXT,
    wage_rate    REAL NOT NULL,                   -- copied from product.piece_rate at issue time
    wage_amount  REAL NOT NULL DEFAULT 0,         -- qty_received * wage_rate (set on completion)
    batch_id     INTEGER REFERENCES batch(id),
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS work_order_material (
    id              INTEGER PRIMARY KEY,
    work_order_id   INTEGER NOT NULL REFERENCES work_order(id),
    raw_material_id INTEGER NOT NULL REFERENCES raw_material(id),
    qty_issued      REAL NOT NULL,
    qty_returned    REAL NOT NULL DEFAULT 0
);

-- A production batch of finished GI goods. Only status='approved' stock can be sold or published.
CREATE TABLE IF NOT EXISTS batch (
    id               INTEGER PRIMARY KEY,
    batch_no         TEXT NOT NULL UNIQUE,        -- '{GI short_code}-{YYMM}-{NNN}', e.g. 'AIP-2611-004'
    product_id       INTEGER NOT NULL REFERENCES product(id),
    gi_id            INTEGER NOT NULL REFERENCES gi(id),
    member_id        INTEGER REFERENCES member(id),
    work_order_id    INTEGER REFERENCES work_order(id),
    qty              REAL NOT NULL,
    mfg_date         TEXT NOT NULL,
    expiry_date      TEXT,                        -- mfg_date + product.shelf_life_days, else NULL
    serial_from      TEXT,                        -- '{batch_no}-001'
    serial_to        TEXT,                        -- '{batch_no}-{qty:03d}'
    status           TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected
    checklist_result TEXT NOT NULL DEFAULT '[]',  -- JSON list of booleans aligned with gi.checklist
    inspected_by     TEXT,
    inspected_on     TEXT,
    inspection_notes TEXT,
    published_on     TEXT                         -- date pushed to the GI portal export
);

-- Every stock movement. qty is signed: + in, - out.
-- item_type='raw'     -> raw_material_id set
-- item_type='product' -> batch_id AND product_id set
-- ref_type: purchase | wo_issue | wo_return | production | sale | consignment_out | consignment_return | adjustment
CREATE TABLE IF NOT EXISTS stock_txn (
    id              INTEGER PRIMARY KEY,
    date            TEXT NOT NULL,
    item_type       TEXT NOT NULL CHECK (item_type IN ('raw', 'product')),
    raw_material_id INTEGER REFERENCES raw_material(id),
    product_id      INTEGER REFERENCES product(id),
    batch_id        INTEGER REFERENCES batch(id),
    qty             REAL NOT NULL,
    ref_type        TEXT NOT NULL,
    ref_id          INTEGER,
    note            TEXT
);

CREATE TABLE IF NOT EXISTS consignment (
    id          INTEGER PRIMARY KEY,
    cn_no       TEXT NOT NULL UNIQUE,             -- 'CN-0001'
    customer_id INTEGER NOT NULL REFERENCES customer(id),
    sent_on     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',     -- open | settled (settled = nothing left at outlet)
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS consignment_line (
    id             INTEGER PRIMARY KEY,
    consignment_id INTEGER NOT NULL REFERENCES consignment(id),
    product_id     INTEGER NOT NULL REFERENCES product(id),
    batch_id       INTEGER NOT NULL REFERENCES batch(id),
    qty_sent       REAL NOT NULL,
    qty_sold       REAL NOT NULL DEFAULT 0,
    qty_returned   REAL NOT NULL DEFAULT 0,
    rate           REAL NOT NULL                  -- per unit excl. GST
);

-- Tax invoice. channel: counter | fair | wholesale | online | consignment
-- Intra-state (customer.state_code == org_state_code) => CGST+SGST split equally; else IGST.
CREATE TABLE IF NOT EXISTS sale (
    id             INTEGER PRIMARY KEY,
    invoice_no     TEXT NOT NULL UNIQUE,          -- 'INV/2026-27/0001' (Indian financial year Apr–Mar)
    date           TEXT NOT NULL,
    customer_id    INTEGER NOT NULL REFERENCES customer(id),
    channel        TEXT NOT NULL,
    venue          TEXT,                          -- e.g. fair name for channel='fair'
    is_interstate  INTEGER NOT NULL DEFAULT 0,
    subtotal       REAL NOT NULL DEFAULT 0,       -- sum of taxable values
    tax_total      REAL NOT NULL DEFAULT 0,
    total          REAL NOT NULL DEFAULT 0,       -- subtotal + tax_total, rounded to 2 dp
    consignment_id INTEGER REFERENCES consignment(id),
    notes          TEXT
);

CREATE TABLE IF NOT EXISTS sale_line (
    id         INTEGER PRIMARY KEY,
    sale_id    INTEGER NOT NULL REFERENCES sale(id),
    product_id INTEGER NOT NULL REFERENCES product(id),
    batch_id   INTEGER REFERENCES batch(id),
    qty        REAL NOT NULL,
    rate       REAL NOT NULL,                     -- excl. GST
    gst_rate   REAL NOT NULL,
    taxable    REAL NOT NULL,                     -- qty * rate
    tax        REAL NOT NULL,                     -- taxable * gst_rate / 100
    amount     REAL NOT NULL                      -- taxable + tax
);

-- Money received from customers, always against an invoice.
CREATE TABLE IF NOT EXISTS payment_in (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,
    sale_id     INTEGER NOT NULL REFERENCES sale(id),
    customer_id INTEGER NOT NULL REFERENCES customer(id),
    amount      REAL NOT NULL,
    mode        TEXT NOT NULL,                    -- upi | cash | bank | cheque
    reference   TEXT,
    notes       TEXT
);

-- Money paid to members (wages / produce).
CREATE TABLE IF NOT EXISTS payout (
    id        INTEGER PRIMARY KEY,
    date      TEXT NOT NULL,
    member_id INTEGER NOT NULL REFERENCES member(id),
    amount    REAL NOT NULL,
    mode      TEXT NOT NULL,                      -- upi | cash | bank | cheque
    reference TEXT,
    notes     TEXT
);

CREATE INDEX IF NOT EXISTS ix_stock_raw   ON stock_txn(raw_material_id);
CREATE INDEX IF NOT EXISTS ix_stock_batch ON stock_txn(batch_id);
CREATE INDEX IF NOT EXISTS ix_sale_cust   ON sale(customer_id);
CREATE INDEX IF NOT EXISTS ix_pay_sale    ON payment_in(sale_id);
CREATE INDEX IF NOT EXISTS ix_wo_member   ON work_order(member_id);

-- ===================== VIEWS (read these instead of re-implementing sums) =====================

CREATE VIEW IF NOT EXISTS v_raw_stock AS
SELECT rm.*,
       COALESCE((SELECT SUM(st.qty) FROM stock_txn st
                 WHERE st.item_type = 'raw' AND st.raw_material_id = rm.id), 0) AS qty_on_hand
FROM raw_material rm;

-- Store stock per batch (goods sitting at an outlet on consignment are NOT counted here).
CREATE VIEW IF NOT EXISTS v_batch_stock AS
SELECT b.*,
       COALESCE((SELECT SUM(st.qty) FROM stock_txn st
                 WHERE st.item_type = 'product' AND st.batch_id = b.id), 0) AS qty_on_hand
FROM batch b;

CREATE VIEW IF NOT EXISTS v_product_stock AS
SELECT p.id AS product_id,
       COALESCE(SUM(CASE WHEN bs.status = 'approved' THEN bs.qty_on_hand END), 0) AS qty_sellable,
       COALESCE(SUM(CASE WHEN bs.status = 'pending'  THEN bs.qty_on_hand END), 0) AS qty_pending,
       COALESCE((SELECT SUM(cl.qty_sent - cl.qty_sold - cl.qty_returned)
                 FROM consignment_line cl WHERE cl.product_id = p.id), 0)          AS qty_at_outlets
FROM product p
LEFT JOIN v_batch_stock bs ON bs.product_id = p.id
GROUP BY p.id;

-- Member ledger: credit = money the cooperative owes the member; debit = money paid out.
CREATE VIEW IF NOT EXISTS v_member_ledger AS
SELECT member_id, received_on AS date, 'wage' AS kind, id AS ref_id, wo_no AS ref,
       wage_amount AS credit, 0 AS debit
FROM work_order WHERE status = 'completed'
UNION ALL
SELECT member_id, date, 'produce' AS kind, id AS ref_id, purchase_no AS ref,
       amount AS credit, 0 AS debit
FROM purchase WHERE member_id IS NOT NULL
UNION ALL
SELECT member_id, date, 'payout' AS kind, id AS ref_id, COALESCE(reference, '') AS ref,
       0 AS credit, amount AS debit
FROM payout;

CREATE VIEW IF NOT EXISTS v_member_balance AS
SELECT m.id AS member_id,
       COALESCE(SUM(l.credit), 0)           AS earned,
       COALESCE(SUM(l.debit), 0)            AS paid,
       COALESCE(SUM(l.credit - l.debit), 0) AS balance
FROM member m LEFT JOIN v_member_ledger l ON l.member_id = m.id
GROUP BY m.id;

CREATE VIEW IF NOT EXISTS v_sale_status AS
SELECT s.*,
       COALESCE((SELECT SUM(p.amount) FROM payment_in p WHERE p.sale_id = s.id), 0) AS paid,
       ROUND(s.total - COALESCE((SELECT SUM(p.amount) FROM payment_in p WHERE p.sale_id = s.id), 0), 2) AS due,
       CASE
         WHEN COALESCE((SELECT SUM(p.amount) FROM payment_in p WHERE p.sale_id = s.id), 0) >= s.total - 0.005 THEN 'paid'
         WHEN COALESCE((SELECT SUM(p.amount) FROM payment_in p WHERE p.sale_id = s.id), 0) > 0 THEN 'partial'
         ELSE 'unpaid'
       END AS pay_status
FROM sale s;

CREATE VIEW IF NOT EXISTS v_customer_balance AS
SELECT c.id AS customer_id,
       COALESCE((SELECT SUM(total)  FROM sale       WHERE customer_id = c.id), 0) AS invoiced,
       COALESCE((SELECT SUM(amount) FROM payment_in WHERE customer_id = c.id), 0) AS received,
       ROUND(COALESCE((SELECT SUM(total)  FROM sale       WHERE customer_id = c.id), 0)
           - COALESCE((SELECT SUM(amount) FROM payment_in WHERE customer_id = c.id), 0), 2) AS balance
FROM customer c;
