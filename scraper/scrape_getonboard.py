# Scraper: GetOnBoard (Tech/LATAM)
# Uses curl_cffi to bypass anti-bot protection
# Covers: general + country-specific sections

import time, logging, hashlib
from curl_cffi import requests as cffi_requests
from lxml import html as lhtml

log = logging.getLogger('job-hub')

def make_id(source, source_id):
    return hashlib.md5(f"{source}:{source_id}".encode()).hexdigest()[:12]

SESSION = cffi_requests.Session(impersonate='chrome')

# GetOnBoard country sections
COUNTRIES = [
    ('cl', 'Chile', 'https://www.getonbrd.com/cl'),
    ('pe', 'Perú', 'https://www.getonbrd.com/pe'),
    ('co', 'Colombia', 'https://www.getonbrd.com/co'),
    ('ar', 'Argentina', 'https://www.getonbrd.com/ar'),
    ('mx', 'México', 'https://www.getonbrd.com/mx'),
    (None, 'General', 'https://www.getonbrd.com'),
]

QUERIES = [
    'remote', 'operaciones', 'ventas', 'marketing',
    'desarrollo', 'customer success', 'sales', 'datos',
    'gerente', 'analista', 'finanzas', 'proyectos',
]


def _classify(loc_text, country_tld):
    loc = loc_text.lower()
    is_spain = country_tld == 'es'
    if any(w in loc for w in ['remoto', 'remote', 'home office', 'teletrabajo', '100% remoto', 'work from home']):
        return ('remote-spain' if is_spain else 'remote-latam',
                3 if is_spain else 2)
    if any(w in loc for w in ['hibrido', 'híbrido', 'semi-remoto', 'hybrid']):
        return ('hybrid-spain' if is_spain else 'hybrid-latam',
                6 if is_spain else 5)
    return ('onsite-spain' if is_spain else 'onsite-latam',
            8 if is_spain else 7)


def _parse_page(page_html, base_url, country_tld, country_name):
    jobs = []
    tree = lhtml.fromstring(page_html)

    # Try multiple card selectors
    cards = (
        tree.cssselect('[class*="JobCard"]') or
        tree.cssselect('[class*="job-card"]') or
        tree.cssselect('article[class*="job"]') or
        tree.cssselect('.job-listing') or
        tree.cssselect('[class*="OfferCard"]') or
        tree.cssselect('a[href*="/jobs/"]') or
        []
    )

    for card in cards:
        try:
            # Title
            title_el = (card.cssselect('h2') or card.cssselect('h3') or
                       card.cssselect('[class*="title"]') or card.cssselect('a'))
            title = (title_el[0].text_content().strip() if title_el else '').strip()
            if not title or len(title) < 5:
                continue

            # Company
            company_el = (card.cssselect('[class*="company"]') or
                         card.cssselect('[class*="Company"]') or
                         card.cssselect('[class*="subtitle"]') or
                         card.cssselect('[class*="organization"]'))
            company = (company_el[0].text_content().strip() if company_el else '').strip()

            # Location
            loc_el = (card.cssselect('[class*="location"]') or
                     card.cssselect('[class*="Location"]') or
                     card.cssselect('[class*="city"]'))
            location = (loc_el[0].text_content().strip() if loc_el else country_name).strip()

            # Salary
            sal_el = (card.cssselect('[class*="salary"]') or
                     card.cssselect('[class*="Salary"]') or
                     card.cssselect('[class*="compensation"]'))
            salary = (sal_el[0].text_content().strip() if sal_el else 'No publicado')

            # Tags
            tag_els = card.cssselect('[class*="tag"]') or card.cssselect('[class*="Tag"]')
            tags = [t.text_content().strip() for t in tag_els if t.text_content().strip()][:6]

            # Link
            link_el = card.cssselect('a[href*="/jobs/"]')
            if not link_el:
                link_el = card.cssselect('a')
            link = ''
            if link_el:
                href = link_el[0].get('href', '')
                if href:
                    link = href if href.startswith('http') else f"{base_url}{href}"

            if not link:
                continue

            if company.lower() == title.lower() or not company:
                company = 'No especificada'

            loc_cat, loc_tier = _classify(title + ' ' + location, country_tld or 'latam')

            src = f'getonboard-{country_tld}' if country_tld else 'getonboard'

            jobs.append({
                'id': make_id(src, link),
                'source': src,
                'sourceUrl': link,
                'title': title,
                'company': company,
                'location': location,
                'remote': loc_tier <= 3,
                'type': 'FULL_TIME',
                'salary': salary if salary and len(salary) > 2 else 'No publicado',
                'description': '',
                'postedAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
                'foundAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
                'tags': tags[:6] + [country_name.lower(), 'tech-market'],
                'locationPriority': loc_cat,
                'locationTier': loc_tier,
                'urlValid': True,
            })
        except Exception:
            continue

    return jobs


def scrape_getonboard(max_jobs=300):
    """Scrape GetOnBoard country sites."""
    all_jobs = []
    seen_links = set()

    for tld, name, base_url in COUNTRIES:
        if len(all_jobs) >= max_jobs:
            break

        log.info(f'Scraping GetOnBoard {name}... ({len(all_jobs)}/{max_jobs})')
        country_jobs = []

        for qi, query in enumerate(QUERIES):
            if len(all_jobs) >= max_jobs:
                break

            for page in range(1, 3):
                if len(all_jobs) >= max_jobs:
                    break

                try:
                    url = f"{base_url}/jobs?attribute=work_mode_remote&query={query.replace(' ', '+')}&page={page}"
                    resp = SESSION.get(url, timeout=20)

                    if resp.status_code != 200:
                        break

                    if 'captcha' in resp.text.lower() or 'challenge' in resp.url:
                        log.warning(f'GetOnBoard {tld}: blocked at query {qi}')
                        break

                    jobs = _parse_page(resp.text, base_url, tld, name)
                    new = [j for j in jobs if j['sourceUrl'] not in seen_links]
                    for j in new:
                        seen_links.add(j['sourceUrl'])
                    country_jobs.extend(new)
                    all_jobs.extend(new)

                    if len(jobs) == 0:
                        break

                    time.sleep(2)
                except Exception as e:
                    log.warning(f'GetOnBoard {tld} "{query}" p{page}: {e}')
                    break

            time.sleep(2)

        log.info(f'GetOnBoard {name}: {len(country_jobs)} jobs')

    return all_jobs


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    jobs = scrape_getonboard()
    print(f'\nTotal: {len(jobs)} jobs from GetOnBoard')
