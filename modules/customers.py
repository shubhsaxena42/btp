import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from core import db
from core.i18n import t

bp = Blueprint('customers', __name__, url_prefix='/customers')

STATES = [
    ('01', 'Jammu & Kashmir'), ('02', 'Himachal Pradesh'), ('03', 'Punjab'),
    ('04', 'Chandigarh'), ('05', 'Uttarakhand'), ('06', 'Haryana'), ('07', 'Delhi'),
    ('08', 'Rajasthan'), ('09', 'Uttar Pradesh'), ('10', 'Bihar'), ('11', 'Sikkim'),
    ('12', 'Arunachal Pradesh'), ('13', 'Nagaland'), ('14', 'Manipur'), ('15', 'Mizoram'),
    ('16', 'Tripura'), ('17', 'Meghalaya'), ('18', 'Assam'), ('19', 'West Bengal'),
    ('20', 'Jharkhand'), ('21', 'Odisha'), ('22', 'Chhattisgarh'), ('23', 'Madhya Pradesh'),
    ('24', 'Gujarat'), ('26', 'Dadra & Nagar Haveli and Daman & Diu'), ('27', 'Maharashtra'),
    ('29', 'Karnataka'), ('30', 'Goa'), ('31', 'Lakshadweep'), ('32', 'Kerala'),
    ('33', 'Tamil Nadu'), ('34', 'Puducherry'), ('35', 'Andaman & Nicobar Islands'),
    ('36', 'Telangana'), ('37', 'Andhra Pradesh'), ('38', 'Ladakh'),
]
STATE_BY_CODE = dict(STATES)
TYPES = ['retail', 'wholesale', 'outlet', 'online', 'individual']
GSTIN_RE = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')
FIELDS = ['name', 'type', 'contact_person', 'phone', 'email', 'gstin', 'address',
          'city', 'state_code', 'notes']


def _org_code():
    return str(db.setting('org_state_code', '05') or '05')


@bp.route('/')
def index():
    ctype = request.args.get('type', '').strip()
    state = request.args.get('state', '').strip()
    q = request.args.get('q', '').strip()
    where, args = [], []
    if ctype:
        where.append('c.type = ?'); args.append(ctype)
    if state:
        where.append('c.state_code = ?'); args.append(state)
    if q:
        where.append('(c.name LIKE ? OR c.code LIKE ? OR c.city LIKE ? OR c.phone LIKE ?)')
        args += ['%' + q + '%'] * 4
    sql = ('SELECT c.*, b.invoiced, b.received, b.balance FROM customer c '
           'JOIN v_customer_balance b ON b.customer_id = c.id')
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY c.name'
    rows = db.query(sql, args)
    org = _org_code()
    total = db.scalar('SELECT COUNT(*) FROM customer', default=0)
    outside = db.scalar('SELECT COUNT(*) FROM customer WHERE state_code != ?', (org,), default=0)
    recv = db.scalar('SELECT COALESCE(SUM(balance),0) FROM v_customer_balance WHERE balance > 0', default=0)
    return render_template('customers/index.html', rows=rows, types=TYPES, states=STATES,
                           f_type=ctype, f_state=state, q=q,
                           kpi_total=total, kpi_outside=outside, kpi_recv=recv)


def _validate(form):
    v = {k: (form.get(k) or '').strip() for k in FIELDS}
    v['gstin'] = v['gstin'].upper()
    errors = []
    if not v['name']:
        errors.append(t('customers.err_name'))
    if v['type'] not in TYPES:
        errors.append(t('customers.err_type'))
    if v['state_code'] not in STATE_BY_CODE:
        errors.append(t('customers.err_state'))
    if v['phone'] and not re.fullmatch(r'\d{10}', v['phone']):
        errors.append(t('customers.err_phone'))
    if v['email'] and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', v['email']):
        errors.append(t('customers.err_email'))
    if v['gstin']:
        if not GSTIN_RE.match(v['gstin']):
            errors.append(t('customers.err_gstin'))
        elif v['state_code'] in STATE_BY_CODE and v['gstin'][:2] != v['state_code']:
            errors.append(t('customers.err_gstin_state'))
    return v, errors


def _form(customer, values, is_new):
    return render_template('customers/form.html', c=customer, v=values, is_new=is_new,
                           types=TYPES, states=STATES)


@bp.route('/new', methods=['GET', 'POST'])
def new():
    if request.method == 'POST':
        v, errors = _validate(request.form)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return _form(None, v, True)
        code = db.next_number('customer')
        db.execute(
            'INSERT INTO customer (code,name,type,contact_person,phone,email,gstin,address,'
            'city,state,state_code,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (code, v['name'], v['type'], v['contact_person'] or None, v['phone'] or None,
             v['email'] or None, v['gstin'] or None, v['address'] or None, v['city'] or None,
             STATE_BY_CODE[v['state_code']], v['state_code'], v['notes'] or None))
        cid = db.scalar('SELECT id FROM customer WHERE code = ?', (code,))
        db.commit()
        flash(t('common.saved'), 'success')
        return redirect(url_for('customers.detail', customer_id=cid))
    return _form(None, {'type': 'retail', 'state_code': _org_code()}, True)


@bp.route('/<int:customer_id>/edit', methods=['GET', 'POST'])
def edit(customer_id):
    c = db.query('SELECT * FROM customer WHERE id = ?', (customer_id,), one=True)
    if c is None:
        abort(404)
    if request.method == 'POST':
        v, errors = _validate(request.form)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return _form(c, v, False)
        db.execute(
            'UPDATE customer SET name=?,type=?,contact_person=?,phone=?,email=?,gstin=?,'
            'address=?,city=?,state=?,state_code=?,notes=? WHERE id=?',
            (v['name'], v['type'], v['contact_person'] or None, v['phone'] or None,
             v['email'] or None, v['gstin'] or None, v['address'] or None, v['city'] or None,
             STATE_BY_CODE[v['state_code']], v['state_code'], v['notes'] or None, customer_id))
        db.commit()
        flash(t('common.saved'), 'success')
        return redirect(url_for('customers.detail', customer_id=customer_id))
    return _form(c, {k: (c[k] if k != 'state_code' else c['state_code']) or '' for k in FIELDS}, False)


@bp.route('/<int:customer_id>')
def detail(customer_id):
    c = db.query('SELECT * FROM customer WHERE id = ?', (customer_id,), one=True)
    if c is None:
        abort(404)
    bal = db.query('SELECT * FROM v_customer_balance WHERE customer_id = ?', (customer_id,), one=True)
    invoices = db.query('SELECT * FROM v_sale_status WHERE customer_id = ? ORDER BY date DESC, id DESC',
                        (customer_id,))
    payments = db.query(
        'SELECT p.*, s.invoice_no FROM payment_in p JOIN sale s ON s.id = p.sale_id '
        'WHERE p.customer_id = ? ORDER BY p.date DESC, p.id DESC', (customer_id,))
    consignments = db.query('SELECT * FROM consignment WHERE customer_id = ? ORDER BY sent_on DESC, id DESC',
                            (customer_id,))
    events = []
    for s in invoices:
        events.append((s['date'], 0, s['id'], 'invoice', s['invoice_no'], s['total'], 0))
    for p in payments:
        events.append((p['date'], 1, p['id'], 'payment', p['invoice_no'], 0, p['amount']))
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    statement, run = [], 0.0
    for d, _, _, kind, ref, dr, cr in events:
        run = round(run + dr - cr, 2)
        statement.append({'date': d, 'kind': kind, 'ref': ref, 'debit': dr, 'credit': cr, 'balance': run})
    return render_template('customers/detail.html', c=c, bal=bal, invoices=invoices,
                           payments=payments, consignments=consignments, statement=statement)
