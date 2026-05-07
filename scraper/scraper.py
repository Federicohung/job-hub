# Job Hub — Scraping Engine
# Prioriza: remoto español > remoto LATAM > remoto España > híbrido LATAM/ES > presencial LATAM/ES
# Fuentes: Remotive API, Arbeitnow API, RemoteOK API (gratis, sin API key)
# Output: data/jobs.json normalizado

import json, hashlib, re, time, logging, html, os
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('job-hub')

# Output path: relative to script location, then one level up for repo root
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(_SCRIPT_DIR, 'data', 'jobs.json')

# ─── Lightweight HTTP client (no deps) ───

def http_get(url, timeout=15):
    req = Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 JobHub/1.0',
        'Accept': 'application/json',
    })
    try:
        resp = urlopen(req, timeout=timeout)
        body = resp.read().decode('utf-8', errors='replace')
        return resp.status, json.loads(body) if body else {}
    except HTTPError as e:
        body = e.read().decode('utf-8', errors='replace') if e.fp else ''
        return e.code, {}
    except (URLError, Exception) as e:
        log.error(f'HTTP GET failed: {url} -> {e}')
        return 0, {}

def http_post(url, payload, timeout=15):
    data = json.dumps(payload).encode('utf-8')
    req = Request(url, data=data, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 JobHub/1.0',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    })
    try:
        resp = urlopen(req, timeout=timeout)
        body = resp.read().decode('utf-8', errors='replace')
        return resp.status, json.loads(body) if body else {}
    except HTTPError as e:
        return e.code, {}
    except (URLError, Exception) as e:
        log.error(f'HTTP POST failed: {url} -> {e}')
        return 0, {}

def head_check(url, timeout=8):
    """Quick HEAD to verify URL reachable."""
    req = Request(url, method='HEAD', headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 JobHub/1.0',
    })
    try:
        resp = urlopen(req, timeout=timeout)
        return resp.status < 400
    except:
        try:
            resp = urlopen(Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 JobHub/1.0',
            }), timeout=timeout)
            return resp.status < 400
        except:
            return False


# ─── Spanish / Hispanic market detection ───

SPANISH_KEYWORDS = [
    'spanish', 'español', 'espanol', 'hispanic', 'latam', 'latin america',
    'mexico', 'méxico', 'colombia', 'argentina', 'chile', 'peru', 'perú',
    'bogota', 'bogotá', 'buenos aires', 'santiago', 'lima', 'madrid',
    'barcelona', 'valencia', 'sevilla', 'bilbao', 'malaga', 'málaga',
    'costa rica', 'ecuador', 'venezuela', 'uruguay', 'panama', 'panamá',
    'guadalajara', 'monterrey', 'medellin', 'medellín', 'caracas',
    'montevideo', 'quito', 'san jose', 'guatemala', 'spain', 'españa',
    'espana', 'sudamerica', 'latinoamérica', 'latinoamerica',
    'bilingual', 'bilingue', 'bilingüe', 'español hablado', 'hablar español',
]

LATAM_COUNTRIES = [
    'mexico', 'méxico', 'colombia', 'argentina', 'chile', 'peru', 'perú',
    'brazil', 'brasil', 'costa rica', 'ecuador', 'venezuela', 'uruguay',
    'panama', 'panamá', 'bolivia', 'paraguay', 'cuba', 'dominican',
    'guatemala', 'honduras', 'nicaragua', 'el salvador',
]

SPAIN_REGIONS = ['madrid', 'barcelona', 'valencia', 'sevilla', 'bilbao',
                 'malaga', 'málaga', 'alicante', 'zaragoza', 'palma',
                 'vigo', 'gijon', 'cataluna', 'cataluña', 'andalucia',
                 'andalucía', 'pais vasco', 'galicia', 'canarias', 'murcia',
                 'navarra', 'rioja', 'asturias', 'cantabria', 'extremadura',
                 'aragon', 'castilla', 'leon', 'galicia']


def is_hispanic_relevant(text: str) -> bool:
    """Check if any text field suggests Hispanic market relevance.
    Strategy: location-based (strongest signal) + language mentions + region context."""
    t = text.lower()

    # Location: direct LATAM/Spain city or country mention
    location_signals = [
        'mexico', 'méxico', 'colombia', 'argentina', 'chile', 'peru', 'perú',
        'bogota', 'bogotá', 'buenos aires', 'santiago', 'lima',
        'madrid', 'barcelona', 'valencia', 'sevilla', 'bilbao', 'malaga', 'málaga',
        'costa rica', 'ecuador', 'venezuela', 'uruguay', 'panama', 'panamá',
        'guadalajara', 'monterrey', 'medellin', 'medellín', 'caracas',
        'montevideo', 'quito', 'guatemala', 'spain', 'españa', 'espana',
        'sudamerica',
    ]
    has_location = any(loc in t for loc in location_signals)

    # Language: explicit Spanish requirement
    language_signals = [
        'spanish', 'español', 'espanol', 'hispanic', 'hispano',
        'bilingue', 'bilingüe', 'bilingual',
        'spanish speaking', 'fluent spanish', 'hablar español',
        'spanish required', 'spanish mandatory', 'español hablado',
    ]
    has_language = any(kw in t for kw in language_signals)

    # Region context: LATAM in job scope
    region_context = any(kw in t for kw in [
        'latam', 'latin america', 'latinoamérica', 'latinoamerica',
        'emea and latam', 'latam south', 'latam north', 'latam region',
        'latin american', 'north america latam', 'mercado hispano',
    ])

    # Decision logic:
    # 1. Location match (Spain/LATAM city) = always relevant
    # 2. Region context (LATAM in scope) = relevant
    # 3. Language mention + no specific non-Hispanic location = relevant
    if has_location:
        return True
    if region_context:
        return True
    if has_language:
        # Accept but exclude if clearly non-relevant (e.g. "Native English and Spanish" in a US-only job)
        non_hispanic_only = any(loc in t for loc in [
            'united states only', 'us-only', 'usa only', 'uk only',
            'germany only', 'berlin only', 'london only',
        ])
        if not non_hispanic_only:
            return True

    return False


def detect_location_priority(location_str: str, description: str = '', remote: bool = False) -> dict:
    loc = location_str.lower()
    desc = description.lower()
    combined = loc + ' ' + desc

    is_remote = remote or any(w in combined for w in ['remote', 'remoto', 'work from home', 'wfh', 'teletrabajo'])
    is_hybrid = any(w in combined for w in ['hybrid', 'híbrido', 'hibrido', 'semi-remote', 'semi remote'])

    has_spain = any(r in combined for r in SPAIN_REGIONS) or any(r in combined for r in ['spain', 'españa', 'espana'])
    has_latam = any(c in combined for c in LATAM_COUNTRIES) or 'latam' in combined
    has_spanish = any(w in combined for w in ['spanish', 'español', 'espanol', 'hispanic', 'biling', 'bilingue'])

    if is_remote:
        if has_spanish:
            return {'tier': 1, 'category': 'remote-spanish'}
        elif has_latam:
            return {'tier': 2, 'category': 'remote-latam'}
        elif has_spain:
            return {'tier': 3, 'category': 'remote-spain'}
        else:
            return {'tier': 4, 'category': 'remote-global'}
    elif is_hybrid:
        if has_latam:
            return {'tier': 5, 'category': 'hybrid-latam'}
        elif has_spain:
            return {'tier': 6, 'category': 'hybrid-spain'}
    else:
        if has_latam:
            return {'tier': 7, 'category': 'onsite-latam'}
        elif has_spain:
            return {'tier': 8, 'category': 'onsite-spain'}

    return {'tier': 9, 'category': 'other'}


def make_id(source: str, source_id: str) -> str:
    return hashlib.md5(f"{source}:{source_id}".encode()).hexdigest()[:12]


def strip_html(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def is_recent(posted_str: str, max_days: int = 21) -> bool:
    try:
        for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']:
            try:
                dt = datetime.strptime(posted_str[:19], fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
                return dt >= cutoff
            except ValueError:
                continue
        try:
            ts = float(posted_str)
            if ts > 1e12:
                ts = ts / 1000
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
            return dt >= cutoff
        except (ValueError, TypeError):
            pass
    except:
        pass
    return True


# ─── Source: Remotive API ───

def scrape_remotive() -> list:
    jobs = []
    categories = ['sales', 'business-management', 'customer-service', 'marketing',
                  'finance-legal', 'hr-people', 'software-dev', 'admin',
                  'customer-support', 'data-science', 'design', 'legal']

    for cat in categories:
        try:
            status, data = http_get(f'https://remotive.com/api/remote-jobs?category={cat}')
            if status != 200:
                log.warning(f'Remotive {cat}: HTTP {status}')
                continue

            for j in data.get('jobs', []):
                title = j.get('title', '')
                company = j.get('company_name', '')
                desc = strip_html(j.get('description', ''))
                location = j.get('candidate_required_location', '')
                url_link = j.get('url', '')
                posted = j.get('publication_date', '')
                job_type = j.get('job_type', '')
                salary = j.get('salary', 'No publicado')
                tags = j.get('tags', [])

                combined = f"{title} {company} {desc} {location} {' '.join(tags)}".lower()
                if not is_hispanic_relevant(combined):
                    continue
                if not is_recent(posted, 21):
                    continue

                loc_info = detect_location_priority(location, desc, remote=True)

                jobs.append({
                    'id': make_id('remotive', str(j.get('id', title))),
                    'source': 'remotive',
                    'sourceUrl': url_link,
                    'title': title,
                    'company': company,
                    'location': location,
                    'remote': True,
                    'type': job_type.upper().replace('_', '_') if job_type else 'FULL_TIME',
                    'salary': salary if salary else 'No publicado',
                    'description': desc[:600],
                    'postedAt': posted,
                    'foundAt': datetime.now(timezone.utc).isoformat(),
                    'tags': tags[:8],
                    'locationPriority': loc_info['category'],
                    'locationTier': loc_info['tier'],
                })
            log.info(f'Remotive {cat}: got {len(data.get("jobs", []))} jobs')
            time.sleep(2)
        except Exception as e:
            log.error(f'Remotive {cat}: {e}')

    return jobs


# ─── Source: Arbeitnow API ───

def scrape_arbeitnow() -> list:
    jobs = []
    seen = set()

    for page in range(1, 5):
        try:
            status, data = http_get(f'https://www.arbeitnow.com/api/job-board-api?page={page}')
            if status != 200:
                log.warning(f'Arbeitnow page {page}: HTTP {status}')
                break

            items = data.get('data', [])
            if not items:
                break

            for j in items:
                title = j.get('title', '')
                company = j.get('company_name', '')
                desc = strip_html(j.get('description', ''))
                location = j.get('location', '')
                url_link = j.get('url', '')
                is_remote = j.get('remote', False)
                created = j.get('created_at', '')
                job_types = j.get('job_types', [])
                tags = j.get('tags', [])

                source_id = j.get('slug', title)
                if source_id in seen:
                    continue
                seen.add(source_id)

                combined = f"{title} {company} {desc} {location}".lower()
                if not is_hispanic_relevant(combined):
                    continue
                if not is_recent(str(created), 21):
                    continue

                loc_info = detect_location_priority(location, desc, remote=is_remote)

                jobs.append({
                    'id': make_id('arbeitnow', source_id),
                    'source': 'arbeitnow',
                    'sourceUrl': url_link,
                    'title': title,
                    'company': company,
                    'location': location,
                    'remote': is_remote,
                    'type': (job_types[0] if job_types else 'full_time').upper().replace('-', '_'),
                    'salary': 'No publicado',
                    'description': desc[:600],
                    'postedAt': str(created),
                    'foundAt': datetime.now(timezone.utc).isoformat(),
                    'tags': tags[:8],
                    'locationPriority': loc_info['category'],
                    'locationTier': loc_info['tier'],
                })

            log.info(f'Arbeitnow page {page}: {len(items)} items')
            time.sleep(3)
        except Exception as e:
            log.error(f'Arbeitnow page {page}: {e}')
            break

    return jobs


# ─── Source: RemoteOK API ───

def scrape_remoteok() -> list:
    jobs = []
    # Search with multiple relevant tags
    search_tags = ['spanish', 'latam', 'spain']

    for tag in search_tags:
        try:
            status, data = http_get(f'https://remoteok.com/api?tags={tag}')
            if status != 200:
                log.warning(f'RemoteOK {tag}: HTTP {status}')
                continue

            for j in data:
                if not isinstance(j, dict) or j.get('slug') is None:
                    continue

                title = j.get('title', '')
                company = j.get('company', '')
                desc = strip_html(j.get('description', ''))
                location = j.get('location', '')
                url_link = j.get('url', '')
                tags = j.get('tags', [])
                posted = j.get('epoch', '')
                salary = j.get('salary', 'No publicado')

                combined = f"{title} {company} {desc} {location} {' '.join(tags)}".lower()
                if not is_hispanic_relevant(combined):
                    continue

                loc_info = detect_location_priority(location, desc, remote=True)

                jobs.append({
                    'id': make_id('remoteok', str(j.get('id', title))),
                    'source': 'remoteok',
                    'sourceUrl': url_link,
                    'title': title,
                    'company': company,
                    'location': location,
                    'remote': True,
                    'type': 'FULL_TIME',
                    'salary': salary if salary else 'No publicado',
                    'description': desc[:600],
                    'postedAt': datetime.fromtimestamp(int(posted), tz=timezone.utc).isoformat() if str(posted).isdigit() else str(posted),
                    'foundAt': datetime.now(timezone.utc).isoformat(),
                    'tags': tags[:8],
                    'locationPriority': loc_info['category'],
                    'locationTier': loc_info['tier'],
                })

            log.info(f'RemoteOK {tag}: collected')
            time.sleep(3)
        except Exception as e:
            log.error(f'RemoteOK {tag}: {e}')

    return jobs


# ─── Source: Torre API ───

def scrape_torre() -> list:
    jobs = []
    queries = [
        {'keyword': 'remote', 'size': 25},
        {'keyword': 'spanish', 'size': 25},
        {'keyword': 'latam', 'size': 25},
    ]

    for q in queries:
        try:
            status, data = http_post(
                'https://api.torre.co/opportunities/_search/',
                {'and': [
                    {'term': {'remote': True}},
                    {'term': {'keyword': q['keyword']}},
                ]}
            )
            if status != 200:
                log.warning(f'Torre {q["keyword"]}: HTTP {status}')
                continue

            results = data.get('results', [])
            for opp in results:
                obj = opp.get('objective', '') or ''
                orgs = opp.get('organizations', [])
                org_name = orgs[0].get('name', 'N/A') if orgs else 'N/A'
                opp_id = opp.get('id', obj)
                locations = opp.get('locations', [])
                loc_str = ', '.join(l.get('name', '') for l in locations) if locations else 'Remote'
                opp_desc = strip_html(opp.get('description', ''))

                combined = f"{obj} {org_name} {loc_str}".lower()
                if not is_hispanic_relevant(combined):
                    continue

                loc_info = detect_location_priority(loc_str, obj, remote=True)

                jobs.append({
                    'id': make_id('torre', str(opp_id)),
                    'source': 'torre',
                    'sourceUrl': f'https://torre.co/opportunities/{opp_id}',
                    'title': obj,
                    'company': org_name,
                    'location': loc_str,
                    'remote': True,
                    'type': 'FULL_TIME',
                    'salary': 'No publicado',
                    'description': opp_desc[:600],
                    'postedAt': opp.get('created', ''),
                    'foundAt': datetime.now(timezone.utc).isoformat(),
                    'tags': [s.get('name', '') for s in opp.get('skills', []) if s.get('name')][:8],
                    'locationPriority': loc_info['category'],
                    'locationTier': loc_info['tier'],
                })

            log.info(f'Torre {q["keyword"]}: {len(results)} results')
            time.sleep(2)
        except Exception as e:
            log.error(f'Torre {q["keyword"]}: {e}')

    return jobs


# ─── Link validation ───

def validate_url(url: str) -> bool:
    if not url or not url.startswith('http'):
        return False
    return head_check(url)


# ─── Deduplication ───

def deduplicate(jobs: list) -> list:
    seen = {}
    for job in jobs:
        key = re.sub(r'[\s\-,\.]+', ' ', f"{job['company'].lower()}:{job['title'].lower()}").strip()
        if key not in seen or job['locationTier'] < seen[key]['locationTier']:
            seen[key] = job
    return list(seen.values())


# ─── Main pipeline ───

def run_pipeline():
    log.info('=== Job Hub Pipeline START ===')
    all_jobs = []

    # Phase 1: Free APIs (fast, no browser)
    api_sources = [
        ('Remotive', scrape_remotive),
        ('Arbeitnow', scrape_arbeitnow),
        ('RemoteOK', scrape_remoteok),
        ('Torre', scrape_torre),
    ]

    for name, fn in api_sources:
        log.info(f'[API] {name}...')
        try:
            results = fn()
            all_jobs.extend(results)
            log.info(f'[API] {name}: {len(results)} jobs')
        except Exception as e:
            log.error(f'[API] {name} FAILED: {e}')

    # Phase 2: Scraping Hispanic job boards (real Spanish jobs)
    log.info('=== Phase 2: Scraping Hispanic Job Boards ===')
    import importlib.util

    _script_dir = os.path.dirname(os.path.abspath(__file__))
    MAX_JOBS = 1000

    try:
        spec = importlib.util.spec_from_file_location("scrape_computrabajo", os.path.join(_script_dir, "scrape_computrabajo.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log.info(f'Scraping Computrabajo (max {MAX_JOBS})...')
        ct_jobs = mod.scrape_computrabajo(max_jobs=MAX_JOBS)
        all_jobs.extend(ct_jobs)
        log.info(f'[Scrape] Computrabajo: {len(ct_jobs)} jobs')
    except Exception as e:
        log.error(f'[Scrape] Computrabajo FAILED: {e}')

    try:
        spec = importlib.util.spec_from_file_location("scrape_infojobs", os.path.join(_script_dir, "scrape_infojobs.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log.info('Scraping InfoJobs (Spain)...')
        ij_jobs = mod.scrape_infojobs()
        all_jobs.extend(ij_jobs)
        log.info(f'[Scrape] InfoJobs: {len(ij_jobs)} jobs')
    except Exception as e:
        log.error(f'[Scrape] InfoJobs FAILED: {e}')

    # GetOnBoard (Tech/LATAM)
    try:
        spec = importlib.util.spec_from_file_location("scrape_getonboard", os.path.join(_script_dir, "scrape_getonboard.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log.info('Scraping GetOnBoard...')
        gob_jobs = mod.scrape_getonboard()
        all_jobs.extend(gob_jobs)
        log.info(f'[Scrape] GetOnBoard: {len(gob_jobs)} jobs')
    except Exception as e:
        log.error(f'[Scrape] GetOnBoard FAILED: {e}')

    # Laborum (CL, PE, AR)
    try:
        spec = importlib.util.spec_from_file_location("scrape_laborum", os.path.join(_script_dir, "scrape_laborum.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log.info('Scraping Laborum...')
        lb_jobs = mod.scrape_laborum()
        all_jobs.extend(lb_jobs)
        log.info(f'[Scrape] Laborum: {len(lb_jobs)} jobs')
    except Exception as e:
        log.error(f'[Scrape] Laborum FAILED: {e}')

    # Bumeran (AR, PE, CO, MX, CL)
    try:
        spec = importlib.util.spec_from_file_location("scrape_bumeran", os.path.join(_script_dir, "scrape_bumeran.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log.info('Scraping Bumeran...')
        bm_jobs = mod.scrape_bumeran()
        all_jobs.extend(bm_jobs)
        log.info(f'[Scrape] Bumeran: {len(bm_jobs)} jobs')
    except Exception as e:
        log.error(f'[Scrape] Bumeran FAILED: {e}')

    # LinkedIn Public Search (best effort — may get blocked)
    try:
        spec = importlib.util.spec_from_file_location("scrape_linkedin", os.path.join(_script_dir, "scrape_linkedin.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log.info('Scraping LinkedIn (public)...')
        li_jobs = mod.scrape_linkedin()
        all_jobs.extend(li_jobs)
        log.info(f'[Scrape] LinkedIn: {len(li_jobs)} jobs')
    except Exception as e:
        log.error(f'[Scrape] LinkedIn FAILED: {e}')

    # Indeed Public Search (best effort — aggressive anti-bot)
    try:
        spec = importlib.util.spec_from_file_location("scrape_indeed", os.path.join(_script_dir, "scrape_indeed.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log.info('Scraping Indeed (public)...')
        ij_jobs = mod.scrape_indeed()
        all_jobs.extend(ij_jobs)
        log.info(f'[Scrape] Indeed: {len(ij_jobs)} jobs')
    except Exception as e:
        log.error(f'[Scrape] Indeed FAILED: {e}')

    before = len(all_jobs)
    all_jobs = deduplicate(all_jobs)
    log.info(f'Dedup: {before} → {len(all_jobs)}')

    # Sort by tier (ascending = higher priority)
    all_jobs.sort(key=lambda j: (j['locationTier'], j['postedAt'] or ''), reverse=False)

    # Validate URLs (sample only — skip for bulk scrapers)
    log.info('Validating URLs (sample)...')
    valid_jobs = []
    # Validate all API-sourced jobs, skip bulk scraper jobs (they have valid domain URLs)
    for job in all_jobs:
        if job['source'].startswith('computrabajo-') or job['source'] == 'infojobs' or job['source'].startswith('getonboard') or job['source'].startswith('laborum') or job['source'].startswith('bumeran') or job['source'] == 'linkedin' or job['source'].startswith('indeed-'):
            job['urlValid'] = True  # Trust known domain URLs
            valid_jobs.append(job)
        else:
            if validate_url(job['sourceUrl']):
                job['urlValid'] = True
                valid_jobs.append(job)
            else:
                log.warning(f'Invalid URL: {job["title"]} @ {job["company"]}')

    log.info(f'URL validation: {len(valid_jobs)}/{len(all_jobs)} valid')

    # Build output
    bd = {}
    for cat in ['remote-spanish', 'remote-latam', 'remote-spain', 'remote-global',
                'hybrid-latam', 'hybrid-spain', 'onsite-latam', 'onsite-spain', 'other']:
        bd[cat] = len([j for j in valid_jobs if j.get('locationPriority') == cat])

    output = {
        'version': '1.0',
        'updatedAt': datetime.now(timezone.utc).isoformat(),
        'totalJobs': len(valid_jobs),
        'sources': sorted(set(j['source'] for j in valid_jobs)),
        'breakdown': bd,
        'jobs': valid_jobs,
    }

    # Save
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info(f'=== DONE: {len(valid_jobs)} jobs saved ===')
    return output


if __name__ == '__main__':
    run_pipeline()
