"""Copy published batches into the GI portal's database.xlsx (local setups only).

Path: env PORTAL_XLSX, else the sibling ../GI-Authentication-Portal/database.xlsx.
If the file isn't there (e.g. on Vercel) syncing is skipped.
"""
import os

import openpyxl

from core.db import ROOT

DEFAULT = os.path.join(os.path.dirname(ROOT), 'GI-Authentication-Portal', 'database.xlsx')


def portal_xlsx_path():
    p = os.environ.get('PORTAL_XLSX') or DEFAULT
    return p if os.path.isfile(p) else None


def _cell(col, v):
    # The portal prints empty cells as "nan", so never leave one blank.
    if v in (None, ''):
        return 'Not applicable' if col == 'Expiry Date' else '—'
    return str(v)


def fill_blanks(ws):
    hdr = [c.value for c in ws[1]]
    n = 0
    for r in ws.iter_rows(min_row=2):
        for h, c in zip(hdr, r):
            if c.value in (None, ''):
                c.value = _cell(h, None)
                n += 1
    return n


def append_row(row):
    """Append a portal row unless its Batch Number is already there.

    Returns 'added', 'exists' or 'unavailable'. Raises OSError if the file is locked.
    """
    path = portal_xlsx_path()
    if not path:
        return 'unavailable'
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    hdr = [c.value for c in ws[1]]
    bi = hdr.index('Batch Number')
    if any(str(r[bi]) == str(row['Batch Number']) for r in ws.iter_rows(min_row=2, values_only=True)):
        return 'exists'
    ws.append([_cell(h, row.get(h)) for h in hdr])
    wb.save(path)
    return 'added'
