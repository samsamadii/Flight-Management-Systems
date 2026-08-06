
import flet as ft
import sys

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
from datetime import datetime, timedelta
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

try:
    import pystray
    from PIL import Image as PILImage
except ImportError:
    pystray = None
    PILImage = None


_FMS_SINGLE_INSTANCE_MUTEX = None
_FMS_SHOW_WINDOW_EVENT = None


def _acquire_fms_single_instance() -> bool:
    global _FMS_SINGLE_INSTANCE_MUTEX, _FMS_SHOW_WINDOW_EVENT
    if os.name != "nt":
        return True

    kernel32 = ctypes.windll.kernel32
    mutex_name = "Local\\SamSamadi.FlightManagementSystems.V10.Instance"
    event_name = "Local\\SamSamadi.FlightManagementSystems.V10.ShowWindow"
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


def _set_window_child_style(hwnd: int):
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
    style = (style & ~ws_popup & ~ws_caption & ~ws_thickframe) | ws_child | ws_visible
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
    nav_width = 78
    top_bar_height = 66
    if slot == "overview-globe":
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
    args = parser.parse_args(argv)

    try:
        import webview
    except Exception as exc:
        print(f"Globe.gl WebView host failed to import pywebview: {exc}")
        return 2

    def attach_to_parent(window):
        if not args.attach:
            return
        user32 = ctypes.windll.user32
        parent_hwnd = 0
        for _ in range(80):
            matches = _enum_windows_by_title(args.parent_title)
            if matches:
                parent_hwnd = matches[0]
                break
            time.sleep(0.1)
        if not parent_hwnd:
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
            return

        _set_window_child_style(child_hwnd)
        user32.SetParent(child_hwnd, parent_hwnd)
        _move_child_webview_to_content(parent_hwnd, child_hwnd, args.slot)

        def keep_attached():
            while user32.IsWindow(parent_hwnd) and user32.IsWindow(child_hwnd):
                _move_child_webview_to_content(parent_hwnd, child_hwnd, args.slot)
                time.sleep(0.18)

        threading.Thread(target=keep_attached, daemon=True).start()

    window_kwargs = dict(
        title="FMS Globe.gl Route Globe",
        url=args.url,
        width=420 if args.slot == "overview-globe" else 1100,
        height=440 if args.slot == "overview-globe" else 720,
        min_size=(320, 300) if args.slot == "overview-globe" else (640, 420),
        frameless=bool(args.attach),
        easy_drag=False,
        background_color="#00000000" if args.slot == "overview-globe" else "#020617",
        text_select=False,
        zoomable=True,
    )
    try:
        window = webview.create_window(**window_kwargs)
    except Exception:
        window_kwargs["background_color"] = "#020617"
        window = webview.create_window(**window_kwargs)
    webview.start(attach_to_parent, args=(window,), gui="edgechromium", debug=False, private_mode=False)
    return 0


AIRLINES = ['Air France',
 'American Airlines',
 'ANA',
 'British Airways',
 'Cathay Pacific',
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

AIRLINE_FLEETS = {
    # Matched to the aircraft/livery screenshot provided by the user.
    "Air France": [
        "Airbus A220-300",
        "Airbus A320-200",
        "Airbus A350-900",
        "Airbus A380-800",
        "Boeing 777-300ER",
        "Boeing 787-9",
        "Boeing 787-10",
    ],
    "ITA Airways": [
        "Airbus A220-300",
        "Airbus A320-200",
        "Airbus A321-200",
    ],
    "American Airlines": [
        "Airbus A321-200",
        "Boeing 737-8 MAX",
    ],
    "ANA": [
        "Boeing 777-300ER",
        "Boeing 787-10",
    ],
    "British Airways": [
        "Airbus A320-200",
        "Airbus A321-200",
        "Airbus A350-1000",
        "Airbus A380-800",
        "Boeing 777-300ER",
        "Boeing 787-9",
        "Boeing 787-10",
    ],
    "Cathay Pacific": [
        "Airbus A330-300",
        "Airbus A350-900",
        "Boeing 777-300ER",
    ],
    "Emirates": [
        "Airbus A350-900",
        "Airbus A380-800",
        "Boeing 777-300ER",
    ],
    "Etihad Airways": [
        "Airbus A320-200",
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
        "Airbus A330-300",
        "Airbus A340-600",
        "Airbus A350-900",
        "Airbus A350-1000",
        "Airbus A380-800",
        "Boeing 737-8 MAX",
        "Boeing 747-200",
        "Boeing 747-8",
        "Boeing 757-200",
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
        "Airbus A330-300",
        "Airbus A340-600",
        "Airbus A350-900",
        "Airbus A380-800",
        "Boeing 747-8",
        "Boeing 787-9",
    ],
    "Mahan Air": [
        "Airbus A340-600",
    ],
    "Qantas": [
        "Airbus A330-300",
        "Airbus A350-1000",
        "Airbus A380-800",
        "Boeing 787-9",
    ],
    "Qatar Airways": [
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
        "Airbus A330-300",
        "Airbus A350-900",
        "Boeing 777-300ER",
        "Boeing 787-9",
    ],
    "United Airlines": [
        "Airbus A350-900",
        "Boeing 737-8 MAX",
        "Boeing 777-300ER",
        "Boeing 787-9",
        "Boeing 787-10",
    ],
    "Virgin Atlantic": [
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
             'vr_speeds': {'1': 145, '2': 140, '3': 135},
             'v2_speeds': {'1': 155, '2': 150, '3': 145},
             'vref_speeds': {'FULL': 135, '3': 140},
             'flap_options': ['1', '2', '3'],
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
             'notes': 'Added as A321neo planning profile. Weight limits use Airbus published A321neo values; '
                      'speeds/distances are planning approximations based on A321 family defaults.'},
 'A330-300': {'name': 'Airbus A330-300',
              'mtow': 242000,
              'oew': 120000,
              'mlw': 187000,
              'vr_speeds': {'1+F': 150, '2': 145, '3': 140},
              'v2_speeds': {'1+F': 160, '2': 155, '3': 150},
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
              'derived_payload_plus_remaining_fuel_at_mlw_kg': 67000},
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

AIRCRAFT_NAME_ALIASES = {'airbus a220-300': 'A220-300',
 'airbus a320-200': 'A320-200',
 'airbus a320': 'A320-200',
 'airbus a320neo': 'A320-200',
 'airbus a321-200': 'A321-200',
 'airbus a321': 'A321-200',
 'airbus a321neo': 'A321neo',
 'airbus a330-200': 'A330-300',
 'airbus a330-300': 'A330-300',
 'airbus a340-300': 'A340-600',
 'airbus a350-900': 'A350-900',
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
 'boeing 777-200er': 'B777-300ER',
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
        "A330-300": 40,
        "A340-600": 50,
        "A350-900": 60,
        "A350-1000": 61,
        "A380-800": 70,
        "B737-8MAX": 110,
        "B747-8": 120,
        "B747-200": 121,
        "B757-200": 130,
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


@dataclass
class WeatherState:
    temperature_c: Optional[float] = None
    condition: str = "—"
    icon: str = "📍"


@dataclass
class AppState:
    is_logged_in: bool = False
    pilot_name: str = "Pilot"
    profile_member_since: str = ""
    location_label: str = "Unknown"
    weather: WeatherState = field(default_factory=WeatherState)
    airline: str = ""
    selected_tab_index: int = 1
    display_mode: str = "dark"
    display_brightness: float = 1.0
    display_contrast: float = 1.0
    airline_overlay_opacity: float = 0.50
    custom_airlines: List[str] = field(default_factory=list)
    default_fuel_unit: str = "kg"
    default_distance_unit: str = "NM"
    default_temperature_unit: str = "°C"
    banner_animation_enabled: bool = False
    low_performance_mode: bool = False
    professional_info_enabled: bool = False
    app_volume: float = 0.85
    app_muted: bool = False
    login_intro_started: bool = False
    login_transition_active: bool = False
    login_transition_progress: float = 0.0
    aircraft: str = ""
    flight_number: str = ""
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
    overview_flight_time_minutes: int = 120
    overview_takeoff_start_timestamp: Optional[float] = None
    overview_locked_eta_timestamp: Optional[float] = None
    overview_progress_running: bool = False
    overview_calendar_completion_key: str = ""
    flight_hibernation_menu_open: bool = False
    flight_hibernation_prompt_seen: bool = False
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
    log_editing_detail_id: Optional[str] = None
    log_editing_detail_field: Optional[str] = None
    profile_image_path: str = ""
    if_connection_status: str = "Not connected"
    if_selected_session_id: str = ""
    if_selected_session_name: str = ""
    if_sessions: List[dict] = field(default_factory=list)
    if_selected_flight: Dict[str, object] = field(default_factory=dict)
    if_selected_flight_plan: Dict[str, object] = field(default_factory=dict)
    if_live_flights: List[dict] = field(default_factory=list)
    if_selected_route_points: List[tuple] = field(default_factory=list)
    if_selected_route_label: str = ""
    if_selected_route_start_label: str = ""
    if_selected_route_end_label: str = ""
    if_last_traffic_refresh: str = "Never"
    if_live_refresh_enabled: bool = False
    if_last_live_refresh_attempt: float = 0.0
    if_active_atc: List[dict] = field(default_factory=list)
    if_user_stats: Dict[str, object] = field(default_factory=dict)
    if_recent_activity: List[dict] = field(default_factory=list)
    if_cache: Dict[str, dict] = field(default_factory=dict)
    if_last_request_status: str = "No request yet"
    if_last_response_ms: str = "—"
    if_last_error: str = ""
    if_cache_status: str = "Empty"
    if_last_activity_timestamp: float = 0.0
    if_polling_paused: bool = False
    page_backgrounds: Dict[str, Optional[str]] = field(default_factory=lambda: {
        "LOGIN": "login_bg.jpg",
        "OVERVIEW": "backgrounds/map_bg.jpg",
        "HOME": "backgrounds/home_bg.jpg",
        "TAKEOFF": "backgrounds/takeoff_bg.jpg",
        "LANDING": "backgrounds/landing_bg.jpg",
        "MAP": "backgrounds/map_bg.jpg",
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


AIRPORT_LIBRARY = {'CYYC': {'elevation_ft': 3606,
          'iata': 'YYC',
          'lat': 51.1215,
          'lon': -114.0076,
          'name': 'Calgary International Airport'},
 'CYUL': {'elevation_ft': 118,
          'iata': 'YUL',
          'lat': 45.4706,
          'lon': -73.7408,
          'name': 'Montreal-Trudeau International Airport'},
 'CYVR': {'elevation_ft': 14,
          'iata': 'YVR',
          'lat': 49.1967,
          'lon': -123.1815,
          'name': 'Vancouver International Airport'},
 'CYYZ': {'elevation_ft': 569,
          'iata': 'YYZ',
          'lat': 43.6777,
          'lon': -79.6248,
          'name': 'Toronto Pearson International Airport'},
 'EDDB': {'elevation_ft': 157, 'iata': 'BER', 'lat': 52.3667, 'lon': 13.5033, 'name': 'Berlin Brandenburg Airport'},
 'EDDF': {'elevation_ft': 364, 'iata': 'FRA', 'lat': 50.0379, 'lon': 8.5622, 'name': 'Frankfurt Airport'},
 'EDDH': {'elevation_ft': 53, 'iata': 'HAM', 'lat': 53.6304, 'lon': 9.9882, 'name': 'Hamburg Airport'},
 'EDDK': {'elevation_ft': 302, 'iata': 'CGN', 'lat': 50.8659, 'lon': 7.1427, 'name': 'Cologne Bonn Airport'},
 'EDDM': {'elevation_ft': 1487, 'iata': 'MUC', 'lat': 48.3538, 'lon': 11.7861, 'name': 'Munich Airport'},
 'EFHK': {'elevation_ft': 179, 'iata': 'HEL', 'lat': 60.3172, 'lon': 24.9633, 'name': 'Helsinki Airport'},
 'EGKK': {'elevation_ft': 202, 'iata': 'LGW', 'lat': 51.1537, 'lon': -0.1821, 'name': 'London Gatwick Airport'},
 'EGLL': {'elevation_ft': 83, 'iata': 'LHR', 'lat': 51.47, 'lon': -0.4543, 'name': 'London Heathrow Airport'},
 'EHAM': {'elevation_ft': -11, 'iata': 'AMS', 'lat': 52.3105, 'lon': 4.7683, 'name': 'Amsterdam Schiphol Airport'},
 'EIDW': {'elevation_ft': 242, 'iata': 'DUB', 'lat': 53.4213, 'lon': -6.2701, 'name': 'Dublin Airport'},
 'EKCH': {'elevation_ft': 17, 'iata': 'CPH', 'lat': 55.6181, 'lon': 12.656, 'name': 'Copenhagen Airport'},
 'ENGM': {'elevation_ft': 681, 'iata': 'OSL', 'lat': 60.1939, 'lon': 11.1004, 'name': 'Oslo Airport'},
 'EPKK': {'elevation_ft': 791, 'iata': 'KRK', 'lat': 50.0777, 'lon': 19.7848, 'name': 'Krakow John Paul II Airport'},
 'EPWA': {'elevation_ft': 362, 'iata': 'WAW', 'lat': 52.1657, 'lon': 20.9671, 'name': 'Warsaw Chopin Airport'},
 'ESSA': {'elevation_ft': 134, 'iata': 'ARN', 'lat': 59.6519, 'lon': 17.9186, 'name': 'Stockholm Arlanda Airport'},
 'FIMP': {'elevation_ft': 186,
          'iata': 'MRU',
          'lat': -20.4302,
          'lon': 57.6836,
          'name': 'Sir Seewoosagur Ramgoolam International Airport'},
 'HECA': {'elevation_ft': 382, 'iata': 'CAI', 'lat': 30.1219, 'lon': 31.4056, 'name': 'Cairo International Airport'},
 'KATL': {'elevation_ft': 1026,
          'iata': 'ATL',
          'lat': 33.6407,
          'lon': -84.4277,
          'name': 'Hartsfield-Jackson Atlanta International Airport'},
 'KBOS': {'elevation_ft': 20,
          'iata': 'BOS',
          'lat': 42.3656,
          'lon': -71.0096,
          'name': 'Boston Logan International Airport'},
 'KDCA': {'elevation_ft': 15,
          'iata': 'DCA',
          'lat': 38.8512,
          'lon': -77.0402,
          'name': 'Ronald Reagan Washington National Airport'},
 'KDEN': {'elevation_ft': 5431,
          'iata': 'DEN',
          'lat': 39.8561,
          'lon': -104.6737,
          'name': 'Denver International Airport'},
 'KDFW': {'elevation_ft': 607,
          'iata': 'DFW',
          'lat': 32.8998,
          'lon': -97.0403,
          'name': 'Dallas Fort Worth International Airport'},
 'KEWR': {'elevation_ft': 18,
          'iata': 'EWR',
          'lat': 40.6895,
          'lon': -74.1745,
          'name': 'Newark Liberty International Airport'},
 'KIAD': {'elevation_ft': 312,
          'iata': 'IAD',
          'lat': 38.9531,
          'lon': -77.4565,
          'name': 'Washington Dulles International Airport'},
 'KIAH': {'elevation_ft': 97,
          'iata': 'IAH',
          'lat': 29.9902,
          'lon': -95.3368,
          'name': 'George Bush Intercontinental Airport'},
 'KJFK': {'elevation_ft': 13,
          'iata': 'JFK',
          'lat': 40.6413,
          'lon': -73.7781,
          'name': 'John F. Kennedy International Airport'},
 'KLAS': {'elevation_ft': 2181,
          'iata': 'LAS',
          'lat': 36.084,
          'lon': -115.1537,
          'name': 'Harry Reid International Airport'},
 'KLAX': {'elevation_ft': 128,
          'iata': 'LAX',
          'lat': 33.9416,
          'lon': -118.4085,
          'name': 'Los Angeles International Airport'},
 'KLGA': {'elevation_ft': 21, 'iata': 'LGA', 'lat': 40.7769, 'lon': -73.874, 'name': 'LaGuardia Airport'},
 'KMCO': {'elevation_ft': 96, 'iata': 'MCO', 'lat': 28.4312, 'lon': -81.3081, 'name': 'Orlando International Airport'},
 'KMDW': {'elevation_ft': 620,
          'iata': 'MDW',
          'lat': 41.7868,
          'lon': -87.7522,
          'name': 'Chicago Midway International Airport'},
 'KMIA': {'elevation_ft': 8, 'iata': 'MIA', 'lat': 25.7959, 'lon': -80.287, 'name': 'Miami International Airport'},
 'KORD': {'elevation_ft': 672,
          'iata': 'ORD',
          'lat': 41.9742,
          'lon': -87.9073,
          'name': "Chicago O'Hare International Airport"},
 'KPHL': {'elevation_ft': 36,
          'iata': 'PHL',
          'lat': 39.8744,
          'lon': -75.2424,
          'name': 'Philadelphia International Airport'},
 'KPHX': {'elevation_ft': 1135,
          'iata': 'PHX',
          'lat': 33.4342,
          'lon': -112.0116,
          'name': 'Phoenix Sky Harbor International Airport'},
 'KSEA': {'elevation_ft': 433,
          'iata': 'SEA',
          'lat': 47.4502,
          'lon': -122.3088,
          'name': 'Seattle-Tacoma International Airport'},
 'KSFO': {'elevation_ft': 13,
          'iata': 'SFO',
          'lat': 37.6213,
          'lon': -122.379,
          'name': 'San Francisco International Airport'},
 'LEBL': {'elevation_ft': 12, 'iata': 'BCN', 'lat': 41.2974, 'lon': 2.0833, 'name': 'Barcelona El Prat Airport'},
 'LEMD': {'elevation_ft': 2000,
          'iata': 'MAD',
          'lat': 40.4722,
          'lon': -3.5608,
          'name': 'Adolfo Suarez Madrid-Barajas Airport'},
 'LFPG': {'elevation_ft': 392, 'iata': 'CDG', 'lat': 49.0097, 'lon': 2.5479, 'name': 'Paris Charles de Gaulle Airport'},
 'LGAV': {'elevation_ft': 308, 'iata': 'ATH', 'lat': 37.9364, 'lon': 23.9445, 'name': 'Athens International Airport'},
 'LGSR': {'elevation_ft': 127,
          'iata': 'JTR',
          'lat': 36.3992,
          'lon': 25.4793,
          'name': 'Santorini International Airport'},
 'LIRF': {'elevation_ft': 13, 'iata': 'FCO', 'lat': 41.8003, 'lon': 12.2389, 'name': 'Rome Fiumicino Airport'},
 'LLBG': {'elevation_ft': 135, 'iata': 'TLV', 'lat': 32.0114, 'lon': 34.8867, 'name': 'Ben Gurion Airport'},
 'LOWW': {'elevation_ft': 600, 'iata': 'VIE', 'lat': 48.1103, 'lon': 16.5697, 'name': 'Vienna International Airport'},
 'LPPT': {'elevation_ft': 374, 'iata': 'LIS', 'lat': 38.7742, 'lon': -9.1342, 'name': 'Lisbon Airport'},
 'LSZH': {'elevation_ft': 1416, 'iata': 'ZRH', 'lat': 47.4582, 'lon': 8.5555, 'name': 'Zurich Airport'},
 'LTBA': {'elevation_ft': 163, 'iata': 'ISL', 'lat': 40.9769, 'lon': 28.8146, 'name': 'Istanbul Ataturk Airport'},
 'LTFM': {'elevation_ft': 325, 'iata': 'IST', 'lat': 41.2753, 'lon': 28.7519, 'name': 'Istanbul Airport'},
 'MMMX': {'elevation_ft': 7316,
          'iata': 'MEX',
          'lat': 19.4361,
          'lon': -99.0719,
          'name': 'Mexico City International Airport'},
 'MMUN': {'elevation_ft': 22, 'iata': 'CUN', 'lat': 21.0365, 'lon': -86.8771, 'name': 'Cancun International Airport'},
 'OBBI': {'elevation_ft': 6, 'iata': 'BAH', 'lat': 26.2708, 'lon': 50.6336, 'name': 'Bahrain International Airport'},
 'OEJN': {'elevation_ft': 48,
          'iata': 'JED',
          'lat': 21.6702,
          'lon': 39.1525,
          'name': 'King Abdulaziz International Airport'},
 'OEKK': {'elevation_ft': 76, 'iata': 'EAM', 'lat': 28.3352, 'lon': 35.4608, 'name': 'Neom Bay Airport'},
 'OERK': {'elevation_ft': 2049,
          'iata': 'RUH',
          'lat': 24.9576,
          'lon': 46.6988,
          'name': 'King Khalid International Airport'},
 'OIIE': {'elevation_ft': 3305,
          'iata': 'IKA',
          'lat': 35.4161,
          'lon': 51.1522,
          'name': 'Tehran Imam Khomeini International Airport'},
 'OIII': {'elevation_ft': 3962, 'iata': 'THR', 'lat': 35.6892, 'lon': 51.3134, 'name': 'Tehran Mehrabad Airport'},
 'OJAI': {'elevation_ft': 2395,
          'iata': 'AMM',
          'lat': 31.7226,
          'lon': 35.9932,
          'name': 'Queen Alia International Airport'},
 'OKBK': {'elevation_ft': 206, 'iata': 'KWI', 'lat': 29.2266, 'lon': 47.9689, 'name': 'Kuwait International Airport'},
 'OMAA': {'elevation_ft': 88, 'iata': 'AUH', 'lat': 24.433, 'lon': 54.6511, 'name': 'Zayed International Airport'},
 'OMDB': {'elevation_ft': 62, 'iata': 'DXB', 'lat': 25.2532, 'lon': 55.3657, 'name': 'Dubai International Airport'},
 'OMSJ': {'elevation_ft': 111, 'iata': 'SHJ', 'lat': 25.3286, 'lon': 55.5172, 'name': 'Sharjah International Airport'},
 'OOMS': {'elevation_ft': 48, 'iata': 'MCT', 'lat': 23.5933, 'lon': 58.2844, 'name': 'Muscat International Airport'},
 'OTHH': {'elevation_ft': 13, 'iata': 'DOH', 'lat': 25.2731, 'lon': 51.6081, 'name': 'Hamad International Airport'},
 'RCSS': {'elevation_ft': 18, 'iata': 'TSA', 'lat': 25.0697, 'lon': 121.5525, 'name': 'Taipei Songshan Airport'},
 'RCTP': {'elevation_ft': 108,
          'iata': 'TPE',
          'lat': 25.0797,
          'lon': 121.2342,
          'name': 'Taiwan Taoyuan International Airport'},
 'RJAA': {'elevation_ft': 141, 'iata': 'NRT', 'lat': 35.7719, 'lon': 140.3929, 'name': 'Narita International Airport'},
 'RJBB': {'elevation_ft': 26, 'iata': 'KIX', 'lat': 34.4347, 'lon': 135.244, 'name': 'Kansai International Airport'},
 'RJTT': {'elevation_ft': 21, 'iata': 'HND', 'lat': 35.5494, 'lon': 139.7798, 'name': 'Tokyo Haneda Airport'},
 'RKSI': {'elevation_ft': 23, 'iata': 'ICN', 'lat': 37.4602, 'lon': 126.4407, 'name': 'Incheon International Airport'},
 'RPLL': {'elevation_ft': 75,
          'iata': 'MNL',
          'lat': 14.5086,
          'lon': 121.0198,
          'name': 'Ninoy Aquino International Airport'},
 'SAEZ': {'elevation_ft': 67, 'iata': 'EZE', 'lat': -34.8222, 'lon': -58.5358, 'name': 'Ezeiza International Airport'},
 'SBGR': {'elevation_ft': 2459,
          'iata': 'GRU',
          'lat': -23.4356,
          'lon': -46.4731,
          'name': 'Sao Paulo Guarulhos International Airport'},
 'SCEL': {'elevation_ft': 1555,
          'iata': 'SCL',
          'lat': -33.3929,
          'lon': -70.7858,
          'name': 'Santiago International Airport'},
 'SKBO': {'elevation_ft': 8361,
          'iata': 'BOG',
          'lat': 4.7016,
          'lon': -74.1469,
          'name': 'El Dorado International Airport'},
 'SPJC': {'elevation_ft': 113,
          'iata': 'LIM',
          'lat': -12.0219,
          'lon': -77.1143,
          'name': 'Jorge Chavez International Airport'},
 'UUEE': {'elevation_ft': 622,
          'iata': 'SVO',
          'lat': 55.9726,
          'lon': 37.4146,
          'name': 'Sheremetyevo International Airport'},
 'VABB': {'elevation_ft': 39,
          'iata': 'BOM',
          'lat': 19.0896,
          'lon': 72.8656,
          'name': 'Mumbai Chhatrapati Shivaji Maharaj Airport'},
 'VHHH': {'elevation_ft': 28, 'iata': 'HKG', 'lat': 22.308, 'lon': 113.9185, 'name': 'Hong Kong International Airport'},
 'VIDP': {'elevation_ft': 777,
          'iata': 'DEL',
          'lat': 28.5562,
          'lon': 77.1,
          'name': 'Indira Gandhi International Airport'},
 'VOBL': {'elevation_ft': 3000,
          'iata': 'BLR',
          'lat': 13.1986,
          'lon': 77.7066,
          'name': 'Kempegowda International Airport'},
 'VOMM': {'elevation_ft': 52, 'iata': 'MAA', 'lat': 12.9941, 'lon': 80.1709, 'name': 'Chennai International Airport'},
 'VTBS': {'elevation_ft': 5, 'iata': 'BKK', 'lat': 13.69, 'lon': 100.7501, 'name': 'Suvarnabhumi Airport'},
 'WIII': {'elevation_ft': 34,
          'iata': 'CGK',
          'lat': -6.1256,
          'lon': 106.6559,
          'name': 'Soekarno-Hatta International Airport'},
 'WMKK': {'elevation_ft': 69,
          'iata': 'KUL',
          'lat': 2.7456,
          'lon': 101.7072,
          'name': 'Kuala Lumpur International Airport'},
 'WSSS': {'elevation_ft': 22, 'iata': 'SIN', 'lat': 1.3644, 'lon': 103.9915, 'name': 'Singapore Changi Airport'},
 'YSSY': {'elevation_ft': 21,
          'iata': 'SYD',
          'lat': -33.9399,
          'lon': 151.1753,
          'name': 'Sydney Kingsford Smith Airport'},
 'ZBAA': {'elevation_ft': 116,
          'iata': 'PEK',
          'lat': 40.0801,
          'lon': 116.5846,
          'name': 'Beijing Capital International Airport'},
 'ZBAD': {'elevation_ft': 98,
          'iata': 'PKX',
          'lat': 39.5099,
          'lon': 116.4105,
          'name': 'Beijing Daxing International Airport'},
 'ZGGG': {'elevation_ft': 49,
          'iata': 'CAN',
          'lat': 23.3924,
          'lon': 113.2988,
          'name': 'Guangzhou Baiyun International Airport'},
 'ZSPD': {'elevation_ft': 13,
          'iata': 'PVG',
          'lat': 31.1443,
          'lon': 121.8083,
          'name': 'Shanghai Pudong International Airport'},
 'ZSSS': {'elevation_ft': 10,
          'iata': 'SHA',
          'lat': 31.1979,
          'lon': 121.3363,
          'name': 'Shanghai Hongqiao International Airport'}}


AIRPORT_CODE_ALIASES = {icao: icao for icao in AIRPORT_LIBRARY}
for icao, airport in AIRPORT_LIBRARY.items():
    iata = str(airport.get("iata", "")).strip().upper()
    if iata:
        AIRPORT_CODE_ALIASES[iata] = icao

# Compatibility aliases for common user inputs and legacy shorthand.
AIRPORT_CODE_ALIASES.update({
    "IKH": "OIIE",
})

AIRPORT_ELEVATIONS_FT = {icao: int(data["elevation_ft"]) for icao, data in AIRPORT_LIBRARY.items()}
AIRPORT_COORDINATES = {icao: (float(data["lat"]), float(data["lon"])) for icao, data in AIRPORT_LIBRARY.items()}
AIRPORT_COORDS = {icao: (float(data["lat"]), float(data["lon"])) for icao, data in AIRPORT_LIBRARY.items()}


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
        clmax_by_flap={"1+F": 1.85, "2": 2.05, "3": 2.25},
        cd0=0.022,
        oswald_e=0.82,
        aspect_ratio=10.1,
        total_static_thrust_n=640000,
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
    if "a321" in name:
        base = TAKEOFF_CONFIGS["A321_FAMILY"]
    elif "a320" in name or "a319" in name:
        base = TAKEOFF_CONFIGS["A320_FAMILY"]
    elif "a220" in name:
        base = TAKEOFF_CONFIGS["A220"]
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
            temperature_c=float(m.get("temp", 15) or 15),
            qnh_hpa=round(float(qnh), 1),
            wind_dir_deg=int(wind_dir),
            wind_speed_kt=int(m.get("wspd", 0) or 0),
            wind_gust_kt=int(gust),
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

    if lib_vr is not None and speed_reference_ratio > 0:
        vr_kt = scale_takeoff_reference_speed_kt(
            float(lib_vr), mass_kg, ac.mtow_kg, speed_reference_ratio
        )
        vr_kt = max(vr_kt, vs_kt * 1.05, vs_kt + 5.0)
    elif lib_vr is not None:
        vr_kt = float(lib_vr)
    else:
        vr_kt = max(vs_kt * vr_factor, vs_kt * 1.05)

    v2_factor = 1.20 if ac.engine_count == 2 else 1.15
    if lib_v2 is not None and speed_reference_ratio > 0:
        v2_kt = scale_takeoff_reference_speed_kt(
            float(lib_v2), mass_kg, ac.mtow_kg, speed_reference_ratio
        )
        v2_kt = max(v2_kt, vs_kt * 1.13, vr_kt + 8.0)
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
    "A330-300": RouteFuelAircraft("A330-300", 6350.0, 139090.0, 40000.0),
    "A340-600": RouteFuelAircraft("A340-600", 7900.0, 195880.0, 54000.0),
    "A350-900": RouteFuelAircraft("A350-900", 8500.0, 166488.0, 45000.0),
    "A350-1000": RouteFuelAircraft("A350-1000", 8700.0, 164000.0, 52000.0),
    "A380-800": RouteFuelAircraft("A380-800", 8000.0, 320000.0, 65000.0),
    "B737-8MAX": RouteFuelAircraft("B737-8MAX", 3550.0, 26020.0, 18000.0),
    "B747-8": RouteFuelAircraft("B747-8", 7730.0, 238610.0, 76000.0),
    "B747-200": RouteFuelAircraft("B747-200", 6100.0, 157560.0, 68000.0),
    "B757-200": RouteFuelAircraft("B757-200", 3915.0, 43490.0, 29000.0),
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
    "A330-300": 6350.0,
    "A340-600": 7900.0,
    "A350-900": 8500.0,
    "A350-1000": 8700.0,
    "A380-800": 8000.0,
    "B737-8MAX": 3550.0,
    "B747-8": 7730.0,
    "B747-200": 6100.0,
    "B757-200": 3915.0,
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

    gs_default = resolve_takeoff_fuel_config(aircraft_name).cruise_gs_kt_default
    ete_hours = effective_distance_nmi / max(float(gs_default or 450.0), 1.0)

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
    if "a321" in name:
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


def main(page: ft.Page):
    state = AppState()
    base_dir = Path(__file__).resolve().parent
    if bool(getattr(sys, "frozen", False)):
        local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        storage_dir = local_app_data / "Flight Management Systems"
        try:
            storage_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            storage_dir = base_dir
    else:
        storage_dir = base_dir

    storage_file_names = (
        "calendar_flights.json",
        "profile_data.json",
        "app_settings.json",
        "infinite_flight_config.json",
        "flight_hibernation.json",
    )
    if storage_dir != base_dir:
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
    infinite_flight_config_path = storage_dir / "infinite_flight_config.json"
    flight_hibernation_storage_path = storage_dir / "flight_hibernation.json"
    runtime_icon = base_dir / "assets" / "app_icon.ico"
    tray_icon = None
    app_exit_requested = False
    hidden_to_tray_notice_shown = False
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SamSamadi.FlightManagementSystems.V10")
        except Exception:
            pass
    if runtime_icon.exists():
        try:
            page.window.icon = str(runtime_icon)
        except Exception:
            pass

    page.title = "Flight Management Systems"
    page.window_width = 1180
    page.window_height = 820
    page.window_min_width = 1000
    page.window_min_height = 760
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0
    page.spacing = 0

    AIRLINE_ACCENT = {'ANA': '#1F4E8C',
     'Air France': '#002157',
     'American Airlines': '#6B7280',
     'British Airways': '#2E5C99',
     'Cathay Pacific': '#006564',
     'Emirates': '#C8102E',
     'Etihad Airways': '#B99A55',
     'Generic': '#64748B',
     'ITA Airways': '#005DAA',
     'Iran Air': '#1F2C51',
     'Lufthansa': '#F9BA00',
     'Mahan Air': '#007A6E',
     'Qantas': '#E4002B',
     'Qatar Airways': '#660033',
     'Singapore Airlines': '#F0B323',
     'Southwest Airlines': '#304CB2',
     'Turkish Airlines': '#C70A0C',
     'United Airlines': '#005DAA',
     'Virgin Atlantic': '#DA0530'}

    AIRLINE_BACKGROUND = {'ANA': '#081A32',
     'Air France': '#07132A',
     'American Airlines': '#171B22',
     'British Airways': '#081426',
     'Cathay Pacific': '#062624',
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

    CARD_FILL = "#141519"
    SHELL_WARM_BG = "#1B1714"
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
    }

    # Performance cache: avoid repeated filesystem scans for image assets during
    # page refreshes, tab changes, banner ticks, and airline/logo updates.
    asset_rel_cache: Dict[str, Optional[str]] = {}
    airline_logo_cache: Dict[str, Optional[str]] = {}
    manufacturer_logo_cache: Dict[str, Optional[str]] = {}
    aircraft_livery_cache: Dict[tuple[str, str], Optional[str]] = {}
    airport_weather_cache: Dict[str, dict] = {}
    airport_environment_cache: Dict[str, dict] = {}

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
        clean_name = re.sub(r"\s+", " ", (airline_name or "").strip())
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
        AIRLINE_FLEETS.setdefault(clean_name, list(AIRLINE_FLEETS.get("Generic", [])))
        if clean_name not in state.custom_airlines and clean_name not in {
            'Air France', 'American Airlines', 'ANA', 'British Airways', 'Cathay Pacific',
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
        # Keep Flet controls in dark theme so custom app surfaces own the
        # day/night palette instead of inheriting mixed platform defaults.
        page.theme_mode = ft.ThemeMode.DARK
        tokens["accent"] = AIRLINE_ACCENT.get(state.airline, "#0A84FF")
        daylight_cards = daylight_mode and int(getattr(state, "selected_tab_index", 0) or 0) != 0

        if daylight_mode:
            # Daytime shell mode shifts the chrome and non-overview cards toward
            # a softer candy-blue daylight palette.
            tokens["bg"] = "#DCEEFF"
            tokens["text"] = DAYLIGHT_TEXT if daylight_cards else PANEL_TEXT
            tokens["muted"] = DAYLIGHT_MUTED if daylight_cards else PANEL_MUTED
            tokens["topbar"] = "#101113"
            tokens["panel"] = DAYLIGHT_CARD_FILL if daylight_cards else CARD_FILL
            tokens["subpanel"] = DAYLIGHT_SUBPANEL_FILL if daylight_cards else CARD_FILL
            tokens["card_border"] = ft.Colors.with_opacity(0.54 * contrast, DAYLIGHT_BORDER) if daylight_cards else ft.Colors.with_opacity(0.14 * contrast, ft.Colors.WHITE)
            tokens["input_bg"] = ft.Colors.with_opacity(0.86, DAYLIGHT_INPUT_FILL) if daylight_cards else "#202126"
            tokens["success_overlay"] = ft.Colors.with_opacity(0.18, ft.Colors.GREEN)
            tokens["shell_topbar"] = "#092235"
            tokens["shell_topbar_opacity"] = 0.50
            tokens["shell_rail"] = "#061A28"
            tokens["shell_rail_opacity"] = 0.46
            tokens["shell_text"] = "#F8FCFF"
            tokens["shell_muted"] = "#D7E9F6"
            tokens["shell_border"] = ft.Colors.with_opacity(0.18 * contrast, "#B9E7FF")
            tokens["shell_nav_idle"] = "#DDF5FF"
            tokens["shell_nav_idle_opacity"] = 0.08
            tokens["shell_nav_idle_border_opacity"] = 0.14
            tokens["shell_nav_selected_opacity"] = 0.34
            tokens["shell_nav_selected_border_opacity"] = 0.54
            return

        # Global command-center palette. All cards use #141519 and all normal
        # text stays white for readability. Airline selection still controls
        # accents and, when selected, the app-shell background tint.
        tokens["bg"] = AIRLINE_BACKGROUND.get(state.airline, SHELL_WARM_BG) if state.airline else SHELL_WARM_BG
        tokens["text"] = PANEL_TEXT
        tokens["muted"] = PANEL_MUTED
        tokens["topbar"] = "#101113"
        tokens["panel"] = CARD_FILL
        tokens["subpanel"] = CARD_FILL
        tokens["card_border"] = ft.Colors.with_opacity(0.14 * contrast, ft.Colors.WHITE)
        tokens["input_bg"] = "#202126"
        tokens["success_overlay"] = ft.Colors.with_opacity(0.18, ft.Colors.GREEN)
        tokens["shell_topbar"] = "#101113"
        tokens["shell_topbar_opacity"] = 0.58
        tokens["shell_rail"] = ft.Colors.BLACK
        tokens["shell_rail_opacity"] = 0.32
        tokens["shell_text"] = PANEL_TEXT
        tokens["shell_muted"] = PANEL_MUTED
        tokens["shell_border"] = tokens["card_border"]
        tokens["shell_nav_idle"] = ft.Colors.BLACK
        tokens["shell_nav_idle_opacity"] = 0.12
        tokens["shell_nav_idle_border_opacity"] = 0.10
        tokens["shell_nav_selected_opacity"] = 0.38
        tokens["shell_nav_selected_border_opacity"] = 0.46

    def current_airline_label() -> str:
        return state.airline or "Pick an airline"

    def current_aircraft_label() -> str:
        return state.aircraft or "Select an aircraft"

    def current_route_label() -> str:
        if state.departure or state.arrival:
            return f"{state.departure or '—'} → {state.arrival or '—'}"
        return "—"

    def header_banner_route_label() -> str:
        origin = (state.departure or "ORIGIN").strip().upper()
        destination = (state.arrival or "DESTINATION").strip().upper()
        return f"{origin} → {destination}"

    def header_banner_aircraft_label() -> str:
        return (state.aircraft or "AIRCRAFT").strip()

    def header_banner_flight_number_label() -> str:
        return (state.flight_number or "FLIGHT —").strip().upper()

    def header_banner_remaining_time_label() -> str:
        try:
            duration_minutes = max(1, int(float(state.overview_flight_time_minutes or 120)))
        except Exception:
            duration_minutes = 120

        remaining_minutes = duration_minutes
        if int(state.overview_flight_status_index or 0) >= 5:
            remaining_minutes = 0
        elif state.overview_progress_running and isinstance(state.overview_takeoff_start_timestamp, (int, float)):
            elapsed_minutes = int(max(0.0, time.time() - float(state.overview_takeoff_start_timestamp)) / 60.0)
            remaining_minutes = max(0, duration_minutes - elapsed_minutes)

        return format_hours_to_hm(remaining_minutes / 60.0)

    def header_banner_messages() -> tuple[str, str]:
        route = header_banner_route_label()
        aircraft = header_banner_aircraft_label()
        flight_number = header_banner_flight_number_label()
        remaining = header_banner_remaining_time_label()
        long_message = f"{route}    •    AIRCRAFT {aircraft}    •    FLIGHT {flight_number}    •    REMAINING {remaining}"
        short_message = f"{route}    •    {aircraft}"
        return long_message, short_message

    def header_progress_duration_minutes() -> int:
        try:
            return max(1, int(float(state.overview_flight_time_minutes or 120)))
        except Exception:
            return 120

    def header_progress_percent() -> float:
        status_index = int(getattr(state, "overview_flight_status_index", 0) or 0)
        if status_index < 2:
            return 0.0
        if status_index >= 5:
            return 100.0
        start_ts = getattr(state, "overview_takeoff_start_timestamp", None)
        if not bool(getattr(state, "overview_progress_running", False)) or not isinstance(start_ts, (int, float)):
            return 0.0
        elapsed_min = max(0.0, (time.time() - float(start_ts)) / 60.0)
        return clamp((elapsed_min / header_progress_duration_minutes()) * 100.0, 0.0, 100.0)

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
                    ft.Text(title, size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                    ft.Divider(height=10, opacity=0.15),
                    content,
                ],
                spacing=10,
            ),
            padding=16,
            border_radius=20,
            bgcolor=bgcolor_override or tokens["panel"],
            border=ft.border.all(1, tokens["card_border"]),
            shadow=ft.BoxShadow(
                blur_radius=18,
                spread_radius=1,
                color=ft.Colors.with_opacity(0.10, ft.Colors.BLACK),
                offset=ft.Offset(0, 6),
            ),
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
                ft.Container(expand=True, bgcolor=base_bg or tokens["panel"] if use_daylight_cards() else ft.Colors.TRANSPARENT),
                ft.Container(
                    expand=True,
                    image=ft.DecorationImage(src=src, fit=ft.BoxFit.COVER, opacity=0.32),
                ),
            ]
        return [ft.Container(expand=True, bgcolor=base_bg or tokens["panel"])]

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
                    ft.Text(title, size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                    ft.Divider(height=10, opacity=0.15),
                    content,
                ],
                spacing=10,
            ),
            padding=16,
            border_radius=20,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=card_base_bg,
            image=ft.DecorationImage(src=bg_src, fit=ft.BoxFit.COVER, opacity=0.32) if bg_src else None,
            border=ft.border.all(1, tokens["card_border"]),
            shadow=ft.BoxShadow(
                blur_radius=18,
                spread_radius=1,
                color=ft.Colors.with_opacity(0.10, ft.Colors.BLACK),
                offset=ft.Offset(0, 6),
            ),
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
            bgcolor=tokens["subpanel"],
            border=ft.border.all(1, tokens["card_border"]),
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Text(label, size=12, opacity=0.8, color=tokens["muted"]),
                    value_control,
                    ft.Text(subtitle, size=11, opacity=0.8, color=tokens["muted"]),
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
            except Exception:
                state.calendar_entries = []

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
        state.display_mode = "dark"
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
        if settings_storage_path.exists():
            try:
                data = json.loads(settings_storage_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    state.display_mode = "daylight" if str(data.get("display_mode", "dark")).lower() == "daylight" else "dark"
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
                    state.professional_info_enabled = bool(data.get("professional_info_enabled", False))
                    state.app_volume = clamp_setting(data.get("app_volume", 0.85), 0.0, 1.0, 0.85)
                    state.app_muted = bool(data.get("app_muted", False))
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
                "professional_info_enabled": bool(getattr(state, "professional_info_enabled", False)),
                "app_volume": round(float(getattr(state, "app_volume", 0.85) or 0.0), 2),
                "app_muted": bool(getattr(state, "app_muted", False)),
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
    if sync_profile_from_calendar_completion():
        save_calendar_entries()

    # Authentication is intentionally bypassed in this public portfolio version.
    state.is_logged_in = True
    state.pilot_name = "User"
    state.selected_tab_index = 1

    root_host = ft.Container(expand=True)
    airport_background_preload_host = ft.Container(
        width=1,
        height=1,
        opacity=0.01,
        content=ft.Row(spacing=0, controls=[]),
    )
    login_background_preload_host = ft.Container(
        width=1,
        height=1,
        opacity=0.01,
        content=ft.Stack(
            controls=[
                ft.Image(src=state.page_backgrounds.get("LOGIN", "login_bg.jpg"), width=1, height=1, fit=ft.BoxFit.COVER),
                ft.Container(
                    width=1,
                    height=1,
                    image=ft.DecorationImage(
                        src=state.page_backgrounds.get("LOGIN", "login_bg.jpg"),
                        fit=ft.BoxFit.COVER,
                        opacity=1.0,
                    ),
                ),
            ],
        ),
    )

    login_transition_audio = None
    audio_class = getattr(ft, "Audio", None)
    if audio_class is not None:
        try:
            login_transition_audio = audio_class(
                src="audio/login_transition.mp3",
                autoplay=False,
            )
        except TypeError:
            try:
                login_transition_audio = audio_class(src="audio/login_transition.mp3")
            except Exception:
                login_transition_audio = None
        except Exception:
            login_transition_audio = None

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
        font_family="Consolas",
        max_lines=1,
        no_wrap=True,
    )
    header_route_line_host = ft.Container(height=34)

    txt_welcome = ft.Text("", size=18, weight=ft.FontWeight.W_700)
    txt_time = ft.Text("", size=12, opacity=0.9)
    txt_location = ft.Text("", size=12, opacity=0.9)
    txt_weather = ft.Text("", size=12, opacity=0.9)
    overview_date_text = ft.Text("", size=13, color=tokens["muted"])
    overview_time_text = ft.Text("", size=26, weight=ft.FontWeight.W_800, color=tokens["text"])
    overview_location_text = ft.Text("", size=12, color=tokens["muted"])
    overview_weather_text = ft.Text("", size=12, color=tokens["muted"])
    overview_route_line_host = ft.Container()
    overview_ete_value_text = ft.Text("", size=18, weight=ft.FontWeight.W_800, color=tokens["text"], text_align=ft.TextAlign.CENTER)
    overview_eta_value_text = ft.Text("", size=18, weight=ft.FontWeight.W_800, color=tokens["text"], text_align=ft.TextAlign.CENTER)
    overview_progress_percent_text = ft.Text("", size=20, weight=ft.FontWeight.W_900, color=tokens["accent"])
    overview_progress_refresh_callback = None
    ramp_status_card_host = ft.Container(width=500, height=440)
    ramp_status_refresh_callback = None
    takeoff_date_text = ft.Text("", size=14, color=tokens["muted"])
    takeoff_time_text = ft.Text("", size=34, weight=ft.FontWeight.W_800, color=ft.Colors.WHITE)
    takeoff_location_text = ft.Text("", size=12, color=tokens["muted"])
    takeoff_weather_text = ft.Text("", size=12, color=tokens["muted"])
    landing_date_text = ft.Text("", size=14, color=tokens["muted"])
    landing_time_text = ft.Text("", size=34, weight=ft.FontWeight.W_800, color=ft.Colors.WHITE)
    home_airline_logo_host = ft.Container()

    def now_local_str():
        return datetime.now().strftime("%a %d %b • %H:%M:%S")

    def refresh_header_texts():
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
        takeoff_date_text.value = overview_date_text.value
        takeoff_time_text.value = overview_time_text.value
        takeoff_time_text.color = ft.Colors.WHITE if state.airline else tokens["text"]
        takeoff_date_text.color = tokens["muted"]
        takeoff_location_text.color = tokens["muted"]
        takeoff_weather_text.color = tokens["muted"]
        takeoff_location_text.value = txt_location.value
        takeoff_weather_text.value = txt_weather.value
        landing_date_text.value = overview_date_text.value
        landing_time_text.value = overview_time_text.value
        landing_time_text.color = ft.Colors.WHITE if state.airline else tokens["text"]
        landing_date_text.color = tokens["muted"]


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

    def airline_logo_image(
        airline_name: Optional[str],
        width: int = 140,
        height: int = 60,
        opacity: float = 1.0,
        fit=ft.BoxFit.CONTAIN,
        fallback_text: bool = True,
        key_prefix: str = "logo",
    ) -> ft.Control:
        rel = airline_logo_rel_path(airline_name)
        current_airline = (airline_name or "").strip()
        if rel:
            return ft.Image(
                src=rel,
                width=width,
                height=height,
                fit=fit,
                opacity=opacity,
                key=f"{key_prefix}-{current_airline}-{state.logo_refresh_nonce}",
            )
        if fallback_text:
            return ft.Text(current_airline.upper(), size=12, weight=ft.FontWeight.W_700, color=tokens["muted"])
        return ft.Container(width=width, height=height)

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
        "A330-300": "a330_300",
        "A340-600": "a340_600",
        "A350-900": "a350_900",
        "A350-1000": "a350_1000",
        "A380-800": "a380_800",
        "B737-8MAX": "b737_8_max",
        "B747-8": "b747_8",
        "B747-200": "b747_200",
        "B757-200": "b757_200",
        "B777-300ER": "b777_300er",
        "B787-9": "b787_9",
        "B787-10": "b787_10",
    }

    GENERIC_AIRCRAFT_FILE_STEMS = {
        "A320-200": ["a320-200", "generic_a320_200"],
        "A321-200": ["a321-200", "generic_a321_200"],
        "A321neo": ["a321-200", "generic_a321_200"],
        "A330-300": ["a330-300", "generic_a330_300"],
        "A340-600": ["a340-600", "generic_a340_600"],
        "A350-900": ["a350-900", "generic_a350_900"],
        "A350-1000": ["a350-1000", "generic_a350_1000", "a350-900", "generic_a350_900"],
        "A380-800": ["a380-800", "generic_a380_800"],
        "B737-8MAX": ["737-8-max", "b737-8-max", "generic_b737_8_max"],
        "B747-8": ["747-8", "b747-8", "generic_b747_8"],
        "B747-200": ["747-200", "b747-200", "generic_b747_200"],
        "B757-200": ["757-200", "b757-200", "generic_b757_200"],
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
        rel = aircraft_livery_rel_path(airline_name, aircraft_key)
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

    def show_snack(message: str):
        page.snack_bar = ft.SnackBar(ft.Text(message))
        page.snack_bar.open = True
        page.update()

    def safe_update_control(ctrl):
        try:
            if getattr(ctrl, "page", None):
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
                takeoff_time_text,
                takeoff_location_text,
                takeoff_weather_text,
                landing_date_text,
                landing_time_text,
            ):
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

    def login_background_src() -> str:
        return page_background_src("LOGIN") or state.page_backgrounds.get("LOGIN", "login_bg.jpg")

    def login_fms_lower_background_src() -> str:
        # Put the lower image layer for the FMS cutout here:
        # C:\FMS\assets\backgrounds\login_fms_lower_bg.jpg
        for rel_path in (
            "backgrounds/login_fms_lower_bg.png",
            "backgrounds/login_fms_lower_bg.jpg",
            "backgrounds/login_fms_lower_bg.jpeg",
            "backgrounds/login_fms_lower_bg.webp",
        ):
            found = asset_rel_path_if_exists(rel_path)
            if found:
                return found
        return login_background_src()

    def login_fms_lower_background_abs_path() -> Optional[Path]:
        for rel_path in (
            "backgrounds/login_fms_lower_bg.png",
            "backgrounds/login_fms_lower_bg.jpg",
            "backgrounds/login_fms_lower_bg.jpeg",
            "backgrounds/login_fms_lower_bg.webp",
        ):
            found = asset_abs_path_if_exists(rel_path)
            if found:
                return found
        fallback = login_background_src()
        return asset_abs_path_if_exists(fallback)

    def refresh_login_background_preloader():
        try:
            src = login_background_src()
            if getattr(login_background_preload_host, "_fms_login_bg_src", None) == src:
                return
            login_background_preload_host._fms_login_bg_src = src
            login_background_preload_host.content = ft.Stack(
                controls=[
                    ft.Image(src=src, width=1, height=1, fit=ft.BoxFit.COVER),
                    ft.Container(
                        width=1,
                        height=1,
                        image=ft.DecorationImage(src=src, fit=ft.BoxFit.COVER, opacity=1.0),
                    ),
                ],
            )
        except Exception:
            pass

    def login_transition_audio_rel_src() -> Optional[str]:
        return (
            asset_rel_path_if_exists("audio/login_transition.mp3")
            or asset_rel_path_if_exists("sounds/login_transition.mp3")
            or asset_rel_path_if_exists("login_transition.mp3")
        )

    def login_transition_audio_abs_path() -> Optional[Path]:
        return (
            asset_abs_path_if_exists("audio/login_transition.mp3")
            or asset_abs_path_if_exists("sounds/login_transition.mp3")
            or asset_abs_path_if_exists("login_transition.mp3")
        )

    def effective_app_volume() -> float:
        if bool(getattr(state, "app_muted", False)):
            return 0.0
        return clamp_setting(getattr(state, "app_volume", 0.85), 0.0, 1.0, 0.85)

    def play_login_transition_audio_windows_mci(audio_path: Path):
        # Windows desktop fallback for MP3 playback. This does not depend on
        # Flet's Audio control, which may be unavailable in some desktop builds.
        def _worker():
            alias = f"fms_login_transition_{int(time.time() * 1000)}"
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

    def play_login_transition_audio():
        audio_abs = login_transition_audio_abs_path()
        if not audio_abs:
            return

        # Prefer native Windows MP3 playback on Windows because it works even
        # when ft.Audio is not available or silent.
        if os.name == "nt":
            play_login_transition_audio_windows_mci(audio_abs)
            return

        # Fallback for non-Windows/Flet builds.
        if login_transition_audio is None:
            return

        audio_src = login_transition_audio_rel_src()
        if not audio_src:
            return

        try:
            if getattr(login_transition_audio, "src", None) != audio_src:
                login_transition_audio.src = audio_src
            if effective_app_volume() <= 0:
                return
            if hasattr(login_transition_audio, "volume"):
                login_transition_audio.volume = effective_app_volume()
            if hasattr(login_transition_audio, "seek"):
                try:
                    login_transition_audio.seek(0)
                except Exception:
                    pass
            if hasattr(login_transition_audio, "play"):
                login_transition_audio.play()
            elif hasattr(login_transition_audio, "resume"):
                login_transition_audio.resume()
            if getattr(login_transition_audio, "page", None):
                login_transition_audio.update()
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
            play_login_transition_audio_windows_mci(audio_abs)
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


    def airport_card_background_src(code: Optional[str], fallback_key: str = "airport") -> Optional[str]:
        canonical = (normalize_airport_code(code) or code or "").strip().upper()
        fallback_key = (fallback_key or "airport").strip().lower()

        airport_background_groups = {
            "KJFK": "NEW_YORK",
            "KLGA": "NEW_YORK",
            "KEWR": "NEW_YORK",
            "ZSPD": "SHANGHAI",
            "ZSSS": "SHANGHAI",
        }

        grouped_background = airport_background_groups.get(canonical)
        candidates: List[str] = []
        if grouped_background:
            for ext in ("jpg", "jpeg", "png", "webp"):
                candidates.append(f"overview/airport_cards/{grouped_background}.{ext}")
                candidates.append(f"overview/airport_cards/{grouped_background.lower()}.{ext}")

        if canonical:
            for ext in ("jpg", "jpeg", "png", "webp"):
                candidates.append(f"overview/airport_cards/{canonical}.{ext}")
                candidates.append(f"overview/airport_cards/{canonical.lower()}.{ext}")

        for ext in ("jpg", "jpeg", "png", "webp"):
            candidates.append(f"overview/airport_cards/{fallback_key}_default.{ext}")
            candidates.append(f"overview/airport_cards/airport_default.{ext}")

        for rel_path in candidates:
            found = asset_rel_path_if_exists(rel_path)
            if found:
                return found
        return None

    def discover_airport_card_background_assets() -> List[str]:
        rel_paths: List[str] = []
        seen = set()
        for base in (Path(__file__).resolve().parent / "assets", Path.cwd() / "assets"):
            folder = base / "overview" / "airport_cards"
            if not folder.exists():
                continue
            for candidate in folder.iterdir():
                if candidate.is_file() and candidate.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                    rel = f"overview/airport_cards/{candidate.name}"
                    if rel not in seen:
                        seen.add(rel)
                        rel_paths.append(rel)
        return rel_paths

    def refresh_airport_background_preloader(update_page: bool = False):
        try:
            rel_paths = discover_airport_card_background_assets()

            # Prioritize currently relevant route/airport images so they are cached first.
            priority_codes = [
                (state.departure or takeoff_departure_icao_tf.value or "").strip().upper(),
                (state.arrival or landing_arrival_icao_tf.value or "").strip().upper(),
                (takeoff_departure_icao_tf.value or "").strip().upper(),
                (landing_arrival_icao_tf.value or "").strip().upper(),
            ]
            priority_paths: List[str] = []
            for code in priority_codes:
                found = airport_card_background_src(code, "airport")
                if found and found not in priority_paths:
                    priority_paths.append(found)

            ordered_paths = priority_paths + [rel for rel in rel_paths if rel not in priority_paths]
            current_paths = getattr(airport_background_preload_host, "_fms_preloaded_paths", None)
            if current_paths == ordered_paths:
                return

            airport_background_preload_host._fms_preloaded_paths = list(ordered_paths)
            airport_background_preload_host.content = ft.Row(
                spacing=0,
                controls=[
                    ft.Image(
                        src=rel,
                        width=1,
                        height=1,
                        fit=ft.BoxFit.COVER,
                        opacity=0.01,
                    )
                    for rel in ordered_paths
                ],
            )
            if update_page and getattr(airport_background_preload_host, "page", None):
                airport_background_preload_host.update()
        except Exception:
            pass

    def airport_background_glass_card(
        title: str,
        content: ft.Control,
        airport_code: Optional[str],
        fallback_key: str,
        height: Optional[int] = None,
        width: Optional[int] = None,
        expand: bool = False,
    ) -> ft.Control:
        daylight_cards_active = use_daylight_cards()
        background_src = airport_card_background_src(airport_code, fallback_key)

        background_layers: List[ft.Control] = [
            ft.Container(expand=True, bgcolor=tokens["panel"]),
        ]
        if background_src:
            background_layers.extend([
                ft.Container(
                    expand=True,
                    image=ft.DecorationImage(
                        src=background_src,
                        fit=ft.BoxFit.COVER,
                        opacity=0.62 if daylight_cards_active else 0.50,
                    ),
                ),
                ft.Container(
                    expand=True,
                    bgcolor=ft.Colors.with_opacity(0.16 if daylight_cards_active else 0.35, ft.Colors.BLACK),
                ),
            ])

        return ft.Container(
            width=width,
            height=height,
            expand=expand,
            border_radius=20,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=ft.Colors.with_opacity(0.46, tokens["panel"]) if daylight_cards_active else ft.Colors.with_opacity(0.30, tokens["panel"]),
            border=ft.border.all(1, tokens["card_border"] if daylight_cards_active else ft.Colors.with_opacity(0.35, tokens["card_border"])),
            shadow=ft.BoxShadow(
                blur_radius=18,
                spread_radius=1,
                color=ft.Colors.with_opacity(0.10, ft.Colors.BLACK),
                offset=ft.Offset(0, 6),
            ),
            content=ft.Stack(
                expand=True,
                controls=[
                    *background_layers,
                    ft.Container(
                        expand=True,
                        padding=16,
                        content=ft.Column(
                            controls=[
                                ft.Text(title, size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                                ft.Divider(height=10, opacity=0.15),
                                content,
                            ],
                            spacing=10,
                        ),
                    ),
                ],
            ),
        )


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
            actions=[ft.TextButton("Close", on_click=lambda evt: close_help_center())],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog = help_dialog
        help_dialog.open = True
        page.update()

    def close_help_center():
        if page.dialog:
            page.dialog.open = False
            page.update()

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
            bgcolor=tokens["panel"],
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
                            ft.ElevatedButton("Save", on_click=lambda evt: save_status_center(), bgcolor=tokens["accent"], color=ft.Colors.WHITE),
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
    page.overlay.append(airport_background_preload_host)
    if login_transition_audio is not None:
        page.overlay.append(login_transition_audio)

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

    def airport_weather_for_card(code: Optional[str]) -> dict:
        canonical = normalize_airport_code(code) or (code or "").strip().upper()
        if not canonical:
            return {"temperature": "—", "icon": "🌡️", "condition": "Weather unavailable"}

        now_ts = time.time()
        cached = airport_weather_cache.get(canonical)
        if cached and now_ts - float(cached.get("timestamp", 0.0)) < 900:
            return cached

        record = lookup_airport_record(canonical)
        if not record:
            payload = {
                "timestamp": now_ts,
                "temperature": "—",
                "icon": "🌡️",
                "condition": "Weather unavailable",
            }
            airport_weather_cache[canonical] = payload
            return payload

        try:
            latitude = float(record["lat"])
            longitude = float(record["lon"])
            query = urllib.parse.urlencode(
                {
                    "latitude": f"{latitude:.5f}",
                    "longitude": f"{longitude:.5f}",
                    "current": "temperature_2m,weather_code,is_day,wind_speed_10m",
                    "timezone": "auto",
                }
            )
            url = f"https://api.open-meteo.com/v1/forecast?{query}"
            with urllib.request.urlopen(url, timeout=4) as response:
                payload_raw = json.loads(response.read().decode("utf-8"))

            current = payload_raw.get("current", {})
            temperature_c = current.get("temperature_2m")
            weather_code = current.get("weather_code")
            is_day = bool(current.get("is_day", 1))
            wind_speed = current.get("wind_speed_10m")
            icon, condition = weather_icon_and_label(weather_code, is_day=is_day, wind_speed_kmh=wind_speed)
            payload = {
                "timestamp": now_ts,
                "temperature": format_temperature_for_default_unit(float(temperature_c)) if temperature_c is not None else "—",
                "icon": icon,
                "condition": condition,
            }
        except Exception:
            payload = {
                "timestamp": now_ts,
                "temperature": "—",
                "icon": "🌡️",
                "condition": "Weather unavailable",
            }

        airport_weather_cache[canonical] = payload
        return payload

    def airport_environment_for_overview(code: Optional[str]) -> dict:
        canonical = normalize_airport_code(code) or (code or "").strip().upper()
        record = lookup_airport_record(canonical) if canonical else None
        elevation_value = "—"
        if record and record.get("elevation_ft") is not None:
            try:
                elevation_value = f"{float(record.get('elevation_ft')):,.0f} ft"
            except Exception:
                elevation_value = f"{record.get('elevation_ft')} ft"

        if not canonical:
            return {
                "timestamp": time.time(),
                "wind": "—",
                "visibility": "—",
                "elevation": elevation_value,
            }

        now_ts = time.time()
        cached = airport_environment_cache.get(canonical)
        if cached and now_ts - float(cached.get("timestamp", 0.0)) < 900:
            # Keep elevation fresh from the local airport library, even when
            # METAR data is cached.
            cached["elevation"] = elevation_value
            return cached

        payload = {
            "timestamp": now_ts,
            "wind": "—",
            "visibility": "—",
            "elevation": elevation_value,
        }

        try:
            url = f"https://aviationweather.gov/api/data/metar?ids={canonical}&format=json"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as response:
                metar_payload = json.loads(response.read().decode("utf-8"))

            if metar_payload:
                m = metar_payload[0]
                wind_dir = m.get("wdir", None)
                wind_speed = m.get("wspd", None)
                wind_gust = m.get("wgst", None)

                if wind_speed in (None, ""):
                    wind_label = "Calm / unavailable"
                else:
                    direction_label = "VRB" if wind_dir in (None, "", "VRB") else f"{int(float(wind_dir)):03d}°"
                    wind_label = f"{direction_label} {int(float(wind_speed))} kt"
                    if wind_gust not in (None, "", 0, "0"):
                        wind_label += f" G{int(float(wind_gust))}"

                visibility = m.get("visib", None)
                if visibility in (None, ""):
                    visibility_label = "—"
                else:
                    visibility_label = str(visibility).strip()
                    if visibility_label and not visibility_label.upper().endswith(("SM", "KM", "M")):
                        visibility_label = f"{visibility_label} SM"

                payload.update(
                    {
                        "timestamp": now_ts,
                        "wind": wind_label,
                        "visibility": visibility_label,
                        "elevation": elevation_value,
                    }
                )
        except Exception:
            pass

        airport_environment_cache[canonical] = payload
        return payload

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
            content=ft.Text("Allow FCAM to use device location for local position and future weather integration?"),
            actions=[
                ft.TextButton("Not now", on_click=lambda evt: close_location_prompt(False)),
                ft.ElevatedButton("Allow", on_click=lambda evt: close_location_prompt(True), bgcolor=tokens["accent"], color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog = dialog
        dialog.open = True
        page.update()

    def close_location_prompt(enabled: bool):
        if page.dialog:
            page.dialog.open = False
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
    settings_professional_info_switch = ft.Switch(
        value=bool(getattr(state, "professional_info_enabled", False)),
        active_color="#FF3B30",
        active_track_color=ft.Colors.with_opacity(0.38, "#FF3B30"),
        inactive_thumb_color=tokens["muted"],
        inactive_track_color=ft.Colors.with_opacity(0.22, ft.Colors.WHITE),
    )
    settings_volume_slider = ft.Slider(min=0.0, max=1.0, divisions=20, value=getattr(state, "app_volume", 0.85), width=300)
    settings_mute_switch = ft.Switch(label="Mute app sounds", value=bool(getattr(state, "app_muted", False)))
    settings_volume_value_text = ft.Text("Volume: 85%", size=12, color=tokens["muted"])
    settings_performance_status_text = ft.Text("Low performance mode keeps the interface lighter by slowing live refreshes.", size=12, color=tokens["muted"])
    settings_export_status_text = ft.Text(f"Exports will be saved inside {storage_dir / 'exports'}.", size=12, color=tokens["muted"])
    settings_calendar_import_status_text = ft.Text("Upload a calendar JSON export to replace the current calendar.", size=12, color=tokens["muted"])
    settings_background_status_text = ft.Text(f"Global background path: {app_background_instruction_path()} | Daytime path: {daylight_background_instruction_path()}", size=12, color=tokens["muted"])
    settings_professional_info_status_text = ft.Text("Normal information: advanced planning cards are hidden.", size=12, color=tokens["muted"])

    username_tf = ft.TextField(
        label="ID no.",
        width=340,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
        border_color=tokens["card_border"],
        color=tokens["text"],
        label_style=ft.TextStyle(color=tokens["muted"]),
        text_size=14,
    )

    password_tf = ft.TextField(
        label="Password",
        width=340,
        password=True,
        can_reveal_password=True,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
        border_color=tokens["card_border"],
        color=tokens["text"],
        label_style=ft.TextStyle(color=tokens["muted"]),
        text_size=14,
    )
    login_error = ft.Text("", color="#FFB4B4", size=12)

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
        value="",
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
        value="",
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
        value="25",
        width=260,
        border_radius=16,
        filled=True,
        bgcolor=tokens["input_bg"],
        hint_text="Used only in Allowance mode",
    )
    bag_per_bag_kg_tf = ft.TextField(
        label="Mass per checked bag (kg)",
        value="23",
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
    cal_airline_dd = ft.Dropdown(
        label="Airline",
        value=state.airline or None,
        options=[ft.dropdown.Option(name) for name in AIRLINES],
        width=200,
        border_radius=16,
        filled=True,
    )
    cal_aircraft_dd = ft.Dropdown(label="Aircraft", width=200, border_radius=16, filled=True)
    cal_origin_tf = ft.TextField(label="Origin", hint_text="e.g. EDDB", width=200, border_radius=16, filled=True)
    cal_destination_tf = ft.TextField(label="Destination", hint_text="e.g. OMDB", width=200, border_radius=16, filled=True)
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
            ft.dropdown.Option("Longest flight time"),
            ft.dropdown.Option("Shortest flight time"),
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
    takeoff_metar_status_text = ft.Text("Enter a departure ICAO or fetch METAR.", size=12, color=tokens["muted"])
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
    takeoff_climb_high_text = ft.Text("High Alt: —", size=24, weight=ft.FontWeight.W_900, color=tokens["accent"])

    takeoff_route_distance_tf = ft.TextField(label="Route distance (NM, editable)", value="", width=240, border_radius=16, filled=True, bgcolor=tokens["input_bg"], hint_text="Auto-filled. Edit to override.")
    takeoff_fuel_passengers_tf = ft.TextField(label="Passenger count", value="", width=170, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_fuel_baggage_tf = ft.TextField(label="Baggage total (kg)", value="", width=190, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    takeoff_fuel_cargo_tf = ft.TextField(label="Cargo total (kg)", value="", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
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
    takeoff_fuel_status_text = ft.Text("Set departure, destination, aircraft, passengers, baggage, and cargo.", size=12, color=tokens["muted"])
    takeoff_trip_fuel_text = ft.Text("Base trip fuel: —", size=12, color=tokens["text"])
    takeoff_block_fuel_text = ft.Text("Planned fuel: —", size=12, color=tokens["text"])
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
    landing_metar_status_text = ft.Text("Enter an arrival ICAO or fetch METAR.", size=12, color=tokens["muted"])
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
    landing_vs_calc_altitude_tf = ft.TextField(label="V/S calc altitude to lose (ft)", value="", width=220, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    landing_vs_calc_ete_tf = ft.TextField(label="V/S calc ETE (min)", value="", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
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
    seat_business_tf = ft.TextField(label="Business seats", value="32", width=170, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    seat_premium_tf = ft.TextField(label="Premium Economy seats", value="28", width=220, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    seat_economy_tf = ft.TextField(label="Economy seats", value="226", width=180, border_radius=16, filled=True, bgcolor=tokens["input_bg"])

    seat_fill_first_tf = ft.TextField(label="Fill First", value="0", width=150, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    seat_fill_business_tf = ft.TextField(label="Fill Business", value="0", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    seat_fill_premium_tf = ft.TextField(label="Fill Premium", value="0", width=170, border_radius=16, filled=True, bgcolor=tokens["input_bg"])
    seat_fill_economy_tf = ft.TextField(label="Fill Economy", value="0", width=160, border_radius=16, filled=True, bgcolor=tokens["input_bg"])

    seat_status_text = ft.Text("Select airline, aircraft, and seat counts. Then generate the map.", size=13, weight=ft.FontWeight.W_600)
    seat_summary_title = ft.Text("No seat map generated yet.", size=14, weight=ft.FontWeight.W_700, color=tokens["text"])
    seat_total_stat = ft.Text("Total seats: —", size=12, color=tokens["text"])
    seat_occupied_stat = ft.Text("Occupied seats: —", size=12, color=tokens["text"])
    seat_available_stat = ft.Text("Available seats: —", size=12, color=tokens["text"])
    seat_breakdown_stat = ft.Text("Breakdown: —", size=12, color=tokens["muted"])

    seat_map_host = ft.Container(
        padding=0,
        bgcolor=ft.Colors.TRANSPARENT,
        content=glass_card_with_background(
            "Seat Map",
            ft.Text("Generate a seat map to see the cabin overview here.", color=tokens["muted"]),
            bg_key="seat_map",
        ),
    )

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

    def sync_input_colors():
        for ctrl in [
            bag_mode_dd,
            bag_pax_tf,
            bag_carry_on_tf,
            bag_category_dd,
            bag_checked_kg_per_pax_tf,
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
        bag_status_text.color = danger_color
        cal_form_message.color = danger_color
        cal_route_preview.color = tokens["muted"]
        takeoff_metar_status_text.color = tokens["muted"]
        takeoff_status_text.color = danger_color
        landing_metar_status_text.color = tokens["muted"]
        landing_status_text.color = danger_color
        seat_status_text.color = danger_color
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
            takeoff_block_fuel_text,
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
        refresh_seat_widget_styles(update_page=False)

    def default_checked_baggage_for_category(category: Optional[str]) -> float:
        return BAGGAGE_STANDARD_DEFAULTS.get(category or "", BAGGAGE_STANDARD_DEFAULTS["Within the European region"])

    def apply_baggage_category_default():
        bag_checked_kg_per_pax_tf.value = f"{default_checked_baggage_for_category(bag_category_dd.value):.1f}".rstrip("0").rstrip(".")

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
        options = all_library_aircraft_names()
        preferred = canonical_aircraft_name(preferred) or canonical_aircraft_name(state.aircraft) or preferred
        cal_aircraft_dd.options = [ft.dropdown.Option(a) for a in options]
        if preferred in options:
            cal_aircraft_dd.value = preferred
        else:
            cal_aircraft_dd.value = None

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
        return int(record["elevation_ft"]) if record else None

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
        if departure:
            state.departure = departure
        if fill_elevation:
            elev = lookup_airport_elevation_ft(departure)
            if elev is not None:
                takeoff_elevation_tf.value = str(elev)
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
        takeoff_climb_high_text.value = "High Alt: —"
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
        takeoff_raw_metar_tf.value = ""
        takeoff_metar_status_text.value = "Enter a departure ICAO or fetch METAR."
        state.route_distance_override_nm = None
        state.route_distance_override_key = ""
        takeoff_route_distance_tf.value = ""
        takeoff_fuel_passengers_tf.value = ""
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
        takeoff_block_fuel_text.value = "Planned fuel: —"
        takeoff_ete_text.value = "Flight time: —"
        takeoff_burn_rate_text.value = "Actual payload: —"
        takeoff_fuel_breakdown_text.value = "Phase split: —"
        takeoff_recommended_tow_text.value = "Estimated TOW: —"
        takeoff_fuel_status_text.value = "Set departure, destination, aircraft, passengers, baggage, and cargo."
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

    def render_takeoff_warnings(result: TakeoffResultData):
        controls = []
        for message in result.warnings:
            controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=999,
                    bgcolor=ft.Colors.with_opacity(0.16, ft.Colors.RED),
                    content=ft.Text(message, size=12, weight=ft.FontWeight.W_700, color=ft.Colors.RED_700),
                )
            )
        for message in result.cautions:
            controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=999,
                    bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.AMBER),
                    content=ft.Text(message, size=12, weight=ft.FontWeight.W_700, color=ft.Colors.AMBER_800),
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
        if arrival:
            state.arrival = normalize_airport_code(arrival) or arrival
            landing_arrival_icao_tf.value = state.arrival
        if fill_elevation:
            elev = lookup_airport_elevation_ft(arrival)
            if elev is not None:
                landing_elevation_tf.value = str(elev)
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
        landing_raw_metar_tf.value = ""
        landing_metar_status_text.value = "Enter an arrival ICAO or fetch METAR."
        if not state.aircraft:
            landing_status_text.value = "Select an aircraft in Takeoff to begin landing planning."
        reset_landing_result_display()
        if update_page:
            page.update()

    def sync_aircraft_across_pages(aircraft_name: Optional[str], update_page: bool = True):
        canonical = canonical_aircraft_name(aircraft_name)
        if not canonical:
            state.aircraft = ""
            takeoff_aircraft_dd.value = None
            landing_aircraft_dd.value = None
            update_takeoff_aircraft_details(update_page=False)
            update_landing_aircraft_details(update_page=False)
            refresh_takeoff_fuel_info(update_page=False)
            if update_page:
                page.update()
            return

        state.aircraft = canonical
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
                    content=ft.Text(message, size=12, weight=ft.FontWeight.W_700, color=ft.Colors.RED_700),
                )
            )
        for message in result.cautions:
            controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=999,
                    bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.AMBER),
                    content=ft.Text(message, size=12, weight=ft.FontWeight.W_700, color=ft.Colors.AMBER_800),
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

    def apply_seat_template_defaults(aircraft_name: Optional[str] = None):
        aircraft_name = aircraft_name or seat_aircraft_dd.value or state.aircraft
        preset = get_aircraft_seat_preset(aircraft_name)
        defaults = preset.get("defaults", {})
        seat_first_tf.value = str(defaults.get("First", 0))
        seat_business_tf.value = str(defaults.get("Business", 0))
        seat_premium_tf.value = str(defaults.get("Premium Economy", 0))
        seat_economy_tf.value = str(defaults.get("Economy", 0))

    def seat_available_color(cabin: str, occupied: bool) -> str:
        if occupied:
            return tokens["accent"]
        return CABIN_COLORS.get(cabin, tokens["subpanel"])

    def seat_text_color(cabin: str, occupied: bool) -> str:
        if occupied:
            return ft.Colors.WHITE
        if cabin == "Economy":
            return "#374151"
        return ft.Colors.WHITE

    def refresh_seat_widget_styles(update_page: bool = True):
        for seat in seat_model.get("seats", []):
            refs = seat_model.get("seat_controls", {}).get(seat["id"])
            if not refs:
                continue
            container, text = refs
            container.bgcolor = seat_available_color(seat["cabin"], seat["occupied"])
            container.border = ft.border.all(1, tokens["card_border"])
            text.color = seat_text_color(seat["cabin"], seat["occupied"])
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

        bag_pax_tf.value = str(occupied)

        if seat_model.get("generated"):
            aircraft_name = canonical_aircraft_name(seat_model.get("aircraft")) or seat_model.get("aircraft") or current_aircraft_label()
            seat_passenger_load_host.content = build_passenger_load_panel(aircraft_name)
            if update_page:
                safe_update_control(seat_passenger_load_host)

        if update_page:
            page.update()

    def toggle_seat_occupancy(seat_id: str):
        for seat in seat_model.get("seats", []):
            if seat["id"] == seat_id:
                seat["occupied"] = not seat["occupied"]
                refs = seat_model.get("seat_controls", {}).get(seat_id)
                if refs:
                    container, text = refs
                    container.bgcolor = seat_available_color(seat["cabin"], seat["occupied"])
                    text.color = seat_text_color(seat["cabin"], seat["occupied"])
                seat_status_text.value = f"Toggled seat {seat_id}."
                update_seat_summary(update_page=False)
                page.update()
                return

    def build_seat_control(seat: dict) -> ft.Control:
        seat_text = ft.Text(seat["label"], size=10, weight=ft.FontWeight.W_700, color=seat_text_color(seat["cabin"], seat["occupied"]))
        seat_box = ft.Container(
            width=28,
            height=28,
            border_radius=9,
            alignment=ft.Alignment(0, 0),
            bgcolor=seat_available_color(seat["cabin"], seat["occupied"]),
            border=ft.border.all(1, tokens["card_border"]),
            content=seat_text,
            tooltip=f"{seat['id']} • {seat['cabin']}",
        )
        seat_model["seat_controls"][seat["id"]] = (seat_box, seat_text)
        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e, seat_id=seat["id"]: toggle_seat_occupancy(seat_id),
            content=seat_box,
        )

    def make_blank_seat() -> ft.Control:
        return ft.Container(width=28, height=28)


    def make_aisle_gap() -> ft.Control:
        return ft.Container(width=18, height=28)

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

    def build_digital_seat_rows(counts: Dict[str, int], preset: Dict, start_row: int = 0, deck_prefix: str = "", deck_label: str = "") -> List[Dict]:
        rows = []
        row_number = start_row
        for cabin in CABIN_ORDER:
            count = max(0, int(counts.get(cabin, 0)))
            layout = preset.get("layouts", {}).get(cabin)
            if cabin == "First" and count > 0 and not layout:
                layout = [1, 2, 1]
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

    def build_seat_control_small(seat: dict) -> ft.Control:
        seat_text = ft.Text(seat["label"], size=8, weight=ft.FontWeight.W_800, color=seat_text_color(seat["cabin"], seat["occupied"]))
        seat_box = ft.Container(
            width=24,
            height=24,
            border_radius=7,
            alignment=ft.Alignment(0, 0),
            bgcolor=seat_available_color(seat["cabin"], seat["occupied"]),
            border=ft.border.all(1, ft.Colors.with_opacity(0.75, tokens["card_border"])),
            content=seat_text,
            tooltip=f"{seat['id']} • {seat['cabin']}",
        )
        seat_model["seat_controls"][seat["id"]] = (seat_box, seat_text)
        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e, seat_id=seat["id"]: toggle_seat_occupancy(seat_id),
            content=seat_box,
        )

    def cabin_class_label(cabin: str) -> str:
        return "Premium\nEconomy" if cabin == "Premium Economy" else cabin

    def build_seat_row_visual(row: Dict, last_cabin: str = None) -> ft.Control:
        row_controls = [
            ft.Container(
                width=72,
                alignment=ft.Alignment(-1, 0),
                content=ft.Text(cabin_class_label(row["cabin"]) if row["cabin"] != last_cabin else "", size=10, weight=ft.FontWeight.W_800, color=tokens["muted"]),
            ),
            ft.Container(
                width=34,
                alignment=ft.Alignment(1, 0),
                content=ft.Text(f"{row['row']:02d}", size=10, weight=ft.FontWeight.W_800, color=tokens["muted"]),
            ),
        ]
        existing = set(row["existing_seats"])
        for block_index, group in enumerate(row["groups"]):
            for letter in group:
                if letter in existing:
                    seat_id = f"{row['deck_prefix']}{row['row']:02d}{letter}" if row.get("deck_prefix") else f"{row['row']}{letter}"
                    seat = {
                        "id": seat_id,
                        "row": row["row"],
                        "label": letter,
                        "cabin": row["cabin"],
                        "occupied": False,
                        "deck": row.get("deck", ""),
                    }
                    seat_model["seats"].append(seat)
                    row_controls.append(build_seat_control_small(seat))
                else:
                    row_controls.append(ft.Container(width=24, height=24, border_radius=7, bgcolor="#2A3034", border=ft.border.all(1, ft.Colors.with_opacity(0.5, tokens["card_border"]))))
            if block_index < len(row["groups"]) - 1:
                row_controls.append(ft.Container(width=34, height=24))
        return ft.Row(spacing=6, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=row_controls)

    def build_cabin_body_panel(rows: List[Dict], title: str = "Main Deck") -> ft.Control:
        controls = []
        last_cabin = None
        for row in rows:
            controls.append(build_seat_row_visual(row, last_cabin))
            last_cabin = row["cabin"]
        if not controls:
            controls = [ft.Text("No cabin rows generated.", color=tokens["muted"])]
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=18, vertical=16),
            border_radius=22,
            bgcolor="#151A1D",
            border=ft.border.all(1, "#2B343A"),
            content=ft.Column(
                spacing=10,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(title, size=16, weight=ft.FontWeight.W_800, color=tokens["text"]),
                            ft.Text("Click seats to toggle passenger fill", size=11, color=tokens["muted"]),
                        ],
                    ),
                    ft.Divider(height=8, opacity=0.10),
                    ft.Column(spacing=8, controls=controls),
                ],
            ),
        )

    def build_cabin_legend() -> ft.Control:
        legend_items = []
        for cabin in CABIN_ORDER:
            legend_items.append(
                ft.Row(
                    spacing=10,
                    controls=[
                        ft.Container(width=24, height=24, border_radius=7, bgcolor=CABIN_COLORS[cabin], border=ft.border.all(1, "#D7DEE6")),
                        ft.Text(cabin, size=11, color=tokens["muted"], weight=ft.FontWeight.W_600),
                    ],
                )
            )
        legend_items.append(
            ft.Row(
                spacing=10,
                controls=[
                    ft.Container(width=24, height=24, border_radius=7, bgcolor=tokens["accent"], border=ft.border.all(1, tokens["accent"])),
                    ft.Text("Filled passenger seat", size=11, color=tokens["muted"], weight=ft.FontWeight.W_600),
                ],
            )
        )
        return ft.Container(
            width=320,
            padding=18,
            border_radius=22,
            bgcolor=tokens["subpanel"],
            border=ft.border.all(1, tokens["card_border"]),
            content=ft.Column(spacing=12, controls=[ft.Text("Legend", size=16, weight=ft.FontWeight.W_800, color=tokens["text"]), *legend_items]),
        )

    def build_passenger_load_panel(aircraft_name: str) -> ft.Control:
        capacity = {cabin: sum(1 for seat in seat_model.get("seats", []) if seat.get("cabin") == cabin) for cabin in CABIN_ORDER}
        occupied = {cabin: sum(1 for seat in seat_model.get("seats", []) if seat.get("cabin") == cabin and seat.get("occupied")) for cabin in CABIN_ORDER}
        total_capacity = sum(capacity.values())
        total_occupied = sum(occupied.values())
        payload_kg = total_occupied * STANDARD_PASSENGER_WEIGHT_KG
        load_factor = 0 if total_capacity == 0 else total_occupied / total_capacity * 100
        rows = []
        for cabin in CABIN_ORDER:
            rows.append(
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(cabin, size=11, color=tokens["muted"]),
                        ft.Text(f"{occupied[cabin]} / {capacity[cabin]}", size=11, color=tokens["text"], weight=ft.FontWeight.W_800),
                    ],
                )
            )
        return ft.Container(
            width=320,
            padding=18,
            border_radius=22,
            bgcolor=tokens["subpanel"],
            border=ft.border.all(1, tokens["card_border"]),
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Text("Passenger Load", size=16, weight=ft.FontWeight.W_800, color=tokens["text"]),
                    ft.Text(aircraft_name, size=11, color=tokens["muted"]),
                    *rows,
                    ft.Divider(height=8, opacity=0.12),
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Text("Passenger total", size=11, color=tokens["muted"]), ft.Text(f"{total_occupied} / {total_capacity}", size=12, color=tokens["text"], weight=ft.FontWeight.W_800)]),
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Text("Load factor", size=11, color=tokens["muted"]), ft.Text(f"{load_factor:.1f}%", size=12, color=tokens["accent"], weight=ft.FontWeight.W_800)]),
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Text("Passenger payload", size=11, color=tokens["muted"]), ft.Text(f"{payload_kg:,.0f} kg", size=12, color="#D88A42", weight=ft.FontWeight.W_800)]),
                ],
            ),
        )

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
            bgcolor=tokens["subpanel"],
            border=ft.border.all(1, tokens["card_border"]),
            content=ft.Column(spacing=14, controls=[
                ft.Text("Cabin Distribution", size=16, weight=ft.FontWeight.W_800, color=tokens["text"]),
                ft.Row(spacing=0, controls=bar_segments or [ft.Container(height=18, expand=1, bgcolor=tokens["card_border"])]),
                ft.Row(wrap=True, spacing=18, run_spacing=10, controls=stat_controls),
            ]),
        )

    def build_digital_seat_map(airline_name: str, aircraft_name: str, counts: Dict[str, int], preset: Dict) -> ft.Control:
        seat_model["seats"] = []
        seat_model["seat_controls"] = {}

        def seat_dashboard_metric(label: str, value: str, subtitle: str = "") -> ft.Control:
            return ft.Container(
                width=150,
                height=90,
                padding=12,
                border_radius=18,
                bgcolor=tokens["subpanel"],
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    spacing=4,
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.Text(label, size=10, color=tokens["muted"]),
                        ft.Text(value, size=18, weight=ft.FontWeight.W_800, color=tokens["text"]),
                        ft.Text(subtitle, size=9, color=tokens["muted"]),
                    ],
                ),
            )

        header = ft.Row(
            alignment=ft.MainAxisAlignment.START,
            controls=[
                ft.Row(spacing=12, controls=[
                    seat_dashboard_metric("Capacity", f"{sum(counts.values())}", "configured seats"),
                    seat_dashboard_metric("Filled", "0", "passengers"),
                    seat_dashboard_metric("Payload", "0 kg", "passenger weight"),
                ]),
            ],
        )

        def side_payload_card(title: str, controls: List[ft.Control], bg_key: Optional[str] = None) -> ft.Control:
            background_src = card_background_src(bg_key) if bg_key else None
            return ft.Container(
                width=320,
                padding=16,
                border_radius=22,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                bgcolor=ft.Colors.TRANSPARENT if background_src else tokens["subpanel"],
                border=ft.border.all(1, tokens["card_border"]),
                image=ft.DecorationImage(src=background_src, fit=ft.BoxFit.COVER, opacity=0.26) if background_src else None,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text(title, size=16, weight=ft.FontWeight.W_800, color=tokens["text"]),
                        ft.Divider(height=8, opacity=0.12),
                        *controls,
                    ],
                ),
            )

        def calculate_seat_baggage(e):
            occupied = sum(1 for seat in seat_model.get("seats", []) if seat.get("occupied"))
            bag_pax_tf.value = str(occupied)
            do_baggage_calc(e)

        def reset_seat_baggage(e):
            reset_baggage_form(e)
            occupied = sum(1 for seat in seat_model.get("seats", []) if seat.get("occupied"))
            bag_pax_tf.value = str(occupied)
            page.update()

        bag_pax_tf.read_only = True
        bag_pax_tf.label = "Filled passengers"
        bag_pax_tf.width = 250
        bag_carry_on_tf.width = 250
        bag_checked_kg_per_pax_tf.width = 250
        cargo_weight_tf.width = 250
        bag_pax_tf.value = "0"

        if aircraft_name == "Airbus A380-800":
            upper_counts = {"First": counts.get("First", 0), "Business": counts.get("Business", 0), "Premium Economy": counts.get("Premium Economy", 0), "Economy": 0}
            lower_counts = {"First": 0, "Business": 0, "Premium Economy": 0, "Economy": counts.get("Economy", 0)}
            upper_rows = build_digital_seat_rows(upper_counts, preset, start_row=0, deck_prefix="U", deck_label="Upper Deck")
            lower_rows = build_digital_seat_rows(lower_counts, preset, start_row=49, deck_prefix="L", deck_label="Lower Deck")
            cabin_body = ft.Row(
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Container(expand=1, content=build_cabin_body_panel(upper_rows, "Upper Deck")),
                    ft.Container(expand=1, content=build_cabin_body_panel(lower_rows, "Lower Deck")),
                ],
            )
        else:
            rows = build_digital_seat_rows(counts, preset, start_row=0)
            cabin_body = build_cabin_body_panel(rows, "Main Deck")
        seat_passenger_load_host.content = build_passenger_load_panel(aircraft_name)
        side_panel = ft.Column(
            spacing=14,
            controls=[
                build_cabin_legend(),
                seat_passenger_load_host,
                side_payload_card(
                    "Baggage",
                    [
                        ft.Text("Passenger count follows filled seats.", size=12, color=tokens["muted"]),
                        bag_pax_tf,
                        bag_carry_on_tf,
                        bag_checked_kg_per_pax_tf,
                        ft.Row(
                            wrap=True,
                            spacing=10,
                            controls=[
                                ft.ElevatedButton("Calculate", on_click=calculate_seat_baggage, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                                ft.OutlinedButton("Reset", on_click=reset_seat_baggage),
                            ],
                        ),
                        bag_status_text,
                    ],
                    "baggage",
                ),
                side_payload_card(
                    "Cargo",
                    [
                        ft.Text("Extra hold cargo added to baggage payload.", size=12, color=tokens["muted"]),
                        cargo_weight_tf,
                    ],
                    "cargo",
                ),
                side_payload_card(
                    "Calculated Weight",
                    [
                        bag_baggage_weight_summary_text,
                        bag_cargo_weight_summary_text,
                        ft.Divider(height=8, opacity=0.12),
                        bag_payload_weight_summary_text,
                        ft.Container(
                            padding=12,
                            border_radius=14,
                            bgcolor=tokens["subpanel"],
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
                    "calculated_weight",
                ),
            ],
        )
        return ft.Column(
            spacing=18,
            controls=[
                ft.Row(
                    spacing=18,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[ft.Container(expand=1, content=cabin_body), side_panel],
                ),
            ],
        )

    def build_seat_legend(counts: Dict[str, int]) -> ft.Control:
        return ft.Row(
            wrap=True,
            spacing=10,
            controls=[
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    border_radius=999,
                    bgcolor=ft.Colors.with_opacity(0.14, CABIN_COLORS[cabin]),
                    content=ft.Text(cabin, size=11, weight=ft.FontWeight.W_700, color=tokens["text"]),
                )
                for cabin in CABIN_ORDER if counts.get(cabin, 0) > 0
            ] + [
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    border_radius=999,
                    bgcolor=ft.Colors.with_opacity(0.14, tokens["accent"]),
                    content=ft.Text("Occupied", size=11, weight=ft.FontWeight.W_700, color=tokens["text"]),
                )
            ],
        )

    def build_seat_sections(counts: Dict[str, int], preset: Dict, start_row: int = 1, deck_prefix: str = "", deck_label: str = ""):
        section_controls = []
        current_row = start_row

        for cabin in CABIN_ORDER:
            cabin_total = counts.get(cabin, 0)
            layout = preset.get("layouts", {}).get(cabin)
            if cabin == "First" and cabin_total > 0 and not layout:
                layout = [1, 2, 1]
            if cabin_total <= 0 or not layout:
                continue

            seats_per_row = sum(layout)
            row_plan = build_row_seat_plan(cabin_total, seats_per_row)
            letter_blocks = layout_letter_blocks(layout)

            section_controls.append(
                ft.Container(
                    margin=ft.margin.only(top=4, bottom=4),
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=14,
                    bgcolor=ft.Colors.with_opacity(0.12, CABIN_COLORS.get(cabin, tokens["accent"])),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(cabin, weight=ft.FontWeight.W_700, color=tokens["text"]),
                            ft.Text(
                                f"{cabin_total} seats • layout {'-'.join(str(x) for x in layout)}",
                                size=11,
                                color=tokens["muted"],
                            ),
                        ],
                    ),
                )
            )

            for row_seat_count in row_plan:
                row_controls = [
                    ft.Container(
                        width=42,
                        alignment=ft.Alignment(1, 0),
                        content=ft.Text(f"{current_row:02d}", weight=ft.FontWeight.W_700, color=tokens["text"]),
                    )
                ]
                block_allocations = distribute_seats_across_blocks(layout, row_seat_count)

                for block_index, active_count in enumerate(block_allocations):
                    visible_letters = choose_letters_for_block(
                        letter_blocks[block_index],
                        active_count,
                        block_index,
                        len(layout),
                    )

                    for letter in visible_letters:
                        seat = {
                            "id": f"{deck_prefix}{current_row:02d}{letter}" if deck_prefix else f"{current_row}{letter}",
                            "row": current_row,
                            "label": letter,
                            "cabin": cabin,
                            "occupied": False,
                            "deck": deck_label,
                        }
                        seat_model["seats"].append(seat)
                        row_controls.append(build_seat_control(seat))

                    if block_index < len(layout) - 1:
                        row_controls.append(make_aisle_gap())

                section_controls.append(
                    ft.Row(
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=row_controls,
                    )
                )
                current_row = next_seat_row_number(current_row)

            section_controls.append(ft.Divider(height=10, opacity=0.08))

        if not section_controls:
            section_controls = [ft.Text("No cabins configured on this deck.", size=12, color=tokens["muted"])]
        return section_controls, current_row


    def build_deck_panel(deck_name: str, counts: Dict[str, int], preset: Dict, start_row: int, deck_prefix: str) -> ft.Control:
        deck_sections, _ = build_seat_sections(counts, preset, start_row=start_row, deck_prefix=deck_prefix, deck_label=deck_name)
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=18, vertical=14),
            border_radius=20,
            border=ft.border.all(1, tokens["card_border"]),
            bgcolor=tokens["subpanel"],
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Text(deck_name, size=16, weight=ft.FontWeight.W_800, color=tokens["text"]),
                    ft.Divider(height=8, opacity=0.08),
                    *deck_sections,
                ],
            ),
        )

    def generate_seat_map(e):
        try:
            first_count = max(0, int((seat_first_tf.value or "0").strip()))
            business_count = max(0, int((seat_business_tf.value or "0").strip()))
            premium_count = max(0, int((seat_premium_tf.value or "0").strip()))
            economy_count = max(0, int((seat_economy_tf.value or "0").strip()))
        except Exception:
            seat_status_text.value = "Seat counts must be whole numbers."
            page.update()
            return

        airline_name = state.airline or "Generic"
        aircraft_name = canonical_aircraft_name(state.aircraft) or state.aircraft or ""
        if not aircraft_name:
            seat_status_text.value = "Select an aircraft on the Home page first."
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
        seat_model["seats"] = []
        seat_model["seat_controls"] = {}
        seat_model["totals"] = counts.copy()

        seat_map_host.content = glass_card_with_background(
            "Seat Map",
            build_digital_seat_map(airline_name, aircraft_name, counts, preset),
            bg_key="seat_map",
        )

        seat_summary_title.value = f"{aircraft_name} seat map generated"
        if aircraft_name == "Airbus A380-800":
            seat_status_text.value = "A380 double-deck map generated. Upper deck is on the left. Lower deck is on the right."
        else:
            seat_status_text.value = "Seat map generated. Click seats or use the auto-fill controls below."
        seat_fill_first_tf.value = str(first_count if first_count <= 8 else 0)
        seat_fill_business_tf.value = "0"
        seat_fill_premium_tf.value = "0"
        seat_fill_economy_tf.value = "0"
        update_seat_summary(update_page=False)
        refresh_seat_widget_styles(update_page=False)
        page.update()

    def clear_seat_occupancy(e):
        if not seat_model.get("generated"):
            seat_status_text.value = "Generate a seat map first."
            page.update()
            return
        for seat in seat_model.get("seats", []):
            seat["occupied"] = False
            refs = seat_model.get("seat_controls", {}).get(seat["id"])
            if refs:
                container, text = refs
                container.bgcolor = seat_available_color(seat["cabin"], False)
                text.color = seat_text_color(seat["cabin"], False)
        seat_status_text.value = "All seat occupancy has been cleared."
        update_seat_summary(update_page=False)
        page.update()

    def auto_fill_seats(e):
        if not seat_model.get("generated"):
            seat_status_text.value = "Generate a seat map first."
            page.update()
            return

        try:
            requested = {
                "First": max(0, int((seat_fill_first_tf.value or "0").strip())),
                "Business": max(0, int((seat_fill_business_tf.value or "0").strip())),
                "Premium Economy": max(0, int((seat_fill_premium_tf.value or "0").strip())),
                "Economy": max(0, int((seat_fill_economy_tf.value or "0").strip())),
            }
        except Exception:
            seat_status_text.value = "Passenger fill values must be whole numbers."
            page.update()
            return

        available_by_cabin = {
            cabin: sum(1 for seat in seat_model.get("seats", []) if seat.get("cabin") == cabin)
            for cabin in CABIN_ORDER
        }
        for cabin, requested_count in requested.items():
            if requested_count > available_by_cabin.get(cabin, 0):
                seat_status_text.value = f"{cabin} fill exceeds the configured seat count."
                page.update()
                return

        for seat in seat_model.get("seats", []):
            seat["occupied"] = False

        for cabin in CABIN_ORDER:
            remaining = requested.get(cabin, 0)
            for seat in seat_model.get("seats", []):
                if seat.get("cabin") == cabin and remaining > 0:
                    seat["occupied"] = True
                    remaining -= 1

        for seat in seat_model.get("seats", []):
            refs = seat_model.get("seat_controls", {}).get(seat["id"])
            if refs:
                container, text = refs
                container.bgcolor = seat_available_color(seat["cabin"], seat["occupied"])
                text.color = seat_text_color(seat["cabin"], seat["occupied"])

        seat_status_text.value = "Seats filled from your passenger counts."
        update_seat_summary(update_page=False)
        page.update()

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
    cal_airline_dd.on_change = lambda e: (populate_calendar_aircraft_dropdown(e.control.value), page.update())
    log_sort_dd.on_change = lambda e: refresh_ui()
    cal_sort_dd.on_change = lambda e: refresh_ui()
    cal_status_filter_dd.on_change = lambda e: refresh_ui()
    populate_calendar_aircraft_dropdown(state.airline, canonical_aircraft_name(state.aircraft) or state.aircraft)
    populate_seat_aircraft_dropdown(state.airline, canonical_aircraft_name(state.aircraft) or state.aircraft)
    apply_seat_template_defaults(seat_aircraft_dd.value)

    def reset_calendar_form():
        state.calendar_editing_id = None
        state.calendar_selected_date = ""
        cal_date_tf.value = ""
        cal_time_tf.value = ""
        cal_airline_dd.value = state.airline or None
        populate_calendar_aircraft_dropdown(state.airline, canonical_aircraft_name(state.aircraft) or state.aircraft)
        cal_origin_tf.value = ""
        cal_destination_tf.value = ""
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

    def flight_hibernation_elapsed_seconds() -> float:
        if (
            bool(getattr(state, "overview_progress_running", False))
            and isinstance(getattr(state, "overview_takeoff_start_timestamp", None), (int, float))
        ):
            return max(0.0, time.time() - float(state.overview_takeoff_start_timestamp))
        return 0.0

    def flight_hibernation_summary() -> Dict[str, object]:
        route = f"{(state.departure or takeoff_departure_icao_tf.value or 'ORIGIN').strip().upper()} -> {(state.arrival or landing_arrival_icao_tf.value or 'DESTINATION').strip().upper()}"
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
        state.flight_number = ""
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
        state.overview_flight_time_minutes = 120
        state.overview_takeoff_start_timestamp = None
        state.overview_locked_eta_timestamp = None
        state.overview_progress_running = False
        state.overview_calendar_completion_key = ""
        state.flight_hibernation_menu_open = False
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
        bag_carry_on_tf.value = ""
        bag_category_dd.value = "Within the European region"
        apply_baggage_category_default()
        cargo_weight_tf.value = "0"
        bag_two_bag_percent_tf.value = "25"
        bag_per_bag_kg_tf.value = "23"
        refresh_baggage_mode_ui(update_page=False)
        reset_baggage_result_display()
        bag_status_text.value = "Enter values and click Calculate."
        bag_status_text.color = "#FF8080" if page.theme_mode == ft.ThemeMode.DARK else "#B3261E"

        seat_airline_dd.value = None
        seat_aircraft_dd.value = None
        for control in (
            seat_first_tf,
            seat_business_tf,
            seat_premium_tf,
            seat_economy_tf,
            seat_fill_first_tf,
            seat_fill_business_tf,
            seat_fill_premium_tf,
            seat_fill_economy_tf,
        ):
            control.value = "0"
        seat_model.clear()
        seat_model.update(
            {
                "generated": False,
                "airline": "",
                "aircraft": "",
                "template": get_aircraft_seat_preset(""),
                "seats": [],
                "seat_controls": {},
                "totals": {},
            }
        )
        seat_status_text.value = "Select airline, aircraft, and seat counts. Then generate the map."
        seat_summary_title.value = "No seat map generated yet."
        seat_total_stat.value = "Total seats: â€”"
        seat_occupied_stat.value = "Occupied seats: â€”"
        seat_available_stat.value = "Available seats: â€”"
        seat_breakdown_stat.value = "Breakdown: â€”"
        seat_map_host.content = glass_card_with_background(
            "Seat Map",
            ft.Text("Generate a seat map to see the cabin overview here.", color=tokens["muted"]),
            bg_key="seat_map",
        )
        seat_passenger_load_host.content = ft.Container()

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
            "flight_number",
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
            "overview_elapsed_seconds": flight_hibernation_elapsed_seconds(),
            "controls": controls_payload,
            "seat_model": json_safe_value(seat_model),
        }
        try:
            flight_hibernation_storage_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            state.flight_hibernation_menu_open = False
            show_snack("Flight hibernation saved. You can restore it after the next login.")
            refresh_ui()
        except Exception as ex:
            state.flight_hibernation_menu_open = False
            show_snack(f"Could not save flight hibernation: {ex}")

    def restore_flight_hibernation_payload(payload: dict):
        saved_state = payload.get("state", {}) if isinstance(payload, dict) else {}
        if isinstance(saved_state, dict):
            for key, value in saved_state.items():
                if hasattr(state, key):
                    setattr(state, key, value)

        if state.airline:
            register_custom_airline(state.airline)
        state.aircraft = canonical_aircraft_name(state.aircraft) or state.aircraft

        controls_payload = payload.get("controls", {}) if isinstance(payload, dict) else {}
        if isinstance(controls_payload, dict):
            airline_value = str(controls_payload.get("airline") or state.airline or "").strip()
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
        if isinstance(saved_seat_model, dict):
            seat_model.clear()
            seat_model.update(saved_seat_model)
            seat_model["seat_controls"] = {}

        state.departure = normalize_airport_code(state.departure or takeoff_departure_icao_tf.value) or (state.departure or "")
        state.arrival = normalize_airport_code(state.arrival or landing_arrival_icao_tf.value) or (state.arrival or "")
        state.departure_gate = takeoff_gate_tf.value or state.departure_gate
        state.arrival_gate = landing_gate_tf.value or state.arrival_gate
        state.departure_terminal = takeoff_terminal_tf.value or state.departure_terminal
        state.arrival_terminal = landing_terminal_tf.value or state.arrival_terminal

        elapsed_seconds = payload.get("overview_elapsed_seconds", 0) if isinstance(payload, dict) else 0
        try:
            elapsed_seconds = max(0.0, float(elapsed_seconds or 0.0))
        except Exception:
            elapsed_seconds = 0.0
        if bool(getattr(state, "overview_progress_running", False)):
            duration_seconds = max(60, int(getattr(state, "overview_flight_time_minutes", 120) or 120) * 60)
            elapsed_seconds = min(elapsed_seconds, float(duration_seconds))
            state.overview_takeoff_start_timestamp = time.time() - elapsed_seconds
            state.overview_locked_eta_timestamp = time.time() + max(0.0, float(duration_seconds) - elapsed_seconds)
        elif int(getattr(state, "overview_flight_status_index", 0) or 0) >= 5:
            duration_seconds = max(60, int(getattr(state, "overview_flight_time_minutes", 120) or 120) * 60)
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
        show_snack("Saved hibernation cleared. Starting a new flight.")

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
            bgcolor=ft.Colors.with_opacity(0.92, tokens["panel"]),
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
                        "A hibernated flight was found. Continue exactly where you left off, or clear it and start fresh.",
                        size=12,
                        color=tokens["muted"],
                    ),
                    ft.Container(
                        padding=16,
                        border_radius=18,
                        bgcolor=ft.Colors.with_opacity(0.40, tokens["subpanel"]),
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
                            ft.OutlinedButton("Start New Flight", on_click=lambda e: start_new_after_hibernation_prompt()),
                            ft.ElevatedButton(
                                "Continue Previous Flight",
                                on_click=lambda e, saved_payload=payload: continue_previous_flight(saved_payload),
                                bgcolor=tokens["accent"],
                                color=ft.Colors.WHITE,
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
        planned_minutes = int(getattr(state, "overview_flight_time_minutes", 120) or 120)
        elapsed_minutes = planned_minutes
        if isinstance(getattr(state, "overview_takeoff_start_timestamp", None), (int, float)):
            elapsed_minutes = int(max(0.0, time.time() - float(state.overview_takeoff_start_timestamp)) / 60.0)
            elapsed_minutes = min(max(0, elapsed_minutes), max(1, planned_minutes))
        elif int(getattr(state, "overview_flight_status_index", 0) or 0) < 5:
            elapsed_minutes = 0

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
            "route": f"{origin or 'ORIGIN'} -> {destination or 'DESTINATION'}",
            "origin": origin or "—",
            "destination": destination or "—",
            "airline": state.airline or "No airline selected",
            "aircraft": state.aircraft or takeoff_aircraft_dd.value or "No aircraft selected",
            "flight_number": state.flight_number or "—",
            "distance": f"{distance_value:.0f} NM" if distance_value else "—",
            "planned_time": format_hours_to_hm(planned_minutes / 60.0),
            "elapsed_time": format_hours_to_hm(elapsed_minutes / 60.0) if elapsed_minutes > 0 else "Not started",
            "progress": f"{min(100, max(0, round((elapsed_minutes / max(1, planned_minutes)) * 100)))}%",
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
            bgcolor=ft.Colors.with_opacity(0.34, tokens["subpanel"]),
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
            "flight_time": str(summary.get("planned_time") or format_hours_to_hm(float(state.overview_flight_time_minutes or 120) / 60.0)),
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

        if existing_entry is None:
            existing_entry = {
                "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                "notes": completion_note,
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
        state.overview_flight_status_index = 6
        state.flight_status = "Flight ended"
        state.flight_hibernation_menu_open = False
        clear_flight_hibernation_save()
        flight_end_summary_modal.visible = False
        refresh_ui()
        show_snack(f"Flight ended, {calendar_action} in Calendar, and marked completed.")

    def show_flight_end_summary(e=None):
        state.flight_hibernation_menu_open = False
        summary = flight_end_summary_values()
        flight_end_summary_modal.content = ft.Container(
            width=720,
            padding=24,
            border_radius=30,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=ft.Colors.with_opacity(0.90, tokens["panel"]),
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
                        wrap=True,
                        spacing=12,
                        run_spacing=12,
                        controls=[
                            flight_end_summary_tile("Origin", str(summary["origin"]), f"T{summary['departure_terminal']} / Gate {summary['departure_gate']}"),
                            flight_end_summary_tile("Destination", str(summary["destination"]), f"T{summary['arrival_terminal']} / Gate {summary['arrival_gate']}"),
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
                            flight_end_summary_tile("Origin", str(summary["origin"]), f"T{summary['departure_terminal']} • Gate {summary['departure_gate']}"),
                            flight_end_summary_tile("Destination", str(summary["destination"]), f"T{summary['arrival_terminal']} • Gate {summary['arrival_gate']}"),
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
                            ft.ElevatedButton("End Flight", bgcolor=tokens["accent"], color=ft.Colors.WHITE, on_click=finish_current_flight),
                        ],
                    ),
                ],
            ),
        )
        flight_end_summary_modal.visible = True
        page.update()

    def refresh_ui():
        nonlocal ui_refresh_in_progress
        if ui_refresh_in_progress:
            return
        ui_refresh_in_progress = True
        try:
            apply_theme()
            page.bgcolor = ft.Colors.BLACK
            root_host.bgcolor = ft.Colors.TRANSPARENT
            sync_input_colors()
            refresh_header_texts()
            refresh_airport_background_preloader(update_page=False)
            airline_dd.value = state.airline or None
            theme_toggle.value = page.theme_mode == ft.ThemeMode.DARK
            if state.selected_tab_index < 0:
                state.selected_tab_index = 0
            if state.selected_tab_index > 12:
                state.selected_tab_index = 12
            if (not state.is_logged_in) or state.selected_tab_index != 0:
                close_overview_globe_webview()
            root_host.content = login_page() if not state.is_logged_in else app_shell()
            page.update()
        finally:
            ui_refresh_in_progress = False

    def apply_selected_airline(force_refresh: bool = False):
        selected_value = (airline_dd.value or state.airline or "").strip()

        state.airline = selected_value
        airline_dd.value = selected_value or None
        state.logo_refresh_nonce += 1
        clear_asset_lookup_caches()
        state.flight_status = derive_idle_status()

        if seat_airline_dd.value != (selected_value or None):
            seat_airline_dd.value = selected_value or None
        populate_seat_aircraft_dropdown(selected_value, state.aircraft)

        if cal_airline_dd.value != (selected_value or None):
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
        airline_dd.value = value or None
        state.airline = value or ""
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
            bgcolor=tokens["panel"],
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
            bgcolor=tokens["panel"],
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

    async def complete_login_after_transition():
        await asyncio.sleep(3.0)
        state.is_logged_in = True
        state.login_transition_active = False
        state.login_transition_progress = 0.0
        refresh_ui()
        show_flight_hibernation_prompt()

    def do_login(e):
        username = (username_tf.value or "").strip()
        password = (password_tf.value or "").strip()
        if not username or not password:
            login_error.value = "Enter ID and password."
            page.update()
            return

        if bool(getattr(state, "login_transition_active", False)):
            return

        login_error.value = ""
        state.pilot_name = username
        state.selected_tab_index = 1
        state.flight_hibernation_prompt_seen = False
        state.flight_hibernation_menu_open = False

        # Start the client-side swipe-up state immediately.
        play_login_transition_audio()
        state.login_transition_active = True
        state.login_transition_progress = 1.0
        refresh_ui()

        try:
            page.run_task(complete_login_after_transition)
        except Exception:
            # Fallback: still allow login if this Flet build cannot schedule tasks.
            time.sleep(0.35)
            state.is_logged_in = True
            state.login_transition_active = False
            state.login_transition_progress = 0.0
            refresh_ui()
            show_flight_hibernation_prompt()

    password_tf.on_submit = do_login

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

    def close_mapcn_webview(wait: bool = False):
        process = getattr(state, "mapcn_webview_process", None)
        if process is None:
            setattr(state, "mapcn_webview_url", None)
            return
        setattr(state, "mapcn_webview_process", None)
        setattr(state, "mapcn_webview_url", None)

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

    def do_logout(e):
        close_overview_globe_webview(wait=True)
        close_mapcn_webview(wait=True)
        state.is_logged_in = True
        state.pilot_name = "User"
        state.selected_tab_index = 1
        state.login_intro_started = False
        state.login_transition_active = False
        state.login_transition_progress = 0.0
        state.flight_hibernation_prompt_seen = False
        state.flight_hibernation_menu_open = False
        password_tf.value = ""
        login_error.value = ""
        refresh_ui()

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
        close_mapcn_webview(wait=True)
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

    tray_enabled = start_windows_tray()
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
        apply_takeoff_departure_state(update_page=False, fill_elevation=True)
        sync_route_distance_from_state(update_page=False)
        page.update()

    takeoff_aircraft_dd.on_change = on_takeoff_aircraft_changed
    takeoff_aircraft_dd.on_blur = on_takeoff_aircraft_changed
    # Do not update/uppercase on every key press. It can make the field lose focus.
    takeoff_departure_icao_tf.on_blur = on_takeoff_departure_changed
    takeoff_departure_icao_tf.on_submit = on_takeoff_departure_changed
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
            elif not (takeoff_route_distance_tf.value or "").strip():
                takeoff_route_distance_tf.value = ""

        if update_page:
            page.update()
        return route_nm

    def apply_takeoff_route_distance_override(e=None):
        sync_route_distance_from_state(update_page=False, overwrite_field=False)
        raw = (takeoff_route_distance_tf.value or "").strip()
        route_key = active_route_distance_key()

        if not raw:
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

        if manual_nm <= 0:
            takeoff_fuel_status_text.value = "Route distance must be greater than zero."
            page.update()
            return

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
        aircraft_name = canonical_aircraft_name(takeoff_aircraft_dd.value or state.aircraft)
        route_origin = (state.departure or takeoff_departure_icao_tf.value or "").strip().upper()
        route_destination = (state.arrival or landing_arrival_icao_tf.value or "").strip().upper()
        route_label = f"{route_origin} → {route_destination}" if route_origin and route_destination else "Set departure and destination"
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

        if route_distance <= 0:
            takeoff_fuel_status_text.value = 'Enter a route distance greater than zero.'
            takeoff_trip_fuel_text.value = 'Base trip fuel: —'
            takeoff_block_fuel_text.value = 'Planned fuel: —'
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

        state.takeoff_last_result['fuel_plan'] = {
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

        if estimated_tow_kg > 0:
            takeoff_zfw_tf.value = f"{estimated_zfw_kg:.0f}"

        takeoff_trip_fuel_text.value = (
            f"Base trip fuel: {plan.base_trip_fuel_l:,.0f} L • {plan.base_trip_fuel_kg:,.0f} kg | "
            f"Corrected: {plan.corrected_trip_fuel_l:,.0f} L • {plan.corrected_trip_fuel_kg:,.0f} kg"
        )
        takeoff_block_fuel_text.value = (
            f"Planned fuel: {plan.planned_fuel_l:,.0f} L • {plan.planned_fuel_kg:,.0f} kg | "
            f"Margin: {plan.planning_margin_l:,.0f} L • {plan.planning_margin_kg:,.0f} kg | "
            f"Fuel capacity: {plan.fuel_capacity_l:,.0f} L • {plan.fuel_capacity_kg:,.0f} kg"
        )
        takeoff_ete_text.value = f"Flight time: {int(plan.ete_hours)}h {int(round((plan.ete_hours % 1) * 60)):02d}m • Effective distance {plan.effective_distance_nmi:,.0f} NM"
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

    def do_fetch_takeoff_metar(e):
        icao = (takeoff_departure_icao_tf.value or "").strip().upper()
        takeoff_departure_icao_tf.value = icao
        if not icao:
            takeoff_metar_status_text.value = "Enter a valid ICAO before fetching METAR."
            page.update()
            return
        takeoff_metar_status_text.value = f"Fetching METAR for {icao}..."
        page.update()
        metar = fetch_takeoff_metar(icao)
        if not metar:
            takeoff_metar_status_text.value = f"No METAR found for {icao}."
            takeoff_raw_metar_tf.value = ""
            apply_takeoff_departure_state(update_page=False, fill_elevation=True)
            refresh_airport_background_preloader(update_page=False)
            refresh_ui()
            return
        takeoff_oat_tf.value = f"{metar.temperature_c:.0f}"
        takeoff_qnh_tf.value = f"{metar.qnh_hpa:.1f}"
        takeoff_wind_dir_tf.value = str(metar.wind_dir_deg)
        takeoff_wind_speed_tf.value = str(metar.wind_speed_kt)
        takeoff_wind_gust_tf.value = str(metar.wind_gust_kt)
        if not (takeoff_runway_heading_tf.value or "").strip() or takeoff_runway_heading_tf.value == "0":
            takeoff_runway_heading_tf.value = str(metar.wind_dir_deg)
        takeoff_raw_metar_tf.value = metar.raw
        takeoff_metar_status_text.value = f"Updated from METAR for {icao}."
        apply_takeoff_departure_state(update_page=False, fill_elevation=True)
        state.flight_status = "METAR updated"
        refresh_airport_background_preloader(update_page=False)
        refresh_ui()

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
        state.takeoff_last_result = {
            "weight_kg": inputs.takeoff_weight_kg,
            "vr_kt": result.vr_kt,
            "v2_kt": result.v2_kt,
            "takeoff_distance_m": result.takeoff_distance_m,
        }
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
        takeoff_climb_initial_text.value = f"Initial: {result.climb_initial_fpm:,} fpm"
        takeoff_climb_enroute_text.value = f"Enroute: {result.climb_enroute_fpm:,} fpm"
        takeoff_climb_high_text.value = f"High Alt: {result.climb_high_alt_fpm:,} fpm"

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
        apply_landing_arrival_state(update_page=False, fill_elevation=True)
        sync_route_distance_from_state(update_page=False)
        page.update()

    landing_aircraft_dd.on_change = on_landing_aircraft_changed
    # Do not update/uppercase on every key press. It can make the field lose focus.
    landing_arrival_icao_tf.on_blur = on_landing_arrival_changed
    landing_arrival_icao_tf.on_submit = on_landing_arrival_changed
    landing_gate_tf.on_change = lambda e: setattr(state, "arrival_gate", (e.control.value or "").strip())
    landing_terminal_tf.on_change = lambda e: setattr(state, "arrival_terminal", (e.control.value or "").strip())
    populate_landing_aircraft_dropdown(state.airline, state.aircraft)
    reset_landing_form(update_page=False)

    def do_fetch_landing_metar(e):
        icao = (landing_arrival_icao_tf.value or "").strip().upper()
        landing_arrival_icao_tf.value = icao
        if not icao:
            landing_metar_status_text.value = "Enter a valid ICAO before fetching METAR."
            page.update()
            return
        landing_metar_status_text.value = f"Fetching METAR for {icao}..."
        page.update()
        metar = fetch_landing_metar(icao)
        if not metar:
            landing_metar_status_text.value = f"No METAR found for {icao}."
            landing_raw_metar_tf.value = ""
            apply_landing_arrival_state(update_page=False, fill_elevation=True)
            refresh_airport_background_preloader(update_page=False)
            refresh_ui()
            return
        landing_oat_tf.value = f"{metar.temperature_c:.0f}"
        landing_qnh_tf.value = f"{metar.qnh_hpa:.1f}"
        landing_wind_dir_tf.value = str(metar.wind_dir_deg)
        landing_wind_speed_tf.value = str(metar.wind_speed_kt)
        landing_wind_gust_tf.value = str(metar.wind_gust_kt)
        if not (landing_runway_heading_tf.value or "").strip() or landing_runway_heading_tf.value == "0":
            landing_runway_heading_tf.value = str(metar.wind_dir_deg)
        landing_raw_metar_tf.value = metar.raw
        landing_metar_status_text.value = f"Updated from METAR for {icao}."
        apply_landing_arrival_state(update_page=False, fill_elevation=True)
        state.flight_status = "Landing METAR updated"
        refresh_airport_background_preloader(update_page=False)
        refresh_ui()

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
        landing_vapp_text.value = f"Vapp: {result.vapp_kt} kt  •  Additive +{result.additive_kt} kt"
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
            bag_status_text.value = "Passenger count must be a whole number."
            page.update()
            return

        try:
            carry_on_kg = float((bag_carry_on_tf.value or "0").strip())
            if carry_on_kg < 0:
                raise ValueError
        except Exception:
            bag_status_text.value = "Carry-on mass per passenger must be a valid number."
            page.update()
            return

        try:
            cargo_kg = float((cargo_weight_tf.value or "0").strip())
            if cargo_kg < 0:
                raise ValueError
        except Exception:
            bag_status_text.value = "Cargo weight must be a valid number."
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
                bag_status_text.value = "Checked baggage kg per passenger must be a valid number."
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
            bag_status_text.value = "Baggage and cargo payload calculated."
        else:
            try:
                pct_two = float((bag_two_bag_percent_tf.value or "0").strip())
                if pct_two < 0 or pct_two > 100:
                    raise ValueError
            except Exception:
                bag_status_text.value = "Passengers with 2 checked bags must be a number from 0 to 100."
                page.update()
                return

            try:
                per_bag_kg = float((bag_per_bag_kg_tf.value or "0").strip())
                if per_bag_kg < 0:
                    raise ValueError
            except Exception:
                bag_status_text.value = "Mass per checked bag must be a valid number."
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
            bag_status_text.value = "Calculated in Allowance mode. Total shown on the right."

        bag_status_text.color = "#FF8080" if page.theme_mode == ft.ThemeMode.DARK else "#B3261E"
        page.update()

    def reset_baggage_form(e):
        bag_mode_dd.value = "Standard"
        bag_pax_tf.value = "0"
        bag_carry_on_tf.value = ""
        bag_category_dd.value = "Within the European region"
        apply_baggage_category_default()
        cargo_weight_tf.value = "0"
        bag_two_bag_percent_tf.value = "25"
        bag_per_bag_kg_tf.value = "23"
        refresh_baggage_mode_ui(update_page=False)
        reset_baggage_result_display()
        bag_status_text.value = "Enter values and click Calculate."
        bag_status_text.color = "#FF8080" if page.theme_mode == ft.ThemeMode.DARK else "#B3261E"
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
            cal_form_message.value = "Fill date, airline, aircraft, origin, destination, and flight time."
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
        refresh_ui()

    def load_calendar_entry_for_edit(entry_id: str):
        entry = next((item for item in state.calendar_entries if item.get("id") == entry_id), None)
        if not entry:
            return
        state.calendar_editing_id = entry_id
        cal_date_tf.value = entry.get("date", "")
        cal_time_tf.value = entry.get("time", "")
        cal_airline_dd.value = entry.get("airline", state.airline or "")
        populate_calendar_aircraft_dropdown(cal_airline_dd.value, entry.get("aircraft"))
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
        refresh_ui()

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
        refresh_ui()

    def clear_calendar_form(e):
        reset_calendar_form()
        page.update()

    def go_to_tab(index: int):
        new_index = max(0, min(12, int(index)))
        if state.selected_tab_index == new_index:
            return
        if state.selected_tab_index == 0 and new_index != 0:
            close_overview_globe_webview()
        if state.selected_tab_index == 6 and new_index != 6:
            close_mapcn_webview()
        state.selected_tab_index = new_index
        refresh_ui()

    def open_takeoff_fuel_section(e=None):
        state.selected_tab_index = 4
        refresh_ui()
        show_snack("Takeoff tab opened. Scroll to Fuel Planning.")

    def legacy_login_page():
        # Clean FMS cutout login rewrite.
        # The login screen is intentionally simple now:
        # Layer 1: pure black base
        # Layer 2: generated transparent FMS cutout image
        # Layer 3: login panel
        # Layer 4: transition aircraft
        #
        # Put the lower image visible inside FMS here:
        # C:\FMS\assets\backgrounds\login_fms_lower_bg.jpg

        refresh_login_background_preloader()

        def login_input_field(field: ft.TextField) -> ft.TextField:
            field.width = 360
            field.border_radius = 16
            field.filled = True
            field.bgcolor = "#000000"
            field.border_color = ft.Colors.with_opacity(0.28, ft.Colors.WHITE)
            field.focused_border_color = ft.Colors.with_opacity(0.85, ft.Colors.WHITE)
            field.color = ft.Colors.WHITE
            field.label_style = ft.TextStyle(color=ft.Colors.with_opacity(0.72, ft.Colors.WHITE))
            field.text_size = 14
            return field

        login_input_field(username_tf)
        login_input_field(password_tf)
        login_error.color = "#FFB4B4"
        login_error.size = 12

        def generated_fms_cutout_base64() -> Optional[str]:
            lower_bg_abs = login_fms_lower_background_abs_path()
            if not lower_bg_abs or not lower_bg_abs.exists():
                try:
                    print("FMS login cutout warning: lower background image not found. Expected assets/backgrounds/login_fms_lower_bg.jpg")
                except Exception:
                    pass
                return None

            try:
                from PIL import Image, ImageDraw, ImageFont
                import io
                import base64
            except Exception as ex:
                try:
                    print(f"FMS login cutout warning: Pillow is missing or unavailable: {ex}")
                except Exception:
                    pass
                return None

            try:
                canvas_w, canvas_h = 3500, 925
                bg = Image.open(lower_bg_abs).convert("RGB")
                bg_ratio = bg.width / max(1, bg.height)
                target_ratio = canvas_w / canvas_h
                if bg_ratio > target_ratio:
                    new_h = canvas_h
                    new_w = int(new_h * bg_ratio)
                else:
                    new_w = canvas_w
                    new_h = int(new_w / bg_ratio)
                bg_resized = bg.resize((new_w, new_h))
                crop_x = max(0, (new_w - canvas_w) // 2)
                crop_y = max(0, (new_h - canvas_h) // 2)
                bg_crop = bg_resized.crop((crop_x, crop_y, crop_x + canvas_w, crop_y + canvas_h)).convert("RGBA")

                font_candidates = [
                    Path(r"C:\Windows\Fonts\ariblk.ttf"),
                    Path(r"C:\Windows\Fonts\impact.ttf"),
                    Path(r"C:\Windows\Fonts\arialbd.ttf"),
                    Path(r"C:\Windows\Fonts\bahnschrift.ttf"),
                ]
                font_path = next((p for p in font_candidates if p.exists()), None)
                font = ImageFont.truetype(str(font_path), 750) if font_path else ImageFont.load_default()

                mask = Image.new("L", (canvas_w, canvas_h), 0)
                text_value = "FMS"

                tmp_w, tmp_h = 2600, 860
                temp = Image.new("L", (tmp_w, tmp_h), 0)
                temp_draw = ImageDraw.Draw(temp)
                bbox = temp_draw.textbbox((0, 0), text_value, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                temp_draw.text(
                    ((tmp_w - tw) // 2 - bbox[0], (tmp_h - th) // 2 - bbox[1] - 10),
                    text_value,
                    font=font,
                    fill=255,
                )

                stretch_w = int(tmp_w * 1.32)
                temp = temp.resize((stretch_w, tmp_h))
                x = (canvas_w - temp.width) // 2
                y = (canvas_h - temp.height) // 2
                mask.paste(temp, (x, y))

                output = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
                output.paste(bg_crop, (0, 0), mask)

                buffer = io.BytesIO()
                output.save(buffer, format="PNG")
                return base64.b64encode(buffer.getvalue()).decode("ascii")
            except Exception as ex:
                try:
                    print(f"FMS login cutout warning: cutout generation failed: {ex}")
                except Exception:
                    pass
                return None

        def fms_text_layer() -> ft.Control:
            cutout_base64 = generated_fms_cutout_base64()
            if cutout_base64:
                return ft.Container(
                    width=2600,
                    height=688,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Image(
                        src=f"data:image/png;base64,{cutout_base64}",
                        width=2600,
                        height=688,
                        fit=ft.BoxFit.CONTAIN,
                    ),
                )

            return ft.Container(
                width=2600,
                height=688,
                alignment=ft.Alignment(0, 0),
                content=ft.Text(
                    "FMS",
                    size=550,
                    weight=ft.FontWeight.W_900,
                    color=ft.Colors.with_opacity(0.28, ft.Colors.WHITE),
                    text_align=ft.TextAlign.CENTER,
                ),
            )

        login_form = ft.Container(
            width=440,
            height=330,
            padding=ft.padding.only(left=24, right=24, top=26, bottom=22),
            content=ft.Column(
                tight=True,
                spacing=14,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text(
                        "Enter your crew credentials to continue.",
                        size=12,
                        color=ft.Colors.with_opacity(0.72, ft.Colors.WHITE),
                        text_align=ft.TextAlign.CENTER,
                    ),
                    username_tf,
                    password_tf,
                    login_error,
                    ft.GestureDetector(
                        mouse_cursor=ft.MouseCursor.CLICK,
                        on_tap=do_login,
                        content=ft.Container(
                            width=360,
                            height=48,
                            margin=ft.margin.only(top=2),
                            alignment=ft.Alignment(0, 0),
                            border_radius=16,
                            bgcolor=ft.Colors.with_opacity(0.95, "#061A40"),
                            border=ft.border.all(1, ft.Colors.with_opacity(0.28, ft.Colors.WHITE)),
                            shadow=ft.BoxShadow(
                                blur_radius=18,
                                spread_radius=0,
                                color=ft.Colors.with_opacity(0.28, tokens["accent"]),
                                offset=ft.Offset(0, 7),
                            ),
                            content=ft.Text(
                                "Enter Dashboard",
                                size=14,
                                weight=ft.FontWeight.W_800,
                                color=ft.Colors.WHITE,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ),
                    ),
                ],
            ),
        )

        login_panel = ft.Container(
            width=440,
            height=330,
            border_radius=30,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=ft.Colors.BLACK,
            shadow=ft.BoxShadow(
                blur_radius=34,
                spread_radius=1,
                color=ft.Colors.with_opacity(0.45, ft.Colors.BLACK),
                offset=ft.Offset(0, 14),
            ),
            content=login_form,
        )

        hero_top_label = ft.Container(
            height=64,
            padding=ft.padding.only(left=42, right=42, top=18),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Row(
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(
                                width=34,
                                height=34,
                                border_radius=11,
                                alignment=ft.Alignment(0, 0),
                                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.WHITE),
                                border=ft.border.all(1, ft.Colors.with_opacity(0.22, ft.Colors.WHITE)),
                                content=ft.Icon(ft.Icons.FLIGHT_TAKEOFF, size=19, color=ft.Colors.WHITE),
                            ),
                            ft.Text(
                                "Flight Management Systems",
                                size=17,
                                weight=ft.FontWeight.W_700,
                                color=ft.Colors.with_opacity(0.90, ft.Colors.WHITE),
                            ),
                        ],
                    ),
                ],
            ),
        )

        login_layout = ft.Stack(
            expand=True,
            controls=[
                hero_top_label,
                ft.Container(
                    top=-18,
                    left=0,
                    right=0,
                    alignment=ft.Alignment(0, -1),
                    content=fms_text_layer(),
                ),
                ft.Container(
                    top=515,
                    left=0,
                    right=0,
                    alignment=ft.Alignment(0, -1),
                    content=login_panel,
                ),
            ],
        )

        transition_active = bool(getattr(state, "login_transition_active", False))
        login_transition_icon_src = (
            asset_rel_path_if_exists("icons/nav/login_transition_aircraft.png")
            or asset_rel_path_if_exists("icons/login_transition_aircraft.png")
            or asset_rel_path_if_exists("login_transition_aircraft.png")
        )

        viewport_height = int(getattr(page, "window_height", 820) or 820)
        transition_distance = viewport_height + 420
        login_slide_y = transition_distance if transition_active else 0
        aircraft_top = -360 if transition_active else viewport_height + 110
        transition_opacity = 1.0 if transition_active else 0.0

        try:
            transition_animation = ft.Animation(3000, ft.AnimationCurve.EASE_IN_OUT)
        except Exception:
            transition_animation = None

        login_layer_kwargs = dict(
            top=-login_slide_y,
            left=0,
            right=0,
            height=viewport_height,
            content=login_layout,
        )

        aircraft_layer_kwargs = dict(
            key="login_full_page_aircraft_transition",
            top=aircraft_top,
            left=0,
            right=0,
            height=320,
            opacity=transition_opacity,
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                tight=True,
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    (
                        ft.Image(
                            src=login_transition_icon_src,
                            width=116,
                            height=116,
                            fit=ft.BoxFit.CONTAIN,
                        )
                        if login_transition_icon_src
                        else ft.Icon(ft.Icons.FLIGHT_TAKEOFF, size=104, color=ft.Colors.WHITE)
                    ),
                ],
            ),
        )

        if transition_animation is not None:
            login_layer_kwargs["animate_position"] = transition_animation
            aircraft_layer_kwargs["animate_position"] = transition_animation

        login_content_layer = ft.Container(**login_layer_kwargs)
        transition_aircraft_layer = ft.Container(**aircraft_layer_kwargs)

        copyright_text = ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 1),
            padding=ft.padding.only(bottom=10),
            content=ft.Text(
                "© 2026 Flight Management Systems. All rights reserved.",
                size=11,
                color=ft.Colors.with_opacity(0.42, ft.Colors.WHITE),
                text_align=ft.TextAlign.CENTER,
            ),
        )

        return ft.Stack(
            expand=True,
            controls=[
                ft.Container(expand=True, bgcolor=ft.Colors.BLACK),
                copyright_text,
                login_content_layer,
                transition_aircraft_layer,
            ],
        )

    def login_page():
        field_animation = ft.Animation(260, ft.AnimationCurve.EASE_IN_OUT_CUBIC)
        reveal_animation = ft.Animation(760, ft.AnimationCurve.EASE_IN_OUT_CUBIC)

        def app_icon_png_src() -> Optional[str]:
            if bool(getattr(login_page, "_app_icon_loaded", False)):
                return getattr(login_page, "_app_icon_src", None)

            icon_src = None
            try:
                from PIL import Image
                import base64
                import io

                if runtime_icon.exists():
                    with Image.open(runtime_icon) as icon_image:
                        rgba = icon_image.convert("RGBA")
                        rgba.thumbnail((384, 384), Image.Resampling.LANCZOS)
                        buffer = io.BytesIO()
                        rgba.save(buffer, format="PNG")
                        icon_src = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"
            except Exception:
                icon_src = None

            login_page._app_icon_loaded = True
            login_page._app_icon_src = icon_src
            return icon_src

        def style_login_field(field: ft.TextField, hint_text: str):
            field.label = None
            field.hint_text = hint_text
            field.width = 342
            field.height = 58
            field.border = ft.InputBorder.NONE
            field.border_radius = 20
            field.filled = True
            field.bgcolor = ft.Colors.TRANSPARENT
            field.focused_bgcolor = ft.Colors.TRANSPARENT
            field.color = "#F7F8FA"
            field.cursor_color = ft.Colors.WHITE
            field.hint_style = ft.TextStyle(
                color=ft.Colors.with_opacity(0.76, ft.Colors.WHITE),
                size=15,
                weight=ft.FontWeight.W_500,
            )
            field.text_size = 15
            field.content_padding = ft.padding.only(left=18, right=16, top=10, bottom=10)

        style_login_field(username_tf, "Username")
        style_login_field(password_tf, "Password")
        username_tf.autofocus = False
        login_error.color = "#FFB7B7"
        login_error.size = 11
        login_error.height = 18
        login_error.text_align = ft.TextAlign.CENTER

        def active_slot_shadow():
            return ft.BoxShadow(
                blur_radius=20,
                spread_radius=0,
                color=ft.Colors.with_opacity(0.24, ft.Colors.BLACK),
                offset=ft.Offset(0, 8),
            )

        username_slot = ft.Container(
            width=350,
            height=60,
            border_radius=21,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=ft.Colors.with_opacity(0.16, ft.Colors.WHITE),
            border=ft.border.all(1, ft.Colors.with_opacity(0.58, ft.Colors.WHITE)),
            shadow=active_slot_shadow(),
            animate_size=field_animation,
            animate=field_animation,
            alignment=ft.Alignment(0, 0),
            content=username_tf,
        )
        password_slot = ft.Container(
            width=350,
            height=42,
            border_radius=18,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=ft.Colors.TRANSPARENT,
            border=ft.border.all(1, ft.Colors.TRANSPARENT),
            animate_size=field_animation,
            animate=field_animation,
            alignment=ft.Alignment(0, 0),
            content=password_tf,
        )

        active_field = {"value": "username"}

        def set_active_login_field(field_name: str):
            if field_name not in ("username", "password") or active_field["value"] == field_name:
                return
            active_field["value"] = field_name
            username_active = field_name == "username"

            for slot, is_active in ((username_slot, username_active), (password_slot, not username_active)):
                slot.height = 60 if is_active else 42
                slot.border_radius = 21 if is_active else 18
                slot.bgcolor = ft.Colors.with_opacity(0.16, ft.Colors.WHITE) if is_active else ft.Colors.TRANSPARENT
                slot.border = ft.border.all(
                    1,
                    ft.Colors.with_opacity(0.58, ft.Colors.WHITE) if is_active else ft.Colors.TRANSPARENT,
                )
                slot.shadow = active_slot_shadow() if is_active else None

            username_tf.height = 58 if username_active else 40
            password_tf.height = 58 if not username_active else 40
            username_tf.text_size = 15 if username_active else 13
            password_tf.text_size = 15 if not username_active else 13
            page.update()

        def hover_activates(field_name: str):
            def _handler(e):
                set_active_login_field(field_name)
            return _handler

        username_slot.on_hover = hover_activates("username")
        password_slot.on_hover = hover_activates("password")
        username_tf.on_focus = lambda e: set_active_login_field("username")
        password_tf.on_focus = lambda e: set_active_login_field("password")
        username_tf.on_click = lambda e: set_active_login_field("username")
        password_tf.on_click = lambda e: set_active_login_field("password")

        async def submit_username(e):
            set_active_login_field("password")
            try:
                await password_tf.focus()
            except Exception:
                pass

        username_tf.on_submit = submit_username
        password_tf.on_submit = do_login

        def google_login_placeholder(e=None):
            show_snack("Google sign-in is ready for its OAuth backend in the next phase.")

        credentials_panel = ft.Container(
            width=374,
            height=128,
            padding=ft.padding.all(10),
            border_radius=28,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=ft.Colors.with_opacity(0.13, ft.Colors.WHITE),
            border=ft.border.all(1, ft.Colors.with_opacity(0.30, ft.Colors.WHITE)),
            blur=ft.Blur(16, 16, ft.BlurTileMode.CLAMP),
            shadow=[
                ft.BoxShadow(
                    blur_radius=32,
                    spread_radius=0,
                    color=ft.Colors.with_opacity(0.52, ft.Colors.BLACK),
                    offset=ft.Offset(0, 16),
                ),
                ft.BoxShadow(
                    blur_radius=20,
                    spread_radius=0,
                    color=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                    offset=ft.Offset(0, -4),
                ),
            ],
            content=ft.Column(
                tight=True,
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[username_slot, password_slot],
            ),
        )

        sign_in_button = ft.Container(
            width=374,
            height=47,
            alignment=ft.Alignment(0, 0),
            border_radius=18,
            bgcolor="#F3F5F8",
            border=ft.border.all(1, ft.Colors.with_opacity(0.78, ft.Colors.WHITE)),
            shadow=ft.BoxShadow(
                blur_radius=22,
                spread_radius=0,
                color=ft.Colors.with_opacity(0.18, ft.Colors.WHITE),
                offset=ft.Offset(0, 8),
            ),
            on_click=do_login,
            content=ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                controls=[
                    ft.Text("Sign in", size=14, weight=ft.FontWeight.W_800, color="#111317"),
                    ft.Icon(ft.Icons.ARROW_FORWARD_ROUNDED, size=18, color="#111317"),
                ],
            ),
        )

        google_button = ft.Container(
            width=374,
            height=45,
            alignment=ft.Alignment(0, 0),
            border_radius=18,
            bgcolor=ft.Colors.with_opacity(0.40, ft.Colors.BLACK),
            border=ft.border.all(1, ft.Colors.with_opacity(0.24, ft.Colors.WHITE)),
            on_click=google_login_placeholder,
            content=ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=11,
                controls=[
                    ft.Container(
                        width=24,
                        height=24,
                        alignment=ft.Alignment(0, 0),
                        shape=ft.BoxShape.CIRCLE,
                        bgcolor=ft.Colors.WHITE,
                        content=ft.Text("G", size=14, weight=ft.FontWeight.W_900, color="#4285F4"),
                    ),
                    ft.Text(
                        "Sign in with Gmail",
                        size=13,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.with_opacity(0.92, ft.Colors.WHITE),
                    ),
                ],
            ),
        )

        login_panel = ft.Container(
            width=410,
            height=384,
            opacity=1.0,
            offset=ft.Offset(0, 0),
            animate_opacity=reveal_animation,
            animate_offset=reveal_animation,
            content=ft.Stack(
                controls=[
                    ft.Container(left=18, top=128, content=credentials_panel),
                    ft.Container(
                        left=0,
                        right=0,
                        top=258,
                        alignment=ft.Alignment(0, 0),
                        content=login_error,
                    ),
                    ft.Container(left=18, top=280, content=sign_in_button),
                    ft.Container(left=18, top=337, content=google_button),
                ],
            ),
        )

        def fms_text(text_color: str, top: int) -> ft.Container:
            return ft.Container(
                left=0,
                right=0,
                top=top,
                alignment=ft.Alignment(0, 0),
                content=ft.Text(
                    "FMS",
                    size=216,
                    weight=ft.FontWeight.W_900,
                    font_family="Arial Black",
                    color=text_color,
                ),
            )

        fms_title_layer = ft.Container(
            width=840,
            height=330,
            opacity=1.0,
            scale=1.0,
            animate_opacity=reveal_animation,
            animate_scale=reveal_animation,
            content=ft.Stack(
                controls=[
                    fms_text("#41454D", 27),
                    fms_text("#A9ADB5", 22),
                    fms_text("#F7F8FA", 17),
                ],
            ),
        )

        light_beam_layer = ft.Container(
            width=855,
            height=360,
            opacity=1.0,
            animate_opacity=ft.Animation(900, ft.AnimationCurve.EASE_IN_OUT_SINE),
            content=ft.Stack(
                controls=[
                    ft.Container(
                        left=0,
                        right=0,
                        top=3,
                        height=350,
                        gradient=ft.RadialGradient(
                            center=ft.Alignment(0, -1),
                            radius=0.96,
                            colors=[
                                ft.Colors.with_opacity(0.15, ft.Colors.WHITE),
                                ft.Colors.with_opacity(0.07, ft.Colors.WHITE),
                                ft.Colors.TRANSPARENT,
                                ft.Colors.TRANSPARENT,
                            ],
                            stops=[0.0, 0.32, 0.82, 1.0],
                        ),
                    ),
                    ft.Container(
                        left=30,
                        right=30,
                        top=3,
                        height=342,
                        gradient=ft.RadialGradient(
                            center=ft.Alignment(0, -1),
                            radius=1.05,
                            colors=[
                                ft.Colors.with_opacity(0.25, ft.Colors.WHITE),
                                ft.Colors.with_opacity(0.11, ft.Colors.WHITE),
                                ft.Colors.with_opacity(0.03, ft.Colors.WHITE),
                                ft.Colors.TRANSPARENT,
                            ],
                            stops=[0.0, 0.30, 0.66, 1.0],
                        ),
                    ),
                    ft.Container(
                        left=60,
                        right=60,
                        top=3,
                        height=334,
                        gradient=ft.RadialGradient(
                            center=ft.Alignment(0, -1),
                            radius=1.04,
                            colors=[
                                ft.Colors.with_opacity(0.42, ft.Colors.WHITE),
                                ft.Colors.with_opacity(0.18, ft.Colors.WHITE),
                                ft.Colors.with_opacity(0.04, ft.Colors.WHITE),
                                ft.Colors.TRANSPARENT,
                            ],
                            stops=[0.0, 0.28, 0.64, 1.0],
                        ),
                    ),
                    ft.Container(
                        left=147,
                        right=147,
                        top=3,
                        height=3,
                        border_radius=2,
                        gradient=ft.LinearGradient(
                            begin=ft.Alignment(-1, 0),
                            end=ft.Alignment(1, 0),
                            colors=[
                                ft.Colors.TRANSPARENT,
                                ft.Colors.with_opacity(0.98, ft.Colors.WHITE),
                                ft.Colors.TRANSPARENT,
                            ],
                            stops=[0.0, 0.5, 1.0],
                        ),
                    ),
                ],
            ),
        )

        app_icon_src = app_icon_png_src()
        logo_morph_animation = ft.Animation(920, ft.AnimationCurve.EASE_IN_OUT_CUBIC)
        app_icon_visual = ft.Container(
            width=124,
            height=124,
            opacity=0.0,
            scale=0.92,
            animate_opacity=logo_morph_animation,
            animate_scale=logo_morph_animation,
            alignment=ft.Alignment(0, 0),
            content=(
                ft.Image(src=app_icon_src, width=118, height=118, fit=ft.BoxFit.CONTAIN, anti_alias=True)
                if app_icon_src
                else ft.Icon(ft.Icons.FLIGHT_TAKEOFF, size=92, color=ft.Colors.WHITE)
            ),
        )

        hero = ft.Container(
            width=855,
            height=360,
            content=ft.Stack(controls=[light_beam_layer, fms_title_layer]),
        )

        transition_active = bool(getattr(state, "login_transition_active", False))
        viewport_height = int(getattr(page, "height", 0) or getattr(page, "window_height", 820) or 820)
        splash_center_top = max(0, int((viewport_height - 124) / 2))
        app_icon_position_layer = ft.Container(
            left=0,
            right=0,
            top=splash_center_top,
            height=124,
            alignment=ft.Alignment(0, 0),
            animate_position=logo_morph_animation,
            content=app_icon_visual,
        )

        intro_pending = not bool(getattr(state, "login_intro_started", False)) and not transition_active
        if intro_pending:
            state.login_intro_started = True
            app_icon_visual.opacity = 1.0
            app_icon_visual.scale = 0.96
            fms_title_layer.opacity = 0.0
            fms_title_layer.scale = 0.72
            light_beam_layer.opacity = 0.0
            login_panel.opacity = 0.0
            login_panel.offset = ft.Offset(0, 0.08)

        login_layout = ft.Stack(
            expand=True,
            controls=[
                ft.Container(
                    left=0,
                    right=0,
                    top=34,
                    height=360,
                    alignment=ft.Alignment(0, -1),
                    content=hero,
                ),
                ft.Container(
                    left=0,
                    right=0,
                    top=0,
                    bottom=0,
                    alignment=ft.Alignment(0, 0),
                    content=login_panel,
                ),
                app_icon_position_layer,
            ],
        )

        async def play_login_intro():
            await asyncio.sleep(2.0)
            if state.is_logged_in or bool(getattr(state, "login_transition_active", False)):
                return
            app_icon_position_layer.top = 86
            app_icon_visual.scale = ft.Scale(scale_x=5.0, scale_y=0.68)
            app_icon_visual.opacity = 0.05
            fms_title_layer.opacity = 1.0
            fms_title_layer.scale = 1.0
            light_beam_layer.opacity = 1.0
            login_panel.opacity = 1.0
            login_panel.offset = ft.Offset(0, 0)
            page.update()
            await asyncio.sleep(0.85)
            if state.is_logged_in or bool(getattr(state, "login_transition_active", False)):
                return
            app_icon_visual.opacity = 0.0
            light_beam_layer.opacity = 0.86
            page.update()
            await asyncio.sleep(0.40)
            if state.is_logged_in or bool(getattr(state, "login_transition_active", False)):
                return
            light_beam_layer.opacity = 1.0
            page.update()

        login_transition_icon_src = (
            asset_rel_path_if_exists("icons/nav/login_transition_aircraft.png")
            or asset_rel_path_if_exists("icons/login_transition_aircraft.png")
            or asset_rel_path_if_exists("login_transition_aircraft.png")
        )
        transition_distance = viewport_height + 420
        login_slide_y = transition_distance if transition_active else 0
        aircraft_top = -360 if transition_active else viewport_height + 110
        transition_opacity = 1.0 if transition_active else 0.0
        transition_animation = ft.Animation(3000, ft.AnimationCurve.EASE_IN_OUT_CUBIC)

        login_content_layer = ft.Container(
            key="login_full_page_content",
            top=-login_slide_y,
            bottom=login_slide_y,
            left=0,
            right=0,
            animate_position=transition_animation,
            content=login_layout,
        )
        transition_aircraft_layer = ft.Container(
            key="login_full_page_aircraft_transition",
            top=aircraft_top,
            left=0,
            right=0,
            height=320,
            opacity=transition_opacity,
            animate_position=transition_animation,
            alignment=ft.Alignment(0, 0),
            content=(
                ft.Image(
                    src=login_transition_icon_src,
                    width=116,
                    height=116,
                    fit=ft.BoxFit.CONTAIN,
                )
                if login_transition_icon_src
                else ft.Icon(ft.Icons.FLIGHT_TAKEOFF, size=104, color=ft.Colors.WHITE)
            ),
        )

        copyright_text = ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 1),
            padding=ft.padding.only(bottom=10),
            content=ft.Text(
                "Copyright 2026 Flight Management Systems. All rights reserved.",
                size=11,
                color=ft.Colors.with_opacity(0.42, ft.Colors.WHITE),
                text_align=ft.TextAlign.CENTER,
            ),
        )

        result = ft.Stack(
            expand=True,
            controls=[
                ft.Container(expand=True, bgcolor="#111214"),
                ft.Container(
                    expand=True,
                    gradient=ft.RadialGradient(
                        center=ft.Alignment(0, -0.68),
                        radius=1.12,
                        colors=["#25272B", "#151618", "#101113"],
                        stops=[0.0, 0.48, 1.0],
                    ),
                ),
                copyright_text,
                login_content_layer,
                transition_aircraft_layer,
            ],
        )

        if intro_pending:
            try:
                page.run_task(play_login_intro)
            except Exception:
                app_icon_visual.opacity = 0.0
                fms_title_layer.opacity = 1.0
                fms_title_layer.scale = 1.0
                light_beam_layer.opacity = 1.0
                login_panel.opacity = 1.0
                login_panel.offset = ft.Offset(0, 0)
        return result

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
        nonlocal overview_progress_refresh_callback, ramp_status_refresh_callback
        # Phase 4 debug version:
        # Keep the original app intact and rebuild only the Overview page body.
        # This avoids the previous blank/gray render while preserving all other pages.
        overview_daylight_mode = str(getattr(state, "display_mode", "dark") or "dark").lower() == "daylight"
        overview_route_scale = 1.00
        overview_card_height = 440
        overview_ramp_width = 430
        overview_flight_width = 240
        overview_margin = 18
        overview_glass_fill = ft.Colors.with_opacity(0.34, tokens["panel"])
        overview_glass_border = ft.Colors.with_opacity(0.14, ft.Colors.WHITE)
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
            radius: int = 20,
        ) -> ft.Control:
            return ft.Container(
                width=width,
                height=height,
                expand=expand,
                padding=padding,
                border_radius=radius,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                bgcolor=overview_glass_fill,
                blur=ft.Blur(12, 12, ft.BlurTileMode.CLAMP),
                border=ft.border.all(1, overview_glass_border),
                shadow=ft.BoxShadow(
                    blur_radius=18,
                    spread_radius=1,
                    color=ft.Colors.with_opacity(0.10, ft.Colors.BLACK),
                    offset=ft.Offset(0, 6),
                ),
                content=content,
            )

        ramp_status_card_host.width = overview_ramp_width
        ramp_status_card_host.height = overview_card_height
        origin_icao = (state.departure or takeoff_departure_icao_tf.value or "").strip().upper()
        destination_icao = (state.arrival or landing_arrival_icao_tf.value or "").strip().upper()
        origin_icao = normalize_airport_code(origin_icao) or origin_icao
        destination_icao = normalize_airport_code(destination_icao) or destination_icao
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
        distance_subtitle = "Manual from fuel plan" if override_active else "Great-circle estimate"
        fuel_plan = state.takeoff_last_result.get("fuel_plan", {}) if state.takeoff_last_result else {}
        ete_hours = fuel_plan.get("ete_hours") if isinstance(fuel_plan, dict) else None
        if not isinstance(ete_hours, (int, float)) or ete_hours <= 0:
            try:
                gs = resolve_takeoff_fuel_config(state.aircraft or takeoff_aircraft_dd.value).cruise_gs_kt_default
            except Exception:
                gs = 460
            ete_hours = (route_nm / gs) if route_nm else None

        total_ete_minutes = int(round(float(ete_hours) * 60)) if ete_hours else 0
        if total_ete_minutes <= 0:
            total_ete_minutes = int(getattr(state, "overview_flight_time_minutes", 0) or 0)

        ete_remaining_minutes = total_ete_minutes
        if int(state.overview_flight_status_index or 0) >= 5:
            ete_remaining_minutes = 0
        elif (
            bool(getattr(state, "overview_progress_running", False))
            and isinstance(getattr(state, "overview_takeoff_start_timestamp", None), (int, float))
            and total_ete_minutes > 0
        ):
            elapsed_minutes = int(max(0.0, time.time() - float(state.overview_takeoff_start_timestamp)) / 60.0)
            ete_remaining_minutes = max(0, total_ete_minutes - elapsed_minutes)

        ete_label = format_hours_to_hm(ete_remaining_minutes / 60.0) if total_ete_minutes > 0 else "Awaiting route"

        if isinstance(getattr(state, "overview_locked_eta_timestamp", None), (int, float)):
            eta_timestamp = float(state.overview_locked_eta_timestamp)
        elif ete_hours:
            eta_timestamp = datetime.now().timestamp() + float(ete_hours) * 3600
        else:
            eta_timestamp = None
        eta_text = datetime.fromtimestamp(eta_timestamp).strftime("%H:%M") if eta_timestamp else "—"
        overview_ete_value_text.value = ete_label
        overview_eta_value_text.value = eta_text
        overview_ete_value_text.color = tokens["text"]
        overview_eta_value_text.color = tokens["text"]
        overview_ete_value_text.size = route_scaled(18, 13)
        overview_eta_value_text.size = route_scaled(18, 13)
        distance_label = f"{route_nm:.0f} NM" if route_nm else "—"
        flight_phase = "Cruise monitor ready" if route_nm else "Awaiting route setup"

        planned_fuel = fuel_plan.get("planned_fuel_kg") if isinstance(fuel_plan, dict) else None
        trip_fuel = (fuel_plan.get("corrected_trip_fuel_kg") or fuel_plan.get("trip_fuel_kg")) if isinstance(fuel_plan, dict) else None
        planned_fuel_label = f"{planned_fuel/1000:.1f} t" if isinstance(planned_fuel, (int, float)) else "—"
        fuel_burn_label = f"{trip_fuel/1000:.1f} t trip" if isinstance(trip_fuel, (int, float)) else "—"

        def overview_metric(label: str, value: str, subtitle: str = "") -> ft.Control:
            return ft.Container(
                width=190,
                height=110,
                padding=12,
                border_radius=18,
                bgcolor=tokens["subpanel"],
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

        def overview_airport_card_background_src(code: str, title: str) -> Optional[str]:
            title_key = "origin" if title.lower().startswith("origin") else "destination"
            return airport_card_background_src(code, title_key)

        def point_card(title: str, code: str, target_tab_index: Optional[int] = None) -> ft.Control:
            record = lookup_airport_record(code)
            airport_name = record.get("name", "Airport not selected") if record else "Airport not selected"
            weather = airport_weather_for_card(code)
            background_src = overview_airport_card_background_src(code, title)
            is_origin_card = title.lower().startswith("origin")
            terminal_value = (state.departure_terminal if is_origin_card else state.arrival_terminal) or "—"
            gate_value = (state.departure_gate if is_origin_card else state.arrival_gate) or "—"
            point_size = route_scaled(280, 180)

            background_layers: List[ft.Control] = [
                ft.Container(expand=True, bgcolor=overview_glass_fill, blur=ft.Blur(12, 12, ft.BlurTileMode.CLAMP)),
            ]
            if background_src:
                background_layers.extend([
                    ft.Container(
                        expand=True,
                        image=ft.DecorationImage(
                            src=background_src,
                            fit=ft.BoxFit.COVER,
                            opacity=0.42,
                        ),
                    ),
                    ft.Container(
                        expand=True,
                        bgcolor=ft.Colors.with_opacity(0.18 if overview_daylight_mode else 0.28, ft.Colors.BLACK),
                    ),
                ])

            card = ft.Container(
                width=point_size,
                height=point_size,
                border_radius=route_scaled(20, 14),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                bgcolor=overview_glass_fill,
                blur=ft.Blur(12, 12, ft.BlurTileMode.CLAMP),
                border=ft.border.all(1, overview_glass_border),
                shadow=ft.BoxShadow(
                    blur_radius=18,
                    spread_radius=1,
                    color=ft.Colors.with_opacity(0.10, ft.Colors.BLACK),
                    offset=ft.Offset(0, 6),
                ),
                content=ft.Stack(
                    expand=True,
                    controls=[
                        *background_layers,
                        ft.Container(
                            expand=True,
                            padding=route_scaled(14, 10),
                            content=ft.Column(
                                spacing=route_scaled(6, 4),
                                controls=[
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        vertical_alignment=ft.CrossAxisAlignment.START,
                                        controls=[
                                            ft.Text(title, size=route_scaled(11, 9), color=tokens["muted"]),
                                            ft.Column(
                                                spacing=1,
                                                horizontal_alignment=ft.CrossAxisAlignment.END,
                                                controls=[
                                                    ft.Text(
                                                        str(weather.get("temperature", "—")),
                                                        size=route_scaled(14, 10),
                                                        weight=ft.FontWeight.W_800,
                                                        color=tokens["text"],
                                                    ),
                                                    ft.Text(
                                                        f"{weather.get('icon', '🌡️')} {weather.get('condition', 'Weather unavailable')}",
                                                        size=route_scaled(11, 8),
                                                        color=tokens["muted"],
                                                        max_lines=1,
                                                        overflow=ft.TextOverflow.ELLIPSIS,
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                    ft.Text(code or "—", size=route_scaled(28, 20), weight=ft.FontWeight.W_900, color=tokens["text"]),
                                    ft.Text(airport_name, size=route_scaled(13, 10), color=tokens["muted"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Container(
                                        margin=ft.margin.only(top=route_scaled(4, 2)),
                                        content=ft.Column(
                                            tight=True,
                                            spacing=2,
                                            controls=[
                                                ft.Text(f"Terminal: {terminal_value}", size=route_scaled(12, 9), color=tokens["muted"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                                ft.Text(f"Gate: {gate_value}", size=route_scaled(12, 9), color=tokens["muted"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                            ],
                                        ),
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
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

        def overview_flight_duration_minutes() -> int:
            try:
                return max(1, int(float(state.overview_flight_time_minutes or 120)))
            except Exception:
                return 120

        def overview_progress_percent() -> float:
            idx = max(0, min(len(OVERVIEW_FLIGHT_STATUSES) - 1, int(state.overview_flight_status_index or 0)))
            if idx < 2:
                return 0.0
            if idx >= 5:
                return 100.0
            start_ts = state.overview_takeoff_start_timestamp
            if not state.overview_progress_running or not isinstance(start_ts, (int, float)):
                return 0.0
            elapsed_min = max(0.0, (time.time() - float(start_ts)) / 60.0)
            return clamp((elapsed_min / overview_flight_duration_minutes()) * 100.0, 0.0, 100.0)

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
            duration_minutes = overview_flight_duration_minutes()
            remaining_minutes = duration_minutes
            if int(state.overview_flight_status_index or 0) >= 5:
                remaining_minutes = 0
            elif (
                bool(getattr(state, "overview_progress_running", False))
                and isinstance(getattr(state, "overview_takeoff_start_timestamp", None), (int, float))
            ):
                elapsed_minutes = int(max(0.0, time.time() - float(state.overview_takeoff_start_timestamp)) / 60.0)
                remaining_minutes = max(0, duration_minutes - elapsed_minutes)

            locked_eta = getattr(state, "overview_locked_eta_timestamp", None)
            if isinstance(locked_eta, (int, float)):
                live_eta_text = datetime.fromtimestamp(float(locked_eta)).strftime("%H:%M")
            elif duration_minutes > 0:
                live_eta_text = datetime.fromtimestamp(datetime.now().timestamp() + duration_minutes * 60).strftime("%H:%M")
            else:
                live_eta_text = "—"

            overview_route_line_host.content = build_aircraft_progress_line(live_progress)
            overview_ete_value_text.value = format_hours_to_hm(remaining_minutes / 60.0) if duration_minutes > 0 else "Awaiting route"
            overview_eta_value_text.value = live_eta_text
            overview_progress_percent_text.value = f"{live_progress:.0f}%"
            overview_progress_percent_text.color = tokens["accent"]

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
                    overview_progress_percent_text,
                ):
                    safe_update_control(ctrl)
                safe_update_control(overview_route_aircraft_marker)

        overview_progress_refresh_callback = refresh_overview_progress_controls
        refresh_overview_progress_controls(update_page=False)

        route_line = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e: go_to_tab(6),
            content=ft.Container(
                height=route_scaled(48, 34),
                padding=ft.padding.symmetric(horizontal=route_scaled(12, 8), vertical=route_scaled(3, 2)),
                content=overview_route_line_host,
            ),
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
                bgcolor=tokens["subpanel"],
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
                bgcolor=ft.Colors.with_opacity(0.48, tokens["subpanel"]),
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
                                ft.Text("Origin", size=10, color=tokens["muted"]),
                                ft.Text("Destination", size=10, color=tokens["muted"]),
                            ],
                        ),
                    ],
                ),
            )

        def set_overview_status(new_index: int):
            new_index = max(0, min(len(OVERVIEW_FLIGHT_STATUSES) - 1, int(new_index)))
            state.overview_flight_status_index = new_index
            # Back before Takeoff means the aircraft is still at origin.
            if new_index < 2:
                state.overview_takeoff_start_timestamp = None
                state.overview_locked_eta_timestamp = None
                state.overview_progress_running = False
                state.overview_calendar_completion_key = ""
            # Reaching Takeoff arms the progress system, but does not start it.
            # The aircraft starts moving only after pressing Play.
            elif new_index in (2, 3, 4):
                if state.overview_takeoff_start_timestamp is None:
                    state.overview_progress_running = False
            # Force complete progress after landing/arrival phases.
            elif new_index >= 5:
                duration_sec = overview_flight_duration_minutes() * 60
                finish_ts = time.time()
                state.overview_takeoff_start_timestamp = finish_ts - duration_sec
                state.overview_locked_eta_timestamp = finish_ts
                state.overview_progress_running = False
            refresh_ui()

        def play_overview_progress(e=None):
            # Play starts the moving aircraft progress. If the flight is still at
            # Gate or Taxi Out, jump to Takeoff first, then start the timer.
            if int(state.overview_flight_status_index or 0) < 2:
                state.overview_flight_status_index = 2
            if int(state.overview_flight_status_index or 0) >= 5:
                state.overview_flight_status_index = 2
            if state.overview_takeoff_start_timestamp is None or not state.overview_progress_running:
                start_ts = time.time()
                state.overview_takeoff_start_timestamp = start_ts
                state.overview_locked_eta_timestamp = start_ts + overview_flight_duration_minutes() * 60
                state.overview_calendar_completion_key = ""
            elif not isinstance(getattr(state, "overview_locked_eta_timestamp", None), (int, float)):
                state.overview_locked_eta_timestamp = float(state.overview_takeoff_start_timestamp) + overview_flight_duration_minutes() * 60
            state.overview_progress_running = True
            refresh_ui()

        def update_overview_flight_time(e=None):
            raw = (overview_flight_time_tf.value or "").strip()
            minutes = parse_flight_time_minutes(raw)
            if minutes <= 0:
                try:
                    minutes = int(float(raw))
                except Exception:
                    minutes = overview_flight_duration_minutes()
            state.overview_flight_time_minutes = max(1, int(minutes))
            if not bool(getattr(state, "overview_progress_running", False)):
                state.overview_locked_eta_timestamp = None
            refresh_ui()

        overview_flight_time_tf = ft.TextField(
            label="Flight time",
            value=format_hours_to_hm(overview_flight_duration_minutes() / 60.0),
            width=132,
            height=44,
            text_size=12,
            border_radius=12,
            filled=True,
            bgcolor=tokens["input_bg"],
            on_submit=update_overview_flight_time,
            on_blur=update_overview_flight_time,
        )

        def status_chip(label: str, active: bool = False) -> ft.Control:
            return ft.Container(
                padding=ft.padding.symmetric(horizontal=8, vertical=5),
                border_radius=999,
                bgcolor=ft.Colors.with_opacity(0.18 if active else 0.07, tokens["accent"] if active else tokens["muted"]),
                border=ft.border.all(1, ft.Colors.with_opacity(0.28 if active else 0.10, tokens["accent"] if active else tokens["muted"])),
                content=ft.Text(label, size=9, weight=ft.FontWeight.W_700 if active else ft.FontWeight.W_500, color=tokens["text"]),
            )

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
                bgcolor=tokens["subpanel"],
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

        def flight_status_action_button(icon_value, tooltip: str, handler, active: bool = False) -> ft.Control:
            return ft.IconButton(
                icon=icon_value,
                tooltip=tooltip,
                on_click=handler,
                bgcolor=tokens["accent"] if active else tokens["subpanel"],
                icon_color=ft.Colors.WHITE if active else tokens["text"],
                width=34,
                height=34,
                icon_size=18,
            )

        def flight_status_play_button() -> ft.Control:
            is_running = bool(getattr(state, "overview_progress_running", False))
            label = "LIVE" if is_running else "PLAY"
            icon_value = ft.Icons.RADIO_BUTTON_CHECKED if is_running else ft.Icons.PLAY_ARROW
            bg_color = tokens["accent"] if is_running else tokens["subpanel"]
            border_color = ft.Colors.with_opacity(0.72 if is_running else 0.22, tokens["accent"] if is_running else ft.Colors.WHITE)
            glow_color = ft.Colors.with_opacity(0.34 if is_running else 0.10, tokens["accent"] if is_running else ft.Colors.BLACK)

            return ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=play_overview_progress,
                content=ft.Container(
                    width=76,
                    height=38,
                    border_radius=999,
                    alignment=ft.Alignment(0, 0),
                    bgcolor=bg_color,
                    border=ft.border.all(1, border_color),
                    shadow=ft.BoxShadow(
                        blur_radius=20 if is_running else 10,
                        spread_radius=1 if is_running else 0,
                        color=glow_color,
                        offset=ft.Offset(0, 6),
                    ),
                    content=ft.Row(
                        tight=True,
                        spacing=7,
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(icon_value, size=15, color=ft.Colors.WHITE if is_running else tokens["text"]),
                            ft.Text(label, size=10, weight=ft.FontWeight.W_900, color=ft.Colors.WHITE if is_running else tokens["text"]),
                        ],
                    ),
                ),
            )

        flight_status_card = overview_glass_panel(
            ft.Column(
                spacing=12,
                controls=[
                    ft.Column(
                        tight=True,
                        spacing=2,
                        controls=[
                            ft.Text("Flight Status", size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                            ft.Text("Live route progress", size=10, color=tokens["muted"]),
                        ],
                    ),
                    ft.Container(
                        alignment=ft.Alignment(0, 0),
                        padding=ft.padding.symmetric(horizontal=10, vertical=7),
                        border_radius=999,
                        bgcolor=ft.Colors.with_opacity(0.16, tokens["accent"]),
                        border=ft.border.all(1, ft.Colors.with_opacity(0.30, tokens["accent"])),
                        content=ft.Text(f"{current_progress:.0f}%", size=12, weight=ft.FontWeight.W_900, color=tokens["accent"]),
                    ),
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=11, vertical=11),
                        border_radius=16,
                        bgcolor=ft.Colors.with_opacity(0.13, tokens["accent"]),
                        border=ft.border.all(1, ft.Colors.with_opacity(0.28, tokens["accent"])),
                        content=ft.Column(
                            tight=True,
                            spacing=4,
                            controls=[
                                ft.Text("Current phase", size=10, color=tokens["muted"]),
                                ft.Text(live_summary_status_label(), size=18, weight=ft.FontWeight.W_900, color=tokens["accent"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                            ],
                        ),
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=5,
                        controls=[
                            flight_status_action_button(ft.Icons.CHEVRON_LEFT, "Previous status", lambda e: set_overview_status(int(state.overview_flight_status_index or 0) - 1)),
                            flight_status_play_button(),
                            flight_status_action_button(ft.Icons.CHEVRON_RIGHT, "Next status", lambda e: set_overview_status(int(state.overview_flight_status_index or 0) + 1), active=True),
                        ],
                    ),
                    ft.Row(
                        wrap=True,
                        spacing=5,
                        run_spacing=5,
                        controls=[status_chip(label, i == int(state.overview_flight_status_index or 0)) for i, label in enumerate(OVERVIEW_FLIGHT_STATUSES)],
                    ),
                    ft.Container(height=1, bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.WHITE)),
                    overview_flight_time_tf,
                    ft.Container(
                        width=132,
                        padding=ft.padding.symmetric(horizontal=10, vertical=6),
                        border_radius=12,
                        bgcolor=ft.Colors.with_opacity(0.08, tokens["accent"]),
                        border=ft.border.all(1, ft.Colors.with_opacity(0.18, tokens["accent"])),
                        content=ft.Column(
                            tight=True,
                            spacing=1,
                            controls=[
                                ft.Text("Progress", size=9, color=tokens["muted"]),
                                overview_progress_percent_text,
                            ],
                        ),
                    ),
                ],
            ),
            width=overview_flight_width,
            height=overview_card_height,
        )

        overview_aircraft_image = ft.Container(
            width=route_scaled(370, 259),
            height=route_scaled(150, 105),
            padding=route_scaled(6, 4),
            border_radius=route_scaled(18, 13),
            bgcolor="#141519",
            border=ft.border.all(0.6, ft.Colors.with_opacity(0.22, ft.Colors.WHITE)),
            alignment=ft.Alignment(0, 0),
            content=aircraft_livery_image(state.airline, state.aircraft, width=route_scaled(360, 252), height=route_scaled(138, 97)),
        )

        def route_center_metric(label: str, value: str, subtitle: str = "") -> ft.Control:
            return ft.Container(
                width=route_scaled(180, 126),
                height=route_scaled(85, 60),
                padding=route_scaled(10, 7),
                border_radius=route_scaled(18, 13),
                bgcolor=ft.Colors.with_opacity(0.56, tokens["subpanel"]),
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
                "AUH": "Abu Dhabi, UAE", "BAH": "Bahrain", "BCN": "Barcelona, Spain",
                "BER": "Berlin, Germany", "BKK": "Bangkok, Thailand", "BLR": "Bengaluru, India",
                "BOG": "Bogota, Colombia", "BOM": "Mumbai, India", "BOS": "Boston, USA",
                "CAI": "Cairo, Egypt", "CAN": "Guangzhou, China", "CDG": "Paris, France",
                "CGK": "Jakarta, Indonesia", "CGN": "Cologne, Germany", "CUN": "Cancun, Mexico",
                "DEL": "Delhi, India", "DEN": "Denver, USA", "DFW": "Dallas, USA",
                "DOH": "Doha, Qatar", "DUB": "Dublin, Ireland", "DXB": "Dubai, UAE",
                "EWR": "Newark, USA", "EZE": "Buenos Aires, Argentina", "FCO": "Rome, Italy",
                "FRA": "Frankfurt, Germany", "GRU": "Sao Paulo, Brazil", "HAM": "Hamburg, Germany",
                "HEL": "Helsinki, Finland", "HKG": "Hong Kong", "HND": "Tokyo, Japan",
                "IAD": "Washington, USA", "IAH": "Houston, USA", "ICN": "Seoul, South Korea",
                "IKA": "Tehran, Iran", "IST": "Istanbul, Turkiye", "JED": "Jeddah, Saudi Arabia",
                "JFK": "New York, USA", "KIX": "Osaka, Japan", "KUL": "Kuala Lumpur, Malaysia",
                "KWI": "Kuwait City, Kuwait", "LAS": "Las Vegas, USA", "LAX": "Los Angeles, USA",
                "LGW": "London, UK", "LHR": "London, UK", "LIM": "Lima, Peru",
                "LIS": "Lisbon, Portugal", "MAD": "Madrid, Spain", "MAA": "Chennai, India",
                "MCO": "Orlando, USA", "MEX": "Mexico City, Mexico", "MIA": "Miami, USA",
                "MNL": "Manila, Philippines", "MRU": "Mauritius", "MUC": "Munich, Germany",
                "NRT": "Tokyo, Japan", "ORD": "Chicago, USA", "OSL": "Oslo, Norway",
                "PEK": "Beijing, China", "PHL": "Philadelphia, USA", "PHX": "Phoenix, USA",
                "PVG": "Shanghai, China", "RUH": "Riyadh, Saudi Arabia", "SEA": "Seattle, USA",
                "SFO": "San Francisco, USA", "SHA": "Shanghai, China", "SIN": "Singapore",
                "SVO": "Moscow, Russia", "TLV": "Tel Aviv, Israel", "TPE": "Taipei, Taiwan",
                "SYD": "Sydney, Australia", "VIE": "Vienna, Austria", "WAW": "Warsaw, Poland",
                "YUL": "Montreal, Canada", "YVR": "Vancouver, Canada", "YYC": "Calgary, Canada",
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
                "WI": "Indonesia", "WM": "Malaysia", "WS": "Singapore", "YS": "Australia", "ZB": "China", "ZP": "China",
                "ZG": "China", "ZS": "China",
            }
            airport_name = str((record or {}).get("name", "") or "").strip()
            city = re.sub(r"\b(International|Intl|Airport|Airfield|Regional|Brandenburg|Charles de Gaulle)\b", "", airport_name, flags=re.IGNORECASE)
            city = re.sub(r"\s+", " ", city).strip(" -") or (iata or canonical or "Airport")
            country = country_by_prefix.get(canonical[:2], "")
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
                ft.Container(expand=True, bgcolor=ft.Colors.with_opacity(0.82, tokens["panel"])),
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

        def overview_airport_label(code: str, color: str) -> ft.Control:
            canonical = normalize_airport_code(code) or (code or "").strip().upper()
            record = lookup_airport_record(canonical)
            weather = airport_weather_for_card(canonical)
            label = str((record or {}).get("iata", "") or canonical or "-").strip().upper()
            airport_name = str((record or {}).get("name", "Airport not selected") or "Airport not selected")
            city_country = airport_city_country_label(canonical, record)
            return ft.Container(
                width=218,
                height=78,
                padding=ft.padding.symmetric(horizontal=12, vertical=10),
                border_radius=17,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                bgcolor=overview_glass_fill,
                blur=ft.Blur(12, 12, ft.BlurTileMode.CLAMP),
                border=ft.border.all(1, ft.Colors.with_opacity(0.18, ft.Colors.WHITE)),
                shadow=ft.BoxShadow(
                    blur_radius=18,
                    spread_radius=1,
                    color=ft.Colors.with_opacity(0.16, ft.Colors.BLACK),
                    offset=ft.Offset(0, 8),
                ),
                content=ft.Column(
                    tight=True,
                    spacing=4,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Text(label, size=17, weight=ft.FontWeight.W_900, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Container(
                                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                    border_radius=999,
                                    bgcolor=ft.Colors.with_opacity(0.16, color),
                                    border=ft.border.all(1, ft.Colors.with_opacity(0.30, color)),
                                    content=ft.Text(str(weather.get("temperature", "-")), size=10, weight=ft.FontWeight.W_900, color=tokens["text"]),
                                ),
                            ],
                        ),
                        ft.Text(city_country, size=10, weight=ft.FontWeight.W_800, color=tokens["muted"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(airport_name, size=9, color=tokens["muted"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        def overview_route_aircraft_content(bearing: float) -> ft.Control:
            icon = header_progress_icon()
            # The shared PNG points east at zero rotation; map bearings start at north.
            icon.rotate = math.radians(bearing - 90.0)
            return icon

        def overview_route_map_control() -> ft.Control:
            nonlocal overview_route_aircraft_marker, overview_route_aircraft_points
            if ftm is None:
                return ft.Container(
                    expand=True,
                    bgcolor=ft.Colors.with_opacity(0.70, tokens["panel"]),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Text(
                        "flet-map is not installed, so the Overview map cannot render in this build.",
                        size=12,
                        color=tokens["muted"],
                        text_align=ft.TextAlign.CENTER,
                    ),
                )

            if MAPTILER_API_KEY:
                tile_url = f"https://api.maptiler.com/maps/satellite/{{z}}/{{x}}/{{y}}.jpg?key={MAPTILER_API_KEY}"
                map_attribution = "MapTiler"
                attribution_url = "https://www.maptiler.com/"
            else:
                tile_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                map_attribution = "Esri"
                attribution_url = "https://www.esri.com/"

            layers = [
                ftm.TileLayer(url_template=tile_url),
                ftm.SimpleAttribution(
                    text=ft.Text(map_attribution, size=7, color=ft.Colors.with_opacity(0.72, ft.Colors.WHITE)),
                    bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.BLACK),
                    on_click=lambda e, url=attribution_url: e.page.launch_url(url),
                ),
            ]
            center = ftm.MapLatitudeLongitude(25.0, 10.0)
            zoom = 2.45
            overview_map_clamp_state = {"active": False}

            def overview_vertical_latitude_limit(zoom_value: float) -> float:
                try:
                    zoom_number = float(zoom_value)
                except Exception:
                    zoom_number = 2.45
                return max(54.0, min(84.5, 54.0 + max(0.0, zoom_number - 2.45) * 13.0))

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
                max_latitude = overview_vertical_latitude_limit(current_zoom)
                clamped_lat = max(-max_latitude, min(max_latitude, current_lat))
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

            if origin_coord and destination_coord:
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
                layers.append(
                    ftm.MarkerLayer(
                        markers=[
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(origin_coord[0], origin_coord[1]),
                                width=16,
                                height=16,
                                alignment=ft.Alignment(0, 0),
                                content=overview_airport_dot(tokens["accent"]),
                            ),
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(origin_coord[0], origin_coord[1]),
                                width=230,
                                height=82,
                                alignment=ft.Alignment(-1.18, 0),
                                content=overview_airport_label(origin_icao, tokens["accent"]),
                            ),
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(destination_coord[0], destination_coord[1]),
                                width=16,
                                height=16,
                                alignment=ft.Alignment(0, 0),
                                content=overview_airport_dot("#50E3C2"),
                            ),
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(destination_coord[0], destination_coord[1]),
                                width=230,
                                height=82,
                                alignment=ft.Alignment(1.18, 0),
                                content=overview_airport_label(destination_icao, "#50E3C2"),
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
                layers.append(ftm.MarkerLayer(markers=[overview_route_aircraft_marker], rotate=False))
            elif origin_coord or destination_coord:
                overview_route_aircraft_marker = None
                overview_route_aircraft_points = []
                available_coord = origin_coord or destination_coord
                available_icao = origin_icao if origin_coord else destination_icao
                center = ftm.MapLatitudeLongitude(available_coord[0], available_coord[1])
                zoom = 4.8
                layers.append(
                    ftm.MarkerLayer(
                        markers=[
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(available_coord[0], available_coord[1]),
                                width=16,
                                height=16,
                                alignment=ft.Alignment(0, 0),
                                content=overview_airport_dot(tokens["accent"]),
                            ),
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(available_coord[0], available_coord[1]),
                                width=230,
                                height=82,
                                alignment=ft.Alignment(-1.18, 0),
                                content=overview_airport_label(available_icao, tokens["accent"]),
                            ),
                        ]
                    )
                )

            return ftm.Map(
                expand=True,
                initial_center=center,
                initial_zoom=zoom,
                min_zoom=2.45,
                max_zoom=10.0,
                bgcolor="#020617",
                keep_alive=True,
                interaction_configuration=ftm.InteractionConfiguration(flags=ftm.InteractionFlag.ALL),
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
                    text=ft.Text(map_attribution, size=7, color=ft.Colors.with_opacity(0.72, ft.Colors.WHITE)),
                    bgcolor=ft.Colors.with_opacity(0.22, ft.Colors.BLACK),
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
                bgcolor=tokens["panel"],
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
                                        bgcolor=ft.Colors.with_opacity(0.46, tokens["panel"]),
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

        def route_metric_item(label: str, value: str | ft.Control, subtitle: str = "") -> ft.Control:
            return ft.Container(
                width=150,
                content=ft.Column(
                    tight=True,
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(label, size=10, color=tokens["muted"], text_align=ft.TextAlign.CENTER),
                        value if isinstance(value, ft.Control) else ft.Text(value, size=18, weight=ft.FontWeight.W_800, color=tokens["text"], text_align=ft.TextAlign.CENTER),
                        ft.Text(subtitle, size=9, color=tokens["muted"], text_align=ft.TextAlign.CENTER, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        progress_strip = ft.Container(
            height=overview_progress_height,
            padding=ft.padding.only(left=12, right=12, top=0, bottom=6),
            bgcolor=ft.Colors.TRANSPARENT,
            content=route_line,
        )

        def toggle_flight_hibernation_menu(e=None):
            state.flight_hibernation_menu_open = not bool(getattr(state, "flight_hibernation_menu_open", False))
            refresh_ui()

        def hibernation_menu_button(title: str, subtitle: str, icon_name: str, handler, disabled: bool = False) -> ft.Control:
            icon_value = getattr(ft.Icons, str(icon_name or "").upper(), ft.Icons.CIRCLE)
            foreground = tokens["muted"] if disabled else tokens["text"]
            accent = tokens["muted"] if disabled else tokens["accent"]
            surface = ft.Container(
                height=58,
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                border_radius=15,
                bgcolor=ft.Colors.with_opacity(0.15 if not disabled else 0.08, tokens["accent"] if not disabled else tokens["subpanel"]),
                border=ft.border.all(1, ft.Colors.with_opacity(0.32 if not disabled else 0.14, tokens["accent"] if not disabled else ft.Colors.WHITE)),
                content=ft.Row(
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(
                            width=28,
                            height=28,
                            border_radius=999,
                            alignment=ft.Alignment(0, 0),
                            bgcolor=ft.Colors.with_opacity(0.14, accent),
                            content=ft.Icon(icon_value, size=17, color=accent),
                        ),
                        ft.Container(
                            expand=True,
                            content=ft.Column(
                                tight=True,
                                spacing=2,
                                alignment=ft.MainAxisAlignment.CENTER,
                                controls=[
                                    ft.Text(title, size=12, weight=ft.FontWeight.W_900, color=foreground, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(subtitle, size=9, color=tokens["muted"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ],
                            ),
                        ),
                    ],
                ),
            )
            if disabled:
                return surface
            return ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=handler,
                content=surface,
            )

        flight_hibernation_action_button = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=toggle_flight_hibernation_menu,
            content=ft.Container(
                width=48,
                height=48,
                border_radius=999,
                alignment=ft.Alignment(0, 0),
                tooltip="Flight actions",
                bgcolor=ft.Colors.with_opacity(0.18, tokens["accent"] if bool(getattr(state, "flight_hibernation_menu_open", False)) else tokens["subpanel"]),
                border=ft.border.all(1, ft.Colors.with_opacity(0.34, tokens["accent"] if bool(getattr(state, "flight_hibernation_menu_open", False)) else ft.Colors.WHITE)),
                content=ft.Icon(ft.Icons.MORE_VERT, size=23, color=tokens["text"]),
            ),
        )

        flight_hibernation_menu = ft.Container(
            width=250,
            content=overview_glass_panel(
                ft.Column(
                    tight=True,
                    spacing=10,
                    controls=[
                        ft.Text("Flight Actions", size=13, weight=ft.FontWeight.W_900, color=tokens["text"]),
                        hibernation_menu_button(
                            "Flight Hibernation",
                            "Save this flight for next launch",
                            "pause_circle",
                            save_current_flight_hibernation,
                        ),
                        hibernation_menu_button(
                            "Flight End",
                            "Open flight summary",
                            "flag",
                            show_flight_end_summary,
                        ),
                        hibernation_menu_button(
                            "Start New Flight",
                            "Reset the current flight workspace",
                            "restart_alt",
                            lambda e: reset_active_flight_workspace(),
                        ),
                    ],
                ),
                width=250,
                padding=12,
                radius=18,
            ),
        )

        route_metrics_card = overview_glass_panel(
            ft.Row(
                spacing=12,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    route_metric_item("Distance", distance_label, distance_subtitle),
                    route_metric_item("ETE", overview_ete_value_text, "Estimated flight time"),
                    route_metric_item("ETA", overview_eta_value_text, "Route arrival"),
                    flight_hibernation_action_button,
                ],
            ),
            width=600,
            height=106,
            padding=12,
            radius=18,
        )

        # Return the Overview page directly instead of wrapping it in build_tab_page().
        # The previous wrapper could render as a blank gray layer on this new tab
        # because OVERVIEW is not part of the existing background map.
        return ft.Container(
            expand=True,
            bgcolor=ft.Colors.TRANSPARENT,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=ft.Stack(
                expand=True,
                controls=[
                    ft.Container(
                        expand=True,
                        content=overview_route_map_control(),
                    ),
                    ft.Container(
                        left=overview_margin,
                        top=overview_margin,
                        width=280,
                        height=280,
                        content=point_card("Origin", origin_icao, 4),
                    ),
                    ft.Container(
                        right=overview_margin,
                        top=overview_margin,
                        width=280,
                        height=280,
                        content=point_card("Destination", destination_icao, 5),
                    ),
                    ft.Container(
                        left=overview_margin,
                        bottom=overview_margin,
                        width=370,
                        height=150,
                        content=overview_aircraft_image,
                    ),
                    ft.Container(
                        left=0,
                        right=0,
                        bottom=overview_margin,
                        alignment=ft.Alignment(0, 1),
                        content=route_metrics_card,
                    ),
                    ft.Container(
                        right=overview_margin,
                        bottom=overview_margin,
                        width=overview_flight_width,
                        height=overview_card_height,
                        content=flight_status_card,
                    ),
                    *(
                        [
                            ft.Container(
                                left=0,
                                right=0,
                                bottom=overview_margin + 118,
                                alignment=ft.Alignment(0.44, 1),
                                content=flight_hibernation_menu,
                            )
                        ]
                        if bool(getattr(state, "flight_hibernation_menu_open", False))
                        else []
                    ),
                ],
            ),
        )



    def home_page():
        occupied_pax = sum(1 for seat in seat_model.get("seats", []) if seat.get("occupied")) if seat_model.get("generated") else 0
        configured_seats = len(seat_model.get("seats", [])) if seat_model.get("generated") else 0
        pax_value = str(occupied_pax) if seat_model.get("generated") else "—"

        home_card_bg = tokens["panel"]
        home_tile_bg = tokens["subpanel"]
        home_info_fill_bg = tokens["panel"]

        home_origin_icao = (state.departure or takeoff_departure_icao_tf.value or "").strip().upper()
        home_destination_icao = (state.arrival or landing_arrival_icao_tf.value or "").strip().upper()
        home_origin_icao = normalize_airport_code(home_origin_icao) or home_origin_icao
        home_destination_icao = normalize_airport_code(home_destination_icao) or home_destination_icao
        home_route_nm = route_distance_nm(home_origin_icao, home_destination_icao) if home_origin_icao and home_destination_icao else None
        home_ete_label = format_hours_to_hm(home_route_nm / 480.0) if home_route_nm else "—"
        home_route_label = f"{home_origin_icao or '—'} → {home_destination_icao or '—'}"

        def home_stat_tile(label: str, value: str, subtitle: str = "", width: int = 160) -> ft.Control:
            return ft.Container(
                width=width,
                height=94,
                padding=14,
                border_radius=18,
                bgcolor=home_tile_bg,
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    spacing=4,
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.Text(label, size=11, color=tokens["muted"]),
                        ft.Text(value or "—", size=20, weight=ft.FontWeight.W_800, color=tokens["text"], max_lines=1),
                        ft.Text(subtitle, size=10, color=tokens["muted"], max_lines=1),
                    ],
                ),
            )

        def calendar_dt(entry: dict):
            try:
                return parse_calendar_entry_datetime(entry)
            except Exception:
                try:
                    return datetime.strptime((entry.get("date") or "") + " " + (entry.get("time") or "00:00"), "%Y-%m-%d %H:%M")
                except Exception:
                    return datetime.max

        now_dt = datetime.now()
        planned_entries = [entry for entry in state.calendar_entries if not bool(entry.get("completed"))]
        upcoming_entries = [entry for entry in planned_entries if calendar_dt(entry) >= now_dt.replace(hour=0, minute=0, second=0, microsecond=0)]
        upcoming_entries.sort(key=calendar_dt)
        next_entry = upcoming_entries[0] if upcoming_entries else None
        today_str = now_dt.strftime("%Y-%m-%d")
        today_entries = [entry for entry in state.calendar_entries if (entry.get("date") or "") == today_str]
        completed_entries = [entry for entry in state.calendar_entries if bool(entry.get("completed"))]
        completed_entries.sort(key=calendar_dt, reverse=True)
        recent_completed = completed_entries[0] if completed_entries else None

        def today_schedule_heading() -> str:
            if not today_entries:
                return "No flights scheduled"
            routes = []
            for entry in today_entries[:2]:
                route = (entry.get("route") or f"{entry.get('origin', '—')} → {entry.get('destination', '—')}").strip()
                airline = (entry.get("airline") or "").strip()
                routes.append(f"{route} • {airline}" if airline else route)
            if len(today_entries) > 2:
                routes.append(f"+{len(today_entries) - 2} more")
            return "  |  ".join(routes)

        next_route = next_entry.get("route") if next_entry else "—"
        next_airline = next_entry.get("airline") if next_entry else "No planned flight"
        next_time = f"{next_entry.get('date', '')} {next_entry.get('time', '')}".strip() if next_entry else "—"

        greeting_card = glass_card_with_background(
            "Pilot Greeting",
            ft.Column(
                spacing=18,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.START,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Column(
                                tight=True,
                                spacing=8,
                                controls=[
                                    ft.Text(f"Hello, {state.pilot_name}", size=32, weight=ft.FontWeight.W_800, color=tokens["text"]),
                                    ft.Text(now_local_str(), size=18, weight=ft.FontWeight.W_700, color=tokens["text"]),
                                ],
                            ),
                        ],
                    ),
                    ft.Row(
                        wrap=True,
                        spacing=12,
                        run_spacing=12,
                        controls=[
                            home_stat_tile("Location", state.location_label if state.location_permission_enabled else "Not enabled", "city / area", width=230),
                            home_stat_tile("Weather", f"{state.weather.icon} {state.weather.condition}" if state.weather.condition else "—", "live station", width=230),
                        ],
                    ),
                    ft.Row(
                        wrap=True,
                        spacing=10,
                        controls=[
                            ft.ElevatedButton(
                                "Enable Location" if not state.location_permission_enabled else "Refresh Location",
                                on_click=enable_location_tracking,
                                bgcolor=tokens["accent"],
                                color=ft.Colors.WHITE,
                            ),
                            ft.OutlinedButton("Location Settings", on_click=open_device_location_settings),
                            ft.OutlinedButton("Open Map", on_click=lambda e: go_to_tab(6)),
                        ],
                    ),
                ],
            ),
            bgcolor_override=home_info_fill_bg,
            height=375,
        )

        def home_airline_code(airline_name: Optional[str]) -> str:
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
            if code and code != "--":
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
            on_submit=update_home_flight_number,
            on_blur=update_home_flight_number,
        )

        def home_aircraft_option_values() -> List[str]:
            if state.airline and state.airline != "Generic" and state.airline in AIRLINE_FLEETS:
                fleet_keys: List[str] = []
                for fleet_name in AIRLINE_FLEETS.get(state.airline, []):
                    key = canonical_aircraft_name(fleet_name)
                    if key and key in AIRCRAFT_LIBRARY and key not in fleet_keys:
                        fleet_keys.append(key)
                if fleet_keys:
                    return fleet_keys
            return sorted(all_library_aircraft_names(), key=aircraft_picker_sort_key)

        def home_dropdown_menu_style() -> ft.MenuStyle:
            return ft.MenuStyle(
                bgcolor=ft.Colors.with_opacity(0.70, ft.Colors.BLACK),
                elevation=12,
                padding=ft.padding.symmetric(vertical=6),
                side=ft.BorderSide(1, ft.Colors.with_opacity(0.16, ft.Colors.WHITE)),
                shape=ft.RoundedRectangleBorder(radius=14),
            )

        def home_dropdown_logo_slot(content: ft.Control) -> ft.Container:
            return ft.Container(
                width=58,
                height=32,
                alignment=ft.Alignment(0, 0),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=content,
            )

        def home_airline_option(name: str) -> ft.dropdown.Option:
            logo = airline_logo_image(name, width=52, height=24, fallback_text=False, key_prefix="home-airline-dd-logo")
            if not airline_logo_rel_path(name):
                logo = ft.Text(home_airline_code(name), size=10, weight=ft.FontWeight.W_800, color=tokens["muted"], text_align=ft.TextAlign.CENTER)
            return ft.dropdown.Option(
                key=name,
                text=name,
                content=ft.Container(
                    height=46,
                    alignment=ft.Alignment(-1, 0),
                    content=ft.Row(
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            home_dropdown_logo_slot(logo),
                            ft.Text(name, size=15, weight=ft.FontWeight.W_700, color=ft.Colors.WHITE, no_wrap=True),
                        ],
                    ),
                ),
            )

        def home_aircraft_option(key: str) -> ft.dropdown.Option:
            display = AIRCRAFT_LIBRARY.get(key, {}).get("name", key)
            logo = manufacturer_logo_image(key, width=50, height=24, fallback_icon=False, key_prefix="home-aircraft-dd-logo")
            return ft.dropdown.Option(
                key=key,
                text=display,
                content=ft.Container(
                    height=46,
                    alignment=ft.Alignment(-1, 0),
                    content=ft.Row(
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            home_dropdown_logo_slot(logo),
                            ft.Text(display, size=15, weight=ft.FontWeight.W_700, color=ft.Colors.WHITE, no_wrap=True),
                        ],
                    ),
                ),
            )

        def on_home_airline_changed(e):
            selected_airline = e.control.value or ""
            suffix = home_flight_number_suffix(home_flight_number_tf.value or state.flight_number, state.airline)
            state.flight_number = home_full_flight_number(suffix, selected_airline)
            home_flight_number_tf.value = suffix
            set_airline(selected_airline)

        def on_home_aircraft_changed(e):
            sync_aircraft_across_pages(e.control.value, update_page=False)
            state.logo_refresh_nonce += 1
            refresh_ui()

        home_airline_dd = ft.Dropdown(
            label="Airline",
            value=state.airline or None,
            options=[home_airline_option(name) for name in AIRLINES],
            height=58,
            expand=True,
            menu_height=420,
            menu_style=home_dropdown_menu_style(),
            border_radius=14,
            filled=True,
            fill_color=ft.Colors.with_opacity(0.70, ft.Colors.BLACK),
            bgcolor=ft.Colors.with_opacity(0.70, ft.Colors.BLACK),
            color=tokens["text"],
            border_color=ft.Colors.with_opacity(0.18, ft.Colors.WHITE),
            focused_border_color=tokens["accent"],
            hover_color=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
            label_style=ft.TextStyle(color=tokens["muted"]),
            text_style=ft.TextStyle(color=ft.Colors.WHITE, size=15, weight=ft.FontWeight.W_700),
            content_padding=ft.padding.symmetric(horizontal=12, vertical=8),
            on_select=on_home_airline_changed,
        )

        selected_airline_selector = ft.Container(
            padding=14,
            border_radius=20,
            bgcolor=tokens["subpanel"],
            border=ft.border.all(1, tokens["card_border"]),
            content=ft.Row(
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=72,
                        height=72,
                        border_radius=18,
                        alignment=ft.Alignment(0, 0),
                        bgcolor=ft.Colors.with_opacity(0.10, tokens["accent"]),
                        border=ft.border.all(1, ft.Colors.with_opacity(0.28, tokens["accent"])),
                        content=airline_logo_image(state.airline, width=56, height=38, fallback_text=False, key_prefix="home-selector-logo") if state.airline else ft.Icon(ft.Icons.FLIGHT, size=30, color=tokens["accent"]),
                    ),
                    home_airline_dd,
                ],
            ),
        )

        info_card_bg = home_info_fill_bg
        has_home_airline = bool((state.airline or "").strip())
        has_home_aircraft = bool((state.aircraft or "").strip())
        home_compact_info_height = 200
        airline_info_controls = [selected_airline_selector]
        if has_home_airline:
            airline_info_controls.append(home_flight_number_tf)
        airline_info_height = 260 if has_home_airline else home_compact_info_height

        airline_info_card = glass_card(
            "Airline Info",
            ft.Column(
                spacing=12,
                controls=airline_info_controls,
            ),
            bgcolor_override=info_card_bg,
            height=airline_info_height,
        )

        aircraft_options = home_aircraft_option_values()
        home_aircraft_dd = ft.Dropdown(
            label="Aircraft",
            value=state.aircraft if state.aircraft in aircraft_options else None,
            options=[home_aircraft_option(key) for key in aircraft_options],
            height=58,
            expand=True,
            menu_height=420,
            menu_style=home_dropdown_menu_style(),
            border_radius=14,
            filled=True,
            fill_color=ft.Colors.with_opacity(0.70, ft.Colors.BLACK),
            bgcolor=ft.Colors.with_opacity(0.70, ft.Colors.BLACK),
            color=tokens["text"],
            border_color=ft.Colors.with_opacity(0.18, ft.Colors.WHITE),
            focused_border_color=tokens["accent"],
            hover_color=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
            label_style=ft.TextStyle(color=tokens["muted"]),
            text_style=ft.TextStyle(color=ft.Colors.WHITE, size=15, weight=ft.FontWeight.W_700),
            content_padding=ft.padding.symmetric(horizontal=12, vertical=8),
            on_select=on_home_aircraft_changed,
        )

        selected_aircraft_selector = ft.Container(
            padding=14,
            border_radius=20,
            bgcolor=tokens["subpanel"],
            border=ft.border.all(1, tokens["card_border"]),
            content=ft.Row(
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=72,
                        height=72,
                        border_radius=18,
                        alignment=ft.Alignment(0, 0),
                        bgcolor=ft.Colors.with_opacity(0.10, tokens["accent"]),
                        border=ft.border.all(1, ft.Colors.with_opacity(0.28, tokens["accent"])),
                        content=manufacturer_logo_image(state.aircraft, width=54, height=42, key_prefix="home-aircraft-manufacturer-logo"),
                    ),
                    home_aircraft_dd,
                ],
            ),
        )

        home_aircraft_image_panel = ft.Container(
            width=666,
            height=420,
            padding=8,
            border_radius=20,
            bgcolor=ft.Colors.TRANSPARENT,
            border=ft.border.all(0.7, ft.Colors.with_opacity(0.16, ft.Colors.WHITE)),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            alignment=ft.Alignment(0, 0),
            content=aircraft_livery_image("Generic", state.aircraft, width=650, height=400),
        )

        compact_info_height = home_compact_info_height
        aircraft_info_height = 650 if has_home_aircraft else compact_info_height
        aircraft_info_top = ft.Container(
            padding=16,
            bgcolor=info_card_bg,
            border_radius=ft.border_radius.only(
                top_left=20,
                top_right=20,
                bottom_left=0 if has_home_aircraft else 20,
                bottom_right=0 if has_home_aircraft else 20,
            ),
            content=ft.Column(
                spacing=16,
                controls=[
                    ft.Text("Aircraft Info", size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                    ft.Divider(height=10, opacity=0.15),
                    selected_aircraft_selector,
                ],
            ),
        )
        aircraft_info_controls: List[ft.Control] = [aircraft_info_top]
        if has_home_aircraft:
            aircraft_info_controls.append(
                ft.Container(
                    padding=ft.padding.only(left=16, right=16, bottom=16, top=14),
                    bgcolor=ft.Colors.with_opacity(0.32, info_card_bg),
                    border_radius=ft.border_radius.only(bottom_left=20, bottom_right=20),
                    content=home_aircraft_image_panel,
                )
            )
        secondary_info_card = ft.Container(
            content=ft.Column(spacing=0, controls=aircraft_info_controls),
            border_radius=20,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=ft.Colors.TRANSPARENT,
            border=ft.border.all(1, tokens["card_border"]),
            shadow=ft.BoxShadow(
                blur_radius=18,
                spread_radius=1,
                color=ft.Colors.with_opacity(0.10, ft.Colors.BLACK),
                offset=ft.Offset(0, 6),
            ),
            height=aircraft_info_height,
        )

        unused_route_snapshot_card = glass_card(
            "Route Snapshot",
            ft.Column(
                spacing=12,
                controls=[
                    ft.Text(home_route_label, size=24, weight=ft.FontWeight.W_800, color=tokens["text"]),
                    ft.Row(
                        wrap=True,
                        spacing=12,
                        controls=[
                            home_stat_tile("Distance", f"{home_route_nm:,.0f} NM" if home_route_nm else "—", "great circle", width=150),
                            home_stat_tile("ETE", home_ete_label, "at 480 kt", width=150),
                            home_stat_tile("PAX", pax_value, "seats loaded", width=150),
                        ],
                    ),
                ],
            ),
            height=250,
        )

        readiness_items = [
            ("Airline", bool(state.airline), current_airline_label()),
            ("Aircraft", bool(state.aircraft), current_aircraft_label()),
            ("Route", bool(home_origin_icao and home_destination_icao), home_route_label),
            ("Seats", bool(configured_seats), f"{configured_seats} configured" if configured_seats else "not generated"),
            ("Baggage", bool((bag_payload_weight_summary_text.value or "").find("—") < 0), "payload ready" if (bag_payload_weight_summary_text.value or "").find("—") < 0 else "not calculated"),
        ]
        readiness_controls = []
        for label, done, detail in readiness_items:
            readiness_controls.append(
                ft.Row(
                    spacing=10,
                    controls=[
                        ft.Icon(ft.Icons.CHECK_CIRCLE if done else ft.Icons.RADIO_BUTTON_UNCHECKED, size=18, color=tokens["accent"] if done else tokens["muted"]),
                        ft.Text(label, width=78, size=12, color=tokens["text"], weight=ft.FontWeight.W_700),
                        ft.Text(detail, size=12, color=tokens["muted"]),
                    ],
                )
            )
        readiness_card = glass_card(
            "Flight Readiness",
            ft.Column(spacing=10, controls=readiness_controls),
            height=250,
        )

        next_flight_card = glass_card(
            "Next Planned Flight",
            ft.Column(
                spacing=10,
                controls=[
                    ft.Text(next_route or "—", size=22, weight=ft.FontWeight.W_800, color=tokens["text"]),
                    ft.Text(next_airline or "—", size=13, color=tokens["muted"]),
                    ft.Text(next_time or "—", size=13, color=tokens["muted"]),
                ],
            ),
            height=190,
        )

        today_schedule_card = glass_card(
            "Today Schedule",
            ft.Column(
                spacing=10,
                controls=[
                    ft.Text(today_schedule_heading(), size=20, weight=ft.FontWeight.W_800, color=tokens["text"]),
                    ft.Text("Next flight: " + (next_route if next_entry else "—"), size=12, color=tokens["muted"]),
                ],
            ),
            height=190,
        )

        HOME_RAMP_STATUS_LABELS = {
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
        HOME_RAMP_STATUS_ICONS = {
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

        def ensure_home_ramp_status_data():
            for phase_name in ("departure", "arrival"):
                current = getattr(state, f"ramp_{phase_name}_statuses", None)
                if not isinstance(current, dict):
                    current = {}
                    setattr(state, f"ramp_{phase_name}_statuses", current)
                for item_key in HOME_RAMP_STATUS_LABELS[phase_name]:
                    current.setdefault(item_key, "idle")

        def home_active_ramp_phase() -> str:
            phase = getattr(state, "ramp_status_phase", "departure")
            if phase not in ("departure", "arrival"):
                phase = "departure"
                state.ramp_status_phase = phase
            return phase

        def set_home_ramp_phase(phase: str):
            if phase in ("departure", "arrival"):
                state.ramp_status_phase = phase
                refresh_ui()

        def reset_home_ramp_phase(e=None):
            ensure_home_ramp_status_data()
            phase = home_active_ramp_phase()
            status_map = getattr(state, f"ramp_{phase}_statuses")
            for key in HOME_RAMP_STATUS_LABELS[phase]:
                status_map[key] = "idle"
            refresh_ui()

        def next_home_ramp_status_value(current_value: str) -> str:
            if current_value == "idle":
                return "progress"
            if current_value == "progress":
                return "done"
            return "idle"

        def home_ramp_icon(item_key: str) -> ft.Control:
            icon_value = getattr(ft.Icons, HOME_RAMP_STATUS_ICONS.get(item_key, "CHECK_CIRCLE_OUTLINE"), None)
            return ft.Icon(icon_value, size=15, color=tokens["accent"]) if icon_value else ft.Text("•", size=16, weight=ft.FontWeight.W_900, color=tokens["accent"])

        def home_ramp_phase_chip(label: str, phase: str) -> ft.Control:
            active = home_active_ramp_phase() == phase
            return ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda e, target_phase=phase: set_home_ramp_phase(target_phase),
                content=ft.Container(
                    padding=ft.padding.symmetric(horizontal=11, vertical=7),
                    border_radius=999,
                    bgcolor=ft.Colors.with_opacity(0.20 if active else 0.06, tokens["accent"] if active else tokens["muted"]),
                    border=ft.border.all(1, ft.Colors.with_opacity(0.34 if active else 0.12, tokens["accent"] if active else tokens["muted"])),
                    content=ft.Text(label, size=10, weight=ft.FontWeight.W_800 if active else ft.FontWeight.W_600, color=tokens["text"]),
                ),
            )

        def home_ramp_status_button(phase: str, item_key: str) -> ft.Control:
            ensure_home_ramp_status_data()
            status_map = getattr(state, f"ramp_{phase}_statuses")
            current_value = status_map.get(item_key, "idle")
            if current_value == "done":
                label, status_color, fill_opacity, border_opacity = "COMPLETE", ft.Colors.GREEN_300, 0.18, 0.48
            elif current_value == "progress":
                label, status_color, fill_opacity, border_opacity = "IN PROGRESS", tokens["accent"], 0.18, 0.46
            else:
                label, status_color, fill_opacity, border_opacity = "STANDBY", tokens["muted"], 0.07, 0.14

            def cycle_status(e=None, target_phase=phase, target_key=item_key):
                ensure_home_ramp_status_data()
                target_map = getattr(state, f"ramp_{target_phase}_statuses")
                target_map[target_key] = next_home_ramp_status_value(target_map.get(target_key, "idle"))
                refresh_ui()

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
                    content=ft.Text(label, size=9, weight=ft.FontWeight.W_900, color=status_color, text_align=ft.TextAlign.CENTER),
                ),
            )

        def home_ramp_status_row(phase: str, item_key: str, label: str) -> ft.Control:
            ensure_home_ramp_status_data()
            status_map = getattr(state, f"ramp_{phase}_statuses")
            item_status = status_map.get(item_key, "idle")
            status_color = ft.Colors.GREEN_300 if item_status == "done" else tokens["accent"] if item_status == "progress" else ft.Colors.WHITE
            return ft.Container(
                height=36,
                padding=ft.padding.only(left=9, right=8, top=4, bottom=4),
                border_radius=14,
                bgcolor=ft.Colors.with_opacity(0.12 if item_status == "done" else 0.08 if item_status == "progress" else 0.045, status_color),
                border=ft.border.all(1, ft.Colors.with_opacity(0.30 if item_status in ("done", "progress") else 0.10, ft.Colors.GREEN_300 if item_status == "done" else tokens["accent"] if item_status == "progress" else tokens["card_border"])),
                content=ft.Row(
                    spacing=9,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(width=26, height=26, border_radius=9, alignment=ft.Alignment(0, 0), bgcolor=ft.Colors.with_opacity(0.10, tokens["accent"]), content=home_ramp_icon(item_key)),
                        ft.Container(expand=True, content=ft.Text(label, size=12, weight=ft.FontWeight.W_700, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)),
                        home_ramp_status_button(phase, item_key),
                    ],
                ),
            )

        def home_ramp_status_card() -> ft.Control:
            ensure_home_ramp_status_data()
            phase = home_active_ramp_phase()
            labels = HOME_RAMP_STATUS_LABELS[phase]
            status_map = getattr(state, f"ramp_{phase}_statuses")
            completed_count = sum(1 for key in labels if status_map.get(key) == "done")
            progress_count = sum(1 for key in labels if status_map.get(key) == "progress")
            active_label = "Departure ramp" if phase == "departure" else "Arrival ramp"
            return glass_card_with_background(
                "Ramp Status",
                ft.Column(
                    spacing=7,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Text(f"{active_label} • {progress_count} in process • {completed_count}/{len(labels)} done", size=10, color=tokens["muted"]),
                                ft.Row(spacing=6, controls=[home_ramp_phase_chip("Departure", "departure"), home_ramp_phase_chip("Arrival", "arrival")]),
                            ],
                        ),
                        ft.Container(height=1, bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.WHITE)),
                        ft.Row(
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Container(expand=True, content=ft.Text("Checklist", size=10, color=tokens["muted"], weight=ft.FontWeight.W_700)),
                                ft.Container(width=112, alignment=ft.Alignment(0, 0), content=ft.Text("Status", size=10, color=tokens["muted"], weight=ft.FontWeight.W_700)),
                            ],
                        ),
                        ft.Column(spacing=6, controls=[home_ramp_status_row(phase, key, label) for key, label in labels.items()]),
                        ft.Row(alignment=ft.MainAxisAlignment.END, controls=[ft.TextButton("Reset", on_click=reset_home_ramp_phase)]),
                    ],
                ),
                height=440,
                bgcolor_override=home_info_fill_bg,
            )

        return build_tab_page(
            "HOME",
            ft.Container(
                expand=True,
                padding=18,
                content=ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=16,
                    controls=[
                        ft.Row(
                            spacing=14,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                            controls=[
                                ft.Column(width=520, spacing=14, controls=[ft.Container(width=520, height=375, content=greeting_card), ft.Container(width=520, content=next_flight_card)]),
                                ft.Column(width=520, spacing=14, controls=[ft.Container(width=520, height=airline_info_height, content=airline_info_card), ft.Container(width=520, height=440, content=home_ramp_status_card())]),
                                ft.Column(width=700, spacing=14, controls=[ft.Container(width=700, height=aircraft_info_height, content=secondary_info_card)]),
                            ],
                        ),
                    ],
                ),
            ),
            overlay_opacity=0.08,
        )



    def premium_summary_chip(label: str, value: str, width: int = 160) -> ft.Control:
        return ft.Container(
            width=width,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            border_radius=16,
            bgcolor=ft.Colors.with_opacity(0.34, tokens["subpanel"]),
            border=ft.border.all(1, ft.Colors.with_opacity(0.28, ft.Colors.WHITE)),
            content=ft.Column(
                tight=True,
                spacing=4,
                controls=[
                    ft.Text(label, size=11, color=tokens["muted"]),
                    ft.Text(value or "—", size=14, weight=ft.FontWeight.W_700, color=tokens["text"]),
                ],
            ),
        )

    def apply_airport_weather_glass_style(controls: List[ft.Control]):
        glass_fill = ft.Colors.with_opacity(0.30, tokens["input_bg"])
        glass_border = ft.Colors.with_opacity(0.34, ft.Colors.WHITE)
        for ctrl in controls:
            try:
                ctrl.filled = True
            except Exception:
                pass
            try:
                ctrl.bgcolor = glass_fill
            except Exception:
                pass
            try:
                ctrl.fill_color = glass_fill
            except Exception:
                pass
            try:
                ctrl.border_color = glass_border
            except Exception:
                pass
            try:
                ctrl.focused_border_color = ft.Colors.with_opacity(0.78, tokens["accent"])
            except Exception:
                pass
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


    def takeoff_view():
        professional_info = bool(getattr(state, "professional_info_enabled", False))
        apply_airport_weather_glass_style([
            takeoff_departure_icao_tf,
            takeoff_gate_tf,
            takeoff_terminal_tf,
            takeoff_elevation_tf,
            takeoff_oat_tf,
            takeoff_qnh_tf,
            takeoff_wind_dir_tf,
            takeoff_wind_speed_tf,
            takeoff_wind_gust_tf,
            takeoff_raw_metar_tf,
        ])
        takeoff_airport_code_for_background = (takeoff_departure_icao_tf.value or state.departure or "").strip().upper()
        airport_weather_card = airport_background_glass_card(
            "Airport and Weather",
            ft.Column(
                spacing=14,
                controls=[
                    ft.Row(
                        wrap=True,
                        spacing=12,
                        run_spacing=12,
                        controls=[
                            premium_summary_chip("Airline", current_airline_label(), width=160),
                            premium_summary_chip("Aircraft", current_aircraft_label(), width=170),
                            premium_summary_chip("Departure", (takeoff_departure_icao_tf.value or state.departure or '—').strip().upper() or '—', width=140),
                        ],
                    ),
                    ft.Row(wrap=True, spacing=12, controls=[takeoff_departure_icao_tf, takeoff_gate_tf, takeoff_terminal_tf, takeoff_elevation_tf, takeoff_oat_tf, takeoff_qnh_tf]),
                    ft.Row(wrap=True, spacing=12, controls=[takeoff_wind_dir_tf, takeoff_wind_speed_tf, takeoff_wind_gust_tf]),
                    ft.Row(
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.ElevatedButton("Fetch METAR", on_click=do_fetch_takeoff_metar, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                            takeoff_metar_status_text,
                        ],
                    ),
                    takeoff_raw_metar_tf,
                ],
            ),
            airport_code=takeoff_airport_code_for_background,
            fallback_key="origin",
            height=470,
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

        takeoff_alerts_card = glass_card(
            "Warnings",
            ft.Column(
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[takeoff_warning_host],
            ),
            height=170,
        )

        live_clock_card = glass_card(
            "Local Clock",
            ft.Column(
                spacing=12,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    takeoff_date_text,
                    takeoff_time_text,
                ],
            ),
            height=170,
        )

        weight_actions_card = glass_card(
            "Weight and Actions",
            ft.Column(
                spacing=12,
                controls=[
                    takeoff_weight_tf,
                    takeoff_mtow_value_text,
                    ft.Divider(height=8, opacity=0.10),
                    ft.Row(
                        wrap=True,
                        spacing=10,
                        controls=[
                            ft.ElevatedButton("Compute", on_click=do_compute_takeoff, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                            ft.OutlinedButton("Reset", on_click=do_reset_takeoff),
                            ft.OutlinedButton("Save", on_click=do_save_takeoff_log),
                        ],
                    ),
                    takeoff_status_text,
                ],
            ),
            height=310,
        )

        speeds_card = glass_card_with_background(
            "Performance Speeds",
            ft.Column(spacing=12, controls=[takeoff_vs_text, takeoff_v1_text, takeoff_vr_text, takeoff_v2_text]),
            height=300,
            bg_key="takeoff_performance_speeds",
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

        takeoff_climb_card = glass_card(
            "Climb Estimates",
            ft.Column(spacing=12, controls=[takeoff_climb_initial_text, takeoff_climb_enroute_text, takeoff_climb_high_text]),
            height=270,
        )

        fuel_card = glass_card(
            "Fuel Planning",
            ft.Column(
                spacing=14,
                controls=[
                    ft.Row(
                        wrap=True,
                        spacing=18,
                        run_spacing=18,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Container(
                                width=560,
                                content=ft.Column(
                                    spacing=12,
                                    controls=[
                                        takeoff_fuel_aircraft_text,
                                        takeoff_fuel_engine_text,
                                        takeoff_fuel_assumptions_text,
                                        ft.Text(
                                            "Enter route distance, passengers, baggage, and cargo. Taxi fuel is fixed in the model.",
                                            size=12,
                                            color=tokens["muted"],
                                        ),
                                        ft.Row(
                                            wrap=True,
                                            spacing=12,
                                            controls=[takeoff_route_distance_tf, takeoff_fuel_passengers_tf, takeoff_fuel_baggage_tf, takeoff_fuel_cargo_tf],
                                        ),
                                        ft.Row(
                                            wrap=True,
                                            spacing=10,
                                            controls=[
                                                ft.ElevatedButton("Compute Fuel", on_click=do_compute_fuel, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                                                takeoff_fuel_status_text,
                                            ],
                                        ),
                                    ],
                                ),
                            ),
                            ft.Container(
                                width=360,
                                content=ft.Column(
                                    spacing=8,
                                    controls=[
                                        takeoff_trip_fuel_text,
                                        takeoff_block_fuel_text,
                                        takeoff_ete_text,
                                        takeoff_burn_rate_text,
                                        takeoff_fuel_breakdown_text,
                                        takeoff_recommended_tow_text,
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )

        top_right_controls: List[ft.Control] = []
        if professional_info:
            top_right_controls.append(runway_config_card)
        top_right_controls.append(
            ft.Row(
                wrap=True,
                spacing=16,
                run_spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Container(width=330, content=takeoff_alerts_card),
                    ft.Container(width=330, content=live_clock_card),
                ],
            )
        )

        top_right_stack = ft.Column(
            spacing=16,
            controls=top_right_controls,
        )

        takeoff_performance_controls: List[ft.Control] = [
            ft.Container(width=280, content=weight_actions_card),
            ft.Container(width=300, content=speeds_card),
            ft.Container(width=260, content=takeoff_climb_card),
        ]
        if professional_info:
            takeoff_performance_controls.extend(
                [
                    ft.Container(width=260, content=distances_card),
                    ft.Container(width=260, content=atmosphere_card),
                ]
            )

        performance_cards_row = ft.Row(
            wrap=True,
            spacing=16,
            run_spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=takeoff_performance_controls,
        )

        return ft.Container(
            expand=True,
            padding=18,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=16,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Row(
                        wrap=True,
                        spacing=16,
                        run_spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Container(width=760, content=airport_weather_card),
                            ft.Container(width=760, content=top_right_stack),
                        ],
                    ),
                    performance_cards_row,
                    fuel_card,
                ],
            ),
        )


    def landing_view():
        professional_info = bool(getattr(state, "professional_info_enabled", False))
        apply_airport_weather_glass_style([
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
        ])
        landing_airport_code_for_background = (landing_arrival_icao_tf.value or state.arrival or "").strip().upper()
        airport_weather_card = airport_background_glass_card(
            "Airport and Weather",
            ft.Column(
                spacing=14,
                controls=[
                    ft.Row(
                        wrap=True,
                        spacing=12,
                        run_spacing=12,
                        controls=[
                            premium_summary_chip("Airline", current_airline_label(), width=160),
                            premium_summary_chip("Aircraft", current_aircraft_label(), width=170),
                            premium_summary_chip("Arrival", (landing_arrival_icao_tf.value or state.arrival or '—').strip().upper() or '—', width=140),
                        ],
                    ),
                    ft.Row(wrap=True, spacing=12, controls=[landing_arrival_icao_tf, landing_gate_tf, landing_terminal_tf, landing_elevation_tf, landing_oat_tf, landing_qnh_tf]),
                    ft.Row(wrap=True, spacing=12, controls=[landing_wind_dir_tf, landing_wind_speed_tf, landing_wind_gust_tf]),
                    ft.Row(
                        wrap=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.ElevatedButton("Fetch METAR", on_click=do_fetch_landing_metar, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                            landing_metar_status_text,
                        ],
                    ),
                    landing_raw_metar_tf,
                ],
            ),
            airport_code=landing_airport_code_for_background,
            fallback_key="destination",
            height=470,
        )

        landing_aircraft_chip = ft.Container(
            width=230,
            padding=12,
            border_radius=16,
            bgcolor=tokens["subpanel"],
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

        landing_alerts_card = glass_card(
            "Warnings",
            ft.Column(
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[landing_warning_host],
            ),
            height=170,
        )

        landing_local_clock_card = glass_card(
            "Local Clock",
            ft.Column(
                spacing=12,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[landing_date_text, landing_time_text],
            ),
            height=170,
        )

        landing_weight_actions_card = glass_card(
            "Weight and Actions",
            ft.Column(
                spacing=12,
                controls=[
                    landing_weight_tf,
                    landing_mlw_value_text,
                    ft.Divider(height=8, opacity=0.10),
                    ft.Row(
                        wrap=True,
                        spacing=10,
                        controls=[
                            ft.ElevatedButton("Compute", on_click=do_compute_landing, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                            ft.OutlinedButton("Reset", on_click=do_reset_landing),
                            ft.OutlinedButton("Save", on_click=do_save_landing_log),
                        ],
                    ),
                    landing_status_text,
                ],
            ),
            height=310,
        )

        landing_speeds_card = glass_card_with_background(
            "Approach Speeds",
            ft.Column(spacing=12, controls=[landing_vs_text, landing_vref_text, landing_vapp_text, landing_weight_ratio_text]),
            height=300,
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
                spacing=12,
                controls=[
                    ft.Row(wrap=True, spacing=12, controls=[landing_vs_calc_alt_tf, landing_vs_calc_ete_tf]),
                    ft.Row(
                        wrap=True,
                        spacing=10,
                        controls=[
                            ft.ElevatedButton("Calc V/S", on_click=do_calc_landing_vs, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                        ],
                    ),
                    landing_vs_calc_result_text,
                ],
            ),
        )

        top_right_controls: List[ft.Control] = []
        if professional_info:
            top_right_controls.append(runway_config_card)
        top_right_controls.append(
            ft.Row(
                wrap=True,
                spacing=16,
                run_spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Container(width=330, content=landing_alerts_card),
                    ft.Container(width=330, content=landing_local_clock_card),
                ],
            )
        )

        top_right_stack = ft.Column(
            spacing=16,
            controls=top_right_controls,
        )

        landing_performance_controls: List[ft.Control] = [
            ft.Container(width=280, content=landing_weight_actions_card),
            ft.Container(width=300, content=landing_speeds_card),
        ]
        if professional_info:
            landing_performance_controls.extend(
                [
                    ft.Container(width=260, content=landing_distance_card),
                    ft.Container(width=260, content=landing_wind_card),
                    ft.Container(width=260, content=landing_descent_card),
                ]
            )

        performance_cards_row = ft.Row(
            wrap=True,
            spacing=16,
            run_spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=landing_performance_controls,
        )

        return ft.Container(
            expand=True,
            padding=18,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=16,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Row(
                        wrap=True,
                        spacing=16,
                        run_spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Container(width=760, content=airport_weather_card),
                            ft.Container(width=760, content=top_right_stack),
                        ],
                    ),
                    performance_cards_row,
                    ft.Row(
                        wrap=True,
                        spacing=16,
                        run_spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Container(width=600, content=landing_vs_calc_card),
                        ],
                    ),
                ],
            ),
        )


    def baggage_view():
        def baggage_input_panel():
            return ft.Container(
                width=390,
                padding=18,
                border_radius=22,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                bgcolor=ft.Colors.TRANSPARENT if card_background_src("baggage") else tokens["panel"],
                border=ft.border.all(1, tokens["card_border"]),
                image=ft.DecorationImage(src=card_background_src("baggage"), fit=ft.BoxFit.COVER, opacity=0.32) if card_background_src("baggage") else None,
                content=ft.Column(
                    spacing=14,
                    controls=[
                        ft.Text("Baggage", size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                        ft.Divider(height=8, opacity=0.12),
                        ft.Text("Passenger baggage inputs", size=12, color=tokens["muted"]),
                        bag_pax_tf,
                        bag_carry_on_tf,
                        bag_checked_kg_per_pax_tf,
                        ft.Row(
                            wrap=True,
                            spacing=10,
                            controls=[
                                ft.ElevatedButton("Calculate", on_click=do_baggage_calc, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                                ft.OutlinedButton("Reset", on_click=reset_baggage_form),
                            ],
                        ),
                        bag_status_text,
                    ],
                ),
            )

        def cargo_input_panel():
            return ft.Container(
                width=390,
                padding=18,
                border_radius=22,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                bgcolor=ft.Colors.TRANSPARENT if card_background_src("cargo") else tokens["panel"],
                border=ft.border.all(1, tokens["card_border"]),
                image=ft.DecorationImage(src=card_background_src("cargo"), fit=ft.BoxFit.COVER, opacity=0.32) if card_background_src("cargo") else None,
                content=ft.Column(
                    spacing=14,
                    controls=[
                        ft.Text("Cargo", size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                        ft.Divider(height=8, opacity=0.12),
                        ft.Text("Add extra cargo mass carried in the hold.", size=12, color=tokens["muted"]),
                        cargo_weight_tf,
                        ft.Container(
                            padding=14,
                            border_radius=16,
                            bgcolor=tokens["subpanel"],
                            border=ft.border.all(1, tokens["card_border"]),
                            content=ft.Column(
                                spacing=6,
                                controls=[
                                    ft.Text("Cargo note", size=12, color=tokens["muted"]),
                                    ft.Text("This value is added to baggage weight to create total payload.", size=12, color=tokens["text"]),
                                ],
                            ),
                        ),
                    ],
                ),
            )

        def payload_result_panel():
            return ft.Container(
                width=440,
                padding=18,
                border_radius=22,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                bgcolor=ft.Colors.TRANSPARENT if card_background_src("calculated_weight") else tokens["panel"],
                border=ft.border.all(1, tokens["card_border"]),
                image=ft.DecorationImage(src=card_background_src("calculated_weight"), fit=ft.BoxFit.COVER, opacity=0.32) if card_background_src("calculated_weight") else None,
                content=ft.Column(
                    spacing=12,
                    controls=[
                        ft.Text("Calculated Weight", size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                        ft.Divider(height=8, opacity=0.12),
                        bag_baggage_weight_summary_text,
                        bag_cargo_weight_summary_text,
                        ft.Divider(height=8, opacity=0.12),
                        bag_payload_weight_summary_text,
                        ft.Container(
                            padding=14,
                            border_radius=16,
                            bgcolor=tokens["subpanel"],
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

        return ft.Container(
            expand=True,
            bgcolor=ft.Colors.TRANSPARENT,
            padding=18,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=16,
                controls=[
                    ft.Row(
                        wrap=True,
                        spacing=16,
                        run_spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            baggage_input_panel(),
                            cargo_input_panel(),
                            payload_result_panel(),
                        ],
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
            "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
            "© OpenStreetMap contributors, © CARTO",
            "Fallback Dark",
        )


    def map_view():
        origin_icao = (state.departure or takeoff_departure_icao_tf.value or "").strip().upper()
        destination_icao = (state.arrival or landing_arrival_icao_tf.value or "").strip().upper()
        origin_icao = normalize_airport_code(origin_icao) or origin_icao
        destination_icao = normalize_airport_code(destination_icao) or destination_icao
        if origin_icao:
            state.departure = origin_icao
        if destination_icao:
            state.arrival = destination_icao
        origin_coord = resolve_airport_coordinates(origin_icao)
        destination_coord = resolve_airport_coordinates(destination_icao)
        route_nm = route_distance_nm(origin_icao, destination_icao)

        def midpoint_coordinates(origin: tuple[float, float], destination: tuple[float, float]) -> tuple[float, float]:
            return ((origin[0] + destination[0]) / 2.0, (origin[1] + destination[1]) / 2.0)

        def default_route_zoom(distance_nm: Optional[float]) -> float:
            if distance_nm is None:
                return 2.5
            if distance_nm < 200:
                return 7.0
            if distance_nm < 500:
                return 6.0
            if distance_nm < 1000:
                return 5.0
            if distance_nm < 2000:
                return 4.2
            if distance_nm < 3500:
                return 3.7
            if distance_nm < 5500:
                return 3.1
            return 2.5

        def estimate_map_flight_time_hours(distance_nm_value: Optional[float]) -> Optional[float]:
            if not distance_nm_value:
                return None
            fuel_plan = state.takeoff_last_result.get("fuel_plan", {}) if state.takeoff_last_result else {}
            ete_from_plan = fuel_plan.get("ete_hours")
            if isinstance(ete_from_plan, (int, float)) and ete_from_plan > 0:
                return float(ete_from_plan)
            try:
                cruise_gs = float((takeoff_cruise_gs_tf.value or "").strip())
            except Exception:
                cruise_gs = 0.0
            if cruise_gs <= 0:
                cruise_gs = resolve_takeoff_fuel_config(takeoff_aircraft_dd.value or state.aircraft).cruise_gs_kt_default
            return (distance_nm_value / cruise_gs) if cruise_gs > 0 else None

        def build_airport_marker(label: str, icao: str, color: str) -> ft.Control:
            marker_box_width = 170
            marker_box_height = 64
            dot_size = 18
            pill_width = 78
            pill_height = 30
            center_x = marker_box_width / 2
            center_y = marker_box_height / 2
            pill_left = int(center_x + 12)
            pill_top = int(center_y - (pill_height / 2))
            dot_left = int(center_x - (dot_size / 2))
            dot_top = int(center_y - (dot_size / 2))

            return ft.Container(
                width=marker_box_width,
                height=marker_box_height,
                tooltip=f"{label} {icao}",
                bgcolor=ft.Colors.TRANSPARENT,
                content=ft.Stack(
                    width=marker_box_width,
                    height=marker_box_height,
                    controls=[
                        ft.Container(
                            left=dot_left,
                            top=dot_top,
                            width=dot_size,
                            height=dot_size,
                            border_radius=999,
                            bgcolor=color,
                            border=ft.border.all(3, ft.Colors.WHITE),
                            shadow=ft.BoxShadow(
                                blur_radius=10,
                                spread_radius=0,
                                color=ft.Colors.with_opacity(0.25, ft.Colors.BLACK),
                                offset=ft.Offset(0, 3),
                            ),
                        ),
                        ft.Container(
                            left=pill_left,
                            top=pill_top,
                            width=pill_width,
                            height=pill_height,
                            alignment=ft.Alignment(0, 0),
                            padding=ft.padding.symmetric(horizontal=10, vertical=5),
                            border_radius=999,
                            bgcolor=tokens["panel"],
                            border=ft.border.all(1, tokens["card_border"]),
                            content=ft.Text(
                                icao,
                                size=11,
                                weight=ft.FontWeight.W_700,
                                color=tokens["text"],
                                text_align=ft.TextAlign.CENTER,
                                no_wrap=True,
                            ),
                        ),
                    ],
                ),
            )

        flight_time_hours = estimate_map_flight_time_hours(route_nm)
        flight_time_label = format_hours_to_hm(flight_time_hours) if flight_time_hours is not None else "Awaiting route"
        route_label = f"{origin_icao or '—'} → {destination_icao or '—'}"
        distance_label = f"{route_nm:.0f} NM" if route_nm is not None else "Awaiting airports"
        camera_status = ft.Text(
            f"Route overview: {route_label} • {distance_label} • Flight time {flight_time_label}",
            color=tokens["muted"],
        )

        def mapcn_route_query() -> str:
            params: Dict[str, object] = {
                "route_ready": "1" if origin_coord and destination_coord else "0",
                "airline": state.airline or "Airline not selected",
                "aircraft": state.aircraft or takeoff_aircraft_dd.value or "Aircraft not selected",
                "flight_time": flight_time_label if flight_time_label != "Awaiting route" else "",
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
            return urllib.parse.urlencode(params)

        def mapcn_local_url() -> Optional[str]:
            web_map_index = base_dir / "globe-gl-test-web" / "dist" / "index.html"
            if not web_map_index.exists():
                return None
            query = mapcn_route_query()
            base_url = web_map_index.as_uri()
            return f"{base_url}#{query}" if query else base_url

        def ensure_mapcn_webview():
            url = mapcn_local_url()
            if not url:
                close_mapcn_webview()
                return False

            existing = getattr(state, "mapcn_webview_process", None)
            if existing is not None:
                try:
                    if existing.poll() is None:
                        if getattr(state, "mapcn_webview_url", None) == url:
                            return True
                        close_mapcn_webview()
                except Exception:
                    pass
                setattr(state, "mapcn_webview_process", None)

            if getattr(sys, "frozen", False):
                command = [sys.executable, "--globe-webview", "--attach", "--url", url, "--parent-title", page.title]
            else:
                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--globe-webview",
                    "--attach",
                    "--url",
                    url,
                    "--parent-title",
                    page.title,
                ]
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(base_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                setattr(state, "mapcn_webview_process", process)
                setattr(state, "mapcn_webview_url", url)
                return True
            except Exception:
                return False

        ensure_mapcn_webview()

        return ft.Container(
            expand=True,
            bgcolor="#020617",
            alignment=ft.Alignment(0, 0),
            content=ft.Stack(
                expand=True,
                controls=[
                    ft.Container(expand=True, bgcolor="#020617"),
                    ft.Container(
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Column(
                            tight=True,
                            spacing=16,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.ProgressRing(width=42, height=42, stroke_width=3, color=tokens["accent"]),
                                ft.Text(
                                    "Loading the map",
                                    size=18,
                                    weight=ft.FontWeight.W_800,
                                    color=tokens["text"],
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        )

        state.map_style = "dataviz-v4-dark"
        tile_url, map_attribution, active_map_label = active_maptiler_tile_url()
        map_layers = [
            ftm.TileLayer(
                url_template=tile_url,
            ),
            ftm.SimpleAttribution(
                text=map_attribution,
                on_click=lambda e: e.page.launch_url("https://carto.com/"),
            ),
        ]

        map_note = None
        initial_center = ftm.MapLatitudeLongitude(30.0, 20.0)
        initial_zoom = 2.5
        route_center = None

        marker_layer_supported = all(hasattr(ftm, attr) for attr in ["MarkerLayer", "Marker", "MapLatitudeLongitude"])
        polyline_layer_supported = hasattr(ftm, "PolylineLayer") and hasattr(ftm, "MapLatitudeLongitude")
        polyline_marker_supported = hasattr(ftm, "PolylineMarker")
        legacy_polyline_supported = hasattr(ftm, "Polyline")
        dashed_pattern_supported = hasattr(ftm, "DashedStrokePattern")

        if origin_coord and destination_coord:
            mid_lat, mid_lon = midpoint_coordinates(origin_coord, destination_coord)
            route_center = ftm.MapLatitudeLongitude(mid_lat, mid_lon)
            initial_center = route_center
            initial_zoom = default_route_zoom(route_nm)

            if polyline_layer_supported:
                route_coordinates = [
                    ftm.MapLatitudeLongitude(origin_coord[0], origin_coord[1]),
                    ftm.MapLatitudeLongitude(destination_coord[0], destination_coord[1]),
                ]
                if polyline_marker_supported:
                    polyline_kwargs = {
                        "coordinates": route_coordinates,
                        "color": tokens["accent"],
                        "stroke_width": 4,
                    }
                    if dashed_pattern_supported:
                        polyline_kwargs["stroke_pattern"] = ftm.DashedStrokePattern(segments=[50, 20])
                    map_layers.append(
                        ftm.PolylineLayer(
                            polylines=[
                                ftm.PolylineMarker(**polyline_kwargs)
                            ]
                        )
                    )
                elif legacy_polyline_supported:
                    legacy_polyline_kwargs = {
                        "coordinates": route_coordinates,
                        "stroke_width": 4,
                        "color": tokens["accent"],
                    }
                    if dashed_pattern_supported:
                        legacy_polyline_kwargs["stroke_pattern"] = ftm.DashedStrokePattern(segments=[50, 20])
                    map_layers.append(
                        ftm.PolylineLayer(
                            polylines=[
                                ftm.Polyline(**legacy_polyline_kwargs)
                            ]
                        )
                    )
                else:
                    map_note = "This installed flet-map build can show the basemap, but not the route line overlay."
            else:
                map_note = "This installed flet-map build is missing the route overlay layers."

            if marker_layer_supported:
                midpoint_summary = ft.Container(
                    width=320,
                    padding=16,
                    border_radius=18,
                    bgcolor=tokens["panel"],
                    border=ft.border.all(1, tokens["card_border"]),
                    shadow=ft.BoxShadow(
                        blur_radius=16,
                        spread_radius=0,
                        color=ft.Colors.with_opacity(0.16, ft.Colors.BLACK),
                        offset=ft.Offset(0, 5),
                    ),
                    content=ft.Column(
                        spacing=5,
                        controls=[
                            ft.Text(
                                f"Route: {route_label}",
                                size=12,
                                weight=ft.FontWeight.W_800,
                                color=tokens["text"],
                                no_wrap=True,
                            ),
                            ft.Text(f"Distance: {distance_label}", size=11, color=tokens["text"], no_wrap=True),
                            ft.Text(f"Flight time: {flight_time_label}", size=11, color=tokens["text"], no_wrap=True),
                        ],
                    ),
                )
                map_layers.append(
                    ftm.MarkerLayer(
                        markers=[
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(origin_coord[0], origin_coord[1]),
                                width=170,
                                height=64,
                                alignment=ft.Alignment(0, 0),
                                content=build_airport_marker("Origin", origin_icao, tokens["accent"]),
                            ),
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(destination_coord[0], destination_coord[1]),
                                width=170,
                                height=64,
                                alignment=ft.Alignment(0, 0),
                                content=build_airport_marker("Destination", destination_icao, tokens["text"]),
                            ),
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(mid_lat, mid_lon),
                                width=320,
                                height=92,
                                alignment=ft.Alignment(0, 1),
                                content=midpoint_summary,
                            ),
                        ]
                    )
                )
            elif map_note is None:
                map_note = "This installed flet-map build can show the route line, but not the route markers."
        elif origin_coord or destination_coord:
            available_icao = origin_icao if origin_coord else destination_icao
            available_coord = origin_coord if origin_coord else destination_coord
            initial_center = ftm.MapLatitudeLongitude(available_coord[0], available_coord[1])
            initial_zoom = 5.0
            map_note = "Only one airport is available. Set both departure and arrival to draw the full route."
            if marker_layer_supported:
                map_layers.append(
                    ftm.MarkerLayer(
                        markers=[
                            ftm.Marker(
                                coordinates=ftm.MapLatitudeLongitude(available_coord[0], available_coord[1]),
                                width=170,
                                height=64,
                                alignment=ft.Alignment(0, 0),
                                content=build_airport_marker("Airport", available_icao, tokens["accent"]),
                            )
                        ]
                    )
                )
        else:
            map_note = "Set departure and arrival ICAO codes on the Takeoff and Landing pages to draw the active route."

        map_min_zoom = 2.5
        initial_zoom = max(float(initial_zoom or map_min_zoom), map_min_zoom)
        map_kwargs = dict(
            expand=True,
            initial_center=initial_center,
            initial_zoom=initial_zoom,
            interaction_configuration=ftm.InteractionConfiguration(flags=ftm.InteractionFlag.ALL),
            layers=map_layers,
        )
        try:
            world_map = ftm.Map(**map_kwargs, min_zoom=map_min_zoom)
        except TypeError:
            # Older flet-map builds may not support min_zoom. Keep the safe
            # initial/world-view zoom values so the map does not intentionally
            # zoom beyond the visible world boundary.
            world_map = ftm.Map(**map_kwargs)

        async def go_route(e):
            if route_center is not None:
                await world_map.center_on(point=route_center, zoom=default_route_zoom(route_nm))
                camera_status.value = f"Route centered: {route_label} • {distance_label} • Flight time {flight_time_label}"
            elif origin_coord:
                await world_map.center_on(point=ftm.MapLatitudeLongitude(origin_coord[0], origin_coord[1]), zoom=5.0)
                camera_status.value = f"Centered on {origin_icao}"
            elif destination_coord:
                await world_map.center_on(point=ftm.MapLatitudeLongitude(destination_coord[0], destination_coord[1]), zoom=5.0)
                camera_status.value = f"Centered on {destination_icao}"
            else:
                camera_status.value = "Set a departure and arrival to center on the active route."
            page.update()

        async def go_berlin(e):
            await world_map.center_on(point=ftm.MapLatitudeLongitude(52.52, 13.405), zoom=6)
            camera_status.value = "Centered on Berlin"
            page.update()

        async def go_tehran(e):
            await world_map.center_on(point=ftm.MapLatitudeLongitude(35.6892, 51.3890), zoom=6)
            camera_status.value = "Centered on Tehran"
            page.update()

        async def world_view(e):
            await world_map.zoom_to(map_min_zoom)
            camera_status.value = "World view"
            page.update()

        return ft.Container(
            expand=True,
            padding=18,
            content=ft.Column(
                expand=True,
                spacing=12,
                controls=[
                    glass_card(
                        "Map",
                        ft.Column(
                            spacing=12,
                            controls=[
                                ft.Text(
                                    "Dark command-center map. Route markers and route lines stay active.",
                                    size=12,
                                    color=tokens["muted"],
                                ),
                                ft.Row(
                                    wrap=True,
                                    spacing=10,
                                    controls=[
                                        ft.ElevatedButton("Route view", on_click=go_route, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                                        ft.OutlinedButton("World view", on_click=world_view),
                                    ],
                                ),
                                camera_status,
                                ft.Text(
                                    (map_note or f"Active map style: {active_map_label}." + (" Add MAPTILER_API_KEY to enable MapTiler tiles." if not MAPTILER_API_KEY else "")),
                                    size=12,
                                    color=tokens["muted"],
                                ),
                            ],
                        ),
                    ),
                    ft.Container(
                        expand=True,
                        border_radius=18,
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        border=ft.border.all(1, tokens["card_border"]),
                        content=world_map,
                    ),
                ],
            ),
        )

    def calendar_entry_card(entry: dict):
        is_completed = bool(entry.get("completed"))
        status_text = "Completed" if is_completed else "Planned"
        status_color = ft.Colors.GREEN_700 if is_completed else tokens["accent"]
        bg_color = tokens["success_overlay"] if is_completed else tokens["subpanel"]

        return ft.Container(
            padding=16,
            border_radius=18,
            bgcolor=bg_color,
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
                                content=ft.Text(status_text, color=status_color, size=10, weight=ft.FontWeight.W_700),
                            ),
                        ],
                    ),
                    ft.Row(
                        wrap=True,
                        spacing=20,
                        controls=[
                            ft.Text(f"Flight time: {entry.get('flight_time', '—')}", size=11, color=tokens["text"]),
                            ft.Text(f"Origin: {entry.get('origin', '—')}", size=11, color=tokens["text"]),
                            ft.Text(f"Destination: {entry.get('destination', '—')}", size=11, color=tokens["text"]),
                        ],
                    ),
                    ft.Text(f"Notes: {entry.get('notes', '—') or '—'}", size=11, color=tokens["muted"]),
                    ft.Row(
                        wrap=True,
                        spacing=8,
                        controls=[
                            ft.OutlinedButton("Edit", on_click=lambda e, entry_id=entry.get("id"): load_calendar_entry_for_edit(entry_id)),
                            ft.OutlinedButton("Delete", on_click=lambda e, entry_id=entry.get("id"): delete_calendar_entry(entry_id)),
                        ],
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
            refresh_ui()

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
            refresh_ui()

        def clear_calendar_selected_date(e=None):
            if (getattr(state, "calendar_selected_date", "") or "").strip():
                reset_calendar_form()
                refresh_calendar_route_preview()
                refresh_ui()

        def flights_for_date(date_str: str) -> list[dict]:
            return [entry for entry in state.calendar_entries if (entry.get("date") or "") == date_str]

        def planner_compact_card() -> ft.Control:
            return glass_card(
                "Flight Planner",
                ft.Column(
                    spacing=12,
                    controls=[
                        ft.Row(wrap=True, spacing=10, controls=[cal_date_tf, cal_time_tf]),
                        cal_airline_dd,
                        cal_aircraft_dd,
                        ft.Row(wrap=True, spacing=10, controls=[cal_origin_tf, cal_destination_tf]),
                        cal_flight_time_tf,
                        ft.Row(
                            wrap=True,
                            spacing=10,
                            controls=[
                                ft.ElevatedButton(
                                    "Update flight" if state.calendar_editing_id else "Add flight",
                                    on_click=add_or_update_calendar_entry,
                                    bgcolor=tokens["accent"],
                                    color=ft.Colors.WHITE,
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
        calendar_week_count = max(5, len(month_dates) // 7)
        calendar_board_height = 951 + max(0, calendar_week_count - 5) * 158

        cell_w = 146
        normal_cell_h = 152
        expanded_cell_h = 152

        day_headers = ft.Row(
            spacing=10,
            controls=[
                ft.Container(width=cell_w, alignment=ft.Alignment(0, 0), content=ft.Text(day, size=12, weight=ft.FontWeight.W_700, color=tokens["muted"]))
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
            for entry in entries[:2]:
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
            if entry_count > 2:
                compact_info.append(ft.Text(f"+{entry_count - 2} more", size=10, color=tokens["accent"], weight=ft.FontWeight.W_700))
            if not compact_info:
                compact_info.append(ft.Text("No flight", size=9, color=ft.Colors.with_opacity(0.65, tokens["muted"])))

            detail_controls = []
            if is_selected and entries:
                detail_controls = [
                    ft.Divider(height=3, opacity=0.10),
                    ft.Text(f"{entry_count} flight{'s' if entry_count != 1 else ''} selected", size=9, color=tokens["accent"], weight=ft.FontWeight.W_700, no_wrap=True),
                ]
            elif is_selected:
                detail_controls = [
                    ft.Divider(height=3, opacity=0.10),
                    ft.Text("No saved flight", size=9, color=tokens["muted"]),
                ]

            date_cells.append(
                ft.Container(
                    width=cell_w,
                    height=expanded_cell_h if is_selected else normal_cell_h,
                    padding=10,
                    border_radius=18,
                    bgcolor=cell_bg,
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
                            *detail_controls,
                        ],
                    ),
                )
            )

        week_rows: list[ft.Control] = []
        for idx in range(0, len(date_cells), 7):
            week_rows.append(ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.START, controls=date_cells[idx:idx + 7]))

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
                                spacing=10,
                                controls=[
                                    ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, on_click=lambda e: shift_calendar_month(-1), icon_color=tokens["text"]),
                                    ft.Text(month_label, size=26, weight=ft.FontWeight.W_800, color=tokens["text"]),
                                    ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, on_click=lambda e: shift_calendar_month(1), icon_color=tokens["text"]),
                                ],
                            ),
                        ],
                    ),
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        border_radius=24,
                        bgcolor=tokens["panel"],
                        border=ft.border.all(1, tokens["card_border"]),
                        content=ft.Column(spacing=6, controls=[day_headers, *week_rows]),
                    ),
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
                    bgcolor=tokens["subpanel"],
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
                        content=ft.Column(
                            expand=True,
                            spacing=12,
                            scroll=ft.ScrollMode.AUTO,
                            controls=[*entry_controls, ft.Container(height=28)],
                        ),
                    ),
                ],
            ),
            height=calendar_board_height,
        )

        return ft.Container(
            expand=True,
            bgcolor=ft.Colors.TRANSPARENT,
            padding=8,
            content=ft.Column(
                expand=True,
                scroll=None,
                spacing=16,
                controls=[
                    ft.Row(
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Container(width=240, content=planner_compact_card()),
                            ft.Container(width=1140, content=calendar_board),
                            ft.Container(width=390, content=saved_flights_card),
                        ],
                    ),
                ],
            ),
        )


    def log_entry_row(entry: dict, stack_index: int = 0) -> ft.Control:
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

        def toggle_log_detail(e=None, item_id=entry_id):
            if state.log_editing_detail_id == item_id:
                return
            if getattr(state, "log_expanded_id", None) == item_id:
                state.log_expanded_id = None
            else:
                state.log_expanded_id = item_id
            refresh_ui()

        def clean(value, fallback="—"):
            value = "" if value is None else str(value).strip()
            return value if value else fallback

        def start_detail_edit(field_key: str):
            state.log_expanded_id = entry_id
            state.log_editing_detail_id = entry_id
            state.log_editing_detail_field = field_key
            refresh_ui()

        def finish_detail_edit(field_key: str, new_value: str):
            if state.log_editing_detail_id != entry_id or state.log_editing_detail_field != field_key:
                return
            new_value = (new_value or "").strip()

            if field_key == "date" and new_value:
                try:
                    datetime.strptime(new_value, "%Y-%m-%d")
                except ValueError:
                    show_snack("Date must use YYYY-MM-DD.")
                    return
            if field_key in ("time", "arrival_time") and new_value:
                try:
                    datetime.strptime(new_value, "%H:%M")
                except ValueError:
                    show_snack("Time must use HH:MM.")
                    return

            if field_key in ("origin", "destination"):
                stored_value = (normalize_airport_code(new_value) or new_value).strip().upper()
                entry[field_key] = stored_value
                origin_code = (normalize_airport_code(entry.get("origin")) or str(entry.get("origin") or "")).strip().upper()
                destination_code = (normalize_airport_code(entry.get("destination")) or str(entry.get("destination") or "")).strip().upper()
                if origin_code and destination_code:
                    entry["route"] = f"{origin_code} -> {destination_code}"
            else:
                entry[field_key] = new_value

            entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
            entry_id_value = entry.get("id")
            if entry_id_value:
                for idx, item in enumerate(state.calendar_entries):
                    if item.get("id") == entry_id_value:
                        state.calendar_entries[idx] = entry
                        break
            sync_profile_from_calendar_completion()
            save_calendar_entries()
            state.log_editing_detail_id = None
            state.log_editing_detail_field = None
            refresh_ui()

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

        def detail_line(
            label: str,
            value: str,
            width: int = 220,
            field_key: Optional[str] = None,
            edit_value: Optional[str] = None,
        ) -> ft.Control:
            is_editing = (
                bool(field_key)
                and state.log_editing_detail_id == entry_id
                and state.log_editing_detail_field == field_key
            )
            display_value = clean(value)
            editable_value = clean(edit_value, display_value) if edit_value is not None else display_value
            if is_editing:
                edit_field = ft.TextField(
                    value=editable_value,
                    dense=True,
                    text_size=13,
                    border_radius=10,
                    filled=True,
                    bgcolor=tokens["input_bg"],
                    color=tokens["text"],
                    autofocus=True,
                    multiline=width >= 400,
                    min_lines=1,
                    max_lines=3 if width >= 400 else 1,
                )

                def submit_edit(e=None, key=field_key, control=edit_field):
                    finish_detail_edit(key, control.value or "")

                edit_field.on_submit = submit_edit
                edit_field.on_blur = submit_edit
                value_control: ft.Control = edit_field
            else:
                value_control = ft.Text(
                    display_value,
                    size=13,
                    weight=ft.FontWeight.W_700,
                    color=tokens["text"],
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                )

            detail_body = ft.Container(
                width=width,
                padding=ft.padding.symmetric(horizontal=12, vertical=10),
                border_radius=16,
                bgcolor=tokens["subpanel"],
                border=ft.border.all(1, tokens["accent"] if is_editing else tokens["card_border"]),
                content=ft.Column(
                    tight=True,
                    spacing=4,
                    controls=[
                        ft.Text(label, size=11, color=tokens["muted"]),
                        value_control,
                    ],
                ),
            )
            if not field_key or is_editing:
                return detail_body
            return ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda e, key=field_key: start_detail_edit(key),
                on_double_tap=lambda e, key=field_key: start_detail_edit(key),
                content=detail_body,
            )

        def barcode_visual(width: int = 250, height: int = 58) -> ft.Control:
            bars = []
            pattern = [3, 1, 2, 1, 5, 2, 1, 3, 1, 4, 2, 1, 3, 2, 5, 1, 1, 4, 2, 2, 1, 5, 3, 1, 2, 4]
            for i, bar_width in enumerate(pattern):
                bars.append(
                    ft.Container(
                        width=bar_width,
                        height=height,
                        bgcolor=pass_text if i % 3 != 1 else tokens["muted"],
                    )
                )
            return ft.Container(
                width=width,
                height=height,
                padding=ft.padding.symmetric(horizontal=8, vertical=6),
                bgcolor=tokens["subpanel"],
                border_radius=8,
                border=ft.border.all(1, pass_line),
                content=ft.Row(spacing=3, alignment=ft.MainAxisAlignment.CENTER, controls=bars),
            )

        def pass_info_block(label: str, value: str, width: int = 120) -> ft.Control:
            return ft.Container(
                width=width,
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
        notes = clean(entry.get("notes"))
        flight_number = clean(entry.get("flight_number"), clean(state.flight_number, "FMS —"))
        block_fuel_note = note_value("Block fuel")
        ete_note = note_value("ETE")
        metar_note = note_value("METAR")

        fuel_plan = state.takeoff_last_result.get("fuel_plan", {}) if isinstance(getattr(state, "takeoff_last_result", {}), dict) else {}
        planned_fuel = clean(entry.get("planned_fuel"), "")
        if not planned_fuel and isinstance(fuel_plan, dict) and fuel_plan.get("block_fuel_kg"):
            try:
                planned_fuel = f"{float(fuel_plan.get('block_fuel_kg')):,.0f} kg"
            except Exception:
                planned_fuel = "—"
        if not planned_fuel and block_fuel_note != "—":
            planned_fuel = block_fuel_note.replace("Block fuel", "").strip(" :")

        fuel_ete = clean(entry.get("fuel_ete"), ete_note)
        origin_weather = clean(entry.get("origin_weather"), metar_note)

        origin_name = airport_display_name(origin)
        destination_name = airport_display_name(destination)
        passenger_name = clean(state.pilot_name, "Pilot")

        header_height = 190 if is_expanded else 100
        collapsed_code_size = 24
        expanded_code_size = 32
        code_size = expanded_code_size if is_expanded else collapsed_code_size
        city_size = 13 if is_expanded else 11

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
                        pass_info_block("Passenger", passenger_name.upper(), 150),
                        pass_info_block("Flight", flight_number.upper(), 105),
                        pass_info_block("Aircraft", aircraft.upper(), 170),
                        pass_info_block("Date", departure_date, 120),
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

        boarding_pass_header_bg_src = card_background_src("boarding_pass_header")

        header_left = ft.Container(
            height=header_height,
            expand=True,
            padding=ft.padding.only(left=22, top=(16 if is_expanded else 12), right=22, bottom=12),
            bgcolor=pass_bg,
            image=ft.DecorationImage(src=boarding_pass_header_bg_src, fit=ft.BoxFit.COVER, opacity=0.36) if boarding_pass_header_bg_src else None,
            content=ft.Column(
                spacing=(10 if is_expanded else 4),
                alignment=ft.MainAxisAlignment.CENTER if not is_expanded else ft.MainAxisAlignment.START,
                controls=[
                    *left_top_controls,
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(
                                width=230,
                                content=ft.Column(
                                    spacing=0,
                                    controls=[
                                        ft.Text("FROM", size=10, color=pass_muted, weight=ft.FontWeight.W_700),
                                        ft.Text(origin, size=code_size, weight=ft.FontWeight.W_900, color=pass_text),
                                        ft.Text(origin_name.upper(), size=city_size, weight=ft.FontWeight.W_700, color=tokens["muted"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ],
                                ),
                            ),
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
                            ft.Container(
                                width=230,
                                alignment=ft.Alignment(1, 0),
                                content=ft.Column(
                                    horizontal_alignment=ft.CrossAxisAlignment.END,
                                    spacing=0,
                                    controls=[
                                        ft.Text("TO", size=10, color=pass_muted, weight=ft.FontWeight.W_700),
                                        ft.Text(destination, size=code_size, weight=ft.FontWeight.W_900, color=pass_text),
                                        ft.Text(destination_name.upper(), size=city_size, weight=ft.FontWeight.W_700, color=tokens["muted"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    *expanded_bottom_info,
                ],
            ),
        )

        stub_controls = [
            ft.Text("B O A R D I N G   P A S S", size=(18 if is_expanded else 14), weight=ft.FontWeight.W_900, color=pass_text),
            ft.Row(spacing=14, controls=[pass_info_block("FROM", origin, width=100), pass_info_block("TO", destination, width=100)]),
        ]
        if is_expanded:
            stub_controls.extend([
                ft.Row(spacing=14, controls=[pass_info_block("Departure", departure_time, width=100), pass_info_block("Arrival", arrival_time, width=100)]),
                ft.Row(spacing=14, controls=[pass_info_block("Time", flight_time, width=100), pass_info_block("Gate", clean(entry.get("gate"), clean(state.departure_gate)), width=100)]),
            ])

        header_stub = ft.Container(
            width=310,
            height=header_height,
            padding=ft.padding.only(left=20, top=(16 if is_expanded else 12), right=20, bottom=12),
            bgcolor=pass_stub_bg,
            image=ft.DecorationImage(src=boarding_pass_header_bg_src, fit=ft.BoxFit.COVER, opacity=0.36) if boarding_pass_header_bg_src else None,
            content=ft.Column(
                spacing=(10 if is_expanded else 6),
                alignment=ft.MainAxisAlignment.CENTER,
                controls=stub_controls,
            ),
        )

        expanded_details = ft.Container(height=0)
        if is_expanded:
            aircraft_media_card = ft.Container(
                width=320,
                padding=12,
                border_radius=20,
                bgcolor=tokens["subpanel"],
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    spacing=10,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(
                            width=296,
                            height=136,
                            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                            border_radius=16,
                            bgcolor=tokens["panel"],
                            alignment=ft.Alignment(0, 0),
                            content=aircraft_livery_image(airline, aircraft, width=280, height=122),
                        ),
                        barcode_visual(width=280, height=60),
                    ],
                ),
            )

            expanded_details = ft.Container(
                padding=ft.padding.only(left=20, right=20, top=16, bottom=20),
                bgcolor=tokens["panel"],
                border=ft.border.only(top=ft.BorderSide(1, tokens["card_border"])),
                content=ft.Row(
                    spacing=18,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Container(
                            expand=True,
                            content=ft.Column(
                                spacing=14,
                                controls=[
                                    ft.Text("Flight recorder details", size=14, weight=ft.FontWeight.W_600, color=tokens["text"]),
                                    ft.Row(
                                        wrap=True,
                                        spacing=12,
                                        run_spacing=12,
                                        controls=[
                                            detail_line("Departure time", departure_time, field_key="time"),
                                            detail_line("Estimated arrival", arrival_time, field_key="arrival_time"),
                                            detail_line("Flight time", flight_time, field_key="flight_time"),
                                            detail_line("Air pathway", route, field_key="route"),
                                            detail_line("Airline", airline, field_key="airline"),
                                            detail_line("Aircraft", aircraft, field_key="aircraft"),
                                            detail_line("Origin", origin_name, field_key="origin", edit_value=origin),
                                            detail_line("Destination", destination_name, field_key="destination", edit_value=destination),
                                            detail_line("Passengers", clean(entry.get("passengers"), clean(getattr(takeoff_fuel_passengers_tf, "value", ""))), field_key="passengers"),
                                            detail_line("Baggage weight", clean(entry.get("baggage_weight"), clean(getattr(takeoff_fuel_baggage_tf, "value", ""))), field_key="baggage_weight"),
                                            detail_line("Cargo weight", clean(entry.get("cargo_weight"), clean(getattr(takeoff_fuel_cargo_tf, "value", ""))), field_key="cargo_weight"),
                                            detail_line("Planned fuel", planned_fuel, field_key="planned_fuel"),
                                            detail_line("Fuel ETE", fuel_ete, field_key="fuel_ete"),
                                            detail_line("Origin weather / METAR", origin_weather, width=450, field_key="origin_weather"),
                                            detail_line("Destination weather", clean(entry.get("destination_weather")), width=450, field_key="destination_weather"),
                                            detail_line("Notes", notes, width=450, field_key="notes"),
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

        return ft.Container(
            margin=ft.margin.only(top=(-8 if stack_index > 0 and not is_expanded else 0)),
            border_radius=28,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=pass_bg,
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


    def log_view():
        log_entries = get_completed_log_entries()
        summary = summarize_log_entries(log_entries)
        log_controls = [log_entry_row(entry, index) for index, entry in enumerate(log_entries)]
        if not log_controls:
            log_controls = [
                ft.Container(
                    padding=18,
                    border_radius=18,
                    bgcolor=tokens["subpanel"],
                    border=ft.border.all(1, tokens["card_border"]),
                    content=ft.Text("Completed flights from the Calendar tab will appear here.", color=tokens["muted"]),
                )
            ]

        def summary_stat_box(label: str, value: str, subtitle: str) -> ft.Control:
            return ft.Container(
                width=220,
                padding=ft.padding.symmetric(horizontal=14, vertical=12),
                border_radius=16,
                bgcolor=tokens["subpanel"],
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
                    ft.Column(spacing=0, tight=True, controls=log_controls),
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
                width=250,
                height=88,
                padding=ft.padding.only(left=14, right=14, top=10, bottom=10),
                border_radius=14,
                bgcolor=ft.Colors.with_opacity(0.055, ft.Colors.WHITE),
                border=ft.border.all(1, ft.Colors.with_opacity(0.10, ft.Colors.WHITE)),
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
                width=650,
                height=96,
                padding=ft.padding.only(left=18, right=18, top=12, bottom=12),
                border_radius=18,
                bgcolor=ft.Colors.with_opacity(0.075, ft.Colors.WHITE),
                border=ft.border.all(1, ft.Colors.with_opacity(0.13, ft.Colors.WHITE)),
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
                border_radius=18,
                bgcolor=tokens["subpanel"],
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
                bgcolor=tokens["panel"],
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
                                ft.ElevatedButton("Save", on_click=save_profile, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
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
                    ft.IconButton(icon=ft.Icons.SETTINGS, tooltip="Edit profile", on_click=open_profile_editor, bgcolor=tokens["subpanel"], icon_color=tokens["text"]),
                ],
            ),
        )

        career_stats_content = ft.Row(
            wrap=True,
            spacing=10,
            run_spacing=10,
            controls=[
                career_name_card(),
                transparent_profile_stat_card("Member since", member_since),
                transparent_profile_stat_card("Total flight time", total_hours),
                transparent_profile_stat_card("Online flights", str(online_flight_count)),
                transparent_profile_stat_card("Total landings", str(total_landings)),
                transparent_profile_stat_card("Violations", violations_value),
                transparent_profile_stat_card("Favorite airline", favorite_airline_value),
                transparent_profile_stat_card("Favorite aircraft", favorite_aircraft_value),
                transparent_profile_stat_card("Countries visited", countries_visited_value),
            ],
        )

        career_bg_src = card_background_src("career_statistics")
        passport_dark = "#101826"
        stats_card = ft.Container(
            width=700,
            height=730,
            border_radius=34,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=passport_dark,
            image=ft.DecorationImage(src=career_bg_src, fit=ft.BoxFit.COVER, opacity=0.24) if career_bg_src else None,
            border=ft.border.all(1.5, ft.Colors.with_opacity(0.32, tokens["accent"])),
            shadow=ft.BoxShadow(
                blur_radius=40,
                spread_radius=2,
                color=ft.Colors.with_opacity(0.22, tokens["accent"]),
                offset=ft.Offset(0, 10),
            ),
            content=ft.Stack(
                expand=True,
                controls=[
                    ft.Container(expand=True, bgcolor=ft.Colors.with_opacity(0.10, tokens["accent"])),
                    ft.Container(left=0, top=0, bottom=0, width=46, bgcolor=ft.Colors.with_opacity(0.30, tokens["accent"])),
                    ft.Container(left=54, top=26, bottom=26, width=1, bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.WHITE)),
                    ft.Container(
                        expand=True,
                        padding=ft.padding.only(left=72, right=24, top=22, bottom=22),
                        content=ft.Column(
                            spacing=12,
                            controls=[
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        ft.Column(
                                            tight=True,
                                            spacing=2,
                                            controls=[
                                                ft.Text("FLIGHT MANAGEMENT SYSTEMS", size=11, weight=ft.FontWeight.W_800, color=ft.Colors.with_opacity(0.70, tokens["text"])),
                                                ft.Text("CREW PASSPORT", size=24, weight=ft.FontWeight.W_900, color=tokens["text"]),
                                            ],
                                        ),
                                        ft.Container(width=58, height=1),
                                    ],
                                ),
                                ft.Container(height=1, bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.WHITE)),
                                career_stats_content,
                                ft.Container(expand=True),
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    controls=[
                                        ft.Text(f"ISSUED {member_since}", size=10, weight=ft.FontWeight.W_700, color=tokens["muted"]),
                                        ft.Text("DIGITAL PASSPORT ID  •  FMS-OPS", size=10, weight=ft.FontWeight.W_700, color=tokens["muted"]),
                                    ],
                                ),
                            ],
                        ),
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
                    bgcolor=tokens["subpanel"],
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
            padding=18,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=16,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.END,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.IconButton(icon=ft.Icons.SETTINGS, tooltip="Edit profile", on_click=open_profile_editor, bgcolor=tokens["subpanel"], icon_color=tokens["text"]),
                        ],
                    ),
                    ft.Row(
                        wrap=False,
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            stats_card,
                            ft.Container(expand=True, content=recent_card),
                        ],
                    ),
                ],
            ),
        )


    def seats_view():
        selected_seat_aircraft = canonical_aircraft_name(state.aircraft) or state.aircraft
        if selected_seat_aircraft:
            apply_seat_template_defaults(selected_seat_aircraft)
        control_panel = glass_card_with_background(
            "Cabin Control",
            ft.Column(
                spacing=14,
                controls=[
                    ft.Text("Seat map and passenger load", size=12, color=tokens["muted"]),
                    ft.Row(
                        spacing=10,
                        controls=[
                            ft.Container(
                                expand=1,
                                height=86,
                                padding=ft.padding.symmetric(horizontal=14, vertical=12),
                                border_radius=16,
                                bgcolor=tokens["subpanel"],
                                border=ft.border.all(1, tokens["card_border"]),
                                content=ft.Column(
                                    spacing=8,
                                    controls=[
                                        ft.Text(current_airline_label(), size=16, weight=ft.FontWeight.W_800, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                        ft.Text(current_aircraft_label(), size=16, weight=ft.FontWeight.W_800, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
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
                                        padding=ft.padding.symmetric(horizontal=14, vertical=12),
                                        border_radius=16,
                                        bgcolor=tokens["subpanel"],
                                        border=ft.border.all(1, tokens["card_border"]),
                                        alignment=ft.Alignment(0, 0),
                                        content=ft.Column(
                                            tight=True,
                                            spacing=6,
                                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                            controls=[
                                                ft.Text("Seat Belt", size=16, weight=ft.FontWeight.W_800, color=tokens["text"], text_align=ft.TextAlign.CENTER),
                                                ft.Text("Sign", size=16, weight=ft.FontWeight.W_800, color=tokens["text"], text_align=ft.TextAlign.CENTER),
                                            ],
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
                        ft.ElevatedButton("Generate Seat Map", on_click=generate_seat_map, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                        ft.OutlinedButton("Clear Occupancy", on_click=clear_seat_occupancy),
                    ]),
                    seat_status_text,
                    ft.Divider(height=8, opacity=0.10),
                    ft.Text("Fill seats", size=14, weight=ft.FontWeight.W_800, color=tokens["text"]),
                    ft.Row(wrap=True, spacing=12, controls=[seat_fill_first_tf, seat_fill_business_tf]),
                    ft.Row(wrap=True, spacing=12, controls=[seat_fill_premium_tf, seat_fill_economy_tf]),
                    ft.Row(wrap=True, spacing=10, controls=[
                        ft.ElevatedButton("Fill Seats", on_click=auto_fill_seats, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                        ft.OutlinedButton("Reset Fill", on_click=lambda e: (setattr(seat_fill_first_tf, "value", "0"), setattr(seat_fill_business_tf, "value", "0"), setattr(seat_fill_premium_tf, "value", "0"), setattr(seat_fill_economy_tf, "value", "0"), page.update())),
                    ]),
                ],
            ),
        )
        return ft.Container(
            expand=True,
            padding=18,
            content=ft.Row(
                expand=True,
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Container(width=380, content=control_panel),
                    ft.Container(expand=True, content=ft.Column(scroll=ft.ScrollMode.AUTO, spacing=16, controls=[seat_map_host])),
                ],
            ),
        )

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
        for ctrl in [airline_dd, cal_airline_dd, seat_airline_dd]:
            ctrl.options = [ft.dropdown.Option(name) for name in AIRLINES]
            if ctrl.value not in (None, "") and ctrl.value not in AIRLINES:
                ctrl.value = None
        if preferred_airline:
            if airline_dd.value in (None, ""):
                airline_dd.value = preferred_airline if preferred_airline in AIRLINES else airline_dd.value
            if cal_airline_dd.value in (None, ""):
                cal_airline_dd.value = state.airline if state.airline in AIRLINES else None
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
        settings_brightness_value_text.value = f"Brightness: {settings_brightness_slider.value:.2f}x"
        settings_contrast_value_text.value = f"Contrast: {settings_contrast_slider.value:.2f}x"
        settings_overlay_value_text.value = f"Airline overlay opacity: {int(settings_overlay_slider.value * 100)}%"
        settings_volume_value_text.value = "Volume: muted" if settings_mute_switch.value else f"Volume: {int(settings_volume_slider.value * 100)}%"
        settings_fuel_unit_dd.value = state.default_fuel_unit if state.default_fuel_unit in ("kg", "lb") else "kg"
        settings_distance_unit_dd.value = state.default_distance_unit if state.default_distance_unit in ("NM", "km") else "NM"
        settings_temperature_unit_dd.value = state.default_temperature_unit if state.default_temperature_unit in ("°C", "°F") else "°C"
        settings_low_performance_switch.value = bool(state.low_performance_mode)
        settings_professional_info_switch.value = bool(getattr(state, "professional_info_enabled", False))
        settings_professional_info_status_text.value = (
            "Professional information: runway, distance, wind/atmosphere, landing distance, and descent planning cards are visible."
            if settings_professional_info_switch.value
            else "Normal information: advanced planning cards are hidden."
        )
        settings_professional_info_status_text.color = "#FF8A80" if settings_professional_info_switch.value else tokens["muted"]
        settings_brightness_value_text.color = tokens["muted"]
        settings_contrast_value_text.color = tokens["muted"]
        settings_overlay_value_text.color = tokens["muted"]
        settings_volume_value_text.color = tokens["muted"]
        settings_airline_status_text.color = tokens["muted"]
        settings_custom_airlines_text.color = tokens["muted"]
        settings_performance_status_text.color = tokens["muted"]
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
        state.display_mode = "dark"
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

    def apply_professional_info_settings(e=None):
        state.professional_info_enabled = bool(settings_professional_info_switch.value)
        save_settings_data()
        sync_settings_controls(update_page=False)
        refresh_ui()

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
            if page.dialog:
                page.dialog.open = False
                page.update()

        def reset_profile_stats(evt=None):
            state.profile_total_flight_minutes = 0
            state.profile_online_flights = 0
            state.profile_total_landings = 0
            save_profile_data()
            settings_export_status_text.value = "Profile statistics reset. Calendar flights were not deleted."
            close_dialog()
            refresh_ui()
            show_snack("Profile statistics reset.")

        page.dialog = ft.AlertDialog(
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
        page.dialog.open = True
        page.update()

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

        add_button = ft.ElevatedButton("Add Airline", bgcolor=tokens["accent"], color=ft.Colors.WHITE)
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
            bgcolor=tokens["panel"],
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
        for ctrl in (airline_dd, cal_airline_dd, seat_airline_dd):
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

    settings_add_airline_btn = ft.ElevatedButton("Add Airline", bgcolor=tokens["accent"], color=ft.Colors.WHITE)
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
    settings_fuel_unit_dd.on_change = apply_aviation_default_settings
    settings_distance_unit_dd.on_change = apply_aviation_default_settings
    settings_temperature_unit_dd.on_change = apply_aviation_default_settings
    settings_low_performance_switch.on_change = apply_performance_settings
    settings_professional_info_switch.on_change = apply_professional_info_settings
    sync_settings_controls(update_page=False)

    IF_API_BASE_URL = "https://api.infiniteflight.com/public/v2"
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
    IF_ATC_TYPES = {
        0: "Ground",
        1: "Tower",
        2: "Unicom",
        3: "Clearance",
        4: "Approach",
        5: "Departure",
        6: "Center",
        7: "ATIS",
        8: "Aircraft",
        9: "Recorded",
        10: "Unknown",
        11: "Unused",
    }
    IF_WORLD_TYPES = {
        0: "Solo",
        1: "Casual",
        2: "Training",
        3: "Expert",
        4: "Private",
    }
    IF_PILOT_STATES = {
        0: "Active",
        1: "Away in flight",
        2: "Away parked",
        3: "In background",
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

    def if_config_data() -> dict:
        if not infinite_flight_config_path.exists():
            return {}
        try:
            data = json.loads(infinite_flight_config_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def if_env_api_key() -> str:
        return os.environ.get("INFINITE_FLIGHT_API_KEY", "").strip()

    def if_local_api_key() -> str:
        return str(if_config_data().get("api_key") or "").strip()

    def if_current_api_key(candidate: str = "") -> tuple[str, str]:
        typed_key = (candidate or "").strip()
        if typed_key:
            return typed_key, "entered"
        env_key = if_env_api_key()
        if env_key:
            return env_key, "environment"
        local_key = if_local_api_key()
        if local_key:
            return local_key, "local config"
        return "", "missing"

    def if_saved_key_hint() -> str:
        if if_env_api_key():
            return "Using INFINITE_FLIGHT_API_KEY from environment"
        if if_local_api_key():
            return "Saved local key available"
        return "Enter API key or set INFINITE_FLIGHT_API_KEY"

    def if_save_api_key_value(api_key: str) -> bool:
        key = (api_key or "").strip()
        if not key:
            return False
        payload = {
            "api_key": key,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        infinite_flight_config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return True

    def if_clear_local_api_key():
        try:
            if infinite_flight_config_path.exists():
                infinite_flight_config_path.unlink()
        except Exception:
            pass
        state.if_connection_status = "Not connected"
        state.if_sessions = []
        state.if_selected_session_id = ""
        state.if_selected_session_name = ""
        state.if_selected_flight = {}
        state.if_selected_flight_plan = {}
        state.if_live_flights = []
        state.if_selected_route_points = []
        state.if_selected_route_label = ""
        state.if_selected_route_start_label = ""
        state.if_selected_route_end_label = ""
        state.if_last_traffic_refresh = "Never"
        state.if_live_refresh_enabled = False
        state.if_last_live_refresh_attempt = 0.0
        state.if_active_atc = []
        state.if_user_stats = {}
        state.if_recent_activity = []
        state.if_cache.clear()
        state.if_cache_status = "Cleared"
        state.if_last_request_status = "No request yet"
        state.if_last_response_ms = "—"
        state.if_last_error = ""

    def if_cache_get(key: str, ttl_seconds: int):
        cached = state.if_cache.get(key)
        if not cached:
            return None
        age = if_now() - float(cached.get("timestamp", 0.0) or 0.0)
        if age <= ttl_seconds:
            state.if_cache_status = f"Cache hit: {key} ({age:.0f}s old)"
            return cached.get("data")
        return None

    def if_cache_set(key: str, data: dict):
        state.if_cache[key] = {
            "timestamp": if_now(),
            "data": data,
        }
        state.if_cache_status = f"Cache stored: {key}"

    def if_api_request(method: str, endpoint: str, body: Optional[dict] = None, cache_key: str = "", ttl_seconds: int = 0, force: bool = False):
        if state.if_last_activity_timestamp and if_now() - state.if_last_activity_timestamp > IF_IDLE_TIMEOUT_SECONDS and not force:
            state.if_polling_paused = True
            state.if_last_request_status = "Paused by inactivity timeout"
            state.if_last_error = "No API refresh after 15 minutes idle. Press a button to resume."
            return None

        if cache_key and ttl_seconds > 0 and not force:
            cached = if_cache_get(cache_key, ttl_seconds)
            if cached is not None:
                return cached

        api_key, source = if_current_api_key()
        if not api_key:
            state.if_connection_status = "Not connected"
            state.if_last_request_status = "Missing API key"
            state.if_last_error = "Add an Infinite Flight API key or set INFINITE_FLIGHT_API_KEY."
            return None

        url = IF_API_BASE_URL + endpoint
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "FMS-Sim-Desktop/7",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")

        started = if_now()
        try:
            request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
                elapsed_ms = int((if_now() - started) * 1000)
                state.if_last_response_ms = f"{elapsed_ms} ms"
                state.if_last_request_status = f"HTTP {getattr(response, 'status', 200)}"
                state.if_last_error = ""

                error_code = payload.get("errorCode") if isinstance(payload, dict) else None
                if error_code not in (None, 0):
                    state.if_last_request_status = if_error_label(error_code)
                    state.if_last_error = if_error_label(error_code)
                    if int(error_code) == 4:
                        state.if_connection_status = "Not authorized"
                    return None

                state.if_connection_status = f"Connected ({source})"
                if cache_key:
                    if_cache_set(cache_key, payload)
                return payload
        except urllib.error.HTTPError as ex:
            state.if_last_response_ms = f"{int((if_now() - started) * 1000)} ms"
            if ex.code == 401:
                state.if_connection_status = "Not authorized"
                state.if_last_request_status = "HTTP 401"
                state.if_last_error = "Invalid or unauthorized API key."
            elif ex.code == 429:
                state.if_last_request_status = "HTTP 429"
                state.if_last_error = "Rate limit reached. Wait before refreshing again."
            else:
                state.if_last_request_status = f"HTTP {ex.code}"
                state.if_last_error = str(ex)
        except urllib.error.URLError as ex:
            state.if_last_response_ms = f"{int((if_now() - started) * 1000)} ms"
            state.if_last_request_status = "Network error"
            state.if_last_error = str(getattr(ex, "reason", ex))
        except TimeoutError:
            state.if_last_response_ms = f"{int((if_now() - started) * 1000)} ms"
            state.if_last_request_status = "Timeout"
            state.if_last_error = "Infinite Flight API request timed out."
        except Exception as ex:
            state.if_last_response_ms = f"{int((if_now() - started) * 1000)} ms"
            state.if_last_request_status = "Request failed"
            state.if_last_error = str(ex)
        return None

    def if_get_sessions(force: bool = False) -> List[dict]:
        payload = if_api_request("GET", "/sessions", cache_key="sessions", ttl_seconds=600, force=force)
        sessions = payload.get("result", []) if isinstance(payload, dict) else []
        return sessions if isinstance(sessions, list) else []

    def if_get_flights(session_id: str, force: bool = False) -> List[dict]:
        if not session_id:
            return []
        payload = if_api_request("GET", f"/sessions/{session_id}/flights", cache_key=f"flights:{session_id}", ttl_seconds=15, force=force)
        flights = payload.get("result", []) if isinstance(payload, dict) else []
        return flights if isinstance(flights, list) else []

    def if_get_atc(session_id: str, force: bool = False) -> List[dict]:
        if not session_id:
            return []
        payload = if_api_request("GET", f"/sessions/{session_id}/atc", cache_key=f"atc:{session_id}", ttl_seconds=15, force=force)
        atc = payload.get("result", []) if isinstance(payload, dict) else []
        return atc if isinstance(atc, list) else []

    def if_get_flight_plan(session_id: str, flight_id: str, force: bool = False) -> dict:
        if not session_id or not flight_id:
            return {}
        payload = if_api_request("GET", f"/sessions/{session_id}/flights/{flight_id}/flightplan", cache_key=f"flightplan:{session_id}:{flight_id}", ttl_seconds=15, force=force)
        result = payload.get("result", {}) if isinstance(payload, dict) else {}
        return result if isinstance(result, dict) else {}

    def if_get_user_stats(query: str, force: bool = False) -> dict:
        raw = (query or "").strip()
        if not raw:
            return {}
        if re.fullmatch(r"[0-9a-fA-F]{8}", raw):
            body = {"userHashes": [raw.upper()]}
        elif re.fullmatch(r"[0-9a-fA-F-]{32,36}", raw):
            body = {"userIds": [raw]}
        else:
            body = {"discourseNames": [raw]}
        payload = if_api_request("POST", "/users", body=body, cache_key=f"userstats:{raw.lower()}", ttl_seconds=300, force=force)
        result = payload.get("result", []) if isinstance(payload, dict) else []
        if isinstance(result, list) and result:
            first = result[0]
            return first if isinstance(first, dict) else {}
        return {}

    def if_get_user_flights(user_id: str, force: bool = False) -> List[dict]:
        if not user_id:
            return []
        payload = if_api_request("GET", f"/users/{user_id}/flights?page=1", cache_key=f"userflights:{user_id}:1", ttl_seconds=300, force=force)
        result = payload.get("result", {}) if isinstance(payload, dict) else {}
        flights = result.get("data", []) if isinstance(result, dict) else []
        return flights if isinstance(flights, list) else []

    def if_session_label(session: dict) -> str:
        world_type = IF_WORLD_TYPES.get(int(session.get("worldType", -1) or -1), "Server")
        name = str(session.get("name") or world_type or "Server").strip()
        count = session.get("userCount", 0)
        max_users = session.get("maxUsers", "—")
        return f"{world_type} - {name} - {count}/{max_users}"

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
        first = state.if_sessions[0]
        state.if_selected_session_id = str(first.get("id") or "")
        state.if_selected_session_name = str(first.get("name") or "")

    def if_number(value, decimals: int = 0, fallback: str = "—") -> str:
        try:
            return f"{float(value):,.{decimals}f}"
        except Exception:
            return fallback

    def if_time_minutes(value) -> str:
        try:
            minutes = int(round(float(value or 0)))
            hours, mins = divmod(minutes, 60)
            return f"{hours}h {mins:02d}m"
        except Exception:
            return "—"

    def if_flight_matches_query(flight: dict, query: str) -> bool:
        q = (query or "").strip().lower()
        if not q:
            return False
        for key in ("callsign", "username", "userId", "flightId"):
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
        username = str(flight.get("username") or "").strip()
        if callsign and username:
            return f"{callsign} / {username}"
        return callsign or username or str(flight.get("flightId") or "Unknown flight")[:8]

    def if_flight_heading(flight: dict) -> float:
        heading = if_float(flight.get("heading"))
        if heading is None:
            heading = if_float(flight.get("track"))
        return float(heading or 0.0) % 360.0

    def if_plan_points_and_label(plan: dict) -> tuple[List[tuple[float, float]], str, str, str]:
        points: List[tuple[float, float]] = []
        names: List[str] = []

        def walk(items):
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                location = item.get("location") if isinstance(item.get("location"), dict) else {}
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

        walk(plan.get("flightPlanItems") if isinstance(plan, dict) else [])
        if len(points) >= 2:
            label = f"{names[0]} to {names[-1]}"
        elif points:
            label = names[0]
        else:
            label = "No route points available"
        start_label = names[0] if names else ""
        end_label = names[-1] if len(names) > 1 else ""
        return points, label, start_label, end_label

    def if_route_distance_label(points: List[tuple[float, float]]) -> str:
        if len(points) < 2:
            return "Route unavailable"
        distance = 0.0
        for start, end in zip(points[:-1], points[1:]):
            distance += great_circle_distance_nm_points(start, end)
        return f"{distance:.0f} NM"

    def if_find_live_flight(flight_id: str) -> dict:
        target = str(flight_id or "")
        for flight in state.if_live_flights:
            if str(flight.get("flightId") or "") == target:
                return flight
        return {}

    def if_load_live_traffic(force: bool = True, mark_activity: bool = True) -> List[dict]:
        if mark_activity:
            if_mark_activity()
        state.if_last_live_refresh_attempt = if_now()
        if not state.if_sessions:
            state.if_sessions = if_get_sessions(force=force)
        if_ensure_selected_session()
        if not state.if_selected_session_id:
            state.if_live_flights = []
            state.if_last_request_status = "No session selected"
            state.if_last_error = "Select or load an Infinite Flight server/session first."
            return []
        flights = [flight for flight in if_get_flights(state.if_selected_session_id, force=force) if if_flight_position(flight)]
        state.if_live_flights = flights
        state.if_last_traffic_refresh = datetime.now().strftime("%H:%M:%S")
        if state.if_selected_flight:
            selected_id = str(state.if_selected_flight.get("flightId") or "")
            updated = if_find_live_flight(selected_id)
            if updated:
                state.if_selected_flight = updated
            else:
                state.if_selected_flight = {}
                state.if_selected_flight_plan = {}
                state.if_selected_route_points = []
                state.if_selected_route_label = ""
                state.if_selected_route_start_label = ""
                state.if_selected_route_end_label = ""
        state.if_last_request_status = f"Traffic loaded - {len(flights)} aircraft"
        return flights

    def if_select_map_flight(flight_id: str):
        if_mark_activity()
        flight = if_find_live_flight(flight_id)
        if not flight:
            state.if_last_request_status = "Flight not found"
            state.if_last_error = "Refresh traffic and select the aircraft again."
            return
        state.if_selected_flight = flight
        state.if_user_stats = {}
        state.if_recent_activity = []
        plan = if_get_flight_plan(state.if_selected_session_id, str(flight.get("flightId") or ""), force=True)
        state.if_selected_flight_plan = plan or {}
        points, label, start_label, end_label = if_plan_points_and_label(plan or {})
        state.if_selected_route_points = points
        state.if_selected_route_label = label
        state.if_selected_route_start_label = start_label
        state.if_selected_route_end_label = end_label
        state.if_last_request_status = "Aircraft selected"
        state.if_last_error = "" if points else "This aircraft has no retrievable filed flight plan, so only its live position is shown."

    def settings_page():
        sync_settings_controls(update_page=False)

        display_controls = ft.Column(
            spacing=14,
            controls=[
                ft.Text("Switch between the default night shell and an experimental softer daytime shell. Cards stay dark for readability.", size=12, color=tokens["muted"]),
                settings_daylight_switch,
                ft.Divider(height=8, opacity=0.10),
                ft.Text("Brightness", size=13, weight=ft.FontWeight.W_700, color=tokens["text"]),
                ft.Row(wrap=True, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[settings_brightness_slider, settings_brightness_value_text]),
                ft.Text("Contrast", size=13, weight=ft.FontWeight.W_700, color=tokens["text"]),
                ft.Row(wrap=True, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[settings_contrast_slider, settings_contrast_value_text]),
                ft.Text("Airline color overlay", size=13, weight=ft.FontWeight.W_700, color=tokens["text"]),
                ft.Row(wrap=True, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[settings_overlay_slider, settings_overlay_value_text]),
                ft.Divider(height=8, opacity=0.10),
                ft.Text("Global background image", size=13, weight=ft.FontWeight.W_700, color=tokens["text"]),
                ft.Text("Night mode uses the global image. Daytime display can use its own background file.", size=12, color=tokens["muted"]),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    controls=[
                        ft.OutlinedButton("Upload Background", icon=ft.Icons.UPLOAD_FILE, on_click=upload_global_background),
                    ],
                ),
                settings_background_status_text,
                ft.Row(
                    wrap=True,
                    spacing=10,
                    controls=[
                        ft.OutlinedButton("Reset Display", on_click=reset_display_settings),
                    ],
                ),
            ],
        )

        airline_tools = ft.Column(
            spacing=12,
            controls=[
                ft.Text("Add an airline to the app list and then place its logo in the generated logo path.", size=12, color=tokens["muted"]),
                settings_add_airline_btn,
                ft.Divider(height=8, opacity=0.10),
                ft.Text("Remove an airline that was added from Settings. Built-in airlines are protected.", size=12, color=tokens["muted"]),
                ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[settings_remove_airline_dd, settings_remove_airline_btn]),
                settings_airline_status_text,
                settings_custom_airlines_text,
                ft.Container(
                    padding=12,
                    border_radius=14,
                    bgcolor=tokens["subpanel"],
                    border=ft.border.all(1, tokens["card_border"]),
                    content=ft.Text(
                        "Logo format: assets/airlines/logos/airline_name.png. The app will show text fallback until the logo file exists.",
                        size=11,
                        color=tokens["muted"],
                    ),
                ),
            ],
        )

        aviation_defaults = ft.Column(
            spacing=12,
            controls=[
                ft.Text("Set the app's preferred planning units. These values are saved for future sessions.", size=12, color=tokens["muted"]),
                ft.Row(wrap=True, spacing=12, run_spacing=12, controls=[settings_fuel_unit_dd, settings_distance_unit_dd, settings_temperature_unit_dd]),
            ],
        )

        data_tools = ft.Column(
            spacing=12,
            controls=[
                ft.Text("Export saved data, upload a calendar JSON, or reset profile statistics without deleting calendar flights.", size=12, color=tokens["muted"]),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    run_spacing=10,
                    controls=[
                        ft.ElevatedButton("Upload Calendar", icon=ft.Icons.UPLOAD_FILE, on_click=import_calendar_data, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                        ft.ElevatedButton("Export Calendar", on_click=export_calendar_data, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                        ft.ElevatedButton("Export Profile", on_click=export_profile_data, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                        ft.OutlinedButton("Reset Profile", on_click=open_reset_profile_confirmation),
                    ],
                ),
                settings_calendar_import_status_text,
                settings_export_status_text,
            ],
        )

        professional_info_tools = ft.Column(
            spacing=12,
            controls=[
                ft.Text("Choose how much operational planning detail is shown on the Takeoff and Landing pages.", size=12, color=tokens["muted"]),
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=10),
                    border_radius=16,
                    bgcolor=tokens["subpanel"],
                    border=ft.border.all(1, tokens["card_border"]),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text("Normal information", size=12, weight=ft.FontWeight.W_800, color=tokens["text"]),
                            settings_professional_info_switch,
                            ft.Text("Professional information", size=12, weight=ft.FontWeight.W_800, color="#FF8A80"),
                        ],
                    ),
                ),
                settings_professional_info_status_text,
            ],
        )

        performance_tools = ft.Column(
            spacing=12,
            controls=[
                ft.Text("Reduce live visual updates when you want the app to run lighter.", size=12, color=tokens["muted"]),
                settings_low_performance_switch,
                settings_performance_status_text,
            ],
        )

        volume_tools = ft.Column(
            spacing=12,
            controls=[
                ft.Text("Control the app sound level for login and cabin audio cues.", size=12, color=tokens["muted"]),
                ft.Row(wrap=True, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[settings_volume_slider, settings_volume_value_text]),
                settings_mute_switch,
                ft.OutlinedButton("Apply Volume", on_click=apply_audio_settings),
            ],
        )

        def if_settings_tile(label: str, value: str, width: int = 150) -> ft.Control:
            return ft.Container(
                width=width,
                height=72,
                padding=ft.padding.symmetric(horizontal=12, vertical=9),
                border_radius=14,
                bgcolor=tokens["subpanel"],
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    tight=True,
                    spacing=3,
                    controls=[
                        ft.Text(label, size=10, color=tokens["muted"], weight=ft.FontWeight.W_700),
                        ft.Text(value or "-", size=14, weight=ft.FontWeight.W_900, color=tokens["text"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        if_api_key_tf = ft.TextField(
            label="Infinite Flight API key",
            hint_text=if_saved_key_hint(),
            width=340,
            password=True,
            can_reveal_password=True,
            border_radius=16,
            filled=True,
            bgcolor=tokens["input_bg"],
            color=tokens["text"],
            border_color=tokens["card_border"],
            focused_border_color=tokens["accent"],
            label_style=ft.TextStyle(color=tokens["muted"]),
        )
        if_session_dd = ft.Dropdown(
            label="Server / session",
            value=state.if_selected_session_id or None,
            options=if_session_options(),
            width=310,
            border_radius=16,
            filled=True,
            bgcolor=tokens["input_bg"],
            color=tokens["text"],
            border_color=tokens["card_border"],
            label_style=ft.TextStyle(color=tokens["muted"]),
            disabled=not bool(state.if_sessions),
        )

        def clear_if_route_selection():
            state.if_selected_flight = {}
            state.if_selected_flight_plan = {}
            state.if_selected_route_points = []
            state.if_selected_route_label = ""
            state.if_selected_route_start_label = ""
            state.if_selected_route_end_label = ""

        def set_if_session_from_settings(e=None):
            if e is None or not getattr(e, "control", None):
                return
            selected = if_select_session(e.control.value or "")
            if not selected:
                state.if_last_request_status = "Server selection failed"
                state.if_last_error = f"Could not match selected server: {e.control.value}"
                refresh_ui()
                return
            clear_if_route_selection()
            state.if_live_flights = []
            if_load_live_traffic(force=True)
            refresh_ui()

        if_session_dd.on_change = set_if_session_from_settings

        def test_if_connection(e=None):
            if_mark_activity()
            typed_key = (if_api_key_tf.value or "").strip()
            if typed_key:
                if_save_api_key_value(typed_key)
            state.if_sessions = if_get_sessions(force=True)
            if_ensure_selected_session()
            if state.if_sessions:
                state.if_connection_status = f"Connected - {len(state.if_sessions)} sessions"
                if_load_live_traffic(force=True)
                show_snack("Infinite Flight API connection ready.")
            else:
                state.if_live_flights = []
                show_snack("Infinite Flight API connection did not return sessions.")
            refresh_ui()

        def save_if_key(e=None):
            key = (if_api_key_tf.value or "").strip()
            if not key:
                state.if_last_error = "Enter an API key before saving."
                state.if_last_request_status = "No key entered"
                refresh_ui()
                return
            try:
                if_save_api_key_value(key)
                state.if_last_request_status = "API key saved locally"
                state.if_last_error = ""
                show_snack("Infinite Flight API key saved locally.")
            except Exception as ex:
                state.if_last_request_status = "Could not save API key"
                state.if_last_error = str(ex)
            refresh_ui()

        def clear_if_key(e=None):
            if_clear_local_api_key()
            show_snack("Local Infinite Flight API key cleared.")
            refresh_ui()

        def refresh_if_sessions(e=None):
            if_mark_activity()
            state.if_sessions = if_get_sessions(force=True)
            if_ensure_selected_session()
            refresh_ui()

        def refresh_if_traffic(e=None):
            if_load_live_traffic(force=True)
            refresh_ui()

        def select_if_server_type(world_type_name: str):
            if not state.if_sessions:
                state.if_sessions = if_get_sessions(force=True)
            selected = if_select_session(world_type_name)
            if selected:
                clear_if_route_selection()
                state.if_live_flights = []
                if_load_live_traffic(force=True)
            else:
                state.if_last_request_status = "Server unavailable"
                state.if_last_error = f"No active {world_type_name} server was returned by the API."
            refresh_ui()

        def toggle_if_live_refresh(e=None):
            state.if_live_refresh_enabled = bool(getattr(getattr(e, "control", None), "value", False))
            if state.if_live_refresh_enabled:
                if_mark_activity()
                if_load_live_traffic(force=True)
                show_snack("Live traffic refresh enabled.")
            else:
                show_snack("Live traffic refresh paused.")
            refresh_ui()

        selected_session = next((session for session in state.if_sessions if str(session.get("id") or "") == str(state.if_selected_session_id or "")), {})
        selected_world = IF_WORLD_TYPES.get(int(selected_session.get("worldType", -1) or -1), "")

        def if_server_button(label: str) -> ft.Control:
            active = selected_world == label
            if active:
                return ft.ElevatedButton(label, on_click=lambda e, value=label: select_if_server_type(value), bgcolor=tokens["accent"], color=ft.Colors.WHITE)
            return ft.OutlinedButton(label, on_click=lambda e, value=label: select_if_server_type(value))

        if_live_refresh_switch = ft.Switch(label="Live refresh (15s)", value=state.if_live_refresh_enabled)
        if_live_refresh_switch.on_change = toggle_if_live_refresh
        if_key_source = if_current_api_key()[1]
        if_key_source_label = "Environment variable" if if_key_source == "environment" else "Local config" if if_key_source == "local config" else "Not saved"
        infinite_flight_tools = ft.Column(
            spacing=12,
            controls=[
                ft.Container(
                    padding=12,
                    border_radius=14,
                    bgcolor=ft.Colors.with_opacity(0.12, tokens["accent"]),
                    border=ft.border.all(1, ft.Colors.with_opacity(0.22, tokens["accent"])),
                    content=ft.Text(
                        "Simulator use only. Not for real-world aviation, dispatch, navigation, or flight operations.",
                        size=12,
                        weight=ft.FontWeight.W_800,
                        color=tokens["text"],
                    ),
                ),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    run_spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        if_settings_tile("Status", state.if_connection_status, 200),
                        if_settings_tile("API key source", if_key_source_label, 170),
                        if_settings_tile("Aircraft loaded", str(len(state.if_live_flights)), 145),
                        if_settings_tile("Last refresh", state.if_last_traffic_refresh, 145),
                    ],
                ),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    run_spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        if_api_key_tf,
                        ft.ElevatedButton("Test Connection", on_click=test_if_connection, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                        ft.OutlinedButton("Save Key", on_click=save_if_key),
                        ft.OutlinedButton("Clear API Key", on_click=clear_if_key),
                    ],
                ),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    run_spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        if_server_button("Casual"),
                        if_server_button("Training"),
                        if_server_button("Expert"),
                        if_session_dd,
                        ft.ElevatedButton("Refresh Traffic", on_click=refresh_if_traffic, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                        ft.OutlinedButton("Refresh Sessions", on_click=refresh_if_sessions),
                        if_live_refresh_switch,
                    ],
                ),
                ft.Text(
                    state.if_last_error or "Live Flights uses these settings for its map and selected server.",
                    size=12,
                    color="#FF8080" if state.if_last_error else tokens["muted"],
                ),
            ],
        )

        return build_tab_page(
            "SETTINGS",
            ft.Container(
                expand=True,
                padding=18,
                content=ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=16,
                    controls=[
                        ft.Row(
                            wrap=False,
                            spacing=16,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                            controls=[
                                ft.Column(
                                    width=876,
                                    spacing=16,
                                    controls=[
                                        ft.Container(width=876, content=glass_card("Infinite Flight Live API", infinite_flight_tools)),
                                        ft.Row(
                                            spacing=16,
                                            vertical_alignment=ft.CrossAxisAlignment.START,
                                            controls=[
                                                ft.Column(
                                                    width=430,
                                                    spacing=16,
                                                    controls=[
                                                        ft.Container(width=430, content=glass_card("Data Management", data_tools)),
                                                        ft.Container(width=430, content=glass_card("Information Detail", professional_info_tools)),
                                                    ],
                                                ),
                                                ft.Container(width=430, content=glass_card("Aviation Defaults", aviation_defaults)),
                                            ],
                                        ),
                                    ],
                                ),
                                ft.Column(
                                    width=430,
                                    spacing=16,
                                    controls=[
                                        ft.Container(width=430, content=glass_card("Display", display_controls)),
                                        ft.Container(width=430, content=glass_card("Performance", performance_tools)),
                                    ],
                                ),
                                ft.Column(
                                    width=430,
                                    spacing=16,
                                    controls=[
                                        ft.Container(width=430, content=glass_card("Airline Management", airline_tools)),
                                        ft.Container(width=430, content=glass_card("Volume", volume_tools)),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ),
            overlay_opacity=0.08,
        )


    def infinite_flight_page():
        def set_session_from_dropdown(e=None):
            if e is not None and getattr(e, "control", None):
                if_select_session(e.control.value or "")
                state.if_selected_flight = {}
                state.if_selected_flight_plan = {}
                state.if_active_atc = []
                state.if_recent_activity = []
                state.if_user_stats = {}
                refresh_ui()

        api_key_tf = ft.TextField(
            label="Infinite Flight API key",
            hint_text=if_saved_key_hint(),
            width=360,
            password=True,
            can_reveal_password=True,
            border_radius=16,
            filled=True,
            bgcolor=tokens["input_bg"],
            color=tokens["text"],
            border_color=tokens["card_border"],
            focused_border_color=tokens["accent"],
            label_style=ft.TextStyle(color=tokens["muted"]),
        )
        session_dd = ft.Dropdown(
            label="Server / session",
            value=state.if_selected_session_id or None,
            options=if_session_options(),
            width=310,
            border_radius=16,
            filled=True,
            bgcolor=tokens["input_bg"],
            color=tokens["text"],
            border_color=tokens["card_border"],
            label_style=ft.TextStyle(color=tokens["muted"]),
            disabled=not bool(state.if_sessions),
        )
        session_dd.on_change = set_session_from_dropdown
        search_tf = ft.TextField(
            label="Username, user ID, flight ID, or callsign",
            hint_text="Example: DLH400 or your Infinite Flight username",
            width=370,
            border_radius=16,
            filled=True,
            bgcolor=tokens["input_bg"],
            color=tokens["text"],
            border_color=tokens["card_border"],
            focused_border_color=tokens["accent"],
            label_style=ft.TextStyle(color=tokens["muted"]),
        )

        def test_connection(e=None):
            if_mark_activity()
            typed_key = (api_key_tf.value or "").strip()
            if typed_key:
                if_save_api_key_value(typed_key)
            sessions = if_get_sessions(force=True)
            state.if_sessions = sessions
            if sessions and not state.if_selected_session_id:
                first = sessions[0]
                state.if_selected_session_id = str(first.get("id") or "")
                state.if_selected_session_name = str(first.get("name") or "")
            if sessions:
                state.if_connection_status = f"Connected - {len(sessions)} sessions"
                show_snack("Infinite Flight API connection ready.")
            else:
                show_snack("Infinite Flight API connection did not return sessions.")
            refresh_ui()

        def save_key(e=None):
            key = (api_key_tf.value or "").strip()
            if not key:
                state.if_last_error = "Enter an API key before saving."
                state.if_last_request_status = "No key entered"
                refresh_ui()
                return
            try:
                if_save_api_key_value(key)
                state.if_last_request_status = "API key saved locally"
                state.if_last_error = ""
                show_snack("Infinite Flight API key saved locally.")
            except Exception as ex:
                state.if_last_request_status = "Could not save API key"
                state.if_last_error = str(ex)
            refresh_ui()

        def clear_key(e=None):
            if_clear_local_api_key()
            show_snack("Local Infinite Flight API key cleared.")
            refresh_ui()

        def refresh_sessions(e=None):
            if_mark_activity()
            sessions = if_get_sessions(force=True)
            state.if_sessions = sessions
            if sessions and not state.if_selected_session_id:
                first = sessions[0]
                state.if_selected_session_id = str(first.get("id") or "")
                state.if_selected_session_name = str(first.get("name") or "")
            refresh_ui()

        def find_live_flight(e=None):
            if_mark_activity()
            query = (search_tf.value or "").strip()
            if not query:
                state.if_last_request_status = "Search required"
                state.if_last_error = "Enter a username, user ID, flight ID, or callsign."
                refresh_ui()
                return
            if not state.if_sessions:
                state.if_sessions = if_get_sessions(force=False)
            if not state.if_selected_session_id and state.if_sessions:
                first = state.if_sessions[0]
                state.if_selected_session_id = str(first.get("id") or "")
                state.if_selected_session_name = str(first.get("name") or "")
            flights = if_get_flights(state.if_selected_session_id, force=True)
            match = next((flight for flight in flights if if_flight_matches_query(flight, query)), None)
            state.if_selected_flight = match or {}
            state.if_selected_flight_plan = {}
            state.if_recent_activity = []
            state.if_user_stats = {}
            if match:
                state.if_last_request_status = "Active flight found"
                state.if_last_error = ""
                show_snack("Active Infinite Flight flight found.")
            else:
                stats = if_get_user_stats(query, force=False)
                state.if_user_stats = stats
                state.if_last_request_status = "No active flight found"
                state.if_last_error = "No active flight matched this search in the selected session."
            refresh_ui()

        def preview_flight_plan(e=None):
            if_mark_activity()
            flight_id = str(state.if_selected_flight.get("flightId") or "")
            if not flight_id:
                state.if_last_request_status = "No selected flight"
                state.if_last_error = "Find an active flight before previewing the flight plan."
                refresh_ui()
                return
            state.if_selected_flight_plan = if_get_flight_plan(state.if_selected_session_id, flight_id, force=True)
            if state.if_selected_flight_plan:
                state.if_last_request_status = "Flight plan loaded"
                state.if_last_error = ""
            else:
                state.if_last_request_status = "No flight plan"
                state.if_last_error = "This active flight has no filed flight plan or it could not be retrieved."
            refresh_ui()

        def refresh_atc(e=None):
            if_mark_activity()
            if not state.if_selected_session_id:
                state.if_last_request_status = "No session selected"
                state.if_last_error = "Select a server/session before loading ATC."
                refresh_ui()
                return
            state.if_active_atc = if_get_atc(state.if_selected_session_id, force=True)
            state.if_last_request_status = f"ATC loaded - {len(state.if_active_atc)} facilities"
            state.if_last_error = ""
            refresh_ui()

        def load_recent_activity(e=None):
            if_mark_activity()
            user_id = str(state.if_selected_flight.get("userId") or state.if_user_stats.get("userId") or "")
            query = (search_tf.value or "").strip()
            if not user_id and query:
                state.if_user_stats = if_get_user_stats(query, force=True)
                user_id = str(state.if_user_stats.get("userId") or "")
            if not user_id:
                state.if_last_request_status = "No user selected"
                state.if_last_error = "Find an active flight or search a user before loading recent activity."
                refresh_ui()
                return
            state.if_recent_activity = if_get_user_flights(user_id, force=True)
            state.if_last_request_status = f"Recent activity loaded - {len(state.if_recent_activity)} rows"
            state.if_last_error = ""
            refresh_ui()

        search_tf.on_submit = find_live_flight

        def info_tile(label: str, value: str, width: int = 150) -> ft.Control:
            return ft.Container(
                width=width,
                height=76,
                padding=ft.padding.symmetric(horizontal=12, vertical=10),
                border_radius=14,
                bgcolor=tokens["subpanel"],
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    tight=True,
                    spacing=3,
                    controls=[
                        ft.Text(label, size=10, color=tokens["muted"], weight=ft.FontWeight.W_700),
                        ft.Text(value or "—", size=15, weight=ft.FontWeight.W_900, color=tokens["text"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        def plan_item_names(items: List[dict]) -> List[str]:
            names: List[str] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("identifier") or "").strip()
                if name:
                    names.append(name)
                children = item.get("children")
                if isinstance(children, list):
                    names.extend(plan_item_names(children))
            return names

        def connection_card() -> ft.Control:
            key_source = if_current_api_key()[1]
            key_source_label = "Environment variable" if key_source == "environment" else "Local config" if key_source == "local config" else "Not saved"
            return glass_card(
                "Infinite Flight Live API",
                ft.Column(
                    spacing=12,
                    controls=[
                        ft.Container(
                            padding=12,
                            border_radius=14,
                            bgcolor=ft.Colors.with_opacity(0.12, tokens["accent"]),
                            border=ft.border.all(1, ft.Colors.with_opacity(0.22, tokens["accent"])),
                            content=ft.Text(
                                "Simulator use only. Not for real-world aviation, dispatch, navigation, or flight operations.",
                                size=12,
                                weight=ft.FontWeight.W_800,
                                color=tokens["text"],
                            ),
                        ),
                        ft.Row(
                            wrap=True,
                            spacing=12,
                            run_spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                info_tile("Status", state.if_connection_status, 210),
                                info_tile("API key source", key_source_label, 190),
                                info_tile("Idle timeout", "Paused" if state.if_polling_paused else "15 min", 150),
                            ],
                        ),
                        ft.Row(
                            wrap=True,
                            spacing=10,
                            run_spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                api_key_tf,
                                ft.ElevatedButton("Test Connection", on_click=test_connection, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                                ft.OutlinedButton("Save Key", on_click=save_key),
                                ft.OutlinedButton("Clear API Key", on_click=clear_key),
                            ],
                        ),
                        ft.Row(
                            wrap=True,
                            spacing=10,
                            run_spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                session_dd,
                                ft.OutlinedButton("Refresh Sessions", on_click=refresh_sessions),
                            ],
                        ),
                    ],
                ),
            )

        def search_card() -> ft.Control:
            result = "Active" if state.if_selected_flight else "Not active / not searched"
            if state.if_user_stats and not state.if_selected_flight:
                result = "User found, no active flight"
            return glass_card(
                "Live Flight Search",
                ft.Column(
                    spacing=12,
                    controls=[
                        ft.Text("Search the selected Infinite Flight server by callsign, username, user ID, or flight ID.", size=12, color=tokens["muted"]),
                        search_tf,
                        ft.Row(
                            wrap=True,
                            spacing=10,
                            controls=[
                                ft.ElevatedButton("Find Live Flight", on_click=find_live_flight, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                                ft.OutlinedButton("Load Recent Activity", on_click=load_recent_activity),
                            ],
                        ),
                        info_tile("Result", result, 240),
                    ],
                ),
            )

        def current_flight_card() -> ft.Control:
            flight = state.if_selected_flight
            if not flight:
                content = ft.Text("No active simulated flight selected yet.", size=12, color=tokens["muted"])
            else:
                content = ft.Column(
                    spacing=12,
                    controls=[
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[
                            info_tile("Callsign", str(flight.get("callsign") or "—")),
                            info_tile("Username", str(flight.get("username") or flight.get("userId") or "—"), 190),
                            info_tile("Pilot state", IF_PILOT_STATES.get(int(flight.get("pilotState", 0) or 0), "—"), 170),
                        ]),
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[
                            info_tile("Altitude", f"{if_number(flight.get('altitude'))} ft"),
                            info_tile("Speed", f"{if_number(flight.get('speed'))} kt"),
                            info_tile("Heading", f"{if_number(flight.get('heading'))}°"),
                        ]),
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[
                            info_tile("Latitude", if_number(flight.get("latitude"), 4)),
                            info_tile("Longitude", if_number(flight.get("longitude"), 4)),
                            info_tile("Last report", str(flight.get("lastReport") or "—"), 190),
                        ]),
                    ],
                )
            return glass_card("Current Simulated Flight", content)

        def flight_plan_card() -> ft.Control:
            plan = state.if_selected_flight_plan
            if not plan:
                content = ft.Column(
                    spacing=12,
                    controls=[
                        ft.Text("Preview only. This does not import anything into the existing FMS route or Map page.", size=12, color=tokens["muted"]),
                        ft.ElevatedButton("Preview Flight Plan", on_click=preview_flight_plan, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                    ],
                )
            else:
                items = plan.get("flightPlanItems") if isinstance(plan.get("flightPlanItems"), list) else []
                names = plan_item_names(items)
                shown = "  •  ".join(names[:18]) if names else "No waypoint names returned"
                content = ft.Column(
                    spacing=12,
                    controls=[
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[
                            info_tile("Flight plan ID", str(plan.get("flightPlanId") or "—"), 260),
                            info_tile("Type", "IFR" if plan.get("flightPlanType") == 1 else "VFR" if plan.get("flightPlanType") == 0 else "—", 120),
                            info_tile("Last update", str(plan.get("lastUpdate") or "—"), 190),
                        ]),
                        ft.Container(
                            padding=12,
                            border_radius=14,
                            bgcolor=tokens["subpanel"],
                            border=ft.border.all(1, tokens["card_border"]),
                            content=ft.Text(shown, size=12, color=tokens["text"]),
                        ),
                        ft.Text("Preview only. Nothing is written into FMS route, Map, Log, Calendar, or Profile.", size=11, color=tokens["muted"]),
                    ],
                )
            return glass_card("Flight Plan Preview", content)

        def atc_card() -> ft.Control:
            rows = []
            for facility in state.if_active_atc[:8]:
                facility_type = IF_ATC_TYPES.get(int(facility.get("type", 10) or 10), "Unknown")
                airport = facility.get("airportName") or "Center"
                rows.append(
                    ft.Container(
                        padding=10,
                        border_radius=12,
                        bgcolor=tokens["subpanel"],
                        border=ft.border.all(1, tokens["card_border"]),
                        content=ft.Row(
                            spacing=10,
                            controls=[
                                ft.Container(width=84, content=ft.Text(str(airport), size=12, weight=ft.FontWeight.W_800, color=tokens["text"])),
                                ft.Container(width=96, content=ft.Text(facility_type, size=12, color=tokens["muted"])),
                                ft.Container(expand=True, content=ft.Text(str(facility.get("username") or facility.get("userId") or "—"), size=12, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)),
                            ],
                        ),
                    )
                )
            if not rows:
                rows = [ft.Text("No ATC data loaded for this session yet.", size=12, color=tokens["muted"])]
            return glass_card(
                "Active ATC Preview",
                ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(wrap=True, spacing=10, controls=[
                            ft.ElevatedButton("Refresh ATC", on_click=refresh_atc, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                            info_tile("Facilities", str(len(state.if_active_atc)), 120),
                        ]),
                        *rows,
                    ],
                ),
            )

        def recent_activity_card() -> ft.Control:
            rows = []
            for entry in state.if_recent_activity[:5]:
                route = f"{entry.get('originAirport') or '—'} → {entry.get('destinationAirport') or '—'}"
                subtitle = f"{entry.get('server') or '—'} - {if_time_minutes(entry.get('totalTime'))} - {entry.get('landingCount', 0)} landing(s)"
                rows.append(
                    ft.Container(
                        padding=10,
                        border_radius=12,
                        bgcolor=tokens["subpanel"],
                        border=ft.border.all(1, tokens["card_border"]),
                        content=ft.Column(
                            tight=True,
                            spacing=3,
                            controls=[
                                ft.Text(route, size=12, weight=ft.FontWeight.W_800, color=tokens["text"]),
                                ft.Text(subtitle, size=11, color=tokens["muted"]),
                            ],
                        ),
                    )
                )
            if not rows:
                rows = [ft.Text("Recent Infinite Flight activity preview is empty. This does not sync to the FMS Log or Profile.", size=12, color=tokens["muted"])]
            return glass_card("Recent IF Activity Preview", ft.Column(spacing=10, controls=rows))

        def diagnostics_card() -> ft.Control:
            idle_age = "Not started"
            if state.if_last_activity_timestamp:
                idle_age = f"{int(max(0, if_now() - state.if_last_activity_timestamp))}s since last action"
            return glass_card(
                "API Diagnostics",
                ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[
                            info_tile("Last request", state.if_last_request_status, 220),
                            info_tile("Response time", state.if_last_response_ms, 150),
                            info_tile("Cache", state.if_cache_status, 240),
                        ]),
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[
                            info_tile("Activity", idle_age, 220),
                            info_tile("Polling", "Paused" if state.if_polling_paused else "Manual / visible only", 200),
                        ]),
                        ft.Text(state.if_last_error or "No API error reported.", size=12, color="#FF8080" if state.if_last_error else tokens["muted"]),
                    ],
                ),
            )

        return build_tab_page(
            "LIVE API",
            ft.Container(
                expand=True,
                padding=18,
                content=ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=16,
                    controls=[
                        connection_card(),
                        ft.Row(
                            wrap=True,
                            spacing=16,
                            run_spacing=16,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                            controls=[
                                ft.Container(width=430, content=search_card()),
                                ft.Container(width=660, content=current_flight_card()),
                            ],
                        ),
                        ft.Row(
                            wrap=True,
                            spacing=16,
                            run_spacing=16,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                            controls=[
                                ft.Container(width=540, content=flight_plan_card()),
                                ft.Container(width=540, content=atc_card()),
                            ],
                        ),
                        ft.Row(
                            wrap=True,
                            spacing=16,
                            run_spacing=16,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                            controls=[
                                ft.Container(width=540, content=recent_activity_card()),
                                ft.Container(width=540, content=diagnostics_card()),
                            ],
                        ),
                    ],
                ),
            ),
            overlay_opacity=0.08,
        )

    def infinite_flight_page():
        def info_tile(label: str, value: str, width: int = 150) -> ft.Control:
            return ft.Container(
                width=width,
                height=72,
                padding=ft.padding.symmetric(horizontal=12, vertical=9),
                border_radius=14,
                bgcolor=tokens["subpanel"],
                border=ft.border.all(1, tokens["card_border"]),
                content=ft.Column(
                    tight=True,
                    spacing=3,
                    controls=[
                        ft.Text(label, size=10, color=tokens["muted"], weight=ft.FontWeight.W_700),
                        ft.Text(value or "-", size=14, weight=ft.FontWeight.W_900, color=tokens["text"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
            )

        def set_session_from_dropdown(e=None):
            if e is not None and getattr(e, "control", None):
                selected = if_select_session(e.control.value or "")
                if not selected:
                    state.if_last_request_status = "Server selection failed"
                    state.if_last_error = f"Could not match selected server: {e.control.value}"
                    refresh_ui()
                    return
                state.if_selected_flight = {}
                state.if_selected_flight_plan = {}
                state.if_selected_route_points = []
                state.if_selected_route_label = ""
                state.if_selected_route_start_label = ""
                state.if_selected_route_end_label = ""
                state.if_live_flights = []
                if_load_live_traffic(force=True)
                refresh_ui()

        api_key_tf = ft.TextField(
            label="Infinite Flight API key",
            hint_text=if_saved_key_hint(),
            width=340,
            password=True,
            can_reveal_password=True,
            border_radius=16,
            filled=True,
            bgcolor=tokens["input_bg"],
            color=tokens["text"],
            border_color=tokens["card_border"],
            focused_border_color=tokens["accent"],
            label_style=ft.TextStyle(color=tokens["muted"]),
        )
        session_dd = ft.Dropdown(
            label="Server / session",
            value=state.if_selected_session_id or None,
            options=if_session_options(),
            width=310,
            border_radius=16,
            filled=True,
            bgcolor=tokens["input_bg"],
            color=tokens["text"],
            border_color=tokens["card_border"],
            label_style=ft.TextStyle(color=tokens["muted"]),
            disabled=not bool(state.if_sessions),
        )
        session_dd.on_change = set_session_from_dropdown

        def test_connection(e=None):
            if_mark_activity()
            typed_key = (api_key_tf.value or "").strip()
            if typed_key:
                if_save_api_key_value(typed_key)
            state.if_sessions = if_get_sessions(force=True)
            if_ensure_selected_session()
            if state.if_sessions:
                state.if_connection_status = f"Connected - {len(state.if_sessions)} sessions"
                if_load_live_traffic(force=True)
                show_snack("Infinite Flight API connection ready.")
            else:
                state.if_live_flights = []
                show_snack("Infinite Flight API connection did not return sessions.")
            refresh_ui()

        def save_key(e=None):
            key = (api_key_tf.value or "").strip()
            if not key:
                state.if_last_error = "Enter an API key before saving."
                state.if_last_request_status = "No key entered"
                refresh_ui()
                return
            try:
                if_save_api_key_value(key)
                state.if_last_request_status = "API key saved locally"
                state.if_last_error = ""
                show_snack("Infinite Flight API key saved locally.")
            except Exception as ex:
                state.if_last_request_status = "Could not save API key"
                state.if_last_error = str(ex)
            refresh_ui()

        def clear_key(e=None):
            if_clear_local_api_key()
            show_snack("Local Infinite Flight API key cleared.")
            refresh_ui()

        def refresh_sessions(e=None):
            if_mark_activity()
            state.if_sessions = if_get_sessions(force=True)
            if_ensure_selected_session()
            refresh_ui()

        def refresh_traffic(e=None):
            if_load_live_traffic(force=True)
            refresh_ui()

        def select_server_type(world_type_name: str):
            if not state.if_sessions:
                state.if_sessions = if_get_sessions(force=True)
            selected = if_select_session(world_type_name)
            if selected:
                state.if_selected_flight = {}
                state.if_selected_flight_plan = {}
                state.if_selected_route_points = []
                state.if_selected_route_label = ""
                state.if_selected_route_start_label = ""
                state.if_selected_route_end_label = ""
                state.if_live_flights = []
                if_load_live_traffic(force=True)
            else:
                state.if_last_request_status = "Server unavailable"
                state.if_last_error = f"No active {world_type_name} server was returned by the API."
            refresh_ui()

        def toggle_live_refresh(e=None):
            state.if_live_refresh_enabled = bool(getattr(getattr(e, "control", None), "value", False))
            if state.if_live_refresh_enabled:
                if_mark_activity()
                if_load_live_traffic(force=True)
                show_snack("Live traffic refresh enabled.")
            else:
                show_snack("Live traffic refresh paused.")
            refresh_ui()

        def select_aircraft(flight_id: str):
            if_select_map_flight(flight_id)
            refresh_ui()

        def connection_card() -> ft.Control:
            key_source = if_current_api_key()[1]
            key_source_label = "Environment variable" if key_source == "environment" else "Local config" if key_source == "local config" else "Not saved"
            live_refresh_switch = ft.Switch(label="Live refresh (15s)", value=state.if_live_refresh_enabled)
            live_refresh_switch.on_change = toggle_live_refresh
            selected_session = next((session for session in state.if_sessions if str(session.get("id") or "") == str(state.if_selected_session_id or "")), {})
            selected_world = IF_WORLD_TYPES.get(int(selected_session.get("worldType", -1) or -1), "")

            def server_button(label: str) -> ft.Control:
                active = selected_world == label
                if active:
                    return ft.ElevatedButton(label, on_click=lambda e, value=label: select_server_type(value), bgcolor=tokens["accent"], color=ft.Colors.WHITE)
                return ft.OutlinedButton(label, on_click=lambda e, value=label: select_server_type(value))

            return glass_card(
                "Infinite Flight Live API",
                ft.Column(
                    spacing=12,
                    controls=[
                        ft.Container(
                            padding=12,
                            border_radius=14,
                            bgcolor=ft.Colors.with_opacity(0.12, tokens["accent"]),
                            border=ft.border.all(1, ft.Colors.with_opacity(0.22, tokens["accent"])),
                            content=ft.Text(
                                "Simulator use only. Not for real-world aviation, dispatch, navigation, or flight operations.",
                                size=12,
                                weight=ft.FontWeight.W_800,
                                color=tokens["text"],
                            ),
                        ),
                        ft.Row(
                            wrap=True,
                            spacing=10,
                            run_spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                info_tile("Status", state.if_connection_status, 200),
                                info_tile("API key source", key_source_label, 170),
                                info_tile("Aircraft loaded", str(len(state.if_live_flights)), 145),
                                info_tile("Last refresh", state.if_last_traffic_refresh, 145),
                            ],
                        ),
                        ft.Row(
                            wrap=True,
                            spacing=10,
                            run_spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                api_key_tf,
                                ft.ElevatedButton("Test Connection", on_click=test_connection, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                                ft.OutlinedButton("Save Key", on_click=save_key),
                                ft.OutlinedButton("Clear API Key", on_click=clear_key),
                            ],
                        ),
                        ft.Row(
                            wrap=True,
                            spacing=10,
                            run_spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                server_button("Casual"),
                                server_button("Training"),
                                server_button("Expert"),
                                session_dd,
                                ft.ElevatedButton("Refresh Traffic", on_click=refresh_traffic, bgcolor=tokens["accent"], color=ft.Colors.WHITE),
                                ft.OutlinedButton("Refresh Sessions", on_click=refresh_sessions),
                                live_refresh_switch,
                            ],
                        ),
                    ],
                ),
            )

        def aircraft_marker(flight: dict, selected: bool) -> ft.Control:
            fill = tokens["accent"] if selected else "#50E3C2"
            heading = if_flight_heading(flight)
            rotation = math.radians(heading)
            aircraft_icon_src = asset_rel_path_if_exists("icons/nav/live_aircraft_north.png")
            icon_size = 28 if selected else 24
            icon_left = 5 if selected else 7
            icon_top = 5 if selected else 7
            icon_control = (
                ft.Image(
                    src=aircraft_icon_src,
                    width=icon_size,
                    height=icon_size,
                    fit=ft.BoxFit.CONTAIN,
                    color=fill,
                    color_blend_mode=ft.BlendMode.SRC_IN,
                    rotate=rotation,
                    left=icon_left,
                    top=icon_top,
                )
                if aircraft_icon_src
                else ft.Icon(
                    ft.Icons.FLIGHT,
                    size=25 if selected else 21,
                    color=fill,
                    rotate=math.radians(heading - 45.0),
                    left=6 if selected else 8,
                    top=6 if selected else 8,
                )
            )
            return ft.Container(
                width=38,
                height=38,
                tooltip=if_flight_display_name(flight),
                on_click=lambda e, fid=str(flight.get("flightId") or ""): select_aircraft(fid),
                ink=True,
                border_radius=999,
                content=ft.Stack(
                    width=38,
                    height=38,
                    controls=[
                        ft.Container(
                            left=5,
                            top=5,
                            width=28,
                            height=28,
                            border_radius=999,
                            bgcolor=ft.Colors.with_opacity(0.12 if selected else 0.04, fill),
                            border=ft.border.all(1.5, ft.Colors.with_opacity(0.55 if selected else 0.16, fill)),
                            shadow=ft.BoxShadow(
                                blur_radius=12 if selected else 4,
                                spread_radius=0,
                                color=ft.Colors.with_opacity(0.35 if selected else 0.18, fill),
                                offset=ft.Offset(0, 0),
                            ),
                        ),
                        icon_control,
                    ],
                ),
            )

        def route_endpoint_marker(label: str, color: str) -> ft.Control:
            return ft.Container(
                width=112,
                height=34,
                alignment=ft.Alignment(0, 0),
                border_radius=999,
                bgcolor=tokens["panel"],
                border=ft.border.all(1, color),
                content=ft.Text(label, size=10, weight=ft.FontWeight.W_800, color=tokens["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            )

        def traffic_map_card() -> ft.Control:
            if ftm is None:
                return glass_card(
                    "Live Traffic Map",
                    ft.Text("flet-map is not installed, so the live traffic map cannot render in this build.", size=12, color=tokens["muted"]),
                )

            tile_url, map_attribution, active_map_label = active_maptiler_tile_url()
            layers = [
                ftm.TileLayer(url_template=tile_url),
                ftm.SimpleAttribution(text=map_attribution, on_click=lambda e: e.page.launch_url("https://carto.com/")),
            ]

            selected_id = str(state.if_selected_flight.get("flightId") or "")
            selected_position = if_flight_position(state.if_selected_flight) if state.if_selected_flight else None
            route_points = state.if_selected_route_points or []

            if len(route_points) >= 2:
                layers.append(
                    ftm.PolylineLayer(
                        polylines=[
                            ftm.PolylineMarker(
                                coordinates=[ftm.MapLatitudeLongitude(lat, lon) for lat, lon in route_points],
                                color=ft.Colors.with_opacity(0.28, tokens["accent"]),
                                stroke_width=8,
                                border_color=ft.Colors.with_opacity(0.10, ft.Colors.WHITE),
                                border_stroke_width=1,
                            ),
                            ftm.PolylineMarker(
                                coordinates=[ftm.MapLatitudeLongitude(lat, lon) for lat, lon in route_points],
                                color=tokens["accent"],
                                stroke_width=3.2,
                            )
                        ]
                    )
                )

            marker_limit = 700
            visible_flights = state.if_live_flights[:marker_limit]
            markers = []
            for flight in visible_flights:
                position = if_flight_position(flight)
                if not position:
                    continue
                fid = str(flight.get("flightId") or "")
                markers.append(
                    ftm.Marker(
                        coordinates=ftm.MapLatitudeLongitude(position[0], position[1]),
                        width=38,
                        height=38,
                        alignment=ft.Alignment(0, 0),
                        content=aircraft_marker(flight, fid == selected_id),
                    )
                )

            if len(route_points) >= 2:
                markers.extend(
                    [
                        ftm.Marker(
                            coordinates=ftm.MapLatitudeLongitude(route_points[0][0], route_points[0][1]),
                            width=112,
                            height=34,
                            alignment=ft.Alignment(0, 1),
                            content=route_endpoint_marker(state.if_selected_route_start_label or "START", tokens["accent"]),
                        ),
                        ftm.Marker(
                            coordinates=ftm.MapLatitudeLongitude(route_points[-1][0], route_points[-1][1]),
                            width=112,
                            height=34,
                            alignment=ft.Alignment(0, 1),
                            content=route_endpoint_marker(state.if_selected_route_end_label or "END", "#50E3C2"),
                        ),
                    ]
                )

            if markers:
                layers.append(ftm.MarkerLayer(markers=markers))

            center = ftm.MapLatitudeLongitude(25.0, 10.0)
            zoom = 2.2
            if selected_position:
                center = ftm.MapLatitudeLongitude(selected_position[0], selected_position[1])
                zoom = 4.0

            world_map = ftm.Map(
                expand=True,
                initial_center=center,
                initial_zoom=zoom,
                min_zoom=2.0,
                max_zoom=10.0,
                bgcolor="#020617",
                keep_alive=True,
                interaction_configuration=ftm.InteractionConfiguration(flags=ftm.InteractionFlag.ALL),
                layers=layers,
            )

            footer_text = f"{len(state.if_live_flights)} valid aircraft loaded from {state.if_selected_session_name or 'selected session'}."
            if len(state.if_live_flights) > marker_limit:
                footer_text += f" Showing first {marker_limit} for performance."
            footer_text += f" Map style: {active_map_label}."

            return glass_card(
                "Live Traffic Map",
                ft.Column(
                    spacing=12,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Text("Click an aircraft to load its filed route and flight details.", size=12, color=tokens["muted"]),
                                ft.Text(footer_text, size=11, color=tokens["muted"], text_align=ft.TextAlign.RIGHT),
                            ],
                        ),
                        ft.Container(
                            height=820,
                            border_radius=16,
                            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                            border=ft.border.all(1, tokens["card_border"]),
                            content=ft.Stack(
                                expand=True,
                                controls=[
                                    world_map,
                                    ft.Container(
                                        right=14,
                                        top=14,
                                        width=382,
                                        content=selected_flight_card(),
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
                expand=True,
            )

        def selected_flight_card() -> ft.Control:
            flight = state.if_selected_flight
            if not flight:
                content = ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text("Select an aircraft marker on the map.", size=12, color=tokens["muted"]),
                        info_tile("Aircraft loaded", str(len(state.if_live_flights)), 170),
                        info_tile("Selected route", "None", 170),
                    ],
                )
            else:
                position = if_flight_position(flight)
                route_points = state.if_selected_route_points or []
                route_label = state.if_selected_route_label or "No route available"
                distance_label = if_route_distance_label(route_points)
                content = ft.Column(
                    spacing=12,
                    controls=[
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[
                            info_tile("Callsign", str(flight.get("callsign") or "-"), 150),
                            info_tile("Username", str(flight.get("username") or flight.get("userId") or "-"), 190),
                        ]),
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[
                            info_tile("Altitude", f"{if_number(flight.get('altitude'))} ft", 150),
                            info_tile("Speed", f"{if_number(flight.get('speed'))} kt", 150),
                            info_tile("Heading", f"{if_number(flight.get('heading'))} deg", 150),
                        ]),
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[
                            info_tile("Latitude", if_number(position[0] if position else None, 4), 150),
                            info_tile("Longitude", if_number(position[1] if position else None, 4), 150),
                            info_tile("Route distance", distance_label, 170),
                        ]),
                        ft.Container(
                            padding=12,
                            border_radius=14,
                            bgcolor=tokens["subpanel"],
                            border=ft.border.all(1, tokens["card_border"]),
                            content=ft.Column(
                                tight=True,
                                spacing=4,
                                controls=[
                                    ft.Text("Filed route", size=10, color=tokens["muted"], weight=ft.FontWeight.W_700),
                                    ft.Text(route_label, size=13, weight=ft.FontWeight.W_900, color=tokens["text"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(
                                        "Route line is drawn only from the selected aircraft's Infinite Flight flight plan.",
                                        size=11,
                                        color=tokens["muted"],
                                    ),
                                ],
                            ),
                        ),
                        ft.Text(f"Last report: {flight.get('lastReport') or '-'}", size=11, color=tokens["muted"]),
                    ],
                )
            return ft.Container(
                padding=14,
                border_radius=16,
                bgcolor=ft.Colors.with_opacity(0.92, tokens["panel"]),
                border=ft.border.all(1, tokens["card_border"]),
                shadow=ft.BoxShadow(
                    blur_radius=18,
                    spread_radius=1,
                    color=ft.Colors.with_opacity(0.22, ft.Colors.BLACK),
                    offset=ft.Offset(0, 6),
                ),
                content=ft.Column(
                    tight=True,
                    spacing=10,
                    controls=[
                        ft.Text("Selected Aircraft", size=13, weight=ft.FontWeight.W_800, color=tokens["text"]),
                        ft.Divider(height=8, opacity=0.12),
                        content,
                    ],
                ),
            )

        def diagnostics_card() -> ft.Control:
            idle_age = "Not started"
            if state.if_last_activity_timestamp:
                idle_age = f"{int(max(0, if_now() - state.if_last_activity_timestamp))}s since last action"
            return glass_card(
                "API Diagnostics",
                ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[
                            info_tile("Last request", state.if_last_request_status, 220),
                            info_tile("Response time", state.if_last_response_ms, 150),
                            info_tile("Cache", state.if_cache_status, 230),
                        ]),
                        ft.Row(wrap=True, spacing=10, run_spacing=10, controls=[
                            info_tile("Activity", idle_age, 190),
                            info_tile("Polling", "Manual refresh", 170),
                            info_tile("Idle timeout", "Paused" if state.if_polling_paused else "15 min", 150),
                        ]),
                        ft.Text(state.if_last_error or "No API error reported.", size=12, color="#FF8080" if state.if_last_error else tokens["muted"]),
                    ],
                ),
            )

        return build_tab_page(
            "LIVE FLIGHTS",
            ft.Container(
                expand=True,
                padding=8,
                content=ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=0,
                    controls=[
                        traffic_map_card(),
                    ],
                ),
            ),
            overlay_opacity=0.08,
        )

    def about_page():
        modules = [
            "Overview", "Home", "Payload", "Takeoff", "Landing",
            "Map", "Calendar", "Log", "Profile", "Settings", "About",
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
                    info_line("Version", "V10"),
                    info_line("Author", "Sam Samadi"),
                    info_line("Editor", "Sam Samadi"),
                    info_line("Application type", "Python Flet desktop application"),
                    info_line("Build type", "Local desktop build"),
                    info_line("Aircraft images", "Aircraft images are from Infinite Flight"),
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
                    ft.Text("FMS stores configuration data and operational records locally as JSON files in the application folder. This includes app settings, custom airline entries, calendar flights, and profile information.", size=12, color=tokens["text"]),
                    info_line("Primary app folder", r"C:\FCAM_FLET"),
                    info_line("Assets folder", r"C:\FCAM_FLET\assets"),
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

    def app_shell():
        refresh_header_texts()

        def current_page_view():
            selected = max(0, min(12, int(state.selected_tab_index or 0)))
            if selected == 0:
                return overview_page()
            if selected == 1:
                return home_page()
            if selected == 2:
                return build_tab_page("PAYLOAD", seats_view(), overlay_opacity=0.08)
            if selected == 3:
                return build_tab_page("PAYLOAD", seats_view(), overlay_opacity=0.08)
            if selected == 4:
                return build_tab_page("TAKEOFF", takeoff_view(), overlay_opacity=0.08)
            if selected == 5:
                return build_tab_page("LANDING", landing_view(), overlay_opacity=0.08)
            if selected == 6:
                return build_tab_page("MAP", map_view(), overlay_opacity=0.08)
            if selected == 7:
                return calendar_view()
            if selected == 8:
                return log_view()
            if selected == 9:
                return profile_view()
            if selected == 10:
                return settings_page()
            if selected == 12:
                return infinite_flight_page()
            return about_page()

        def nav_icon_content(label: str, icon: str, icon_file: Optional[str], selected: bool) -> ft.Control:
            icon_src = asset_rel_path_if_exists(icon_file)
            if icon_src:
                return ft.Image(
                    src=icon_src,
                    width=24,
                    height=24,
                    fit=ft.BoxFit.CONTAIN,
                    opacity=1.0 if selected else 0.82,
                    key=f"nav-icon-{label.lower().replace(' ', '-')}-{state.logo_refresh_nonce}",
                )
            return ft.Icon(
                icon,
                size=24,
            )

        def rail_button(index: int, label: str, icon: str, icon_file: Optional[str] = None):
            selected = index == state.selected_tab_index
            button_body = ft.Container(
                width=56,
                height=52,
                border_radius=18,
                alignment=ft.Alignment(0, 0),
                bgcolor=ft.Colors.with_opacity(tokens["shell_nav_selected_opacity"], tokens["accent"]) if selected else ft.Colors.with_opacity(tokens["shell_nav_idle_opacity"], tokens["shell_nav_idle"]),
                border=ft.border.all(1, ft.Colors.with_opacity(tokens["shell_nav_selected_border_opacity"], tokens["accent"])) if selected else ft.border.all(1, ft.Colors.with_opacity(tokens["shell_nav_idle_border_opacity"], ft.Colors.WHITE)),
                tooltip=label,
                content=nav_icon_content(label, icon, icon_file, selected),
            )
            return ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap_down=lambda e, idx=index: go_to_tab(idx),
                on_tap=lambda e, idx=index: go_to_tab(idx),
                content=button_body,
            )

        def current_tab_title() -> str:
            titles = [
                "Overview",
                "Home",
                "Payload",
                "Payload",
                "Takeoff",
                "Landing",
                "Map",
                "Calendar",
                "Log",
                "Profile",
                "Settings",
                "About",
                "Live Flights",
            ]
            idx = max(0, min(len(titles) - 1, int(state.selected_tab_index or 0)))
            return titles[idx]

        refresh_header_banner_tick()

        top_bar = ft.Container(
            padding=ft.padding.only(left=18, right=16, top=12, bottom=10),
            bgcolor=ft.Colors.with_opacity(tokens["shell_topbar_opacity"], tokens["shell_topbar"]),
            border=ft.border.only(bottom=ft.BorderSide(1, tokens["shell_border"])),
            content=ft.Row(
                spacing=16,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=140,
                        alignment=ft.Alignment(-1, 0),
                        content=ft.Text(current_tab_title(), size=18, weight=ft.FontWeight.W_800, color=tokens["shell_text"]),
                    ),
                    ft.Container(
                        expand=True,
                        height=34,
                        alignment=ft.Alignment(-1, 0),
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        bgcolor=ft.Colors.TRANSPARENT,
                        content=header_route_line_host,
                    ),
                    ft.Row(
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(
                                width=180,
                                height=44,
                                alignment=ft.Alignment(1, 0),
                                content=airline_logo_image(
                                    state.airline,
                                    width=170,
                                    height=42,
                                    opacity=0.98,
                                    fit=ft.BoxFit.CONTAIN,
                                    key_prefix="topbar-logo",
                                ) if state.airline else ft.Text("No airline selected", size=12, color=tokens["shell_muted"]),
                            ),
                            ft.OutlinedButton("Logout", on_click=do_logout),
                        ],
                    ),
                ],
            ),
        )

        navigation_rail = ft.Container(
            width=78,
            padding=ft.padding.only(top=14, bottom=14),
            bgcolor=ft.Colors.with_opacity(tokens["shell_rail_opacity"], tokens["shell_rail"]),
            border=ft.border.only(right=ft.BorderSide(1, tokens["shell_border"])),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    rail_button(1, "Home", "home", "icons/nav/home.png"),
                    rail_button(0, "Overview", "dashboard", "icons/nav/overview.png"),
                    rail_button(2, "Payload", "event_seat", "icons/nav/seats_baggage.png"),
                    rail_button(4, "Takeoff", "flight_takeoff", "icons/nav/takeoff.png"),
                    rail_button(5, "Landing", "flight_land", "icons/nav/landing.png"),
                    rail_button(6, "Map", "map", "icons/nav/map.png"),
                    rail_button(12, "Live Flights", "public", "icons/nav/live_api.png"),
                    rail_button(7, "Calendar", "calendar_month", "icons/nav/calendar.png"),
                    rail_button(8, "Log", "receipt_long", "icons/nav/log.png"),
                    ft.Container(expand=True),
                    rail_button(9, "Profile", "person", "icons/nav/profile.png"),
                    rail_button(10, "Settings", "settings", "icons/nav/settings.png"),
                    rail_button(11, "About", "info_outline", "icons/nav/about.png"),
                ],
            ),
        )

        main_area = ft.Container(
            expand=True,
            bgcolor=ft.Colors.TRANSPARENT,
            padding=ft.padding.only(top=0),
            alignment=ft.Alignment(-1, -1),
            content=ft.Container(
                expand=True,
                bgcolor=ft.Colors.TRANSPARENT,
                alignment=ft.Alignment(-1, -1),
                content=current_page_view(),
            ),
        )

        shell_content = ft.Column(
            expand=True,
            spacing=0,
            controls=[
                top_bar,
                ft.Row(
                    expand=True,
                    spacing=0,
                    controls=[
                        navigation_rail,
                        main_area,
                    ],
                ),
            ],
        )

        # Background Project rewrite. This is the only app background system.
        # It supports PNG, JPG, JPEG, and WEBP. Put your file here:
        # assets/backgrounds/app_background.png
        daylight_mode = str(state.display_mode).lower() == "daylight"
        background_image = daylight_background_src() if daylight_mode else app_background_src()
        airline_overlay_color = AIRLINE_BACKGROUND.get(state.airline, tokens["bg"]) if state.airline else tokens["bg"]
        brightness = clamp_setting(state.display_brightness, 0.70, 1.30, 1.0)
        contrast = clamp_setting(state.display_contrast, 0.70, 1.35, 1.0)
        airline_overlay_opacity = clamp_setting(state.airline_overlay_opacity, 0.0, 0.80, 0.50)

        background_layers = [
            ft.Container(expand=True, bgcolor=tokens["bg"]),
        ]
        if background_image:
            background_layers.append(
                ft.Container(
                    expand=True,
                    image=ft.DecorationImage(
                        src=background_image,
                        fit=ft.BoxFit.COVER,
                        opacity=1.0,
                    ),
                )
            )
            # Airline tint. In daylight mode this is capped so the background
            # image keeps its original colors instead of becoming washed out.
            effective_airline_overlay_opacity = min(airline_overlay_opacity, 0.14) if daylight_mode else airline_overlay_opacity
            if effective_airline_overlay_opacity > 0:
                background_layers.append(
                    ft.Container(
                        expand=True,
                        bgcolor=ft.Colors.with_opacity(effective_airline_overlay_opacity, airline_overlay_color),
                    )
                )
            # Brightness and contrast overlays. Daylight mode uses a subtle dark
            # readability layer instead of a white wash, preserving image color.
            if daylight_mode:
                daylight_dark_opacity = max(
                    0.08,
                    min(
                        0.30,
                        0.14 + max(0.0, 1.0 - brightness) * 0.35 - max(0.0, brightness - 1.0) * 0.05,
                    ),
                )
                background_layers.append(
                    ft.Container(
                        expand=True,
                        bgcolor=ft.Colors.with_opacity(daylight_dark_opacity, ft.Colors.BLACK),
                    )
                )
                if brightness > 1.0:
                    background_layers.append(
                        ft.Container(
                            expand=True,
                            bgcolor=ft.Colors.with_opacity(min(0.08, (brightness - 1.0) * 0.16), ft.Colors.WHITE),
                        )
                    )
            else:
                dark_opacity = max(0.0, min(0.55, 0.16 + max(0.0, 1.0 - brightness) * 0.30 + max(0.0, contrast - 1.0) * 0.10))
                background_layers.append(
                    ft.Container(
                        expand=True,
                        bgcolor=ft.Colors.with_opacity(dark_opacity, ft.Colors.BLACK),
                    )
                )
                if brightness > 1.0:
                    background_layers.append(
                        ft.Container(
                            expand=True,
                            bgcolor=ft.Colors.with_opacity(min(0.18, (brightness - 1.0) * 0.30), ft.Colors.WHITE),
                        )
                    )
            if contrast < 1.0:
                background_layers.append(
                    ft.Container(
                        expand=True,
                        bgcolor=ft.Colors.with_opacity((1.0 - contrast) * 0.12, "#808080"),
                    )
                )

        return ft.Stack(
            expand=True,
            controls=[
                *background_layers,
                shell_content,
            ],
        )

    def on_tab_change(e):
        selected = e.control.selected_index
        if selected is None:
            return
        selected = max(0, min(12, int(selected)))
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
                current_second = now_local_str()
                should_update_clock = current_second != last_header_second
                progress_refresh_seconds = 15 if bool(getattr(state, "low_performance_mode", False)) else OVERVIEW_PROGRESS_REFRESH_SECONDS
                should_update_progress = (
                    state.overview_takeoff_start_timestamp is not None
                    and state.overview_progress_running
                    and time.time() - last_overview_progress_update >= progress_refresh_seconds
                )
                should_update_if_traffic = (
                    state.selected_tab_index == 12
                    and bool(getattr(state, "if_live_refresh_enabled", False))
                    and time.time() - float(getattr(state, "if_last_live_refresh_attempt", 0.0) or 0.0) >= 15.0
                )

                should_update_banner = refresh_header_banner_tick()

                if not should_update_clock and not should_update_progress and not should_update_banner and not should_update_if_traffic:
                    continue

                if should_update_if_traffic:
                    await asyncio.to_thread(if_load_live_traffic, False, False)
                    if bool(getattr(state, "if_polling_paused", False)):
                        state.if_live_refresh_enabled = False

                if should_update_clock:
                    last_header_second = current_second
                    refresh_header_texts()

                if should_update_if_traffic:
                    refresh_ui()
                elif should_update_progress:
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
                        state.selected_tab_index == 12
                        and bool(getattr(state, "if_live_refresh_enabled", False))
                        and time.time() - float(getattr(state, "if_last_live_refresh_attempt", 0.0) or 0.0) >= 15.0
                    )
                    should_update_banner = refresh_header_banner_tick()
                    if should_update_clock:
                        last_header_second = current_second
                        refresh_header_texts()
                    if should_update_if_traffic:
                        if_load_live_traffic(False, False)
                        if bool(getattr(state, "if_polling_paused", False)):
                            state.if_live_refresh_enabled = False
                        refresh_ui()
                    elif should_update_progress:
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


if __name__ == "__main__":
    webview_flags = [flag for flag in ("--globe-webview", "--mapcn-webview") if flag in sys.argv]
    if webview_flags:
        arg_index = sys.argv.index(webview_flags[0])
        raise SystemExit(run_globe_webview_host(sys.argv[arg_index + 1 :]))
    if not _acquire_fms_single_instance():
        raise SystemExit(0)
    runtime_assets_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"
    ft.app(target=main, assets_dir=str(runtime_assets_dir))
