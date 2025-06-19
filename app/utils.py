import cv2
import numpy as np
import os
from django.conf import settings
from .disease_detector import get_cat_care_detector, get_disease_detector


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
                print(f"Already executed this minute: {current_minute_key}")
                return False
                
            schedules = FeedingSchedule.objects.filter(
                user=user,
                enabled=True,
                time__hour=current_time.hour,
                time__minute=current_time.minute
            )
            
            all_schedules = FeedingSchedule.objects.filter(user=user, enabled=True)
            print(f"All enabled schedules: {[f'{s.time.hour:02d}:{s.time.minute:02d}' for s in all_schedules]}")
            print(f"Matching schedules: {schedules.count()}")
            
            if schedules.exists():
                print(f"Schedule matched! Sending feed command...")
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
                    
                    print(f"Feed command sent successfully!")
                    return True
                else:
                    print(f"Failed to send MQTT command")
            else:
                print(f"No schedule match for {current_time.hour:02d}:{current_time.minute:02d}")
                    
        except SystemSettings.DoesNotExist:
            print(f"SystemSettings not found for user {user.username}")
        except Exception as e:
            print(f"Lỗi kiểm tra schedule: {e}")
            
        return False


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