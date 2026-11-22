"""Language helpers: t() for strings, L() for bilingual DB columns."""
import logging

from flask import has_request_context, request

log = logging.getLogger(__name__)
LANGS = ('en', 'hi')


def current_lang():
    if has_request_context():
        c = request.cookies.get('lang', 'en')
        if c in LANGS:
            return c
    return 'en'


def t(key, **fmt):
    from translations import STRINGS
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry[1] if (current_lang() == 'hi' and len(entry) > 1 and entry[1]) else entry[0]
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def L(row, field='name'):
    if row is None:
        return ''
    try:
        base = row[field]
    except (KeyError, IndexError):
        base = None
    if current_lang() == 'hi':
        try:
            hi = row[field + '_hi']
        except (KeyError, IndexError):
            hi = None
        if hi:
            return hi
    return base if base is not None else ''
