# Scraper: Indeed (Public search — multiple countries)
# Uses curl_cffi with Chrome impersonation
# Best effort — Indeed is very aggressive with anti-bot. Gracefully handles failures.
# Focus: Spanish language positions, LATAM, Spain, remote global Spanish

import time, logging, hashlib, re
from curl_cffi import requests as cffi_requests
from lxml import html as lhtml

log = logging.getLogger('job-hub')

def make_id(source, source_id):
    return hashlib.md5(f"{source}:{source_id}".encode()).hexdigest()[:12]

SESSION = cffi_requests.Session(impersonate='chrome')

# Indeed country-specific domains
COUNTRIES = [
    ('es', 'España', 'https://es.indeed.com'),
    ('cl', 'Chile', 'https://cl.indeed.com'),
    ('mx', 'México', 'https://mx.indeed.com'),
    ('co', 'Colombia', 'https://co.indeed.com'),
    ('ar', 'Argentina', 'https://ar.indeed.com'),
    ('pe', 'Perú', 'https://pe.indeed.com'),
]

# Queries targeting SPANISH LANGUAGE positions across all markets
QUERIES = [
    'spanish required remote',
    'spanish speaking remote',
    'bilingual spanish english remote',
    'trabajo remoto español',
    'remote español',
    'remoto español',
    'trabajo remoto',
    'teletrabajo',
    'operations manager remoto',
    'gerente comercial remoto',
    'customer success español',
    'sales manager spanish',
    'director operaciones remoto',
    'marketing remoto español',
    'datos remoto español',
]


def _classify(loc_text, country_tld, query_text):
    """Classify based on language + location signals."""
    combined = (loc_text + ' ' + query_text).lower()

    has_spanish_lang = any(w in combined for w in [
        'spanish', 'español', 'espanol', 'bilingual', 'bilingue',
        'bilingüe', 'hispanic', 'español hablado', 'hablar español',
        'spanish required', 'spanish mandatory', 'fluent spanish',
        'idioma español', 'nivel español',
    ])
    has_latam = any(w in combined for w in [
        'latam', 'latin america', 'chile', 'colombia', 'mexico', 'méxico',
        'argentina', 'peru', 'perú', 'costa rica', 'ecuador', 'venezuela',
        'uruguay', 'guadalajara', 'monterrey', 'medellin', 'medellín',
        'bogota', 'bogotá', 'buenos aires', 'santiago', 'lima',
    ])
    has_spain = any(w in combined for w in [
        'spain', 'españa', 'espana', 'madrid', 'barcelona', 'valencia',
    ])
    is_remote = any(w in combined for w in ['remote', 'remoto', 'teletrabajo', 'work from home', 'home office'])

    # Priority: Spanish language + remote is the highest tier
    if has_spanish_lang:
        if is_remote:
            return ('remote-spanish', 1)
        elif has_latam:
            return ('onsite-latam', 7)
        elif has_spain:
            return ('onsite-spain', 8)
        else:
            return ('remote-spanish', 1)

    if is_remote:
        if has_latam or country_tld in ('cl', 'mx', 'co', 'ar', 'pe'):
            return ('remote-latam', 2)
        elif has_spain or country_tld == 'es':
            return ('remote-spain', 3)
        else:
            return ('remote-global', 4)

    # Onsite by country
    if country_tld == 'es':
        return ('onsite-spain', 8)
    return ('onsite-latam', 7)


def _parse_indeed_page(page_html, base_url, country_tld, country_name, query_text):
    jobs = []
    tree = lhtml.fromstring(page_html)

    # Indeed job card selectors (they change frequently)
    cards = (
        tree.cssselect('.job_seen_beacon') or
        tree.cssselect('[class*="job_seen"]') or
        tree.cssselect('.jobsearch-ResultsList > li') or
        tree.cssselect('[data-jk]') or
        tree.cssselect('.result') or
        tree.cssselect('[class*="JobCard"]') or
        tree.cssselect('ul.jobsearch-ResultsList li') or
        []
    )

    for card in cards:
        try:
            # Job key ID from Indeed
            jk = card.get('data-jk', '') or ''
            if not jk:
                # Try to find ID from link
                link_el = card.cssselect('h2 a[href*="jk="]')
                if link_el:
                    href = link_el[0].get('href', '')
                    match = re.search(r'jk=([a-f0-9]+)', href)
                    if match:
                        jk = match.group(1)

            # Title
            title_el = (card.cssselect('h2 a') or card.cssselect('.jobTitle') or
                       card.cssselect('[class*="title"] a') or card.cssselect('h2'))
            title = (title_el[0].text_content().strip() if title_el else '').strip()
            if not title or len(title) < 5:
                continue

            # Company
            company_el = (card.cssselect('.companyName') or
                         card.cssselect('[class*="companyName"]') or
                         card.cssselect('[data-testid="company-name"]') or
                         card.cssselect('[class*="company"]'))
            company = (company_el[0].text_content().strip() if company_el else '').strip()

            # Location
            loc_el = (card.cssselect('.companyLocation') or
                     card.cssselect('[class*="companyLocation"]') or
                     card.cssselect('[data-testid="text-location"]') or
                     card.cssselect('[class*="location"]'))
            location = (loc_el[0].text_content().strip() if loc_el else country_name).strip()

            # Salary
            sal_el = (card.cssselect('.salary-snippet') or
                     card.cssselect('[class*="salary"]') or
                     card.cssselect('[class*="attribute_snippet"]'))
            salary = (sal_el[0].text_content().strip() if sal_el else 'No publicado')

            # Link — build full URL
            link = ''
            if jk:
                link = f'{base_url}/viewjob?jk={jk}'
            else:
                link_el = (card.cssselect('h2 a') or card.cssselect('a[href*="/pagead/"]'))
                if link_el:
                    href = link_el[0].get('href', '')
                    if href:
                        link = href if href.startswith('http') else f"{base_url}{href}"

            if not link:
                continue

            # Spanish language check — must have Spanish signal
            all_text = (title + ' ' + (company or '') + ' ' + location + ' ' + query_text).lower()
            has_spanish = any(w in all_text for w in [
                'spanish', 'español', 'espanol', 'bilingual', 'bilingue',
                'remoto', 'teletrabajo', 'trabajo', 'gerente', 'comercial',
                'hispanic', 'latam', 'chile', 'colombia', 'mexico',
                'argentina', 'peru', 'spain', 'españa', 'madrid', 'barcelona',
            ])
            # For LATAM country sites, almost everything is in Spanish by default
            is_latam_site = country_tld in ('cl', 'mx', 'co', 'ar', 'pe')
            if not has_spanish and not is_latam_site:
                continue

            if company.lower() == title.lower() or not company or len(company) > 80:
                company = 'No especificada'

            loc_cat, loc_tier = _classify(location, country_tld, query_text)
            source_id = jk if jk else link

            jobs.append({
                'id': make_id(f'indeed-{country_tld}', source_id),
                'source': f'indeed-{country_tld}',
                'sourceUrl': link,
                'title': title,
                'company': company,
                'location': location,
                'remote': loc_tier <= 4,
                'type': 'FULL_TIME',
                'salary': salary if salary and len(salary) > 2 else 'No publicado',
                'description': '',
                'postedAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
                'foundAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
                'tags': [country_name.lower(), 'indeed', 'spanish-language'],
                'locationPriority': loc_cat,
                'locationTier': loc_tier,
                'urlValid': True,
            })
        except Exception:
            continue

    return jobs


def scrape_indeed(max_jobs=400):
    """Scrape Indeed public search across LATAM + Spain."""
    all_jobs = []
    seen_ids = set()

    for tld, name, base_url in COUNTRIES:
        if len(all_jobs) >= max_jobs:
            break

        log.info(f'Scraping Indeed {name} ({tld})... ({len(all_jobs)}/{max_jobs})')
        country_jobs = []
        blocked = False

        for query in QUERIES:
            if blocked or len(all_jobs) >= max_jobs:
                break

            for page_offset in [0, 10, 20]:
                if blocked or len(all_jobs) >= max_jobs:
                    break

                try:
                    url = f'{base_url}/trabajos?q={query.replace(" ", "+")}&start={page_offset}'
                    log.info(f'  Indeed {tld}: "{query}" offset={page_offset}')

                    resp = SESSION.get(url, timeout=25)

                    if resp.status_code == 403 or 'captcha' in resp.text.lower() or 'challenge' in resp.url:
                        log.warning(f'Indeed {tld}: blocked. Moving to next country.')
                        blocked = True
                        break

                    if resp.status_code != 200:
                        log.warning(f'Indeed {tld}: HTTP {resp.status_code}')
                        break

                    jobs = _parse_indeed_page(resp.text, base_url, tld, name, query)
                    new = [j for j in jobs if j['id'] not in seen_ids]
                    for j in new:
                        seen_ids.add(j['id'])
                    country_jobs.extend(new)
                    all_jobs.extend(new)

                    if len(jobs) == 0:
                        break

                    log.info(f'    → {len(new)} new jobs')
                    time.sleep(4)  # Indeed is aggressive

                except Exception as e:
                    log.warning(f'Indeed {tld} "{query}": {e}')
                    break

            time.sleep(3)

        log.info(f'Indeed {name}: {len(country_jobs)} jobs')

    log.info(f'Indeed total: {len(all_jobs)} jobs')
    return all_jobs


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    jobs = scrape_indeed()
    print(f'\nTotal: {len(jobs)} jobs from Indeed')
    if jobs:
        print(f'Sample: {jobs[0]["title"]} @ {jobs[0]["company"]} ({jobs[0]["locationPriority"]})')
