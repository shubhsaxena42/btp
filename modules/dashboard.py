from datetime import date, timedelta

from flask import Blueprint, render_template

from core import db
from core.i18n import t, L

bp = Blueprint('dashboard', __name__, url_prefix='/')


def _add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


@bp.route('/')
def index():
    today_s = db.today()
    today = date.fromisoformat(today_s)
    q, sc = db.query, db.scalar

    # ---- sales this / last month
    m0 = today.replace(day=1)
    m_prev = _add_months(m0, -1)
    m_next = _add_months(m0, 1)
    sales_this = sc("SELECT COALESCE(SUM(total),0) FROM sale WHERE date>=? AND date<?",
                    (m0.isoformat(), m_next.isoformat()), 0) or 0
    sales_last = sc("SELECT COALESCE(SUM(total),0) FROM sale WHERE date>=? AND date<?",
                    (m_prev.isoformat(), m0.isoformat()), 0) or 0
    sales_pct = round((sales_this - sales_last) * 100.0 / sales_last, 1) if sales_last > 0 else None

    receivable = sc("SELECT COALESCE(SUM(balance),0) FROM v_customer_balance WHERE balance>0", (), 0) or 0
    payable = sc("SELECT COALESCE(SUM(balance),0) FROM v_member_balance WHERE balance>0", (), 0) or 0
    stock_fg = sc("""SELECT COALESCE(SUM((ps.qty_sellable+ps.qty_pending)*p.price),0)
                     FROM v_product_stock ps JOIN product p ON p.id=ps.product_id""", (), 0) or 0
    stock_raw = sc("SELECT COALESCE(SUM(qty_on_hand*cost_per_unit),0) FROM v_raw_stock "
                   "WHERE qty_on_hand>0", (), 0) or 0
    pending_batches = sc("SELECT COUNT(*) FROM batch WHERE status='pending'", (), 0) or 0
    wo = q("""SELECT COUNT(*) AS open_cnt,
                     COALESCE(SUM(CASE WHEN due_on IS NOT NULL AND due_on<? THEN 1 ELSE 0 END),0) AS overdue_cnt
              FROM work_order WHERE status='issued'""", (today_s,), one=True)

    kpis = dict(sales=sales_this, sales_pct=sales_pct, receivable=receivable, payable=payable,
                stock=stock_fg + stock_raw, pending=pending_batches,
                wo_open=wo['open_cnt'], wo_overdue=wo['overdue_cnt'])

    # ---- charts
    start6 = _add_months(m0, -5).isoformat()
    by_month = {r['ym']: r['v'] for r in q(
        "SELECT substr(date,1,7) AS ym, SUM(total) AS v FROM sale WHERE date>=? GROUP BY ym", (start6,))}
    monthly = []
    for i in range(-5, 1):
        d = _add_months(m0, i)
        label = '%s %s' % (t('dashboard.month_%d' % d.month), str(d.year)[2:])
        monthly.append((label, round(by_month.get(d.strftime('%Y-%m'), 0), 2)))

    fy_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1).isoformat()
    by_gi = [(L(r, 'name'), round(r['v'], 2)) for r in q(
        """SELECT g.name, g.name_hi, SUM(sl.amount) AS v
           FROM sale_line sl JOIN sale s ON s.id=sl.sale_id
           JOIN product p ON p.id=sl.product_id JOIN gi g ON g.id=p.gi_id
           WHERE s.date>=? GROUP BY g.id ORDER BY v DESC""", (fy_start,))]
    by_channel = [(t('channel.' + r['channel']), round(r['v'], 2)) for r in q(
        "SELECT channel, SUM(total) AS v FROM sale WHERE date>=? GROUP BY channel ORDER BY v DESC",
        (fy_start,))]

    # ---- alerts
    alerts = []

    def add(tone, icon, text, endpoint, **kw):
        alerts.append(dict(tone=tone, icon=icon, text=text, endpoint=endpoint, kw=kw))

    for r in q("SELECT * FROM v_raw_stock WHERE reorder_level>0 AND qty_on_hand<=reorder_level "
               "ORDER BY name"):
        add('warning', 'stock', t('dashboard.al_reorder', name=L(r, 'name'),
                                  qty=_n(r['qty_on_hand']), unit=t('unit.' + r['unit']),
                                  level=_n(r['reorder_level'])),
            'inventory.index')
    for r in q("""SELECT w.id, w.wo_no, w.due_on, m.name, m.name_hi FROM work_order w
                  JOIN member m ON m.id=w.member_id
                  WHERE w.status='issued' AND w.due_on IS NOT NULL AND w.due_on<? ORDER BY w.due_on""",
               (today_s,)):
        add('danger', 'clock', t('dashboard.al_wo_overdue', wo=r['wo_no'], member=L(r, 'name'),
                                 due=_dmy(r['due_on'])), 'work_orders.detail', wo_id=r['id'])
    au_limit = (today + timedelta(days=90)).isoformat()
    for r in q("""SELECT mg.member_id, mg.au_valid_upto, m.name, m.name_hi, g.name AS gname, g.name_hi AS gname_hi
                  FROM member_gi mg JOIN member m ON m.id=mg.member_id AND m.active=1
                  JOIN gi g ON g.id=mg.gi_id
                  WHERE mg.au_valid_upto IS NOT NULL AND mg.au_valid_upto<=? ORDER BY mg.au_valid_upto""",
               (au_limit,)):
        gname = L({'name': r['gname'], 'name_hi': r['gname_hi']}, 'name')
        expired = r['au_valid_upto'] < today_s
        add('danger' if expired else 'warning', 'id',
            t('dashboard.al_au_expired' if expired else 'dashboard.al_au_expiring',
              member=L(r, 'name'), gi=gname, date=_dmy(r['au_valid_upto'])),
            'members.detail', member_id=r['member_id'])
    gi_limit = (today + timedelta(days=365)).isoformat()
    for r in q("SELECT id, name, name_hi, valid_upto FROM gi WHERE valid_upto IS NOT NULL AND valid_upto<=? "
               "ORDER BY valid_upto", (gi_limit,)):
        expired = r['valid_upto'] < today_s
        add('danger' if expired else 'warning', 'cert',
            t('dashboard.al_gi_expired' if expired else 'dashboard.al_gi_expiring',
              gi=L(r, 'name'), date=_dmy(r['valid_upto'])), 'gi.detail', gi_id=r['id'])
    exp_limit = (today + timedelta(days=30)).isoformat()
    for r in q("""SELECT id, batch_no, expiry_date, qty_on_hand FROM v_batch_stock
                  WHERE status='approved' AND expiry_date IS NOT NULL AND expiry_date<=? AND qty_on_hand>0
                  ORDER BY expiry_date""", (exp_limit,)):
        expired = r['expiry_date'] < today_s
        add('danger' if expired else 'warning', 'batch',
            t('dashboard.al_batch_expired' if expired else 'dashboard.al_batch_expiring',
              batch=r['batch_no'], qty=_n(r['qty_on_hand']), date=_dmy(r['expiry_date'])),
            'batches.detail', batch_id=r['id'])
    cn_limit = (today - timedelta(days=45)).isoformat()
    for r in q("""SELECT cn.id, cn.cn_no, cn.sent_on, c.name FROM consignment cn
                  JOIN customer c ON c.id=cn.customer_id
                  WHERE cn.status='open' AND cn.sent_on<? ORDER BY cn.sent_on""", (cn_limit,)):
        days = (today - date.fromisoformat(r['sent_on'])).days
        add('warning', 'truck', t('dashboard.al_consignment', cn=r['cn_no'], customer=r['name'], days=days),
            'consignments.detail', cn_id=r['id'])
    inv_limit = (today - timedelta(days=30)).isoformat()
    for r in q("""SELECT s.id, s.invoice_no, s.date, s.due, c.name FROM v_sale_status s
                  JOIN customer c ON c.id=s.customer_id
                  WHERE s.pay_status!='paid' AND s.date<? ORDER BY s.date""", (inv_limit,)):
        days = (today - date.fromisoformat(r['date'])).days
        add('warning', 'money', t('dashboard.al_invoice', inv=r['invoice_no'], customer=r['name'],
                                  due=_inr(r['due']), days=days), 'sales.detail', sale_id=r['id'])

    # ---- recent activity
    recent_sales = q("""SELECT s.id, s.invoice_no, s.date, s.total, s.pay_status, c.name AS customer
                        FROM v_sale_status s JOIN customer c ON c.id=s.customer_id
                        ORDER BY s.date DESC, s.id DESC LIMIT 8""")
    recent_batches = q("""SELECT b.id, b.batch_no, b.status, b.mfg_date, b.qty, p.name, p.name_hi
                          FROM batch b JOIN product p ON p.id=b.product_id
                          ORDER BY b.mfg_date DESC, b.id DESC LIMIT 6""")

    return render_template('dashboard/index.html', kpis=kpis, monthly=monthly, by_gi=by_gi,
                           by_channel=by_channel, alerts=alerts, recent_sales=recent_sales,
                           recent_batches=recent_batches)


def _n(x):
    x = round(x or 0, 3)
    return ('%d' % x) if x == int(x) else ('%g' % x)


def _dmy(d):
    return '%s/%s/%s' % (d[8:10], d[5:7], d[0:4]) if d else ''


def _inr(x):
    s = '%.0f' % (x or 0)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ','.join(parts + [tail])
    return '₹' + s
