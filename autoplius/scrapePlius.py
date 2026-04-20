import asyncio
import hashlib
import json
import os
import time
from autoplius.autoplius import autoplius, _strip_mobile

DOMAIN = "https://autoplius.lt"
SEEN_DIR = os.path.dirname(__file__)
SEED_RETRY_DELAY = 10
STALE_THRESHOLD = 600

LISTING_XPATHS = [
    '//a[@class="announcement-item is-enhanced is-gallery"]',
    '//a[@class="announcement-item"]',
]

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
        for xpath in LISTING_XPATHS:
            for link in html.xpath(xpath):
                href = link.attrib.get('href')
                if href:
                    full = DOMAIN + href if href.startswith('/') else href
                    full = _strip_mobile(full)
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
            print(f'[AUTOPLIUS] {len(still_pending)} pages failed, retrying in {SEED_RETRY_DELAY}s...')
            await asyncio.sleep(SEED_RETRY_DELAY)
        pending = still_pending

    return [results[page] for page, _ in paged_urls]

def _ensure_order_params(url: str) -> str:
    if 'order_by=' not in url:
        separator = '&' if '?' in url else '?'
        url = url + separator + 'order_by=3&order_direction=DESC'
    return url

async def scrape(url, client=None, proxy=None, on_new_listing=None):
    url = _strip_mobile(url)
    url = _ensure_order_params(url)
    if client is None:
        client = autoplius(proxy=proxy)

    max_page = await client.get_max_page(url)
    print(f'[AUTOPLIUS] Total pages: {max_page}')

    seen_file = _seen_file(url)
    ready_file = _ready_file(url)
    last_run_file = _last_run_file(url)
    is_seeded = os.path.exists(ready_file)
    seen = load_seen(seen_file)

    paged_urls = [
        (page, client._set_page(url, page))
        for page in range(1, max_page + 1)
    ]

    if not is_seeded:
        responses = await _fetch_all_until_complete(client, paged_urls)
        _parse_hrefs(responses, seen)
        save_seen(seen, seen_file)
        open(ready_file, 'w').close()
        save_last_run(last_run_file)
        print(f'[AUTOPLIUS] Seeding complete — {len(seen)} listings known, watching for new ones')
        return []

    last_run = load_last_run(last_run_file)
    is_stale = (time.time() - last_run) > STALE_THRESHOLD

    if is_stale:
        print(f'[AUTOPLIUS] Catching up after idle...')
        responses = await _fetch_all_until_complete(client, paged_urls)
        _parse_hrefs(responses, seen)
        save_seen(seen, seen_file)
        save_last_run(last_run_file)
        print(f'[AUTOPLIUS] Caught up — {len(seen)} listings known, watching for new ones')
        return []

    # scrape cycle
    first_page_url = client._set_page(url, 1)
    responses = await asyncio.gather(client.fetch(first_page_url, page=1))
    new_hrefs = _parse_hrefs(responses, seen)
    save_last_run(last_run_file)
    if new_hrefs:
        save_seen(seen, seen_file)
        print(f'[AUTOPLIUS] {len(new_hrefs)} new listings found')
        for href in new_hrefs:
            if on_new_listing:
                await on_new_listing(href)
    else:
        print(f'[AUTOPLIUS] No new listings')
    return new_hrefs
