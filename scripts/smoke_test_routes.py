from __future__ import annotations

import json

from agents.root_agent import RootTravelPlannerAgent
from services.request_parser import parse_user_request


TEST_CASES = [
    {"origin": "Hà Nội", "text": "Tôi muốn khám phá Hà Nội 2 ngày với ngân sách 5 triệu. Tôi thích ẩm thực địa phương và lịch sử."},
    {"origin": "Hà Nội", "text": "Tôi muốn đi Ninh Bình 3 ngày với ngân sách 6 triệu cho 2 người. Tôi thích thiên nhiên và ngắm cảnh."},
    {"origin": "Hà Nội", "text": "Tôi muốn đi Tam Đảo 2 ngày với ngân sách 4 triệu cho 2 người. Tôi thích thư giãn và ngắm cảnh."},
    {"origin": "Đà Nẵng", "text": "Tôi muốn đi Bà Nà 1 ngày với ngân sách 3 triệu cho 2 người. Tôi thích ngắm cảnh và vui chơi."},
    {"origin": "Hà Nội", "text": "Tôi muốn đi Măng Đen 3 ngày với ngân sách 8 triệu cho 2 người. Tôi thích thiên nhiên và thư giãn."},
    {"origin": "Hà Nội", "text": "Tôi muốn đi thành phố Hồ Chí Minh 3 ngày với ngân sách 8 triệu cho 2 người. Tôi thích ẩm thực và lịch sử."},
    {"origin": "TP HCM", "text": "Tôi muốn đi Bến Tre 2 ngày với ngân sách 4 triệu cho 2 người. Tôi thích ẩm thực địa phương và sông nước."},
    {"origin": "TP HCM", "text": "Tôi muốn đi Côn Đảo 3 ngày với ngân sách 10 triệu cho 2 người. Tôi thích biển và nghỉ dưỡng."},
    {"origin": "Hà Nội", "text": "Tôi muốn đi Hạ Long 2 ngày với ngân sách 6 triệu cho 2 người. Tôi thích biển và chụp ảnh."},
    {"origin": "TP HCM", "text": "Tôi muốn đi Phú Quốc 3 ngày với ngân sách 10 triệu cho 2 người. Tôi thích biển và nghỉ dưỡng."},
]


def main() -> None:
    planner = RootTravelPlannerAgent()
    results = []
    for case in TEST_CASES:
        parsed = parse_user_request(case['text'], origin=case['origin'])
        plan = planner.run(parsed)
        results.append({
            'origin_input': case['origin'],
            'text': case['text'],
            'parsed': parsed.model_dump(),
            'result_destination': plan.destination,
            'provider_status': plan.provider_status,
            'transport_count': len(plan.transport_options),
            'hotel_count': len(plan.hotels),
            'attraction_count': len(plan.attractions),
        })
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
