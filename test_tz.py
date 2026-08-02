from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

z = ZoneInfo("America/New_York")
noon = datetime(2023, 11, 5, 12, tzinfo=z) # Fall back day
midnight = noon - timedelta(hours=12)
print("Midnight wall clock:", midnight)

noon_spring = datetime(2024, 3, 10, 12, tzinfo=z) # Spring forward day
midnight_spring = noon_spring - timedelta(hours=12)
print("Spring midnight wall clock:", midnight_spring)
