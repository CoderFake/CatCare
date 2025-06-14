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
            
        try:
            model_path = os.path.join(settings.BASE_DIR, 'static', 'model', 'cat.pt')
            if os.path.exists(model_path):
                self.model = YOLO(model_path)
                print("Model YOLO đã được tải thành công")
            else:
                print(f"Không tìm thấy model tại: {model_path}")
        except Exception as e:
            print(f"Lỗi tải model: {e}")
    
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
                return False
                
            current_time = timezone.now().time()
            schedules = FeedingSchedule.objects.filter(
                user=user,
                enabled=True,
                time__hour=current_time.hour,
                time__minute=current_time.minute
            )
            
            if schedules.exists():
                mqtt_manager = get_mqtt_manager()
                if mqtt_manager.publish_feed_command('auto'):
                    return True
                    
        except SystemSettings.DoesNotExist:
            pass
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


def create_blank_frame():
    """
    Tạo frame trống khi không có camera
    """
    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(blank_frame, 'Watting for camera...', (150, 240), 
               cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    _, buffer = cv2.imencode('.jpg', blank_frame)
    return buffer.tobytes()