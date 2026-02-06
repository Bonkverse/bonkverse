import json
import requests
import time
from pathlib import Path

MEDIA_BASE = "https://bonkverse.io/media/skins"
INPUT_JSON = "skin_ids.json"

OUT_EXISTING = "existing_ids.json"
OUT_MISSING = "missing_ids.json"
OUT_REPORT  = "media_audit.json"

HEADERS = {
    "User-Agent": "Bonkverse-Media-Audit/1.0"
}

REQUEST_DELAY = 0.05  # 20 req/sec, safe


def image_exists(skin_id: int) -> bool:
    url = f"{MEDIA_BASE}/{skin_id}.png"
    try:
        r = requests.head(url, headers=HEADERS, timeout=5)
        return r.status_code == 200
    except requests.RequestException:
        return False


def main():
    ids = json.loads(Path(INPUT_JSON).read_text())

    existing = []
    missing = []
    report = {}

    for i, skin_id in enumerate(ids, start=1):
        ok = image_exists(skin_id)

        report[skin_id] = {
            "exists": ok,
            "url": f"{MEDIA_BASE}/{skin_id}.png"
        }

        if ok:
            existing.append(skin_id)
        else:
            missing.append(skin_id)

        if i % 100 == 0:
            print(f"Checked {i}/{len(ids)}")

        time.sleep(REQUEST_DELAY)

    Path(OUT_EXISTING).write_text(json.dumps(existing, indent=2))
    Path(OUT_MISSING).write_text(json.dumps(missing, indent=2))
    Path(OUT_REPORT).write_text(json.dumps(report, indent=2))

    print("\n✅ Media audit complete")
    print(f"🟢 Existing: {len(existing)}")
    print(f"🔴 Missing:  {len(missing)}")


if __name__ == "__main__":
    main()
