import asyncio
import sys
import os

# Append project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cloud_server.database.connection import engine, Base, async_session
from cloud_server.database.orm_models import PlateRecord, VehicleStat, ParkingViolation, RoadAnomaly, SystemMetric, ModelConfig

async def test_db_operations():
    print("Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables initialized successfully.")

    print("Testing insertion operations...")
    async with async_session() as db:
        # Create test records
        stat = VehicleStat(zone_name="Test Zone", vehicle_count=5, congestion_level="medium")
        plate = PlateRecord(plate_number="粤B99999", is_whitelisted=True)
        violation = ParkingViolation(vehicle_id="12", zone_name="No Parking", parking_duration=12.5)
        anomaly = RoadAnomaly(anomaly_type="box", confidence=0.88, location_x=100.0, location_y=200.0)
        
        db.add_all([stat, plate, violation, anomaly])
        await db.commit()
        print("Test records inserted and committed successfully.")

    print("Testing read operations...")
    async with async_session() as db:
        # Query items
        from sqlalchemy import select
        result = await db.execute(select(VehicleStat).where(VehicleStat.zone_name == "Test Zone"))
        stats = result.scalars().all()
        print(f"Queried {len(stats)} VehicleStat records from database.")
        for s in stats:
            print(f" - Zone: {s.zone_name}, Count: {s.vehicle_count}, Level: {s.congestion_level}")

        result_plate = await db.execute(select(PlateRecord).where(PlateRecord.plate_number == "粤B99999"))
        plates = result_plate.scalars().all()
        print(f"Queried {len(plates)} PlateRecord records.")
        for p in plates:
            print(f" - Plate: {p.plate_number}, Whitelisted: {p.is_whitelisted}")

    print("DB Verification SUCCESS!")

if __name__ == "__main__":
    asyncio.run(test_db_operations())
