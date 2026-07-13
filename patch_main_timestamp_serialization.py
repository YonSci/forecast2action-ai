from pathlib import Path
import re

MAIN_PATH = Path("app/api/main.py")

if not MAIN_PATH.exists():
    raise SystemExit("Could not find app/api/main.py. Run this script from D:\\forecast2action-ai.")

text = MAIN_PATH.read_text(encoding="utf-8")
backup = MAIN_PATH.with_suffix(".py.timestamp_backup")
backup.write_text(text, encoding="utf-8")

HELPER_BLOCK = """
# ---------------------------------------------------------------------
# JSON-safe admin boundary helpers
# ---------------------------------------------------------------------

def json_safe(value):
    \"\"\"Convert shapefile/GeoPandas/Pandas/Numpy values into JSON-safe values.\"\"\"
    import math
    from datetime import date, datetime
    from decimal import Decimal

    if value is None:
        return None

    try:
        if str(value) in {"NaT", "<NA>", "nan", "NaN", "None"}:
            return None
    except Exception:
        pass

    try:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
    except Exception:
        pass

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if hasattr(value, "isoformat") and value.__class__.__name__ in {
        "Timestamp",
        "NaTType",
    }:
        try:
            if str(value) == "NaT":
                return None
            return value.isoformat()
        except Exception:
            return str(value)

    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            return json_safe(value.item())
        except Exception:
            pass

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")

    if isinstance(value, (str, int, bool)):
        return value

    if isinstance(value, float):
        return value

    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]

    return str(value)


def geometry_to_geojson_safe(geometry_obj):
    \"\"\"Return a JSON-safe geometry dict without calling GeoDataFrame.to_json().\"\"\"
    if geometry_obj is None:
        return None

    try:
        if geometry_obj.is_empty:
            return None
    except Exception:
        pass

    if hasattr(geometry_obj, "__geo_interface__"):
        return json_safe(geometry_obj.__geo_interface__)

    return json_safe(geometry_obj)


def row_to_json_safe_properties(row, columns, geometry_column_name):
    props = {}

    for column in columns:
        if column == geometry_column_name:
            continue

        try:
            props[str(column)] = json_safe(row[column])
        except Exception:
            props[str(column)] = None

    return props
"""

LOAD_ADMIN_FUNCTION = """
@lru_cache(maxsize=8)
def load_admin_features(level: str) -> tuple:
    \"\"\"Load Ethiopia admin shapefiles without GeoDataFrame.to_json().

    This avoids 500 errors caused by Timestamp/NaT fields in shapefile
    attributes. It manually converts every geometry and property to JSON-safe
    Python objects.
    \"\"\"
    if level not in ADMIN_SHP_PATHS:
        level = "admin1"

    shp_path = ADMIN_SHP_PATHS[level]

    if gpd is None or not shp_path.exists():
        return tuple(fallback_admin_features(level))

    try:
        gdf = gpd.read_file(shp_path)

        if gdf.empty:
            return tuple(fallback_admin_features(level))

        if gdf.crs is not None and str(gdf.crs).lower() not in {"epsg:4326", "wgs84"}:
            gdf = gdf.to_crs("EPSG:4326")

        standardized = []
        geometry_column_name = gdf.geometry.name

        for index, row in gdf.iterrows():
            geometry_obj = row.geometry
            geometry = geometry_to_geojson_safe(geometry_obj)

            if not geometry:
                continue

            props = row_to_json_safe_properties(
                row=row,
                columns=gdf.columns,
                geometry_column_name=geometry_column_name,
            )

            region = first_existing(
                props,
                [
                    "region", "reg_name", "reg_name_en", "adm1_en", "adm1_name",
                    "name_1", "admin1", "adm1", "adm1_pcode", "ADM1_EN",
                    "ADM1_NAME", "shapeName", "shape_name", "NAME_1",
                ],
                "",
            )

            zone = first_existing(
                props,
                [
                    "zone", "zon_name", "zone_name", "adm2_en", "adm2_name",
                    "name_2", "admin2", "adm2", "adm2_pcode", "ADM2_EN",
                    "ADM2_NAME", "shapeName", "shape_name", "NAME_2",
                ],
                "",
            )

            woreda = first_existing(
                props,
                [
                    "woreda", "wereda", "wrd_name", "woreda_name", "adm3_en",
                    "adm3_name", "name_3", "admin3", "adm3", "adm3_pcode",
                    "ADM3_EN", "ADM3_NAME", "shapeName", "shape_name", "NAME_3",
                ],
                "",
            )

            if level == "admin1":
                if not region:
                    region = first_existing(
                        props,
                        ["name", "shapeName", "shape_name", "adm1_en", "name_1", "NAME_1"],
                        f"Region {index + 1}",
                    )
                zone = ""
                woreda = ""
                name = region

            elif level == "admin2":
                if not zone:
                    zone = first_existing(
                        props,
                        ["name", "shapeName", "shape_name", "adm2_en", "name_2", "NAME_2"],
                        f"Zone {index + 1}",
                    )
                if not region:
                    region = first_existing(
                        props,
                        ["adm1_en", "name_1", "region", "reg_name", "ADM1_EN", "NAME_1"],
                        "",
                    )
                woreda = ""
                name = zone

            else:
                if not woreda:
                    woreda = first_existing(
                        props,
                        ["name", "shapeName", "shape_name", "adm3_en", "name_3", "NAME_3"],
                        f"Woreda {index + 1}",
                    )
                if not zone:
                    zone = first_existing(
                        props,
                        ["adm2_en", "name_2", "zone", "zon_name", "ADM2_EN", "NAME_2"],
                        "",
                    )
                if not region:
                    region = first_existing(
                        props,
                        ["adm1_en", "name_1", "region", "reg_name", "ADM1_EN", "NAME_1"],
                        "",
                    )
                name = woreda

            region_id = slugify(region)
            zone_id = f"{region_id}__{slugify(zone)}" if zone else ""
            woreda_id = f"{zone_id}__{slugify(woreda)}" if woreda and zone_id else ""

            feature = {
                "type": "Feature",
                "id": str(index),
                "geometry": geometry,
                "properties": {
                    **props,
                    "admin_level": level,
                    "name": name,
                    "region": region,
                    "zone": zone,
                    "woreda": woreda,
                    "region_id": region_id,
                    "zone_id": zone_id,
                    "woreda_id": woreda_id,
                },
            }

            standardized.append(json_safe(feature))

        if not standardized:
            return tuple(fallback_admin_features(level))

        return tuple(standardized)

    except Exception as error:
        print(f"[Forecast2Action] Failed to load {level} shapefile at {shp_path}: {error}")
        return tuple(fallback_admin_features(level))
"""

if "def geometry_to_geojson_safe" not in text:
    match = re.search(r"\n@lru_cache\(maxsize=8\)\s*\ndef load_admin_features", text)
    if not match:
        match = re.search(r"\ndef load_admin_features", text)
    if not match:
        raise SystemExit("Could not find load_admin_features in app/api/main.py.")

    insert_at = match.start()
    text = text[:insert_at] + "\n" + HELPER_BLOCK + "\n" + text[insert_at:]

pattern = re.compile(
    r"\n@lru_cache\(maxsize=8\)\s*\ndef load_admin_features\(level: str\).*?(?=\n\n(?:@app\.|def |class |# -|\Z))",
    flags=re.DOTALL,
)

if not pattern.search(text):
    pattern = re.compile(
        r"\ndef load_admin_features\(level: str\).*?(?=\n\n(?:@app\.|def |class |# -|\Z))",
        flags=re.DOTALL,
    )

if not pattern.search(text):
    raise SystemExit("Could not replace load_admin_features. Please paste the function manually.")

text = pattern.sub("\n" + LOAD_ADMIN_FUNCTION.strip() + "\n", text, count=1)

MAIN_PATH.write_text(text, encoding="utf-8")

print("Patched app/api/main.py successfully.")
print(f"Backup saved to: {backup}")
print("Now restart backend with: uvicorn app.api.main:app --reload")
