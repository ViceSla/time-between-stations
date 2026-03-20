import argparse
import time
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


# ── file paths (edit if needed) ───────────────────────────────────────────────
IDS_FILE    = "ids_to_check.txt"
STOPS_FILE  = "Moje Stanice.txt"
OUTPUT_FILE = "times.txt"
INTERVAL = 5

# ── loaders ───────────────────────────────────────────────────────────────────

def load_trip_ids(path: str) -> set[str]:
    """Read trip IDs from a single-row CSV file."""
    raw = Path(path).read_text().strip()
    ids = {t.strip() for t in raw.split(",") if t.strip()}
    if not ids:
        sys.exit(f"[ERROR] No trip IDs found in '{path}'")
    print(f"[INFO] Loaded {len(ids)} trip ID(s) from '{path}'")
    return ids


def load_stations(path: str) -> tuple[str, str]:
    """Read exactly two stop IDs (one per line) from the stations file."""
    lines = [l.strip() for l in Path(path).read_text().splitlines() if l.strip()]
    if len(lines) != 2:
        sys.exit(f"[ERROR] '{path}' must contain exactly 2 stop IDs, found {len(lines)}")
    print(f"[INFO] Watching for stops: '{lines[0]}'  and  '{lines[1]}'")
    return lines[0], lines[1]


# ── GTFS-RT fetch ─────────────────────────────────────────────────────────────

def fetch_feed(url: str, timeout: int = 10) -> gtfs_realtime_pb2.FeedMessage:
    resp = requests.get(
        url, timeout=timeout,
        headers={"Accept": "application/x-protobuf"}
    )
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


# ── core check ────────────────────────────────────────────────────────────────

def stop_time(stu) -> int | None:
    """
    Return the best Unix timestamp for a StopTimeUpdate.
    Prefers departure (for the first stop) but falls back to arrival,
    and vice-versa.  Returns None if neither is set.
    """
    if stu.HasField("departure") and stu.departure.time:
        return stu.departure.time
    if stu.HasField("arrival") and stu.arrival.time:
        return stu.arrival.time
    return None


def arrival_time(stu) -> int | None:
    """Return arrival time, falling back to departure time."""
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
    stop_a_times: dict[str, int],   # trip_id -> predicted departure time at stop_a
    already_logged: set[str],
) -> list[tuple[str, int]]:
    """
    Returns a list of (trip_id, duration_seconds) for newly completed pairs.

    State machine per trip:
      • See stop_a  → cache its departure time in stop_a_times
      • See stop_b AND stop_a already cached → compute duration, mark logged
      • Trip vanishes from feed → clear both caches (midnight reset)
    """
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

            # Step 1 – record stop_a departure the first time we see it
            if sid == stop_a and trip_id not in stop_a_times:
                t = stop_time(stu)
                if t:
                    stop_a_times[trip_id] = t
                    human = datetime.fromtimestamp(t).strftime("%H:%M:%S")
                    print(f"  [STOP_A] trip={trip_id}  stop_a departure={human} ({t})")

            # Step 2 – when stop_b is seen and we already have stop_a time
            elif sid == stop_b and trip_id in stop_a_times and trip_id not in already_logged:
                t = arrival_time(stu)
                if t:
                    duration = t - stop_a_times[trip_id]
                    already_logged.add(trip_id)
                    newly_matched.append((trip_id, duration))

    # Reset trips that have left the feed (midnight rollover or trip finished)
    expired = (stop_a_times.keys() | already_logged) - active_in_feed
    if expired:
        print(f"  [RESET] {len(expired)} trip(s) left the feed, caches cleared: {expired}")
        for tid in expired:
            stop_a_times.pop(tid, None)
            already_logged.discard(tid)

    return newly_matched


# ── output ────────────────────────────────────────────────────────────────────

def append_duration(path: str, trip_id: str, duration: int) -> None:
    """Append travel duration in seconds (with a human-readable comment) to times.txt."""
    mins, secs = divmod(abs(duration), 60)
    line = f"{duration}    # trip_id={trip_id}  ({mins}m {secs}s)\n"
    with open(path, "a") as fh:
        fh.write(line)
    print(f"  [LOGGED] {line.strip()}")


# ── main loop ─────────────────────────────────────────────────────────────────

def run(feed_url: str, interval: int) -> None:
    trip_ids        = load_trip_ids(IDS_FILE)
    stop_a, stop_b  = load_stations(STOPS_FILE)
    stop_a_times:  dict[str, int] = {}   # trip_id -> predicted departure time at stop_a
    already_logged: set[str]      = set()

    # Make sure output file exists
    Path(OUTPUT_FILE).touch()

    print(f"\n[INFO] Feed    : {feed_url}")
    print(f"[INFO] Interval: {interval}s  |  Ctrl-C to stop\n")

    while True:
        try:
            feed = fetch_feed(feed_url)
            feed_ts = feed.header.timestamp
            print(f"[POLL] feed_timestamp={feed_ts}  entities={len(feed.entity)}")

            matches = check_feed(feed, trip_ids, stop_a, stop_b, stop_a_times, already_logged)

            if matches:
                print(f"  [HIT] {len(matches)} trip(s) completed both stops!")
                for trip_id, duration in matches:
                    append_duration(OUTPUT_FILE, trip_id, duration)
            else:
                print("  [--]  No completed pairs this poll.")

        except requests.RequestException as exc:
            print(f"[WARN] Network error: {exc}")
        except Exception as exc:
            print(f"[ERROR] {exc}")

        print()
        time.sleep(interval)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Log Unix timestamps when a watched trip covers both target stops."
    )
    parser.add_argument(
        "--feed", required=True,
        help="URL of the GTFS Realtime TripUpdates feed (protobuf)."
    )
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Polling interval in seconds (default: 30)."
    )
    return parser.parse_args()


if __name__ == "__main__":
    url = "https://www.zet.hr/gtfs-rt-protobuf"
    try:
        run(url, INTERVAL)
    except KeyboardInterrupt:
        print("\n[INFO] Stopped.")