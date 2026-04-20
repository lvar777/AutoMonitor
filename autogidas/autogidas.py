from urllib.parse import urlparse, urlunparse
from curl_cffi.requests import AsyncSession
from lxml import html as lxml_html

def _strip_mobile(url):
    parsed = urlparse(url)
    if parsed.netloc.startswith('m.'):
        parsed = parsed._replace(netloc=parsed.netloc[2:])
    return urlunparse(parsed)

class autogidas:
    def __init__(self, proxy):
        self.proxy = proxy
        self._session = AsyncSession(impersonate="chrome")

    async def _get(self, url, timeout=15, retries=5):
        for attempt in range(1, retries + 1):
            try:
                r = await self._session.get(url, proxy=self.proxy, timeout=timeout)
                if r.status_code == 200:
                    return lxml_html.fromstring(r.content)
                print(f'[AUTOGIDAS] HTTP {r.status_code} on attempt {attempt}/{retries}: {url}')
            except Exception as e:
                print(f'[AUTOGIDAS] Request error on attempt {attempt}/{retries}: {e}')
        print(f'[AUTOGIDAS] All {retries} attempts failed for: {url}')
        return None

    async def get_max_page(self, url):
        url = _strip_mobile(url)
        try:
            tree = await self._get(url)
            if tree is not None:
                page_links = tree.xpath('//a[@class="page"]')
                numbers = [int(a.text.strip()) for a in page_links if a.text and a.text.strip().isdigit()]
                return max(numbers) if numbers else 1
        except Exception as e:
            print(f'[AUTOGIDAS] An error during max_pages: {e}')
        return 1

    async def get_listing(self, url):
        url = _strip_mobile(url)
        try:
            tree = await self._get(url)
            if tree is not None:
                def og(prop):
                    el = tree.xpath(f'//meta[@property="{prop}"]')
                    return el[0].get('content') if el else None
                def og_all(prop):
                    return [el.get('content') for el in tree.xpath(f'//meta[@property="{prop}"]') if el.get('content')]
                return {
                    'title': og('og:title'),
                    'images': og_all('og:image'),
                    'description': og('og:description'),
                    'url': url,
                }
        except Exception as e:
            print(f'[AUTOGIDAS] An error fetching listing: {e}')
        return None

    async def fetch(self, url, page=1):
        url = _strip_mobile(url)
        print(f'[AUTOGIDAS] Fetching page {page}...')
        try:
            return await self._get(url)
        except Exception as e:
            print(f'[AUTOGIDAS] An error has occured: {e}')
        return None
