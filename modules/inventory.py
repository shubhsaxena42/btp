"""Inventory: raw + finished stock, movements, adjustments, raw material master."""
from datetime import date as _date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from core.numbers import num
from core import db, stock
from core.i18n import t

bp = Blueprint('inventory', __name__, url_prefix='/inventory')

UNITS = ['kg', 'g', 'litre', 'metre', 'sheet', 'pcs']
REF_TYPES = ['purchase', 'wo_issue', 'wo_return', 'production', 'sale',
             'consignment_out', 'consignment_return', 'adjustment']
PER_PAGE = 100


def _f(val, default=None):
    return num(val, default)


def _valid_date(s):
    try:
        _date.fromisoformat(s or '')
        return True
    except ValueError:
        return False


@bp.route('/')
def index():
    tab = request.args.get('tab', 'finished')
    if tab not in ('raw', 'finished'):
        tab = 'finished'
    today = db.today()
    soon = (_date.fromisoformat(today) + timedelta(days=30)).isoformat()

    products = db.query(
        "SELECT p.*, g.name AS gi_name, g.name_hi AS gi_name_hi, "
        "ps.qty_sellable, ps.qty_pending, ps.qty_at_outlets "
        "FROM product p JOIN v_product_stock ps ON ps.product_id = p.id "
        "JOIN gi g ON g.id = p.gi_id "
        "WHERE p.active = 1 OR ps.qty_sellable + ps.qty_pending + ps.qty_at_outlets > 0 "
        "ORDER BY p.name")
    batches_by_product = {}
    for b in db.query("SELECT * FROM v_batch_stock WHERE qty_on_hand > 0 "
                      "ORDER BY mfg_date, id"):
        batches_by_product.setdefault(b['product_id'], []).append(b)
    raws = db.query("SELECT * FROM v_raw_stock ORDER BY code")

    finished_value = sum((p['qty_sellable'] + p['qty_pending']) * p['price'] for p in products)
    raw_value = sum(max(r['qty_on_hand'], 0) * r['cost_per_unit'] for r in raws)
    low_count = sum(1 for r in raws if r['qty_on_hand'] < r['reorder_level'])
    expiring = db.scalar(
        "SELECT COUNT(*) FROM v_batch_stock WHERE qty_on_hand > 0 AND expiry_date IS NOT NULL "
        "AND expiry_date >= ? AND expiry_date <= ?", (today, soon), 0)
    return render_template('inventory/index.html', tab=tab, products=products,
                           batches_by_product=batches_by_product, raws=raws,
                           finished_value=finished_value, raw_value=raw_value,
                           low_count=low_count, expiring=expiring, today=today, soon=soon)


@bp.route('/movements')
def movements():
    a = request.args
    item_type = a.get('item_type', '')
    ref_type = a.get('ref_type', '')
    raw_id = a.get('raw_material_id', type=int)
    product_id = a.get('product_id', type=int)
    d_from = a.get('date_from', '')
    d_to = a.get('date_to', '')
    page = max(a.get('page', 1, type=int) or 1, 1)

    where, args = [], []
    if item_type in ('raw', 'product'):
        where.append('st.item_type = ?'); args.append(item_type)
    if ref_type in REF_TYPES:
        where.append('st.ref_type = ?'); args.append(ref_type)
    if raw_id:
        where.append('st.raw_material_id = ?'); args.append(raw_id)
    if product_id:
        where.append('st.product_id = ?'); args.append(product_id)
    if _valid_date(d_from):
        where.append('st.date >= ?'); args.append(d_from)
    if _valid_date(d_to):
        where.append('st.date <= ?'); args.append(d_to)
    w = (' WHERE ' + ' AND '.join(where)) if where else ''
    total = db.scalar('SELECT COUNT(*) FROM stock_txn st' + w, args, 0)
    pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
    page = min(page, pages)
    rows = db.query(
        "SELECT st.*, rm.name AS rm_name, rm.name_hi AS rm_name_hi, rm.unit AS rm_unit, "
        "p.name AS p_name, p.name_hi AS p_name_hi, p.unit AS p_unit, b.batch_no "
        "FROM stock_txn st LEFT JOIN raw_material rm ON rm.id = st.raw_material_id "
        "LEFT JOIN product p ON p.id = st.product_id "
        "LEFT JOIN batch b ON b.id = st.batch_id" + w +
        " ORDER BY st.date DESC, st.id DESC LIMIT ? OFFSET ?",
        list(args) + [PER_PAGE, (page - 1) * PER_PAGE])
    qs = {k: v for k, v in a.items() if k != 'page' and v}
    return render_template(
        'inventory/movements.html', rows=rows, total=total, page=page, pages=pages, qs=qs,
        ref_types=REF_TYPES, materials=db.query("SELECT * FROM raw_material ORDER BY name"),
        products=db.query("SELECT * FROM product ORDER BY name"),
        f=dict(item_type=item_type, ref_type=ref_type, raw_material_id=raw_id,
               product_id=product_id, date_from=d_from, date_to=d_to))


def _adjust_ctx(form):
    return dict(
        materials=db.query("SELECT * FROM v_raw_stock ORDER BY name"),
        batches=db.query(
            "SELECT bs.*, p.name AS p_name, p.name_hi AS p_name_hi, p.unit AS p_unit "
            "FROM v_batch_stock bs JOIN product p ON p.id = bs.product_id "
            "ORDER BY bs.batch_no"),
        form=form)


@bp.route('/adjust', methods=['GET', 'POST'])
def adjust():
    if request.method == 'GET':
        form = dict(item_type='batch' if request.args.get('batch_id') else 'raw',
                    raw_material_id=request.args.get('raw_material_id', ''),
                    batch_id=request.args.get('batch_id', ''),
                    qty='', date=db.today(), reason='')
        return render_template('inventory/adjust.html', **_adjust_ctx(form))

    f = request.form
    form = dict(item_type=f.get('item_type', 'raw'), raw_material_id=f.get('raw_material_id', ''),
                batch_id=f.get('batch_id', ''), qty=f.get('qty', ''),
                date=f.get('date', ''), reason=f.get('reason', '').strip())
    err = None
    qty = _f(form['qty'])
    if form['item_type'] not in ('raw', 'batch'):
        err = t('common.invalid_input')
    elif not qty:
        err = t('inventory.err_qty')
    elif not _valid_date(form['date']):
        err = t('common.invalid_input')
    elif not form['reason']:
        err = t('inventory.err_reason')
    if not err:
        try:
            if form['item_type'] == 'raw':
                rm = db.query("SELECT * FROM raw_material WHERE id = ?",
                              (form['raw_material_id'] or 0,), one=True)
                if not rm:
                    err = t('inventory.err_item')
                elif stock.raw_on_hand(rm['id']) + qty < -1e-9:
                    err = t('inventory.err_negative')
                else:
                    stock.add_txn(form['date'], 'raw', qty, 'adjustment',
                                  raw_material_id=rm['id'], note=form['reason'])
            else:
                b = db.query("SELECT * FROM batch WHERE id = ?", (form['batch_id'] or 0,), one=True)
                if not b:
                    err = t('inventory.err_item')
                elif stock.batch_on_hand(b['id']) + qty < -1e-9:
                    err = t('inventory.err_negative')
                else:
                    if qty != int(qty):
                        err = t('inventory.err_whole')
                    else:
                        stock.add_txn(form['date'], 'product', qty, 'adjustment',
                                      product_id=b['product_id'], batch_id=b['id'],
                                      note=form['reason'])
            if not err:
                db.commit()
                flash(t('common.saved'), 'success')
                return redirect(url_for('inventory.index',
                                        tab='raw' if form['item_type'] == 'raw' else 'finished'))
        except stock.StockError as e:
            err = str(e)
        db.rollback()
    flash(err, 'danger')
    return render_template('inventory/adjust.html', **_adjust_ctx(form))


@bp.route('/materials')
def materials():
    rows = db.query("SELECT * FROM v_raw_stock ORDER BY code")
    return render_template('inventory/materials.html', rows=rows)


def _material_form(row, material):
    form = dict(code=row.get('code', ''), name=row.get('name', ''), name_hi=row.get('name_hi', ''),
                unit=row.get('unit', 'kg'), cost_per_unit=row.get('cost_per_unit', ''),
                reorder_level=row.get('reorder_level', ''))
    return render_template('inventory/material_form.html', form=form, material=material,
                           units_opts=[(u, t('unit.' + u)) for u in UNITS])


def _save_material(material):
    f = request.form
    name = f.get('name', '').strip()
    name_hi = f.get('name_hi', '').strip()
    unit = f.get('unit', '')
    cost = _f(f.get('cost_per_unit')) if f.get('cost_per_unit', '').strip() else 0.0
    reorder = _f(f.get('reorder_level')) if f.get('reorder_level', '').strip() else 0.0
    code = (material['code'] if material else f.get('code', '').strip()) or db.next_number('raw_material')
    err = None
    if not name:
        err = t('inventory.err_name')
    elif unit not in UNITS or cost is None or reorder is None or cost < 0 or reorder < 0:
        err = t('common.invalid_input')
    elif db.scalar("SELECT 1 FROM raw_material WHERE code = ? AND id != ?",
                   (code, material['id'] if material else 0)):
        err = t('inventory.err_code')
    if err:
        flash(err, 'danger')
        return _material_form(dict(code=code, name=name, name_hi=name_hi, unit=unit,
                                   cost_per_unit=f.get('cost_per_unit', ''),
                                   reorder_level=f.get('reorder_level', '')), material)
    if material:
        db.execute("UPDATE raw_material SET name=?, name_hi=?, unit=?, cost_per_unit=?, "
                   "reorder_level=? WHERE id=?",
                   (name, name_hi or None, unit, cost, reorder, material['id']))
    else:
        db.execute("INSERT INTO raw_material (code, name, name_hi, unit, cost_per_unit, reorder_level) "
                   "VALUES (?,?,?,?,?,?)", (code, name, name_hi or None, unit, cost, reorder))
    db.commit()
    flash(t('common.saved'), 'success')
    return redirect(url_for('inventory.materials'))


@bp.route('/materials/new', methods=['GET', 'POST'])
def new_material():
    if request.method == 'POST':
        return _save_material(None)
    return _material_form(dict(code=db.next_number('raw_material')), None)


@bp.route('/materials/<int:material_id>/edit', methods=['GET', 'POST'])
def edit_material(material_id):
    m = db.query("SELECT * FROM raw_material WHERE id = ?", (material_id,), one=True)
    if not m:
        abort(404)
    if request.method == 'POST':
        return _save_material(m)
    return _material_form(dict(m), m)
