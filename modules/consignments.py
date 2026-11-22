"""Consignments: goods placed at outlets, paid only for what sells."""
from datetime import date as _date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from core import db, invoicing, stock
from core.numbers import num, whole
from core.i18n import t

bp = Blueprint('consignments', __name__, url_prefix='/consignments')


def _whole(s):
    return whole(s)


def _num(s):
    return num(s)


def _valid_date(s):
    try:
        _date.fromisoformat(s or '')
        return True
    except ValueError:
        return False


def _age(sent_on):
    try:
        return (_date.today() - _date.fromisoformat(sent_on)).days
    except (TypeError, ValueError):
        return 0


@bp.route('/')
def index():
    outlet = request.args.get('outlet', type=int)
    status = request.args.get('status', '')
    where, args = [], []
    if outlet:
        where.append('c.customer_id = ?')
        args.append(outlet)
    if status in ('open', 'settled'):
        where.append('c.status = ?')
        args.append(status)
    w = ('WHERE ' + ' AND '.join(where)) if where else ''
    rows = db.query(f"""
        SELECT c.*, cu.name AS outlet_name,
          COALESCE((SELECT SUM(qty_sent) FROM consignment_line WHERE consignment_id=c.id),0) AS sent,
          COALESCE((SELECT SUM(qty_sold) FROM consignment_line WHERE consignment_id=c.id),0) AS sold,
          COALESCE((SELECT SUM(qty_returned) FROM consignment_line WHERE consignment_id=c.id),0) AS returned,
          COALESCE((SELECT SUM((qty_sent-qty_sold-qty_returned)*rate) FROM consignment_line WHERE consignment_id=c.id),0) AS value_out,
          COALESCE((SELECT SUM(total) FROM sale WHERE consignment_id=c.id),0) AS invoiced,
          COALESCE((SELECT SUM(due) FROM v_sale_status WHERE consignment_id=c.id),0) AS due
        FROM consignment c JOIN customer cu ON cu.id=c.customer_id
        {w} ORDER BY c.sent_on DESC, c.id DESC""", args)
    items = []
    for r in rows:
        d = dict(r)
        d['at_outlet'] = d['sent'] - d['sold'] - d['returned']
        d['age'] = _age(d['sent_on'])
        items.append(d)
    all_rows = db.query("""
        SELECT COUNT(CASE WHEN c.status='open' THEN 1 END) AS n_open
        FROM consignment c""", one=True)
    summary = db.query("""
        SELECT cu.id, cu.name,
          COALESCE(SUM(cl.qty_sent-cl.qty_sold-cl.qty_returned),0) AS units,
          COALESCE(SUM((cl.qty_sent-cl.qty_sold-cl.qty_returned)*cl.rate),0) AS value,
          COALESCE((SELECT SUM(due) FROM v_sale_status WHERE customer_id=cu.id AND consignment_id IS NOT NULL),0) AS due
        FROM customer cu
        JOIN consignment c ON c.customer_id=cu.id
        LEFT JOIN consignment_line cl ON cl.consignment_id=c.id
        GROUP BY cu.id ORDER BY value DESC, cu.name""")
    kpi = {
        'open': all_rows['n_open'] if all_rows else 0,
        'units': sum(s['units'] for s in summary),
        'value': sum(s['value'] for s in summary),
        'due': sum(s['due'] for s in summary),
    }
    outlets = db.query("""SELECT id, name FROM customer WHERE id IN
                          (SELECT customer_id FROM consignment) ORDER BY name""")
    return render_template('consignments/index.html', items=items, summary=summary,
                           kpi=kpi, outlets=outlets, f_outlet=outlet, f_status=status)


def _form_data():
    customers = db.query("""SELECT id, name, type FROM customer
                            ORDER BY CASE type WHEN 'outlet' THEN 0 ELSE 1 END, name""")
    products = db.query("""SELECT p.id, p.name, p.name_hi, p.price, p.unit,
                                  COALESCE(vs.qty_sellable,0) AS stock
                           FROM product p LEFT JOIN v_product_stock vs ON vs.product_id=p.id
                           WHERE p.active=1 ORDER BY p.name""")
    return customers, products


@bp.route('/new', methods=['GET', 'POST'])
def new():
    customers, products = _form_data()
    form = {'customer_id': request.args.get('customer_id', ''), 'sent_on': db.today(),
            'notes': '', 'lines': []}
    if request.method == 'POST':
        form['customer_id'] = request.form.get('customer_id', '')
        form['sent_on'] = request.form.get('sent_on', '')
        form['notes'] = request.form.get('notes', '').strip()
        pids = request.form.getlist('product_id[]')
        qtys = request.form.getlist('qty[]')
        rates = request.form.getlist('rate[]')
        lines, ok = [], True
        for i, pid in enumerate(pids):
            q = qtys[i] if i < len(qtys) else ''
            r = rates[i] if i < len(rates) else ''
            if not pid and not q:
                continue
            form['lines'].append({'product_id': pid, 'qty': q, 'rate': r})
            pidn, qn, rn = _whole(pid), _whole(q), _num(r)
            if not pidn or qn is None or qn <= 0 or rn is None or rn < 0:
                ok = False
                continue
            lines.append((pidn, qn, rn))
        cust = db.query('SELECT * FROM customer WHERE id=?', (_whole(form['customer_id']) or 0,), one=True)
        if not cust or not _valid_date(form['sent_on']) or not lines or not ok:
            flash(t('common.invalid_input'), 'danger')
        else:
            try:
                cn_no = db.next_number('consignment', form['sent_on'])
                cn_id = db.execute(
                    "INSERT INTO consignment (cn_no, customer_id, sent_on, status, notes) VALUES (?,?,?,?,?)",
                    (cn_no, cust['id'], form['sent_on'], 'open', form['notes'] or None))
                for pid, qty, rate in lines:
                    for batch_id, bq in stock.allocate_fifo(pid, qty):
                        db.execute("""INSERT INTO consignment_line
                                      (consignment_id, product_id, batch_id, qty_sent, rate)
                                      VALUES (?,?,?,?,?)""", (cn_id, pid, batch_id, bq, rate))
                        stock.add_txn(form['sent_on'], 'product', -bq, 'consignment_out',
                                      cn_id, batch_id=batch_id, product_id=pid)
                db.commit()
                flash(t('consignments.created', no=cn_no), 'success')
                return redirect(url_for('consignments.detail', cn_id=cn_id))
            except stock.StockError as e:
                db.rollback()
                flash(str(e), 'danger')
    return render_template('consignments/new.html', customers=customers, products=products, form=form)


def _load(cn_id):
    cn = db.query("""SELECT c.*, cu.name AS outlet_name, cu.id AS outlet_id
                     FROM consignment c JOIN customer cu ON cu.id=c.customer_id
                     WHERE c.id=?""", (cn_id,), one=True)
    if not cn:
        abort(404)
    return cn


@bp.route('/<int:cn_id>')
def detail(cn_id):
    cn = _load(cn_id)
    lines = db.query("""SELECT cl.*, p.name, p.name_hi, p.unit, b.batch_no,
                               (cl.qty_sent-cl.qty_sold-cl.qty_returned) AS remaining
                        FROM consignment_line cl
                        JOIN product p ON p.id=cl.product_id
                        JOIN batch b ON b.id=cl.batch_id
                        WHERE cl.consignment_id=? ORDER BY cl.id""", (cn_id,))
    sales = db.query("SELECT * FROM v_sale_status WHERE consignment_id=? ORDER BY date, id", (cn_id,))
    tot = {
        'sent': sum(l['qty_sent'] for l in lines),
        'sold': sum(l['qty_sold'] for l in lines),
        'returned': sum(l['qty_returned'] for l in lines),
        'remaining': sum(l['remaining'] for l in lines),
        'value': sum(l['remaining'] * l['rate'] for l in lines),
        'invoiced': sum(s['total'] for s in sales),
        'due': sum(s['due'] for s in sales),
    }
    return render_template('consignments/detail.html', cn=cn, lines=lines, sales=sales,
                           tot=tot, age=_age(cn['sent_on']), today=db.today())


def _parse_qtys(cn_id):
    """Return (date, [(line, qty)], error_flag) for per-line qty inputs."""
    d = request.form.get('date', '')
    lines = db.query("""SELECT *, (qty_sent-qty_sold-qty_returned) AS remaining
                        FROM consignment_line WHERE consignment_id=?""", (cn_id,))
    picked, ok = [], _valid_date(d)
    for l in lines:
        raw = request.form.get(f"qty_{l['id']}", '').strip()
        if raw == '':
            continue
        q = _whole(raw)
        if q is None or q < 0 or q > l['remaining']:
            ok = False
            continue
        if q > 0:
            picked.append((l, q))
    if not picked:
        ok = False
    return d, picked, ok


def _settle(cn_id):
    left = db.scalar("""SELECT COUNT(*) FROM consignment_line WHERE consignment_id=?
                        AND qty_sent - qty_sold - qty_returned > 0""", (cn_id,), 0)
    if not left:
        db.execute("UPDATE consignment SET status='settled' WHERE id=?", (cn_id,))


@bp.route('/<int:cn_id>/record-sale', methods=['POST'])
def record_sale(cn_id):
    cn = _load(cn_id)
    if cn['status'] != 'open':
        flash(t('consignments.not_open'), 'danger')
        return redirect(url_for('consignments.detail', cn_id=cn_id))
    d, picked, ok = _parse_qtys(cn_id)
    if not ok:
        flash(t('consignments.invalid_qty'), 'danger')
        return redirect(url_for('consignments.detail', cn_id=cn_id))
    try:
        inv_lines = []
        for l, q in picked:
            gst = db.scalar('SELECT gst_rate FROM product WHERE id=?', (l['product_id'],), 0)
            db.execute('UPDATE consignment_line SET qty_sold = qty_sold + ? WHERE id=?', (q, l['id']))
            inv_lines.append({'product_id': l['product_id'], 'batch_id': l['batch_id'],
                              'qty': q, 'rate': l['rate'], 'gst_rate': gst})
        sale_id = invoicing.create_invoice(d, cn['customer_id'], 'consignment', inv_lines,
                                           consignment_id=cn_id, notes='Consignment ' + cn['cn_no'])
        _settle(cn_id)
        inv_no = db.scalar('SELECT invoice_no FROM sale WHERE id=?', (sale_id,), '')
        db.commit()
        flash(t('consignments.sale_recorded', no=inv_no), 'success')
    except Exception as e:  # keep data consistent
        db.rollback()
        flash(str(e) or t('common.invalid_input'), 'danger')
    return redirect(url_for('consignments.detail', cn_id=cn_id))


@bp.route('/<int:cn_id>/record-return', methods=['POST'])
def record_return(cn_id):
    cn = _load(cn_id)
    if cn['status'] != 'open':
        flash(t('consignments.not_open'), 'danger')
        return redirect(url_for('consignments.detail', cn_id=cn_id))
    d, picked, ok = _parse_qtys(cn_id)
    if not ok:
        flash(t('consignments.invalid_qty'), 'danger')
        return redirect(url_for('consignments.detail', cn_id=cn_id))
    try:
        for l, q in picked:
            db.execute('UPDATE consignment_line SET qty_returned = qty_returned + ? WHERE id=?', (q, l['id']))
            stock.add_txn(d, 'product', q, 'consignment_return', cn_id,
                          batch_id=l['batch_id'], product_id=l['product_id'])
        _settle(cn_id)
        db.commit()
        flash(t('consignments.return_recorded'), 'success')
    except stock.StockError as e:
        db.rollback()
        flash(str(e), 'danger')
    return redirect(url_for('consignments.detail', cn_id=cn_id))
