import cv2
import numpy as np
import os
from django.conf import settings
from .models import DiseaseDetection
from django.contrib.auth.models import User

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


class DiseaseDetector:
    """
    Phát hiện bệnh trên mèo sử dụng YOLO
    """
    
    def __init__(self):
        self.model = None
        self.class_names = ['demodicosis', 'dermatitis', 'flea_allergy', 'fungus', 'ringworm', 'scabies']
        self._load_model()
    
    def _load_model(self):
        if not YOLO_AVAILABLE:
            print("YOLO không khả dụng. Cần cài đặt ultralytics")
            return
            
        model_path = os.path.join(settings.BASE_DIR, 'static', 'model', 'cat.pt')
        if not os.path.exists(model_path):
            print(f"Không tìm thấy model tại: {model_path}")
            return
            
        load_methods = [
            self._load_with_safe_globals,
            self._load_with_weights_only_false,
            self._load_basic
        ]
        
        for i, method in enumerate(load_methods):
            try:
                self.model = method(model_path)
                print(f"Model YOLO đã được tải thành công (method {i+1})")
                return
            except Exception as e:
                print(f"Method {i+1} failed: {e}")
                continue
        
        print("Không thể load model với bất kỳ method nào")
    
    def _load_with_safe_globals(self, model_path):
        """Load với safe globals cho PyTorch 2.6+"""
        import torch
        torch.serialization.add_safe_globals([
            'ultralytics.nn.tasks.DetectionModel',
            'ultralytics.nn.modules.block.C3k2',
            'ultralytics.nn.modules.conv.Conv',
            'ultralytics.nn.modules.head.Detect'
        ])
        return YOLO(model_path)
    
    def _load_with_weights_only_false(self, model_path):
        """Load với weights_only=False"""
        import torch
        original_load = torch.load
        torch.load = lambda *args, **kwargs: original_load(*args, **kwargs, weights_only=False)
        try:
            model = YOLO(model_path)
            return model
        finally:
            torch.load = original_load
    
    def _load_basic(self, model_path):
        """Load cơ bản"""
        return YOLO(model_path)
    
    def detect_diseases(self, image_data, user, confidence_threshold=0.5):
        """
        Phát hiện bệnh từ dữ liệu ảnh
        """
        if not self.model:
            return {
                'success': False,
                'message': 'Model không khả dụng'
            }
        
        try:
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                return {
                    'success': False,
                    'message': 'Không thể decode ảnh'
                }
            
            results = self.model(img)
            diseases = []
            
            for r in results:
                boxes = r.boxes
                if boxes is not None:
                    for box in boxes:
                        cls = int(box.cls[0])
                        conf = float(box.conf[0])
                        
                        if conf > confidence_threshold:
                            disease_name = self.class_names[cls] if cls < len(self.class_names) else 'unknown'
                            bbox = box.xyxy[0].tolist()
                            
                            disease_data = {
                                'disease': disease_name,
                                'confidence': conf * 100,
                                'bbox': bbox
                            }
                            diseases.append(disease_data)
                            
                            DiseaseDetection.objects.create(
                                user=user,
                                disease_name=disease_name,
                                confidence=conf,
                                bbox_x1=bbox[0],
                                bbox_y1=bbox[1], 
                                bbox_x2=bbox[2],
                                bbox_y2=bbox[3]
                            )
            
            return {
                'success': True,
                'diseases': diseases,
                'total_detections': len(diseases)
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Lỗi phân tích: {str(e)}'
            }
    
    def is_available(self):
        return self.model is not None


class ScheduleManager:
    """
    Quản lý lịch cho ăn tự động
    """
    
    _executed_schedules = set()
    
    @staticmethod
    def check_schedules(user):
        """
        Kiểm tra và thực hiện lịch cho ăn
        """
        from .models import FeedingSchedule, SystemSettings
        from .mqtt_client import get_mqtt_manager
        from django.utils import timezone
        
        try:
            settings = SystemSettings.objects.get(user=user)
            if settings.current_mode != 'auto':
                print(f"User {user.username} not in auto mode: {settings.current_mode}")
                return False
                
            current_time = timezone.now().time()
            current_datetime = timezone.now()
            current_minute_key = f"{user.id}_{current_time.hour}_{current_time.minute}"
            
            print(f"Checking schedules for {user.username}")
            print(f"Current datetime: {current_datetime}")
            print(f"Current time: {current_time.hour:02d}:{current_time.minute:02d}")
            print(f"Timezone: {timezone.get_current_timezone()}")
            
            if current_minute_key in ScheduleManager._executed_schedules:
                print(f"   Already executed this minute: {current_minute_key}")
                return False
                
            schedules = FeedingSchedule.objects.filter(
                user=user,
                enabled=True,
                time__hour=current_time.hour,
                time__minute=current_time.minute
            )
            
            all_schedules = FeedingSchedule.objects.filter(user=user, enabled=True)
            print(f"   All enabled schedules: {[f'{s.time.hour:02d}:{s.time.minute:02d}' for s in all_schedules]}")
            print(f"   Matching schedules: {schedules.count()}")
            
            if schedules.exists():
                print(f"   🎯 Schedule matched! Sending feed command...")
                mqtt_manager = get_mqtt_manager()
                if mqtt_manager.publish_feed_command('auto'):
                    ScheduleManager._executed_schedules.add(current_minute_key)
                    
                    current_total_minutes = current_time.hour * 60 + current_time.minute
                    to_remove = []
                    for key in ScheduleManager._executed_schedules:
                        parts = key.split('_')
                        if len(parts) == 3:
                            key_total_minutes = int(parts[1]) * 60 + int(parts[2])
                            if abs(current_total_minutes - key_total_minutes) > 2:
                                to_remove.append(key)
                    
                    for key in to_remove:
                        ScheduleManager._executed_schedules.discard(key)
                    
                    print(f"   ✅ Feed command sent successfully!")
                    return True
                else:
                    print(f"   ❌ Failed to send MQTT command")
            else:
                print(f"   No schedule match for {current_time.hour:02d}:{current_time.minute:02d}")
                    
        except SystemSettings.DoesNotExist:
            print(f"SystemSettings not found for user {user.username}")
        except Exception as e:
            print(f"Lỗi kiểm tra schedule: {e}")
            
        return False


def get_disease_detector():
    """
    Singleton pattern cho disease detector
    """
    if not hasattr(get_disease_detector, '_instance'):
        get_disease_detector._instance = DiseaseDetector()
    return get_disease_detector._instance


def create_blank_frame(message="Waiting for camera..."):
    """
    Tạo frame trống khi không có camera
    """
    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.8
    thickness = 2
    
    lines = []
    if len(message) > 30:
        words = message.split(' ')
        current_line = ""
        for word in words:
            if len(current_line + word) < 30:
                current_line += word + " "
            else:
                lines.append(current_line.strip())
                current_line = word + " "
        if current_line:
            lines.append(current_line.strip())
    else:
        lines = [message]
    
    y_start = 220
    for i, line in enumerate(lines):
        text_size = cv2.getTextSize(line, font, font_scale, thickness)[0]
        x = (640 - text_size[0]) // 2
        y = y_start + (i * 40)
        cv2.putText(blank_frame, line, (x, y), font, font_scale, (255, 255, 255), thickness)
    
    _, buffer = cv2.imencode('.jpg', blank_frame)
    return buffer.tobytes()