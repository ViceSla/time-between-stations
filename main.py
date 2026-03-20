import requests
from google.transit import gtfs_realtime_pb2
import time


def fetch_feed(url: str, timeout: int = 10) -> gtfs_realtime_pb2.FeedMessage:
    resp = requests.get(url, timeout=timeout, headers={"Accept": "application/x-protobuf"})
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


def run(feed_url: str, trip_ids: set[str], interval: int) -> None:
    while True:
        try:
            feed = fetch_feed(feed_url)
            ts = feed.header.timestamp
 
            matched = 0
            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue
                trip_id = entity.trip_update.trip.trip_id
                if trip_id in trip_ids:
                    print(entity)
                    matched += 1
 
            if matched == 0:
                print("[INFO] No matching trip_updates in this snapshot.")
 
        except requests.RequestException as exc:
            print(f"[WARN] Network error: {exc}")
        except Exception as exc:
            print(f"[ERROR] {exc}")
 
        print()
        time.sleep(interval)


def getTripIds(file):
    with open(file, "r") as f:
        s = f.read().split(",")
    
    return set(s)


if __name__ == "__main__":
    url = "https://www.zet.hr/gtfs-rt-protobuf"
    ids = getTripIds("ids_to_check.txt")
    run(url, ids, 30)