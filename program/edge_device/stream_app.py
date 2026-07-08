import os
import time
import threading
import cv2
import numpy as np
import websocket
from flask import Flask, render_template, request, jsonify
from loguru import logger

app = Flask(__name__)

# Global streaming state
streaming_active = False
stream_mode = "mock"       # "mock" or "camera" or "video"
video_path = ""
ws_url = "ws://10.217.55.162:8000/ws/stream/cam_01"
fps_target = 10.0

# Mock traffic simulation state
class MockTrafficSimulation:
    def __init__(self):
        self.frame_index = 0
        self.vehicles = [
            {"id": 1, "x": 300, "y": 100, "speed": 5, "type": "car", "plate": "粤B88888"},
            {"id": 2, "x": 700, "y": -100, "speed": 8, "type": "truck", "plate": "京A66666"},
            {"id": 3, "x": 180, "y": 300, "speed": 0, "type": "car", "plate": "沪C12345", "stop_start": None} # Stopped for violation
        ]
        self.anomaly = {"x": 550, "y": 450, "w": 40, "h": 40, "type": "box", "detected": False}

    def generate_frame(self):
        self.frame_index += 1
        
        # BGR Canvas (1280x720)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        
        # Draw background (gray asphalt road)
        cv2.rectangle(frame, (100, 0), (1180, 720), (60, 60, 60), -1)
        
        # Draw green grass on sides
        cv2.rectangle(frame, (0, 0), (100, 720), (34, 139, 34), -1)
        cv2.rectangle(frame, (1180, 0), (1280, 720), (34, 139, 34), -1)
        
        # Draw lane separators (dashed white lines)
        for y in range(0, 720, 60):
            if (y // 30) % 2 == 0:
                cv2.line(frame, (460, y), (460, y + 30), (255, 255, 255), 2)
                cv2.line(frame, (820, y), (820, y + 30), (255, 255, 255), 2)
                
        # Draw double solid yellow line in the center
        cv2.line(frame, (635, 0), (635, 720), (0, 255, 255), 2)
        cv2.line(frame, (645, 0), (645, 720), (0, 255, 255), 2)
        
        # Draw forbidden zones (outline) - matching configs:
        # Zone 1: "主路禁停区" -> (0.1, 0.1) to (0.3, 0.4) relative -> x: 128-384, y: 72-288
        cv2.rectangle(frame, (128, 72), (384, 288), (150, 0, 150), 2)
        cv2.putText(frame, "FORBIDDEN ZONE 1", (135, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 0, 150), 2)
        
        # Zone 2: "路口禁停区" -> (0.6, 0.5) to (0.9, 0.9) relative -> x: 768-1152, y: 360-648
        cv2.rectangle(frame, (768, 360), (1152, 648), (150, 0, 150), 2)
        cv2.putText(frame, "FORBIDDEN ZONE 2", (775, 385), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 0, 150), 2)
        
        # Update simulation vehicles
        for v in self.vehicles:
            # Stopped vehicle logic
            if v["speed"] == 0:
                # Is in Zone 1? (128-384, 72-288). Vehicle x: 180, y: 300. Bottom center of vehicle: x=210, y=280 (inside!)
                if v["stop_start"] is None:
                    v["stop_start"] = time.time()
            else:
                v["y"] += v["speed"]
                # Loop back vehicles
                if v["y"] > 780:
                    v["y"] = -100
                    
            # Draw vehicle body (rect)
            vx, vy = v["x"], v["y"]
            w, h = 60, 100 if v["type"] == "truck" else 80
            vcolor = (180, 50, 50) if v["type"] == "truck" else (50, 180, 50)
            cv2.rectangle(frame, (vx, vy), (vx + w, vy + h), vcolor, -1)
            
            # Draw fake license plate label on vehicle bumper (so OCR can read it)
            # EasyOCR expects plate pattern. Let's write the text clearly inside a white rectangle.
            cv2.rectangle(frame, (vx + 5, vy + h - 25), (vx + w - 5, vy + h - 5), (255, 255, 255), -1)
            cv2.putText(frame, v["plate"], (vx + 8, vy + h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
            
            # Label vehicle ID
            cv2.putText(frame, f"{v['type'].upper()} #{v['id']}", (vx, vy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # Draw road anomaly (box dropped cargo)
        ax, ay, aw, ah = self.anomaly["x"], self.anomaly["y"], self.anomaly["w"], self.anomaly["h"]
        # Draw cardboard box
        cv2.rectangle(frame, (ax, ay), (ax + aw, ay + ah), (42, 100, 139), -1) # Brown color
        cv2.rectangle(frame, (ax, ay), (ax + aw, ay + ah), (20, 50, 80), 2) # outline
        cv2.line(frame, (ax, ay), (ax + aw, ay + ah), (20, 50, 80), 2) # box flaps
        cv2.line(frame, (ax + aw, ay), (ax, ay + ah), (20, 50, 80), 2)
        cv2.putText(frame, "DROPPED CARGO", (ax - 20, ay - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 165, 255), 1)
        
        # Display simulated metrics
        cv2.putText(frame, "EDGE SIMULATION MODE", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.putText(frame, f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        
        return frame


def stream_worker():
    global streaming_active
    logger.info("Edge streaming worker thread started.")
    
    simulation = MockTrafficSimulation()
    cap = None
    
    # WebSocket connection
    ws = None
    
    while streaming_active:
        try:
            # Reconnect loop
            if ws is None:
                logger.info(f"Connecting to cloud server WebSocket: {ws_url}")
                ws = websocket.create_connection(ws_url, timeout=5)
                logger.info("WebSocket connected successfully.")
            
            # Get frame
            frame = None
            if stream_mode == "camera":
                if cap is None or not cap.isOpened():
                    cap = cv2.VideoCapture(0)
                    if not cap.isOpened():
                        logger.error("Failed to open local camera. Falling back to mock simulation.")
                        stream_mode == "mock"
                        continue
                ret, frame = cap.read()
                if not ret:
                    logger.warning("Failed to grab camera frame.")
                    time.sleep(0.1)
                    continue
            elif stream_mode == "video":
                if not os.path.exists(video_path):
                    logger.error(f"Video file not found: {video_path}. Falling back to mock simulation.")
                    stream_mode = "mock"
                    continue
                if cap is None or not cap.isOpened():
                    cap = cv2.VideoCapture(video_path)
                ret, frame = cap.read()
                if not ret:
                    # Loop video
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
            else:  # Mock traffic simulation
                frame = simulation.generate_frame()
                
            if frame is not None:
                # Resize if necessary to match config
                frame = cv2.resize(frame, (1280, 720))
                
                # Encode frame to JPEG
                success, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if success:
                    # Send bytes via WS
                    ws.send_binary(buffer.tobytes())
                    
            # Control frame rate
            time.sleep(1.0 / fps_target)
            
        except Exception as e:
            logger.error(f"WebSocket send error or frame capture error: {e}")
            if ws:
                try:
                    ws.close()
                except:
                    pass
                ws = None
            time.sleep(2.0)  # Wait before reconnecting
            
    # Cleanup
    if cap is not None:
        cap.release()
    if ws is not None:
        try:
            ws.close()
        except:
            pass
    logger.info("Edge streaming worker thread stopped.")


@app.route("/")
def index():
    return render_template("stream.html")

@app.route("/api/status", methods=["GET"])
def get_status():
    return jsonify({
        "streaming": streaming_active,
        "mode": stream_mode,
        "ws_url": ws_url,
        "fps_target": fps_target,
        "video_path": video_path
    })

@app.route("/api/start", methods=["POST"])
def start_stream():
    global streaming_active, stream_mode, ws_url, fps_target, video_path
    
    if streaming_active:
        return jsonify({"status": "error", "message": "Streaming already running"})
        
    data = request.json or {}
    stream_mode = data.get("mode", "mock")
    ws_url = data.get("ws_url", "ws://10.217.55.162:8000/ws/stream/cam_01")
    fps_target = float(data.get("fps", 10.0))
    video_path = data.get("video_path", "")
    
    streaming_active = True
    t = threading.Thread(target=stream_worker, daemon=True)
    t.start()
    
    logger.info(f"Stream started. Mode: {stream_mode}, Target: {ws_url}")
    return jsonify({"status": "success", "message": "Stream started"})

@app.route("/api/stop", methods=["POST"])
def stop_stream():
    global streaming_active
    if not streaming_active:
        return jsonify({"status": "error", "message": "Streaming is not running"})
        
    streaming_active = False
    logger.info("Stream stopped command received.")
    return jsonify({"status": "success", "message": "Stream stopped"})


if __name__ == "__main__":
    # Start Flask server on Port 5001 for edge device management
    app.run(host="0.0.0.0", port=5001)
