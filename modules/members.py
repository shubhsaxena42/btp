import re
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from core import db
from core.numbers import num
from core.i18n import t

bp = Blueprint('members', __name__, url_prefix='/members')

DISTRICTS = ['Almora', 'Bageshwar', 'Chamoli', 'Champawat', 'Dehradun', 'Haridwar', 'Nainital',
             'Pauri Garhwal', 'Pithoragarh', 'Rudraprayag', 'Tehri Garhwal', 'Udham Singh Nagar',
             'Uttarkashi']
MODES = ['upi', 'cash', 'bank', 'cheque']
FIELDS = ['name', 'name_hi', 'gender', 'phone', 'village', 'block', 'district', 'shg_name', 'skill',
          'skill_hi', 'upi_id', 'bank_account', 'ifsc', 'joined_on', 'notes']


def _inr(x):
    s = '%.2f' % abs(x)
    whole, frac = s.split('.')
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ','.join(parts + [tail])
    return ('-' if x < 0 else '') + '\u20b9' + whole + '.' + frac


def _valid_date(s):
    try:
        datetime.strptime(s, '%Y-%m-%d')
        return True
    except (ValueError, TypeError):
        return False


def _member_or_404(member_id):
    m = db.query('SELECT * FROM member WHERE id=?', (member_id,), one=True)
    if m is None:
        abort(404)
    return m


def _form_values():
    v = {k: (request.form.get(k) or '').strip() for k in FIELDS}
    v['active'] = 1 if request.form.get('active') else 0
    return v


def _validate_member(v):
    errs = []
    if not v['name']:
        errs.append(t('members.err_name'))
    if v['gender'] and v['gender'] not in ('F', 'M', 'O'):
        errs.append(t('members.err_gender'))
    if v['phone'] and not re.fullmatch(r'\d{10}', v['phone']):
        errs.append(t('members.err_phone'))
    if v['ifsc'] and len(v['ifsc']) != 11:
        errs.append(t('members.err_ifsc'))
    if v['joined_on'] and not _valid_date(v['joined_on']):
        errs.append(t('members.err_date'))
    return errs


def _form_page(member, values, is_new):
    return render_template('members/form.html', member=member, v=values, is_new=is_new,
                           districts=DISTRICTS)


@bp.route('/')
def index():
    q = (request.args.get('q') or request.args.get('search') or '').strip()
    district = request.args.get('district', '')
    gi_id = request.args.get('gi', type=int)
    state = request.args.get('state', 'active')
    where, args = [], []
    if q:
        like = f'%{q}%'
        where.append('(m.name LIKE ? OR m.name_hi LIKE ? OR m.code LIKE ? OR m.village LIKE ? OR m.phone LIKE ?)')
        args += [like] * 5
    if district:
        where.append('m.district = ?')
        args.append(district)
    if gi_id:
        where.append('m.id IN (SELECT member_id FROM member_gi WHERE gi_id = ?)')
        args.append(gi_id)
    if state == 'active':
        where.append('m.active = 1')
    elif state == 'inactive':
        where.append('m.active = 0')
    sql = ('SELECT m.*, COALESCE(b.balance,0) AS balance FROM member m '
           'LEFT JOIN v_member_balance b ON b.member_id = m.id')
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY m.code'
    members = db.query(sql, args)
    gis = {}
    for r in db.query('SELECT mg.member_id, g.name, g.name_hi FROM member_gi mg '
                      'JOIN gi g ON g.id = mg.gi_id ORDER BY g.name'):
        gis.setdefault(r['member_id'], []).append(r)
    total_active = db.scalar('SELECT COUNT(*) FROM member WHERE active=1', default=0)
    women = db.scalar("SELECT COUNT(*) FROM member WHERE active=1 AND gender='F'", default=0)
    owed = db.scalar('SELECT COALESCE(SUM(b.balance),0) FROM v_member_balance b WHERE b.balance > 0',
                     default=0)
    return render_template('members/index.html', members=members, gis=gis, q=q, district=district,
                           gi_id=gi_id, state=state, districts=DISTRICTS,
                           gi_list=db.query('SELECT id, name, name_hi FROM gi ORDER BY name'),
                           total_active=total_active, women=women,
                           women_pct=(women * 100.0 / total_active) if total_active else 0,
                           owed=owed)


@bp.route('/new', methods=['GET', 'POST'])
def new():
    if request.method == 'POST':
        v = _form_values()
        errs = _validate_member(v)
        if errs:
            for e in errs:
                flash(e, 'danger')
            return _form_page(None, v, True)
        code = db.next_number('member')
        cols = ['code'] + FIELDS + ['active']
        mid = db.execute('INSERT INTO member (%s) VALUES (%s)' % (','.join(cols), ','.join('?' * len(cols))),
                         [code] + [v[k] or None if k != 'name' else v[k] for k in FIELDS] + [v['active']])
        db.commit()
        flash(t('members.saved_new', code=code), 'success')
        return redirect(url_for('members.detail', member_id=mid))
    v = {k: '' for k in FIELDS}
    v.update(active=1, joined_on=db.today(), district='')
    return _form_page(None, v, True)


@bp.route('/<int:member_id>/edit', methods=['GET', 'POST'])
def edit(member_id):
    m = _member_or_404(member_id)
    if request.method == 'POST':
        v = _form_values()
        errs = _validate_member(v)
        if errs:
            for e in errs:
                flash(e, 'danger')
            return _form_page(m, v, False)
        sets = ','.join(f'{k}=?' for k in FIELDS + ['active'])
        db.execute(f'UPDATE member SET {sets} WHERE id=?',
                   [v[k] or None if k != 'name' else v[k] for k in FIELDS] + [v['active'], member_id])
        db.commit()
        flash(t('common.saved'), 'success')
        return redirect(url_for('members.detail', member_id=member_id))
    return _form_page(m, dict(m), False)


@bp.route('/<int:member_id>')
def detail(member_id):
    m = _member_or_404(member_id)
    bal = db.query('SELECT * FROM v_member_balance WHERE member_id=?', (member_id,), one=True)
    today = date.today()
    soon = (today + timedelta(days=90)).isoformat()
    gi_rows = []
    for r in db.query('SELECT mg.*, g.name, g.name_hi FROM member_gi mg JOIN gi g ON g.id=mg.gi_id '
                      'WHERE mg.member_id=? ORDER BY g.name', (member_id,)):
        d = dict(r)
        up = d['au_valid_upto']
        d['state'] = ('expired' if up and up < today.isoformat()
                      else 'expiring' if up and up <= soon else '')
        gi_rows.append(d)
    avail_gis = db.query('SELECT id, name, name_hi FROM gi WHERE id NOT IN '
                         '(SELECT gi_id FROM member_gi WHERE member_id=?) ORDER BY name', (member_id,))
    wos = db.query('SELECT w.*, p.name AS pname, p.name_hi AS pname_hi FROM work_order w '
                   'JOIN product p ON p.id=w.product_id WHERE w.member_id=? ORDER BY w.issued_on DESC, w.id DESC',
                   (member_id,))
    purchases = db.query('SELECT pu.*, r.name AS rname, r.name_hi AS rname_hi, r.unit AS runit '
                         'FROM purchase pu JOIN raw_material r ON r.id=pu.raw_material_id '
                         'WHERE pu.member_id=? ORDER BY pu.date DESC, pu.id DESC', (member_id,))
    ledger, run = [], 0.0
    for r in db.query("SELECT * FROM v_member_ledger WHERE member_id=? "
                      "ORDER BY date, CASE kind WHEN 'payout' THEN 1 ELSE 0 END, ref_id", (member_id,)):
        run += (r['credit'] or 0) - (r['debit'] or 0)
        d = dict(r)
        d['running'] = run
        ledger.append(d)
    return render_template('members/detail.html', m=m, bal=bal, gi_rows=gi_rows, avail_gis=avail_gis,
                           wos=wos, purchases=purchases, ledger=ledger, today=today.isoformat())


@bp.route('/<int:member_id>/add-gi', methods=['POST'])
def add_gi(member_id):
    _member_or_404(member_id)
    gi_id = request.form.get('gi_id', type=int)
    au = (request.form.get('au_number') or '').strip() or None
    reg = (request.form.get('au_registered_on') or '').strip() or None
    upto = (request.form.get('au_valid_upto') or '').strip() or None
    if not gi_id or db.scalar('SELECT id FROM gi WHERE id=?', (gi_id,)) is None:
        flash(t('members.err_gi'), 'danger')
    elif (reg and not _valid_date(reg)) or (upto and not _valid_date(upto)):
        flash(t('members.err_date'), 'danger')
    elif db.scalar('SELECT id FROM member_gi WHERE member_id=? AND gi_id=?', (member_id, gi_id)):
        flash(t('members.gi_exists'), 'warning')
    else:
        db.execute('INSERT INTO member_gi (member_id, gi_id, au_number, au_registered_on, au_valid_upto) '
                   'VALUES (?,?,?,?,?)', (member_id, gi_id, au, reg, upto))
        db.commit()
        flash(t('members.gi_added'), 'success')
    return redirect(url_for('members.detail', member_id=member_id))


@bp.route('/payouts')
def payouts():
    month = (request.args.get('month') or '').strip()
    owed = db.query('SELECT m.*, b.balance FROM member m JOIN v_member_balance b ON b.member_id=m.id '
                    'WHERE b.balance > 0.005 ORDER BY b.balance DESC')
    sql = ('SELECT p.*, m.name, m.name_hi, m.code FROM payout p JOIN member m ON m.id=p.member_id')
    args = []
    if re.fullmatch(r'\d{4}-\d{2}', month):
        sql += ' WHERE substr(p.date,1,7)=?'
        args.append(month)
    else:
        month = ''
    sql += ' ORDER BY p.date DESC, p.id DESC'
    rows = db.query(sql, args)
    total = sum(r['amount'] for r in rows)
    months = [r[0] for r in db.query('SELECT DISTINCT substr(date,1,7) FROM payout ORDER BY 1 DESC')]
    return render_template('members/payouts.html', owed=owed, rows=rows, total=total, month=month,
                           months=months, owed_total=sum(r['balance'] for r in owed))


@bp.route('/payouts/new', methods=['GET', 'POST'])
def new_payout():
    members = db.query('SELECT m.id, m.code, m.name, m.name_hi, COALESCE(b.balance,0) AS balance '
                       'FROM member m LEFT JOIN v_member_balance b ON b.member_id=m.id '
                       'WHERE m.active=1 ORDER BY m.name')
    v = {'member_id': request.args.get('member_id', type=int), 'date': db.today(), 'amount': '',
         'mode': 'upi', 'reference': '', 'notes': ''}
    if request.method == 'POST':
        v = {'member_id': request.form.get('member_id', type=int),
             'date': (request.form.get('date') or '').strip(),
             'amount': (request.form.get('amount') or '').strip(),
             'mode': request.form.get('mode', ''),
             'reference': (request.form.get('reference') or '').strip(),
             'notes': (request.form.get('notes') or '').strip()}
        errs = []
        mem = db.query('SELECT id FROM member WHERE id=?', (v['member_id'],), one=True) if v['member_id'] else None
        if not mem:
            errs.append(t('members.err_member'))
        amt = num(v['amount'])
        if amt is None or round(amt, 2) <= 0:
            amt = 0
            errs.append(t('members.err_amount'))
        else:
            amt = round(amt, 2)
        if not _valid_date(v['date']):
            errs.append(t('members.err_date'))
        if v['mode'] not in MODES:
            errs.append(t('members.err_mode'))
        if errs:
            for e in errs:
                flash(e, 'danger')
        else:
            bal = db.scalar('SELECT balance FROM v_member_balance WHERE member_id=?', (v['member_id'],), default=0)
            if amt > bal + 0.005:
                flash(t('members.warn_over', bal=_inr(bal)), 'warning')
            db.execute('INSERT INTO payout (date, member_id, amount, mode, reference, notes) VALUES (?,?,?,?,?,?)',
                       (v['date'], v['member_id'], amt, v['mode'], v['reference'] or None, v['notes'] or None))
            db.commit()
            flash(t('members.payout_saved', amt=_inr(amt)), 'success')
            return redirect(url_for('members.detail', member_id=v['member_id']))
    return render_template('members/payout_form.html', members=members, v=v, modes=MODES)
