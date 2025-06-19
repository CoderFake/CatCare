# CatCare - Hệ thống cho mèo ăn tự động với ESP32-CAM

Dự án IoT tự động cho mèo ăn sử dụng ESP32-CAM, Django, MQTT và RTSP streaming.

## Tính năng chính

- **Cho mèo ăn tự động** qua web hoặc nút bấm
- **Live streaming RTSP** từ ESP32-CAM
- **Theo dõi lịch sử** cho ăn qua MQTT
- **Web interface** Django để điều khiển
- **Real-time updates** qua WebSocket
- **Thông báo** LED, buzzer khi cho ăn

## Yêu cầu hệ thống

### Hardware
- **ESP32-CAM** (AI-Thinker)
- **Servo MG90S** cho cơ chế cho ăn
- **LED** xanh/đỏ cho trạng thái
- **Buzzer** cho âm thanh
- **Nút bấm** cho chế độ manual

### Software
- **Python 3.9+**
- **Django 4.0+**
- **Arduino IDE** hoặc PlatformIO
- **MQTT Broker** (sẽ dùng broker.emqx.io miễn phí)

## Cài đặt và Cấu hình

### 1. Setup Django Backend

#### Bước 1: Clone và cài đặt dependencies
```bash
git clone <repository-url>
cd CatCare

# Tạo virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# hoặc
venv\Scripts\activate     # Windows

# Cài đặt packages
pip install -r requirements.txt
```

#### Bước 2: Cấu hình environment
```bash
# Copy file cấu hình mẫu
cp env.example .env

# Chỉnh sửa file .env
nano .env
```

**Cấu hình .env:**
```env
# Django Settings
SECRET_KEY=your-secret-key-here-change-this
DEBUG=True
TIME_ZONE=Asia/Ho_Chi_Minh

# MQTT Settings
MQTT_BROKER=broker.emqx.io
MQTT_PORT=1883
MQTT_CLIENT_ID=Django_CatCare_Server
MQTT_USERNAME=
MQTT_PASSWORD=

# MQTT Topics (giữ nguyên nếu không có lý do đặc biệt)
MQTT_TOPIC_FEED=catcare/feed
MQTT_TOPIC_MODE=catcare/mode
MQTT_TOPIC_STATUS=catcare/status
MQTT_TOPIC_FEED_LOG=catcare/feed_log

# Camera Settings
CAMERA_FLIP_HORIZONTAL=True
CAMERA_FLIP_VERTICAL=False
CAMERA_DETECTION_ENABLED=True

# ESP32 Settings - ⚠️ CẬP NHẬT IP THẬT CỦA ESP32-CAM
ESP32_IP=192.168.1.100
```

#### Bước 3: Khởi tạo database
```bash
python manage.py makemigrations
python manage.py migrate
python init_superuser.py
```

### 2. Setup ESP32-CAM

#### Bước 1: Cài đặt Arduino IDE
1. Tải Arduino IDE từ https://www.arduino.cc/
2. Thêm ESP32 board:
   - File → Preferences
   - Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Tìm "ESP32" và cài đặt

#### Bước 2: Cài đặt thư viện
Trong Arduino IDE: Tools → Manage Libraries, tìm và cài đặt:
- `PubSubClient` by Nick O'Leary
- `ArduinoJson` by Benoit Blanchon  
- `ESP32Servo` by Kevin Harrington
- `ESP32-RTSPServer` by Geekshop Electronics

#### Bước 3: Cấu hình WiFi
Tạo file `cat_care/wifikeys.h`:
```cpp
#ifndef WIFIKEYS_H
#define WIFIKEYS_H

const char* ssid = "TEN_WIFI_CUA_BAN";
const char* password = "MAT_KHAU_WIFI";

#endif
```

#### Bước 4: Upload code
1. Mở file `cat_care/cat_care.ino`
2. Chọn board: **AI Thinker ESP32-CAM**
3. Chọn port COM tương ứng
4. Bấm Upload

### 3. Chạy hệ thống

#### Bước 1: Chạy Django server
```bash

# Terminal 2: Daphne cho WebSocket
daphne -b 0.0.0.0 -p 8001 CatCare.asgi:application
```

#### Bước 3: Kiểm tra ESP32-CAM
1. Mở Serial Monitor (115200 baud)
2. Reset ESP32-CAM
3. Chờ kết nối WiFi và MQTT
4. Ghi lại **IP address** hiển thị

#### Bước 4: Cập nhật IP trong .env
```bash
# Cập nhật IP thật của ESP32-CAM
ESP32_IP=192.168.1.XXX  # IP từ Serial Monitor
```

## Sử dụng hệ thống

### 1. Web Interface
- Truy cập: `http://localhost:8000`
- Login bằng superuser đã tạo
- Điều khiển cho ăn, xem lịch sử

### 2. RTSP Stream  
- URL: `rtsp://[ESP32_IP]:8554/`
- Có thể xem bằng VLC: Media → Open Network Stream

### 3. Điều khiển Manual
- Bấm nút trên ESP32-CAM để cho ăn manual
- LED đỏ: chế độ chờ
- LED xanh: đang cho ăn
- Buzzer: báo hiệu khi cho ăn

## Debug và Troubleshooting

### 1. ESP32-CAM không kết nối WiFi
```bash
# Kiểm tra Serial Monitor
- Đảm bảo WiFi credentials đúng
- Thử reset ESP32-CAM
- Kiểm tra tín hiệu WiFi
```

### 2. MQTT không hoạt động
```bash
# Test MQTT connection
python manage.py shell
>>> from app.mqtt_client import test_mqtt
>>> test_mqtt()
```

### 3. Servo không quay
```bash  
# Kiểm tra trong Serial Monitor:
[SERVO] Attached to pin 16
[SERVO] Testing servo movement...  
[SERVO] Position: 0

# Nếu không thấy log → kiểm tra kết nối
# Nếu thấy log nhưng không quay → cấp nguồn riêng 5V cho servo
```

### 4. RTSP không stream
```bash
# Kiểm tra IP ESP32-CAM
ping [ESP32_IP]

# Test RTSP bằng VLC
vlc rtsp://[ESP32_IP]:8554/
```

## Tính năng nâng cao

### 1. Tự động hóa theo lịch
- Sửa code Django để thêm scheduled feeding
- Sử dụng cho background tasks

### 2. AI Detection
- Thêm computer vision để detect mèo
- Phát hiện mèo có bị bệnh hay không
