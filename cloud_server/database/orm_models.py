from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, JSON
from datetime import datetime
from cloud_server.database.connection import Base

class PlateRecord(Base):
    __tablename__ = "plate_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plate_number = Column(String(20), index=True, nullable=False)
    is_whitelisted = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.now)

class VehicleStat(Base):
    __tablename__ = "vehicle_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    zone_name = Column(String(50), index=True, nullable=False)
    vehicle_count = Column(Integer, default=0)
    congestion_level = Column(String(20), default="low")  # low / medium / high
    timestamp = Column(DateTime, index=True, default=datetime.utcnow)

class ParkingViolation(Base):
    __tablename__ = "parking_violations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(String(50), nullable=False)
    zone_name = Column(String(50), nullable=False)
    parking_duration = Column(Float, default=0.0)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    alert_triggered = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

class RoadAnomaly(Base):
    __tablename__ = "road_anomalies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    anomaly_type = Column(String(50), nullable=False)  # obstacle / debris / dropped_cargo / tire / box / trash / rock
    confidence = Column(Float, nullable=False)
    location_x = Column(Float, nullable=False)
    location_y = Column(Float, nullable=False)
    affected_lane = Column(String(20), default="Unknown")
    timestamp = Column(DateTime, index=True, default=datetime.utcnow)

class SystemMetric(Base):
    __tablename__ = "system_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cpu_usage = Column(Float, nullable=False)
    gpu_usage = Column(Float, nullable=True)
    memory_usage = Column(Float, nullable=False)
    disk_usage = Column(Float, nullable=False)
    network_rx = Column(Float, default=0.0)  # Mbps
    network_tx = Column(Float, default=0.0)  # Mbps
    video_fps = Column(Float, default=0.0)
    video_resolution = Column(String(20), default="1280x720")
    active_devices = Column(Integer, default=0)
    timestamp = Column(DateTime, index=True, default=datetime.utcnow)

class ModelConfig(Base):
    __tablename__ = "model_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(50), unique=True, index=True, nullable=False)
    task_type = Column(String(30), nullable=False)  # detection / recognition
    confidence_threshold = Column(Float, default=0.5)
    iou_threshold = Column(Float, default=0.45)
    enabled = Column(Boolean, default=True)
    params = Column(JSON, nullable=True)  # Additional config parameters
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class EdgeDevice(Base):
    __tablename__ = "edge_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(80), unique=True, index=True, nullable=False)
    device_name = Column(String(120), nullable=True)
    source_mode = Column(String(30), default="camera")
    user_agent = Column(String(500), nullable=True)
    last_ip = Column(String(80), nullable=True)
    allowed = Column(Boolean, default=True)
    first_registered_at = Column(DateTime, default=datetime.utcnow)
    last_verified_at = Column(DateTime, default=datetime.utcnow)
    last_stream_at = Column(DateTime, nullable=True)

class EdgeStreamRecord(Base):
    __tablename__ = "edge_stream_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(80), index=True, nullable=False)
    device_name = Column(String(120), nullable=True)
    source_mode = Column(String(30), default="camera")
    client_ip = Column(String(80), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String(30), default="streaming")
    frames_received = Column(Integer, default=0)
