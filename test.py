import requests
from google.transit import gtfs_realtime_pb2

url = "https://www.zet.hr/gtfs-rt-protobuf"

response = requests.get(url)

feed = gtfs_realtime_pb2.FeedMessage()
feed.ParseFromString(response.content)

print(feed)

# for entity in feed.entity:
#     if entity.HasField("vehicle"):
#         print(entity)
#         break
        # vehicle = entity.vehicle
        # print("Vehicle ID:", vehicle.vehicle.id)
        # print("Trip ID:", vehicle.trip.trip_id)
        # print("Latitude:", vehicle.position.latitude)
        # print("Longitude:", vehicle.position.longitude)
        # print("Timestamp:", vehicle.timestamp)
        # print("------")
