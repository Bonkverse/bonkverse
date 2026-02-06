import os
import json
import psycopg2
from datetime import datetime, timezone
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import time
import argparse

# --------------------
# CLI arguments
# --------------------
parser = argparse.ArgumentParser(description="Label Bonkverse skins using OpenAI")
parser.add_argument("--limit", type=int, default=None, help="Limit number of skins to process")
parser.add_argument("--dry-run", action="store_true", help="Run without writing to database")
args = parser.parse_args()

# --------------------
# Setup
# --------------------
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set")

client = OpenAI(api_key=OPENAI_API_KEY)
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

MEDIA_BASE = "https://bonkverse.io"
IDS_FILE = "existing_ids.json"

REQUEST_DELAY = 0.5  # seconds (rate-limit friendly)

# --------------------
# Load IDs
# --------------------
skin_ids = json.loads(Path(IDS_FILE).read_text())

print(f"🧠 Loaded {len(skin_ids)} existing skin IDs")

# --------------------
# Fetch skins to label
# --------------------
cursor.execute(
    """
    SELECT id, image_url, name
    FROM skins_skin
    WHERE id = ANY(%s)
      AND (description IS NULL OR labels IS NULL)
    ORDER BY id
    """,
    (skin_ids,)
)

skins = cursor.fetchall()

if args.limit:
    skins = skins[:args.limit]

print(f"🎯 Skins queued for labeling: {len(skins)}")

if args.dry_run:
    print("🧪 DRY RUN MODE — no database writes will occur")

# --------------------
# OpenAI call
# --------------------
def get_description_and_labels(image_url, skin_name):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You're an image labeling assistant for a Bonk.io skin database. "
                    "You will be shown a circular skin design. "
                    "Do NOT include markdown. Do NOT say 'Sure' or 'Here you go'. "
                    "Output ONLY valid JSON in this structure:\n\n"
                    "{\n"
                    "  \"description\": \"Describe this skin in detail. Then, provide tags for color palette, "
                    "artistic style, recognizable objects, themes, references to media and culture "
                    "(memes, movies, shows, etc. if applicable), and overall impression.\",\n"
                    "  \"labels\": {\n"
                    "    \"colors\": [],\n"
                    "    \"style\": \"\",\n"
                    "    \"objects\": [],\n"
                    "    \"themes\": [],\n"
                    "    \"references\": []\n"
                    "  }\n"
                    "}\n\n"
                    "If no specific references are identifiable, describe shapes, colors, layout, and style. "
                    "You may add generic labels such as 'logo', 'abstract', or 'nsfw'. "
                    "Do NOT say you cannot identify it."
                )
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Skin name: {skin_name}"},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ],
        max_tokens=700,
    )

    return response.choices[0].message.content

# --------------------
# Processing loop
# --------------------
for index, (skin_id, image_url, name) in enumerate(skins, start=1):
    full_image_url = (
        image_url if image_url.startswith("http")
        else f"{MEDIA_BASE}{image_url}"
    )

    print(f"🔍 [{index}/{len(skins)}] Labeling skin {skin_id} — {name}")

    for attempt in range(3):
        try:
            raw = get_description_and_labels(full_image_url, name)
            parsed = json.loads(raw)

            description = parsed.get("description", "").strip() or "A circular skin design."
            labels = parsed.get("labels") or {
                "style": "unknown",
                "colors": [],
                "objects": [],
                "themes": [],
                "references": [],
            }

            now = datetime.now(timezone.utc)

            if not args.dry_run:
                cursor.execute(
                    """
                    UPDATE skins_skin
                    SET description = %s,
                        labels = %s,
                        labeled_at = %s
                    WHERE id = %s
                    """,
                    (description, json.dumps(labels), now, skin_id)
                )
                conn.commit()
                print(f"✅ Updated skin {skin_id}")
            else:
                print(f"🧪 Would update skin {skin_id}")

            break  # success → exit retry loop

        except Exception as e:
            print(f"⚠️ Attempt {attempt + 1} failed for skin {skin_id}: {e}")

            if attempt == 2:
                with open("failed_skins.log", "a") as f:
                    f.write(f"❌ Skin {skin_id} failed\n")
                    f.write(f"Image: {full_image_url}\n")
                    f.write(f"Error: {e}\n\n")

        time.sleep(REQUEST_DELAY)

# --------------------
# Cleanup
# --------------------
cursor.close()
conn.close()
print("🏁 Labeling process complete")
