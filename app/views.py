from django.shortcuts import render, redirect
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib import messages
from django.utils import timezone
from django.db import models
import json
import time
from .models import FeedingSchedule, FeedingLog, SystemSettings, DiseaseDetection
from .mqtt_client import get_mqtt_manager
from .utils import get_disease_detector, create_blank_frame


def login_view(request):
    """
    Trang đăng nhập
    """
    if request.user.is_authenticated:
        return redirect('app:dashboard')
        
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('app:dashboard')
        else:
            messages.error(request, 'Tên đăng nhập hoặc mật khẩu không đúng')
    
    return render(request, 'app/login.html')


def logout_view(request):
    """
    Đăng xuất
    """
    logout(request)
    return redirect('app:login')


@login_required
def dashboard(request):
    """
    Trang dashboard chính
    """
    mqtt_manager = get_mqtt_manager()
    
    try:
        system_settings = SystemSettings.objects.get(user=request.user)
    except SystemSettings.DoesNotExist:
        system_settings = SystemSettings.objects.create(user=request.user)
    
    today = timezone.now().date()

    today_logs = FeedingLog.objects.filter(
        user=request.user,
        timestamp__date=today
    )
    
    recent_logs = today_logs.order_by('-timestamp')[:10]
    
    schedules = FeedingSchedule.objects.filter(user=request.user, enabled=True)
    recent_diseases = DiseaseDetection.objects.filter(user=request.user)[:5]
    
    context = {
        'current_mode': system_settings.current_mode,
        'device_status': mqtt_manager.get_device_status(),
        'feed_logs': recent_logs,
        'feeding_schedules': schedules,
        'recent_diseases': recent_diseases,
        'is_device_connected': mqtt_manager.is_device_connected()
    }
    
    return render(request, 'app/dashboard.html', context)


@login_required
def settings_view(request):
    """
    Trang cài đặt
    """
    try:
        system_settings = SystemSettings.objects.get(user=request.user)
    except SystemSettings.DoesNotExist:
        system_settings = SystemSettings.objects.create(user=request.user)
    
    if request.method == 'POST':
        current_mode = request.POST.get('mode', 'manual')
        system_settings.current_mode = current_mode
        system_settings.save()
        
        FeedingSchedule.objects.filter(user=request.user).delete()
        
        schedule_times = request.POST.getlist('schedule_time')
        for time_str in schedule_times:
            if time_str:
                FeedingSchedule.objects.create(
                    user=request.user,
                    time=time_str,
                    enabled=True
                )
        
        mqtt_manager = get_mqtt_manager()
        mqtt_manager.publish_mode_change(current_mode)
        
        messages.success(request, 'Cài đặt đã được lưu thành công')
        return redirect('app:settings')
    
    schedules = FeedingSchedule.objects.filter(user=request.user)
    
    context = {
        'system_settings': system_settings,
        'feeding_schedules': schedules
    }
    
    return render(request, 'app/settings.html', context)


@login_required
@require_POST
def manual_feed(request):
    """
    Cho ăn thủ công - chỉ gửi lệnh, không tạo log ngay
    """
    mqtt_manager = get_mqtt_manager()
    
    if mqtt_manager.publish_feed_command('manual'):
        return JsonResponse({
            'success': True, 
            'message': 'Đã gửi lệnh cho ăn, đang chờ xác nhận từ thiết bị...'
        })
    else:
        return JsonResponse({
            'success': False, 
            'message': 'Không thể kết nối với thiết bị'
        })


@login_required
@require_POST
def change_mode(request):
    """
    Thay đổi chế độ hoạt động
    """
    try:
        data = json.loads(request.body)
        mode = data.get('mode', 'manual')
        
        if mode not in ['manual', 'auto']:
            return JsonResponse({
                'success': False, 
                'message': 'Chế độ không hợp lệ'
            })
        
        system_settings, created = SystemSettings.objects.get_or_create(
            user=request.user,
            defaults={'current_mode': mode}
        )
        
        if not created:
            system_settings.current_mode = mode
            system_settings.save()
        
        mqtt_manager = get_mqtt_manager()
        mqtt_manager.publish_mode_change(mode)
        
        return JsonResponse({
            'success': True, 
            'mode': mode
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False, 
            'message': 'Dữ liệu JSON không hợp lệ'
        })
    except Exception as e:
        return JsonResponse({
            'success': False, 
            'message': f'Lỗi: {str(e)}'
        })


@login_required
def video_feed(request):
    """
    Stream video từ ESP32 CAM HTTP stream với flip
    """
    def generate():
        import requests
        import cv2
        import numpy as np
        from django.conf import settings
        
        esp32_ip = settings.ESP32_IP
        stream_url = f"http://{esp32_ip}/stream"
        
        try:
            print(f"Connecting to ESP32 stream: {stream_url}")
            
            response = requests.get(stream_url, stream=True, timeout=10)
            response.raise_for_status()
            print(f"Connected successfully. Content-Type: {response.headers.get('content-type', 'unknown')}")
            
            buffer = b''
            frame_count = 0
            
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    buffer += chunk
                    
                    while True:
                        start = buffer.find(b'\xff\xd8')
                        if start == -1:
                            break
                            
                        end = buffer.find(b'\xff\xd9', start + 2)
                        if end == -1:
                            break
                            
                        jpeg_data = buffer[start:end+2]
                        buffer = buffer[end+2:]
                        
                        if len(jpeg_data) > 1000:  
                            nparr = np.frombuffer(jpeg_data, np.uint8)
                            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            
                            if img is not None:
                                camera_settings = getattr(settings, 'CAMERA_SETTINGS', {})
                                
                                if camera_settings.get('FLIP_HORIZONTAL', False):
                                    img = cv2.flip(img, 1)
                                
                                if camera_settings.get('FLIP_VERTICAL', False):
                                    img = cv2.flip(img, 0)
                                
                                if camera_settings.get('ROTATE_180', False):
                                    img = cv2.flip(img, -1)
                                
                                # Encode lại thành JPEG
                                ret, processed_jpeg = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                                
                                if ret:
                                    frame_count += 1
                                    if frame_count % 100 == 0:
                                        print(f"Processed {frame_count} frames")
                                    
                                    yield (b'--frame\r\n'
                                           b'Content-Type: image/jpeg\r\n\r\n' + 
                                           processed_jpeg.tobytes() + b'\r\n\r\n')
                            else:
                                # Nếu không decode được, dùng JPEG gốc
                                yield (b'--frame\r\n'
                                       b'Content-Type: image/jpeg\r\n\r\n' + 
                                       jpeg_data + b'\r\n\r\n')
                        
        except Exception as e:
            print(f"Stream error: {str(e)}")
            # Tạo blank frame khi có lỗi
            while True:
                blank_frame = create_blank_frame(f"Lỗi kết nối: {str(e)}")
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + blank_frame + b'\r\n\r\n')
                time.sleep(1)
    
    return StreamingHttpResponse(
        generate(), 
        content_type='multipart/x-mixed-replace; boundary=frame'
    )

def process_image_flip(image_data):
    """
    Xử lý flip image theo settings
    """
    try:
        import cv2
        import numpy as np
        from django.conf import settings
        
        camera_settings = getattr(settings, 'CAMERA_SETTINGS', {})
        
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return image_data
        
        if camera_settings.get('FLIP_HORIZONTAL', False):
            img = cv2.flip(img, 1) 
            
        if camera_settings.get('FLIP_VERTICAL', False):
            img = cv2.flip(img, 0) 
            
        if camera_settings.get('ROTATE_180', False):
            img = cv2.flip(img, -1)  
        
        _, buffer = cv2.imencode('.jpg', img)
        return buffer.tobytes()
        
    except Exception as e:
        print(f"Lỗi xử lý flip image: {e}")
        return image_data

def capture_frame_from_esp32():
    """
    Capture frame từ ESP32 RTSP
    """
    try:
        import cv2
        from django.conf import settings
        
        esp32_ip = settings.ESP32_IP
        rtsp_url = f"rtsp://{esp32_ip}:8554/mjpeg/1"
        
        print(f"Capturing frame from ESP32 RTSP: {rtsp_url}")
        
        cap = cv2.VideoCapture(rtsp_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_TIMEOUT, 5000)  
        
        for i in range(5):
            ret, frame = cap.read()
            if ret:
                camera_settings = getattr(settings, 'CAMERA_SETTINGS', {})
                
                if camera_settings.get('FLIP_HORIZONTAL', False):
                    frame = cv2.flip(frame, 1)
                    
                if camera_settings.get('FLIP_VERTICAL', False):
                    frame = cv2.flip(frame, 0)
                    
                if camera_settings.get('ROTATE_180', False):
                    frame = cv2.flip(frame, -1)
                
                cap.release()
                print("Successfully captured frame from RTSP with OpenCV")
                return frame
        
        cap.release()
        print("Failed to capture frame from RTSP")
        return None
        
    except Exception as e:
        print(f"Lỗi capture frame từ RTSP với OpenCV: {e}")
        return None


@login_required
def detect_disease(request):
    """
    Real-time disease detection
    """
    return JsonResponse({
        'success': True,
    'message': 'Real-time detection được xử lý qua WebSocket'
    })


@login_required
def get_status(request):
    """
    Lấy trạng thái hệ thống realtime
    """
    mqtt_manager = get_mqtt_manager()
    
    try:
        system_settings = SystemSettings.objects.get(user=request.user)
        current_mode = system_settings.current_mode
    except SystemSettings.DoesNotExist:
        current_mode = 'manual'
    
    today = timezone.now().date()
    today_logs_count = FeedingLog.objects.filter(
        user=request.user,
        timestamp__date=today
    ).count()
    
    return JsonResponse({
        'device_status': mqtt_manager.get_device_status(),
        'current_mode': current_mode,
        'feed_logs_count': today_logs_count,
        'is_connected': mqtt_manager.is_device_connected(),
        'timestamp': timezone.now().isoformat()
    })


@login_required
def feeding_history(request):
    """
    Lịch sử cho ăn với filter và pagination
    """
    from datetime import date, timedelta
    from django.core.paginator import Paginator
    from django.http import HttpResponse
    import csv
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    mode_filter = request.GET.get('mode')
    export_excel = request.GET.get('export')
    
    if not start_date:
        start_date = (date.today() - timedelta(days=6)).strftime('%Y-%m-%d')
    if not end_date:
        end_date = date.today().strftime('%Y-%m-%d')
    
    logs = FeedingLog.objects.filter(user=request.user)
    
    if start_date:
        logs = logs.filter(timestamp__date__gte=start_date)
    if end_date:
        logs = logs.filter(timestamp__date__lte=end_date)
    
    if mode_filter:
        logs = logs.filter(mode=mode_filter)
    
    logs = logs.order_by('-timestamp')
    
    total_feeds = logs.count()
    auto_feeds = logs.filter(mode='auto').count()
    manual_feeds = logs.filter(mode='manual').count()
    
    if total_feeds > 0:
        date_range = logs.aggregate(
            min_date=models.Min('timestamp__date'),
            max_date=models.Max('timestamp__date')
        )
        if date_range['min_date'] and date_range['max_date']:
            days_count = (date_range['max_date'] - date_range['min_date']).days + 1
        else:
            days_count = 1
    else:
        days_count = 0
    
    if export_excel == 'excel':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="lich_su_cho_an_{start_date}_to_{end_date}.csv"'
        response.write('\ufeff') 
        
        writer = csv.writer(response)
        writer.writerow(['STT', 'Ngày giờ', 'Chế độ', 'Trạng thái'])
        
        for i, log in enumerate(logs, 1):
            writer.writerow([
                i,
                log.timestamp.strftime('%d/%m/%Y %H:%M:%S'),
                'Tự động' if log.mode == 'auto' else 'Thủ công',
                'Thành công'
            ])
        
        return response
    
    paginator = Paginator(logs, 20) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'logs': page_obj,
        'start_date': start_date,
        'end_date': end_date,
        'selected_mode': mode_filter,
        'total_feeds': total_feeds,
        'auto_feeds': auto_feeds,
        'manual_feeds': manual_feeds,
        'days_count': days_count,
    }
    
    return render(request, 'app/feeding_history.html', context)


@login_required
def disease_history(request):
    """
    Lịch sử phát hiện bệnh
    """
    detections = DiseaseDetection.objects.filter(user=request.user)
    
    context = {
        'detections': detections
    }
    
    return render(request, 'app/disease_history.html', context)


@login_required
def get_feeding_data(request):
    from datetime import date
    
    today = date.today()
    today_feed_count = FeedingLog.objects.filter(
        user=request.user,
        timestamp__date=today
    ).count()
    
    recent_feeds = FeedingLog.objects.filter(
        user=request.user,
        timestamp__date=today
    ).order_by('-timestamp')[:10]
    
    feeds_data = []
    for feed in recent_feeds:
        feeds_data.append({
            'id': feed.id,
            'mode': feed.mode,
            'timestamp': feed.timestamp.isoformat(),
        })
    
    return JsonResponse({
        'success': True,
        'today_feed_count': today_feed_count,
        'recent_feeds': feeds_data,
        'timestamp': timezone.now().isoformat()
    })
