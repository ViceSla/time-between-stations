import sys
from pathlib import Path
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

try:
    from google.transit import gtfs_realtime_pb2
except ImportError:
    sys.exit("Missing dependency: pip install gtfs-realtime-bindings")


# ── file paths ────────────────────────────────────────────────────────────────
IDS_FILE    = "ids_to_check.txt"
STOPS_FILE  = "Moje Stanice.txt"
OUTPUT_FILE = "times.txt"
LOGGER_FILE = "logger.txt"

FEED_URL    = "https://www.zet.hr/gtfs-rt-protobuf"

# ── loaders ───────────────────────────────────────────────────────────────────

def load_trip_ids(path: str) -> set[str]:
    raw = Path(path).read_text().strip()
    ids = {t.strip() for t in raw.split(",") if t.strip()}
    if not ids:
        sys.exit(f"[ERROR] No trip IDs found in '{path}'")
    return ids


def load_stations(path: str) -> tuple[str, str]:
    lines = [l.strip() for l in Path(path).read_text().splitlines() if l.strip()]
    if len(lines) != 2:
        sys.exit(f"[ERROR] '{path}' must contain exactly 2 stop IDs, found {len(lines)}")
    return lines[0], lines[1]


# ── already_logged persistence ────────────────────────────────────────────────

def load_logged(path: str) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    ids = {l.strip() for l in p.read_text().splitlines() if l.strip()}
    return ids


def save_logged(path: str, already_logged: set[str]) -> None:
    Path(path).write_text("\n".join(sorted(already_logged)) + "\n" if already_logged else "")


# ── GTFS-RT fetch ─────────────────────────────────────────────────────────────

def fetch_feed(url: str, timeout: int = 10) -> gtfs_realtime_pb2.FeedMessage:
    resp = requests.get(url, timeout=timeout, headers={"Accept": "application/x-protobuf"})
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


# ── core check ────────────────────────────────────────────────────────────────

def stop_time(stu) -> int | None:
    if stu.HasField("departure") and stu.departure.time:
        return stu.departure.time
    if stu.HasField("arrival") and stu.arrival.time:
        return stu.arrival.time
    return None


def arrival_time(stu) -> int | None:
    if stu.HasField("arrival") and stu.arrival.time:
        return stu.arrival.time
    if stu.HasField("departure") and stu.departure.time:
        return stu.departure.time
    return None


def check_feed(
    feed: gtfs_realtime_pb2.FeedMessage,
    trip_ids: set[str],
    stop_a: str,
    stop_b: str,
    stop_a_times: dict[str, int],
    already_logged: set[str],
) -> list[tuple[str, int]]:
    active_in_feed: set[str] = set()
    newly_matched: list[tuple[str, int]] = []

    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue

        trip_id = entity.trip_update.trip.trip_id
        if trip_id not in trip_ids:
            continue

        active_in_feed.add(trip_id)

        for stu in entity.trip_update.stop_time_update:
            sid = stu.stop_id

            if sid == stop_a and trip_id not in stop_a_times:
                t = stop_time(stu)
                if t:
                    stop_a_times[trip_id] = t

            elif sid == stop_b and trip_id in stop_a_times and trip_id not in already_logged:
                t = arrival_time(stu)
                if t:
                    duration = t - stop_a_times[trip_id]
                    already_logged.add(trip_id)
                    newly_matched.append((trip_id, duration))

    expired = (stop_a_times.keys() | already_logged) - active_in_feed
    if expired:
        for tid in expired:
            stop_a_times.pop(tid, None)
            already_logged.discard(tid)

    return newly_matched


# ── output ────────────────────────────────────────────────────────────────────

def append_duration(path: str, trip_id: str, duration: int) -> None:
    mins, secs = divmod(abs(duration), 60)
    line = f"{duration}    # trip_id={trip_id}  ({mins}m {secs}s)\n"
    with open(path, "a") as fh:
        fh.write(line)


# ── single run ────────────────────────────────────────────────────────────────

def run() -> None:
    trip_ids       = load_trip_ids(IDS_FILE)
    stop_a, stop_b = load_stations(STOPS_FILE)
    already_logged = load_logged(LOGGER_FILE)
    stop_a_times: dict[str, int] = {}

    Path(OUTPUT_FILE).touch()

    try:
        feed = fetch_feed(FEED_URL)
        matches = check_feed(feed, trip_ids, stop_a, stop_b, stop_a_times, already_logged)

        if matches:
            for trip_id, duration in matches:
                append_duration(OUTPUT_FILE, trip_id, duration)
        else:
            print("  [--]  No completed pairs this poll.")

    except requests.RequestException as exc:
        print(f"[WARN] Network error: {exc}")
    except Exception as exc:
        print(f"[ERROR] {exc}")
    finally:
        save_logged(LOGGER_FILE, already_logged)


if __name__ == "__main__":
    run()
