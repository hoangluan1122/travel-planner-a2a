# travel-planner-a2a

Demo Python cho bài toán AI Travel Planner theo hướng Agent2Agent (A2A).

## Kiến trúc

- `RootTravelPlannerAgent`: nhận yêu cầu người dùng, điều phối các agent con và tổng hợp kết quả.
- `WeatherAgent`: cung cấp thông tin thời tiết **live** từ OpenWeather.
- `FlightAgent`: lấy chuyến bay **live** từ SerpAPI Google Flights.
- `HotelAgent`: lấy khách sạn **live** từ OpenStreetMap / Overpass.
- `AttractionAgent`: đề xuất địa điểm tham quan **live** và có gọi `WeatherAgent` để điều chỉnh theo thời tiết.

Điểm A2A chính của demo này là specialist agent (`AttractionAgent`) có cộng tác với specialist agent khác (`WeatherAgent`), không chỉ phụ thuộc vào root agent.

## Chế độ hiện tại
Project đã được chuyển sang **live-only**.

Điều này có nghĩa là:
- không còn fallback sang mock data
- nếu nguồn live không có dữ liệu hoặc API key thiếu, hệ thống sẽ trả danh sách rỗng hoặc thông báo rõ là không có dữ liệu thật

## Cấu trúc

```text
travel-planner-a2a/
├─ agents/
├─ data/
├─ schemas/
├─ services/
├─ static/
├─ templates/
├─ main.py
├─ web.py
├─ requirements.txt
└─ README.md
```

## Demo siêu ngắn

```bash
cd travel-planner-a2a
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn web:app --reload
```

Mở `http://127.0.0.1:8000` rồi nhập mô tả chuyến đi.

Test nhanh API:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/plan" `
-Method Post `
-ContentType "application/json" `
-Body '{"user_text":"Tôi muốn đi Đà Nẵng 3 ngày, ngân sách 8 triệu, 2 người, thích biển và chụp ảnh"}'
```

## Cài đặt

```bash
cd travel-planner-a2a
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Chạy CLI demo

```bash
python main.py
```

## Chạy web app

```bash
python -m uvicorn web:app --reload
```

Mở trình duyệt tại:

```text
http://127.0.0.1:8000
```

## API JSON

### POST `/api/plan`
Body:
```json
{
  "user_text": "Tôi muốn đi Đà Nẵng 3 ngày, ngân sách 8 triệu, 2 người, thích biển và chụp ảnh"
}
```

### Test bằng PowerShell
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/plan" `
-Method Post `
-ContentType "application/json" `
-Body '{"user_text":"Tôi muốn đi Đà Nẵng 3 ngày, ngân sách 8 triệu, 2 người, thích biển và chụp ảnh"}'
```

## API keys cần có

### 1. OpenWeather
```env
OPENWEATHER_API_KEY=your_openweather_key
```

### 2. SerpAPI Google Flights
```env
SERPAPI_KEY=your_serpapi_key
ORIGIN_IATA=SGN
```

## Dữ liệu live đang dùng
- **Weather**: OpenWeatherMap
- **Hotels**: OpenStreetMap / Overpass
- **Attractions**: OpenStreetMap / Overpass
- **Flights**: SerpAPI Google Flights

## Endpoint debug provider
```text
GET /api/providers-status
```

Ví dụ:
```text
http://127.0.0.1:8000/api/providers-status?destination=Da%20Nang
```

## Lưu ý quan trọng
- Nếu thiếu API key hoặc provider không trả kết quả, project sẽ không quay về mock nữa.
- Flights hiện phụ thuộc vào mapping airport code ở `services/live_travel_service.py`.
- Hotels và attractions đang dùng dữ liệu địa điểm live từ OSM/Overpass.
- Riêng giá và rating khách sạn trong live hotel hiện vẫn là giá trị ước lượng trong code, không phải booking data đầy đủ từ OTA.

## Gợi ý mở rộng tiếp theo
- mở rộng airport mapping cho nhiều thành phố hơn
- thay live hotel sang provider có giá thật hơn
- thêm endpoint `/api/providers-status`
- thêm log nguồn dữ liệu cho từng agent
