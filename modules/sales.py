import re
from datetime import date as _date
from urllib.parse import quote

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from core import db, stock, invoicing
from core.numbers import num
from core.i18n import t

bp = Blueprint('sales', __name__, url_prefix='/sales')

CHANNELS = ['counter', 'fair', 'wholesale', 'online']
MODES = ['upi', 'cash', 'bank', 'cheque']
PAY_STATUSES = ['paid', 'partial', 'unpaid']


def _valid_date(s):
    try:
        _date.fromisoformat(s or '')
        return True
    except ValueError:
        return False


def _tax_split(sale):
    try:
        return invoicing.tax_split(sale)
    except Exception:
        tax = float(sale['tax_total'] or 0)
        if sale['is_interstate']:
            return {'cgst': 0.0, 'sgst': 0.0, 'igst': round(tax, 2)}
        return {'cgst': round(tax / 2, 2), 'sgst': round(tax - round(tax / 2, 2), 2), 'igst': 0.0}


def _get_sale(sale_id):
    sale = db.query('SELECT * FROM v_sale_status WHERE id=?', (sale_id,), one=True)
    if not sale:
        abort(404)
    return sale


def _sale_lines(sale_id):
    return db.query(
        '''SELECT sl.*, p.name AS p_name, p.name_hi AS p_name_hi, p.unit, p.hsn, p.sku,
                  g.name AS gi_name, g.name_hi AS gi_name_hi,
                  b.batch_no, b.id AS b_id
           FROM sale_line sl
           JOIN product p ON p.id = sl.product_id
           JOIN gi g ON g.id = p.gi_id
           LEFT JOIN batch b ON b.id = sl.batch_id
           WHERE sl.sale_id = ? ORDER BY sl.id''', (sale_id,))


def _customer(cid):
    return db.query('SELECT * FROM customer WHERE id=?', (cid,), one=True)


# ---------------------------------------------------------------- index
@bp.route('/')
def index():
    q = (request.args.get('search') or '').strip()
    customer = request.args.get('customer', type=int)
    channel = request.args.get('channel') or ''
    pay = request.args.get('pay_status') or ''
    month = request.args.get('month') or ''
    where, args = [], []
    if q:
        where.append('(s.invoice_no LIKE ? OR c.name LIKE ?)')
        args += ['%' + q + '%'] * 2
    if customer:
        where.append('s.customer_id = ?'); args.append(customer)
    if channel:
        where.append('s.channel = ?'); args.append(channel)
    if pay in PAY_STATUSES:
        where.append('s.pay_status = ?'); args.append(pay)
    if re.match(r'^\d{4}-\d{2}$', month):
        where.append('substr(s.date,1,7) = ?'); args.append(month)
    sql = '''SELECT s.*, c.name AS customer_name FROM v_sale_status s
             JOIN customer c ON c.id = s.customer_id'''
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY s.date DESC, s.id DESC'
    rows = db.query(sql, args)
    tot = {'total': sum(r['total'] for r in rows), 'paid': sum(r['paid'] for r in rows),
           'due': sum(r['due'] for r in rows)}
    cur = db.today()[:7]
    m = db.query('SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS tot FROM sale WHERE substr(date,1,7)=?',
                 (cur,), one=True)
    outstanding = db.scalar('SELECT COALESCE(SUM(due),0) FROM v_sale_status WHERE due > 0.005', default=0)
    kpi = {'month_sales': m['tot'], 'month_count': m['n'], 'outstanding': outstanding,
           'avg': (m['tot'] / m['n']) if m['n'] else 0}
    customers = db.query('SELECT id, name FROM customer ORDER BY name')
    return render_template('sales/index.html', rows=rows, tot=tot, kpi=kpi, customers=customers,
                           channels=CHANNELS, pay_statuses=PAY_STATUSES,
                           f=dict(search=q, customer=customer, channel=channel, pay_status=pay, month=month))


# ---------------------------------------------------------------- new
def _form_context(f, lines, error_lines=None):
    customers = db.query('SELECT * FROM customer ORDER BY name')
    products = db.query(
        '''SELECT p.*, COALESCE(vs.qty_sellable,0) AS sellable FROM product p
           LEFT JOIN v_product_stock vs ON vs.product_id = p.id
           WHERE p.active = 1 ORDER BY p.name''')
    return dict(f=f, lines=lines, customers=customers, products=products, channels=CHANNELS,
                modes=MODES, org_state_code=db.setting('org_state_code', '05'))


@bp.route('/new', methods=['GET', 'POST'])
def new():
    if request.method == 'GET':
        f = {'date': db.today(), 'customer_id': request.args.get('customer_id', type=int),
             'channel': 'counter', 'venue': '', 'notes': '', 'pay_amount': '', 'pay_mode': 'upi'}
        return render_template('sales/form.html', **_form_context(f, [{}]))

    form = request.form
    f = {'date': form.get('date') or db.today(), 'customer_id': form.get('customer_id', type=int),
         'channel': form.get('channel') or '', 'venue': (form.get('venue') or '').strip(),
         'notes': (form.get('notes') or '').strip(), 'pay_amount': form.get('pay_amount') or '',
         'pay_mode': form.get('pay_mode') or 'upi'}
    pids = form.getlist('product_id[]')
    qtys = form.getlist('qty[]')
    rates = form.getlist('rate[]')
    entered = []
    for i, pid in enumerate(pids):
        entered.append({'product_id': pid, 'qty': qtys[i] if i < len(qtys) else '',
                        'rate': rates[i] if i < len(rates) else ''})

    def fail(msg):
        flash(msg, 'danger')
        return render_template('sales/form.html', **_form_context(f, entered or [{}]))

    if not _valid_date(f['date']):
        return fail(t('sales.err_date'))
    cust = _customer(f['customer_id']) if f['customer_id'] else None
    if not cust:
        return fail(t('sales.err_customer'))
    if f['channel'] not in CHANNELS:
        return fail(t('sales.err_channel'))

    clean = []
    for e in entered:
        if not e['product_id'] and not e['qty']:
            continue
        try:
            pid = int(e['product_id'])
        except (TypeError, ValueError):
            return fail(t('sales.err_product'))
        prod = db.query('SELECT * FROM product WHERE id=?', (pid,), one=True)
        if not prod:
            return fail(t('sales.err_product'))
        qf = num(e['qty'])
        if qf is None or qf <= 0 or qf != int(qf):
            return fail(t('sales.err_qty'))
        if str(e['rate'] or '').strip() == '':
            rate = float(prod['price'])
        else:
            rate = num(e['rate'])
        if rate is None or rate < 0:
            return fail(t('sales.err_rate'))
        clean.append((prod, int(qf), rate))
    if not clean:
        return fail(t('sales.err_no_lines'))

    pay_amount = 0.0
    if f['pay_amount'] not in ('', None):
        pay_amount = num(f['pay_amount'])
        if pay_amount is None or pay_amount < 0:
            return fail(t('sales.err_pay_amount'))
        if pay_amount > 0 and f['pay_mode'] not in MODES:
            return fail(t('sales.err_mode'))

    try:
        inv_lines, allocs, txn_ids = [], [], []
        for prod, qty, rate in clean:
            # allocate per row; earlier rows' txns are already written so FIFO sees them
            for batch_id, bq in stock.allocate_fifo(prod['id'], qty):
                inv_lines.append({'product_id': prod['id'], 'batch_id': batch_id, 'qty': bq,
                                  'rate': rate, 'gst_rate': prod['gst_rate']})
                txn_ids.append(stock.add_txn(f['date'], 'product', -bq, 'sale', None,
                                             batch_id=batch_id, product_id=prod['id']))
        sale_id = invoicing.create_invoice(
            f['date'], cust['id'], f['channel'], inv_lines,
            venue=f['venue'] if f['channel'] == 'fair' and f['venue'] else None,
            notes=f['notes'] or None)
        for tid in txn_ids:
            db.execute('UPDATE stock_txn SET ref_id=? WHERE id=?', (sale_id, tid))
        total = db.scalar('SELECT total FROM sale WHERE id=?', (sale_id,), default=0)
        if pay_amount > 0:
            if pay_amount > total + 0.005:
                raise ValueError(t('sales.err_pay_amount'))
            db.execute('''INSERT INTO payment_in (date, sale_id, customer_id, amount, mode, reference)
                          VALUES (?,?,?,?,?,?)''',
                       (f['date'], sale_id, cust['id'], round(pay_amount, 2), f['pay_mode'], None))
        db.commit()
    except stock.StockError as e:
        db.rollback()
        return fail(str(e))
    except ValueError as e:
        db.rollback()
        return fail(str(e))
    inv_no = db.scalar('SELECT invoice_no FROM sale WHERE id=?', (sale_id,))
    flash(t('sales.created', no=inv_no), 'success')
    return redirect(url_for('sales.detail', sale_id=sale_id))


# ---------------------------------------------------------------- detail
def _wa_link(sale, cust):
    org = db.setting('org_name', '')
    text = t('sales.wa_text', org=org, no=sale['invoice_no'],
             date=_dmy(sale['date']), total='Rs. %.2f' % sale['total'],
             due='Rs. %.2f' % max(sale['due'], 0), upi=db.setting('org_upi', '') or '-')
    phone = re.sub(r'\D', '', cust['phone'] or '')
    base = 'https://wa.me/'
    if len(phone) >= 10:
        base += '91' + phone[-10:]
    return base + '?text=' + quote(text)


def _dmy(d):
    try:
        y, m, dd = d.split('-')
        return '%s/%s/%s' % (dd, m, y)
    except Exception:
        return d or ''


def _invoice_ctx(sale_id):
    sale = _get_sale(sale_id)
    cust = _customer(sale['customer_id'])
    lines = _sale_lines(sale_id)
    split = _tax_split(sale)
    batches = []
    seen = set()
    for l in lines:
        if l['b_id'] and l['b_id'] not in seen:
            seen.add(l['b_id'])
            batches.append((l['b_id'], l['batch_no']))
    return dict(sale=sale, cust=cust, lines=lines, split=split, batches=batches)


@bp.route('/<int:sale_id>')
def detail(sale_id):
    ctx = _invoice_ctx(sale_id)
    payments = db.query('SELECT * FROM payment_in WHERE sale_id=? ORDER BY date, id', (sale_id,))
    return render_template('sales/detail.html', payments=payments, modes=MODES,
                           wa_link=_wa_link(ctx['sale'], ctx['cust']), **ctx)


@bp.route('/<int:sale_id>/print')
def print_invoice(sale_id):
    ctx = _invoice_ctx(sale_id)
    return render_template('sales/print.html', auto=request.args.get('print') == '1', **ctx)


@bp.route('/<int:sale_id>/payment', methods=['POST'])
def add_payment(sale_id):
    sale = _get_sale(sale_id)
    form = request.form
    d = form.get('date') or db.today()
    mode = form.get('mode') or ''
    amount = num(form.get('amount'))
    amount = round(amount, 2) if amount is not None else 0
    if not _valid_date(d):
        flash(t('sales.err_date'), 'danger')
    elif mode not in MODES:
        flash(t('sales.err_mode'), 'danger')
    elif amount <= 0 or amount > sale['due'] + 0.005:
        flash(t('sales.err_pay_amount'), 'danger')
    else:
        db.execute('''INSERT INTO payment_in (date, sale_id, customer_id, amount, mode, reference)
                      VALUES (?,?,?,?,?,?)''',
                   (d, sale_id, sale['customer_id'], amount, mode,
                    (form.get('reference') or '').strip() or None))
        db.commit()
        flash(t('sales.payment_saved'), 'success')
    return redirect(url_for('sales.detail', sale_id=sale_id))


# ---------------------------------------------------------------- payments
@bp.route('/payments')
def payments():
    month = request.args.get('month') or ''
    mode = request.args.get('mode') or ''
    customer = request.args.get('customer', type=int)
    where, args = [], []
    if re.match(r'^\d{4}-\d{2}$', month):
        where.append('substr(p.date,1,7)=?'); args.append(month)
    if mode in MODES:
        where.append('p.mode=?'); args.append(mode)
    if customer:
        where.append('p.customer_id=?'); args.append(customer)
    sql = '''SELECT p.*, s.invoice_no, c.name AS customer_name FROM payment_in p
             JOIN sale s ON s.id = p.sale_id JOIN customer c ON c.id = p.customer_id'''
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY p.date DESC, p.id DESC'
    rows = db.query(sql, args)
    by_mode = {}
    for r in rows:
        by_mode[r['mode']] = by_mode.get(r['mode'], 0) + r['amount']
    customers = db.query('SELECT id, name FROM customer ORDER BY name')
    return render_template('sales/payments.html', rows=rows, by_mode=by_mode, modes=MODES,
                           total=sum(r['amount'] for r in rows), customers=customers,
                           f=dict(month=month, mode=mode, customer=customer))
