import json
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from core import db
from core.i18n import t

bp = Blueprint('gi', __name__, url_prefix='/gi')

CATEGORIES = ['Agricultural', 'Handicraft', 'Manufactured', 'Foodstuff', 'Natural']


def expiry_tone(valid_upto):
    """Return 'danger' | 'warning' | 'success' | None for an ISO date."""
    if not valid_upto:
        return None
    try:
        d = date.fromisoformat(str(valid_upto)[:10])
    except ValueError:
        return None
    today = date.today()
    if d < today:
        return 'danger'
    if d <= today + timedelta(days=365):
        return 'warning'
    return 'success'


def parse_json_list(s):
    try:
        v = json.loads(s or '[]')
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def parse_checklist(s):
    out = []
    for r in parse_json_list(s):
        if isinstance(r, dict):
            out.append({'en': (r.get('en') or '').strip(), 'hi': (r.get('hi') or '').strip()})
        elif isinstance(r, str):
            out.append({'en': r.strip(), 'hi': ''})
    return out


@bp.route('/')
def index():
    q = (request.args.get('q') or '').strip()
    cat = (request.args.get('category') or '').strip()
    sql = """SELECT g.*,
               (SELECT COUNT(*) FROM member_gi mg WHERE mg.gi_id = g.id) AS n_members,
               (SELECT COUNT(*) FROM product p WHERE p.gi_id = g.id) AS n_products
             FROM gi g WHERE 1=1"""
    args = []
    if q:
        sql += """ AND (g.name LIKE ? OR g.name_hi LIKE ? OR g.application_number LIKE ?
                        OR g.goods LIKE ? OR g.short_code LIKE ?)"""
        args += ['%' + q + '%'] * 5
    if cat:
        sql += ' AND g.category = ?'
        args.append(cat)
    sql += ' ORDER BY g.name'
    rows = db.query(sql, args)
    gis = [dict(r, tone=expiry_tone(r['valid_upto'])) for r in rows]
    allrows = db.query("""SELECT g.status, g.valid_upto,
               (SELECT COUNT(*) FROM product p WHERE p.gi_id = g.id) AS n_products FROM gi g""")
    kpi = {
        'total': len(allrows),
        'registered': sum(1 for r in allrows if (r['status'] or '').lower() == 'registered'),
        'with_products': sum(1 for r in allrows if r['n_products']),
        'expiring': sum(1 for r in allrows if expiry_tone(r['valid_upto']) == 'warning'),
    }
    return render_template('gi/index.html', gis=gis, kpi=kpi, q=q, cat=cat, categories=CATEGORIES)


@bp.route('/<int:gi_id>')
def detail(gi_id):
    g = db.query('SELECT * FROM gi WHERE id = ?', (gi_id,), one=True)
    if not g:
        abort(404)
    members = [dict(r, tone=expiry_tone(r['au_valid_upto'])) for r in db.query(
        """SELECT m.id, m.code, m.name, m.name_hi, m.village, mg.au_number, mg.au_valid_upto
           FROM member_gi mg JOIN member m ON m.id = mg.member_id
           WHERE mg.gi_id = ? ORDER BY m.code""", (gi_id,))]
    products = db.query(
        """SELECT p.id, p.sku, p.name, p.name_hi, p.unit, COALESCE(s.qty_sellable, 0) AS qty_sellable
           FROM product p LEFT JOIN v_product_stock s ON s.product_id = p.id
           WHERE p.gi_id = ? ORDER BY p.sku""", (gi_id,))
    batches = db.query(
        """SELECT b.id, b.batch_no, b.qty, b.mfg_date, b.status, p.name, p.name_hi
           FROM batch b JOIN product p ON p.id = b.product_id
           WHERE b.gi_id = ? ORDER BY b.mfg_date DESC, b.id DESC LIMIT 10""", (gi_id,))
    sources = [u for u in parse_json_list(g['source_urls']) if isinstance(u, str) and u]
    return render_template('gi/detail.html', g=g, tone=expiry_tone(g['valid_upto']),
                           members=members, products=products, batches=batches,
                           checklist=parse_checklist(g['checklist']), sources=sources)


@bp.route('/<int:gi_id>/edit', methods=['GET', 'POST'])
def edit(gi_id):
    g = db.query('SELECT * FROM gi WHERE id = ?', (gi_id,), one=True)
    if not g:
        abort(404)
    form = {
        'name_hi': g['name_hi'] or '',
        'description': g['description'] or '',
        'description_hi': g['description_hi'] or '',
    }
    checklist = parse_checklist(g['checklist'])
    if request.method == 'POST':
        form = {k: (request.form.get(k) or '').strip() for k in form}
        en = request.form.getlist('check_en')
        hi = request.form.getlist('check_hi')
        checklist = []
        for i, e in enumerate(en):
            e = e.strip()
            h = (hi[i] if i < len(hi) else '').strip()
            if e or h:
                checklist.append({'en': e, 'hi': h})
        errors = []
        if any(not c['en'] for c in checklist):
            errors.append(t('gi.err_check_en'))
        for k, mx in (('name_hi', 200), ('description', 4000), ('description_hi', 4000)):
            if len(form[k]) > mx:
                errors.append(t('common.invalid_input'))
                break
        if errors:
            for e in errors:
                flash(e, 'danger')
        else:
            db.execute(
                'UPDATE gi SET name_hi=?, description=?, description_hi=?, checklist=? WHERE id=?',
                (form['name_hi'] or None, form['description'] or None,
                 form['description_hi'] or None,
                 json.dumps(checklist, ensure_ascii=False), gi_id))
            db.commit()
            flash(t('common.saved'), 'success')
            return redirect(url_for('gi.detail', gi_id=gi_id))
    return render_template('gi/edit.html', g=g, form=form, checklist=checklist)
