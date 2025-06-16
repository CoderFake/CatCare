import json
import asyncio
import base64
import cv2
import numpy as np
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.conf import settings
import os
from ultralytics import YOLO
import time
import logging
import warnings
import threading
import queue
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore")
logging.getLogger('ultralytics').setLevel(logging.ERROR)

os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'

class VideoStreamConsumer(AsyncWebsocketConsumer):
    _shared_frame_queue = None
    _shared_capture_thread = None
    _shared_streaming = False
    _connection_lock = threading.Lock()
    
    async def connect(self):
        await self.accept()
        self.streaming = True
        self.detection_enabled = False
        self.last_detection_time = 0
        self.detection_interval = 5 
        self.executor = ThreadPoolExecutor(max_workers=2)
        
        with VideoStreamConsumer._connection_lock:
            if VideoStreamConsumer._shared_frame_queue is None:
                VideoStreamConsumer._shared_frame_queue = queue.Queue(maxsize=3)
            self.frame_queue = VideoStreamConsumer._shared_frame_queue
            
            if (VideoStreamConsumer._shared_capture_thread is None or 
                not VideoStreamConsumer._shared_capture_thread.is_alive()):
                VideoStreamConsumer._shared_streaming = True
                esp32_ip = settings.ESP32_IP
                rtsp_url = f"rtsp://{esp32_ip}:8554/" 
                VideoStreamConsumer._shared_capture_thread = threading.Thread(
                    target=self.capture_frames_thread,
                    args=(rtsp_url,),
                    daemon=True
                )
                VideoStreamConsumer._shared_capture_thread.start()
        
        self.stream_task = asyncio.create_task(self.stream_video())
    
    async def disconnect(self, close_code):
        self.streaming = False
        if hasattr(self, 'stream_task'):
            self.stream_task.cancel()
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
        
        with VideoStreamConsumer._connection_lock:
            try:
                if (VideoStreamConsumer._shared_capture_thread and 
                    VideoStreamConsumer._shared_capture_thread.is_alive()):
                    VideoStreamConsumer._shared_streaming = False
                    VideoStreamConsumer._shared_capture_thread.join(timeout=2)
                    VideoStreamConsumer._shared_capture_thread = None
                    VideoStreamConsumer._shared_frame_queue = None
            except:
                pass
    
    def capture_frames_thread(self, rtsp_url):
        """Thread riêng để capture frames từ RTSP - không block Django"""
        cap = None
        retry_count = 0
        max_retries = 5
        
        while VideoStreamConsumer._shared_streaming:
            try:
                cap = None
                backends = [
                    (cv2.CAP_FFMPEG, "CAP_FFMPEG"),
                    (cv2.CAP_ANY, "CAP_ANY (default)"),
                ]
                
                for backend_id, backend_name in backends:
                    try:
                        cap = cv2.VideoCapture(rtsp_url, backend_id)
                        
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
                        cap.set(cv2.CAP_PROP_FPS, 10) 
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        
                        if cap.isOpened():
                            break
                        else:
                            cap.release()
                            cap = None
                    except Exception as e:
                        if cap:
                            cap.release()
                        cap = None
                
                if not cap:
                    raise Exception("Cannot open RTSP stream")
                
                test_success = False
                for test_attempt in range(3):
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None:
                        test_success = True
                        break
                    else:
                        time.sleep(0.5)
                
                if not test_success:
                    raise Exception("Cannot read frames from RTSP")
                
                retry_count = 0
                consecutive_failures = 0
                frame_count = 0
                
                while VideoStreamConsumer._shared_streaming:
                    ret, frame = cap.read()
                    
                    if not ret or frame is None:
                        consecutive_failures += 1
                        if consecutive_failures > 10:  
                            break
                        time.sleep(0.1)
                        continue
                    
                    consecutive_failures = 0
                    frame_count += 1
                   
                    try:
                        while not VideoStreamConsumer._shared_frame_queue.empty():
                            try:
                                VideoStreamConsumer._shared_frame_queue.get_nowait()
                            except queue.Empty:
                                break
                        
                        VideoStreamConsumer._shared_frame_queue.put_nowait(frame)
                        
                    except queue.Full:
                        pass
                    
                    time.sleep(0.1)  # 10 FPS
                
            except Exception as e:
                error_str = str(e).lower()
                if 'missing packets' not in error_str and 'rtp timestamps' not in error_str:
                    print(f"RTSP connection error: {e}")
                retry_count += 1
                
            finally:
                if cap is not None:
                    cap.release()
            
            if VideoStreamConsumer._shared_streaming and retry_count <= max_retries:
                retry_delay = min(retry_count * 3, 10)
                time.sleep(retry_delay)
            else:
                break
    
    async def stream_video(self):
        """Main streaming loop chỉ lấy frames từ shared queue"""
        import asyncio
        import time
        
        await self.send(text_data=json.dumps({
            'type': 'status',
            'message': 'Waiting for RTSP frames...'
        }))
        
        camera_settings = getattr(settings, 'CAMERA_SETTINGS', {})
        last_frame_time = time.time()
        connection_notified = False
        
        while self.streaming:
            try:
                try:
                    frame = self.frame_queue.get_nowait()
                    last_frame_time = time.time()
                    
                    if not connection_notified:
                        await self.send(text_data=json.dumps({
                            'type': 'status',
                            'message': 'RTSP connected'
                        }))
                        connection_notified = True
                        
                except queue.Empty:
                    if time.time() - last_frame_time > 10:
                        await self.send(text_data=json.dumps({
                            'type': 'status', 
                            'message': 'Waiting for RTSP frames...'
                        }))
                        last_frame_time = time.time()
                        connection_notified = False
                    
                    await asyncio.sleep(0.1)
                    continue
                
                flip_horizontal = os.getenv('CAMERA_FLIP_HORIZONTAL', 'False').lower() == 'true'
                flip_vertical = os.getenv('CAMERA_FLIP_VERTICAL', 'False').lower() == 'true'
                rotate_180 = os.getenv('CAMERA_ROTATE_180', 'False').lower() == 'true'
                
                if flip_horizontal:
                    frame = cv2.flip(frame, 1)
                
                if flip_vertical:
                    frame = cv2.flip(frame, 0)
                
                if rotate_180:
                    frame = cv2.flip(frame, -1)
                
                current_time = time.time()
                if (self.detection_enabled and 
                    current_time - self.last_detection_time > self.detection_interval):
                    
                    loop = asyncio.get_event_loop()
                    detection_result = await loop.run_in_executor(
                        self.executor, 
                        self.detect_disease_sync, 
                        frame.copy()
                    )
                    
                    if detection_result:
                        await self.send(text_data=json.dumps({
                            'type': 'detection_result',
                            **detection_result
                        }))
                    
                    self.last_detection_time = current_time
                
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                
                if ret:
                    img_base64 = base64.b64encode(buffer).decode('utf-8')
                    
                    await self.send(text_data=json.dumps({
                        'type': 'video_frame',
                        'image': img_base64
                    }))
                
                await asyncio.sleep(0.1)  # 10 FPS
                
            except Exception as e:
                print(f"Stream processing error: {e}")
                await asyncio.sleep(0.5)
    
    def detect_disease_sync(self, frame):
        """Synchronous disease detection để chạy trong thread pool"""
        try:
            from ultralytics import YOLO
            import torch
            
            disease_mapping = {
                'demodicosis': 'Ghẻ demodex',
                'dermatitis': 'Viêm da', 
                'flea_allergy': 'Dị ứng bọ chét',
                'fungus': 'Nấm da',
                'ringworm': 'Nấm tròn',
                'scabies': 'Ghẻ sarcoptic'
            }
            
            model_path = os.path.join(settings.BASE_DIR, 'static', 'model', 'cat.pt')
            
            if not os.path.exists(model_path):
                return
            
            model = None
            load_methods = [
                lambda: self._load_model_with_safe_globals(model_path),
                lambda: self._load_model_with_weights_only_false(model_path),
                lambda: YOLO(model_path)
            ]
            
            for i, method in enumerate(load_methods):
                try:
                    model = method()
                    break
                except Exception as e:
                    if i == len(load_methods) - 1:
                        raise e
                    continue
            
            results = model(frame)
            
            cat_detected = False
            cat_confidence = 0
            diseases_detected = []
            
            camera_settings = getattr(settings, 'CAMERA_SETTINGS', {})
            confidence_threshold = camera_settings.get('DETECTION_CONFIDENCE_THRESHOLD', 0.5)
            
            for result in results:
                if result.boxes is not None and result.names is not None:
                    for box in result.boxes:
                        conf = float(box.conf[0])
                        cls_id = int(box.cls[0])
                        class_name = result.names[cls_id]
                        
                        if conf >= confidence_threshold:
                            if class_name in disease_mapping:
                                disease_vn_name = disease_mapping[class_name]
                                diseases_detected.append({
                                    'disease': disease_vn_name,
                                    'confidence': int(conf * 100),
                                    'english_name': class_name
                                })
                            
                            if not cat_detected or conf > cat_confidence:
                                cat_detected = True
                                cat_confidence = int(conf * 100)
            
            return {
                'cat_detected': cat_detected,
                'cat_confidence': cat_confidence,
                'diseases': diseases_detected,
                'total_diseases': len(diseases_detected)
            }
            
        except Exception as e:
            print(f"Detection error: {e}")
            return None
    
    def _load_model_with_safe_globals(self, model_path):
        import torch
        torch.serialization.add_safe_globals([
            'ultralytics.nn.tasks.DetectionModel',
            'ultralytics.nn.modules.block.C3k2',
            'ultralytics.nn.modules.conv.Conv',
            'ultralytics.nn.modules.head.Detect'
        ])
        return YOLO(model_path)
    
    def _load_model_with_weights_only_false(self, model_path):
        """Load với weights_only=False"""
        import torch
        original_load = torch.load
        torch.load = lambda *args, **kwargs: original_load(*args, **kwargs, weights_only=False)
        try:
            model = YOLO(model_path)
            return model
        finally:
            torch.load = original_load

    async def receive(self, text_data):
        """Nhận lệnh từ client"""
        try:
            data = json.loads(text_data)
            command = data.get('command')
            
            if command == 'start_stream':
                if not self.streaming:
                    self.streaming = True
                    self.stream_task = asyncio.create_task(self.stream_video())
            
            elif command == 'stop_stream':
                self.streaming = False
                if hasattr(self, 'stream_task'):
                    self.stream_task.cancel()
            
            elif command == 'reconnect_camera':
                with VideoStreamConsumer._connection_lock:
                    VideoStreamConsumer._shared_streaming = False
                    if (VideoStreamConsumer._shared_capture_thread and 
                        VideoStreamConsumer._shared_capture_thread.is_alive()):
                        VideoStreamConsumer._shared_capture_thread.join(timeout=3)
                    
                    VideoStreamConsumer._shared_capture_thread = None
                    VideoStreamConsumer._shared_frame_queue = queue.Queue(maxsize=3)
                    VideoStreamConsumer._shared_streaming = True
                    
                    esp32_ip = settings.ESP32_IP
                    rtsp_url = f"rtsp://{esp32_ip}:8554/"
                    VideoStreamConsumer._shared_capture_thread = threading.Thread(
                        target=self.capture_frames_thread,
                        args=(rtsp_url,),
                        daemon=True
                    )
                    VideoStreamConsumer._shared_capture_thread.start()
                
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'message': 'Camera reconnecting...'
                }))
            
            elif command == 'start_detection':
                self.detection_enabled = True
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'message': 'Real-time detection started'
                }))
                
            elif command == 'stop_detection':
                self.detection_enabled = False
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'message': 'Real-time detection stopped'
                }))
            
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON'
            }))


class SystemStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        
        await self.channel_layer.group_add(
            "system_status",
            self.channel_name
        )
        
        self.status_task = asyncio.create_task(self.send_status_updates())
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            "system_status",
            self.channel_name
        )
        
        if hasattr(self, 'status_task'):
            self.status_task.cancel()
    
    async def send_status_updates(self):
        """Gửi status updates định kỳ"""
        while True:
            try:
                from .mqtt_client import get_mqtt_manager
                from .models import SystemSettings, FeedingLog
                from django.utils import timezone
                from django.contrib.auth.models import User
                
                mqtt_manager = get_mqtt_manager()
                
                user = await database_sync_to_async(lambda: User.objects.first())()
                
                if user:
                    try:
                        system_settings = await database_sync_to_async(
                            lambda: SystemSettings.objects.get(user=user)
                        )()
                        current_mode = system_settings.current_mode
                    except:
                        current_mode = 'manual'
                    
                    today = timezone.now().date()
                    today_feeds = await database_sync_to_async(
                        lambda: FeedingLog.objects.filter(
                            user=user, 
                            timestamp__date=today
                        ).count()
                    )()
                    
                    status_data = {
                        'type': 'status_update',
                        'device_status': mqtt_manager.get_device_status(),
                        'current_mode': current_mode,
                        'is_connected': mqtt_manager.is_device_connected(),
                        'today_feeds': today_feeds,
                        'timestamp': timezone.now().isoformat()
                    }
                    
                    await self.send(text_data=json.dumps(status_data))
                
                await asyncio.sleep(10) 
                
            except Exception as e:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Lỗi cập nhật status: {str(e)}'
                }))
                await asyncio.sleep(5)
    
    async def feed_log_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'feed_log',
            'data': event['data']
        }))
    
    async def device_status_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'device_status',
            'status': event['status']
        })) 