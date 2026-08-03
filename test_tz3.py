from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

z = ZoneInfo("America/New_York")
noon = datetime(2024, 3, 10, 12, tzinfo=z) # Spring forward day (missing 2 AM hour)
midnight = noon - timedelta(hours=12)

# GTFS time 5:00 AM (18000 seconds)
# True elapsed from midnight should be 5 hours
true_start = midnight.astimezone(ZoneInfo("UTC")) + timedelta(seconds=18000)
calc_start = (midnight + timedelta(seconds=18000)).astimezone(ZoneInfo("UTC"))
print("Start true:", true_start, "| calc:", calc_start)

# GTFS time 25:00 (90000 seconds, i.e. 1 AM next day)
true_end = midnight.astimezone(ZoneInfo("UTC")) + timedelta(seconds=90000)
calc_end = (midnight + timedelta(seconds=90000)).astimezone(ZoneInfo("UTC"))
print("End true:", true_end, "| calc:", calc_end)

