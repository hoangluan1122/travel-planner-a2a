from __future__ import annotations

import json

from services.location_resolver import resolve_location

CASES = [
    'Ha Noi', 'Hai Phong', 'Nam Dinh', 'Ninh Binh', 'Lao Cai', 'Sa Pa', 'Ha Giang', 'Cao Bang',
    'Quang Ninh', 'Hue', 'Da Nang', 'Hoi An', 'Da Lat', 'Nha Trang', 'Quy Nhon', 'Phan Thiet',
    'Ho Chi Minh', 'Vung Tau', 'Ben Tre', 'Can Tho', 'Phu Quoc', 'Con Dao', 'Mang Den', 'Tam Dao',
    'Bac Ninh', 'Hai Duong', 'Thai Binh', 'Thanh Hoa', 'Nghe An', 'Quang Tri', 'Quang Nam',
    'Binh Dinh', 'Khanh Hoa', 'Lam Dong', 'Ba Ria Vung Tau', 'Kien Giang'
]


def main() -> None:
    rows = []
    for value in CASES:
        r = resolve_location(value)
        rows.append({
            'input': value,
            'canonical_name': r.canonical_name,
            'matched_by': r.matched_by,
            'nearest_airport_hub': r.nearest_airport_hub,
            'nearest_train_hub': r.nearest_train_hub,
            'nearest_bus_hub': r.nearest_bus_hub,
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
