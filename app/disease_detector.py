import cv2
import numpy as np
import os

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


class ModelLoader:
    """Class để load YOLO models với các method khác nhau"""
    
    @staticmethod
    def load_model(model_path):
        """Load YOLO model với nhiều method fallback"""
        if not YOLO_AVAILABLE:
            raise Exception("YOLO không khả dụng. Cần cài đặt ultralytics")
            
        if not os.path.exists(model_path):
            raise Exception(f"Không tìm thấy model tại: {model_path}")
        
        load_methods = [
            ModelLoader._load_with_safe_globals,
            ModelLoader._load_with_weights_only_false,
            ModelLoader._load_basic
        ]
        
        for i, method in enumerate(load_methods):
            try:
                model = method(model_path)
                print(f"Model loaded successfully (method {i+1}): {os.path.basename(model_path)}")
                return model
            except Exception as e:
                print(f"Load method {i+1} failed: {e}")
                continue
        
        raise Exception("Không thể load model với bất kỳ method nào")
    
    @staticmethod
    def _load_with_safe_globals(model_path):
        """Load với safe globals cho PyTorch 2.6+"""
        import torch
        torch.serialization.add_safe_globals([
            'ultralytics.nn.tasks.DetectionModel',
            'ultralytics.nn.modules.block.C3k2',
            'ultralytics.nn.modules.conv.Conv',
            'ultralytics.nn.modules.head.Detect'
        ])
        return YOLO(model_path)
    
    @staticmethod
    def _load_with_weights_only_false(model_path):
        """Load với weights_only=False"""
        import torch
        original_load = torch.load
        torch.load = lambda *args, **kwargs: original_load(*args, **kwargs, weights_only=False)
        try:
            model = YOLO(model_path)
            return model
        finally:
            torch.load = original_load
    
    @staticmethod
    def _load_basic(model_path):
        """Load cơ bản"""
        return YOLO(model_path)


class CatDetector:
    """Class để detect mèo trong ảnh"""
    
    def __init__(self):
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load cat detection model"""
        try:
            from django.conf import settings
            model_path = os.path.join(settings.BASE_DIR, 'static', 'model', 'cat.pt')
            self.model = ModelLoader.load_model(model_path)
        except Exception as e:
            print(f"Không thể load cat model: {e}")
            self.model = None
    
    def detect_cats(self, frame, confidence_threshold=0.5):
        """
        Detect mèo trong frame
        Returns: List of cat bounding boxes [x1, y1, x2, y2, confidence]
        """
        if not self.model:
            return []
        
        try:
            results = self.model(frame)
            cats = []
            
            for result in results:
                if result.boxes is not None:
                    for box in result.boxes:
                        conf = float(box.conf[0])
                        if conf >= confidence_threshold:
                            # Get bounding box coordinates
                            x1, y1, x2, y2 = box.xyxy[0].tolist()
                            cats.append({
                                'bbox': [int(x1), int(y1), int(x2), int(y2)],
                                'confidence': conf
                            })
            
            return cats
            
        except Exception as e:
            print(f"Lỗi detect mèo: {e}")
            return []
    
    def crop_cat_from_frame(self, frame, confidence_threshold=0.5):
        """
        Crop ảnh mèo từ frame (lấy mèo có confidence cao nhất)
        Returns: cropped_image hoặc None
        """
        cats = self.detect_cats(frame, confidence_threshold)
        
        if not cats:
            return None
        
        # Lấy mèo có confidence cao nhất
        best_cat = max(cats, key=lambda x: x['confidence'])
        x1, y1, x2, y2 = best_cat['bbox']
        
        # Crop ảnh
        cropped = frame[y1:y2, x1:x2]
        
        if cropped.size == 0:
            return None
            
        return cropped
    
    def draw_cat_boxes(self, frame, confidence_threshold=0.5):
        """
        Vẽ bounding box của mèo lên frame
        Returns: frame with bounding boxes
        """
        cats = self.detect_cats(frame, confidence_threshold)
        
        for cat in cats:
            x1, y1, x2, y2 = cat['bbox']
            confidence = cat['confidence']
            
            # Vẽ bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            # Vẽ label
            label = f"Cat: {confidence:.2f}"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)[0]
            cv2.rectangle(frame, (x1, y1 - label_size[1] - 10), 
                         (x1 + label_size[0], y1), (0, 255, 0), -1)
            cv2.putText(frame, label, (x1, y1 - 5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
        
        return frame
    
    def is_available(self):
        return self.model is not None


class DiseaseDetector:
    """Class để detect bệnh trên mèo"""
    
    def __init__(self):
        self.model = None
        self.class_names = {
            'demodicosis': 'Ghẻ demodex',
            'dermatitis': 'Viêm da', 
            'flea_allergy': 'Dị ứng bọ chét',
            'fungus': 'Nấm da',
            'ringworm': 'Nấm tròn',
            'scabies': 'Ghẻ sarcoptic',
            # Mapping cho các class_id từ model
            'class_0': 'Ghẻ demodex',
            'class_1': 'Viêm da',
            'class_2': 'Dị ứng bọ chét', 
            'class_3': 'Nấm da',
            'class_4': 'Nấm tròn',
            'class_5': 'Ghẻ sarcoptic'
        }
        self._load_model()
    
    def _load_model(self):
        """Load disease detection model"""
        try:
            from django.conf import settings
            model_path = os.path.join(settings.BASE_DIR, 'static', 'model', 'cat-detect.pt')
            self.model = ModelLoader.load_model(model_path)
        except Exception as e:
            print(f"Không thể load disease model: {e}")
            self.model = None
    
    def detect_diseases(self, image, confidence_threshold=0.5):
        """
        Detect bệnh trong ảnh
        Args:
            image: numpy array (OpenCV image) hoặc bytes
            confidence_threshold: ngưỡng confidence
        Returns: dict với thông tin bệnh
        """
        if not self.model:
            return {
                'success': False,
                'message': 'Disease model không khả dụng'
            }
        
        try:
            # Xử lý input image
            if isinstance(image, bytes):
                nparr = np.frombuffer(image, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            else:
                img = image
                
            if img is None:
                return {
                    'success': False,
                    'message': 'Không thể decode ảnh'
                }
            
            results = self.model(img)
            diseases = []
            
            for result in results:
                if result.boxes is not None:
                    for box in result.boxes:
                        cls_id = int(box.cls[0])
                        conf = float(box.conf[0])
                        
                        if conf >= confidence_threshold:
                            # Get class name
                            if hasattr(result, 'names') and cls_id in result.names:
                                disease_en = result.names[cls_id]
                            else:
                                disease_en = list(self.class_names.keys())[cls_id] if cls_id < len(self.class_names) else 'unknown'
                            
                            disease_vn = self.class_names.get(disease_en, disease_en)
                            bbox = box.xyxy[0].tolist()
                            
                            disease_data = {
                                'disease_en': disease_en,
                                'disease_vn': disease_vn,
                                'confidence': conf * 100,
                                'bbox': bbox
                            }
                            diseases.append(disease_data)
            
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
    
    def detect_diseases_and_save(self, image_data, user, confidence_threshold=0.5):
        """
        Detect bệnh và lưu vào database
        """
        result = self.detect_diseases(image_data, confidence_threshold)
        
        if result['success']:
            try:
                from .models import DiseaseDetection
                for disease_data in result['diseases']:
                    DiseaseDetection.objects.create(
                        user=user,
                        disease_name=disease_data['disease_en'],
                        confidence=disease_data['confidence'] / 100,
                        bbox_x1=disease_data['bbox'][0],
                        bbox_y1=disease_data['bbox'][1], 
                        bbox_x2=disease_data['bbox'][2],
                        bbox_y2=disease_data['bbox'][3]
                    )
            except Exception as e:
                print(f"Lỗi lưu database: {e}")
        
        return result
    
    def is_available(self):
        return self.model is not None


class CatCareDetector:
    """Main class kết hợp cat detection và disease detection"""
    
    def __init__(self):
        self.cat_detector = CatDetector()
        self.disease_detector = DiseaseDetector()
    
    def detect_cat_realtime(self, frame, confidence_threshold=0.5):
        """
        Detect mèo và vẽ bounding box cho realtime stream
        """
        if not self.cat_detector.is_available():
            return frame, []
        
        cats = self.cat_detector.detect_cats(frame, confidence_threshold)
        annotated_frame = self.cat_detector.draw_cat_boxes(frame.copy(), confidence_threshold)
        
        return annotated_frame, cats
    
    def detect_diseases_on_frame(self, frame, user, confidence_threshold=0.5):
        """
        Phát hiện bệnh trên frame:
        1. Detect mèo từ frame (lấy confidence thực tế)
        2. Crop mèo từ frame
        3. Detect bệnh trên ảnh mèo đã crop
        """
        if not self.cat_detector.is_available() or not self.disease_detector.is_available():
            return {
                'success': False,
                'message': 'Models không khả dụng'
            }
        
        cats = self.cat_detector.detect_cats(frame, confidence_threshold)
        
        if not cats:
            return {
                'success': False,
                'message': 'Không phát hiện mèo trong ảnh'
            }
        
        best_cat = max(cats, key=lambda x: x['confidence'])
        cat_confidence = best_cat['confidence']
        
        x1, y1, x2, y2 = best_cat['bbox']
        cat_image = frame[y1:y2, x1:x2]
        
        if cat_image.size == 0:
            return {
                'success': False,
                'message': 'Không thể crop ảnh mèo',
                'cat_detected': True,
                'cat_confidence': cat_confidence * 100
            }
        
        disease_result = self.disease_detector.detect_diseases_and_save(
            cat_image, user, confidence_threshold
        )
        
        if disease_result['success']:
            disease_result['cat_detected'] = True
            disease_result['cat_cropped'] = True
            disease_result['cat_confidence'] = cat_confidence * 100
        else:
            disease_result['cat_detected'] = True
            disease_result['cat_cropped'] = False
            disease_result['cat_confidence'] = cat_confidence * 100
        
        return disease_result
    
    def is_available(self):
        """Kiểm tra cả 2 models có sẵn không"""
        return self.cat_detector.is_available() and self.disease_detector.is_available()


# Singleton instances
_cat_care_detector = None
_cat_detector = None
_disease_detector = None

def get_cat_care_detector():
    """Singleton pattern cho main detector"""
    global _cat_care_detector
    if _cat_care_detector is None:
        _cat_care_detector = CatCareDetector()
    return _cat_care_detector

def get_cat_detector():
    """Singleton pattern cho cat detector"""
    global _cat_detector
    if _cat_detector is None:
        _cat_detector = CatDetector()
    return _cat_detector

def get_disease_detector():
    """Singleton pattern cho disease detector"""
    global _disease_detector
    if _disease_detector is None:
        _disease_detector = DiseaseDetector()
    return _disease_detector 