import requests
from services.db import get_prep_time, get_kitchen_queue_delay

# ── Kitchen coordinates ───────────────────────────────────────
KITCHEN_LAT = 13.010886
KITCHEN_LNG = 80.157838

USER_AGENT = "home-kitchen-delivery-app"

# ── Geocoding ─────────────────────────────────────────────────
def _geocode_address(address: str):
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": address,
                "format": "json",
                "limit": 1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=10,  # increased timeout
        )

        results = response.json()
        print(f"[Nominatim] Raw results: {results}")

        if not results:
            print(f"[Nominatim] ❌ No results for address: '{address}'")
            return None

        lat = float(results[0]["lat"])
        lng = float(results[0]["lon"])
        display_name = results[0].get("display_name", "N/A")

        print(f"[Nominatim] ✅ Matched: {display_name}")
        print(f"[Nominatim] Coordinates: ({lat}, {lng})")

        return lat, lng

    except Exception as e:
        print(f"[Nominatim] ❌ Error: {e}")
        return None


# ── Travel Time ────────────────────────────────────────────────
def get_travel_time_minutes(customer_address: str) -> int:
    if not customer_address:
        print("[OSRM] ⚠️ No address provided → travel time = 0")
        return 0

    coords = _geocode_address(customer_address)
    if not coords:
        print("[OSRM] ⚠️ Geocoding failed → fallback = 20 mins")
        return 20

    dest_lat, dest_lng = coords

    try:
        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{KITCHEN_LNG},{KITCHEN_LAT};{dest_lng},{dest_lat}"
            f"?overview=false"
        )

        response = requests.get(url, timeout=10)
        data = response.json()

        print(f"[OSRM] Raw response: {data}")

        if data.get("code") != "Ok" or not data.get("routes"):
            print("[OSRM] ❌ Invalid response → fallback = 20 mins")
            return 20

        seconds = data["routes"][0]["duration"]
        travel_mins = max(5, round(seconds / 60))  # reduced min to 5

        print(f"[OSRM] ✅ Travel time: {travel_mins} mins")

        return travel_mins

    except Exception as e:
        print(f"[OSRM] ❌ Error: {e} → fallback = 20 mins")
        return 20


# ── Full ETA ───────────────────────────────────────────────────
def calculate_full_eta(items: list, customer_address: str = None) -> dict:
    prep = get_prep_time(items)
    queue_delay = get_kitchen_queue_delay()
    travel = get_travel_time_minutes(customer_address) if customer_address else 0
    buffer = 5

    total = prep + queue_delay + travel + buffer

    print("\n[ETA BREAKDOWN]")
    print(f"Prep Time     : {prep} mins")
    print(f"Queue Delay   : {queue_delay} mins")
    print(f"Travel Time   : {travel} mins")
    print(f"Buffer        : {buffer} mins")
    print(f"TOTAL ETA     : {total} mins")

    return {
        "total": total,
        "breakdown": {
            "prep_time": prep,
            "queue_delay": queue_delay,
            "travel_time": travel,
            "buffer": buffer,
        },
    }


# ── TESTING FUNCTIONS ──────────────────────────────────────────
def test_travel_time():
    test_cases = [
        "T Nagar Chennai",
        "Anna Nagar Chennai",
        "Chennai",
        "random vague text",
        "",
    ]

    for address in test_cases:
        print("\n==============================")
        print(f"📍 Testing address: '{address}'")

        travel_time = get_travel_time_minutes(address)

        print(f"👉 Final Travel Time: {travel_time} mins")


def test_full_eta():
    items = ["dosa", "idli"]

    addresses = [
        "T Nagar Chennai",
        "random vague text"
    ]

    for addr in addresses:
        print("\n==============================")
        print(f"🚀 Testing FULL ETA for: '{addr}'")

        eta = calculate_full_eta(items, addr)

        print(f"👉 Final ETA Output: {eta}")


# ── MAIN ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n===== TRAVEL TIME TEST =====")
    test_travel_time()

    print("\n\n===== FULL ETA TEST =====")
    test_full_eta()