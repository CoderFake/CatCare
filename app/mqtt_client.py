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
        
        mqtt_settings = getattr(settings, 'MQTT_SETTINGS', {})
        self.topics = {
            'feed': mqtt_settings.get('TOPICS', {}).get('FEED', 'catcare/feed'),
            'mode': mqtt_settings.get('TOPICS', {}).get('MODE', 'catcare/mode'),
            'status': mqtt_settings.get('TOPICS', {}).get('STATUS', 'catcare/status'),
            'feed_log': mqtt_settings.get('TOPICS', {}).get('FEED_LOG', 'catcare/feed_log'),
        }
        
        self.mqtt_settings = mqtt_settings
        
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("MQTT kết nối thành công")
            self.is_connected = True
            self.connect_attempts = 0 
            for topic_name, topic in self.topics.items():
                result = client.subscribe(topic)
                print(f"Subscribed to {topic_name}: {topic} - Result: {result}")
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
            payload = json.loads(msg.payload.decode())
            
            if topic == self.topics['status']:
                self.device_status = payload.get('status', 'offline')
                print(f"Device status updated: {self.device_status}")
                
            elif topic == self.topics['feed_log']:
                self._handle_feed_log(payload)
                
        except Exception as e:
            print(f"Lỗi xử lý MQTT message: {e}")
    

    def _handle_feed_log(self, payload):
        try:
            from .models import FeedingLog
            from django.contrib.auth.models import User
            
            user = User.objects.first()
            if user:
                FeedingLog.objects.create(
                    user=user,
                    mode=payload.get('mode', 'manual'),
                    device_id=payload.get('device', 'esp32_cam')
                )
        except Exception as e:
            print(f"Lỗi lưu feed log: {e}")
    

    
    def connect(self):
        try:
            # Tạo client_id unique để tránh conflict
            import uuid
            client_id = f"Django_CatCare_{uuid.uuid4().hex[:8]}"
            self.client = mqtt.Client(client_id)
            
            # Cấu hình keep alive và reconnect với backoff
            self.client.keepalive = 60
            self.client.reconnect_delay_set(min_delay=5, max_delay=300)
            
            # Cấu hình will message để báo offline khi mất kết nối
            self.client.will_set(self.topics['status'], 
                               json.dumps({'status': 'offline', 'timestamp': time.time()}), 
                               qos=1, retain=True)
            
            # Set username/password nếu có
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
        return self.device_status
    
    def is_device_connected(self):
        return self.is_connected and self.device_status == "online"
    

    
    def ensure_connection(self):
        """
        Đảm bảo kết nối MQTT, reconnect nếu cần
        """
        if not self.is_connected and self.client:
            try:
                current_time = time.time()
                if (current_time - self.last_connect_time) > 10:
                    print("Attempting MQTT reconnect...")
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