from django.db import models
from django.contrib.auth.models import User


class FeedingSchedule(models.Model):
    """
    Lịch cho ăn tự động
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    time = models.TimeField(verbose_name="Thời gian")
    enabled = models.BooleanField(default=True, verbose_name="Kích hoạt")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Lịch cho ăn"
        verbose_name_plural = "Lịch cho ăn"
        ordering = ['time']


class FeedingLog(models.Model):
    """
    Lịch sử cho ăn
    """
    MODE_CHOICES = [
        ('manual', 'Thủ công'),
        ('auto', 'Tự động'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES)
    device_id = models.CharField(max_length=50, default="esp32_cam")
    
    class Meta:
        verbose_name = "Lịch sử cho ăn"
        verbose_name_plural = "Lịch sử cho ăn"
        ordering = ['-timestamp']


class SystemSettings(models.Model):
    """
    Cài đặt hệ thống
    """
    MODE_CHOICES = [
        ('manual', 'Thủ công'),
        ('auto', 'Tự động'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    current_mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='manual')
    mqtt_broker = models.CharField(max_length=100, default="broker.emqx.io")
    mqtt_port = models.IntegerField(default=1883)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Cài đặt hệ thống"
        verbose_name_plural = "Cài đặt hệ thống"


class DiseaseDetection(models.Model):
    """
    Kết quả phát hiện bệnh
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    disease_name = models.CharField(max_length=50)
    confidence = models.FloatField()
    bbox_x1 = models.FloatField()
    bbox_y1 = models.FloatField()
    bbox_x2 = models.FloatField()
    bbox_y2 = models.FloatField()
    
    class Meta:
        verbose_name = "Phát hiện bệnh"
        verbose_name_plural = "Phát hiện bệnh"
        ordering = ['-timestamp']