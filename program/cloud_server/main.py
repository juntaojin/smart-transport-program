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

@asynccontextmanager
async def lifespan(app: FastAPI):
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
    pipeline.add_node(PlateRecognitionNode())
    pipeline.add_node(AnomalyDetectionNode())
    pipeline.add_node(ViolationDetectionNode())

    # Enable foundational nodes by default
    pipeline.toggle_node("vehicle_detection", True)
    pipeline.toggle_node("tracking", True)
    pipeline.toggle_node("violation_detection", True)
    
    # Share pipeline instance through FastAPI app state
    app.state.pipeline = pipeline
    logger.info("Pipeline initialized and foundational nodes started.")

    yield

    # 3. Clean up on shutdown
    logger.info("Application shutting down. Releasing model resources...")
    for name, node in pipeline.nodes.items():
        try:
            node.unload_model()
        except Exception as e:
            logger.error(f"Error unloading node '{name}': {e}")
    logger.info("Models successfully unloaded.")


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

if __name__ == "__main__":
    # Standard Uvicorn runner listening on Port 8000
    uvicorn.run(
        "cloud_server.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False  # Turn reload off when models are loaded to avoid multi-process leaks
    )
