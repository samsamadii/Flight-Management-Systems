# Third-party notices

This file lists third-party components and content used by Flight Management Systems. The project's MIT License covers the original source code. Third-party components and assets retain their own terms.

Where this file says **“Licence/redistribution permission must be verified before public release,”** no adequate licence record was found in the inspected project files. Do not publish that material until the required rights and attribution have been confirmed.

## Python libraries

| Component | Use in the application | Notice status |
| --- | --- | --- |
| Flet and Flet Desktop | Desktop UI and runtime | Upstream licence and redistribution requirements apply; verify the selected release before distribution. |
| flet-map | Interactive tile maps, markers, and route lines | Upstream licence and redistribution requirements apply; verify before distribution. |
| flet-geolocator | Optional device-location integration | Upstream licence and redistribution requirements apply; verify before distribution. |
| pywebview | Local Globe.gl view through the Windows WebView2 backend | Upstream licence and redistribution requirements apply; verify before distribution. |
| pystray | Optional Windows system-tray integration | Upstream licence and redistribution requirements apply; verify before distribution. |
| Pillow | Image loading and login/tray image processing | Upstream licence and redistribution requirements apply; verify before distribution. |

Python standard-library modules used by the source are not third-party pip dependencies and are not listed in `requirements.txt`.

## JavaScript and embedded web components

`globe-gl-test-web/package.json` identifies these direct packages:

| Component | Declared version | Use | Notice status |
| --- | --- | --- | --- |
| `globe.gl` | `^2.44.0` | Interactive 3D route globe | Upstream licence and notices apply; verify before public release. |
| `three` | `^0.181.2` | WebGL rendering used by the globe | Upstream licence and notices apply; verify before public release. |
| `vite` | `^8.0.12` | Development/build tool | Upstream licence and notices apply; verify before public release. |

The existing `node_modules` directory contains transitive packages and is intentionally ignored. If the web bundle is rebuilt or redistributed, retain all notices required by the resolved dependency tree.

Microsoft Edge WebView2 is an external runtime used by pywebview on Windows and remains governed by Microsoft's terms.

The Live Flights map bundles [Mapbox GL RTL Text 0.3.0](https://github.com/mapbox/mapbox-gl-rtl-text) for right-to-left label shaping. The bundled BSD and ICU notices are in `assets/live-map/mapbox-gl-rtl-text-LICENSE.md`.

## Typeface

[Jost](https://github.com/google/fonts/tree/main/ofl/jost) is distributed under the SIL Open Font License 1.1. The bundled license is in `assets/fonts/Jost-OFL.txt`.

[Noto Sans Arabic](https://github.com/google/fonts/tree/main/ofl/notosansarabic) is distributed under the SIL Open Font License 1.1. The bundled license is in `assets/fonts/NotoSansArabic-OFL.txt`.

## External APIs, tiles, data, and services

| Provider/service | Application use | Notes |
| --- | --- | --- |
| MapTiler | Hosted raster map tiles | API key, provider terms, attribution, and usage limits apply. |
| OpenStreetMap contributors | Map-data attribution used with tile layers | Applicable attribution and data terms must be followed. |
| CARTO | Dark basemap tiles | Provider terms and attribution requirements apply. |
| Esri World Imagery | Satellite imagery fallback | Provider terms, attribution, and usage restrictions apply. |
| AviationWeather.gov | METAR retrieval | API/service terms and data-use conditions apply. |
| Open-Meteo | Forecast data and reverse geocoding | API/service terms and attribution requirements apply. |
| Infinite Flight public API | Simulator sessions, flights, flight plans, ATC, user statistics, and activity | API key, platform terms, rate limits, branding, and data-use conditions apply. |

Availability through an API does not imply permission to republish provider data, branding, screenshots, or derived assets.

## Airport-card photographs

`assets/overview/airport_cards/SOURCES.md` records the following files as Unsplash images and links their source pages: `CYYZ.jpg`, `OMAA.jpg`, `FIMP.jpg`, `SAEZ.jpg`, `CYYC.jpg`, `KDEN.jpg`, `KPHL.jpg`, `KATL.jpg`, `MMMX.jpg`, `SHANGHAI.jpg`, and `YSSY.jpg`. That source file identifies the Unsplash License. Confirm that each file matches the recorded source and that the applicable terms and attribution are satisfied at the time of release.

No source or licence record was found for these airport-card files: `CYVR.jpg`, `EDDB.jpg`, `EDDF.jpg`, `EDDM.jpg`, `EGLL.jpg`, `KIAH.jpg`, `KLAX.jpg`, `KMIA.jpg`, `KSFO.jpg`, `LFPG.jpg`, `LTFM.jpg`, `NEW_YORK.jpg`, `OIIE.jpg`, `OMDB.jpg`, `RJTT.jpg`, `VHHH.jpg`, and `WSSS.jpg`.

**Licence/redistribution permission must be verified before public release.**

## Aircraft images and liveries

The application credits its aircraft imagery to Infinite Flight. The inspected project does not contain per-file source records or documented redistribution permission for `assets/aircraft/generic/` or `assets/aircraft/liveries/`.

**Licence/redistribution permission must be verified before public release.** Aircraft designs, liveries, airline names, and related marks may also involve rights belonging to aircraft manufacturers, airlines, Infinite Flight, photographers, or other creators.

## Airline and manufacturer logos

The files under `assets/airlines/` and `assets/manufacturers/` depict airline or manufacturer branding. No redistribution licence record was found in the project.

**Licence/redistribution permission must be verified before public release.** All third-party trademarks, airline names, logos, liveries, and manufacturer marks belong to their respective owners. Their inclusion does not imply sponsorship, endorsement, or affiliation.

## Earth textures and globe images

The repository includes Earth textures under `assets/textures/`, a rendered cache under `assets/globe/`, and additional Earth-map images under `globe-gl-test-web/public/` and `globe-gl-test-web/dist/`. Several filenames refer to NASA Blue Marble/Next Generation material, but no source URL, exact provenance chain, or redistribution terms were included in the inspected notice files. `assets/textures/README.txt` only describes expected filenames.

**Licence/redistribution permission and any required NASA or other attribution must be verified before public release.** Derived or cached images require the same review as their sources.

## Login photograph

The login background shows Frankfurt Airport. [Photo by Dennis Gecaj on Unsplash](https://unsplash.com/photos/empty-gray-airport-seats-during-daytime-jVvtCCycgcQ). [Unsplash License](https://unsplash.com/license).

## Backgrounds, card art, icons, audio, and application icon

No conclusive source/licence records were found for the following categories:

- `assets/home_bg.jpg` and other assets under `assets/backgrounds/`.
- `assets/icons/`, including bitmap and SVG navigation assets.
- `assets/audio/login.mp3` and `assets/audio/seatbelt_sign.mp3`.
- `assets/app_icon.ico`.
- `assets/generated/`, which may contain derived images created from other assets.

**Licence/redistribution permission must be verified before public release.** User-selected background files are local content and are ignored by the repository rules.

The source also uses Flet's built-in icon catalog. The relevant Flet and underlying icon-set notices must be retained as required by their upstream terms.

## Release checklist for third-party material

Before a public release:

1. Verify every asset's creator, source URL, exact licence, and redistribution permission.
2. Replace or remove any asset that cannot be legally redistributed.
3. Retain required copyright, licence, and attribution notices.
4. Review trademark and branding use separately from copyright permission.
5. Re-run a dependency licence inventory for the exact Python and JavaScript versions being distributed.


## Online aviation lookup

- Airport records are retrieved from [OurAirports](https://ourairports.com/data/), which publishes its data in the public domain.
- Airline and aircraft catalogs are retrieved from [OpenFlights](https://openflights.org/data.php) under the Open Database License.
- Airline search can display logos from [Aviasales](https://support.travelpayouts.com/hc/en-us/articles/203956073-Airline-logos-by-Aviasales) using IATA codes. The logos belong to their respective owners.
- City card thumbnails are provided by [Wikipedia's PageImages API](https://www.mediawiki.org/wiki/Extension:PageImages). Individual images carry their respective licenses.
- Overview METAR observations are provided by the [Aviation Weather Center Data API](https://aviationweather.gov/data/api/).

## V14 map and interface assets

- Flag artwork retains the licence in `assets/flags/LICENSE`.
- MapLibre GL JS retains its notice in `assets/live-map/maplibre-license.txt`.
- Adapted aircraft outlines and the derived browser outline data retain the upstream GPL notice and provenance in `assets/live-aircraft/`.
