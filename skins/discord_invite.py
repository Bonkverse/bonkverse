# skins/discord_invite.py
import requests

DISCORD_INVITE_API = "https://discord.com/api/v9/invites/{code}"

def fetch_invite(code: str) -> dict:
    url = DISCORD_INVITE_API.format(code=code)
    params = {"with_counts": "true", "with_expiration": "true"}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def parse_invite_payload(payload: dict) -> dict:
    guild = payload.get("guild") or {}
    profile = payload.get("profile") or {}

    expires_at = payload.get("expires_at")  # None or ISO string
    # keep as string here; convert in caller if you want dt

    return {
        "guild_id": str(guild.get("id") or payload.get("guild_id") or ""),
        "name": guild.get("name") or profile.get("name") or "",
        "description": guild.get("description") or profile.get("description") or "",
        "icon_hash": guild.get("icon") or profile.get("icon_hash") or "",
        "splash_hash": guild.get("splash") or "",
        "member_count": int(profile.get("member_count") or 0),
        "online_count": int(profile.get("online_count") or 0),
        "expires_at": expires_at,  # keep raw; null means permanent
    }
