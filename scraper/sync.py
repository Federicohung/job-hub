# Job Hub — Sync Engine
# Persistent database: accumulates jobs, removes expired (>30 days)
# Processes in batches of 1500 with progress tracking

import json, os, time, logging, hashlib
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('job-hub-sync')

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_SCRIPT_DIR, 'data')
RAW_FILE = os.path.join(DATA_DIR, 'raw_scrape.json')
DB_FILE = os.path.join(DATA_DIR, 'jobs.json')
SYNC_LOG = os.path.join(DATA_DIR, 'sync_log.json')
HISTORY_FILE = os.path.join(DATA_DIR, 'sync_history.json')

MAX_AGE_DAYS = 30
BATCH_SIZE = 1500


def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_date(date_str):
    """Parse various date formats to datetime (always UTC)."""
    if not date_str:
        return None
    try:
        s = date_str.replace('Z', '+00:00')
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except:
        pass
    try:
        dt = datetime.strptime(date_str[:19], '%Y-%m-%dT%H:%M:%S')
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except:
        pass
    try:
        ts = float(date_str)
        if ts > 1e12:
            ts = ts / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except:
        return None


def deduplicate_key(job):
    """Generate dedup key from company + title."""
    import re
    return re.sub(r'[\s\-,\.]+', ' ', f"{job.get('company', '').lower()}:{job.get('title', '').lower()}").strip()


def update_sync_progress(pct, message, sync_id=None):
    """Update progress in sync_log.json for the dashboard to read."""
    progress = {
        'status': 'running' if pct < 100 else 'complete',
        'progress': pct,
        'message': message,
        'syncId': sync_id,
        'updatedAt': datetime.now(timezone.utc).isoformat(),
    }
    save_json(SYNC_LOG, progress)


def sync(raw_file=None, db_file=None, batch_size=BATCH_SIZE, max_age_days=MAX_AGE_DAYS):
    """
    Sync engine: merge new scraped jobs into persistent database.
    
    Logic:
    - New jobs (by ID) → add to database
    - Existing jobs found again → update foundAt (still active)
    - Existing jobs NOT found AND posted >30 days ago → remove
    - Existing jobs NOT found BUT posted <30 days ago → keep
    - Also deduplicate by company:title
    - Process in batches of batch_size
    """
    raw_path = raw_file or RAW_FILE
    db_path = db_file or DB_FILE

    # Generate sync ID for tracking
    sync_id = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')

    # ── Phase 1: Load raw scrape ──
    log.info(f'[SYNC {sync_id}] Phase 1: Loading raw scrape from {raw_path}')
    update_sync_progress(5, 'Cargando datos del scrape...', sync_id)

    raw_data = load_json(raw_path)
    new_jobs = raw_data.get('jobs', [])

    if not new_jobs:
        log.warning('[SYNC] No new jobs in raw scrape. Nothing to sync.')
        update_sync_progress(100, 'Sin datos nuevos para sincronizar', sync_id)
        return {'added': 0, 'updated': 0, 'removed': 0, 'total': 0, 'deduped': 0, 'syncId': sync_id}

    # Limit to batch size — take highest priority first
    new_jobs.sort(key=lambda j: (j.get('locationTier', 9), j.get('postedAt', '')))
    new_jobs = new_jobs[:batch_size]
    log.info(f'[SYNC {sync_id}] Processing batch: {len(new_jobs)} jobs (max {batch_size})')

    # ── Phase 2: Load existing database ──
    log.info(f'[SYNC {sync_id}] Phase 2: Loading existing database from {db_path}')
    update_sync_progress(15, f'Cargando base de datos existente...', sync_id)

    db_data = load_json(db_path)
    existing_jobs = db_data.get('jobs', [])

    # Build ID lookup + dedup key lookup
    existing_by_id = {j['id']: j for j in existing_jobs}
    existing_by_dedup = {}

    for job in existing_jobs:
        dk = deduplicate_key(job)
        if dk not in existing_by_dedup:
            existing_by_dedup[dk] = job['id']

    # ── Phase 3: Merge new jobs ──
    log.info(f'[SYNC {sync_id}] Phase 3: Merging new jobs...')
    merged = []
    added = 0
    updated = 0
    deduped = 0
    processed_ids = set()

    total_to_process = len(new_jobs)

    for i, job in enumerate(new_jobs):
        jid = job['id']
        processed_ids.add(jid)

        if jid in existing_by_id:
            # Job exists — update foundAt (still active in source)
            existing_job = existing_by_id[jid]
            existing_job['foundAt'] = job.get('foundAt', existing_job.get('foundAt', ''))
            existing_job['urlValid'] = job.get('urlValid', existing_job.get('urlValid', True))
            # Update salary if new data has it
            if job.get('salary') and job['salary'] != 'No publicado':
                existing_job['salary'] = job['salary']
            merged.append(existing_job)
            updated += 1
            del existing_by_id[jid]
        else:
            # Check dedup by company:title (cross-source duplicates)
            dk = deduplicate_key(job)
            if dk in existing_by_dedup and existing_by_dedup[dk] in existing_by_id:
                # Same company:title exists from another source — keep the one with better tier
                existing_job = existing_by_id[existing_by_dedup[dk]]
                if job.get('locationTier', 9) < existing_job.get('locationTier', 9):
                    # New job has better priority — replace
                    merged.append(job)
                    del existing_by_id[existing_by_dedup[dk]]
                else:
                    merged.append(existing_job)
                    del existing_by_id[existing_by_dedup[dk]]
                deduped += 1
            else:
                merged.append(job)
                added += 1

        # Progress every 150 jobs (10% of 1500)
        if (i + 1) % 150 == 0 or (i + 1) == total_to_process:
            pct = 15 + int((i + 1) / total_to_process * 50)  # 15% to 65%
            update_sync_progress(pct,
                f'Merge: {i+1}/{total_to_process} — +{added} nuevos, ~{updated} actualizados, ={deduped} duplicados',
                sync_id)
            log.info(f'[SYNC {sync_id}] Progress: {i+1}/{total_to_process} ({pct}%) — Added: {added}, Updated: {updated}, Deduped: {deduped}')

    # ── Phase 4: Handle remaining existing jobs (not in this scrape) ──
    log.info(f'[SYNC {sync_id}] Phase 4: Checking {len(existing_by_id)} remaining jobs for expiry...')
    update_sync_progress(70, 'Verificando expiración (30 días)...', sync_id)

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    removed = 0
    kept_old = 0

    for jid, job in existing_by_id.items():
        posted = parse_date(job.get('postedAt', ''))
        found = parse_date(job.get('foundAt', ''))

        # Use the most recent of posted/found (ensure timezone-aware)
        job_date = None
        try:
            if posted and found:
                if posted.tzinfo is None: posted = posted.replace(tzinfo=timezone.utc)
                if found.tzinfo is None: found = found.replace(tzinfo=timezone.utc)
                job_date = max(posted, found)
            else:
                d = posted or found
                if d and d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
                job_date = d
        except TypeError:
            job_date = posted or found

        if job_date and job_date < cutoff:
            # Job is older than 30 days and wasn't found in this scrape → remove
            removed += 1
        else:
            # Keep — either still recent or couldn't parse date
            merged.append(job)
            kept_old += 1

    log.info(f'[SYNC {sync_id}] Expiry check: -{removed} removed (>{max_age_days}d), {kept_old} kept')

    # ── Phase 4.5: FINAL DEDUP — zero tolerance for duplicates ──
    log.info(f'[SYNC {sync_id}] Phase 4.5: Final dedup pass on {len(merged)} jobs...')
    update_sync_progress(80, 'Deduplicación final (cero duplicados)...', sync_id)

    seen_keys = {}
    final_jobs = []
    final_deduped = 0

    for job in merged:
        # Dedup by company:title — keep the one with best tier
        dk = deduplicate_key(job)
        if dk in seen_keys:
            existing = seen_keys[dk]
            if job.get('locationTier', 9) < existing.get('locationTier', 9):
                # Replace with better tier
                seen_keys[dk] = job
                final_deduped += 1
            else:
                final_deduped += 1
            continue
        seen_keys[dk] = job

        # Also dedup by sourceUrl if available
        su = job.get('sourceUrl', '')
        if su:
            url_key = su.split('?')[0]  # Strip query params
            if url_key in seen_keys:
                final_deduped += 1
                continue

        final_jobs.append(job)

    merged = final_jobs
    if final_deduped > 0:
        log.info(f'[SYNC {sync_id}] Final dedup removed {final_deduped} duplicates → {len(merged)} unique jobs')
        deduped += final_deduped

    # ── Phase 5: Final sort and save ──
    log.info(f'[SYNC {sync_id}] Phase 5: Saving database...')
    update_sync_progress(85, 'Guardando base de datos...', sync_id)

    # Sort by tier then date
    merged.sort(key=lambda j: (j.get('locationTier', 9), j.get('postedAt', '') or ''))

    # Build breakdown
    bd = {}
    for cat in ['remote-spanish', 'remote-latam', 'remote-spain', 'remote-global',
                'hybrid-latam', 'hybrid-spain', 'onsite-latam', 'onsite-spain', 'other']:
        bd[cat] = len([j for j in merged if j.get('locationPriority') == cat])

    output = {
        'version': '2.0',
        'schema': 'persistent-db',
        'updatedAt': datetime.now(timezone.utc).isoformat(),
        'lastSync': datetime.now(timezone.utc).isoformat(),
        'syncId': sync_id,
        'maxAgeDays': max_age_days,
        'batchSize': batch_size,
        'totalJobs': len(merged),
        'sources': sorted(set(j['source'] for j in merged)),
        'breakdown': bd,
        'jobs': merged,
    }

    save_json(db_path, output)

    # ── Phase 6: Write sync log ──
    update_sync_progress(95, 'Guardando registro de sincronización...', sync_id)

    sync_log = {
        'status': 'complete',
        'progress': 100,
        'syncId': sync_id,
        'lastSync': datetime.now(timezone.utc).isoformat(),
        'batchSize': batch_size,
        'maxAgeDays': max_age_days,
        'processed': total_to_process,
        'added': added,
        'updated': updated,
        'deduped': deduped,
        'removed': removed,
        'keptExisting': kept_old,
        'totalInDb': len(merged),
        'sources': output['sources'],
        'message': f'+{added} nuevos, ~{updated} actualizados, ={deduped} duplicados, -{removed} expirados → {len(merged)} total',
    }

    save_json(SYNC_LOG, sync_log)

    # ── Phase 7: Append to sync history ──
    history = load_json(HISTORY_FILE)
    if not isinstance(history, list):
        history = []
    history.append(sync_log)
    # Keep last 90 syncs
    history = history[-90:]
    save_json(HISTORY_FILE, history)

    update_sync_progress(100, sync_log['message'], sync_id)

    log.info(f'[SYNC {sync_id}] ✅ COMPLETE: {sync_log["message"]}')
    return sync_log


if __name__ == '__main__':
    result = sync()
    print(f'\n{"="*50}')
    print(f'SYNC RESULT')
    print(f'{"="*50}')
    for k, v in result.items():
        print(f'  {k}: {v}')
    print(f'{"="*50}')
