from datetime import date as _date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from core import db, stock
from core.numbers import num
from core.i18n import t

bp = Blueprint('purchases', __name__, url_prefix='/purchases')


def _num(v, default=None):
    return num(v, default)


@bp.route('/')
def index():
    material = request.args.get('raw_material_id', type=int)
    stype = request.args.get('supplier_type', 'all')
    member = request.args.get('member_id', type=int)
    month = (request.args.get('month') or '').strip()
    q = (request.args.get('q') or '').strip()

    where, args = [], []
    if material:
        where.append('p.raw_material_id = ?'); args.append(material)
    if stype == 'members':
        where.append('p.member_id IS NOT NULL')
    elif stype == 'vendors':
        where.append('p.member_id IS NULL')
    if member:
        where.append('p.member_id = ?'); args.append(member)
    if len(month) == 7:
        where.append("substr(p.date,1,7) = ?"); args.append(month)
    if q:
        where.append('(p.purchase_no LIKE ? OR p.supplier_name LIKE ? OR p.notes LIKE ? '
                     'OR m.name LIKE ? OR r.name LIKE ?)')
        args += [f'%{q}%'] * 5
    w = ('WHERE ' + ' AND '.join(where)) if where else ''
    rows = db.query(
        'SELECT p.*, r.name AS rm_name, r.name_hi AS rm_name_hi, r.unit AS unit, '
        'm.name AS m_name, m.name_hi AS m_name_hi '
        'FROM purchase p JOIN raw_material r ON r.id = p.raw_material_id '
        'LEFT JOIN member m ON m.id = p.member_id '
        f'{w} ORDER BY p.date DESC, p.id DESC', args)
    total_amount = round(sum(r['amount'] for r in rows), 2)

    cur = db.today()[:7]
    kpi = db.query(
        'SELECT COALESCE(SUM(amount),0) AS tot, '
        'COALESCE(SUM(CASE WHEN member_id IS NOT NULL THEN amount END),0) AS mem, '
        'COALESCE(SUM(CASE WHEN member_id IS NULL THEN amount END),0) AS ven '
        'FROM purchase WHERE substr(date,1,7) = ?', (cur,), one=True)
    months = [r[0] for r in db.query(
        'SELECT DISTINCT substr(date,1,7) AS m FROM purchase ORDER BY m DESC')]
    materials = db.query('SELECT * FROM raw_material ORDER BY name')
    members = db.query('SELECT * FROM member ORDER BY name')
    return render_template('purchases/index.html', rows=rows, total_amount=total_amount,
                           kpi=kpi, months=months, materials=materials, members=members,
                           f=dict(material=material, stype=stype, member=member,
                                  month=month, q=q))


def _form_data(src=None):
    src = src or {}
    return dict(
        date=src.get('date') or db.today(),
        raw_material_id=src.get('raw_material_id') or '',
        qty=src.get('qty') or '',
        rate=src.get('rate') or '',
        supplier_type=src.get('supplier_type') or 'member',
        member_id=src.get('member_id') or '',
        supplier_name=src.get('supplier_name') or '',
        notes=src.get('notes') or '',
        update_cost=bool(src.get('update_cost')),
    )


def _render_form(form):
    materials = db.query('SELECT * FROM raw_material ORDER BY name')
    onhand = {m['id']: stock.raw_on_hand(m['id']) for m in materials}
    members = db.query('SELECT * FROM member WHERE active = 1 ORDER BY name')
    return render_template('purchases/form.html', form=form, materials=materials,
                           onhand=onhand, members=members,
                           back_member=request.args.get('back_member', type=int) or request.args.get('member_id', type=int))


@bp.route('/new', methods=['GET', 'POST'])
def new():
    if request.method == 'GET':
        form = _form_data()
        mid = request.args.get('member_id', type=int)
        rid = request.args.get('raw_material_id', type=int)
        if mid:
            form['member_id'] = str(mid)
            form['supplier_type'] = 'member'
        if rid:
            form['raw_material_id'] = str(rid)
            rm = db.query('SELECT cost_per_unit FROM raw_material WHERE id = ?', (rid,), one=True)
            if rm:
                form['rate'] = ('%g' % rm['cost_per_unit'])
        return _render_form(form)

    f = request.form
    form = _form_data(f)
    qty, rate = _num(f.get('qty')), _num(f.get('rate'))
    errors = []
    try:
        _date.fromisoformat(form['date'])
    except ValueError:
        errors.append('purchases.err_date')
    rm = None
    if f.get('raw_material_id', '').isdigit():
        rm = db.query('SELECT * FROM raw_material WHERE id = ?', (int(f['raw_material_id']),), one=True)
    if not rm:
        errors.append('purchases.err_material')
    if qty is None or qty <= 0:
        errors.append('purchases.err_qty')
    if rate is None or rate < 0:
        errors.append('purchases.err_rate')
    member_id, vendor = None, None
    if form['supplier_type'] == 'vendor':
        vendor = form['supplier_name'].strip()
        if not vendor:
            errors.append('purchases.err_vendor')
    else:
        form['supplier_type'] = 'member'
        if f.get('member_id', '').isdigit() and db.query(
                'SELECT 1 FROM member WHERE id = ?', (int(f['member_id']),), one=True):
            member_id = int(f['member_id'])
        else:
            errors.append('purchases.err_member')
    if errors:
        for e in errors:
            flash(t(e), 'danger')
        return _render_form(form)

    try:
        no = db.next_number('purchase', form['date'])
        amount = round(qty * rate, 2)
        pid = db.execute(
            'INSERT INTO purchase (purchase_no, date, raw_material_id, qty, rate, amount, '
            'member_id, supplier_name, notes) VALUES (?,?,?,?,?,?,?,?,?)',
            (no, form['date'], rm['id'], qty, rate, amount, member_id, vendor,
             form['notes'].strip() or None))
        stock.add_txn(form['date'], 'raw', qty, 'purchase', ref_id=pid, raw_material_id=rm['id'])
        if form['update_cost']:
            db.execute('UPDATE raw_material SET cost_per_unit = ? WHERE id = ?', (rate, rm['id']))
        db.commit()
    except stock.StockError as e:
        db.rollback()
        flash(str(e), 'danger')
        return _render_form(form)
    flash(t('purchases.saved', no=no), 'success')
    back = request.args.get('back_member', type=int)
    if back:
        from flask import current_app
        if 'members.detail' in current_app.view_functions:
            return redirect(url_for('members.detail', member_id=back))
    return redirect(url_for('purchases.index'))
