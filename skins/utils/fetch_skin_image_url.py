import urllib.parse

_playwright = None  # global cache
_browser = None

def _get_browser():
    """ Lazily start Playwright → Chromium only once. """
    global _playwright, _browser
    if _browser:
        return _browser

    from playwright.sync_api import sync_playwright  # lazy import
    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(headless=True)
    return _browser


def fetch_skin_image_url(bonkleagues_link):
    try:
        browser = _get_browser()
        page = browser.new_page()
        page.goto(bonkleagues_link, wait_until="domcontentloaded")

        image_element = page.locator("//img[@id='sharedimg']")
        image_url = image_element.get_attribute("src") if image_element.count() > 0 else None
        page.close()

        if not image_url:
            return None

        parsed = urllib.parse.urlparse(image_url)
        query_params = urllib.parse.parse_qs(parsed.query)
        skin_code = query_params.get("skinCode", [None])[0]

        if not skin_code:
            return None

        return f"https://bonkleagues.io/api/avatar.svg?skinCode={urllib.parse.quote(skin_code)}"

    except Exception as e:
        print(f"❌ Error fetching skin image URL: {e}")
        return None
