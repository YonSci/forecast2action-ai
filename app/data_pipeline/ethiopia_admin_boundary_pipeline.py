from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import shapefile


SHAPEFILE_DIR = Path("data/eth_shapefile")
OUTPUT_DIR = Path("data/sample/admin_boundaries")

ADMIN_FILES = {
    "admin0": SHAPEFILE_DIR / "eth_admin0.shp",
    "admin1": SHAPEFILE_DIR / "eth_admin1.shp",
    "admin2": SHAPEFILE_DIR / "eth_admin2.shp",
    "admin3": SHAPEFILE_DIR / "eth_admin3.shp",
}

REGION_FIELD_CANDIDATES = [
    "ADM1_EN",
    "ADM1_NAME",
    "ADMIN1",
    "REGION",
    "REGIONNAME",
    "REGION_NAME",
    "REG_NAME",
    "NAME_1",
    "NAME1",
    "ADM1",
]

ZONE_FIELD_CANDIDATES = [
    "ADM2_EN",
    "ADM2_NAME",
    "ADMIN2",
    "ZONE",
    "ZONENAME",
    "ZONE_NAME",
    "NAME_2",
    "NAME2",
    "ADM2",
]

WOREDA_FIELD_CANDIDATES = [
    "ADM3_EN",
    "ADM3_NAME",
    "ADMIN3",
    "WOREDA",
    "WEREDA",
    "WOREDA_NAME",
    "WEREDA_NAME",
    "WORD_NAME",
    "NAME_3",
    "NAME3",
    "ADM3",
]


def slugify(value: str) -> str:
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown"


def normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def find_field(fields: List[str], candidates: List[str]) -> Optional[str]:
    normalized_fields = {
        normalize_field_name(field): field
        for field in fields
    }

    for candidate in candidates:
        normalized_candidate = normalize_field_name(candidate)
        if normalized_candidate in normalized_fields:
            return normalized_fields[normalized_candidate]

    for field in fields:
        normalized_field = normalize_field_name(field)

        for candidate in candidates:
            normalized_candidate = normalize_field_name(candidate)

            if normalized_candidate in normalized_field:
                return field

    return None


def get_attribute(attributes: Dict, field: Optional[str], fallback: str = "Unknown") -> str:
    if not field:
        return fallback

    value = attributes.get(field)

    if value is None:
        return fallback

    value = str(value).strip()

    if value == "":
        return fallback

    return value


def read_reader(path: Path) -> shapefile.Reader:
    if not path.exists():
        raise FileNotFoundError(f"Missing shapefile: {path}")

    for encoding in ["utf-8", "latin1", "cp1252"]:
        try:
            reader = shapefile.Reader(str(path), encoding=encoding)
            _ = reader.fields
            return reader
        except Exception:
            continue

    return shapefile.Reader(str(path))


def read_layer(level: str) -> Dict:
    path = ADMIN_FILES[level]
    reader = read_reader(path)

    fields = [field[0] for field in reader.fields[1:]]

    region_field = find_field(fields, REGION_FIELD_CANDIDATES)
    zone_field = find_field(fields, ZONE_FIELD_CANDIDATES)
    woreda_field = find_field(fields, WOREDA_FIELD_CANDIDATES)

    features = []

    for index, shape_record in enumerate(reader.shapeRecords()):
        attributes = dict(zip(fields, list(shape_record.record)))

        region = get_attribute(attributes, region_field, "Unknown Region")
        zone = get_attribute(attributes, zone_field, "Unknown Zone")
        woreda = get_attribute(attributes, woreda_field, "Unknown Woreda")

        if level == "admin1":
            name = region
            zone = ""
            woreda = ""
        elif level == "admin2":
            name = zone
            woreda = ""
        elif level == "admin3":
            name = woreda
        else:
            name = "Ethiopia"

        region_id = slugify(region)
        zone_id = slugify(f"{region}_{zone}") if zone else ""
        woreda_id = slugify(f"{region}_{zone}_{woreda}") if woreda else ""

        feature_id = slugify(f"{level}_{region}_{zone}_{woreda}_{index}")

        feature = {
            "type": "Feature",
            "id": feature_id,
            "geometry": shape_record.shape.__geo_interface__,
            "properties": {
                "id": feature_id,
                "admin_level": level,
                "name": name,
                "region": region,
                "region_id": region_id,
                "zone": zone,
                "zone_id": zone_id,
                "woreda": woreda,
                "woreda_id": woreda_id,
            },
        }

        features.append(feature)

    print(f"{level}: {path}")
    print(f"  Fields: {fields}")
    print(f"  Detected region field: {region_field}")
    print(f"  Detected zone field: {zone_field}")
    print(f"  Detected woreda field: {woreda_field}")
    print(f"  Features: {len(features)}")

    return {
        "type": "FeatureCollection",
        "metadata": {
            "admin_level": level,
            "source": str(path),
            "detected_fields": {
                "region": region_field,
                "zone": zone_field,
                "woreda": woreda_field,
            },
        },
        "features": features,
    }


def unique_options(features: List[Dict], id_key: str, label_key: str, extra_keys: List[str]) -> List[Dict]:
    seen = {}
    for feature in features:
        props = feature.get("properties", {})
        value = props.get(id_key)
        label = props.get(label_key)

        if not value or not label or str(label).startswith("Unknown"):
            continue

        item = {
            "value": value,
            "label": label,
        }

        for key in extra_keys:
            item[key] = props.get(key, "")

        seen[value] = item

    return sorted(seen.values(), key=lambda item: item["label"])


def build_options(admin1: Dict, admin2: Dict, admin3: Dict) -> Dict:
    regions = unique_options(
        admin1["features"],
        id_key="region_id",
        label_key="region",
        extra_keys=[],
    )

    zones = unique_options(
        admin2["features"],
        id_key="zone_id",
        label_key="zone",
        extra_keys=["region_id", "region"],
    )

    woredas = unique_options(
        admin3["features"],
        id_key="woreda_id",
        label_key="woreda",
        extra_keys=["region_id", "region", "zone_id", "zone"],
    )

    return {
        "regions": regions,
        "zones": zones,
        "woredas": woredas,
    }


def write_json(path: Path, data: Dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )


def run_ethiopia_admin_boundary_pipeline() -> Dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    admin0 = read_layer("admin0")
    admin1 = read_layer("admin1")
    admin2 = read_layer("admin2")
    admin3 = read_layer("admin3")

    options = build_options(admin1, admin2, admin3)

    write_json(OUTPUT_DIR / "eth_admin0.json", admin0)
    write_json(OUTPUT_DIR / "eth_admin1.json", admin1)
    write_json(OUTPUT_DIR / "eth_admin2.json", admin2)
    write_json(OUTPUT_DIR / "eth_admin3.json", admin3)
    write_json(OUTPUT_DIR / "ethiopia_admin_options.json", options)

    print("Ethiopia administrative boundary pipeline completed.")
    print(f"Output folder: {OUTPUT_DIR}")
    print(f"Country features: {len(admin0['features'])}")
    print(f"Regions: {len(options['regions'])}")
    print(f"Zones: {len(options['zones'])}")
    print(f"Woredas: {len(options['woredas'])}")

    return {
        "admin0": admin0,
        "admin1": admin1,
        "admin2": admin2,
        "admin3": admin3,
        "options": options,
    }


if __name__ == "__main__":
    run_ethiopia_admin_boundary_pipeline()