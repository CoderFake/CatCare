from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from app.utils import ScheduleManager
import time


class Command(BaseCommand):
    help = 'Kiểm tra và thực hiện lịch cho ăn tự động'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=60,
            help='Khoảng thời gian kiểm tra (giây), mặc định 60 giây'
        )
    
    def handle(self, *args, **options):
        interval = options['interval']
        self.stdout.write(
            self.style.SUCCESS(f'Bắt đầu kiểm tra lịch cho ăn mỗi {interval} giây...')
        )
        
        try:
            while True:
                users = User.objects.all()
                for user in users:
                    try:
                        if ScheduleManager.check_schedules(user):
                            self.stdout.write(
                                self.style.SUCCESS(f'Đã thực hiện cho ăn tự động cho user: {user.username}')
                            )
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'Lỗi kiểm tra lịch cho user {user.username}: {e}')
                        )
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS('Dừng schedule checker'))