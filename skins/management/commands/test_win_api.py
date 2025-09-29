import time
import json
import requests
from django.core.management.base import BaseCommand

BASE_URL = "http://127.0.0.1:8000/api"


def pretty_print(label, resp):
    """Safely print API response"""
    try:
        data = resp.json()
    except Exception:
        data = resp.text
    print(f"{label} [{resp.status_code}]: {json.dumps(data, indent=2)}")


def start_session(username):
    resp = requests.post(f"{BASE_URL}/start_tracking/", json={"username": username})
    pretty_print("Start Tracking", resp)
    return resp.json().get("token") if resp.ok else None


def heartbeat(token):
    resp = requests.post(f"{BASE_URL}/heartbeat/", headers={"Authorization": f"Bearer {token}"})
    pretty_print("Heartbeat", resp)


def stop_session(token):
    resp = requests.post(f"{BASE_URL}/stop_tracking/", headers={"Authorization": f"Bearer {token}"})
    pretty_print("Stop Tracking", resp)


def send_win(username, token, map_name="Simple 1v1"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = requests.post(
        f"{BASE_URL}/wins/",
        headers=headers,
        json={"username": username, "map_name": map_name, "ts": int(time.time() * 1000)},
    )
    pretty_print("Win", resp)


def run_tests():
    print("---- Test 1: Valid session and win ----")
    token = start_session("TestPlayer")
    send_win("TestPlayer", token)

    print("\n---- Test 2: Start session twice (old token should break) ----")
    token1 = start_session("TestPlayer")
    token2 = start_session("TestPlayer")
    print("Old token (should fail):")
    send_win("TestPlayer", token1)
    print("New token (should succeed):")
    time.sleep(5)  # prevent <5s duplicate win
    send_win("TestPlayer", token2)

    print("\n---- Test 3: No token ----")
    r = requests.post(f"{BASE_URL}/wins/", json={"username": "TestPlayer", "map_name": "Simple"})
    pretty_print("No token", r)

    print("\n---- Test 4: Wrong token ----")
    send_win("TestPlayer", "badtoken123")

    print("\n---- Test 5: Username mismatch (PlayerB tries with PlayerA's token) ----")
    tokenA = start_session("PlayerA")
    send_win("PlayerB", tokenA)

    print("\n---- Test 6: Too fast wins (<5s apart) ----")
    token = start_session("Speedy")
    send_win("Speedy", token)
    time.sleep(1)
    send_win("Speedy", token)

    print("\n---- Test 7: Blacklisted map ----")
    token = start_session("Farmer")
    send_win("Farmer", token, "XP Farm 1000")

    print("\n---- Test 8: Rate limiting (>10 wins/minute) ----")
    token = start_session("RateLimitPlayer")
    for i in range(12):
        send_win("RateLimitPlayer", token)
        time.sleep(2)

    print("\n---- Test 9: Stop tracking and try win ----")
    token = start_session("Ender")
    stop_session(token)
    send_win("Ender", token)  # should now be 403 Invalid/Expired


class Command(BaseCommand):
    help = "Run integration tests for the win tracking API"

    def handle(self, *args, **options):
        run_tests()
