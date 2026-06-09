from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.root_agent import RootTravelPlannerAgent
from services.request_parser import parse_user_request

CASES = [
    ('Ha Noi', 3, 7000000, '2026-05-10'),
    ('Ho Chi Minh', 3, 8000000, '2026-05-10'),
    ('Da Nang', 3, 7000000, '2026-05-10'),
    ('Da Lat', 4, 8000000, '2026-05-10'),
    ('Nha Trang', 3, 8000000, '2026-05-10'),
    ('Hue', 3, 7000000, '2026-05-10'),
    ('Hoi An', 3, 7000000, '2026-05-10'),
    ('Ha Long', 3, 7000000, '2026-05-10'),
    ('Phu Quoc', 3, 10000000, '2026-05-10'),
    ('Ninh Binh', 3, 7000000, '2026-05-10'),
]

agent = RootTravelPlannerAgent()
rows = []
for dest, days, budget, date in CASES:
    req = parse_user_request(f'Tôi muốn đi {dest} {days} ngày với ngân sách {budget}', origin='Ha Noi')
    req.lang = 'vi'
    req.departure_date = date
    req.days = days
    req.budget = budget
    res = agent.run(req)
    rows.append({
        'destination': dest,
        'hotel_count': len(res.hotels),
        'transport_count': len(res.transport_options),
        'attraction_count': len(res.attractions),
        'hotels': [h.title for h in res.hotels[:4]],
        'transport': [t.title for t in res.transport_options[:4]],
        'attractions': [a.title for a in res.attractions[:4]],
        'provider_status': res.provider_status,
        'estimated_cost': res.estimated_cost,
    })

OUTPUT = ROOT / 'data' / 'ten_case_snapshot.json'
OUTPUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Saved to {OUTPUT}')
