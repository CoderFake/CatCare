import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CatCare.settings')
django.setup()

from django.contrib.auth.models import User
from app.models import SystemSettings

def create_superuser():
    """
    Tạo superuser mặc định
    """
    username = os.getenv('SUPERUSER_USERNAME')
    email = os.getenv('SUPERUSER_EMAIL')
    password = os.getenv('SUPERUSER_PASSWORD')
    
    if not User.objects.filter(username=username).exists():
        user = User.objects.create_superuser(username, email, password)
        print(f'Đã tạo superuser: {username}')
        
        SystemSettings.objects.get_or_create(
            user=user,
            defaults={
                'current_mode': 'manual',
                'mqtt_broker': 'broker.emqx.io',
                'mqtt_port': 1883
            }
        )
        print('Đã tạo cài đặt hệ thống mặc định')
        
    else:
        print(f'Superuser {username} đã tồn tại')

if __name__ == '__main__':
    create_superuser()