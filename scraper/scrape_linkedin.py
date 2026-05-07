# Scraper: LinkedIn Public Job Search (no login required)
# Uses curl_cffi with Chrome impersonation
# Best effort — LinkedIn blocks aggressively. Gracefully handles failures.
# Focus: Spanish-speaking positions, LATAM, Spain, remote global

import time, logging, hashlib, re
from curl_cffi import requests as cffi_requests
from lxml import html as lhtml

log = logging.getLogger('job-hub')

def make_id(source, source_id):
    return hashlib.md5(f"{source}:{source_id}".encode()).hexdigest()[:12]

SESSION = cffi_requests.Session(impersonate='chrome')

# LinkedIn search queries targeting Spanish-speaking / LATAM / Spain markets
QUERIES = [
    ('remote spanish speaking', 'Remote Worldwide'),
    ('remote latam', 'Remote LATAM'),
    ('remote spain', 'Remote Spain'),
    ('trabajo remoto español', 'Remoto Español'),
    ('spanish required remote', 'Remote Spanish Required'),
    ('bilingual spanish english remote', 'Remote Bilingual'),
    ('remoto latinoamerica', 'Remoto LatAm'),
    ('remote chile', 'Remote Chile'),
    ('remote colombia', 'Remote Colombia'),
    ('remote mexico', 'Remote Mexico'),
    ('remote argentina', 'Remote Argentina'),
    ('director operaciones remote', 'Director Ops Remote'),
    ('gerente comercial remote', 'Gerente Comercial Remote'),
    ('operations manager remote spanish', 'Ops Manager Spanish Remote'),
    ('customer success manager remote latam', 'CSM Remote LATAM'),
    ('sales manager remote spanish speaking', 'Sales Manager Spanish Remote'),
]


def _classify(query_label, location_text=''):
    combined = (query_label + ' ' + location_text).lower()

    has_spanish = any(w in combined for w in [
        'spanish', 'español', 'espanol', 'bilingual', 'bilingue',
        'hispanic', 'latam', 'latin america', 'chile', 'colombia',
        'mexico', 'méxico', 'argentina', 'peru', 'perú',
    ])
    has_spain = any(w in combined for w in ['spain', 'españa', 'espana', 'madrid', 'barcelona'])

    if has_spanish and has_spain:
        return ('remote-spain', 3)
    elif has_spanish:
        return ('remote-spanish', 1)
    elif has_spain:
        return ('remote-spain', 3)
    else:
        return ('remote-global', 4)


def _parse_linkedin_jobs(page_html, query_label):
    jobs = []
    tree = lhtml.fromstring(page_html)

    # LinkedIn job cards - public search selectors
    cards = (
        tree.cssselect('.base-search-card') or
        tree.cssselect('[class*="job-search-card"]') or
        tree.cssselect('[class*="JobCard"]') or
        tree.cssselect('.job-card-container') or
        tree.cssselect('li[data-occluded-depth]') or
        tree.cssselect('.jobs-search__results-list li') or
        []
    )

    for card in cards:
        try:
            # Title
            title_el = (card.cssselect('.base-search-card__title') or
                       card.cssselect('h3') or
                       card.cssselect('[class*="title"]'))
            title = (title_el[0].text_content().strip() if title_el else '').strip()
            if not title or len(title) < 5:
                continue

            # Company
            company_el = (card.cssselect('.base-search-card__subtitle') or
                         card.cssselect('h4') or
                         card.cssselect('[class*="company"]'))
            company = (company_el[0].text_content().strip() if company_el else '').strip()

            # Location
            loc_el = (card.cssselect('.job-search-card__location') or
                     card.cssselect('[class*="location"]'))
            location = (loc_el[0].text_content().strip() if loc_el else 'Remote').strip()

            # Link — LinkedIn job links
            link_el = (card.cssselect('a.base-search-card__full-link') or
                      card.cssselect('a[href*="/jobs/view/"]') or
                      card.cssselect('h3 a') or card.cssselect('a'))
            link = ''
            if link_el:
                href = link_el[0].get('href', '')
                if href and '/jobs/view/' in href:
                    # Clean tracking params
                    link = href.split('?')[0]

            if not link or '/jobs/view/' not in link:
                continue

            if company.lower() == title.lower() or not company:
                company = 'No especificada'

            loc_cat, loc_tier = _classify(query_label, location)

            # Extract job ID from URL
            job_id_match = re.search(r'/jobs/view/(\d+)', link)
            source_id = job_id_match.group(1) if job_id_match else link

            jobs.append({
                'id': make_id('linkedin', source_id),
                'source': 'linkedin',
                'sourceUrl': link,
                'title': title,
                'company': company,
                'location': location,
                'remote': True,  # All LinkedIn queries are remote-focused
                'type': 'FULL_TIME',
                'salary': 'No publicado',
                'description': '',
                'postedAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
                'foundAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
                'tags': ['linkedin', query_label.lower().replace(' ', '-')],
                'locationPriority': loc_cat,
                'locationTier': loc_tier,
                'urlValid': True,
            })
        except Exception:
            continue

    return jobs


def scrape_linkedin(max_jobs=300):
    """Scrape LinkedIn public job search. Best effort — may get blocked."""
    all_jobs = []
    seen_ids = set()
    blocked = False

    for query, label in QUERIES:
        if blocked or len(all_jobs) >= max_jobs:
            break

        for page in range(0, 3):  # 0, 25, 50
            if blocked or len(all_jobs) >= max_jobs:
                break

            try:
                url = f'https://www.linkedin.com/jobs/search/?keywords={query.replace(" ", "+")}&start={page}'
                log.info(f'LinkedIn: "{query}" page {page}')

                resp = SESSION.get(url, timeout=25)

                if resp.status_code == 403 or 'captcha' in resp.text.lower() or 'challenge' in resp.url:
                    log.warning('LinkedIn: blocked (403/captcha). Stopping LinkedIn scraping.')
                    blocked = True
                    break

                if resp.status_code != 200:
                    log.warning(f'LinkedIn: HTTP {resp.status_code}')
                    break

                jobs = _parse_linkedin_jobs(resp.text, label)
                new = [j for j in jobs if j['id'] not in seen_ids]
                for j in new:
                    seen_ids.add(j['id'])
                all_jobs.extend(new)

                if len(jobs) == 0:
                    break

                log.info(f'  → {len(new)} new jobs (total: {len(all_jobs)})')
                time.sleep(4)  # LinkedIn is aggressive — longer delay

            except Exception as e:
                log.warning(f'LinkedIn "{query}" p{page}: {e}')
                break

        time.sleep(3)

    log.info(f'LinkedIn: {len(all_jobs)} total jobs ({"BLOCKED" if blocked else "OK"})')
    return all_jobs


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    jobs = scrape_linkedin()
    print(f'\nTotal: {len(jobs)} jobs from LinkedIn')
    if jobs:
        print(f'Sample: {jobs[0]["title"]} @ {jobs[0]["company"]} ({jobs[0]["locationPriority"]})')
