import urllib.parse
from playwright.sync_api import sync_playwright

def fetch_skin_image_url(bonkleagues_link):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(bonkleagues_link, wait_until="domcontentloaded")

            image_element = page.locator("//img[@id='sharedimg']")
            image_url = image_element.get_attribute("src") if image_element.count() > 0 else None
            browser.close()

            if not image_url:
                return None

            parsed = urllib.parse.urlparse(image_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            skin_code = query_params.get("skinCode", [None])[0]

            if not skin_code:
                return None

            # Construct API URL
            svg_url = f"https://bonkleagues.io/api/avatar.svg?skinCode={urllib.parse.quote(skin_code)}"
            return svg_url

    except Exception as e:
        print(f"❌ Error fetching skin image URL: {e}")
        return None