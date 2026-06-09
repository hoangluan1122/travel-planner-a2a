from __future__ import annotations

import json
from pathlib import Path

from services.bus_area_service import load_bus_areas, resolve_bus_area_id
from services.location_resolver import load_registry, resolve_location

OUTPUT_PATH = Path(__file__).resolve().parent.parent / 'data' / 'bus_coverage_audit.json'


def audit() -> list[dict]:
    areas = load_bus_areas()
    area_count = len(areas)
    rows: list[dict] = []
    for record in load_registry():
        resolved = resolve_location(record.name)
        area_id = resolve_bus_area_id(record.name)
        rows.append({
            'location': record.name,
            'kind': record.kind,
            'canonical_name': resolved.canonical_name,
            'nearest_bus_hub': resolved.nearest_bus_hub,
            'bus_area_id': area_id,
            'has_bus_area': bool(area_id),
            'matched_bus_hub_directly': resolved.nearest_bus_hub == resolved.canonical_name,
        })
    rows.sort(key=lambda x: (not x['has_bus_area'], x['location']))
    OUTPUT_PATH.write_text(json.dumps({'area_count': area_count, 'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    return rows


def main() -> None:
    rows = audit()
    with_area = sum(1 for x in rows if x['has_bus_area'])
    print(json.dumps({
        'total_locations': len(rows),
        'locations_with_bus_area': with_area,
        'locations_without_bus_area': len(rows) - with_area,
        'sample_missing': [x['location'] for x in rows if not x['has_bus_area']][:15],
        'output_file': str(OUTPUT_PATH),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
