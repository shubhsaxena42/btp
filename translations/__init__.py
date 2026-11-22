"""Loads every translations/<module>.py and merges their STRINGS dicts."""
import importlib
import logging
import pkgutil

log = logging.getLogger(__name__)
STRINGS = {}


def _load():
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: (i.name != 'common', i.name)):
        try:
            mod = importlib.import_module('%s.%s' % (__name__, info.name))
        except Exception:
            log.exception('Could not load translations.%s', info.name)
            continue
        for k, v in getattr(mod, 'STRINGS', {}).items():
            if k in STRINGS:
                log.warning('Duplicate translation key %r in translations.%s', k, info.name)
            STRINGS[k] = v


_load()
