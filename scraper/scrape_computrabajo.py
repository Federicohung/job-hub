# Scraper: Computrabajo (CL, MX, CO, AR, PE, ES)
# Uses curl_cffi to bypass Cloudflare — no browser needed
# URLs are normalized to the {country}.computrabajo.com format

import time, logging, re, hashlib
from curl_cffi import requests as cffi_requests
from lxml import html as lhtml

log = logging.getLogger('job-hub')

def make_id(source, source_id):
    return hashlib.md5(f"{source}:{source_id}".encode()).hexdigest()[:12]

SESSION = cffi_requests.Session(impersonate='chrome')

# Use the canonical domain format that Computrabajo actually uses
COUNTRIES = [
    ('cl', 'Chile', 'https://cl.computrabajo.com'),
    ('mx', 'México', 'https://mx.computrabajo.com'),
    ('co', 'Colombia', 'https://co.computrabajo.com'),
    ('ar', 'Argentina', 'https://ar.computrabajo.com'),
    ('pe', 'Perú', 'https://pe.computrabajo.com'),
    ('es', 'España', 'https://es.computrabajo.com'),
]

QUERIES = [
    'remoto', 'teletrabajo',
    'gerente', 'director',
    'ventas', 'comercial', 'operaciones',
    'marketing', 'desarrollo',
    'customer success', 'datos',
]


def _normalize_url(url):
    """Ensure URL uses the canonical {country}.computrabajo.com domain."""
    # Map old domain formats to canonical
    domain_map = {
        'www.computrabajo.cl': 'cl.computrabajo.com',
        'www.computrabajo.com.mx': 'mx.computrabajo.com',
        'www.computrabajo.com.co': 'co.computrabajo.com',
        'www.computrabajo.com.ar': 'ar.computrabajo.com',
        'www.computrabajo.com.pe': 'pe.computrabajo.com',
        'www.computrabajo.es': 'es.computrabajo.com',
        'computrabajo.cl': 'cl.computrabajo.com',
        'computrabajo.com.mx': 'mx.computrabajo.com',
        'computrabajo.com.co': 'co.computrabajo.com',
        'computrabajo.com.ar': 'ar.computrabajo.com',
        'computrabajo.com.pe': 'pe.computrabajo.com',
        'computrabajo.es': 'es.computrabajo.com',
    }
    for old, new in domain_map.items():
        if old in url:
            url = url.replace(old, new)
    # Always use https
    if url.startswith('//'):
        url = 'https:' + url
    elif url.startswith('/'):
        url = 'https://cl.computrabajo.com' + url  # fallback
    return url


def _classify(loc_text, country_tld):
    loc = loc_text.lower()
    if any(w in loc for w in ['remoto', 'remote', 'home office', 'teletrabajo', '100% remoto']):
        return ('remote-latam' if country_tld != 'es' else 'remote-spain',
                2 if country_tld != 'es' else 3)
    if any(w in loc for w in ['hibrido', 'híbrido', 'semi-remoto']):
        return ('hybrid-latam' if country_tld != 'es' else 'hybrid-spain',
                5 if country_tld != 'es' else 6)
    return ('onsite-latam' if country_tld != 'es' else 'onsite-spain',
            7 if country_tld != 'es' else 8)


def _parse_computrabajo_page(page_html, base_url, country_tld, country_name):
    jobs = []
    tree = lhtml.fromstring(page_html)

    cards = (
        tree.cssselect('article[id^="offer-"]') or
        tree.cssselect('.box_offer') or
        tree.cssselect('div.b_OfferCard') or
        tree.cssselect('[class*="OfferCard"]') or
        tree.cssselect('ul.listOffers li') or
        tree.cssselect('div[id^="offer"]') or
        tree.cssselect('div.b_OfferList article') or
        []
    )

    if not cards:
        cards = tree.cssselect('a[href*="/ofertas-de-trabajo/"]')

    for card in cards:
        try:
            # Title
            title_el = (card.cssselect('h2 a') or card.cssselect('h2') or
                       card.cssselect('.fs18') or card.cssselect('a'))
            title = ''
            if title_el:
                title = title_el[0].text_content().strip()
            if not title or len(title) < 5:
                continue

            # Company — be more selective, avoid picking up title text
            company_el = (
                card.cssselect('.d-flex .t_company') or
                card.cssselect('[class*="company"]') or
                card.cssselect('.fc_base') or
                card.cssselect('p[class*="company"]') or
                card.cssselect('span[class*="company"]')
            )
            company = ''
            if company_el:
                company = company_el[0].text_content().strip()
            # Sanity: if company looks like a title (too long, contains keywords), skip it
            if not company or len(company) > 80:
                company = 'No especificada'

            # Location
            loc_el = (card.cssselect('.text_muted') or card.cssselect('[class*="location"]') or
                     card.cssselect('.fs13'))
            location = ''
            if loc_el:
                location = loc_el[0].text_content().strip()
            if not location:
                location = country_name

            # Salary
            sal_el = card.cssselect('.salary')
            salary = ''
            if sal_el:
                salary = sal_el[0].text_content().strip()
            if not salary or len(salary) < 2:
                salary = 'No publicado'

            # Link
            link_el = (card.cssselect('h2 a') or card.cssselect('a[href*="/ofertas-de-trabajo/"]') or
                      card.cssselect('a'))
            link = ''
            if link_el:
                href = link_el[0].get('href', '')
                if href:
                    link = href if href.startswith('http') else f"{base_url}{href}"

            if not link or 'ofertas-de-trabajo' not in link:
                continue

            # Normalize URL to canonical domain
            link = _normalize_url(link)

            # Skip if title and company are the same (parsing error)
            if company.lower() == title.lower():
                company = 'No especificada'

            loc_cat, loc_tier = _classify(title + ' ' + location, country_tld)

            jobs.append({
                'id': make_id(f'computrabajo-{country_tld}', link),
                'source': f'computrabajo-{country_tld}',
                'sourceUrl': link,
                'title': title,
                'company': company,
                'location': location,
                'remote': loc_tier <= 3,
                'type': 'FULL_TIME',
                'salary': salary,
                'description': '',
                'postedAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
                'foundAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
                'tags': [country_name, 'hispanic-market'],
                'locationPriority': loc_cat,
                'locationTier': loc_tier,
                'urlValid': True,  # validated below
            })
        except Exception:
            continue

    return jobs


def scrape_computrabajo(max_jobs=500):
    """Scrape Computrabajo country sites. Validates URLs with GET."""
    all_jobs = []
    seen_links = set()

    for tld, name, base_url in COUNTRIES:
        if len(all_jobs) >= max_jobs:
            break

        log.info(f'Scraping Computrabajo {name} ({tld})... ({len(all_jobs)}/{max_jobs})')
        country_jobs = []

        for qi, query in enumerate(QUERIES):
            if len(all_jobs) >= max_jobs:
                break

            for page in range(1, 3):
                if len(all_jobs) >= max_jobs:
                    break

                try:
                    url = f"{base_url}/ofertas-de-trabajo/?q={query.replace(' ', '+')}&p={page}"
                    resp = SESSION.get(url, timeout=20)

                    if resp.status_code != 200:
                        break

                    if 'captcha' in resp.text.lower() or 'challenge' in resp.url:
                        log.warning(f'Computrabajo {tld}: blocked at query {qi}')
                        break

                    jobs = _parse_computrabajo_page(resp.text, base_url, tld, name)
                    new = [j for j in jobs if j['sourceUrl'] not in seen_links]
                    for j in new:
                        seen_links.add(j['sourceUrl'])
                    country_jobs.extend(new)
                    all_jobs.extend(new)

                    if len(jobs) == 0:
                        break

                    time.sleep(1.5)
                except Exception as e:
                    log.warning(f'Computrabajo {tld} "{query}" p{page}: {e}')
                    break

            time.sleep(2)

        log.info(f'Computrabajo {name}: {len(country_jobs)} jobs')

    # Validate URLs — quick HEAD check
    valid_jobs = []
    removed = 0
    log.info(f'Validating {len(all_jobs)} URLs...')
    for i, job in enumerate(all_jobs):
        try:
            r = SESSION.head(job['sourceUrl'], allow_redirects=True, timeout=8)
            if r.status_code < 400:
                valid_jobs.append(job)
            else:
                removed += 1
                if removed <= 5:
                    log.warning(f'Invalid URL ({r.status_code}): {job["title"][:40]}')
        except:
            valid_jobs.append(job)  # network error = keep (transient)
        if (i + 1) % 50 == 0:
            log.info(f'  URL check: {i+1}/{len(all_jobs)} (valid={len(valid_jobs)})')
            time.sleep(3)

    if removed > 0:
        log.info(f'Removed {removed} jobs with invalid URLs')

    return valid_jobs


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    jobs = scrape_computrabajo(max_jobs=1200)
    print(f'\nTotal: {len(jobs)} validated jobs from Computrabajo')
    if jobs:
        print(f'Sample: {jobs[0]["title"]} @ {jobs[0]["company"]} ({jobs[0]["locationPriority"]})')
        print(f'URL: {jobs[0]["sourceUrl"][:100]}')
