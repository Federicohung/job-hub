# Scraper: Bumeran (AR, PE, CO, MX, CL)
# Uses curl_cffi to bypass anti-bot protection

import time, logging, hashlib
from curl_cffi import requests as cffi_requests
from lxml import html as lhtml

log = logging.getLogger('job-hub')

def make_id(source, source_id):
    return hashlib.md5(f"{source}:{source_id}".encode()).hexdigest()[:12]

SESSION = cffi_requests.Session(impersonate='chrome')

COUNTRIES = [
    ('ar', 'Argentina', 'https://www.bumeran.com.ar'),
    ('pe', 'Perú', 'https://www.bumeran.com.pe'),
    ('co', 'Colombia', 'https://www.bumeran.com.co'),
    ('mx', 'México', 'https://www.bumeran.com.mx'),
    ('cl', 'Chile', 'https://www.bumeran.cl'),
]

QUERIES = [
    'remoto', 'teletrabajo', 'gerente', 'ventas',
    'operaciones', 'marketing', 'comercial', 'desarrollo',
    'administrativo', 'finanzas', 'datos', 'analista',
]


def _classify(loc_text, country_tld):
    loc = loc_text.lower()
    if any(w in loc for w in ['remoto', 'remote', 'home office', 'teletrabajo', '100% remoto']):
        return ('remote-latam', 2)
    if any(w in loc for w in ['hibrido', 'híbrido', 'semi-remoto', 'hybrid']):
        return ('hybrid-latam', 5)
    return ('onsite-latam', 7)


def _parse_page(page_html, base_url, country_tld, country_name):
    jobs = []
    tree = lhtml.fromstring(page_html)

    # Bumeran selectors - try multiple patterns
    cards = (
        tree.cssselect('.aviso') or
        tree.cssselect('.job-item') or
        tree.cssselect('[data-id^="job-"]') or
        tree.cssselect('[class*="JobCard"]') or
        tree.cssselect('[class*="job-card"]') or
        tree.cssselect('[class*="vacante"]') or
        tree.cssselect('article') or
        tree.cssselect('.listado-avisos a') or
        []
    )

    for card in cards:
        try:
            # Title
            title_el = (card.cssselect('h2 a') or card.cssselect('h2') or
                       card.cssselect('.title') or card.cssselect('[class*="title"]') or
                       card.cssselect('.puesto') or card.cssselect('a'))
            title = (title_el[0].text_content().strip() if title_el else '').strip()
            if not title or len(title) < 5:
                continue

            # Company
            company_el = (card.cssselect('.company') or
                         card.cssselect('a[href*="/empresas/"]') or
                         card.cssselect('[class*="company"]') or
                         card.cssselect('[class*="empresa"]') or
                         card.cssselect('.nombre-empresa'))
            company = (company_el[0].text_content().strip() if company_el else '').strip()

            # Location
            loc_el = (card.cssselect('.location') or
                     card.cssselect('[class*="location"]') or
                     card.cssselect('.ubicacion') or
                     card.cssselect('[class*="ciudad"]') or
                     card.cssselect('[class*="region"]'))
            location = (loc_el[0].text_content().strip() if loc_el else country_name).strip()

            # Salary
            sal_el = (card.cssselect('[class*="salary"]') or
                     card.cssselect('[class*="sueldo"]') or
                     card.cssselect('[class*="remuneracion"]'))
            salary = (sal_el[0].text_content().strip() if sal_el else 'No publicado')

            # Link
            link_el = (card.cssselect('h2 a') or card.cssselect('a[href*="/empleos/"]') or
                      card.cssselect('a[href*="/trabajo/"]') or card.cssselect('a'))
            link = ''
            if link_el:
                href = link_el[0].get('href', '')
                if href:
                    link = href if href.startswith('http') else f"{base_url}{href}"

            if not link:
                continue

            if company.lower() == title.lower() or not company or len(company) > 80:
                company = 'No especificada'

            loc_cat, loc_tier = _classify(title + ' ' + location, country_tld)

            jobs.append({
                'id': make_id(f'bumeran-{country_tld}', link),
                'source': f'bumeran-{country_tld}',
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
                'tags': [country_name.lower(), 'hispanic-market'],
                'locationPriority': loc_cat,
                'locationTier': loc_tier,
                'urlValid': True,
            })
        except Exception:
            continue

    return jobs


def scrape_bumeran(max_jobs=300):
    """Scrape Bumeran country sites."""
    all_jobs = []
    seen_links = set()

    for tld, name, base_url in COUNTRIES:
        if len(all_jobs) >= max_jobs:
            break

        log.info(f'Scraping Bumeran {name} ({tld})... ({len(all_jobs)}/{max_jobs})')
        country_jobs = []

        for qi, query in enumerate(QUERIES):
            if len(all_jobs) >= max_jobs:
                break

            for page in range(1, 3):
                if len(all_jobs) >= max_jobs:
                    break

                try:
                    url = f"{base_url}/empleos-busqueda.html?q={query.replace(' ', '+')}&page={page}"
                    resp = SESSION.get(url, timeout=20)

                    if resp.status_code != 200:
                        break

                    if 'captcha' in resp.text.lower() or 'challenge' in resp.url:
                        log.warning(f'Bumeran {tld}: blocked at query {qi}')
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
                    log.warning(f'Bumeran {tld} "{query}" p{page}: {e}')
                    break

            time.sleep(2)

        log.info(f'Bumeran {name}: {len(country_jobs)} jobs')

    return all_jobs


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    jobs = scrape_bumeran()
    print(f'\nTotal: {len(jobs)} jobs from Bumeran')
