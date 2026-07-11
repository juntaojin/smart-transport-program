"""IPM 服务接口测试脚本 —— 使用 FastAPI TestClient"""
import sys
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from fastapi import FastAPI
from ipm_service.routes import router
import json
import numpy as np

app = FastAPI()
app.include_router(router)
client = TestClient(app)

CAMERA_ID = "test_cam_01"
LANE_ID = "test_lane"
CAMERA_POINTS = [[100, 200], [800, 180], [820, 500], [80, 520]]
WORLD_POINTS = [[50, 100], [400, 100], [400, 300], [50, 300]]
VEHICLES = [[320, 350], [600, 380], [150, 420]]

passed = 0
failed = 0


def check(name, resp, expected_code, expected_data_key=None, status_code=200):
    global passed, failed
    ok = True
    if resp.status_code != status_code:
        print(f"  [FAIL] {name}: HTTP 状态码 {resp.status_code} != {status_code}")
        ok = False
    body = resp.json()
    if body.get("code") != expected_code:
        print(f"  [FAIL] {name}: code {body.get('code')} != {expected_code}")
        ok = False
    if expected_data_key is True:
        if body.get("data") is None:
            print(f"  [FAIL] {name}: data 不应为 null")
            ok = False
    elif expected_data_key == False:
        if body.get("data") is not None:
            print(f"  [FAIL] {name}: data 应为 null")
            ok = False
    elif expected_data_key is not None:
        if expected_data_key not in (body.get("data") or {}):
            print(f"  [FAIL] {name}: data 中缺少 key '{expected_data_key}'")
            ok = False
    if ok:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"    Response: {json.dumps(body, ensure_ascii=False)}")


print("=" * 60)
print("IPM 服务接口测试")
print("=" * 60)

# --- 1. POST /api/ipm/calibrate ---
print("\n[1] POST /api/ipm/calibrate")

# 正常标定
resp = client.post("/api/ipm/calibrate", json={
    "camera_id": CAMERA_ID,
    "lane_id": LANE_ID,
    "camera_points": CAMERA_POINTS,
    "world_points": WORLD_POINTS,
})
check("正常标定", resp, 200, "homography_matrix")
data = resp.json()["data"]
h_matrix = data["homography_matrix"]
assert len(h_matrix) == 3 and len(h_matrix[0]) == 3, "homography_matrix 应为 3x3"
assert abs(h_matrix[2][2] - 1.0) < 0.001, "H[2][2] 应约为 1.0"

# 点数不足 4
resp = client.post("/api/ipm/calibrate", json={
    "camera_id": "bad",
    "lane_id": "bad",
    "camera_points": [[1, 2], [3, 4]],
    "world_points": [[1, 2], [3, 4]],
})
check("点数不足4→400", resp, 400, False, status_code=400)

# 点数超过 4（应使用前4个）
resp = client.post("/api/ipm/calibrate", json={
    "camera_id": CAMERA_ID,
    "lane_id": "extra_lane",
    "camera_points": [[100, 200], [800, 180], [820, 500], [80, 520], [999, 999]],
    "world_points": [[50, 100], [400, 100], [400, 300], [50, 300], [999, 999]],
})
check("超过4个点→截断前4", resp, 200, "homography_matrix")

# 删除 extra_lane 清理
client.delete(f"/api/ipm/config/{CAMERA_ID}/extra_lane")

# 三点共线（应失败）
resp = client.post("/api/ipm/calibrate", json={
    "camera_id": "colinear",
    "lane_id": "bad",
    "camera_points": [[0, 0], [100, 0], [200, 0], [300, 0]],
    "world_points": [[0, 0], [100, 0], [200, 0], [300, 0]],
})
check("三点共线→400", resp, 400, False, status_code=400)

# --- 2. POST /api/ipm/transform (单摄模式) ---
print("\n[2] POST /api/ipm/transform (单摄)")

# 正常变换
resp = client.post("/api/ipm/transform", json={
    "camera_id": CAMERA_ID,
    "lane_id": LANE_ID,
    "vehicles": VEHICLES,
})
check("正常坐标变换", resp, 200, "transformed")
transformed = resp.json()["data"]["transformed"]
assert len(transformed) == len(VEHICLES), "变换结果数量应等于输入数量"
for pt in transformed:
    assert isinstance(pt, list) and len(pt) == 2, "每个点应为 [x, y]"

# 空 vehicles
resp = client.post("/api/ipm/transform", json={
    "camera_id": CAMERA_ID,
    "lane_id": LANE_ID,
    "vehicles": [],
})
check("空vehicles→空结果", resp, 200, "transformed")
assert resp.json()["data"]["transformed"] == [], "空vehicles应返回空数组"

# 未标定
resp = client.post("/api/ipm/transform", json={
    "camera_id": "nonexistent",
    "lane_id": "nonexistent",
    "vehicles": [[100, 200]],
})
check("未标定→404", resp, 404, False, status_code=404)

# 缺少字段
resp = client.post("/api/ipm/transform", json={
    "vehicles": [[100, 200]],
})
check("缺少camera_id→400", resp, 400, False, status_code=400)

# --- 3. POST /api/ipm/transform (批量模式) ---
print("\n[3] POST /api/ipm/transform (批量)")

# 批量变换
resp = client.post("/api/ipm/transform", json={
    "requests": [
        {
            "camera_id": CAMERA_ID,
            "lane_id": LANE_ID,
            "vehicles": [[320, 350], [600, 380]],
        },
        {
            "camera_id": CAMERA_ID,
            "lane_id": LANE_ID,
            "vehicles": [],
        },
        {
            "camera_id": "bad_cam",
            "lane_id": "bad_lane",
            "vehicles": [[100, 200]],
        },
    ],
})
check("批量变换", resp, 200, "results")
results = resp.json()["data"]["results"]
assert len(results) == 3, "应返回3个结果"
assert results[0]["transformed"] is not None and len(results[0]["transformed"]) == 2
assert results[1]["transformed"] == []
assert results[2]["transformed"] is None, "未标定应返回null"

# --- 4. GET /api/ipm/config ---
print("\n[4] GET /api/ipm/config")

resp = client.get("/api/ipm/config")
check("列出所有标定", resp, 200, "cameras")
cameras = resp.json()["data"]["cameras"]
assert CAMERA_ID in cameras
assert LANE_ID in cameras[CAMERA_ID]

# --- 5. GET /api/ipm/config/{camera_id} ---
print("\n[5] GET /api/ipm/config/{camera_id}")

resp = client.get(f"/api/ipm/config/{CAMERA_ID}")
check("获取指定摄像头", resp, 200, "lanes")
lanes = resp.json()["data"]["lanes"]
assert LANE_ID in lanes
assert "camera_points" in lanes[LANE_ID]
assert "world_points" in lanes[LANE_ID]
assert "homography_matrix" not in lanes[LANE_ID], "查询接口不应暴露 homography_matrix"

resp = client.get("/api/ipm/config/nonexistent")
check("查询不存在的摄像头→404", resp, 404, False, status_code=404)

# --- 6. DELETE /api/ipm/config/{camera_id}/{lane_id} ---
print("\n[6] DELETE /api/ipm/config/{camera_id}/{lane_id}")

resp = client.delete(f"/api/ipm/config/{CAMERA_ID}/nonexistent")
check("删除不存在的标定→404", resp, 404, False, status_code=404)

resp = client.delete(f"/api/ipm/config/{CAMERA_ID}/{LANE_ID}")
check("删除标定", resp, 200, False)

# 验证已删除
resp = client.get(f"/api/ipm/config/{CAMERA_ID}")
check("验证已删除→404", resp, 404, False, status_code=404)

# --- 总结 ---
print()
print("=" * 60)
total = passed + failed
print(f"测试完成: {passed}/{total} 通过, {failed}/{total} 失败")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
