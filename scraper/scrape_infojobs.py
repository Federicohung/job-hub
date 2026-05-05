# Scraper: InfoJobs (Spain)
# Uses curl_cffi to bypass anti-bot protection

import time, logging, re, hashlib
from curl_cffi import requests as cffi_requests
from lxml import html as lhtml

log = logging.getLogger('job-hub')

def make_id(source, source_id):
    return hashlib.md5(f"{source}:{source_id}".encode()).hexdigest()[:12]

SESSION = cffi_requests.Session(impersonate='chrome')

QUERIES = [
    'remoto', 'teletrabajo', 'trabajo desde casa',
    'gerente comercial', 'director operaciones',
    'ventas remoto', 'comercial remoto',
    'key account manager', 'customer success',
]


def _parse_infojobs_page(page_html):
    jobs = []
    tree = lhtml.fromstring(page_html)

    # Try multiple selectors
    cards = (
        tree.cssselect('[data-cy="offer-card"]') or
        tree.cssselect('.ij-OfferCard') or
        tree.cssselect('div.sui-AtomCard') or
        tree.cssselect('article') or
        []
    )

    for card in cards:
        try:
            title_el = (card.cssselect('h2') or card.cssselect('[class*="title"]') or
                       card.cssselect('a'))
            title = (title_el[0].text_content().strip() if title_el else '').strip()
            if not title or len(title) < 5:
                continue

            company_el = (card.cssselect('[class*="company"]') or
                         card.cssselect('a[href*="/empresa/"]') or
                         card.cssselect('[class*="subtitle"]'))
            company = (company_el[0].text_content().strip() if company_el else '').strip()

            loc_el = (card.cssselect('[class*="location"]') or card.cssselect('[class*="city"]'))
            location = (loc_el[0].text_content().strip() if loc_el else 'España').strip()

            sal_el = (card.cssselect('[class*="salary"]') or card.cssselect('[class*="salario"]'))
            salary = (sal_el[0].text_content().strip() if sal_el else 'No publicado')

            link_el = (card.cssselect('h2 a') or card.cssselect('a[href*="/ofertas-"]') or
                      card.cssselect('a'))
            link = ''
            if link_el:
                href = link_el[0].get('href', '')
                if href:
                    link = href if href.startswith('http') else f'https://www.infojobs.net{href}'

            if not link:
                continue

            loc_text = (title + ' ' + location).lower()
            is_remote = any(w in loc_text for w in ['remoto', 'remote', 'teletrabajo', '100% remoto'])
            is_hybrid = any(w in loc_text for w in ['hibrido', 'híbrido', 'semi-presencial'])

            jobs.append({
                'id': make_id('infojobs', link),
                'source': 'infojobs',
                'sourceUrl': link,
                'title': title,
                'company': company,
                'location': location,
                'remote': is_remote,
                'type': 'FULL_TIME',
                'salary': salary if salary and len(salary) > 2 else 'No publicado',
                'description': '',
                'postedAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
                'foundAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()),
                'tags': ['españa', 'hispanic-market'],
                'locationPriority': 'remote-spain' if is_remote else ('hybrid-spain' if is_hybrid else 'onsite-spain'),
                'locationTier': 3 if is_remote else (6 if is_hybrid else 8),
            })
        except Exception:
            continue

    return jobs


def scrape_infojobs():
    """Scrape InfoJobs Spain."""
    all_jobs = []
    seen_links = set()

    for query in QUERIES:
        log.info(f'InfoJobs query: "{query}"')
        for page in range(1, 4):
            try:
                url = f'https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword={query.replace(" ", "+")}&pageIdx={page}'
                resp = SESSION.get(url, timeout=20)

                if resp.status_code != 200:
                    break

                if 'captcha' in resp.text.lower():
                    log.warning(f'InfoJobs: blocked for "{query}"')
                    break

                jobs = _parse_infojobs_page(resp.text)
                new = [j for j in jobs if j['sourceUrl'] not in seen_links]
                for j in new:
                    seen_links.add(j['sourceUrl'])
                all_jobs.extend(new)

                if len(jobs) == 0:
                    break

                time.sleep(2)
            except Exception as e:
                log.warning(f'InfoJobs "{query}" p{page}: {e}')
                break

        time.sleep(2)

    log.info(f'InfoJobs: {len(all_jobs)} total jobs')
    return all_jobs


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    jobs = scrape_infojobs()
    print(f'\nTotal: {len(jobs)} jobs from InfoJobs')
    if jobs:
        print(f'Sample: {jobs[0]["title"]} @ {jobs[0]["company"]} ({jobs[0]["locationPriority"]})')
