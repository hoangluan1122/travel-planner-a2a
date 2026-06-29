# Travel Planner A2A

Ứng dụng web lập kế hoạch du lịch bằng Python/FastAPI theo hướng Agent2Agent (A2A). Người dùng nhập yêu cầu chuyến đi, hệ thống phân tích điểm đến, số ngày, ngân sách, số người, ngày khởi hành và trả về kế hoạch gồm lịch trình, phương tiện, khách sạn, điểm tham quan, thời tiết, chi phí và trạng thái nguồn dữ liệu.

## Tính năng chính

- Giao diện web v2 nền sáng tại `/v2`, thiết kế theo phong cách SaaS du lịch hiện đại.
- Luồng chuẩn POST -> Redirect -> GET cho `/v2/plan`, giúp refresh trang kết quả mà không gửi lại form.
- Trang kết quả `/v2/result/{plan_id}` hiển thị đầy đủ dữ liệu backend trả về.
- Lịch trình theo ngày, bản đồ xem trước, ngân sách, thời tiết, phương tiện, lưu trú, điểm tham quan và ghi chú.
- API JSON cho kiểm thử và tích hợp.
- Live provider cho thời tiết, chuyến bay, khách sạn và điểm tham quan khi có API key phù hợp.
- Fallback dữ liệu chọn lọc cho một số điểm đến như Đà Nẵng và Hạ Long để tránh rỗng dữ liệu khi provider ngoài không trả kết quả.

## Kiến trúc agent

- `RootTravelPlannerAgent`: nhận yêu cầu người dùng, điều phối các agent con và tổng hợp kết quả.
- `WeatherAgent`: lấy và tóm tắt thời tiết từ OpenWeather.
- `FlightAgent`: lấy gợi ý chuyến bay từ SerpAPI Google Flights.
- `HotelAgent`: tìm khách sạn từ Google Hotels/Booking provider hoặc OpenStreetMap/Overpass.
- `AttractionAgent`: đề xuất điểm tham quan, có phối hợp với `WeatherAgent` để điều chỉnh theo thời tiết.

Điểm A2A chính của demo là specialist agent có thể cộng tác với specialist agent khác, không chỉ phụ thuộc vào root agent.

## Cấu trúc thư mục

```text
travel-planner-a2a/
├─ agents/
├─ data/
├─ schemas/
├─ services/
├─ static/
├─ templates/
│  ├─ index.html
│  └─ index_v2.html
├─ main.py
├─ web.py
├─ requirements.txt
└─ README.md
```

## Cài đặt

```powershell
cd travel-planner-a2a
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Chạy web app

```powershell
.\.venv\Scripts\python.exe -m uvicorn web:app --host 127.0.0.1 --port 8000
```

Mở giao diện v2:

```text
http://127.0.0.1:8000/v2
```

Khi gửi form, app xử lý tại `POST /v2/plan`, lưu kết quả tạm bằng `plan_id`, rồi redirect sang:

```text
GET /v2/result/{plan_id}
```

Nhờ vậy người dùng có thể refresh trang kết quả mà không bị gửi lại form. Cache kết quả v2 là in-memory, giới hạn 50 plan và TTL 1 giờ.

## Chạy CLI demo

```powershell
.\.venv\Scripts\python.exe main.py
```

## API chính

### POST `/api/plan`

```json
{
  "user_text": "Tôi muốn đi Đà Nẵng 3 ngày, ngân sách 8 triệu, 2 người, thích biển và chụp ảnh"
}
```

Test nhanh bằng PowerShell:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/plan" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"user_text":"Tôi muốn đi Đà Nẵng 3 ngày, ngân sách 8 triệu, 2 người, thích biển và chụp ảnh"}'
```

### GET `/api/debug-plan`

Kiểm tra nhanh kết quả parse, chi phí và danh sách provider trả về.

```text
http://127.0.0.1:8000/api/debug-plan?user_text=Tôi%20muốn%20đi%20Đà%20Nẵng%203%20ngày
```

### GET `/api/providers-status`

Kiểm tra trạng thái nguồn dữ liệu theo điểm đến.

```text
http://127.0.0.1:8000/api/providers-status?destination=Da%20Nang
```

### GET `/api/reverse-origin`

Suy luận điểm xuất phát từ tọa độ trình duyệt gửi lên.

### GET `/health`

Health check cơ bản.

## Biến môi trường

```env
OPENWEATHER_API_KEY=your_openweather_key
SERPAPI_KEY=your_serpapi_key
ORIGIN_IATA=SGN
GEOAPIFY_API_KEY=your_geoapify_key
RAPIDAPI_KEY=your_rapidapi_key
```

Một số provider là tùy chọn. Nếu thiếu key hoặc provider không trả dữ liệu, app sẽ hiển thị trạng thái rõ ràng và dùng nguồn còn lại nếu có.

## Nguồn dữ liệu

- Weather: OpenWeatherMap.
- Flights: SerpAPI Google Flights.
- Hotels: SerpAPI Google Hotels, RapidAPI Booking, Geoapify, OpenStreetMap/Overpass.
- Attractions: Geoapify, Wikipedia GeoSearch, OpenStreetMap/Overpass và danh sách curated cho điểm đến hỗ trợ.

## Ghi chú

- Giá khách sạn từ OSM/Overpass chỉ là ước lượng, không phải dữ liệu OTA đầy đủ.
- Kết quả `/v2/result/{plan_id}` đang lưu trong bộ nhớ tiến trình, nên sẽ mất khi restart server.
- Giao diện v2 chỉ hiển thị các chức năng backend đang có; không thêm các nút giả như lưu, chia sẻ hay trợ lý chat nếu chưa có xử lý thật.
