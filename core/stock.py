"""All stock writes go through here. Nothing in this module commits."""
import re
from datetime import datetime, timedelta

from core import db
from core.i18n import t, L

EPS = 1e-9


class StockError(Exception):
    """User-facing (already translated) stock problem."""


def add_txn(date, item_type, qty, ref_type, ref_id=None, raw_material_id=None,
            batch_id=None, product_id=None, note=None):
    if item_type == 'raw':
        if not raw_material_id:
            raise StockError(t('common.invalid_input'))
    elif item_type == 'product':
        if not batch_id:
            raise StockError(t('common.invalid_input'))
        if not product_id:
            product_id = db.scalar('SELECT product_id FROM batch WHERE id = ?', (batch_id,))
            if not product_id:
                raise StockError(t('common.not_found'))
    else:
        raise StockError(t('common.invalid_input'))
    return db.execute(
        'INSERT INTO stock_txn (date, item_type, raw_material_id, product_id, batch_id, qty, ref_type, ref_id, note) '
        'VALUES (?,?,?,?,?,?,?,?,?)',
        (date, item_type, raw_material_id if item_type == 'raw' else None,
         product_id if item_type == 'product' else None,
         batch_id if item_type == 'product' else None,
         float(qty), ref_type, ref_id, note))


def raw_on_hand(raw_material_id):
    return float(db.scalar("SELECT SUM(qty) FROM stock_txn WHERE item_type='raw' AND raw_material_id=?",
                           (raw_material_id,), 0))


def batch_on_hand(batch_id):
    return float(db.scalar("SELECT SUM(qty) FROM stock_txn WHERE item_type='product' AND batch_id=?",
                           (batch_id,), 0))


def product_sellable(product_id):
    return float(db.scalar(
        "SELECT qty_sellable FROM v_product_stock WHERE product_id=?", (product_id,), 0))


def allocate_fifo(product_id, qty):
    qty = float(qty)
    rows = db.query(
        "SELECT id, qty_on_hand FROM v_batch_stock WHERE product_id=? AND status='approved' "
        "AND qty_on_hand > 0 AND (expiry_date IS NULL OR expiry_date >= ?) "
        "ORDER BY mfg_date, id", (product_id, db.today()))
    out, need = [], qty
    for r in rows:
        if need <= EPS:
            break
        take = min(need, r['qty_on_hand'])
        out.append((r['id'], take))
        need -= take
    if need > EPS:
        p = db.query('SELECT * FROM product WHERE id=?', (product_id,), one=True)
        available = qty - need
        raise StockError(t('common.insufficient_stock', name=L(p) if p else str(product_id),
                           available=_fmt(available)))
    return out


def _fmt(x):
    return ('%.3f' % x).rstrip('0').rstrip('.') if x else '0'


def issue_raw(date, raw_material_id, qty, ref_type, ref_id, note=None):
    qty = float(qty)
    have = raw_on_hand(raw_material_id)
    if qty > have + EPS:
        rm = db.query('SELECT * FROM raw_material WHERE id=?', (raw_material_id,), one=True)
        raise StockError(t('common.insufficient_stock', name=L(rm) if rm else str(raw_material_id),
                           available=_fmt(have)))
    return add_txn(date, 'raw', -qty, ref_type, ref_id, raw_material_id=raw_material_id, note=note)


def create_batch(product_id, qty, mfg_date, member_id=None, work_order_id=None):
    p = db.query('SELECT p.*, g.short_code FROM product p JOIN gi g ON g.id = p.gi_id WHERE p.id=?',
                 (product_id,), one=True)
    if p is None:
        raise StockError(t('common.not_found'))
    qty = float(qty)
    if qty <= 0:
        raise StockError(t('common.invalid_input'))
    d = datetime.strptime(mfg_date[:10], '%Y-%m-%d')
    prefix = '%s-%s-' % (p['short_code'], d.strftime('%y%m'))
    best = 0
    pat = re.compile('^' + re.escape(prefix) + r'(\d+)$')
    for r in db.query('SELECT batch_no FROM batch WHERE batch_no LIKE ?', (prefix + '%',)):
        m = pat.match(r['batch_no'])
        if m:
            best = max(best, int(m.group(1)))
    batch_no = '%s%03d' % (prefix, best + 1)
    expiry = None
    if p['shelf_life_days']:
        expiry = (d + timedelta(days=int(p['shelf_life_days']))).strftime('%Y-%m-%d')
    bid = db.execute(
        "INSERT INTO batch (batch_no, product_id, gi_id, member_id, work_order_id, qty, mfg_date, expiry_date, "
        "serial_from, serial_to, status) VALUES (?,?,?,?,?,?,?,?,?,?, 'pending')",
        (batch_no, product_id, p['gi_id'], member_id, work_order_id, qty, mfg_date[:10], expiry,
         batch_no + '-001', '%s-%03d' % (batch_no, int(qty))))
    add_txn(mfg_date[:10], 'product', qty, 'production', bid, batch_id=bid, product_id=product_id)
    return bid
