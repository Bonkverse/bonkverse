"""Replay a search flood and measure what a normal visitor experiences meanwhile.

Reproduces the 2026-11-03 incident: one client fires searches faster than a
person could read them (each abandoned after 0.25 s, like rapid clicking), while
a second client loads the home page once a second and records how long it takes.

Usage (against a local server, never production):

    # 1. Start the server the way production runs it, with search limits lifted
    #    so every search is a real search (the worst case):
    ENV=production RATE_LIMIT_SEARCH=100000/m PORT=8899 \
        gunicorn -c gunicorn.conf.py bonk_skin_search.wsgi:application

    # 2. In another terminal:
    python scripts/load_test_search.py http://127.0.0.1:8899            # 240 searches/min
    python scripts/load_test_search.py http://127.0.0.1:8899 --searches 960

Healthy result: the home page stays well under a second throughout.
Before the 2026-11-03 fix it reached 15 s locally (and 115 s in production).
"""

import argparse
import random
import statistics
import threading
import time
import urllib.error
import urllib.request

WORDS = ["dog", "cat", "fire", "anime", "red", "blue", "flag", "space", "cute", "logo", "skull"]
SORTS = ["relevance", "newest", "upvotes"]


def _get(url: str, timeout: float):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except Exception:
        status = "timeout"
    return status, time.perf_counter() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url", help="e.g. http://127.0.0.1:8899 (local only)")
    parser.add_argument("--searches", type=int, default=240, help="searches to send (default 240)")
    parser.add_argument(
        "--seconds", type=int, default=60, help="spread over this long (default 60)"
    )
    args = parser.parse_args()

    if "bonkverse.io" in args.base_url or "railway.app" in args.base_url:
        parser.error("refusing to load-test production; point this at a local server")

    home_times, stop = [], threading.Event()

    def visitor():
        while not stop.is_set():
            status, seconds = _get(f"{args.base_url}/", timeout=120)
            home_times.append((status, seconds))
            time.sleep(1)

    watcher = threading.Thread(target=visitor)
    watcher.start()
    for i in range(args.searches):
        query = random.choice(WORDS) + (str(random.randint(0, 99)) if i % 3 else "")
        url = f"{args.base_url}/search/?q={query}&sort={random.choice(SORTS)}"
        threading.Thread(target=_get, args=(url, 0.25), daemon=True).start()
        time.sleep(args.seconds / args.searches)
    time.sleep(15)  # let any queue drain while still measuring
    stop.set()
    watcher.join()

    times = sorted(seconds for _status, seconds in home_times)
    statuses = sorted({str(status) for status, _seconds in home_times})
    print(f"{args.searches} searches over {args.seconds}s")
    print(
        f"home page: loads={len(times)}  median={statistics.median(times):.2f}s  "
        f"p90={times[int(len(times) * 0.9) - 1]:.2f}s  max={times[-1]:.2f}s  statuses={statuses}"
    )


if __name__ == "__main__":
    main()
