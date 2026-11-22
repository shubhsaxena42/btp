"""Batches: GI compliance inspection and GI-portal bridge."""
import io
import json
from datetime import date, datetime, timedelta

from flask import (Blueprint, Response, abort, flash, redirect, render_template,
                   request, url_for)

from core import db
from core.i18n import t

bp = Blueprint('batches', __name__, url_prefix='/batches')

PORTAL_COLUMNS = [
    'Application Number', 'Product Name', 'Manufacturer Name', 'Geographical Indications',
    'Status', 'Serial Number', 'Batch Number', 'Manufacturing Date', 'Expiry Date',
    'Applicant Name', 'Applicant Address', 'Date of Filing', 'Class', 'Goods',
    'Geographical Area', 'Priority Country', 'Journal Number', 'Availability Date',
    'Certificate Number', 'Certificate Date', 'Registration Valid Upto',
]
XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _dmy(d):
    if not d:
        return ''
    try:
        return datetime.strptime(str(d)[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        return str(d)


def _s(v):
    return '' if v is None else str(v)


def _get_batch(batch_id):
    b = db.query(
        """SELECT bs.*, p.name AS product_name, p.name_hi AS product_name_hi, p.sku,
                  g.name AS gi_name, g.name_hi AS gi_name_hi, g.application_number,
                  g.checklist AS gi_checklist, m.name AS member_name,
                  m.name_hi AS member_name_hi, m.code AS member_code,
                  wo.wo_no AS wo_no
           FROM v_batch_stock bs
           JOIN product p ON p.id = bs.product_id
           JOIN gi g ON g.id = bs.gi_id
           LEFT JOIN member m ON m.id = bs.member_id
           LEFT JOIN work_order wo ON wo.id = bs.work_order_id
           WHERE bs.id = ?""", (batch_id,), one=True)
    if b is None:
        abort(404)
    return b


def portal_row(batch_id):
    """Ordered dict (21 portal headers) for one batch. Raises 404 if unknown."""
    b = db.query("SELECT * FROM batch WHERE id = ?", (batch_id,), one=True)
    if b is None:
        abort(404)
    p = db.query("SELECT * FROM product WHERE id = ?", (b['product_id'],), one=True)
    g = db.query("SELECT * FROM gi WHERE id = ?", (b['gi_id'],), one=True)
    row = {
        'Application Number': g['application_number'],
        'Product Name': p['name'],
        'Manufacturer Name': db.setting('portal_manufacturer_name', '') or '',
        'Geographical Indications': g['name'],
        'Status': g['status'] or 'Registered',
        'Serial Number': '%s to %s' % (_s(b['serial_from']), _s(b['serial_to'])),
        'Batch Number': b['batch_no'],
        'Manufacturing Date': _dmy(b['mfg_date']),
        'Expiry Date': _dmy(b['expiry_date']),
        'Applicant Name': g['applicant_name'],
        'Applicant Address': g['applicant_address'],
        'Date of Filing': _dmy(g['date_of_filing']),
        'Class': g['class'],
        'Goods': g['goods'],
        'Geographical Area': g['geographical_area'],
        'Priority Country': g['priority_country'],
        'Journal Number': g['journal_number'],
        'Availability Date': _dmy(g['availability_date']),
        'Certificate Number': g['certificate_number'],
        'Certificate Date': _dmy(g['certificate_date']),
        'Registration Valid Upto': _dmy(g['valid_upto']),
    }
    return {k: _s(row[k]) for k in PORTAL_COLUMNS}


def _xlsx_response(rows, filename):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Sheet1'
    ws.append(PORTAL_COLUMNS)
    for r in rows:
        ws.append([_s(r[c]) for c in PORTAL_COLUMNS])
    for i, c in enumerate(PORTAL_COLUMNS, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(14, min(40, len(c) + 4))
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), mimetype=XLSX_MIME, headers={
        'Content-Disposition': 'attachment; filename="%s"' % filename})


def _verify_url(application_number):
    base = (db.setting('portal_url', '') or '').rstrip('/')
    return '%s/?id=%s' % (base, application_number)


def _expiry_state(expiry, today):
    """'expired' | 'soon' | None"""
    if not expiry:
        return None
    if expiry < today:
        return 'expired'
    try:
        d = datetime.strptime(expiry, '%Y-%m-%d').date()
        if d <= datetime.strptime(today, '%Y-%m-%d').date() + timedelta(days=30):
            return 'soon'
    except ValueError:
        pass
    return None


@bp.route('/')
def index():
    status = request.args.get('status', 'all')
    gi_id = request.args.get('gi', type=int)
    product_id = request.args.get('product', type=int)
    published = request.args.get('published', '')
    q = (request.args.get('q') or request.args.get('search') or '').strip()
    where, args = [], []
    if status in ('pending', 'approved', 'rejected'):
        where.append('bs.status = ?'); args.append(status)
    else:
        status = 'all'
    if gi_id:
        where.append('bs.gi_id = ?'); args.append(gi_id)
    if product_id:
        where.append('bs.product_id = ?'); args.append(product_id)
    if published == 'yes':
        where.append('bs.published_on IS NOT NULL')
    elif published == 'no':
        where.append('bs.published_on IS NULL')
    if q:
        where.append('bs.batch_no LIKE ?'); args.append('%' + q + '%')
    sql = """SELECT bs.*, p.name AS product_name, p.name_hi AS product_name_hi, p.unit,
                    g.name AS gi_name, g.name_hi AS gi_name_hi, g.short_code,
                    m.name AS member_name, m.name_hi AS member_name_hi
             FROM v_batch_stock bs
             JOIN product p ON p.id = bs.product_id
             JOIN gi g ON g.id = bs.gi_id
             LEFT JOIN member m ON m.id = bs.member_id"""
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY bs.mfg_date DESC, bs.id DESC'
    rows = db.query(sql, args)
    today = db.today()
    batches = [{'r': r, 'exp': _expiry_state(r['expiry_date'], today)} for r in rows]
    month = today[:7]
    kpi = {
        'pending': db.scalar("SELECT COUNT(*) FROM batch WHERE status='pending'", default=0),
        'approved_month': db.scalar(
            "SELECT COUNT(*) FROM batch WHERE status='approved' AND substr(inspected_on,1,7)=?",
            (month,), default=0),
        'rejected': db.scalar("SELECT COUNT(*) FROM batch WHERE status='rejected'", default=0),
        'published': db.scalar("SELECT COUNT(*) FROM batch WHERE published_on IS NOT NULL", default=0),
    }
    return render_template(
        'batches/index.html', batches=batches, kpi=kpi, status=status, gi_id=gi_id,
        product_id=product_id, published=published, q=q,
        gis=db.query('SELECT id, name, name_hi FROM gi ORDER BY name'),
        products=db.query('SELECT id, name, name_hi FROM product ORDER BY name'))


@bp.route('/<int:batch_id>')
def detail(batch_id):
    b = _get_batch(batch_id)
    today = db.today()
    try:
        checklist = json.loads(b['gi_checklist'] or '[]')
    except ValueError:
        checklist = []
    try:
        result = json.loads(b['checklist_result'] or '[]')
    except ValueError:
        result = []
    result = (list(result) + [False] * len(checklist))[:len(checklist)]
    gi = db.query('SELECT * FROM gi WHERE id = ?', (b['gi_id'],), one=True)
    txns = db.query(
        "SELECT * FROM stock_txn WHERE item_type='product' AND batch_id = ? ORDER BY date DESC, id DESC",
        (batch_id,))
    ctx = dict(b=b, checklist=checklist, result=result, gi=gi, txns=txns,
               exp=_expiry_state(b['expiry_date'], today))
    if b['status'] == 'approved':
        ctx['row'] = portal_row(batch_id)
        ctx['verify_url'] = _verify_url(b['application_number'])
    return render_template('batches/detail.html', **ctx)


@bp.route('/<int:batch_id>/inspect', methods=['POST'])
def inspect(batch_id):
    b = _get_batch(batch_id)
    if b['status'] != 'pending':
        flash(t('batches.not_pending'), 'danger')
        return redirect(url_for('batches.detail', batch_id=batch_id))
    try:
        checklist = json.loads(b['gi_checklist'] or '[]')
    except ValueError:
        checklist = []
    result = [request.form.get('check_%d' % i) is not None for i in range(len(checklist))]
    inspector = (request.form.get('inspected_by') or '').strip()
    notes = (request.form.get('notes') or '').strip()
    action = request.form.get('action')
    if not inspector:
        flash(t('batches.inspector_required'), 'danger')
        return redirect(url_for('batches.detail', batch_id=batch_id))
    if action == 'approve':
        if not all(result):
            flash(t('batches.all_checks_required'), 'danger')
            return redirect(url_for('batches.detail', batch_id=batch_id))
        status = 'approved'
    elif action == 'reject':
        if not notes:
            flash(t('batches.notes_required'), 'danger')
            return redirect(url_for('batches.detail', batch_id=batch_id))
        status = 'rejected'
    else:
        flash(t('common.invalid_input'), 'danger')
        return redirect(url_for('batches.detail', batch_id=batch_id))
    db.execute("""UPDATE batch SET status=?, checklist_result=?, inspected_by=?, inspected_on=?,
                  inspection_notes=? WHERE id=?""",
               (status, json.dumps(result), inspector, db.today(), notes or None, batch_id))
    db.commit()
    flash(t('batches.approved_msg' if status == 'approved' else 'batches.rejected_msg',
            batch_no=b['batch_no']), 'success' if status == 'approved' else 'warning')
    return redirect(url_for('batches.detail', batch_id=batch_id))


@bp.route('/<int:batch_id>/publish', methods=['POST'])
def publish(batch_id):
    b = _get_batch(batch_id)
    if b['status'] != 'approved':
        flash(t('batches.only_approved'), 'danger')
    else:
        if not b['published_on']:
            db.execute('UPDATE batch SET published_on = ? WHERE id = ?', (db.today(), batch_id))
            db.commit()
        flash(t('batches.published_msg', batch_no=b['batch_no']), 'success')
    nxt = request.form.get('next')
    if nxt == 'portal':
        return redirect(url_for('batches.portal'))
    return redirect(url_for('batches.detail', batch_id=batch_id))


@bp.route('/<int:batch_id>/qr.svg')
def qr(batch_id):
    import segno
    b = _get_batch(batch_id)
    q = segno.make(_verify_url(b['application_number']), error='m')
    buf = io.BytesIO()
    q.save(buf, kind='svg', scale=6, border=2, dark='#003366')
    return Response(buf.getvalue(), mimetype='image/svg+xml',
                    headers={'Cache-Control': 'public, max-age=3600'})


@bp.route('/<int:batch_id>/portal-row.xlsx')
def export_row(batch_id):
    b = _get_batch(batch_id)
    return _xlsx_response([portal_row(batch_id)], 'portal_row_%s.xlsx' % b['batch_no'])


@bp.route('/portal')
def portal():
    pub = db.query("""SELECT b.id, b.batch_no, b.serial_from, b.serial_to, b.mfg_date,
                             b.expiry_date, b.published_on, g.application_number,
                             g.name AS gi_name, g.name_hi AS gi_name_hi,
                             p.name AS product_name, p.name_hi AS product_name_hi
                      FROM batch b JOIN gi g ON g.id=b.gi_id JOIN product p ON p.id=b.product_id
                      WHERE b.published_on IS NOT NULL ORDER BY b.published_on DESC, b.id DESC""")
    unpub = db.query("""SELECT b.id, b.batch_no, b.mfg_date, b.inspected_on, b.qty,
                               p.name AS product_name, p.name_hi AS product_name_hi
                        FROM batch b JOIN product p ON p.id=b.product_id
                        WHERE b.status='approved' AND b.published_on IS NULL
                        ORDER BY b.mfg_date, b.id""")
    return render_template('batches/portal.html', pub=pub, unpub=unpub,
                           portal_url=db.setting('portal_url', ''))


@bp.route('/portal.xlsx')
def portal_xlsx():
    ids = [r['id'] for r in db.query(
        "SELECT id FROM batch WHERE published_on IS NOT NULL AND status='approved' ORDER BY id")]
    return _xlsx_response([portal_row(i) for i in ids], 'gi_portal_rows_%s.xlsx' % db.today())
