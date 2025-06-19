# Models cho CatCare

## Cấu trúc models cần thiết:

### 1. cat.pt
- **Chức năng**: Detect mèo trong ảnh/video
- **Input**: Ảnh RGB
- **Output**: Bounding box của mèo với confidence score
- **Classes**: ['cat']

### 2. cat-detect.pt  
- **Chức năng**: Phát hiện bệnh trên mèo
- **Input**: Ảnh mèo đã được crop
- **Output**: Các loại bệnh với confidence score
- **Classes**: ['demodicosis', 'dermatitis', 'flea_allergy', 'fungus', 'ringworm', 'scabies']

## Workflow:

1. **Realtime stream**: Sử dụng `cat.pt` để detect và vẽ bounding box mèo
2. **Disease detection**: 
   - Dùng `cat.pt` để crop mèo từ frame
   - Dùng `cat-detect.pt` để phát hiện bệnh trên ảnh mèo đã crop

## Yêu cầu models:

- Format: PyTorch .pt files
- Framework: YOLO (ultralytics)
- Input size: 640x640 (recommended)
- Confidence threshold: 0.5 (default)

## Hướng dẫn thêm models:

1. Đặt file `cat.pt` và `cat-detect.pt` vào thư mục này
2. Đảm bảo models tương thích với ultralytics YOLO
3. Test models bằng script test riêng trước khi integrate

## Models hiện tại:

- `cat-detect.pt` - Disease detection model
- `cat.pt` - Cat detection model (cần thêm)
- `cat.yaml` - Training config for cat detection 