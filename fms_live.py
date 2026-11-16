"""Infinite Flight tracker formatting and Windows credential storage."""

import ctypes
import math
import os
import re
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile


class _DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]


def _protect(data: bytes, *, decrypt: bool = False) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.addressof(buffer))
    result = _DataBlob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    free = ctypes.windll.kernel32.LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        free(result.data)


def read_api_key(path: Path) -> str:
    try:
        return _protect(path.read_bytes(), decrypt=True).decode("utf-8").strip()
    except (OSError, UnicodeError, AttributeError):
        return ""


def write_api_key(path: Path, key: str) -> None:
    protected = _protect(key.encode("utf-8"))
    with NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        temporary_path = Path(temp.name)
        try:
            temp.write(protected)
            temp.close()
            os.replace(temporary_path, path)
        finally:
            temp.close()
            temporary_path.unlink(missing_ok=True)


def airport_code(*values) -> str:
    for value in values:
        if isinstance(value, dict):
            value = value.get("icao") or value.get("identifier")
        code = str(value or "").strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9]{3}", code):
            return code
    return ""


def flight_airports(flight: dict, plan: dict, first: str = "", last: str = "") -> tuple[str, str]:
    waypoints = plan.get("waypoints")
    names = waypoints if isinstance(waypoints, list) else []
    departure = airport_code(
        plan.get("originAirportIcao"), plan.get("originIcao"), flight.get("originAirportIcao"),
        flight.get("originAirport"), names[0] if names else "", first,
    )
    arrival = airport_code(
        plan.get("destinationAirportIcao"), plan.get("destinationIcao"), flight.get("destinationAirportIcao"),
        flight.get("destinationAirport"), names[-1] if len(names) > 1 else "", last,
    )
    return departure, arrival


def flight_timing(flight: dict, plan: dict, format_duration, *, remaining_nm=None, now=None):
    def value(*keys):
        for key in keys:
            for source in (flight, plan):
                candidate = source.get(key)
                if candidate is not None and candidate != "":
                    return candidate
        return None

    now = now or datetime.now(timezone.utc)

    def utc_time(raw):
        text = str(raw or "").strip()
        try:
            if re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", text):
                return datetime.strptime(text[:5], "%H:%M").strftime("%H:%M UTC")
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.year > 1:
                return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc).strftime("%H:%M UTC")
        except ValueError:
            pass
        return "—"

    etd = utc_time(value("estimatedDepartureUtc", "estimatedDepartureTime", "scheduledDepartureUtc", "departureTime", "etd"))
    arrival_time = value("estimatedArrivalUtc", "estimatedArrivalTime", "scheduledArrivalUtc", "arrivalTime", "eta")
    eta = utc_time(arrival_time)
    try:
        minutes = float(value("flightTimeMinutes", "estimatedFlightTimeMinutes", "durationMinutes"))
    except (TypeError, ValueError):
        minutes = 0
    duration = format_duration(minutes / 60) if math.isfinite(minutes) and 0 < minutes <= 14400 else "—"

    def positive_number(raw):
        try:
            number = float(raw)
            return number if math.isfinite(number) and number > 0 else None
        except (TypeError, ValueError):
            return None

    remaining = positive_number(value("eteMinutes", "estimatedTimeEnrouteMinutes", "remainingFlightTimeMinutes"))
    if remaining is None and eta != "—":
        raw = str(arrival_time).strip()
        if re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", raw):
            hour, minute = map(int, raw[:5].split(":"))
            minutes_to_arrival = ((hour * 60 + minute) - (now.hour * 60 + now.minute)) % 1440
            remaining = minutes_to_arrival
        else:
            instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            instant = instant.replace(tzinfo=instant.tzinfo or timezone.utc)
            remaining = max(0, (instant - now).total_seconds() / 60)
    speed = positive_number(flight.get("speed"))
    estimated = False
    if remaining is None and remaining_nm is not None and speed and speed >= 60 and flight.get("isOnGround") is not True:
        remaining = remaining_nm / speed * 60
        estimated = True
    ete = format_duration(remaining / 60) if remaining is not None and 0 <= remaining <= 14400 else "—"
    eta_estimated = False
    if eta == "—" and ete != "—":
        eta = (now + timedelta(minutes=remaining)).strftime("%H:%M UTC")
        eta_estimated = True
    return etd, eta, duration, ete, eta_estimated, estimated
