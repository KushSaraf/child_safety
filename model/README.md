# YOLOv8 Child Detection Model

This directory contains the YOLOv8 model training and inference code for child detection in the hackathon system.

## Dataset

- **Total Images**: 71 (52 train, 11 valid, 8 test)
- **Class**: 1 (Rahul - child)
- **Format**: YOLOv8 format with bounding box annotations
- **Source**: Roboflow dataset (CC BY 4.0 license)

## Files

- `data/` - Dataset directory with train/valid/test splits
- `data/data.yaml` - Dataset configuration file
- `train_yolo.py` - Training script
- `inference.py` - Inference script for images/videos
- `cctv_simulation.py` - CCTV simulation with real detection
- `requirements.txt` - Python dependencies
- `67629-523386662.mp4` - Sample video for testing

## Setup

1. **Install dependencies**:
   ```bash
   cd model
   pip install -r requirements.txt
   ```

2. **Train the model**:
   ```bash
   python train_yolo.py
   ```
   
   This will:
   - Train YOLOv8n (nano) model for 100 epochs
   - Save best model to `runs/train/child_detection/weights/best.pt`
   - Export to ONNX and TorchScript formats
   - Generate training plots and metrics

3. **Run inference on images**:
   ```bash
   python inference.py --model runs/train/child_detection/weights/best.pt --source path/to/image.jpg --output result.jpg
   ```

4. **Run inference on videos**:
   ```bash
   python inference.py --model runs/train/child_detection/weights/best.pt --source path/to/video.mp4 --output result.mp4
   ```

5. **Run CCTV simulation**:
   ```bash
   # With specific incident ID
   python cctv_simulation.py --model runs/train/child_detection/weights/best.pt --incident-id <incident-id>
   
   # With custom video
   python cctv_simulation.py --model runs/train/child_detection/weights/best.pt --video path/to/video.mp4 --incident-id <incident-id>
   ```

## Integration with Hackathon System

The trained model integrates with the hackathon system in two ways:

1. **CCTV Simulation**: The `cctv_simulation.py` script processes video frames and sends real detection results to the backend when a child is found.

2. **Backend Integration**: The backend can trigger CCTV simulation which uses the trained model to detect children in video footage.

## Model Performance

After training, the model will provide:
- **mAP50**: Mean Average Precision at IoU 0.5
- **mAP50-95**: Mean Average Precision at IoU 0.5-0.95
- **Confidence scores** for each detection

## Customization

- **Model size**: Change `yolov8n.pt` to `yolov8s.pt`, `yolov8m.pt`, `yolov8l.pt`, or `yolov8x.pt` for different speed/accuracy tradeoffs
- **Training epochs**: Modify `epochs=100` in `train_yolo.py`
- **Confidence threshold**: Adjust `conf_threshold` parameter in inference scripts
- **Image size**: Change `imgsz=640` for different input resolutions

## Troubleshooting

- **CUDA out of memory**: Reduce `batch` size in training script
- **No detections**: Lower `conf_threshold` or check if model is properly trained
- **Slow inference**: Use smaller model variant (yolov8n.pt) or reduce image size
- **Video processing**: Ensure OpenCV can read the video format

## Demo Flow

1. Train the model: `python train_yolo.py`
2. Start the hackathon backend: `python ../backend/main.py`
3. Create an incident via Flutter app or dashboard
4. Run CCTV simulation: `python cctv_simulation.py --model runs/train/child_detection/weights/best.pt`
5. Watch the dashboard for CCTV match updates
