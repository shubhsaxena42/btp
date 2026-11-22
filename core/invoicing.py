"""Invoice creation shared by sales and consignments. Does not commit or touch stock."""
from core import db


def r2(x):
    return round(float(x) + 1e-9, 2)


def create_invoice(date, customer_id, channel, lines, venue=None, consignment_id=None, notes=None):
    cust = db.query('SELECT * FROM customer WHERE id=?', (customer_id,), one=True)
    if cust is None:
        raise ValueError('customer not found')
    org_code = db.setting('org_state_code', '05')
    interstate = 1 if str(cust['state_code'] or '') != str(org_code or '') else 0
    computed, subtotal, tax_total = [], 0.0, 0.0
    for ln in lines:
        qty, rate, gst = float(ln['qty']), float(ln['rate']), float(ln.get('gst_rate') or 0)
        taxable = r2(qty * rate)
        tax = r2(taxable * gst / 100)
        computed.append((ln['product_id'], ln.get('batch_id'), qty, rate, gst, taxable, tax, r2(taxable + tax)))
        subtotal += taxable
        tax_total += tax
    subtotal, tax_total = r2(subtotal), r2(tax_total)
    total = r2(subtotal + tax_total)
    invoice_no = db.next_number('invoice', date)
    sale_id = db.execute(
        'INSERT INTO sale (invoice_no, date, customer_id, channel, venue, is_interstate, subtotal, tax_total, '
        'total, consignment_id, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (invoice_no, date, customer_id, channel, venue, interstate, subtotal, tax_total, total,
         consignment_id, notes))
    for c in computed:
        db.execute('INSERT INTO sale_line (sale_id, product_id, batch_id, qty, rate, gst_rate, taxable, tax, amount) '
                   'VALUES (?,?,?,?,?,?,?,?,?)', (sale_id,) + c)
    return sale_id


def tax_split(sale_row):
    tax = float(sale_row['tax_total'] or 0)
    if sale_row['is_interstate']:
        return {'cgst': 0.0, 'sgst': 0.0, 'igst': round(tax, 2)}
    half = round(tax / 2, 2)
    return {'cgst': half, 'sgst': round(tax - half, 2), 'igst': 0.0}
