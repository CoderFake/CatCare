from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/video_stream/$', consumers.VideoStreamConsumer.as_asgi()),
    re_path(r'ws/system_status/$', consumers.SystemStatusConsumer.as_asgi()),
] 