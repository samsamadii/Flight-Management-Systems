
import flet as ft
import sys
from aviation_lookup import city_image, fetch_metar, metar_condition, search_catalog, search_key
from fms_cabin import SEAT_BLUE, SEAT_RED, SEAT_YELLOW, cabin_diagram, seat_artwork
from fms_live import flight_airports, flight_timing, read_api_key, write_api_key
from fms_interface import (
    CARD_RADIUS, CONTEXT_HEIGHT, CONTROL_RADIUS, DARK, GAP, LIGHT, NAV_HEIGHT, NAV_OPACITY, SHELL_HEIGHT, SURFACE_OPACITY,
    UI_FONT, UI_FONT_ASSET, airline_background, button_style, prepare_controls, surface_fill, with_hover,
)

# FMS Flet compatibility patch
# Keeps the app compatible across Flet desktop/web versions where helper APIs differ.
def _fms_padding(left=0, top=0, right=0, bottom=0):
    try:
        return ft.Padding(left=left, top=top, right=right, bottom=bottom)
    except TypeError:
        return ft.Padding(left, top, right, bottom)

def _fms_border_side(width=1, color=None):
    try:
        return ft.BorderSide(width=width, color=color)
    except TypeError:
        return ft.BorderSide(width, color)

def _fms_border_all(width=1, color=None):
    side = _fms_border_side(width, color)
    try:
        return ft.Border(left=side, top=side, right=side, bottom=side)
    except TypeError:
        return ft.Border(side, side, side, side)

def _fms_border_only(left=None, top=None, right=None, bottom=None):
    try:
        return ft.Border(left=left, top=top, right=right, bottom=bottom)
    except TypeError:
        return ft.Border(left, top, right, bottom)

def _fms_border_radius(top_left=0, top_right=0, bottom_left=0, bottom_right=0):
    try:
        return ft.BorderRadius(
            top_left=top_left,
            top_right=top_right,
            bottom_left=bottom_left,
            bottom_right=bottom_right,
        )
    except TypeError:
        return ft.BorderRadius(top_left, top_right, bottom_left, bottom_right)

if hasattr(ft, "padding"):
    if not hasattr(ft.padding, "only"):
        ft.padding.only = lambda left=0, top=0, right=0, bottom=0: _fms_padding(left, top, right, bottom)
    if not hasattr(ft.padding, "symmetric"):
        ft.padding.symmetric = lambda horizontal=0, vertical=0: _fms_padding(horizontal, vertical, horizontal, vertical)
    if not hasattr(ft.padding, "all"):
        ft.padding.all = lambda value=0: _fms_padding(value, value, value, value)

if hasattr(ft, "margin"):
    if not hasattr(ft.margin, "only"):
        ft.margin.only = lambda left=0, top=0, right=0, bottom=0: _fms_padding(left, top, right, bottom)
    if not hasattr(ft.margin, "symmetric"):
        ft.margin.symmetric = lambda horizontal=0, vertical=0: _fms_padding(horizontal, vertical, horizontal, vertical)
    if not hasattr(ft.margin, "all"):
        ft.margin.all = lambda value=0: _fms_padding(value, value, value, value)

if hasattr(ft, "border"):
    if not hasattr(ft.border, "all"):
        ft.border.all = _fms_border_all
    if not hasattr(ft.border, "only"):
        ft.border.only = _fms_border_only
    if not hasattr(ft.border, "BorderSide") and hasattr(ft, "BorderSide"):
        ft.border.BorderSide = ft.BorderSide

if hasattr(ft, "border_radius"):
    if not hasattr(ft.border_radius, "all"):
        ft.border_radius.all = lambda value=0: _fms_border_radius(value, value, value, value)
    if not hasattr(ft.border_radius, "only"):
        ft.border_radius.only = lambda top_left=0, top_right=0, bottom_left=0, bottom_right=0: _fms_border_radius(
            top_left,
            top_right,
            bottom_left,
            bottom_right,
        )
    if not hasattr(ft.border_radius, "vertical"):
        ft.border_radius.vertical = lambda top=0, bottom=0: _fms_border_radius(top, top, bottom, bottom)
    if not hasattr(ft.border_radius, "horizontal"):
        ft.border_radius.horizontal = lambda left=0, right=0: _fms_border_radius(left, right, left, right)

try:
    import flet_map as ftm
except ImportError:
    ftm = None
try:
    import flet_geolocator as ftg
except ImportError:
    ftg = None

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
import re
import subprocess
import shutil
import time
import ctypes
import threading
import urllib.error
import urllib.parse
import urllib.request
import asyncio
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from captain_announcements import (
    LANGUAGE_DISPLAY_LABELS,
    RTL_ANNOUNCEMENT_LANGUAGES,
    missing_native_language_for_airline,
    primary_languages_for_airline,
    render_announcement,
    supported_languages,
)

try:
    import pystray
    from PIL import Image as PILImage
except ImportError:
    pystray = None
    PILImage = None


def blend_hex_colors(base: str, tint: str, tint_weight: float) -> str:
    """Blend two six-digit colors while keeping theme calculations deterministic."""
    weight = max(0.0, min(float(tint_weight), 1.0))

    def channels(value: str) -> tuple[int, int, int]:
        clean = str(value or "").strip().lstrip("#")
        if len(clean) != 6:
            raise ValueError(f"Expected a six-digit hex color, got {value!r}")
        return tuple(int(clean[index:index + 2], 16) for index in (0, 2, 4))

    base_rgb = channels(base)
    tint_rgb = channels(tint)
    mixed = tuple(round(base_channel * (1.0 - weight) + tint_channel * weight) for base_channel, tint_channel in zip(base_rgb, tint_rgb))
    return "#" + "".join(f"{channel:02X}" for channel in mixed)


def relative_luminance(color: str) -> float:
    """Return WCAG relative luminance for a six-digit color."""
    clean = str(color or "").strip().lstrip("#")
    if len(clean) != 6:
        raise ValueError(f"Expected a six-digit hex color, got {color!r}")
    values = [int(clean[index:index + 2], 16) / 255.0 for index in (0, 2, 4)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def parse_landing_g(value) -> Optional[float]:
    raw = str(value).strip().replace(",", ".")
    if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", raw):
        return None
    number = float(raw)
    return number if 0 < number <= 2.6 else None


def landing_g_grade(value: float) -> tuple[str, str, str]:
    # Start each band at the next grade's lower bound to cover decimal gaps.
    if value < 1.1:
        return "Very smooth", "#12643B", "#DDF5E5"
    if value < 1.3:
        return "Smooth / Good", "#2E5C0C", "#EAF4D7"
    if value < 1.5:
        return "Regular / Standard", "#6E5000", "#FFF1C5"
    if value <= 1.8:
        return "Firm / Hard", "#893F09", "#FFE6CE"
    return "Very hard / Inspection limit", "#921F23", "#FDE1E0"


def contrast_ratio(foreground: str, background: str) -> float:
    lighter = max(relative_luminance(foreground), relative_luminance(background))
    darker = min(relative_luminance(foreground), relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


_FMS_SINGLE_INSTANCE_MUTEX = None
_FMS_SHOW_WINDOW_EVENT = None
_INTERFACE_PREVIEW = False
FMS_VERSION = "V14"
_PREVIEW_INSTANCE_ID = f"{FMS_VERSION}LiveTrackerPreview"
_PREVIEW_WINDOW_TITLE = f"FMS {FMS_VERSION} Live Tracker Preview"
DASHBOARD_DATE_HEIGHT = 55
DASHBOARD_ACTIONS_HEIGHT = 48
DASHBOARD_MAP_INSET = 6
DASHBOARD_MAP_WINDOW = "FMS Dashboard Airport Ground Map"
LIVE_MAP_WINDOW = "FMS OpenFreeMap Traffic"


def _acquire_fms_single_instance() -> bool:
    global _FMS_SINGLE_INSTANCE_MUTEX, _FMS_SHOW_WINDOW_EVENT
    if os.name != "nt":
        return True

    kernel32 = ctypes.windll.kernel32
    instance_id = _PREVIEW_INSTANCE_ID if _INTERFACE_PREVIEW else "V14Public"
    mutex_name = f"Local\\SamSamadi.FlightManagementSystems.{instance_id}.Instance"
    event_name = f"Local\\SamSamadi.FlightManagementSystems.{instance_id}.ShowWindow"
    mutex_handle = kernel32.CreateMutexW(None, False, mutex_name)
    already_running = kernel32.GetLastError() == 183
    show_event = kernel32.CreateEventW(None, False, False, event_name)

    if already_running:
        if show_event:
            kernel32.SetEvent(show_event)
            kernel32.CloseHandle(show_event)
        if mutex_handle:
            kernel32.CloseHandle(mutex_handle)
        return False

    _FMS_SINGLE_INSTANCE_MUTEX = mutex_handle
    _FMS_SHOW_WINDOW_EVENT = show_event
    return True

# MapTiler map style configuration.
# Set MAPTILER_API_KEY as an environment variable to enable these hosted tiles.
MAPTILER_API_KEY = os.environ.get("MAPTILER_API_KEY", "").strip()
MAPTILER_STYLES = {
    "dataviz-v4-dark": {
        "label": "Dark",
        # MapTiler raster tile URL. Do not include the old /256 segment here;
        # that can make some styles fail to render in flet-map.
        "url": "https://api.maptiler.com/maps/dataviz-v4-dark/{z}/{x}/{y}.png?key={key}",
        "attribution": "© MapTiler © OpenStreetMap contributors",
    },
}


def _enum_windows_by_title(title_fragment: str) -> List[int]:
    user32 = ctypes.windll.user32
    matches: List[int] = []
    needle = title_fragment.lower()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if needle in buffer.value.lower():
            matches.append(int(hwnd))
        return True

    user32.EnumWindows(enum_proc, 0)
    return matches


def _set_window_child_style(hwnd: int, *, visible=True):
    user32 = ctypes.windll.user32
    gwl_style = -16
    ws_child = 0x40000000
    ws_visible = 0x10000000
    ws_caption = 0x00C00000
    ws_thickframe = 0x00040000
    ws_popup = 0x80000000

    try:
        get_style = user32.GetWindowLongPtrW
        set_style = user32.SetWindowLongPtrW
    except AttributeError:
        get_style = user32.GetWindowLongW
        set_style = user32.SetWindowLongW

    style = int(get_style(hwnd, gwl_style))
    style = (style & ~(ws_popup | ws_caption | ws_thickframe | ws_visible)) | ws_child
    if visible:
        style |= ws_visible
    set_style(hwnd, gwl_style, style)


def _move_child_webview_to_content(parent_hwnd: int, child_hwnd: int, slot: str = "content"):
    user32 = ctypes.windll.user32

    class Rect(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    rect = Rect()
    user32.GetClientRect(parent_hwnd, ctypes.byref(rect))
    width = max(420, int(rect.right - rect.left))
    height = max(320, int(rect.bottom - rect.top))
    nav_width = 0
    dpi = user32.GetDpiForWindow(parent_hwnd)
    top_bar_height = round(SHELL_HEIGHT * (dpi or 96) / 96)
    if slot == "dashboard-airport":
        scale = (dpi or 96) / 96
        x = round((width + GAP * scale) / 2 + DASHBOARD_MAP_INSET * scale)
        y = round((SHELL_HEIGHT + 2 * GAP + DASHBOARD_DATE_HEIGHT + DASHBOARD_MAP_INSET) * scale)
        w = max(1, width - x - round((GAP + DASHBOARD_MAP_INSET) * scale))
        h = max(1, height - y - round((2 * GAP + DASHBOARD_ACTIONS_HEIGHT + DASHBOARD_MAP_INSET) * scale))
    elif slot == "live-map":
        x = 0
        y = top_bar_height
        w = max(1, rect.right - rect.left)
        h = max(1, rect.bottom - rect.top - y)
    elif slot == "overview-globe":
        dpi_scale = 1.0
        try:
            get_dpi_for_window = user32.GetDpiForWindow
            dpi_value = int(get_dpi_for_window(parent_hwnd) or 96)
            dpi_scale = max(1.0, dpi_value / 96.0)
        except Exception:
            dpi_scale = 1.0
        overview_padding = 18
        row_gap = 16
        live_card_width = 420
        live_card_height = 440
        webview_width = 400
        route_card_height = 360
        card_x = nav_width + overview_padding + 500 + row_gap + 500 + row_gap
        card_x = min(max(nav_width + overview_padding, card_x), max(nav_width + overview_padding, width - live_card_width - overview_padding))
        card_y = top_bar_height + 5 + overview_padding + route_card_height + row_gap
        card_y = min(max(top_bar_height + 5 + overview_padding, card_y), max(top_bar_height + 5 + overview_padding, height - live_card_height - overview_padding))
        x = card_x + max(0, (live_card_width - webview_width) // 2)
        y = card_y
        w = min(webview_width, max(320, width - x - overview_padding))
        h = min(live_card_height, max(300, height - y - overview_padding))
        w = int(w * dpi_scale)
        h = int(h * dpi_scale)
    else:
        x = nav_width
        y = top_bar_height
        w = max(420, width - nav_width)
        h = max(320, height - top_bar_height)
    user32.MoveWindow(child_hwnd, x, y, w, h, True)


def run_globe_webview_host(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="FMS embedded Globe.gl WebView2 host")
    parser.add_argument("--url", required=True)
    parser.add_argument("--parent-title", default="Flight Management Systems")
    parser.add_argument("--attach", action="store_true")
    parser.add_argument("--slot", default="content")
    parser.add_argument("--storage-path")
    parser.add_argument("--departure-file", type=Path)
    parser.add_argument("--live-map-bridge", type=Path)
    args = parser.parse_args(argv)
    dashboard_airport = args.slot == "dashboard-airport"
    live_map = args.slot == "live-map"
    embedded = dashboard_airport or live_map

    try:
        import webview
    except Exception as exc:
        print(f"Globe.gl WebView host failed to import pywebview: {exc}")
        return 2

    def attach_to_parent(window):
        if not args.attach:
            return
        if embedded:
            try:
                ready = window.events.loaded.wait(8) and window.evaluate_js(
                    "typeof window.updateLiveMap === 'function'" if live_map
                    else "typeof window.setDashboardDeparture === 'function'"
                )
            except Exception:
                ready = False
            if not ready:
                os._exit(2)
        user32 = ctypes.windll.user32
        parent_hwnd = 0
        for _ in range(80):
            matches = _enum_windows_by_title(args.parent_title)
            if matches:
                parent_hwnd = matches[0]
                break
            time.sleep(0.1)
        if not parent_hwnd:
            if embedded:
                os._exit(2)
            return

        child_hwnd = 0
        for _ in range(80):
            native = getattr(window, "native", None)
            handle = getattr(native, "Handle", None)
            if handle is not None:
                try:
                    child_hwnd = int(handle.ToInt64())
                except Exception:
                    try:
                        child_hwnd = int(handle.ToInt32())
                    except Exception:
                        child_hwnd = 0
            if child_hwnd:
                break
            time.sleep(0.1)
        if not child_hwnd:
            if embedded:
                os._exit(2)
            return

        _set_window_child_style(child_hwnd, visible=not embedded)
        user32.SetParent(child_hwnd, parent_hwnd)
        _move_child_webview_to_content(parent_hwnd, child_hwnd, args.slot)

        def keep_attached():
            last_departure = None
            last_snapshot = None
            while user32.IsWindow(parent_hwnd) and user32.IsWindow(child_hwnd):
                _move_child_webview_to_content(parent_hwnd, child_hwnd, args.slot)
                if dashboard_airport and args.departure_file:
                    try:
                        value = args.departure_file.read_bytes().decode("ascii")
                        if value != last_departure and re.fullmatch(r"(?:[A-Z]{4}|-)\n", value):
                            code = "" if value == "-\n" else value.strip()
                            window.evaluate_js(f"window.setDashboardDeparture({json.dumps(code)})")
                            last_departure = value
                    except (OSError, UnicodeError, webview.errors.WebViewException):
                        pass
                if live_map and args.live_map_bridge:
                    try:
                        snapshot = (args.live_map_bridge / "snapshot.json").read_text(encoding="utf-8")
                        if snapshot != last_snapshot:
                            window.evaluate_js(f"window.updateLiveMap({snapshot})")
                            last_snapshot = snapshot
                        action_path = args.live_map_bridge / "actions.json"
                        actions = window.evaluate_js("window.takeLiveMapActions()") if not action_path.exists() else []
                        if actions:
                            file = args.live_map_bridge / "actions.tmp"
                            file.write_text(json.dumps(actions), encoding="utf-8")
                            file.replace(action_path)
                    except (OSError, UnicodeError, webview.errors.WebViewException):
                        pass
                time.sleep(0.18)
            if embedded:
                os._exit(0)

        threading.Thread(target=keep_attached, daemon=True).start()

    window_kwargs = dict(
        title=LIVE_MAP_WINDOW if live_map else DASHBOARD_MAP_WINDOW if dashboard_airport else "FMS Globe.gl Route Globe",
        url=args.url,
        width=420 if args.slot == "overview-globe" else 1100,
        height=440 if args.slot == "overview-globe" else 720,
        min_size=(1, 1) if embedded else ((320, 300) if args.slot == "overview-globe" else (640, 420)),
        hidden=embedded,
        frameless=bool(args.attach),
        easy_drag=False,
        background_color="#00000000" if args.slot == "overview-globe" else "#020617",
        text_select=False,
        zoomable=not embedded,
    )
    try:
        window = webview.create_window(**window_kwargs)
    except Exception:
        window_kwargs["background_color"] = "#020617"
        window = webview.create_window(**window_kwargs)
    webview.start(
        attach_to_parent, args=(window,), gui="edgechromium", debug=False,
        private_mode=False, storage_path=args.storage_path,
    )
    return 0


AIRLINES = ['Air France',
 'American Airlines',
 'ANA',
 'British Airways',
 'Cathay Pacific',
 'Delta Air Lines',
 'Emirates',
 'Etihad Airways',
 'Generic',
 'Iran Air',
 'ITA Airways',
 'Lufthansa',
 'Mahan Air',
 'Qantas',
 'Qatar Airways',
 'Singapore Airlines',
 'Southwest Airlines',
 'Turkish Airlines',
 'United Airlines',
 'Virgin Atlantic']

AIRLINE_CALLSIGNS = {
    "Air France": "AF",
    "American Airlines": "AA",
    "ANA": "NH",
    "British Airways": "BA",
    "Cathay Pacific": "CX",
    "Delta Air Lines": "DL",
    "Emirates": "EK",
    "Etihad Airways": "EY",
    "Generic": "GEN",
    "Iran Air": "IR",
    "ITA Airways": "AZ",
    "Lufthansa": "LH",
    "Mahan Air": "W5",
    "Qantas": "QF",
    "Qatar Airways": "QR",
    "Singapore Airlines": "SQ",
    "Southwest Airlines": "WN",
    "Turkish Airlines": "TK",
    "United Airlines": "UA",
    "Virgin Atlantic": "VS",
}

AIRLINE_NAME_ALIASES = {
    "delta": "Delta Air Lines",
    "delta airlines": "Delta Air Lines",
}


def canonical_airline_name(name: Optional[str]) -> str:
    clean_name = re.sub(r"\s+", " ", str(name or "").strip())
    return AIRLINE_NAME_ALIASES.get(clean_name.lower(), clean_name)


AIRLINE_FLEETS = {
    # Matched to the aircraft/livery screenshot provided by the user.
    "Air France": [
        "Airbus A220-300",
        "Airbus A320-200",
        "Airbus A350-900",
        "Airbus A380-800",
        "Boeing 777-200ER",
        "Boeing 777-300ER",
        "Boeing 787-9",
        "Boeing 787-10",
    ],
    "ITA Airways": [
        "Airbus A220-300",
        "Airbus A320-200",
        "Airbus A321-200",
        "Airbus A321neo",
        "Airbus A330-900neo",
    ],
    "American Airlines": [
        "Airbus A321-200",
        "Airbus A321neo",
        "Boeing 737-8 MAX",
        "Boeing 777-200ER",
    ],
    "ANA": [
        "Airbus A321neo",
        "Boeing 777-200ER",
        "Boeing 777-300ER",
        "Boeing 787-10",
    ],
    "British Airways": [
        "Airbus A320-200",
        "Airbus A321-200",
        "Airbus A321neo",
        "Airbus A350-1000",
        "Airbus A380-800",
        "Boeing 777-200ER",
        "Boeing 777-300ER",
        "Boeing 787-9",
        "Boeing 787-10",
    ],
    "Cathay Pacific": [
        "Airbus A321neo",
        "Airbus A330-300",
        "Airbus A350-900",
        "Airbus A350-1000",
        "Boeing 777-300ER",
    ],
    "Delta Air Lines": [
        "Airbus A320-200",
        "Airbus A321-200",
        "Airbus A321neo",
        "Airbus A330-300",
        "Airbus A330-900neo",
        "Airbus A350-900",
        # Retired from Delta service in 2020; retained for the supplied simulator livery.
        "Boeing 777-200ER",
    ],
    "Emirates": [
        "Airbus A350-900",
        "Airbus A380-800",
        "Boeing 777-300ER",
    ],
    "Etihad Airways": [
        "Airbus A320-200",
        "Airbus A321neo",
        "Airbus A350-1000",
        "Airbus A380-800",
        "Boeing 777-300ER",
        "Boeing 787-9",
        "Boeing 787-10",
    ],
    "Generic": [
        "Airbus A220-300",
        "Airbus A320-200",
        "Airbus A321-200",
        "Airbus A321neo",
        "Airbus A330-300",
        "Airbus A330-900neo",
        "Airbus A340-600",
        "Airbus A350-900",
        "Airbus A350-1000",
        "Airbus A380-800",
        "Boeing 737-8 MAX",
        "Boeing 747-200",
        "Boeing 747-8",
        "Boeing 757-200",
        "Boeing 777-200ER",
        "Boeing 777-300ER",
        "Boeing 787-9",
        "Boeing 787-10",
    ],
    "Iran Air": [
        "Boeing 747-200",
    ],
    "Lufthansa": [
        "Airbus A320-200",
        "Airbus A321-200",
        "Airbus A321neo",
        "Airbus A330-300",
        "Airbus A340-600",
        "Airbus A350-900",
        "Airbus A350-900 (100 Years)",
        "Airbus A380-800",
        "Boeing 747-8",
        "Boeing 787-9",
    ],
    "Mahan Air": [
        "Airbus A340-600",
    ],
    "Qantas": [
        "Airbus A321neo",
        "Airbus A330-300",
        "Airbus A350-1000",
        "Airbus A380-800",
        "Boeing 787-9",
    ],
    "Qatar Airways": [
        "Airbus A350-1000",
        "Boeing 777-300ER",
    ],
    "Singapore Airlines": [
        "Airbus A330-300",
        "Airbus A350-900",
        "Airbus A380-800",
        "Boeing 737-8 MAX",
        "Boeing 777-300ER",
        "Boeing 787-10",
    ],
    "Southwest Airlines": [
        "Boeing 737-8 MAX",
    ],
    "Turkish Airlines": [
        "Airbus A320-200",
        "Airbus A321-200",
        "Airbus A321neo",
        "Airbus A330-300",
        "Airbus A350-900",
        "Boeing 777-300ER",
        "Boeing 787-9",
    ],
    "United Airlines": [
        "Airbus A321neo",
        "Airbus A350-900",
        "Boeing 737-8 MAX",
        "Boeing 777-200ER",
        "Boeing 777-300ER",
        "Boeing 787-9",
        "Boeing 787-10",
    ],
    "Virgin Atlantic": [
        "Airbus A330-900neo",
        "Airbus A350-1000",
        "Airbus A340-600",
    ],
}

AIRCRAFT_LIBRARY = {'A220-300': {'name': 'Airbus A220-300',
              'mtow': 77000,
              'oew': 42600,
              'mlw': 64500,
              'vr_speeds': {'1': 140, '2': 135, '3': 130},
              'v2_speeds': {'1': 150, '2': 145, '3': 140},
              'vref_speeds': {'FULL': 130, '3': 135},
              'flap_options': ['1', '2', '3'],
              'land_flaps': ['FULL', '3'],
              'base_roll': 2100,
              'land_roll': 1550,
              'engines': '2× Pratt & Whitney PW1500G',
              'fuel_burn': 1800,
              'max_alt': 39000,
              'climb_fpm': 2400,
              'approach_speed': 135,
              'notes': 'Planning default fuel flow updated from public ops references; engine fit refreshed.',
              'derived_payload_plus_fuel_at_mtow_kg': 34400,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 21900},
 'A320-200': {'name': 'Airbus A320-200',
              'mtow': 77000,
              'oew': 42600,
              'mlw': 64500,
              'vr_speeds': {'1': 140, '2': 135, '3': 130},
              'v2_speeds': {'1': 150, '2': 145, '3': 140},
              'vref_speeds': {'FULL': 130, '3': 135},
              'flap_options': ['1', '2', '3'],
              'land_flaps': ['FULL', '3'],
              'base_roll': 2100,
              'land_roll': 1550,
              'engines': '2× CFM56-5B / IAE V2500-A5',
              'fuel_burn': 2430,
              'max_alt': 39000,
              'climb_fpm': 2400,
              'approach_speed': 135,
              'derived_payload_plus_fuel_at_mtow_kg': 34400,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 21900},
 'A321-200': {'name': 'Airbus A321-200',
              'mtow': 93000,
              'oew': 49500,
              'mlw': 77000,
              'vr_speeds': {'1': 145, '2': 140, '3': 135},
              'v2_speeds': {'1': 155, '2': 150, '3': 145},
              'vref_speeds': {'FULL': 135, '3': 140},
              'flap_options': ['1', '2', '3'],
              'land_flaps': ['FULL', '3'],
              'base_roll': 2300,
              'land_roll': 1650,
              'engines': '2× CFM56-5B / IAE V2500-A5',
              'fuel_burn': 2740,
              'max_alt': 39000,
              'climb_fpm': 2400,
              'approach_speed': 140,
              'derived_payload_plus_fuel_at_mtow_kg': 43500,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 27500},
 'A321neo': {'name': 'Airbus A321neo',
             'mtow': 97000,
             'oew': 50700,
             'mlw': 79200,
             'vr_speeds': {'1+F': 154, '2': 150, '3': 146},
             'v2_speeds': {'1+F': 162, '2': 158, '3': 154},
             'takeoff_speed_reference_weight_ratio': 1.0,
             'takeoff_vr_floor_speeds': {'1+F': 128, '2': 126, '3': 124},
             'takeoff_v2_floor_speeds': {'1+F': 136, '2': 134, '3': 132},
             'takeoff_v1_max_gap_kt': 10,
             'vref_speeds': {'FULL': 137, '3': 142},
             'flap_options': ['1+F', '2', '3'],
             'land_flaps': ['FULL', '3'],
             'base_roll': 2200,
             'land_roll': 1600,
             'engines': '2× CFM LEAP-1A / Pratt & Whitney PW1100G-JM',
             'fuel_burn': 2500,
             'max_alt': 39000,
             'climb_fpm': 2400,
             'approach_speed': 140,
             'derived_payload_plus_fuel_at_mtow_kg': 46300,
             'derived_payload_plus_remaining_fuel_at_mlw_kg': 28500,
             'notes': 'Infinite Flight A321neo simulator planning profile. Weight limits follow the 97 t MTOW and '
                      '79.2 t MLW variant; V-speeds scale by weight and configuration and are not for real-world operations.'},
 'A330-200': {'name': 'Airbus A330-200',
              'mtow': 242000,
              'oew': 120000,
              'mlw': 182000,
              'vr_speeds': {'1+F': 153, '2': 149, '3': 146},
              'v2_speeds': {'1+F': 161, '2': 157, '3': 154},
              'takeoff_speed_reference_weight_ratio': 1.0,
              'takeoff_vr_floor_speeds': {'1+F': 130, '2': 128, '3': 126},
              'takeoff_v2_floor_speeds': {'1+F': 138, '2': 136, '3': 134},
              'takeoff_v1_max_gap_kt': 12,
              'vref_speeds': {'FULL': 135, '3': 140, '2': 145},
              'flap_options': ['1+F', '2', '3'],
              'land_flaps': ['FULL', '3', '2'],
              'base_roll': 2350,
              'land_roll': 1680,
              'engines': '2× GE CF6-80E1 / PW4000 / RR Trent 700',
              'fuel_burn': 5600,
              'max_alt': 41100,
              'climb_fpm': 2500,
              'approach_speed': 140,
              'derived_payload_plus_fuel_at_mtow_kg': 122000,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 62000,
              'notes': 'Infinite Flight A330-200 simulator planning profile. Takeoff speeds vary with weight and '
                       'configuration; not for real-world operations.'},
 'A330-300': {'name': 'Airbus A330-300',
              'mtow': 242000,
              'oew': 120000,
              'mlw': 185000,
              'vr_speeds': {'1+F': 154, '2': 150, '3': 147},
              'v2_speeds': {'1+F': 162, '2': 158, '3': 155},
              'takeoff_speed_reference_weight_ratio': 1.0,
              'takeoff_vr_floor_speeds': {'1+F': 130, '2': 128, '3': 126},
              'takeoff_v2_floor_speeds': {'1+F': 138, '2': 136, '3': 134},
              'takeoff_v1_max_gap_kt': 12,
              'vref_speeds': {'FULL': 135, '3': 140, '2': 145},
              'flap_options': ['1+F', '2', '3'],
              'land_flaps': ['FULL', '3', '2'],
              'base_roll': 2400,
              'land_roll': 1700,
              'engines': '2× GE CF6-80E1 / PW4000 / RR Trent 700',
              'fuel_burn': 5700,
              'max_alt': 41000,
              'climb_fpm': 2500,
              'approach_speed': 140,
              'derived_payload_plus_fuel_at_mtow_kg': 122000,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 65000,
              'notes': 'Infinite Flight A330-300 simulator planning profile. Approximately 150 kt VR at MTOW '
                       'in configuration 2; not for real-world operations.'},
 'A330-800': {'name': 'Airbus A330-800neo',
              'mtow': 251000,
              'oew': 132000,
              'mlw': 186000,
              'vr_speeds': {'1+F': 153, '2': 149, '3': 146},
              'v2_speeds': {'1+F': 161, '2': 157, '3': 154},
              'takeoff_speed_reference_weight_ratio': 1.0,
              'takeoff_vr_floor_speeds': {'1+F': 130, '2': 128, '3': 126},
              'takeoff_v2_floor_speeds': {'1+F': 138, '2': 136, '3': 134},
              'takeoff_v1_max_gap_kt': 12,
              'vref_speeds': {'FULL': 135, '3': 140, '2': 145},
              'flap_options': ['1+F', '2', '3'],
              'land_flaps': ['FULL', '3', '2'],
              'base_roll': 2350,
              'land_roll': 1680,
              'engines': '2× Rolls-Royce Trent 7000-72',
              'fuel_burn': 5000,
              'max_alt': 41000,
              'climb_fpm': 2500,
              'approach_speed': 140,
              'derived_payload_plus_fuel_at_mtow_kg': 119000,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 54000,
              'notes': 'Infinite Flight A330-800neo simulator planning profile. Takeoff speeds vary with weight and '
                       'configuration; not for real-world operations.'},
 'A330-900': {'name': 'Airbus A330-900neo',
              'mtow': 251000,
              'oew': 137000,
              'mlw': 185000,
              'vr_speeds': {'1+F': 154, '2': 150, '3': 147},
              'v2_speeds': {'1+F': 162, '2': 158, '3': 155},
              'takeoff_speed_reference_weight_ratio': 1.0,
              'takeoff_vr_floor_speeds': {'1+F': 130, '2': 128, '3': 126},
              'takeoff_v2_floor_speeds': {'1+F': 138, '2': 136, '3': 134},
              'takeoff_v1_max_gap_kt': 12,
              'vref_speeds': {'FULL': 135, '3': 140, '2': 145},
              'flap_options': ['1+F', '2', '3'],
              'land_flaps': ['FULL', '3', '2'],
              'base_roll': 2400,
              'land_roll': 1700,
              'engines': '2× Rolls-Royce Trent 7000-72',
              'fuel_burn': 5200,
              'max_alt': 41500,
              'climb_fpm': 2500,
              'approach_speed': 140,
              'derived_payload_plus_fuel_at_mtow_kg': 114000,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 48000,
              'notes': 'Infinite Flight A330-900neo simulator planning profile. Approximately 150 kt VR at MTOW '
                       'in configuration 2; not for real-world operations.'},
 'A340-600': {'name': 'Airbus A340-600',
              'mtow': 380000,
              'oew': 174000,
              'mlw': 259000,
              'vr_speeds': {'1+F': 150, '2': 145, '3': 140},
              'v2_speeds': {'1+F': 160, '2': 155, '3': 150},
              'vref_speeds': {'FULL': 135, '3': 140, '2': 145},
              'flap_options': ['1+F', '2', '3'],
              'land_flaps': ['FULL', '3', '2'],
              'base_roll': 3000,
              'land_roll': 2050,
              'engines': '4× Rolls-Royce Trent 556',
              'fuel_burn': 8100,
              'max_alt': 41000,
              'climb_fpm': 2300,
              'approach_speed': 150,
              'derived_payload_plus_fuel_at_mtow_kg': 206000,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 85000,
              'notes': 'Replaces A340-300. Weight limits use Airbus A340-500/-600 planning data; speeds/distances are '
                       'planning approximations.'},
 'A350-1000': {'name': 'Airbus A350-1000',
                'mtow': 322000,
                'oew': 155000,
                'mlw': 236000,
                'vr_speeds': {'1+F': 155, '2': 150, '3': 145},
                'v2_speeds': {'1+F': 165, '2': 160, '3': 155},
                'takeoff_speed_reference_weight_ratio': 0.85,
               'vref_speeds': {'FULL': 135, '3': 140, '2': 145},
               'flap_options': ['1+F', '2', '3'],
               'land_flaps': ['FULL', '3', '2'],
               'base_roll': 2600,
               'land_roll': 1800,
               'engines': '2× Rolls-Royce Trent XWB-97',
               'fuel_burn': 6500,
               'max_alt': 43000,
               'climb_fpm': 2600,
               'approach_speed': 145,
               'derived_payload_plus_fuel_at_mtow_kg': 167000,
               'derived_payload_plus_remaining_fuel_at_mlw_kg': 81000,
               'notes': 'Added as A350-1000 planning profile. Weight limits use Airbus A350-1000 published values; '
                        'speeds/distances are planning approximations.'},
 'A350-900': {'name': 'Airbus A350-900',
               'mtow': 280000,
               'oew': 142400,
               'mlw': 205000,
               'vr_speeds': {'1+F': 150, '2': 145, '3': 140},
               'v2_speeds': {'1+F': 160, '2': 155, '3': 150},
               'takeoff_speed_reference_weight_ratio': 0.85,
              'vref_speeds': {'FULL': 135, '3': 140, '2': 145},
              'flap_options': ['1+F', '2', '3'],
              'land_flaps': ['FULL', '3', '2'],
              'base_roll': 2480,
              'land_roll': 1700,
              'engines': '2× Rolls-Royce Trent XWB-84',
              'fuel_burn': 5800,
              'max_alt': 43000,
              'climb_fpm': 2600,
              'approach_speed': 140,
              'derived_payload_plus_fuel_at_mtow_kg': 137600,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 62600},
 'A380-800': {'name': 'Airbus A380-800',
               'mtow': 575000,
               'oew': 277000,
               'mlw': 394000,
               'vr_speeds': {'1+F': 165, '2': 160, '3': 155},
               'v2_speeds': {'1+F': 175, '2': 170, '3': 165},
               'takeoff_speed_reference_weight_ratio': 0.95,
              'vref_speeds': {'FULL': 150, '3': 155, '2': 160},
              'flap_options': ['1+F', '2', '3'],
              'land_flaps': ['FULL', '3', '2'],
              'base_roll': 3100,
              'land_roll': 2300,
              'engines': '4× Rolls-Royce Trent 900 / Engine Alliance GP7200',
              'fuel_burn': 11500,
              'max_alt': 43000,
              'climb_fpm': 2000,
              'approach_speed': 155,
              'derived_payload_plus_fuel_at_mtow_kg': 298000,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 117000},
 'B737-8MAX': {'name': 'Boeing 737-8 MAX',
                'mtow': 82190,
                'oew': 45100,
                'mlw': 69308,
                'vr_speeds': {'1': 145, '2': 140, '5': 135},
                'v2_speeds': {'1': 155, '2': 150, '5': 145},
                'takeoff_speed_reference_weight_ratio': 0.85,
               'vref_speeds': {'40': 135, '30': 140},
               'flap_options': ['1', '2', '5'],
               'land_flaps': ['40', '30'],
               'base_roll': 2200,
               'land_roll': 1550,
               'engines': '2× CFM LEAP-1B',
               'fuel_burn': 2300,
               'max_alt': 41000,
               'climb_fpm': 2500,
               'approach_speed': 138,
               'derived_payload_plus_fuel_at_mtow_kg': 37090,
               'derived_payload_plus_remaining_fuel_at_mlw_kg': 24208,
               'notes': 'Replaces Boeing 737-800. Weight limits use Boeing 737 MAX airport planning data for 737-8.'},
 'B747-8': {'name': 'Boeing 747-8',
            'mtow': 447700,
            'oew': 220000,
            'mlw': 346000,
            'vr_speeds': {'10': 170, '20': 165, '30': 160},
            'v2_speeds': {'10': 180, '20': 175, '30': 170},
            'vref_speeds': {'30': 155, '25': 160},
            'flap_options': ['10', '20', '30'],
            'land_flaps': ['30', '25'],
            'base_roll': 2900,
            'land_roll': 2100,
            'engines': '4× GEnx-2B67',
            'fuel_burn': 9600,
            'max_alt': 43000,
            'climb_fpm': 2000,
            'approach_speed': 160,
            'derived_payload_plus_fuel_at_mtow_kg': 227700,
            'derived_payload_plus_remaining_fuel_at_mlw_kg': 126000},
 'B747-200': {'name': 'Boeing 747-200',
              'mtow': 374850,
              'oew': 174000,
              'mlw': 285700,
              'vr_speeds': {'10': 166, '20': 162, '30': 158},
              'v2_speeds': {'10': 173, '20': 170, '30': 166},
              'vref_speeds': {'30': 155, '25': 160},
              'flap_options': ['10', '20', '30'],
              'land_flaps': ['30', '25'],
              'base_roll': 3200,
              'land_roll': 2195,
              'engines': '4× JT9D / CF6-50 / RB211',
              'fuel_burn': 13500,
              'max_alt': 45000,
              'climb_fpm': 1500,
              'approach_speed': 158,
              'derived_payload_plus_fuel_at_mtow_kg': 200850,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 111700,
              'notes': 'Added for Iran Air fleet. Planning values based on 747-200 public airport/specification references; not for real-world dispatch.'},
 'B757-200': {'name': 'Boeing 757-200',
              'mtow': 79000,
              'oew': 41400,
              'mlw': 66300,
              'vr_speeds': {'1': 145, '2': 140, '5': 135},
              'v2_speeds': {'1': 155, '2': 150, '5': 145},
              'vref_speeds': {'40': 135, '30': 140},
              'flap_options': ['1', '2', '5'],
              'land_flaps': ['40', '30'],
              'base_roll': 2250,
              'land_roll': 1600,
              'engines': '2× Rolls-Royce RB211-535E4 / Pratt & Whitney PW2037/2040',
              'fuel_burn': 3320,
              'max_alt': 41000,
              'climb_fpm': 2500,
              'approach_speed': 140,
              'notes': 'Planning default fuel flow updated from public ops references; engine fit refreshed.',
              'derived_payload_plus_fuel_at_mtow_kg': 37600,
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 24900},
 'B777-200ER': {'name': 'Boeing 777-200ER',
                 'mtow': 297550,
                 'oew': 141880,
                 'mlw': 213180,
                 'vr_speeds': {'5': 155, '15': 150, '20': 145},
                 'v2_speeds': {'5': 165, '15': 160, '20': 155},
                 'takeoff_speed_reference_weight_ratio': 0.85,
                 'vref_speeds': {'30': 139, '25': 144},
                 'flap_options': ['5', '15', '20'],
                 'land_flaps': ['30', '25'],
                 'base_roll': 2800,
                 'land_roll': 1615,
                 'engines': '2× GE90-94B / PW4090 / Rolls-Royce Trent 895',
                 'fuel_burn': 6800,
                 'max_alt': 43100,
                 'climb_fpm': 2500,
                 'approach_speed': 139,
                 'derived_payload_plus_fuel_at_mtow_kg': 155670,
                 'derived_payload_plus_remaining_fuel_at_mlw_kg': 71300,
                 'notes': 'Boeing 777-200ER simulator planning profile. Delta retired the type in 2020; '
                          'retained as a historical livery option and not for real-world operations.'},
 'B777-300ER': {'name': 'Boeing 777-300ER',
                 'mtow': 351500,
                 'oew': 167800,
                 'mlw': 251000,
                 'vr_speeds': {'5': 160, '15': 155, '20': 150},
                 'v2_speeds': {'5': 170, '15': 165, '20': 160},
                 'takeoff_speed_reference_weight_ratio': 0.85,
                'vref_speeds': {'30': 145, '25': 150},
                'flap_options': ['5', '15', '20'],
                'land_flaps': ['30', '25'],
                'base_roll': 2700,
                'land_roll': 1900,
                'engines': '2× GE90-115B',
                'fuel_burn': 7500,
                'max_alt': 43000,
                'climb_fpm': 2400,
                'approach_speed': 150,
                'derived_payload_plus_fuel_at_mtow_kg': 183700,
                'derived_payload_plus_remaining_fuel_at_mlw_kg': 83200},
 'B787-10': {'name': 'Boeing 787-10',
             'mtow': 254011,
             'oew': 135500,
             'mlw': 201848,
             'vr_speeds': {'5': 160, '15': 155, '20': 150},
             'v2_speeds': {'5': 170, '15': 165, '20': 160},
             'vref_speeds': {'30': 145, '25': 150},
             'flap_options': ['5', '15', '20'],
             'land_flaps': ['30', '25'],
             'base_roll': 2800,
             'land_roll': 1850,
             'engines': '2× GEnx-1B / Rolls-Royce Trent 1000',
             'fuel_burn': 5900,
             'max_alt': 43000,
             'climb_fpm': 2400,
             'approach_speed': 150,
             'notes': 'Added as 787-10 planning profile. MTOW/MLW/OEW use published 787-10 planning/specification '
                      'values; speeds/distances are planning approximations.',
             'derived_payload_plus_fuel_at_mtow_kg': 118511,
             'derived_payload_plus_remaining_fuel_at_mlw_kg': 66348},
 'B787-9': {'name': 'Boeing 787-9',
            'mtow': 351500,
            'oew': 167800,
            'mlw': 251000,
            'vr_speeds': {'5': 160, '15': 155, '20': 150},
            'v2_speeds': {'5': 170, '15': 165, '20': 160},
            'vref_speeds': {'30': 145, '25': 150},
            'flap_options': ['5', '15', '20'],
            'land_flaps': ['30', '25'],
            'base_roll': 2700,
            'land_roll': 1900,
            'engines': '2× GEnx-1B / Trent 1000',
            'fuel_burn': 5600,
            'max_alt': 43000,
            'climb_fpm': 2400,
            'approach_speed': 150,
            'notes': 'Planning default fuel flow updated from public ops references; engine fit refreshed.',
            'derived_payload_plus_fuel_at_mtow_kg': 183700,
            'derived_payload_plus_remaining_fuel_at_mlw_kg': 83200}}

# Keep the anniversary aircraft operationally identical to the regular A350-900,
# while exposing it as a distinct selectable livery in the Lufthansa fleet.
AIRCRAFT_LIBRARY["A350-900-LH100"] = {
    **AIRCRAFT_LIBRARY["A350-900"],
    "name": "Airbus A350-900 (100 Years)",
}

AIRCRAFT_NAME_ALIASES = {'airbus a220-300': 'A220-300',
 'airbus a320-200': 'A320-200',
 'airbus a320': 'A320-200',
 'airbus a320neo': 'A320-200',
 'airbus a321-200': 'A321-200',
 'airbus a321': 'A321-200',
 'airbus a321neo': 'A321neo',
 'airbus a330-200': 'A330-200',
 'airbus a330-300': 'A330-300',
 'airbus a330-800': 'A330-800',
 'airbus a330-800neo': 'A330-800',
 'airbus a330-800 neo': 'A330-800',
 'airbus a330-900': 'A330-900',
 'airbus a330-900neo': 'A330-900',
 'airbus a330-900 neo': 'A330-900',
 'airbus a340-300': 'A340-600',
 'airbus a350-900': 'A350-900',
 'airbus a350-900 (100 years)': 'A350-900-LH100',
 'a350-900-lh100': 'A350-900-LH100',
 'airbus a380-800': 'A380-800',
 'boeing 737-800': 'B737-8MAX',
 'boeing 737 max 8': 'B737-8MAX',
 'boeing 737-900er': 'B737-8MAX',
 'boeing 747-8': 'B747-8',
 'boeing 747-200': 'B747-200',
 '747-200': 'B747-200',
 'boeing 757-200': 'B757-200',
 'boeing 757-300': 'B757-200',
 'boeing 767-300er': 'B757-200',
 'boeing 777-300': 'B777-300ER',
 'boeing 777-300er': 'B777-300ER',
 'boeing 777-200er': 'B777-200ER',
 'boeing 787-8': 'B787-9',
 'boeing 787-9': 'B787-9',
 'boeing 787-10': 'B787-10',
 'embraer 190': 'A220-300',
 'embraer 175': 'A220-300',
 'airbus a321 neo': 'A321neo',
 'a321neo': 'A321neo',
 'airbus a340-600': 'A340-600',
 'a340-600': 'A340-600',
 'airbus a350-1000': 'A350-1000',
 'a350-1000': 'A350-1000',
 'boeing 737-8 max': 'B737-8MAX',
 'boeing 737-8': 'B737-8MAX',
 'b737-8max': 'B737-8MAX',
 'b787-10': 'B787-10',
 'airbus a350-1000': 'A350-1000',
 'airbus a321 neo': 'A321neo',
 'boeing 787-10': 'B787-10',
 'boeing 737-8 max': 'B737-8MAX'}

def canonical_aircraft_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    raw = str(name).strip()
    if raw in AIRCRAFT_LIBRARY:
        return raw
    alias = AIRCRAFT_NAME_ALIASES.get(raw.lower())
    if alias:
        return alias
    for candidate in AIRCRAFT_LIBRARY:
        if candidate.lower() == raw.lower():
            return candidate
    return None


def get_library_aircraft(name: Optional[str]) -> Optional[dict]:
    key = canonical_aircraft_name(name)
    return AIRCRAFT_LIBRARY.get(key) if key else None


def all_library_aircraft_names() -> List[str]:
    return list(AIRCRAFT_LIBRARY.keys())


def aircraft_picker_sort_key(aircraft_key: str) -> tuple[int, int, str]:
    """Order aircraft in the picker by manufacturer and family/model, not raw dictionary order."""
    aircraft = AIRCRAFT_LIBRARY.get(aircraft_key, {})
    display = str(aircraft.get("name", aircraft_key))
    lower = display.lower()
    manufacturer_order = 0 if lower.startswith("airbus") else 1 if lower.startswith("boeing") else 2
    model_order = {
        "A220-300": 10,
        "A320-200": 20,
        "A321-200": 30,
        "A321neo": 31,
        "A330-200": 40,
        "A330-300": 41,
        "A330-800": 42,
        "A330-900": 43,
        "A340-600": 50,
        "A350-900": 60,
        "A350-1000": 61,
        "A380-800": 70,
        "B737-8MAX": 110,
        "B747-8": 120,
        "B747-200": 121,
        "B757-200": 130,
        "B777-200ER": 139,
        "B777-300ER": 140,
        "B787-9": 150,
        "B787-10": 151,
    }.get(aircraft_key, 999)
    return (manufacturer_order, model_order, display)



def audit_aircraft_database_links() -> Dict[str, List[str]]:
    """Checks that every aircraft shown in airline dropdowns resolves into the app databases.

    This is a lightweight internal audit helper for development. It does not
    block runtime behavior. It only reports missing or weak links so future
    aircraft additions do not break fuel, speed, seat, or livery features.
    """
    report: Dict[str, List[str]] = {
        "fleet_aircraft_without_library_key": [],
        "library_aircraft_without_route_fuel": [],
        "library_aircraft_without_livery_slug": [],
        "library_aircraft_without_fuel_burn": [],
        "library_aircraft_without_takeoff_speed_tables": [],
        "library_aircraft_without_landing_speed_tables": [],
        "library_aircraft_using_seat_fallback": [],
    }

    for airline, fleet in AIRLINE_FLEETS.items():
        for aircraft_label in fleet:
            if canonical_aircraft_name(aircraft_label) is None:
                report["fleet_aircraft_without_library_key"].append(f"{airline}: {aircraft_label}")

    for aircraft_key, aircraft in AIRCRAFT_LIBRARY.items():
        if aircraft_key not in ROUTE_FUEL_DATABASE and resolve_route_fuel_aircraft(aircraft_key) is None:
            report["library_aircraft_without_route_fuel"].append(aircraft_key)

        if aircraft_key not in AIRCRAFT_LIVERY_SLUGS:
            report["library_aircraft_without_livery_slug"].append(aircraft_key)

        if not aircraft.get("fuel_burn"):
            report["library_aircraft_without_fuel_burn"].append(aircraft_key)

        if not aircraft.get("vr_speeds") or not aircraft.get("v2_speeds") or not aircraft.get("flap_options"):
            report["library_aircraft_without_takeoff_speed_tables"].append(aircraft_key)

        if not aircraft.get("vref_speeds") or not aircraft.get("land_flaps"):
            report["library_aircraft_without_landing_speed_tables"].append(aircraft_key)

        aircraft_display_name = str(aircraft.get("name", aircraft_key))
        if aircraft_display_name not in AIRCRAFT_SEAT_PRESETS:
            report["library_aircraft_using_seat_fallback"].append(aircraft_key)

    speed_report = audit_aircraft_speed_tables()
    for key, values in speed_report.items():
        if values:
            report[key] = values
    return report


AIRLINE_LOGO_FILES = {'ANA': 'airlines/logos/ana.png',
 'Air France': 'airlines/logos/air_france.png',
 'American Airlines': 'airlines/logos/american_airlines.png',
 'British Airways': 'airlines/logos/british_airways.png',
 'Cathay Pacific': 'airlines/logos/cathay_pacific.png',
 'Delta Air Lines': 'airlines/logos/delta_air_lines.png',
 'Emirates': 'airlines/logos/emirates.png',
 'Etihad Airways': 'airlines/logos/etihad_airways.webp',
 'Generic': 'airlines/logos/generic.png',
 'ITA Airways': 'airlines/logos/ita_airways.png',
 'Iran Air': 'airlines/logos/iran_air.png',
 'Lufthansa': 'airlines/logos/lufthansa.png',
 'Mahan Air': 'airlines/logos/mahan_air.webp',
 'Qantas': 'airlines/logos/qantas.webp',
 'Qatar Airways': 'airlines/logos/qatar_airways.png',
 'Singapore Airlines': 'airlines/logos/singapore_airlines.png',
 'Southwest Airlines': 'airlines/logos/southwest_airlines.png',
 'Turkish Airlines': 'airlines/logos/turkish_airlines.png',
 'United Airlines': 'airlines/logos/united_airlines.png',
 'Virgin Atlantic': 'airlines/logos/virgin_atlantic.png'}

AIRLINE_LOGO_ALTERNATE_FILES = {
    'American Airlines': ['american_airlines.png', 'american.png', 'aa.png'],
    'British Airways': ['british_airways.png', 'british.png', 'ba.png'],
    'Delta Air Lines': ['delta_air_lines.png', 'delta.png', 'dl.png'],
    'Etihad Airways': ['etihad_airways.webp', 'etihad_airways.png', 'etihad.png', 'ey.png'],
    'ITA Airways': ['ita_airways.png', 'ita.png'],
    'Singapore Airlines': ['singapore_airlines.png', 'singapore.png', 'sia.png'],
    'Turkish Airlines': ['turkish_airlines.png', 'turkish.png', 'thy.png'],
    'United Airlines': ['united_airlines.png', 'united.png'],
    'Virgin Atlantic': ['virgin_atlantic.png', 'virgin.png'],
    'Iran Air': ['iran_air.png', 'iranair.png'],
    'Mahan Air': ['mahan_air.webp', 'mahan_air.png', 'mahan.png', 'w5.png'],
    'Qantas': ['qantas.webp', 'qantas.png', 'qf.png'],
    'Qatar Airways': ['qatar_airways.png', 'qatar.png'],
    'Southwest Airlines': ['southwest_airlines.png', 'southwest.png'],
}

MANUFACTURER_LOGO_FILES = {
    "Airbus": "aircraft/manufacturers/airbus.png",
    "Boeing": "aircraft/manufacturers/boeing.png",
}

MANUFACTURER_LOGO_ALTERNATE_FILES = {
    "Airbus": ["airbus.png", "airbus_logo.png"],
    "Boeing": ["boeing.png", "boeing_logo.png"],
}

WEATHER_CODE_LABELS = {
    0: "Sunny",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Cloudy",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Rain showers",
    82: "Heavy showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm",
    99: "Thunderstorm",
}


CHECKLIST_SECTIONS = [
    {
        "key": "turn_on_aircraft",
        "title": "Turn On Aircraft",
        "items": [
            ("Batteries 1 & 2", "ON"),
            ("External Power", "ON (if available)"),
            ("ADIRS Switches", "NAV"),
            ("APU Master", "ON"),
            ("APU Start", "ON"),
            ("APU Bleed", "ON"),
            ("NAV Lights", "ON"),
            ("No portable devices sign", "ON"),
            ("Seatbelts", "ON"),
        ],
    },
    {
        "key": "start_engines",
        "title": "Start Engines",
        "items": [
            ("Beacon Light", "ON"),
            ("Fuel Pumps", "ON"),
            ("Engine Mode Selector", "IGN / START"),
            ("Engine 1 Master", "ON"),
            ("Engine 1", "STABLE"),
            ("Engine 2 Master", "ON"),
            ("Engine 2", "STABLE"),
            ("Engine Mode Selector", "NORM"),
            ("APU Bleed", "OFF"),
            ("APU Master", "OFF"),
            ("Taxi Light", "ON"),
        ],
    },
    {
        "key": "before_takeoff",
        "title": "Before Takeoff",
        "items": [
            ("Flight Controls", "CHECK"),
            ("Flight Instruments", "CHECK"),
            ("Trim", "AS REQUIRED"),
            ("Autobrake", "MAX"),
            ("Spoilers", "ARM"),
            ("Flaps", "SET"),
            ("Strobe Lights", "ON"),
            ("Landing Lights", "ON"),
        ],
    },
    {
        "key": "after_takeoff",
        "title": "After Takeoff",
        "items": [
            ("Gear", "UP"),
            ("Flaps", "RETRACTED"),
            ("Spoilers", "DISARM"),
            ("Taxi Light", "OFF"),
        ],
    },
    {
        "key": "climb_out",
        "title": "Climb-out",
        "items": [
            ("Autopilot", "AS REQUIRED"),
            ("Landing Lights", "OFF (10,000 ft)"),
            ("Seatbelts", "OFF (above 10,000 ft)"),
        ],
    },
    {
        "key": "landing",
        "title": "Landing",
        "items": [
            ("Seatbelts", "ON"),
            ("Landing Lights", "ON (10,000 ft)"),
            ("Autobrake", "SET"),
            ("Flaps", "SET"),
            ("Landing Gear", "DOWN"),
            ("Spoilers", "ARM"),
        ],
    },
    {
        "key": "after_landing",
        "title": "After Landing",
        "items": [
            ("Spoilers", "DISARM"),
            ("Flaps", "RETRACT"),
            ("Landing Lights", "OFF"),
            ("Strobe Lights", "OFF"),
            ("Taxi Light", "ON"),
            ("APU Master", "ON"),
            ("Brake Temp", "CHECK"),
            ("Brake Fans", "AS REQUIRED"),
            ("APU Start", "ON"),
            ("APU Bleed", "ON"),
        ],
    },
    {
        "key": "shutdown_aircraft",
        "title": "Shutdown Aircraft",
        "items": [
            ("Taxi Light", "OFF"),
            ("Parking Brake", "SET"),
            ("Thrust Levers", "IDLE"),
            ("Engine 1 Master", "OFF"),
            ("Engine 2 Master", "OFF"),
            ("Beacon Light", "OFF"),
            ("Seatbelts", "OFF"),
            ("Fuel Pumps", "OFF"),
            ("External Power", "ON (if available)"),
            ("ADIRS", "OFF"),
            ("Brake Fans", "OFF"),
            ("APU Bleed", "OFF"),
            ("APU Master", "OFF"),
            ("NAV Lights", "OFF"),
            ("External Power", "OFF"),
            ("Battery 1 & 2", "OFF"),
        ],
    },
]


@dataclass
class WeatherState:
    temperature_c: Optional[float] = None
    condition: str = "—"
    icon: str = "📍"


@dataclass
class AppState:
    is_logged_in: bool = True
    pilot_name: str = "Pilot"
    profile_member_since: str = ""
    location_label: str = "Unknown"
    weather: WeatherState = field(default_factory=WeatherState)
    airline: str = ""
    selected_tab_index: int = 1
    display_mode: str = "daylight"
    display_brightness: float = 1.0
    display_contrast: float = 1.0
    airline_overlay_opacity: float = 0.50
    payload_view: str = "seats"
    custom_airlines: List[str] = field(default_factory=list)
    default_fuel_unit: str = "kg"
    default_distance_unit: str = "NM"
    default_temperature_unit: str = "°C"
    banner_animation_enabled: bool = False
    low_performance_mode: bool = False
    professional_info_enabled: bool = False
    app_volume: float = 0.85
    app_muted: bool = False
    aircraft: str = ""
    airline_record: dict = field(default_factory=dict)
    aircraft_record: dict = field(default_factory=dict)
    flight_number: str = ""
    dashboard_flight_plan: Dict[str, str] = field(default_factory=dict)
    tutorial_seen: set[str] = field(default_factory=set)
    tutorial_skipped: bool = False
    departure: str = ""
    arrival: str = ""
    departure_gate: str = ""
    arrival_gate: str = ""
    departure_terminal: str = ""
    arrival_terminal: str = ""
    boarding_status: str = "Not started"
    cargo_status: str = "Not started"
    catering_status: str = "Not started"
    flight_status: str = "Select an airline"
    overview_flight_status_index: int = 0
    overview_flight_time_minutes: int = 0  # Flight Plan override in minutes.
    overview_takeoff_start_timestamp: Optional[float] = None
    overview_locked_eta_timestamp: Optional[float] = None
    overview_progress_running: bool = False
    overview_paused_elapsed_seconds: Optional[float] = None
    overview_calendar_completion_key: str = ""
    flight_hibernation_prompt_seen: bool = False
    captain_announcement_language: str = "English"
    captain_announcement_phase: str = "departure"
    captain_announcement_text: str = ""
    captain_departure_announcement_text: str = ""
    captain_descent_announcement_text: str = ""
    captain_announcement_cruise_altitude_ft: str = ""
    captain_announcement_current_altitude_ft: str = ""
    captain_announcement_generating: bool = False
    takeoff_announcement_expanded: bool = False
    descent_announcement_expanded: bool = False
    takeoff_operations_view: str = "menu"
    landing_operations_view: str = "menu"
    checklist_section: str = "turn_on_aircraft"
    checklist_completed: Dict[str, List[int]] = field(default_factory=dict)
    takeoff_clock_source: str = "route"
    landing_clock_source: str = "route"
    takeoff_clock_menu_open: bool = False
    landing_clock_menu_open: bool = False
    route_distance_override_nm: Optional[float] = None
    route_distance_override_key: str = ""
    ramp_status_phase: str = "departure"
    ramp_departure_statuses: Dict[str, str] = field(default_factory=dict)
    ramp_arrival_statuses: Dict[str, str] = field(default_factory=dict)
    map_style: str = "dataviz-v4-dark"
    takeoff_last_result: Dict[str, object] = field(default_factory=dict)
    landing_last_result: Dict[str, object] = field(default_factory=dict)
    location_permission_enabled: bool = False
    logo_refresh_nonce: int = 0
    calendar_entries: List[dict] = field(default_factory=list)
    calendar_editing_id: Optional[str] = None
    calendar_selected_date: str = ""
    log_expanded_id: Optional[str] = None
    profile_image_path: str = ""
    if_selected_session_id: str = ""
    if_selected_session_name: str = ""
    if_sessions: List[dict] = field(default_factory=list)
    if_selected_flight: Dict[str, object] = field(default_factory=dict)
    if_selected_flight_plan: Dict[str, object] = field(default_factory=dict)
    if_live_flights: List[dict] = field(default_factory=list)
    if_selected_route_points: List[tuple] = field(default_factory=list)
    if_selected_route_start_label: str = ""
    if_selected_route_end_label: str = ""
    if_last_traffic_refresh: str = "Never"
    overview_live: bool = False
    if_followed_flight_id: str = ""
    if_last_live_refresh_attempt: float = 0.0
    if_traffic_retry_at: float = 0.0
    if_atc_session: str = ""
    if_atc_checked_at: float = 0.0
    if_atc_markers: list = field(default_factory=list)
    if_traffic_session: str = ""
    if_cache: Dict[str, dict] = field(default_factory=dict)
    if_last_error: str = ""
    if_last_activity_timestamp: float = 0.0
    if_polling_paused: bool = False
    page_backgrounds: Dict[str, Optional[str]] = field(default_factory=lambda: {
        "OVERVIEW": "backgrounds/map_bg.jpg",
        "HOME": "backgrounds/home_bg.jpg",
        "TAKEOFF": "backgrounds/takeoff_bg.jpg",
        "LANDING": "backgrounds/landing_bg.jpg",
        "SEATS": "backgrounds/seats_bg.jpg",
        "CALENDAR": "backgrounds/calendar_bg.jpg",
        "LOG": "backgrounds/log_bg.jpg",
        "BAGGAGE": "backgrounds/baggage_bg.jpg",
        "PROFILE": "backgrounds/profile_bg.jpg",
        "ABOUT": "backgrounds/profile_bg.jpg",
    })


BAGGAGE_STANDARD_DEFAULTS = {
    "Domestic": 11.0,
    "Within the European region": 13.0,
    "Intercontinental": 15.0,
    "All other": 13.0,
}


@dataclass
class Result:
    passengers: int
    pax_two_bags: int
    pax_one_bag: int
    total_checked_bags: int
    carry_on_total_kg: float
    checked_total_kg: float
    total_baggage_kg: float


def estimate_standard_mode(
    passengers: int,
    carry_on_kg_per_pax: float,
    checked_kg_per_pax: float,
) -> Result:
    carry_on_total = passengers * carry_on_kg_per_pax
    checked_total = passengers * checked_kg_per_pax
    return Result(
        passengers=passengers,
        pax_two_bags=0,
        pax_one_bag=0,
        total_checked_bags=0,
        carry_on_total_kg=carry_on_total,
        checked_total_kg=checked_total,
        total_baggage_kg=carry_on_total + checked_total,
    )


def estimate_allowance_mode(
    passengers: int,
    pct_two_checked_bags: float,
    carry_on_kg_per_pax: float,
    per_checked_bag_kg: float,
) -> Result:
    pct_two_checked_bags = max(0.0, min(100.0, pct_two_checked_bags))
    pax_two = round(passengers * (pct_two_checked_bags / 100.0))
    pax_one = passengers - pax_two
    total_checked_bags = pax_two * 2 + pax_one
    carry_on_total = passengers * carry_on_kg_per_pax
    checked_total = total_checked_bags * per_checked_bag_kg

    return Result(
        passengers=passengers,
        pax_two_bags=pax_two,
        pax_one_bag=pax_one,
        total_checked_bags=total_checked_bags,
        carry_on_total_kg=carry_on_total,
        checked_total_kg=checked_total,
        total_baggage_kg=carry_on_total + checked_total,
    )


KTS_TO_MPS = 0.514444
MPS_TO_KTS = 1.943844
FT_TO_M = 0.3048
G = 9.81


# Populated only by selected airports, restored flights and legacy route lookups.
AIRPORT_LIBRARY: dict[str, dict] = {}
AIRPORT_CODE_ALIASES = {"IKH": "OIIE"}


def remember_airport(record: dict):
    code = record["code"]
    AIRPORT_LIBRARY[code] = record
    if record.get("iata"):
        AIRPORT_CODE_ALIASES[record["iata"]] = code


def normalize_airport_code(code: Optional[str]) -> Optional[str]:
    raw = (code or "").strip().upper()
    if not raw:
        return None
    return AIRPORT_CODE_ALIASES.get(raw, raw)


def lookup_airport_record(code: Optional[str]) -> Optional[dict]:
    canonical = normalize_airport_code(code)
    return AIRPORT_LIBRARY.get(canonical) if canonical else None


def resolve_airport_coordinates(code: str) -> Optional[tuple[float, float]]:
    record = lookup_airport_record(code)
    if not record:
        return None
    return float(record["lat"]), float(record["lon"])


def great_circle_distance_nm_points(origin: tuple[float, float], destination: tuple[float, float]) -> float:
    lat1, lon1 = origin
    lat2, lon2 = destination
    r_nm = 3440.065
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return r_nm * c


def route_distance_nm_for_icaos(origin_code: str, destination_code: str) -> Optional[float]:
    origin = resolve_airport_coordinates(origin_code)
    destination = resolve_airport_coordinates(destination_code)
    if not origin or not destination:
        return None
    return great_circle_distance_nm_points(origin, destination)


def format_hours_to_hm(hours: float) -> str:
    total_minutes = max(0, int(round(hours * 60)))
    hrs, mins = divmod(total_minutes, 60)
    return f"{hrs}h {mins:02d}m"


def great_circle_distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_nm = 3440.065
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(1 - a, 0)))
    return r_nm * c


def route_distance_nm(origin_code: str, destination_code: str) -> Optional[float]:
    origin = resolve_airport_coordinates(origin_code)
    dest = resolve_airport_coordinates(destination_code)
    if not origin or not dest:
        return None
    return great_circle_distance_nm(origin[0], origin[1], dest[0], dest[1])



TAKEOFF_SURFACE_FACTORS = {
    "DRY": 1.00,
    "WET": 1.15,
    "CONTAMINATED": 1.35,
    "SNOW": 1.50,
    "ICE": 1.70,
}

LANDING_SURFACE_FACTORS = {
    "DRY": 1.00,
    "WET": 1.15,
    "CONTAMINATED": 1.35,
}

LANDING_AUTOBRAKE_FACTORS = {
    "OFF": 1.10,
    "LOW": 1.03,
    "MED": 0.98,
    "HIGH": 0.92,
}


@dataclass(frozen=True)
class TakeoffAircraftConfig:
    name: str
    mtow_kg: float
    climb_fpm: float
    flap_options: List[str]
    wing_area_m2: float
    clmax_by_flap: Dict[str, float]
    cd0: float
    oswald_e: float
    aspect_ratio: float
    total_static_thrust_n: float
    engine_count: int


TAKEOFF_CONFIGS = {
    "A320_FAMILY": TakeoffAircraftConfig(
        name="Airbus A320 Family",
        mtow_kg=78000,
        climb_fpm=3000,
        flap_options=["1+F", "2", "3"],
        wing_area_m2=122.6,
        clmax_by_flap={"1+F": 1.95, "2": 2.15, "3": 2.35},
        cd0=0.024,
        oswald_e=0.80,
        aspect_ratio=9.5,
        total_static_thrust_n=240000,
        engine_count=2,
    ),
    "A321_FAMILY": TakeoffAircraftConfig(
        name="Airbus A321 Family",
        mtow_kg=93500,
        climb_fpm=2800,
        flap_options=["1+F", "2", "3"],
        wing_area_m2=122.6,
        clmax_by_flap={"1+F": 1.95, "2": 2.15, "3": 2.35},
        cd0=0.024,
        oswald_e=0.80,
        aspect_ratio=9.5,
        total_static_thrust_n=280000,
        engine_count=2,
    ),
    "A321_NEO": TakeoffAircraftConfig(
        name="Airbus A321neo",
        mtow_kg=97000,
        climb_fpm=2850,
        flap_options=["1+F", "2", "3"],
        wing_area_m2=122.6,
        clmax_by_flap={"1+F": 1.95, "2": 2.15, "3": 2.35},
        cd0=0.022,
        oswald_e=0.82,
        aspect_ratio=9.5,
        total_static_thrust_n=294000,
        engine_count=2,
    ),
    "A220": TakeoffAircraftConfig(
        name="Airbus A220-300",
        mtow_kg=70400,
        climb_fpm=3200,
        flap_options=["1+F", "2", "3"],
        wing_area_m2=112.3,
        clmax_by_flap={"1+F": 1.90, "2": 2.08, "3": 2.28},
        cd0=0.024,
        oswald_e=0.81,
        aspect_ratio=11.0,
        total_static_thrust_n=208000,
        engine_count=2,
    ),
    "A330": TakeoffAircraftConfig(
        name="Airbus A330",
        mtow_kg=242000,
        climb_fpm=2400,
        flap_options=["1+F", "2", "3"],
        wing_area_m2=361.6,
        clmax_by_flap={"1+F": 2.20, "2": 2.40, "3": 2.60},
        cd0=0.022,
        oswald_e=0.82,
        aspect_ratio=10.1,
        total_static_thrust_n=640000,
        engine_count=2,
    ),
    "A330_NEO": TakeoffAircraftConfig(
        name="Airbus A330neo",
        mtow_kg=251000,
        climb_fpm=2500,
        flap_options=["1+F", "2", "3"],
        wing_area_m2=361.6,
        clmax_by_flap={"1+F": 2.24, "2": 2.44, "3": 2.64},
        cd0=0.021,
        oswald_e=0.84,
        aspect_ratio=11.3,
        total_static_thrust_n=646000,
        engine_count=2,
    ),
    "A350": TakeoffAircraftConfig(
        name="Airbus A350",
        mtow_kg=280000,
        climb_fpm=2600,
        flap_options=["1+F", "2", "3"],
        wing_area_m2=442.0,
        clmax_by_flap={"1+F": 1.90, "2": 2.10, "3": 2.30},
        cd0=0.021,
        oswald_e=0.85,
        aspect_ratio=9.5,
        total_static_thrust_n=740000,
        engine_count=2,
    ),
    "A380": TakeoffAircraftConfig(
        name="Airbus A380-800",
        mtow_kg=575000,
        climb_fpm=2000,
        flap_options=["1+F", "2", "3"],
        wing_area_m2=845.0,
        clmax_by_flap={"1+F": 1.80, "2": 2.00, "3": 2.20},
        cd0=0.022,
        oswald_e=0.83,
        aspect_ratio=7.5,
        total_static_thrust_n=1360000,
        engine_count=4,
    ),
    "B737": TakeoffAircraftConfig(
        name="Boeing 737 Family",
        mtow_kg=82000,
        climb_fpm=3200,
        flap_options=["1", "2", "5"],
        wing_area_m2=124.6,
        clmax_by_flap={"1": 1.75, "2": 1.85, "5": 2.05},
        cd0=0.025,
        oswald_e=0.78,
        aspect_ratio=9.4,
        total_static_thrust_n=250000,
        engine_count=2,
    ),
    "B747": TakeoffAircraftConfig(
        name="Boeing 747-8",
        mtow_kg=447700,
        climb_fpm=2200,
        flap_options=["10", "20"],
        wing_area_m2=554.0,
        clmax_by_flap={"10": 1.85, "20": 2.10},
        cd0=0.024,
        oswald_e=0.80,
        aspect_ratio=7.1,
        total_static_thrust_n=1160000,
        engine_count=4,
    ),
    "B757": TakeoffAircraftConfig(
        name="Boeing 757-300",
        mtow_kg=124700,
        climb_fpm=3000,
        flap_options=["5", "15", "20"],
        wing_area_m2=185.3,
        clmax_by_flap={"5": 1.78, "15": 2.00, "20": 2.18},
        cd0=0.024,
        oswald_e=0.80,
        aspect_ratio=8.6,
        total_static_thrust_n=380000,
        engine_count=2,
    ),
    "B767": TakeoffAircraftConfig(
        name="Boeing 767-300ER",
        mtow_kg=186900,
        climb_fpm=2700,
        flap_options=["5", "15", "20"],
        wing_area_m2=283.3,
        clmax_by_flap={"5": 1.80, "15": 2.00, "20": 2.20},
        cd0=0.023,
        oswald_e=0.81,
        aspect_ratio=8.7,
        total_static_thrust_n=520000,
        engine_count=2,
    ),
    "B777": TakeoffAircraftConfig(
        name="Boeing 777 Family",
        mtow_kg=351500,
        climb_fpm=2500,
        flap_options=["5", "15", "20"],
        wing_area_m2=427.8,
        clmax_by_flap={"5": 2.00, "15": 2.20, "20": 2.40},
        cd0=0.023,
        oswald_e=0.82,
        aspect_ratio=8.7,
        total_static_thrust_n=900000,
        engine_count=2,
    ),
    "B787": TakeoffAircraftConfig(
        name="Boeing 787 Family",
        mtow_kg=254000,
        climb_fpm=2800,
        flap_options=["5", "15", "20"],
        wing_area_m2=377.0,
        clmax_by_flap={"5": 1.85, "15": 2.05, "20": 2.25},
        cd0=0.021,
        oswald_e=0.84,
        aspect_ratio=9.6,
        total_static_thrust_n=640000,
        engine_count=2,
    ),
    "E190": TakeoffAircraftConfig(
        name="Embraer 190",
        mtow_kg=51800,
        climb_fpm=3200,
        flap_options=["1", "2", "3"],
        wing_area_m2=92.5,
        clmax_by_flap={"1": 1.70, "2": 1.95, "3": 2.12},
        cd0=0.026,
        oswald_e=0.79,
        aspect_ratio=8.4,
        total_static_thrust_n=164000,
        engine_count=2,
    ),
    "E175": TakeoffAircraftConfig(
        name="Embraer 175",
        mtow_kg=39700,
        climb_fpm=3300,
        flap_options=["1", "2", "3"],
        wing_area_m2=70.6,
        clmax_by_flap={"1": 1.70, "2": 1.92, "3": 2.08},
        cd0=0.026,
        oswald_e=0.79,
        aspect_ratio=8.4,
        total_static_thrust_n=128000,
        engine_count=2,
    ),
}


@dataclass(frozen=True)
class FuelAircraftConfig:
    burn_kg_per_hr: float
    cruise_gs_kt_default: float
    taxi_fuel_kg_default: float
    alternate_fuel_kg_default: float
    reserve_time_min_default: int = 30


TAKEOFF_FUEL_CONFIGS = {
    "A320_FAMILY": FuelAircraftConfig(2500, 440, 220, 900, 30),
    "A321_FAMILY": FuelAircraftConfig(2800, 445, 240, 950, 30),
    "A220": FuelAircraftConfig(2200, 430, 180, 800, 30),
    "A330": FuelAircraftConfig(5600, 470, 450, 2200, 30),
    "A350": FuelAircraftConfig(5800, 480, 480, 2300, 30),
    "A380": FuelAircraftConfig(11500, 490, 900, 4200, 30),
    "B737": FuelAircraftConfig(2600, 440, 220, 900, 30),
    "B747": FuelAircraftConfig(9800, 490, 750, 3600, 30),
    "B757": FuelAircraftConfig(3600, 450, 260, 1200, 30),
    "B767": FuelAircraftConfig(4700, 455, 320, 1700, 30),
    "B777": FuelAircraftConfig(7000, 485, 550, 2600, 30),
    "B787": FuelAircraftConfig(5400, 485, 420, 2100, 30),
    "E190": FuelAircraftConfig(1800, 410, 150, 650, 30),
    "E175": FuelAircraftConfig(1500, 400, 130, 550, 30),
}


def resolve_takeoff_fuel_family_config(aircraft_name: str) -> FuelAircraftConfig:
    name = (aircraft_name or "").lower()
    if "a321" in name:
        return TAKEOFF_FUEL_CONFIGS["A321_FAMILY"]
    if "a320" in name or "a319" in name:
        return TAKEOFF_FUEL_CONFIGS["A320_FAMILY"]
    if "a220" in name:
        return TAKEOFF_FUEL_CONFIGS["A220"]
    if "a330" in name or "a340" in name:
        return TAKEOFF_FUEL_CONFIGS["A330"]
    if "a350" in name:
        return TAKEOFF_FUEL_CONFIGS["A350"]
    if "a380" in name:
        return TAKEOFF_FUEL_CONFIGS["A380"]
    if "747" in name:
        return TAKEOFF_FUEL_CONFIGS["B747"]
    if "757" in name or "767" in name:
        return TAKEOFF_FUEL_CONFIGS["B757"]
    if "777" in name:
        return TAKEOFF_FUEL_CONFIGS["B777"]
    if "787" in name:
        return TAKEOFF_FUEL_CONFIGS["B787"]
    if "737" in name:
        return TAKEOFF_FUEL_CONFIGS["B737"]
    if "embraer 175" in name:
        return TAKEOFF_FUEL_CONFIGS["E175"]
    if "embraer" in name:
        return TAKEOFF_FUEL_CONFIGS["E190"]
    return TAKEOFF_FUEL_CONFIGS["B787"]


def resolve_takeoff_fuel_config(aircraft_name: str) -> FuelAircraftConfig:
    base = resolve_takeoff_fuel_family_config(aircraft_name)
    lib = get_library_aircraft(aircraft_name)
    if not lib:
        return base
    return FuelAircraftConfig(
        burn_kg_per_hr=float(lib.get("fuel_burn", base.burn_kg_per_hr)),
        cruise_gs_kt_default=base.cruise_gs_kt_default,
        taxi_fuel_kg_default=base.taxi_fuel_kg_default,
        alternate_fuel_kg_default=base.alternate_fuel_kg_default,
        reserve_time_min_default=base.reserve_time_min_default,
    )


def compute_takeoff_fuel_plan(
    aircraft_name: str,
    distance_nm: float,
    ground_speed_kt: Optional[float] = None,
    headwind_component_kt: float = 0.0,
    taxi_fuel_kg: Optional[float] = None,
    contingency_percent: float = 5.0,
    alternate_fuel_kg: Optional[float] = None,
    reserve_minutes: Optional[float] = None,
    extra_fuel_kg: float = 0.0,
) -> Dict[str, float]:
    cfg = resolve_takeoff_fuel_config(aircraft_name)
    distance_nm = max(0.0, distance_nm)
    base_gs = float(ground_speed_kt) if ground_speed_kt not in (None, 0) else cfg.cruise_gs_kt_default
    gs_eff = max(250.0, base_gs - max(headwind_component_kt, 0.0))
    ete_hours = distance_nm / max(gs_eff, 1.0)
    burn_kg_per_hr = cfg.burn_kg_per_hr
    burn_kg_per_nm = burn_kg_per_hr / max(gs_eff, 1.0)
    trip_fuel_kg = ete_hours * burn_kg_per_hr
    contingency_fuel_kg = trip_fuel_kg * max(0.0, contingency_percent) / 100.0
    reserve_min = float(reserve_minutes) if reserve_minutes not in (None, "") else float(cfg.reserve_time_min_default)
    reserve_fuel_kg = max(0.0, reserve_min) / 60.0 * burn_kg_per_hr
    taxi = max(0.0, float(taxi_fuel_kg) if taxi_fuel_kg not in (None, "") else cfg.taxi_fuel_kg_default)
    alternate = max(0.0, float(alternate_fuel_kg) if alternate_fuel_kg not in (None, "") else cfg.alternate_fuel_kg_default)
    extra = max(0.0, float(extra_fuel_kg or 0.0))
    block_fuel_kg = taxi + trip_fuel_kg + contingency_fuel_kg + alternate + reserve_fuel_kg + extra
    return {
        "distance_nm": distance_nm,
        "effective_gs_kt": gs_eff,
        "ete_hours": ete_hours,
        "trip_fuel_kg": trip_fuel_kg,
        "contingency_fuel_kg": contingency_fuel_kg,
        "reserve_fuel_kg": reserve_fuel_kg,
        "alternate_fuel_kg": alternate,
        "taxi_fuel_kg": taxi,
        "extra_fuel_kg": extra,
        "block_fuel_kg": block_fuel_kg,
        "burn_kg_per_hr": burn_kg_per_hr,
        "burn_kg_per_nm": burn_kg_per_nm,
    }


@dataclass
class TakeoffMetarData:
    raw: str
    temperature_c: float
    qnh_hpa: float
    wind_dir_deg: int
    wind_speed_kt: int
    wind_gust_kt: int = 0
    observation: Optional[dict] = None


@dataclass
class TakeoffInputs:
    aircraft_name: str
    takeoff_weight_kg: float
    elevation_ft: float
    oat_c: float
    qnh_hpa: float
    wind_from_deg: int
    wind_speed_kt: float
    runway_heading_deg: int
    runway_slope_pct: float
    surface_condition: str
    flap_setting: str
    wind_gust_kt: float = 0.0
    tora_m: Optional[float] = None
    toda_m: Optional[float] = None
    asda_m: Optional[float] = None


@dataclass
class TakeoffResultData:
    aircraft_name: str
    flap_setting: str
    vs_kt: int
    v1_kt: int
    vr_kt: int
    v2_kt: int
    accelerate_go_m: int
    accelerate_stop_m: int
    takeoff_distance_m: int
    pressure_altitude_ft: int
    density_altitude_ft: int
    isa_temperature_c: float
    isa_deviation_c: float
    sigma: float
    headwind_kt: int
    headwind_gust_kt: int
    crosswind_kt: int
    climb_initial_fpm: int
    climb_enroute_fpm: int
    climb_high_alt_fpm: int
    mtow_kg: int
    runway_margins_m: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)


def resolve_takeoff_aircraft_config(aircraft_name: str) -> TakeoffAircraftConfig:
    name = (aircraft_name or "").lower()
    if "a321neo" in name or "a321 neo" in name:
        base = TAKEOFF_CONFIGS["A321_NEO"]
    elif "a321" in name:
        base = TAKEOFF_CONFIGS["A321_FAMILY"]
    elif "a320" in name or "a319" in name:
        base = TAKEOFF_CONFIGS["A320_FAMILY"]
    elif "a220" in name:
        base = TAKEOFF_CONFIGS["A220"]
    elif "a330-800" in name or "a330-900" in name:
        base = TAKEOFF_CONFIGS["A330_NEO"]
    elif "a330" in name or "a340" in name:
        base = TAKEOFF_CONFIGS["A330"]
    elif "a350" in name:
        base = TAKEOFF_CONFIGS["A350"]
    elif "a380" in name:
        base = TAKEOFF_CONFIGS["A380"]
    elif "747" in name:
        base = TAKEOFF_CONFIGS["B747"]
    elif "757" in name or "767" in name:
        base = TAKEOFF_CONFIGS["B757"]
    elif "777" in name:
        base = TAKEOFF_CONFIGS["B777"]
    elif "787" in name:
        base = TAKEOFF_CONFIGS["B787"]
    elif "737" in name:
        base = TAKEOFF_CONFIGS["B737"]
    elif "embraer 175" in name:
        base = TAKEOFF_CONFIGS["E175"]
    elif "embraer" in name:
        base = TAKEOFF_CONFIGS["E190"]
    else:
        base = TAKEOFF_CONFIGS["B787"]
    lib = get_library_aircraft(aircraft_name)
    if not lib:
        return base
    flap_options = list(lib.get("flap_options", base.flap_options))
    fallback_cl = list(base.clmax_by_flap.values())[-1]
    clmax_by_flap = {flap: base.clmax_by_flap.get(flap, fallback_cl) for flap in flap_options}
    return TakeoffAircraftConfig(
        name=lib.get("name", base.name),
        mtow_kg=float(lib.get("mtow", base.mtow_kg)),
        climb_fpm=float(lib.get("climb_fpm", base.climb_fpm)),
        flap_options=flap_options,
        wing_area_m2=base.wing_area_m2,
        clmax_by_flap=clmax_by_flap,
        cd0=base.cd0,
        oswald_e=base.oswald_e,
        aspect_ratio=base.aspect_ratio,
        total_static_thrust_n=base.total_static_thrust_n,
        engine_count=base.engine_count,
    )


def fetch_takeoff_metar(icao: str) -> Optional[TakeoffMetarData]:
    icao = normalize_airport_code(icao)
    if not icao:
        return None
    url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload:
            return None
        m = payload[0]
        altim = m.get("altim")
        if altim is not None:
            altim = float(altim)
            qnh = altim * 33.8639 if altim < 100 else altim
        else:
            qnh = 1013.25
        wind_dir = m.get("wdir", 0)
        if wind_dir in (None, "VRB"):
            wind_dir = 0
        gust = m.get("wgst", 0) or 0
        return TakeoffMetarData(
            raw=m.get("rawOb", "N/A"),
            temperature_c=float(m["temp"]) if m.get("temp") is not None else 15.0,
            qnh_hpa=round(float(qnh), 1),
            wind_dir_deg=int(wind_dir),
            wind_speed_kt=int(m.get("wspd", 0) or 0),
            wind_gust_kt=int(gust),
            observation=m,
        )
    except Exception:
        return None


def density_ratio_from_density_altitude_ft(density_altitude_ft: float) -> float:
    sigma = (1 - 0.0000068756 * density_altitude_ft) ** 4.2561
    return max(float(sigma), 0.4)


def scale_takeoff_reference_speed_kt(
    reference_speed_kt: float,
    takeoff_weight_kg: float,
    mtow_kg: float,
    reference_weight_ratio: float,
) -> float:
    """Scale a simulator reference speed using the aerodynamic square-root weight relationship."""
    mtow = max(float(mtow_kg), 1.0)
    reference_ratio = max(float(reference_weight_ratio), 0.01)
    weight_ratio = max(0.50, min(float(takeoff_weight_kg) / mtow, 1.05))
    return float(reference_speed_kt) * math.sqrt(weight_ratio / reference_ratio)


def normalize_angle_diff_deg(a_deg: float, b_deg: float) -> float:
    return (a_deg - b_deg + 180.0) % 360.0 - 180.0


def validate_takeoff_vspeeds(vs_kt: float, v1_kt: float, vr_kt: float, v2_kt: float) -> Tuple[float, float, float]:
    """Keep displayed takeoff V-speeds in a realistic order: V1 < VR < V2."""
    vs = max(float(vs_kt or 0.0), 1.0)
    vr = max(float(vr_kt or 0.0), vs + 7.0)

    v1 = float(v1_kt or 0.0)
    if v1 <= 0:
        v1 = vr - 6.0
    v1 = min(v1, vr - 5.0)
    v1 = max(v1, vs + 3.0)
    if v1 >= vr:
        v1 = vr - 5.0

    v2 = float(v2_kt or 0.0)
    v2 = max(v2, vr + 8.0, vs + 13.0)

    if int(round(v1)) >= int(round(vr)):
        v1 = vr - 5.0
    if int(round(v2)) <= int(round(vr)):
        v2 = vr + 8.0

    return v1, vr, v2


def validate_landing_speeds(vs_kt: float, vref_kt: float, vapp_kt: float, additive_kt: float) -> Tuple[float, float, float, float]:
    """Keep landing speeds separated and physically sensible: Vs < Vref < Vapp."""
    vs = max(float(vs_kt or 0.0), 1.0)
    vref = max(float(vref_kt or 0.0), vs * 1.18, vs + 10.0)
    additive = max(float(additive_kt or 0.0), 5.0)
    vapp = max(float(vapp_kt or 0.0), vref + additive)
    if int(round(vapp)) <= int(round(vref)):
        vapp = vref + max(additive, 5.0)
    return vs, vref, vapp, additive


def audit_aircraft_speed_tables() -> Dict[str, List[str]]:
    """Audit aircraft-library speed tables for missing or impossible speed spacing."""
    report: Dict[str, List[str]] = {
        "takeoff_speed_order_fixed_by_validator": [],
        "landing_speed_order_fixed_by_validator": [],
        "missing_takeoff_speed_keys": [],
        "missing_landing_speed_keys": [],
    }
    for aircraft_key, aircraft in AIRCRAFT_LIBRARY.items():
        flap_options = [str(x) for x in aircraft.get("flap_options", [])]
        vr_table = aircraft.get("vr_speeds", {}) or {}
        v2_table = aircraft.get("v2_speeds", {}) or {}
        for flap in flap_options:
            if flap not in vr_table or flap not in v2_table:
                report["missing_takeoff_speed_keys"].append(f"{aircraft_key}: flap {flap}")
                continue
            vr = float(vr_table.get(flap) or 0)
            v2 = float(v2_table.get(flap) or 0)
            v1, new_vr, new_v2 = validate_takeoff_vspeeds(max(vr - 12, 1), vr - 4, vr, v2)
            if int(round(new_v2)) <= int(round(new_vr)) or int(round(v1)) >= int(round(new_vr)):
                report["takeoff_speed_order_fixed_by_validator"].append(f"{aircraft_key}: flap {flap}")

        land_flaps = [str(x) for x in aircraft.get("land_flaps", [])]
        vref_table = aircraft.get("vref_speeds", {}) or {}
        for flap in land_flaps:
            if flap not in vref_table:
                report["missing_landing_speed_keys"].append(f"{aircraft_key}: flap {flap}")
                continue
            vref = float(vref_table.get(flap) or 0)
            vs, new_vref, new_vapp, _ = validate_landing_speeds(max(vref - 18, 1), vref, vref + 5, 5)
            if int(round(new_vapp)) <= int(round(new_vref)):
                report["landing_speed_order_fixed_by_validator"].append(f"{aircraft_key}: flap {flap}")
    return report


def compute_takeoff_performance(inputs: TakeoffInputs) -> TakeoffResultData:
    ac = resolve_takeoff_aircraft_config(inputs.aircraft_name)
    flap_setting = inputs.flap_setting if inputs.flap_setting in ac.clmax_by_flap else ac.flap_options[0]
    surface = (inputs.surface_condition or "DRY").upper()
    surface_factor = TAKEOFF_SURFACE_FACTORS.get(surface, 1.0)

    elevation_ft = float(inputs.elevation_ft)
    isa_temp_c = 15.0 - 0.0019812 * elevation_ft
    isa_deviation_c = float(inputs.oat_c) - isa_temp_c
    pressure_altitude_ft = elevation_ft + (1013.25 - float(inputs.qnh_hpa)) * 30.0
    density_altitude_ft = pressure_altitude_ft + 120.0 * isa_deviation_c

    sigma = density_ratio_from_density_altitude_ft(density_altitude_ft)
    sea_level_rho = 1.225
    rho = sea_level_rho * sigma

    delta_deg = normalize_angle_diff_deg(float(inputs.wind_from_deg), float(inputs.runway_heading_deg))
    delta_rad = math.radians(delta_deg)
    headwind_kt = float(inputs.wind_speed_kt) * math.cos(delta_rad)
    crosswind_kt = abs(float(inputs.wind_speed_kt) * math.sin(delta_rad))

    gust_speed_kt = max(float(inputs.wind_gust_kt or 0.0), float(inputs.wind_speed_kt or 0.0))
    headwind_gust_kt = gust_speed_kt * math.cos(delta_rad)

    wing_area = ac.wing_area_m2
    clmax = ac.clmax_by_flap[flap_setting]
    flap_drag_increment = {
        "1+F": 0.012,
        "2": 0.022,
        "3": 0.038,
        "1": 0.010,
        "5": 0.018,
        "10": 0.020,
        "15": 0.028,
        "20": 0.040,
        "FULL": 0.055,
    }.get(flap_setting, 0.025)

    thrust_lapse = sigma ** 0.8 * (1.0 - 0.004 * max(isa_deviation_c, 0.0))
    thrust_available_n = max(ac.total_static_thrust_n * thrust_lapse, 0.0)

    mu_roll = 0.015
    mu_brake = 0.40 / surface_factor
    slope_rad = math.atan(float(inputs.runway_slope_pct) / 100.0)

    mass_kg = float(inputs.takeoff_weight_kg)
    weight_n = mass_kg * G

    # V-speeds are displayed as calibrated/indicated airspeed. Density affects
    # the corresponding true airspeed and runway distance, not the scheduled KIAS directly.
    vs_ias_mps = math.sqrt((2.0 * weight_n) / (sea_level_rho * wing_area * clmax))
    vs_kt = vs_ias_mps * MPS_TO_KTS

    vr_factor = 1.10
    if mass_kg / ac.mtow_kg > 0.92:
        vr_factor = 1.12
    if density_altitude_ft > 4000:
        vr_factor += 0.02

    lib = get_library_aircraft(inputs.aircraft_name)
    lib_vr = lib.get("vr_speeds", {}).get(flap_setting) if lib else None
    lib_v2 = lib.get("v2_speeds", {}).get(flap_setting) if lib else None
    speed_reference_ratio = float((lib or {}).get("takeoff_speed_reference_weight_ratio", 0.0) or 0.0)
    vr_floor = float((lib or {}).get("takeoff_vr_floor_speeds", {}).get(flap_setting, 0.0) or 0.0)
    v2_floor = float((lib or {}).get("takeoff_v2_floor_speeds", {}).get(flap_setting, 0.0) or 0.0)

    if lib_vr is not None and speed_reference_ratio > 0:
        vr_kt = scale_takeoff_reference_speed_kt(
            float(lib_vr), mass_kg, ac.mtow_kg, speed_reference_ratio
        )
        vr_kt = max(vr_kt, vr_floor, vs_kt * 1.05, vs_kt + 5.0)
    elif lib_vr is not None:
        vr_kt = float(lib_vr)
    else:
        vr_kt = max(vs_kt * vr_factor, vs_kt * 1.05)

    v2_factor = 1.20 if ac.engine_count == 2 else 1.15
    if lib_v2 is not None and speed_reference_ratio > 0:
        v2_kt = scale_takeoff_reference_speed_kt(
            float(lib_v2), mass_kg, ac.mtow_kg, speed_reference_ratio
        )
        v2_kt = max(v2_kt, v2_floor, vs_kt * 1.13, vr_kt + 8.0)
    elif lib_v2 is not None:
        v2_kt = float(lib_v2)
    else:
        v2_kt = max(vs_kt * v2_factor, vr_kt + 5.0)
    v2_kt = max(v2_kt, vr_kt + 5.0)

    tas_per_ias = 1.0 / max(math.sqrt(sigma), 0.01)
    vr_mps = vr_kt * KTS_TO_MPS * tas_per_ias

    dt = 0.25

    def drag_n(airspeed_mps: float, on_ground: bool = True) -> float:
        if airspeed_mps < 1e-6:
            return 0.0
        q = 0.5 * rho * airspeed_mps * airspeed_mps
        cl = weight_n / max(q * wing_area, 1e-6)
        if on_ground:
            cl = min(cl, clmax * 0.7)
        induced = (cl * cl) / (math.pi * ac.aspect_ratio * ac.oswald_e)
        if on_ground:
            induced *= 0.5
        cd_total = ac.cd0 + flap_drag_increment + induced
        return q * wing_area * cd_total

    def lift_n(airspeed_mps: float) -> float:
        if airspeed_mps < 1e-6:
            return 0.0
        q = 0.5 * rho * airspeed_mps * airspeed_mps
        cl_ground = min(0.4, clmax * 0.3)
        return q * wing_area * cl_ground

    def integrate_accel(target_airspeed_mps: float, thrust_n: float, asym_drag: bool = False, min_accel: float = 0.0):
        airspeed = 0.0
        distance = 0.0
        while airspeed < target_airspeed_mps and distance < 4000:
            drag = drag_n(airspeed, on_ground=True)
            if asym_drag:
                drag += 0.5 * rho * airspeed * airspeed * wing_area * 0.003
            lift = lift_n(airspeed)
            friction = mu_roll * max(weight_n - lift, 0.0)
            slope_force = weight_n * math.sin(slope_rad)
            accel = max((thrust_n - drag - friction - slope_force) / mass_kg, min_accel)
            airspeed += accel * dt
            groundspeed = max(airspeed - headwind_kt * KTS_TO_MPS, 0.0)
            distance += groundspeed * dt
        return airspeed, distance

    def accelerate_stop_distance(v1_mps: float) -> float:
        airspeed, distance = integrate_accel(v1_mps, thrust_available_n, asym_drag=False, min_accel=0.1)
        groundspeed = max(airspeed - headwind_kt * KTS_TO_MPS, 0.0)
        distance += groundspeed * 2.0
        while groundspeed > 0.5 and distance < 5000:
            airspeed = max(groundspeed + headwind_kt * KTS_TO_MPS, 0.0)
            drag = drag_n(airspeed, on_ground=True)
            lift = lift_n(airspeed)
            brake_force = mu_brake * max(weight_n - lift, 0.0)
            slope_force = weight_n * math.sin(slope_rad)
            spoiler_drag = 0.5 * rho * airspeed * airspeed * wing_area * 0.05
            accel = (-drag - spoiler_drag - brake_force + slope_force) / mass_kg
            groundspeed = max(groundspeed + accel * dt, 0.0)
            distance += groundspeed * dt
        return distance

    def accelerate_go_distance(v1_mps: float) -> float:
        airspeed, distance = integrate_accel(v1_mps, thrust_available_n, asym_drag=False, min_accel=0.1)
        oei_thrust_n = thrust_available_n * (ac.engine_count - 1) / ac.engine_count
        while airspeed < vr_mps and distance < 4000:
            drag = drag_n(airspeed, on_ground=True) + 0.5 * rho * airspeed * airspeed * wing_area * 0.003
            lift = lift_n(airspeed)
            friction = mu_roll * max(weight_n - lift, 0.0)
            slope_force = weight_n * math.sin(slope_rad)
            accel = max((oei_thrust_n - drag - friction - slope_force) / mass_kg, 0.05)
            airspeed += accel * dt
            groundspeed = max(airspeed - headwind_kt * KTS_TO_MPS, 0.0)
            distance += groundspeed * dt
        distance += 250.0 * surface_factor
        return distance

    v1_low = vs_kt * 1.05 * KTS_TO_MPS * tas_per_ias
    v1_high = vr_mps
    for _ in range(20):
        test_v1 = 0.5 * (v1_low + v1_high)
        asd = accelerate_stop_distance(test_v1)
        agd = accelerate_go_distance(test_v1)
        if abs(asd - agd) < 10.0:
            break
        if asd > agd:
            v1_high = test_v1
        else:
            v1_low = test_v1

    v1_tas_mps = 0.5 * (v1_low + v1_high)
    v1_kt = min(max(v1_tas_mps * MPS_TO_KTS / tas_per_ias, vs_kt * 1.05), vr_kt)
    v1_kt, vr_kt, v2_kt = validate_takeoff_vspeeds(vs_kt, v1_kt, vr_kt, v2_kt)
    v1_max_gap_kt = float((lib or {}).get("takeoff_v1_max_gap_kt", 0.0) or 0.0)
    if v1_max_gap_kt > 0.0:
        v1_kt = max(v1_kt, vr_kt - v1_max_gap_kt)
        v1_kt, vr_kt, v2_kt = validate_takeoff_vspeeds(vs_kt, v1_kt, vr_kt, v2_kt)
    vr_mps = vr_kt * KTS_TO_MPS * tas_per_ias
    v1_tas_mps = v1_kt * KTS_TO_MPS * tas_per_ias
    accelerate_go_m = int(round(accelerate_go_distance(v1_tas_mps)))
    accelerate_stop_m = int(round(accelerate_stop_distance(v1_tas_mps)))
    takeoff_distance_m = int(round(accelerate_go_m * 1.15))

    weight_factor = max(0.6, 1.0 - (mass_kg / ac.mtow_kg - 0.7) * 0.5)
    max_fpm = int(ac.climb_fpm * weight_factor * math.sqrt(sigma))

    warnings: List[str] = []
    cautions: List[str] = []
    if crosswind_kt > 25:
        warnings.append(f"Crosswind {int(crosswind_kt)} kt exceeds limit")
    elif crosswind_kt > 15:
        cautions.append(f"Crosswind {int(crosswind_kt)} kt")

    if headwind_kt < -10:
        warnings.append(f"Tailwind {int(abs(headwind_kt))} kt")
    elif headwind_kt < -5:
        cautions.append(f"Tailwind {int(abs(headwind_kt))} kt")

    if gust_speed_kt > inputs.wind_speed_kt:
        if headwind_kt < 0 and headwind_gust_kt < headwind_kt:
            cautions.append(f"Gusts increase tailwind to {int(abs(headwind_gust_kt))} kt")
        elif headwind_kt > 0 and headwind_gust_kt > headwind_kt + 3:
            cautions.append(f"Gusts increase headwind to {int(headwind_gust_kt)} kt")

    if density_altitude_ft > 8000:
        warnings.append(f"High density altitude {int(density_altitude_ft)} ft")
    elif density_altitude_ft > 4000:
        cautions.append(f"Density altitude {int(density_altitude_ft)} ft")

    if mass_kg > ac.mtow_kg:
        warnings.append("Takeoff weight exceeds MTOW")
    elif mass_kg > ac.mtow_kg * 0.97:
        cautions.append("Takeoff weight is near MTOW")

    if surface_factor > 1.2:
        cautions.append(f"Runway condition {surface}")

    runway_margins: Dict[str, int] = {}
    if inputs.tora_m and inputs.tora_m > 0:
        margin = int(round(inputs.tora_m - accelerate_go_m))
        runway_margins["TORA"] = margin
        if accelerate_go_m > inputs.tora_m:
            warnings.append(f"TORA exceeded by {accelerate_go_m - int(inputs.tora_m)} m")
    if inputs.toda_m and inputs.toda_m > 0:
        margin = int(round(inputs.toda_m - takeoff_distance_m))
        runway_margins["TODA"] = margin
        if takeoff_distance_m > inputs.toda_m:
            warnings.append(f"TODA exceeded by {takeoff_distance_m - int(inputs.toda_m)} m")
    if inputs.asda_m and inputs.asda_m > 0:
        margin = int(round(inputs.asda_m - accelerate_stop_m))
        runway_margins["ASDA"] = margin
        if accelerate_stop_m > inputs.asda_m:
            warnings.append(f"ASDA exceeded by {accelerate_stop_m - int(inputs.asda_m)} m")

    return TakeoffResultData(
        aircraft_name=inputs.aircraft_name,
        flap_setting=flap_setting,
        vs_kt=int(round(vs_kt)),
        v1_kt=int(round(v1_kt)),
        vr_kt=int(round(vr_kt)),
        v2_kt=int(round(v2_kt)),
        accelerate_go_m=accelerate_go_m,
        accelerate_stop_m=accelerate_stop_m,
        takeoff_distance_m=takeoff_distance_m,
        pressure_altitude_ft=int(round(pressure_altitude_ft)),
        density_altitude_ft=int(round(density_altitude_ft)),
        isa_temperature_c=round(isa_temp_c, 1),
        isa_deviation_c=round(isa_deviation_c, 1),
        sigma=round(sigma, 4),
        headwind_kt=int(round(headwind_kt)),
        headwind_gust_kt=int(round(headwind_gust_kt)),
        crosswind_kt=int(round(crosswind_kt)),
        climb_initial_fpm=min(max_fpm, 2200),
        climb_enroute_fpm=min(max_fpm, 2800),
        climb_high_alt_fpm=int(max_fpm * 0.65),
        mtow_kg=int(round(ac.mtow_kg)),
        runway_margins_m=runway_margins,
        warnings=warnings,
        cautions=cautions,
    )


SEAT_LETTER_POOL = list("ABCDEFGHJKLMNPQRSTUVWXYZ")
CABIN_ORDER = ["First", "Business", "Premium Economy", "Economy"]
CABIN_COLORS = {
    "First": "#F59E0B",
    "Business": "#2563EB",
    "Premium Economy": "#0F766E",
    "Economy": "#E5E7EB",
}


AIRCRAFT_SEAT_PRESETS = {
    "Airbus A350-900": {
        "layouts": {
            "First": None,
            "Business": [1, 2, 1],
            "Premium Economy": [2, 4, 2],
            "Economy": [3, 3, 3],
        },
        "defaults": {"First": 0, "Business": 32, "Premium Economy": 28, "Economy": 280},
    },
    "Airbus A380-800": {
        "layouts": {
            "First": [1, 2, 1],
            "Business": [1, 2, 1],
            "Premium Economy": [2, 4, 2],
            "Economy": [3, 4, 3],
        },
        "defaults": {"First": 14, "Business": 76, "Premium Economy": 56, "Economy": 338},
    },
    "Boeing 777-300ER": {
        "layouts": {
            "First": [1, 2, 1],
            "Business": [1, 2, 1],
            "Premium Economy": [2, 4, 2],
            "Economy": [3, 4, 3],
        },
        "defaults": {"First": 8, "Business": 42, "Premium Economy": 24, "Economy": 304},
    },
    "Boeing 777-200ER": {
        "layouts": {
            "First": [1, 2, 1],
            "Business": [1, 2, 1],
            "Premium Economy": [2, 4, 2],
            "Economy": [3, 3, 3],
        },
        "defaults": {"First": 8, "Business": 37, "Premium Economy": 24, "Economy": 242},
    },
    "Boeing 787-8": {
        "layouts": {
            "First": None,
            "Business": [1, 2, 1],
            "Premium Economy": [2, 3, 2],
            "Economy": [3, 3, 3],
        },
        "defaults": {"First": 0, "Business": 28, "Premium Economy": 21, "Economy": 214},
    },
    "Boeing 787-9": {
        "layouts": {
            "First": None,
            "Business": [1, 2, 1],
            "Premium Economy": [2, 3, 2],
            "Economy": [3, 3, 3],
        },
        "defaults": {"First": 0, "Business": 30, "Premium Economy": 28, "Economy": 226},
    },
    "Boeing 787-10": {
        "layouts": {
            "First": None,
            "Business": [1, 2, 1],
            "Premium Economy": [2, 3, 2],
            "Economy": [3, 3, 3],
        },
        "defaults": {"First": 0, "Business": 34, "Premium Economy": 28, "Economy": 272},
    },
    "Airbus A330-200": {
        "layouts": {
            "First": None,
            "Business": [1, 2, 1],
            "Premium Economy": [2, 3, 2],
            "Economy": [2, 4, 2],
        },
        "defaults": {"First": 0, "Business": 20, "Premium Economy": 21, "Economy": 208},
    },
    "Airbus A330-300": {
        "layouts": {
            "First": None,
            "Business": [1, 2, 1],
            "Premium Economy": [2, 3, 2],
            "Economy": [2, 4, 2],
        },
        "defaults": {"First": 0, "Business": 28, "Premium Economy": 24, "Economy": 267},
    },
    "Boeing 767-300ER": {
        "layouts": {
            "First": None,
            "Business": [1, 2, 1],
            "Premium Economy": [2, 3, 2],
            "Economy": [2, 3, 2],
        },
        "defaults": {"First": 0, "Business": 30, "Premium Economy": 21, "Economy": 170},
    },
    "Boeing 747-8": {
        "layouts": {
            "First": [1, 2, 1],
            "Business": [1, 2, 1],
            "Premium Economy": [2, 4, 2],
            "Economy": [3, 4, 3],
        },
        "defaults": {"First": 8, "Business": 48, "Premium Economy": 32, "Economy": 244},
    },
    "Airbus A321neo": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [3, 3],
            "Economy": [3, 3],
        },
        "defaults": {"First": 0, "Business": 16, "Premium Economy": 24, "Economy": 170},
    },
    "Airbus A320": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [3, 3],
            "Economy": [3, 3],
        },
        "defaults": {"First": 0, "Business": 12, "Premium Economy": 18, "Economy": 120},
    },
    "Airbus A320neo": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [3, 3],
            "Economy": [3, 3],
        },
        "defaults": {"First": 0, "Business": 12, "Premium Economy": 18, "Economy": 150},
    },
    "Airbus A321": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [3, 3],
            "Economy": [3, 3],
        },
        "defaults": {"First": 0, "Business": 16, "Premium Economy": 24, "Economy": 160},
    },
    "Airbus A319": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [3, 3],
            "Economy": [3, 3],
        },
        "defaults": {"First": 0, "Business": 8, "Premium Economy": 12, "Economy": 108},
    },
    "Boeing 737 MAX 8": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [3, 3],
            "Economy": [3, 3],
        },
        "defaults": {"First": 0, "Business": 16, "Premium Economy": 18, "Economy": 144},
    },
    "Boeing 737-900ER": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [3, 3],
            "Economy": [3, 3],
        },
        "defaults": {"First": 0, "Business": 16, "Premium Economy": 18, "Economy": 162},
    },
    "Boeing 737-800": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [3, 3],
            "Economy": [3, 3],
        },
        "defaults": {"First": 0, "Business": 12, "Premium Economy": 18, "Economy": 132},
    },
    "Boeing 737-8": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [3, 3],
            "Economy": [3, 3],
        },
        "defaults": {"First": 0, "Business": 12, "Premium Economy": 18, "Economy": 144},
    },
    "Boeing 757-300": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [3, 3],
            "Economy": [3, 3],
        },
        "defaults": {"First": 0, "Business": 24, "Premium Economy": 24, "Economy": 180},
    },
    "Airbus A220-300": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [2, 3],
            "Economy": [2, 3],
        },
        "defaults": {"First": 0, "Business": 12, "Premium Economy": 15, "Economy": 100},
    },
    "Embraer 190": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [2, 2],
            "Economy": [2, 2],
        },
        "defaults": {"First": 0, "Business": 8, "Premium Economy": 12, "Economy": 76},
    },
    "Embraer 175": {
        "layouts": {
            "First": None,
            "Business": [2, 2],
            "Premium Economy": [2, 2],
            "Economy": [2, 2],
        },
        "defaults": {"First": 0, "Business": 8, "Premium Economy": 8, "Economy": 64},
    },
}


def get_aircraft_seat_preset(aircraft_name: str) -> dict:
    if aircraft_name in AIRCRAFT_SEAT_PRESETS:
        return AIRCRAFT_SEAT_PRESETS[aircraft_name]

    name = (aircraft_name or "").lower()
    if "a380" in name:
        return AIRCRAFT_SEAT_PRESETS["Airbus A380-800"]
    if "a350" in name:
        return AIRCRAFT_SEAT_PRESETS["Airbus A350-900"]
    if "777" in name:
        return AIRCRAFT_SEAT_PRESETS["Boeing 777-300ER"]
    if "787-10" in name:
        return AIRCRAFT_SEAT_PRESETS["Boeing 787-10"]
    if "787-9" in name:
        return AIRCRAFT_SEAT_PRESETS["Boeing 787-9"]
    if "787" in name:
        return AIRCRAFT_SEAT_PRESETS["Boeing 787-8"]
    if "767" in name:
        return AIRCRAFT_SEAT_PRESETS["Boeing 767-300ER"]
    if "747" in name:
        return AIRCRAFT_SEAT_PRESETS["Boeing 747-8"]
    if "a330" in name:
        return AIRCRAFT_SEAT_PRESETS["Airbus A330-300"]
    if "a321" in name:
        return AIRCRAFT_SEAT_PRESETS["Airbus A321neo"]
    if "a320" in name:
        return AIRCRAFT_SEAT_PRESETS["Airbus A320neo"]
    if "a319" in name:
        return AIRCRAFT_SEAT_PRESETS["Airbus A319"]
    if "737" in name:
        return AIRCRAFT_SEAT_PRESETS["Boeing 737 MAX 8"]
    if "757" in name:
        return AIRCRAFT_SEAT_PRESETS["Boeing 757-300"]
    if "embraer 175" in name:
        return AIRCRAFT_SEAT_PRESETS["Embraer 175"]
    if "embraer" in name:
        return AIRCRAFT_SEAT_PRESETS["Embraer 190"]
    if "a220" in name:
        return AIRCRAFT_SEAT_PRESETS["Airbus A220-300"]
    return AIRCRAFT_SEAT_PRESETS["Boeing 787-9"]


def seat_letters_for_row(total_seats: int) -> List[str]:
    return SEAT_LETTER_POOL[:total_seats]


def next_seat_row_number(current_row: int) -> int:
    next_row = current_row + 1
    if next_row == 13:
        next_row += 1
    return next_row


def build_row_seat_plan(total_seats: int, seats_per_row: int) -> List[int]:
    full_rows, remainder = divmod(total_seats, seats_per_row)
    if remainder == 0:
        return [seats_per_row] * full_rows

    if full_rows >= 1 and remainder <= max(2, seats_per_row // 2):
        split_total = seats_per_row + remainder
        first_row = math.ceil(split_total / 2)
        second_row = split_total - first_row
        return [seats_per_row] * max(0, full_rows - 1) + [first_row, second_row]

    return [seats_per_row] * full_rows + [remainder]


def seat_block_priority(layout: List[int]) -> List[int]:
    block_count = len(layout)
    if block_count == 1:
        return [0]

    order: List[int] = []
    if block_count % 2 == 1:
        center = block_count // 2
        order.append(center)
        for offset in range(1, center + 1):
            if center - offset >= 0:
                order.append(center - offset)
            if center + offset < block_count:
                order.append(center + offset)
    else:
        left_center = block_count // 2 - 1
        right_center = block_count // 2
        order.extend([left_center, right_center])
        for offset in range(1, block_count):
            if left_center - offset >= 0:
                order.append(left_center - offset)
            if right_center + offset < block_count:
                order.append(right_center + offset)

    return order


def distribute_seats_across_blocks(layout: List[int], row_seat_count: int) -> List[int]:
    if row_seat_count >= sum(layout):
        return layout[:]

    allocation = [0] * len(layout)
    priority = seat_block_priority(layout)

    while sum(allocation) < row_seat_count:
        progress = False
        for block_index in priority:
            if sum(allocation) >= row_seat_count:
                break
            if allocation[block_index] < layout[block_index]:
                allocation[block_index] += 1
                progress = True
        if not progress:
            break

    return allocation


def layout_letter_blocks(layout: List[int]) -> List[List[str]]:
    letters = seat_letters_for_row(sum(layout))
    blocks: List[List[str]] = []
    cursor = 0
    for block_size in layout:
        blocks.append(letters[cursor:cursor + block_size])
        cursor += block_size
    return blocks


def choose_letters_for_block(block_letters: List[str], count: int, block_index: int, total_blocks: int) -> List[str]:
    if count <= 0:
        return []
    if count >= len(block_letters):
        return block_letters[:]
    if block_index == 0:
        return block_letters[:count]
    if block_index == total_blocks - 1:
        return block_letters[-count:]
    start = max(0, (len(block_letters) - count) // 2)
    return block_letters[start:start + count]




def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


@dataclass(frozen=True)
class RouteFuelAircraft:
    code: str
    range_nmi: float
    fuel_capacity_l: float
    reference_payload_kg: float
    payload_sensitivity_per_10t: float = 0.03


JET_FUEL_DENSITY_KG_PER_L = 0.80
STANDARD_PASSENGER_WEIGHT_KG = 84.0
FIXED_TAXI_FUEL_KG = 500.0
FIXED_TAXI_FUEL_L = FIXED_TAXI_FUEL_KG / JET_FUEL_DENSITY_KG_PER_L
DEFAULT_ROUTE_WIND_FACTOR = 0.00
DEFAULT_FUEL_SAFETY_MARGIN = 0.03
LONG_HAUL_EFFICIENCY_START_NMI = 4500.0
LONG_HAUL_EFFICIENCY_FULL_NMI = 6500.0
LONG_HAUL_MAX_EFFICIENCY_DISCOUNT = 0.075


ROUTE_FUEL_DATABASE: Dict[str, RouteFuelAircraft] = {
    "A220-300": RouteFuelAircraft("A220-300", 3400.0, 21918.0, 13000.0),
    "A320-200": RouteFuelAircraft("A320-200", 3347.7, 27200.0, 17000.0),
    "A321-200": RouteFuelAircraft("A321-200", 3212.7, 30030.0, 21000.0),
    "A321neo": RouteFuelAircraft("A321neo", 4000.0, 32940.0, 21500.0),
    "A330-200": RouteFuelAircraft("A330-200", 7262.0, 139090.0, 39000.0),
    "A330-300": RouteFuelAircraft("A330-300", 7262.0, 139090.0, 40000.0),
    "A330-800": RouteFuelAircraft("A330-800", 8099.0, 139090.0, 40000.0),
    "A330-900": RouteFuelAircraft("A330-900", 7200.0, 139090.0, 45000.0),
    "A340-600": RouteFuelAircraft("A340-600", 7900.0, 195880.0, 54000.0),
    "A350-900": RouteFuelAircraft("A350-900", 8500.0, 166488.0, 45000.0),
    "A350-1000": RouteFuelAircraft("A350-1000", 8700.0, 164000.0, 52000.0),
    "A380-800": RouteFuelAircraft("A380-800", 8000.0, 320000.0, 65000.0),
    "B737-8MAX": RouteFuelAircraft("B737-8MAX", 3550.0, 26020.0, 18000.0),
    "B747-8": RouteFuelAircraft("B747-8", 7730.0, 238610.0, 76000.0),
    "B747-200": RouteFuelAircraft("B747-200", 6100.0, 157560.0, 68000.0),
    "B757-200": RouteFuelAircraft("B757-200", 3915.0, 43490.0, 29000.0),
    "B777-200ER": RouteFuelAircraft("B777-200ER", 7500.0, 171170.0, 42000.0),
    "B777-300ER": RouteFuelAircraft("B777-300ER", 7370.0, 181280.0, 44000.0),
    "B787-9": RouteFuelAircraft("B787-9", 7565.0, 126356.0, 36000.0),
    "B787-10": RouteFuelAircraft("B787-10", 6430.0, 126356.0, 43000.0),
}


@dataclass
class RouteFuelPlanResult:
    route_distance_nmi: float
    effective_distance_nmi: float
    actual_payload_kg: float
    payload_factor: float
    base_trip_fuel_l: float
    corrected_trip_fuel_l: float
    planned_fuel_l: float
    base_trip_fuel_kg: float
    corrected_trip_fuel_kg: float
    planned_fuel_kg: float
    planning_margin_l: float
    planning_margin_kg: float
    long_haul_efficiency_factor: float
    climb_fuel_l: float
    cruise_fuel_l: float
    descent_fuel_l: float
    climb_fuel_kg: float
    cruise_fuel_kg: float
    descent_fuel_kg: float
    taxi_fuel_l: float
    taxi_fuel_kg: float
    ete_hours: float
    burn_coefficient_l_per_nmi: float
    fuel_capacity_l: float
    fuel_capacity_kg: float
    remaining_capacity_l: float
    exceeds_capacity: bool
    safety_margin_percent: float


ROUTE_FUEL_FALLBACK_RANGE_NM = {
    "A220-300": 3400.0,
    "A320-200": 3348.0,
    "A321-200": 3213.0,
    "A321neo": 4000.0,
    "A330-200": 7262.0,
    "A330-300": 7262.0,
    "A330-800": 8099.0,
    "A330-900": 7200.0,
    "A340-600": 7900.0,
    "A350-900": 8500.0,
    "A350-1000": 8700.0,
    "A380-800": 8000.0,
    "B737-8MAX": 3550.0,
    "B747-8": 7730.0,
    "B747-200": 6100.0,
    "B757-200": 3915.0,
    "B777-200ER": 7500.0,
    "B777-300ER": 7370.0,
    "B787-9": 7565.0,
    "B787-10": 6430.0,
}


def route_fuel_reference_payload_from_library(canonical: str, lib: dict) -> float:
    name = str(lib.get("name", canonical)).lower()
    mtow = float(lib.get("mtow", 0.0) or 0.0)
    oew = float(lib.get("oew", 0.0) or 0.0)
    if mtow > 0 and oew > 0:
        return max(12000.0, min(76000.0, (mtow - oew) * 0.32))
    if "a380" in name or "747" in name:
        return 65000.0
    if "777" in name or "350" in name or "340" in name:
        return 50000.0
    if "330" in name or "787" in name:
        return 40000.0
    if "321" in name or "757" in name:
        return 23000.0
    return 18000.0


def build_fallback_route_fuel_aircraft(canonical: str, lib: dict) -> Optional[RouteFuelAircraft]:
    if not canonical or not lib:
        return None

    fuel_burn_kg_hr = float(lib.get("fuel_burn", 0.0) or 0.0)
    if fuel_burn_kg_hr <= 0:
        return None

    takeoff_fuel = resolve_takeoff_fuel_config(canonical)
    cruise_gs_kt = max(float(takeoff_fuel.cruise_gs_kt_default or 450.0), 350.0)
    range_nmi = float(ROUTE_FUEL_FALLBACK_RANGE_NM.get(canonical, 0.0) or 0.0)
    if range_nmi <= 0:
        name = str(lib.get("name", canonical)).lower()
        if "a380" in name:
            range_nmi = 8000.0
        elif "a350" in name or "787" in name or "777" in name or "a340" in name:
            range_nmi = 7400.0
        elif "a330" in name or "747" in name:
            range_nmi = 6200.0
        elif "757" in name or "a321" in name:
            range_nmi = 3900.0
        elif "737" in name or "a320" in name or "a220" in name:
            range_nmi = 3400.0
        else:
            range_nmi = 4500.0

    estimated_capacity_kg = (fuel_burn_kg_hr * (range_nmi / cruise_gs_kt)) * 1.10

    mtow = float(lib.get("mtow", 0.0) or 0.0)
    oew = float(lib.get("oew", 0.0) or 0.0)
    if mtow > 0 and oew > 0:
        reference_payload = route_fuel_reference_payload_from_library(canonical, lib)
        max_structural_fuel_kg = max(0.0, mtow - oew - reference_payload * 0.55)
        if max_structural_fuel_kg > 0:
            estimated_capacity_kg = min(max(estimated_capacity_kg, fuel_burn_kg_hr * 1.5), max_structural_fuel_kg * 1.05)

    estimated_capacity_l = max(10000.0, estimated_capacity_kg / JET_FUEL_DENSITY_KG_PER_L)
    reference_payload_kg = route_fuel_reference_payload_from_library(canonical, lib)
    return RouteFuelAircraft(canonical, range_nmi, estimated_capacity_l, reference_payload_kg)


def resolve_route_fuel_aircraft(aircraft_name: str) -> Optional[RouteFuelAircraft]:
    canonical = canonical_aircraft_name(aircraft_name)
    if not canonical:
        return None

    exact = ROUTE_FUEL_DATABASE.get(canonical)
    if exact:
        return exact

    compatibility_aliases = {
        "A350-900-LH100": "A350-900",
        "A340-600": "A340-300",
        "B737-8MAX": "B737-800",
        "B787-10": "B787-9",
        "A350-1000": "A350-900",
        "A321neo": "A321-200",
    }
    fallback_key = compatibility_aliases.get(canonical)
    if fallback_key and fallback_key in ROUTE_FUEL_DATABASE:
        base = ROUTE_FUEL_DATABASE[fallback_key]
        lib = get_library_aircraft(canonical) or {}
        return RouteFuelAircraft(
            canonical,
            base.range_nmi,
            base.fuel_capacity_l,
            route_fuel_reference_payload_from_library(canonical, lib) if lib else base.reference_payload_kg,
            base.payload_sensitivity_per_10t,
        )

    lib = get_library_aircraft(canonical)
    return build_fallback_route_fuel_aircraft(canonical, lib or {})


def audit_route_fuel_database() -> Dict[str, List[str]]:
    missing = []
    fallback_only = []
    for aircraft_key in AIRCRAFT_LIBRARY:
        if aircraft_key not in ROUTE_FUEL_DATABASE:
            fallback_only.append(aircraft_key)
        if resolve_route_fuel_aircraft(aircraft_key) is None:
            missing.append(aircraft_key)
    return {"missing": missing, "fallback_only": fallback_only}


def route_long_haul_efficiency_factor(distance_nm: float) -> float:
    """Gently reduce the old range/fuel-capacity estimate on very long sectors."""
    distance_nm = max(float(distance_nm or 0.0), 0.0)
    if distance_nm <= LONG_HAUL_EFFICIENCY_START_NMI:
        return 1.0
    span = max(LONG_HAUL_EFFICIENCY_FULL_NMI - LONG_HAUL_EFFICIENCY_START_NMI, 1.0)
    progress = clamp((distance_nm - LONG_HAUL_EFFICIENCY_START_NMI) / span, 0.0, 1.0)
    return 1.0 - (LONG_HAUL_MAX_EFFICIENCY_DISCOUNT * progress)


def route_fuel_ete_hours(aircraft_name: str, distance_nm: float) -> float:
    speed = resolve_takeoff_fuel_config(aircraft_name).cruise_gs_kt_default if aircraft_name else 450.0
    return distance_nm * (1.0 + DEFAULT_ROUTE_WIND_FACTOR) / max(float(speed or 450.0), 1.0)


def compute_route_fuel_plan(
    aircraft_name: str,
    distance_nm: float,
    passengers: int,
    baggage_kg: float,
    cargo_kg: float,
) -> Optional[RouteFuelPlanResult]:
    aircraft = resolve_route_fuel_aircraft(aircraft_name)
    distance_nm = max(float(distance_nm or 0.0), 0.0)
    if not aircraft or distance_nm <= 0:
        return None

    effective_distance_nmi = distance_nm * (1.0 + DEFAULT_ROUTE_WIND_FACTOR)
    actual_payload_kg = (
        max(int(passengers or 0), 0) * STANDARD_PASSENGER_WEIGHT_KG
        + max(float(baggage_kg or 0.0), 0.0)
        + max(float(cargo_kg or 0.0), 0.0)
    )

    payload_factor = 1.0 + aircraft.payload_sensitivity_per_10t * ((actual_payload_kg - aircraft.reference_payload_kg) / 10000.0)
    payload_factor = clamp(payload_factor, 0.85, 1.20)

    burn_coefficient_l_per_nmi = aircraft.fuel_capacity_l / aircraft.range_nmi
    base_trip_fuel_l = aircraft.fuel_capacity_l * (effective_distance_nmi / aircraft.range_nmi)
    long_haul_efficiency_factor = route_long_haul_efficiency_factor(effective_distance_nmi)
    corrected_trip_fuel_l = base_trip_fuel_l * payload_factor * long_haul_efficiency_factor
    planning_margin_l = corrected_trip_fuel_l * DEFAULT_FUEL_SAFETY_MARGIN
    planned_fuel_l = corrected_trip_fuel_l + planning_margin_l + FIXED_TAXI_FUEL_L

    climb_fuel_l = corrected_trip_fuel_l * 0.10
    cruise_fuel_l = corrected_trip_fuel_l * 0.86
    descent_fuel_l = corrected_trip_fuel_l * 0.04

    base_trip_fuel_kg = base_trip_fuel_l * JET_FUEL_DENSITY_KG_PER_L
    corrected_trip_fuel_kg = corrected_trip_fuel_l * JET_FUEL_DENSITY_KG_PER_L
    planned_fuel_kg = planned_fuel_l * JET_FUEL_DENSITY_KG_PER_L
    planning_margin_kg = planning_margin_l * JET_FUEL_DENSITY_KG_PER_L
    climb_fuel_kg = climb_fuel_l * JET_FUEL_DENSITY_KG_PER_L
    cruise_fuel_kg = cruise_fuel_l * JET_FUEL_DENSITY_KG_PER_L
    descent_fuel_kg = descent_fuel_l * JET_FUEL_DENSITY_KG_PER_L
    fuel_capacity_kg = aircraft.fuel_capacity_l * JET_FUEL_DENSITY_KG_PER_L
    remaining_capacity_l = aircraft.fuel_capacity_l - planned_fuel_l

    ete_hours = route_fuel_ete_hours(aircraft_name, distance_nm)

    return RouteFuelPlanResult(
        route_distance_nmi=distance_nm,
        effective_distance_nmi=effective_distance_nmi,
        actual_payload_kg=actual_payload_kg,
        payload_factor=payload_factor,
        base_trip_fuel_l=base_trip_fuel_l,
        corrected_trip_fuel_l=corrected_trip_fuel_l,
        planned_fuel_l=planned_fuel_l,
        base_trip_fuel_kg=base_trip_fuel_kg,
        corrected_trip_fuel_kg=corrected_trip_fuel_kg,
        planned_fuel_kg=planned_fuel_kg,
        planning_margin_l=planning_margin_l,
        planning_margin_kg=planning_margin_kg,
        long_haul_efficiency_factor=long_haul_efficiency_factor,
        climb_fuel_l=climb_fuel_l,
        cruise_fuel_l=cruise_fuel_l,
        descent_fuel_l=descent_fuel_l,
        climb_fuel_kg=climb_fuel_kg,
        cruise_fuel_kg=cruise_fuel_kg,
        descent_fuel_kg=descent_fuel_kg,
        taxi_fuel_l=FIXED_TAXI_FUEL_L,
        taxi_fuel_kg=FIXED_TAXI_FUEL_KG,
        ete_hours=ete_hours,
        burn_coefficient_l_per_nmi=burn_coefficient_l_per_nmi,
        fuel_capacity_l=aircraft.fuel_capacity_l,
        fuel_capacity_kg=fuel_capacity_kg,
        remaining_capacity_l=remaining_capacity_l,
        exceeds_capacity=planned_fuel_l > aircraft.fuel_capacity_l,
        safety_margin_percent=DEFAULT_FUEL_SAFETY_MARGIN * 100.0,
    )


@dataclass(frozen=True)
class LandingAircraftConfig:
    name: str
    mlw_kg: float
    flap_options: List[str]
    wing_area_m2: float
    clmax_by_flap: Dict[str, float]
    landing_distance_ref_m: float
    reference_weight_kg: float
    vref_reference_by_flap: Dict[str, int] = field(default_factory=dict)


LANDING_CONFIGS = {
    "A320_FAMILY": LandingAircraftConfig(
        name="Airbus A320 Family",
        mlw_kg=66000,
        flap_options=["3", "FULL"],
        wing_area_m2=122.6,
        clmax_by_flap={"3": 2.35, "FULL": 2.55},
        landing_distance_ref_m=1500,
        reference_weight_kg=66000,
        vref_reference_by_flap={"FULL": 130, "3": 135, "2": 140},
    ),
    "A321_FAMILY": LandingAircraftConfig(
        name="Airbus A321 Family",
        mlw_kg=77800,
        flap_options=["3", "FULL"],
        wing_area_m2=122.6,
        clmax_by_flap={"3": 2.35, "FULL": 2.55},
        landing_distance_ref_m=1600,
        reference_weight_kg=77800,
        vref_reference_by_flap={"FULL": 135, "3": 140, "2": 145},
    ),
    "A321_NEO": LandingAircraftConfig(
        name="Airbus A321neo",
        mlw_kg=79200,
        flap_options=["3", "FULL"],
        wing_area_m2=122.6,
        clmax_by_flap={"3": 2.35, "FULL": 2.55},
        landing_distance_ref_m=1600,
        reference_weight_kg=79200,
        vref_reference_by_flap={"FULL": 137, "3": 142},
    ),
    "A220": LandingAircraftConfig(
        name="Airbus A220-300",
        mlw_kg=61000,
        flap_options=["3", "FULL"],
        wing_area_m2=112.3,
        clmax_by_flap={"3": 2.28, "FULL": 2.45},
        landing_distance_ref_m=1380,
        reference_weight_kg=61000,
        vref_reference_by_flap={"FULL": 132, "3": 137},
    ),
    "A330": LandingAircraftConfig(
        name="Airbus A330",
        mlw_kg=187000,
        flap_options=["3", "FULL"],
        wing_area_m2=361.6,
        clmax_by_flap={"3": 2.25, "FULL": 2.40},
        landing_distance_ref_m=1800,
        reference_weight_kg=187000,
        vref_reference_by_flap={"FULL": 138, "3": 143, "2": 148},
    ),
    "A350": LandingAircraftConfig(
        name="Airbus A350",
        mlw_kg=220000,
        flap_options=["3", "FULL"],
        wing_area_m2=442.0,
        clmax_by_flap={"3": 2.30, "FULL": 2.45},
        landing_distance_ref_m=1700,
        reference_weight_kg=205000,
        vref_reference_by_flap={"FULL": 135, "3": 140, "2": 145},
    ),
    "A380": LandingAircraftConfig(
        name="Airbus A380-800",
        mlw_kg=391000,
        flap_options=["3", "FULL"],
        wing_area_m2=845.0,
        clmax_by_flap={"3": 2.20, "FULL": 2.35},
        landing_distance_ref_m=2100,
        reference_weight_kg=394000,
        vref_reference_by_flap={"FULL": 140, "3": 145},
    ),
    "B737": LandingAircraftConfig(
        name="Boeing 737 Family",
        mlw_kg=66360,
        flap_options=["25", "30", "40"],
        wing_area_m2=124.6,
        clmax_by_flap={"25": 2.15, "30": 2.30, "40": 2.45},
        landing_distance_ref_m=1600,
        reference_weight_kg=66360,
        vref_reference_by_flap={"40": 130, "30": 137, "25": 142},
    ),
    "B747": LandingAircraftConfig(
        name="Boeing 747 Family",
        mlw_kg=295740,
        flap_options=["25", "30"],
        wing_area_m2=554.0,
        clmax_by_flap={"25": 2.10, "30": 2.25},
        landing_distance_ref_m=2200,
        reference_weight_kg=295740,
        vref_reference_by_flap={"30": 145, "25": 150},
    ),
    "B757": LandingAircraftConfig(
        name="Boeing 757-300",
        mlw_kg=101150,
        flap_options=["25", "30"],
        wing_area_m2=185.3,
        clmax_by_flap={"25": 2.18, "30": 2.30},
        landing_distance_ref_m=1620,
        reference_weight_kg=101150,
        vref_reference_by_flap={"30": 138, "25": 143},
    ),
    "B767": LandingAircraftConfig(
        name="Boeing 767-300ER",
        mlw_kg=145150,
        flap_options=["25", "30"],
        wing_area_m2=283.3,
        clmax_by_flap={"25": 2.20, "30": 2.32},
        landing_distance_ref_m=1680,
        reference_weight_kg=145150,
        vref_reference_by_flap={"30": 136, "25": 141},
    ),
    "B777": LandingAircraftConfig(
        name="Boeing 777 Family",
        mlw_kg=251290,
        flap_options=["25", "30"],
        wing_area_m2=427.8,
        clmax_by_flap={"25": 2.95, "30": 3.10},
        landing_distance_ref_m=1900,
        reference_weight_kg=251290,
        vref_reference_by_flap={"30": 140, "25": 145},
    ),
    "B787": LandingAircraftConfig(
        name="Boeing 787 Family",
        mlw_kg=192780,
        flap_options=["20", "25", "30"],
        wing_area_m2=377.0,
        clmax_by_flap={"20": 2.10, "25": 2.25, "30": 2.38},
        landing_distance_ref_m=1700,
        reference_weight_kg=192780,
        vref_reference_by_flap={"30": 135, "25": 140, "20": 145},
    ),
    "E190": LandingAircraftConfig(
        name="Embraer 190",
        mlw_kg=43000,
        flap_options=["4", "FULL"],
        wing_area_m2=92.5,
        clmax_by_flap={"4": 2.12, "FULL": 2.25},
        landing_distance_ref_m=1320,
        reference_weight_kg=43000,
        vref_reference_by_flap={"FULL": 123, "4": 128},
    ),
    "E175": LandingAircraftConfig(
        name="Embraer 175",
        mlw_kg=34000,
        flap_options=["4", "FULL"],
        wing_area_m2=70.6,
        clmax_by_flap={"4": 2.08, "FULL": 2.22},
        landing_distance_ref_m=1240,
        reference_weight_kg=34000,
        vref_reference_by_flap={"FULL": 118, "4": 123},
    ),
}


@dataclass
class LandingInputs:
    aircraft_name: str
    landing_weight_kg: float
    elevation_ft: float
    oat_c: float
    qnh_hpa: float
    wind_from_deg: int
    wind_speed_kt: float
    runway_heading_deg: int
    surface_condition: str
    flap_setting: str
    autobrake_mode: str = "MED"
    reverse_enabled: bool = True
    wind_gust_kt: float = 0.0
    lda_m: Optional[float] = None
    obstacle_height_ft: float = 50.0
    current_altitude_ft: Optional[float] = None
    distance_to_go_nm: Optional[float] = None
    planned_ground_speed_kt: Optional[float] = None


@dataclass
class LandingResultData:
    aircraft_name: str
    flap_setting: str
    vs_landing_kt: int
    vref_kt: int
    vapp_kt: int
    additive_kt: int
    landing_distance_m: int
    pressure_altitude_ft: int
    density_altitude_ft: int
    isa_temperature_c: float
    isa_deviation_c: float
    sigma: float
    headwind_kt: int
    headwind_gust_kt: int
    crosswind_kt: int
    mlw_kg: int
    weight_ratio: float
    altitude_to_lose_ft: int
    tod_distance_nm: float
    distance_to_go_nm: float
    suggested_vs_fpm: int
    estimated_descent_time_min: float
    profile_status: str
    braking_summary: str
    lda_margin_m: Optional[int] = None
    warnings: List[str] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)


def resolve_landing_aircraft_config(aircraft_name: str) -> LandingAircraftConfig:
    name = (aircraft_name or "").lower()
    if "a321neo" in name or "a321 neo" in name:
        base = LANDING_CONFIGS["A321_NEO"]
    elif "a321" in name:
        base = LANDING_CONFIGS["A321_FAMILY"]
    elif "a320" in name or "a319" in name:
        base = LANDING_CONFIGS["A320_FAMILY"]
    elif "a220" in name:
        base = LANDING_CONFIGS["A220"]
    elif "a330" in name or "a340" in name:
        base = LANDING_CONFIGS["A330"]
    elif "a350" in name:
        base = LANDING_CONFIGS["A350"]
    elif "a380" in name:
        base = LANDING_CONFIGS["A380"]
    elif "747" in name:
        base = LANDING_CONFIGS["B747"]
    elif "757" in name or "767" in name:
        base = LANDING_CONFIGS["B757"]
    elif "777" in name:
        base = LANDING_CONFIGS["B777"]
    elif "787" in name:
        base = LANDING_CONFIGS["B787"]
    elif "737" in name:
        base = LANDING_CONFIGS["B737"]
    elif "embraer 175" in name:
        base = LANDING_CONFIGS["E175"]
    elif "embraer" in name:
        base = LANDING_CONFIGS["E190"]
    else:
        base = LANDING_CONFIGS["B787"]
    lib = get_library_aircraft(aircraft_name)
    if not lib:
        return base
    flap_options = list(lib.get("land_flaps", base.flap_options))
    fallback_cl = list(base.clmax_by_flap.values())[-1]
    clmax_by_flap = {flap: base.clmax_by_flap.get(flap, fallback_cl) for flap in flap_options}
    return LandingAircraftConfig(
        name=lib.get("name", base.name),
        mlw_kg=float(lib.get("mlw", base.mlw_kg)),
        flap_options=flap_options,
        wing_area_m2=base.wing_area_m2,
        clmax_by_flap=clmax_by_flap,
        landing_distance_ref_m=float(lib.get("land_roll", base.landing_distance_ref_m)),
        reference_weight_kg=float(lib.get("mlw", base.reference_weight_kg)),
        vref_reference_by_flap={str(k): int(v) for k, v in lib.get("vref_speeds", base.vref_reference_by_flap).items()},
    )


def fetch_landing_metar(icao: str) -> Optional[TakeoffMetarData]:
    return fetch_takeoff_metar(icao)


def compute_landing_performance(inputs: LandingInputs) -> LandingResultData:
    ac = resolve_landing_aircraft_config(inputs.aircraft_name)
    flap_setting = inputs.flap_setting if inputs.flap_setting in ac.clmax_by_flap else ac.flap_options[0]
    surface = (inputs.surface_condition or "DRY").upper()
    surface_factor = LANDING_SURFACE_FACTORS.get(surface, 1.0)
    autobrake_mode = (inputs.autobrake_mode or "MED").upper()
    autobrake_factor = LANDING_AUTOBRAKE_FACTORS.get(autobrake_mode, 0.98)

    elevation_ft = float(inputs.elevation_ft)
    isa_temp_c = 15.0 - 0.0019812 * elevation_ft
    isa_deviation_c = float(inputs.oat_c) - isa_temp_c
    pressure_altitude_ft = elevation_ft + (1013.25 - float(inputs.qnh_hpa)) * 30.0
    density_altitude_ft = pressure_altitude_ft + 120.0 * isa_deviation_c

    sigma = density_ratio_from_density_altitude_ft(density_altitude_ft)
    rho = 1.225 * sigma

    delta_deg = normalize_angle_diff_deg(float(inputs.wind_from_deg), float(inputs.runway_heading_deg))
    delta_rad = math.radians(delta_deg)
    headwind_kt = float(inputs.wind_speed_kt) * math.cos(delta_rad)
    crosswind_kt = abs(float(inputs.wind_speed_kt) * math.sin(delta_rad))

    gust_speed_kt = max(float(inputs.wind_gust_kt or 0.0), float(inputs.wind_speed_kt or 0.0))
    headwind_gust_kt = gust_speed_kt * math.cos(delta_rad)

    mass_kg = float(inputs.landing_weight_kg)
    weight_n = mass_kg * G
    wing_area = ac.wing_area_m2
    clmax = ac.clmax_by_flap[flap_setting]
    vs_mps = math.sqrt((2.0 * weight_n) / (rho * wing_area * clmax))
    vs_kt = vs_mps * MPS_TO_KTS

    ref_weight_kg = ac.reference_weight_kg or ac.mlw_kg
    weight_ratio = mass_kg / ref_weight_kg if ref_weight_kg > 0 else 1.0
    base_vref_kt = ac.vref_reference_by_flap.get(flap_setting, list(ac.vref_reference_by_flap.values())[0])
    wt_ratio_for_speed = math.sqrt(max(mass_kg, 1.0) / max(ac.mlw_kg, 1.0)) if mass_kg < ac.mlw_kg else 1.1
    vref_kt = base_vref_kt * wt_ratio_for_speed
    gust_additive_kt = 0.5 * max(0.0, float(inputs.wind_gust_kt or 0.0) - float(inputs.wind_speed_kt or 0.0))
    additive_kt = min(max(5.0, gust_additive_kt), 20.0)
    vapp_kt = vref_kt + additive_kt
    vs_kt, vref_kt, vapp_kt, additive_kt = validate_landing_speeds(vs_kt, vref_kt, vapp_kt, additive_kt)
    density_factor = 1.0 + max(density_altitude_ft, 0.0) / 30000.0
    if headwind_kt >= 0:
        wind_factor = max(0.82, 1.0 - headwind_kt * 0.005)
    else:
        wind_factor = 1.0 + abs(headwind_kt) * 0.03
    obstacle_factor = 1.0 + max(float(inputs.obstacle_height_ft or 50.0) - 50.0, 0.0) / 500.0
    reverse_factor = 0.96 if inputs.reverse_enabled else 1.00
    if surface == "CONTAMINATED" and not inputs.reverse_enabled:
        reverse_factor *= 1.04
    speed_factor = max(1.0, (vapp_kt / max(vref_kt, 1.0)) ** 1.3)

    landing_distance_m = ac.landing_distance_ref_m
    landing_distance_m *= max(wt_ratio_for_speed, 0.70) * 1.10
    landing_distance_m *= surface_factor * autobrake_factor * reverse_factor * density_factor * wind_factor * obstacle_factor * speed_factor
    landing_distance_m = max(850.0, landing_distance_m)

    target_alt_ft = elevation_ft
    current_alt_ft = float(inputs.current_altitude_ft) if inputs.current_altitude_ft is not None else target_alt_ft
    current_alt_ft = max(current_alt_ft, target_alt_ft)
    alt_to_lose_ft = max(0.0, current_alt_ft - target_alt_ft)
    tod_distance_nm = max(0.0, (alt_to_lose_ft / 1000.0) * 3.0)

    distance_to_go_nm = float(inputs.distance_to_go_nm) if inputs.distance_to_go_nm is not None else 0.0
    used_ground_speed_kt = float(inputs.planned_ground_speed_kt) if inputs.planned_ground_speed_kt is not None else max(vapp_kt + 20.0, 140.0)
    planning_distance_nm = distance_to_go_nm if distance_to_go_nm > 0 else tod_distance_nm
    estimated_time_min = (planning_distance_nm / used_ground_speed_kt) * 60.0 if planning_distance_nm > 0 and used_ground_speed_kt > 0 else 0.0
    suggested_vs_fpm = int(round(alt_to_lose_ft / max(estimated_time_min, 0.1))) if alt_to_lose_ft > 0 and estimated_time_min > 0 else 0

    if alt_to_lose_ft <= 0:
        profile_status = "At or below target altitude."
    elif distance_to_go_nm <= 0:
        profile_status = f"Rule-of-thumb TOD is {tod_distance_nm:.1f} NM."
    else:
        delta_nm = distance_to_go_nm - tod_distance_nm
        if delta_nm < -1.0:
            profile_status = "High on profile. Start descent now."
        elif delta_nm > 1.0:
            profile_status = "Low on profile. Descent can start later."
        else:
            profile_status = "On profile."

    warnings: List[str] = []
    cautions: List[str] = []

    if crosswind_kt > 25:
        warnings.append(f"XWIND {int(round(crosswind_kt))}KT EXCEEDS LIMIT")
    elif crosswind_kt > 15:
        cautions.append(f"XWIND {int(round(crosswind_kt))}KT")

    if headwind_kt < -10:
        warnings.append(f"TAILWIND {int(round(abs(headwind_kt)))}KT")
    elif headwind_kt < -5:
        cautions.append(f"TAILWIND {int(round(abs(headwind_kt)))}KT")

    if gust_speed_kt > inputs.wind_speed_kt:
        if headwind_kt < 0 and headwind_gust_kt < headwind_kt:
            cautions.append(f"GUSTS INCREASE TAILWIND TO {int(round(abs(headwind_gust_kt)))}KT")
        elif headwind_kt >= 0 and headwind_gust_kt > headwind_kt + 3:
            cautions.append(f"GUSTS INCREASE HEADWIND TO {int(round(headwind_gust_kt))}KT")

    if density_altitude_ft > 8000:
        warnings.append(f"HIGH DA {int(round(density_altitude_ft))}FT")
    elif density_altitude_ft > 4000:
        cautions.append(f"DA {int(round(density_altitude_ft))}FT")

    if mass_kg > ac.mlw_kg:
        warnings.append("EXCEEDS MLW")
    elif mass_kg > ac.mlw_kg * 0.97:
        cautions.append("NEAR MLW")

    if suggested_vs_fpm > 3000:
        warnings.append(f"DESCENT RATE {suggested_vs_fpm} FPM")
    elif suggested_vs_fpm > 2000:
        cautions.append(f"DESCENT RATE {suggested_vs_fpm} FPM")

    if surface == "CONTAMINATED":
        warnings.append("CONTAMINATED RUNWAY")
    elif surface == "WET":
        cautions.append("WET RUNWAY")

    lda_margin_m = None
    if inputs.lda_m is not None and inputs.lda_m > 0:
        lda_margin_m = int(round(inputs.lda_m - landing_distance_m))
        if landing_distance_m > inputs.lda_m:
            warnings.append(f"LDA LIMIT EXCEEDED ({int(round(landing_distance_m))}m > {int(round(inputs.lda_m))}m)")

    braking_summary = f"Surface {surface} • Autobrake {autobrake_mode} • Reverse {'ON' if inputs.reverse_enabled else 'OFF'}"

    return LandingResultData(
        aircraft_name=ac.name,
        flap_setting=flap_setting,
        vs_landing_kt=int(round(vs_kt)),
        vref_kt=int(round(vref_kt)),
        vapp_kt=int(round(vapp_kt)),
        additive_kt=int(round(additive_kt)),
        landing_distance_m=int(round(landing_distance_m)),
        pressure_altitude_ft=int(round(pressure_altitude_ft)),
        density_altitude_ft=int(round(density_altitude_ft)),
        isa_temperature_c=round(isa_temp_c, 1),
        isa_deviation_c=round(isa_deviation_c, 1),
        sigma=round(sigma, 4),
        headwind_kt=int(round(headwind_kt)),
        headwind_gust_kt=int(round(headwind_gust_kt)),
        crosswind_kt=int(round(crosswind_kt)),
        mlw_kg=int(round(ac.mlw_kg)),
        weight_ratio=round(mass_kg / ac.mlw_kg, 3) if ac.mlw_kg > 0 else 0.0,
        altitude_to_lose_ft=int(round(alt_to_lose_ft)),
        tod_distance_nm=round(tod_distance_nm, 1),
        distance_to_go_nm=round(distance_to_go_nm, 1),
        suggested_vs_fpm=int(round(suggested_vs_fpm)),
        estimated_descent_time_min=round(estimated_time_min, 1),
        profile_status=profile_status,
        braking_summary=braking_summary,
        lda_margin_m=lda_margin_m,
        warnings=warnings,
        cautions=cautions,
    )


def mark_calendar_entry_completed(
    entries: List[dict],
    entry_id: str,
    completed_at: Optional[datetime] = None,
) -> bool:
    """Mark one planned calendar entry complete without altering its flight details."""
    if not entry_id:
        return False
    timestamp = (completed_at or datetime.now()).isoformat(timespec="seconds")
    for entry in entries:
        if str(entry.get("id") or "") != str(entry_id):
            continue
        if bool(entry.get("completed")):
            return False
        entry["completed"] = True
        entry["completed_at"] = timestamp
        entry["updated_at"] = timestamp
        entry["completion_source"] = "calendar_agenda"
        return True
    return False


def index_calendar_entries_by_date(entries: List[dict]) -> Dict[str, List[dict]]:
    """Group calendar entries once so month cells do not repeatedly scan the full log."""
    indexed: Dict[str, List[dict]] = {}
    for entry in entries:
        date_key = str(entry.get("date") or "").strip()
        if date_key:
            indexed.setdefault(date_key, []).append(entry)
    return indexed


def main(page: ft.Page):
    state = AppState()
    live_map_process = None
    live_map_child = None
    live_map_visible = False
    live_map_unavailable = False
    dashboard_airport_process = None
    dashboard_airport_unavailable = False
    dashboard_remarks_dialog = None
    tutorial_dialog = None
    page_guides = {
        1: ("Dashboard", "Choose your departure, arrival, airline, and aircraft to start planning. Set gates and terminals and review the estimated flight time in the Flight Plan."),
        0: ("Overview", "Review your route, estimated arrival, and flight progress. Switch to Live Flights to browse and follow aircraft on Infinite Flight."),
        2: ("Payload", "Set cabin capacity and occupancy, then enter baggage and cargo weights. The seat map shows occupied and available seats."),
        13: ("Checklist", "Work through the preflight and in-flight checklists. Select an item to mark it complete."),
        4: ("Takeoff", "Review departure weather, calculate takeoff speeds, and use Fuel Planning to estimate fuel and flight time."),
        5: ("Landing", "Review arrival weather, calculate approach speeds, and use the descent calculator to plan your approach."),
        7: ("Calendar", "Schedule flights, review saved plans, and mark flights complete to add them to the log."),
        8: ("Log", "Open a completed flight to review its boarding pass and record landing G. Sort your log by date or landing G."),
        9: ("Profile", "Review your pilot information, flight hours, and career statistics."),
        10: ("Settings", "Manage display, sound, planning units, and your Infinite Flight API key. You can also import or export your data here."),
        11: ("About", "Find the FMS version, data folder, image credits, and simulator-use disclaimer."),
    }
    base_dir = Path(__file__).resolve().parent
    if _INTERFACE_PREVIEW:
        preview_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else base_dir / "dist" / "Interface Preview"
        storage_dir = preview_dir / "Preview Data"
        storage_dir.mkdir(parents=True, exist_ok=True)
    else:
        local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        storage_dir = local_app_data / "Flight Management Systems Public"
        storage_dir.mkdir(parents=True, exist_ok=True)

    storage_file_names = (
        "calendar_flights.json",
        "profile_data.json",
        "app_settings.json",
        "flight_hibernation.json",
    )
    if storage_dir != base_dir and not _INTERFACE_PREVIEW:
        for storage_file_name in storage_file_names:
            legacy_path = base_dir / storage_file_name
            current_path = storage_dir / storage_file_name
            if legacy_path.exists() and not current_path.exists():
                try:
                    shutil.copy2(legacy_path, current_path)
                except OSError:
                    pass

    calendar_storage_path = storage_dir / "calendar_flights.json"
    profile_storage_path = storage_dir / "profile_data.json"
    settings_storage_path = storage_dir / "app_settings.json"
    infinite_flight_key_path = storage_dir / "infinite_flight_key.dpapi"
    live_request_lock = asyncio.Lock()
    live_render_callback = None
    overview_cameras = {}
    flight_hibernation_storage_path = storage_dir / "flight_hibernation.json"
    runtime_icon = base_dir / "assets" / "app_icon.ico"
    tray_icon = None
    app_exit_requested = False
    hidden_to_tray_notice_shown = False
    if os.name == "nt":
        try:
            instance_id = _PREVIEW_INSTANCE_ID if _INTERFACE_PREVIEW else "V14Public"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"SamSamadi.FlightManagementSystems.{instance_id}")
        except Exception:
            pass
    if runtime_icon.exists():
        try:
            page.window.icon = str(runtime_icon)
        except Exception:
            pass

    page.title = _PREVIEW_WINDOW_TITLE if _INTERFACE_PREVIEW else "Flight Management Systems"
    page.window.width = 1360
    page.window.height = 860
    page.window.min_width = 1000
    page.window.min_height = 720
    page.theme_mode = ft.ThemeMode.LIGHT
    rtl_announcement_font = "Noto Sans Arabic"
    page.fonts = {UI_FONT: UI_FONT_ASSET, rtl_announcement_font: "fonts/NotoSansArabic.ttf"}
    page.padding = 0
    page.spacing = 0

    AIRLINE_ACCENT = {'ANA': '#1F4E8C',
     'Air France': '#002157',
     'American Airlines': '#6B7280',
     'British Airways': '#2E5C99',
     'Cathay Pacific': '#006564',
     'Delta Air Lines': '#C8102E',
     'Emirates': '#D71A21',
     'Etihad Airways': '#715A28',
     'Generic': '#52606D',
     'ITA Airways': '#005DAA',
     'Iran Air': '#1F2C51',
     'Lufthansa': '#7A5B00',
     'Mahan Air': '#00685E',
     'Qantas': '#E4002B',
     'Qatar Airways': '#660033',
     'Singapore Airlines': '#765600',
     'Southwest Airlines': '#304CB2',
     'Turkish Airlines': '#C70A0C',
     'United Airlines': '#005DAA',
     'Virgin Atlantic': '#DA0530'}

    AIRLINE_BACKGROUND = {'ANA': '#081A32',
     'Air France': '#07132A',
     'American Airlines': '#171B22',
     'British Airways': '#081426',
     'Cathay Pacific': '#062624',
     'Delta Air Lines': '#12162A',
     'Emirates': '#2A0B12',
     'Etihad Airways': '#241E14',
     'Generic': '#111827',
     'ITA Airways': '#071D33',
     'Iran Air': '#0C152A',
     'Lufthansa': '#2A2206',
     'Mahan Air': '#06231F',
     'Qantas': '#2A0710',
     'Qatar Airways': '#210013',
     'Singapore Airlines': '#2A2108',
     'Southwest Airlines': '#0B1433',
     'Turkish Airlines': '#2A090A',
     'United Airlines': '#071D33',
     'Virgin Atlantic': '#2B0811'}

    # Light neumorphic surfaces are intentionally muted versions of each brand.
    # They preserve airline identity without turning large backgrounds into saturated color fields.
    AIRLINE_NEUMORPHIC_LIGHT = {
        'ANA': '#E7EDF6',
        'Air France': '#E8EDF4',
        'American Airlines': '#ECEFF2',
        'British Airways': '#E7ECF4',
        'Cathay Pacific': '#E5EFED',
        'Delta Air Lines': '#F1E7EA',
        'Emirates': '#F2E7E9',
        'Etihad Airways': '#F1ECE2',
        'Generic': '#ECF0F3',
        'ITA Airways': '#E5EEF5',
        'Iran Air': '#E8EBF2',
        'Lufthansa': '#F3EEDF',
        'Mahan Air': '#E5EFEC',
        'Qantas': '#F3E6E9',
        'Qatar Airways': '#EFE5EA',
        'Singapore Airlines': '#F3EEDF',
        'Southwest Airlines': '#E7EAF5',
        'Turkish Airlines': '#F2E7E8',
        'United Airlines': '#E5EEF5',
        'Virgin Atlantic': '#F2E6EA',
    }

    CARD_FILL = "#20242B"
    SHELL_WARM_BG = "#1B1E24"
    DAYLIGHT_CARD_FILL = "#B2D5E5"
    DAYLIGHT_SUBPANEL_FILL = "#B2D5E5"
    DAYLIGHT_INPUT_FILL = "#FFFFFF"
    DAYLIGHT_TEXT = "#17212B"
    DAYLIGHT_MUTED = "#536170"
    DAYLIGHT_BORDER = "#A9D7EF"
    PANEL_TEXT = ft.Colors.WHITE
    PANEL_MUTED = "#C7CBD1"

    tokens = {
        "accent": AIRLINE_ACCENT.get(state.airline, "#0A84FF"),
        "bg": SHELL_WARM_BG,
        "text": PANEL_TEXT,
        "muted": PANEL_MUTED,
        "topbar": "#101113",
        "panel": CARD_FILL,
        "subpanel": CARD_FILL,
        "card_border": ft.Colors.with_opacity(0.14, ft.Colors.WHITE),
        "input_bg": "#202126",
        "success_overlay": ft.Colors.with_opacity(0.18, ft.Colors.GREEN),
        "shell_topbar": "#101113",
        "shell_topbar_opacity": 0.58,
        "shell_rail": ft.Colors.BLACK,
        "shell_rail_opacity": 0.32,
        "shell_text": PANEL_TEXT,
        "shell_muted": PANEL_MUTED,
        "shell_border": ft.Colors.with_opacity(0.14, ft.Colors.WHITE),
        "shell_nav_idle": ft.Colors.BLACK,
        "shell_nav_idle_opacity": 0.12,
        "shell_nav_idle_border_opacity": 0.10,
        "shell_nav_selected_opacity": 0.38,
        "shell_nav_selected_border_opacity": 0.46,
        "shadow_dark": ft.Colors.with_opacity(0.52, ft.Colors.BLACK),
        "shadow_light": ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
        "pressed": "#181B20",
    }

    # Performance cache: avoid repeated filesystem scans for image assets during
    # page refreshes, tab changes, banner ticks, and airline/logo updates.
    asset_rel_cache: Dict[str, Optional[str]] = {}
    airline_logo_cache: Dict[str, Optional[str]] = {}
    manufacturer_logo_cache: Dict[str, Optional[str]] = {}
    aircraft_livery_cache: Dict[tuple[str, str], Optional[str]] = {}
    airport_weather_cache: Dict[str, dict] = {}
    performance_metar_requests = {}
    pending_airport_media: set[str] = set()
    airport_images: dict[str, str] = {}
    planner_records: dict[str, dict] = {}
    close_suggestions = None

    def clear_asset_lookup_caches():
        asset_rel_cache.clear()
        airline_logo_cache.clear()
        manufacturer_logo_cache.clear()
        aircraft_livery_cache.clear()

    def clamp_setting(value: float, low: float, high: float, fallback: float) -> float:
        try:
            return max(low, min(float(value), high))
        except Exception:
            return fallback

    def airline_asset_slug(value: Optional[str]) -> str:
        raw = (value or "").strip().lower()
        raw = raw.replace("&", "and")
        raw = re.sub(r"[^a-z0-9]+", "_", raw)
        raw = re.sub(r"_+", "_", raw).strip("_")
        return raw or "airline"

    def register_custom_airline(airline_name: str) -> Optional[str]:
        clean_name = canonical_airline_name(airline_name)
        if not clean_name:
            return None
        existing = next((name for name in AIRLINES if name.lower() == clean_name.lower()), None)
        if existing:
            clean_name = existing
        else:
            AIRLINES.append(clean_name)
            AIRLINES.sort(key=lambda name: name.lower())

        slug = airline_asset_slug(clean_name)
        AIRLINE_LOGO_FILES.setdefault(clean_name, f"airlines/logos/{slug}.png")
        AIRLINE_ACCENT.setdefault(clean_name, AIRLINE_ACCENT.get("Generic", "#64748B"))
        AIRLINE_BACKGROUND.setdefault(clean_name, AIRLINE_BACKGROUND.get("Generic", "#111827"))
        AIRLINE_NEUMORPHIC_LIGHT.setdefault(clean_name, AIRLINE_NEUMORPHIC_LIGHT.get("Generic", "#ECF0F3"))
        AIRLINE_FLEETS.setdefault(clean_name, list(AIRLINE_FLEETS.get("Generic", [])))
        if clean_name not in state.custom_airlines and clean_name not in {
                'Air France', 'American Airlines', 'ANA', 'British Airways', 'Cathay Pacific', 'Delta Air Lines',
            'Emirates', 'Etihad Airways', 'Generic', 'Iran Air', 'ITA Airways', 'Lufthansa',
            'Mahan Air', 'Qantas', 'Qatar Airways', 'Singapore Airlines', 'Southwest Airlines',
            'Turkish Airlines', 'United Airlines', 'Virgin Atlantic'
        }:
            state.custom_airlines.append(clean_name)
            state.custom_airlines.sort(key=lambda name: name.lower())
        return clean_name

    def apply_theme():
        brightness = clamp_setting(state.display_brightness, 0.70, 1.30, 1.0)
        contrast = clamp_setting(state.display_contrast, 0.70, 1.35, 1.0)
        state.display_brightness = brightness
        state.display_contrast = contrast
        state.airline_overlay_opacity = clamp_setting(state.airline_overlay_opacity, 0.0, 0.80, 0.50)

        daylight_mode = str(getattr(state, "display_mode", "dark") or "dark").lower() == "daylight"
        page.theme_mode = ft.ThemeMode.LIGHT if daylight_mode else ft.ThemeMode.DARK
        palette = LIGHT if daylight_mode else DARK
        tokens.update(palette)
        for key in ("bg", "panel", "subpanel", "input_bg", "shell_topbar"):
            tint = "#FFFFFF" if brightness >= 1 else "#000000"
            tokens[key] = blend_hex_colors(palette[key], tint, abs(brightness - 1) * 0.25)
        brand = AIRLINE_ACCENT.get(state.airline)
        if brand:
            tokens["subpanel"] = blend_hex_colors(tokens["subpanel"], brand, state.airline_overlay_opacity * 0.08)
        contrast_target = palette["text"] if contrast >= 1 else tokens["panel"]
        tokens["muted"] = blend_hex_colors(palette["muted"], contrast_target, abs(contrast - 1) * 0.25)
        tokens["card_border"] = blend_hex_colors(palette["card_border"], palette["text"], max(0, contrast - 1) * 0.18)
        tokens["shell_text"] = tokens["text"]
        tokens["shell_muted"] = tokens["muted"]
        tokens["shell_border"] = tokens["card_border"]
        tokens["topbar"] = tokens["shell_topbar"]
        tokens["success_overlay"] = ft.Colors.with_opacity(0.18, ft.Colors.GREEN)
        secondary = button_style(tokens)
        primary = button_style(tokens, primary=True)
        theme = ft.Theme(
            use_material3=True,
            font_family=UI_FONT,
            scaffold_bgcolor=tokens["bg"],
            canvas_color=tokens["bg"],
            card_bgcolor=surface_fill(tokens["panel"]),
            divider_color=tokens["card_border"],
            color_scheme=ft.ColorScheme(
                primary=tokens["primary"],
                on_primary=tokens["on_primary"],
                secondary=tokens["accent"],
                surface=tokens["panel"],
                on_surface=tokens["text"],
                on_surface_variant=tokens["muted"],
                outline=tokens["card_border"],
            ),
            button_theme=ft.ButtonTheme(style=primary),
            outlined_button_theme=ft.OutlinedButtonTheme(style=secondary),
            filled_button_theme=ft.FilledButtonTheme(style=primary),
            text_button_theme=ft.TextButtonTheme(style=secondary),
            icon_button_theme=ft.IconButtonTheme(style=button_style(tokens, circular=True)),
            card_theme=ft.CardTheme(
                color=surface_fill(tokens["panel"]), elevation=0, shape=ft.RoundedRectangleBorder(radius=CARD_RADIUS)
            ),
        )
        if daylight_mode:
            page.theme = theme
        else:
            page.dark_theme = theme

    def surface_shadow(depth: float = 1.0, pressed: bool = False) -> Optional[ft.BoxShadow]:
        if pressed:
            return None
        return ft.BoxShadow(
            blur_radius=4 + 3 * depth,
            color=ft.Colors.with_opacity(0.08, ft.Colors.BLACK),
            offset=ft.Offset(0, 1 + depth),
        )

    def current_airline_label() -> str:
        return state.airline or "Pick an airline"

    def current_aircraft_label() -> str:
        return state.aircraft_record.get("name") or state.aircraft or "Select an aircraft"

    def current_route_label() -> str:
        if state.departure or state.arrival:
            return f"{state.departure or '—'} → {state.arrival or '—'}"
        return "—"

    def header_banner_route_label() -> str:
        origin = (state.departure or "DEPARTURE").strip().upper()
        destination = (state.arrival or "ARRIVAL").strip().upper()
        return f"{origin} → {destination}"

    def header_banner_aircraft_label() -> str:
        return (state.aircraft or "AIRCRAFT").strip()

    def header_banner_flight_number_label() -> str:
        return (state.flight_number or "FLIGHT —").strip().upper()

    def fuel_plan_flight_minutes() -> int:
        if not state.departure or not state.arrival:
            return 0
        route_key = active_route_distance_key()
        if not route_key:
            return 0
        distance = state.route_distance_override_nm if state.route_distance_override_key == route_key else None
        if distance is None:
            departure, arrival = route_key.split("->", 1)
            distance = route_distance_nm(departure, arrival)
        aircraft = canonical_aircraft_name(state.aircraft)
        if distance is not None and math.isfinite(distance):
            return max(1, round(route_fuel_ete_hours(aircraft, distance) * 60)) if distance > 0 else 0
        plan = state.takeoff_last_result.get("fuel_plan") or {}
        if plan.get("route_key") == route_key and plan.get("aircraft") == aircraft:
            minutes = plan.get("ete_minutes")
            return minutes if isinstance(minutes, int) and minutes > 0 else 0
        return 0

    def clear_dashboard_time_override():
        state.overview_flight_time_minutes = 0
        state.dashboard_flight_plan.pop("flight_time", None)

    def planned_overview_minutes() -> int:
        return state.overview_flight_time_minutes or fuel_plan_flight_minutes()

    def overview_elapsed_seconds() -> float:
        if state.overview_progress_running and state.overview_takeoff_start_timestamp is not None:
            return max(0.0, time.time() - state.overview_takeoff_start_timestamp)
        return state.overview_paused_elapsed_seconds or 0.0

    def header_banner_remaining_time_label() -> str:
        duration_minutes = planned_overview_minutes()
        if not duration_minutes:
            return "—"

        remaining_minutes = duration_minutes
        if int(state.overview_flight_status_index or 0) >= 5:
            remaining_minutes = 0
        else:
            remaining_minutes = max(0, duration_minutes - int(overview_elapsed_seconds() / 60.0))

        return format_hours_to_hm(remaining_minutes / 60.0)

    def header_banner_messages() -> tuple[str, str]:
        route = header_banner_route_label()
        aircraft = header_banner_aircraft_label()
        flight_number = header_banner_flight_number_label()
        remaining = header_banner_remaining_time_label()
        long_message = f"{route}    •    AIRCRAFT {aircraft}    •    FLIGHT {flight_number}    •    REMAINING {remaining}"
        short_message = f"{route}    •    {aircraft}"
        return long_message, short_message

    def header_progress_percent() -> float:
        status_index = int(getattr(state, "overview_flight_status_index", 0) or 0)
        if status_index < 2:
            return 0.0
        if status_index >= 5:
            return 100.0
        duration_minutes = planned_overview_minutes()
        if not duration_minutes:
            return 0.0
        elapsed_min = overview_elapsed_seconds() / 60.0
        return clamp((elapsed_min / duration_minutes) * 100.0, 0.0, 100.0)

    def header_progress_icon() -> ft.Control:
        rel = asset_rel_path_if_exists("icons/nav/aircraft_progress.png")
        if rel:
            return ft.Image(src=rel, width=26, height=26, fit=ft.BoxFit.CONTAIN)
        return ft.Icon(ft.Icons.FLIGHT, size=22, color=tokens["shell_text"])

    def build_header_progress_line() -> ft.Control:
        progress = clamp(float(header_progress_percent() or 0.0), 0.0, 100.0)
        covered_units = max(1, int(round(progress)))
        remaining_units = max(1, int(round(100.0 - progress)))
        completed_line_color = ft.Colors.with_opacity(0.84, tokens["accent"])
        remaining_line_color = ft.Colors.with_opacity(0.24, tokens["accent"])

        aircraft_on_line = ft.Container(
            width=32,
            height=32,
            content=ft.Stack(
                controls=[
                    ft.Container(
                        top=15,
                        left=0,
                        right=0,
                        height=3,
                        border_radius=999,
                        bgcolor=completed_line_color if progress >= 100.0 else remaining_line_color,
                    ),
                    ft.Container(alignment=ft.Alignment(0, 0), content=header_progress_icon()),
                ],
            ),
        )

        return ft.Container(
            height=34,
            padding=ft.padding.symmetric(horizontal=10, vertical=2),
            alignment=ft.Alignment(0, 0),
            content=ft.Row(
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(width=12, height=12, border_radius=999, bgcolor=tokens["accent"]),
                    ft.Container(expand=covered_units, height=3, border_radius=999, bgcolor=completed_line_color),
                    aircraft_on_line,
                    ft.Container(expand=remaining_units, height=3, border_radius=999, bgcolor=remaining_line_color),
                    ft.Container(width=12, height=12, border_radius=999, bgcolor=tokens["accent"]),
                ],
            ),
        )

    def refresh_header_banner_tick(reset: bool = False) -> bool:
        header_route_line_host.content = build_header_progress_line()
        return True

    def derive_idle_status() -> str:
        if not state.airline:
            return "Select an airline"
        if not state.aircraft:
            return "Select an aircraft"
        return "Awaiting route setup"

    def glass_card(
        title: str,
        content: ft.Control,
        width: Optional[int] = None,
        expand: bool = False,
        bgcolor_override: Optional[str] = None,
        height: Optional[int] = None,
    ):
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(title, size=15, weight=ft.FontWeight.W_700, color=tokens["text"]),
                    content,
                ],
                spacing=10,
            ),
            padding=14,
            border_radius=CARD_RADIUS,
            bgcolor=surface_fill(bgcolor_override or tokens["panel"]),
            border=ft.border.all(1, tokens["card_border"]),
            shadow=surface_shadow(),
            width=width,
            height=height,
            expand=expand,
        )

    CARD_BACKGROUND_KEYS = {
        "Route Schematic": "route_schematic",
        "Pilot and Environment": "pilot_environment",
        "Ramp Status": "ramp_status",
        "Live Flight Summary": "live_flight_summary",
        "Flight Status": "flight_status",
        "Pilot Greeting": "pilot_greeting",
        "Baggage": "baggage",
        "Cargo": "cargo",
        "Calculated Weight": "calculated_weight",
        "Cabin Control": "cabin_control",
        "Seat Map": "seat_map",
        "Career Statistics": "career_statistics",
        "Takeoff Performance Speeds": "takeoff_performance_speeds",
        "Landing Performance Speeds": "landing_performance_speeds",
        "Desk Calendar": "desk_calendar",
    }

    def card_background_src(key_or_title: Optional[str]) -> Optional[str]:
        if not key_or_title:
            return None
        key = CARD_BACKGROUND_KEYS.get(str(key_or_title).strip(), str(key_or_title).strip())
        key = re.sub(r"[^A-Za-z0-9_\\-]+", "_", key).strip("_").lower()
        if not key:
            return None
        # V12 uses a single neumorphic surface language. Flight Recorder keeps
        # its purpose-built artwork; boarding passes use their own renderer.
        if key not in {"flight_recorder", "boarding_pass_header"}:
            return None
        for ext in ("png", "jpg", "jpeg", "webp"):
            found = asset_rel_path_if_exists(f"backgrounds/cards/{key}.{ext}")
            if found:
                return found
        return None

    def card_background_layers(
        key_or_title: Optional[str],
        base_bg: Optional[str] = None,
        overlay_opacity: float = 0.38,
    ) -> List[ft.Control]:
        # Global card-background rule:
        # image opacity = 32%, no black/dark overlay.
        # If an image exists, the base layer is transparent so the dark panel
        # does not behave like a hidden black overlay under the image.
        src = card_background_src(key_or_title)
        if src:
            return [
                ft.Container(expand=True, bgcolor=surface_fill(base_bg or tokens["panel"]) if use_daylight_cards() else ft.Colors.TRANSPARENT),
                ft.Container(
                    expand=True,
                    image=ft.DecorationImage(src=src, fit=ft.BoxFit.COVER, opacity=0.32),
                ),
            ]
        return [ft.Container(expand=True, bgcolor=surface_fill(base_bg or tokens["panel"]))]

    def glass_card_with_background(
        title: str,
        content: ft.Control,
        width: Optional[int] = None,
        expand: bool = False,
        bgcolor_override: Optional[str] = None,
        height: Optional[int] = None,
        bg_key: Optional[str] = None,
    ):
        bg_src = card_background_src(bg_key or title)
        card_base_bg = (bgcolor_override or tokens["panel"]) if use_daylight_cards() else (ft.Colors.TRANSPARENT if bg_src else (bgcolor_override or tokens["panel"]))
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(title, size=15, weight=ft.FontWeight.W_700, color=tokens["text"]),
                    content,
                ],
                spacing=10,
            ),
            padding=14,
            border_radius=CARD_RADIUS,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=surface_fill(card_base_bg),
            image=ft.DecorationImage(src=bg_src, fit=ft.BoxFit.COVER, opacity=0.32) if bg_src else None,
            border=ft.border.all(1, tokens["card_border"]),
            shadow=surface_shadow(),
            width=width,
            height=height,
            expand=expand,
        )

    def metric_card(label: str, value, subtitle: str = "", expand: bool = True, width: Optional[int] = None):
        value_control = value if isinstance(value, ft.Control) else ft.Text(str(value), size=22, weight=ft.FontWeight.W_700, color=tokens["text"])
        if isinstance(value_control, ft.Text):
            value_control.size = 22
            value_control.weight = ft.FontWeight.W_700
            value_control.color = tokens["text"]

        return ft.Container(
            padding=16,
            border_radius=18,
            bgcolor=surface_fill(tokens["subpanel"]),
            border=ft.border.all(1, tokens["card_border"]),
            shadow=surface_shadow(0.52),
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Text(label, size=12, color=tokens["muted"]),
                    value_control,
                    *([ft.Text(subtitle, size=11, color=tokens["muted"])] if subtitle else []),
                ],
            ),
            expand=expand,
            width=width,
        )

    def load_calendar_entries():
        if calendar_storage_path.exists():
            try:
                data = json.loads(calendar_storage_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    state.calendar_entries = data
                    for entry in data:
                        for record in (entry.get("aviation_records") or {}).values():
                            if isinstance(record, dict) and record.get("lat") is not None and record.get("code"):
                                remember_airport(record)
            except Exception:
                state.calendar_entries = []

    def active_flight_records(origin, destination):
        records = {
            key: record for key, code in (("origin", origin), ("destination", destination))
            if (record := lookup_airport_record(code))
        }
        if state.airline_record:
            records["airline"] = state.airline_record
        if state.aircraft_record:
            records["aircraft"] = state.aircraft_record
        return records

    def save_calendar_entries():
        try:
            calendar_storage_path.write_text(
                json.dumps(state.calendar_entries, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def format_profile_minutes(total_minutes: int) -> str:
        total_minutes = max(0, int(total_minutes or 0))
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours}h {minutes:02d}m"

    def default_member_since_date() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def normalize_member_since_date(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return default_member_since_date()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except Exception:
                pass
        return raw

    def parse_profile_time_minutes(value: str) -> int:
        raw = (value or "").strip().lower()
        if not raw or raw == "—":
            return 0
        hhmm = re.fullmatch(r"(\d{1,5}):(\d{2})", raw)
        if hhmm:
            return int(hhmm.group(1)) * 60 + int(hhmm.group(2))
        hours_match = re.search(r"(\d+(?:\.\d+)?)\s*h", raw)
        mins_match = re.search(r"(\d+)\s*m", raw)
        total = 0
        if hours_match:
            total += int(round(float(hours_match.group(1)) * 60))
        if mins_match:
            total += int(mins_match.group(1))
        if total > 0:
            return total
        try:
            # Plain numbers in the profile editor mean HOURS, not minutes.
            return int(round(float(raw) * 60))
        except Exception:
            return 0

    def load_profile_data():
        state.profile_total_flight_minutes = 0
        state.profile_online_flights = 0
        state.profile_total_landings = 0
        state.profile_member_since = default_member_since_date()
        state.profile_violations = 0
        state.profile_favorite_airline = ""
        state.profile_favorite_aircraft = ""
        state.profile_countries_visited = 0
        state.profile_image_path = ""
        if profile_storage_path.exists():
            try:
                data = json.loads(profile_storage_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    state.pilot_name = str(data.get("pilot_name") or state.pilot_name or "Pilot")
                    state.profile_member_since = normalize_member_since_date(str(data.get("member_since") or state.profile_member_since))
                    state.profile_total_flight_minutes = int(data.get("total_flight_minutes") or 0)
                    state.profile_online_flights = int(data.get("online_flights") or 0)
                    state.profile_total_landings = int(data.get("total_landings") or 0)
                    state.profile_violations = int(data.get("violations") or 0)
                    state.profile_favorite_airline = str(data.get("favorite_airline") or "")
                    state.profile_favorite_aircraft = str(data.get("favorite_aircraft") or "")
                    state.profile_countries_visited = int(data.get("countries_visited") or 0)
                    state.profile_image_path = str(data.get("profile_image_path") or "")
            except Exception:
                pass

    def save_profile_data():
        try:
            payload = {
                "pilot_name": state.pilot_name or "Pilot",
                "member_since": normalize_member_since_date(getattr(state, "profile_member_since", "") or default_member_since_date()),
                "total_flight_minutes": int(getattr(state, "profile_total_flight_minutes", 0) or 0),
                "online_flights": int(getattr(state, "profile_online_flights", 0) or 0),
                "total_landings": int(getattr(state, "profile_total_landings", 0) or 0),
                "violations": int(getattr(state, "profile_violations", 0) or 0),
                "favorite_airline": str(getattr(state, "profile_favorite_airline", "") or ""),
                "favorite_aircraft": str(getattr(state, "profile_favorite_aircraft", "") or ""),
                "countries_visited": int(getattr(state, "profile_countries_visited", 0) or 0),
                "profile_image_path": str(getattr(state, "profile_image_path", "") or ""),
            }
            profile_storage_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def load_settings_data():
        state.display_mode = "daylight"
        state.display_brightness = 1.0
        state.display_contrast = 1.0
        state.airline_overlay_opacity = 0.50
        state.custom_airlines = []
        state.default_fuel_unit = "kg"
        state.default_distance_unit = "NM"
        state.default_temperature_unit = "°C"
        state.banner_animation_enabled = False
        state.low_performance_mode = False
        state.professional_info_enabled = False
        state.app_volume = 0.85
        state.app_muted = False
        state.takeoff_clock_source = "route"
        state.landing_clock_source = "route"
        if settings_storage_path.exists():
            try:
                data = json.loads(settings_storage_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    state.display_mode = "daylight" if str(data.get("display_mode", "daylight")).lower() == "daylight" else "dark"
                    state.display_brightness = clamp_setting(data.get("display_brightness", 1.0), 0.70, 1.30, 1.0)
                    state.display_contrast = clamp_setting(data.get("display_contrast", 1.0), 0.70, 1.35, 1.0)
                    state.airline_overlay_opacity = clamp_setting(data.get("airline_overlay_opacity", 0.50), 0.0, 0.80, 0.50)
                    fuel_unit = str(data.get("default_fuel_unit", "kg"))
                    distance_unit = str(data.get("default_distance_unit", "NM"))
                    temperature_unit = str(data.get("default_temperature_unit", "°C"))
                    state.default_fuel_unit = fuel_unit if fuel_unit in ("kg", "lb") else "kg"
                    state.default_distance_unit = distance_unit if distance_unit in ("NM", "km") else "NM"
                    state.default_temperature_unit = temperature_unit if temperature_unit in ("°C", "°F") else "°C"
                    state.low_performance_mode = bool(data.get("low_performance_mode", False))
                    state.tutorial_skipped = data.get("tutorial_skipped") is True
                    seen = data.get("tutorial_seen", [])
                    if isinstance(seen, list):
                        state.tutorial_seen = {name for name in seen if isinstance(name, str)}
                    state.professional_info_enabled = bool(data.get("professional_info_enabled", False))
                    state.app_volume = clamp_setting(data.get("app_volume", 0.85), 0.0, 1.0, 0.85)
                    state.app_muted = bool(data.get("app_muted", False))
                    takeoff_source = str(data.get("takeoff_clock_source", "route"))
                    landing_source = str(data.get("landing_clock_source", "route"))
                    state.takeoff_clock_source = takeoff_source if takeoff_source in ("route", "device", "simulation") else "route"
                    state.landing_clock_source = landing_source if landing_source in ("route", "device", "simulation") else "route"
                    custom_airlines = data.get("custom_airlines", [])
                    if isinstance(custom_airlines, list):
                        for airline_name in custom_airlines:
                            register_custom_airline(str(airline_name))
            except Exception:
                pass

    def save_settings_data():
        try:
            payload = {
                "display_mode": state.display_mode,
                "display_brightness": round(float(state.display_brightness), 2),
                "display_contrast": round(float(state.display_contrast), 2),
                "airline_overlay_opacity": round(float(state.airline_overlay_opacity), 2),
                "custom_airlines": list(state.custom_airlines),
                "default_fuel_unit": state.default_fuel_unit,
                "default_distance_unit": state.default_distance_unit,
                "default_temperature_unit": state.default_temperature_unit,
                "low_performance_mode": bool(state.low_performance_mode),
                "tutorial_skipped": state.tutorial_skipped,
                "tutorial_seen": sorted(state.tutorial_seen),
                "professional_info_enabled": bool(getattr(state, "professional_info_enabled", False)),
                "app_volume": round(float(getattr(state, "app_volume", 0.85) or 0.0), 2),
                "app_muted": bool(getattr(state, "app_muted", False)),
                "takeoff_clock_source": getattr(state, "takeoff_clock_source", "route"),
                "landing_clock_source": getattr(state, "landing_clock_source", "route"),
            }
            settings_storage_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def parse_flight_time_minutes(value: str) -> int:
        raw = (value or "").strip().lower()
        if not raw or raw == "—":
            return 0
        hhmm = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
        if hhmm:
            return int(hhmm.group(1)) * 60 + int(hhmm.group(2))
        hours_match = re.search(r"(\d+)\s*h", raw)
        mins_match = re.search(r"(\d+)\s*m", raw)
        total = 0
        if hours_match:
            total += int(hours_match.group(1)) * 60
        if mins_match:
            total += int(mins_match.group(1))
        if total > 0:
            return total
        try:
            return int(round(float(raw) * 60))
        except Exception:
            return 0

    def sync_profile_from_calendar_completion() -> bool:
        changed = False
        total_minutes = int(getattr(state, "profile_total_flight_minutes", 0) or 0)
        online_flights = int(getattr(state, "profile_online_flights", 0) or 0)
        total_landings = int(getattr(state, "profile_total_landings", 0) or 0)

        for entry in state.calendar_entries:
            completed = bool(entry.get("completed"))
            accounted = bool(entry.get("profile_accounted"))
            minutes = parse_flight_time_minutes(entry.get("flight_time", ""))
            previous_minutes = int(entry.get("profile_accounted_minutes") or 0)

            if completed and not accounted:
                total_minutes += minutes
                online_flights += 1
                total_landings += 1
                entry["profile_accounted"] = True
                entry["profile_accounted_minutes"] = minutes
                changed = True
            elif completed and accounted and minutes != previous_minutes:
                total_minutes += minutes - previous_minutes
                entry["profile_accounted_minutes"] = minutes
                changed = True
            elif (not completed) and accounted:
                total_minutes = max(0, total_minutes - previous_minutes)
                online_flights = max(0, online_flights - 1)
                total_landings = max(0, total_landings - 1)
                entry["profile_accounted"] = False
                entry["profile_accounted_minutes"] = 0
                changed = True

        if changed:
            state.profile_total_flight_minutes = total_minutes
            state.profile_online_flights = online_flights
            state.profile_total_landings = total_landings
            save_profile_data()
        return changed

    load_settings_data()
    apply_theme()
    load_calendar_entries()
    load_profile_data()
    state.pilot_name = "User"
    if sync_profile_from_calendar_completion():
        save_calendar_entries()

    root_host = ft.Container(expand=True)
    active_page_host = ft.Container(expand=True, bgcolor=ft.Colors.TRANSPARENT, alignment=ft.Alignment(-1, -1))
    active_navigation_glyph = None
    log_entry_control_registry: Dict[str, tuple[ft.Container, dict, int]] = {}
    login_audio = None
    audio_class = getattr(ft, "Audio", None)
    if audio_class is not None:
        try:
            login_audio = audio_class(
                src="audio/login.mp3",
                autoplay=False,
            )
        except TypeError:
            try:
                login_audio = audio_class(src="audio/login.mp3")
            except Exception:
                login_audio = None
        except Exception:
            login_audio = None

    ui_refresh_in_progress = False
    last_header_second = ""
    last_overview_progress_update = 0.0
    OVERVIEW_PROGRESS_REFRESH_SECONDS = 1
    HEADER_BANNER_VISIBLE_CHARS = 72
    HEADER_BANNER_PAUSE_TICKS = 10
    HEADER_BANNER_TICK_SECONDS = 1.0
    header_banner_state = {"frame": 0, "last_message": ""}
    header_banner_text = ft.Text(
        "",
        size=16,
        weight=ft.FontWeight.W_800,
        color=tokens["accent"],
        max_lines=1,
        no_wrap=True,
    )
    header_route_line_host = ft.Container(height=34)

    txt_welcome = ft.Text("", size=18, weight=ft.FontWeight.W_700)
    txt_time = ft.Text("", size=12, opacity=0.9)
    txt_location = ft.Text("", size=12, opacity=0.9)
    txt_weather = ft.Text("", size=12, opacity=0.9)
    overview_date_text = ft.Text("", size=13, color=tokens["muted"])
    dashboard_weekday_text = ft.Text("", size=17, font_family="Georgia")
    dashboard_date_text = ft.Text("", size=36, font_family="Georgia", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
    dashboard_year_text = ft.Text("", size=16, font_family="Georgia")
    overview_time_text = ft.Text("", size=26, weight=ft.FontWeight.W_800, color=tokens["text"])
    overview_location_text = ft.Text("", size=12, color=tokens["muted"])
    overview_weather_text = ft.Text("", size=12, color=tokens["muted"])
    overview_route_line_host = ft.Container()
    overview_ete_value_text = ft.Text("", size=18, weight=ft.FontWeight.W_800, color=tokens["text"], text_align=ft.TextAlign.CENTER, no_wrap=True)
    overview_eta_value_text = ft.Text("", size=18, weight=ft.FontWeight.W_800, color=tokens["text"], text_align=ft.TextAlign.CENTER, no_wrap=True)

    overview_progress_refresh_callback = None
    ramp_status_card_host = ft.Container(width=500, height=440)
    ramp_status_refresh_callback = None
    takeoff_date_text = ft.Text("", size=13, color=tokens["muted"], text_align=ft.TextAlign.CENTER)
    takeoff_route_time_text = ft.Text("", size=16, weight=ft.FontWeight.W_800, color=tokens["text"])
    takeoff_time_text = ft.Text("", size=13, weight=ft.FontWeight.W_700, color=tokens["muted"])
    takeoff_clock_source_text = ft.Text("", size=10, weight=ft.FontWeight.W_700, color=tokens["accent"])
    takeoff_location_text = ft.Text("", size=12, color=tokens["muted"])
    takeoff_weather_text = ft.Text("", size=12, color=tokens["muted"])
    landing_date_text = ft.Text("", size=13, color=tokens["muted"], text_align=ft.TextAlign.CENTER)
    landing_route_time_text = ft.Text("", size=16, weight=ft.FontWeight.W_800, color=tokens["text"])
    landing_time_text = ft.Text("", size=13, weight=ft.FontWeight.W_700, color=tokens["muted"])
    landing_clock_source_text = ft.Text("", size=10, weight=ft.FontWeight.W_700, color=tokens["accent"])
    home_airline_logo_host = ft.Container()

    def build_analog_clock_face(moment: datetime, size: int = 240) -> ft.Control:
        center = size / 2.0
        scale = size / 62.0
        hub_diameter = max(8.0, 2.5 * scale)

        def hand(length: float, width: float, angle: float, color: str) -> ft.Control:
            return ft.Container(
                left=center - width / 2.0,
                top=center - length,
                width=width,
                height=length,
                bgcolor=color,
                border_radius=999,
                rotate=ft.Rotate(angle=angle, alignment=ft.Alignment(0, 1)),
            )

        second_angle = (moment.second / 60.0) * math.tau
        minute_angle = ((moment.minute + moment.second / 60.0) / 60.0) * math.tau
        hour_angle = (((moment.hour % 12) + moment.minute / 60.0) / 12.0) * math.tau
        tick_color = ft.Colors.with_opacity(0.64, tokens["muted"])
        ticks: List[ft.Control] = []
        for index in range(12):
            angle = index * math.tau / 12.0
            tick_height = (6 if index % 3 == 0 else 3) * scale
            tick_width = max(2.0, 1.25 * scale)
            radius = center - 9 * scale
            ticks.append(
                ft.Container(
                    left=center - tick_width / 2.0 + math.sin(angle) * radius,
                    top=center - tick_height / 2.0 - math.cos(angle) * radius,
                    width=tick_width,
                    height=tick_height,
                    bgcolor=tick_color,
                    border_radius=999,
                    rotate=ft.Rotate(angle=angle),
                )
            )

        return ft.Container(
            width=size,
            height=size,
            border_radius=999,
            bgcolor=surface_fill(tokens["panel"]),
            border=ft.border.all(1, tokens["card_border"]),
            shadow=surface_shadow(0.58),
            content=ft.Stack(
                width=size,
                height=size,
                controls=[
                    *ticks,
                    hand(size * 0.23, 5.5, hour_angle, tokens["text"]),
                    hand(size * 0.31, 3.5, minute_angle, tokens["text"]),
                    hand(size * 0.34, 1.5, second_angle, tokens["accent"]),
                    ft.Container(
                        left=center - hub_diameter / 2.0,
                        top=center - hub_diameter / 2.0,
                        width=hub_diameter,
                        height=hub_diameter,
                        border_radius=999,
                        bgcolor=tokens["accent"],
                    ),
                ],
            ),
        )

    takeoff_analog_clock_host = ft.Container(width=240, height=240)
    landing_analog_clock_host = ft.Container(width=240, height=240)

    def airport_local_datetime(code: Optional[str]) -> datetime:
        canonical = normalize_airport_code(code) or (code or "").strip().upper()
        record = lookup_airport_record(canonical)
        if record:
            # Estimate the local offset from the airport longitude.
            longitude = float(record.get("lon", 0.0) or 0.0)
            offset_minutes = int(round((longitude / 15.0) * 2.0) * 30)
            offset_minutes = max(-720, min(840, offset_minutes))
            return datetime.now(timezone.utc).astimezone(timezone(timedelta(minutes=offset_minutes)))
        return datetime.now().astimezone()

    def phase_clock_moment(phase: str) -> tuple[datetime, str]:
        is_departure = phase == "departure"
        source = getattr(state, "takeoff_clock_source" if is_departure else "landing_clock_source", "route")
        if source == "device":
            return datetime.now().astimezone(), "Device local"
        if source == "simulation":
            return datetime.now().astimezone(), "Simulation local"
        code = (state.departure or takeoff_departure_icao_tf.value) if is_departure else (state.arrival or landing_arrival_icao_tf.value)
        label = "Departure local" if is_departure else "Arrival local"
        return airport_local_datetime(code), label

    def now_local_str():
        return datetime.now().strftime("%a %d %b • %H:%M:%S")

    def refresh_header_texts():
        local_today = datetime.now().date()
        dashboard_weekday_text.value = local_today.strftime("%A")
        dashboard_date_text.value = f"{local_today.day} {local_today:%B}"
        dashboard_year_text.value = str(local_today.year)
        txt_welcome.value = f"Hello, {state.pilot_name}"
        txt_time.value = f"Local time: {now_local_str()}"
        if state.location_permission_enabled:
            txt_location.value = f"Location: {state.location_label}"
        else:
            txt_location.value = "Location: tracking disabled"
        if state.weather.temperature_c is None:
            txt_weather.value = f"Weather: {state.weather.icon} {state.weather.condition}"
        else:
            txt_weather.value = f"Weather: {state.weather.icon} {state.weather.condition} • {state.weather.temperature_c:.0f}°C"
        overview_date_text.value = datetime.now().strftime("%A, %d %B %Y")
        overview_time_text.value = datetime.now().strftime("%H:%M:%S")
        # When an airline theme is active, the Overview clock must stay white
        # for readability over the airline-colored/dark background.
        overview_time_text.color = ft.Colors.WHITE if state.airline else tokens["text"]
        overview_date_text.color = tokens["muted"]
        overview_location_text.color = tokens["muted"]
        overview_weather_text.color = tokens["muted"]
        overview_location_text.value = txt_location.value
        overview_weather_text.value = txt_weather.value
        takeoff_moment, takeoff_source_label = phase_clock_moment("departure")
        landing_moment, landing_source_label = phase_clock_moment("descent")
        takeoff_date_text.value = takeoff_moment.strftime("%A, %d %B %Y")
        utc_label = datetime.utcnow().strftime("UTC %H:%M:%S")
        takeoff_route_time_text.value = f"Local {takeoff_moment.strftime('%H:%M:%S')}"
        takeoff_time_text.value = utc_label
        takeoff_clock_source_text.value = takeoff_source_label
        takeoff_route_time_text.color = tokens["text"]
        takeoff_clock_source_text.color = tokens["accent"]
        takeoff_time_text.color = tokens["muted"]
        takeoff_date_text.color = tokens["muted"]
        takeoff_location_text.color = tokens["muted"]
        takeoff_weather_text.color = tokens["muted"]
        takeoff_location_text.value = txt_location.value
        takeoff_weather_text.value = txt_weather.value
        takeoff_analog_clock_host.content = build_analog_clock_face(takeoff_moment, int(takeoff_analog_clock_host.width))
        landing_date_text.value = landing_moment.strftime("%A, %d %B %Y")
        landing_route_time_text.value = f"Local {landing_moment.strftime('%H:%M:%S')}"
        landing_time_text.value = utc_label
        landing_clock_source_text.value = landing_source_label
        landing_route_time_text.color = tokens["text"]
        landing_clock_source_text.color = tokens["accent"]
        landing_time_text.color = tokens["muted"]
        landing_date_text.color = tokens["muted"]
        landing_analog_clock_host.content = build_analog_clock_face(landing_moment, int(landing_analog_clock_host.width))


    def airline_logo_rel_path(airline_name: Optional[str]) -> Optional[str]:
        airline_name = (airline_name or "").strip()
        if not airline_name:
            return None
        if airline_name in airline_logo_cache:
            return airline_logo_cache[airline_name]

        rel = AIRLINE_LOGO_FILES.get(airline_name)
        if not rel:
            airline_logo_cache[airline_name] = None
            return None

        primary_file_name = Path(rel).name
        file_names = [primary_file_name]
        for alt_name in AIRLINE_LOGO_ALTERNATE_FILES.get(airline_name, []):
            if alt_name not in file_names:
                file_names.append(alt_name)

        for file_name in file_names:
            search_locations = [
                (Path(__file__).resolve().parent / "assets" / "airlines" / "logos" / file_name, f"airlines/logos/{file_name}"),
                (Path.cwd() / "assets" / "airlines" / "logos" / file_name, f"airlines/logos/{file_name}"),
                (Path(__file__).resolve().parent / "assets" / "airlines" / file_name, f"airlines/{file_name}"),
                (Path.cwd() / "assets" / "airlines" / file_name, f"airlines/{file_name}"),
            ]
            for candidate, return_rel in search_locations:
                if candidate.exists():
                    airline_logo_cache[airline_name] = return_rel
                    return return_rel
        airline_logo_cache[airline_name] = None
        return None

    def airline_logo_source(airline_name, iata=None):
        name = canonical_airline_name(airline_name)
        local = airline_logo_rel_path(name)
        if local:
            return local
        code = str(iata or "").strip().upper()
        if re.fullmatch(r"[A-Z0-9]{2}", code):
            return f"https://img.wway.io/pics/root/{code}@png?exar=1&rs=fit:340:120"
        return None

    def airline_logo_image(
        airline_name: Optional[str],
        width: int = 140,
        height: int = 60,
        opacity: float = 1.0,
        fit=ft.BoxFit.CONTAIN,
        fallback_text: bool = True,
        key_prefix: str = "logo",
    ) -> ft.Control:
        current_airline = canonical_airline_name(airline_name)
        selected_name = canonical_airline_name(state.airline_record.get("name"))
        iata = state.airline_record.get("iata") if current_airline == selected_name else None
        src = airline_logo_source(current_airline, iata)
        fallback = (
            ft.Text(current_airline.upper(), size=12, weight=ft.FontWeight.W_700, color=tokens["muted"])
            if fallback_text else ft.Icon(ft.Icons.FLIGHT, size=20, color=tokens["muted"])
        )
        if not src:
            return fallback
        image = ft.Image(
            src=src, width=width, height=height, fit=fit, opacity=opacity,
            key=f"{key_prefix}-{current_airline}-{state.logo_refresh_nonce}",
            error_content=fallback,
        )
        if src.startswith("https://"):
            return ft.Container(
                width=width, height=height, padding=3, bgcolor="#F0F3F6", border_radius=6,
                alignment=ft.Alignment(0, 0), content=image,
            )
        return image

    def aircraft_manufacturer_name(aircraft_name: Optional[str]) -> Optional[str]:
        key = canonical_aircraft_name(aircraft_name) or (aircraft_name or "")
        source = str(key).strip().lower()
        source_full = f"{source} {aircraft_name or ''}".lower()
        if source_full.startswith("airbus") or source.upper().startswith("A") or "airbus" in source_full:
            return "Airbus"
        if source_full.startswith("boeing") or source.upper().startswith("B") or "boeing" in source_full:
            return "Boeing"
        return None

    def manufacturer_logo_rel_path(manufacturer_name: Optional[str]) -> Optional[str]:
        manufacturer_name = (manufacturer_name or "").strip()
        if not manufacturer_name:
            return None
        if manufacturer_name in manufacturer_logo_cache:
            return manufacturer_logo_cache[manufacturer_name]

        rel = MANUFACTURER_LOGO_FILES.get(manufacturer_name)
        if not rel:
            manufacturer_logo_cache[manufacturer_name] = None
            return None
        primary_file_name = Path(rel).name
        file_names = [primary_file_name]
        for alt_name in MANUFACTURER_LOGO_ALTERNATE_FILES.get(manufacturer_name, []):
            if alt_name not in file_names:
                file_names.append(alt_name)
        for file_name in file_names:
            search_locations = [
                (Path(__file__).resolve().parent / "assets" / "aircraft" / "manufacturers" / file_name, f"aircraft/manufacturers/{file_name}"),
                (Path.cwd() / "assets" / "aircraft" / "manufacturers" / file_name, f"aircraft/manufacturers/{file_name}"),
                (Path(__file__).resolve().parent / "assets" / "manufacturers" / file_name, f"manufacturers/{file_name}"),
                (Path.cwd() / "assets" / "manufacturers" / file_name, f"manufacturers/{file_name}"),
            ]
            for candidate, return_rel in search_locations:
                if candidate.exists():
                    manufacturer_logo_cache[manufacturer_name] = return_rel
                    return return_rel
        manufacturer_logo_cache[manufacturer_name] = None
        return None

    def manufacturer_logo_image(
        aircraft_name: Optional[str],
        width: int = 54,
        height: int = 42,
        fallback_icon=True,
        key_prefix: str = "manufacturer-logo",
    ) -> ft.Control:
        manufacturer = aircraft_manufacturer_name(aircraft_name)
        rel = manufacturer_logo_rel_path(manufacturer)
        if rel:
            return ft.Image(
                src=rel,
                width=width,
                height=height,
                fit=ft.BoxFit.CONTAIN,
                key=f"{key_prefix}-{manufacturer}-{state.logo_refresh_nonce}",
            )
        if manufacturer:
            return ft.Text(manufacturer.upper(), size=10, weight=ft.FontWeight.W_800, color=tokens["accent"], text_align=ft.TextAlign.CENTER)
        if fallback_icon:
            return ft.Icon(ft.Icons.FLIGHT, size=32, color=tokens["accent"])
        return ft.Container(width=width, height=height)

    def airline_logo_watermark(
        airline_name: Optional[str],
        width: int = 320,
        height: int = 180,
        opacity: float = 0.13,
    ) -> ft.Control:
        rel = airline_logo_rel_path(airline_name)
        current_airline = (airline_name or "").strip()
        if not rel:
            return ft.Container()
        return ft.Container(
            expand=True,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=ft.Image(
                src=rel,
                width=width,
                height=height,
                fit=ft.BoxFit.COVER,
                opacity=opacity,
                key=f"watermark-{current_airline}-{state.logo_refresh_nonce}",
            ),
        )

    def safe_asset_slug(value: Optional[str]) -> str:
        raw = (value or "").strip().lower()
        raw = raw.replace("&", "and")
        raw = re.sub(r"[^a-z0-9]+", "_", raw)
        raw = re.sub(r"_+", "_", raw).strip("_")
        return raw

    AIRLINE_LIVERY_SLUGS = {
        "Air France": "air_france",
        "American Airlines": "american_airlines",
        "ANA": "ana",
        "British Airways": "british_airways",
        "Cathay Pacific": "cathay_pacific",
        "Delta Air Lines": "delta_air_lines",
        "Emirates": "emirates",
        "Etihad Airways": "etihad_airways",
        "Generic": "generic",
        "Iran Air": "iran_air",
        "ITA Airways": "ita_airways",
        "Lufthansa": "lufthansa",
        "Mahan Air": "mahan_air",
        "Qantas": "qantas",
        "Qatar Airways": "qatar_airways",
        "Singapore Airlines": "singapore_airlines",
        "Southwest Airlines": "southwest_airlines",
        "Turkish Airlines": "turkish_airlines",
        "United Airlines": "united_airlines",
        "Virgin Atlantic": "virgin_atlantic",
    }

    AIRCRAFT_LIVERY_SLUGS = {
        "A220-300": "a220_300",
        "A320-200": "a320_200",
        "A321-200": "a321_200",
        "A321neo": "a321neo",
        "A330-200": "a330_200",
        "A330-300": "a330_300",
        "A330-800": "a330_800",
        "A330-900": "a330_900",
        "A340-600": "a340_600",
        "A350-900": "a350_900",
        "A350-900-LH100": "a350_900_100_years",
        "A350-1000": "a350_1000",
        "A380-800": "a380_800",
        "B737-8MAX": "b737_8_max",
        "B747-8": "b747_8",
        "B747-200": "b747_200",
        "B757-200": "b757_200",
        "B777-200ER": "b777_200er",
        "B777-300ER": "b777_300er",
        "B787-9": "b787_9",
        "B787-10": "b787_10",
    }

    GENERIC_AIRCRAFT_FILE_STEMS = {
        "A320-200": ["a320-200", "generic_a320_200"],
        "A321-200": ["a321-200", "generic_a321_200"],
        "A321neo": ["a321neo", "generic_a321neo", "a321-200", "generic_a321_200"],
        "A330-200": ["a330-200", "generic_a330_200", "a330-300", "generic_a330_300"],
        "A330-300": ["a330-300", "generic_a330_300"],
        "A330-800": ["a330-800", "a330-800neo", "generic_a330_800", "a330-300", "generic_a330_300"],
        "A330-900": ["a330-900", "a330-900neo", "generic_a330_900", "a330-300", "generic_a330_300"],
        "A340-600": ["a340-600", "generic_a340_600"],
        "A350-900": ["a350-900", "generic_a350_900"],
        "A350-900-LH100": ["a350-900", "generic_a350_900"],
        "A350-1000": ["a350-1000", "generic_a350_1000", "a350-900", "generic_a350_900"],
        "A380-800": ["a380-800", "generic_a380_800"],
        "B737-8MAX": ["737-8-max", "b737-8-max", "generic_b737_8_max"],
        "B747-8": ["747-8", "b747-8", "generic_b747_8"],
        "B747-200": ["747-200", "b747-200", "generic_b747_200"],
        "B757-200": ["757-200", "b757-200", "generic_b757_200"],
        "B777-200ER": ["777-200er", "b777-200er", "generic_b777_200er"],
        "B777-200LR": ["777-200lr", "b777-200lr", "generic_b777_200lr"],
        "B777-300ER": ["777-300er", "b777-300er", "generic_b777_300er"],
        "B787-8": ["787-8", "b787-8", "generic_b787_8"],
        "B787-9": ["787-9", "b787-9", "generic_b787_9"],
        "B787-10": ["787-10", "b787-10", "generic_b787_10"],
    }

    AIRCRAFT_LIVERY_FALLBACK_SLUGS = {
        "a321neo": ["a321_200"],
        "a350_1000": ["a350_900"],
        "b737_8_max": ["b737_8_max"],
    }

    # Exact livery image addresses. Place these JPEG files here:
    # assets/aircraft/liveries/lufthansa_b747_8.jpeg
    # assets/aircraft/liveries/iran_air_b747_200.jpeg
    AIRCRAFT_LIVERY_EXACT_FILES = {
        ("Lufthansa", "B747-8"): "lufthansa_b747_8.jpeg",
        ("Iran Air", "B747-200"): "iran_air_b747_200.jpeg",
        ("Lufthansa", "A350-900-LH100"): "lufthansa_a350_900_100_years.jpg",
    }

    def aircraft_livery_rel_path(airline_name: Optional[str], aircraft_name: Optional[str]) -> Optional[str]:
        aircraft_key = canonical_aircraft_name(aircraft_name)
        raw_aircraft_key = (aircraft_name or "").strip()
        if not aircraft_key and raw_aircraft_key in AIRCRAFT_LIVERY_SLUGS:
            aircraft_key = raw_aircraft_key
        if not aircraft_key:
            return None

        airline_label = (airline_name or "").strip()
        cache_key = (airline_label, aircraft_key)
        if cache_key in aircraft_livery_cache:
            return aircraft_livery_cache[cache_key]

        exact_filename = AIRCRAFT_LIVERY_EXACT_FILES.get((airline_label, aircraft_key))
        if exact_filename:
            exact_rel = asset_rel_path_if_exists(f"aircraft/liveries/{exact_filename}")
            if exact_rel:
                aircraft_livery_cache[cache_key] = exact_rel
                return exact_rel

        airline_slug = AIRLINE_LIVERY_SLUGS.get(airline_label) or safe_asset_slug(airline_name) or "generic"
        aircraft_slug = AIRCRAFT_LIVERY_SLUGS.get(aircraft_key) or safe_asset_slug(aircraft_key)
        aircraft_slug_candidates = [aircraft_slug] + AIRCRAFT_LIVERY_FALLBACK_SLUGS.get(aircraft_slug, [])

        filename_candidates = []
        if airline_label == "Generic":
            for stem in GENERIC_AIRCRAFT_FILE_STEMS.get(aircraft_key, []):
                for ext in ("webp", "png", "jpeg", "jpg"):
                    filename_candidates.append(f"aircraft/generic/{stem}.{ext}")
                    filename_candidates.append(f"aircraft/liveries/{stem}.{ext}")
        for slug in aircraft_slug_candidates:
            if airline_slug:
                for ext in ("webp", "png", "jpeg", "jpg"):
                    filename_candidates.append(f"aircraft/liveries/{airline_slug}_{slug}.{ext}")
            for ext in ("webp", "png", "jpeg", "jpg"):
                filename_candidates.append(f"aircraft/liveries/generic_{slug}.{ext}")

        # Airline-specific artwork wins; otherwise use the shared transparent
        # aircraft profile so every supported fleet entry remains visual.
        if airline_label != "Generic":
            for stem in GENERIC_AIRCRAFT_FILE_STEMS.get(aircraft_key, []):
                for ext in ("webp", "png", "jpeg", "jpg"):
                    filename_candidates.append(f"aircraft/generic/{stem}.{ext}")
                    filename_candidates.append(f"aircraft/liveries/{stem}.{ext}")

        for filename in filename_candidates:
            rel = asset_rel_path_if_exists(filename)
            if rel:
                aircraft_livery_cache[cache_key] = rel
                return rel
        aircraft_livery_cache[cache_key] = None
        return None

    def aircraft_livery_image(
        airline_name: Optional[str],
        aircraft_name: Optional[str],
        width: int = 300,
        height: int = 150,
    ) -> ft.Control:
        aircraft_key = canonical_aircraft_name(aircraft_name) or (aircraft_name or "").strip()
        rel = (
            aircraft_profile_path(aircraft_key) if airline_name == "Generic"
            else aircraft_livery_rel_path(airline_name, aircraft_key)
        )
        if rel:
            return ft.Image(
                src=rel,
                width=width,
                height=height,
                fit=ft.BoxFit.CONTAIN,
                key=f"aircraft-livery-{safe_asset_slug(airline_name)}-{safe_asset_slug(aircraft_key)}-{state.logo_refresh_nonce}",
            )
        return ft.Column(
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
            controls=[
                ft.Icon(ft.Icons.IMAGE_OUTLINED, size=34, color=tokens["muted"]),
                ft.Text("Aircraft image", size=12, weight=ft.FontWeight.W_700, color=tokens["text"]),
                ft.Text("Select airline and aircraft", size=11, color=tokens["muted"]),
            ],
        )

    def aircraft_profile_path(aircraft_name: Optional[str]) -> Optional[str]:
        return aircraft_livery_rel_path("Generic", aircraft_name)

    def aircraft_profile_image(aircraft_name: Optional[str], width: int, height: int) -> ft.Control:
        return aircraft_livery_image("Generic", aircraft_name, width=width, height=height)

    def show_snack(message: str):
        page.show_dialog(ft.SnackBar(ft.Text(message)))

    def show_alert(dialog):
        prepare_controls(dialog)
        page.show_dialog(dialog)

    async def show_page_guide(tab):
        nonlocal tutorial_dialog
        await asyncio.sleep(0.15)
        guide = page_guides.get(2 if tab == 3 else tab)
        if (not guide or not state.is_logged_in or state.selected_tab_index != tab or state.tutorial_skipped
                or guide[0] in state.tutorial_seen or flight_hibernation_prompt_modal.visible
                or (tutorial_dialog and tutorial_dialog.open)):
            return
        title, instructions = guide

        def dismiss(e, *, skip_all=False):
            if skip_all:
                state.tutorial_skipped = True
                save_settings_data()
            page.pop_dialog()

        tutorial_dialog = ft.AlertDialog(
            modal=True, title=ft.Text(title), content=ft.Text(instructions, width=380),
            actions=[
                ft.TextButton("Skip all tutorials", on_click=lambda e: dismiss(e, skip_all=True)),
                ft.FilledButton("Got it", on_click=dismiss),
            ],
        )
        show_alert(tutorial_dialog)
        state.tutorial_seen.add(title)
        save_settings_data()

    def safe_update_control(ctrl):
        try:
            if getattr(ctrl, "page", None):
                prepare_controls(ctrl)
                ctrl.update()
        except Exception:
            pass

    def safe_update_live_header_controls(include_clock: bool = False, include_banner: bool = False):
        # Keep the always-running clock/progress loop lightweight. Updating only
        # the affected controls avoids a full page refresh every progress tick.
        if include_clock:
            for ctrl in (
                txt_welcome,
                txt_time,
                txt_location,
                txt_weather,
                overview_date_text,
                overview_time_text,
                overview_location_text,
                overview_weather_text,
                takeoff_date_text,
                takeoff_route_time_text,
                takeoff_time_text,
                takeoff_clock_source_text,
                takeoff_analog_clock_host,
                takeoff_location_text,
                takeoff_weather_text,
                landing_date_text,
                landing_route_time_text,
                landing_time_text,
                landing_clock_source_text,
                landing_analog_clock_host,
            ):
                safe_update_control(ctrl)
            if state.selected_tab_index == 1:
                for ctrl in (dashboard_weekday_text, dashboard_date_text, dashboard_year_text):
                    safe_update_control(ctrl)
        if include_banner:
            safe_update_control(header_route_line_host)

    def asset_rel_path_if_exists(rel_path: Optional[str]) -> Optional[str]:
        if not rel_path:
            return None
        rel_path = str(rel_path).replace("\\", "/").strip("/")
        if rel_path in asset_rel_cache:
            return asset_rel_cache[rel_path]

        rel_parts = [part for part in rel_path.split("/") if part]
        search_dirs = [
            Path(__file__).resolve().parent / "assets",
            Path.cwd() / "assets",
        ]
        try:
            if getattr(sys, "frozen", False):
                search_dirs.insert(0, Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets")
                search_dirs.insert(1, Path(sys.executable).resolve().parent / "assets")
        except Exception:
            pass
        for directory in search_dirs:
            candidate = directory.joinpath(*rel_parts)
            if candidate.exists():
                asset_rel_cache[rel_path] = rel_path
                return rel_path
        asset_rel_cache[rel_path] = None
        return None

    def asset_abs_path_if_exists(rel_path: Optional[str]) -> Optional[Path]:
        if not rel_path:
            return None
        rel_path = str(rel_path).replace("\\", "/").strip("/")
        rel_parts = [part for part in rel_path.split("/") if part]
        search_dirs = [
            Path(__file__).resolve().parent / "assets",
            Path.cwd() / "assets",
        ]
        for directory in search_dirs:
            candidate = directory.joinpath(*rel_parts)
            if candidate.exists():
                return candidate
        return None

    def app_background_src() -> Optional[str]:
        # Background Project: one global image under the whole app.
        # Supported files, in priority order. Put one of these in assets/backgrounds/.
        for rel_path in (
            "backgrounds/app_background.png",
            "backgrounds/app_background.jpg",
            "backgrounds/app_background.jpeg",
            "backgrounds/app_background.webp",
        ):
            found = asset_rel_path_if_exists(rel_path)
            if found:
                return found
        return None

    def app_background_instruction_path() -> str:
        return str(base_dir / "assets" / "backgrounds" / "app_background.png")

    def daylight_background_src() -> Optional[str]:
        # Daytime display background. Place one of these files here:
        # C:\FMS\assets\backgrounds\daytime_display.png
        for rel_path in (
            "backgrounds/daytime_display.png",
            "backgrounds/daytime_display.jpg",
            "backgrounds/daytime_display.jpeg",
            "backgrounds/daytime_display.webp",
            "home_bg.jpg",
        ):
            found = asset_rel_path_if_exists(rel_path)
            if found:
                return found
        return app_background_src()

    def daylight_background_instruction_path() -> str:
        return str(base_dir / "assets" / "backgrounds" / "daytime_display.png")

    def use_daylight_cards() -> bool:
        return (
            str(getattr(state, "display_mode", "dark") or "dark").lower() == "daylight"
            and int(getattr(state, "selected_tab_index", 0) or 0) != 0
        )

    def page_background_src(page_key: str) -> Optional[str]:
        # Background Project rewrite:
        # Disable older per-page backgrounds so they cannot cover or compete with
        # the new global background image.
        return None

    def login_audio_rel_src() -> Optional[str]:
        return asset_rel_path_if_exists("audio/login.mp3")

    def login_audio_abs_path() -> Optional[Path]:
        return asset_abs_path_if_exists("audio/login.mp3")

    def effective_app_volume() -> float:
        if bool(getattr(state, "app_muted", False)):
            return 0.0
        return clamp_setting(getattr(state, "app_volume", 0.85), 0.0, 1.0, 0.85)

    def play_mp3_windows_mci(audio_path: Path):
        # Windows desktop fallback for MP3 playback. This does not depend on
        # Flet's Audio control, which may be unavailable in some desktop builds.
        def _worker():
            alias = f"fms_audio_{int(time.time() * 1000)}"
            path_str = str(audio_path)

            def mci(command: str) -> int:
                return ctypes.windll.winmm.mciSendStringW(command, None, 0, None)

            try:
                mci(f'close {alias}')
                result = mci(f'open "{path_str}" type mpegvideo alias {alias}')
                if result != 0:
                    return
                volume_value = int(effective_app_volume() * 1000)
                if volume_value <= 0:
                    return
                mci(f'setaudio {alias} volume to {volume_value}')
                mci(f'play {alias}')
                # The audio is short. Keep the MCI alias alive long enough, then close.
                time.sleep(8.0)
            except Exception:
                pass
            finally:
                try:
                    ctypes.windll.winmm.mciSendStringW(f"close {alias}", None, 0, None)
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def play_login_audio():
        audio_abs = login_audio_abs_path()
        if not audio_abs:
            return

        # Prefer native Windows MP3 playback on Windows because it works even
        # when ft.Audio is not available or silent.
        if os.name == "nt":
            play_mp3_windows_mci(audio_abs)
            return

        # Fallback for non-Windows/Flet builds.
        if login_audio is None:
            return

        audio_src = login_audio_rel_src()
        if not audio_src:
            return

        try:
            if getattr(login_audio, "src", None) != audio_src:
                login_audio.src = audio_src
            if effective_app_volume() <= 0:
                return
            if hasattr(login_audio, "volume"):
                login_audio.volume = effective_app_volume()
            if hasattr(login_audio, "seek"):
                try:
                    login_audio.seek(0)
                except Exception:
                    pass
            if hasattr(login_audio, "play"):
                login_audio.play()
            elif hasattr(login_audio, "resume"):
                login_audio.resume()
            if getattr(login_audio, "page", None):
                login_audio.update()
        except Exception:
            pass


    def seatbelt_sign_audio_abs_path() -> Optional[Path]:
        return (
            asset_abs_path_if_exists("audio/seatbelt_sign.mp3")
            or asset_abs_path_if_exists("audio/seat_belt_sign.mp3")
            or asset_abs_path_if_exists("sounds/seatbelt_sign.mp3")
            or asset_abs_path_if_exists("sounds/seat_belt_sign.mp3")
            or asset_abs_path_if_exists("seatbelt_sign.mp3")
            or asset_abs_path_if_exists("seat_belt_sign.mp3")
        )

    def play_seatbelt_sign_audio(e=None):
        audio_abs = seatbelt_sign_audio_abs_path()
        if not audio_abs:
            try:
                seat_status_text.value = "Seat belt sign audio not found. Add it to assets/audio/seatbelt_sign.mp3."
                page.update()
            except Exception:
                pass
            return

        if os.name == "nt":
            play_mp3_windows_mci(audio_abs)
            return


    def build_tab_page(page_key: str, content: ft.Control, overlay_opacity: float = 0.10) -> ft.Control:
        # All tabs must stay transparent so the global background project remains
        # visible behind the header, navigation rail, and page content.
        return ft.Container(
            expand=True,
            bgcolor=ft.Colors.TRANSPARENT,
            alignment=ft.Alignment(-1, -1),
            content=content,
        )


    def aircraft_value(record: dict) -> str:
        return canonical_aircraft_name(record["name"]) or record["name"]

    def aviation_autocomplete(label, kind, value, on_selection, *, width=None, expand=False, dropdown=False,
                              commit_airport_code=False, floating_results=None):
        nonlocal close_suggestions
        selected = bool(value)
        revision = 0
        field = ft.TextField(
            label=label, value=value or "", border_radius=14, filled=True,
            bgcolor=tokens["input_bg"], hint_text="Search by name or code",
            color=tokens["text"], label_style=ft.TextStyle(color=tokens["muted"]),
            hint_style=ft.TextStyle(color=tokens["muted"]),
        )
        suggestions = ft.ListView(spacing=2, visible=False, height=0)
        results = ft.Container(
            content=suggestions, visible=False, bgcolor=tokens["panel"], border_radius=CONTROL_RADIUS,
            border=ft.Border.all(1, tokens["card_border"]), clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        ) if dropdown else suggestions
        if floating_results is not None:
            floating_results[label] = results
        control = ft.Column(
            [field, results] if floating_results is None else [field],
            width=width, expand=expand or None, spacing=4, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH if dropdown else ft.CrossAxisAlignment.START,
        )

        def show(controls, height=None):
            suggestions.controls = controls
            suggestions.visible = results.visible = bool(controls)
            suggestions.height = height if height is not None else (28 if controls else 0)
            safe_update_control(results if floating_results is not None else control)

        def dismiss():
            nonlocal revision
            revision += 1
            show([])

        def choose(record):
            nonlocal selected
            selected = True
            field.value = record["code"] if kind == "airport" else record["name"]
            dismiss()
            if floating_results is not None:
                safe_update_control(field)
            on_selection(record)

        async def search(e):
            nonlocal revision, selected, close_suggestions
            query = field.value or ""
            if selected and (not commit_airport_code or not query.strip()):
                selected = False
                on_selection(None)
            if close_suggestions and close_suggestions is not dismiss:
                close_suggestions()
            close_suggestions = dismiss
            revision += 1
            request_revision = revision
            if len(search_key(query)) < 2:
                show([])
                return
            show([ft.Text("Searching…", color=tokens["muted"])])
            await asyncio.sleep(0.25 if commit_airport_code else 0.5)
            if request_revision != revision or query != (field.value or ""):
                return
            code = query.strip().upper()
            # Three-letter IATA codes can also be the start of a four-letter ICAO code.
            is_icao = commit_airport_code and re.fullmatch(r"[A-Z]{4}", code)
            if is_icao and (record := AIRPORT_LIBRARY.get(code)):
                choose(record)
                return

            local = ()
            if kind == "aircraft":
                local = tuple(
                    dict(id=key, code=key, name=row["name"],
                         manufacturer=row.get("manufacturer") or row["name"].split()[0])
                    for key, row in AIRCRAFT_LIBRARY.items()
                )
            elif kind == "airline":
                local = tuple(
                    dict(id=name, name=name, iata=AIRLINE_CALLSIGNS.get(name, ""))
                    for name in AIRLINES
                )
            elif kind == "airport":
                local = tuple(AIRPORT_LIBRARY.values())
            records, unavailable = await asyncio.to_thread(search_catalog, kind, query, local)
            if request_revision != revision or query != (field.value or ""):
                return
            if is_icao:
                exact = next((record for record in records if record.get("icao") == code or record.get("code") == code), None)
                if exact:
                    choose(exact)
                    return

            rows = []
            for record in records:
                keys = ("city", "iata", "icao", "code") if dropdown and kind == "airport" else ("iata", "icao", "callsign", "manufacturer")
                details = [record.get(key) for key in keys]
                leading = None
                if kind == "airline":
                    logo = airline_logo_source(record["name"], record.get("iata"))
                    fallback = ft.Icon(ft.Icons.FLIGHT, size=18, color="#526171")
                    leading = ft.Container(
                        width=48,
                        height=32,
                        padding=3,
                        border_radius=6,
                        alignment=ft.Alignment(0, 0),
                        bgcolor="#F0F3F6",
                        content=ft.Image(
                            src=logo, width=42, height=26, fit=ft.BoxFit.CONTAIN,
                            error_content=fallback,
                        ) if logo else fallback,
                    )
                rows.append(ft.ListTile(
                    title=ft.Text(record["name"], size=13, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    subtitle=ft.Text(" · ".join(dict.fromkeys(value for value in details if value)), size=11),
                    leading=leading, dense=True, on_click=lambda e, row=record: choose(row),
                ))
            if unavailable:
                rows.append(ft.TextButton("Search unavailable · Retry", on_click=search))
            elif not rows:
                rows.append(ft.Text("No matches", color=tokens["muted"]))
            show(rows, min(156 if floating_results is not None else 230, len(rows) * 62))

        field.on_change = search
        return control

    def on_aviation_keyboard(event):
        if event.key == "Escape" and close_suggestions:
            close_suggestions()

    page.on_keyboard_event = on_aviation_keyboard

    def planner_search(key, label, backing):
        kind = "airport" if key in ("origin", "destination") else key
        record = planner_records.get(key, {})
        def select(selected):
            if selected:
                planner_records[key] = selected
                if kind == "airport":
                    remember_airport(selected)
                    backing.value = selected["code"]
                elif kind == "aircraft":
                    backing.value = aircraft_value(selected)
                else:
                    backing.value = selected["name"]
            else:
                planner_records.pop(key, None)
                backing.value = None
            if kind == "airport":
                refresh_calendar_route_preview()

        display = backing.value if kind == "airport" else record.get("name") or backing.value
        return aviation_autocomplete(label, kind, display, select, width=200)

    def airport_card_background_src(code: Optional[str], fallback_key: str = "airport") -> Optional[str]:
        canonical = normalize_airport_code(code)
        image = airport_images.get(canonical)
        if image:
            return image
        for key in (fallback_key, "airport"):
            for ext in ("jpg", "jpeg", "png", "webp"):
                found = asset_rel_path_if_exists(f"overview/airport_cards/{key}_default.{ext}")
                if found:
                    return found
        return None

    def open_help_center(e=None):
        help_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Help"),
            content=ft.Container(
                width=390,
                content=ft.Column(
                    tight=True,
                    spacing=10,
                    controls=[
                        ft.Text("How do I add a new airline logo?", weight=ft.FontWeight.W_700, color=tokens["text"]),
                        ft.Text("1. Put the PNG file inside assets/airlines.", size=12, color=tokens["text"]),
                        ft.Text("2. Use a clear file name like airline_name.png.", size=12, color=tokens["text"]),
                        ft.Text("3. If it is a new airline, also add its name and logo path in the airline lists inside the app.", size=12, color=tokens["muted"]),
                    ],
                ),
            ),
            actions=[ft.TextButton("Close", on_click=lambda evt: page.pop_dialog())],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        show_alert(help_dialog)

    status_gate_tf = ft.TextField(label="Gate", value=state.departure_gate or "", width=180, border_radius=16, filled=True)
    status_boarding_dd = ft.Dropdown(
        label="Boarding",
        value=state.boarding_status,
        options=[ft.dropdown.Option("Not started"), ft.dropdown.Option("In process"), ft.dropdown.Option("Completed")],
        width=180,
        border_radius=16,
        filled=True,
    )
    status_cargo_dd = ft.Dropdown(
        label="Cargo",
        value=state.cargo_status,
        options=[ft.dropdown.Option("Not started"), ft.dropdown.Option("In process"), ft.dropdown.Option("Completed")],
        width=180,
        border_radius=16,
        filled=True,
    )
    status_catering_dd = ft.Dropdown(
        label="Catering",
        value=state.catering_status,
        options=[ft.dropdown.Option("Not started"), ft.dropdown.Option("In process"), ft.dropdown.Option("Completed")],
        width=180,
        border_radius=16,
        filled=True,
    )


    status_center_modal = ft.Container(
        visible=False,
        expand=True,
        bgcolor=ft.Colors.with_opacity(0.36, ft.Colors.BLACK),
        alignment=ft.Alignment(0, 0),
        content=ft.Container(
            width=460,
            padding=20,
            border_radius=22,
            bgcolor=surface_fill(tokens["panel"]),
            border=ft.border.all(1, tokens["card_border"]),
            shadow=ft.BoxShadow(
                blur_radius=24,
                spread_radius=1,
                color=ft.Colors.with_opacity(0.20, ft.Colors.BLACK),
                offset=ft.Offset(0, 8),
            ),
            content=ft.Column(
                tight=True,
                spacing=14,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text("Cabin and Cargo Status", size=18, weight=ft.FontWeight.W_800, color=tokens["text"]),
                            ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close", on_click=lambda e: close_status_center()),
                        ],
                    ),
                    ft.Text("Update the current turnaround status and departure gate.", size=12, color=tokens["muted"]),
                    ft.Row(wrap=True, spacing=12, controls=[status_gate_tf, status_boarding_dd]),
                    ft.Row(wrap=True, spacing=12, controls=[status_cargo_dd, status_catering_dd]),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.END,
                        controls=[
                            ft.TextButton("Cancel", on_click=lambda evt: close_status_center()),
                            ft.ElevatedButton("Save", on_click=lambda evt: save_status_center(), bgcolor=tokens["primary"], color=tokens["on_primary"]),
                        ],
                    ),
                ],
            ),
        ),
    )

    airline_picker_modal = ft.Container(
        visible=False,
        expand=True,
        bgcolor=ft.Colors.with_opacity(0.30, ft.Colors.BLACK),
        alignment=ft.Alignment(0, 1),
        content=ft.Container(),
    )

    aircraft_picker_modal = ft.Container(
        visible=False,
        expand=True,
        bgcolor=ft.Colors.with_opacity(0.30, ft.Colors.BLACK),
        alignment=ft.Alignment(0, 1),
        content=ft.Container(),
    )

    flight_hibernation_prompt_modal = ft.Container(
        visible=False,
        expand=True,
        bgcolor=ft.Colors.with_opacity(0.58, ft.Colors.BLACK),
        alignment=ft.Alignment(0, 0),
        content=ft.Container(),
    )

    flight_end_summary_modal = ft.Container(
        visible=False,
        expand=True,
        bgcolor=ft.Colors.with_opacity(0.58, ft.Colors.BLACK),
        alignment=ft.Alignment(0, 0),
        content=ft.Container(),
    )

    def open_status_center(e=None):
        status_gate_tf.value = state.departure_gate or ""
        status_boarding_dd.value = state.boarding_status
        status_cargo_dd.value = state.cargo_status
        status_catering_dd.value = state.catering_status
        status_center_modal.visible = True
        status_center_modal.update() if getattr(status_center_modal, 'page', None) else None
        page.update()

    def close_status_center():
        status_center_modal.visible = False
        status_center_modal.update() if getattr(status_center_modal, 'page', None) else None
        page.update()

    def save_status_center():
        state.departure_gate = (status_gate_tf.value or "").strip()
        state.boarding_status = status_boarding_dd.value or "Not started"
        state.cargo_status = status_cargo_dd.value or "Not started"
        state.catering_status = status_catering_dd.value or "Not started"
        takeoff_gate_tf.value = state.departure_gate
        close_status_center()
        refresh_ui()

    page.overlay.append(status_center_modal)
    page.overlay.append(airline_picker_modal)
    page.overlay.append(aircraft_picker_modal)
    page.overlay.append(flight_hibernation_prompt_modal)
    page.overlay.append(flight_end_summary_modal)
    if login_audio is not None:
        page.overlay.append(login_audio)

    def parse_calendar_entry_datetime(entry: dict) -> datetime:
        date_str = (entry.get("date") or "").strip()
        time_str = (entry.get("time") or "").strip() or "00:00"
        try:
            return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except Exception:
            try:
                return datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                return datetime.min

    def parse_flight_time_minutes(value: str) -> int:
        raw = (value or "").strip().lower()
        if not raw or raw == "—":
            return 0
        hhmm = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
        if hhmm:
            return int(hhmm.group(1)) * 60 + int(hhmm.group(2))
        hours_match = re.search(r"(\d+)\s*h", raw)
        mins_match = re.search(r"(\d+)\s*m", raw)
        total = 0
        if hours_match:
            total += int(hours_match.group(1)) * 60
        if mins_match:
            total += int(mins_match.group(1))
        if total > 0:
            return total
        digits = re.findall(r"\d+", raw)
        if len(digits) == 1:
            return int(digits[0])
        return 0

    def sort_calendar_entries_default():
        state.calendar_entries.sort(
            key=lambda entry: (parse_calendar_entry_datetime(entry), entry.get("airline", "")),
            reverse=True,
        )

    sort_calendar_entries_default()

    def get_filtered_sorted_calendar_entries() -> List[dict]:
        entries = list(state.calendar_entries)
        status_filter = cal_status_filter_dd.value or "All"
        if status_filter == "Completed only":
            entries = [entry for entry in entries if bool(entry.get("completed"))]
        elif status_filter == "Planned only":
            entries = [entry for entry in entries if not bool(entry.get("completed"))]

        sort_mode = cal_sort_dd.value or "Most recent date"
        if sort_mode == "Oldest date":
            entries.sort(key=lambda entry: (parse_calendar_entry_datetime(entry), entry.get("airline", "")))
        elif sort_mode == "Longest flight time":
            entries.sort(
                key=lambda entry: (parse_flight_time_minutes(entry.get("flight_time", "")), parse_calendar_entry_datetime(entry)),
                reverse=True,
            )
        elif sort_mode == "Shortest flight time":
            entries.sort(
                key=lambda entry: (parse_flight_time_minutes(entry.get("flight_time", "")), parse_calendar_entry_datetime(entry)),
            )
        else:
            entries.sort(key=lambda entry: (parse_calendar_entry_datetime(entry), entry.get("airline", "")), reverse=True)
        return entries

    def get_completed_log_entries() -> List[dict]:
        entries = [entry for entry in state.calendar_entries if bool(entry.get("completed"))]
        sort_mode = log_sort_dd.value or "Most recent date"
        entries.sort(
            key=lambda entry: (parse_calendar_entry_datetime(entry), entry.get("airline", "")),
            reverse=sort_mode != "Oldest date",
        )
        if sort_mode in ("Lowest landing G", "Highest landing G"):
            direction = 1 if sort_mode == "Lowest landing G" else -1

            def landing_sort_key(entry):
                value = parse_landing_g(entry.get("landing_g"))
                return direction * value if value is not None else math.inf

            entries.sort(key=landing_sort_key)
        return entries

    def summarize_log_entries(entries: List[dict]) -> dict:
        total_flights = len(entries)
        total_minutes = sum(parse_flight_time_minutes(entry.get("flight_time", "")) for entry in entries)
        average_minutes = int(round(total_minutes / total_flights)) if total_flights else 0

        aircraft_counts: Dict[str, int] = {}
        route_counts: Dict[str, int] = {}
        for entry in entries:
            aircraft = (entry.get("aircraft") or "").strip()
            route = (entry.get("route") or "").strip()
            if aircraft:
                aircraft_counts[aircraft] = aircraft_counts.get(aircraft, 0) + 1
            if route:
                route_counts[route] = route_counts.get(route, 0) + 1

        most_used_aircraft = max(aircraft_counts, key=aircraft_counts.get) if aircraft_counts else "—"
        most_used_route = max(route_counts, key=route_counts.get) if route_counts else "—"

        return {
            "total_flights": str(total_flights),
            "total_hours": format_hours_to_hm(total_minutes / 60.0) if total_minutes else "—",
            "most_used_aircraft": most_used_aircraft,
            "most_used_route": most_used_route,
            "average_sector": format_hours_to_hm(average_minutes / 60.0) if average_minutes else "—",
        }

    def weather_icon_and_label(weather_code: Optional[int], is_day: bool = True, wind_speed_kmh: Optional[float] = None):
        if wind_speed_kmh is not None and wind_speed_kmh >= 35:
            return "💨", "Windy"
        if weather_code is None:
            return "🌡️", "Weather unavailable"
        if weather_code == 0:
            return ("☀️" if is_day else "🌙"), WEATHER_CODE_LABELS.get(weather_code, "Clear")
        if weather_code in (1, 2):
            return ("⛅" if is_day else "☁️"), WEATHER_CODE_LABELS.get(weather_code, "Partly cloudy")
        if weather_code in (3, 45, 48):
            return "☁️", WEATHER_CODE_LABELS.get(weather_code, "Cloudy")
        if weather_code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
            return "🌧️", WEATHER_CODE_LABELS.get(weather_code, "Rain")
        if weather_code in (71, 73, 75, 77, 85, 86):
            return "❄️", WEATHER_CODE_LABELS.get(weather_code, "Snow")
        if weather_code in (95, 96, 99):
            return "⛈️", WEATHER_CODE_LABELS.get(weather_code, "Thunderstorm")
        return "🌤️", WEATHER_CODE_LABELS.get(weather_code, "Weather")

    def format_temperature_for_default_unit(temp_c: Optional[float]) -> str:
        if temp_c is None:
            return "—"
        try:
            value_c = float(temp_c)
        except Exception:
            return "—"
        if getattr(state, "default_temperature_unit", "°C") == "°F":
            return f"{round(value_c * 9 / 5 + 32)}°F"
        return f"{round(value_c)}°C"

    async def load_airport_media(code: str):
        async def get_record():
            record = lookup_airport_record(code)
            if record:
                return record
            matches, _ = await asyncio.to_thread(search_catalog, "airport", code)
            record = next((row for row in matches if code in (row["code"], row["iata"])), None)
            if record:
                remember_airport(record)
            return record

        async def load_report(station):
            requested_at = time.monotonic()
            try:
                report = await asyncio.to_thread(fetch_metar, station) if re.fullmatch(r"[A-Z]{4}", station) else {}
            except (OSError, ValueError):
                report = {}
            if airport_weather_cache.get(station, {}).get("timestamp", 0) <= requested_at:
                airport_weather_cache[station] = {"report": report, "timestamp": time.monotonic()}

        async def load_image(record, station):
            if station in airport_images or not record:
                return
            try:
                airport_images[station] = await asyncio.to_thread(city_image, record["city"], record["country"])
            except (OSError, ValueError):
                pass

        try:
            record = await get_record()
            station = (record.get("icao") or record["code"]) if record else code
            await asyncio.gather(load_report(station), load_image(record, station))
        finally:
            pending_airport_media.discard(code)
        route = {normalize_airport_code(state.departure), normalize_airport_code(state.arrival)}
        if state.is_logged_in and state.selected_tab_index in (0, 4, 5) and (station in route or code in route):
            refresh_active_page()

    def queue_airport_media(code: Optional[str]):
        canonical = normalize_airport_code(code)
        if not canonical or canonical in pending_airport_media:
            return
        cached = airport_weather_cache.get(canonical, {})
        ttl = 900 if cached.get("report") else 120
        if cached and time.monotonic() - cached["timestamp"] < ttl:
            return
        pending_airport_media.add(canonical)
        page.run_task(load_airport_media, canonical)

    def airport_weather_for_card(code: Optional[str], *, fetch: bool = True) -> dict:
        canonical = normalize_airport_code(code)
        if fetch:
            queue_airport_media(canonical)
        report = airport_weather_cache.get(canonical, {}).get("report", {})
        temperature = report.get("temp")
        icon, condition = metar_condition(report)
        return {
            "temperature": format_temperature_for_default_unit(float(temperature)) if temperature is not None else "—",
            "temperature_c": temperature,
            "icon": icon,
            "condition": condition,
        }

    def update_weather_from_coordinates(latitude: float, longitude: float):
        try:
            query = urllib.parse.urlencode(
                {
                    "latitude": f"{latitude:.5f}",
                    "longitude": f"{longitude:.5f}",
                    "current": "temperature_2m,weather_code,is_day,wind_speed_10m",
                    "timezone": "auto",
                }
            )
            url = f"https://api.open-meteo.com/v1/forecast?{query}"
            with urllib.request.urlopen(url, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            current = payload.get("current", {})
            temperature = current.get("temperature_2m")
            weather_code = current.get("weather_code")
            is_day = bool(current.get("is_day", 1))
            wind_speed = current.get("wind_speed_10m")
            icon, label = weather_icon_and_label(weather_code, is_day=is_day, wind_speed_kmh=wind_speed)
            state.weather.temperature_c = float(temperature) if temperature is not None else None
            state.weather.condition = label
            state.weather.icon = icon
        except Exception:
            state.weather.temperature_c = None
            state.weather.condition = "Weather unavailable"
            state.weather.icon = "🌡️"

    def readable_location_from_coordinates(latitude: float, longitude: float) -> str:
        """Return a readable nearby major city/area name instead of raw coordinates.
        First tries Open-Meteo reverse geocoding. If that fails, it uses a small
        offline major-city fallback so the Home page does not show raw coordinates.
        """
        try:
            query = urllib.parse.urlencode(
                {
                    "latitude": f"{latitude:.5f}",
                    "longitude": f"{longitude:.5f}",
                    "count": "1",
                    "language": "en",
                    "format": "json",
                }
            )
            url = f"https://geocoding-api.open-meteo.com/v1/reverse?{query}"
            with urllib.request.urlopen(url, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            result = (payload.get("results") or [{}])[0]
            city = (result.get("name") or "").strip()
            admin = (result.get("admin1") or "").strip()
            country = (result.get("country") or "").strip()
            if city:
                if country and country.lower() not in city.lower():
                    return f"{city}, {country}"
                return city
            if admin:
                return admin
        except Exception:
            pass

        # Offline fallback. This prevents raw coordinate labels when reverse
        # geocoding is blocked or unavailable in the desktop app.
        major_cities = [
            (52.5200, 13.4050, "Berlin, Germany"),
            (25.2048, 55.2708, "Dubai, UAE"),
            (40.7128, -74.0060, "New York, USA"),
            (35.6892, 51.3890, "Tehran, Iran"),
            (51.5072, -0.1276, "London, UK"),
            (48.8566, 2.3522, "Paris, France"),
            (41.0082, 28.9784, "Istanbul, Türkiye"),
            (25.2854, 51.5310, "Doha, Qatar"),
            (48.1351, 11.5820, "Munich, Germany"),
            (34.0522, -118.2437, "Los Angeles, USA"),
            (1.3521, 103.8198, "Singapore"),
            (35.6762, 139.6503, "Tokyo, Japan"),
            (55.7558, 37.6173, "Moscow, Russia"),
            (39.9334, 32.8597, "Ankara, Türkiye"),
            (19.0760, 72.8777, "Mumbai, India"),
            (21.3891, 39.8579, "Jeddah, Saudi Arabia"),
            (24.7136, 46.6753, "Riyadh, Saudi Arabia"),
            (31.2304, 121.4737, "Shanghai, China"),
            (22.3193, 114.1694, "Hong Kong"),
            (-33.8688, 151.2093, "Sydney, Australia"),
        ]
        try:
            import math
            def distance_score(item):
                lat, lon, _name = item
                return (latitude - lat) ** 2 + ((longitude - lon) * math.cos(math.radians(latitude))) ** 2
            nearest = min(major_cities, key=distance_score)
            return nearest[2]
        except Exception:
            return "Nearby major city unavailable"

    async def enable_location_tracking(e=None):
        if ftg is None:
            state.location_permission_enabled = False
            state.location_label = "Location unavailable"
            state.weather.temperature_c = None
            state.weather.condition = "Install flet-geolocator"
            state.weather.icon = "📍"
            refresh_ui()
            show_snack("Install the geolocator extension first: py -3.13 -m pip install flet-geolocator")
            return

        try:
            geo = ftg.Geolocator(
                configuration=ftg.GeolocatorConfiguration(
                    accuracy=ftg.GeolocatorPositionAccuracy.LOW
                ),
                on_error=lambda evt: None,
            )
            service_enabled = await geo.is_location_service_enabled()
            if not service_enabled:
                state.location_permission_enabled = False
                state.location_label = "Windows location services are off"
                state.weather.temperature_c = None
                state.weather.condition = "Enable location in Windows Settings"
                state.weather.icon = "📍"
                refresh_ui()
                show_snack("Windows location services are off. Use 'Open Location Settings' to enable them.")
                return

            permission = await geo.get_permission_status()
            permission_text = str(permission).lower()
            if "denied" in permission_text or "undetermined" in permission_text or "unknown" in permission_text:
                permission = await geo.request_permission(timeout=60)
                permission_text = str(permission).lower()

            if "denied" in permission_text:
                state.location_permission_enabled = False
                state.location_label = "Permission denied"
                state.weather.temperature_c = None
                state.weather.condition = "Allow app access to location"
                state.weather.icon = "📍"
                refresh_ui()
                show_snack("Location permission was denied. Check Windows privacy settings for location access.")
                return

            position = None
            try:
                position = await geo.get_current_position()
            except Exception:
                try:
                    position = await geo.get_last_known_position()
                except Exception:
                    position = None

            if position is None:
                state.location_permission_enabled = False
                state.location_label = "No position fix yet"
                state.weather.temperature_c = None
                state.weather.condition = "Try again near Wi-Fi or GPS"
                state.weather.icon = "📍"
                refresh_ui()
                show_snack("No location fix was available yet.")
                return

            state.location_permission_enabled = True
            state.location_label = readable_location_from_coordinates(position.latitude, position.longitude)
            update_weather_from_coordinates(position.latitude, position.longitude)
            refresh_ui()
            show_snack("Live device location updated.")
        except Exception as ex:
            state.location_permission_enabled = False
            state.location_label = "Location error"
            state.weather.temperature_c = None
            state.weather.condition = "Could not read device location"
            state.weather.icon = "📍"
            refresh_ui()
            show_snack(f"Location failed: {ex}")

    async def open_device_location_settings(e=None):
        if ftg is None:
            show_snack("Install the geolocator extension first: py -3.13 -m pip install flet-geolocator")
            return
        try:
            geo = ftg.Geolocator(
                configuration=ftg.GeolocatorConfiguration(
                    accuracy=ftg.GeolocatorPositionAccuracy.LOW
                ),
                on_error=lambda evt: None,
            )
            opened = await geo.open_location_settings()
            if opened:
                show_snack("Windows location settings opened.")
            else:
                show_snack("Could not open Windows location settings.")
        except Exception as ex:
            show_snack(f"Could not open location settings: {ex}")

    def open_location_prompt(e=None):
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Enable location tracking"),
            content=ft.Text("Allow FMS to use your device location for local weather and time?"),
            actions=[
                ft.TextButton("Not now", on_click=lambda evt: close_location_prompt(False)),
                ft.ElevatedButton("Allow", on_click=lambda evt: close_location_prompt(True), bgcolor=tokens["primary"], color=tokens["on_primary"]),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        show_alert(dialog)

    def close_location_prompt(enabled: bool):
        page.pop_dialog()
        state.location_permission_enabled = enabled
        if enabled and state.location_label == "Berlin":
            state.location_label = "Awaiting live device location"
        refresh_ui()

    airline_dd = ft.Dropdown(
        label="Pick an airline",
        value=state.airline or None,
        options=[ft.dropdown.Option(name) for name in AIRLINES],
        width=220,
    )
    theme_toggle = ft.Switch(label="Dark", value=True, visible=False)

    settings_daylight_switch = ft.Switch(label="Daytime display", value=(state.display_mode == "daylight"))
    settings_brightness_slider = ft.Slider(min=0.70, max=1.30, divisions=12, value=state.display_brightness, width=300)
    settings_contrast_slider = ft.Slider(min=0.70, max=1.35, divisions=13, value=state.display_contrast, width=300)
    settings_overlay_slider = ft.Slider(min=0.0, max=0.80, divisions=16, value=state.airline_overlay_opacity, width=300)
    settings_brightness_value_text = ft.Text("", size=12, color=tokens["muted"])
    settings_contrast_value_text = ft.Text("", size=12, color=tokens["muted"])
    settings_overlay_value_text = ft.Text("", size=12, color=tokens["muted"])
    settings_airline_status_text = ft.Text("Add a new airline to the app list.", size=12, color=tokens["muted"])
    settings_custom_airlines_text = ft.Text("Custom airlines: none", size=12, color=tokens["muted"])
    settings_remove_airline_dd = ft.Dropdown(
        label="Remove custom airline",
        value=None,
        options=[],
        width=260,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
        color=tokens["text"],
        border_color=tokens["card_border"],
        label_style=ft.TextStyle(color=tokens["muted"]),
    )
    settings_fuel_unit_dd = ft.Dropdown(
        label="Default fuel unit",
        value=state.default_fuel_unit,
        options=[ft.dropdown.Option("kg"), ft.dropdown.Option("lb")],
        width=180,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    settings_distance_unit_dd = ft.Dropdown(
        label="Default distance unit",
        value=state.default_distance_unit,
        options=[ft.dropdown.Option("NM"), ft.dropdown.Option("km")],
        width=180,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    settings_temperature_unit_dd = ft.Dropdown(
        label="Default temperature unit",
        value=state.default_temperature_unit,
        options=[ft.dropdown.Option("°C"), ft.dropdown.Option("°F")],
        width=180,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    settings_low_performance_switch = ft.Switch(label="Low performance mode", value=state.low_performance_mode)
    settings_volume_slider = ft.Slider(min=0.0, max=1.0, divisions=20, value=getattr(state, "app_volume", 0.85), width=300)
    settings_mute_switch = ft.Switch(label="Mute app sounds", value=bool(getattr(state, "app_muted", False)))
    settings_volume_value_text = ft.Text("Volume: 85%", size=12, color=tokens["muted"])
    settings_export_status_text = ft.Text(f"Exports will be saved inside {storage_dir / 'exports'}.", size=12, color=tokens["muted"])
    settings_calendar_import_status_text = ft.Text("Upload a calendar JSON export to replace the current calendar.", size=12, color=tokens["muted"])
    settings_background_status_text = ft.Text(f"Global background path: {app_background_instruction_path()} | Daytime path: {daylight_background_instruction_path()}", size=12, color=tokens["muted"])

    # Baggage controls rebuilt from the calculator workflow
    bag_mode_dd = ft.Dropdown(
        label="Calculation mode",
        value="Standard",
        options=[ft.dropdown.Option("Standard"), ft.dropdown.Option("Allowance")],
        width=220,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    bag_pax_tf = ft.TextField(
        label="Passenger count",
        value="0",
        width=330,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    bag_carry_on_tf = ft.TextField(
        label="Carry-on kg per passenger",
        value="0",
        width=330,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    bag_category_dd = ft.Dropdown(
        label="Flight category",
        value="Within the European region",
        options=[ft.dropdown.Option(k) for k in BAGGAGE_STANDARD_DEFAULTS.keys()],
        width=260,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    bag_checked_kg_per_pax_tf = ft.TextField(
        label="Checked baggage kg per passenger",
        value="0",
        width=330,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
        hint_text="Average checked baggage mass",
    )
    cargo_weight_tf = ft.TextField(
        label="Cargo weight (kg)",
        value="0",
        width=330,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
        color=tokens["text"],
    )

    bag_two_bag_percent_tf = ft.TextField(
        label="Passengers with 2 checked bags (%)",
        value="0",
        width=260,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
        hint_text="Used only in Allowance mode",
    )
    bag_per_bag_kg_tf = ft.TextField(
        label="Mass per checked bag (kg)",
        value="0",
        width=220,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )

    bag_standard_controls = ft.Column(spacing=12)
    bag_allowance_controls = ft.Column(spacing=12)
    bag_info_text = ft.Text(
        "Standard mode uses an average checked-baggage mass per passenger.",
        size=12,
        color=tokens["muted"],
    )
    bag_status_text = ft.Text("Enter values and click Calculate.", size=13, weight=ft.FontWeight.W_600)

    def set_baggage_status(message, *, error=False):
        bag_status_text.value = message
        bag_status_text.data = error
        bag_status_text.tooltip = message
        danger = "#FF8080" if page.theme_mode == ft.ThemeMode.DARK else "#B3261E"
        bag_status_text.color = danger if error else tokens["muted"]

    bag_total_weight_text = ft.Text("TOTAL baggage: —", size=20, weight=ft.FontWeight.W_800, color=tokens["accent"])
    bag_baggage_weight_summary_text = ft.Text("Baggage weight: —", size=15, weight=ft.FontWeight.W_700, color=tokens["text"])
    bag_cargo_weight_summary_text = ft.Text("Cargo weight: —", size=15, weight=ft.FontWeight.W_700, color=tokens["text"])
    bag_payload_weight_summary_text = ft.Text("Total payload: —", size=22, weight=ft.FontWeight.W_800, color=tokens["accent"])
    bag_mode_result_text = ft.Text("Mode: —", size=12, color=tokens["muted"])
    bag_passengers_result_text = ft.Text("Passengers: —", size=12, color=tokens["text"])
    bag_carry_on_result_text = ft.Text("Carry-on total: —", size=14, weight=ft.FontWeight.W_600, color=tokens["text"])
    bag_checked_result_text = ft.Text("Checked baggage total: —", size=14, weight=ft.FontWeight.W_600, color=tokens["text"])
    bag_checked_bags_result_text = ft.Text("Total checked bags: —", size=12, color=tokens["text"])
    bag_split_result_text = ft.Text("Bag split: —", size=12, color=tokens["text"])

    bag_assumption_1 = ft.Text("Waiting for input.", size=12, color=tokens["text"])
    bag_assumption_2 = ft.Text("", size=12, color=tokens["text"])
    bag_assumption_3 = ft.Text("", size=12, color=tokens["text"])
    bag_assumption_4 = ft.Text("", size=12, color=tokens["text"])

    bag_results_column = ft.Column(
        spacing=10,
        controls=[
            ft.Text("Visible Results", size=16, weight=ft.FontWeight.W_700, color=tokens["text"]),
            bag_total_weight_text,
            ft.Divider(height=8, opacity=0.15),
            bag_mode_result_text,
            bag_passengers_result_text,
            bag_carry_on_result_text,
            bag_checked_result_text,
            bag_checked_bags_result_text,
            bag_split_result_text,
        ],
    )
    bag_assumptions_column = ft.Column(
        spacing=8,
        controls=[
            ft.Text("Calculator Inputs Used", size=14, weight=ft.FontWeight.W_700, color=tokens["text"]),
            bag_assumption_1,
            bag_assumption_2,
            bag_assumption_3,
            bag_assumption_4,
        ],
    )

    # Calendar controls
    cal_date_tf = ft.TextField(label="Date", hint_text="YYYY-MM-DD", width=200, border_radius=16, filled=True)
    cal_time_tf = ft.TextField(label="Departure time", hint_text="HH:MM", width=200, border_radius=16, filled=True)
    cal_airline_dd = ft.TextField(value=state.airline or "")
    cal_aircraft_dd = ft.TextField()
    cal_origin_tf = ft.TextField(label="Departure", hint_text="e.g. EDDB", width=200, border_radius=16, filled=True)
    cal_destination_tf = ft.TextField(label="Arrival", hint_text="e.g. OMDB", width=200, border_radius=16, filled=True)
    cal_flight_time_tf = ft.TextField(label="Flight time", hint_text="e.g. 6h 20m", width=200, border_radius=16, filled=True)
    cal_notes_tf = ft.TextField(label="Notes", multiline=True, min_lines=3, max_lines=5, border_radius=16, filled=True, expand=True)
    cal_form_message = ft.Text("Add a planned flight or edit flight details.", size=12, color="#8B0000")
    cal_route_preview = ft.Text("Route: —", size=12)
    cal_sort_dd = ft.Dropdown(
        label="Sort saved flights",
        value="Most recent date",
        options=[
            ft.dropdown.Option("Most recent date"),
            ft.dropdown.Option("Oldest date"),
            ft.dropdown.Option("Longest flight time"),
            ft.dropdown.Option("Shortest flight time"),
        ],
        width=220,
        border_radius=16,
        filled=True,
    )
    cal_status_filter_dd = ft.Dropdown(
        label="Status filter",
        value="All",
        options=[
            ft.dropdown.Option("All"),
            ft.dropdown.Option("Completed only"),
            ft.dropdown.Option("Planned only"),
        ],
        width=190,
        border_radius=16,
        filled=True,
    )
    log_sort_dd = ft.Dropdown(
        label="Sort log",
        value="Most recent date",
        options=[
            ft.dropdown.Option("Most recent date"),
            ft.dropdown.Option("Oldest date"),
            ft.dropdown.Option("Highest landing G"),
            ft.dropdown.Option("Lowest landing G"),
        ],
        width=220,
        border_radius=16,
        filled=True,
    )

    # Takeoff controls
    takeoff_aircraft_dd = ft.Dropdown(
        label="Select an aircraft",
        width=260,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    takeoff_departure_icao_tf = ft.TextField(label="Departure ICAO", value=state.departure or "", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_gate_tf = ft.TextField(label="Departure gate", value=state.departure_gate or "", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_terminal_tf = ft.TextField(label="Departure terminal", value=state.departure_terminal or "", width=170, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_elevation_tf = ft.TextField(label="Elevation (ft)", value="", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_oat_tf = ft.TextField(label="OAT (°C)", value="15", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_qnh_tf = ft.TextField(label="QNH (hPa)", value="1013", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_wind_dir_tf = ft.TextField(label="Wind dir (deg)", value="0", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_wind_speed_tf = ft.TextField(label="Wind speed (kt)", value="0", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_wind_gust_tf = ft.TextField(label="Gust (kt)", value="0", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_metar_status_text = ft.Text("", size=12, color=tokens["muted"])
    takeoff_raw_metar_tf = ft.TextField(label="Raw METAR", value="", width=684, multiline=True, min_lines=2, max_lines=4, read_only=True, border_radius=16, filled=True, bgcolor=tokens["input_bg"])

    takeoff_runway_heading_tf = ft.TextField(label="Runway heading (deg)", value="0", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_slope_tf = ft.TextField(label="Runway slope (%)", value="0.0", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_surface_dd = ft.Dropdown(
        label="Surface",
        value="DRY",
        options=[ft.dropdown.Option(name) for name in TAKEOFF_SURFACE_FACTORS.keys()],
        width=200,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    takeoff_flap_dd = ft.Dropdown(label="Flap setting", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_tora_tf = ft.TextField(label="TORA (m)", value="", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_toda_tf = ft.TextField(label="TODA (m)", value="", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_asda_tf = ft.TextField(label="ASDA (m)", value="", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])

    takeoff_weight_tf = ft.TextField(label="Takeoff weight (kg)", value="", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_mtow_value_text = ft.Text("MTOW: —", size=13, weight=ft.FontWeight.W_700, color=tokens["text"])
    takeoff_mtow_display_tf = ft.Text("—", visible=False)
    takeoff_status_text = ft.Text("Select an aircraft to begin takeoff planning.", size=13, weight=ft.FontWeight.W_600, color=tokens["muted"])

    takeoff_isa_temp_text = ft.Text("ISA temp: —", size=12, color=tokens["text"])
    takeoff_pressure_alt_text = ft.Text("Pressure altitude: —", size=12, color=tokens["text"])
    takeoff_density_alt_text = ft.Text("Density altitude: —", size=12, color=tokens["text"])
    takeoff_isa_dev_text = ft.Text("ISA deviation: —", size=12, color=tokens["text"])
    takeoff_headwind_text = ft.Text("Headwind: —", size=12, color=tokens["text"])
    takeoff_crosswind_text = ft.Text("Crosswind: —", size=12, color=tokens["text"])

    takeoff_vs_text = ft.Text("Vs: —", size=28, weight=ft.FontWeight.W_900, color=tokens["accent"])
    takeoff_v1_text = ft.Text("V1: —", size=28, weight=ft.FontWeight.W_900, color=tokens["accent"])
    takeoff_vr_text = ft.Text("VR: —", size=28, weight=ft.FontWeight.W_900, color=tokens["accent"])
    takeoff_v2_text = ft.Text("V2: —", size=28, weight=ft.FontWeight.W_900, color=tokens["accent"])

    takeoff_asd_text = ft.Text("Accelerate-stop: —", size=12, color=tokens["text"])
    takeoff_agd_text = ft.Text("Accelerate-go: —", size=12, color=tokens["text"])
    takeoff_tod_text = ft.Text("Takeoff distance: —", size=12, color=tokens["text"])
    takeoff_margin_text = ft.Text("Runway margins: —", size=12, color=tokens["text"])
    takeoff_climb_initial_text = ft.Text("Initial: —", size=24, weight=ft.FontWeight.W_900, color=tokens["accent"])
    takeoff_climb_enroute_text = ft.Text("Enroute: —", size=24, weight=ft.FontWeight.W_900, color=tokens["accent"])
    takeoff_climb_high_text = ft.Text("High altitude: —", size=24, weight=ft.FontWeight.W_900, color=tokens["accent"])

    takeoff_route_distance_tf = ft.TextField(label="Route distance (NM)", value="", width=158, border_radius=16, filled=True, bgcolor=tokens["input_bg"], hint_text="Editable")
    takeoff_fuel_passengers_tf = ft.TextField(label="Passengers", value="", width=142, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_fuel_baggage_tf = ft.TextField(label="Baggage (kg)", value="", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_fuel_cargo_tf = ft.TextField(label="Cargo (kg)", value="", width=142, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_cruise_gs_tf = ft.TextField(label="Cruise GS (kt)", value="", width=170, border_radius=16, filled=True, bgcolor=tokens["input_bg"], visible=False)
    takeoff_fuel_units_dd = ft.Dropdown(label="Display units", value="kg", options=[ft.dropdown.Option("kg"), ft.dropdown.Option("lb")], width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"], visible=False)
    takeoff_taxi_fuel_tf = ft.TextField(label="Taxi fuel", value="", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"], visible=False)
    takeoff_contingency_tf = ft.TextField(label="Contingency (%)", value="5", width=170, border_radius=16, filled=True, bgcolor=tokens["input_bg"], visible=False)
    takeoff_alternate_fuel_tf = ft.TextField(label="Alternate fuel", value="", width=170, border_radius=16, filled=True, bgcolor=tokens["input_bg"], visible=False)
    takeoff_final_reserve_tf = ft.TextField(label="Final reserve (min)", value="", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"], visible=False)
    takeoff_extra_fuel_tf = ft.TextField(label="Extra fuel", value="0", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"], visible=False)
    takeoff_zfw_tf = ft.TextField(label="ZFW (kg)", value="", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"], visible=False)
    takeoff_fuel_aircraft_text = ft.Text("Selected aircraft: —", size=13, weight=ft.FontWeight.W_700, color=tokens["text"])
    takeoff_fuel_engine_text = ft.Text("Active route: —", size=12, color=tokens["text"])
    takeoff_fuel_assumptions_text = ft.Text("Model: route fuel from published range and fuel capacity • taxi 500 kg • passenger weight 84 kg • Jet fuel density 0.80 kg/L • safety margin 5%", size=12, color=tokens["muted"])
    takeoff_fuel_status_text = ft.Text("Set departure, arrival, aircraft, passengers, baggage, and cargo.", size=12, color=tokens["muted"])
    takeoff_trip_fuel_text = ft.Text("Base trip fuel: —", size=12, color=tokens["text"])
    takeoff_block_fuel_text = ft.Text("— L  /  — kg", size=28, weight=ft.FontWeight.W_900, color=tokens["accent"])
    takeoff_fuel_limits_text = ft.Text("", size=12, color=tokens["text"])
    takeoff_ete_text = ft.Text("Flight time: —", size=12, color=tokens["text"])
    takeoff_burn_rate_text = ft.Text("Actual payload: —", size=12, color=tokens["text"])
    takeoff_fuel_breakdown_text = ft.Text("Phase split: —", size=12, color=tokens["text"])
    takeoff_fuel_ete_text = takeoff_ete_text
    takeoff_fuel_burn_text = takeoff_burn_rate_text
    takeoff_recommended_tow_text = ft.Text("Estimated TOW: —", size=12, color=tokens["text"])
    takeoff_reserve_minutes_tf = takeoff_final_reserve_tf

    takeoff_warning_host = ft.Column(
        spacing=8,
        controls=[ft.Text("No active alerts.", size=12, color=tokens["muted"])],
    )


    landing_aircraft_dd = ft.Dropdown(label="Aircraft", value=state.aircraft or None, width=220, border_radius=16, filled=True, bgcolor=tokens["input_bg"], visible=False)
    landing_arrival_icao_tf = ft.TextField(label="Arrival ICAO", value=state.arrival or "", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_gate_tf = ft.TextField(label="Arrival gate", value=state.arrival_gate or "", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_terminal_tf = ft.TextField(label="Arrival terminal", value=state.arrival_terminal or "", width=170, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_elevation_tf = ft.TextField(label="Elevation (ft)", value="", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_oat_tf = ft.TextField(label="OAT (°C)", value="15", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_qnh_tf = ft.TextField(label="QNH (hPa)", value="1013", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_wind_dir_tf = ft.TextField(label="Wind dir (deg)", value="0", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_wind_speed_tf = ft.TextField(label="Wind speed (kt)", value="0", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_wind_gust_tf = ft.TextField(label="Gust (kt)", value="0", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_metar_status_text = ft.Text("", size=12, color=tokens["muted"])
    landing_raw_metar_tf = ft.TextField(label="Raw METAR", value="", width=684, multiline=True, min_lines=2, max_lines=4, read_only=True, border_radius=16, filled=True, bgcolor=tokens["input_bg"])

    landing_aircraft_display_text = ft.Text(current_aircraft_label(), color=tokens["text"], weight=ft.FontWeight.W_700)
    landing_weight_tf = ft.TextField(label="Landing weight (kg)", value="", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_mlw_value_text = ft.Text("MLW: —", size=13, weight=ft.FontWeight.W_700, color=tokens["text"])
    landing_flap_dd = ft.Dropdown(label="Landing config", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_autobrake_dd = ft.Dropdown(
        label="Autobrake",
        value="MED",
        options=[ft.dropdown.Option(name) for name in LANDING_AUTOBRAKE_FACTORS.keys()],
        width=180,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    landing_surface_dd = ft.Dropdown(
        label="Surface",
        value="DRY",
        options=[ft.dropdown.Option(name) for name in LANDING_SURFACE_FACTORS.keys()],
        width=200,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    landing_reverse_sw = ft.Switch(label="Reverse thrust", value=True)

    landing_runway_heading_tf = ft.TextField(label="Runway heading (deg)", value="0", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_lda_tf = ft.TextField(label="LDA (m)", value="", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_obstacle_tf = ft.TextField(label="Obstacle height (ft)", value="50", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_current_alt_tf = ft.TextField(label="Current altitude (ft)", value="", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_distance_to_go_tf = ft.TextField(label="Distance-to-go (NM)", value="", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_ground_speed_tf = ft.TextField(label="Planned ground speed (kt)", value="", width=210, border_radius=16, filled=True, bgcolor=tokens["input_bg"])

    landing_status_text = ft.Text("Select an aircraft in Takeoff to begin landing planning.", size=13, weight=ft.FontWeight.W_600, color=tokens["muted"])

    landing_pressure_alt_text = ft.Text("Pressure altitude: —", size=12, color=tokens["text"])
    landing_density_alt_text = ft.Text("Density altitude: —", size=12, color=tokens["text"])
    landing_headwind_text = ft.Text("Headwind: —", size=12, color=tokens["text"])
    landing_crosswind_text = ft.Text("Crosswind: —", size=12, color=tokens["text"])

    landing_vs_text = ft.Text("Vs landing: —", size=28, weight=ft.FontWeight.W_900, color=tokens["accent"])
    landing_vref_text = ft.Text("Vref: —", size=28, weight=ft.FontWeight.W_900, color=tokens["accent"])
    landing_vapp_text = ft.Text("Vapp: —", size=28, weight=ft.FontWeight.W_900, color=tokens["accent"])
    landing_additive_text = ft.Text(size=13, weight=ft.FontWeight.W_700, color=tokens["muted"], visible=False)
    landing_weight_ratio_text = ft.Text("Weight ratio: —", size=12, color=tokens["text"])

    landing_altitude_to_lose_text = ft.Text("Altitude to lose: —", size=12, color=tokens["text"])
    landing_tod_text = ft.Text("TOD distance: —", size=12, color=tokens["text"])
    landing_descent_rate_text = ft.Text("Suggested descent rate: —", size=12, color=tokens["text"])
    landing_descent_time_text = ft.Text("Estimated descent time: —", size=12, color=tokens["text"])
    landing_profile_text = ft.Text("Profile status: —", size=12, color=tokens["text"])
    landing_vs_calc_alt_tf = ft.TextField(label="ALT to lose (ft)", value="10000", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_vs_calc_ete_tf = ft.TextField(label="ETE (min)", value="10", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_vs_calc_result_text = ft.Text("Required V/S: —", size=28, weight=ft.FontWeight.W_900, color=tokens["accent"])

    landing_distance_text = ft.Text("Estimated landing distance: —", size=12, color=tokens["text"])
    landing_braking_text = ft.Text("Braking adjustments: —", size=12, color=tokens["text"])
    landing_margin_text = ft.Text("LDA margin: —", size=12, color=tokens["text"])

    landing_warning_host = ft.Column(
        spacing=8,
        controls=[ft.Text("No active alerts.", size=12, color=tokens["muted"])],
    )
    landing_vs_calc_altitude_tf = ft.TextField(label="Altitude to lose (ft)", value="", width=164, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_vs_calc_ete_tf = ft.TextField(label="ETE (min)", value="", width=148, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_vs_calc_result_text = ft.Text("Required V/S: —", size=28, weight=ft.FontWeight.W_900, color=tokens["accent"])
    landing_vs_calc_alt_tf = landing_vs_calc_altitude_tf


    # Seat map controls
    seat_airline_dd = ft.Dropdown(
        label="Airline",
        value=state.airline or None,
        options=[ft.dropdown.Option(name) for name in AIRLINES],
        width=220,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    seat_aircraft_dd = ft.Dropdown(
        label="Aircraft type",
        width=260,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
    )
    seat_first_tf = ft.TextField(label="First seats", value="0", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    seat_business_tf = ft.TextField(label="Business seats", value="0", width=170, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    seat_premium_tf = ft.TextField(label="Premium Economy seats", value="0", width=176, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    seat_economy_tf = ft.TextField(label="Economy seats", value="0", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"])

    seat_fill_first_tf = ft.TextField(label="Fill First", value="0", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    seat_fill_business_tf = ft.TextField(label="Fill Business", value="0", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    seat_fill_premium_tf = ft.TextField(label="Fill Premium", value="0", width=170, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    seat_fill_economy_tf = ft.TextField(label="Fill Economy", value="0", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"])

    seat_capacity_fields = (seat_first_tf, seat_business_tf, seat_premium_tf, seat_economy_tf)
    seat_fill_fields = dict(zip(CABIN_ORDER, (seat_fill_first_tf, seat_fill_business_tf, seat_fill_premium_tf, seat_fill_economy_tf)))
    seat_initial_message = "Select airline, aircraft, and seat counts. Then generate the map."
    seat_status_text = ft.Text(seat_initial_message, size=13, weight=ft.FontWeight.W_600)
    seat_summary_title = ft.Text("No seat map generated yet.", size=14, weight=ft.FontWeight.W_700, color=tokens["text"])
    seat_total_stat = ft.Text("Total seats: —", size=12, color=tokens["text"])
    seat_occupied_stat = ft.Text("Occupied seats: —", size=12, color=tokens["text"])
    seat_available_stat = ft.Text("Available seats: —", size=12, color=tokens["text"])
    seat_breakdown_stat = ft.Text("Breakdown: —", size=12, color=tokens["muted"])

    def empty_seat_map():
        return glass_card_with_background(
            "Seat Map",
            ft.Text("Generate a seat map to see the cabin overview here.", color=tokens["muted"]),
            bg_key="seat_map",
        )

    seat_map_host = ft.Container(padding=0, bgcolor=ft.Colors.TRANSPARENT, content=empty_seat_map())

    seat_map_scroll = ft.Column(
        [seat_map_host], scroll=ft.ScrollMode.AUTO, spacing=GAP,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    def set_seat_status(message, *, error=False):
        seat_status_text.value = message
        seat_status_text.tooltip = message
        seat_status_text.data = error
        seat_status_text.color = ("#A9291C" if use_daylight_cards() else "#FFB4A8") if error else tokens["muted"]

    seat_model = {
        "generated": False,
        "airline": state.airline,
        "aircraft": state.aircraft,
        "template": get_aircraft_seat_preset(state.aircraft),
        "seats": [],
        "seat_controls": {},
        "totals": {},
    }
    seat_passenger_load_host = ft.Container()
    highlighted_seat_ids = set()

    def sync_input_colors():
        for ctrl in [
            bag_mode_dd,
            bag_pax_tf,
            bag_carry_on_tf,
            bag_category_dd,
            bag_checked_kg_per_pax_tf,
            cargo_weight_tf,
            bag_two_bag_percent_tf,
            bag_per_bag_kg_tf,
            cal_date_tf,
            cal_time_tf,
            cal_airline_dd,
            cal_aircraft_dd,
            cal_origin_tf,
            cal_destination_tf,
            cal_flight_time_tf,
            cal_notes_tf,
            cal_sort_dd,
            cal_status_filter_dd,
            log_sort_dd,
            status_gate_tf,
            status_boarding_dd,
            status_cargo_dd,
            status_catering_dd,
            takeoff_aircraft_dd,
            takeoff_departure_icao_tf,
            takeoff_gate_tf,
            takeoff_terminal_tf,
            takeoff_elevation_tf,
            takeoff_oat_tf,
            takeoff_qnh_tf,
            takeoff_wind_dir_tf,
            takeoff_wind_speed_tf,
            takeoff_wind_gust_tf,
            takeoff_runway_heading_tf,
            takeoff_slope_tf,
            takeoff_surface_dd,
            takeoff_flap_dd,
            takeoff_tora_tf,
            takeoff_toda_tf,
            takeoff_asda_tf,
            takeoff_weight_tf,
            takeoff_route_distance_tf,
            takeoff_fuel_passengers_tf,
            takeoff_fuel_baggage_tf,
            takeoff_fuel_cargo_tf,
            takeoff_cruise_gs_tf,
            takeoff_fuel_units_dd,
            takeoff_taxi_fuel_tf,
            takeoff_contingency_tf,
            takeoff_alternate_fuel_tf,
            takeoff_final_reserve_tf,
            takeoff_extra_fuel_tf,
            takeoff_zfw_tf,
            takeoff_raw_metar_tf,
            landing_aircraft_dd,
            landing_arrival_icao_tf,
            landing_gate_tf,
            landing_terminal_tf,
            landing_elevation_tf,
            landing_oat_tf,
            landing_qnh_tf,
            landing_wind_dir_tf,
            landing_wind_speed_tf,
            landing_wind_gust_tf,
            landing_raw_metar_tf,
            landing_weight_tf,
            landing_flap_dd,
            landing_autobrake_dd,
            landing_surface_dd,
            landing_runway_heading_tf,
            landing_lda_tf,
            landing_obstacle_tf,
            landing_current_alt_tf,
            landing_distance_to_go_tf,
            landing_ground_speed_tf,
            landing_vs_calc_altitude_tf,
            landing_vs_calc_ete_tf,
            seat_airline_dd,
            seat_aircraft_dd,
            seat_first_tf,
            seat_business_tf,
            seat_premium_tf,
            seat_economy_tf,
            seat_fill_first_tf,
            seat_fill_business_tf,
            seat_fill_premium_tf,
            seat_fill_economy_tf,
        ]:
            ctrl.bgcolor = tokens["input_bg"]
            # Keep text readable on airline-colored dark backgrounds and in dark mode.
            try:
                ctrl.color = tokens["text"]
            except Exception:
                pass
            try:
                ctrl.label_style = ft.TextStyle(color=tokens["muted"])
            except Exception:
                pass
            try:
                ctrl.hint_style = ft.TextStyle(color=tokens["muted"])
            except Exception:
                pass
            try:
                ctrl.text_style = ft.TextStyle(color=tokens["text"])
            except Exception:
                pass
            try:
                ctrl.border_color = tokens["card_border"]
            except Exception:
                pass
            try:
                ctrl.focused_border_color = tokens["accent"]
            except Exception:
                pass
        bag_info_text.color = tokens["muted"]
        danger_color = "#FF8080" if (page.theme_mode == ft.ThemeMode.DARK or bool(state.airline)) else "#B3261E"
        bag_status_text.color = danger_color if bag_status_text.data else tokens["muted"]
        cal_form_message.color = danger_color
        cal_route_preview.color = tokens["muted"]
        takeoff_metar_status_text.color = tokens["muted"]
        takeoff_fuel_status_text.color = tokens["muted"]
        takeoff_status_text.color = danger_color
        landing_metar_status_text.color = tokens["muted"]
        landing_status_text.color = danger_color
        set_seat_status(seat_status_text.value, error=bool(seat_status_text.data))
        seat_summary_title.color = tokens["text"]
        seat_total_stat.color = tokens["text"]
        seat_occupied_stat.color = tokens["text"]
        seat_available_stat.color = tokens["text"]
        seat_breakdown_stat.color = tokens["muted"]
        status_center_modal.bgcolor = ft.Colors.with_opacity(0.36, ft.Colors.BLACK)
        if isinstance(status_center_modal.content, ft.Container):
            status_center_modal.content.bgcolor = tokens["panel"]
            status_center_modal.content.border = ft.border.all(1, tokens["card_border"])
        
        for ctrl in [
            bag_mode_result_text,
            bag_baggage_weight_summary_text,
            bag_cargo_weight_summary_text,
            bag_passengers_result_text,
            bag_carry_on_result_text,
            bag_checked_result_text,
            bag_checked_bags_result_text,
            bag_split_result_text,
            bag_assumption_1,
            bag_assumption_2,
            bag_assumption_3,
            bag_assumption_4,
        ]:
            ctrl.color = tokens["text"]
        for ctrl in [
            takeoff_mtow_value_text,
            takeoff_isa_temp_text,
            takeoff_pressure_alt_text,
            takeoff_density_alt_text,
            takeoff_isa_dev_text,
            takeoff_headwind_text,
            takeoff_crosswind_text,
            takeoff_trip_fuel_text,
            takeoff_fuel_limits_text,
            takeoff_fuel_ete_text,
            takeoff_fuel_burn_text,
            takeoff_fuel_breakdown_text,
            takeoff_recommended_tow_text,
            takeoff_asd_text,
            takeoff_agd_text,
            takeoff_tod_text,
            takeoff_margin_text,
            takeoff_fuel_aircraft_text,
            takeoff_fuel_engine_text,
            takeoff_fuel_assumptions_text,
            landing_mlw_value_text,
            landing_aircraft_display_text,
            landing_pressure_alt_text,
            landing_density_alt_text,
            landing_headwind_text,
            landing_crosswind_text,
            landing_weight_ratio_text,
            landing_altitude_to_lose_text,
            landing_tod_text,
            landing_descent_rate_text,
            landing_descent_time_text,
            landing_profile_text,
            landing_distance_text,
            landing_braking_text,
            landing_margin_text,
        ]:
            ctrl.color = tokens["text"]
        for ctrl in [
            takeoff_block_fuel_text,
            takeoff_vs_text,
            takeoff_v1_text,
            takeoff_vr_text,
            takeoff_v2_text,
            takeoff_climb_initial_text,
            takeoff_climb_enroute_text,
            takeoff_climb_high_text,
            landing_vs_text,
            landing_vref_text,
            landing_vapp_text,
            landing_vs_calc_result_text,
        ]:
            ctrl.color = tokens["accent"]
        bag_total_weight_text.color = tokens["accent"]
        bag_payload_weight_summary_text.color = tokens["accent"]
        refresh_seat_widget_styles(update_page=False)

    def default_checked_baggage_for_category(category: Optional[str]) -> float:
        return BAGGAGE_STANDARD_DEFAULTS.get(category or "", BAGGAGE_STANDARD_DEFAULTS["Within the European region"])

    def apply_baggage_category_default():
        bag_checked_kg_per_pax_tf.value = "0"

    def reset_baggage_result_display():
        bag_total_weight_text.value = "TOTAL baggage: —"
        bag_baggage_weight_summary_text.value = "Baggage weight: —"
        bag_cargo_weight_summary_text.value = "Cargo weight: —"
        bag_payload_weight_summary_text.value = "Total payload: —"
        bag_mode_result_text.value = "Mode: —"
        bag_passengers_result_text.value = "Passengers: —"
        bag_carry_on_result_text.value = "Carry-on total: —"
        bag_checked_result_text.value = "Checked baggage total: —"
        bag_checked_bags_result_text.value = "Total checked bags: —"
        bag_split_result_text.value = "Bag split: —"
        bag_assumption_1.value = "Waiting for input."
        bag_assumption_2.value = ""
        bag_assumption_3.value = ""
        bag_assumption_4.value = ""

    def refresh_baggage_mode_ui(update_page: bool = True):
        mode = bag_mode_dd.value or "Standard"
        is_standard = mode == "Standard"
        bag_standard_controls.visible = is_standard
        bag_allowance_controls.visible = not is_standard
        if is_standard:
            bag_info_text.value = "Standard mode uses an average checked-baggage mass per passenger by flight category."
        else:
            bag_info_text.value = "Allowance mode uses bag count × per-bag mass and a share of passengers with two checked bags."
        if update_page:
            page.update()

    def populate_calendar_aircraft_dropdown(airline_name: Optional[str] = None, preferred: Optional[str] = None):
        airline_name = airline_name or cal_airline_dd.value or state.airline
        preferred = canonical_aircraft_name(preferred) or canonical_aircraft_name(state.aircraft) or preferred or state.aircraft
        cal_aircraft_dd.value = preferred or None

    def refresh_calendar_route_preview():
        origin = (cal_origin_tf.value or "").strip().upper()
        destination = (cal_destination_tf.value or "").strip().upper()
        if origin or destination:
            cal_route_preview.value = f"Route: {origin or '—'} → {destination or '—'}"
        else:
            cal_route_preview.value = "Route: —"
        page.update()


    def lookup_airport_elevation_ft(icao: str) -> Optional[int]:
        record = lookup_airport_record(icao)
        return int(record["elevation_ft"]) if record and record.get("elevation_ft") is not None else None

    def populate_takeoff_aircraft_dropdown(airline_name: Optional[str] = None, preferred: Optional[str] = None):
        airline_name = airline_name or state.airline
        options = all_library_aircraft_names()
        preferred = canonical_aircraft_name(preferred) or canonical_aircraft_name(state.aircraft) or preferred
        takeoff_aircraft_dd.options = [ft.dropdown.Option(a) for a in options]
        takeoff_aircraft_dd.value = preferred if preferred in options else None
        update_takeoff_aircraft_details(update_page=False)

    def update_takeoff_aircraft_details(update_page: bool = True, reset_weight: bool = False):
        aircraft_name = canonical_aircraft_name(takeoff_aircraft_dd.value or state.aircraft)
        if not aircraft_name:
            takeoff_aircraft_dd.value = None
            takeoff_flap_dd.options = []
            takeoff_flap_dd.value = None
            takeoff_mtow_value_text.value = "MTOW: —"
            takeoff_mtow_display_tf.value = "—"
            takeoff_status_text.value = "Select an aircraft to begin takeoff planning."
            if reset_weight or not (takeoff_weight_tf.value or "").strip():
                takeoff_weight_tf.value = ""
            refresh_takeoff_fuel_info(update_page=False)
            if update_page:
                page.update()
            return

        ac = resolve_takeoff_aircraft_config(aircraft_name)
        takeoff_aircraft_dd.value = aircraft_name
        state.aircraft = aircraft_name
        flap_options = list(ac.flap_options or [])
        takeoff_flap_dd.options = [ft.dropdown.Option(key=flap, text=flap) for flap in flap_options]
        if flap_options and takeoff_flap_dd.value not in flap_options:
            takeoff_flap_dd.value = flap_options[0]
        elif not flap_options:
            takeoff_flap_dd.value = None
        takeoff_mtow_value_text.value = f"MTOW: {ac.mtow_kg:,.0f} kg"
        takeoff_mtow_display_tf.value = f"{ac.mtow_kg:,.0f}"
        takeoff_status_text.value = f"Selected {aircraft_name} • MTOW {ac.mtow_kg:,.0f} kg"
        if reset_weight or not (takeoff_weight_tf.value or "").strip():
            takeoff_weight_tf.value = ""
        refresh_takeoff_fuel_info(update_page=False)
        safe_update_control(takeoff_aircraft_dd)
        safe_update_control(takeoff_flap_dd)
        safe_update_control(takeoff_mtow_value_text)
        safe_update_control(takeoff_mtow_display_tf)
        safe_update_control(takeoff_status_text)
        safe_update_control(takeoff_fuel_aircraft_text)
        if update_page:
            page.update()
    def apply_takeoff_departure_state(update_page: bool = True, fill_elevation: bool = False):
        departure = (takeoff_departure_icao_tf.value or "").strip().upper()
        takeoff_departure_icao_tf.value = departure
        state.departure = normalize_airport_code(departure) or ""
        if fill_elevation:
            elev = lookup_airport_elevation_ft(departure)
            takeoff_elevation_tf.value = str(elev) if elev is not None else ""
        if update_page:
            page.update()

    def reset_takeoff_result_display():
        state.takeoff_last_result = {}
        takeoff_isa_temp_text.value = "ISA temp: —"
        takeoff_pressure_alt_text.value = "Pressure altitude: —"
        takeoff_density_alt_text.value = "Density altitude: —"
        takeoff_isa_dev_text.value = "ISA deviation: —"
        takeoff_headwind_text.value = "Headwind: —"
        takeoff_crosswind_text.value = "Crosswind: —"
        takeoff_vs_text.value = "Vs: —"
        takeoff_v1_text.value = "V1: —"
        takeoff_vr_text.value = "VR: —"
        takeoff_v2_text.value = "V2: —"
        takeoff_asd_text.value = "Accelerate-stop: —"
        takeoff_agd_text.value = "Accelerate-go: —"
        takeoff_tod_text.value = "Takeoff distance: —"
        takeoff_margin_text.value = "Runway margins: —"
        takeoff_climb_initial_text.value = "Initial: —"
        takeoff_climb_enroute_text.value = "Enroute: —"
        takeoff_climb_high_text.value = "High altitude: —"
        takeoff_warning_host.controls = [ft.Text("No active alerts.", size=12, color=tokens["muted"])]

    def reset_takeoff_form(update_page: bool = True):
        populate_takeoff_aircraft_dropdown(state.airline, state.aircraft)
        takeoff_departure_icao_tf.value = state.departure or ""
        takeoff_gate_tf.value = state.departure_gate or ""
        elev = lookup_airport_elevation_ft(takeoff_departure_icao_tf.value)
        takeoff_elevation_tf.value = str(elev) if elev is not None else ""
        takeoff_oat_tf.value = "15"
        takeoff_qnh_tf.value = "1013"
        takeoff_wind_dir_tf.value = "0"
        takeoff_wind_speed_tf.value = "0"
        takeoff_wind_gust_tf.value = "0"
        takeoff_runway_heading_tf.value = "0"
        takeoff_slope_tf.value = "0.0"
        takeoff_surface_dd.value = "DRY"
        update_takeoff_aircraft_details(update_page=False, reset_weight=True)
        takeoff_tora_tf.value = ""
        takeoff_toda_tf.value = ""
        takeoff_asda_tf.value = ""
        performance_metar_requests.pop("departure", None)
        takeoff_raw_metar_tf.value = ""
        takeoff_metar_status_text.value = ""
        state.route_distance_override_nm = None
        state.route_distance_override_key = ""
        takeoff_route_distance_tf.value = ""
        takeoff_fuel_passengers_tf.value = (
            str(sum(seat["occupied"] for seat in seat_model["seats"])) if seat_model.get("generated") else ""
        )
        takeoff_fuel_baggage_tf.value = ""
        takeoff_fuel_cargo_tf.value = ""
        takeoff_cruise_gs_tf.value = ""
        takeoff_fuel_units_dd.value = "kg"
        takeoff_taxi_fuel_tf.value = ""
        takeoff_contingency_tf.value = "5"
        takeoff_alternate_fuel_tf.value = ""
        takeoff_reserve_minutes_tf.value = ""
        takeoff_extra_fuel_tf.value = "0"
        takeoff_zfw_tf.value = ""
        takeoff_trip_fuel_text.value = "Base trip fuel: —"
        takeoff_block_fuel_text.value = "— L  /  — kg"
        takeoff_fuel_limits_text.value = ""
        takeoff_ete_text.value = "Flight time: —"
        takeoff_burn_rate_text.value = "Actual payload: —"
        takeoff_fuel_breakdown_text.value = "Phase split: —"
        takeoff_recommended_tow_text.value = "Estimated TOW: —"
        takeoff_fuel_status_text.value = "Set departure, arrival, aircraft, passengers, baggage, and cargo."
        set_takeoff_fuel_defaults(update_page=False)
        if state.aircraft:
            update_takeoff_aircraft_details(update_page=False)
            update_landing_aircraft_details(update_page=False)
        else:
            takeoff_status_text.value = "Select an aircraft to begin takeoff planning."
        state.flight_status = derive_idle_status()
        reset_takeoff_result_display()
        if update_page:
            page.update()

    def performance_warning_ink(severity):
        if page.theme_mode == ft.ThemeMode.DARK:
            return "#FFB7B3" if severity == "warning" else "#FFD782"
        return "#8B1F20" if severity == "warning" else "#714500"

    def render_takeoff_warnings(result: TakeoffResultData):
        controls = []
        for message in result.warnings:
            controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=999,
                    bgcolor=ft.Colors.with_opacity(0.16, ft.Colors.RED),
                    content=ft.Text(message, size=12, weight=ft.FontWeight.W_700, color=performance_warning_ink("warning"), data="warning"),
                )
            )
        for message in result.cautions:
            controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=999,
                    bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.AMBER),
                    content=ft.Text(message, size=12, weight=ft.FontWeight.W_700, color=performance_warning_ink("caution"), data="caution"),
                )
            )
        if not controls:
            controls = [ft.Text("No warnings or cautions.", size=12, color=tokens["muted"])]
        takeoff_warning_host.controls = controls


    def populate_landing_aircraft_dropdown(airline_name: Optional[str] = None, preferred: Optional[str] = None):
        airline_name = airline_name or state.airline
        options = all_library_aircraft_names()
        preferred = canonical_aircraft_name(preferred) or canonical_aircraft_name(state.aircraft) or preferred
        landing_aircraft_dd.options = [ft.dropdown.Option(a) for a in options]
        landing_aircraft_dd.value = preferred if preferred in options else None
        update_landing_aircraft_details(update_page=False)

    def update_landing_aircraft_details(update_page: bool = True, reset_weight: bool = False):
        aircraft_name = canonical_aircraft_name(state.aircraft or landing_aircraft_dd.value)
        if not aircraft_name:
            landing_aircraft_dd.value = None
            landing_flap_dd.options = []
            landing_flap_dd.value = None
            landing_aircraft_display_text.value = "No aircraft selected"
            landing_mlw_value_text.value = "MLW: —"
            landing_status_text.value = "Select an aircraft in Takeoff to begin landing planning."
            if reset_weight or not (landing_weight_tf.value or "").strip():
                landing_weight_tf.value = ""
            if update_page:
                page.update()
            return

        ac = resolve_landing_aircraft_config(aircraft_name)
        landing_aircraft_dd.value = aircraft_name
        state.aircraft = aircraft_name
        flap_options = list(ac.flap_options or [])
        landing_flap_dd.options = [ft.dropdown.Option(key=flap, text=flap) for flap in flap_options]
        if flap_options and landing_flap_dd.value not in flap_options:
            landing_flap_dd.value = flap_options[0]
        elif not flap_options:
            landing_flap_dd.value = None
        landing_aircraft_display_text.value = ac.name
        landing_mlw_value_text.value = f"MLW: {ac.mlw_kg:,.0f} kg"
        landing_status_text.value = f"Aircraft synced from Takeoff: {ac.name} • MLW {ac.mlw_kg:,.0f} kg"
        if reset_weight or not (landing_weight_tf.value or "").strip():
            landing_weight_tf.value = ""
        safe_update_control(landing_aircraft_dd)
        safe_update_control(landing_flap_dd)
        safe_update_control(landing_aircraft_display_text)
        safe_update_control(landing_mlw_value_text)
        safe_update_control(landing_status_text)
        if update_page:
            page.update()
    def apply_landing_arrival_state(update_page: bool = True, fill_elevation: bool = False):
        arrival = (landing_arrival_icao_tf.value or "").strip().upper()
        landing_arrival_icao_tf.value = arrival
        state.arrival = normalize_airport_code(arrival) or ""
        landing_arrival_icao_tf.value = state.arrival
        if fill_elevation:
            elev = lookup_airport_elevation_ft(arrival)
            landing_elevation_tf.value = str(elev) if elev is not None else ""
        sync_route_distance_from_state(update_page=False)
        refresh_takeoff_fuel_info(update_page=False)
        if update_page:
            page.update()

    def reset_landing_result_display():
        state.landing_last_result = {}
        landing_pressure_alt_text.value = "Pressure altitude: —"
        landing_density_alt_text.value = "Density altitude: —"
        landing_headwind_text.value = "Headwind: —"
        landing_crosswind_text.value = "Crosswind: —"
        landing_vs_text.value = "Vs landing: —"
        landing_vref_text.value = "Vref: —"
        landing_vapp_text.value = "Vapp: —"
        landing_additive_text.value = ""
        landing_additive_text.visible = False
        landing_weight_ratio_text.value = "Weight ratio: —"
        landing_altitude_to_lose_text.value = "Altitude to lose: —"
        landing_tod_text.value = "TOD distance: —"
        landing_descent_rate_text.value = "Suggested descent rate: —"
        landing_descent_time_text.value = "Estimated descent time: —"
        landing_profile_text.value = "Profile status: —"
        landing_distance_text.value = "Estimated landing distance: —"
        landing_braking_text.value = "Braking adjustments: —"
        landing_margin_text.value = "LDA margin: —"
        landing_warning_host.controls = [ft.Text("No active alerts.", size=12, color=tokens["muted"])]

    def reset_landing_form(update_page: bool = True):
        populate_landing_aircraft_dropdown(state.airline, state.aircraft)
        landing_arrival_icao_tf.value = state.arrival or ""
        landing_gate_tf.value = state.arrival_gate or ""
        landing_aircraft_display_text.value = current_aircraft_label()
        elev = lookup_airport_elevation_ft(landing_arrival_icao_tf.value)
        landing_elevation_tf.value = str(elev) if elev is not None else ""
        landing_oat_tf.value = "15"
        landing_qnh_tf.value = "1013"
        landing_wind_dir_tf.value = "0"
        landing_wind_speed_tf.value = "0"
        landing_wind_gust_tf.value = "0"
        landing_runway_heading_tf.value = "0"
        landing_lda_tf.value = ""
        landing_obstacle_tf.value = "50"
        landing_current_alt_tf.value = ""
        landing_distance_to_go_tf.value = ""
        landing_ground_speed_tf.value = ""
        landing_surface_dd.value = "DRY"
        landing_autobrake_dd.value = "MED"
        landing_reverse_sw.value = True
        update_landing_aircraft_details(update_page=False, reset_weight=True)
        performance_metar_requests.pop("arrival", None)
        landing_raw_metar_tf.value = ""
        landing_metar_status_text.value = ""
        if not state.aircraft:
            landing_status_text.value = "Select an aircraft in Takeoff to begin landing planning."
        reset_landing_result_display()
        if update_page:
            page.update()

    def sync_aircraft_across_pages(aircraft_name: Optional[str], update_page: bool = True):
        canonical = canonical_aircraft_name(aircraft_name)
        if not canonical:
            state.aircraft = str(aircraft_name or "").strip()
            takeoff_aircraft_dd.value = None
            landing_aircraft_dd.value = None
            update_takeoff_aircraft_details(update_page=False)
            update_landing_aircraft_details(update_page=False)
            refresh_takeoff_fuel_info(update_page=False)
            if update_page:
                page.update()
            return

        state.aircraft = canonical
        if state.aircraft_record and aircraft_value(state.aircraft_record) != canonical:
            state.aircraft_record = {}
        takeoff_aircraft_dd.value = canonical
        landing_aircraft_dd.value = canonical
        update_takeoff_aircraft_details(update_page=False)
        update_landing_aircraft_details(update_page=False)
        refresh_takeoff_fuel_info(update_page=False)
        if update_page:
            page.update()

    def render_landing_warnings(result: LandingResultData):
        controls = []
        for message in result.warnings:
            controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=999,
                    bgcolor=ft.Colors.with_opacity(0.16, ft.Colors.RED),
                    content=ft.Text(message, size=12, weight=ft.FontWeight.W_700, color=performance_warning_ink("warning"), data="warning"),
                )
            )
        for message in result.cautions:
            controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=999,
                    bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.AMBER),
                    content=ft.Text(message, size=12, weight=ft.FontWeight.W_700, color=performance_warning_ink("caution"), data="caution"),
                )
            )
        if not controls:
            controls = [ft.Text("No warnings or cautions.", size=12, color=tokens["muted"])]
        landing_warning_host.controls = controls


    def populate_seat_aircraft_dropdown(airline_name: Optional[str] = None, preferred: Optional[str] = None):
        airline_name = airline_name or seat_airline_dd.value or state.airline
        options = all_library_aircraft_names()
        preferred = canonical_aircraft_name(preferred) or canonical_aircraft_name(state.aircraft) or preferred
        seat_aircraft_dd.options = [ft.dropdown.Option(a) for a in options]
        if preferred in options:
            seat_aircraft_dd.value = preferred
        elif options:
            seat_aircraft_dd.value = options[0]
        else:
            seat_aircraft_dd.value = None

    def seats_by_cabin():
        cabins = {cabin: [] for cabin in CABIN_ORDER}
        for seat in seat_model.get("seats", []):
            cabins[seat["cabin"]].append(seat)
        return cabins

    def set_cabin_occupancy(seats, count):
        occupied = [seat for seat in seats if seat["occupied"]]
        for seat in occupied[count:]:
            seat["occupied"] = False
        if len(occupied) < count:
            available = [seat for seat in seats if not seat["occupied"]]
            for seat in available[:count - len(occupied)]:
                seat["occupied"] = True

    def sync_fill_target(cabin, old_count, new_count):
        field = seat_fill_fields[cabin]
        if (field.value or "").strip() == str(old_count):
            field.value = str(new_count)

    def seat_available_color(occupied: bool, seat_id: str) -> str:
        if occupied:
            return SEAT_RED
        return SEAT_YELLOW if seat_id in highlighted_seat_ids else SEAT_BLUE

    def seat_text_color(occupied: bool, seat_id: str) -> str:
        return "#222019" if not occupied and seat_id in highlighted_seat_ids else "#FFFFFF"

    def update_seat_artwork(seat):
        refs = seat_model.get("seat_controls", {}).get(seat["id"])
        if refs:
            back, label = refs
            back.bgcolor = seat_available_color(seat["occupied"], seat["id"])
            label.color = seat_text_color(seat["occupied"], seat["id"])

    def refresh_seat_widget_styles(update_page: bool = True):
        for seat in seat_model.get("seats", []):
            update_seat_artwork(seat)
        if seat_model.get("generated") and update_page:
            page.update()

    def update_seat_summary(update_page: bool = True):
        total = len(seat_model.get("seats", []))
        occupied = sum(1 for seat in seat_model.get("seats", []) if seat.get("occupied"))
        available = total - occupied
        breakdown_parts = []
        for cabin in CABIN_ORDER:
            cabin_total = sum(1 for seat in seat_model.get("seats", []) if seat.get("cabin") == cabin)
            if cabin_total == 0:
                continue
            cabin_occ = sum(1 for seat in seat_model.get("seats", []) if seat.get("cabin") == cabin and seat.get("occupied"))
            breakdown_parts.append(f"{cabin}: {cabin_occ}/{cabin_total}")
        seat_total_stat.value = f"Total seats: {total}"
        seat_occupied_stat.value = f"Occupied seats: {occupied}"
        seat_available_stat.value = f"Available seats: {available}"
        seat_breakdown_stat.value = "Breakdown: " + (", ".join(breakdown_parts) if breakdown_parts else "—")

        if seat_model.get("generated"):
            bag_pax_tf.value = str(occupied)
            takeoff_fuel_passengers_tf.value = str(occupied)
            seat_passenger_load_host.content = build_passenger_load_panel()
            if update_page:
                safe_update_control(seat_passenger_load_host)

        if update_page:
            page.update()

    def toggle_seat_occupancy(seat_id: str):
        for seat in seat_model.get("seats", []):
            if seat["id"] == seat_id:
                cabin = seat["cabin"]
                old_count = sum(s["occupied"] for s in seats_by_cabin()[cabin])
                seat["occupied"] = not seat["occupied"]
                sync_fill_target(cabin, old_count, old_count + (1 if seat["occupied"] else -1))
                update_seat_artwork(seat)
                set_seat_status(f"Toggled seat {seat_id}.")
                update_seat_summary(update_page=False)
                page.update()
                return

    def seat_groups_from_layout(layout: List[int]) -> List[List[str]]:
        if not layout:
            return []
        if layout == [3, 4, 3]:
            return [["A", "B", "C"], ["D", "E", "F", "G"], ["H", "J", "K"]]
        if layout == [3, 3, 3]:
            return [["A", "B", "C"], ["D", "E", "F"], ["G", "H", "J"]]
        if layout == [2, 4, 2]:
            return [["A", "C"], ["D", "E", "F", "G"], ["H", "K"]]
        if layout == [2, 3, 2]:
            return [["A", "C"], ["D", "E", "F"], ["H", "K"]]
        if layout == [1, 2, 1]:
            return [["A"], ["D", "G"], ["K"]]
        if layout == [2, 2]:
            return [["A", "C"], ["D", "F"]]
        if layout == [3, 3]:
            return [["A", "B", "C"], ["D", "E", "F"]]
        if layout == [2, 3]:
            return [["A", "C"], ["D", "E", "F"]]
        letters = seat_letters_for_row(sum(layout))
        groups = []
        cursor = 0
        for group_size in layout:
            groups.append(letters[cursor:cursor + group_size])
            cursor += group_size
        return groups

    def flatten_seat_groups(groups: List[List[str]]) -> List[str]:
        return [seat for group in groups for seat in group]

    def build_digital_seat_rows(counts: Dict[str, int], preset: Dict, start_row: int = 0, deck_prefix: str = "", deck_label: str = "", *, single_aisle=False) -> List[Dict]:
        rows = []
        row_number = start_row
        for cabin in CABIN_ORDER:
            count = max(0, int(counts.get(cabin, 0)))
            layout = preset.get("layouts", {}).get(cabin)
            if cabin == "First" and count > 0 and not layout:
                layout = [1, 1] if single_aisle else [1, 2, 1]
            if count <= 0 or not layout:
                continue
            groups = seat_groups_from_layout(layout)
            seat_order = flatten_seat_groups(groups)
            seats_per_row = max(1, len(seat_order))
            full_rows, remainder = divmod(count, seats_per_row)
            for _ in range(full_rows):
                row_number = next_seat_row_number(row_number)
                rows.append({"row": row_number, "cabin": cabin, "groups": groups, "existing_seats": seat_order[:], "deck": deck_label, "deck_prefix": deck_prefix})
            if remainder > 0:
                row_number = next_seat_row_number(row_number)
                rows.append({"row": row_number, "cabin": cabin, "groups": groups, "existing_seats": seat_order[:remainder], "deck": deck_label, "deck_prefix": deck_prefix})
        return rows

    def build_seat_diagram(rows, *, single_aisle):
        def make_seat(row, letter, width, height, highlighted):
            row_number = row["row"]
            deck = row.get("deck_prefix", "")
            label = f"{row_number}{letter}"
            seat_id = f"{deck}{row_number:02d}{letter}" if deck else label
            seat = {
                "id": seat_id, "row": row_number, "label": letter, "cabin": row["cabin"],
                "occupied": False, "deck": row.get("deck", ""),
            }
            if highlighted:
                highlighted_seat_ids.add(seat_id)
            seat_model["seats"].append(seat)
            async def toggle(e):
                toggle_seat_occupancy(seat_id)

            seat_view, back, text = seat_artwork(
                label, seat["cabin"], width, height,
                seat_available_color(seat["occupied"], seat_id),
                seat_text_color(seat["occupied"], seat_id),
                f"{seat_id} · {seat['cabin']}",
                toggle,
            )
            seat_model["seat_controls"][seat_id] = (back, text)
            return seat_view

        return cabin_diagram(rows, make_seat, single_aisle=single_aisle)

    def build_cabin_legend():
        return ft.Row(
            wrap=True, spacing=12, run_spacing=5, alignment=ft.MainAxisAlignment.CENTER,
            controls=[
                ft.Row(
                    tight=True, spacing=5,
                    controls=[
                        ft.Container(width=12, height=12, border_radius=3, bgcolor=color),
                        ft.Text(label, size=11, color=tokens["muted"]),
                    ],
                )
                for label, color in (
                    ("Available", SEAT_BLUE),
                    ("Bulkhead or exit row", SEAT_YELLOW),
                    ("Occupied", SEAT_RED),
                )
            ],
        )

    def build_passenger_load_panel() -> ft.Control:
        cabins = seats_by_cabin()
        capacity = {cabin: len(seats) for cabin, seats in cabins.items()}
        occupied = {cabin: sum(seat["occupied"] for seat in seats) for cabin, seats in cabins.items()}
        total_capacity = sum(capacity.values())
        total_occupied = sum(occupied.values())
        payload_kg = total_occupied * STANDARD_PASSENGER_WEIGHT_KG
        load_factor = 0 if total_capacity == 0 else total_occupied / total_capacity * 100
        cabin_totals = []
        for cabin, label in zip(CABIN_ORDER, ("First", "Business", "Premium", "Economy")):
            total = f"{occupied[cabin]}/{capacity[cabin]}"
            cabin_totals.append(ft.Container(
                expand=True, tooltip=f"{cabin}: {total} seats",
                content=ft.Column(
                    spacing=1,
                    controls=[
                        ft.Text(label, size=12, color=tokens["muted"], no_wrap=True),
                        ft.Text(total, size=13, weight=ft.FontWeight.W_700, color=tokens["text"],
                                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            ))
        card = glass_card(
            "Passenger Load",
            ft.Column(
                spacing=4,
                controls=[
                    ft.Row(cabin_totals, spacing=4),
                    ft.Divider(height=3, opacity=0.15),
                    ft.Row(
                        [
                            ft.Text(f"{total_occupied} / {total_capacity} passengers", size=13, weight=ft.FontWeight.W_700,
                                    color=tokens["text"], expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(f"{payload_kg:,.0f} kg", size=13, color=tokens["text"], no_wrap=True,
                                    tooltip="Passenger payload"),
                        ],
                        spacing=4,
                    ),
                ],
            ),
        )
        card.content.controls[0] = ft.Row(
            [
                card.content.controls[0],
                ft.Text(f"{load_factor:.1f}%", size=14, weight=ft.FontWeight.W_800, color=tokens["accent"],
                        tooltip="Load factor"),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        card.padding = 8
        card.content.spacing = 4
        return card

    def build_cabin_distribution_panel() -> ft.Control:
        capacity = {cabin: sum(1 for seat in seat_model.get("seats", []) if seat.get("cabin") == cabin) for cabin in CABIN_ORDER}
        occupied = {cabin: sum(1 for seat in seat_model.get("seats", []) if seat.get("cabin") == cabin and seat.get("occupied")) for cabin in CABIN_ORDER}
        total_capacity = max(1, sum(capacity.values()))
        bar_segments = []
        for cabin in CABIN_ORDER:
            if capacity[cabin] <= 0:
                continue
            bar_segments.append(ft.Container(expand=max(1, capacity[cabin]), height=18, bgcolor=CABIN_COLORS[cabin]))
        stat_controls = []
        for cabin in CABIN_ORDER:
            if capacity[cabin] <= 0:
                continue
            stat_controls.append(
                ft.Container(
                    width=150,
                    content=ft.Column(spacing=4, controls=[
                        ft.Text(cabin, size=10, color=tokens["muted"]),
                        ft.Text(f"{occupied[cabin]} / {capacity[cabin]}", size=16, color=tokens["text"], weight=ft.FontWeight.W_800),
                    ]),
                )
            )
        return ft.Container(
            padding=18,
            border_radius=22,
            bgcolor=surface_fill(tokens["subpanel"]),
            border=ft.border.all(1, tokens["card_border"]),
            content=ft.Column(spacing=14, controls=[
                ft.Text("Cabin Distribution", size=16, weight=ft.FontWeight.W_800, color=tokens["text"]),
                ft.Row(spacing=0, controls=bar_segments or [ft.Container(height=18, expand=1, bgcolor=tokens["card_border"])]),
                ft.Row(wrap=True, spacing=18, run_spacing=10, controls=stat_controls),
            ]),
        )

    def build_digital_seat_map(aircraft_name: str, counts: Dict[str, int], preset: Dict, *, restoring=False) -> ft.Control:
        previous_cabins = seats_by_cabin()
        seat_model["seats"] = []
        seat_model["seat_controls"] = {}
        highlighted_seat_ids.clear()

        layouts = [layout for layout in preset.get("layouts", {}).values() if layout]
        single_aisle = bool(layouts) and all(len(layout) <= 2 for layout in layouts)
        if canonical_aircraft_name(aircraft_name) == "A380-800":
            upper_counts = {cabin: count for cabin, count in counts.items() if cabin != "Economy"}
            lower_counts = {"Economy": counts.get("Economy", 0)}
            upper_rows = build_digital_seat_rows(upper_counts, preset, start_row=0, deck_prefix="U", deck_label="Upper Deck")
            lower_rows = build_digital_seat_rows(lower_counts, preset, start_row=49, deck_prefix="L", deck_label="Lower Deck")
            deck_rows = {"Upper deck": upper_rows, "Lower deck": lower_rows}
        else:
            deck_rows = {"Cabin diagram": build_digital_seat_rows(counts, preset, single_aisle=single_aisle)}
        panels = {
            label: ft.Column(
                spacing=GAP, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[build_cabin_legend(), build_seat_diagram(rows, single_aisle=single_aisle)],
            )
            for label, rows in deck_rows.items()
        }

        for cabin, seats in seats_by_cabin().items():
            previous = previous_cabins[cabin]
            old_count = sum(seat["occupied"] for seat in previous)
            # Keep the same position within each cabin when earlier rows are renumbered.
            for old_seat, new_seat in zip(previous, seats):
                new_seat["occupied"] = old_seat["occupied"]
            new_count = min(old_count, len(seats))
            set_cabin_occupancy(seats, new_count)
            if not restoring:
                sync_fill_target(cabin, old_count, new_count)
        refresh_seat_widget_styles(update_page=False)

        active_panel = next(iter(panels))
        panel_host = ft.Container(alignment=ft.Alignment(0, -1), content=panels[active_panel])
        tabs = ft.Row(wrap=True, spacing=6, run_spacing=6)

        def select_panel(label):
            nonlocal active_panel
            if label == active_panel:
                return
            active_panel = label
            panel_host.content = panels[label]
            update_panel_tabs()
            prepare_controls(tabs, panel_host)
            page.update()

        def update_panel_tabs():
            tabs.controls = [
                ft.OutlinedButton(
                    label, style=button_style(tokens, primary=label == active_panel),
                    on_click=lambda e, target=label: select_panel(target),
                )
                for label in panels
            ]

        update_panel_tabs()
        return ft.Column(
            spacing=GAP, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Row(
                    wrap=True, spacing=12, run_spacing=5,
                    controls=[seat_total_stat, seat_occupied_stat, seat_available_stat],
                ),
                *([tabs] if len(panels) > 1 else []),
                panel_host,
            ],
        )

    def seat_map_theme_key():
        return tuple(tokens[name] for name in ("panel", "text", "muted", "card_border"))

    def render_seat_map(*, restoring=False):
        seat_map_host.content = glass_card_with_background(
            "Seat Map",
            build_digital_seat_map(
                seat_model["aircraft"], seat_model["totals"], seat_model["template"], restoring=restoring,
            ),
            bg_key="seat_map",
        )
        seat_map_host.data = seat_map_theme_key()
        prepare_controls(seat_map_host)

    async def generate_seat_map(e):
        try:
            first_count = max(0, int((seat_first_tf.value or "0").strip()))
            business_count = max(0, int((seat_business_tf.value or "0").strip()))
            premium_count = max(0, int((seat_premium_tf.value or "0").strip()))
            economy_count = max(0, int((seat_economy_tf.value or "0").strip()))
        except Exception:
            set_seat_status("Seat counts must be whole numbers.", error=True)
            page.update()
            return

        airline_name = state.airline or "Generic"
        aircraft_name = canonical_aircraft_name(state.aircraft) or state.aircraft or ""
        if not aircraft_name:
            set_seat_status("Select an aircraft on the Dashboard first.", error=True)
            page.update()
            return
        preset = get_aircraft_seat_preset(aircraft_name)
        counts = {
            "First": first_count,
            "Business": business_count,
            "Premium Economy": premium_count,
            "Economy": economy_count,
        }

        seat_model["generated"] = True
        seat_model["airline"] = airline_name
        seat_model["aircraft"] = aircraft_name
        seat_model["template"] = preset
        seat_model["totals"] = counts.copy()

        render_seat_map()
        bag_pax_tf.read_only = True
        bag_pax_tf.label = "Filled passengers"

        seat_summary_title.value = f"{aircraft_name} seat map generated"
        if canonical_aircraft_name(aircraft_name) == "A380-800":
            set_seat_status("Seat map generated. Switch between the upper and lower deck above the diagram.")
        else:
            set_seat_status("Seat map generated. Click seats or use the auto-fill controls below.")
        update_seat_summary(update_page=False)
        page.update()

        try:
            await seat_map_scroll.scroll_to(offset=0, duration=120)
        except RuntimeError:
            # The map can detach while switching tabs or closing the window.
            pass

    async def clear_seat_occupancy(e):
        if not seat_model.get("generated"):
            set_seat_status("Generate a seat map first.", error=True)
            page.update()
            return
        for cabin, seats in seats_by_cabin().items():
            old_count = sum(seat["occupied"] for seat in seats)
            set_cabin_occupancy(seats, 0)
            sync_fill_target(cabin, old_count, 0)
        refresh_seat_widget_styles(update_page=False)
        set_seat_status("All seat occupancy has been cleared.")
        update_seat_summary(update_page=False)
        page.update()

    async def auto_fill_seats(e):
        if not seat_model.get("generated"):
            set_seat_status("Generate a seat map first.", error=True)
            page.update()
            return

        try:
            requested = {
                cabin: max(0, int((field.value or "0").strip()))
                for cabin, field in seat_fill_fields.items()
            }
        except Exception:
            set_seat_status("Passenger fill values must be whole numbers.", error=True)
            page.update()
            return

        cabins = seats_by_cabin()
        for cabin, requested_count in requested.items():
            if requested_count > len(cabins[cabin]):
                set_seat_status(f"{cabin} fill exceeds the configured seat count.", error=True)
                page.update()
                return

        for cabin, count in requested.items():
            set_cabin_occupancy(cabins[cabin], count)
            seat_fill_fields[cabin].value = str(count)

        refresh_seat_widget_styles(update_page=False)

        set_seat_status("Seats filled from your passenger counts.")
        update_seat_summary(update_page=False)
        page.update()

    def reset_seat_map():
        seat_model.clear()
        seat_model.update({
            "generated": False,
            "airline": "",
            "aircraft": "",
            "template": get_aircraft_seat_preset(""),
            "seats": [],
            "seat_controls": {},
            "totals": {},
        })
        highlighted_seat_ids.clear()
        set_seat_status(seat_initial_message)
        seat_summary_title.value = "No seat map generated yet."
        seat_total_stat.value = "Total seats: —"
        seat_occupied_stat.value = "Occupied seats: —"
        seat_available_stat.value = "Available seats: —"
        seat_breakdown_stat.value = "Breakdown: —"
        seat_map_host.content = empty_seat_map()
        seat_passenger_load_host.content = None

    def reset_cabin():
        for control in (*seat_capacity_fields, *seat_fill_fields.values()):
            control.value = "0"
        if seat_model.get("generated"):
            bag_pax_tf.value = "0"
            takeoff_fuel_passengers_tf.value = "0"
        reset_seat_map()

    # Seat page reads airline and aircraft from Home. No local seat-page aircraft/airline selection.
    seat_airline_dd.on_change = None
    seat_aircraft_dd.on_change = None

    bag_mode_dd.on_change = lambda e: refresh_baggage_mode_ui()
    bag_category_dd.on_change = lambda e: (apply_baggage_category_default(), page.update())
    apply_baggage_category_default()
    refresh_baggage_mode_ui(update_page=False)
    reset_baggage_result_display()

    cal_origin_tf.on_change = lambda e: refresh_calendar_route_preview()
    cal_destination_tf.on_change = lambda e: refresh_calendar_route_preview()
    log_sort_dd.on_select = lambda e: refresh_active_page()
    cal_sort_dd.on_change = lambda e: refresh_active_page()
    cal_status_filter_dd.on_change = lambda e: refresh_active_page()
    populate_calendar_aircraft_dropdown(state.airline, canonical_aircraft_name(state.aircraft) or state.aircraft)
    populate_seat_aircraft_dropdown(state.airline, canonical_aircraft_name(state.aircraft) or state.aircraft)

    def reset_calendar_form():
        state.calendar_editing_id = None
        state.calendar_selected_date = ""
        cal_date_tf.value = ""
        cal_time_tf.value = ""
        cal_airline_dd.value = state.airline or None
        populate_calendar_aircraft_dropdown(state.airline, canonical_aircraft_name(state.aircraft) or state.aircraft)
        cal_origin_tf.value = ""
        cal_destination_tf.value = ""
        planner_records.clear()
        cal_flight_time_tf.value = ""
        cal_notes_tf.value = ""
        cal_form_message.value = "Add a planned flight or edit flight details."
        cal_route_preview.value = "Route: —"

    def flight_hibernation_controls() -> Dict[str, object]:
        return {
            "airline": airline_dd,
            "calendar_date": cal_date_tf,
            "calendar_time": cal_time_tf,
            "calendar_airline": cal_airline_dd,
            "calendar_aircraft": cal_aircraft_dd,
            "calendar_origin": cal_origin_tf,
            "calendar_destination": cal_destination_tf,
            "calendar_flight_time": cal_flight_time_tf,
            "calendar_notes": cal_notes_tf,
            "takeoff_aircraft": takeoff_aircraft_dd,
            "takeoff_departure_icao": takeoff_departure_icao_tf,
            "takeoff_gate": takeoff_gate_tf,
            "takeoff_terminal": takeoff_terminal_tf,
            "takeoff_elevation": takeoff_elevation_tf,
            "takeoff_oat": takeoff_oat_tf,
            "takeoff_qnh": takeoff_qnh_tf,
            "takeoff_wind_dir": takeoff_wind_dir_tf,
            "takeoff_wind_speed": takeoff_wind_speed_tf,
            "takeoff_wind_gust": takeoff_wind_gust_tf,
            "takeoff_raw_metar": takeoff_raw_metar_tf,
            "takeoff_runway_heading": takeoff_runway_heading_tf,
            "takeoff_slope": takeoff_slope_tf,
            "takeoff_surface": takeoff_surface_dd,
            "takeoff_flap": takeoff_flap_dd,
            "takeoff_tora": takeoff_tora_tf,
            "takeoff_toda": takeoff_toda_tf,
            "takeoff_asda": takeoff_asda_tf,
            "takeoff_weight": takeoff_weight_tf,
            "takeoff_route_distance": takeoff_route_distance_tf,
            "takeoff_fuel_passengers": takeoff_fuel_passengers_tf,
            "takeoff_fuel_baggage": takeoff_fuel_baggage_tf,
            "takeoff_fuel_cargo": takeoff_fuel_cargo_tf,
            "takeoff_cruise_gs": takeoff_cruise_gs_tf,
            "takeoff_fuel_units": takeoff_fuel_units_dd,
            "takeoff_taxi_fuel": takeoff_taxi_fuel_tf,
            "takeoff_contingency": takeoff_contingency_tf,
            "takeoff_alternate_fuel": takeoff_alternate_fuel_tf,
            "takeoff_final_reserve": takeoff_final_reserve_tf,
            "takeoff_extra_fuel": takeoff_extra_fuel_tf,
            "takeoff_zfw": takeoff_zfw_tf,
            "landing_aircraft": landing_aircraft_dd,
            "landing_arrival_icao": landing_arrival_icao_tf,
            "landing_gate": landing_gate_tf,
            "landing_terminal": landing_terminal_tf,
            "landing_elevation": landing_elevation_tf,
            "landing_oat": landing_oat_tf,
            "landing_qnh": landing_qnh_tf,
            "landing_wind_dir": landing_wind_dir_tf,
            "landing_wind_speed": landing_wind_speed_tf,
            "landing_wind_gust": landing_wind_gust_tf,
            "landing_raw_metar": landing_raw_metar_tf,
            "landing_weight": landing_weight_tf,
            "landing_flap": landing_flap_dd,
            "landing_autobrake": landing_autobrake_dd,
            "landing_surface": landing_surface_dd,
            "landing_reverse": landing_reverse_sw,
            "landing_runway_heading": landing_runway_heading_tf,
            "landing_lda": landing_lda_tf,
            "landing_obstacle": landing_obstacle_tf,
            "landing_current_alt": landing_current_alt_tf,
            "landing_distance_to_go": landing_distance_to_go_tf,
            "landing_ground_speed": landing_ground_speed_tf,
            "landing_vs_calc_altitude": landing_vs_calc_altitude_tf,
            "landing_vs_calc_ete": landing_vs_calc_ete_tf,
            "baggage_mode": bag_mode_dd,
            "baggage_passengers": bag_pax_tf,
            "baggage_carry_on": bag_carry_on_tf,
            "baggage_category": bag_category_dd,
            "baggage_checked_kg_per_pax": bag_checked_kg_per_pax_tf,
            "baggage_cargo_weight": cargo_weight_tf,
            "baggage_two_bag_percent": bag_two_bag_percent_tf,
            "baggage_per_bag_kg": bag_per_bag_kg_tf,
            "seat_airline": seat_airline_dd,
            "seat_aircraft": seat_aircraft_dd,
            "seat_first": seat_first_tf,
            "seat_business": seat_business_tf,
            "seat_premium": seat_premium_tf,
            "seat_economy": seat_economy_tf,
            "seat_fill_first": seat_fill_first_tf,
            "seat_fill_business": seat_fill_business_tf,
            "seat_fill_premium": seat_fill_premium_tf,
            "seat_fill_economy": seat_fill_economy_tf,
        }

    def control_snapshot(control: object):
        if hasattr(control, "value"):
            return getattr(control, "value")
        return None

    def set_control_snapshot(control: object, value):
        if hasattr(control, "value"):
            try:
                setattr(control, "value", value)
            except Exception:
                pass

    def json_safe_value(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            safe = {}
            for key, item in value.items():
                if key == "seat_controls":
                    continue
                safe[str(key)] = json_safe_value(item)
            return safe
        if isinstance(value, (list, tuple, set)):
            return [json_safe_value(item) for item in value]
        return str(value)

    def flight_hibernation_summary() -> Dict[str, object]:
        route = f"{(state.departure or takeoff_departure_icao_tf.value or 'DEPARTURE').strip().upper()} -> {(state.arrival or landing_arrival_icao_tf.value or 'ARRIVAL').strip().upper()}"
        return {
            "route": route,
            "airline": state.airline or "No airline selected",
            "aircraft": state.aircraft or "No aircraft selected",
            "flight_number": state.flight_number or "No flight number",
            "status": state.flight_status or "Flight saved",
        }

    def load_flight_hibernation_payload() -> Optional[dict]:
        if not flight_hibernation_storage_path.exists():
            return None
        try:
            payload = json.loads(flight_hibernation_storage_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def has_flight_hibernation_save() -> bool:
        return load_flight_hibernation_payload() is not None

    def clear_flight_hibernation_save():
        try:
            if flight_hibernation_storage_path.exists():
                flight_hibernation_storage_path.unlink()
        except Exception:
            pass

    def reset_active_flight_workspace(show_message: bool = True):
        clear_flight_hibernation_save()

        state.airline = ""
        state.aircraft = ""
        state.aircraft_record = {}
        state.airline_record = {}
        state.flight_number = ""
        state.dashboard_flight_plan.clear()
        state.departure = ""
        state.arrival = ""
        state.departure_gate = ""
        state.arrival_gate = ""
        state.departure_terminal = ""
        state.arrival_terminal = ""
        state.boarding_status = "Not started"
        state.cargo_status = "Not started"
        state.catering_status = "Not started"
        state.flight_status = "Select an airline"
        state.overview_flight_status_index = 0
        state.overview_flight_time_minutes = 0
        state.overview_takeoff_start_timestamp = None
        state.overview_locked_eta_timestamp = None
        state.overview_progress_running = False
        state.overview_paused_elapsed_seconds = None
        state.overview_calendar_completion_key = ""
        state.captain_announcement_language = "English"
        state.captain_announcement_phase = "departure"
        state.captain_announcement_text = ""
        state.captain_departure_announcement_text = ""
        state.captain_descent_announcement_text = ""
        state.captain_announcement_cruise_altitude_ft = ""
        state.captain_announcement_current_altitude_ft = ""
        state.captain_announcement_generating = False
        state.takeoff_announcement_expanded = False
        state.descent_announcement_expanded = False
        state.takeoff_operations_view = "menu"
        state.landing_operations_view = "menu"
        state.checklist_section = "turn_on_aircraft"
        state.checklist_completed = {}
        state.takeoff_clock_source = "route"
        state.landing_clock_source = "route"
        state.takeoff_clock_menu_open = False
        state.landing_clock_menu_open = False
        state.route_distance_override_nm = None
        state.route_distance_override_key = ""
        state.ramp_status_phase = "departure"
        state.ramp_departure_statuses = {}
        state.ramp_arrival_statuses = {}
        state.takeoff_last_result = {}
        state.landing_last_result = {}
        state.logo_refresh_nonce += 1

        for control in flight_hibernation_controls().values():
            set_control_snapshot(control, None)

        airline_dd.value = None
        reset_calendar_form()
        reset_takeoff_form(update_page=False)
        reset_landing_form(update_page=False)

        takeoff_terminal_tf.value = ""
        landing_terminal_tf.value = ""
        landing_vs_calc_altitude_tf.value = ""
        landing_vs_calc_ete_tf.value = ""

        bag_mode_dd.value = "Standard"
        bag_pax_tf.value = "0"
        bag_carry_on_tf.value = "0"
        bag_category_dd.value = "Within the European region"
        apply_baggage_category_default()
        cargo_weight_tf.value = "0"
        bag_two_bag_percent_tf.value = "0"
        bag_per_bag_kg_tf.value = "0"
        refresh_baggage_mode_ui(update_page=False)
        reset_baggage_result_display()
        set_baggage_status("Enter values and click Calculate.")

        seat_airline_dd.value = None
        seat_aircraft_dd.value = None
        reset_cabin()

        status_gate_tf.value = ""
        status_boarding_dd.value = "Not started"
        status_cargo_dd.value = "Not started"
        status_catering_dd.value = "Not started"
        status_center_modal.visible = False
        flight_end_summary_modal.visible = False
        flight_hibernation_prompt_modal.visible = False
        airline_picker_modal.visible = False
        aircraft_picker_modal.visible = False

        clear_asset_lookup_caches()
        sync_input_colors()
        state.selected_tab_index = 1
        refresh_ui()
        if show_message:
            show_snack("New flight started. The previous flight workspace has been reset.")

    def save_current_flight_hibernation(e=None):
        controls_payload = {
            name: json_safe_value(control_snapshot(control))
            for name, control in flight_hibernation_controls().items()
        }
        saved_state_fields = [
            "pilot_name",
            "airline",
            "aircraft",
            "airline_record",
            "aircraft_record",
            "flight_number",
            "dashboard_flight_plan",
            "departure",
            "arrival",
            "departure_gate",
            "arrival_gate",
            "departure_terminal",
            "arrival_terminal",
            "boarding_status",
            "cargo_status",
            "catering_status",
            "flight_status",
            "overview_flight_status_index",
            "overview_flight_time_minutes",
            "overview_locked_eta_timestamp",
            "overview_progress_running",
            "overview_paused_elapsed_seconds",
            "captain_announcement_language",
            "captain_announcement_phase",
            "captain_announcement_text",
            "captain_departure_announcement_text",
            "captain_descent_announcement_text",
            "captain_announcement_cruise_altitude_ft",
            "captain_announcement_current_altitude_ft",
            "route_distance_override_nm",
            "route_distance_override_key",
            "ramp_status_phase",
            "ramp_departure_statuses",
            "ramp_arrival_statuses",
            "takeoff_last_result",
            "landing_last_result",
            "selected_tab_index",
        ]
        payload = {
            "version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "summary": json_safe_value(flight_hibernation_summary()),
            "state": {
                field_name: json_safe_value(getattr(state, field_name, None))
                for field_name in saved_state_fields
            },
            "planner_records": planner_records,
            "airport_records": [record for code in (state.departure, state.arrival)
                                if (record := lookup_airport_record(code))],
            "overview_elapsed_seconds": overview_elapsed_seconds(),
            "controls": controls_payload,
            "seat_model": json_safe_value(seat_model),
        }
        try:
            flight_hibernation_storage_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            show_snack("Paused flight saved. You can resume it after the next login.")
            refresh_ui()
        except Exception as ex:
            show_snack(f"Could not save the paused flight: {ex}")

    def restore_flight_hibernation_payload(payload: dict):
        planner_records.clear()
        planner_records.update(payload.get("planner_records") or {})
        for record in [*payload.get("airport_records", []), planner_records.get("origin"), planner_records.get("destination")]:
            if isinstance(record, dict) and record.get("code"):
                remember_airport(record)
        saved_state = payload.get("state", {}) if isinstance(payload, dict) else {}
        if isinstance(saved_state, dict):
            for key, value in saved_state.items():
                if hasattr(state, key):
                    setattr(state, key, value)

        if state.airline:
            state.airline = canonical_airline_name(state.airline)
            register_custom_airline(state.airline)
        state.aircraft = canonical_aircraft_name(state.aircraft) or state.aircraft

        controls_payload = payload.get("controls", {}) if isinstance(payload, dict) else {}
        if isinstance(controls_payload, dict):
            airline_value = canonical_airline_name(controls_payload.get("airline") or state.airline)
            if airline_value:
                state.airline = airline_value
                register_custom_airline(airline_value)
            aircraft_value = canonical_aircraft_name(controls_payload.get("takeoff_aircraft") or state.aircraft) or state.aircraft
            if aircraft_value:
                state.aircraft = aircraft_value

            airline_dd.value = state.airline or None
            cal_airline_dd.value = state.airline or None
            seat_airline_dd.value = state.airline or None
            populate_calendar_aircraft_dropdown(state.airline, state.aircraft)
            populate_takeoff_aircraft_dropdown(state.airline, state.aircraft)
            populate_landing_aircraft_dropdown(state.airline, state.aircraft)
            populate_seat_aircraft_dropdown(state.airline, state.aircraft)

            for name, value in controls_payload.items():
                control = flight_hibernation_controls().get(name)
                if control is not None:
                    set_control_snapshot(control, value)

        saved_seat_model = payload.get("seat_model", {}) if isinstance(payload, dict) else {}
        if isinstance(saved_seat_model, dict) and saved_seat_model.get("generated") and saved_seat_model.get("totals"):
            seat_model.clear()
            seat_model.update(saved_seat_model)
            seat_model["seat_controls"] = {}
        else:
            reset_seat_map()

        state.departure = normalize_airport_code(state.departure or takeoff_departure_icao_tf.value) or (state.departure or "")
        state.arrival = normalize_airport_code(state.arrival or landing_arrival_icao_tf.value) or (state.arrival or "")
        queue_airport_media(state.departure)
        queue_airport_media(state.arrival)
        state.departure_gate = takeoff_gate_tf.value or state.departure_gate
        state.arrival_gate = landing_gate_tf.value or state.arrival_gate
        state.departure_terminal = takeoff_terminal_tf.value or state.departure_terminal
        state.arrival_terminal = landing_terminal_tf.value or state.arrival_terminal

        elapsed_seconds = payload.get("overview_elapsed_seconds", 0) if isinstance(payload, dict) else 0
        try:
            elapsed_seconds = max(0.0, float(elapsed_seconds or 0.0))
        except Exception:
            elapsed_seconds = 0.0
        duration_seconds = planned_overview_minutes() * 60
        if state.overview_progress_running or state.overview_paused_elapsed_seconds is not None:
            if duration_seconds:
                elapsed_seconds = min(elapsed_seconds, duration_seconds)
            now = time.time()
            state.overview_takeoff_start_timestamp = now - elapsed_seconds
            state.overview_locked_eta_timestamp = now + duration_seconds - elapsed_seconds if duration_seconds else None
            if not state.overview_progress_running:
                state.overview_paused_elapsed_seconds = elapsed_seconds
        elif int(getattr(state, "overview_flight_status_index", 0) or 0) >= 5 and duration_seconds:
            state.overview_takeoff_start_timestamp = time.time() - duration_seconds

        refresh_baggage_mode_ui(update_page=False)
        update_seat_summary(update_page=False)
        refresh_calendar_route_preview()
        update_landing_aircraft_details(update_page=False)
        refresh_takeoff_fuel_info(update_page=False)
        sync_input_colors()

    def continue_previous_flight(payload: dict):
        restore_flight_hibernation_payload(payload)
        flight_hibernation_prompt_modal.visible = False
        refresh_ui()
        show_snack("Previous flight restored.")

    def start_new_after_hibernation_prompt():
        reset_active_flight_workspace(show_message=False)
        show_snack("Saved flight discarded.")

    def show_flight_hibernation_prompt():
        if not state.is_logged_in or bool(getattr(state, "flight_hibernation_prompt_seen", False)):
            return
        payload = load_flight_hibernation_payload()
        if not payload:
            return
        state.flight_hibernation_prompt_seen = True
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        saved_at_raw = str(payload.get("saved_at") or "").replace("T", " ")
        route_label = str(summary.get("route") or "Saved flight")
        airline_label = str(summary.get("airline") or "No airline selected")
        aircraft_label = str(summary.get("aircraft") or "No aircraft selected")

        flight_hibernation_prompt_modal.content = ft.Container(
            width=520,
            padding=22,
            border_radius=26,
            bgcolor=surface_fill(tokens["panel"]),
            border=ft.border.all(1, tokens["card_border"]),
            shadow=ft.BoxShadow(
                blur_radius=34,
                spread_radius=2,
                color=ft.Colors.with_opacity(0.32, ft.Colors.BLACK),
                offset=ft.Offset(0, 12),
            ),
            content=ft.Column(
                tight=True,
                spacing=16,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text("Continue Previous Flight?", size=21, weight=ft.FontWeight.W_900, color=tokens["text"]),
                            ft.Icon(ft.Icons.FLIGHT_TAKEOFF, size=26, color=tokens["accent"]),
                        ],
                    ),
                    ft.Text(
                        "A paused flight was found. Resume where you left off, or discard the saved flight.",
                        size=12,
                        color=tokens["muted"],
                    ),
                    ft.Container(
                        padding=16,
                        border_radius=18,
                        bgcolor=surface_fill(tokens["subpanel"]),
                        border=ft.border.all(1, tokens["card_border"]),
                        content=ft.Column(
                            tight=True,
                            spacing=7,
                            controls=[
                                ft.Text(route_label, size=18, weight=ft.FontWeight.W_900, color=tokens["text"]),
                                ft.Text(f"{airline_label} - {aircraft_label}", size=12, color=tokens["muted"]),
                                ft.Text(f"Saved: {saved_at_raw or 'Unknown time'}", size=11, color=tokens["muted"]),
                            ],
                        ),
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.END,
                        spacing=10,
                        controls=[
                            ft.OutlinedButton("Discard saved flight", on_click=lambda e: start_new_after_hibernation_prompt()),
                            ft.ElevatedButton(
                                "Continue Previous Flight",
                                on_click=lambda e, saved_payload=payload: continue_previous_flight(saved_payload),
                                bgcolor=tokens["primary"],
                                color=tokens["on_primary"],
                            ),
                        ],
                    ),
                ],
            ),
        )
        flight_hibernation_prompt_modal.visible = True
        page.update()

    def flight_end_summary_values() -> Dict[str, object]:
        origin = normalize_airport_code(state.departure or takeoff_departure_icao_tf.value) or (state.departure or takeoff_departure_icao_tf.value or "").strip().upper()
        destination = normalize_airport_code(state.arrival or landing_arrival_icao_tf.value) or (state.arrival or landing_arrival_icao_tf.value or "").strip().upper()
        distance_value = route_distance_nm(origin, destination) if origin and destination else None
        planned_minutes = planned_overview_minutes()
        elapsed_minutes = int(overview_elapsed_seconds() / 60.0)
        if planned_minutes and int(state.overview_flight_status_index or 0) >= 5:
            elapsed_minutes = planned_minutes

        fuel_plan = state.takeoff_last_result.get("fuel_plan", {}) if isinstance(getattr(state, "takeoff_last_result", None), dict) else {}
        planned_fuel = fuel_plan.get("planned_fuel_kg") if isinstance(fuel_plan, dict) else None
        trip_fuel = (fuel_plan.get("corrected_trip_fuel_kg") or fuel_plan.get("trip_fuel_kg")) if isinstance(fuel_plan, dict) else None
        passenger_source = "Manual input"
        passenger_count = None
        if seat_model.get("generated"):
            passenger_count = sum(1 for seat in seat_model.get("seats", []) if seat.get("occupied"))
            passenger_source = "Seat map"
        if passenger_count is None:
            for candidate in (takeoff_fuel_passengers_tf.value, bag_pax_tf.value):
                try:
                    passenger_count = max(0, int(float(str(candidate or "").strip())))
                    break
                except Exception:
                    pass
        return {
            "route": f"{origin or 'DEPARTURE'} -> {destination or 'ARRIVAL'}",
            "origin": origin or "—",
            "destination": destination or "—",
            "airline": state.airline or "No airline selected",
            "aircraft": state.aircraft or takeoff_aircraft_dd.value or "No aircraft selected",
            "flight_number": state.flight_number or "—",
            "distance": f"{distance_value:.0f} NM" if distance_value else "—",
            "planned_time": format_hours_to_hm(planned_minutes / 60.0) if planned_minutes else "—",
            "elapsed_time": format_hours_to_hm(elapsed_minutes / 60.0) if elapsed_minutes > 0 else "—",
            "progress": f"{min(100, round(elapsed_minutes / planned_minutes * 100))}%" if planned_minutes else "—",
            "departure_gate": state.departure_gate or takeoff_gate_tf.value or "—",
            "arrival_gate": state.arrival_gate or landing_gate_tf.value or "—",
            "departure_terminal": state.departure_terminal or takeoff_terminal_tf.value or "—",
            "arrival_terminal": state.arrival_terminal or landing_terminal_tf.value or "—",
            "ramp_phase": str(getattr(state, "ramp_status_phase", "departure") or "departure").title(),
            "planned_fuel": f"{planned_fuel / 1000:.1f} t" if isinstance(planned_fuel, (int, float)) else "—",
            "trip_fuel": f"{trip_fuel / 1000:.1f} t" if isinstance(trip_fuel, (int, float)) else "—",
            "passengers_on_board": f"{passenger_count}" if passenger_count is not None else "â€”",
            "passenger_source": passenger_source if passenger_count is not None else "Not set",
        }

    def flight_end_summary_tile(label: str, value: str, subtitle: str = "", width: int = 124) -> ft.Control:
        return ft.Container(
            width=width,
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            border_radius=17,
            bgcolor=surface_fill(tokens["subpanel"]),
            border=ft.border.all(1, ft.Colors.with_opacity(0.18, ft.Colors.WHITE)),
            content=ft.Column(
                tight=True,
                spacing=4,
                controls=[
                    ft.Text(label, size=10, weight=ft.FontWeight.W_700, color=tokens["muted"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(value or "—", size=17, weight=ft.FontWeight.W_900, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(subtitle, size=9, color=tokens["muted"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ],
            ),
        )

    def close_flight_end_summary(e=None):
        flight_end_summary_modal.visible = False
        if getattr(flight_end_summary_modal, "page", None):
            flight_end_summary_modal.update()
        page.update()

    def save_completed_overview_flight(summary: Dict[str, object]) -> str:
        now = datetime.now()
        start_timestamp = getattr(state, "overview_takeoff_start_timestamp", None)
        departure_datetime = (
            datetime.fromtimestamp(float(start_timestamp))
            if isinstance(start_timestamp, (int, float))
            else now
        )
        origin = normalize_airport_code(str(summary.get("origin") or "")) or str(summary.get("origin") or "TBD").strip().upper()
        destination = normalize_airport_code(str(summary.get("destination") or "")) or str(summary.get("destination") or "TBD").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{3,4}", origin):
            origin = "TBD"
        if not re.fullmatch(r"[A-Z0-9]{3,4}", destination):
            destination = "TBD"

        completion_key = str(getattr(state, "overview_calendar_completion_key", "") or "").strip()
        if not completion_key:
            session_timestamp = int(float(start_timestamp)) if isinstance(start_timestamp, (int, float)) else int(now.timestamp())
            completion_key = f"overview-{session_timestamp}-{origin}-{destination}"
            state.overview_calendar_completion_key = completion_key

        flight_time = str(summary.get("planned_time") or "").strip()
        if not parse_flight_time_minutes(flight_time):
            flight_time = str(summary.get("elapsed_time") or "").strip()

        passenger_value = str(summary.get("passengers_on_board") or "").strip()
        if not re.fullmatch(r"\d+", passenger_value):
            passenger_value = ""
        completion_note = "Completed from the Overview flight-end summary."
        completion_updates = {
            "date": departure_datetime.strftime("%Y-%m-%d"),
            "time": departure_datetime.strftime("%H:%M"),
            "airline": str(summary.get("airline") or state.airline or "No airline selected"),
            "aircraft": str(summary.get("aircraft") or state.aircraft or "No aircraft selected"),
            "origin": origin,
            "destination": destination,
            "route": f"{origin} -> {destination}",
            "flight_number": str(summary.get("flight_number") or state.flight_number or ""),
            "gate": str(summary.get("departure_gate") or state.departure_gate or ""),
            "arrival_gate": str(summary.get("arrival_gate") or state.arrival_gate or ""),
            "departure_terminal": str(summary.get("departure_terminal") or state.departure_terminal or ""),
            "arrival_terminal": str(summary.get("arrival_terminal") or state.arrival_terminal or ""),
            "arrival_time": now.strftime("%H:%M"),
            "passengers": passenger_value,
            "distance": str(summary.get("distance") or ""),
            "completed": True,
            "completed_at": now.isoformat(timespec="seconds"),
            "updated_at": now.isoformat(timespec="seconds"),
            "source": "overview_flight_end",
            "overview_completion_key": completion_key,
        }
        if state.dashboard_flight_plan:
            completion_updates["dashboard_flight_plan"] = dict(state.dashboard_flight_plan)

        existing_entry = next(
            (
                entry
                for entry in state.calendar_entries
                if str(entry.get("overview_completion_key") or "") == completion_key
            ),
            None,
        )
        action = "updated"
        if existing_entry is None:
            current_airline = str(completion_updates["airline"] or "").strip().casefold()
            current_aircraft = canonical_aircraft_name(str(completion_updates["aircraft"] or "")) or str(completion_updates["aircraft"] or "").strip()

            def planned_entry_matches(entry: dict) -> bool:
                entry_airline = str(entry.get("airline") or "").strip().casefold()
                entry_aircraft = canonical_aircraft_name(str(entry.get("aircraft") or "")) or str(entry.get("aircraft") or "").strip()
                airline_matches = not entry_airline or current_airline == "no airline selected" or entry_airline == current_airline
                aircraft_matches = not entry_aircraft or current_aircraft == "No aircraft selected" or entry_aircraft == current_aircraft
                return (
                    not bool(entry.get("completed"))
                    and str(entry.get("date") or "") == completion_updates["date"]
                    and (normalize_airport_code(str(entry.get("origin") or "")) or str(entry.get("origin") or "").strip().upper()) == origin
                    and (normalize_airport_code(str(entry.get("destination") or "")) or str(entry.get("destination") or "").strip().upper()) == destination
                    and airline_matches
                    and aircraft_matches
                )

            def departure_time_distance(entry: dict) -> int:
                try:
                    target_time = datetime.strptime(str(completion_updates["time"]), "%H:%M")
                    entry_time = datetime.strptime(str(entry.get("time") or ""), "%H:%M")
                    return abs((target_time.hour * 60 + target_time.minute) - (entry_time.hour * 60 + entry_time.minute))
                except ValueError:
                    return 24 * 60

            planned_matches = [
                entry
                for entry in state.calendar_entries
                if planned_entry_matches(entry)
            ]
            existing_entry = min(planned_matches, key=departure_time_distance) if planned_matches else None

        if parse_flight_time_minutes(flight_time):
            completion_updates["flight_time"] = flight_time

        if existing_entry is None:
            existing_entry = {
                "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                "notes": completion_note,
                "flight_time": "",
            }
            existing_entry.update(completion_updates)
            state.calendar_entries.append(existing_entry)
            action = "added"
        else:
            existing_notes = str(existing_entry.get("notes") or "").strip()
            if completion_note not in existing_notes:
                existing_entry["notes"] = f"{existing_notes} | {completion_note}" if existing_notes else completion_note
            existing_entry.update(completion_updates)

        sort_calendar_entries_default()
        sync_profile_from_calendar_completion()
        save_calendar_entries()
        return action

    def finish_current_flight(e=None):
        summary = flight_end_summary_values()
        calendar_action = save_completed_overview_flight(summary)
        state.overview_progress_running = False
        state.overview_paused_elapsed_seconds = None
        state.overview_flight_status_index = 6
        state.flight_status = "Flight ended"
        clear_flight_hibernation_save()
        reset_cabin()
        flight_end_summary_modal.visible = False
        refresh_ui()
        show_snack(f"Flight ended, {calendar_action} in Calendar, and marked completed.")

    def show_flight_end_summary(e=None):
        summary = flight_end_summary_values()
        flight_end_summary_modal.content = ft.Container(
            width=720,
            padding=24,
            border_radius=30,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=surface_fill(tokens["panel"]),
            blur=ft.Blur(16, 16, ft.BlurTileMode.CLAMP),
            border=ft.border.all(1, ft.Colors.with_opacity(0.18, ft.Colors.WHITE)),
            shadow=ft.BoxShadow(
                blur_radius=38,
                spread_radius=2,
                color=ft.Colors.with_opacity(0.36, ft.Colors.BLACK),
                offset=ft.Offset(0, 16),
            ),
            content=ft.Column(
                tight=True,
                spacing=18,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Column(
                                tight=True,
                                spacing=3,
                                controls=[
                                    ft.Text("Flight Summary", size=22, weight=ft.FontWeight.W_900, color=tokens["text"]),
                                    ft.Text(str(summary["route"]), size=13, color=tokens["muted"]),
                                ],
                            ),
                            ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close", icon_color=tokens["text"], on_click=close_flight_end_summary),
                        ],
                    ),
                    ft.Container(
                        padding=18,
                        border_radius=22,
                        bgcolor=ft.Colors.with_opacity(0.26, tokens["accent"]),
                        border=ft.border.all(1, ft.Colors.with_opacity(0.30, tokens["accent"])),
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Column(
                                    tight=True,
                                    spacing=4,
                                    controls=[
                                        ft.Text(str(summary["airline"]), size=16, weight=ft.FontWeight.W_900, color=tokens["text"]),
                                        ft.Text(f"{summary['aircraft']} • Flight {summary['flight_number']}", size=12, color=tokens["muted"]),
                                    ],
                                ),
                                ft.Container(
                                    padding=ft.padding.symmetric(horizontal=16, vertical=9),
                                    border_radius=999,
                                    bgcolor=ft.Colors.with_opacity(0.22, tokens["panel"]),
                                    border=ft.border.all(1, ft.Colors.with_opacity(0.28, ft.Colors.WHITE)),
                                    content=ft.Text(str(summary["progress"]), size=18, weight=ft.FontWeight.W_900, color=tokens["accent"]),
                                ),
                            ],
                        ),
                    ),
                    ft.Row(
                        wrap=False,
                        spacing=12,
                        run_spacing=12,
                        controls=[
                            flight_end_summary_tile("Departure", str(summary["origin"]), f"T{summary['departure_terminal']} / Gate {summary['departure_gate']}"),
                            flight_end_summary_tile("Arrival", str(summary["destination"]), f"T{summary['arrival_terminal']} / Gate {summary['arrival_gate']}"),
                            flight_end_summary_tile("Flight Time", str(summary["planned_time"]), "Scheduled"),
                            flight_end_summary_tile("Distance", str(summary["distance"]), "Route estimate"),
                            flight_end_summary_tile("Passengers On Board", str(summary["passengers_on_board"]), str(summary["passenger_source"])),
                        ],
                    ),
                    ft.Row(
                        visible=False,
                        wrap=True,
                        spacing=12,
                        run_spacing=12,
                        controls=[
                            flight_end_summary_tile("Departure", str(summary["origin"]), f"T{summary['departure_terminal']} • Gate {summary['departure_gate']}"),
                            flight_end_summary_tile("Arrival", str(summary["destination"]), f"T{summary['arrival_terminal']} • Gate {summary['arrival_gate']}"),
                        ],
                    ),
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=14, vertical=11),
                        border_radius=18,
                        bgcolor=ft.Colors.with_opacity(0.16, tokens["subpanel"]),
                        border=ft.border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.WHITE)),
                        content=ft.Text(
                            "Simulator use only. This summary is for your FMS workflow and does not represent real-world aviation, dispatch, navigation, or flight operations.",
                            size=11,
                            color=tokens["muted"],
                        ),
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.END,
                        spacing=10,
                        controls=[
                            ft.OutlinedButton("Keep Flight Open", on_click=close_flight_end_summary),
                            ft.ElevatedButton("End Flight", bgcolor="#B3261E", color=ft.Colors.WHITE, on_click=finish_current_flight),
                        ],
                    ),
                ],
            ),
        )
        flight_end_summary_modal.visible = True
        page.update()

    def refresh_ui():
        nonlocal ui_refresh_in_progress, close_suggestions
        if ui_refresh_in_progress:
            return
        ui_refresh_in_progress = True
        try:
            if close_suggestions:
                close_suggestions()
                close_suggestions = None
            apply_theme()
            page.bgcolor = tokens["bg"]
            root_host.bgcolor = ft.Colors.TRANSPARENT
            sync_input_colors()
            refresh_header_texts()
            airline_dd.value = state.airline or None
            theme_toggle.value = page.theme_mode == ft.ThemeMode.DARK
            if state.selected_tab_index < 0:
                state.selected_tab_index = 0
            if state.selected_tab_index > 13:
                state.selected_tab_index = 13
            if state.selected_tab_index == 6:
                state.selected_tab_index = 0
            if (not state.is_logged_in) or state.selected_tab_index != 0:
                close_overview_globe_webview()
            if not state.is_logged_in or state.selected_tab_index != 1:
                close_dashboard_airport_map()
                page.on_resize = None
            if not state.is_logged_in:
                close_live_map()
            elif state.selected_tab_index != 0 or not state.overview_live:
                set_live_map_visibility(False)
            root_host.content = app_shell()
            prepare_controls(root_host, *page.overlay)
            page.update()
            guide = page_guides.get(2 if state.selected_tab_index == 3 else state.selected_tab_index)
            if state.is_logged_in and not state.tutorial_skipped and guide and guide[0] not in state.tutorial_seen:
                page.run_task(show_page_guide, state.selected_tab_index)
        finally:
            ui_refresh_in_progress = False

    def apply_selected_airline(force_refresh: bool = False):
        selected_value = canonical_airline_name(airline_dd.value or state.airline)

        state.airline = selected_value
        airline_dd.value = selected_value or None
        state.logo_refresh_nonce += 1
        clear_asset_lookup_caches()
        state.flight_status = derive_idle_status()

        if seat_airline_dd.value != (selected_value or None):
            seat_airline_dd.value = selected_value or None
        populate_seat_aircraft_dropdown(selected_value, state.aircraft)

        if not state.calendar_editing_id and not planner_records:
            cal_airline_dd.value = selected_value or None
            populate_calendar_aircraft_dropdown(selected_value)

        populate_takeoff_aircraft_dropdown(selected_value, state.aircraft)
        populate_landing_aircraft_dropdown(selected_value, state.aircraft)
        if state.aircraft:
            sync_aircraft_across_pages(state.aircraft, update_page=False)

        if force_refresh or root_host.content is not None:
            refresh_ui()

    def refresh_logo_ui(e=None):
        apply_selected_airline(force_refresh=True)

    def set_airline(value: str):
        airline_name = canonical_airline_name(value)
        airline_dd.value = airline_name or None
        state.airline = airline_name
        if canonical_airline_name(state.airline_record.get("name")) != airline_name:
            state.airline_record = {}
        apply_selected_airline(force_refresh=True)

    def close_airline_picker(e=None):
        airline_picker_modal.visible = False
        if getattr(airline_picker_modal, "page", None):
            airline_picker_modal.update()
        page.update()

    def select_airline_from_picker(airline_name: str):
        airline_picker_modal.visible = False
        set_airline(airline_name)

    def build_airline_picker_card(airline_name: str) -> ft.Control:
        selected = airline_name == state.airline
        card = ft.Container(
            width=150,
            height=150,
            padding=10,
            border_radius=24,
            alignment=ft.Alignment(0, 0),
            bgcolor=ft.Colors.with_opacity(0.18 if selected else 0.10, tokens["accent"] if selected else ft.Colors.WHITE),
            border=ft.border.all(2 if selected else 1, tokens["accent"] if selected else tokens["card_border"]),
            shadow=ft.BoxShadow(
                blur_radius=18 if selected else 10,
                spread_radius=1 if selected else 0,
                color=ft.Colors.with_opacity(0.24 if selected else 0.12, tokens["accent"] if selected else ft.Colors.BLACK),
                offset=ft.Offset(0, 6),
            ),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
                controls=[
                    airline_logo_image(airline_name, width=110, height=110, fallback_text=True, key_prefix="picker-logo"),
                ],
            ),
        )
        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e, name=airline_name: select_airline_from_picker(name),
            content=card,
        )

    airline_picker_page_state = {"start": 0}
    AIRLINE_PICKER_VISIBLE_CARDS = 11

    def visible_airline_names() -> list:
        names = list(AIRLINES)
        start = max(0, min(int(airline_picker_page_state.get("start", 0)), max(0, len(names) - AIRLINE_PICKER_VISIBLE_CARDS)))
        airline_picker_page_state["start"] = start
        return names[start:start + AIRLINE_PICKER_VISIBLE_CARDS]

    def rebuild_airline_picker_content():
        names = list(AIRLINES)
        start = max(0, min(int(airline_picker_page_state.get("start", 0)), max(0, len(names) - AIRLINE_PICKER_VISIBLE_CARDS)))
        airline_picker_page_state["start"] = start
        end_index = min(len(names), start + AIRLINE_PICKER_VISIBLE_CARDS)
        can_left = start > 0
        can_right = end_index < len(names)

        airline_picker_modal.content = ft.Container(
            height=250,
            width=float("inf"),
            padding=ft.padding.only(left=22, right=22, top=18, bottom=18),
            border_radius=ft.border_radius.only(top_left=28, top_right=28),
            bgcolor=surface_fill(tokens["panel"]),
            border=ft.border.all(1, tokens["card_border"]),
            shadow=ft.BoxShadow(
                blur_radius=28,
                spread_radius=2,
                color=ft.Colors.with_opacity(0.28, ft.Colors.BLACK),
                offset=ft.Offset(0, -8),
            ),
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Row(
                                spacing=10,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Text("Select Airline", size=16, weight=ft.FontWeight.W_800, color=tokens["text"]),
                                ],
                            ),
                            ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close", on_click=close_airline_picker, icon_color=tokens["text"]),
                        ],
                    ),
                    ft.Row(
                        height=172,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.IconButton(
                                icon=ft.Icons.CHEVRON_LEFT,
                                tooltip="Previous airlines",
                                disabled=not can_left,
                                on_click=lambda e: scroll_airline_picker(-1),
                                icon_color=tokens["text"],
                                bgcolor=ft.Colors.with_opacity(0.08 if can_left else 0.03, tokens["text"]),
                            ),
                            ft.Container(
                                expand=True,
                                height=172,
                                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                                content=ft.Row(
                                    spacing=14,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[build_airline_picker_card(name) for name in visible_airline_names()],
                                ),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CHEVRON_RIGHT,
                                tooltip="Next airlines",
                                disabled=not can_right,
                                on_click=lambda e: scroll_airline_picker(1),
                                icon_color=tokens["text"],
                                bgcolor=ft.Colors.with_opacity(0.08 if can_right else 0.03, tokens["text"]),
                            ),
                        ],
                    ),
                ],
            ),
        )

    def scroll_airline_picker(direction: int):
        # Rewritten from scratch: this is a carousel/pager instead of relying on
        # Flet's horizontal scroll offset, which can be unreliable in bottom overlays.
        names = list(AIRLINES)
        step = 3
        current = int(airline_picker_page_state.get("start", 0))
        max_start = max(0, len(names) - AIRLINE_PICKER_VISIBLE_CARDS)
        if int(direction) > 0:
            airline_picker_page_state["start"] = min(max_start, current + step)
        else:
            airline_picker_page_state["start"] = max(0, current - step)
        rebuild_airline_picker_content()
        airline_picker_modal.visible = True
        page.update()

    def open_airline_picker(e=None):
        # Keep the selected airline visible when opening the picker.
        names = list(AIRLINES)
        selected = state.airline if state.airline in names else None
        if selected:
            selected_index = names.index(selected)
            max_start = max(0, len(names) - AIRLINE_PICKER_VISIBLE_CARDS)
            airline_picker_page_state["start"] = max(0, min(selected_index, max_start))
        else:
            airline_picker_page_state["start"] = 0
        rebuild_airline_picker_content()
        airline_picker_modal.visible = True
        page.update()

    def close_aircraft_picker(e=None):
        aircraft_picker_modal.visible = False
        if getattr(aircraft_picker_modal, "page", None):
            aircraft_picker_modal.update()
        page.update()

    def select_aircraft_from_picker(aircraft_name: str):
        aircraft_picker_modal.visible = False
        sync_aircraft_across_pages(aircraft_name, update_page=False)
        refresh_ui()

    def build_aircraft_picker_card(aircraft_name: str) -> ft.Control:
        selected = aircraft_name == state.aircraft
        aircraft_data = AIRCRAFT_LIBRARY.get(aircraft_name, {})
        display_name = aircraft_data.get("name", aircraft_name)
        card = ft.Container(
            width=150,
            height=150,
            padding=10,
            border_radius=24,
            alignment=ft.Alignment(0, 0),
            bgcolor=ft.Colors.with_opacity(0.18 if selected else 0.10, tokens["accent"] if selected else ft.Colors.WHITE),
            border=ft.border.all(2 if selected else 1, tokens["accent"] if selected else tokens["card_border"]),
            shadow=ft.BoxShadow(
                blur_radius=18 if selected else 10,
                spread_radius=1 if selected else 0,
                color=ft.Colors.with_opacity(0.24 if selected else 0.12, tokens["accent"] if selected else ft.Colors.BLACK),
                offset=ft.Offset(0, 6),
            ),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
                controls=[
                    ft.Icon(ft.Icons.FLIGHT, size=34, color=tokens["accent"]),
                    ft.Text(aircraft_name, size=11, weight=ft.FontWeight.W_800, color=tokens["text"], text_align=ft.TextAlign.CENTER, max_lines=1),
                    ft.Text(display_name, size=9, weight=ft.FontWeight.W_500, color=tokens["muted"], text_align=ft.TextAlign.CENTER, max_lines=2),
                ],
            ),
        )
        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e, name=aircraft_name: select_aircraft_from_picker(name),
            content=card,
        )

    def open_aircraft_picker(e=None):
        # Aircraft picker is intentionally not scroll-based.
        # It is grouped by manufacturer so the user can pick quickly.
        # If an airline is selected, show only aircraft in that airline fleet.
        # This lets special aircraft, such as Iran Air's B747-200, stay airline-specific.
        if state.airline and state.airline != "Generic" and state.airline in AIRLINE_FLEETS:
            fleet_keys = []
            for fleet_name in AIRLINE_FLEETS.get(state.airline, []):
                key = canonical_aircraft_name(fleet_name)
                if key and key in AIRCRAFT_LIBRARY and key not in fleet_keys:
                    fleet_keys.append(key)
            all_names = sorted(fleet_keys, key=aircraft_picker_sort_key) or sorted(all_library_aircraft_names(), key=aircraft_picker_sort_key)
        else:
            all_names = sorted(all_library_aircraft_names(), key=aircraft_picker_sort_key)
        airbus_names = [name for name in all_names if (AIRCRAFT_LIBRARY.get(name, {}).get("name", name)).lower().startswith("airbus")]
        boeing_names = [name for name in all_names if (AIRCRAFT_LIBRARY.get(name, {}).get("name", name)).lower().startswith("boeing")]

        def manufacturer_section(title: str, names: List[str]) -> ft.Control:
            return ft.Column(
                spacing=8,
                tight=True,
                controls=[
                    ft.Text(title, size=13, weight=ft.FontWeight.W_800, color=tokens["muted"]),
                    ft.Row(
                        spacing=14,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[build_aircraft_picker_card(name) for name in names],
                    ),
                ],
            )

        aircraft_picker_modal.content = ft.Container(
            height=460,
            width=float("inf"),
            padding=ft.padding.only(left=22, right=22, top=18, bottom=18),
            border_radius=ft.border_radius.only(top_left=28, top_right=28),
            bgcolor=surface_fill(tokens["panel"]),
            border=ft.border.all(1, tokens["card_border"]),
            shadow=ft.BoxShadow(
                blur_radius=28,
                spread_radius=2,
                color=ft.Colors.with_opacity(0.28, ft.Colors.BLACK),
                offset=ft.Offset(0, -8),
            ),
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text("Select Aircraft", size=16, weight=ft.FontWeight.W_800, color=tokens["text"]),
                            ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close", on_click=close_aircraft_picker, icon_color=tokens["text"]),
                        ],
                    ),
                    manufacturer_section("Airbus", airbus_names),
                    manufacturer_section("Boeing", boeing_names),
                ],
            ),
        )
        aircraft_picker_modal.visible = True
        page.update()

    def set_theme(is_dark: bool):
        new_mode = ft.ThemeMode.DARK if is_dark else ft.ThemeMode.LIGHT
        if page.theme_mode == new_mode:
            return
        page.theme_mode = new_mode
        refresh_ui()

    airline_dd.on_change = lambda e: set_airline(e.control.value)
    theme_toggle.on_change = lambda e: set_theme(e.control.value)


    def close_overview_globe_webview(wait: bool = False):
        process = getattr(state, "overview_globe_webview_process", None)
        if process is None:
            setattr(state, "overview_globe_webview_url", None)
            return
        setattr(state, "overview_globe_webview_process", None)
        setattr(state, "overview_globe_webview_url", None)

        def terminate_process():
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=1.5)
                    except Exception:
                        process.kill()
            except Exception:
                pass

        if wait:
            terminate_process()
        else:
            threading.Thread(target=terminate_process, daemon=True).start()


    async def show_application_window():
        if app_exit_requested:
            return
        page.window.skip_task_bar = False
        page.window.visible = True
        page.window.minimized = False
        page.window.focused = True
        page.update()
        try:
            await page.window.to_front()
        except Exception:
            pass

    async def exit_application():
        nonlocal app_exit_requested
        if app_exit_requested:
            return
        app_exit_requested = True
        close_overview_globe_webview(wait=True)
        close_dashboard_airport_map()
        close_live_map()
        if tray_icon is not None:
            try:
                tray_icon.stop()
            except Exception:
                pass
        page.window.prevent_close = False
        try:
            page.update()
        except Exception:
            pass
        try:
            await page.window.destroy()
        except Exception:
            try:
                await page.window.close()
            except Exception:
                pass

    def request_show_from_tray(_icon=None, _item=None):
        try:
            page.run_task(show_application_window)
        except Exception:
            pass

    def request_exit_from_tray(_icon=None, _item=None):
        try:
            page.run_task(exit_application)
        except Exception:
            pass

    async def on_window_event(e):
        nonlocal hidden_to_tray_notice_shown
        event_type = getattr(e, "type", None)
        if event_type not in (ft.WindowEventType.CLOSE, "close"):
            return
        if app_exit_requested:
            return
        page.window.visible = False
        page.window.skip_task_bar = True
        page.update()
        if tray_icon is not None and not hidden_to_tray_notice_shown:
            hidden_to_tray_notice_shown = True
            try:
                tray_icon.notify(
                    "FMS is still running. Use the tray icon to reopen or exit.",
                    "Flight Management Systems",
                )
            except Exception:
                pass

    def start_windows_tray() -> bool:
        nonlocal tray_icon
        if os.name != "nt" or pystray is None or PILImage is None or not runtime_icon.exists():
            return False
        try:
            with PILImage.open(runtime_icon) as source_icon:
                tray_image = source_icon.convert("RGBA").copy()
            tray_menu = pystray.Menu(
                pystray.MenuItem("Open Flight Management Systems", request_show_from_tray, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit Flight Management Systems", request_exit_from_tray),
            )
            tray_icon = pystray.Icon(
                "flight_management_systems",
                tray_image,
                "Flight Management Systems",
                tray_menu,
            )
            tray_icon.run_detached()
            return True
        except Exception as ex:
            tray_icon = None
            try:
                print(f"System tray unavailable: {ex}")
            except Exception:
                pass
            return False

    tray_enabled = not _INTERFACE_PREVIEW and start_windows_tray()
    page.window.prevent_close = tray_enabled
    if tray_enabled:
        page.window.on_event = on_window_event

    if os.name == "nt" and _FMS_SHOW_WINDOW_EVENT:
        def wait_for_show_requests():
            kernel32 = ctypes.windll.kernel32
            while not app_exit_requested:
                wait_result = kernel32.WaitForSingleObject(_FMS_SHOW_WINDOW_EVENT, 1000)
                if wait_result == 0 and not app_exit_requested:
                    try:
                        page.run_task(show_application_window)
                    except Exception:
                        pass

        threading.Thread(target=wait_for_show_requests, daemon=True, name="FMSShowWindowListener").start()

    def close_app(e):
        page.run_task(exit_application)

    def on_takeoff_aircraft_changed(e=None):
        # Phase 2.2: repaint MTOW immediately from the dropdown event value.
        raw_value = None
        if e is not None and getattr(e, "control", None) is not None:
            raw_value = getattr(e.control, "value", None)
        selected_aircraft = canonical_aircraft_name(raw_value or takeoff_aircraft_dd.value or state.aircraft)

        if not selected_aircraft:
            takeoff_mtow_value_text.value = "MTOW: —"
            takeoff_mtow_display_tf.value = "—"
            takeoff_status_text.value = "Select an aircraft to begin takeoff planning."
            takeoff_flap_dd.options = []
            takeoff_flap_dd.value = None
            page.update()
            return

        state.aircraft = selected_aircraft
        takeoff_aircraft_dd.value = selected_aircraft
        landing_aircraft_dd.value = selected_aircraft

        ac = resolve_takeoff_aircraft_config(selected_aircraft)
        flap_options = list(ac.flap_options or [])
        takeoff_flap_dd.options = [ft.dropdown.Option(key=flap, text=flap) for flap in flap_options]
        if flap_options and takeoff_flap_dd.value not in flap_options:
            takeoff_flap_dd.value = flap_options[0]
        elif not flap_options:
            takeoff_flap_dd.value = None

        takeoff_mtow_value_text.value = f"MTOW: {ac.mtow_kg:,.0f} kg"
        takeoff_mtow_display_tf.value = f"{ac.mtow_kg:,.0f}"
        takeoff_status_text.value = f"Selected {ac.name} • MTOW {ac.mtow_kg:,.0f} kg"

        update_landing_aircraft_details(update_page=False)
        refresh_takeoff_fuel_info(update_page=False)
        set_takeoff_fuel_defaults(update_page=False)
        state.flight_status = derive_idle_status()

        for ctrl in [
            takeoff_aircraft_dd,
            takeoff_flap_dd,
            takeoff_mtow_value_text,
            takeoff_status_text,
            takeoff_fuel_aircraft_text,
            landing_aircraft_display_text,
            landing_mlw_value_text,
            landing_flap_dd,
        ]:
            safe_update_control(ctrl)
        page.update()

    def on_takeoff_departure_changed(e=None):
        previous_airport = state.departure
        apply_takeoff_departure_state(update_page=False, fill_elevation=True)
        if state.departure != previous_airport:
            clear_dashboard_time_override()
            performance_metar_requests.pop("departure", None)
            takeoff_raw_metar_tf.value = ""
            takeoff_metar_status_text.value = ""
        sync_route_distance_from_state(update_page=False)
        refresh_takeoff_fuel_info(update_page=False)
        page.update()

    takeoff_aircraft_dd.on_change = on_takeoff_aircraft_changed
    takeoff_aircraft_dd.on_blur = on_takeoff_aircraft_changed
    # Do not update/uppercase on every key press. It can make the field lose focus.
    takeoff_gate_tf.on_change = lambda e: setattr(state, "departure_gate", (e.control.value or "").strip())
    takeoff_terminal_tf.on_change = lambda e: setattr(state, "departure_terminal", (e.control.value or "").strip())

    def active_route_distance_key() -> str:
        origin = (state.departure or takeoff_departure_icao_tf.value or "").strip().upper()
        destination = (state.arrival or landing_arrival_icao_tf.value or "").strip().upper()
        origin = normalize_airport_code(origin) or origin
        destination = normalize_airport_code(destination) or destination
        return f"{origin}->{destination}" if origin and destination else ""

    def format_route_distance_value(distance_nm: float) -> str:
        try:
            value = float(distance_nm)
        except Exception:
            return ""
        if abs(value - round(value)) < 0.05:
            return f"{value:.0f}"
        return f"{value:.1f}"

    def sync_route_distance_from_state(update_page: bool = False, overwrite_field: bool = True):
        origin = (takeoff_departure_icao_tf.value or state.departure or "").strip().upper()
        destination = (landing_arrival_icao_tf.value or state.arrival or "").strip().upper()
        if origin:
            state.departure = normalize_airport_code(origin) or origin
            takeoff_departure_icao_tf.value = state.departure
        if destination:
            state.arrival = normalize_airport_code(destination) or destination
            landing_arrival_icao_tf.value = state.arrival

        route_key = active_route_distance_key()
        route_nm = route_distance_nm(state.departure, state.arrival) if state.departure and state.arrival else None

        # If the route changed, remove the old manual override and auto-fill
        # the new calculated distance for the new city pair.
        override_key = getattr(state, "route_distance_override_key", "") or ""
        if override_key and override_key != route_key:
            state.route_distance_override_nm = None
            state.route_distance_override_key = ""

        override_nm = getattr(state, "route_distance_override_nm", None)
        has_valid_override = (
            isinstance(override_nm, (int, float))
            and float(override_nm) > 0
            and getattr(state, "route_distance_override_key", "") == route_key
        )

        if overwrite_field:
            if has_valid_override:
                takeoff_route_distance_tf.value = format_route_distance_value(float(override_nm))
            elif route_nm is not None:
                takeoff_route_distance_tf.value = format_route_distance_value(route_nm)
            else:
                takeoff_route_distance_tf.value = ""

        if update_page:
            page.update()
        return route_nm

    def apply_takeoff_route_distance_override(e=None):
        sync_route_distance_from_state(update_page=False, overwrite_field=False)
        raw = (takeoff_route_distance_tf.value or "").strip()
        route_key = active_route_distance_key()

        if not raw:
            if state.route_distance_override_nm is not None:
                clear_dashboard_time_override()
            state.route_distance_override_nm = None
            state.route_distance_override_key = ""
            sync_route_distance_from_state(update_page=False, overwrite_field=True)
            refresh_takeoff_fuel_info(update_page=False)
            takeoff_fuel_status_text.value = "Route distance reset to calculated value."
            page.update()
            return

        try:
            manual_nm = float(raw)
        except ValueError:
            takeoff_fuel_status_text.value = "Route distance must be a valid number."
            page.update()
            return

        if not math.isfinite(manual_nm) or manual_nm <= 0:
            takeoff_fuel_status_text.value = "Route distance must be greater than zero."
            page.update()
            return

        calculated_nm = route_distance_nm(state.departure, state.arrival) if route_key else None
        previous_nm = state.route_distance_override_nm if state.route_distance_override_key == route_key else calculated_nm
        if previous_nm is None or abs(manual_nm - previous_nm) >= 0.05:
            clear_dashboard_time_override()
        state.route_distance_override_nm = manual_nm
        state.route_distance_override_key = route_key
        takeoff_route_distance_tf.value = format_route_distance_value(manual_nm)
        refresh_takeoff_fuel_info(update_page=False)
        takeoff_fuel_status_text.value = f"Manual route distance set to {format_route_distance_value(manual_nm)} NM."
        page.update()

    takeoff_route_distance_tf.on_blur = apply_takeoff_route_distance_override
    takeoff_route_distance_tf.on_submit = apply_takeoff_route_distance_override

    def set_takeoff_fuel_defaults(update_page: bool = False):
        aircraft_name = canonical_aircraft_name(takeoff_aircraft_dd.value or state.aircraft)
        sync_route_distance_from_state(update_page=False)
        if not aircraft_name:
            takeoff_cruise_gs_tf.value = ""
            takeoff_taxi_fuel_tf.value = f"{FIXED_TAXI_FUEL_KG:.0f}"
            takeoff_contingency_tf.value = f"{DEFAULT_FUEL_SAFETY_MARGIN * 100:.0f}"
            takeoff_alternate_fuel_tf.value = ""
            takeoff_reserve_minutes_tf.value = ""
            takeoff_extra_fuel_tf.value = "0"
            refresh_takeoff_fuel_info(update_page=False)
            if update_page:
                page.update()
            return
        ac = resolve_takeoff_fuel_config(aircraft_name)
        takeoff_cruise_gs_tf.value = f"{ac.cruise_gs_kt_default:.0f}"
        takeoff_taxi_fuel_tf.value = f"{FIXED_TAXI_FUEL_KG:.0f}"
        takeoff_contingency_tf.value = f"{DEFAULT_FUEL_SAFETY_MARGIN * 100:.0f}"
        takeoff_alternate_fuel_tf.value = ""
        takeoff_reserve_minutes_tf.value = ""
        takeoff_extra_fuel_tf.value = "0"
        refresh_takeoff_fuel_info(update_page=False)
        if update_page:
            page.update()

    def refresh_takeoff_fuel_info(update_page: bool = False):
        minutes = fuel_plan_flight_minutes()
        takeoff_ete_text.value = f"Flight time: {format_hours_to_hm(minutes / 60)}" if minutes else "Flight time: —"
        aircraft_name = canonical_aircraft_name(takeoff_aircraft_dd.value or state.aircraft)
        route_origin = (state.departure or takeoff_departure_icao_tf.value or "").strip().upper()
        route_destination = (state.arrival or landing_arrival_icao_tf.value or "").strip().upper()
        route_label = f"{route_origin} → {route_destination}" if route_origin and route_destination else "Set departure and arrival"
        route_key = active_route_distance_key()
        override_nm = getattr(state, "route_distance_override_nm", None)
        has_valid_override = (
            isinstance(override_nm, (int, float))
            and float(override_nm) > 0
            and getattr(state, "route_distance_override_key", "") == route_key
        )
        distance_note = f" • Manual distance {format_route_distance_value(float(override_nm))} NM" if has_valid_override else ""
        takeoff_fuel_engine_text.value = f"Active route: {route_label}{distance_note}"
        takeoff_fuel_assumptions_text.value = (
            f"Model: route fuel from published range and fuel capacity • taxi {FIXED_TAXI_FUEL_KG:.0f} kg • passenger weight {STANDARD_PASSENGER_WEIGHT_KG:.0f} kg • Jet fuel density {JET_FUEL_DENSITY_KG_PER_L:.2f} kg/L • planning margin {DEFAULT_FUEL_SAFETY_MARGIN * 100:.0f}% • long-haul correction enabled"
        )
        if not aircraft_name:
            takeoff_fuel_aircraft_text.value = "Selected aircraft: Select an aircraft"
            if update_page:
                page.update()
            return
        takeoff_fuel_aircraft_text.value = f"Selected aircraft: {aircraft_name}"
        if update_page:
            page.update()

    populate_takeoff_aircraft_dropdown(state.airline, state.aircraft)
    reset_takeoff_form(update_page=False)
    refresh_takeoff_fuel_info(update_page=False)

    def format_fuel_value_kg(value_kg: float) -> str:
        if takeoff_fuel_units_dd.value == 'lb':
            return f"{value_kg * 2.20462:,.0f} lb"
        return f"{value_kg:,.0f} kg"

    def do_compute_fuel(e=None):
        # Preserve the value currently typed in the editable distance field.
        # Do not auto-overwrite it immediately before computing fuel.
        calculated_route_nm = sync_route_distance_from_state(update_page=False, overwrite_field=False)
        refresh_takeoff_fuel_info(update_page=False)

        aircraft_name = canonical_aircraft_name(takeoff_aircraft_dd.value or state.aircraft)
        if not aircraft_name:
            takeoff_fuel_status_text.value = 'Select an aircraft first.'
            page.update()
            return

        try:
            route_distance = float((takeoff_route_distance_tf.value or '0').strip() or 0.0)
            passengers = max(0, int(float((takeoff_fuel_passengers_tf.value or '0').strip() or 0)))
            baggage_kg = max(0.0, float((takeoff_fuel_baggage_tf.value or '0').strip() or 0.0))
            cargo_kg = max(0.0, float((takeoff_fuel_cargo_tf.value or '0').strip() or 0.0))
        except ValueError:
            takeoff_fuel_status_text.value = 'Route distance, passengers, baggage, and cargo must be valid numbers.'
            page.update()
            return

        route_key = active_route_distance_key()
        existing_override_for_route = getattr(state, "route_distance_override_key", "") == route_key
        if route_distance > 0:
            if existing_override_for_route or calculated_route_nm is None or abs(route_distance - float(calculated_route_nm)) > 0.5:
                state.route_distance_override_nm = route_distance
                state.route_distance_override_key = route_key
                takeoff_route_distance_tf.value = format_route_distance_value(route_distance)
            else:
                state.route_distance_override_nm = None
                state.route_distance_override_key = ""

        if not math.isfinite(route_distance) or route_distance <= 0:
            takeoff_fuel_status_text.value = 'Enter a route distance greater than zero.'
            takeoff_trip_fuel_text.value = 'Base trip fuel: —'
            takeoff_block_fuel_text.value = "— L  /  — kg"
            takeoff_fuel_limits_text.value = ""
            takeoff_ete_text.value = 'Flight time: —'
            takeoff_burn_rate_text.value = 'Actual payload: —'
            takeoff_fuel_breakdown_text.value = 'Phase split: —'
            takeoff_recommended_tow_text.value = 'Estimated TOW: —'
            page.update()
            return

        plan = compute_route_fuel_plan(
            aircraft_name=aircraft_name,
            distance_nm=route_distance,
            passengers=passengers,
            baggage_kg=baggage_kg,
            cargo_kg=cargo_kg,
        )
        if plan is None:
            takeoff_fuel_status_text.value = 'Fuel plan could not be computed. Check aircraft selection and route distance.'
            page.update()
            return

        lib = get_library_aircraft(aircraft_name) or {}
        oew_kg = float(lib.get('oew', 0.0) or 0.0)
        estimated_zfw_kg = oew_kg + plan.actual_payload_kg if oew_kg > 0 else 0.0
        estimated_tow_kg = estimated_zfw_kg + plan.planned_fuel_kg if estimated_zfw_kg > 0 else 0.0
        estimated_landing_weight_kg = 0.0
        if estimated_zfw_kg > 0:
            fuel_remaining_at_landing_kg = max(0.0, plan.planned_fuel_kg - plan.taxi_fuel_kg - plan.corrected_trip_fuel_kg)
            estimated_landing_weight_kg = estimated_zfw_kg + fuel_remaining_at_landing_kg
        mlw_kg = float(lib.get('mlw', 0.0) or 0.0)
        mtow_kg = float(lib.get('mtow', 0.0) or 0.0)

        ete_minutes = max(1, round(plan.ete_hours * 60))
        clear_dashboard_time_override()
        state.takeoff_last_result['fuel_plan'] = {
            'route_key': route_key,
            'aircraft': aircraft_name,
            'ete_minutes': ete_minutes,
            'trip_fuel_kg': round(plan.corrected_trip_fuel_kg, 1),
            'block_fuel_kg': round(plan.planned_fuel_kg, 1),
            'ete_hours': round(plan.ete_hours, 2),
            'actual_payload_kg': round(plan.actual_payload_kg, 1),
            'estimated_zfw_kg': round(estimated_zfw_kg, 1),
            'estimated_tow_kg': round(estimated_tow_kg, 1),
            'estimated_landing_weight_kg': round(estimated_landing_weight_kg, 1),
            'mlw_kg': round(mlw_kg, 1),
            'mtow_kg': round(mtow_kg, 1),
            'route_distance_nmi': round(plan.route_distance_nmi, 1),
        }
        start = state.overview_takeoff_start_timestamp
        if not state.overview_flight_time_minutes and state.overview_progress_running and isinstance(start, (int, float)):
            state.overview_locked_eta_timestamp = start + ete_minutes * 60

        if estimated_tow_kg > 0:
            takeoff_zfw_tf.value = f"{estimated_zfw_kg:.0f}"

        takeoff_trip_fuel_text.value = (
            f"Base trip fuel: {plan.base_trip_fuel_l:,.0f} L • {plan.base_trip_fuel_kg:,.0f} kg | "
            f"Corrected: {plan.corrected_trip_fuel_l:,.0f} L • {plan.corrected_trip_fuel_kg:,.0f} kg"
        )
        takeoff_block_fuel_text.value = f"{plan.planned_fuel_l:,.0f} L  /  {plan.planned_fuel_kg:,.0f} kg"
        takeoff_fuel_limits_text.value = (
            f"Margin: {plan.planning_margin_l:,.0f} L • {plan.planning_margin_kg:,.0f} kg | "
            f"Fuel capacity: {plan.fuel_capacity_l:,.0f} L • {plan.fuel_capacity_kg:,.0f} kg"
        )
        takeoff_ete_text.value = f"Flight time: {format_hours_to_hm(ete_minutes / 60)} • Effective distance {plan.effective_distance_nmi:,.0f} NM"
        takeoff_burn_rate_text.value = (
            f"Actual payload: {plan.actual_payload_kg:,.0f} kg | Payload factor {plan.payload_factor:.3f} | "
            f"Long-haul factor {plan.long_haul_efficiency_factor:.3f} | Burn coefficient {plan.burn_coefficient_l_per_nmi:,.2f} L/NM"
        )
        takeoff_fuel_breakdown_text.value = (
            f"Phase split: climb {plan.climb_fuel_l:,.0f} L • {plan.climb_fuel_kg:,.0f} kg | "
            f"cruise {plan.cruise_fuel_l:,.0f} L • {plan.cruise_fuel_kg:,.0f} kg | "
            f"descent {plan.descent_fuel_l:,.0f} L • {plan.descent_fuel_kg:,.0f} kg"
        )
        if estimated_tow_kg > 0:
            landing_part = f" | Estimated LW {estimated_landing_weight_kg:,.0f} kg" if estimated_landing_weight_kg > 0 else ""
            takeoff_recommended_tow_text.value = (
                f"Estimated TOW: {estimated_tow_kg:,.0f} kg | ZFW {estimated_zfw_kg:,.0f} kg{landing_part} | Taxi fuel fixed {FIXED_TAXI_FUEL_KG:,.0f} kg"
            )
        else:
            takeoff_recommended_tow_text.value = f"Taxi fuel fixed: {FIXED_TAXI_FUEL_KG:,.0f} kg | Planning margin {plan.safety_margin_percent:.0f}%"

        fuel_messages = []
        if getattr(state, "route_distance_override_key", "") == active_route_distance_key() and isinstance(getattr(state, "route_distance_override_nm", None), (int, float)):
            fuel_messages.append(f"Using manual route distance: {format_route_distance_value(float(state.route_distance_override_nm))} NM")
        if plan.exceeds_capacity:
            fuel_messages.append('WARNING: Planned fuel exceeds the selected aircraft fuel capacity.')
        else:
            fuel_messages.append(f"Fuel plan computed. Remaining fuel capacity margin: {plan.remaining_capacity_l:,.0f} L")
        if estimated_tow_kg > 0 and mtow_kg > 0:
            if estimated_tow_kg > mtow_kg:
                fuel_messages.append(f"WARNING: estimated TOW exceeds MTOW by {estimated_tow_kg - mtow_kg:,.0f} kg")
            elif estimated_tow_kg > mtow_kg * 0.97:
                fuel_messages.append("CAUTION: estimated TOW is close to MTOW")
        if estimated_landing_weight_kg > 0 and mlw_kg > 0:
            if estimated_landing_weight_kg > mlw_kg:
                fuel_messages.append(f"WARNING: estimated landing weight exceeds MLW by {estimated_landing_weight_kg - mlw_kg:,.0f} kg")
            elif estimated_landing_weight_kg > mlw_kg * 0.97:
                fuel_messages.append("CAUTION: estimated landing weight is close to MLW")
        takeoff_fuel_status_text.value = " • ".join(fuel_messages)
        page.update()

    def do_apply_fuel_to_tow(e=None):
        plan = (state.takeoff_last_result or {}).get('fuel_plan')
        if not plan:
            do_compute_fuel()
            plan = (state.takeoff_last_result or {}).get('fuel_plan')
        if not plan:
            return
        estimated_tow = float(plan.get('estimated_tow_kg', 0) or 0)
        if estimated_tow <= 0:
            takeoff_fuel_status_text.value = 'Fuel plan ready, but OEW is unavailable for automatic TOW application.'
            page.update()
            return
        takeoff_weight_tf.value = f"{estimated_tow:.0f}"
        takeoff_recommended_tow_text.value = f"Estimated TOW: {estimated_tow:,.0f} kg"
        takeoff_fuel_status_text.value = f"Applied estimated TOW: {estimated_tow:,.0f} kg"
        page.update()

    def do_calc_landing_vs(e=None):
        try:
            alt_to_lose = float((landing_vs_calc_alt_tf.value or '0').strip() or 0)
            ete_min = float((landing_vs_calc_ete_tf.value or '0').strip() or 0)
        except ValueError:
            landing_vs_calc_result_text.value = 'Required V/S: —'
            page.update()
            return
        if ete_min <= 0:
            landing_vs_calc_result_text.value = 'Required V/S: —'
        else:
            vs = int(round(alt_to_lose / ete_min))
            landing_vs_calc_result_text.value = f"Required V/S: -{vs:,} fpm"
        page.update()

    async def fetch_performance_metar(
        role, airport, status, raw, fetch_report, weather_fields, runway_heading, apply_airport,
    ):
        icao = normalize_airport_code(getattr(state, role))
        if not icao or not re.fullmatch(r"[A-Z0-9]{4}", icao) or role in performance_metar_requests:
            return

        tab_index = 4 if role == "departure" else 5
        request = object()
        performance_metar_requests[role] = request
        status.value = ""
        refresh_active_page()
        metar = await asyncio.to_thread(fetch_report, icao)

        if performance_metar_requests.get(role) is not request:
            return
        performance_metar_requests.pop(role)
        if normalize_airport_code(getattr(state, role)) != icao:
            return
        if not metar:
            status.value = f"No METAR received for {icao}. Try again."
        else:
            values = (
                f"{metar.temperature_c:.0f}", f"{metar.qnh_hpa:.1f}", str(metar.wind_dir_deg),
                str(metar.wind_speed_kt), str(metar.wind_gust_kt),
            )
            for field, value in zip(weather_fields, values):
                field.value = value
            if (runway_heading.value or "").strip() in ("", "0"):
                runway_heading.value = str(metar.wind_dir_deg)
            raw.value = metar.raw
            if metar.observation:
                airport_weather_cache[icao] = {"report": metar.observation, "timestamp": time.monotonic()}
            airport.value = icao
            apply_airport(update_page=False, fill_elevation=True)
            state.flight_status = "METAR updated" if role == "departure" else "Landing METAR updated"
        if state.selected_tab_index == tab_index:
            refresh_active_page()

    async def do_fetch_takeoff_metar(e):
        await fetch_performance_metar(
            "departure", takeoff_departure_icao_tf, takeoff_metar_status_text, takeoff_raw_metar_tf, fetch_takeoff_metar,
            (takeoff_oat_tf, takeoff_qnh_tf, takeoff_wind_dir_tf, takeoff_wind_speed_tf, takeoff_wind_gust_tf),
            takeoff_runway_heading_tf, apply_takeoff_departure_state,
        )

    def parse_optional_float(value: str) -> Optional[float]:
        value = (value or "").strip()
        if not value:
            return None
        return float(value)

    def do_compute_takeoff(e):
        aircraft_name = canonical_aircraft_name(takeoff_aircraft_dd.value or state.aircraft)
        if not aircraft_name:
            takeoff_status_text.value = "Select an aircraft before computing takeoff."
            page.update()
            return
        try:
            inputs = TakeoffInputs(
                aircraft_name=aircraft_name,
                takeoff_weight_kg=float((takeoff_weight_tf.value or "0").strip()),
                elevation_ft=float((takeoff_elevation_tf.value or "0").strip()),
                oat_c=float((takeoff_oat_tf.value or "0").strip()),
                qnh_hpa=float((takeoff_qnh_tf.value or "1013").strip()),
                wind_from_deg=int(float((takeoff_wind_dir_tf.value or "0").strip())),
                wind_speed_kt=float((takeoff_wind_speed_tf.value or "0").strip()),
                runway_heading_deg=int(float((takeoff_runway_heading_tf.value or "0").strip())),
                runway_slope_pct=float((takeoff_slope_tf.value or "0").strip()),
                surface_condition=takeoff_surface_dd.value or "DRY",
                flap_setting=takeoff_flap_dd.value or resolve_takeoff_aircraft_config(aircraft_name).flap_options[0],
                wind_gust_kt=float((takeoff_wind_gust_tf.value or "0").strip()),
                tora_m=parse_optional_float(takeoff_tora_tf.value or ""),
                toda_m=parse_optional_float(takeoff_toda_tf.value or ""),
                asda_m=parse_optional_float(takeoff_asda_tf.value or ""),
            )
        except Exception:
            takeoff_status_text.value = "Check your numeric takeoff inputs."
            page.update()
            return

        if inputs.takeoff_weight_kg <= 0:
            takeoff_status_text.value = "Takeoff weight must be greater than zero."
            page.update()
            return

        apply_takeoff_departure_state(update_page=False, fill_elevation=False)
        state.departure_gate = (takeoff_gate_tf.value or "").strip()
        state.aircraft = inputs.aircraft_name
        sync_aircraft_across_pages(inputs.aircraft_name, update_page=False)

        result = compute_takeoff_performance(inputs)
        state.takeoff_last_result.update({
            "weight_kg": inputs.takeoff_weight_kg,
            "vr_kt": result.vr_kt,
            "v2_kt": result.v2_kt,
            "takeoff_distance_m": result.takeoff_distance_m,
        })
        state.flight_status = "Takeoff computed"

        takeoff_mtow_value_text.value = f"MTOW: {result.mtow_kg:,.0f} kg"
        takeoff_isa_temp_text.value = f"ISA temp: {result.isa_temperature_c:.1f} °C"
        takeoff_pressure_alt_text.value = f"Pressure altitude: {result.pressure_altitude_ft:,} ft"
        takeoff_density_alt_text.value = f"Density altitude: {result.density_altitude_ft:,} ft"
        takeoff_isa_dev_text.value = f"ISA deviation: {result.isa_deviation_c:+.1f} °C  •  σ {result.sigma:.3f}"
        takeoff_headwind_text.value = f"Headwind component: {result.headwind_kt:+d} kt  •  Gust component: {result.headwind_gust_kt:+d} kt"
        takeoff_crosswind_text.value = f"Crosswind component: {result.crosswind_kt} kt"

        takeoff_vs_text.value = f"Vs: {result.vs_kt} kt"
        takeoff_v1_text.value = f"V1: {result.v1_kt} kt"
        takeoff_vr_text.value = f"VR: {result.vr_kt} kt"
        takeoff_v2_text.value = f"V2: {result.v2_kt} kt"

        takeoff_asd_text.value = f"Accelerate-stop distance: {result.accelerate_stop_m:,} m"
        takeoff_agd_text.value = f"Accelerate-go distance: {result.accelerate_go_m:,} m"
        takeoff_tod_text.value = f"Takeoff distance: {result.takeoff_distance_m:,} m"
        if result.runway_margins_m:
            margin_parts = [f"{name}: {value:+,} m" for name, value in result.runway_margins_m.items()]
            takeoff_margin_text.value = "Runway margins: " + "  •  ".join(margin_parts)
        else:
            takeoff_margin_text.value = "Runway margins: no TORA/TODA/ASDA entered"
        takeoff_climb_initial_text.value = f"Initial: {result.climb_initial_fpm:,}"
        takeoff_climb_enroute_text.value = f"Enroute: {result.climb_enroute_fpm:,}"
        takeoff_climb_high_text.value = f"High altitude: {result.climb_high_alt_fpm:,}"

        render_takeoff_warnings(result)
        takeoff_status_text.value = f"Computed for {inputs.aircraft_name} from {state.departure}."
        page.update()

    def do_reset_takeoff(e):
        reset_takeoff_form(update_page=True)

    def do_save_takeoff_log(e):
        origin = (takeoff_departure_icao_tf.value or state.departure or "").strip().upper()
        destination = (state.arrival or landing_arrival_icao_tf.value or "TBD").strip().upper() or "TBD"
        aircraft_name = canonical_aircraft_name(takeoff_aircraft_dd.value or state.aircraft) or "Aircraft"
        if not origin:
            takeoff_status_text.value = "Set a departure ICAO before saving to log."
            page.update()
            return
        notes = []
        if state.takeoff_last_result:
            notes.append(f"TO data: VR {state.takeoff_last_result.get('vr_kt', '—')} kt")
            notes.append(f"Takeoff distance {state.takeoff_last_result.get('takeoff_distance_m', '—')} m")
            fuel_plan = state.takeoff_last_result.get('fuel_plan')
            if fuel_plan:
                notes.append(f"Block fuel {int(round(fuel_plan.get('block_fuel_kg', 0))):,} kg")
                notes.append(f"ETE {fuel_plan.get('ete_hours', 0):.2f} h")
        if takeoff_raw_metar_tf.value:
            notes.append(f"METAR: {takeoff_raw_metar_tf.value}")
        entry = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
            "airline": state.airline,
            "aircraft": aircraft_name,
            "origin": origin,
            "destination": destination,
            "aviation_records": active_flight_records(origin, destination),
            "route": f"{origin} → {destination}",
            "flight_time": "—",
            "notes": " | ".join(notes) if notes else "Takeoff planning saved from Takeoff tab.",
            "completed": False,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        state.calendar_entries.append(entry)
        sort_calendar_entries_default()
        save_calendar_entries()
        takeoff_status_text.value = "Takeoff entry saved to the flight planner."
        show_snack("Saved to Calendar and Flight Planner.")
        page.update()


    def on_landing_aircraft_changed(e=None):
        selected_aircraft = canonical_aircraft_name(landing_aircraft_dd.value or state.aircraft)
        sync_aircraft_across_pages(selected_aircraft, update_page=False)
        page.update()
    def on_landing_arrival_changed(e=None):
        previous_airport = state.arrival
        apply_landing_arrival_state(update_page=False, fill_elevation=True)
        if state.arrival != previous_airport:
            clear_dashboard_time_override()
            performance_metar_requests.pop("arrival", None)
            landing_raw_metar_tf.value = ""
            landing_metar_status_text.value = ""
        sync_route_distance_from_state(update_page=False)
        refresh_takeoff_fuel_info(update_page=False)
        page.update()

    landing_aircraft_dd.on_change = on_landing_aircraft_changed
    # Do not update/uppercase on every key press. It can make the field lose focus.
    landing_gate_tf.on_change = lambda e: setattr(state, "arrival_gate", (e.control.value or "").strip())
    landing_terminal_tf.on_change = lambda e: setattr(state, "arrival_terminal", (e.control.value or "").strip())
    populate_landing_aircraft_dropdown(state.airline, state.aircraft)
    reset_landing_form(update_page=False)

    async def do_fetch_landing_metar(e):
        await fetch_performance_metar(
            "arrival", landing_arrival_icao_tf, landing_metar_status_text, landing_raw_metar_tf, fetch_landing_metar,
            (landing_oat_tf, landing_qnh_tf, landing_wind_dir_tf, landing_wind_speed_tf, landing_wind_gust_tf),
            landing_runway_heading_tf, apply_landing_arrival_state,
        )

    def do_compute_landing(e):
        aircraft_name = canonical_aircraft_name(state.aircraft or landing_aircraft_dd.value)
        if not aircraft_name:
            landing_status_text.value = "Select an aircraft in Takeoff before computing landing."
            page.update()
            return
        try:
            inputs = LandingInputs(
                aircraft_name=aircraft_name,
                landing_weight_kg=float((landing_weight_tf.value or "0").strip()),
                elevation_ft=float((landing_elevation_tf.value or "0").strip()),
                oat_c=float((landing_oat_tf.value or "0").strip()),
                qnh_hpa=float((landing_qnh_tf.value or "1013").strip()),
                wind_from_deg=int(float((landing_wind_dir_tf.value or "0").strip())),
                wind_speed_kt=float((landing_wind_speed_tf.value or "0").strip()),
                runway_heading_deg=int(float((landing_runway_heading_tf.value or "0").strip())),
                surface_condition=landing_surface_dd.value or "DRY",
                flap_setting=landing_flap_dd.value or resolve_landing_aircraft_config(aircraft_name).flap_options[0],
                autobrake_mode=landing_autobrake_dd.value or "MED",
                reverse_enabled=bool(landing_reverse_sw.value),
                wind_gust_kt=float((landing_wind_gust_tf.value or "0").strip()),
                lda_m=parse_optional_float(landing_lda_tf.value or ""),
                obstacle_height_ft=float((landing_obstacle_tf.value or "50").strip()),
                current_altitude_ft=parse_optional_float(landing_current_alt_tf.value or ""),
                distance_to_go_nm=parse_optional_float(landing_distance_to_go_tf.value or ""),
                planned_ground_speed_kt=parse_optional_float(landing_ground_speed_tf.value or ""),
            )
        except Exception:
            landing_status_text.value = "Check your numeric landing inputs."
            page.update()
            return

        if inputs.landing_weight_kg <= 0:
            landing_status_text.value = "Landing weight must be greater than zero."
            page.update()
            return

        apply_landing_arrival_state(update_page=False, fill_elevation=False)
        state.arrival_gate = (landing_gate_tf.value or "").strip()
        state.aircraft = inputs.aircraft_name

        result = compute_landing_performance(inputs)
        state.landing_last_result = {
            "weight_kg": inputs.landing_weight_kg,
            "vapp_kt": result.vapp_kt,
            "landing_distance_m": result.landing_distance_m,
            "tod_distance_nm": result.tod_distance_nm,
        }
        state.flight_status = "Landing computed"

        landing_mlw_value_text.value = f"MLW: {result.mlw_kg:,.0f} kg"
        landing_pressure_alt_text.value = f"Pressure altitude: {result.pressure_altitude_ft:,} ft"
        landing_density_alt_text.value = f"Density altitude: {result.density_altitude_ft:,} ft"
        landing_headwind_text.value = f"Headwind component: {result.headwind_kt:+d} kt  •  Gust component: {result.headwind_gust_kt:+d} kt"
        landing_crosswind_text.value = f"Crosswind component: {result.crosswind_kt} kt  •  ISA {result.isa_deviation_c:+.1f} °C"

        landing_vs_text.value = f"Vs landing: {result.vs_landing_kt} kt"
        landing_vref_text.value = f"Vref: {result.vref_kt} kt"
        landing_vapp_text.value = f"Vapp: {result.vapp_kt} kt"
        landing_additive_text.value = f"Additive +{result.additive_kt} kt"
        landing_additive_text.visible = True
        landing_weight_ratio_text.value = f"Weight ratio to MLW: {result.weight_ratio:.3f}"

        landing_altitude_to_lose_text.value = f"Altitude to lose: {result.altitude_to_lose_ft:,} ft"
        landing_tod_text.value = f"TOD distance: {result.tod_distance_nm:.1f} NM  •  Distance to go: {result.distance_to_go_nm:.1f} NM"
        landing_descent_rate_text.value = f"Suggested descent rate: {result.suggested_vs_fpm:,} fpm"
        landing_descent_time_text.value = f"Estimated descent time: {result.estimated_descent_time_min:.1f} min"
        landing_profile_text.value = f"Profile status: {result.profile_status}"

        landing_distance_text.value = f"Estimated landing distance: {result.landing_distance_m:,} m"
        landing_braking_text.value = f"Braking adjustments: {result.braking_summary}"
        if result.lda_margin_m is None:
            landing_margin_text.value = "LDA margin: no LDA entered"
        else:
            landing_margin_text.value = f"LDA margin: {result.lda_margin_m:+,} m"

        render_landing_warnings(result)
        landing_status_text.value = f"Computed for {inputs.aircraft_name} into {state.arrival}."
        page.update()

    def do_reset_landing(e):
        reset_landing_form(update_page=True)

    def do_save_landing_log(e):
        origin = (state.departure or "TBD").strip().upper() or "TBD"
        destination = (landing_arrival_icao_tf.value or state.arrival or "").strip().upper()
        aircraft_name = canonical_aircraft_name(state.aircraft or landing_aircraft_dd.value) or "Aircraft"
        if not destination:
            landing_status_text.value = "Set an arrival ICAO before saving to log."
            page.update()
            return
        notes = []
        if state.landing_last_result:
            notes.append(f"LDG data: VAPP {state.landing_last_result.get('vapp_kt', '—')} kt")
            notes.append(f"Landing distance {state.landing_last_result.get('landing_distance_m', '—')} m")
            if state.landing_last_result.get('tod_distance_nm') not in (None, '—'):
                notes.append(f"TOD {state.landing_last_result.get('tod_distance_nm')} NM")
        if landing_raw_metar_tf.value:
            notes.append(f"METAR: {landing_raw_metar_tf.value}")
        entry = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
            "airline": state.airline,
            "aircraft": aircraft_name,
            "origin": origin,
            "destination": destination,
            "aviation_records": active_flight_records(origin, destination),
            "route": f"{origin} → {destination}",
            "flight_time": f"{state.landing_last_result.get('tod_distance_nm', '—')} NM to go" if state.landing_last_result else "—",
            "notes": " | ".join(notes) if notes else "Landing planning saved from Landing tab.",
            "completed": False,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        state.calendar_entries.append(entry)
        sort_calendar_entries_default()
        save_calendar_entries()
        landing_status_text.value = "Landing entry saved to the flight planner."
        show_snack("Saved to Calendar and Flight Planner.")
        page.update()


    def do_baggage_calc(e):
        try:
            passengers = max(0, int((bag_pax_tf.value or "0").strip()))
        except Exception:
            set_baggage_status("Passenger count must be a whole number.", error=True)
            page.update()
            return

        try:
            carry_on_kg = float((bag_carry_on_tf.value or "0").strip())
            if carry_on_kg < 0:
                raise ValueError
        except Exception:
            set_baggage_status("Carry-on mass per passenger must be a valid number.", error=True)
            page.update()
            return

        try:
            cargo_kg = float((cargo_weight_tf.value or "0").strip())
            if cargo_kg < 0:
                raise ValueError
        except Exception:
            set_baggage_status("Cargo weight must be a valid number.", error=True)
            page.update()
            return

        mode = "Standard"

        if mode == "Standard":
            category = "Custom baggage estimate"
            try:
                checked_kg_per_pax = float((bag_checked_kg_per_pax_tf.value or "0").strip())
                if checked_kg_per_pax < 0:
                    raise ValueError
            except Exception:
                set_baggage_status("Checked baggage kg per passenger must be a valid number.", error=True)
                page.update()
                return

            result = estimate_standard_mode(
                passengers=passengers,
                carry_on_kg_per_pax=carry_on_kg,
                checked_kg_per_pax=checked_kg_per_pax,
            )

            bag_total_weight_text.value = f"TOTAL baggage: {result.total_baggage_kg:,.1f} kg"
            bag_mode_result_text.value = "Mode: STANDARD (avg kg per passenger)"
            bag_passengers_result_text.value = f"Passengers: {result.passengers}"
            bag_carry_on_result_text.value = f"Carry-on total: {result.carry_on_total_kg:,.1f} kg"
            bag_checked_result_text.value = f"Checked baggage total: {result.checked_total_kg:,.1f} kg"
            bag_checked_bags_result_text.value = "Total checked bags: not used in Standard mode"
            bag_split_result_text.value = "Bag split: not used in Standard mode"
            total_payload_kg = result.total_baggage_kg + cargo_kg
            bag_baggage_weight_summary_text.value = f"Baggage weight: {result.total_baggage_kg:,.1f} kg"
            bag_cargo_weight_summary_text.value = f"Cargo weight: {cargo_kg:,.1f} kg"
            bag_payload_weight_summary_text.value = f"Total payload: {total_payload_kg:,.1f} kg"

            bag_assumption_1.value = f"Passenger count: {passengers}"
            bag_assumption_2.value = f"Carry-on per passenger: {carry_on_kg:,.1f} kg"
            bag_assumption_3.value = f"Checked baggage per passenger: {checked_kg_per_pax:,.1f} kg"
            bag_assumption_4.value = f"Category default checked baggage: {default_checked_baggage_for_category(category):,.1f} kg"
            set_baggage_status("Baggage and cargo payload calculated.")
        else:
            try:
                pct_two = float((bag_two_bag_percent_tf.value or "0").strip())
                if pct_two < 0 or pct_two > 100:
                    raise ValueError
            except Exception:
                set_baggage_status("Passengers with 2 checked bags must be a number from 0 to 100.", error=True)
                page.update()
                return

            try:
                per_bag_kg = float((bag_per_bag_kg_tf.value or "0").strip())
                if per_bag_kg < 0:
                    raise ValueError
            except Exception:
                set_baggage_status("Mass per checked bag must be a valid number.", error=True)
                page.update()
                return

            result = estimate_allowance_mode(
                passengers=passengers,
                pct_two_checked_bags=pct_two,
                carry_on_kg_per_pax=carry_on_kg,
                per_checked_bag_kg=per_bag_kg,
            )

            bag_total_weight_text.value = f"TOTAL baggage: {result.total_baggage_kg:,.1f} kg"
            bag_mode_result_text.value = "Mode: ALLOWANCE (bag count × kg)"
            bag_passengers_result_text.value = f"Passengers: {result.passengers}"
            bag_carry_on_result_text.value = f"Carry-on total: {result.carry_on_total_kg:,.1f} kg"
            bag_checked_result_text.value = f"Checked baggage total: {result.checked_total_kg:,.1f} kg"
            bag_checked_bags_result_text.value = f"Total checked bags: {result.total_checked_bags}"
            bag_split_result_text.value = f"Bag split: {result.pax_two_bags} passengers with 2 bags, {result.pax_one_bag} passengers with 1 bag"

            bag_assumption_1.value = f"Carry-on per passenger: {carry_on_kg:,.1f} kg"
            bag_assumption_2.value = f"Passengers with 2 checked bags: {pct_two:,.1f}%"
            bag_assumption_3.value = f"Mass per checked bag: {per_bag_kg:,.1f} kg"
            bag_assumption_4.value = "Each remaining passenger is counted with 1 checked bag."
            set_baggage_status("Calculated in Allowance mode.")

        # Push only the calculated baggage total into Fuel Planning. The fuel
        # field remains a normal editable TextField for operational overrides.
        takeoff_fuel_baggage_tf.value = f"{result.total_baggage_kg:.1f}".rstrip("0").rstrip(".")
        page.update()

    def reset_baggage_form(e):
        bag_mode_dd.value = "Standard"
        if not seat_model.get("generated"):
            bag_pax_tf.value = "0"
        bag_carry_on_tf.value = "0"
        bag_category_dd.value = "Within the European region"
        apply_baggage_category_default()
        cargo_weight_tf.value = "0"
        bag_two_bag_percent_tf.value = "0"
        bag_per_bag_kg_tf.value = "0"
        refresh_baggage_mode_ui(update_page=False)
        reset_baggage_result_display()
        set_baggage_status("Enter values and click Calculate.")
        page.update()

    def add_or_update_calendar_entry(e):
        date_str = (cal_date_tf.value or "").strip()
        time_str = (cal_time_tf.value or "").strip()
        airline_name = cal_airline_dd.value or ""
        aircraft_name = cal_aircraft_dd.value or ""
        origin = (cal_origin_tf.value or "").strip().upper()
        destination = (cal_destination_tf.value or "").strip().upper()
        flight_time = (cal_flight_time_tf.value or "").strip()
        notes = (cal_notes_tf.value or "").strip()
        existing_entry = next(
            (item for item in state.calendar_entries if item.get("id") == state.calendar_editing_id),
            None,
        )
        completed = bool(existing_entry.get("completed", False)) if existing_entry else False

        if not date_str or not airline_name or not aircraft_name or not origin or not destination or not flight_time:
            cal_form_message.value = "Select an airline, aircraft, departure, and arrival. Enter the date and flight time."
            page.update()
            return

        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            cal_form_message.value = "Date must be in YYYY-MM-DD format."
            page.update()
            return

        if time_str:
            try:
                datetime.strptime(time_str, "%H:%M")
            except ValueError:
                cal_form_message.value = "Time must be in HH:MM format."
                page.update()
                return

        route_label = f"{origin} → {destination}"
        entry = dict(existing_entry or {})
        entry.update({
            "id": state.calendar_editing_id or datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "date": date_str,
            "time": time_str,
            "airline": airline_name,
            "aircraft": aircraft_name,
            "origin": origin,
            "destination": destination,
            "route": route_label,
            "aviation_records": {
                **planner_records,
                **{key: record for key, code in (("origin", origin), ("destination", destination))
                   if (record := lookup_airport_record(code))},
            },
            "flight_time": flight_time,
            "notes": notes,
            "completed": completed,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })

        if state.calendar_editing_id:
            for idx, item in enumerate(state.calendar_entries):
                if item.get("id") == state.calendar_editing_id:
                    state.calendar_entries[idx] = entry
                    break
            cal_form_message.value = "Flight updated."
        else:
            state.calendar_entries.append(entry)
            cal_form_message.value = "Flight added."

        state.calendar_entries.sort(key=lambda x: (x.get("date", ""), x.get("time", ""), x.get("airline", "")))
        sync_profile_from_calendar_completion()
        save_calendar_entries()
        if state.calendar_editing_id:
            # After updating, automatically deselect the highlighted calendar date.
            # Keep the edited flight loaded in the planner so another correction is still easy.
            state.calendar_selected_date = ""
            cal_form_message.value = f"Updated and still editing: {route_label}"
            refresh_calendar_route_preview()
        else:
            reset_calendar_form()
        refresh_active_page()

    def load_calendar_entry_for_edit(entry_id: str):
        entry = next((item for item in state.calendar_entries if item.get("id") == entry_id), None)
        if not entry:
            return
        state.calendar_editing_id = entry_id
        cal_date_tf.value = entry.get("date", "")
        cal_time_tf.value = entry.get("time", "")
        cal_airline_dd.value = entry.get("airline", "")
        cal_aircraft_dd.value = entry.get("aircraft", "")
        planner_records.clear()
        planner_records.update(entry.get("aviation_records") or {})
        cal_origin_tf.value = entry.get("origin", "")
        cal_destination_tf.value = entry.get("destination", "")
        cal_flight_time_tf.value = entry.get("flight_time", "")
        cal_notes_tf.value = entry.get("notes", "")
        entry_date_value = entry.get("date", "") or datetime.now().strftime("%Y-%m-%d")
        state.calendar_selected_date = entry_date_value
        state.calendar_display_year = int(entry_date_value[:4])
        state.calendar_display_month = int(entry_date_value[5:7])
        cal_form_message.value = f"Editing flight: {entry.get('route', '')}"
        refresh_calendar_route_preview()
        refresh_active_page()

    def delete_calendar_entry(entry_id: str):
        for item in state.calendar_entries:
            if item.get("id") == entry_id and bool(item.get("profile_accounted")):
                minutes = int(item.get("profile_accounted_minutes") or parse_flight_time_minutes(item.get("flight_time", "")) or 0)
                state.profile_total_flight_minutes = max(0, int(getattr(state, "profile_total_flight_minutes", 0) or 0) - minutes)
                state.profile_online_flights = max(0, int(getattr(state, "profile_online_flights", 0) or 0) - 1)
                state.profile_total_landings = max(0, int(getattr(state, "profile_total_landings", 0) or 0) - 1)
                save_profile_data()
                break
        state.calendar_entries = [item for item in state.calendar_entries if item.get("id") != entry_id]
        if state.calendar_editing_id == entry_id:
            reset_calendar_form()
        save_calendar_entries()
        refresh_active_page()

    def complete_calendar_entry(entry_id: str):
        if not mark_calendar_entry_completed(state.calendar_entries, entry_id):
            return
        sync_profile_from_calendar_completion()
        save_calendar_entries()
        refresh_active_page()
        show_snack("Flight marked completed.")

    def clear_calendar_form(e):
        reset_calendar_form()
        page.update()

    def go_to_tab(index: int):
        new_index = max(0, min(13, int(index)))
        if new_index == 6:
            new_index = 0
        if new_index == 12:
            state.selected_tab_index = 0
            change_overview_mode(True)
            return
        if state.selected_tab_index == new_index:
            return
        if state.selected_tab_index == 0 and new_index != 0:
            close_overview_globe_webview()
        state.selected_tab_index = new_index
        refresh_ui()

    def open_takeoff_fuel_section(e=None):
        state.selected_tab_index = 4
        refresh_ui()
        show_snack("Takeoff tab opened. Scroll to Fuel Planning.")



    def build_globe_route_url(view_mode: str = "full") -> Optional[str]:
        web_map_index = base_dir / "globe-gl-test-web" / "dist" / "index.html"
        if not web_map_index.exists():
            return None

        origin_icao = (state.departure or takeoff_departure_icao_tf.value or "").strip().upper()
        destination_icao = (state.arrival or landing_arrival_icao_tf.value or "").strip().upper()
        origin_icao = normalize_airport_code(origin_icao) or origin_icao
        destination_icao = normalize_airport_code(destination_icao) or destination_icao
        origin_coord = resolve_airport_coordinates(origin_icao)
        destination_coord = resolve_airport_coordinates(destination_icao)
        route_nm_value = route_distance_nm(origin_icao, destination_icao)

        def estimate_globe_flight_time_hours(distance_nm_value: Optional[float]) -> Optional[float]:
            if not distance_nm_value:
                return None
            fuel_plan = state.takeoff_last_result.get("fuel_plan", {}) if state.takeoff_last_result else {}
            ete_from_plan = fuel_plan.get("ete_hours") if isinstance(fuel_plan, dict) else None
            if isinstance(ete_from_plan, (int, float)) and ete_from_plan > 0:
                return float(ete_from_plan)
            try:
                cruise_gs = float((takeoff_cruise_gs_tf.value or "").strip())
            except Exception:
                cruise_gs = 0.0
            if cruise_gs <= 0:
                cruise_gs = resolve_takeoff_fuel_config(takeoff_aircraft_dd.value or state.aircraft).cruise_gs_kt_default
            return (distance_nm_value / cruise_gs) if cruise_gs > 0 else None

        flight_time_hours = estimate_globe_flight_time_hours(route_nm_value)
        flight_time_label = format_hours_to_hm(flight_time_hours) if flight_time_hours is not None else ""
        params: Dict[str, object] = {
            "route_ready": "1" if origin_coord and destination_coord else "0",
            "view": view_mode,
            "mini": "1" if str(view_mode).lower() == "mini" else "0",
            "airline": state.airline or "Airline not selected",
            "aircraft": state.aircraft or takeoff_aircraft_dd.value or "Aircraft not selected",
            "flight_time": flight_time_label,
        }
        if origin_coord and destination_coord:
            origin_record = AIRPORT_LIBRARY.get(origin_icao, {})
            destination_record = AIRPORT_LIBRARY.get(destination_icao, {})
            params.update(
                {
                    "dep_code": origin_icao,
                    "dep_name": origin_record.get("name", origin_icao),
                    "dep_lng": origin_coord[1],
                    "dep_lat": origin_coord[0],
                    "arr_code": destination_icao,
                    "arr_name": destination_record.get("name", destination_icao),
                    "arr_lng": destination_coord[1],
                    "arr_lat": destination_coord[0],
                }
            )
        query = urllib.parse.urlencode(params)
        return f"{web_map_index.as_uri()}#{query}" if query else web_map_index.as_uri()


    def overview_page():
        nonlocal overview_progress_refresh_callback, ramp_status_refresh_callback, live_render_callback
        if not live_map_process:
            live_render_callback = None
        overview_daylight_mode = use_daylight_cards()
        overview_route_scale = 1.00
        overview_card_height = 440
        overview_ramp_width = 430
        airport_card_width = 196
        bottom_card_height = 100
        metrics_width = 332
        overview_glass_fill = ft.Colors.with_opacity(0.20, tokens["panel"])
        overview_glass_border = tokens["card_border"]
        # Satellite tiles can be bright or dark in either display mode.
        overview_text_color = DARK["text"]
        overview_text_style = ft.TextStyle(shadow=[
            ft.BoxShadow(color="#101820", blur_radius=2),
            ft.BoxShadow(color="#101820", blur_radius=4, offset=ft.Offset(0, 1)),
        ])
        overview_airport_marker_size = 126
        overview_progress_height = 58
        overview_route_aircraft_marker = None
        overview_route_aircraft_points: List[tuple[float, float]] = []

        def route_scaled(value: float, minimum: int = 1) -> int:
            return max(minimum, int(round(value * overview_route_scale)))

        def overview_glass_panel(
            content: ft.Control,
            width: Optional[int] = None,
            height: Optional[int] = None,
            expand: bool = False,
            padding: int = 14,
            radius: int = CARD_RADIUS,
        ) -> ft.Control:
            return ft.Container(
                width=width,
                height=height,
                expand=expand,
                padding=padding,
                border_radius=radius,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                bgcolor=overview_glass_fill,
                blur=ft.Blur(8, 8, ft.BlurTileMode.CLAMP),
                border=ft.border.all(1, overview_glass_border),
                shadow=surface_shadow(0.72),
                content=content,
            )

        ramp_status_card_host.width = overview_ramp_width
        ramp_status_card_host.height = overview_card_height
        origin_icao = (state.departure or takeoff_departure_icao_tf.value or "").strip().upper()
        destination_icao = (state.arrival or landing_arrival_icao_tf.value or "").strip().upper()
        origin_icao = normalize_airport_code(origin_icao) or origin_icao
        destination_icao = normalize_airport_code(destination_icao) or destination_icao
        has_complete_route = bool(origin_icao and destination_icao)
        if origin_icao:
            state.departure = origin_icao
        if destination_icao:
            state.arrival = destination_icao

        origin_coord = resolve_airport_coordinates(origin_icao)
        destination_coord = resolve_airport_coordinates(destination_icao)
        calculated_route_nm = route_distance_nm(origin_icao, destination_icao) if origin_icao and destination_icao else None
        overview_route_key = f"{origin_icao}->{destination_icao}" if origin_icao and destination_icao else ""
        override_nm = getattr(state, "route_distance_override_nm", None)
        override_active = (
            isinstance(override_nm, (int, float))
            and float(override_nm) > 0
            and getattr(state, "route_distance_override_key", "") == overview_route_key
        )
        route_nm = float(override_nm) if override_active else calculated_route_nm
        distance_label = f"{route_nm:.0f} NM" if route_nm else "—"
        flight_phase = "Cruise monitor ready" if route_nm else "Awaiting route setup"

        fuel_plan = state.takeoff_last_result.get("fuel_plan") or {}
        planned_fuel = fuel_plan.get("planned_fuel_kg") or fuel_plan.get("block_fuel_kg")
        trip_fuel = fuel_plan.get("corrected_trip_fuel_kg") or fuel_plan.get("trip_fuel_kg")
        planned_fuel_label = f"{planned_fuel/1000:.1f} t" if isinstance(planned_fuel, (int, float)) else "—"
        fuel_burn_label = f"{trip_fuel/1000:.1f} t trip" if isinstance(trip_fuel, (int, float)) else "—"

        def overview_metric(label: str, value: str, subtitle: str = "") -> ft.Control:
            return ft.Container(
                width=190,
                height=110,
                padding=12,
                border_radius=18,
                bgcolor=surface_fill(tokens["subpanel"]),
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    spacing=4,
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.Text(label, size=11, color=tokens["muted"]),
                        ft.Text(value, size=20, weight=ft.FontWeight.W_800, color=tokens["text"]),
                        ft.Text(subtitle, size=10, color=tokens["muted"]),
                    ],
                ),
            )

        def point_card(title: str, code: str, target_tab_index: Optional[int] = None, *, live=False) -> ft.Control:
            record = live_airport_record(code) if live else lookup_airport_record(code)
            airport_name = (record or {}).get("name") or ("Airport name unavailable" if code else "Airport not selected")
            weather = airport_weather_for_card(code) if not live else {}
            is_departure = title == "Departure"
            terminal = (state.departure_terminal if is_departure else state.arrival_terminal) or "—"
            gate = (state.departure_gate if is_departure else state.arrival_gate) or "—"
            color, foreground = ("#FFE54D", "#211D0A") if is_departure else ("#7263E8", "#FFFFFF")
            weather_label = f"{weather.get('temperature', '—')}  ·  {weather.get('condition', 'Weather unavailable')}"
            stand_label = f"Terminal {terminal}  ·  Gate {gate}"
            card = overview_glass_panel(
                ft.Column(
                    spacing=5,
                    controls=[
                        ft.Text(title, size=12, weight=ft.FontWeight.W_600, color=overview_text_color, style=overview_text_style),
                        ft.Container(
                            width=74 if live else None,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                            border_radius=5, bgcolor=color,
                            content=ft.Text(code or "—", size=17, weight=ft.FontWeight.W_700, color=foreground),
                        ),
                        ft.Text(airport_name, size=13, color=overview_text_color, style=overview_text_style,
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, tooltip=airport_name),
                        *([] if live else [
                            ft.Text(weather_label, size=11, color=overview_text_color, style=overview_text_style,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=weather_label),
                            ft.Text(stand_label, size=11, color=overview_text_color, style=overview_text_style,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=stand_label),
                        ]),
                    ],
                ),
                padding=11,
            )

            if target_tab_index is None:
                return card
            return ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda e, idx=target_tab_index: go_to_tab(idx),
                content=card,
            )

        # Overview aircraft progress icon.
        # Put the transparent PNG here: assets/icons/nav/aircraft_progress.png
        # Flight status controls below will drive this percentage.
        OVERVIEW_FLIGHT_STATUSES = ["Gate", "Taxi Out", "Takeoff", "Cruise", "Landing", "Taxi In", "Gate"]

        def overview_progress_percent() -> float:
            idx = max(0, min(len(OVERVIEW_FLIGHT_STATUSES) - 1, int(state.overview_flight_status_index or 0)))
            if idx < 2:
                return 0.0
            if idx >= 5:
                return 100.0
            duration_minutes = planned_overview_minutes()
            if not duration_minutes:
                return 0.0
            elapsed_min = overview_elapsed_seconds() / 60.0
            return clamp((elapsed_min / duration_minutes) * 100.0, 0.0, 100.0)

        current_progress = overview_progress_percent()
        current_status = OVERVIEW_FLIGHT_STATUSES[max(0, min(len(OVERVIEW_FLIGHT_STATUSES) - 1, int(state.overview_flight_status_index or 0)))]

        def aircraft_progress_icon() -> ft.Control:
            rel = asset_rel_path_if_exists("icons/nav/aircraft_progress.png")
            icon_content = (
                ft.Image(src=rel, width=route_scaled(32, 22), height=route_scaled(32, 22), fit=ft.BoxFit.CONTAIN)
                if rel
                else ft.Text("✈", size=route_scaled(28, 20), color=tokens["accent"])
            )
            return ft.Container(
                width=route_scaled(36, 25),
                height=route_scaled(36, 25),
                alignment=ft.Alignment(0, 0),
                bgcolor=ft.Colors.TRANSPARENT,
                content=icon_content,
            )

        def build_aircraft_progress_line(progress_percent: float = 0.0) -> ft.Control:
            # Progress line layout:
            # - Remaining route = light airline color.
            # - Covered route = darker/stronger shade of the same airline color.
            # - Aircraft sits directly on the centerline, with the line running behind it.
            progress = clamp(float(progress_percent or 0.0), 0.0, 100.0)
            covered_units = max(1, int(round(progress)))
            remaining_units = max(1, int(round(100.0 - progress)))
            completed_line_color = ft.Colors.with_opacity(0.82, tokens["accent"])
            remaining_line_color = ft.Colors.with_opacity(0.22, tokens["accent"])

            aircraft_on_line = ft.Container(
                width=route_scaled(38, 27),
                height=route_scaled(38, 27),
                content=ft.Stack(
                    controls=[
                        ft.Container(
                            top=route_scaled(17, 12),
                            left=0,
                            right=0,
                            height=route_scaled(4, 3),
                            border_radius=999,
                            bgcolor=completed_line_color if progress >= 100.0 else remaining_line_color,
                        ),
                        ft.Container(
                            alignment=ft.Alignment(0, 0),
                            content=aircraft_progress_icon(),
                        ),
                    ],
                ),
            )

            return ft.Container(
                height=route_scaled(42, 30),
                alignment=ft.Alignment(0, 0),
                content=ft.Row(
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(width=route_scaled(16, 11), height=route_scaled(16, 11), border_radius=999, bgcolor=tokens["accent"]),
                        ft.Container(expand=covered_units, height=route_scaled(4, 3), border_radius=999, bgcolor=completed_line_color),
                        aircraft_on_line,
                        ft.Container(expand=remaining_units, height=route_scaled(4, 3), border_radius=999, bgcolor=remaining_line_color),
                        ft.Container(width=route_scaled(16, 11), height=route_scaled(16, 11), border_radius=999, bgcolor=tokens["accent"]),
                    ],
                ),
            )

        def refresh_overview_progress_controls(update_page: bool = True):
            live_progress = overview_progress_percent()
            duration_minutes = planned_overview_minutes()
            remaining_minutes = max(0, duration_minutes - int(overview_elapsed_seconds() / 60.0))
            if int(state.overview_flight_status_index or 0) >= 5:
                remaining_minutes = 0

            locked_eta = getattr(state, "overview_locked_eta_timestamp", None)
            live_eta_text = "—"
            if has_complete_route and duration_minutes > 0:
                start = state.overview_takeoff_start_timestamp
                if int(state.overview_flight_status_index or 0) >= 5 and locked_eta is not None:
                    eta = locked_eta
                else:
                    eta = (start if start is not None else time.time()) + duration_minutes * 60
                live_eta_text = datetime.fromtimestamp(eta).strftime("%H:%M")

            overview_route_line_host.content = build_aircraft_progress_line(live_progress)
            overview_ete_value_text.value = format_hours_to_hm(remaining_minutes / 60.0) if duration_minutes > 0 else "—"
            overview_eta_value_text.value = live_eta_text

            if overview_route_aircraft_marker is not None and len(overview_route_aircraft_points) >= 2:
                aircraft_lat, aircraft_lon, aircraft_bearing = minimap_route_position_and_bearing(
                    overview_route_aircraft_points,
                    live_progress / 100.0,
                )
                overview_route_aircraft_marker.coordinates = ftm.MapLatitudeLongitude(aircraft_lat, aircraft_lon)
                overview_route_aircraft_marker.content = overview_route_aircraft_content(aircraft_bearing)

            if update_page:
                for ctrl in (
                    overview_route_line_host,
                    overview_ete_value_text,
                    overview_eta_value_text,
                ):
                    safe_update_control(ctrl)
                safe_update_control(overview_route_aircraft_marker)

        overview_progress_refresh_callback = refresh_overview_progress_controls
        refresh_overview_progress_controls(update_page=False)

        route_line = ft.Container(
            height=route_scaled(48, 34),
            padding=ft.padding.symmetric(horizontal=route_scaled(12, 8), vertical=route_scaled(3, 2)),
            content=overview_route_line_host,
        )

        def live_summary_status_label() -> str:
            idx = max(0, min(len(OVERVIEW_FLIGHT_STATUSES) - 1, int(state.overview_flight_status_index or 0)))
            status_map = {
                0: "At gate",
                1: "Taxi out",
                2: "Takeoff",
                3: "Cruise",
                4: "Descending / landing",
                5: "Taxi in",
                6: "Parked / at gate",
            }
            return status_map.get(idx, current_status)

        def live_summary_info_tile(label: str, value: str, width: int = 190) -> ft.Control:
            return ft.Container(
                width=width,
                padding=ft.padding.symmetric(horizontal=14, vertical=12),
                border_radius=18,
                bgcolor=surface_fill(tokens["subpanel"]),
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    tight=True,
                    spacing=4,
                    controls=[
                        ft.Text(label, size=10, color=tokens["muted"]),
                        ft.Text(value or "—", size=15, weight=ft.FontWeight.W_800, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        def live_summary_route_line() -> ft.Control:
            origin_label = origin_icao or "ORG"
            destination_label = destination_icao or "DST"
            return ft.Container(
                padding=ft.padding.symmetric(horizontal=16, vertical=14),
                border_radius=22,
                bgcolor=surface_fill(tokens["subpanel"]),
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Text(origin_label, size=18, weight=ft.FontWeight.W_900, color=tokens["text"]),
                                ft.Text(destination_label, size=18, weight=ft.FontWeight.W_900, color=tokens["text"]),
                            ],
                        ),
                        ft.Row(
                            spacing=0,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Container(width=14, height=14, border_radius=999, bgcolor=tokens["accent"]),
                                ft.Container(expand=True, height=3, border_radius=999, bgcolor=ft.Colors.with_opacity(0.50, tokens["accent"])),
                                ft.Container(width=14, height=14, border_radius=999, bgcolor=tokens["accent"]),
                            ],
                        ),
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("Departure", size=10, color=tokens["muted"]),
                                ft.Text("Arrival", size=10, color=tokens["muted"]),
                            ],
                        ),
                    ],
                ),
            )

        def set_overview_status(new_index: int):
            new_index = max(0, min(len(OVERVIEW_FLIGHT_STATUSES) - 1, int(new_index)))
            was_complete = int(state.overview_flight_status_index or 0) >= 5
            state.overview_flight_status_index = new_index
            if new_index < 2 or (was_complete and new_index < 5):
                state.overview_takeoff_start_timestamp = None
                state.overview_locked_eta_timestamp = None
                state.overview_progress_running = False
                state.overview_paused_elapsed_seconds = None
                state.overview_calendar_completion_key = ""
            elif new_index >= 5:
                duration_sec = planned_overview_minutes() * 60
                finish_ts = time.time()
                elapsed_seconds = overview_elapsed_seconds()
                if duration_sec:
                    state.overview_takeoff_start_timestamp = finish_ts - duration_sec
                state.overview_locked_eta_timestamp = finish_ts if duration_sec else None
                state.overview_progress_running = False
                state.overview_paused_elapsed_seconds = elapsed_seconds if not duration_sec and elapsed_seconds else None
            refresh_ui()

        def toggle_overview_progress(e=None):
            if state.overview_progress_running:
                state.overview_paused_elapsed_seconds = overview_elapsed_seconds()
                state.overview_progress_running = False
            else:
                if not 2 <= int(state.overview_flight_status_index or 0) < 5:
                    state.overview_flight_status_index = 2
                start_ts = time.time() - overview_elapsed_seconds()
                state.overview_takeoff_start_timestamp = start_ts
                duration_minutes = planned_overview_minutes()
                state.overview_locked_eta_timestamp = start_ts + duration_minutes * 60 if duration_minutes else None
                state.overview_paused_elapsed_seconds = None
                state.overview_calendar_completion_key = ""
                state.overview_progress_running = True
            refresh_ui()

        RAMP_STATUS_LABELS = {
            "departure": {
                "boarding": "Boarding",
                "cargo_loading": "Cargo loading",
                "catering": "Catering",
                "fueling": "Fueling",
                "cleaning": "Cleaning",
                "gate_ready": "Gate ready",
                "pushback": "Pushback",
            },
            "arrival": {
                "aircraft_parked": "Aircraft parked",
                "navigation_lights_off": "Navigation lights off",
                "engine_shutdown": "Engine shutdown",
                "beacon_lights_off": "Beacon lights off",
                "jet_bridge_connected": "Jet bridge connected",
                "deboarding": "Deboarding",
                "cargo_unloading": "Cargo unloading",
            },
        }

        RAMP_STATUS_ICONS = {
            "boarding": "GROUP",
            "cargo_loading": "LOCAL_SHIPPING",
            "catering": "RESTAURANT",
            "fueling": "LOCAL_GAS_STATION",
            "cleaning": "CLEANING_SERVICES",
            "gate_ready": "CHECK_CIRCLE_OUTLINE",
            "pushback": "FLIGHT_TAKEOFF",
            "aircraft_parked": "FLIGHT_LAND",
            "navigation_lights_off": "LIGHTBULB_OUTLINE",
            "engine_shutdown": "POWER_SETTINGS_NEW",
            "beacon_lights_off": "LIGHT_MODE",
            "jet_bridge_connected": "AIRLINE_SEAT_RECLINE_NORMAL",
            "deboarding": "DIRECTIONS_WALK",
            "cargo_unloading": "INVENTORY_2",
        }

        def ensure_ramp_status_data():
            for phase_name in ("departure", "arrival"):
                current = getattr(state, f"ramp_{phase_name}_statuses", None)
                if not isinstance(current, dict):
                    current = {}
                    setattr(state, f"ramp_{phase_name}_statuses", current)
                for item_key in RAMP_STATUS_LABELS[phase_name]:
                    current.setdefault(item_key, "idle")

        def active_ramp_phase() -> str:
            phase = getattr(state, "ramp_status_phase", "departure")
            if phase not in ("departure", "arrival"):
                phase = "departure"
                state.ramp_status_phase = phase
            return phase

        def refresh_ramp_status_view(update_page: bool = True):
            callback = ramp_status_refresh_callback
            if state.selected_tab_index == 0 and callable(callback):
                callback(update_page=update_page)
            else:
                refresh_ui()

        def set_ramp_phase(phase: str):
            if phase in ("departure", "arrival"):
                state.ramp_status_phase = phase
                refresh_ramp_status_view()

        def set_ramp_item_status(phase: str, item_key: str, status_value: str):
            ensure_ramp_status_data()
            status_map = getattr(state, f"ramp_{phase}_statuses")
            current_value = status_map.get(item_key, "idle")
            status_map[item_key] = "idle" if current_value == status_value else status_value
            refresh_ramp_status_view()

        def reset_active_ramp_phase(e=None):
            ensure_ramp_status_data()
            phase = active_ramp_phase()
            status_map = getattr(state, f"ramp_{phase}_statuses")
            for key in RAMP_STATUS_LABELS[phase]:
                status_map[key] = "idle"
            refresh_ramp_status_view()

        def ramp_icon_control(item_key: str) -> ft.Control:
            icon_name = RAMP_STATUS_ICONS.get(item_key, "CHECK_CIRCLE_OUTLINE")
            icon_value = getattr(ft.Icons, icon_name, None)
            if icon_value is None:
                return ft.Text("•", size=16, weight=ft.FontWeight.W_900, color=tokens["accent"])
            return ft.Icon(icon_value, size=15, color=tokens["accent"])

        def ramp_phase_chip(label: str, phase: str) -> ft.Control:
            active = active_ramp_phase() == phase
            chip = ft.Container(
                padding=ft.padding.symmetric(horizontal=11, vertical=7),
                border_radius=999,
                bgcolor=ft.Colors.with_opacity(0.20 if active else 0.06, tokens["accent"] if active else tokens["muted"]),
                border=ft.border.all(1, ft.Colors.with_opacity(0.34 if active else 0.12, tokens["accent"] if active else tokens["muted"])),
                content=ft.Text(label, size=10, weight=ft.FontWeight.W_800 if active else ft.FontWeight.W_600, color=tokens["text"]),
            )
            return ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda e, target_phase=phase: set_ramp_phase(target_phase),
                content=chip,
            )

        def next_ramp_status_value(current_value: str) -> str:
            if current_value == "idle":
                return "progress"
            if current_value == "progress":
                return "done"
            return "idle"

        def ramp_status_label_button(phase: str, item_key: str) -> ft.Control:
            ensure_ramp_status_data()
            status_map = getattr(state, f"ramp_{phase}_statuses")
            current_value = status_map.get(item_key, "idle")

            if current_value == "done":
                label = "COMPLETE"
                status_color = ft.Colors.GREEN_300
                fill_opacity = 0.18
                border_opacity = 0.48
            elif current_value == "progress":
                label = "IN PROGRESS"
                status_color = tokens["accent"]
                fill_opacity = 0.18
                border_opacity = 0.46
            else:
                label = "STANDBY"
                status_color = tokens["muted"]
                fill_opacity = 0.07
                border_opacity = 0.14

            def cycle_status(e=None, target_phase=phase, target_key=item_key):
                ensure_ramp_status_data()
                target_map = getattr(state, f"ramp_{target_phase}_statuses")
                target_map[target_key] = next_ramp_status_value(target_map.get(target_key, "idle"))
                refresh_ramp_status_view()

            return ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=cycle_status,
                content=ft.Container(
                    width=112,
                    height=28,
                    border_radius=999,
                    alignment=ft.Alignment(0, 0),
                    bgcolor=ft.Colors.with_opacity(fill_opacity, status_color),
                    border=ft.border.all(1, ft.Colors.with_opacity(border_opacity, status_color)),
                    content=ft.Text(
                        label,
                        size=9,
                        weight=ft.FontWeight.W_900,
                        color=status_color,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ),
            )

        def ramp_status_row(phase: str, item_key: str, label: str) -> ft.Control:
            ensure_ramp_status_data()
            status_map = getattr(state, f"ramp_{phase}_statuses")
            item_status = status_map.get(item_key, "idle")
            status_color = ft.Colors.GREEN_300 if item_status == "done" else tokens["accent"] if item_status == "progress" else ft.Colors.WHITE

            row_fill = ft.Colors.with_opacity(
                0.12 if item_status == "done" else 0.08 if item_status == "progress" else 0.045,
                status_color,
            )
            row_border = ft.Colors.with_opacity(
                0.30 if item_status in ("done", "progress") else 0.10,
                ft.Colors.GREEN_300 if item_status == "done" else tokens["accent"] if item_status == "progress" else tokens["card_border"],
            )
            return ft.Container(
                height=36,
                padding=ft.padding.only(left=9, right=8, top=4, bottom=4),
                border_radius=14,
                bgcolor=row_fill,
                border=ft.border.all(1, row_border),
                content=ft.Row(
                    spacing=9,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(
                            width=26,
                            height=26,
                            border_radius=9,
                            alignment=ft.Alignment(0, 0),
                            bgcolor=ft.Colors.with_opacity(0.10, tokens["accent"]),
                            content=ramp_icon_control(item_key),
                        ),
                        ft.Container(
                            expand=True,
                            content=ft.Text(
                                label,
                                size=12,
                                weight=ft.FontWeight.W_700,
                                color=tokens["text"],
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        ),
                        ramp_status_label_button(phase, item_key),
                    ],
                ),
            )

        def build_ramp_status_card() -> ft.Control:
            ensure_ramp_status_data()
            phase = active_ramp_phase()
            labels = RAMP_STATUS_LABELS[phase]
            status_map = getattr(state, f"ramp_{phase}_statuses")
            completed_count = sum(1 for key in labels if status_map.get(key) == "done")
            progress_count = sum(1 for key in labels if status_map.get(key) == "progress")
            active_label = "Departure ramp" if phase == "departure" else "Arrival ramp"

            return ft.Container(
                width=overview_ramp_width,
                height=overview_card_height,
                border_radius=20,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                bgcolor=surface_fill(tokens["subpanel"]),
                border=ft.border.all(1, tokens["card_border"]),
                shadow=ft.BoxShadow(
                    blur_radius=18,
                    spread_radius=1,
                    color=ft.Colors.with_opacity(0.10, ft.Colors.BLACK),
                    offset=ft.Offset(0, 6),
                ),
                content=ft.Stack(
                    expand=True,
                    controls=[
                        *card_background_layers("ramp_status", tokens["subpanel"], overlay_opacity=0.0),
                        ft.Container(
                            expand=True,
                            padding=16,
                            content=ft.Column(
                                spacing=7,
                                controls=[
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[
                                            ft.Column(
                                                tight=True,
                                                spacing=2,
                                                controls=[
                                                    ft.Text("Ramp Status", size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                                                    ft.Text(f"{active_label} • {progress_count} in process • {completed_count}/{len(labels)} done", size=10, color=tokens["muted"]),
                                                ],
                                            ),
                                            ft.Row(
                                                spacing=6,
                                                controls=[
                                                    ramp_phase_chip("Departure", "departure"),
                                                    ramp_phase_chip("Arrival", "arrival"),
                                                ],
                                            ),
                                        ],
                                    ),
                                    ft.Container(
                                        height=1,
                                        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.WHITE),
                                    ),
                                    ft.Row(
                                        spacing=8,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[
                                            ft.Container(expand=True, content=ft.Text("Checklist", size=10, color=tokens["muted"], weight=ft.FontWeight.W_700)),
                                            ft.Container(width=112, alignment=ft.Alignment(0, 0), content=ft.Text("Status", size=10, color=tokens["muted"], weight=ft.FontWeight.W_700)),
                                        ],
                                    ),
                                    ft.Column(
                                        spacing=6,
                                        controls=[ramp_status_row(phase, key, label) for key, label in labels.items()],
                                    ),
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.END,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[
                                            ft.TextButton("Reset", on_click=reset_active_ramp_phase),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            )

        def refresh_ramp_status_card(update_page: bool = True):
            ramp_status_card_host.content = build_ramp_status_card()
            if update_page:
                safe_update_control(ramp_status_card_host)

        ramp_status_refresh_callback = refresh_ramp_status_card
        refresh_ramp_status_card(update_page=False)
        ramp_status_card = ramp_status_card_host

        def route_center_metric(label: str, value: str, subtitle: str = "") -> ft.Control:
            return ft.Container(
                width=route_scaled(180, 126),
                height=route_scaled(85, 60),
                padding=route_scaled(10, 7),
                border_radius=route_scaled(18, 13),
                bgcolor=surface_fill(tokens["subpanel"]),
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    spacing=route_scaled(3, 2),
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(label, size=route_scaled(10, 7), color=tokens["muted"], text_align=ft.TextAlign.CENTER),
                        value if isinstance(value, ft.Control) else ft.Text(value, size=route_scaled(18, 13), weight=ft.FontWeight.W_800, color=tokens["text"], text_align=ft.TextAlign.CENTER),
                        ft.Text(subtitle, size=route_scaled(9, 6), color=tokens["muted"], text_align=ft.TextAlign.CENTER, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        def minimap_zoom(distance_nm_value: Optional[float]) -> float:
            if distance_nm_value is None:
                return 2.1
            if distance_nm_value < 150:
                return 6.0
            if distance_nm_value < 350:
                return 5.1
            if distance_nm_value < 750:
                return 4.3
            if distance_nm_value < 1500:
                return 3.6
            if distance_nm_value < 3000:
                return 3.0
            if distance_nm_value < 5000:
                return 2.45
            return 2.05

        def minimap_route_points(
            origin: tuple[float, float],
            destination: tuple[float, float],
            steps: int = 48,
        ) -> List[tuple[float, float]]:
            lat1, lon1 = math.radians(origin[0]), math.radians(origin[1])
            lat2, lon2 = math.radians(destination[0]), math.radians(destination[1])
            delta = 2 * math.asin(
                math.sqrt(
                    math.sin((lat2 - lat1) / 2) ** 2
                    + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
                )
            )
            if delta == 0:
                return [origin, destination]

            points: List[tuple[float, float]] = []
            for index in range(steps + 1):
                fraction = index / steps
                a = math.sin((1 - fraction) * delta) / math.sin(delta)
                b = math.sin(fraction * delta) / math.sin(delta)
                x = a * math.cos(lat1) * math.cos(lon1) + b * math.cos(lat2) * math.cos(lon2)
                y = a * math.cos(lat1) * math.sin(lon1) + b * math.cos(lat2) * math.sin(lon2)
                z = a * math.sin(lat1) + b * math.sin(lat2)
                lat = math.degrees(math.atan2(z, math.sqrt(x * x + y * y)))
                lon = math.degrees(math.atan2(y, x))
                points.append((lat, lon))
            return points

        def minimap_route_position_and_bearing(
            route_points: List[tuple[float, float]],
            progress_fraction: float,
        ) -> tuple[float, float, float]:
            """Interpolate on the displayed route and return latitude, longitude, and bearing."""
            if len(route_points) < 2:
                lat, lon = route_points[0] if route_points else (0.0, 0.0)
                return lat, lon, 0.0

            progress = clamp(float(progress_fraction or 0.0), 0.0, 1.0)
            scaled_index = progress * (len(route_points) - 1)
            segment_index = min(len(route_points) - 2, int(math.floor(scaled_index)))
            segment_fraction = scaled_index - segment_index
            start_lat, start_lon = route_points[segment_index]
            end_lat, end_lon = route_points[segment_index + 1]

            lon_delta = ((end_lon - start_lon + 180.0) % 360.0) - 180.0
            latitude = start_lat + (end_lat - start_lat) * segment_fraction
            longitude = ((start_lon + lon_delta * segment_fraction + 180.0) % 360.0) - 180.0

            start_lat_rad = math.radians(start_lat)
            end_lat_rad = math.radians(end_lat)
            lon_delta_rad = math.radians(lon_delta)
            bearing_x = math.sin(lon_delta_rad) * math.cos(end_lat_rad)
            bearing_y = (
                math.cos(start_lat_rad) * math.sin(end_lat_rad)
                - math.sin(start_lat_rad) * math.cos(end_lat_rad) * math.cos(lon_delta_rad)
            )
            bearing = (math.degrees(math.atan2(bearing_x, bearing_y)) + 360.0) % 360.0
            return latitude, longitude, bearing

        def minimap_center(origin: tuple[float, float], destination: tuple[float, float]) -> tuple[float, float]:
            route_points = minimap_route_points(origin, destination, steps=12)
            middle = route_points[len(route_points) // 2]
            return middle

        def airport_city_country_label(code: Optional[str], record: Optional[dict]) -> str:
            canonical = normalize_airport_code(code) or (code or "").strip().upper()
            iata = str((record or {}).get("iata", "") or "").strip().upper()
            city_by_iata = {
                "AMS": "Amsterdam, Netherlands", "ATH": "Athens, Greece", "ATL": "Atlanta, USA",
                "AKL": "Auckland, New Zealand", "AUS": "Austin, USA", "AUH": "Abu Dhabi, UAE",
                "BAH": "Bahrain", "BCN": "Barcelona, Spain", "BNA": "Nashville, USA",
                "BER": "Berlin, Germany", "BKK": "Bangkok, Thailand", "BLR": "Bengaluru, India",
                "BOG": "Bogota, Colombia", "BOM": "Mumbai, India", "BOS": "Boston, USA",
                "CAI": "Cairo, Egypt", "CAN": "Guangzhou, China", "CDG": "Paris, France",
                "CGK": "Jakarta, Indonesia", "CGN": "Cologne, Germany", "CKG": "Chongqing, China",
                "CLT": "Charlotte, USA", "CUN": "Cancun, Mexico",
                "DEL": "Delhi, India", "DEN": "Denver, USA", "DFW": "Dallas, USA",
                "DOH": "Doha, Qatar", "DUB": "Dublin, Ireland", "DXB": "Dubai, UAE",
                "DTW": "Detroit, USA", "EWR": "Newark, USA", "EZE": "Buenos Aires, Argentina", "FCO": "Rome, Italy",
                "FRA": "Frankfurt, Germany", "GRU": "Sao Paulo, Brazil", "HAM": "Hamburg, Germany",
                "HAN": "Hanoi, Vietnam", "HEL": "Helsinki, Finland", "HGH": "Hangzhou, China",
                "HKG": "Hong Kong", "HND": "Tokyo, Japan",
                "IAD": "Washington, USA", "IAH": "Houston, USA", "ICN": "Seoul, South Korea",
                "IKA": "Tehran, Iran", "IST": "Istanbul, Turkiye", "JED": "Jeddah, Saudi Arabia",
                "JFK": "New York, USA", "KIX": "Osaka, Japan", "KMG": "Kunming, China", "KUL": "Kuala Lumpur, Malaysia",
                "KWI": "Kuwait City, Kuwait", "LAS": "Las Vegas, USA", "LAX": "Los Angeles, USA",
                "LGW": "London, UK", "LHR": "London, UK", "LIM": "Lima, Peru",
                "LIS": "Lisbon, Portugal", "MAD": "Madrid, Spain", "MAA": "Chennai, India", "MAN": "Manchester, UK",
                "MCI": "Kansas City, USA", "MCO": "Orlando, USA", "MEX": "Mexico City, Mexico", "MIA": "Miami, USA",
                "MNL": "Manila, Philippines", "MRU": "Mauritius", "MSP": "Minneapolis, USA", "MUC": "Munich, Germany",
                "NCL": "Newcastle, UK", "NKG": "Nanjing, China", "NRT": "Tokyo, Japan", "ORD": "Chicago, USA", "OSL": "Oslo, Norway",
                "PEK": "Beijing, China", "PHL": "Philadelphia, USA", "PHX": "Phoenix, USA",
                "PVG": "Shanghai, China", "RUH": "Riyadh, Saudi Arabia", "RZR": "Ramsar, Iran", "SEA": "Seattle, USA",
                "SFO": "San Francisco, USA", "SHA": "Shanghai, China", "SIN": "Singapore", "STL": "St. Louis, USA",
                "SVO": "Moscow, Russia", "SZX": "Shenzhen, China", "TAO": "Qingdao, China", "TBZ": "Tabriz, Iran",
                "TFU": "Chengdu, China", "TLV": "Tel Aviv, Israel", "TPE": "Taipei, Taiwan",
                "SYD": "Sydney, Australia", "VIE": "Vienna, Austria", "WAW": "Warsaw, Poland",
                "YUL": "Montreal, Canada", "YVR": "Vancouver, Canada", "YYC": "Calgary, Canada",
                "WUH": "Wuhan, China", "XIY": "Xi'an, China", "XMN": "Xiamen, China",
                "YYZ": "Toronto, Canada", "ZRH": "Zurich, Switzerland",
            }
            if iata in city_by_iata:
                return city_by_iata[iata]
            country_by_prefix = {
                "CY": "Canada", "ED": "Germany", "EF": "Finland", "EG": "UK", "EH": "Netherlands",
                "EI": "Ireland", "EK": "Denmark", "EN": "Norway", "EP": "Poland", "ES": "Sweden",
                "FM": "Mauritius", "HE": "Egypt", "KA": "USA", "KB": "USA", "KC": "USA", "KD": "USA", "KE": "USA",
                "KF": "USA", "KG": "USA", "KH": "USA", "KI": "USA", "KJ": "USA", "KK": "USA",
                "KL": "USA", "KM": "USA", "KN": "USA", "KO": "USA", "KP": "USA", "KS": "USA",
                "LE": "Spain", "LF": "France", "LG": "Greece", "LI": "Italy", "LL": "Israel",
                "LO": "Austria", "LP": "Portugal", "LS": "Switzerland", "LT": "Turkiye", "MM": "Mexico",
                "OB": "Bahrain", "OE": "Saudi Arabia", "OI": "Iran", "OJ": "Jordan", "OK": "Kuwait",
                "OM": "UAE", "OO": "Oman", "OT": "Qatar", "RC": "Taiwan", "RJ": "Japan",
                "RK": "South Korea", "RP": "Philippines", "SA": "Argentina", "SB": "Brazil",
                "SC": "Chile", "SK": "Colombia", "SP": "Peru", "UU": "Russia", "VA": "India",
                "VE": "India", "VH": "Hong Kong", "VI": "India", "VO": "India", "VT": "Thailand",
                "NZ": "New Zealand", "VV": "Vietnam", "WI": "Indonesia", "WM": "Malaysia", "WS": "Singapore",
                "YS": "Australia", "ZB": "China", "ZG": "China", "ZH": "China", "ZL": "China", "ZP": "China",
                "ZS": "China", "ZU": "China",
            }
            airport_name = str((record or {}).get("name", "") or "").strip()
            city = re.sub(r"\b(International|Intl|Airport|Airfield|Regional|Brandenburg|Charles de Gaulle)\b", "", airport_name, flags=re.IGNORECASE)
            city = (record or {}).get("city") or re.sub(r"\s+", " ", city).strip(" -") or (iata or canonical or "Airport")
            country = country_by_prefix.get(canonical[:2], "") or (record or {}).get("country", "")
            return f"{city}, {country}" if country else city

        def minimap_endpoint_marker(code: str, color: str) -> ft.Control:
            canonical = normalize_airport_code(code) or (code or "").strip().upper()
            record = lookup_airport_record(canonical)
            weather = airport_weather_for_card(canonical)
            label = str((record or {}).get("iata", "") or canonical or "—").strip().upper()
            airport_name = str((record or {}).get("name", "Airport not selected") or "Airport not selected")
            city_country = airport_city_country_label(canonical, record)
            background_src = airport_card_background_src(canonical, "airport")
            layers: List[ft.Control] = [
                ft.Container(expand=True, bgcolor=surface_fill(tokens["panel"])),
            ]
            if background_src:
                layers.extend(
                    [
                        ft.Container(
                            expand=True,
                            image=ft.DecorationImage(src=background_src, fit=ft.BoxFit.COVER, opacity=0.58),
                        ),
                        ft.Container(expand=True, bgcolor=ft.Colors.with_opacity(0.38, ft.Colors.BLACK)),
                    ]
                )
            return ft.Container(
                width=overview_airport_marker_size,
                height=overview_airport_marker_size,
                border_radius=18,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                border=ft.border.all(1.2, color),
                shadow=ft.BoxShadow(
                    blur_radius=16,
                    spread_radius=1,
                    color=ft.Colors.with_opacity(0.26, ft.Colors.BLACK),
                    offset=ft.Offset(0, 7),
                ),
                content=ft.Stack(
                    expand=True,
                    controls=[
                        *layers,
                        ft.Container(
                            expand=True,
                            padding=10,
                            content=ft.Column(
                                spacing=3,
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        vertical_alignment=ft.CrossAxisAlignment.START,
                                        controls=[
                                            ft.Text(label, size=22, weight=ft.FontWeight.W_900, color=ft.Colors.WHITE),
                                            ft.Text(str(weather.get("temperature", "—")), size=12, weight=ft.FontWeight.W_800, color=ft.Colors.WHITE),
                                        ],
                                    ),
                                    ft.Column(
                                        tight=True,
                                        spacing=2,
                                        controls=[
                                            ft.Text(city_country, size=10, weight=ft.FontWeight.W_800, color=ft.Colors.WHITE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                            ft.Text(airport_name, size=9, color=ft.Colors.with_opacity(0.82, ft.Colors.WHITE), max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            )

        def overview_airport_dot(color: str) -> ft.Control:
            return ft.Container(
                width=16,
                height=16,
                border_radius=999,
                alignment=ft.Alignment(0, 0),
                bgcolor=color,
                border=ft.border.all(2, ft.Colors.with_opacity(0.92, ft.Colors.WHITE)),
                shadow=ft.BoxShadow(
                    blur_radius=14,
                    spread_radius=1,
                    color=ft.Colors.with_opacity(0.44, color),
                    offset=ft.Offset(0, 0),
                ),
            )

        def overview_endpoint_marker(coord: tuple[float, float], code: str, *, departure: bool) -> ft.Control:
            label = "Departure" if departure else "Arrival"
            color, ink = ("#FFE54D", "#211D0A") if departure else ("#7263E8", "#FFFFFF")
            badge = ft.Container(
                top=None if departure else 0,
                bottom=0 if departure else None,
                left=0,
                right=0,
                height=22,
                alignment=ft.Alignment(0, 0),
                bgcolor=color,
                border_radius=5,
                border=ft.border.all(1, ink),
                content=ft.Text(f"{label} {code}", size=11, weight=ft.FontWeight.W_800, color=ink, no_wrap=True),
            )
            return ftm.Marker(
                coordinates=ftm.MapLatitudeLongitude(*coord),
                width=116,
                height=64,
                alignment=ft.Alignment(0, 0),
                rotate=False,
                tooltip=f"{label} {code}",
                content=ft.Stack(
                    controls=[badge, ft.Container(top=24, left=50, content=overview_airport_dot(color))],
                ),
            )

        def overview_route_aircraft_content(bearing: float) -> ft.Control:
            icon = header_progress_icon()
            # The shared PNG points east at zero rotation; map bearings start at north.
            icon.rotate = math.radians(bearing - 90.0)
            return icon

        def overview_route_map_control(live_layers=None) -> ft.Control:
            nonlocal overview_route_aircraft_marker, overview_route_aircraft_points
            if ftm is None:
                return ft.Container(
                    expand=True,
                    bgcolor=surface_fill(tokens["panel"]),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Text(
                        "flet-map is not installed, so the Overview map cannot render in this build.",
                        size=12,
                        color=tokens["muted"],
                        text_align=ft.TextAlign.CENTER,
                    ),
                )

            if live_layers is not None:
                tile_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                map_attribution = "OpenStreetMap contributors"
                attribution_url = "https://www.openstreetmap.org/copyright"
            elif MAPTILER_API_KEY:
                tile_url = f"https://api.maptiler.com/maps/satellite/{{z}}/{{x}}/{{y}}.jpg?key={MAPTILER_API_KEY}"
                map_attribution = "MapTiler"
                attribution_url = "https://www.maptiler.com/"
            else:
                tile_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                map_attribution = "Esri"
                attribution_url = "https://www.esri.com/"

            layers = [
                ftm.TileLayer(url_template=tile_url, **(
                    {"user_agent_package_name": f"FlightManagementSystems/{FMS_VERSION}", "opacity": 0.88}
                    if live_layers is not None else {}
                )),
                ftm.SimpleAttribution(
                    text=map_attribution,
                    bgcolor=surface_fill(tokens["panel"]),
                    on_click=lambda e, url=attribution_url: e.page.launch_url(url),
                ),
            ]
            center = ftm.MapLatitudeLongitude(25.0, 10.0)
            zoom = 2.45
            rotation = 0.0
            camera_key = "live fallback" if live_layers is not None else "normal"
            overview_map_clamp_state = {"active": False}

            def overview_vertical_latitude_limit(zoom_value: float) -> float:
                viewport = max(1, float(page.height or 820) - SHELL_HEIGHT)
                world = 256 * 2 ** float(zoom_value)
                available = max(0, 1 - viewport / world)
                return math.degrees(math.atan(math.sinh(math.pi * available)))

            async def clamp_overview_map_vertical_position(e):
                if bool(overview_map_clamp_state.get("active")):
                    return
                camera = getattr(e, "camera", None)
                center_point = getattr(camera, "center", None) or getattr(e, "coordinates", None)
                if center_point is None:
                    return
                try:
                    current_lat = float(center_point.latitude)
                    current_lon = float(center_point.longitude)
                    current_zoom = float(getattr(camera, "zoom", zoom) or zoom)
                    current_rotation = float(getattr(camera, "rotation", 0.0) or 0.0)
                except Exception:
                    return
                if not all(map(math.isfinite, (current_lat, current_lon, current_zoom, current_rotation))):
                    return
                max_latitude = overview_vertical_latitude_limit(current_zoom)
                clamped_lat = max(-max_latitude, min(max_latitude, current_lat))
                overview_cameras[camera_key] = (clamped_lat, current_lon, current_zoom, current_rotation)
                if abs(clamped_lat - current_lat) < 0.0001:
                    return
                overview_map_clamp_state["active"] = True
                try:
                    await e.control.move_to(
                        destination=ftm.MapLatitudeLongitude(clamped_lat, current_lon),
                        zoom=current_zoom,
                        rotation=current_rotation,
                        animation_duration=0,
                        cancel_ongoing_animations=True,
                    )
                except Exception:
                    pass
                finally:
                    overview_map_clamp_state["active"] = False

            if live_layers is not None:
                layers.extend(live_layers)
            elif origin_coord and destination_coord:
                route_points = minimap_route_points(origin_coord, destination_coord)
                overview_route_aircraft_points = route_points
                mid_lat, mid_lon = minimap_center(origin_coord, destination_coord)
                center = ftm.MapLatitudeLongitude(mid_lat, mid_lon)
                zoom = minimap_zoom(route_nm)
                route_coordinates = [ftm.MapLatitudeLongitude(lat, lon) for lat, lon in route_points]
                layers.append(
                    ftm.PolylineLayer(
                        polylines=[
                            ftm.PolylineMarker(
                                coordinates=route_coordinates,
                                color=ft.Colors.with_opacity(0.28, tokens["accent"]),
                                stroke_width=7,
                                border_color=ft.Colors.with_opacity(0.10, ft.Colors.WHITE),
                                border_stroke_width=1,
                            ),
                            ftm.PolylineMarker(
                                coordinates=route_coordinates,
                                color=tokens["accent"],
                                stroke_width=3,
                            ),
                        ]
                    )
                )
                aircraft_lat, aircraft_lon, aircraft_bearing = minimap_route_position_and_bearing(
                    route_points,
                    overview_progress_percent() / 100.0,
                )
                overview_route_aircraft_marker = ftm.Marker(
                    coordinates=ftm.MapLatitudeLongitude(aircraft_lat, aircraft_lon),
                    width=32,
                    height=32,
                    alignment=ft.Alignment(0, 0),
                    rotate=False,
                    tooltip="Current flight progress",
                    content=overview_route_aircraft_content(aircraft_bearing),
                )
                layers.append(ftm.MarkerLayer(
                    markers=[
                        overview_endpoint_marker(origin_coord, origin_icao, departure=True),
                        overview_endpoint_marker(destination_coord, destination_icao, departure=False),
                    ],
                ))
                layers.append(ftm.MarkerLayer(markers=[overview_route_aircraft_marker], rotate=False))
            elif origin_coord or destination_coord:
                overview_route_aircraft_marker = None
                overview_route_aircraft_points = []
                available_coord = origin_coord or destination_coord
                available_icao = origin_icao if origin_coord else destination_icao
                center = ftm.MapLatitudeLongitude(*available_coord)
                zoom = 4.8
                layers.append(ftm.MarkerLayer(
                    markers=[overview_endpoint_marker(available_coord, available_icao, departure=bool(origin_coord))],
                ))

            viewport = max(1, float(page.height or 820) - SHELL_HEIGHT)
            minimum_zoom = max(2.45, math.log2(viewport / 256))
            if camera_key in overview_cameras:
                lat, lon, zoom, rotation = overview_cameras[camera_key]
                zoom = max(zoom, minimum_zoom)
                limit = overview_vertical_latitude_limit(zoom)
                center = ftm.MapLatitudeLongitude(max(-limit, min(limit, lat)), lon)

            return ftm.Map(
                expand=True,
                initial_center=center,
                initial_zoom=max(zoom, minimum_zoom),
                initial_rotation=rotation,
                min_zoom=minimum_zoom,
                max_zoom=19.0 if live_layers is not None else 10.0,
                bgcolor="#20242A" if live_layers is not None else "#020617",
                keep_alive=True,
                interaction_configuration=ftm.InteractionConfiguration(flags=ftm.InteractionFlag.ALL & ~ftm.InteractionFlag.ROTATE & ~ftm.InteractionFlag.FLING_ANIMATION),
                on_position_change=clamp_overview_map_vertical_position,
                layers=layers,
            )

        def minimap_card() -> ft.Control:
            if ftm is None:
                return glass_card_with_background(
                    "Mini Map",
                    ft.Container(
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Text(
                            "flet-map is not installed, so the mini map cannot render in this build.",
                            size=12,
                            color=tokens["muted"],
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ),
                    height=440,
                    bgcolor_override=tokens["panel"],
                    bg_key="overview_minimap_plain",
                )

            if MAPTILER_API_KEY:
                tile_url = f"https://api.maptiler.com/maps/satellite/{{z}}/{{x}}/{{y}}.jpg?key={MAPTILER_API_KEY}"
                map_attribution = "© MapTiler"
                attribution_url = "https://www.maptiler.com/"
            else:
                tile_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                map_attribution = "Tiles © Esri"
                attribution_url = "https://www.esri.com/"
            layers = [
                ftm.TileLayer(url_template=tile_url),
                ftm.SimpleAttribution(
                    text=map_attribution,
                    bgcolor=surface_fill(tokens["panel"]),
                    on_click=lambda e, url=attribution_url: e.page.launch_url(url),
                ),
            ]
            center = ftm.MapLatitudeLongitude(25.0, 10.0)
            zoom = 2.45
            map_note = "Set departure and arrival to draw the active route."

            if origin_coord and destination_coord:
                route_points = minimap_route_points(origin_coord, destination_coord)
                mid_lat, mid_lon = minimap_center(origin_coord, destination_coord)
                center = ftm.MapLatitudeLongitude(mid_lat, mid_lon)
                zoom = minimap_zoom(route_nm)
                map_note = f"{origin_icao} → {destination_icao} • {distance_label}"
                route_coordinates = [ftm.MapLatitudeLongitude(lat, lon) for lat, lon in route_points]
                layers.append(
                    ftm.PolylineLayer(
                        polylines=[
                            ftm.PolylineMarker(
                                coordinates=route_coordinates,
                                color=ft.Colors.with_opacity(0.28, tokens["accent"]),
                                stroke_width=7,
                                border_color=ft.Colors.with_opacity(0.10, ft.Colors.WHITE),
                                border_stroke_width=1,
                            ),
                            ftm.PolylineMarker(
                                coordinates=route_coordinates,
                                color=tokens["accent"],
                                stroke_width=3,
                            ),
                        ]
                    )
                )
                layers.append(
                    ftm.MarkerLayer(
                        markers=[
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(origin_coord[0], origin_coord[1]),
                                width=overview_airport_marker_size,
                                height=overview_airport_marker_size,
                                alignment=ft.Alignment(0, 0),
                                content=minimap_endpoint_marker(origin_icao, tokens["accent"]),
                            ),
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(destination_coord[0], destination_coord[1]),
                                width=overview_airport_marker_size,
                                height=overview_airport_marker_size,
                                alignment=ft.Alignment(0, 0),
                                content=minimap_endpoint_marker(destination_icao, "#50E3C2"),
                            ),
                        ]
                    )
                )
            elif origin_coord or destination_coord:
                available_coord = origin_coord or destination_coord
                available_icao = origin_icao if origin_coord else destination_icao
                center = ftm.MapLatitudeLongitude(available_coord[0], available_coord[1])
                zoom = 4.8
                map_note = f"Only {available_icao} is set."
                layers.append(
                    ftm.MarkerLayer(
                        markers=[
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(available_coord[0], available_coord[1]),
                                width=overview_airport_marker_size,
                                height=overview_airport_marker_size,
                                alignment=ft.Alignment(0, 0),
                                content=minimap_endpoint_marker(available_icao, tokens["accent"]),
                            ),
                        ]
                    )
                )

            world_map = ftm.Map(
                expand=True,
                initial_center=center,
                initial_zoom=zoom,
                min_zoom=2.45,
                max_zoom=10.0,
                bgcolor="#020617",
                keep_alive=True,
                interaction_configuration=ftm.InteractionConfiguration(flags=ftm.InteractionFlag.ALL),
                layers=layers,
            )

            return ft.Container(
                height=440,
                border_radius=20,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                bgcolor=surface_fill(tokens["panel"]),
                border=ft.border.all(1, tokens["card_border"]),
                shadow=ft.BoxShadow(
                    blur_radius=18,
                    spread_radius=1,
                    color=ft.Colors.with_opacity(0.10, ft.Colors.BLACK),
                    offset=ft.Offset(0, 6),
                ),
                content=ft.Stack(
                    expand=True,
                    controls=[
                        world_map,
                        ft.Container(
                            left=0,
                            top=0,
                            right=0,
                            height=62,
                            border_radius=ft.border_radius.only(top_left=20, top_right=20),
                            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                            content=ft.Stack(
                                expand=True,
                                controls=[
                                    ft.Container(
                                        expand=True,
                                        bgcolor=surface_fill(tokens["panel"]),
                                        blur=ft.Blur(10, 10, ft.BlurTileMode.CLAMP),
                                    ),
                                    ft.Container(
                                        expand=True,
                                        padding=ft.padding.symmetric(horizontal=18, vertical=0),
                                        alignment=ft.Alignment(-1, 0),
                                        border=ft.border.only(
                                            bottom=ft.BorderSide(1, ft.Colors.with_opacity(0.10, ft.Colors.WHITE))
                                        ),
                                        content=ft.Text(
                                            "Mini Map",
                                            size=14,
                                            weight=ft.FontWeight.W_800,
                                            color=tokens["text"],
                                        ),
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            )

        def route_metric_item(label: str, value: ft.Text) -> ft.Control:
            value.color = overview_text_color
            value.style = overview_text_style
            return ft.Container(
                expand=True,
                content=ft.Column(
                    tight=True,
                    spacing=3,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(label, size=11, color=overview_text_color, style=overview_text_style, no_wrap=True),
                        value,
                    ],
                ),
            )

        def live_overview() -> ft.Control:
            nonlocal live_render_callback
            if ftm is None:
                return overview_route_map_control()
            aircraft_layer = ftm.MarkerLayer(markers=[], rotate=False)
            selected_layer = ftm.MarkerLayer(markers=[], rotate=False)
            airport_layer = ftm.MarkerLayer(markers=[])
            route_layer = ftm.PolylineLayer(polylines=[])
            live_map = overview_route_map_control([route_layer, airport_layer, aircraft_layer, selected_layer])
            traffic_markers = {}
            rendered_traffic = None
            traffic_hidden = False
            selected_marker = None
            camera = (live_map.initial_center.latitude, live_map.initial_center.longitude, live_map.initial_zoom)
            traffic_camera = None
            camera_task = None
            clamp_position = live_map.on_position_change
            status = ft.Text("", size=11, color=overview_text_color, style=overview_text_style)
            detail = ft.Column(spacing=6)
            search_results = ft.Column(spacing=2, tight=True)
            airports = ft.Column(spacing=GAP, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
            timing = ft.Row(spacing=3)
            search = ft.TextField(
                label="Find aircraft", hint_text="Callsign or pilot", dense=True,
                border_radius=10, filled=True, bgcolor=tokens["input_bg"],
            )
            server = ft.Dropdown(hint_text="Server", dense=True, filled=True, bgcolor=tokens["input_bg"],
                                 border_radius=10)

            async def center_on_flight(zoom=None):
                position = if_flight_position(state.if_selected_flight)
                if position and live_map.page:
                    await live_map.move_to(
                        destination=ftm.MapLatitudeLongitude(*position), zoom=zoom,
                        animation_duration=300, cancel_ongoing_animations=True,
                    )

            async def select_flight(flight_id, *, from_search):
                selected = if_find_live_flight(flight_id)
                if not selected:
                    return
                if_mark_activity()
                if_clear_selection()
                state.if_selected_flight = selected
                search.value = ""
                safe_update_control(search)
                render()
                page.run_task(refresh_live_plan)
                if from_search:
                    await center_on_flight(5.0)

            def choose_flight(flight_id, *, from_search=False):
                async def choose(e):
                    await select_flight(flight_id, from_search=from_search)
                return choose

            async def toggle_follow(e):
                flight_id = str(state.if_selected_flight.get("flightId") or "")
                state.if_followed_flight_id = "" if state.if_followed_flight_id else flight_id
                if_mark_activity()
                render()
                if state.if_followed_flight_id:
                    await center_on_flight()

            async def select_server(e):
                session_id = e.control.value or ""
                if not if_select_session(session_id):
                    return
                if_clear_selection()
                state.if_live_flights = []
                state.if_traffic_session = ""
                render()
                await refresh_live_traffic(mark_activity=True)

            def render_search(e=None):
                if e is not None:
                    if_mark_activity()
                query = (search.value or "").strip()
                matches = [flight for flight in state.if_live_flights if if_flight_matches_query(flight, query)][:5] if query else []
                search_results.controls = [
                    ft.TextButton(
                        content=ft.Text(if_flight_display_name(flight), max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        on_click=choose_flight(str(flight["flightId"]), from_search=True),
                    ) for flight in matches
                ]
                if query and not matches:
                    search_results.controls = [ft.Text("No matching aircraft", size=12, color=overview_text_color)]
                if e is not None:
                    safe_update_control(search_results)

            def clear_selection(e):
                if_clear_selection()
                render()

            def aircraft_marker(flight, position, selected=False):
                flight_id = str(flight["flightId"])
                size = 30 if selected else 21
                return ftm.Marker(
                    key=f"{'selected' if selected else 'live'}-{flight_id}",
                    coordinates=ftm.MapLatitudeLongitude(*position), width=34, height=34,
                    tooltip=if_flight_display_name(flight),
                    content=ft.GestureDetector(
                        mouse_cursor=ft.MouseCursor.CLICK, scale=1, on_tap=choose_flight(flight_id),
                        content=ft.Container(
                            alignment=ft.Alignment(0, 0), border_radius=18,
                            content=ft.Image(src=if_aircraft_shape(flight, selected=selected), width=size, height=size,
                                             rotate=math.radians(if_flight_heading(flight))),
                        ),
                    ),
                )

            def update_aircraft_marker(marker, flight, position, *, selected=False):
                marker.coordinates = ftm.MapLatitudeLongitude(*position)
                marker.tooltip = if_flight_display_name(flight)
                image = marker.content.content.content
                image.src = if_aircraft_shape(flight, selected=selected)
                image.rotate = math.radians(if_flight_heading(flight))

            def visible_traffic(flights):
                lat, lon, zoom = camera
                world = 256 * 2 ** zoom
                width = float(page.width or 1000) / 2 + 40
                height = max(0, float(page.height or 720) - SHELL_HEIGHT) / 2 + 40

                def mercator(latitude):
                    latitude = max(-85.05, min(85.05, latitude))
                    return math.asinh(math.tan(math.radians(latitude))) / (2 * math.pi)

                center_y = mercator(lat)
                occupied = set()
                for flight in flights:
                    position = if_flight_position(flight)
                    if not position:
                        continue
                    x = ((position[1] - lon + 180) % 360 - 180) * world / 360
                    y = (mercator(position[0]) - center_y) * world
                    if abs(x) > width or abs(y) > height:
                        continue
                    spacing = 23 if zoom < 10 else 12
                    cell = (math.floor(x / spacing), math.floor(y / spacing))
                    if cell not in occupied:
                        occupied.add(cell)
                        yield flight, position

            def render_traffic(following):
                nonlocal rendered_traffic, traffic_hidden, traffic_camera
                unchanged = rendered_traffic is state.if_live_flights and traffic_camera == camera
                if traffic_hidden == following and (following or unchanged):
                    return False
                traffic_hidden = following
                if following:
                    aircraft_layer.visible = False
                    return True
                aircraft_layer.visible = True
                if unchanged:
                    return True
                rendered_traffic = state.if_live_flights
                traffic_camera = camera
                next_markers = {}
                for flight, position in visible_traffic(rendered_traffic):
                    flight_id = str(flight["flightId"])
                    marker = traffic_markers.get(flight_id)
                    if marker is None:
                        marker = aircraft_marker(flight, position)
                    else:
                        update_aircraft_marker(marker, flight, position)
                    next_markers[flight_id] = marker
                traffic_markers.clear()
                traffic_markers.update(next_markers)
                aircraft_layer.markers = [traffic_markers[key] for key in sorted(traffic_markers)]
                return True

            async def redraw_after_pan():
                await asyncio.sleep(0.10)
                if live_render_callback is render_refresh and state.overview_live and state.selected_tab_index == 0:
                    if render_traffic(False):
                        aircraft_layer.update()

            async def map_position_changed(e):
                nonlocal camera, camera_task
                center = e.camera.center
                camera = (center.latitude, center.longitude, e.camera.zoom)
                if camera_task is not None:
                    camera_task.cancel()
                camera_task = asyncio.create_task(redraw_after_pan())
                await clamp_position(e)

            live_map.on_position_change = map_position_changed

            def render(update=True):
                nonlocal selected_marker
                flight = state.if_selected_flight
                plan = state.if_selected_flight_plan
                follow_id = state.if_followed_flight_id
                traffic_changed = render_traffic(False)
                position = if_flight_position(flight)
                if position is None:
                    selected_marker = None
                elif selected_marker is None or selected_marker.key != f"selected-{flight['flightId']}":
                    selected_marker = aircraft_marker(flight, position, selected=True)
                else:
                    update_aircraft_marker(selected_marker, flight, position, selected=True)
                selected_layer.markers = [selected_marker] if selected_marker is not None else []

                departure, arrival = flight_airports(flight, plan, state.if_selected_route_start_label, state.if_selected_route_end_label)
                airports.controls = [point_card("Departure", departure, live=True), point_card("Arrival", arrival, live=True)] if flight else []
                airport_layer.markers = []
                for code, is_departure in ((departure, True), (arrival, False)):
                    record = live_airport_record(code)
                    if record:
                        airport_layer.markers.append(overview_endpoint_marker(
                            (record["lat"], record["lon"]), code, departure=is_departure,
                        ))
                points = state.if_selected_route_points
                route_layer.polylines = [ftm.PolylineMarker(
                    coordinates=[ftm.MapLatitudeLongitude(*point) for point in points],
                    color=tokens["accent"], stroke_width=3,
                )] if len(points) >= 2 else []
                timing.controls = [
                    route_metric_item(label, ft.Text(value, size=16, weight=ft.FontWeight.W_800, no_wrap=True))
                    for label, value in zip(("ETD", "ETA", "Flight time", "ETE"), live_flight_timing(flight, plan))
                ]
                timing_panel.visible = bool(flight)
                detail_panel.visible = bool(flight)
                if flight:
                    detail_heading.value = if_airline_name(flight)
                    def measurement(key, unit):
                        number = if_number(flight.get(key), fallback="")
                        return f"{number} {unit}" if number else ""

                    for control, value in zip(detail_values, (
                        flight.get("callsign"), flight.get("username") or flight.get("displayName"),
                        if_aircraft_name(flight), measurement("altitude", "ft"), measurement("speed", "kt"),
                    )):
                        control.value = value or "—"
                    follow_button.content = "Stop following" if follow_id else "Follow"
                status.value = state.if_last_error or (
                    f"{'Following 1 of ' if follow_id else ''}{len(state.if_live_flights):,} aircraft on server · {state.if_last_traffic_refresh}"
                    if state.if_traffic_session else "Connecting to Infinite Flight…"
                )
                server.options = if_session_options()
                server.value = state.if_selected_session_id or None
                server.visible = bool(server.options)
                render_search()
                if update:
                    for control in (status, server, search_results, left_panel, timing_panel,
                                    selected_layer, airport_layer, route_layer):
                        safe_update_control(control)
                    if traffic_changed and aircraft_layer.page:
                        aircraft_layer.update()

            async def render_refresh():
                render()
                if state.if_followed_flight_id:
                    await center_on_flight()

            search.on_change = render_search
            server.on_select = select_server
            flight_panel = ft.Container(
                top=GAP, right=GAP, width=248,
                content=overview_glass_panel(ft.Column(
                    [
                        server, search, search_results, status,
                        ft.TextButton("Refresh traffic", on_click=refresh_live_clicked),
                        ft.TextButton("Open Settings", on_click=lambda e: go_to_tab(10), visible=not bool(if_local_api_key())),
                    ], tight=True, spacing=5,
                ), padding=10),
            )
            detail_heading = ft.Text(size=14, expand=True, weight=ft.FontWeight.W_800,
                                     color=overview_text_color, style=overview_text_style, max_lines=2)
            detail_values = [ft.Text(size=12, color=overview_text_color, style=overview_text_style) for _ in range(5)]
            follow_button = ft.FilledButton("Follow", on_click=toggle_follow)
            detail.controls = [
                ft.Row([detail_heading, ft.IconButton(
                    ft.Icons.CLOSE, tooltip="Close flight details", on_click=clear_selection,
                    width=26, height=26, padding=0, icon_size=17, icon_color="#211D0A", bgcolor="#F5F1E8",
                )], spacing=4),
                *[ft.Column([
                    ft.Text(label, size=10, color=overview_text_color, style=overview_text_style),
                    value,
                ], spacing=1, tight=True) for label, value in zip(
                    ("Callsign", "Pilot", "Aircraft type", "Altitude", "Ground speed"), detail_values,
                )],
                follow_button,
            ]
            detail_panel = overview_glass_panel(detail, padding=10)
            left_panel = ft.Container(
                top=GAP, bottom=GAP, left=GAP, width=airport_card_width,
                content=ft.Column([airports, detail_panel], spacing=GAP, scroll=ft.ScrollMode.AUTO,
                                  horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            )
            timing_panel = ft.Container(
                left=0, right=0, bottom=35, alignment=ft.Alignment(0, 0),
                content=overview_glass_panel(timing, width=metrics_width, padding=10),
            )
            live_render_callback = render_refresh
            render(update=False)
            return ft.Stack(expand=True, clip_behavior=ft.ClipBehavior.HARD_EDGE, controls=[
                ft.Container(left=0, top=0, right=0, bottom=0, content=live_map),
                left_panel, flight_panel, timing_panel,
            ])

        if state.overview_live:
            overview_progress_refresh_callback = None
            ramp_status_refresh_callback = None
            asset = asset_abs_path_if_exists("live-map/index.html")
            if os.name == "nt" and asset and not live_map_unavailable:
                if live_map_process is None:
                    page.run_task(show_live_map, asset.as_uri())
                return ft.Container(expand=True, bgcolor="#101318")
            return live_overview()

        def overview_action(icon, tooltip: str, handler, primary: bool = False) -> ft.IconButton:
            return ft.IconButton(
                icon=icon,
                tooltip=tooltip,
                on_click=handler,
                width=32,
                height=32,
                padding=0,
                icon_size=17,
                bgcolor=tokens["accent"] if primary else tokens["subpanel"],
                icon_color=ft.Colors.WHITE if primary else tokens["text"],
            )

        progress_strip = ft.Container(
            height=overview_progress_height,
            padding=ft.padding.only(left=12, right=12, top=0, bottom=6),
            bgcolor=ft.Colors.TRANSPARENT,
            content=route_line,
        )

        duration_minutes = planned_overview_minutes()
        flight_time_text = ft.Text(
            format_hours_to_hm(duration_minutes / 60.0) if duration_minutes else "—",
            size=18, weight=ft.FontWeight.W_800, color=tokens["text"],
            text_align=ft.TextAlign.CENTER, no_wrap=True,
            tooltip="Planned duration from Dashboard or Fuel Planning",
        )
        status_index = int(state.overview_flight_status_index or 0)
        is_playing = state.overview_progress_running
        route_metrics_card = overview_glass_panel(
            ft.Column(
                spacing=6,
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.Row(
                        spacing=2,
                        controls=[
                            route_metric_item("ETE", overview_ete_value_text),
                            route_metric_item("ETA", overview_eta_value_text),
                            route_metric_item("Flight time", flight_time_text),
                        ],
                    ),
                    ft.Row(
                        spacing=6,
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[
                            overview_action(ft.Icons.SKIP_PREVIOUS, "Previous phase", lambda e: set_overview_status(status_index - 1)),
                            overview_action(ft.Icons.PAUSE if is_playing else ft.Icons.PLAY_ARROW,
                                            "Pause flight progress" if is_playing else "Play flight progress",
                                            toggle_overview_progress, primary=True),
                            overview_action(ft.Icons.SKIP_NEXT, "Next phase", lambda e: set_overview_status(status_index + 1)),
                        ],
                    ),
                ],
            ),
            height=bottom_card_height,
            padding=6,
        )
        return ft.Stack(
            expand=True, clip_behavior=ft.ClipBehavior.HARD_EDGE,
            controls=[
                ft.Container(left=0, top=0, right=0, bottom=0, content=overview_route_map_control()),
                ft.Container(
                    top=GAP, left=GAP, width=airport_card_width,
                    content=ft.Column(
                        spacing=GAP, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                        controls=[point_card("Departure", origin_icao, 4), point_card("Arrival", destination_icao, 5)],
                    ),
                ),
                ft.Container(
                    left=0, right=0, bottom=35,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Container(width=metrics_width, content=route_metrics_card),
                ),
            ],
        )


    def announcement_airport_label(code: str) -> str:
        canonical = normalize_airport_code(code) or (code or "").strip().upper()
        record = lookup_airport_record(canonical)
        if not record:
            return canonical
        airport_name = str(record.get("name") or canonical).strip()
        iata = str(record.get("iata") or "").strip().upper()
        return f"{airport_name} ({iata})" if iata else airport_name

    def announcement_temperature(weather: dict) -> str:
        value = weather.get("temperature_c")
        if value is not None:
            try:
                return str(int(round(float(value))))
            except (TypeError, ValueError):
                pass
        match = re.search(r"-?\d+(?:\.\d+)?", str(weather.get("temperature") or ""))
        return str(int(round(float(match.group(0))))) if match else ""

    def announcement_sky_condition(condition: str) -> str:
        label = (condition or "").strip()
        lowered = label.lower()
        if not label or "unavailable" in lowered:
            return ""
        if "clear" in lowered:
            return "clear skies"
        if "partly" in lowered:
            return "partly cloudy skies"
        if "overcast" in lowered:
            return "overcast skies"
        if "cloud" in lowered:
            return "cloudy skies"
        if "fog" in lowered:
            return "foggy conditions"
        if "thunder" in lowered:
            return "thunderstorms"
        if "snow" in lowered:
            return "snow showers"
        if "rain" in lowered or "drizzle" in lowered or "shower" in lowered:
            return "rain showers"
        return label.lower()

    def announcement_time_to_arrival() -> str:
        distance_to_go = parse_optional_float(landing_distance_to_go_tf.value or "")
        ground_speed = parse_optional_float(landing_ground_speed_tf.value or "")
        if distance_to_go is not None and ground_speed is not None and distance_to_go >= 0 and ground_speed > 0:
            remaining_minutes = max(1, int(round((distance_to_go / ground_speed) * 60.0)))
            return format_hours_to_hm(remaining_minutes / 60.0)
        return header_banner_remaining_time_label() if planned_overview_minutes() else ""

    def build_captain_announcement_card(phase: str, embedded: bool = False) -> ft.Control:
        is_departure = phase == "departure"
        state_field = "captain_departure_announcement_text" if is_departure else "captain_descent_announcement_text"
        expanded_field = "takeoff_announcement_expanded" if is_departure else "descent_announcement_expanded"
        title = "Takeoff Announcement" if is_departure else "Descent Announcement"
        all_languages = supported_languages()
        requested_language_order = ["English", "German", "Arabic", "Italian", "Spanish", "Farsi"]
        language_order = [language for language in requested_language_order if language in all_languages]
        language_order.extend(language for language in all_languages if language not in language_order)
        if state.captain_announcement_language not in language_order:
            state.captain_announcement_language = "English"

        def toggle_expanded(e=None):
            setattr(state, expanded_field, not bool(getattr(state, expanded_field, False)))
            refresh_ui()

        def set_status(message: str, color: Optional[str] = None):
            status_text.value = message
            status_text.color = color or tokens["muted"]

        def set_language(language: str):
            state.captain_announcement_language = language
            state.captain_departure_announcement_text = ""
            state.captain_descent_announcement_text = ""
            state.captain_announcement_text = ""
            refresh_ui()

        def language_segment(language: str) -> ft.Control:
            active = state.captain_announcement_language == language
            return ft.Container(
                expand=True,
                content=ft.GestureDetector(
                    mouse_cursor=ft.MouseCursor.CLICK,
                    on_tap=lambda e, selected=language: set_language(selected),
                    content=ft.Container(
                        height=32,
                        padding=ft.padding.symmetric(horizontal=3, vertical=6),
                        border_radius=9,
                        alignment=ft.Alignment(0, 0),
                        bgcolor=ft.Colors.with_opacity(0.24 if active else 0.06, tokens["accent"] if active else tokens["subpanel"]),
                        border=ft.border.all(1, ft.Colors.with_opacity(0.56 if active else 0.14, tokens["accent"] if active else ft.Colors.WHITE)),
                        content=ft.Text(
                            LANGUAGE_DISPLAY_LABELS.get(language, language),
                            size=10,
                            font_family=rtl_announcement_font if language in RTL_ANNOUNCEMENT_LANGUAGES else UI_FONT,
                            weight=ft.FontWeight.W_800 if active else ft.FontWeight.W_600,
                            color=tokens["text"],
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ),
                ),
            )

        def output_text_control(text: str) -> ft.Control:
            is_rtl = state.captain_announcement_language in RTL_ANNOUNCEMENT_LANGUAGES
            return ft.Text(
                text,
                size=13,
                font_family=rtl_announcement_font if is_rtl else UI_FONT,
                rtl=is_rtl,
                color=tokens["text"],
                text_align=ft.TextAlign.RIGHT if is_rtl else ft.TextAlign.LEFT,
                selectable=True,
            )

        async def generate(e=None):
            language = state.captain_announcement_language if state.captain_announcement_language in all_languages else "English"
            origin = normalize_airport_code(state.departure or takeoff_departure_icao_tf.value) or ""
            destination = normalize_airport_code(state.arrival or landing_arrival_icao_tf.value) or ""
            airline = (state.airline or "").strip()
            aircraft_key = canonical_aircraft_name(state.aircraft) or (state.aircraft or "").strip()
            aircraft_name = str(AIRCRAFT_LIBRARY.get(aircraft_key, {}).get("name") or state.aircraft or "").strip()
            flight_number = (state.flight_number or "").strip()
            state.captain_announcement_generating = True
            generate_button.disabled = True
            generation_progress.visible = True
            set_status("Generating announcement…", tokens["accent"])
            page.update()

            try:
                altitude_input = altitude_tf.value or ""
                altitude_value = parse_optional_float(altitude_input)
                altitude_label = f"{round(altitude_value):,}" if altitude_value is not None else ""
                if is_departure:
                    state.captain_announcement_cruise_altitude_ft = altitude_input
                else:
                    state.captain_announcement_current_altitude_ft = altitude_input
                origin_weather = airport_weather_for_card(origin, fetch=False)
                destination_weather = airport_weather_for_card(destination, fetch=False)

                origin_temperature = announcement_temperature(origin_weather) if is_departure else ""
                destination_temperature = announcement_temperature(destination_weather)
                origin_condition = str(origin_weather.get("condition") or "").replace("Weather unavailable", "").strip()
                destination_condition = str(destination_weather.get("condition") or "").replace("Weather unavailable", "").strip()
                values = {
                    "CAPTAIN NAME": state.dashboard_flight_plan.get("pilot_in_command") or (
                        state.pilot_name if state.pilot_name != "Pilot" else ""
                    ),
                    "AIRLINE": airline,
                    "AIRCRAFT TYPE": aircraft_name,
                    "FLIGHT NUMBER": flight_number,
                    "ORIGIN": announcement_airport_label(origin),
                    "DESTINATION": announcement_airport_label(destination),
                    "FLIGHT TIME": format_hours_to_hm(float(planned_overview_minutes()) / 60.0) if planned_overview_minutes() else "",
                    "CRUISING ALTITUDE": altitude_label if is_departure else "",
                    "CURRENT ALTITUDE": altitude_label if not is_departure else "",
                    "TIME TO ARRIVAL": announcement_time_to_arrival(),
                    "ORIGIN TEMPERATURE": origin_temperature,
                    "ORIGIN WEATHER CONDITION": origin_condition.lower(),
                    "ORIGIN SKY CONDITION": announcement_sky_condition(origin_condition),
                    "DESTINATION TEMPERATURE": destination_temperature,
                    "DESTINATION WEATHER CONDITION": destination_condition.lower(),
                    "DESTINATION SKY CONDITION": announcement_sky_condition(destination_condition),
                    "DESTINATION SKY / PRECIPITATION": announcement_sky_condition(destination_condition),
                }
                announcement = render_announcement(language, phase, values, allow_partial=True)
                setattr(state, state_field, announcement)
                state.captain_announcement_text = announcement
                state.captain_announcement_phase = phase
                output_surface.content = output_text_control(announcement)
                set_status("Announcement ready.", tokens["accent"])
            except Exception as ex:
                setattr(state, state_field, "")
                state.captain_announcement_text = ""
                output_surface.content = ft.Container(height=24)
                set_status(f"Could not generate: {ex}", "#FFB4B4")
            finally:
                state.captain_announcement_generating = False
                generate_button.disabled = False
                generation_progress.visible = False
                page.update()

        altitude_tf = ft.TextField(
            label="Cruising altitude (ft)" if is_departure else "Current altitude (ft)",
            value=(
                state.captain_announcement_cruise_altitude_ft
                if is_departure
                else state.captain_announcement_current_altitude_ft or landing_current_alt_tf.value or ""
            ),
            hint_text="e.g. 35000" if is_departure else "e.g. 12000",
            width=200,
            height=48,
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=12,
            filled=True,
            bgcolor=tokens["input_bg"],
            color=tokens["text"],
            label_style=ft.TextStyle(color=tokens["muted"]),
            hint_style=ft.TextStyle(color=tokens["muted"]),
        )
        status_text = ft.Text("", size=11, color=tokens["muted"])
        generation_progress = ft.ProgressRing(
            width=18,
            height=18,
            stroke_width=2,
            color=tokens["accent"],
            visible=bool(state.captain_announcement_generating),
        )
        generate_button = ft.ElevatedButton(
            "Generate Speech",
            icon=ft.Icons.MIC,
            on_click=generate,
            disabled=bool(state.captain_announcement_generating),
            bgcolor=tokens["primary"],
            color=tokens["on_primary"],
        )
        existing_text = str(getattr(state, state_field, "") or "")
        output_surface = ft.Container(
            padding=14,
            border_radius=16,
            bgcolor=surface_fill(tokens["subpanel"]),
            border=ft.border.all(1, ft.Colors.with_opacity(0.18, ft.Colors.WHITE)),
            content=output_text_control(existing_text) if existing_text else ft.Container(height=24),
        )

        missing_native_language = missing_native_language_for_airline(state.airline)
        language_rows = [
            ft.Row(
                spacing=6,
                controls=[language_segment(language) for language in language_order[index:index + 3]],
            )
            for index in range(0, len(language_order), 3)
        ]
        card_controls: List[ft.Control] = [ft.Column(spacing=7, controls=language_rows), altitude_tf]
        if missing_native_language:
            card_controls.append(ft.Text(f"{missing_native_language} template not supplied", size=10, color=tokens["muted"]))
        card_controls.extend(
            [
                ft.Row(
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[generate_button, generation_progress],
                ),
                status_text,
                output_surface,
            ]
        )
        expanded = embedded or bool(getattr(state, expanded_field, False))
        shell_controls: List[ft.Control] = []
        if not embedded:
            shell_controls.append(
                ft.GestureDetector(
                    mouse_cursor=ft.MouseCursor.CLICK,
                    on_tap=toggle_expanded,
                    content=ft.Container(
                        height=32,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Text(title, size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                                ft.Icon(
                                    ft.Icons.KEYBOARD_ARROW_UP_ROUNDED if expanded else ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED,
                                    size=22,
                                    color=tokens["muted"],
                                ),
                            ],
                        ),
                    ),
                )
            )
        if expanded:
            if not embedded:
                shell_controls.append(ft.Divider(height=10, opacity=0.15))
            shell_controls.append(ft.Column(spacing=12, controls=card_controls))
        return ft.Container(
            content=ft.Column(spacing=10, controls=shell_controls),
            padding=0 if embedded else 16,
            border_radius=0 if embedded else 20,
            bgcolor=ft.Colors.TRANSPARENT if embedded else surface_fill(tokens["panel"]),
            border=None if embedded else ft.border.all(1, tokens["card_border"]),
            shadow=None if embedded else surface_shadow(0.72),
        )

    def build_operations_panel(
        phase: str, warning_host: ft.Control, weight_limit: ft.Text, weight_status: ft.Text,
        weight_controls: List[ft.Control],
    ) -> ft.Control:
        is_departure = phase == "departure"
        announcement_title = "Takeoff Announcement" if is_departure else "Descent Announcement"
        view_field = "takeoff_operations_view" if is_departure else "landing_operations_view"
        panel_view = str(getattr(state, view_field, "menu") or "menu")
        if panel_view not in ("menu", "warnings", "announcement"):
            panel_view = "menu"
            setattr(state, view_field, panel_view)

        def select_view(view_name: str):
            setattr(state, view_field, view_name)
            if view_name == "announcement":
                setattr(state, "takeoff_announcement_expanded" if is_departure else "descent_announcement_expanded", True)
            refresh_ui()

        weight_card = glass_card(
            "Weight and Actions",
            ft.Column(
                weight_controls, spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )
        weight_limit.size = 14
        weight_limit.no_wrap = True
        weight_title = weight_card.content.controls[0]
        weight_title.expand = True
        weight_title.size = weight_limit.size
        weight_title.weight = weight_limit.weight
        weight_title.style = ft.TextStyle(height=1.0)
        weight_title.max_lines = 2
        weight_title.overflow = ft.TextOverflow.ELLIPSIS
        weight_card.content.controls[0] = ft.Row(
            [weight_title, weight_limit], spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        if panel_view == "menu":
            operations_content = ft.Column(
                expand=True, spacing=6, alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.OutlinedButton(
                        "Warnings", icon=ft.Icons.WARNING_AMBER_ROUNDED, height=30,
                        on_click=lambda e: select_view("warnings"),
                    ),
                    ft.OutlinedButton(
                        announcement_title, icon=ft.Icons.RECORD_VOICE_OVER_ROUNDED, height=30,
                        on_click=lambda e: select_view("announcement"),
                    ),
                    weight_status,
                ],
            )
        else:
            if panel_view == "warnings":
                for item in warning_host.controls:
                    if isinstance(item, ft.Text):
                        item.color = tokens["muted"]
                    elif isinstance(item.content, ft.Text):
                        item.content.color = performance_warning_ink(item.content.data)
            content = warning_host if panel_view == "warnings" else build_captain_announcement_card(phase, embedded=True)
            operations_content = ft.Column(
                [content], expand=True, scroll=ft.ScrollMode.AUTO,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )

        operations_card = glass_card("Warnings & Announcements", operations_content, expand=True)
        if panel_view != "menu":
            operations_card.content.controls[0] = ft.Row(
                [
                    ft.IconButton(
                        ft.Icons.ARROW_BACK_ROUNDED, tooltip="Back to operations",
                        width=28, height=28, padding=0, icon_size=17,
                        on_click=lambda e: select_view("menu"),
                    ),
                    ft.Text(
                        "Warnings" if panel_view == "warnings" else announcement_title,
                        size=14, weight=ft.FontWeight.W_700, color=tokens["text"],
                        expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
                spacing=6,
            )

        weight_card.padding = ft.Padding.symmetric(horizontal=10, vertical=14)
        weight_card.content.spacing = 7
        operations_card.padding = 10
        operations_card.content.spacing = 5
        return ft.Column(
            [weight_card, operations_card], spacing=GAP,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )


    def close_dashboard_airport_map():
        nonlocal dashboard_airport_process, dashboard_airport_unavailable
        process = dashboard_airport_process
        dashboard_airport_process = None
        dashboard_airport_unavailable = False
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def set_live_map_visibility(show):
        nonlocal live_map_visible
        if live_map_child and live_map_visible != show:
            ctypes.windll.user32.ShowWindow(ctypes.c_void_p(live_map_child), 4 if show else 0)
            live_map_visible = show

    def close_live_map():
        nonlocal live_map_process, live_map_child, live_map_unavailable, live_render_callback
        process = live_map_process
        set_live_map_visibility(False)
        live_map_process = None
        live_map_child = None
        live_map_unavailable = False
        live_render_callback = None
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    async def show_live_map(url):
        from tempfile import TemporaryDirectory

        nonlocal live_map_process, live_map_unavailable, live_render_callback
        if live_map_process or not state.is_logged_in or state.selected_tab_index != 0 or not state.overview_live:
            return
        with TemporaryDirectory(prefix="fms-live-map-", ignore_cleanup_errors=True) as directory:
            bridge = Path(directory)
            command = [sys.executable]
            if not getattr(sys, "frozen", False):
                command.append(str(Path(__file__).resolve()))
            command += [
                "--globe-webview", "--attach", "--slot", "live-map", "--url", url,
                "--parent-title", page.title, "--storage-path", str(storage_dir / "Live Map Cache"),
                "--live-map-bridge", directory,
            ]
            process = None
            try:
                process = subprocess.Popen(
                    command, cwd=str(base_dir), creationflags=subprocess.CREATE_NO_WINDOW,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                live_map_process = process
                await run_live_map_bridge(process, bridge)
            except OSError:
                pass
            finally:
                if live_map_process is process:
                    close_live_map()
                    if state.is_logged_in and state.selected_tab_index == 0 and state.overview_live:
                        live_map_unavailable = True
                        refresh_active_page()

    async def run_live_map_bridge(process, bridge):
        nonlocal live_render_callback, live_map_child
        user32 = ctypes.windll.user32
        find_child = user32.FindWindowExW
        find_child.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p)
        find_child.restype = ctypes.c_void_p
        child = None
        deadline = time.monotonic() + 12
        snapshot_pending = True
        was_active = False

        async def snapshot_changed():
            nonlocal snapshot_pending
            snapshot_pending = True

        live_render_callback = snapshot_changed
        while live_map_process is process and process.poll() is None:
            active = state.is_logged_in and state.selected_tab_index == 0 and state.overview_live
            if active and not was_active:
                snapshot_pending = True
            was_active = active
            if active and snapshot_pending:
                payload = live_map_snapshot()
                try:
                    temp = bridge / "snapshot.tmp"
                    temp.write_text(json.dumps(payload, ensure_ascii=True, allow_nan=False), encoding="utf-8")
                    temp.replace(bridge / "snapshot.json")
                    snapshot_pending = False
                except OSError:
                    pass
            if not child:
                parents = _enum_windows_by_title(page.title)
                child = find_child(parents[0], None, None, LIVE_MAP_WINDOW) if parents else None
                if not child and time.monotonic() >= deadline:
                    return
            if child:
                live_map_child = child
                show = active and page.window.visible is not False and not page.window.minimized
                set_live_map_visibility(show and not (tutorial_dialog and tutorial_dialog.open))
            actions_path = bridge / "actions.json"
            try:
                actions = json.loads(actions_path.read_text(encoding="utf-8"))
                actions_path.unlink()
            except (OSError, ValueError):
                actions = []
            if active:
                for action in actions:
                    handle_live_map_action(action)
            await asyncio.sleep(0.12)

    def dashboard_departure_icao():
        code = normalize_airport_code(state.departure) or ""
        airport = lookup_airport_record(code) or {}
        icao = str(airport.get("icao") or code).upper()
        return icao if re.fullmatch(r"[A-Z]{4}", icao) else ""

    async def show_dashboard_airport_map(url):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory(prefix="fms-dashboard-", ignore_cleanup_errors=True) as directory:
            await run_dashboard_airport_map(url, Path(directory) / "departure")

    async def run_dashboard_airport_map(url, departure_file):
        nonlocal dashboard_airport_process, dashboard_airport_unavailable
        if dashboard_airport_process or dashboard_airport_unavailable or not state.is_logged_in or state.selected_tab_index != 1:
            return
        command = [sys.executable]
        if not getattr(sys, "frozen", False):
            command.append(str(Path(__file__).resolve()))
        command += [
            "--globe-webview", "--attach", "--slot", "dashboard-airport", "--url", url,
            "--parent-title", page.title, "--storage-path", str(storage_dir / "Airport Map Cache"),
            "--departure-file", str(departure_file),
        ]
        try:
            process = subprocess.Popen(
                command, cwd=str(base_dir), creationflags=subprocess.CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError:
            dashboard_airport_unavailable = True
            refresh_active_page()
            return
        dashboard_airport_process = process
        user32 = ctypes.windll.user32
        find_child = user32.FindWindowExW
        find_child.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p)
        find_child.restype = ctypes.c_void_p
        deadline = time.monotonic() + 12
        parent = child = None
        shown = None
        published_departure = None
        while dashboard_airport_process is process and process.poll() is None:
            departure = dashboard_departure_icao()
            if departure != published_departure:
                try:
                    departure_file.write_bytes(f"{departure or '-'}\n".encode("ascii"))
                    published_departure = departure
                except OSError:
                    pass
            if not child:
                parents = _enum_windows_by_title(page.title) if not parent else ()
                parent = parents[0] if parents else parent
                child = find_child(parent, None, None, DASHBOARD_MAP_WINDOW) if parent else None
                if not child and time.monotonic() >= deadline:
                    break
            if child:
                show = (
                    page.window.visible is not False and not page.window.minimized
                    and not (tutorial_dialog and tutorial_dialog.open)
                    and not (dashboard_remarks_dialog and dashboard_remarks_dialog.open)
                    and not any(isinstance(control, ft.Container) and control.visible for control in page.overlay)
                )
                if shown != show:
                    user32.ShowWindow(ctypes.c_void_p(child), 4 if show else 0)
                    shown = show
            await asyncio.sleep(0.10)
        if dashboard_airport_process is process:
            close_dashboard_airport_map()
            if state.is_logged_in and state.selected_tab_index == 1:
                dashboard_airport_unavailable = True
                refresh_active_page()

    def home_page():
        def home_airline_code(airline_name: Optional[str]) -> str:
            if airline_name and airline_name == canonical_airline_name(state.airline_record.get("name")):
                code = state.airline_record.get("iata") or state.airline_record.get("icao")
                if code:
                    return code
            return AIRLINE_CALLSIGNS.get((airline_name or "").strip(), "--")

        def home_flight_number_suffix(value: Optional[str], airline_name: Optional[str]) -> str:
            text = (value or "").strip()
            if not text:
                return ""
            current_code = home_airline_code(airline_name)
            known_codes = [current_code] + [code for code in AIRLINE_CALLSIGNS.values() if code != current_code]
            for code in known_codes:
                code = (code or "").strip()
                if code and code != "--" and text.upper().startswith(code.upper()):
                    return text[len(code):].strip()
            return text

        def home_full_flight_number(suffix: Optional[str], airline_name: Optional[str]) -> str:
            code = home_airline_code(airline_name)
            number = (suffix or "").strip()
            if number and code and code != "--":
                if number.upper().startswith(code.upper()):
                    return number
                return f"{code}{number}".strip()
            return number

        def update_home_flight_number(e=None):
            state.flight_number = home_full_flight_number(home_flight_number_tf.value, state.airline)

        home_flight_number_tf = ft.TextField(
            label="Flight number",
            value=home_flight_number_suffix(state.flight_number, state.airline),
            prefix=f"{home_airline_code(state.airline)} " if home_airline_code(state.airline) != "--" else None,
            prefix_style=ft.TextStyle(color=tokens["text"], size=14, weight=ft.FontWeight.W_800),
            hint_text="1234",
            height=52,
            border_radius=14,
            filled=True,
            bgcolor=tokens["input_bg"],
            color=tokens["text"],
            label_style=ft.TextStyle(color=tokens["muted"]),
            hint_style=ft.TextStyle(color=tokens["muted"]),
            on_change=update_home_flight_number,
            on_submit=update_home_flight_number,
            on_blur=update_home_flight_number,
        )

        def select_home_airline(record):
            previous = state.airline
            suffix = home_flight_number_suffix(home_flight_number_tf.value or state.flight_number, previous)
            state.airline_record = record or {}
            name = canonical_airline_name(record["name"]) if record else ""
            state.flight_number = home_full_flight_number(suffix, name)
            home_flight_number_tf.value = suffix
            if record:
                set_airline(name)
            else:
                state.airline = ""
                airline_dd.value = None
                home_flight_number_tf.prefix = None
                safe_update_control(home_flight_number_tf)
                refresh_navigation_accent()

        def select_home_aircraft(record):
            state.aircraft_record = record or {}
            state.aircraft = aircraft_value(record) if record else ""
            if record:
                sync_aircraft_across_pages(state.aircraft, update_page=False)
                state.logo_refresh_nonce += 1
                refresh_ui()
            else:
                sync_aircraft_across_pages(None, update_page=False)
                aircraft_image_host.content = None
                aircraft_image_host.visible = False
                safe_update_control(aircraft_image_host)
                refresh_navigation_accent()

        plan_dropdowns = {}

        def airport_search(label, backing, current, update_airport):
            def choose(record):
                if record:
                    remember_airport(record)
                    queue_airport_media(record["code"])
                backing.value = record["code"] if record else ""
                update_airport()
                if record:
                    refresh_ui()

            return aviation_autocomplete(
                label, "airport", current or backing.value, choose, expand=True, dropdown=True,
                commit_airport_code=True, floating_results=plan_dropdowns,
            )

        departure_search = airport_search("Departure", takeoff_departure_icao_tf, state.departure, on_takeoff_departure_changed)
        arrival_search = airport_search("Arrival", landing_arrival_icao_tf, state.arrival, on_landing_arrival_changed)
        airline_search = aviation_autocomplete(
            "Airline", "airline", state.airline, select_home_airline, expand=True, dropdown=True,
            floating_results=plan_dropdowns,
        )
        aircraft_search = aviation_autocomplete(
            "Aircraft", "aircraft", (state.aircraft_record.get("name") or current_aircraft_label()) if state.aircraft else "",
            select_home_aircraft, expand=True, dropdown=True,
            floating_results=plan_dropdowns,
        )
        heading_height = 22
        form_spacing = 1
        plan_spacing = 2
        original_outline_height = 31
        extra_outline_height = original_outline_height * 0.5
        target_field_height = 43 + extra_outline_height

        def fitting_field_height(viewport_height):
            card_height = viewport_height - SHELL_HEIGHT - 4 * GAP - DASHBOARD_DATE_HEIGHT - DASHBOARD_ACTIONS_HEIGHT
            # Reserve room for the card title, section headings, padding, and row gaps.
            form_chrome_height = 50 + 4 * heading_height
            return max(36, min(target_field_height, math.floor((card_height - form_chrome_height) / 8)))

        plan_field_height = fitting_field_height(page.height or 821)
        aircraft_section_height = 3 * plan_field_height + 2 * plan_spacing
        dashboard_aircraft = (
            aircraft_profile_image(state.aircraft, width=676, height=aircraft_section_height)
            if state.aircraft else None
        )
        aircraft_image_host = ft.Container(
            expand=True, height=aircraft_section_height, alignment=ft.Alignment(0, 0), content=dashboard_aircraft,
        )

        plan_fields = []

        def size_plan_field(field, height):
            field.height = height
            field.content_padding = ft.Padding.symmetric(
                horizontal=10, vertical=max(9, 9 + (height - 43) / 2),
            )

        def style_plan_field(field):
            plan_fields.append(field)
            size_plan_field(field, plan_field_height)
            field.dense = True
            field.text_size = 16
            field.text_style = ft.TextStyle(font_family=UI_FONT, size=16, color=tokens["text"])
            field.label_style = ft.TextStyle(font_family=UI_FONT, size=16, color=tokens["muted"])
            field.hint_style = ft.TextStyle(font_family=UI_FONT, size=16, color=tokens["muted"])
            field.suffix_style = ft.TextStyle(font_family=UI_FONT, size=15, color=tokens["muted"])
            if field.prefix_style:
                field.prefix_style = field.prefix_style.copy(font_family=UI_FONT, size=16)
            return field

        for picker in (departure_search, arrival_search, airline_search, aircraft_search):
            style_plan_field(picker.controls[0])
            picker.expand = None

        def plan_field(label, key, *, suffix=None, hint=None, numeric=False, multiline=False, expand=True):
            def store(e):
                value = (field.value or "").strip()
                if key == "flight_time":
                    match = re.fullmatch(r"(\d{1,3}):([0-5]\d)", value)
                    minutes = int(match[1]) * 60 + int(match[2]) if match else 0
                    error = "Use hours and minutes, e.g. 06:30." if value and not minutes else None
                    if error is None:
                        state.overview_flight_time_minutes = minutes
                else:
                    error = "Enter a whole number." if numeric and value and not re.fullmatch(r"[0-9]+", value) else None
                if error is None:
                    if value:
                        state.dashboard_flight_plan[key] = value
                    else:
                        state.dashboard_flight_plan.pop(key, None)
                if field.tooltip != error:
                    field.tooltip = error
                    field.border_color = "#B3261E" if error else tokens["card_border"]
                    safe_update_control(field)

            field = ft.TextField(
                label=label, value=(
                    f"{planned_overview_minutes() // 60:02d}:{planned_overview_minutes() % 60:02d}"
                    if key == "flight_time" and planned_overview_minutes()
                    else state.dashboard_flight_plan.get(key, "")
                ),
                suffix=suffix, hint_text=hint, keyboard_type=ft.KeyboardType.NUMBER if numeric else ft.KeyboardType.TEXT,
                border_radius=14, filled=True, bgcolor=tokens["input_bg"], color=tokens["text"],
                dense=True, expand=expand, multiline=multiline, min_lines=2 if multiline else 1,
                max_lines=3 if multiline else 1, on_change=store,
            )
            return style_plan_field(field)

        def open_remarks(e):
            nonlocal dashboard_remarks_dialog
            entry = ft.TextField(
                label="Remarks", value=state.dashboard_flight_plan.get("remarks", ""),
                multiline=True, min_lines=4, max_lines=9, width=410,
                text_style=ft.TextStyle(font_family=UI_FONT, size=16),
                label_style=ft.TextStyle(font_family=UI_FONT, size=16),
            )

            def save_remarks(e):
                remarks.value = entry.value or ""
                remarks.on_change(e)
                page.pop_dialog()
                safe_update_control(remarks)

            dashboard_remarks_dialog = ft.AlertDialog(
                title=ft.Text("Flight plan remarks"), content=entry, modal=True,
                actions=[ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog()),
                         ft.FilledButton("Save", on_click=save_remarks)],
            )
            show_alert(dashboard_remarks_dialog)

        cabin_capacity = sum(seat_model.get("totals", {}).values()) if seat_model.get("generated") else 0
        flight_time = plan_field("Flight time", "flight_time", hint="HH:MM")
        remarks = plan_field("Remarks", "remarks")
        pilot = plan_field("Pilot in command", "pilot_in_command")
        route_fields = [
            ("Dep. gate", takeoff_gate_tf), ("Dep. terminal", takeoff_terminal_tf),
            ("Arr. gate", landing_gate_tf), ("Arr. terminal", landing_terminal_tf),
        ]
        gate_state_keys = {
            "Departure gate": "departure_gate", "Departure terminal": "departure_terminal",
            "Arrival gate": "arrival_gate", "Arrival terminal": "arrival_terminal",
        }
        gate_fields = []
        for label, backing in route_fields:
            field = ft.TextField(label=label, value=backing.value, expand=True, filled=True,
                                 border_radius=14, bgcolor=tokens["input_bg"], color=tokens["text"],
                                 tooltip=backing.label)
            def save_gate(e, target=backing):
                target.value = e.control.value
                setattr(state, gate_state_keys[target.label], (target.value or "").strip())
            field.on_change = save_gate
            gate_fields.append(style_plan_field(field))

        def plan_heading(title):
            return ft.Container(
                height=heading_height,
                content=ft.Text(title, size=12, weight=ft.FontWeight.W_700, color=tokens["muted"]),
            )

        dropdown_rows = {}
        for label, results in plan_dropdowns.items():
            results.expand = True
            spacer = ft.Container(expand=True)
            dropdown_rows[label] = ft.Row(
                [spacer, results] if label == "Arrival" else [results, spacer],
                left=0, right=0, spacing=6 if label in ("Departure", "Arrival") else 8,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )

        def position_dropdowns(field_height):
            route_top = heading_height + form_spacing
            operator_top = 2 * heading_height + 2 * field_height + 4 * form_spacing
            for label in ("Departure", "Arrival"):
                dropdown_rows[label].top = route_top + field_height
            dropdown_rows["Airline"].top = operator_top + field_height
            dropdown_rows["Aircraft"].top = operator_top + 2 * field_height + plan_spacing

        position_dropdowns(plan_field_height)

        plan_form = ft.Column(
            spacing=form_spacing, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                plan_heading("Route"),
                ft.Row([ft.Container(expand=True, content=departure_search),
                        ft.Container(expand=True, content=arrival_search)],
                       spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Row(gate_fields, spacing=6),
                plan_heading("Operator and Aircraft"),
                ft.Row([
                    ft.Column([airline_search, aircraft_search, style_plan_field(home_flight_number_tf)],
                              expand=True, spacing=plan_spacing, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                    aircraft_image_host,
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                plan_heading("Cruise and Timing"),
                ft.Row([
                    plan_field("Cruising speed", "cruise_speed", suffix="kt", numeric=True),
                    plan_field("Cruising altitude", "cruise_altitude", suffix="ft", numeric=True),
                    flight_time,
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
                plan_heading("Supplementary Information"),
                ft.Row([
                    plan_field("Seat capacity", "seat_capacity", hint=str(cabin_capacity) if cabin_capacity else None,
                               numeric=True, expand=3),
                    plan_field("Persons on board", "persons_on_board", numeric=True, expand=3),
                    plan_field("Aircraft color and markings", "aircraft_markings", expand=5),
                ], spacing=6),
                ft.Row([pilot, remarks, ft.IconButton(ft.Icons.OPEN_IN_FULL, tooltip="Expand remarks",
                                                      width=36, height=34, on_click=open_remarks)],
                       spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
            ],
        )
        plan_card = glass_card(
            "Flight Plan",
            ft.Stack(
                expand=True, fit=ft.StackFit.EXPAND,
                controls=[plan_form, *dropdown_rows.values()],
            ),
        )
        plan_card.padding = 10
        plan_card.content.controls[0].size = 17
        plan_card.content.spacing = plan_spacing

        def resize_flight_plan(e):
            height = fitting_field_height(e.height)
            if height == plan_fields[0].height:
                return
            for field in plan_fields:
                size_plan_field(field, height)
            position_dropdowns(height)
            image_height = 3 * height + 2 * plan_spacing
            aircraft_image_host.height = image_height
            if dashboard_aircraft is not None:
                dashboard_aircraft.height = image_height
            safe_update_control(plan_card)

        page.on_resize = resize_flight_plan

        backdrop = airline_background(state.airline, AIRLINE_ACCENT)
        date_surface = blend_hex_colors(backdrop.colors[0], tokens["bg"], SURFACE_OPACITY) if backdrop else tokens["bg"]
        date_ink = max(("#111318", "#FFFFFF"), key=lambda color: contrast_ratio(color, date_surface))
        for date_control in (dashboard_weekday_text, dashboard_date_text, dashboard_year_text):
            date_control.color = date_ink
            date_control.style = ft.TextStyle(
                shadow=[
                    ft.BoxShadow(color=ft.Colors.with_opacity(0.28, ft.Colors.BLACK),
                                 offset=ft.Offset(-0.7, -0.7), blur_radius=0.7),
                    ft.BoxShadow(color=ft.Colors.with_opacity(0.5, ft.Colors.WHITE),
                                 offset=ft.Offset(0.9, 1.1), blur_radius=0.9),
                ],
            )
        date_display = ft.Row(
            [dashboard_weekday_text, dashboard_date_text, dashboard_year_text],
            alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )
        flight_actions = ft.Row(
            alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=GAP,
            controls=[
                ft.FilledButton(
                    "Pause", icon=ft.Icons.PAUSE_ROUNDED, width=108, height=40,
                    tooltip="Save this flight to resume after the next login",
                    style=ft.ButtonStyle(
                        bgcolor=LIGHT["accent"], color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=10),
                    ),
                    on_click=save_current_flight_hibernation,
                ),
                ft.FilledButton(
                    "End Flight", icon=ft.Icons.FLAG_ROUNDED, width=158, height=48,
                    style=ft.ButtonStyle(
                        bgcolor="#B3261E", color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=10),
                        text_style=ft.TextStyle(size=14, weight=ft.FontWeight.W_700),
                    ),
                    on_click=show_flight_end_summary,
                ),
            ],
        )
        plan_host = ft.Container(
            expand=True, content=plan_card,
        )

        map_path = asset_abs_path_if_exists("airport-map.html")
        map_params = {"theme": "dark" if page.theme_mode == ft.ThemeMode.DARK else "light"}
        departure_icao = dashboard_departure_icao()
        if departure_icao:
            map_params["icao"] = departure_icao
        map_url = f"{map_path.as_uri()}#{urllib.parse.urlencode(map_params)}" if map_path else ""
        embedded = os.name == "nt" and bool(map_url) and not dashboard_airport_unavailable
        if embedded:
            page.run_task(show_dashboard_airport_map, map_url)
        airport_card = glass_card(
            "Airport Map",
            ft.Container(
                expand=True, alignment=ft.Alignment(0, 0),
                content=ft.Text("Loading airport map…", color=tokens["muted"]) if embedded else (
                    ft.OutlinedButton("Open airport map", on_click=lambda e: page.launch_url(map_url))
                    if map_url else ft.Text("Airport map unavailable.", color=tokens["muted"])
                ),
            ),
        )

        return build_tab_page(
            "HOME",
            ft.Container(
                expand=True, padding=GAP,
                content=ft.Column(
                    expand=True, spacing=GAP, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    controls=[
                        ft.Container(height=DASHBOARD_DATE_HEIGHT, content=date_display),
                        ft.Row(
                            [plan_host, ft.Container(expand=True, content=airport_card)],
                            expand=True, spacing=GAP,
                            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                        ),
                        ft.Container(height=DASHBOARD_ACTIONS_HEIGHT, content=flight_actions),
                    ],
                ),
            ),
        )


    def set_clock_source(phase: str, source: str):
        is_departure = phase == "departure"
        source = source if source in ("route", "device", "simulation") else "route"
        if is_departure:
            state.takeoff_clock_source = source
            state.takeoff_clock_menu_open = False
        else:
            state.landing_clock_source = source
            state.landing_clock_menu_open = False
        save_settings_data()
        refresh_header_texts()
        refresh_active_page()

    def build_phase_clock_content(phase: str) -> ft.Control:
        is_departure = phase == "departure"
        selected_source = getattr(state, "takeoff_clock_source" if is_departure else "landing_clock_source", "route")
        analog_host = takeoff_analog_clock_host if is_departure else landing_analog_clock_host
        date_text = takeoff_date_text if is_departure else landing_date_text
        local_text = takeoff_route_time_text if is_departure else landing_route_time_text
        utc_text = takeoff_time_text if is_departure else landing_time_text
        source_text = takeoff_clock_source_text if is_departure else landing_clock_source_text

        source_labels = [
            ("route", "Route local"),
            ("device", "My location"),
            ("simulation", "Simulation"),
        ]
        clock = with_hover(ft.PopupMenuButton(
            tooltip="Choose clock source",
            padding=0,
            bgcolor=surface_fill(tokens["panel"]),
            content=ft.Column(
                spacing=4,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    analog_host,
                    date_text,
                    local_text,
                    utc_text,
                    ft.Row(
                        tight=True,
                        spacing=4,
                        controls=[source_text, ft.Icon(ft.Icons.EXPAND_MORE, size=14, color=tokens["accent"])],
                    ),
                ],
            ),
            items=[
                ft.PopupMenuItem(
                    content=label,
                    checked=key == selected_source,
                    height=38,
                    on_click=lambda e, source=key: set_clock_source(phase, source),
                )
                for key, label in source_labels
            ],
        ))

        def fit_clock(width, height):
            diameter = max(64, min(240, int(width) - 4, int(height) - 89))
            if analog_host.width != diameter:
                analog_host.width = analog_host.height = diameter
                moment, _ = phase_clock_moment(phase)
                analog_host.content = build_analog_clock_face(moment, diameter)
                safe_update_control(analog_host)

        fit_clock((page.width or 1344) * 0.28, estimated_performance_top_height() - 53)
        return ft.Container(
            expand=True, alignment=ft.Alignment(0, 0),
            on_size_change=lambda e: fit_clock(e.width, e.height),
            content=clock,
        )

    def checklist_page():
        section_by_key = {section["key"]: section for section in CHECKLIST_SECTIONS}
        selected_key = str(getattr(state, "checklist_section", "turn_on_aircraft") or "turn_on_aircraft")
        if selected_key not in section_by_key:
            selected_key = CHECKLIST_SECTIONS[0]["key"]
            state.checklist_section = selected_key
        selected_section = section_by_key[selected_key]
        completed_indices = {
            int(index)
            for index in getattr(state, "checklist_completed", {}).get(selected_key, [])
            if isinstance(index, int) or str(index).isdigit()
        }

        def section_progress(section: dict) -> tuple[int, int]:
            indices = {
                int(index)
                for index in getattr(state, "checklist_completed", {}).get(section["key"], [])
                if isinstance(index, int) or str(index).isdigit()
            }
            total = len(section["items"])
            return len([index for index in indices if 0 <= index < total]), total

        def choose_section(section_key: str):
            state.checklist_section = section_key
            refresh_active_page()

        def set_item_complete(item_index: int, is_complete: bool):
            current = {
                int(index)
                for index in getattr(state, "checklist_completed", {}).get(selected_key, [])
                if isinstance(index, int) or str(index).isdigit()
            }
            if is_complete:
                current.add(item_index)
            else:
                current.discard(item_index)
            state.checklist_completed[selected_key] = sorted(current)
            refresh_active_page()

        def set_all_complete(is_complete: bool):
            state.checklist_completed[selected_key] = list(range(len(selected_section["items"]))) if is_complete else []
            refresh_active_page()

        def move_section(delta: int):
            current_index = next((index for index, section in enumerate(CHECKLIST_SECTIONS) if section["key"] == selected_key), 0)
            next_index = max(0, min(len(CHECKLIST_SECTIONS) - 1, current_index + delta))
            choose_section(CHECKLIST_SECTIONS[next_index]["key"])

        section_buttons: List[ft.Control] = []
        for section in CHECKLIST_SECTIONS:
            done, total = section_progress(section)
            is_selected = section["key"] == selected_key
            is_complete = total > 0 and done == total
            button_color = ft.Colors.GREEN_700 if is_complete else (tokens["accent"] if is_selected else tokens["subpanel"])
            text_color = ft.Colors.WHITE if is_complete or is_selected else tokens["text"]
            section_buttons.append(
                ft.ElevatedButton(
                    f"{section['title']}  {done}/{total}",
                    icon=ft.Icons.CHECK_CIRCLE_ROUNDED if is_complete else ft.Icons.CHECKLIST_ROUNDED,
                    height=44,
                    bgcolor=button_color,
                    color=text_color,
                    on_click=lambda e, key=section["key"]: choose_section(key),
                )
            )

        checklist_rows: List[ft.Control] = []
        for item_index, (label, action) in enumerate(selected_section["items"]):
            is_complete = item_index in completed_indices
            checklist_rows.append(
                ft.Container(
                    height=64,
                    padding=ft.padding.symmetric(horizontal=16, vertical=8),
                    border_radius=14,
                    bgcolor=tokens["pressed"] if is_complete else tokens["subpanel"],
                    border=ft.border.all(1, ft.Colors.with_opacity(0.45 if is_complete else 1.0, tokens["accent"] if is_complete else tokens["card_border"])),
                    shadow=surface_shadow(0.24, pressed=is_complete),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Row(
                                expand=True,
                                spacing=12,
                                controls=[
                                    ft.Checkbox(
                                        value=is_complete,
                                        active_color=tokens["accent"],
                                        on_change=lambda e, index=item_index: set_item_complete(index, bool(e.control.value)),
                                    ),
                                    ft.Text(label, size=14, weight=ft.FontWeight.W_700, color=tokens["text"]),
                                ],
                            ),
                            ft.Text(
                                action,
                                size=13,
                                weight=ft.FontWeight.W_800,
                                color=ft.Colors.GREEN_400 if is_complete else tokens["accent"],
                                text_align=ft.TextAlign.RIGHT,
                            ),
                        ],
                    ),
                )
            )

        completed_count = len(completed_indices)
        total_count = len(selected_section["items"])
        checklist_card = glass_card(
            selected_section["title"],
            ft.Column(
                expand=True,
                spacing=12,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(f"{completed_count} of {total_count} items complete", size=12, color=tokens["muted"]),
                            ft.ProgressBar(
                                width=300,
                                value=(completed_count / total_count) if total_count else 0,
                                color=ft.Colors.GREEN_400 if completed_count == total_count else tokens["accent"],
                                bgcolor=tokens["pressed"],
                            ),
                        ],
                    ),
                    ft.Container(
                        expand=True,
                        content=ft.ListView(expand=True, spacing=10, controls=checklist_rows),
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.OutlinedButton(
                                "Back",
                                icon=ft.Icons.CHEVRON_LEFT,
                                disabled=selected_key == CHECKLIST_SECTIONS[0]["key"],
                                on_click=lambda e: move_section(-1),
                            ),
                            ft.Row(
                                spacing=10,
                                controls=[
                                    ft.OutlinedButton("Reset section", icon=ft.Icons.RESTART_ALT_ROUNDED, on_click=lambda e: set_all_complete(False)),
                                    ft.ElevatedButton("Check all", icon=ft.Icons.DONE_ALL_ROUNDED, bgcolor=tokens["primary"], color=tokens["on_primary"], on_click=lambda e: set_all_complete(True)),
                                    ft.OutlinedButton(
                                        "Next",
                                        icon=ft.Icons.CHEVRON_RIGHT,
                                        disabled=selected_key == CHECKLIST_SECTIONS[-1]["key"],
                                        on_click=lambda e: move_section(1),
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            expand=True,
        )

        return build_tab_page(
            "CHECKLIST",
            ft.Container(
                expand=True,
                padding=18,
                content=ft.Column(
                    expand=True,
                    spacing=16,
                    controls=[
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=section_buttons),
                        ft.Container(expand=True, content=checklist_card),
                    ],
                ),
            ),
            overlay_opacity=0.08,
        )


    PERFORMANCE_TOP_WIDTHS = (44, 26, 30)
    PERFORMANCE_METRIC_SIZE = 27

    def estimated_performance_top_height():
        return round(((page.height or 821) - SHELL_HEIGHT - 4 * GAP - 28) * 3 / 5)

    def aligned_planning_row(*panels, widths, expand=None):
        return ft.Row(
            expand=expand, spacing=GAP,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH if expand else ft.CrossAxisAlignment.START,
            controls=[ft.Container(expand=width, content=panel) for panel, width in zip(panels, widths)],
        )

    def performance_page(top_row, results_row, professional_panels):
        def route_airport(code):
            canonical = normalize_airport_code(code)
            airport = lookup_airport_record(canonical) or {}
            return airport.get("iata") or canonical or "—"

        route = f"{route_airport(state.departure)} - {route_airport(state.arrival)}" if state.departure or state.arrival else ""
        summary = "  ·  ".join(part for part in (
            state.airline, current_aircraft_label() if state.aircraft else "", state.flight_number, route,
        ) if part)

        def open_professional_details(e):
            show_alert(ft.AlertDialog(
                modal=True,
                title=ft.Text("Professional details"),
                content=ft.Column(
                    professional_panels, width=min(850, (page.width or 984) - 100),
                    height=min(590, (page.height or 681) - 180),
                    spacing=GAP, scroll=ft.ScrollMode.AUTO,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                actions=[ft.TextButton("Done", on_click=lambda e: page.pop_dialog())],
            ))

        return ft.Container(
            expand=True, padding=GAP,
            content=ft.Column(
                spacing=GAP, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Container(
                        height=28, padding=ft.Padding.symmetric(horizontal=4),
                        content=ft.Row([
                            ft.Text(
                                summary, expand=True, size=20, weight=ft.FontWeight.W_700,
                                color=tokens["text"], no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                                tooltip=summary or None,
                            ),
                            *([ft.OutlinedButton(
                                "Professional details", height=28, on_click=open_professional_details,
                            )] if professional_panels else []),
                        ]),
                    ),
                    top_row,
                    results_row,
                ],
            ),
        )

    def compact_performance_input(field, height=40):
        field.height = height
        field.text_size = 13
        field.label_style = ft.TextStyle(size=12, color=tokens["muted"])
        field.content_padding = ft.Padding.symmetric(horizontal=8, vertical=7)
        return field

    flag_catalog_file = asset_abs_path_if_exists("flags/country.json")
    flag_catalog = json.loads(flag_catalog_file.read_text(encoding="utf-8")) if flag_catalog_file else []
    flag_codes = {entry["name"].casefold(): entry["code"] for entry in flag_catalog}
    flag_names = {entry["code"]: entry["name"] for entry in flag_catalog}
    region_catalog_file = asset_abs_path_if_exists("airport_regions.json")
    airport_regions = json.loads(region_catalog_file.read_text(encoding="utf-8")) if region_catalog_file else {}

    def performance_airport_weather(role, raw_metar, status, fetch_weather):
        airport_code = normalize_airport_code(getattr(state, role)) or ""
        record = lookup_airport_record(airport_code) or {}
        airport_name = record.get("name") or (
            "Airport name unavailable" if airport_code else "Select an airport on Dashboard"
        )
        region_code = record.get("region_code") or (record.get("source_record") or {}).get("iso_region", "")
        region_name = airport_regions.get(region_code, "")
        queue_airport_media(airport_code)
        observation = airport_weather_cache.get(airport_code, {}).get("report") or {}
        _, condition = metar_condition(observation)
        temperature = observation.get("temp")
        temperature_label = f"{temperature:.0f}°C" if isinstance(temperature, (int, float)) else "—"
        direction = observation.get("wdir")
        direction_label = f"{direction:03.0f}°" if isinstance(direction, (int, float)) else "—"
        if direction == "VRB":
            direction_label = "VRB"
        wind_speed = observation.get("wspd")
        wind_gust = observation.get("wgst")
        wind_label = f"{direction_label}  ·  {wind_speed:.0f} kt" if isinstance(wind_speed, (int, float)) else "Wind unavailable"
        weather_icons = {
            "Clear": ft.Icons.WB_SUNNY,
            "Partly cloudy": ft.Icons.FILTER_DRAMA,
            "Cloudy": ft.Icons.CLOUD,
            "Overcast": ft.Icons.CLOUD,
            "Rain": ft.Icons.WATER_DROP,
            "Drizzle": ft.Icons.WATER_DROP,
            "Fog": ft.Icons.FOGGY,
            "Mist": ft.Icons.FOGGY,
            "Haze": ft.Icons.FOGGY,
            "Thunderstorms": ft.Icons.THUNDERSTORM,
            "Snow": ft.Icons.AC_UNIT,
            "Freezing precipitation": ft.Icons.AC_UNIT,
        }
        windy = isinstance(wind_speed, (int, float)) and wind_speed >= 19
        if windy and condition in ("Clear", "Partly cloudy", "Cloudy", "Overcast", "Weather unavailable"):
            condition = "Windy"
        weather_icon = ft.Icons.AIR if condition == "Windy" else weather_icons.get(condition, ft.Icons.DEVICE_THERMOSTAT)

        country = (record.get("country") or "").strip().casefold()
        country_code = flag_codes.get(country, country)
        flag_path = asset_rel_path_if_exists(f"flags/{country_code}.svg") if re.fullmatch(r"[a-z]{2}", country_code) else None
        latitude, longitude = record.get("lat"), record.get("lon")
        coordinates = ""
        if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
            coordinates = f"{abs(latitude):.3f}°{'N' if latitude >= 0 else 'S'}  ·  {abs(longitude):.3f}°{'E' if longitude >= 0 else 'W'}"

        airport_code_text = ft.Text(
            airport_code or "—", weight=ft.FontWeight.W_800, color=tokens["text"],
            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, style=ft.TextStyle(height=1.0),
        )
        airport_name_text = ft.Text(
            airport_name, weight=ft.FontWeight.W_500, color=tokens["text"],
            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, tooltip=airport_name,
            style=ft.TextStyle(height=1.15),
        )
        airport_tile = glass_card(
            "Airport",
            ft.Column(
                expand=True, spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Column(
                        [
                            airport_code_text, airport_name_text,
                            *([ft.Text(region_name, size=13, color=tokens["muted"], no_wrap=True,
                                       overflow=ft.TextOverflow.ELLIPSIS, tooltip=region_name,
                                       style=ft.TextStyle(height=1.1))] if region_name else []),
                        ],
                        expand=True, spacing=4,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    *([ft.Row([
                        ft.Icon(ft.Icons.LOCATION_ON_OUTLINED, size=15, color=tokens["accent"]),
                        ft.Text(coordinates, size=12, color=tokens["muted"], no_wrap=True),
                    ], spacing=6)] if coordinates else []),
                ],
            ),
            expand=True,
        )
        if flag_path:
            flag = ft.Image(
                src=flag_path, width=27, height=20, fit=ft.BoxFit.CONTAIN,
                semantics_label=f"{flag_names.get(country_code, country_code.upper())} flag",
            )
            airport_tile.content.controls[0] = ft.Row(
                [airport_tile.content.controls[0], ft.Container(
                    content=flag, border_radius=3, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    tooltip=flag.semantics_label,
                )],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )

        temperature_text = ft.Text(
            temperature_label, weight=ft.FontWeight.W_800, color=tokens["text"], no_wrap=True,
        )
        condition_icon = ft.Icon(weather_icon, color=tokens["accent"], tooltip=condition)
        gust = isinstance(wind_gust, (int, float)) and wind_gust > 0
        pressure = observation.get("altim")
        dew_point = observation.get("dewp")
        details = []
        if isinstance(pressure, (int, float)):
            pressure_hpa = pressure * 33.8639 if pressure < 100 else pressure
            details.append(f"QNH {pressure_hpa:.0f} hPa")
        if isinstance(dew_point, (int, float)):
            details.append(f"Dew {dew_point:.0f}°C")

        weather_tile = glass_card(
            "Weather",
            ft.Column(
                expand=True, spacing=6,
                controls=[
                    ft.Column(
                        [
                            ft.Row([temperature_text, condition_icon], spacing=8),
                            ft.Text(condition, size=16, weight=ft.FontWeight.W_500, color=tokens["text"]),
                        ],
                        expand=True, spacing=2, alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.AIR, size=16, color=tokens["accent"]),
                            ft.Text(wind_label, size=14, color=tokens["text"], no_wrap=True),
                            *([ft.Text(f"Gust {wind_gust:.0f} kt", size=12, weight=ft.FontWeight.W_600,
                                       color=tokens["text"], no_wrap=True)] if gust else []),
                        ],
                        spacing=6,
                    ),
                    *([ft.Text("  ·  ".join(details), size=12, color=tokens["muted"], no_wrap=True)]
                      if details else []),
                ],
            ),
            expand=True,
        )
        observed_at = re.search(r"\b\d{2}(\d{2})(\d{2})Z\b", observation.get("rawOb") or "")
        if observed_at:
            weather_tile.content.controls[0] = ft.Row(
                [
                    weather_tile.content.controls[0],
                    ft.Text(f"{observed_at[1]}:{observed_at[2]}Z", size=11, color=tokens["muted"],
                            tooltip="METAR observation time in UTC"),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )

        raw = (raw_metar.value or "").strip()
        report_station = re.search(r"\b([A-Z0-9]{4})\s+\d{6}Z\b", raw)
        report = raw if report_station and report_station[1] == airport_code else ""
        pending = role in performance_metar_requests
        if report:
            metar_content = ft.Column(
                expand=True, scroll=ft.ScrollMode.AUTO,
                controls=[ft.Text(report, selectable=True, size=14, color=tokens["text"])],
            )
        else:
            fetch_style = button_style(tokens, primary=True)
            accent = tokens["accent"]
            fetch_style.bgcolor = {
                ft.ControlState.DEFAULT: accent,
                ft.ControlState.HOVERED: blend_hex_colors(accent, tokens["text"], 0.12),
                ft.ControlState.PRESSED: blend_hex_colors(accent, tokens["text"], 0.20),
                ft.ControlState.DISABLED: blend_hex_colors(accent, tokens["panel"], 0.16),
            }
            fetch_style.color = LIGHT["text"] if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.WHITE
            metar_content = ft.Container(
                expand=True, alignment=ft.Alignment(0, 0),
                content=ft.FilledButton(
                    "Fetching METAR…" if pending else "Fetch METAR",
                    icon=ft.Icons.DOWNLOAD_OUTLINED, on_click=fetch_weather,
                    disabled=pending or not re.fullmatch(r"[A-Z0-9]{4}", airport_code),
                    style=fetch_style,
                ),
            )

        metar_tile = glass_card("METAR", metar_content, expand=True)
        metar_tile.padding = 10
        metar_tile.content.spacing = 5
        if report:
            metar_tile.content.controls[0] = ft.Row(
                [metar_tile.content.controls[0], ft.IconButton(
                    ft.Icons.REFRESH, tooltip="Refresh METAR", on_click=fetch_weather, disabled=pending,
                    width=30, height=30, padding=0, icon_size=18,
                )],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
        message = "Refreshing METAR…" if report and pending else status.value
        if message:
            metar_tile.content.controls.append(ft.Text(message, size=12, color=tokens["muted"]))

        def airport_weather_height(width, height):
            # Keep the tiles square when space permits and reserve room for METAR on wide screens.
            return min(round((width - GAP) / 2), round(height) - GAP - 82)

        def size_airport_weather_text(width, height):
            tile_width = (width - GAP) / 2
            size_cap = max(42, round((height - 110) * 0.5))
            airport_code_text.size = min(64, size_cap, max(39, round(tile_width * 0.22)))
            airport_name_text.size = min(23, max(16, round(tile_width * 0.065)))
            temperature_text.size = min(68, size_cap, max(42, round(tile_width * 0.23)))
            condition_icon.size = min(40, max(27, round(tile_width * 0.14)))

        width_share = PERFORMANCE_TOP_WIDTHS[0] / sum(PERFORMANCE_TOP_WIDTHS)
        estimated_width = ((page.width or 1344) - 4 * GAP) * width_share
        initial_height = airport_weather_height(estimated_width, estimated_performance_top_height())
        size_airport_weather_text(estimated_width, initial_height)
        airport_weather_row = ft.Container(
            height=initial_height,
            content=ft.Row(
                [airport_tile, weather_tile], spacing=GAP,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

        def fit_airport_weather(e):
            airport_weather_row.height = airport_weather_height(e.width, e.height)
            size_airport_weather_text(e.width, airport_weather_row.height)
            safe_update_control(airport_weather_row)

        return ft.Container(
            on_size_change=fit_airport_weather,
            content=ft.Column(
                [airport_weather_row, metar_tile], spacing=GAP,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

    def takeoff_view():
        professional_info = bool(getattr(state, "professional_info_enabled", False))
        airport_weather_card = performance_airport_weather(
            "departure", takeoff_raw_metar_tf, takeoff_metar_status_text, do_fetch_takeoff_metar,
        )

        runway_config_card = glass_card(
            "Runway and Configuration",
            ft.Column(
                spacing=12,
                controls=[
                    ft.Row(wrap=True, spacing=12, controls=[takeoff_runway_heading_tf, takeoff_slope_tf, takeoff_surface_dd]),
                    ft.Row(wrap=True, spacing=12, controls=[takeoff_tora_tf, takeoff_toda_tf, takeoff_asda_tf]),
                ],
            ),
            height=205,
        )

        live_clock_card = glass_card(
            "Local Clock",
            build_phase_clock_content("departure"),
        )

        takeoff_status_text.size = 11
        takeoff_operations_card = build_operations_panel(
            "departure", takeoff_warning_host, takeoff_mtow_value_text, takeoff_status_text,
            [
                compact_performance_input(takeoff_weight_tf, height=36),
                ft.Row(
                    wrap=True,
                    spacing=8,
                    controls=[
                        ft.ElevatedButton("Compute", on_click=do_compute_takeoff, bgcolor=tokens["primary"], color=tokens["on_primary"]),
                        ft.OutlinedButton("Reset", on_click=do_reset_takeoff),
                        ft.OutlinedButton("Save", on_click=do_save_takeoff_log),
                    ],
                ),
            ],
        )

        for metric in (
            takeoff_vs_text, takeoff_v1_text, takeoff_vr_text, takeoff_v2_text, takeoff_block_fuel_text,
            takeoff_climb_initial_text, takeoff_climb_enroute_text, takeoff_climb_high_text,
        ):
            metric.size = PERFORMANCE_METRIC_SIZE
            metric.style = ft.TextStyle(height=1.05)

        climb_performance_card = glass_card_with_background(
            "Climb Performance",
            ft.Row(
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Container(
                        expand=2,
                        content=ft.Column(
                            spacing=5,
                            controls=[takeoff_vs_text, takeoff_v1_text, takeoff_vr_text, takeoff_v2_text],
                        ),
                    ),
                    ft.VerticalDivider(width=1, opacity=0.18),
                    ft.Container(
                        expand=3,
                        content=ft.Column(
                            spacing=5,
                            controls=[takeoff_climb_initial_text, takeoff_climb_enroute_text, takeoff_climb_high_text],
                        ),
                    ),
                ],
            ),
            bg_key="takeoff_performance_speeds",
        )
        climb_performance_card.content.controls[0] = ft.Row(
            [
                climb_performance_card.content.controls[0],
                ft.Text("Climb rates (fpm)", size=12, color=tokens["muted"]),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        distances_card = glass_card(
            "Distances",
            ft.Column(spacing=12, controls=[takeoff_asd_text, takeoff_agd_text, takeoff_tod_text, takeoff_margin_text]),
            height=300,
        )

        atmosphere_card = glass_card(
            "Wind and Atmosphere",
            ft.Column(
                spacing=10,
                controls=[
                    takeoff_isa_temp_text,
                    takeoff_pressure_alt_text,
                    takeoff_density_alt_text,
                    takeoff_isa_dev_text,
                    takeoff_headwind_text,
                    takeoff_crosswind_text,
                ],
            ),
            height=300,
        )


        fuel_overview = aligned_planning_row(
            ft.Column(
                [
                    ft.Text("Planned fuel", size=13, weight=ft.FontWeight.W_700, color=tokens["muted"]),
                    takeoff_block_fuel_text,
                ],
                spacing=2,
            ),
            ft.Column(
                [
                    aligned_planning_row(
                        compact_performance_input(takeoff_route_distance_tf),
                        compact_performance_input(takeoff_fuel_passengers_tf), widths=(1, 1),
                    ),
                    aligned_planning_row(
                        compact_performance_input(takeoff_fuel_baggage_tf),
                        compact_performance_input(takeoff_fuel_cargo_tf), widths=(1, 1),
                    ),
                ],
                spacing=6,
            ),
            widths=(43, 57),
        )
        fuel_card = glass_card(
            "Fuel Planning",
            ft.Column(
                expand=True, spacing=5,
                controls=[
                    fuel_overview,
                    ft.Column(
                        expand=True, scroll=ft.ScrollMode.AUTO, spacing=4,
                        controls=[
                            takeoff_trip_fuel_text,
                            takeoff_ete_text,
                            takeoff_fuel_status_text,
                            takeoff_fuel_limits_text,
                            takeoff_fuel_burn_text,
                            takeoff_fuel_breakdown_text,
                            takeoff_recommended_tow_text,
                            takeoff_fuel_aircraft_text,
                            takeoff_fuel_engine_text,
                            takeoff_fuel_assumptions_text,
                        ],
                    ),
                ],
            ),
        )

        fuel_card.content.controls[0] = ft.Row(
            [
                fuel_card.content.controls[0],
                ft.ElevatedButton(
                    "Compute Fuel", on_click=do_compute_fuel, height=30,
                    bgcolor=tokens["primary"], color=tokens["on_primary"],
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        fuel_card.content.spacing = 6

        diagnostic_cards_row = ft.Row(
            wrap=True,
            spacing=GAP,
            run_spacing=GAP,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Container(width=260, content=distances_card),
                ft.Container(width=260, content=atmosphere_card),
            ],
        )

        return performance_page(
            aligned_planning_row(
                airport_weather_card, takeoff_operations_card, live_clock_card, widths=PERFORMANCE_TOP_WIDTHS, expand=3,
            ),
            aligned_planning_row(climb_performance_card, fuel_card, widths=(46, 54), expand=2),
            [runway_config_card, diagnostic_cards_row] if professional_info else [],
        )


    def landing_view():
        professional_info = bool(getattr(state, "professional_info_enabled", False))
        airport_weather_card = performance_airport_weather(
            "arrival", landing_raw_metar_tf, landing_metar_status_text, do_fetch_landing_metar,
        )

        landing_aircraft_chip = ft.Container(
            width=230,
            padding=12,
            border_radius=16,
            bgcolor=surface_fill(tokens["subpanel"]),
            border=ft.border.all(1, tokens["card_border"]),
            content=ft.Column(
                tight=True,
                spacing=4,
                controls=[
                    ft.Text("Aircraft", size=11, color=tokens["muted"]),
                    landing_aircraft_display_text,
                ],
            ),
        )

        runway_config_card = glass_card(
            "Runway and Configuration",
            ft.Column(
                spacing=12,
                controls=[
                    ft.Row(wrap=True, spacing=12, controls=[landing_runway_heading_tf, landing_surface_dd, landing_autobrake_dd]),
                    ft.Row(wrap=True, spacing=12, controls=[landing_reverse_sw, landing_lda_tf, landing_obstacle_tf]),
                    ft.Row(wrap=True, spacing=12, controls=[landing_current_alt_tf, landing_distance_to_go_tf, landing_ground_speed_tf]),
                ],
            ),
            height=280,
        )

        landing_local_clock_card = glass_card(
            "Local Clock",
            build_phase_clock_content("descent"),
        )

        landing_status_text.size = 11
        landing_operations_card = build_operations_panel(
            "descent", landing_warning_host, landing_mlw_value_text, landing_status_text,
            [
                compact_performance_input(landing_weight_tf, height=36),
                ft.Row(
                    wrap=True,
                    spacing=8,
                    controls=[
                        ft.ElevatedButton("Compute", on_click=do_compute_landing, bgcolor=tokens["primary"], color=tokens["on_primary"]),
                        ft.OutlinedButton("Reset", on_click=do_reset_landing),
                        ft.OutlinedButton("Save", on_click=do_save_landing_log),
                    ],
                ),
            ],
        )

        for metric in (landing_vs_text, landing_vref_text, landing_vapp_text):
            metric.size = PERFORMANCE_METRIC_SIZE
            metric.style = ft.TextStyle(height=1.05)
        landing_additive_text.color = tokens["muted"]
        landing_vs_calc_result_text.size = 22

        landing_speeds_card = glass_card_with_background(
            "Approach Speeds",
            ft.Column(
                spacing=5,
                controls=[landing_vs_text, landing_vref_text, landing_vapp_text, landing_additive_text, landing_weight_ratio_text],
            ),
            bg_key="landing_performance_speeds",
        )

        landing_distance_card = glass_card(
            "Landing Distance",
            ft.Column(spacing=12, controls=[landing_distance_text, landing_braking_text, landing_margin_text]),
            height=300,
        )

        landing_wind_card = glass_card(
            "Wind and Atmosphere",
            ft.Column(
                spacing=10,
                controls=[
                    landing_headwind_text,
                    landing_crosswind_text,
                    landing_pressure_alt_text,
                    landing_density_alt_text,
                ],
            ),
            height=300,
        )

        landing_descent_card = glass_card(
            "Descent Planning",
            ft.Column(
                spacing=10,
                controls=[
                    landing_altitude_to_lose_text,
                    landing_tod_text,
                    landing_descent_rate_text,
                    landing_descent_time_text,
                    landing_profile_text,
                ],
            ),
            height=270,
        )

        landing_vs_calc_card = glass_card(
            "V/S Calculator",
            ft.Column(
                spacing=8,
                controls=[
                    aligned_planning_row(
                        compact_performance_input(landing_vs_calc_alt_tf),
                        compact_performance_input(landing_vs_calc_ete_tf), widths=(1, 1),
                    ),
                    ft.ElevatedButton("Calc V/S", on_click=do_calc_landing_vs,
                                      bgcolor=tokens["primary"], color=tokens["on_primary"]),
                    landing_vs_calc_result_text,
                ],
            ),
        )

        return performance_page(
            aligned_planning_row(
                airport_weather_card, landing_operations_card, landing_local_clock_card, widths=PERFORMANCE_TOP_WIDTHS, expand=3,
            ),
            aligned_planning_row(landing_speeds_card, landing_vs_calc_card, widths=(1, 1), expand=2),
            [
                runway_config_card,
                aligned_planning_row(landing_descent_card, landing_distance_card, landing_wind_card, widths=(1, 1, 1)),
            ] if professional_info else [],
        )


    def baggage_view():
        bag_pax_tf.read_only = bool(seat_model.get("generated"))
        bag_pax_tf.label = "Filled passengers" if bag_pax_tf.read_only else "Passenger count"

        outline_style = button_style(tokens) if page.theme_mode == ft.ThemeMode.DARK else None

        def section_title(title):
            return ft.Text(title, size=14, weight=ft.FontWeight.W_600, color=tokens["text"])

        return glass_card(
            "Baggage",
            ft.Column(
                expand=True, scroll=ft.ScrollMode.AUTO, spacing=12,
                controls=[
                    ft.Text("Passenger baggage inputs", size=12, color=tokens["muted"]),
                    bag_pax_tf,
                    bag_carry_on_tf,
                    bag_checked_kg_per_pax_tf,
                    ft.Divider(height=8, opacity=0.12),
                    section_title("Cargo"),
                    ft.Text("Add extra cargo mass carried in the hold.", size=12, color=tokens["muted"]),
                    cargo_weight_tf,
                    ft.Container(
                        padding=14, border_radius=16,
                        bgcolor=surface_fill(tokens["subpanel"]),
                        border=ft.border.all(1, tokens["card_border"]),
                        content=ft.Column(
                            tight=True, spacing=6,
                            controls=[
                                ft.Text("Cargo note", size=12, color=tokens["muted"]),
                                ft.Text("This value is added to baggage weight to create total payload.", size=12, color=tokens["text"]),
                            ],
                        ),
                    ),
                    ft.Row(wrap=True, spacing=10, controls=[
                        ft.ElevatedButton("Calculate", on_click=do_baggage_calc,
                                          bgcolor=tokens["primary"], color=tokens["on_primary"]),
                        ft.OutlinedButton("Reset", on_click=reset_baggage_form, style=outline_style),
                    ]),
                    bag_status_text,
                    ft.Divider(height=8, opacity=0.12),
                    section_title("Calculated Weight"),
                    bag_baggage_weight_summary_text,
                    bag_cargo_weight_summary_text,
                    bag_payload_weight_summary_text,
                    ft.Container(
                        padding=14, border_radius=16,
                        bgcolor=surface_fill(tokens["subpanel"]),
                        border=ft.border.all(1, tokens["card_border"]),
                        content=ft.Column(
                            spacing=6,
                            controls=[
                                ft.Text("Breakdown", size=12, color=tokens["muted"]),
                                bag_carry_on_result_text,
                                bag_checked_result_text,
                            ],
                        ),
                    ),
                ],
            ),
        )


    def active_maptiler_tile_url() -> tuple[str, str, str]:
        # Dark map only. Keep one reliable style so route markers/lines remain stable.
        state.map_style = "dataviz-v4-dark"
        style = MAPTILER_STYLES["dataviz-v4-dark"]
        if MAPTILER_API_KEY:
            return (
                style["url"].format(key=MAPTILER_API_KEY),
                style["attribution"],
                style["label"],
            )
        return (
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            "Tiles © Esri",
            "Satellite",
        )


    def calendar_entry_card(entry: dict):
        is_completed = bool(entry.get("completed"))
        status_text = "Completed" if is_completed else "Planned"
        status_color = ft.Colors.GREEN_700 if is_completed else tokens["accent"]
        bg_color = tokens["success_overlay"] if is_completed else tokens["subpanel"]
        entry_id = str(entry.get("id") or "")
        action_buttons: List[ft.Control] = [
            ft.OutlinedButton("Edit", on_click=lambda e, target_id=entry_id: load_calendar_entry_for_edit(target_id)),
            ft.OutlinedButton("Delete", on_click=lambda e, target_id=entry_id: delete_calendar_entry(target_id)),
        ]
        if not is_completed:
            action_buttons.append(
                ft.ElevatedButton(
                    "Complete",
                    icon=ft.Icons.CHECK_ROUNDED,
                    on_click=lambda e, target_id=entry_id: complete_calendar_entry(target_id),
                    bgcolor=tokens["primary"],
                    color=tokens["on_primary"],
                )
            )

        return ft.Container(
            padding=16,
            border_radius=18,
            bgcolor=surface_fill(bg_color),
            border=ft.border.all(1, tokens["card_border"]),
            content=ft.Column(
                spacing=10,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Column(
                                spacing=4,
                                controls=[
                                    ft.Text(entry.get("route", "—"), size=17, weight=ft.FontWeight.W_700, color=tokens["text"]),
                                    ft.Text(
                                        f"{entry.get('date', '')}  {entry.get('time', '')} • {entry.get('airline', '')} • {entry.get('aircraft', '')}",
                                        size=11,
                                        color=tokens["muted"],
                                    ),
                                ],
                            ),
                            ft.Container(
                                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                                border_radius=999,
                                bgcolor=ft.Colors.with_opacity(0.12, status_color),
                                content=ft.Row(
                                    spacing=5,
                                    controls=[
                                        *([ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=13, color=status_color)] if is_completed else []),
                                        ft.Text(status_text, color=status_color, size=10, weight=ft.FontWeight.W_700),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    ft.Row(
                        wrap=True,
                        spacing=20,
                        controls=[
                            ft.Text(f"Flight time: {entry.get('flight_time', '—')}", size=11, color=tokens["text"]),
                            ft.Text(f"Departure: {entry.get('origin', '—')}", size=11, color=tokens["text"]),
                            ft.Text(f"Arrival: {entry.get('destination', '—')}", size=11, color=tokens["text"]),
                        ],
                    ),
                    ft.Text(f"Notes: {entry.get('notes', '—') or '—'}", size=11, color=tokens["muted"]),
                    ft.Row(
                        wrap=True,
                        spacing=8,
                        controls=action_buttons,
                    ),
                ],
            ),
        )

    def calendar_view():
        import calendar as pycalendar

        display_year = int(getattr(state, "calendar_display_year", datetime.now().year) or datetime.now().year)
        display_month = int(getattr(state, "calendar_display_month", datetime.now().month) or datetime.now().month)
        state.calendar_display_year = display_year
        state.calendar_display_month = display_month
        entries_by_date = index_calendar_entries_by_date(state.calendar_entries)

        selected_date = (getattr(state, "calendar_selected_date", "") or "").strip()
        today_str = datetime.now().strftime("%Y-%m-%d")

        def shift_calendar_month(delta: int):
            month = int(getattr(state, "calendar_display_month", datetime.now().month) or datetime.now().month)
            year = int(getattr(state, "calendar_display_year", datetime.now().year) or datetime.now().year)
            month += delta
            while month < 1:
                month += 12
                year -= 1
            while month > 12:
                month -= 12
                year += 1
            state.calendar_display_month = month
            state.calendar_display_year = year
            refresh_active_page()

        def choose_calendar_date(date_str: str):
            # Click a date once to select it and fill the planner date.
            # Click the same date again to deselect and return the planner to defaults.
            if (getattr(state, "calendar_selected_date", "") or "").strip() == date_str:
                reset_calendar_form()
            else:
                state.calendar_editing_id = None
                state.calendar_selected_date = date_str
                cal_date_tf.value = date_str
                cal_form_message.value = f"Selected date: {date_str}"
            refresh_calendar_route_preview()
            refresh_active_page()

        def clear_calendar_selected_date(e=None):
            if (getattr(state, "calendar_selected_date", "") or "").strip():
                reset_calendar_form()
                refresh_calendar_route_preview()
                refresh_active_page()

        def flights_for_date(date_str: str) -> list[dict]:
            return entries_by_date.get(date_str, [])

        def planner_compact_card() -> ft.Control:
            return glass_card(
                "Flight Planner",
                ft.Column(
                    spacing=12,
                    controls=[
                        ft.Row(wrap=True, spacing=10, controls=[cal_date_tf, cal_time_tf]),
                        planner_search("airline", "Airline", cal_airline_dd),
                        planner_search("aircraft", "Aircraft", cal_aircraft_dd),
                        ft.Row(wrap=True, spacing=10, controls=[
                            planner_search("origin", "Departure", cal_origin_tf),
                            planner_search("destination", "Arrival", cal_destination_tf),
                        ]),
                        cal_flight_time_tf,
                        ft.Row(
                            wrap=True,
                            spacing=10,
                            controls=[
                                ft.ElevatedButton(
                                    "Update flight" if state.calendar_editing_id else "Add flight",
                                    on_click=add_or_update_calendar_entry,
                                    bgcolor=tokens["primary"],
                                    color=tokens["on_primary"],
                                ),
                                ft.OutlinedButton("Clear", on_click=clear_calendar_form),
                            ],
                        ),
                        cal_form_message,
                    ],
                ),
            )

        cal = pycalendar.Calendar(firstweekday=0)
        month_label = datetime(display_year, display_month, 1).strftime("%B %Y")
        month_dates = list(cal.itermonthdates(display_year, display_month))
        calendar_board_height = 116 + (len(month_dates) // 7) * 122
        cell_height = 116

        day_headers = ft.Row(
            spacing=6,
            controls=[
                ft.Container(expand=True, alignment=ft.Alignment(0, 0), content=ft.Text(day, size=12, weight=ft.FontWeight.W_700, color=tokens["muted"]))
                for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            ],
        )

        date_cells: list[ft.Control] = []
        for date_obj in month_dates:
            date_str = date_obj.strftime("%Y-%m-%d")
            entries = flights_for_date(date_str)
            first_entry = entries[0] if entries else {}
            entry_count = len(entries)
            completed_count = len([entry for entry in entries if bool(entry.get("completed"))])
            is_current_month = date_obj.month == display_month
            is_today = date_str == today_str
            is_selected = date_str == selected_date

            if is_selected:
                cell_bg = ft.Colors.with_opacity(0.18, tokens["accent"])
                border_color = tokens["accent"]
            elif is_today:
                cell_bg = ft.Colors.with_opacity(0.10, tokens["accent"])
                border_color = ft.Colors.with_opacity(0.55, tokens["accent"])
            else:
                cell_bg = tokens["subpanel"]
                border_color = tokens["card_border"]

            day_text_color = tokens["text"] if is_current_month else tokens["muted"]
            compact_info = []
            for entry in entries[:1]:
                route_text = f"{entry.get('origin', '')} → {entry.get('destination', '')}".strip()
                detail_text = " • ".join(
                    part for part in [
                        (entry.get("time") or "").strip(),
                        (entry.get("airline") or "").strip(),
                    ]
                    if part
                )
                compact_info.append(
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=8, vertical=5),
                        border_radius=11,
                        bgcolor=ft.Colors.with_opacity(0.08, tokens["accent"]),
                        border=ft.border.all(1, ft.Colors.with_opacity(0.14, tokens["accent"])),
                        content=ft.Column(
                            tight=True,
                            spacing=1,
                            controls=[
                                ft.Text(route_text or "Flight", size=10, weight=ft.FontWeight.W_800, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(detail_text or (entry.get("aircraft", "") or "Planned"), size=8, color=tokens["muted"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ],
                        ),
                    )
                )
            if entry_count > 1:
                compact_info.append(ft.Text(f"+{entry_count - 1} more", size=10, color=tokens["accent"], weight=ft.FontWeight.W_700))
            date_cells.append(
                ft.Container(
                    expand=True,
                    height=cell_height,
                    padding=7,
                    border_radius=7,
                    bgcolor=surface_fill(cell_bg),
                    border=ft.border.all(1.4, border_color),
                    ink=True,
                    on_click=lambda e, ds=date_str: choose_calendar_date(ds),
                    content=ft.Column(
                        spacing=6,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(str(date_obj.day), size=22, weight=ft.FontWeight.W_900, color=day_text_color),
                                    ft.Icon(ft.Icons.CIRCLE, size=8, color=tokens["accent"] if is_today else ft.Colors.TRANSPARENT),
                                ],
                            ),
                            *compact_info,
                        ],
                    ),
                )
            )

        week_rows: list[ft.Control] = []
        for idx in range(0, len(date_cells), 7):
            week_rows.append(ft.Row(spacing=6, vertical_alignment=ft.CrossAxisAlignment.START, controls=date_cells[idx:idx + 7]))

        calendar_board = glass_card_with_background(
            "Desk Calendar",
            ft.Column(
                spacing=8,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.START,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, on_click=lambda e: shift_calendar_month(-1), icon_color=tokens["text"]),
                                    ft.Text(month_label, size=26, weight=ft.FontWeight.W_800, color=tokens["text"]),
                                    ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, on_click=lambda e: shift_calendar_month(1), icon_color=tokens["text"]),
                                ],
                            ),
                        ],
                    ),
                    ft.Column(spacing=6, controls=[day_headers, *week_rows]),
                ],
            ),
            height=calendar_board_height,
            bg_key="desk_calendar",
        )

        entry_controls = [calendar_entry_card(entry) for entry in get_filtered_sorted_calendar_entries()]
        if not entry_controls:
            entry_controls = [
                ft.Container(
                    padding=18,
                    border_radius=18,
                    bgcolor=surface_fill(tokens["subpanel"]),
                    border=ft.border.all(1, tokens["card_border"]),
                    content=ft.Text("No flights match the current filters yet.", color=tokens["muted"]),
                )
            ]

        saved_flights_card = glass_card(
            "Flight Agenda",
            ft.Column(
                expand=True,
                spacing=12,
                controls=[
                    ft.Row(wrap=True, spacing=12, controls=[cal_sort_dd, cal_status_filter_dd]),
                    ft.Container(
                        expand=True,
                        content=ft.ListView(
                            expand=True,
                            spacing=12,
                            build_controls_on_demand=True,
                            cache_extent=360,
                            controls=[*entry_controls, ft.Container(height=28)],
                        ),
                    ),
                ],
            ),
            height=calendar_board_height,
        )

        return ft.Container(
            expand=True, padding=GAP,
            content=ft.Column(
                expand=True, scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.ResponsiveRow(
                        spacing=GAP, run_spacing=GAP,
                        breakpoints={"sm": 0, "lg": 1280},
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Container(col={"sm": 3, "lg": 2.4}, content=planner_compact_card()),
                            ft.Container(col={"sm": 9, "lg": 6.2}, content=calendar_board),
                            ft.Container(col={"sm": 12, "lg": 3.4}, content=saved_flights_card),
                        ],
                    ),
                ],
            ),
        )



    def log_entry_row(entry: dict, stack_index: int = 0, register_control: bool = True) -> ft.Control:
        entry_id = entry.get("id") or f"{entry.get('date', '')}-{entry.get('time', '')}-{entry.get('route', '')}"
        is_expanded = getattr(state, "log_expanded_id", None) == entry_id
        status_text = "Completed" if bool(entry.get("completed")) else "Planned"
        status_color = ft.Colors.GREEN_300 if bool(entry.get("completed")) else tokens["accent"]

        # Soft boarding-pass palette. Pure white was too bright against the dark
        # command-center background, so the ticket uses a warm aviation-paper tone.
        pass_bg = tokens["input_bg"]
        pass_stub_bg = tokens["input_bg"]
        pass_text = tokens["text"]
        pass_muted = tokens["muted"]
        pass_line = tokens["card_border"]

        def refresh_log_ticket(item_id: Optional[str]):
            if not item_id:
                return
            registered = log_entry_control_registry.get(str(item_id))
            if not registered:
                return
            host, source_entry, source_index = registered
            replacement = log_entry_row(source_entry, source_index, register_control=False)
            host.content = replacement.content
            host.margin = replacement.margin
            host.bgcolor = replacement.bgcolor
            host.border = replacement.border
            host.border_radius = replacement.border_radius
            host.clip_behavior = replacement.clip_behavior
            host.shadow = replacement.shadow
            if getattr(host, "page", None):
                host.update()

        def toggle_log_detail(e=None, item_id=entry_id):
            previous_id = getattr(state, "log_expanded_id", None)
            if getattr(state, "log_expanded_id", None) == item_id:
                state.log_expanded_id = None
            else:
                state.log_expanded_id = item_id
            for refresh_id in dict.fromkeys([previous_id, item_id]):
                refresh_log_ticket(refresh_id)

        def clean(value, fallback="—"):
            value = "" if value is None else str(value).strip()
            return value if value else fallback

        def estimate_arrival_time() -> str:
            saved_arrival_time = clean(entry.get("arrival_time"), "")
            if saved_arrival_time:
                return saved_arrival_time
            date_str = clean(entry.get("date"), "")
            time_str = clean(entry.get("time"), "")
            minutes = parse_flight_time_minutes(entry.get("flight_time", ""))
            if not date_str or not time_str or minutes <= 0:
                return clean(entry.get("arrival_time"))
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                return (dt + timedelta(minutes=minutes)).strftime("%H:%M")
            except Exception:
                return clean(entry.get("arrival_time"))

        def note_value(label: str) -> str:
            notes = clean(entry.get("notes"), "")
            if not notes:
                return "—"
            parts = [p.strip() for p in notes.replace("\n", " | ").split("|")]
            for part in parts:
                if part.lower().startswith(label.lower()):
                    return part
            return "—"

        def airport_display_name(code: str) -> str:
            record = lookup_airport_record(code)
            if not record:
                return clean(code)
            name = clean(record.get("name"), clean(code))
            for word in ("International Airport", "International", "Airport"):
                name = name.replace(word, "").strip()
            return name or clean(code)

        def detail_line(label: str, value: str) -> ft.Control:
            return ft.Container(
                width=220,
                padding=ft.padding.symmetric(horizontal=12, vertical=10),
                border_radius=16,
                bgcolor=surface_fill(tokens["subpanel"]),
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    tight=True,
                    spacing=4,
                    controls=[
                        ft.Text(label, size=11, color=tokens["muted"]),
                        ft.Text(clean(value), size=13, weight=ft.FontWeight.W_700,
                                color=tokens["text"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        def landing_performance_control() -> ft.Control:
            saved_value = parse_landing_g(entry.get("landing_g"))
            field = ft.TextField(
                label="Landing performance",
                suffix="G",
                value=clean(entry.get("landing_g"), "") if saved_value is not None else "",
                keyboard_type=ft.KeyboardType.NUMBER,
                width=220,
                border_radius=16,
                filled=True,
                bgcolor=tokens["input_bg"],
            )
            grade_text = ft.Text(size=12, weight=ft.FontWeight.W_700)
            grade = ft.Container(
                content=grade_text,
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                border_radius=10,
                visible=False,
            )

            def update_grade(e=None):
                raw = (field.value or "").strip()
                value = parse_landing_g(raw)
                field.error_text = "Enter a number above 0 and up to 2.6." if raw and value is None else None
                grade.visible = value is not None
                if value is not None:
                    grade_text.value, grade_text.color, grade.bgcolor = landing_g_grade(value)
                if e is not None:
                    field.update()
                    grade.update()

            def save_grade(e):
                raw = (field.value or "").strip()
                value = parse_landing_g(raw)
                if (raw and value is None) or value == parse_landing_g(entry.get("landing_g")):
                    return
                if value is None:
                    entry.pop("landing_g", None)
                else:
                    entry["landing_g"] = value
                entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
                save_calendar_entries()
                if log_sort_dd.value in ("Lowest landing G", "Highest landing G"):
                    refresh_active_page()

            field.on_change = update_grade
            field.on_submit = field.on_blur = save_grade
            update_grade()
            return ft.Row([field, grade], wrap=True, spacing=10, run_spacing=5)

        def pass_info_block(label: str, value: str, width: Optional[int] = None) -> ft.Control:
            return ft.Container(
                width=width,
                expand=width is None,
                content=ft.Column(
                    tight=True,
                    spacing=2,
                    controls=[
                        ft.Text(label, size=10, color=pass_muted),
                        ft.Text(clean(value), size=14, weight=ft.FontWeight.W_800, color=pass_text, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        airline = clean(entry.get("airline"), clean(state.airline))
        aircraft = clean(entry.get("aircraft"), clean(state.aircraft))
        origin = normalize_airport_code(clean(entry.get("origin"), "")) or clean(entry.get("origin"))
        destination = normalize_airport_code(clean(entry.get("destination"), "")) or clean(entry.get("destination"))
        route = clean(entry.get("route"), f"{origin} → {destination}" if origin != "—" and destination != "—" else "—")
        flight_time = clean(entry.get("flight_time"))
        departure_date = clean(entry.get("date"))
        departure_time = clean(entry.get("time"))
        arrival_time = estimate_arrival_time()
        flight_number = clean(entry.get("flight_number"), clean(state.flight_number, "FMS —"))
        block_fuel_note = note_value("Block fuel")

        fuel_plan = state.takeoff_last_result.get("fuel_plan", {}) if isinstance(getattr(state, "takeoff_last_result", {}), dict) else {}
        planned_fuel = clean(entry.get("planned_fuel"), "")
        if not planned_fuel and isinstance(fuel_plan, dict) and fuel_plan.get("block_fuel_kg"):
            try:
                planned_fuel = f"{float(fuel_plan.get('block_fuel_kg')):,.0f} kg"
            except Exception:
                planned_fuel = "—"
        if not planned_fuel and block_fuel_note != "—":
            planned_fuel = block_fuel_note.replace("Block fuel", "").strip(" :")

        origin_name = airport_display_name(origin)
        destination_name = airport_display_name(destination)
        passenger_name = clean(state.pilot_name, "Pilot")

        header_height = 190 if is_expanded else 100
        collapsed_code_size = 24
        expanded_code_size = 32
        code_size = expanded_code_size if is_expanded else collapsed_code_size
        city_size = 13 if is_expanded else 11

        def airport_heading(label, code, name, time, *, arrival=False):
            code_text = ft.Text(code, size=code_size, weight=ft.FontWeight.W_900, color=pass_text)
            time_text = ft.Text(time, size=22 if is_expanded else 17, weight=ft.FontWeight.W_800, color=pass_text)
            return ft.Container(
                expand=True,
                content=ft.Column(
                    spacing=0,
                    horizontal_alignment=ft.CrossAxisAlignment.END if arrival else ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Text(label, size=10, color=pass_muted, weight=ft.FontWeight.W_700),
                        ft.Row(
                            [time_text, code_text] if arrival else [code_text, time_text],
                            spacing=10,
                            alignment=ft.MainAxisAlignment.END if arrival else ft.MainAxisAlignment.START,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(name.upper(), size=city_size, weight=ft.FontWeight.W_700,
                                color=pass_muted, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        perforation = ft.Container(
            width=16,
            height=header_height,
            bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.WHITE),
            content=ft.Column(
                spacing=6,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(width=3, height=12, bgcolor=ft.Colors.with_opacity(0.40, ft.Colors.WHITE), border_radius=4)
                    for _ in range(7 if is_expanded else 4)
                ],
            ),
        )

        left_top_controls = []
        if is_expanded:
            left_top_controls = [
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(width=150, height=36, alignment=ft.Alignment(-1, 0), content=airline_logo_image(airline, width=145, height=34, fallback_text=True, key_prefix="boarding-pass-logo")),
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=10, vertical=6),
                            border_radius=999,
                            bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.WHITE),
                            content=ft.Text(status_text.upper(), size=10, weight=ft.FontWeight.W_800, color=tokens["text"]),
                        ),
                    ],
                )
            ]

        expanded_bottom_info = []
        if is_expanded:
            expanded_bottom_info = [
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        pass_info_block("Passenger", passenger_name.upper()),
                        pass_info_block("Flight", flight_number.upper()),
                        pass_info_block("Aircraft", aircraft.upper()),
                        pass_info_block("Date", departure_date),
                    ],
                )
            ]

        center_brand = (
            ft.Container(
                width=140,
                height=38,
                alignment=ft.Alignment(0, 0),
                content=airline_logo_image(
                    airline,
                    width=136,
                    height=34,
                    fallback_text=True,
                    key_prefix="boarding-pass-center-logo",
                ),
            )
            if not is_expanded
            else ft.Container(width=140, height=38)
        )

        header_left = ft.Container(
            height=header_height,
            expand=True,
            padding=ft.padding.only(left=22, top=(16 if is_expanded else 12), right=22, bottom=12),
            bgcolor=surface_fill(pass_bg),
            content=ft.Column(
                spacing=(10 if is_expanded else 4),
                alignment=ft.MainAxisAlignment.CENTER if not is_expanded else ft.MainAxisAlignment.START,
                controls=[
                    *left_top_controls,
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            airport_heading("DEPARTURE", origin, origin_name, departure_time),
                            ft.Container(
                                width=150,
                                alignment=ft.Alignment(0, 0),
                                content=ft.Column(
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                    spacing=2,
                                    controls=[
                                        center_brand,
                                    ],
                                ),
                            ),
                            airport_heading("ARRIVAL", destination, destination_name, arrival_time, arrival=True),
                        ],
                    ),
                    *expanded_bottom_info,
                ],
            ),
        )

        stub_controls = [
            ft.Text("Boarding pass", size=16, weight=ft.FontWeight.W_800, color=pass_text),
            ft.Row(spacing=14, controls=[pass_info_block("Departure", origin, width=100), pass_info_block("Arrival", destination, width=100)]),
        ]
        if is_expanded:
            stub_controls.extend([
                ft.Row(spacing=14, controls=[pass_info_block("Time", flight_time, width=100), pass_info_block("Gate", clean(entry.get("gate"), clean(state.departure_gate)), width=100)]),
            ])

        header_stub = ft.Container(
            width=252,
            height=header_height,
            padding=ft.padding.only(left=20, top=(16 if is_expanded else 12), right=20, bottom=12),
            bgcolor=surface_fill(pass_stub_bg),
            content=ft.Column(
                spacing=(10 if is_expanded else 6),
                alignment=ft.MainAxisAlignment.CENTER,
                controls=stub_controls,
            ),
        )

        expanded_details = ft.Container(height=0)
        if is_expanded:
            aircraft_media_card = ft.Container(
                expand=2,
                height=272,
                padding=12,
                border_radius=20,
                bgcolor=surface_fill(tokens["subpanel"]),
                border=ft.border.all(1, tokens["card_border"]),
                alignment=ft.Alignment(0, 0),
                content=aircraft_profile_image(aircraft, width=560, height=246),
            )

            expanded_details = ft.Container(
                padding=ft.padding.only(left=20, right=20, top=16, bottom=20),
                bgcolor=surface_fill(tokens["panel"]),
                border=ft.border.only(top=ft.BorderSide(1, tokens["card_border"])),
                content=ft.Row(
                    spacing=18,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Container(
                            expand=3,
                            content=ft.Column(
                                spacing=14,
                                controls=[
                                    ft.Text("Flight recorder details", size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                                    landing_performance_control(),
                                    ft.Row(
                                        wrap=True,
                                        spacing=12,
                                        run_spacing=12,
                                        controls=[
                                            detail_line("Flight time", flight_time),
                                            detail_line("Air pathway", route),
                                            detail_line("Airline", airline),
                                            detail_line("Aircraft", aircraft),
                                            detail_line("Passengers", clean(entry.get("passengers"), clean(getattr(takeoff_fuel_passengers_tf, "value", "")))),
                                            detail_line("Baggage weight", clean(entry.get("baggage_weight"), clean(getattr(takeoff_fuel_baggage_tf, "value", "")))),
                                            detail_line("Cargo weight", clean(entry.get("cargo_weight"), clean(getattr(takeoff_fuel_cargo_tf, "value", "")))),
                                            detail_line("Planned fuel", planned_fuel),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                        aircraft_media_card,
                    ],
                ),
            )

        ticket_body = ft.Column(
            tight=False,
            spacing=0,
            controls=[
                ft.Row(
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[header_left, perforation, header_stub],
                ),
                expanded_details,
            ],
        )

        ticket_control = ft.Container(
            margin=ft.Margin.only(bottom=8),
            border_radius=CARD_RADIUS,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=surface_fill(pass_bg),
            border=ft.border.all(1, pass_line),
            shadow=ft.BoxShadow(
                blur_radius=18 if is_expanded else 12,
                spread_radius=1,
                color=ft.Colors.with_opacity(0.18 if is_expanded else 0.10, ft.Colors.BLACK),
                offset=ft.Offset(0, 7),
            ),
            on_click=toggle_log_detail,
            content=ticket_body,
        )
        if register_control:
            log_entry_control_registry[str(entry_id)] = (ticket_control, entry, stack_index)
        return ticket_control


    def log_view():
        log_entries = get_completed_log_entries()
        summary = summarize_log_entries(log_entries)
        log_entry_control_registry.clear()
        log_controls = [log_entry_row(entry, index) for index, entry in enumerate(log_entries)]
        if not log_controls:
            log_controls = [
                ft.Container(
                    padding=18,
                    border_radius=18,
                    bgcolor=surface_fill(tokens["subpanel"]),
                    border=ft.border.all(1, tokens["card_border"]),
                    content=ft.Text("Completed flights from the Calendar tab will appear here.", color=tokens["muted"]),
                )
            ]

        def summary_stat_box(label: str, value: str, subtitle: str) -> ft.Control:
            return ft.Container(
                width=220,
                padding=ft.padding.symmetric(horizontal=14, vertical=12),
                border_radius=16,
                bgcolor=surface_fill(tokens["subpanel"]),
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    tight=True,
                    spacing=4,
                    controls=[
                        ft.Text(label, size=12, color=tokens["muted"]),
                        ft.Text(value or "—", size=22, weight=ft.FontWeight.W_700, color=tokens["text"]),
                        ft.Text(subtitle, size=11, color=tokens["muted"]),
                    ],
                ),
            )

        summary_card = glass_card(
            "Flight Log Summary",
            ft.Column(
                tight=True,
                spacing=12,
                controls=[
                    ft.Row(
                        wrap=True,
                        spacing=12,
                        run_spacing=12,
                        controls=[
                            summary_stat_box("Total flights", summary["total_flights"], "Completed flights only"),
                            summary_stat_box("Total flight hours", summary["total_hours"], "Across completed flights"),
                            summary_stat_box("Most used aircraft", summary["most_used_aircraft"], "Based on the log"),
                            summary_stat_box("Most used route", summary["most_used_route"], "Based on the log"),
                            summary_stat_box("Average sector time", summary["average_sector"], "Mean completed flight time"),
                        ],
                    ),
                ],
            ),
        )

        completed_card = glass_card(
            "Flight Recorder",
            ft.Column(
                tight=True,
                spacing=12,
                controls=[
                    ft.Text(
                        "Completed flights are shown as a digital boarding-pass wallet. Click a pass to expand or collapse the full flight record.",
                        size=12,
                        color=tokens["muted"],
                    ),
                    ft.Row(wrap=True, spacing=12, controls=[log_sort_dd]),
                    ft.ListView(
                        height=680,
                        spacing=0,
                        build_controls_on_demand=True,
                        cache_extent=450,
                        controls=log_controls,
                    ),
                ],
            ),
        )


        return build_tab_page(
            "LOG",
            ft.Container(
                expand=True,
                bgcolor=ft.Colors.TRANSPARENT,
                padding=18,
                alignment=ft.Alignment(-1, -1),
                content=ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    spacing=12,
                    controls=[summary_card, completed_card],
                ),
            ),
            overlay_opacity=0.08,
        )


    def profile_view():
        completed_entries = get_completed_log_entries()
        logged_flights = len(completed_entries)
        logged_minutes = sum(parse_flight_time_minutes(entry.get("flight_time", "")) for entry in completed_entries)

        aircraft_counts: Dict[str, int] = {}
        airline_counts: Dict[str, int] = {}
        route_counts: Dict[str, int] = {}
        for entry in completed_entries:
            aircraft = (entry.get("aircraft") or "").strip()
            airline = (entry.get("airline") or "").strip()
            route = (entry.get("route") or "").strip()
            if aircraft:
                aircraft_counts[aircraft] = aircraft_counts.get(aircraft, 0) + 1
            if airline:
                airline_counts[airline] = airline_counts.get(airline, 0) + 1
            if route:
                route_counts[route] = route_counts.get(route, 0) + 1

        profile_minutes = int(getattr(state, "profile_total_flight_minutes", 0) or 0)
        online_flight_count = int(getattr(state, "profile_online_flights", 0) or 0)
        total_landings = int(getattr(state, "profile_total_landings", 0) or 0)
        member_since = normalize_member_since_date(getattr(state, "profile_member_since", "") or default_member_since_date())

        total_hours = format_profile_minutes(profile_minutes) if profile_minutes else "—"
        online_flight_count = str(online_flight_count)
        total_landings = str(total_landings)
        average_minutes = int(round(logged_minutes / logged_flights)) if logged_flights else 0
        average_sector = format_hours_to_hm(average_minutes / 60.0) if average_minutes else "—"
        most_used_aircraft = max(aircraft_counts, key=aircraft_counts.get) if aircraft_counts else (state.aircraft or "—")
        most_used_airline = max(airline_counts, key=airline_counts.get) if airline_counts else (state.airline or "—")
        most_used_route = max(route_counts, key=route_counts.get) if route_counts else "—"
        violations_value = str(int(getattr(state, "profile_violations", 0) or 0))
        favorite_airline_value = (getattr(state, "profile_favorite_airline", "") or state.airline or "—").strip() or "—"
        favorite_aircraft_value = (getattr(state, "profile_favorite_aircraft", "") or state.aircraft or "—").strip() or "—"
        countries_visited_value = str(int(getattr(state, "profile_countries_visited", 0) or 0))

        def profile_image_src() -> Optional[str]:
            raw = (getattr(state, "profile_image_path", "") or "").strip()
            if raw:
                possible = Path(raw)
                if possible.exists():
                    return str(possible)
                asset_rel = raw.replace("\\", "/")
                found = asset_rel_path_if_exists(asset_rel)
                if found:
                    return found
            for rel in (
                "profile/profile_photo.png",
                "profile/profile_photo.jpg",
                "profile/profile_photo.jpeg",
                "profile/profile_photo.webp",
                "profile/pilot_profile.png",
                "profile/pilot_profile.jpg",
            ):
                found = asset_rel_path_if_exists(rel)
                if found:
                    return found
            return None

        def profile_photo_control(size: int = 58) -> ft.Control:
            src = profile_image_src()
            if src:
                return ft.Image(src=src, width=size, height=size, fit=ft.BoxFit.COVER, border_radius=999)
            return ft.Icon(ft.Icons.PERSON, size=int(size * 0.48), color=tokens["accent"])

        def transparent_profile_stat_card(label: str, value: str, subtitle: str = "") -> ft.Control:
            return ft.Container(
                height=88,
                padding=ft.padding.only(left=14, right=14, top=10, bottom=10),
                border_radius=CARD_RADIUS,
                bgcolor=surface_fill(tokens["subpanel"]),
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    spacing=4,
                    controls=[
                        ft.Text(label.upper(), size=10, weight=ft.FontWeight.W_700, color=ft.Colors.with_opacity(0.72, tokens["text"])),
                        ft.Text(value or "—", size=19, weight=ft.FontWeight.W_900, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        def career_name_card() -> ft.Control:
            return ft.Container(
                height=96,
                padding=ft.padding.only(left=18, right=18, top=12, bottom=12),
                border_radius=CARD_RADIUS,
                bgcolor=surface_fill(tokens["subpanel"]),
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Row(
                    spacing=14,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(
                            width=62,
                            height=62,
                            border_radius=999,
                            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                            bgcolor=ft.Colors.with_opacity(0.12, tokens["accent"]),
                            border=ft.border.all(2, ft.Colors.with_opacity(0.50, tokens["accent"])),
                            alignment=ft.Alignment(0, 0),
                            content=profile_photo_control(58),
                        ),
                        ft.Column(
                            tight=True,
                            spacing=4,
                            controls=[
                                ft.Text("PASSPORT HOLDER", size=10, weight=ft.FontWeight.W_800, color=ft.Colors.with_opacity(0.72, tokens["text"])),
                                ft.Text(state.pilot_name or "Pilot", size=24, weight=ft.FontWeight.W_900, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text("FMS CREW PROFILE  •  DIGITAL FLIGHT RECORD", size=10, weight=ft.FontWeight.W_700, color=tokens["muted"]),
                            ],
                        ),
                    ],
                ),
            )

        def usage_stat_card(label: str, value: str, subtitle: str = "") -> ft.Control:
            return ft.Container(
                width=245,
                height=118,
                padding=16,
                border_radius=CARD_RADIUS,
                bgcolor=surface_fill(tokens["subpanel"]),
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    spacing=6,
                    controls=[
                        ft.Text(label, size=12, color=tokens["muted"]),
                        ft.Text(value or "—", size=20, weight=ft.FontWeight.W_800, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(subtitle, size=11, color=tokens["muted"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        def profile_info_row(label: str, value: str) -> ft.Control:
            return ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Text(label, size=12, color=tokens["muted"]),
                    ft.Text(value or "—", size=12, weight=ft.FontWeight.W_700, color=tokens["text"]),
                ],
            )

        def open_profile_editor(e=None):
            pilot_tf = ft.TextField(
                label="Pilot name",
                value=state.pilot_name or "",
                width=340,
                bgcolor=tokens["input_bg"],
                color=tokens["text"],
                border_radius=14,
            )
            member_since_tf = ft.TextField(
                label="Member since",
                value=member_since,
                hint_text="YYYY-MM-DD",
                width=340,
                bgcolor=tokens["input_bg"],
                color=tokens["text"],
                border_radius=14,
            )
            flight_time_tf = ft.TextField(
                label="Total flight time",
                value="" if total_hours == "—" else total_hours,
                width=340,
                bgcolor=tokens["input_bg"],
                color=tokens["text"],
                border_radius=14,
            )
            online_tf = ft.TextField(
                label="Online flight count",
                value="" if online_flight_count == "0" else online_flight_count,
                width=340,
                bgcolor=tokens["input_bg"],
                color=tokens["text"],
                border_radius=14,
            )
            landings_tf = ft.TextField(
                label="Total landings",
                value="" if total_landings == "0" else total_landings,
                width=340,
                bgcolor=tokens["input_bg"],
                color=tokens["text"],
                border_radius=14,
            )
            violations_tf = ft.TextField(
                label="Violations",
                value="" if violations_value == "0" else violations_value,
                width=340,
                bgcolor=tokens["input_bg"],
                color=tokens["text"],
                border_radius=14,
            )
            favorite_airline_tf = ft.TextField(
                label="Favorite airline",
                value="" if favorite_airline_value == "—" else favorite_airline_value,
                width=340,
                bgcolor=tokens["input_bg"],
                color=tokens["text"],
                border_radius=14,
            )
            favorite_aircraft_tf = ft.TextField(
                label="Favorite aircraft",
                value="" if favorite_aircraft_value == "—" else favorite_aircraft_value,
                width=340,
                bgcolor=tokens["input_bg"],
                color=tokens["text"],
                border_radius=14,
            )
            countries_visited_tf = ft.TextField(
                label="Countries visited",
                value="" if countries_visited_value == "0" else countries_visited_value,
                width=340,
                bgcolor=tokens["input_bg"],
                color=tokens["text"],
                border_radius=14,
            )
            profile_image_status_text = ft.Text(
                "No profile image selected." if not getattr(state, "profile_image_path", "") else "Profile image selected.",
                size=11,
                color=tokens["muted"],
            )

            modal_holder = {"control": None}

            def select_profile_image(e=None):
                try:
                    import tkinter as tk
                    from tkinter import filedialog

                    root = tk.Tk()
                    root.withdraw()
                    root.attributes("-topmost", True)
                    picked_path = filedialog.askopenfilename(
                        title="Select profile picture",
                        filetypes=[
                            ("Image files", "*.png *.jpg *.jpeg *.webp"),
                            ("PNG files", "*.png"),
                            ("JPEG files", "*.jpg *.jpeg"),
                            ("WEBP files", "*.webp"),
                            ("All files", "*.*"),
                        ],
                    )
                    root.destroy()

                    if not picked_path:
                        profile_image_status_text.value = "No image selected."
                        profile_image_status_text.color = tokens["muted"]
                        page.update()
                        return

                    state.profile_image_path = str(picked_path)
                    save_profile_data()
                    profile_image_status_text.value = "Profile image selected. Press Save to refresh the passport."
                    profile_image_status_text.color = tokens["accent"]
                    page.update()
                except Exception as ex:
                    profile_image_status_text.value = "Could not open the image picker. Try running the app as a desktop app."
                    profile_image_status_text.color = "#FF8080"
                    try:
                        print(f"Profile image picker error: {ex}")
                    except Exception:
                        pass
                    page.update()

            upload_profile_image_button = ft.OutlinedButton(
                "Upload profile picture",
                icon=ft.Icons.UPLOAD_FILE,
                on_click=select_profile_image,
            )

            def close_dialog(e=None):
                modal = modal_holder.get("control")
                if modal is not None:
                    try:
                        if modal in page.overlay:
                            page.overlay.remove(modal)
                    except Exception:
                        pass
                try:
                    page.update()
                except Exception:
                    pass

            def save_profile(e=None):
                state.pilot_name = (pilot_tf.value or "Pilot").strip() or "Pilot"
                state.profile_member_since = normalize_member_since_date(member_since_tf.value or member_since)
                state.profile_total_flight_minutes = parse_profile_time_minutes(flight_time_tf.value or "")
                try:
                    state.profile_online_flights = max(0, int((online_tf.value or "0").strip() or "0"))
                except Exception:
                    state.profile_online_flights = 0
                try:
                    state.profile_total_landings = max(0, int((landings_tf.value or "0").strip() or "0"))
                except Exception:
                    state.profile_total_landings = 0
                try:
                    state.profile_violations = max(0, int((violations_tf.value or "0").strip() or "0"))
                except Exception:
                    state.profile_violations = 0
                state.profile_favorite_airline = (favorite_airline_tf.value or "").strip()
                state.profile_favorite_aircraft = (favorite_aircraft_tf.value or "").strip()
                try:
                    state.profile_countries_visited = max(0, int((countries_visited_tf.value or "0").strip() or "0"))
                except Exception:
                    state.profile_countries_visited = 0
                save_profile_data()
                close_dialog()
                refresh_ui()

            modal_card = ft.Container(
                width=430,
                height=720,
                padding=22,
                border_radius=24,
                bgcolor=surface_fill(tokens["panel"]),
                border=ft.border.all(1, tokens["card_border"]),
                shadow=ft.BoxShadow(blur_radius=32, spread_radius=2, color=ft.Colors.with_opacity(0.45, ft.Colors.BLACK)),
                content=ft.Column(
                    tight=False,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=14,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Text("Edit Profile", size=22, weight=ft.FontWeight.W_800, color=tokens["text"]),
                                ft.IconButton(
                                    icon=ft.Icons.CLOSE,
                                    tooltip="Close",
                                    icon_color=tokens["text"],
                                    on_click=close_dialog,
                                ),
                            ],
                        ),
                        pilot_tf,
                        member_since_tf,
                        flight_time_tf,
                        online_tf,
                        landings_tf,
                        violations_tf,
                        favorite_airline_tf,
                        favorite_aircraft_tf,
                        countries_visited_tf,
                        upload_profile_image_button,
                        profile_image_status_text,
                        ft.Row(
                            alignment=ft.MainAxisAlignment.END,
                            spacing=10,
                            controls=[
                                ft.TextButton("Cancel", on_click=close_dialog),
                                ft.ElevatedButton("Save", on_click=save_profile, bgcolor=tokens["primary"], color=tokens["on_primary"]),
                            ],
                        ),
                    ],
                ),
            )

            modal = ft.Container(
                expand=True,
                bgcolor=ft.Colors.with_opacity(0.68, ft.Colors.BLACK),
                alignment=ft.Alignment(0, 0),
                content=modal_card,
            )
            modal_holder["control"] = modal
            prepare_controls(modal)
            page.overlay.append(modal)
            page.update()

        profile_top = glass_card(
            "Pilot Profile",
            ft.Row(
                wrap=True,
                spacing=18,
                run_spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=84,
                        height=84,
                        border_radius=24,
                        alignment=ft.Alignment(0, 0),
                        bgcolor=ft.Colors.with_opacity(0.16, tokens["accent"]),
                        border=ft.border.all(1, ft.Colors.with_opacity(0.45, tokens["accent"])),
                        content=ft.Icon(ft.Icons.PERSON, size=42, color=tokens["text"]),
                    ),
                    ft.Column(
                        spacing=8,
                        controls=[
                            ft.Text(state.pilot_name or "Pilot", size=28, weight=ft.FontWeight.W_800, color=tokens["text"]),
                            ft.Text("Flight profile and personal statistics", size=13, color=tokens["muted"]),
                            profile_info_row("Member since", member_since),
                            profile_info_row("Current airline", current_airline_label()),
                            profile_info_row("Current aircraft", current_aircraft_label()),
                            profile_info_row("Current route", current_route_label()),
                        ],
                    ),
                    ft.Container(expand=True),
                    ft.IconButton(icon=ft.Icons.SETTINGS, tooltip="Edit profile", on_click=open_profile_editor, bgcolor=surface_fill(tokens["subpanel"]), icon_color=tokens["text"]),
                ],
            ),
        )

        career_stats = [
            ("Member since", member_since),
            ("Total flight time", total_hours),
            ("Online flights", str(online_flight_count)),
            ("Total landings", str(total_landings)),
            ("Violations", violations_value),
            ("Favorite airline", favorite_airline_value),
            ("Favorite aircraft", favorite_aircraft_value),
            ("Countries visited", countries_visited_value),
        ]
        stats_card = glass_card(
            "Crew Passport",
            ft.Column(
                spacing=GAP, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    career_name_card(),
                    ft.ResponsiveRow(
                        spacing=GAP, run_spacing=GAP,
                        controls=[
                            ft.Container(col=6, content=transparent_profile_stat_card(label, value))
                            for label, value in career_stats
                        ],
                    ),
                ],
            ),
        )

        recent_entries = completed_entries[:5]
        recent_rows = []
        for entry in recent_entries:
            recent_rows.append(
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=14, vertical=10),
                    border_radius=14,
                    bgcolor=surface_fill(tokens["subpanel"]),
                    border=ft.border.all(1, tokens["card_border"]),
                    content=ft.Row(
                        wrap=True,
                        spacing=16,
                        controls=[
                            ft.Text(entry.get("date", "—"), width=110, size=12, color=tokens["muted"]),
                            ft.Text(entry.get("route", "—"), width=160, size=12, weight=ft.FontWeight.W_700, color=tokens["text"]),
                            ft.Text(entry.get("flight_time", "—"), width=90, size=12, color=tokens["text"]),
                            ft.Text(entry.get("aircraft", "—"), width=160, size=12, color=tokens["text"]),
                            ft.Text(entry.get("airline", "—"), width=150, size=12, color=tokens["text"]),
                        ],
                    ),
                )
            )
        if not recent_rows:
            recent_rows = [ft.Text("Completed flights from Calendar will appear here.", color=tokens["muted"], size=12)]

        usage_summary_cards = ft.Row(
            wrap=True,
            spacing=12,
            run_spacing=12,
            controls=[
                usage_stat_card("Most used aircraft", most_used_aircraft, "From completed flight log"),
                usage_stat_card("Most used airline", most_used_airline, "From completed flight log"),
                usage_stat_card("Most used route", most_used_route, "From completed flight log"),
                usage_stat_card("Average sector", average_sector, "From completed flight log"),
            ],
        )

        recent_card = glass_card(
            "Recent Activity",
            ft.Column(
                spacing=12,
                controls=[
                    usage_summary_cards,
                    ft.Divider(height=8, opacity=0.12),
                    *recent_rows,
                ],
            ),
        )

        return ft.Container(
            expand=True,
            bgcolor=ft.Colors.TRANSPARENT,
            padding=GAP,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=16,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.END,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.IconButton(icon=ft.Icons.SETTINGS, tooltip="Edit profile", on_click=open_profile_editor, bgcolor=surface_fill(tokens["subpanel"]), icon_color=tokens["text"]),
                        ],
                    ),
                    ft.ResponsiveRow(
                        spacing=GAP, run_spacing=GAP,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Container(col=7, content=stats_card),
                            ft.Container(col=5, content=recent_card),
                        ],
                    ),
                ],
            ),
        )


    def seats_view():
        if seat_model.get("generated"):
            if not seat_model.get("seat_controls") or seat_map_host.data != seat_map_theme_key():
                render_seat_map(restoring=True)
                update_seat_summary(update_page=False)
        else:
            seat_map_host.content = empty_seat_map()
        seat_passenger_load_host.content = build_passenger_load_panel()

        outline_style = button_style(tokens) if page.theme_mode == ft.ThemeMode.DARK else None

        async def reset_fill(e):
            for field in seat_fill_fields.values():
                field.value = "0"
            page.update()

        control_panel = glass_card_with_background(
            "Cabin Control",
            ft.Column(
                spacing=14,
                controls=[
                    ft.Row(
                        spacing=10,
                        controls=[
                            ft.Container(
                                expand=2,
                                height=86,
                                padding=ft.padding.symmetric(horizontal=14, vertical=12),
                                border_radius=16,
                                bgcolor=surface_fill(tokens["subpanel"]),
                                border=ft.border.all(1, tokens["card_border"]),
                                content=ft.Column(
                                    spacing=8,
                                    controls=[
                                        ft.Text(current_airline_label(), size=16, weight=ft.FontWeight.W_800, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                        ft.Text(current_aircraft_label(), size=14, weight=ft.FontWeight.W_700, color=tokens["text"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                    ],
                                ),
                            ),
                            ft.Container(
                                expand=1,
                                height=86,
                                content=ft.GestureDetector(
                                    mouse_cursor=ft.MouseCursor.CLICK,
                                    on_tap=play_seatbelt_sign_audio,
                                    content=ft.Container(
                                        expand=True,
                                        height=86,
                                        padding=6,
                                        border_radius=16,
                                        bgcolor=surface_fill(tokens["subpanel"]),
                                        border=ft.border.all(1, tokens["card_border"]),
                                        alignment=ft.Alignment(0, 0),
                                        content=ft.Text(
                                            "Seat belt\nsign", size=12, weight=ft.FontWeight.W_800,
                                            color=tokens["text"], text_align=ft.TextAlign.CENTER,
                                        ),
                                    ),
                                ),
                            ),
                        ],
                    ),
                    ft.Divider(height=8, opacity=0.10),
                    ft.Text("Cabin seats", size=14, weight=ft.FontWeight.W_800, color=tokens["text"]),
                    ft.Row(wrap=True, spacing=12, controls=[seat_first_tf, seat_business_tf]),
                    ft.Row(wrap=True, spacing=12, controls=[seat_premium_tf, seat_economy_tf]),
                    ft.Row(wrap=True, spacing=10, controls=[
                        ft.ElevatedButton("Generate Seat Map", on_click=generate_seat_map, bgcolor=tokens["primary"], color=tokens["on_primary"]),
                        ft.OutlinedButton("Clear Occupancy", on_click=clear_seat_occupancy, style=outline_style),
                    ]),
                    seat_status_text,
                    ft.Divider(height=8, opacity=0.10),
                    ft.Text("Fill seats", size=14, weight=ft.FontWeight.W_800, color=tokens["text"]),
                    ft.Row(wrap=True, spacing=12, controls=[seat_fill_first_tf, seat_fill_business_tf]),
                    ft.Row(wrap=True, spacing=12, controls=[seat_fill_premium_tf, seat_fill_economy_tf]),
                    ft.Row(wrap=True, spacing=10, controls=[
                        ft.ElevatedButton("Fill Seats", on_click=auto_fill_seats, bgcolor=tokens["primary"], color=tokens["on_primary"]),
                        ft.OutlinedButton("Reset Fill", on_click=reset_fill, style=outline_style),
                    ]),
                ],
            ),
        )
        return ft.Container(
            expand=True, padding=GAP,
            content=ft.Row(
                expand=True, spacing=GAP, vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Container(expand=True, content=ft.Column(
                        [control_panel, seat_passenger_load_host], spacing=GAP, scroll=ft.ScrollMode.AUTO,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    )),
                    ft.Container(width=486, content=seat_map_scroll),
                    ft.Container(expand=True, content=baggage_view()),
                ],
            ),
        )

    def payload_page() -> ft.Control:
        return build_tab_page("PAYLOAD", seats_view())

    def placeholder_page(title: str):
        return ft.Container(
            expand=True,
            padding=18,
            bgcolor=ft.Colors.TRANSPARENT,
            content=glass_card(title, ft.Text("Phase A placeholder.", color=tokens["text"])),
        )

    def airline_logo_instruction_path(airline_name: str) -> str:
        slug = airline_asset_slug(airline_name)
        return str(base_dir / "assets" / "airlines" / "logos" / f"{slug}.png")

    def refresh_airline_option_controls(preferred_airline: Optional[str] = None):
        for ctrl in [airline_dd, seat_airline_dd]:
            ctrl.options = [ft.dropdown.Option(name) for name in AIRLINES]
            if ctrl.value not in (None, "") and ctrl.value not in AIRLINES:
                ctrl.value = None
        if preferred_airline:
            if airline_dd.value in (None, ""):
                airline_dd.value = preferred_airline if preferred_airline in AIRLINES else airline_dd.value
            if seat_airline_dd.value in (None, ""):
                seat_airline_dd.value = state.airline if state.airline in AIRLINES else None

    def visible_dropdown_option(value: str, color: Optional[str] = None):
        label = str(value)
        text_color = color or tokens["text"]
        try:
            return ft.dropdown.Option(
                key=label,
                text=label,
                content=ft.Text(label, color=text_color),
            )
        except TypeError:
            return ft.dropdown.Option(label)

    def sync_settings_controls(update_page: bool = False):
        settings_daylight_switch.value = str(state.display_mode).lower() == "daylight"
        settings_brightness_slider.value = clamp_setting(state.display_brightness, 0.70, 1.30, 1.0)
        settings_contrast_slider.value = clamp_setting(state.display_contrast, 0.70, 1.35, 1.0)
        settings_overlay_slider.value = clamp_setting(state.airline_overlay_opacity, 0.0, 0.80, 0.50)
        settings_volume_slider.value = clamp_setting(getattr(state, "app_volume", 0.85), 0.0, 1.0, 0.85)
        settings_mute_switch.value = bool(getattr(state, "app_muted", False))
        settings_brightness_value_text.value = f"{settings_brightness_slider.value:.2f}×"
        settings_contrast_value_text.value = f"{settings_contrast_slider.value:.2f}×"
        settings_overlay_value_text.value = f"{int(settings_overlay_slider.value * 100)}%"
        settings_volume_value_text.value = "Muted" if settings_mute_switch.value else f"{int(settings_volume_slider.value * 100)}%"
        settings_fuel_unit_dd.value = state.default_fuel_unit if state.default_fuel_unit in ("kg", "lb") else "kg"
        settings_distance_unit_dd.value = state.default_distance_unit if state.default_distance_unit in ("NM", "km") else "NM"
        settings_temperature_unit_dd.value = state.default_temperature_unit if state.default_temperature_unit in ("°C", "°F") else "°C"
        settings_low_performance_switch.value = bool(state.low_performance_mode)
        settings_brightness_value_text.color = tokens["muted"]
        settings_contrast_value_text.color = tokens["muted"]
        settings_overlay_value_text.color = tokens["muted"]
        settings_volume_value_text.color = tokens["muted"]
        settings_airline_status_text.color = tokens["muted"]
        settings_custom_airlines_text.color = tokens["muted"]
        settings_export_status_text.color = tokens["muted"]
        settings_calendar_import_status_text.color = tokens["muted"]
        settings_background_status_text.color = tokens["muted"]
        if state.custom_airlines:
            settings_remove_airline_dd.disabled = False
            settings_remove_airline_dd.options = [visible_dropdown_option(name, tokens["text"]) for name in state.custom_airlines]
            if settings_remove_airline_dd.value not in state.custom_airlines:
                settings_remove_airline_dd.value = state.custom_airlines[0]
        else:
            settings_remove_airline_dd.disabled = True
            settings_remove_airline_dd.options = [visible_dropdown_option("No custom airlines added", tokens["muted"])]
            settings_remove_airline_dd.value = "No custom airlines added"
        try:
            settings_remove_airline_btn.disabled = not bool(state.custom_airlines)
        except NameError:
            pass
        for ctrl in (settings_fuel_unit_dd, settings_distance_unit_dd, settings_temperature_unit_dd, settings_remove_airline_dd):
            ctrl.bgcolor = tokens["input_bg"]
            ctrl.color = tokens["text"]
            ctrl.border_color = tokens["card_border"]
            ctrl.label_style = ft.TextStyle(color=tokens["muted"])
        if state.custom_airlines:
            settings_custom_airlines_text.value = "Custom airlines: " + ", ".join(state.custom_airlines)
        else:
            settings_custom_airlines_text.value = "Custom airlines: none"
        if update_page:
            page.update()

    def apply_display_settings(e=None):
        state.display_mode = "daylight" if bool(settings_daylight_switch.value) else "dark"
        state.display_brightness = clamp_setting(settings_brightness_slider.value, 0.70, 1.30, 1.0)
        state.display_contrast = clamp_setting(settings_contrast_slider.value, 0.70, 1.35, 1.0)
        state.airline_overlay_opacity = clamp_setting(settings_overlay_slider.value, 0.0, 0.80, 0.50)
        save_settings_data()
        sync_settings_controls(update_page=False)
        refresh_ui()

    def reset_display_settings(e=None):
        state.display_mode = "daylight"
        state.display_brightness = 1.0
        state.display_contrast = 1.0
        state.airline_overlay_opacity = 0.50
        save_settings_data()
        sync_settings_controls(update_page=False)
        refresh_ui()

    def apply_aviation_default_settings(e=None):
        fuel_unit = settings_fuel_unit_dd.value or "kg"
        distance_unit = settings_distance_unit_dd.value or "NM"
        temperature_unit = settings_temperature_unit_dd.value or "°C"
        state.default_fuel_unit = fuel_unit if fuel_unit in ("kg", "lb") else "kg"
        state.default_distance_unit = distance_unit if distance_unit in ("NM", "km") else "NM"
        state.default_temperature_unit = temperature_unit if temperature_unit in ("°C", "°F") else "°C"
        save_settings_data()
        sync_settings_controls(update_page=True)

    def apply_performance_settings(e=None):
        state.low_performance_mode = bool(settings_low_performance_switch.value)
        state.banner_animation_enabled = False
        save_settings_data()
        sync_settings_controls(update_page=False)
        refresh_header_banner_tick(reset=True)
        refresh_ui()

    def apply_audio_settings(e=None):
        state.app_volume = clamp_setting(settings_volume_slider.value, 0.0, 1.0, 0.85)
        state.app_muted = bool(settings_mute_switch.value)
        save_settings_data()
        sync_settings_controls(update_page=True)

    def timestamp_for_export() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def export_calendar_data(e=None):
        try:
            export_dir = storage_dir / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            export_path = export_dir / f"calendar_export_{timestamp_for_export()}.json"
            payload = {
                "export_type": "calendar",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "entries": state.calendar_entries,
            }
            export_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            settings_export_status_text.value = f"Calendar exported: {export_path}"
            show_snack(f"Calendar exported to {export_path}")
            sync_settings_controls(update_page=True)
        except Exception as ex:
            settings_export_status_text.value = f"Calendar export failed: {ex}"
            settings_export_status_text.color = "#FF8080"
            page.update()

    def export_profile_data(e=None):
        try:
            export_dir = storage_dir / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            export_path = export_dir / f"profile_export_{timestamp_for_export()}.json"
            payload = {
                "export_type": "profile",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "pilot_name": state.pilot_name or "Pilot",
                "member_since": normalize_member_since_date(getattr(state, "profile_member_since", "") or default_member_since_date()),
                "total_flight_minutes": int(getattr(state, "profile_total_flight_minutes", 0) or 0),
                "online_flights": int(getattr(state, "profile_online_flights", 0) or 0),
                "total_landings": int(getattr(state, "profile_total_landings", 0) or 0),
            }
            export_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            settings_export_status_text.value = f"Profile exported: {export_path}"
            show_snack(f"Profile exported to {export_path}")
            sync_settings_controls(update_page=True)
        except Exception as ex:
            settings_export_status_text.value = f"Profile export failed: {ex}"
            settings_export_status_text.color = "#FF8080"
            page.update()

    def choose_file_with_tk(title: str, filetypes: List[tuple[str, str]]) -> str:
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            picked_path = filedialog.askopenfilename(title=title, filetypes=filetypes)
            root.destroy()
            return picked_path or ""
        except Exception:
            return ""

    def normalize_imported_calendar_entries(raw_entries) -> List[dict]:
        if not isinstance(raw_entries, list):
            raise ValueError("Calendar file must contain an entries list.")

        imported_entries: List[dict] = []
        for idx, raw_entry in enumerate(raw_entries, start=1):
            if not isinstance(raw_entry, dict):
                raise ValueError(f"Calendar entry {idx} is not valid.")

            entry = dict(raw_entry)
            entry["id"] = str(entry.get("id") or datetime.now().strftime("%Y%m%d%H%M%S%f") + f"_{idx}")
            entry["date"] = str(entry.get("date") or "").strip()
            entry["time"] = str(entry.get("time") or "").strip()
            entry["airline"] = str(entry.get("airline") or "").strip()
            entry["aircraft"] = str(entry.get("aircraft") or "").strip()

            origin = normalize_airport_code(entry.get("origin")) or str(entry.get("origin") or "").strip().upper()
            destination = normalize_airport_code(entry.get("destination")) or str(entry.get("destination") or "").strip().upper()
            entry["origin"] = origin
            entry["destination"] = destination
            if not entry.get("route") and origin and destination:
                entry["route"] = f"{origin} -> {destination}"

            entry["flight_time"] = str(entry.get("flight_time") or "").strip()
            entry["notes"] = str(entry.get("notes") or "").strip()
            entry["completed"] = bool(entry.get("completed", False))
            entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
            imported_entries.append(entry)

        return imported_entries

    def import_calendar_data(e=None):
        picked_path = choose_file_with_tk(
            "Select calendar JSON export",
            [
                ("Calendar JSON", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if not picked_path:
            settings_calendar_import_status_text.value = "No calendar file selected."
            settings_calendar_import_status_text.color = tokens["muted"]
            page.update()
            return

        try:
            data = json.loads(Path(picked_path).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                export_type = str(data.get("export_type") or "").strip().lower()
                if export_type and export_type != "calendar":
                    raise ValueError("This JSON file is not a calendar export.")
                raw_entries = data.get("entries")
            else:
                raw_entries = data

            imported_entries = normalize_imported_calendar_entries(raw_entries)
            state.calendar_entries = imported_entries
            state.calendar_editing_id = None
            state.calendar_selected_date = ""
            sort_calendar_entries_default()
            save_calendar_entries()
            reset_calendar_form()

            settings_calendar_import_status_text.value = f"Calendar imported: {len(imported_entries)} entries from {picked_path}"
            settings_calendar_import_status_text.color = tokens["accent"]
            show_snack(f"Calendar imported: {len(imported_entries)} entries.")
            refresh_ui()
        except Exception as ex:
            settings_calendar_import_status_text.value = f"Calendar import failed: {ex}"
            settings_calendar_import_status_text.color = "#FF8080"
            page.update()

    def upload_global_background(e=None):
        picked_path = choose_file_with_tk(
            "Select global app background",
            [
                ("Image files", "*.png *.jpg *.jpeg *.webp"),
                ("PNG files", "*.png"),
                ("JPEG files", "*.jpg *.jpeg"),
                ("WEBP files", "*.webp"),
                ("All files", "*.*"),
            ],
        )
        if not picked_path:
            settings_background_status_text.value = "No background image selected."
            settings_background_status_text.color = tokens["muted"]
            page.update()
            return

        try:
            source = Path(picked_path)
            suffix = source.suffix.lower()
            if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
                raise ValueError("Background must be PNG, JPG, JPEG, or WEBP.")

            target_dir = base_dir / "assets" / "backgrounds"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"app_background{suffix}"
            for old_background in target_dir.glob("app_background.*"):
                if old_background.resolve() != target.resolve():
                    try:
                        old_background.unlink()
                    except Exception:
                        pass
            target.write_bytes(source.read_bytes())
            clear_asset_lookup_caches()

            settings_background_status_text.value = f"Global background set: {target}"
            settings_background_status_text.color = tokens["accent"]
            show_snack("Global app background updated.")
            refresh_ui()
        except Exception as ex:
            settings_background_status_text.value = f"Background upload failed: {ex}"
            settings_background_status_text.color = "#FF8080"
            page.update()

    def open_reset_profile_confirmation(e=None):
        def close_dialog(evt=None):
            page.pop_dialog()

        def reset_profile_stats(evt=None):
            state.profile_total_flight_minutes = 0
            state.profile_online_flights = 0
            state.profile_total_landings = 0
            save_profile_data()
            settings_export_status_text.value = "Profile statistics reset. Calendar flights were not deleted."
            close_dialog()
            refresh_ui()
            show_snack("Profile statistics reset.")

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Reset Profile Statistics", color=tokens["text"]),
            content=ft.Text(
                "This resets total flight time, online flights, and total landings. Calendar flights will not be deleted.",
                color=tokens["muted"],
            ),
            actions=[
                ft.TextButton("Cancel", on_click=close_dialog),
                ft.ElevatedButton("Reset Profile", on_click=reset_profile_stats, bgcolor="#8B1E1E", color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        show_alert(dialog)

    def open_add_airline_dialog(e=None):
        new_airline_tf = ft.TextField(
            label="Airline name",
            hint_text="Example: Simorgh Airlines",
            width=380,
            border_radius=16,
            filled=True,
            bgcolor=tokens["input_bg"],
            color=tokens["text"],
            border_color=tokens["card_border"],
            focused_border_color=tokens["accent"],
            label_style=ft.TextStyle(color=tokens["muted"]),
        )
        dialog_message = ft.Text(
            "Enter the airline name exactly as you want it to appear.",
            size=12,
            color=tokens["muted"],
        )
        logo_hint_text = ft.Text(
            "The app will create/check the logo folder and show the exact PNG path after adding.",
            size=11,
            color=tokens["muted"],
        )
        modal_holder: Dict[str, Optional[ft.Control]] = {"control": None}

        def close_modal(evt=None):
            modal = modal_holder.get("control")
            try:
                if modal in page.overlay:
                    page.overlay.remove(modal)
            except Exception:
                pass
            page.update()

        def add_airline_from_dialog(evt=None):
            airline_name = re.sub(r"\s+", " ", (new_airline_tf.value or "").strip())
            if not airline_name:
                dialog_message.value = "Enter an airline name first."
                dialog_message.color = "#FF8080"
                try:
                    dialog_message.update()
                except Exception:
                    page.update()
                return

            already_exists = any(name.lower() == airline_name.lower() for name in AIRLINES)
            registered_name = register_custom_airline(airline_name)
            if not registered_name:
                dialog_message.value = "Could not add this airline name."
                dialog_message.color = "#FF8080"
                try:
                    dialog_message.update()
                except Exception:
                    page.update()
                return

            try:
                (base_dir / "assets" / "airlines" / "logos").mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

            refresh_airline_option_controls(registered_name)
            clear_asset_lookup_caches()
            save_settings_data()
            logo_path = airline_logo_instruction_path(registered_name)
            settings_airline_status_text.value = f"{registered_name} is available. Add its logo here: {logo_path}"
            sync_settings_controls(update_page=False)
            close_modal()
            refresh_ui()
            if already_exists:
                show_snack(f"{registered_name} already exists in the airline list.")
            else:
                show_snack(f"{registered_name} added. Logo path: {logo_path}")

        add_button = ft.ElevatedButton("Add Airline", bgcolor=tokens["primary"], color=tokens["on_primary"])
        cancel_button = ft.TextButton("Cancel")
        add_button.on_click = add_airline_from_dialog
        cancel_button.on_click = close_modal
        try:
            new_airline_tf.on_submit = add_airline_from_dialog
        except Exception:
            pass

        modal_card = ft.Container(
            width=460,
            padding=20,
            border_radius=22,
            bgcolor=surface_fill(tokens["panel"]),
            border=ft.border.all(1, tokens["card_border"]),
            shadow=ft.BoxShadow(
                blur_radius=24,
                spread_radius=1,
                color=ft.Colors.with_opacity(0.22, ft.Colors.BLACK),
                offset=ft.Offset(0, 8),
            ),
            content=ft.Column(
                tight=True,
                spacing=14,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text("Add Airline", size=18, weight=ft.FontWeight.W_800, color=tokens["text"]),
                            ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close", icon_color=tokens["text"], on_click=close_modal),
                        ],
                    ),
                    new_airline_tf,
                    dialog_message,
                    logo_hint_text,
                    ft.Row(
                        alignment=ft.MainAxisAlignment.END,
                        spacing=10,
                        controls=[cancel_button, add_button],
                    ),
                ],
            ),
        )

        modal = ft.Container(
            expand=True,
            bgcolor=ft.Colors.with_opacity(0.56, ft.Colors.BLACK),
            alignment=ft.Alignment(0, 0),
            content=modal_card,
        )
        modal_holder["control"] = modal
        prepare_controls(modal)
        page.overlay.append(modal)
        page.update()

    def remove_selected_custom_airline(e=None):
        airline_name = (settings_remove_airline_dd.value or "").strip()
        if not airline_name:
            settings_airline_status_text.value = "Select a custom airline to remove."
            settings_airline_status_text.color = "#FF8080"
            sync_settings_controls(update_page=True)
            return
        if airline_name not in state.custom_airlines:
            settings_airline_status_text.value = "Only airlines added in Settings can be removed."
            settings_airline_status_text.color = "#FF8080"
            sync_settings_controls(update_page=True)
            return

        state.custom_airlines = [name for name in state.custom_airlines if name != airline_name]
        try:
            AIRLINES.remove(airline_name)
        except ValueError:
            pass
        AIRLINE_LOGO_FILES.pop(airline_name, None)
        AIRLINE_ACCENT.pop(airline_name, None)
        AIRLINE_BACKGROUND.pop(airline_name, None)
        AIRLINE_FLEETS.pop(airline_name, None)

        if state.airline == airline_name:
            state.airline = ""
            state.flight_status = derive_idle_status()
        for ctrl in (airline_dd, seat_airline_dd):
            if ctrl.value == airline_name:
                ctrl.value = None

        refresh_airline_option_controls()
        clear_asset_lookup_caches()
        save_settings_data()
        settings_remove_airline_dd.value = state.custom_airlines[0] if state.custom_airlines else None
        settings_airline_status_text.value = f"{airline_name} was removed from the custom airline list. Logo files were not deleted."
        sync_settings_controls(update_page=False)
        refresh_ui()
        show_snack(f"{airline_name} removed.")

    settings_add_airline_btn = ft.ElevatedButton("Add Airline", bgcolor=tokens["primary"], color=tokens["on_primary"])
    settings_remove_airline_btn = ft.OutlinedButton("Remove Airline")
    try:
        settings_remove_airline_btn.style = ft.ButtonStyle(color=tokens["text"])
    except Exception:
        pass
    settings_add_airline_btn.on_click = open_add_airline_dialog
    settings_remove_airline_btn.on_click = remove_selected_custom_airline

    settings_daylight_switch.on_change = apply_display_settings
    settings_brightness_slider.on_change = apply_display_settings
    settings_contrast_slider.on_change = apply_display_settings
    settings_overlay_slider.on_change = apply_display_settings
    settings_fuel_unit_dd.on_select = apply_aviation_default_settings
    settings_distance_unit_dd.on_select = apply_aviation_default_settings
    settings_temperature_unit_dd.on_select = apply_aviation_default_settings
    settings_low_performance_switch.on_change = apply_performance_settings
    sync_settings_controls(update_page=False)

    IF_API_BASE_URL = "https://api.infiniteflight.com/public/v2"
    IF_TRAFFIC_INTERVAL = 5
    IF_IDLE_TIMEOUT_SECONDS = 15 * 60
    IF_ERROR_LABELS = {
        0: "Ok",
        1: "User not found",
        2: "Missing request parameters",
        3: "Endpoint error",
        4: "Not authorized",
        5: "Server not found",
        6: "Flight not found",
        7: "No ATIS available",
        8: "Airport not found",
        9: "Exceeded maximum request size",
    }
    IF_WORLD_TYPES = {
        0: "Solo",
        1: "Casual",
        2: "Training",
        3: "Expert",
        4: "Private",
    }
    def if_now() -> float:
        return time.time()

    def if_mark_activity():
        state.if_last_activity_timestamp = if_now()
        state.if_polling_paused = False

    def if_error_label(code) -> str:
        try:
            return IF_ERROR_LABELS.get(int(code), f"API error {code}")
        except Exception:
            return "API error"

    def if_local_api_key() -> str:
        return read_api_key(infinite_flight_key_path)

    def if_clear_selection():
        state.if_selected_flight = {}
        state.if_selected_flight_plan = {}
        state.if_selected_route_points = []
        state.if_selected_route_start_label = ""
        state.if_selected_route_end_label = ""
        state.if_followed_flight_id = ""

    def if_reset_connection():
        nonlocal live_aircraft_catalog_checked_at
        if_clear_selection()
        state.if_sessions = []
        state.if_selected_session_id = ""
        state.if_selected_session_name = ""
        state.if_live_flights = []
        state.if_traffic_session = ""
        state.if_last_traffic_refresh = "Never"
        state.if_last_live_refresh_attempt = 0.0
        state.if_traffic_retry_at = 0.0
        state.if_atc_session = ""
        state.if_atc_checked_at = 0.0
        state.if_atc_markers = []
        state.if_last_error = ""
        state.if_cache.clear()
        live_aircraft_names.clear()
        live_aircraft_catalog_checked_at = 0.0

    def if_cache_get(key: str, ttl_seconds: int):
        cached = state.if_cache.get(key)
        if not cached:
            return None
        age = if_now() - float(cached.get("timestamp", 0.0) or 0.0)
        if age <= ttl_seconds:
            return cached.get("data")
        return None

    def if_cache_set(key: str, data: dict, *, requested_at: float):
        now = if_now()
        for expired in [name for name, entry in state.if_cache.items() if now - entry["timestamp"] > 600]:
            state.if_cache.pop(expired, None)
        state.if_cache[key] = {
            "timestamp": requested_at,
            "data": data,
        }

    def if_api_request(method: str, endpoint: str, body: Optional[dict] = None, cache_key: str = "", ttl_seconds: int = 0, force: bool = False):
        if state.if_last_activity_timestamp and if_now() - state.if_last_activity_timestamp > IF_IDLE_TIMEOUT_SECONDS and not force:
            state.if_polling_paused = True
            state.if_last_error = "No API refresh after 15 minutes idle. Press a button to resume."
            return None

        if cache_key and ttl_seconds > 0 and not force:
            cached = if_cache_get(cache_key, ttl_seconds)
            if cached is not None:
                return cached

        api_key = if_local_api_key()
        if not api_key:
            state.if_last_error = "Save an Infinite Flight API key in Settings."
            return None

        url = IF_API_BASE_URL + endpoint
        headers = {
            "Accept": "application/json",
            "User-Agent": f"FMS-Sim-Desktop/{FMS_VERSION}",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")

        try:
            requested_at = if_now()
            request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
            request.add_unredirected_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
                state.if_last_error = ""

                error_code = payload.get("errorCode") if isinstance(payload, dict) else None
                if error_code not in (None, 0):
                    state.if_last_error = if_error_label(error_code)
                    return None

                if cache_key:
                    if_cache_set(cache_key, payload, requested_at=requested_at)
                return payload
        except urllib.error.HTTPError as ex:
            if ex.code == 401:
                state.if_last_error = "Invalid or unauthorized API key."
            elif ex.code == 429:
                state.if_last_error = "Rate limit reached. Wait before refreshing again."
                if cache_key.startswith("flights:"):
                    retry_after = (ex.headers or {}).get("Retry-After", "")
                    try:
                        delay = int(retry_after)
                    except ValueError:
                        try:
                            delay = parsedate_to_datetime(retry_after).timestamp() - if_now()
                        except (ValueError, TypeError, OverflowError, OSError):
                            delay = 60
                    state.if_traffic_retry_at = if_now() + max(IF_TRAFFIC_INTERVAL, delay)
            else:
                state.if_last_error = f"Infinite Flight returned HTTP {ex.code}."
        except urllib.error.URLError:
            state.if_last_error = "Could not reach Infinite Flight."
        except TimeoutError:
            state.if_last_error = "Infinite Flight API request timed out."
        except Exception:
            state.if_last_error = "Infinite Flight returned an unreadable response."
        return None

    def if_get_sessions(force: bool = False) -> List[dict]:
        payload = if_api_request("GET", "/sessions", cache_key="sessions", ttl_seconds=600, force=force)
        sessions = payload.get("result", []) if isinstance(payload, dict) else []
        return [session for session in sessions if isinstance(session, dict) and session.get("id")] if isinstance(sessions, list) else []

    def if_get_flight_plan(session_id: str, flight_id: str, force: bool = False) -> dict:
        if not session_id or not flight_id:
            return {}
        session_path = urllib.parse.quote(session_id, safe="")
        flight_path = urllib.parse.quote(flight_id, safe="")
        payload = if_api_request("GET", f"/sessions/{session_path}/flights/{flight_path}/flightplan", cache_key=f"flightplan:{session_id}:{flight_id}", ttl_seconds=60, force=force)
        result = payload.get("result", {}) if isinstance(payload, dict) else {}
        return result if isinstance(result, dict) else {}

    def if_session_label(session: dict) -> str:
        world_type = IF_WORLD_TYPES.get(int(session.get("worldType", -1) or -1), "Server")
        name = str(session.get("name") or world_type or "Server").strip()
        return name if name.casefold() == world_type.casefold() else f"{world_type} · {name}"

    def if_select_session(session_id: str) -> bool:
        selector = str(session_id or "").strip()
        selected = next((session for session in state.if_sessions if str(session.get("id")) == selector), None)
        if not selected:
            selected = next((session for session in state.if_sessions if if_session_label(session) == selector), None)
        if not selected:
            selected = next((session for session in state.if_sessions if str(session.get("name") or "").strip().lower() == selector.lower()), None)
        if not selected:
            selected = next((session for session in state.if_sessions if IF_WORLD_TYPES.get(int(session.get("worldType", -1) or -1), "").lower() == selector.lower()), None)
        if selected:
            state.if_selected_session_id = str(selected.get("id") or "")
            state.if_selected_session_name = str(selected.get("name") or "")
            return True
        return False

    def if_session_options() -> List[ft.dropdown.Option]:
        options = []
        order = {"Casual": 0, "Training": 1, "Expert": 2, "Solo": 3, "Private": 4}
        sorted_sessions = sorted(
            state.if_sessions,
            key=lambda session: (
                order.get(IF_WORLD_TYPES.get(int(session.get("worldType", -1) or -1), "Private"), 99),
                str(session.get("name") or ""),
            ),
        )
        for session in sorted_sessions:
            options.append(ft.dropdown.Option(key=str(session.get("id") or ""), text=if_session_label(session)))
        return options

    def if_ensure_selected_session():
        if not state.if_sessions:
            state.if_selected_session_id = ""
            state.if_selected_session_name = ""
            return
        current = str(state.if_selected_session_id or "")
        if current and any(str(session.get("id") or "") == current for session in state.if_sessions):
            return
        previous_name = str(state.if_selected_session_name or "").strip().lower()
        if previous_name:
            for session in state.if_sessions:
                if str(session.get("name") or "").strip().lower() == previous_name:
                    state.if_selected_session_id = str(session.get("id") or "")
                    state.if_selected_session_name = str(session.get("name") or "")
                    return
        first = next((session for session in state.if_sessions if session.get("worldType") == 3), state.if_sessions[0])
        state.if_selected_session_id = str(first.get("id") or "")
        state.if_selected_session_name = str(first.get("name") or "")

    def if_number(value, decimals: int = 0, fallback: str = "—") -> str:
        try:
            return f"{float(value):,.{decimals}f}"
        except Exception:
            return fallback

    def if_flight_matches_query(flight: dict, query: str) -> bool:
        q = (query or "").strip().lower()
        if not q:
            return False
        for key in ("callsign", "username", "displayName", "userId", "flightId"):
            value = str(flight.get(key) or "").strip().lower()
            if value and q in value:
                return True
        return False

    def if_float(value) -> Optional[float]:
        try:
            number = float(value)
        except Exception:
            return None
        if math.isnan(number) or math.isinf(number):
            return None
        return number

    def if_valid_lat_lon(lat, lon) -> bool:
        lat_value = if_float(lat)
        lon_value = if_float(lon)
        if lat_value is None or lon_value is None:
            return False
        return -90.0 <= lat_value <= 90.0 and -180.0 <= lon_value <= 180.0

    def if_flight_position(flight: dict) -> Optional[tuple[float, float]]:
        lat = if_float(flight.get("latitude"))
        lon = if_float(flight.get("longitude"))
        if lat is None or lon is None or not if_valid_lat_lon(lat, lon):
            return None
        return lat, lon

    def if_flight_display_name(flight: dict) -> str:
        callsign = str(flight.get("callsign") or "").strip()
        username = str(flight.get("username") or flight.get("displayName") or "").strip()
        if callsign and username:
            return f"{callsign} / {username}"
        return callsign or username or str(flight.get("flightId") or "Unknown flight")[:8]

    def if_flight_heading(flight: dict) -> float:
        heading = if_float(flight.get("heading"))
        if heading is None:
            heading = if_float(flight.get("track"))
        return float(heading or 0.0) % 360.0

    def if_plan_points(plan: dict) -> tuple[List[tuple[float, float]], str, str]:
        points: List[tuple[float, float]] = []
        names: List[str] = []

        def walk(items):
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                location = item.get("location") if isinstance(item.get("location"), dict) else item
                lat = if_float(location.get("latitude"))
                lon = if_float(location.get("longitude"))
                if lat is not None and lon is not None and if_valid_lat_lon(lat, lon):
                    # The Live API often uses 0/0 as a procedure placeholder.
                    if abs(lat) > 0.0001 or abs(lon) > 0.0001:
                        point = (lat, lon)
                        if not points or great_circle_distance_nm_points(points[-1], point) > 0.05:
                            points.append(point)
                            names.append(str(item.get("name") or item.get("identifier") or "Point").strip() or "Point")
                children = item.get("children")
                if isinstance(children, list):
                    walk(children)

        walk(plan.get("flightPlanItems") or plan.get("waypointDetails") or [])
        return points, names[0] if names else "", names[-1] if len(names) > 1 else ""

    def if_find_live_flight(flight_id: str) -> dict:
        target = str(flight_id or "")
        for flight in state.if_live_flights:
            if str(flight.get("flightId") or "") == target:
                return flight
        return {}

    live_aircraft_names = {}
    live_aircraft_catalog_checked_at = 0.0
    aircraft_assets = asset_abs_path_if_exists("live-aircraft/aliases.json")
    live_airports = None
    available_shapes = {path.stem for path in aircraft_assets.parent.glob("*.svg")} if aircraft_assets else set()
    aliases = {}
    if aircraft_assets:
        for model, names in json.loads(aircraft_assets.read_text(encoding="utf-8")).items():
            aliases.update({name: model for name in (model, *names)})

    def if_aircraft_name(flight: dict) -> str:
        return str(flight.get("aircraftName") or flight.get("aircraftType")
                   or live_aircraft_names.get(str(flight.get("aircraftId") or "")) or "")

    def live_airport_record(code):
        nonlocal live_airports
        if not code:
            return None
        known = lookup_airport_record(code)
        if known:
            return known
        if live_airports is None:
            index = asset_abs_path_if_exists("live-aircraft/airports.json")
            live_airports = json.loads(index.read_text(encoding="utf-8")) if index else {}
        entry = live_airports.get(code)
        if entry:
            return {"name": entry[0], "lat": entry[1], "lon": entry[2]}
        return None

    airline_by_prefix = {code: name for name, code in AIRLINE_CALLSIGNS.items() if name != "Generic"}
    airline_by_prefix.update({
        "AFR": "Air France", "AAL": "American Airlines", "ANA": "ANA", "BAW": "British Airways",
        "CPA": "Cathay Pacific", "DAL": "Delta Air Lines", "DLH": "Lufthansa", "ETD": "Etihad Airways",
        "IRA": "Iran Air", "ITY": "ITA Airways", "QFA": "Qantas", "QTR": "Qatar Airways",
        "SIA": "Singapore Airlines", "SWA": "Southwest Airlines", "THY": "Turkish Airlines",
        "UAL": "United Airlines", "VIR": "Virgin Atlantic", "UAE": "Emirates", "IRM": "Mahan Air",
    })

    def if_airline_name(flight):
        name = flight.get("airlineName") or flight.get("airline")
        if isinstance(name, str) and name.strip():
            return name.strip()
        callsign = re.sub(r"\s+", "", str(flight.get("callsign") or "").upper())
        for length in (3, 2):
            name = airline_by_prefix.get(callsign[:length])
            if name and callsign[length:length + 1].isdigit():
                return name
        return "Airline unavailable"

    def if_aircraft_shape(flight: dict, *, selected=False) -> str:
        name = re.sub(r"^(AIRBUS|BOEING|BOMBARDIER|CIRRUS|LOCKHEED MARTIN)\s+", "", if_aircraft_name(flight).upper())
        code = re.sub(r"[^A-Z0-9]", "", name)
        shape = aliases.get(code, code)
        model = shape if shape in available_shapes else "Unidentified"
        suffix = "-selected" if selected else ""
        return f"live-aircraft/{model}{suffix}.svg"

    async def refresh_live_plan(*, render=True):
        session = state.if_selected_session_id
        flight_id = str(state.if_selected_flight.get("flightId") or "")
        if not session or not flight_id:
            return
        async with live_request_lock:
            if not state.overview_live or session != state.if_selected_session_id or flight_id != str(state.if_selected_flight.get("flightId") or ""):
                return
            traffic_error = state.if_last_error
            plan = await asyncio.to_thread(if_get_flight_plan, session, flight_id)
            if not state.if_polling_paused:
                state.if_last_error = traffic_error
            if session != state.if_selected_session_id or flight_id != str(state.if_selected_flight.get("flightId") or ""):
                return
            if plan:
                state.if_selected_flight_plan = plan
                points, first, last = if_plan_points(plan)
                state.if_selected_route_points = points
                state.if_selected_route_start_label = first
                state.if_selected_route_end_label = last
        if render and state.overview_live and state.selected_tab_index == 0 and live_render_callback:
            await live_render_callback()

    async def refresh_live_traffic(*, mark_activity=False):
        nonlocal live_aircraft_catalog_checked_at
        if mark_activity:
            if_mark_activity()
        async with live_request_lock:
            if not state.overview_live or state.selected_tab_index != 0:
                return
            if if_now() < state.if_traffic_retry_at:
                return
            if if_now() - state.if_last_live_refresh_attempt < IF_TRAFFIC_INTERVAL and state.if_traffic_session == state.if_selected_session_id and not mark_activity:
                return
            state.if_last_live_refresh_attempt = if_now()
            if not if_local_api_key():
                state.if_last_error = "Save an Infinite Flight API key in Settings."
            else:
                sessions = await asyncio.to_thread(if_get_sessions)
                if sessions:
                    state.if_sessions = sessions
                    if_ensure_selected_session()
                session = state.if_selected_session_id
                if session:
                    session_path = urllib.parse.quote(session, safe="")
                    state.if_last_live_refresh_attempt = if_now()
                    payload = await asyncio.to_thread(
                        if_api_request, "GET", f"/sessions/{session_path}/flights", None, f"flights:{session}", IF_TRAFFIC_INTERVAL,
                    )
                    if session == state.if_selected_session_id and isinstance(payload, dict) and isinstance(payload.get("result"), list):
                        state.if_live_flights = [
                            flight for flight in payload["result"]
                            if isinstance(flight, dict) and flight.get("flightId")
                            and if_flight_position(flight)
                        ]
                        state.if_traffic_session = session
                        state.if_last_traffic_refresh = datetime.now().strftime("%H:%M:%S")
                        if state.if_selected_flight:
                            selected = if_find_live_flight(str(state.if_selected_flight.get("flightId") or ""))
                            if selected:
                                state.if_selected_flight = selected
                            else:
                                if_clear_selection()
                                state.if_last_error = "The selected aircraft left this session."
                        if state.overview_live and state.selected_tab_index == 0 and live_render_callback:
                            await live_render_callback()
                    if not state.if_last_error and if_now() - live_aircraft_catalog_checked_at >= 600:
                        live_aircraft_catalog_checked_at = if_now()
                        traffic_error = state.if_last_error
                        cached = await asyncio.to_thread(if_api_request, "GET", "/aircraft", None, "aircraft", 600)
                        if isinstance(cached, dict) and isinstance(cached.get("result"), list):
                            live_aircraft_names.update({
                                str(item["id"]): str(item.get("name") or "")
                                for item in cached["result"] if isinstance(item, dict) and item.get("id")
                            })
                        if not state.if_polling_paused:
                            state.if_last_error = traffic_error
                    if not state.if_last_error and live_map_process and (
                        state.if_atc_session != session or if_now() - state.if_atc_checked_at >= 60
                    ):
                        await refresh_live_atc(session, session_path)
                elif not state.if_last_error:
                    state.if_last_error = "Infinite Flight returned no available servers."
        if state.overview_live and state.selected_tab_index == 0 and live_render_callback:
            await live_render_callback()
            if state.if_selected_flight:
                await refresh_live_plan()

    async def refresh_live_clicked(e=None):
        await refresh_live_traffic(mark_activity=True)

    live_map_style = "dark"

    async def refresh_live_atc(session, session_path):
        state.if_atc_session = session
        state.if_atc_checked_at = if_now()
        try:
            payload = await asyncio.to_thread(if_api_request, "GET", f"/sessions/{session_path}/atc", None, f"atc:{session}", 60)
            facilities = payload.get("result") if isinstance(payload, dict) else None
            if session != state.if_selected_session_id or not isinstance(facilities, list):
                return
            labels = {0: "Ground", 1: "Tower", 3: "Clearance", 4: "Approach", 5: "Departure", 6: "Center"}
            markers = {}
            for facility in facilities:
                if not isinstance(facility, dict):
                    continue
                facility_type = str(facility.get("type", "")).strip()
                label = labels.get(int(facility_type)) if facility_type.isdecimal() else None
                if not label:
                    continue
                code = str(facility.get("airportName") or "").strip().upper()
                airport = live_airport_record(code)
                position = (airport["lat"], airport["lon"]) if airport else if_flight_position(facility)
                if position and position != (0, 0):
                    markers.setdefault((position, code), set()).add(label)
            state.if_atc_markers = [
                {"position": [lon, lat], "label": " · ".join(filter(None, [code, ", ".join(sorted(types))]))}
                for ((lat, lon), code), types in markers.items()
            ]
        finally:
            if not state.if_polling_paused:
                state.if_last_error = ""

    def live_flight_timing(flight, plan, arrival=""):
        if not arrival:
            _, arrival = flight_airports(flight, plan, state.if_selected_route_start_label, state.if_selected_route_end_label)
        airport = live_airport_record(arrival)
        position = if_flight_position(flight)
        remaining = (
            great_circle_distance_nm_points(position, (airport["lat"], airport["lon"]))
            if position and airport else None
        )
        return flight_timing(flight, plan, format_hours_to_hm, remaining_nm=remaining)

    def live_map_snapshot():
        flight = state.if_selected_flight
        plan = state.if_selected_flight_plan
        departure, arrival = flight_airports(flight, plan, state.if_selected_route_start_label, state.if_selected_route_end_label)

        def airport(code):
            record = live_airport_record(code) or {}
            return {"code": code, "name": record.get("name", ""), "position": [record["lon"], record["lat"]] if record else None}

        def aircraft(item):
            lat, lon = if_flight_position(item)
            flight_id = str(item["flightId"])
            return {
                "id": flight_id, "position": [lon, lat], "heading": if_flight_heading(item),
                "name": if_flight_display_name(item),
                "callsign": str(item.get("callsign") or ""),
                "shape": Path(if_aircraft_shape(item)).stem,
            }

        details = None
        if flight:
            airline = if_airline_name(flight)
            model = if_aircraft_name(flight)
            photo = aircraft_profile_path(model)
            details = {
                **aircraft(flight), "airline": airline, "model": model,
                "pilot": str(flight.get("username") or flight.get("displayName") or ""),
                "callsign": str(flight.get("callsign") or ""),
                "altitude": if_number(flight.get("altitude")), "speed": if_number(flight.get("speed")),
                "vertical": if_number(flight.get("verticalSpeed")), "photo": photo or "",
                "departure": airport(departure), "arrival": airport(arrival),
                "timing": live_flight_timing(flight, plan, arrival),
                "route": [[lon, lat] for lat, lon in state.if_selected_route_points],
            }
        return {
            "style": live_map_style, "selected": details,
            "atc": state.if_atc_markers if state.if_atc_session == state.if_selected_session_id else [],
            "following": bool(state.if_followed_flight_id),
            "flights": [aircraft(item) for item in state.if_live_flights],
            "session": state.if_selected_session_id,
            "servers": [{"id": str(item["id"]), "name": if_session_label(item)} for item in state.if_sessions],
            "status": state.if_last_error or (
                f"{len(state.if_live_flights):,} aircraft · {state.if_last_traffic_refresh}"
                if state.if_traffic_session else "Connecting to Infinite Flight…"
            ),
            "needsKey": not infinite_flight_key_path.is_file(),
        }

    def handle_live_map_action(action):
        nonlocal live_map_style
        if not isinstance(action, dict):
            return
        kind, value = action.get("type"), action.get("value")
        if not isinstance(kind, str) or not isinstance(value, (str, int, type(None))):
            return
        if_mark_activity()
        if kind == "select":
            flight = if_find_live_flight(value)
            if flight:
                if_clear_selection()
                state.if_selected_flight = flight
                page.run_task(refresh_live_plan)
        elif kind == "close":
            if_clear_selection()
        elif kind == "follow" and state.if_selected_flight:
            state.if_followed_flight_id = "" if state.if_followed_flight_id else str(state.if_selected_flight["flightId"])
        elif kind == "server" and if_select_session(value):
            if_clear_selection()
            state.if_live_flights = []
            state.if_traffic_session = ""
            page.run_task(refresh_live_clicked)
        elif kind == "refresh":
            page.run_task(refresh_live_clicked)
        elif kind == "settings":
            go_to_tab(10)
        elif kind == "style" and value in ("dark", "positron", "bright"):
            live_map_style = value
        if live_render_callback and live_map_process:
            page.run_task(live_render_callback)

    def change_overview_mode(live: bool):
        state.overview_live = live
        if not live:
            if_clear_selection()
            state.if_live_flights = []
            state.if_traffic_session = ""
            state.if_last_error = ""
        refresh_ui()
        if live:
            page.run_task(refresh_live_clicked)

    def compact_settings_field(field):
        field.dense = True
        field.width = None
        field.expand = True
        field.content_padding = ft.Padding.symmetric(horizontal=10, vertical=7)
        if isinstance(field, ft.TextField):
            field.counter = ft.Container(height=0)
        return field

    def compact_settings_row(*controls):
        return ft.Row(list(controls), spacing=7, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def compact_settings_card(title, *controls):
        card = glass_card(title, ft.Column(list(controls), spacing=6,
                                          horizontal_alignment=ft.CrossAxisAlignment.STRETCH))
        card.padding = 10
        card.content.spacing = 6
        return card


    def settings_page():
        sync_settings_controls(update_page=False)

        def slider_row(label, slider, value):
            slider.width = None
            slider.expand = True
            value.size = 11
            return ft.Container(height=35, content=compact_settings_row(
                ft.Text(label, size=11, width=77, color=tokens["text"]), slider, value,
            ))

        def compact_status(control):
            control.max_lines = 2
            control.overflow = ft.TextOverflow.ELLIPSIS
            return control

        display_card = compact_settings_card(
            "Display", settings_daylight_switch,
            slider_row("Brightness", settings_brightness_slider, settings_brightness_value_text),
            slider_row("Contrast", settings_contrast_slider, settings_contrast_value_text),
            slider_row("Airline tint", settings_overlay_slider, settings_overlay_value_text),
            compact_settings_row(ft.OutlinedButton("Reset Display", on_click=reset_display_settings)),
        )
        volume_card = compact_settings_card(
            "Volume", slider_row("Sound level", settings_volume_slider, settings_volume_value_text),
            compact_settings_row(settings_mute_switch, ft.OutlinedButton("Apply Volume", on_click=apply_audio_settings)),
        )
        aviation_card = compact_settings_card(
            "Aviation Defaults",
            compact_settings_row(compact_settings_field(settings_fuel_unit_dd),
                                 compact_settings_field(settings_distance_unit_dd)),
            compact_settings_row(compact_settings_field(settings_temperature_unit_dd)),
        )
        airline_card = compact_settings_card(
            "Airline Management",
            compact_settings_row(settings_add_airline_btn),
            compact_settings_row(compact_settings_field(settings_remove_airline_dd), settings_remove_airline_btn),
            compact_status(settings_airline_status_text),
        )
        data_card = compact_settings_card(
            "Data Management",
            compact_settings_row(
                ft.OutlinedButton("Upload Calendar", expand=True, on_click=import_calendar_data),
                ft.OutlinedButton("Export Calendar", expand=True, on_click=export_calendar_data),
            ),
            compact_settings_row(
                ft.OutlinedButton("Export Profile", expand=True, on_click=export_profile_data),
                ft.OutlinedButton("Reset Profile", expand=True, on_click=open_reset_profile_confirmation),
            ),
            compact_status(settings_calendar_import_status_text),
            compact_status(settings_export_status_text),
        )

        if_api_key_tf = ft.TextField(
            label="Infinite Flight API key", password=True, border_radius=16, filled=True,
            bgcolor=tokens["input_bg"], color=tokens["text"],
        )

        async def save_if_key(e):
            key = (if_api_key_tf.value or "").strip()
            if not key:
                show_snack("Enter an Infinite Flight API key before saving.")
                return
            async with live_request_lock:
                try:
                    write_api_key(infinite_flight_key_path, key)
                except (OSError, AttributeError):
                    show_snack("Windows could not save the Infinite Flight API key.")
                    return
                if_reset_connection()
            refresh_active_page()
            show_snack("Infinite Flight API key saved.")

        async def clear_if_key(e):
            async with live_request_lock:
                try:
                    infinite_flight_key_path.unlink(missing_ok=True)
                except OSError:
                    show_snack("Windows could not remove the Infinite Flight API key.")
                    return
                if_reset_connection()
            refresh_active_page()
            show_snack("Infinite Flight API key removed.")

        key_saved = bool(if_local_api_key())
        api_card = compact_settings_card(
            "Infinite Flight Live API",
            ft.Text("API key saved" if key_saved else "Add your key to enable Live Flights.",
                    size=12, color=tokens["muted"]),
            compact_settings_row(compact_settings_field(if_api_key_tf)),
            compact_settings_row(
                ft.FilledButton("Save Key", on_click=save_if_key),
                ft.OutlinedButton("Clear API Key", on_click=clear_if_key, disabled=not key_saved),
            ),
        )
        performance_card = compact_settings_card("Performance", settings_low_performance_switch)
        return build_tab_page(
            "SETTINGS",
            ft.Container(
                expand=True, padding=GAP,
                content=ft.Row([
                    ft.Column([performance_card], expand=True, spacing=GAP,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                    ft.Column([display_card, volume_card, aviation_card], expand=True, spacing=GAP,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                    ft.Column([api_card, airline_card, data_card], expand=True, spacing=GAP,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                ], expand=True, spacing=GAP, vertical_alignment=ft.CrossAxisAlignment.START),
            ),
        )


    def about_page():
        modules = [
            "Overview", "Dashboard", "Payload", "Checklist", "Takeoff", "Landing",
            "Calendar", "Log", "Profile", "Settings", "About",
        ]
        features = [
            "Operational airline and aircraft selection",
            "Live header banner with route and flight status",
            "Route overview and progress visualization",
            "Seat map, passenger load, baggage, and cargo calculation tools",
            "Takeoff performance planning interface",
            "Landing performance planning interface",
            "Map-assisted route context",
            "Calendar-based flight planning",
            "Completed flight log and review history",
            "Pilot profile and career statistics",
            "Custom airline management",
            "Calendar and profile data export",
            "Display, performance, and interface settings",
        ]

        def info_line(label: str, value: str) -> ft.Control:
            return ft.Row(
                spacing=8,
                wrap=True,
                controls=[
                    ft.Text(f"{label}:", size=12, weight=ft.FontWeight.W_800, color=tokens["muted"]),
                    ft.Text(value, size=12, weight=ft.FontWeight.W_700, color=tokens["text"]),
                ],
            )

        def chip(label: str) -> ft.Control:
            return ft.Container(
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                border_radius=999,
                bgcolor=ft.Colors.with_opacity(0.12, tokens["accent"]),
                border=ft.border.all(1, ft.Colors.with_opacity(0.20, tokens["accent"])),
                content=ft.Text(label, size=11, weight=ft.FontWeight.W_700, color=tokens["text"]),
            )

        def bullet(text_value: str) -> ft.Control:
            return ft.Row(
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Text("•", size=14, color=tokens["accent"]),
                    ft.Text(text_value, size=12, color=tokens["text"]),
                ],
            )

        identity_card = glass_card(
            "Description",
            ft.Column(
                spacing=12,
                controls=[
                    ft.Text(
                        "Flight Management Systems (FMS) is a locally run desktop application for structured aviation workflow management. It brings flight preparation, airline and aircraft selection, route planning, payload and baggage handling, performance references, scheduling, completed flight records, and pilot profile tracking into one operational workspace.",
                        size=13,
                        color=tokens["text"],
                    ),
                    ft.Text(
                        "The application is designed around a command-center interface for simulation, education, and personal planning. It supports airline-based theming, a live flight banner, configurable display settings, local data storage, and export functions for calendar and profile records.",
                        size=13,
                        color=tokens["muted"],
                    ),
                    ft.Divider(height=8, opacity=0.15),
                    info_line("Version", FMS_VERSION),
                    info_line("Author", "Sam Samadi"),
                    info_line("Editor", "Sam Samadi"),
                    info_line("Application type", "Python Flet desktop application"),
                    info_line("Build type", "Local desktop build"),
                    info_line("Aircraft images", "Aircraft images are from Infinite Flight"),
                    info_line("Seat maps", "Seat maps are from SeatMaps.com"),
                ],
            ),
        )

        modules_card = glass_card(
            "Core Modules",
            ft.Row(
                wrap=True,
                spacing=8,
                run_spacing=8,
                controls=[chip(module) for module in modules],
            ),
        )

        features_card = glass_card(
            "Key Features",
            ft.Column(
                spacing=7,
                controls=[bullet(item) for item in features],
            ),
        )

        local_data_card = glass_card(
            "Local Data",
            ft.Column(
                spacing=10,
                controls=[
                    ft.Text("FMS stores settings, calendar flights, and profile information locally.", size=12, color=tokens["text"]),
                    info_line("Data folder", str(storage_dir)),
                ],
            ),
        )

        disclaimer_card = glass_card(
            "Disclaimer",
            ft.Column(
                spacing=10,
                controls=[
                    ft.Text(
                        "Flight Management Systems (FMS) is intended strictly for simulation, education, and personal planning. It is not certified or approved for real-world flight operations, dispatch, navigation, aircraft performance calculation, or any safety-critical aviation decision-making.",
                        size=12,
                        color=tokens["text"],
                    ),
                    ft.Text(
                        "Aircraft imagery shown in the application is credited to Infinite Flight.",
                        size=12,
                        color=tokens["muted"],
                    ),
                    ft.Text(
                        "Seat maps shown in the application are credited to SeatMaps.com.",
                        size=12,
                        color=tokens["muted"],
                    ),
                    ft.Text("© 2026 Sam Samadi. All rights reserved.", size=12, weight=ft.FontWeight.W_700, color=tokens["muted"]),
                ],
            ),
        )

        return build_tab_page(
            "ABOUT",
            ft.Container(
                expand=True,
                padding=ft.padding.only(left=22, right=22, top=18, bottom=24),
                content=ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    spacing=16,
                    controls=[
                        identity_card,
                        ft.Row(
                            wrap=True,
                            spacing=16,
                            run_spacing=16,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                            controls=[
                                ft.Container(width=430, content=modules_card),
                                ft.Container(width=430, content=local_data_card),
                            ],
                        ),
                        features_card,
                        disclaimer_card,
                    ],
                ),
            ),
            overlay_opacity=0.08,
        )

    def build_current_page_view() -> ft.Control:
        selected = max(0, min(13, int(state.selected_tab_index or 0)))
        if selected == 0:
            return overview_page()
        if selected == 1:
            return home_page()
        if selected in (2, 3):
            return payload_page()
        if selected == 13:
            return checklist_page()
        if selected == 4:
            return build_tab_page("TAKEOFF", takeoff_view(), overlay_opacity=0.08)
        if selected == 5:
            return build_tab_page("LANDING", landing_view(), overlay_opacity=0.08)
        if selected == 7:
            return calendar_view()
        if selected == 8:
            return log_view()
        if selected == 9:
            return profile_view()
        if selected == 10:
            return settings_page()
        return about_page()

    def refresh_active_page(update_page: bool = True):
        active_page_host.content = build_current_page_view()
        prepare_controls(active_page_host)
        if getattr(active_page_host, "page", None):
            active_page_host.update()
        elif update_page:
            page.update()

    def navigation_accent():
        gradient = airline_background(state.airline, AIRLINE_ACCENT) if state.aircraft else None
        fill = gradient.colors[0] if gradient else "#D5CEC4"
        ink = max(("#111318", "#FFFFFF"), key=lambda color: contrast_ratio(color, fill))
        return fill, ink

    def refresh_navigation_accent():
        if active_navigation_glyph is not None:
            fill, ink = navigation_accent()
            active_navigation_glyph.bgcolor = fill
            active_navigation_glyph.content.color = ink
            safe_update_control(active_navigation_glyph)

    def app_shell():
        refresh_header_texts()
        active_page_host.content = build_current_page_view()
        active_page_host.bgcolor = surface_fill(tokens["bg"])
        refresh_header_banner_tick()
        background = airline_background(state.airline, AIRLINE_ACCENT)
        header_backdrop = background.colors[0] if background else tokens["bg"]

        def header_ink(tint, opacity):
            glass_surface = blend_hex_colors(header_backdrop, tint, opacity)
            return max(("#111318", "#FFFFFF"), key=lambda color: contrast_ratio(color, glass_surface))

        glass = {
            "blur": ft.Blur(12, 12, ft.BlurTileMode.CLAMP),
            "clip_behavior": ft.ClipBehavior.ANTI_ALIAS,
            "border": ft.Border(
                top=ft.BorderSide(1, ft.Colors.with_opacity(0.24, ft.Colors.WHITE)),
                bottom=ft.BorderSide(1, ft.Colors.with_opacity(0.18, ft.Colors.BLACK)),
            ),
        }
        nav_tint = "#F5EFE6"
        nav_ink = "#292620"
        brand_ink = header_ink(nav_tint, NAV_OPACITY)
        title_ink = header_ink(tokens["bg"], SURFACE_OPACITY)

        destinations = (
            (1, "Dashboard", ft.Icons.HOME_OUTLINED),
            (0, "Overview", ft.Icons.DASHBOARD_OUTLINED),
            (2, "Payload", ft.Icons.INVENTORY_2_OUTLINED),
            (13, "Checklist", ft.Icons.CHECKLIST),
            (4, "Takeoff", ft.Icons.FLIGHT_TAKEOFF_OUTLINED),
            (5, "Landing", ft.Icons.FLIGHT_LAND_OUTLINED),
            (7, "Calendar", ft.Icons.CALENDAR_MONTH_OUTLINED),
            (8, "Log", ft.Icons.RECEIPT_LONG_OUTLINED),
            (9, "Profile", ft.Icons.PERSON_OUTLINE),
            (10, "Settings", ft.Icons.SETTINGS_OUTLINED),
            (11, "About", ft.Icons.INFO_OUTLINE),
        )
        selected = 2 if state.selected_tab_index == 3 else state.selected_tab_index
        title = next((label for index, label, _ in destinations if index == selected), "Overview")

        active_fill, active_ink = navigation_accent()

        def nav_button(index, label, icon):
            nonlocal active_navigation_glyph
            active = index == selected
            glyph = ft.Container(
                width=30, height=30, border_radius=999,
                alignment=ft.Alignment(0, 0),
                bgcolor=active_fill if active else None,
                content=ft.Icon(icon, size=17, color=active_ink if active else "#4A433B"),
            )
            if active:
                active_navigation_glyph = glyph
            content = ft.Row(
                tight=True, spacing=7,
                controls=[glyph, *([ft.Text(label, size=13, color=nav_ink)] if active else [])],
            )
            return ft.TextButton(
                content=content, width=None if active else 39, height=39, tooltip=label,
                style=ft.ButtonStyle(
                    color=nav_ink,
                    bgcolor={
                        ft.ControlState.DEFAULT: surface_fill("#E4DACD"),
                        ft.ControlState.HOVERED: surface_fill("#D5C9BA"),
                    },
                    padding=ft.Padding.only(left=4, right=10 if active else 4, top=4, bottom=4),
                    side={
                        ft.ControlState.DEFAULT: ft.BorderSide(1, "#B7AB9C"),
                        ft.ControlState.FOCUSED: ft.BorderSide(1, "#675D51"),
                    },
                    shape=ft.RoundedRectangleBorder(radius=999),
                ),
                on_click=lambda e, target=index: go_to_tab(target),
            )

        nav_capsule = ft.Container(
            border_radius=999,
            bgcolor=ft.Colors.with_opacity(NAV_OPACITY, nav_tint),
            padding=4,
            content=ft.Row(
                tight=True, alignment=ft.MainAxisAlignment.CENTER, spacing=4,
                controls=[nav_button(*destination) for destination in destinations],
            ),
        )
        navigation = ft.Container(
            height=NAV_HEIGHT,
            padding=ft.Padding.symmetric(horizontal=16),
            bgcolor=ft.Colors.with_opacity(NAV_OPACITY, nav_tint),
            **glass,
            content=ft.Row(
                spacing=8,
                controls=[
                    ft.Row(
                        width=64, spacing=6,
                        controls=[
                            ft.Icon(ft.Icons.FLIGHT, size=20, color=brand_ink),
                            ft.Text("FMS", size=16, weight=ft.FontWeight.W_800, color=brand_ink),
                        ],
                    ),
                    ft.Container(expand=True, alignment=ft.Alignment(0, 0), content=nav_capsule),
                    ft.Container(
                        width=64, alignment=ft.Alignment(1, 0),
                    ),
                ],
            ),
        )

        def route_chip(value, color, foreground):
            return ft.Container(
                height=26, border_radius=5, bgcolor=color,
                padding=ft.Padding.symmetric(horizontal=8), alignment=ft.Alignment(0, 0),
                content=ft.Text(value, size=12, weight=ft.FontWeight.W_600, color=foreground),
            )

        route_controls = []
        live_context = selected == 0 and state.overview_live
        if state.departure and not live_context:
            route_controls.append(route_chip(state.departure, "#FFE54D", "#211D0A"))
        if state.arrival and not live_context:
            if route_controls:
                route_controls.append(ft.Icon(ft.Icons.ARROW_FORWARD, size=14, color=title_ink))
            route_controls.append(route_chip(state.arrival, "#7263E8", "#FFFFFF"))

        context = ft.Container(
            height=CONTEXT_HEIGHT,
            padding=ft.Padding.symmetric(horizontal=16),
            bgcolor=ft.Colors.with_opacity(SURFACE_OPACITY, tokens["bg"]),
            **glass,
            content=ft.Row(
                spacing=GAP,
                controls=[
                    ft.Text(title, size=20, weight=ft.FontWeight.W_700, color=title_ink),
                    *route_controls,
                    ft.Container(
                        expand=True, alignment=ft.Alignment(0, 0),
                        content=header_route_line_host if state.departure and state.arrival and not live_context else None,
                    ),
                    *([ft.OutlinedButton(
                        "Normal Map" if live_context else "Live Flights",
                        icon=ft.Icons.MAP_OUTLINED if live_context else ft.Icons.PUBLIC,
                        height=32, on_click=lambda e: change_overview_mode(not live_context),
                    )] if selected == 0 else []),
                    *([airline_logo_image(state.airline, width=120, height=28, key_prefix="topbar-logo")]
                      if state.airline else []),
                ],
            ),
        )
        return ft.Container(
            expand=True, bgcolor=tokens["bg"], gradient=background,
            content=ft.Column([navigation, context, active_page_host], expand=True, spacing=0),
        )

    def on_tab_change(e):
        selected = e.control.selected_index
        if selected is None:
            return
        selected = max(0, min(13, int(selected)))
        if state.selected_tab_index == selected:
            return
        state.selected_tab_index = selected
        # Do not rebuild the whole app on tab clicks.
        # Flet already switches the visible TabBarView page.
        # Rebuilding here caused tab bounce-backs, double-click behavior,
        # slow transitions, and scroll positions jumping to the top.

    page.add(root_host)
    refresh_ui()

    async def live_update_loop():
        # Flet UI updates are more reliable when scheduled on the page event loop
        # instead of a normal background thread. This loop keeps the clock live and
        # refreshes the Overview aircraft progress every 5 seconds while Play is active.
        nonlocal last_header_second, last_overview_progress_update
        while True:
            await asyncio.sleep(1.0 if bool(getattr(state, "low_performance_mode", False)) else HEADER_BANNER_TICK_SECONDS)
            if not state.is_logged_in:
                continue

            try:
                if state.selected_tab_index == 0:
                    queue_airport_media(state.departure)
                    queue_airport_media(state.arrival)
                current_second = now_local_str()
                should_update_clock = current_second != last_header_second
                progress_refresh_seconds = 15 if bool(getattr(state, "low_performance_mode", False)) else OVERVIEW_PROGRESS_REFRESH_SECONDS
                should_update_progress = (
                    state.overview_takeoff_start_timestamp is not None
                    and state.overview_progress_running
                    and time.time() - last_overview_progress_update >= progress_refresh_seconds
                )
                should_update_if_traffic = (
                    state.selected_tab_index == 0 and state.overview_live and infinite_flight_key_path.is_file()
                    and not state.if_polling_paused
                    and time.time() >= max(state.if_last_live_refresh_attempt + IF_TRAFFIC_INTERVAL, state.if_traffic_retry_at)
                )

                should_update_banner = refresh_header_banner_tick()

                if not should_update_clock and not should_update_progress and not should_update_banner and not should_update_if_traffic:
                    continue

                if should_update_if_traffic:
                    await refresh_live_traffic()

                if should_update_clock:
                    last_header_second = current_second
                    refresh_header_texts()

                if should_update_progress and not (state.selected_tab_index == 0 and state.overview_live):
                    # Live progress update without rebuilding the whole Overview page.
                    # This prevents the Route Schematic card from blinking.
                    last_overview_progress_update = time.time()
                    callback = overview_progress_refresh_callback
                    if state.selected_tab_index == 0 and callable(callback):
                        callback(update_page=True)
                    elif state.selected_tab_index == 0:
                        refresh_ui()
                    safe_update_live_header_controls(should_update_clock, should_update_banner)
                else:
                    safe_update_live_header_controls(should_update_clock, should_update_banner)

            except Exception as ex:
                try:
                    print(f"Live update loop warning: {ex}")
                except Exception:
                    pass
                continue

    try:
        page.run_task(live_update_loop)
    except Exception:
        # Fallback for older Flet builds.
        def tick_thread():
            nonlocal last_header_second, last_overview_progress_update
            while True:
                time.sleep(1.0 if bool(getattr(state, "low_performance_mode", False)) else HEADER_BANNER_TICK_SECONDS)
                if not state.is_logged_in:
                    continue
                try:
                    current_second = now_local_str()
                    should_update_clock = current_second != last_header_second
                    progress_refresh_seconds = 15 if bool(getattr(state, "low_performance_mode", False)) else OVERVIEW_PROGRESS_REFRESH_SECONDS
                    should_update_progress = (
                        state.overview_takeoff_start_timestamp is not None
                        and state.overview_progress_running
                        and time.time() - last_overview_progress_update >= progress_refresh_seconds
                    )
                    should_update_if_traffic = (
                        state.selected_tab_index == 0 and state.overview_live and infinite_flight_key_path.is_file()
                        and not state.if_polling_paused
                        and time.time() >= max(state.if_last_live_refresh_attempt + IF_TRAFFIC_INTERVAL, state.if_traffic_retry_at)
                    )
                    should_update_banner = refresh_header_banner_tick()
                    if should_update_clock:
                        last_header_second = current_second
                        refresh_header_texts()
                    if should_update_if_traffic:
                        page.run_task(refresh_live_traffic)
                    if should_update_progress and not (state.selected_tab_index == 0 and state.overview_live):
                        # Live progress update fallback without full Overview rebuild.
                        last_overview_progress_update = time.time()
                        callback = overview_progress_refresh_callback
                        if state.selected_tab_index == 0 and callable(callback):
                            callback(update_page=True)
                        elif state.selected_tab_index == 0:
                            refresh_ui()
                        safe_update_live_header_controls(should_update_clock, should_update_banner)
                    elif should_update_clock or should_update_banner:
                        safe_update_live_header_controls(should_update_clock, should_update_banner)
                except Exception as ex:
                    try:
                        print(f"Live update thread warning: {ex}")
                    except Exception:
                        pass
                    continue
        page.run_thread(tick_thread)


def run_app(*, preview=False):
    global _INTERFACE_PREVIEW
    _INTERFACE_PREVIEW = preview
    webview_flags = [flag for flag in ("--globe-webview", "--mapcn-webview") if flag in sys.argv]
    if webview_flags:
        arg_index = sys.argv.index(webview_flags[0])
        raise SystemExit(run_globe_webview_host(sys.argv[arg_index + 1 :]))
    if not _acquire_fms_single_instance():
        raise SystemExit(0)
    runtime_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled_client = runtime_root / "flet_desktop" / "app" / "flet"
    if getattr(sys, "frozen", False) and (bundled_client / "flet.exe").is_file():
        os.environ["FLET_VIEW_PATH"] = str(bundled_client)
    runtime_assets_dir = runtime_root / "assets"
    ft.app(target=main, assets_dir=str(runtime_assets_dir))


if __name__ == "__main__":
    run_app()
