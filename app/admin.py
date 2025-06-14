from django.contrib import admin
from .models import FeedingSchedule, FeedingLog, SystemSettings, DiseaseDetection


@admin.register(FeedingSchedule)
class FeedingScheduleAdmin(admin.ModelAdmin):
    list_display = ['user', 'time', 'enabled', 'created_at']
    list_filter = ['enabled', 'created_at']
    search_fields = ['user__username']


@admin.register(FeedingLog)
class FeedingLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'timestamp', 'mode', 'device_id']
    list_filter = ['mode', 'timestamp']
    search_fields = ['user__username', 'device_id']
    readonly_fields = ['timestamp']


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = ['user', 'current_mode', 'mqtt_broker', 'mqtt_port', 'updated_at']
    list_filter = ['current_mode']
    search_fields = ['user__username']


@admin.register(DiseaseDetection)
class DiseaseDetectionAdmin(admin.ModelAdmin):
    list_display = ['user', 'timestamp', 'disease_name', 'confidence']
    list_filter = ['disease_name', 'timestamp']
    search_fields = ['user__username', 'disease_name']
    readonly_fields = ['timestamp']