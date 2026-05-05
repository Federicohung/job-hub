# Job Hub — Web Dashboard + API Server
# Separate project from existing panel
# Dashboard with job listings + refresh button
# Webhook endpoint /api/jobs for external systems

import json, os, threading, logging, sys, time
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('job-hub')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPER_DIR = os.path.join(BASE_DIR, 'scraper')
DATA_FILE = os.path.join(SCRAPER_DIR, 'data', 'jobs.json')
PYTHON = sys.executable

CACHE = {'data': None, 'last_load': None, 'refreshing': False}


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        CACHE['data'] = data
        CACHE['last_load'] = datetime.now(timezone.utc).isoformat()
        return data
    return {'version': '0', 'totalJobs': 0, 'jobs': [], 'breakdown': {}, 'sources': [], 'updatedAt': ''}


def trigger_refresh():
    if CACHE.get('refreshing'):
        return False
    CACHE['refreshing'] = True
    def _run():
        try:
            log.info('Background refresh started...')
            import importlib.util
            spec = importlib.util.spec_from_file_location("scraper", os.path.join(SCRAPER_DIR, "scraper.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            data = mod.run_pipeline()
            CACHE['data'] = data
            CACHE['last_load'] = datetime.now(timezone.utc).isoformat()
            log.info(f'Refresh done: {data.get("totalJobs", 0)} jobs')
        except Exception as e:
            log.error(f'Refresh failed: {e}')
        finally:
            CACHE['refreshing'] = False
    threading.Thread(target=_run, daemon=True).start()
    return True


# ─── Webhook / API Endpoints ───

@app.route('/api/jobs', methods=['GET'])
def api_jobs():
    """Webhook endpoint — returns all jobs as JSON."""
    data = load_data()
    jobs = data.get('jobs', [])

    category = request.args.get('category', '').lower()
    if category:
        jobs = [j for j in jobs if j.get('locationPriority') == category]

    source = request.args.get('source', '').lower()
    if source:
        jobs = [j for j in jobs if j.get('source') == source]

    remote_only = request.args.get('remote', '').lower() == 'true'
    if remote_only:
        jobs = [j for j in jobs if j.get('remote')]

    search = request.args.get('search', '').lower()
    if search:
        jobs = [j for j in jobs if search in j.get('title', '').lower()
                or search in j.get('company', '').lower()]

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 100))
    start = (page - 1) * per_page
    end = start + per_page

    return jsonify({
        'success': True,
        'total': len(jobs),
        'page': page,
        'perPage': per_page,
        'updatedAt': data.get('updatedAt', ''),
        'breakdown': data.get('breakdown', {}),
        'jobs': jobs[start:end],
    })


@app.route('/api/stats', methods=['GET'])
def api_stats():
    data = load_data()
    return jsonify({
        'success': True,
        'updatedAt': data.get('updatedAt', ''),
        'totalJobs': data.get('totalJobs', 0),
        'sources': data.get('sources', []),
        'breakdown': data.get('breakdown', {}),
        'refreshing': CACHE.get('refreshing', False),
        'lastLoad': CACHE.get('last_load', ''),
    })


@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    started = trigger_refresh()
    return jsonify({
        'success': started,
        'message': 'Refresh started' if started else 'Refresh already in progress',
    })


@app.route('/api/health', methods=['GET'])
def api_health():
    data = load_data()
    return jsonify({'status': 'ok', 'totalJobs': data.get('totalJobs', 0)})


# ─── Dashboard ───

@app.route('/')
def dashboard():
    data = load_data()
    bd = data.get('breakdown', {})
    return send_file(os.path.join(BASE_DIR, 'hub.html'))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5100))
    log.info(f'Starting Job Hub on port {port}...')
    load_data()
    app.run(host='0.0.0.0', port=port, debug=False)
