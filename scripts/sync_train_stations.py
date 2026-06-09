from __future__ import annotations

import json
from pathlib import Path

import httpx


def main() -> None:
    url = 'https://k.vnticketonline.vn/api/GTGV/LoadDmGa'
    response = httpx.get(url, headers={'User-Agent': 'travel-planner-a2a/1.0'}, timeout=30)
    response.raise_for_status()
    rows = response.json()

    stations = []
    for row in rows:
        name = (row.get('TenGa') or '').strip()
        code = (row.get('MaGa') or '').strip().upper()
        skeys = row.get('SKeys') or ''
        aliases = []
        for part in str(skeys).split(','):
            value = part.strip()
            if value and value.lower() != code.lower() and value.lower() != name.lower():
                aliases.append(value)
        stations.append({
            'name': name,
            'code': code,
            'aliases': aliases,
        })

    out_path = Path(__file__).resolve().parent.parent / 'data' / 'train_stations_live.json'
    out_path.write_text(json.dumps(stations, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Saved {len(stations)} stations to {out_path}')


if __name__ == '__main__':
    main()
