import { useEffect, useState, useRef, useCallback } from 'react';
import { DashboardWebSocket, type FrameMeta } from '../services/ws';
import { streamAPI, anomalyAPI } from '../services/api';
import { MapPin, Trash2, Check, RefreshCw, Crosshair, Move } from 'lucide-react';
import roadModelV5 from '../assets/roadModelV5';

interface Point { x: number; y: number }
interface SandCamera { id: string; name: string; url: string }

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';
const ROAD_MODEL = roadModelV5;
const WORLD_WIDTH = ROAD_MODEL.metadata.extent.width;
const WORLD_HEIGHT = ROAD_MODEL.metadata.extent.height;
const WORLD_DISPLAY_SCALE = 1.6;

async function ipmRequest(path: string, options: RequestInit = {}) {
  const url = `${API_BASE}${path}`;
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  const res = await fetch(url, { ...options, headers });
  return res.json();
}

const ipmAPI = {
  calibrate: (cameraId: string, laneId: string, cameraPoints: Point[], worldPoints: Point[]) =>
    ipmRequest('/ipm/calibrate', {
      method: 'POST',
      body: JSON.stringify({
        camera_id: cameraId,
        lane_id: laneId,
        camera_points: cameraPoints.map(p => [p.x, p.y]),
        world_points: worldPoints.map(p => [p.x, p.y]),
      }),
    }),
  getConfig: () => ipmRequest('/ipm/config'),
  getCameraConfig: (cameraId: string) => ipmRequest(`/ipm/config/${cameraId}`),
  deleteConfig: (cameraId: string, laneId: string) =>
    ipmRequest(`/ipm/config/${cameraId}/${laneId}`, { method: 'DELETE' }),
};

export default function IPMCalibration() {
  const [cameraId, setCameraId] = useState('camera_01');
  const [laneId, setLaneId] = useState('');
  const [cameraPoints, setCameraPoints] = useState<Point[]>([]);
  const [worldPoints, setWorldPoints] = useState<Point[]>([]);
  const camPtsRef = useRef(cameraPoints);
  camPtsRef.current = cameraPoints;
  const worldPtsRef = useRef(worldPoints);
  worldPtsRef.current = worldPoints;
  const [calibratedLanes, setCalibratedLanes] = useState<Record<string, string[]>>({});
  const [hasFrame, setHasFrame] = useState(false);
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');
  const [message, setMessage] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [currentVehicles, setCurrentVehicles] = useState<any[]>([]);
  const [transformedVehicles, setTransformedVehicles] = useState<any[]>([]);
  const [sandCameras, setSandCameras] = useState<SandCamera[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('default');
  const [activeRtspDevices, setActiveRtspDevices] = useState<string[]>([]);
  const [videoAspectRatio, setVideoAspectRatio] = useState('16 / 9');
  const vehicleDotsRef = useRef<any[]>([]);
  vehicleDotsRef.current = transformedVehicles;

  const cameraCanvasRef = useRef<HTMLCanvasElement>(null);
  const worldCanvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<string | null>(null);
  const selectedDeviceRef = useRef(selectedDeviceId);
  selectedDeviceRef.current = selectedDeviceId;
  const frameUrlsRef = useRef<Record<string, string>>({});
  const payloadsRef = useRef<Record<string, any>>({});
  const wsRef = useRef<DashboardWebSocket | null>(null);
  const camSizeRef = useRef({ w: 0, h: 0 });
  const videoAspectRatioRef = useRef(videoAspectRatio);
  videoAspectRatioRef.current = videoAspectRatio;

  useEffect(() => { if (message) { const t = setTimeout(() => setMessage(null), 3000); return () => clearTimeout(t); } }, [message]);

  // Load existing configs
  const loadConfigs = useCallback(async () => {
    try {
      const res = await ipmAPI.getConfig();
      if (res.code === 200 && res.data?.cameras) {
        setCalibratedLanes(res.data.cameras);
      }
    } catch {}
  }, []);
  useEffect(() => { loadConfigs(); }, [loadConfigs]);

  // Load points for selected camera+lane
  useEffect(() => {
    if (!cameraId || !laneId) { setCameraPoints([]); setWorldPoints([]); return; }
    (async () => {
      try {
        const res = await ipmAPI.getCameraConfig(cameraId);
        if (res.code === 200 && res.data?.lanes?.[laneId]) {
          const lane = res.data.lanes[laneId];
          setCameraPoints(lane.camera_points.map((p: number[]) => ({ x: p[0], y: p[1] })));
          setWorldPoints(lane.world_points.map((p: number[]) => ({ x: p[0], y: p[1] })));
        } else {
          setCameraPoints([]);
          setWorldPoints([]);
        }
      } catch { setCameraPoints([]); setWorldPoints([]); }
    })();
  }, [cameraId, laneId]);

  const selectLane = (lid: string) => { setLaneId(lid); };

  useEffect(() => {
    const loadSandCameras = async () => {
      try {
        const res = await streamAPI.cameras();
        if (res.code === 200 && Array.isArray(res.data)) setSandCameras(res.data);
      } catch {}
    };
    loadSandCameras();
  }, []);

  const activeSandCameras = sandCameras.filter(camera => activeRtspDevices.includes(`rtsp_${camera.id}`));
  const cameraLanes = calibratedLanes[cameraId] || [];

  const normalizeDeviceId = (deviceId?: string) => deviceId?.startsWith('rtsp_') ? deviceId : 'default';

  const selectDevice = (deviceId: string) => {
    if (deviceId.startsWith("rtsp_")) anomalyAPI.reset(deviceId).catch(() => {});
    setSelectedDeviceId(deviceId);
    frameRef.current = frameUrlsRef.current[deviceId] || null;
    setHasFrame(Boolean(frameRef.current));
    const payload = payloadsRef.current[deviceId];
    setCurrentVehicles(payload?.vehicles || []);
    const rtspCameraId = deviceId.startsWith('rtsp_') ? deviceId.slice(5) : deviceId;
    setCameraId(rtspCameraId);
  };

  useEffect(() => {
    let cancelled = false;

    const syncRtspStatus = async () => {
      try {
        const res = await streamAPI.status();
        if (cancelled || res.code !== 200 || !res.data) return;

        const activeIds = Object.entries(res.data)
          .filter(([deviceId, info]: [string, any]) => deviceId.startsWith('rtsp_') && info?.active)
          .map(([deviceId]) => deviceId);
        const activeSet = new Set(activeIds);

        for (const [deviceId, url] of Object.entries(frameUrlsRef.current)) {
          if (deviceId.startsWith('rtsp_') && !activeSet.has(deviceId)) {
            if (typeof url === 'string' && url.startsWith('blob:')) URL.revokeObjectURL(url);
            delete frameUrlsRef.current[deviceId];
          }
        }
        for (const deviceId of Object.keys(payloadsRef.current)) {
          if (deviceId.startsWith('rtsp_') && !activeSet.has(deviceId)) delete payloadsRef.current[deviceId];
        }

        setActiveRtspDevices(activeIds);

        if (selectedDeviceRef.current.startsWith('rtsp_') && !activeSet.has(selectedDeviceRef.current)) {
          const fallback = activeIds[0] || 'default';
          selectedDeviceRef.current = fallback;
          setSelectedDeviceId(fallback);
          frameRef.current = frameUrlsRef.current[fallback] || null;
          setHasFrame(Boolean(frameRef.current));
          const payload = payloadsRef.current[fallback];
          setCurrentVehicles(payload?.vehicles || []);
          setCameraId(fallback.startsWith('rtsp_') ? fallback.slice(5) : fallback);
        }
      } catch {}
    };

    syncRtspStatus();
    const timer = window.setInterval(syncRtspStatus, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  // WebSocket for camera feed
  useEffect(() => {
    const onImage = (blob: Blob, meta: FrameMeta) => {
      const deviceId = normalizeDeviceId(meta.deviceId);
      const url = URL.createObjectURL(blob);
      const previous = frameUrlsRef.current[deviceId];
      if (previous) URL.revokeObjectURL(previous);
      frameUrlsRef.current[deviceId] = url;
      if (deviceId.startsWith('rtsp_')) {
        setActiveRtspDevices(prev => prev.includes(deviceId) ? prev : [...prev, deviceId]);
        if (selectedDeviceRef.current === 'default' && !frameUrlsRef.current.default) {
          selectedDeviceRef.current = deviceId;
          setSelectedDeviceId(deviceId);
          setCameraId(deviceId.slice(5));
          frameRef.current = url;
          setHasFrame(true);
        }
      }
      if (selectedDeviceRef.current === deviceId) {
        frameRef.current = url;
        setHasFrame(true);
      }
    };
    const onMessage = (data: any) => {
      const deviceId = normalizeDeviceId(data.device_id);
      payloadsRef.current[deviceId] = data;
      if (deviceId.startsWith('rtsp_')) {
        setActiveRtspDevices(prev => prev.includes(deviceId) ? prev : [...prev, deviceId]);
        if (selectedDeviceRef.current === 'default' && !frameUrlsRef.current.default) {
          selectedDeviceRef.current = deviceId;
          setSelectedDeviceId(deviceId);
          setCameraId(deviceId.slice(5));
          if (data.vehicles) setCurrentVehicles(data.vehicles);
        }
      }
      if (selectedDeviceRef.current === deviceId && data.vehicles) {
        setCurrentVehicles(data.vehicles);
      }
    };
    const onStatus = (s: any) => setWsStatus(s);
    wsRef.current = new DashboardWebSocket(onMessage, onImage, onStatus);
    wsRef.current.connect();
    return () => {
      wsRef.current?.stop();
      for (const url of Object.values(frameUrlsRef.current)) {
        if (url.startsWith('blob:')) URL.revokeObjectURL(url);
      }
    };
  }, []);
  // Render camera feed canvas
  useEffect(() => {
    const canvas = cameraCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    let animating = true;

    const parent = canvas.parentElement;
    const ro = new ResizeObserver(entries => {
      for (const e of entries) {
        canvas.width = e.contentRect.width;
        canvas.height = e.contentRect.height;
      }
    });
    if (parent) ro.observe(parent);

    const img = new Image();
    let pending: string | null = null;

    const render = () => {
      if (!animating) return;
      const f = frameRef.current;
      if (f && f !== pending) {
        pending = f;
        img.onload = () => {
          if (!animating) return;
          const cw = canvas.width, ch = canvas.height;
          if (!cw || !ch) return;
          ctx.clearRect(0, 0, cw, ch);
          const scale = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
          const sw = img.naturalWidth * scale, sh = img.naturalHeight * scale;
          const sx = (cw - sw) / 2, sy = (ch - sh) / 2;
          camSizeRef.current = { w: img.naturalWidth, h: img.naturalHeight };
          const nextAspect = img.naturalWidth + ' / ' + img.naturalHeight;
          if (videoAspectRatioRef.current !== nextAspect) {
            videoAspectRatioRef.current = nextAspect;
            setVideoAspectRatio(nextAspect);
          }
          ctx.drawImage(img, sx, sy, sw, sh);
          drawPoints(ctx, camPtsRef.current, sx, sy, sw, sh, img.naturalWidth, img.naturalHeight);
        };
        img.src = f;
      }
      requestAnimationFrame(render);
    };
    render();
    return () => { animating = false; };
  }, []);

  const drawRoadModelBackground = (ctx: CanvasRenderingContext2D, cw: number, ch: number) => {
    const sx = cw / WORLD_WIDTH;
    const sy = ch / WORLD_HEIGHT;

    ctx.save();
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, cw, ch);

    ctx.strokeStyle = 'rgba(51, 65, 85, 0.75)';
    ctx.lineWidth = 1;
    for (let x = 0; x <= WORLD_WIDTH; x += 80) {
      ctx.beginPath(); ctx.moveTo(x * sx, 0); ctx.lineTo(x * sx, ch); ctx.stroke();
    }
    for (let y = 0; y <= WORLD_HEIGHT; y += 80) {
      ctx.beginPath(); ctx.moveTo(0, y * sy); ctx.lineTo(cw, y * sy); ctx.stroke();
    }

    for (const road of ROAD_MODEL.roads) {
      const points = road.centerline;
      if (!points || points.length < 2) continue;

      ctx.beginPath();
      points.forEach(([x, y], index) => {
        const px = x * sx;
        const py = y * sy;
        if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      });
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.strokeStyle = 'rgba(2, 6, 23, 0.92)';
      ctx.lineWidth = 18;
      ctx.stroke();

      ctx.strokeStyle = 'rgba(148, 163, 184, 0.88)';
      ctx.lineWidth = 10;
      ctx.stroke();

      ctx.strokeStyle = 'rgba(226, 232, 240, 0.30)';
      ctx.lineWidth = 2;
      ctx.setLineDash([12, 12]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    for (const node of ROAD_MODEL.nodes) {
      const px = node.x * sx;
      const py = node.y * sy;
      ctx.beginPath(); ctx.arc(px, py, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(15, 23, 42, 0.95)'; ctx.fill();
      ctx.strokeStyle = 'rgba(226, 232, 240, 0.65)'; ctx.lineWidth = 1.5; ctx.stroke();
    }

    ctx.strokeStyle = 'rgba(59, 130, 246, 0.55)';
    ctx.lineWidth = 3;
    ctx.strokeRect(1.5, 1.5, cw - 3, ch - 3);
    ctx.restore();
  };

  // Render world canvas (read-only sand-table road model background)
  useEffect(() => {
    const canvas = worldCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const redrawWorld = () => {
      const cw = canvas.width || WORLD_WIDTH, ch = canvas.height || WORLD_HEIGHT;
      drawRoadModelBackground(ctx, cw, ch);

      // Calibration points (green)
      drawPoints(ctx, worldPtsRef.current, 0, 0, cw, ch, WORLD_WIDTH, WORLD_HEIGHT);
      // Transformed vehicle dots (red)
      for (const v of vehicleDotsRef.current) {
        if (!v.world) continue;
        const px = v.world[0] / WORLD_WIDTH * cw;
        const py = v.world[1] / WORLD_HEIGHT * ch;
        ctx.beginPath(); ctx.arc(px, py, 8, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(239, 68, 68, 0.8)'; ctx.fill();
        ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
        ctx.fillStyle = '#fff'; ctx.font = 'bold 10px monospace'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(`#${v.id || '?'}`, px, py - 12);
      }
    };

    const parent = canvas.parentElement;
    const ro = new ResizeObserver(() => {
      canvas.width = WORLD_WIDTH;
      canvas.height = WORLD_HEIGHT;
      redrawWorld();
    });
    if (parent) ro.observe(parent);

    redrawWorld();
    return () => { ro.disconnect(); };
  }, [worldPoints, transformedVehicles]);
  const drawPoints = (ctx: CanvasRenderingContext2D, points: Point[], sx: number, sy: number, sw: number, sh: number, imgW: number, imgH: number) => {
    for (let i = 0; i < points.length; i++) {
      const px = sx + points[i].x / imgW * sw;
      const py = sy + points[i].y / imgH * sh;
      ctx.beginPath(); ctx.arc(px, py, 7, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(34, 197, 94, 0.9)'; ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = '#fff'; ctx.font = 'bold 11px monospace'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(String(i + 1), px, py);
    }
    if (points.length >= 2) {
      ctx.beginPath(); ctx.setLineDash([5, 3]); ctx.strokeStyle = 'rgba(34, 197, 94, 0.6)'; ctx.lineWidth = 2;
      for (let i = 0; i < points.length; i++) {
        const px = sx + points[i].x / imgW * sw;
        const py = sy + points[i].y / imgH * sh;
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.stroke(); ctx.setLineDash([]);
    }
  };

  const handleCameraClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (cameraPoints.length >= 4 || !camSizeRef.current.w) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const cw = e.currentTarget.width, ch = e.currentTarget.height;
    const scale = Math.min(cw / camSizeRef.current.w, ch / camSizeRef.current.h);
    const sw = camSizeRef.current.w * scale, sh = camSizeRef.current.h * scale;
    const sx = (cw - sw) / 2, sy = (ch - sh) / 2;
    const cx = (e.clientX - rect.left) * (cw / rect.width);
    const cy = (e.clientY - rect.top) * (ch / rect.height);
    const imgX = (cx - sx) / sw * camSizeRef.current.w;
    const imgY = (cy - sy) / sh * camSizeRef.current.h;
    if (imgX < 0 || imgY < 0 || imgX > camSizeRef.current.w || imgY > camSizeRef.current.h) return;
    setCameraPoints(prev => [...prev, { x: Math.round(imgX), y: Math.round(imgY) }]);
  };

  const handleWorldClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (worldPoints.length >= 4) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const cw = e.currentTarget.width || WORLD_WIDTH;
    const ch = e.currentTarget.height || WORLD_HEIGHT;
    const worldX = (e.clientX - rect.left) * (cw / rect.width);
    const worldY = (e.clientY - rect.top) * (ch / rect.height);
    if (worldX < 0 || worldY < 0 || worldX > WORLD_WIDTH || worldY > WORLD_HEIGHT) return;
    setWorldPoints(prev => [...prev, { x: Math.round(worldX), y: Math.round(worldY) }]);
  };

  const handleCalibrate = async () => {
    if (cameraPoints.length !== 4 || worldPoints.length !== 4 || !laneId) return;
    try {
      const res = await ipmAPI.calibrate(cameraId, laneId, cameraPoints, worldPoints);
      if (res.code === 200) {
        setMessage({ type: 'ok', text: `标定成功: ${cameraId}/${laneId}` });
        loadConfigs();
      } else {
        setMessage({ type: 'err', text: res.message || '标定失败' });
      }
    } catch (e: any) {
      setMessage({ type: 'err', text: '标定失败: ' + (e?.message || '网络错误') });
    }
  };

  const handleDelete = async (cid: string, lid: string) => {
    try {
      const res = await ipmAPI.deleteConfig(cid, lid);
      if (res.code === 200) {
        setMessage({ type: 'ok', text: `已删除: ${cid}/${lid}` });
        if (cid === cameraId && lid === laneId) { setCameraPoints([]); setWorldPoints([]); }
        loadConfigs();
      } else {
        setMessage({ type: 'err', text: res.message || '删除失败' });
      }
    } catch (e: any) {
      setMessage({ type: 'err', text: '删除失败: ' + (e?.message || '网络错误') });
    }
  };

  const doTransform = useCallback(async () => {
    if (!laneId || currentVehicles.length === 0) { setTransformedVehicles([]); return; }
    const points = currentVehicles.map((v: any) => [(v.box[0] + v.box[2]) / 2, v.box[3]]);
    try {
      const res = await ipmRequest('/ipm/transform', {
        method: 'POST',
        body: JSON.stringify({ camera_id: cameraId, lane_id: laneId, vehicles: points }),
      });
      if (res.code === 200 && res.data?.transformed) {
        const transformed = res.data.transformed;
        setTransformedVehicles(currentVehicles.map((v: any, i: number) => ({
          id: v.id,
          class: v.class,
          camera: points[i],
          world: transformed[i] || null,
        })));
      } else {
        setTransformedVehicles([]);
      }
    } catch { setTransformedVehicles([]); }
  }, [cameraId, laneId, currentVehicles]);

  // Auto-transform every 5 seconds
  useEffect(() => {
    const t = setInterval(() => doTransform(), 5000);
    return () => clearInterval(t);
  }, [doTransform]);

  return (
    <div className="space-y-6">
      <div className="dashboard-card p-6">
        <h2 className="text-xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
          <MapPin className="text-emerald-400" /> IPM 逆透视变换标定
        </h2>
        <p className="text-[var(--color-text-secondary)] text-sm mt-1">在摄像头画面和俯视图上各标记4个对应点（顺时针），计算单应性矩阵用于热力图坐标映射</p>
      </div>

      {message && (
        <div className={`rounded-2xl p-4 text-sm font-semibold ${message.type === 'ok' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
          {message.text}
        </div>
      )}

      {activeSandCameras.length > 0 && (
        <div className="dashboard-card p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-[var(--color-text-secondary)] mr-2">沙盘摄像头</span>
            <button
              type="button"
              onClick={() => selectDevice('default')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${selectedDeviceId === 'default' ? 'bg-blue-500/20 text-blue-300 border-blue-500/40' : 'bg-white/90 dark:bg-[#1C1C22]/90 text-[var(--color-text-secondary)] border-[var(--color-border-card)] hover:text-gray-900 dark:text-gray-200'}`}
            >
              默认推流
            </button>
            {activeSandCameras.map(camera => {
              const deviceId = `rtsp_${camera.id}`;
              return (
                <button
                  key={camera.id}
                  type="button"
                  onClick={() => selectDevice(deviceId)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${selectedDeviceId === deviceId ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' : 'bg-white/90 dark:bg-[#1C1C22]/90 text-[var(--color-text-secondary)] border-[var(--color-border-card)] hover:text-gray-900 dark:text-gray-200'}`}
                >
                  {camera.id} {camera.name}
                </button>
              );
            })}
          </div>
        </div>
      )}
      {/* Camera ID + Lane ID */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="text-xs text-[var(--color-text-secondary)] block mb-1">摄像头 ID</label>
            <input value={cameraId} onChange={e => setCameraId(e.target.value)} className="bg-white/90 dark:bg-[#1C1C22]/90 border border-[var(--color-border-card)] rounded-xl px-4 py-2.5 text-sm text-gray-900 dark:text-gray-200 w-44 outline-none focus:border-blue-500 transition-colors" />
          </div>
          <button
            onClick={handleCalibrate}
            disabled={cameraPoints.length !== 4 || worldPoints.length !== 4 || !laneId}
            className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl text-sm font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <Check size={16} /> 计算标定
          </button>
        </div>

        {/* Lane selection buttons */}
        <div>
          <label className="text-xs text-[var(--color-text-secondary)] block mb-2">已标定车道（点击选择）</label>
          <div className="flex flex-wrap items-center gap-2">
            {cameraLanes.length === 0 ? (
              <span className="text-xs text-[var(--color-text-muted)]">暂无，请先标定或手动输入车道ID</span>
            ) : (
              cameraLanes.map((lid: string) => (
                <button
                  key={lid}
                  onClick={() => selectLane(lid)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                    laneId === lid
                      ? 'bg-blue-500/20 text-blue-400 border border-blue-500/40'
                      : 'bg-white/90 dark:bg-[#1C1C22]/90 text-[var(--color-text-secondary)] border border-[var(--color-border-card)] hover:border-blue-500/30 hover:text-gray-900 dark:text-gray-200'
                  }`}
                >
                  {lid}
                </button>
              ))
            )}
            <button
              onClick={() => { setLaneId(''); setCameraPoints([]); setWorldPoints([]); }}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-white/90 dark:bg-[#1C1C22]/90 text-[var(--color-text-muted)] border border-dashed border-gray-600 hover:border-gray-400 hover:text-gray-300 transition-colors"
            >
              + 新建
            </button>
          </div>
        </div>

        <div>
          <label className="text-xs text-[var(--color-text-secondary)] block mb-1">车道 ID（可手动输入）</label>
          <input value={laneId} onChange={e => setLaneId(e.target.value)} placeholder="输入车道名称后回车" className="bg-white/90 dark:bg-[#1C1C22]/90 border border-[var(--color-border-card)] rounded-xl px-4 py-2.5 text-sm text-gray-900 dark:text-gray-200 w-56 outline-none focus:border-blue-500 transition-colors" />
        </div>
      </div>

      {/* Dual panels */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
        {/* Camera panel */}
        <div className="dashboard-card p-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-900 dark:text-gray-200 flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${wsStatus === 'connected' ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />
              摄像头画面
            </h3>
            <div className="flex items-center gap-3">
              <span className="text-xs text-[var(--color-text-secondary)]">{cameraPoints.length}/4 点</span>
              <button onClick={() => setCameraPoints([])} className="text-xs text-[var(--color-text-muted)] hover:text-rose-400 transition-colors">清除</button>
            </div>
          </div>
          <div className="relative w-full max-h-[62vh] rounded-xl overflow-hidden bg-gray-100 dark:bg-[#0F1013] border border-[var(--color-border-card)]" style={{ aspectRatio: videoAspectRatio }}>
            <canvas ref={cameraCanvasRef} onClick={handleCameraClick} className="absolute inset-0 w-full h-full block" style={{ cursor: cameraPoints.length < 4 ? 'crosshair' : 'default' }} />
            {!hasFrame && (
              <div className="absolute inset-0 flex items-center justify-center bg-gray-100 dark:bg-[#0F1013]">
                <div className="text-center">
                  <div className="w-8 h-8 border-3 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                  <p className="text-[var(--color-text-muted)] text-sm">等待视频流...</p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* World panel */}
        <div className="dashboard-card p-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-900 dark:text-gray-200 flex items-center gap-2"><Move size={16} className="text-blue-400" /> 俯视图（白板）</h3>
            <div className="flex items-center gap-3">
              <span className="text-xs text-[var(--color-text-secondary)]">{worldPoints.length}/4 点</span>
              <button onClick={() => setWorldPoints([])} className="text-xs text-[var(--color-text-muted)] hover:text-rose-400 transition-colors">清除</button>
            </div>
          </div>
          <div className="relative h-[720px] xl:h-[760px] rounded-xl overflow-auto bg-gray-100 dark:bg-[#0F1013] border border-[var(--color-border-card)]">
            <canvas ref={worldCanvasRef} onClick={handleWorldClick} className="block" style={{ width: `${WORLD_WIDTH * WORLD_DISPLAY_SCALE}px`, height: `${WORLD_HEIGHT * WORLD_DISPLAY_SCALE}px`, cursor: worldPoints.length < 4 ? 'crosshair' : 'grab' }} />
          </div>
        </div>
      </div>

      {/* Transform verification */}
      <div className="dashboard-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-200 flex items-center gap-2">
            <Crosshair size={16} className="text-rose-400" /> 俯视坐标验证
          </h3>
          <div className="flex items-center gap-3">
            <span className="text-xs text-[var(--color-text-secondary)]">当前 {currentVehicles.length} 辆车 · 每5秒自动刷新</span>
            <button
              onClick={doTransform}
              disabled={!laneId || currentVehicles.length === 0}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-blue-500/20 text-blue-400 border border-blue-500/30 hover:bg-blue-500/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <RefreshCw size={14} /> 立即转换
            </button>
          </div>
        </div>
        {transformedVehicles.length === 0 ? (
          <p className="text-[var(--color-text-muted)] text-sm py-4 text-center">
            {!laneId ? '请先选择车道 ID' : currentVehicles.length === 0 ? '等待车辆检测数据...' : '转换中...'}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border-card)] text-[var(--color-text-secondary)] text-xs uppercase tracking-wider">
                  <th className="py-2 px-3">Track ID</th>
                  <th className="py-2 px-3">类别</th>
                  <th className="py-2 px-3">摄像头坐标</th>
                  <th className="py-2 px-3">俯视坐标</th>
                  <th className="py-2 px-3">状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#222328]/50">
                {transformedVehicles.map((v: any, i: number) => (
                  <tr key={i} className="hover:hover:bg-gray-100 dark:hover:bg-[#1C1E24]/40 transition-colors">
                    <td className="py-2 px-3 font-mono text-blue-400">#{v.id}</td>
                    <td className="py-2 px-3 text-gray-300 capitalize">{v.class}</td>
                    <td className="py-2 px-3 font-mono text-[var(--color-text-secondary)]">
                      ({v.camera[0].toFixed(0)}, {v.camera[1].toFixed(0)})
                    </td>
                    <td className="py-2 px-3 font-mono text-emerald-400">
                      {v.world ? `(${v.world[0].toFixed(1)}, ${v.world[1].toFixed(1)})` : '-'}
                    </td>
                    <td className="py-2 px-3">
                      {v.world ? (
                        <span className="text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded">已变换</span>
                      ) : (
                        <span className="text-xs bg-rose-500/10 text-rose-400 border border-rose-500/20 px-2 py-0.5 rounded">无标定</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Existing calibrations */}
      <div className="dashboard-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-200 flex items-center gap-2">
            <RefreshCw size={16} className="text-blue-400" /> 已标定车道
          </h3>
          <button onClick={loadConfigs} className="text-xs text-blue-400 hover:text-blue-300 transition-colors">刷新</button>
        </div>
        {Object.keys(calibratedLanes).length === 0 ? (
          <p className="text-[var(--color-text-muted)] text-sm py-4 text-center">暂无标定数据</p>
        ) : (
          <div className="space-y-3">
            {Object.entries(calibratedLanes).map(([cid, lanes]) =>
              lanes.map((lid: string) => (
                <div key={`${cid}/${lid}`} className="flex items-center justify-between bg-white/90 dark:bg-[#1C1C22]/90 border border-[var(--color-border-card)] rounded-xl px-4 py-3 hover:border-[var(--color-border-card)] transition-colors">
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-mono text-blue-400">{cid}</span>
                    <span className="text-xs text-[var(--color-text-muted)]">/</span>
                    <span className="text-sm font-semibold text-gray-900 dark:text-gray-200">{lid}</span>
                  </div>
                  <button onClick={() => handleDelete(cid, lid)} className="text-rose-500/80 hover:text-rose-400 hover:bg-rose-500/10 p-1.5 rounded-lg transition-colors">
                    <Trash2 size={16} />
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
