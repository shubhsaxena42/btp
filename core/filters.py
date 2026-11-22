"""Jinja filters and helpers."""
import json
from datetime import date as _date, datetime
from decimal import Decimal, ROUND_HALF_UP


def _group(int_str):
    """Indian digit grouping for a string of digits."""
    if len(int_str) <= 3:
        return int_str
    head, tail = int_str[:-3], int_str[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ','.join(parts + [tail])


def _fmt(x, places):
    try:
        d = Decimal(str(x if x not in (None, '') else 0))
    except Exception:
        d = Decimal(0)
    d = d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    neg = d < 0
    s = '{:f}'.format(abs(d))
    whole, _, frac = s.partition('.')
    out = _group(whole) + ('.' + frac if places else '')
    return '-' + out if neg else out


def inr(x):
    s = _fmt(x, 2)
    return ('-₹' + s[1:]) if s.startswith('-') else '₹' + s


def inr0(x):
    s = _fmt(x, 0)
    return ('-₹' + s[1:]) if s.startswith('-') else '₹' + s


def num(x):
    try:
        d = Decimal(str(x if x not in (None, '') else 0))
    except Exception:
        return str(x)
    d = d.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
    s = '{:f}'.format(abs(d))
    whole, _, frac = s.partition('.')
    frac = frac.rstrip('0')
    out = _group(whole) + ('.' + frac if frac else '')
    return '-' + out if d < 0 and out.strip('0.,') else out


def dmy(d):
    if not d:
        return ''
    if isinstance(d, (_date, datetime)):
        return d.strftime('%d/%m/%Y')
    s = str(d)[:10]
    try:
        return datetime.strptime(s, '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        return str(d)


def fromjson(s):
    if s is None or s == '':
        return []
    if isinstance(s, (list, dict)):
        return s
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return []


_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
         'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen',
         'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _below_100(n):
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else '')


def _below_1000(n):
    out = []
    if n >= 100:
        out.append(_ONES[n // 100] + ' Hundred')
        n %= 100
    if n:
        out.append(_below_100(n))
    return ' '.join(out)


def _int_words(n):
    if n == 0:
        return 'Zero'
    out = []
    for div, name in ((10000000, 'Crore'), (100000, 'Lakh'), (1000, 'Thousand')):
        if n >= div:
            out.append(_int_words(n // div) + ' ' + name if div == 10000000 else _below_100(n // div) + ' ' + name)
            n %= div
    if n:
        out.append(_below_1000(n))
    return ' '.join(out)


def words(x):
    try:
        d = Decimal(str(x if x not in (None, '') else 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        d = Decimal(0)
    d = abs(d)
    rupees = int(d)
    paise = int((d - rupees) * 100)
    s = 'Rupees ' + _int_words(rupees)
    if paise:
        s += ' and ' + _below_100(paise) + ' Paise'
    return s + ' Only'


def register(app):
    for f in (inr, inr0, num, dmy, fromjson, words):
        app.jinja_env.filters[f.__name__] = f
