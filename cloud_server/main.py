"""Smart Transport Cloud Server - Entry Point"""
import os
import sys

# ===== GPU DLL PATH: ensure onnxruntime CUDA providers find torch CUDA 12 DLLs =====
# Must be set before ANY imports that load onnxruntime or hyperlpr3.
_torch_lib = os.path.join(sys.prefix, 'Lib', 'site-packages', 'torch', 'lib')
if os.path.isdir(_torch_lib):
    os.environ['PATH'] = _torch_lib + os.pathsep + os.environ.get('PATH', '')

from contextlib import asynccontextmanager
from fastapi import FastAPI
from loguru import logger
import uvicorn

from cloud_server.database.connection import engine, Base
from cloud_server.api.middleware import setup_middleware
from cloud_server.api.rest_routes import router as rest_router
from cloud_server.api.ws_routes import router as ws_router

# Import Pipeline and Nodes
from cloud_server.pipeline.engine import InferencePipeline
from cloud_server.pipeline.nodes.detection_node import VehicleDetectionNode
from cloud_server.pipeline.nodes.tracking_node import TrackingNode
from cloud_server.pipeline.nodes.ocr_node import PlateRecognitionNode
from cloud_server.pipeline.nodes.anomaly_node import AnomalyDetectionNode
from cloud_server.pipeline.nodes.violation_node import ViolationDetectionNode
from cloud_server.pipeline.nodes.transform_node import CoordinateTransformNode


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("Environment Info:")
    try:
        import torch
        logger.info(f"  PyTorch: {torch.__version__}")
        logger.info(f"  CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            logger.info(f"  CUDA device: {torch.cuda.get_device_name(0)}")
    except ImportError:
        logger.info("  PyTorch: not installed (模型推理由 model_api 包提供)")
    logger.info("  Model API: model_api/ (函数直接调用)")
    logger.info("=" * 60)

    # 1. Initialize SQLite Database Tables
    logger.info("Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized successfully.")

    # 2. Build and Configure the AI Inference Pipeline
    logger.info("Assembling inference pipeline...")
    pipeline = InferencePipeline()
    pipeline.add_node(VehicleDetectionNode())
    pipeline.add_node(TrackingNode())
    pipeline.add_node(CoordinateTransformNode())  # 坐标变换：像素 → 俯视世界坐标
    pipeline.add_node(PlateRecognitionNode())
    pipeline.add_node(AnomalyDetectionNode())
    pipeline.add_node(ViolationDetectionNode())

    # All nodes start disabled by default — enable via frontend or API
    # 车辆检测和跟踪默认开启（前端核心功能依赖）
    pipeline.toggle_node("vehicle_detection", True)
    pipeline.toggle_node("tracking", True)
    app.state.pipeline = pipeline
    registered = list(pipeline.nodes.keys())
    logger.info(f"Pipeline nodes registered: {registered}")
    logger.info("Pipeline initialized with all nodes disabled by default.")
    logger.info("Use /api/configs/models to enable nodes dynamically.")

    # 3. Initialize RTSP stream manager
    from cloud_server.api.rtsp_streamer import RTSPStreamManager
    app.state.rtsp_manager = RTSPStreamManager(pipeline)
    logger.info("RTSP stream manager initialized.")

    yield

    # 4. Clean up on shutdown
    logger.info("Application shutting down. Cleaning up nodes...")
    for name, node in pipeline.nodes.items():
        try:
            node.unload_model()
        except Exception as e:
            logger.error(f"Error cleaning up node '{name}': {e}")
    logger.info("All nodes cleaned up.")


# Create FastAPI App
app = FastAPI(
    title="Intelligent Transportation System Cloud Server",
    description="FastAPI Backend for Real-time Video Stream Reception, AI Pipeline Processing, and REST Control",
    version="1.0.0",
    lifespan=lifespan
)

# Setup Middlewares (CORS)
setup_middleware(app)

# Include Routers
app.include_router(rest_router)
app.include_router(ws_router)
from ipm_service.routes import router as ipm_router
app.include_router(ipm_router)

# Route to serve the mobile phone camera stream client webpage
from fastapi.responses import HTMLResponse

@app.get("/phone", response_class=HTMLResponse)
async def get_phone_stream_page():
    from cloud_server.config import BASE_DIR, CAPTURE_FPS
    template_path = os.path.join(BASE_DIR, "cloud_server", "templates", "phone.html")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        html_content = html_content.replace("{{CAPTURE_FPS}}", str(CAPTURE_FPS))
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Failed to read phone template: {e}")
        return HTMLResponse(content="<h1>Internal Server Error: Missing phone.html template</h1>", status_code=500)

if __name__ == "__main__":
    from cloud_server.config import HOST, PORT, ENABLE_SSL, BASE_DIR
    
    ssl_keyfile = None
    ssl_certfile = None
    
    if ENABLE_SSL:
        cert_dir = os.path.join(BASE_DIR, "certs")
        ssl_certfile = os.path.join(cert_dir, "cert.pem")
        ssl_keyfile = os.path.join(cert_dir, "key.pem")
        
        if not (os.path.exists(ssl_certfile) and os.path.exists(ssl_keyfile)):
            os.makedirs(cert_dir, exist_ok=True)
            logger.info("Generating self-signed SSL certificates for HTTPS/WSS...")
            try:
                import subprocess
                subprocess.run([
                    "openssl", "req", "-x509", "-newkey", "rsa:2048",
                    "-keyout", ssl_keyfile, "-out", ssl_certfile,
                    "-days", "365", "-nodes",
                    "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=IP:127.0.0.1",
                ], check=True, capture_output=True)
                logger.info("Certificates generated successfully.")
            except Exception as e:
                logger.error(f"Failed to generate self-signed certificates via openssl: {e}")
                logger.warning("SSL will be disabled. Running backend in standard HTTP mode.")
                ssl_certfile = None
                ssl_keyfile = None
                
    uvicorn.run(
        "cloud_server.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile
    )
