"""GI Producer ERP - Flask application factory."""
import importlib
import logging
import os

from flask import Flask, redirect, request, url_for, render_template, make_response
from werkzeug.routing import BuildError

from core import db, filters
from core.i18n import t, L, current_lang, LANGS

log = logging.getLogger(__name__)

MODULES = [
    ('dashboard', None), ('gi', None), ('members', None), ('products', None),
    ('inventory', None), ('purchases', None), ('work_orders', None), ('batches', None),
    ('sales', None), ('consignments', None), ('customers', None),
]


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gi-erp-iit-roorkee-fixed-secret-key')
    app.config['JSON_AS_ASCII'] = False

    filters.register(app)
    app.teardown_appcontext(db.close_db)

    def safe_url(endpoint, **kw):
        try:
            return url_for(endpoint, **kw)
        except BuildError:
            return '#'

    def now_fy():
        return db.fy(db.today())

    def org():
        try:
            return {r['key']: r['value'] for r in db.query('SELECT key, value FROM settings')}
        except Exception:
            return {}

    app.jinja_env.globals.update(t=t, L=L, safe_url=safe_url, today=db.today, now_fy=now_fy,
                                 current_lang=current_lang)

    @app.context_processor
    def inject():
        return dict(t=t, L=L, lang=current_lang(), safe_url=safe_url, today=db.today(),
                    org=org(), now_fy=now_fy())

    for name, _ in MODULES:
        try:
            mod = importlib.import_module('modules.%s' % name)
            app.register_blueprint(mod.bp)
        except Exception:
            log.exception('Module %r not loaded', name)

    @app.route('/lang/<code>')
    def set_lang(code):
        resp = make_response(redirect(request.referrer or '/'))
        if code in LANGS:
            resp.set_cookie('lang', code, max_age=60 * 60 * 24 * 365, samesite='Lax')
        return resp

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        try:
            db.rollback()
        except Exception:
            pass
        return render_template('errors/500.html'), 500

    return app


app = create_app()

if __name__ == '__main__':
    app.run(port=5050, debug=True)
