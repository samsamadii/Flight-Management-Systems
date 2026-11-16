# Flight Management Systems — V14 Public Portfolio Edition

Flight Management Systems is a Windows desktop application built with Python and Flet for aviation simulation, education, and personal workflow practice. This public portfolio version opens directly into the main application and does not display or require a login.

> **Aviation safety warning:** This software is an educational and simulation project. It is not certified, approved, validated, or suitable for real-world flight planning, navigation, aircraft performance calculations, dispatch, or flight operations. Never use its calculations, weather data, maps, or outputs for an operational or safety-critical decision.

## Features

- Airline and aircraft selection with airline-aware presentation.
- Home and overview dashboards with route, flight-status, checklist, ramp-status, and progress views.
- Passenger seating, cabin distribution, baggage estimation, and cargo/payload tools.
- Simulation-oriented takeoff, landing, descent, vertical-speed, and fuel-planning interfaces.
- METAR retrieval and airport weather context.
- Interactive maps and a bundled local Globe.gl route visualization.
- Calendar planning, JSON import/export, completed-flight logs, and flight hibernation/restore.
- A local pilot profile with activity and career statistics.
- Optional Infinite Flight live tracker with traffic, routes, and airport context.
- Display, performance, audio, unit, custom-airline, background, and data-management settings.

## Requirements

- Windows 10 or Windows 11.
- Python 3.12 with the Windows `py` launcher.
- Microsoft Edge WebView2 Runtime for the local Globe.gl view.
- Internet access for live maps, weather, METAR, geocoding, and Infinite Flight features.

## Windows setup

Download and extract the repository ZIP. Open PowerShell in the extracted folder and run:

```powershell
.\Start-FMS.cmd
```

You can also double-click `Start-FMS.cmd`. It creates a local Python environment, installs the dependencies on first run, and opens FMS. Later runs reuse the environment.

For the portable edition, extract the Windows ZIP attached to the GitHub release and open `FMS V14 Public.exe`. Keep the `_internal` folder beside the executable. The portable edition includes Python.

## Environment variables

Optionally enable MapTiler tiles for the current PowerShell session:

```powershell
$env:MAPTILER_API_KEY="your_maptiler_api_key_here"
```

Optionally enable Infinite Flight live-data features:

```powershell
$env:INFINITE_FLIGHT_API_KEY="your_infinite_flight_api_key_here"
```

`.env.example` documents the variable names, but the application does not automatically load a `.env` file. Never commit real keys or `infinite_flight_config.json`.

## Run

Run the public no-login application from the project root:

```powershell
.\Start-FMS.cmd
```

The app opens directly with the local display name `User`. On Windows, this edition stores its data under `%LOCALAPPDATA%\Flight Management Systems Public`.

## Project structure

```text
.
├── flightmanagementsystems_public.py   # Public no-login application
├── assets/                             # Runtime images, icons, and audio
├── globe-gl-test-web/dist/             # Local Globe.gl bundle used by the app
├── requirements.txt                    # Python runtime dependencies
├── .env.example                        # Secret-free environment template
├── LICENSE                             # Proprietary All Rights Reserved terms
└── *.md                                # Security, copyright, contribution, and notices
```

Runtime data—including `calendar_flights.json`, `profile_data.json`, `app_settings.json`, `infinite_flight_config.json`, `flight_hibernation.json`, exports, logs, and caches—is excluded by `.gitignore`.

## Privacy and security

- Local JSON files may contain profile information, routes, flight history, settings, or API credentials.
- Saving an Infinite Flight key inside the application stores it locally using Windows DPAPI. Prefer the environment variable.
- Do not place real keys, credentials, personal routes, private callsigns, profile data, or diagnostic logs in issues or screenshots.
- Revoke and replace any credential that is accidentally exposed.
- See `SECURITY.md` before reporting a vulnerability.

## Assets and third-party content

This package contains third-party libraries and may contain third-party photographs, aircraft imagery, airline and manufacturer logos, maps, textures, icons, backgrounds, and audio. Some content does not yet have confirmed redistribution records. Public availability does not establish permission to redistribute third-party material.

Verify or replace every asset whose ownership, licence, attribution, trademark status, or redistribution permission has not been confirmed. See `THIRD_PARTY_NOTICES.md` for the detailed inventory.

## Copyright and licence

Copyright © 2026 Sam Samadi. All rights reserved.

This is proprietary software. Public visibility does not make it open source or grant permission to copy, modify, redistribute, sublicense, sell, commercially exploit, or create derivative works. Public hosting can allow technical viewing and downloading; the licence provides legal terms, not technical copy prevention. See `LICENSE` and `COPYRIGHT.md`.

Third-party material remains subject to its owners' terms and is not relicensed by the project's proprietary licence.

## Author

Sam Samadi

