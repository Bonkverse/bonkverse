from playwright.sync_api import sync_playwright

def fetch_skin_image_url(bonkleagues_link):
    """
    Uses Playwright to fetch the Bonkleagues skin image URL from the shared image element.
    Returns the direct image URL or None if not found.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(bonkleagues_link, wait_until="domcontentloaded")

            image_element = page.locator("//img[@id='sharedimg']")
            skin_image_url = image_element.get_attribute("src") if image_element.count() > 0 else None
            browser.close()

        return skin_image_url
    except Exception as e:
        print(f"❌ Error fetching image URL: {e}")
        return None