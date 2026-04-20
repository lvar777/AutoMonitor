import asyncio
import hashlib
import json
import os
import time
from autogidas.autogidas import autogidas

DOMAIN = "https://autogidas.lt"
SEEN_DIR = os.path.dirname(__file__)
SEED_RETRY_DELAY = 10
STALE_THRESHOLD = 600

def _seen_file(url: str) -> str:
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    return os.path.join(SEEN_DIR, f"seen_{url_hash}.json")

def _ready_file(url: str) -> str:
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    return os.path.join(SEEN_DIR, f"ready_{url_hash}")

def _last_run_file(url: str) -> str:
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    return os.path.join(SEEN_DIR, f"last_run_{url_hash}")

def load_seen(seen_file: str):
    if os.path.exists(seen_file):
        with open(seen_file) as f:
            return set(json.load(f))
    return set()

def save_seen(seen: set, seen_file: str):
    with open(seen_file, "w") as f:
        json.dump(list(seen), f)

def load_last_run(last_run_file: str) -> float:
    if os.path.exists(last_run_file):
        with open(last_run_file) as f:
            return float(f.read().strip())
    return 0.0

def save_last_run(last_run_file: str):
    with open(last_run_file, "w") as f:
        f.write(str(time.time()))

def _parse_hrefs(responses, seen):
    new_hrefs = []
    for html in responses:
        if html is None:
            continue
        articles = html.xpath('//article[@id="cars-container"]')
        for article in articles:
            for link in article.xpath('.//a[@href]'):
                href = link.attrib.get('href')
                # fix for only listings
                if href and href.startswith('/skelbimas/'):
                    full = DOMAIN + href
                    if full not in seen:
                        seen.add(full)
                        new_hrefs.append(full)
                        print(f'  - {full}')
    return new_hrefs

async def _fetch_all_until_complete(client, paged_urls):
    results = {page: None for page, _ in paged_urls}
    pending = list(paged_urls)

    while pending:
        responses = await asyncio.gather(*[client.fetch(u, page=p) for p, u in pending])
        still_pending = []
        for (page, u), response in zip(pending, responses):
            if response is not None:
                results[page] = response
            else:
                still_pending.append((page, u))

        if still_pending:
            print(f'[AUTOGIDAS] {len(still_pending)} page(s) failed, retrying in {SEED_RETRY_DELAY}s...')
            await asyncio.sleep(SEED_RETRY_DELAY)
        pending = still_pending

    return [results[page] for page, _ in paged_urls]

async def scrape(url, client=None, proxy=None, on_new_listing=None):
    if client is None:
        client = autogidas(proxy=proxy)

    max_page = await client.get_max_page(url)
    print(f'[AUTOGIDAS] Total pages: {max_page}')

    seen_file = _seen_file(url)
    ready_file = _ready_file(url)
    last_run_file = _last_run_file(url)
    is_seeded = os.path.exists(ready_file)
    seen = load_seen(seen_file)

    paged_urls = [
        (page, f"{url}&page={page}" if "?" in url else f"{url}?page={page}")
        for page in range(1, max_page + 1)
    ]

    if not is_seeded:
        responses = await _fetch_all_until_complete(client, paged_urls)
        _parse_hrefs(responses, seen)
        save_seen(seen, seen_file)
        open(ready_file, 'w').close()
        save_last_run(last_run_file)
        print(f'[AUTOGIDAS] Seeding was completed: {len(seen)} listings known, watching for new ones')
        return []

    last_run = load_last_run(last_run_file)
    is_stale = (time.time() - last_run) > STALE_THRESHOLD

    if is_stale:
        print(f'[AUTOGIDAS] Catching up after being idle...')
        responses = await _fetch_all_until_complete(client, paged_urls)
        _parse_hrefs(responses, seen)
        save_seen(seen, seen_file)
        save_last_run(last_run_file)
        print(f'[AUTOGIDAS] Caught up — {len(seen)} listings known, watching for new ones')
        return []

    # scrape cycle
    responses = await asyncio.gather(*[client.fetch(u, page=p) for p, u in paged_urls])
    new_hrefs = _parse_hrefs(responses, seen)
    save_last_run(last_run_file)
    if new_hrefs:
        save_seen(seen, seen_file)
        print(f'[AUTOGIDAS] {len(new_hrefs)} new listings found')
        for href in new_hrefs:
            if on_new_listing:
                await on_new_listing(href)
    else:
        print(f'[AUTOGIDAS] No new listings')
    return new_hrefs
