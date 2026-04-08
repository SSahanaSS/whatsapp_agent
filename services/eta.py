import math
from services.db import get_prep_time, get_kitchen_queue_delay

KITCHEN_LAT = 13.010886
KITCHEN_LNG = 80.157838


def haversine_minutes(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Straight-line distance converted to drive time assuming 20 km/h Chennai traffic."""
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lng / 2) ** 2
    )
    km = R * 2 * math.asin(math.sqrt(a))
    mins = round((km / 20) * 60)
    print(f"[Haversine] Distance: {km:.2f} km → {mins} mins")
    return max(5, mins)


def can_geocode(address: str) -> bool:
    return True


def calculate_full_eta(
    items: list,
    customer_address: str = None,
    lat: float = None,
    lng: float = None,
) -> dict:
    prep        = get_prep_time(items)
    queue_delay = get_kitchen_queue_delay()
    buffer      = 5

    if lat and lng:
        travel = haversine_minutes(KITCHEN_LAT, KITCHEN_LNG, lat, lng)
        print(f"[ETA] Using coordinates: ({lat}, {lng})")
    else:
        travel = 20
        print(f"[ETA] No coordinates — using flat 20 min travel fallback")

    total = prep + queue_delay + travel + buffer

    print("\n[ETA BREAKDOWN]")
    print(f"Prep Time   : {prep} mins")
    print(f"Queue Delay : {queue_delay} mins")
    print(f"Travel Time : {travel} mins")
    print(f"Buffer      : {buffer} mins")
    print(f"TOTAL ETA   : {total} mins")

    return {
        "total": total,
        "breakdown": {
            "prep_time":   prep,
            "queue_delay": queue_delay,
            "travel_time": travel,
            "buffer":      buffer,
        },
    }