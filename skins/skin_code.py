# skins/utils/skin_code.py
import re
from urllib.parse import urlparse, parse_qs

SKIN_URL_RE = re.compile(r"https?://bonkleagues\.io/s/[A-Za-z0-9]{7}")

def extract_skin_code(link_or_img_url: str) -> str | None:
    # Works for either /s/<id> links (which redirect) or the avatar.svg URL with ?skinCode=...
    if "avatar.svg" in link_or_img_url:
        qs = parse_qs(urlparse(link_or_img_url).query)
        code = qs.get("skinCode", [None])[0]
        return code
    if SKIN_URL_RE.match(link_or_img_url):
        # You likely store the final image_url; if you still have only /s/<id>,
        # you can resolve it once via your existing fetcher to get the avatar.svg
        return None
    return None
