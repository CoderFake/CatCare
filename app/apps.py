from django.apps import AppConfig
import threading
import time
import os


class AppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'
    
    def ready(self):
        print(f"[APPS] Django ready() called, RUN_MAIN={os.environ.get('RUN_MAIN')}")
        
        if os.environ.get('RUN_MAIN') == 'false':
            print("[APPS] Skipping initialization due to RUN_MAIN=false")
            return
            
        print("[APPS] Initializing MQTT client...")
        from . import mqtt_client
        try:
            mqtt_client.init_mqtt()
            print("[APPS] ✅ MQTT client initialized successfully")
        except Exception as e:
            print(f"[APPS] ❌ MQTT initialization failed: {e}")
        
        print("[APPS] Starting schedule checker thread...")
        from .utils import ScheduleManager
        from django.contrib.auth.models import User
        
        def schedule_checker_thread():
            """Background thread để kiểm tra feeding schedules"""
            print("🕒 Schedule checker started")
            
            while True:
                try:
                    users = User.objects.all()
                    for user in users:
                        try:
                            if ScheduleManager.check_schedules(user):
                                print(f"Đã thực hiện cho ăn tự động cho user: {user.username}")
                        except Exception as e:
                            print(f"Lỗi kiểm tra lịch cho user {user.username}: {e}")
                    
                    time.sleep(60) 
                    
                except Exception as e:
                    print(f"Lỗi schedule checker: {e}")
                    time.sleep(60)
        
        scheduler_thread = threading.Thread(target=schedule_checker_thread, daemon=True)
        scheduler_thread.start()
        print("[APPS] ✅ All initialization completed")