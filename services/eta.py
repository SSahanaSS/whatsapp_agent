import requests
from services.db import get_prep_time, get_kitchen_queue_delay

# ── Your home kitchen's GPS coordinates ───────────────────────────────────────
# Replace with your actual kitchen lat/lng
KITCHEN_LAT = 13.010886
KITCHEN_LNG = 80.157838

# Nominatim requires a User-Agent header — put your app name here
USER_AGENT = "home-kitchen-delivery-app"


def _geocode_address(address: str):
    """
    Converts a text address to (lat, lng) using Nominatim (OpenStreetMap).
    Returns (lat, lng) tuple or None if not found.
    """
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q":      address,
                "format": "json",
                "limit":  1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=5,
        )
        results = response.json()
        print(f"[Nominatim] Raw results: {results}")
        if not results:
            print(f"[Nominatim] No results for address: '{address}'")
            return None

        lat = float(results[0]["lat"])
        lng = float(results[0]["lon"])
        print(f"[Nominatim] Geocoded '{address}' → ({lat}, {lng})")
        return lat, lng

    except Exception as e:
        print(f"[Nominatim] Error: {e}")
        return None


def get_travel_time_minutes(customer_address: str) -> int:
    """
    Gets driving time from kitchen to customer using OSRM (free, no API key).
    Falls back to 20 mins if geocoding or routing fails.
    """
    if not customer_address:
        print("[OSRM] No address provided, skipping travel time.")
        return 0

    # Step 1 — Geocode the customer address
    coords = _geocode_address(customer_address)
    if not coords:
        print("[OSRM] Geocoding failed, defaulting to 20 mins.")
        return 20

    dest_lat, dest_lng = coords

    # Step 2 — Get driving duration from OSRM
    try:
        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{KITCHEN_LNG},{KITCHEN_LAT};{dest_lng},{dest_lat}"
            f"?overview=false"
        )
        response = requests.get(url, timeout=5)
        data     = response.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            print(f"[OSRM] Bad response: {data.get('code')}, defaulting to 20 mins.")
            return 20

        seconds     = data["routes"][0]["duration"]
        travel_mins = max(10, round(seconds / 60))
        print(f"[OSRM] Travel time to '{customer_address}': {travel_mins} mins")
        return travel_mins

    except Exception as e:
        print(f"[OSRM] Error: {e}, defaulting to 20 mins.")
        return 20


def calculate_full_eta(items: list, customer_address: str = None) -> dict:
    """
    Full ETA = Prep Time + Kitchen Queue Delay + Travel Time + Buffer (5 mins)

    If customer_address is None or empty, travel time is skipped.

    Returns:
        {
            "total": int,
            "breakdown": {
                "prep_time":   int,
                "queue_delay": int,
                "travel_time": int,
                "buffer":      int,
            }
        }
    """
    prep        = get_prep_time(items)
    queue_delay = get_kitchen_queue_delay()
    travel      = get_travel_time_minutes(customer_address) if customer_address else 0
    buffer      = 5

    total = prep + queue_delay + travel + buffer

    print(
        f"[ETA] prep={prep} | queue={queue_delay} | "
        f"travel={travel} | buffer={buffer} | total={total}"
    )

    return {
        "total": total,
        "breakdown": {
            "prep_time":   prep,
            "queue_delay": queue_delay,
            "travel_time": travel,
            "buffer":      buffer,
        },
    }