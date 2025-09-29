import requests
import time

API_URL = "http://127.0.0.1:8000/api/wins/"

def send_win(username, map_name="Simple 1v1"):
    resp = requests.post(API_URL, json={
        "username": username,
        "map_name": map_name,
        "ts": int(time.time() * 1000)
    })
    try:
        print(resp.json())
    except Exception:
        print("Error:", resp.text)

print("---- Test 1: Normal win ----")
send_win("TestPlayer", "Simple 1v1")

print("---- Test 2: Fast win (<5s apart, should fail) ----")
send_win("TestPlayer", "Simple 1v1")  # immediately
time.sleep(1)
send_win("TestPlayer", "Simple 1v1")  # 1s later

print("---- Test 3: Blacklisted map ----")
send_win("TestPlayer", "Fastest XP Grind")  # should be blocked

print("---- Test 4: Rate limiting (11 wins in <60s) ----")
for i in range(11):
    send_win("RateLimitPlayer", "Simple 1v1")
    time.sleep(2)  # small pause so they’re valid, but total > 10/min
