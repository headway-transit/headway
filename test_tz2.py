from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

z = ZoneInfo("America/New_York")
noon = datetime(2023, 11, 5, 12, tzinfo=z) # Fall back day
midnight = noon - timedelta(hours=12)

# GTFS time of 24:00 (86400 seconds) should be exactly 24 elapsed hours from midnight
gtfs_seconds = 86400
event_time = (midnight + timedelta(seconds=gtfs_seconds)).astimezone(ZoneInfo("UTC"))
print("GTFS 24:00 absolute:", event_time)

# True absolute 24 hours from midnight:
absolute_24h = midnight.astimezone(ZoneInfo("UTC")) + timedelta(seconds=86400)
print("True 24h elapsed:  ", absolute_24h)
