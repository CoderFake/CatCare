from django.urls import path
from . import views

app_name = 'app'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('settings/', views.settings_view, name='settings'),
    path('feeding-history/', views.feeding_history, name='feeding_history'),
    path('disease-history/', views.disease_history, name='disease_history'),
    
    path('api/feed/', views.manual_feed, name='manual_feed'),
    path('api/mode/', views.change_mode, name='change_mode'),
    path('api/status/', views.get_status, name='get_status'),
    path('api/detect/', views.detect_disease, name='detect_disease'),
    path('api/feeding-data/', views.get_feeding_data, name='get_feeding_data'),
    path('api/test-esp32/', views.test_esp32_stream, name='test_esp32_stream'),
    
    path('video-feed/', views.video_feed, name='video_feed'),
]