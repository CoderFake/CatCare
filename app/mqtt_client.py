import paho.mqtt.client as mqtt
import json
import base64
import threading
import time
from django.conf import settings
from django.utils import timezone


class MQTTManager:
    """
    Quản lý kết nối MQTT
    """
    
    def __init__(self):
        self.client = None
        self.device_status = "offline"
        self.is_connected = False
        self.last_connect_time = 0
        self.connect_attempts = 0
        self.last_status_update = 0
        self.camera_info = {}
        self.last_camera_update = 0
        
        mqtt_settings = getattr(settings, 'MQTT_SETTINGS', {})
        self.topics = {
            'feed': mqtt_settings.get('TOPICS', {}).get('FEED', 'catcare/feed'),
            'mode': mqtt_settings.get('TOPICS', {}).get('MODE', 'catcare/mode'),
            'status': mqtt_settings.get('TOPICS', {}).get('STATUS', 'catcare/status'),
            'feed_log': mqtt_settings.get('TOPICS', {}).get('FEED_LOG', 'catcare/feed_log'),
            'camera_status': mqtt_settings.get('TOPICS', {}).get('CAMERA_STATUS', 'catcare/camera_status'),
        }
        
        self.mqtt_settings = mqtt_settings
        
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("MQTT kết nối thành công")
            self.is_connected = True
            self.connect_attempts = 0 
            
            print(f"Available topics to subscribe: {self.topics}")
            
            for topic_name, topic in self.topics.items():
                result = client.subscribe(topic)
                print(f"Subscribed to {topic_name}: {topic} - Result: {result}")
                if result[0] != 0:
                    print(f"CẢNH BÁO: Subscribe thất bại cho topic {topic} với code {result[0]}")
                    
            self.last_connect_time = time.time()
            print(f"MQTT connection established at {self.last_connect_time}")
            
        else:
            print(f"MQTT kết nối thất bại với code {rc}")
            self.is_connected = False
            self.connect_attempts += 1
    
    def on_disconnect(self, client, userdata, rc):
        self.is_connected = False
        current_time = time.time()
        
        if rc == 0 or (current_time - self.last_connect_time) > 30:
            if rc != 0:
                print(f"MQTT ngắt kết nối bất ngờ (code: {rc}), attempts: {self.connect_attempts}")
            else:
                print("MQTT ngắt kết nối bình thường")
            self.last_connect_time = current_time
        
    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            raw_payload = msg.payload.decode()
            print(f"Raw MQTT message received on topic '{topic}': {raw_payload}")
            
            try:
                payload = json.loads(raw_payload)
                print(f"Parsed JSON payload: {payload}")
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}, raw payload: {raw_payload}")
                return
            
            if topic == self.topics['status']:
                old_status = self.device_status
                self.device_status = payload.get('status', 'offline')
                self.last_status_update = time.time()
                print(f"Device status updated: {old_status} -> {self.device_status}")
                print(f"Status update time: {self.last_status_update}")
                print(f"Full status payload: {payload}")
                
                if 'rtsp_url' in payload:
                    print(f"RTSP Stream URL (from status): {payload['rtsp_url']}")
                    if 'fps' in payload:
                        print(f"Current FPS: {payload['fps']}")
                
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        "system_status",
                        {
                            "type": "device_status_update",
                            "status": self.device_status,
                            "payload": payload
                        }
                    )
                    print(f"Sent WebSocket update with status: {self.device_status}")
                
            elif topic == self.topics['feed_log']:
                print(f"Feed log received: {payload}")
                
                if 'rtsp_url' in payload:
                    print(f"RTSP Stream URL: {payload['rtsp_url']}")
                    print(f"RTSP Status: Available")
                
                self._handle_feed_log(payload)
                
            elif topic == self.topics['camera_status']:
                print(f"=== CAMERA STATUS RECEIVED ===")
                print(f"Device: {payload.get('device', 'unknown')}")
                print(f"Status: {payload.get('status', 'unknown')}")
                print(f"RTSP URL: {payload.get('rtsp_url', 'not available')}")
                print(f"IP Address: {payload.get('ip', 'unknown')}")
                print(f"FPS: {payload.get('fps', 0)}")
                print(f"Free Heap: {payload.get('free_heap', 0)} bytes")
                print(f"Camera Quality: {payload.get('quality', 'unknown')}")
                print(f"Timestamp: {payload.get('timestamp', 0)}")
                print(f"==============================")
                
                self.camera_info = payload
                self.last_camera_update = time.time()
                
                # Gửi camera info qua WebSocket
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        "system_status",
                        {
                            "type": "camera_status_update",
                            "camera_info": payload
                        }
                    )
                    print(f"Sent camera info via WebSocket: {payload.get('rtsp_url', 'N/A')}")
            else:
                print(f"Unknown topic '{topic}' with payload: {payload}")
                
        except Exception as e:
            print(f"Lỗi xử lý MQTT message: {e}")
            import traceback
            print(traceback.format_exc())
    

    def _handle_feed_log(self, payload):
        try:
            from .models import FeedingLog
            from django.contrib.auth.models import User
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            
            user = User.objects.first()
            if user:
                if payload.get('success', False):
                    feed_log = FeedingLog.objects.create(
                        user=user,
                        mode=payload.get('mode', 'manual'),
                        device_id=payload.get('device', 'esp32_cam')
                    )
                    
                    print(f"Feed log saved: {feed_log.mode} at {feed_log.timestamp}")
                    
                    channel_layer = get_channel_layer()
                    if channel_layer:
                        async_to_sync(channel_layer.group_send)(
                            "system_status",
                            {
                                "type": "feed_log_update",
                                "data": {
                                    "mode": feed_log.mode,
                                    "timestamp": feed_log.timestamp.isoformat(),
                                    "device_id": feed_log.device_id,
                                    "daily_count": payload.get('daily_count', 0),
                                    "rtsp_url": payload.get('rtsp_url', '')
                                }
                            }
                        )
                else:
                    print(f"Feed command failed on device: {payload}")
        except Exception as e:
            print(f"Lỗi lưu feed log: {e}")
    

    
    def connect(self):
        try:
            import uuid
            client_id = f"Django_CatCare_{uuid.uuid4().hex[:8]}"
            self.client = mqtt.Client(client_id)
            
            self.client.keepalive = 60
            self.client.reconnect_delay_set(min_delay=5, max_delay=300)
            
            self.client.will_set(self.topics['status'], 
                               json.dumps({'status': 'offline', 'timestamp': time.time()}), 
                               qos=1, retain=True)
        
            username = self.mqtt_settings.get('USERNAME', '')
            password = self.mqtt_settings.get('PASSWORD', '')
            if username and password:
                self.client.username_pw_set(username, password)
            
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect  
            self.client.on_message = self.on_message
            
            broker = self.mqtt_settings.get('BROKER', 'broker.emqx.io')
            port = self.mqtt_settings.get('PORT', 1883)
            
            print(f"Connecting to MQTT broker: {broker}:{port} with client_id: {client_id}")
            self.client.connect(broker, port, 60)
            self.client.loop_start()
            
        except Exception as e:
            print(f"Lỗi kết nối MQTT: {e}")
    
    def publish_feed_command(self, mode='manual'):
        if self.ensure_connection():
            self.client.publish(self.topics['feed'], mode)
            return True
        return False
    
    def publish_mode_change(self, mode):
        if self.ensure_connection():
            self.client.publish(self.topics['mode'], mode)
            return True
        return False
    

    
    def get_device_status(self):
        current_time = time.time()
        
        if self.last_status_update == 0:
            print("Chưa nhận được status update nào từ device")
            return "offline"
        
        time_since_update = current_time - self.last_status_update
        print(f"Time since last status update: {time_since_update:.1f} seconds")
        
        if time_since_update > 60:
            print(f"Device timeout: {time_since_update:.1f}s > 60s, marking as offline")
            self.device_status = "offline"
        
        print(f"Current device status: {self.device_status}")
        return self.device_status
    
    def is_device_connected(self):
        mqtt_connected = self.is_connected
        device_online = self.get_device_status() == "online"
        
        print(f"MQTT connected: {mqtt_connected}, Device online: {device_online}")
        return mqtt_connected and device_online
    
    def get_camera_info(self):
        """
        Lấy thông tin camera từ ESP32-CAM
        """
        current_time = time.time()
        
        if self.last_camera_update == 0:
            print("Chưa nhận được camera info từ ESP32-CAM")
            return None
        
        time_since_update = current_time - self.last_camera_update
        print(f"Time since last camera update: {time_since_update:.1f} seconds")
        
        if time_since_update > 60:
            print(f"Camera timeout: {time_since_update:.1f}s > 60s")
            return None
        
        print(f"Current camera info: {self.camera_info}")
        return self.camera_info
    
    def get_rtsp_url(self):
        """
        Lấy RTSP URL từ camera info
        """
        camera_info = self.get_camera_info()
        if camera_info:
            rtsp_url = camera_info.get('rtsp_url', '')
            print(f"RTSP URL: {rtsp_url}")
            return rtsp_url
        return None
    

    
    def debug_status(self):
        """
        Debug method để kiểm tra toàn bộ trạng thái MQTT
        """
        current_time = time.time()
        print("=== MQTT DEBUG STATUS ===")
        print(f"MQTT Client Connected: {self.is_connected}")
        print(f"Device Status: {self.device_status}")
        print(f"Last Connect Time: {self.last_connect_time}")
        print(f"Last Status Update: {self.last_status_update}")
        if self.last_status_update > 0:
            print(f"Time Since Last Update: {current_time - self.last_status_update:.1f}s")
        print(f"Connect Attempts: {self.connect_attempts}")
        print(f"Subscribed Topics: {self.topics}")
        print(f"MQTT Settings: {self.mqtt_settings}")
        
        # Camera info
        print("\n=== CAMERA INFO ===")
        print(f"Last Camera Update: {self.last_camera_update}")
        if self.last_camera_update > 0:
            print(f"Time Since Camera Update: {current_time - self.last_camera_update:.1f}s")
        print(f"Camera Info: {self.camera_info}")
        if self.camera_info:
            print(f"RTSP URL: {self.camera_info.get('rtsp_url', 'N/A')}")
            print(f"Camera IP: {self.camera_info.get('ip', 'N/A')}")
            print(f"Camera FPS: {self.camera_info.get('fps', 0)}")
            print(f"Camera Status: {self.camera_info.get('status', 'unknown')}")
        print("===================")
    
    def ensure_connection(self):
        """
        Đảm bảo kết nối MQTT, reconnect nếu cần
        """
        if not self.is_connected and self.client:
            try:
                current_time = time.time()
                if (current_time - self.last_connect_time) > 10:
                    print("Attempting MQTT reconnect...")
                    self.debug_status()
                    self.client.reconnect()
                    self.last_connect_time = current_time
            except Exception as e:
                print(f"Lỗi reconnect MQTT: {e}")
        return self.is_connected
    



mqtt_manager = MQTTManager()


def init_mqtt():
    """
    Khởi tạo MQTT connection
    """
    mqtt_manager.connect()


def get_mqtt_manager():
    """
    Lấy instance của MQTT manager
    """
    return mqtt_manager


def test_mqtt():
    """
    Function để test MQTT connection và debug
    """
    print("Testing MQTT Connection...")
    manager = get_mqtt_manager()
    manager.debug_status()
    
    if manager.is_connected:
        print("✅ MQTT Client connected")
    else:
        print("❌ MQTT Client not connected")
        
    status = manager.get_device_status()
    print(f"Device Status: {status}")
    
    if manager.is_device_connected():
        print("✅ Device is connected and online")
    else:
        print("❌ Device is offline or disconnected")
        
    print("\nCó thể test bằng cách gọi: python manage.py shell")
    print(">>> from app.mqtt_client import test_mqtt")
    print(">>> test_mqtt()")
    
    return manager