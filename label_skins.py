import os
import requests
import json
import base64
import psycopg2
import subprocess
from datetime import datetime, timezone
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# PostgreSQL connection
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cursor = conn.cursor()

# Get skins that need labeling
cursor.execute("SELECT id, image_url, name FROM skins_skin WHERE description IS NULL OR labels IS NULL")
skins = cursor.fetchall()

# === SVG to PNG Conversion ===
def download_svg(svg_url, filename="skin.svg"):
    try:
        response = requests.get(svg_url)
        response.raise_for_status()
        with open(filename, "wb") as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"❌ Failed to download SVG from {svg_url}: {e}")
        return False

def convert_svg_to_png(svg_path="skin.svg", png_path="skin.png", size=512):
    try:
        cmd = [
            "inkscape", svg_path,
            f"--export-filename={png_path}",
            f"--export-width={size}",
            f"--export-height={size}",
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return png_path
    except Exception as e:
        print(f"❌ Failed to convert SVG to PNG: {e}")
        return None

def encode_image_to_base64(png_path="skin.png"):
    try:
        with open(png_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print(f"❌ Failed to encode PNG to base64: {e}")
        return None

# === AI Analysis ===
def get_description_and_labels(base64_image, skin_name):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You're an image labeling assistant for a Bonk.io skin database. "
                    "You will be shown a circular skin design. Don't include any markdown, don't say 'Sure' or 'Here you go', etc. Your job is to output only valid JSON in this structure:\n\n"
                    "{\n"
                    "  \"description\": \"Describe this skin in detail. Then, provide tags for color palette, artistic style, recognizable objects, themes, references to media and culture (memes, movies, shows, etc...if applicable), and overall impression. Return tags as a JSON dictionary.\",\n"
                    "  \"labels\": {\n"
                    "    \"colors\": [\"...\"],\n"
                    "    \"style\": \"...\",\n"
                    "    \"objects\": [\"...\"],\n"
                    "    \"themes\": [\"...\"],\n"
                    "    \"references\": [\"...\"]\n"
                    "  }\n"
                    "}\n\n"
                    "If you cannot identify specific references (like copyrighted stuff or NSFW content), just describe shapes, colors, layout, and style. You can still add generic labels such as 'logo', 'nsfw', etc. Do not say you cannot identify it"
                )
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Return only the JSON structure described."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]
            }
        ],
        max_tokens=700
    )
    return response.choices[0].message.content

# === Process Each Skin ===
def process_skin(skin_id, image_url, name, retries=2):
    if not download_svg(image_url):
        return
    if not convert_svg_to_png():
        return
    base64_image = encode_image_to_base64()
    if not base64_image:
        return

    for attempt in range(retries + 1):
        try:
            result = get_description_and_labels(base64_image, name)

            if not result or result.strip() == "":
                raise ValueError("Empty response from OpenAI")

            try:
                parsed = json.loads(result)
            except json.JSONDecodeError:
                if "```json" in result:
                    _, json_part = result.split("```json", 1)
                    json_part = json_part.strip("`\n ")
                    parsed = json.loads(json_part)
                else:
                    raise

            description = parsed.get("description", "").strip() or "A circular skin design."
            labels = parsed.get("labels", {}) or {
                "style": "unknown", "colors": [], "objects": [], "themes": [], "references": []
            }

            now = datetime.now(timezone.utc)
            cursor.execute(
                "UPDATE skins_skin SET description = %s, labels = %s, labeled_at = %s WHERE id = %s",
                (description, json.dumps(labels), now, skin_id)
            )
            print(f"✅ Updated skin {skin_id}")
            return  # Success, break out of retry loop

        except Exception as e:
            print(f"⚠️ Attempt {attempt + 1} failed for skin {skin_id}: {e}")
            if attempt == retries:
                # Log the issue for manual follow-up
                with open("failed_skins.log", "a") as f:
                    f.write(f"❌ Skin {skin_id} failed with error: {e}\n")
                    f.write(f"Raw result: {result if 'result' in locals() else 'No result'}\n\n")



# === Main loop ===
for skin_id, image_url, name in skins:
    process_skin(skin_id, image_url, name)
    conn.commit()

cursor.close()
conn.close()
print("🏁 All done.")
