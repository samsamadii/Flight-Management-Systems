"""On-demand aviation catalogs and airport city imagery."""
import csv
from functools import lru_cache
import io
import json
import re
import threading
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen

AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OPENFLIGHTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/"
USER_AGENT = "FlightManagementSystems/13 (desktop flight simulator companion)"
_catalog_lock = {kind: threading.Lock() for kind in ("airport", "airline", "aircraft")}
_catalogs = {}


def request_text(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=8) as response:
        return response.read().decode("utf-8-sig")


def search_key(value):
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in text if char.isalnum())


def airport_catalog():
    for row in csv.DictReader(io.StringIO(request_text(AIRPORTS_URL))):
        if row["type"] == "closed":
            continue
        icao = row.get("icao_code") or row.get("gps_code") or ""
        code = icao or row["iata_code"] or row["ident"]
        yield {
            "id": row["id"], "code": code, "icao": icao, "iata": row["iata_code"],
            "name": row["name"], "city": row["municipality"], "country": row["iso_country"],
            "region_code": row.get("iso_region", ""),
            "lat": float(row["latitude_deg"]), "lon": float(row["longitude_deg"]),
            "elevation_ft": int(row["elevation_ft"]) if row["elevation_ft"] else None,
            "source_record": row,
        }


def airline_catalog():
    for row in csv.reader(io.StringIO(request_text(OPENFLIGHTS_URL + "airlines.dat"))):
        if len(row) != 8:
            continue
        identifier, name, alias, iata, icao, callsign, country, active = (
            "" if value == r"\N" else value for value in row
        )
        if name and name != "Unknown" and identifier != "-1":
            yield dict(id=identifier, name=name, alias=alias, iata=iata, icao=icao,
                       callsign=callsign, country=country, active=active == "Y")


def aircraft_catalog():
    manufacturers = (
        "British Aerospace", "de Havilland Canada", "de Havilland", "McDonnell Douglas",
        "Canadair Regional Jet", "Pilatus Britten-Norman", "Rockwell Commander",
    )
    for row in csv.reader(io.StringIO(request_text(OPENFLIGHTS_URL + "planes.dat"))):
        if len(row) != 3:
            continue
        name, iata, icao = ("" if value == r"\N" else value for value in row)
        if not name:
            continue
        manufacturer = next((m for m in manufacturers if name.startswith(m + " ")), name.split()[0])
        yield dict(id=icao or iata or name, name=name, iata=iata, icao=icao,
                   manufacturer=manufacturer)


def catalog(kind):
    with _catalog_lock[kind]:
        timestamp, records = _catalogs.get(kind, (0, ()))
        if time.monotonic() - timestamp < 21600 and records:
            return records
        loaders = {"airport": airport_catalog, "airline": airline_catalog, "aircraft": aircraft_catalog}
        try:
            fresh = tuple(loaders[kind]())
            if not fresh:
                raise ValueError(f"Empty {kind} catalog")
        except (OSError, ValueError, KeyError):
            if records:
                return records
            raise
        _catalogs[kind] = (time.monotonic(), fresh)
        return fresh


def search_catalog(kind, query, local_records=(), limit=8):
    needle = search_key(query)
    if len(needle) < 2:
        return [], False
    unavailable = False
    try:
        online = catalog(kind)
    except (OSError, ValueError, KeyError):
        online = ()
        unavailable = True

    ranked = []
    for record in (*online, *local_records):
        codes = [search_key(record.get(key)) for key in ("iata", "icao", "code")]
        names = [search_key(record.get(key)) for key in ("name", "city", "alias", "callsign", "manufacturer")]
        if needle in codes:
            rank = 0
        elif needle in names:
            rank = 1
        elif any(value.startswith(needle) for value in codes + names):
            rank = 2
        elif any(needle in value for value in names):
            rank = 3
        else:
            continue
        less_relevant = (
            record.get("source_record", {}).get("scheduled_service") != "yes"
            if kind == "airport" else not record.get("active", True)
        )
        ranked.append((rank, less_relevant, record))
    ranked.sort(key=lambda item: item[:2])

    results = []
    seen = set()
    for rank, _, record in ranked:
        if kind == "airport" and ranked[0][0] == 0 and rank != 0:
            break
        identity = record.get("code") if kind == "airport" else search_key(record["name"])
        if identity not in seen:
            results.append(record)
            seen.add(identity)
        if len(results) == limit:
            break
    return results, unavailable


@lru_cache(maxsize=128)
def city_image(city, country):
    if not city:
        return ""
    query = {
        "action": "query", "format": "json", "formatversion": 2,
        "titles": city, "redirects": 1, "prop": "pageimages|pageprops|coordinates",
        "ppprop": "disambiguation", "piprop": "thumbnail", "pithumbsize": 800,
    }
    api = "https://en.wikipedia.org/w/api.php?"
    pages = json.loads(request_text(api + urlencode(query))).get("query", {}).get("pages", [])
    for page in pages:
        if page.get("coordinates") and "disambiguation" not in page.get("pageprops", {}):
            image = page.get("thumbnail", {}).get("source")
            if image:
                return image

    query.pop("titles")
    query.update(generator="search", gsrsearch=f'"{city}" {country} city', gsrlimit=5, pilimit=5)
    pages = json.loads(request_text(api + urlencode(query))).get("query", {}).get("pages", [])
    for page in sorted(pages, key=lambda item: item.get("index", 99)):
        if search_key(city) in search_key(page.get("title")) and page.get("coordinates"):
            image = page.get("thumbnail", {}).get("source")
            if image and "disambiguation" not in page.get("pageprops", {}):
                return image
    return ""


def fetch_metar(icao):
    query = urlencode({"ids": icao, "format": "json"})
    payload = request_text("https://aviationweather.gov/api/data/metar?" + query)
    return next(iter(json.loads(payload or "[]")), {})


def metar_condition(report):
    weather = report.get("wxString") or ""
    for code, icon, label in (
        ("TS", "⛈️", "Thunderstorms"), ("SN", "❄️", "Snow"), ("FZ", "🌨️", "Freezing precipitation"),
        ("RA", "🌧️", "Rain"), ("DZ", "🌧️", "Drizzle"), ("FG", "🌫️", "Fog"),
        ("BR", "🌫️", "Mist"), ("HZ", "🌫️", "Haze"),
    ):
        if code in weather:
            return icon, label

    covers = {layer.get("cover") for layer in report.get("clouds") or []}
    for codes, icon, label in (
        ({"OVC", "VV"}, "☁️", "Overcast"), ({"BKN"}, "☁️", "Cloudy"),
        ({"SCT", "FEW"}, "⛅", "Partly cloudy"), ({"CLR", "SKC", "NSC", "NCD"}, "☀️", "Clear"),
    ):
        if covers & codes:
            return icon, label
    if re.search(r"\bCAVOK\b", report.get("rawOb") or ""):
        return "☀️", "Clear"
    return "🌡️", "Weather unavailable"
