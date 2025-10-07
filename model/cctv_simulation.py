#!/usr/bin/env python3
"""
CCTV Simulation with YOLOv8 Child Detection
Simulates CCTV footage processing with real child detection
"""

import os
import sys
import time
import threading
import requests # type: ignore
import cv2 # type: ignore
import numpy as np # type: ignore
from pathlib import Path
from ultralytics import YOLO # type: ignore
import argparse

class CCTVSIMULATOR:
    def __init__(self, model_path, backend_url="http://localhost:8000"):
        self.model_path = model_path
        self.backend_url = backend_url
        self.model = None
        self.load_model()
    
    def load_model(self):
        """Load the trained YOLOv8 model"""
        try:
            self.model = YOLO(self.model_path)
            print(f"Model loaded successfully: {self.model_path}")
        except Exception as e:
            print(f"Error loading model: {e}")
            sys.exit(1)
    
    def process_video_frame(self, frame, conf_threshold=0.5):
        """Process a single video frame for child detection"""
        if self.model is None:
            return False, 0.0
        
        try:
            # Run inference
            results = self.model(frame, conf=conf_threshold, verbose=False)
            
            # Check for detections
            for result in results:
                boxes = result.boxes
                if boxes is not None and len(boxes) > 0:
                    # Get the highest confidence detection
                    max_conf = 0.0
                    for box in boxes:
                        conf = box.conf[0].cpu().numpy()
                        max_conf = max(max_conf, conf)
                    
                    return True, max_conf
            
            return False, 0.0
            
        except Exception as e:
            print(f"Error processing frame: {e}")
            return False, 0.0
    
    def simulate_cctv_processing(self, video_path, incident_id, delay_seconds=5, conf_threshold=0.5):
        """Simulate CCTV processing with real child detection"""
        def worker():
            print(f"Starting CCTV simulation for incident {incident_id}")
            print(f"Processing video: {video_path}")
            print(f"Delay: {delay_seconds} seconds")
            
            # Wait for initial delay
            time.sleep(delay_seconds)
            
            # Check if incident still exists and is open
            try:
                response = requests.get(f"{self.backend_url}/incidents", timeout=5)
                incidents = response.json()
                incident = next((inc for inc in incidents if inc['id'] == incident_id), None)
                
                if not incident or incident.get('status') != 'open':
                    print(f"Incident {incident_id} not found or already resolved")
                    return
            except Exception as e:
                print(f"Error checking incident status: {e}")
                return
            
            # Process video
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                print(f"Error: Could not open video {video_path}")
                return
            
            frame_count = 0
            detection_found = False
            max_confidence = 0.0
            
            print("Processing video frames...")
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Process every 10th frame for efficiency
                if frame_count % 10 == 0:
                    detected, confidence = self.process_video_frame(frame, conf_threshold)
                    if detected:
                        detection_found = True
                        max_confidence = max(max_confidence, confidence)
                        print(f"Child detected in frame {frame_count} with confidence {confidence:.3f}")
                
                frame_count += 1
                
                # Stop after processing enough frames or finding detection
                if frame_count > 100 or detection_found:
                    break
            
            cap.release()
            
            # Send CCTV match to backend
            if detection_found:
                try:
                    response = requests.post(
                        f"{self.backend_url}/incident/{incident_id}/cctv_match",
                        json={
                            "camera_id": "CAM_GATE_3",
                            "confidence": float(max_confidence),
                            "frame_ts": time.strftime("%Y-%m-%dT%H:%M:%S")
                        },
                        timeout=10
                    )
                    print(f"CCTV match posted: {response.status_code} - {response.text}")
                except Exception as e:
                    print(f"Error posting CCTV match: {e}")
            else:
                print("No child detected in video")
        
        # Start background thread
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread

def main():
    parser = argparse.ArgumentParser(description='CCTV Simulation with YOLOv8')
    parser.add_argument('--model', required=True, help='Path to trained YOLOv8 model (.pt file)')
    parser.add_argument('--video', help='Path to video file (default: use sample video)')
    parser.add_argument('--incident-id', help='Incident ID to simulate detection for')
    parser.add_argument('--backend', default='http://localhost:8000', help='Backend URL')
    parser.add_argument('--delay', type=int, default=5, help='Delay before processing (seconds)')
    parser.add_argument('--conf', type=float, default=0.5, help='Confidence threshold')
    
    args = parser.parse_args()
    
    # Check if model exists
    if not os.path.exists(args.model):
        print(f"Error: Model file {args.model} not found!")
        sys.exit(1)
    
    # Use sample video if not provided
    video_path = args.video
    if not video_path:
        video_path = Path(__file__).parent / "67629-523386662.mp4"
        if not video_path.exists():
            print(f"Error: Sample video {video_path} not found!")
            print("Please provide --video argument with path to video file")
            sys.exit(1)
    
    # Check if video exists
    if not os.path.exists(video_path):
        print(f"Error: Video file {video_path} not found!")
        sys.exit(1)
    
    # Create simulator
    simulator = CCTVSIMULATOR(args.model, args.backend)
    
    # Get incident ID
    incident_id = args.incident_id
    if not incident_id:
        # Try to get latest incident from backend
        try:
            response = requests.get(f"{args.backend}/incidents", timeout=5)
            incidents = response.json()
            if incidents:
                incident_id = incidents[0]['id']  # Get most recent incident
                print(f"Using latest incident ID: {incident_id}")
            else:
                print("No incidents found. Please provide --incident-id")
                sys.exit(1)
        except Exception as e:
            print(f"Error fetching incidents: {e}")
            print("Please provide --incident-id")
            sys.exit(1)
    
    # Start simulation
    print(f"Starting CCTV simulation...")
    print(f"Model: {args.model}")
    print(f"Video: {video_path}")
    print(f"Incident ID: {incident_id}")
    print(f"Backend: {args.backend}")
    print(f"Delay: {args.delay}s")
    print(f"Confidence threshold: {args.conf}")
    
    thread = simulator.simulate_cctv_processing(
        video_path, incident_id, args.delay, args.conf
    )
    
    print("CCTV simulation started. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting...")

if __name__ == "__main__":
    main()