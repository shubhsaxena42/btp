"""Products: catalogue, bill of materials, stock, fair-price calculator."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from core import db
from core.numbers import num
from core.i18n import t, L

bp = Blueprint('products', __name__, url_prefix='/products')

UNITS = ['pcs', 'pack', 'set']
GST_RATES = [0, 5, 12, 18]


def _f(val, default=0.0):
    s = str(val if val is not None else '').strip()
    if s == '':
        return default
    return num(s)


def fair_price(material, hours, rate, overhead_pct, margin_pct, gst_rate, price):
    """Single source of the formula (mirrored in the template JS)."""
    labour = hours * rate
    base = material + labour
    overhead = base * overhead_pct / 100.0
    total = base + overhead
    fair = total * (1 + margin_pct / 100.0)
    incl = fair * (1 + gst_rate / 100.0)
    diff = fair - price
    if fair > 0 and abs(diff) <= 0.05 * fair:
        verdict = 'within'
    elif diff > 0:
        verdict = 'below'
    else:
        verdict = 'above'
    share = (labour / price * 100.0) if price else 0.0
    return dict(labour=labour, base=base, overhead=overhead, total=total, fair=fair,
                incl=incl, diff=diff, verdict=verdict, share=share)


def _bom(product_id):
    rows = db.query(
        """SELECT pm.raw_material_id, pm.qty_per_unit, rm.name, rm.name_hi, rm.code,
                  rm.unit, rm.cost_per_unit, pm.qty_per_unit * rm.cost_per_unit AS cost
           FROM product_material pm JOIN raw_material rm ON rm.id = pm.raw_material_id
           WHERE pm.product_id = ? ORDER BY pm.id""", (product_id,))
    return rows


def _form_context(product, bom_rows, errors=None):
    gis = db.query("SELECT id, name, name_hi FROM gi ORDER BY name")
    return dict(
        p=product, bom_rows=bom_rows, errors=errors or {}, gis=gis,
        materials=db.query("SELECT id, code, name, name_hi, unit FROM raw_material ORDER BY name"),
        gi_opts=[(g['id'], L(g, 'name')) for g in gis],
        unit_opts=[(u, t('unit.' + u)) for u in UNITS],
        gst_opts=[(r, '%d%%' % r) for r in GST_RATES])


@bp.route('/')
def index():
    gi_id = request.args.get('gi_id', type=int)
    q = (request.args.get('q') or '').strip()
    sql = """SELECT p.*, g.name AS gi_name, g.name_hi AS gi_name_hi,
                    s.qty_sellable, s.qty_pending, s.qty_at_outlets
             FROM product p JOIN gi g ON g.id = p.gi_id
             LEFT JOIN v_product_stock s ON s.product_id = p.id WHERE 1=1"""
    args = []
    if gi_id:
        sql += " AND p.gi_id = ?"
        args.append(gi_id)
    if q:
        sql += " AND (p.sku LIKE ? OR p.name LIKE ? OR COALESCE(p.name_hi,'') LIKE ?)"
        args += ['%' + q + '%'] * 3
    sql += " ORDER BY g.name, p.name"
    products = db.query(sql, args)
    gis = db.query("SELECT id, name, name_hi FROM gi ORDER BY name")
    return render_template('products/index.html', products=products, gis=gis,
                           gi_id=gi_id, q=q)


def _parse_form(product_id=None):
    form = request.form
    errors = {}
    v = {}
    v['sku'] = (form.get('sku') or '').strip().upper()
    v['name'] = (form.get('name') or '').strip()
    v['name_hi'] = (form.get('name_hi') or '').strip() or None
    v['gi_id'] = form.get('gi_id', type=int)
    v['unit'] = form.get('unit') or ''
    v['hsn'] = (form.get('hsn') or '').strip() or None
    v['gst_rate'] = _f(form.get('gst_rate'), 5.0)
    v['price'] = _f(form.get('price'), None)
    v['piece_rate'] = _f(form.get('piece_rate'), 0.0)
    sl = (form.get('shelf_life_days') or '').strip()
    v['shelf_life_days'] = None
    v['description'] = (form.get('description') or '').strip() or None
    v['description_hi'] = (form.get('description_hi') or '').strip() or None
    v['active'] = 1 if form.get('active') else 0

    if not v['sku']:
        errors['sku'] = t('common.required')
    elif db.scalar("SELECT id FROM product WHERE sku = ? AND id IS NOT ?", (v['sku'], product_id)):
        errors['sku'] = t('products.err_sku_exists')
    if not v['name']:
        errors['name'] = t('common.required')
    if not v['gi_id'] or not db.scalar("SELECT id FROM gi WHERE id = ?", (v['gi_id'],)):
        errors['gi_id'] = t('common.required')
    if v['unit'] not in UNITS:
        errors['unit'] = t('common.required')
    if v['gst_rate'] is None or int(v['gst_rate']) not in GST_RATES:
        errors['gst_rate'] = t('common.invalid_input')
    if v['price'] is None or v['price'] < 0:
        errors['price'] = t('common.invalid_input')
    if v['piece_rate'] is None or v['piece_rate'] < 0:
        errors['piece_rate'] = t('common.invalid_input')
    if sl:
        try:
            v['shelf_life_days'] = int(sl)
            if v['shelf_life_days'] <= 0:
                raise ValueError
        except ValueError:
            errors['shelf_life_days'] = t('common.invalid_input')

    # BOM rows
    bom, seen = [], set()
    rm_ids = form.getlist('raw_material_id[]')
    qtys = form.getlist('qty_per_unit[]')
    bom_error = False
    for rid, qty in zip(rm_ids, qtys):
        if not rid and not qty.strip():
            continue
        try:
            rid_i = int(rid)
            q = num(qty)
            if q is None or q <= 0 or rid_i in seen or not db.scalar("SELECT id FROM raw_material WHERE id=?", (rid_i,)):
                raise ValueError
        except ValueError:
            bom_error = True
            continue
        seen.add(rid_i)
        bom.append((rid_i, q))
    if bom_error:
        errors['bom'] = t('products.err_bom')
    return v, bom, errors


def _bom_rows_from_pairs(pairs):
    out = []
    for rid, q in pairs:
        out.append({'raw_material_id': rid, 'qty_per_unit': q})
    return out


def _save(product_id):
    v, bom, errors = _parse_form(product_id)
    if errors:
        flash(t('common.invalid_input'), 'danger')
        raw = request.form
        shown = dict(v)
        shown['id'] = product_id
        shown['price'] = raw.get('price', '')
        shown['gst_rate'] = v['gst_rate']
        shown['shelf_life_days'] = raw.get('shelf_life_days', '')
        shown['piece_rate'] = raw.get('piece_rate', '')
        return render_template('products/form.html',
                               **_form_context(shown, _bom_rows_from_pairs(bom), errors))
    cols = ['sku', 'name', 'name_hi', 'gi_id', 'unit', 'hsn', 'gst_rate', 'price', 'piece_rate',
            'shelf_life_days', 'description', 'description_hi', 'active']
    try:
        if product_id:
            db.execute("UPDATE product SET " + ", ".join(c + "=?" for c in cols) + " WHERE id=?",
                       [v[c] for c in cols] + [product_id])
            db.execute("DELETE FROM product_material WHERE product_id=?", (product_id,))
        else:
            product_id = db.execute(
                "INSERT INTO product (" + ", ".join(cols) + ") VALUES (" + ",".join("?" * len(cols)) + ")",
                [v[c] for c in cols])
        for rid, q in bom:
            db.execute("INSERT INTO product_material (product_id, raw_material_id, qty_per_unit) VALUES (?,?,?)",
                       (product_id, rid, q))
        db.commit()
    except Exception:
        db.rollback()
        raise
    flash(t('common.saved'), 'success')
    return redirect(url_for('products.detail', product_id=product_id))


@bp.route('/new', methods=['GET', 'POST'])
def new():
    if request.method == 'POST':
        return _save(None)
    p = dict(sku='', name='', name_hi='', gi_id=request.args.get('gi_id', type=int), unit='pcs',
             hsn='', gst_rate=5, price='', piece_rate='', shelf_life_days='',
             description='', description_hi='', active=1)
    return render_template('products/form.html', **_form_context(p, []))


@bp.route('/<int:product_id>/edit', methods=['GET', 'POST'])
def edit(product_id):
    p = db.query("SELECT * FROM product WHERE id=?", (product_id,), one=True)
    if p is None:
        abort(404)
    if request.method == 'POST':
        return _save(product_id)
    return render_template('products/form.html', **_form_context(p, _bom(product_id)))


@bp.route('/<int:product_id>')
def detail(product_id):
    p = db.query("""SELECT p.*, g.name AS gi_name, g.name_hi AS gi_name_hi
                    FROM product p JOIN gi g ON g.id = p.gi_id WHERE p.id=?""",
                 (product_id,), one=True)
    if p is None:
        abort(404)
    stock = db.query("SELECT * FROM v_product_stock WHERE product_id=?", (product_id,), one=True)
    bom = _bom(product_id)
    bom_cost = sum(r['cost'] for r in bom)
    batches = db.query("""SELECT * FROM v_batch_stock WHERE product_id=?
                          ORDER BY mfg_date DESC, id DESC""", (product_id,))
    sales = db.query("""SELECT sl.qty, sl.rate, sl.amount, s.id AS sale_id, s.invoice_no, s.date,
                               c.name AS customer_name, b.batch_no
                        FROM sale_line sl JOIN sale s ON s.id = sl.sale_id
                        JOIN customer c ON c.id = s.customer_id
                        LEFT JOIN batch b ON b.id = sl.batch_id
                        WHERE sl.product_id=? ORDER BY s.date DESC, sl.id DESC LIMIT 10""",
                     (product_id,))
    calc = fair_price(p['material_cost'], p['labour_hours'], p['labour_rate'],
                      p['overhead_pct'], p['margin_pct'], p['gst_rate'], p['price'])
    return render_template('products/detail.html', p=p, stock=stock, bom=bom,
                           bom_cost=bom_cost, batches=batches, sales=sales, calc=calc)


@bp.route('/<int:product_id>/pricing', methods=['POST'])
def save_pricing(product_id):
    p = db.query("SELECT * FROM product WHERE id=?", (product_id,), one=True)
    if p is None:
        abort(404)
    vals = {k: _f(request.form.get(k), 0.0) for k in
            ('material_cost', 'labour_hours', 'labour_rate', 'overhead_pct', 'margin_pct')}
    if any(x is None or x < 0 for x in vals.values()):
        flash(t('common.invalid_input'), 'danger')
        return redirect(url_for('products.detail', product_id=product_id) + '#fair-price')
    sets = dict(vals)
    msg = t('products.pricing_saved')
    if request.form.get('action') == 'apply':
        c = fair_price(vals['material_cost'], vals['labour_hours'], vals['labour_rate'],
                       vals['overhead_pct'], vals['margin_pct'], p['gst_rate'], p['price'])
        new_price = round(c['fair'] / 5.0) * 5
        if new_price <= 0:
            flash(t('products.err_price_zero'), 'danger')
            return redirect(url_for('products.detail', product_id=product_id) + '#fair-price')
        sets['price'] = float(new_price)
        msg = t('products.price_updated', price='{:,.2f}'.format(new_price))
    db.execute("UPDATE product SET " + ", ".join(k + "=?" for k in sets) + " WHERE id=?",
               list(sets.values()) + [product_id])
    db.commit()
    flash(msg, 'success')
    return redirect(url_for('products.detail', product_id=product_id) + '#fair-price')
