import json
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from core import db, stock
from core.numbers import num
from core.i18n import t

bp = Blueprint('work_orders', __name__, url_prefix='/work-orders')


def _f(v, default=None):
    return num(v, default)


def _iso(v):
    try:
        return date.fromisoformat((v or '').strip()).isoformat()
    except ValueError:
        return None


def _get_wo(wo_id):
    wo = db.query(
        "SELECT w.*, m.code AS member_code, m.name AS member_name, m.name_hi AS member_name_hi,"
        " p.sku, p.name AS product_name, p.name_hi AS product_name_hi, p.unit, p.gi_id,"
        " g.name AS gi_name, g.name_hi AS gi_name_hi, b.batch_no"
        " FROM work_order w JOIN member m ON m.id=w.member_id JOIN product p ON p.id=w.product_id"
        " JOIN gi g ON g.id=p.gi_id LEFT JOIN batch b ON b.id=w.batch_id WHERE w.id=?",
        (wo_id,), one=True)
    if not wo:
        abort(404)
    return wo


def _materials(wo_id):
    return db.query(
        "SELECT wm.*, rm.code, rm.name, rm.name_hi, rm.unit FROM work_order_material wm"
        " JOIN raw_material rm ON rm.id=wm.raw_material_id WHERE wm.work_order_id=? ORDER BY wm.id",
        (wo_id,))


@bp.route('/')
def index():
    status = request.args.get('status', 'issued')
    if status not in ('issued', 'completed', 'cancelled', 'all'):
        status = 'issued'
    member_id = request.args.get('member_id', type=int)
    product_id = request.args.get('product_id', type=int)
    where, args = [], []
    if status != 'all':
        where.append('w.status=?'); args.append(status)
    if member_id:
        where.append('w.member_id=?'); args.append(member_id)
    if product_id:
        where.append('w.product_id=?'); args.append(product_id)
    rows = db.query(
        "SELECT w.*, m.name AS member_name, m.name_hi AS member_name_hi,"
        " p.name AS product_name, p.name_hi AS product_name_hi, p.unit, b.batch_no"
        " FROM work_order w JOIN member m ON m.id=w.member_id JOIN product p ON p.id=w.product_id"
        " LEFT JOIN batch b ON b.id=w.batch_id"
        + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY w.issued_on DESC, w.id DESC",
        args)
    today = db.today()
    month = today[:7]
    kpi = dict(
        open=db.scalar("SELECT COUNT(*) FROM work_order WHERE status='issued'", default=0),
        overdue=db.scalar("SELECT COUNT(*) FROM work_order WHERE status='issued' AND due_on IS NOT NULL AND due_on<?", (today,), default=0),
        completed=db.scalar("SELECT COUNT(*) FROM work_order WHERE status='completed' AND substr(received_on,1,7)=?", (month,), default=0),
        wages=db.scalar("SELECT COALESCE(SUM(wage_amount),0) FROM work_order WHERE status='completed' AND substr(received_on,1,7)=?", (month,), default=0),
    )
    members = db.query("SELECT id, name, name_hi FROM member ORDER BY name")
    products = db.query("SELECT id, name, name_hi FROM product ORDER BY name")
    return render_template('work_orders/index.html', rows=rows, status=status, member_id=member_id,
                           product_id=product_id, kpi=kpi, members=members, products=products, today=today)


def _form_data():
    members = db.query("SELECT id, code, name, name_hi FROM member WHERE active=1 ORDER BY name")
    mgi = {}
    for r in db.query("SELECT member_id, gi_id FROM member_gi"):
        mgi.setdefault(r['member_id'], []).append(r['gi_id'])
    products = db.query("SELECT id, sku, name, name_hi, gi_id, piece_rate, unit FROM product WHERE active=1 ORDER BY name")
    bom = {}
    for r in db.query("SELECT pm.product_id, pm.raw_material_id, pm.qty_per_unit FROM product_material pm"):
        bom.setdefault(r['product_id'], []).append(
            {'rm': r['raw_material_id'], 'q': r['qty_per_unit']})
    raws = db.query("SELECT id, code, name, name_hi, unit, qty_on_hand FROM v_raw_stock ORDER BY name")
    return members, mgi, products, bom, raws


def _render_new(values, status=200):
    members, mgi, products, bom, raws = _form_data()
    return render_template('work_orders/new.html', members=members, mgi=mgi, products=products,
                           bom=bom, raws=raws, v=values), status


@bp.route('/new', methods=['GET', 'POST'])
def new():
    if request.method == 'GET':
        today = db.today()
        pid = request.args.get('product_id', type=int)
        prod = db.query("SELECT piece_rate FROM product WHERE id=?", (pid,), one=True) if pid else None
        v = dict(member_id=request.args.get('member_id', type=int), product_id=pid, qty='',
                 issued_on=today, due_on=(date.fromisoformat(today) + timedelta(days=14)).isoformat(),
                 wage_rate=prod['piece_rate'] if prod else '', notes='', lines=[])
        return _render_new(v)

    form = request.form
    member_id = form.get('member_id', type=int)
    product_id = form.get('product_id', type=int)
    qty = _f(form.get('qty'))
    issued_on = _iso(form.get('issued_on'))
    due_on = _iso(form.get('due_on')) if form.get('due_on') else None
    wage_rate = _f(form.get('wage_rate'))
    notes = (form.get('notes') or '').strip()
    lines, bad_line = [], False
    for rid, q in zip(form.getlist('rm_id[]'), form.getlist('mat_qty[]')):
        if not rid.strip() and not q.strip():
            continue
        rid, q = (int(rid) if rid.isdigit() else None), _f(q)
        if rid and q is not None:
            lines.append({'rm': rid, 'q': q})
        else:
            bad_line = True
    v = dict(member_id=member_id, product_id=product_id, qty=form.get('qty', ''),
             issued_on=form.get('issued_on', ''), due_on=form.get('due_on', ''),
             wage_rate=form.get('wage_rate', ''), notes=notes, lines=lines)

    prod = db.query("SELECT * FROM product WHERE id=?", (product_id,), one=True) if product_id else None
    member = db.query("SELECT * FROM member WHERE id=? AND active=1", (member_id,), one=True) if member_id else None
    if (not prod or not member or not qty or qty <= 0 or qty != int(qty) or not issued_on
            or wage_rate is None or wage_rate < 0 or (form.get('due_on') and not due_on)
            or (due_on and due_on < issued_on)
            or bad_line or not lines or any(l['q'] <= 0 for l in lines)
            or len({l['rm'] for l in lines}) != len(lines)):
        flash(t('common.invalid_input'), 'danger')
        return _render_new(v, 400)
    if not db.scalar("SELECT 1 FROM member_gi WHERE member_id=? AND gi_id=?", (member_id, prod['gi_id'])):
        flash(t('work_orders.not_au'), 'danger')
        return _render_new(v, 400)
    try:
        wo_no = db.next_number('work_order', issued_on)
        wo_id = db.execute(
            "INSERT INTO work_order (wo_no, member_id, product_id, qty_ordered, issued_on, due_on,"
            " status, wage_rate, notes) VALUES (?,?,?,?,?,?,'issued',?,?)",
            (wo_no, member_id, product_id, int(qty), issued_on, due_on, wage_rate, notes or None))
        for l in lines:
            if not db.scalar("SELECT 1 FROM raw_material WHERE id=?", (l['rm'],)):
                abort(400)
            db.execute("INSERT INTO work_order_material (work_order_id, raw_material_id, qty_issued)"
                       " VALUES (?,?,?)", (wo_id, l['rm'], l['q']))
            stock.issue_raw(issued_on, l['rm'], l['q'], 'wo_issue', wo_id)
        db.commit()
    except stock.StockError as e:
        db.rollback()
        flash(str(e), 'danger')
        return _render_new(v, 400)
    flash(t('work_orders.created', wo_no=wo_no), 'success')
    return redirect(url_for('work_orders.detail', wo_id=wo_id))


@bp.route('/<int:wo_id>')
def detail(wo_id):
    wo = _get_wo(wo_id)
    return render_template('work_orders/detail.html', wo=wo, mats=_materials(wo_id), today=db.today())


@bp.route('/<int:wo_id>/receive', methods=['GET', 'POST'])
def receive(wo_id):
    wo = _get_wo(wo_id)
    if wo['status'] != 'issued':
        flash(t('work_orders.not_open'), 'warning')
        return redirect(url_for('work_orders.detail', wo_id=wo_id))
    mats = _materials(wo_id)
    v = dict(received_on=db.today(), qty=int(wo['qty_ordered']), notes='',
             returned={m['id']: 0 for m in mats})
    if request.method == 'POST':
        form = request.form
        received_on = _iso(form.get('received_on'))
        qty = _f(form.get('qty_received'))
        returned, ok = {}, True
        for m in mats:
            raw_r = (form.get(f'returned_{m["id"]}') or '').strip()
            r = _f(raw_r) if raw_r else 0.0
            if r is None:
                r, ok = 0.0, False
            returned[m['id']] = r
            if r < 0 or r > m['qty_issued'] + 1e-9:
                ok = False
        v = dict(received_on=form.get('received_on', ''), qty=form.get('qty_received', ''),
                 notes=(form.get('notes') or '').strip(), returned=returned)
        if (not ok or not received_on or received_on < wo['issued_on'] or not qty or qty <= 0
                or qty != int(qty) or qty > wo['qty_ordered']):
            flash(t('common.invalid_input'), 'danger')
            return render_template('work_orders/receive.html', wo=wo, mats=mats, v=v), 400
        qty = int(qty)
        try:
            for m in mats:
                r = returned[m['id']]
                if r > 0:
                    db.execute("UPDATE work_order_material SET qty_returned=? WHERE id=?", (r, m['id']))
                    stock.add_txn(received_on, 'raw', r, 'wo_return', wo_id, raw_material_id=m['raw_material_id'])
            batch_id = stock.create_batch(wo['product_id'], qty, received_on, wo['member_id'], wo_id)
            wage = round(qty * wo['wage_rate'], 2)
            note = '\n'.join(x for x in (wo['notes'], v['notes']) if x) or None
            db.execute("UPDATE work_order SET status='completed', qty_received=?, received_on=?,"
                       " wage_amount=?, batch_id=?, notes=? WHERE id=?",
                       (qty, received_on, wage, batch_id, note, wo_id))
            batch_no = db.scalar("SELECT batch_no FROM batch WHERE id=?", (batch_id,))
            db.commit()
        except stock.StockError as e:
            db.rollback()
            flash(str(e), 'danger')
            return render_template('work_orders/receive.html', wo=wo, mats=mats, v=v), 400
        flash(t('work_orders.received_msg', batch_no=batch_no), 'success')
        target = url_for('batches.detail', batch_id=batch_id) if 'batches.detail' in _endpoints() \
            else url_for('work_orders.detail', wo_id=wo_id)
        return redirect(target)
    return render_template('work_orders/receive.html', wo=wo, mats=mats, v=v)


def _endpoints():
    from flask import current_app
    return {r.endpoint for r in current_app.url_map.iter_rules()}


@bp.route('/<int:wo_id>/cancel', methods=['POST'])
def cancel(wo_id):
    wo = _get_wo(wo_id)
    if wo['status'] != 'issued':
        flash(t('work_orders.not_open'), 'warning')
        return redirect(url_for('work_orders.detail', wo_id=wo_id))
    today = db.today()
    for m in _materials(wo_id):
        if m['qty_issued'] > 0:
            db.execute("UPDATE work_order_material SET qty_returned=qty_issued WHERE id=?", (m['id'],))
            stock.add_txn(today, 'raw', m['qty_issued'], 'wo_return', wo_id, raw_material_id=m['raw_material_id'])
    db.execute("UPDATE work_order SET status='cancelled' WHERE id=?", (wo_id,))
    db.commit()
    flash(t('work_orders.cancelled_msg', wo_no=wo['wo_no']), 'success')
    return redirect(url_for('work_orders.detail', wo_id=wo_id))
