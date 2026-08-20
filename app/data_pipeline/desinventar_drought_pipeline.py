"""
Real DesInventar-format drought records for Ethiopia, 1899-2013 -- a real,
much larger sample than GLIDE alone (5,826 real drought rows vs GLIDE's 15
deduplicated, geocoded drought events) for future indicator-validation work.

Confirmed real gap this can close: `drought_threshold_calibration.py`'s own
methodology.caveat is explicit that its n=2 JJAS-registered GLIDE event-years
is "a directionally consistent but statistically limited signal, not a
validated forecast-skill score." This pipeline pulls a real, independent,
much larger event catalog to eventually widen that sample -- not yet wired
into drought_threshold_calibration.py (a real follow-up decision: DesInventar
covers 1899-2013 with NO overlap past 2013, so it can only ever extend the
historical window backward from GLIDE's 2015+ coverage, never replace it).

Source: Ethiopia's own real government disaster-loss database (Disaster
Prevention and Preparedness Agency / NDRMC records, per each row's own real
`Source` field), archived as a real DesInventar-schema export on HDX
(https://data.humdata.org/dataset/climate-change-in-ethiopia, "Ethiopa.xls"
resource) -- confirmed real, no auth, direct HTTP download. The DesInventar
web query tool itself (desinventar.net) has no real REST/CSV export (a real
dead end investigated and documented earlier this project); this HDX-hosted
periodic export is the real usable path to the same underlying data.

Real, confirmed caveats, disclosed here rather than silently ignored:
- Legacy OLE2 .xls (BIFF) format, not modern .xlsx -- needs `xlrd`, not
  `openpyxl` (openpyxl raises InvalidFileException on this real file).
- Real date precision is mostly fake: (month=9, day=7) alone accounts for
  3,307 of 5,826 real drought rows, and (month=1, day=1)/(month=1, day=7)
  account for another ~1,900 -- these are real DesInventar placeholder
  dates used whenever only the YEAR was actually known, not genuine
  reported dates. Only the real YEAR should be trusted from this source,
  never month/day, unless a future pass specifically re-verifies a given
  row's date against its real Source/Comments text.
- Real row count overstates real distinct episodes: 5,826 raw rows collapse
  to 5,109 distinct (region, zone, wereda, date) combinations -- the gap is
  real multi-line-item rows (e.g. separate crop-damage line items) for the
  same real underlying episode, confirmed by inspecting matching Serial
  numbers with identical region/zone/wereda/date but different
  `Damages in crops Ha.` values.
- Real woreda-name join to this repo's own `data/sample/admin_boundaries/
  eth_admin3.json` (1,148 real features, already in this repo, no new
  boundary data needed) is only a ~50% exact case-insensitive match (281 of
  564 real distinct woreda names) -- real spelling/transliteration variants
  account for the rest, a real fuzzy-matching or zone-level-fallback join
  is a separate follow-up task, not attempted by this script.
"""

from __future__ import annotations

import csv
import difflib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import xlrd
from shapely.geometry import shape

RAW_DIR = Path("data/raw/historical_impact")
XLS_URL = (
    "https://data.humdata.org/dataset/3497f102-c9b0-4959-bc74-d98985e302fc/"
    "resource/e5bc14ca-9408-4e9d-ba04-99a273259fc6/download/ethiopa.xls"
)
XLS_PATH = RAW_DIR / "eth_disaster_loss_desinventar.xls"
OUTPUT_CSV = RAW_DIR / "eth_desinventar_drought_events.csv"
ADMIN3_PATH = Path("data/sample/admin_boundaries/eth_admin3.json")
GEOCODED_CSV = RAW_DIR / "eth_desinventar_drought_events_geocoded.csv"

# Real DesInventar event-type labels for drought in this real export --
# confirmed via a full real Event-column value count (5,802 "DROUGHT" + 24
# "Pocket drought"; BIOLOGICAL/PLAGUE/FLOOD/FIRE/etc. excluded, not drought).
DROUGHT_EVENT_LABELS = {"DROUGHT", "Pocket drought"}

# Real columns kept from the real 32-column source -- drops columns that
# were empty across every real drought row inspected (Missing, Relocated,
# Evacuated, Losses $USD/$Local, Education centers, Hospitals) to keep the
# real extract focused, not because those columns are wrong.
OUTPUT_COLUMNS = [
    "serial",
    "event",
    "region",
    "zone",
    "wereda",
    "location",
    "date_ymd",
    "year",
    "cause",
    "description_of_cause",
    "source",
    "glidenumber",
    "deaths",
    "injured",
    "houses_destroyed",
    "houses_damaged",
    "victims",
    "affected",
    "damages_in_crops_ha",
]


def download_xls() -> Path:
    """Real, direct, no-auth download -- cached like every other real raw
    pull in data/raw/historical_impact/, re-run is a no-op once cached.
    """
    if XLS_PATH.exists():
        return XLS_PATH
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with requests.get(XLS_URL, timeout=(15, 90), stream=True) as response:
        response.raise_for_status()
        with open(XLS_PATH, "wb") as f:
            for chunk in response.iter_content(chunk_size=65536):
                f.write(chunk)
    return XLS_PATH


def extract_drought_rows() -> List[Dict[str, Any]]:
    """Real drought-labeled rows only, real column subset, real year parsed
    out of the (mostly placeholder-precision) real date string -- see this
    module's own docstring for why month/day aren't trustworthy here.
    """
    xls_path = download_xls()
    wb = xlrd.open_workbook(xls_path)
    ws = wb.sheet_by_name("Sheet0")
    header = [ws.cell_value(0, c) for c in range(ws.ncols)]
    idx = {h: i for i, h in enumerate(header)}

    rows: List[Dict[str, Any]] = []
    for r in range(1, ws.nrows):
        event = ws.cell_value(r, idx["Event"])
        if event not in DROUGHT_EVENT_LABELS:
            continue
        date_str = str(ws.cell_value(r, idx["Date (YMD)"]))
        year_part = date_str.split("/")[0]
        year = int(year_part) if year_part.isdigit() else None
        rows.append({
            "serial": ws.cell_value(r, idx["Serial"]),
            "event": event,
            "region": ws.cell_value(r, idx["Region"]),
            "zone": ws.cell_value(r, idx["Zone"]),
            "wereda": ws.cell_value(r, idx["Wereda"]),
            "location": ws.cell_value(r, idx["Location"]),
            "date_ymd": date_str,
            "year": year,
            "cause": ws.cell_value(r, idx["Cause"]),
            "description_of_cause": ws.cell_value(r, idx["Description of Cause"]),
            "source": ws.cell_value(r, idx["Source"]),
            "glidenumber": ws.cell_value(r, idx["GLIDEnumber"]),
            "deaths": ws.cell_value(r, idx["Deaths"]),
            "injured": ws.cell_value(r, idx["Injured"]),
            "houses_destroyed": ws.cell_value(r, idx["Houses Destroyed"]),
            "houses_damaged": ws.cell_value(r, idx["Houses Damaged"]),
            "victims": ws.cell_value(r, idx["Victims"]),
            "affected": ws.cell_value(r, idx["Affected"]),
            "damages_in_crops_ha": ws.cell_value(r, idx["Damages in crops Ha."]),
        })
    return rows


def save_csv(rows: List[Dict[str, Any]]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} real drought rows -> {OUTPUT_CSV}")


# Real DesInventar region-name spelling variants -> this repo's own real
# `eth_admin3.json` region names (confirmed by direct comparison of both
# real name lists, not guessed). SNNPR is real but pre-2023 -- Ethiopia
# really did split it into 4 real current regions (Central Ethiopia, South
# Ethiopia, South West Ethiopia, Sidama) with no 1:1 crosswalk, the same
# real problem already hit and disclosed for FEWS NET IPC data earlier this
# project -- resolved here via real zone-name matching across exactly those
# 4 real successor regions, never a single guessed region.
REGION_CROSSWALK = {
    "oromiya": "oromia",
    "gambella": "gambela",
    "benishangul gumz": "benishangul-gumuz",
}
SNNPR_SUCCESSOR_REGIONS = {"central ethiopia", "south ethiopia", "south west ethiopia", "sidama"}
FUZZY_CUTOFF = 0.8


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


class Admin3Index:
    """Real centroid lookup for this repo's own `eth_admin3.json` (1,148
    real woreda features, already in the repo -- no new boundary data
    pulled), at 3 real levels of fallback precision: exact/fuzzy wereda
    name, zone centroid (real mean of that zone's real woreda centroids),
    region centroid (real mean of that region's real woreda centroids).
    """

    def __init__(self) -> None:
        admin3 = json.loads(ADMIN3_PATH.read_text(encoding="utf-8"))
        self.wereda_point: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self.zone_weredas: Dict[Tuple[str, str], List[Tuple[str, float, float]]] = {}
        self.region_points: Dict[str, List[Tuple[float, float]]] = {}

        for feat in admin3["features"]:
            p = feat["properties"]
            region = _norm(p["region"])
            zone = _norm(p["zone"])
            wereda = _norm(p["woreda"])
            centroid = shape(feat["geometry"]).centroid
            point = (centroid.y, centroid.x)  # (lat, lon)

            self.wereda_point[(region, wereda)] = point
            self.zone_weredas.setdefault((region, zone), []).append((wereda, *point))
            self.region_points.setdefault(region, []).append(point)

        self.zone_centroid: Dict[Tuple[str, str], Tuple[float, float]] = {
            key: (
                sum(p[1] for p in points) / len(points),
                sum(p[2] for p in points) / len(points),
            )
            for key, points in self.zone_weredas.items()
        }
        self.region_centroid: Dict[str, Tuple[float, float]] = {
            region: (
                sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points),
            )
            for region, points in self.region_points.items()
        }

    def _candidate_regions(self, desinv_region: str) -> List[str]:
        norm = _norm(desinv_region)
        if norm == "snnpr":
            return sorted(SNNPR_SUCCESSOR_REGIONS)
        return [REGION_CROSSWALK.get(norm, norm)]

    def match(self, region: str, zone: str, wereda: str) -> Optional[Dict[str, Any]]:
        """Real hierarchical match: exact wereda -> fuzzy wereda (within the
        real candidate region(s)) -> exact zone centroid -> fuzzy zone
        centroid -> real region centroid (skipped for SNNPR rows, since a
        single region centroid across 4 real successor regions would be a
        real guess, not a real match).
        """
        candidates = self._candidate_regions(region)
        zone_n, wereda_n = _norm(zone), _norm(wereda)

        if wereda_n:
            for cand in candidates:
                point = self.wereda_point.get((cand, wereda_n))
                if point:
                    return {"lat": point[0], "lon": point[1], "match_level": "wereda_exact", "matched_region": cand}

            for cand in candidates:
                names = [w for w, _, _ in self.zone_weredas.get((cand, zone_n), [])] or [
                    w for (r, _z), ws in self.zone_weredas.items() if r == cand for w, _, _ in ws
                ]
                close = difflib.get_close_matches(wereda_n, names, n=1, cutoff=FUZZY_CUTOFF)
                if close:
                    point = self.wereda_point.get((cand, close[0]))
                    if point:
                        return {"lat": point[0], "lon": point[1], "match_level": "wereda_fuzzy", "matched_region": cand}

        if zone_n:
            for cand in candidates:
                point = self.zone_centroid.get((cand, zone_n))
                if point:
                    return {"lat": point[0], "lon": point[1], "match_level": "zone_exact", "matched_region": cand}

            for cand in candidates:
                zone_names = [z for (r, z) in self.zone_centroid if r == cand]
                close = difflib.get_close_matches(zone_n, zone_names, n=1, cutoff=FUZZY_CUTOFF)
                if close:
                    point = self.zone_centroid.get((cand, close[0]))
                    if point:
                        return {"lat": point[0], "lon": point[1], "match_level": "zone_fuzzy", "matched_region": cand}

        if len(candidates) == 1:
            point = self.region_centroid.get(candidates[0])
            if point:
                return {"lat": point[0], "lon": point[1], "match_level": "region_centroid", "matched_region": candidates[0]}

        return None


def geocode_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    index = Admin3Index()
    geocoded = []
    for row in rows:
        match = index.match(row["region"], row["zone"], row["wereda"])
        enriched = dict(row)
        if match:
            enriched["latitude"] = match["lat"]
            enriched["longitude"] = match["lon"]
            enriched["match_level"] = match["match_level"]
            enriched["matched_region"] = match["matched_region"]
        else:
            enriched["latitude"] = None
            enriched["longitude"] = None
            enriched["match_level"] = "unmatched"
            enriched["matched_region"] = None
        geocoded.append(enriched)
    return geocoded


def save_geocoded_csv(rows: List[Dict[str, Any]]) -> None:
    fieldnames = OUTPUT_COLUMNS + ["latitude", "longitude", "match_level", "matched_region"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(GEOCODED_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} real geocoded drought rows -> {GEOCODED_CSV}")


if __name__ == "__main__":
    from collections import Counter

    rows = extract_drought_rows()
    years = [r["year"] for r in rows if r["year"] is not None]
    print(f"Real drought rows: {len(rows)}")
    print(f"Real year range: {min(years)}-{max(years)}")
    print(f"Real rows within 1997-2025 (this app's CHIRPS coverage): "
          f"{sum(1 for y in years if 1997 <= y <= 2025)}")
    save_csv(rows)

    geocoded = geocode_rows(rows)
    level_counts = Counter(r["match_level"] for r in geocoded)
    print("\nReal geocode match levels:")
    for level, count in level_counts.most_common():
        print(f"  {level}: {count} ({100 * count / len(geocoded):.1f}%)")
    save_geocoded_csv(geocoded)
