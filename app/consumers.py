import json
import asyncio
import base64
import cv2
import numpy as np
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.conf import settings
import os
import time
import logging
import warnings
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from .disease_detector import get_cat_care_detector

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
        self.cat_detection_enabled = True 
        self.disease_detection_enabled = True 
        self.last_detection_time = 0
        self.detection_interval = 5 
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.detector = get_cat_care_detector()
        
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
        
        print(f"Bắt đầu kết nối RTSP: {rtsp_url}")
        
        while VideoStreamConsumer._shared_streaming:
            try:
                cap = None
                backends = [
                    (cv2.CAP_FFMPEG, "CAP_FFMPEG"),
                    (cv2.CAP_ANY, "CAP_ANY (default)"),
                    (cv2.CAP_GSTREAMER, "CAP_GSTREAMER"),
                ]
                
                for backend_id, backend_name in backends:
                    try:
                        print(f"Thử kết nối với backend: {backend_name}")
                        cap = cv2.VideoCapture(rtsp_url, backend_id)
                        
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        cap.set(cv2.CAP_PROP_FPS, 15) 
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M','J','P','G'))
                        
                        if cap.isOpened():
                            print(f"Kết nối thành công với {backend_name}")
                            break
                        else:
                            print(f"Không thể mở stream với {backend_name}")
                            cap.release()
                            cap = None
                    except Exception as e:
                        print(f"Lỗi khi thử {backend_name}: {e}")
                        if cap:
                            cap.release()
                        cap = None
                
                if not cap:
                    print("Không thể mở RTSP stream với bất kỳ backend nào")
                    raise Exception("Cannot open RTSP stream")
                
                print("Đang test đọc frame...")
                test_success = False
                for test_attempt in range(5):  # Tăng số lần thử
                    print(f"Thử đọc frame lần {test_attempt + 1}/5...")
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None:
                        print(f"Đọc frame thành công! Kích thước: {test_frame.shape}")
                        test_success = True
                        break
                    else:
                        print(f"Thất bại lần {test_attempt + 1}, đợi 1s...")
                        time.sleep(1.0)  # Tăng thời gian chờ
                
                if not test_success:
                    print("Không thể đọc frame nào từ RTSP sau 5 lần thử")
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
                    print(f"RTSP connection error (attempt {retry_count + 1}/{max_retries}): {e}")
                    print(f"Error type: {type(e).__name__}")
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
                
                camera_settings = getattr(settings, 'CAMERA_SETTINGS', {})
                flip_horizontal = camera_settings.get('FLIP_HORIZONTAL', False)
                flip_vertical = camera_settings.get('FLIP_VERTICAL', False)
                rotate_180 = camera_settings.get('ROTATE_180', False)
                
                if flip_horizontal:
                    frame = cv2.flip(frame, 1)
                
                if flip_vertical:
                    frame = cv2.flip(frame, 0)
                
                if rotate_180:
                    frame = cv2.flip(frame, -1)
                
                current_time = time.time()
                cats_detected = []
                
                if self.cat_detection_enabled and self.detector.cat_detector.is_available():
                    annotated_frame, cats_detected = self.detector.detect_cat_realtime(frame.copy())
                    frame = annotated_frame
                
                should_detect_disease = False
                
                if should_detect_disease:
                    loop = asyncio.get_event_loop()
                    detection_result = await loop.run_in_executor(
                        self.executor, 
                        self.detect_disease_on_frame_sync, 
                        frame.copy()
                    )
                    
                    if detection_result:
                        print(f"Sending WebSocket message: {detection_result}") 
                        await self.send(text_data=json.dumps({
                            'type': 'disease_detection_result',
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
    
    def get_current_frame(self):
        """Lấy frame hiện tại từ queue"""
        try:
            if VideoStreamConsumer._shared_frame_queue and not VideoStreamConsumer._shared_frame_queue.empty():
                frame = VideoStreamConsumer._shared_frame_queue.get_nowait()
                return frame
        except queue.Empty:
            pass
        return None
    
    def detect_disease_on_frame_sync(self, frame):
        """Synchronous disease detection để chạy trong thread pool"""
        try:
            from django.contrib.auth.models import User
            
            user = User.objects.first()
            if not user:
                return None
            
            result = self.detector.detect_diseases_on_frame(frame, user)
            print(f"Disease detection result: {result}") 
            
            if result['success']:
                diseases_formatted = []
                for disease in result.get('diseases', []):
                    diseases_formatted.append({
                        'disease': disease.get('disease_vn', disease.get('disease_en', 'Unknown')),
                        'confidence': int(disease['confidence']),
                        'english_name': disease.get('disease_en', 'unknown')
                    })
                
                if result.get('cat_detected', False) and result.get('cat_cropped', False):
                    if diseases_formatted:
                        message = f'Phát hiện mèo → Crop thành công → Tìm thấy {len(diseases_formatted)} bệnh'
                    else:
                        message = 'Phát hiện mèo → Crop thành công → Mèo khỏe mạnh'
                else:
                    message = 'Phát hiện bệnh thành công' if diseases_formatted else 'Không phát hiện bệnh'
                
                return {
                    'cat_detected': result.get('cat_detected', False),
                    'cat_cropped': result.get('cat_cropped', False),
                    'cat_confidence': result.get('cat_confidence', 0),
                    'diseases': diseases_formatted,
                    'total_diseases': len(diseases_formatted),
                    'message': message
                }
            else:
                error_message = result.get('message', 'Không thể phát hiện bệnh')
                if 'Không phát hiện mèo' in error_message:
                    error_message = 'Không phát hiện mèo trong khung hình → Không thể crop → Bỏ qua detect bệnh'
                
                return {
                    'cat_detected': result.get('cat_detected', False),
                    'cat_cropped': result.get('cat_cropped', False), 
                    'cat_confidence': result.get('cat_confidence', 0),
                    'diseases': [],
                    'total_diseases': 0,
                    'message': error_message
                }
                
        except Exception as e:
            print(f"Disease detection error: {e}")
            return {
                'cat_detected': False,
                'cat_cropped': False,
                'diseases': [],
                'total_diseases': 0,
                'message': f'Lỗi: {str(e)}'
            }

    def detect_disease_multi_frame_sync(self):
        """Phát hiện bệnh bằng cách phân tích nhiều frame trong 5 giây"""
        import time
        from collections import defaultdict
        
        print("Bắt đầu phân tích video trong 5 giây...")
        start_time = time.time()
        frame_results = []
        frames_analyzed = 0
        detection_interval = 0.5 
        
        try:
            from django.contrib.auth.models import User
            user = User.objects.first()
            if not user:
                return {
                    'cat_detected': False,
                    'diseases': [],
                    'total_diseases': 0,
                    'message': 'Không tìm thấy user'
                }
            
            last_analysis_time = 0
            
            while time.time() - start_time < 5.0:
                current_time = time.time()
                
                if current_time - last_analysis_time >= detection_interval:
                    frame = self.get_current_frame()
                    if frame is not None:
                        try:
                            result = self.detector.detect_diseases_on_frame(frame, user)
                            if result and result.get('success', False):
                                frame_results.append(result)
                                frames_analyzed += 1
                                diseases_count = len(result.get('diseases', []))
                                print(f"Frame {frames_analyzed}: {diseases_count} bệnh phát hiện")
                            
                            last_analysis_time = current_time
                            
                        except Exception as e:
                            print(f"Lỗi phân tích frame {frames_analyzed + 1}: {e}")
                
                time.sleep(0.1)
            
            if not frame_results:
                return {
                    'cat_detected': False,
                    'diseases': [],
                    'total_diseases': 0,
                    'message': 'Không thể lấy frame nào để phân tích trong 5 giây'
                }
            
            print(f"Đã phân tích {frames_analyzed} frames trong 5 giây")
            return self._aggregate_detection_results(frame_results)
            
        except Exception as e:
            print(f"Lỗi trong quá trình phân tích multi-frame: {e}")
            return {
                'cat_detected': False,
                'diseases': [],
                'total_diseases': 0,
                'message': f'Lỗi: {str(e)}'
            }

    def _aggregate_detection_results(self, frame_results):
        """Tổng hợp kết quả từ nhiều frame để có kết quả tốt nhất"""
        from collections import defaultdict
        
        if not frame_results:
            return {
                'cat_detected': False,
                'diseases': [],
                'total_diseases': 0,
                'message': 'Không có dữ liệu để tổng hợp'
            }
        
        disease_stats = defaultdict(list) 
        cat_detected_count = 0
        cat_cropped_count = 0
        total_frames = len(frame_results)
        
        for result in frame_results:
            if result.get('cat_detected', False):
                cat_detected_count += 1
            if result.get('cat_cropped', False):
                cat_cropped_count += 1
            
            diseases = result.get('diseases', [])
            for disease in diseases:
                disease_name = disease.get('disease_vn', disease.get('disease_en', 'Unknown'))
                confidence = disease.get('confidence', 0)
                disease_stats[disease_name].append({
                    'confidence': confidence,
                    'english_name': disease.get('disease_en', 'unknown')
                })

        final_diseases = []
        
        for disease_name, disease_data in disease_stats.items():
            appearance_rate = len(disease_data) / total_frames
            if appearance_rate >= 0.3:
                confidences = [d['confidence'] for d in disease_data]
                avg_confidence = sum(confidences) / len(confidences)
                max_confidence = max(confidences)
                
                best_record = max(disease_data, key=lambda x: x['confidence'])
                
                final_diseases.append({
                    'disease': disease_name,
                    'confidence': int(max_confidence), 
                    'english_name': best_record['english_name'],
                    'avg_confidence': avg_confidence,
                    'appearance_rate': appearance_rate,
                    'detection_count': len(disease_data)
                })
        
        # Sắp xếp theo confidence giảm dần
        final_diseases.sort(key=lambda x: x['confidence'], reverse=True)
        
        # Tính cat detection và cropping
        cat_detected = cat_detected_count >= (total_frames * 0.5)  # Mèo xuất hiện ít nhất 50% frames
        cat_cropped = cat_cropped_count >= (total_frames * 0.3)   # Crop thành công ít nhất 30% frames
        
        # Tạo message
        if cat_detected and cat_cropped:
            if final_diseases:
                message = f'Phân tích {total_frames} frames → Phát hiện mèo → Crop thành công → Tìm thấy {len(final_diseases)} loại bệnh'
            else:
                message = f'Phân tích {total_frames} frames → Phát hiện mèo → Crop thành công → Mèo khỏe mạnh'
        elif cat_detected:
            message = f'Phân tích {total_frames} frames → Phát hiện mèo → Không thể crop → Không phân tích được bệnh'
        else:
            message = f'Phân tích {total_frames} frames → Không phát hiện mèo trong đủ frame'
        
        result = {
            'cat_detected': cat_detected,
            'cat_cropped': cat_cropped,
            'cat_confidence': cat_detected_count / total_frames if total_frames > 0 else 0,
            'diseases': final_diseases,
            'total_diseases': len(final_diseases),
            'frames_analyzed': total_frames,
            'message': message
        }
        
        print(f"Kết quả cuối cùng: {len(final_diseases)} bệnh từ {total_frames} frames")
        return result
    

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
                self.disease_detection_enabled = True
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'message': 'Phát hiện bệnh đã bắt đầu'
                }))
                
            elif command == 'stop_detection':
                self.disease_detection_enabled = False
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'message': 'Đã dừng phát hiện bệnh'
                }))
            
            elif command == 'detect_once':
                if self.disease_detection_enabled:
                    # Phân tích video trong 5 giây để có kết quả chính xác hơn
                    loop = asyncio.get_event_loop()
                    detection_result = await loop.run_in_executor(
                        self.executor, 
                        self.detect_disease_multi_frame_sync
                    )
                    
                    if detection_result:
                        print(f"Manual detection result: {detection_result}") 
                        await self.send(text_data=json.dumps({
                            'type': 'disease_detection_result',
                            **detection_result
                        }))
                    else:
                        await self.send(text_data=json.dumps({
                            'type': 'error',
                            'message': 'Không thể lấy frames để phân tích'
                        }))
                else:
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'Phát hiện bệnh chưa được bật'
                    }))
            
            elif command == 'toggle_cat_detection':
                self.cat_detection_enabled = not self.cat_detection_enabled
                status = 'bật' if self.cat_detection_enabled else 'tắt'
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'message': f'Phát hiện mèo đã {status}'
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
    
    async def camera_status_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'camera_status',
            'data': event['camera_info']
        }))