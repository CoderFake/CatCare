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
        self.latest_image = None
        self.device_status = "offline"
        self.is_connected = False
        
        self.topics = {
            'feed': 'catcare/feed',
            'mode': 'catcare/mode', 
            'status': 'catcare/status',
            'image': 'catcare/image',
            'feed_log': 'catcare/feed_log',
            'image_chunk': 'catcare/image_chunk'
        }
        
        self.image_chunks = {}
        
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("MQTT kết nối thành công")
            self.is_connected = True
            for topic in self.topics.values():
                client.subscribe(topic)
        else:
            print(f"MQTT kết nối thất bại với code {rc}")
            self.is_connected = False
    
    def on_disconnect(self, client, userdata, rc):
        print("MQTT ngắt kết nối")
        self.is_connected = False
        
    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            
            if topic == self.topics['image']:
                self._handle_image(payload)
                
            elif topic == self.topics['image_chunk']:
                self._handle_image_chunk(payload)
                
            elif topic == self.topics['status']:
                self.device_status = payload.get('status', 'offline')
                
            elif topic == self.topics['feed_log']:
                self._handle_feed_log(payload)
                
        except Exception as e:
            print(f"Lỗi xử lý MQTT message: {e}")
    
    def _handle_image(self, payload):
        try:
            image_data = base64.b64decode(payload['image'])
            self.latest_image = {
                'data': image_data,
                'timestamp': payload['timestamp'],
                'format': payload.get('format', 'jpeg')
            }
        except Exception as e:
            print(f"Lỗi xử lý ảnh: {e}")
    
    def _handle_image_chunk(self, payload):
        try:
            chunk_id = payload['chunk']
            total_chunks = payload['total']
            data = payload['data']
            
            if 'current_image' not in self.image_chunks:
                self.image_chunks['current_image'] = {}
            
            self.image_chunks['current_image'][chunk_id] = data
            
            if len(self.image_chunks['current_image']) == total_chunks:
                full_data = ""
                for i in range(total_chunks):
                    full_data += self.image_chunks['current_image'][i]
                
                image_payload = json.loads(full_data)
                self._handle_image(image_payload)
                
                self.image_chunks['current_image'] = {}
                
        except Exception as e:
            print(f"Lỗi xử lý image chunk: {e}")
    
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
            self.client = mqtt.Client()
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect  
            self.client.on_message = self.on_message
            
            broker = getattr(settings, 'MQTT_BROKER', 'broker.emqx.io')
            port = getattr(settings, 'MQTT_PORT', 1883)
            
            self.client.connect(broker, port, 60)
            self.client.loop_start()
            
        except Exception as e:
            print(f"Lỗi kết nối MQTT: {e}")
    
    def publish_feed_command(self, mode='manual'):
        if self.client and self.is_connected:
            self.client.publish(self.topics['feed'], mode)
            return True
        return False
    
    def publish_mode_change(self, mode):
        if self.client and self.is_connected:
            self.client.publish(self.topics['mode'], mode)
            return True
        return False
    
    def get_latest_image(self):
        return self.latest_image
    
    def get_device_status(self):
        return self.device_status
    
    def is_device_connected(self):
        return self.is_connected and self.device_status == "online"


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