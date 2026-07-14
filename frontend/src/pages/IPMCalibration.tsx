import { useEffect, useState, useRef, useCallback } from 'react';
import simpleheat, { type SimpleHeat } from 'simpleheat';
import { DashboardWebSocket, type FrameMeta } from '../services/ws';
import { streamAPI, anomalyAPI, trafficAnalysisAPI } from '../services/api';
import { MapPin, Trash2, Check, RefreshCw, Crosshair, Move, Maximize2, X, Download, BrainCircuit } from 'lucide-react';
import roadModelV8 from '../assets/roadModelV8';

interface Point { x: number; y: number }
interface SandCamera { id: string; name: string; url: string }
interface HeatmapConfig {
  radius: number;
  blur: number;
  internalScale: number;
  sampleGridSize: number;
  animationFps: number;
  animationShift: number;
  animationBandHeight: number;
  intensity: number;
  decayFactor: number;
  maxHeat: number;
  updateInterval: number;
  opacity: number;
  minVisibleHeat: number;
  minSampleValue: number;
  sampleLifetime: number;
  trailStep: number;
  maxSamples: number;
  smoothingAlpha: number;
  vehicleTimeout: number;
}

interface HeatmapVehicleCache {
  x: number;
  y: number;
  lastSeen: number;
}

interface HeatmapVehiclePosition {
  id: string;
  x: number;
  y: number;
}

interface HeatmapSample {
  x: number;
  y: number;
  value: number;
  updatedAt: number;
}

interface GenerationFrame {
  elapsed: number;
  vehicles: any[];
}

interface TrafficAnalysisResult {
  metrics: {
    duration_ms: number;
    frame_count: number;
    capacity: number;
    current_count: number;
    average_count: number;
    maximum_count: number;
    two_or_more_ratio: number;
    full_capacity_ratio: number;
    first_5s_average: number;
    last_5s_average: number;
    trend: string;
    level: string;
    score: number;
  };
  report: {
    overall_level: string;
    score: number;
    confidence: number;
    trend: string;
    summary: string;
    evidence: string[];
    recommendations: string[];
    limitations: string[];
  };
  source: 'deepseek-v4' | 'rule' | 'rule_fallback';
  llm_error?: string | null;
}

type GenerationStatus = 'idle' | 'recording' | 'replaying';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';
const ROAD_MODEL = roadModelV8;
const WORLD_WIDTH = ROAD_MODEL.metadata.extent.width;
const WORLD_HEIGHT = ROAD_MODEL.metadata.extent.height;
const WORLD_DISPLAY_SCALE = 1.6;
const MAX_RECORDING_DURATION = 15000;
const DEFAULT_HEATMAP_CONFIG: HeatmapConfig = {
  radius: 46,
  blur: 52,
  internalScale: 0.66,
  sampleGridSize: 12,
  animationFps: 15,
  animationShift: 5,
  animationBandHeight: 8,
  intensity: 0.16,
  decayFactor: 0.94,
  maxHeat: 1,
  updateInterval: 350,
  opacity: 0.68,
  minVisibleHeat: 0.1,
  minSampleValue: 0.018,
  sampleLifetime: 12000,
  trailStep: 18,
  maxSamples: 640,
  smoothingAlpha: 0.3,
  vehicleTimeout: 3000,
};
const HEATMAP_GRADIENT = {
  0.18: 'rgba(34, 211, 238, 0.95)',
  0.36: '#22C55E',
  0.58: '#FACC15',
  0.78: '#F97316',
  1.00: '#EF4444',
};

const createCanvasElement = (width: number, height: number) => {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  return canvas;
};

const renderAnimatedHeatmapCanvas = (
  source: HTMLCanvasElement,
  animated: HTMLCanvasElement,
  time: number,
) => {
  const ctx = animated.getContext('2d');
  if (!ctx) return;

  ctx.clearRect(0, 0, animated.width, animated.height);
  ctx.save();
  ctx.globalCompositeOperation = 'source-over';
  ctx.imageSmoothingEnabled = true;
  ctx.filter = 'blur(0.45px) saturate(1.06)';

  const bandHeight = Math.max(3, Math.round(DEFAULT_HEATMAP_CONFIG.animationBandHeight * DEFAULT_HEATMAP_CONFIG.internalScale));
  const shift = DEFAULT_HEATMAP_CONFIG.animationShift * DEFAULT_HEATMAP_CONFIG.internalScale;
  const phase = time * 0.001;
  for (let y = 0; y < source.height; y += bandHeight) {
    const height = Math.min(bandHeight + 2, source.height - y);
    const edgeWave = Math.sin(y * 0.036 + phase * 2.1) + Math.sin(y * 0.017 - phase * 1.45) * 0.55;
    const dx = edgeWave * shift;
    const dy = Math.sin(y * 0.029 + phase * 1.7) * 1.2 - Math.max(0, 1 - y / source.height) * 1.5;
    const stretch = 1 + Math.sin(y * 0.022 - phase * 1.2) * 0.006;
    ctx.drawImage(source, 0, y, source.width, height, dx, y + dy, source.width * stretch, height + 1);
  }
  ctx.restore();

  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  ctx.globalAlpha = 0.1 + (Math.sin(phase * 2.4) + 1) * 0.025;
  ctx.filter = 'blur(2px)';
  for (let y = 0; y < source.height; y += bandHeight * 2) {
    const height = Math.min(bandHeight * 2, source.height - y);
    const dx = Math.cos(y * 0.021 + phase * 1.6) * shift * 0.55;
    const dy = Math.sin(y * 0.018 - phase * 1.9) * 1.6 - 1;
    ctx.drawImage(source, 0, y, source.width, height, dx, y + dy, source.width, height);
  }
  ctx.restore();
};

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
  const [isWorldFullscreen, setIsWorldFullscreen] = useState(false);
  const [isHeatmapMode, setIsHeatmapMode] = useState(false);
  const [generationStatus, setGenerationStatus] = useState<GenerationStatus>('idle');
  const [generationElapsed, setGenerationElapsed] = useState(0);
  const [recordingTotalElapsed, setRecordingTotalElapsed] = useState(0);
  const [recordedFrameCount, setRecordedFrameCount] = useState(0);
  const [isExportingVideo, setIsExportingVideo] = useState(false);
  const [videoExportProgress, setVideoExportProgress] = useState(0);
  const [isAnalyzingTraffic, setIsAnalyzingTraffic] = useState(false);
  const [trafficAnalysis, setTrafficAnalysis] = useState<TrafficAnalysisResult | null>(null);
  const recordedFramesRef = useRef<GenerationFrame[]>([]);
  const sessionHeatmapModeRef = useRef(false);
  const vehicleDotsRef = useRef<any[]>([]);
  vehicleDotsRef.current = transformedVehicles;

  const cameraCanvasRef = useRef<HTMLCanvasElement>(null);
  const worldCanvasRef = useRef<HTMLCanvasElement>(null);
  const fullscreenWorldCanvasRef = useRef<HTMLCanvasElement>(null);
  const roadBaseCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const heatmapColorRef = useRef<HTMLCanvasElement | null>(null);
  const heatmapAnimatedRef = useRef<HTMLCanvasElement | null>(null);
  const heatmapRendererRef = useRef<SimpleHeat | null>(null);
  const heatmapSamplesRef = useRef<HeatmapSample[]>([]);
  const heatmapVehicleCacheRef = useRef<Map<string, HeatmapVehicleCache>>(new Map());
  const heatmapLastUpdateRef = useRef(Date.now());
  const heatmapVisibleRef = useRef(false);
  const heatmapAnimationFrameRef = useRef<number | null>(null);
  const heatmapLastAnimationRef = useRef(0);
  const worldScrollRef = useRef<HTMLDivElement>(null);
  const fullscreenWorldScrollRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<string | null>(null);
  const selectedDeviceRef = useRef(selectedDeviceId);
  selectedDeviceRef.current = selectedDeviceId;
  const frameUrlsRef = useRef<Record<string, string>>({});
  const payloadsRef = useRef<Record<string, any>>({});
  const lastFrameAtRef = useRef<Record<string, number>>({});
  const rtspStreamIdentityRef = useRef<Record<string, string>>({});
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

  const clearHeatmapBuffers = useCallback(() => {
    for (const canvas of [heatmapColorRef.current, heatmapAnimatedRef.current]) {
      const ctx = canvas?.getContext('2d');
      if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    heatmapRendererRef.current?.clear();
    heatmapSamplesRef.current = [];
    heatmapVehicleCacheRef.current.clear();
    heatmapLastUpdateRef.current = Date.now();
    heatmapVisibleRef.current = false;
  }, []);

  const clearCameraMarks = useCallback(() => {
    setCameraPoints([]);
    setTransformedVehicles([]);
    setGenerationStatus('idle');
    setGenerationElapsed(0);
    setRecordingTotalElapsed(0);
    setRecordedFrameCount(0);
    recordedFramesRef.current = [];
    setTrafficAnalysis(null);
    clearHeatmapBuffers();
  }, [clearHeatmapBuffers]);

  const selectDevice = (deviceId: string) => {
    if (selectedDeviceRef.current !== deviceId) clearCameraMarks();
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
            delete lastFrameAtRef.current[deviceId];
            delete rtspStreamIdentityRef.current[deviceId];
          }
        }
        for (const deviceId of Object.keys(payloadsRef.current)) {
          if (deviceId.startsWith('rtsp_') && !activeSet.has(deviceId)) delete payloadsRef.current[deviceId];
        }

        setActiveRtspDevices(activeIds);

        for (const [deviceId, info] of Object.entries(res.data)) {
          if (!deviceId.startsWith('rtsp_')) continue;
          const streamInfo = info as any;
          const nextIdentity = [streamInfo?.url, streamInfo?.camera_id, streamInfo?.camera_name].filter(Boolean).join('|');
          const previousIdentity = rtspStreamIdentityRef.current[deviceId];
          if (nextIdentity && previousIdentity && nextIdentity !== previousIdentity && selectedDeviceRef.current === deviceId) {
            clearCameraMarks();
          }
          if (nextIdentity) rtspStreamIdentityRef.current[deviceId] = nextIdentity;
        }

        if (selectedDeviceRef.current.startsWith('rtsp_') && !activeSet.has(selectedDeviceRef.current)) {
          const fallback = activeIds[0] || 'default';
          selectedDeviceRef.current = fallback;
          setSelectedDeviceId(fallback);
          frameRef.current = frameUrlsRef.current[fallback] || null;
          setHasFrame(Boolean(frameRef.current));
          const payload = payloadsRef.current[fallback];
          setCurrentVehicles(payload?.vehicles || []);
          setCameraId(fallback.startsWith('rtsp_') ? fallback.slice(5) : fallback);
          clearCameraMarks();
        }
      } catch {}
    };

    syncRtspStatus();
    const timer = window.setInterval(syncRtspStatus, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [clearCameraMarks]);

  // WebSocket for camera feed
  useEffect(() => {
    const onImage = (blob: Blob, meta: FrameMeta) => {
      const deviceId = normalizeDeviceId(meta.deviceId);
      const now = Date.now();
      const lastFrameAt = lastFrameAtRef.current[deviceId];
      const selectedBeforeImage = selectedDeviceRef.current;
      const url = URL.createObjectURL(blob);
      const previous = frameUrlsRef.current[deviceId];
      if (previous) URL.revokeObjectURL(previous);
      frameUrlsRef.current[deviceId] = url;
      lastFrameAtRef.current[deviceId] = now;
      if (deviceId.startsWith('rtsp_')) {
        setActiveRtspDevices(prev => prev.includes(deviceId) ? prev : [...prev, deviceId]);
        if (selectedDeviceRef.current === 'default' && !frameUrlsRef.current.default) {
          clearCameraMarks();
          selectedDeviceRef.current = deviceId;
          setSelectedDeviceId(deviceId);
          setCameraId(deviceId.slice(5));
          frameRef.current = url;
          setHasFrame(true);
        }
      }
      if (selectedDeviceRef.current === deviceId) {
        if (selectedBeforeImage === deviceId && lastFrameAt && now - lastFrameAt > 4000) {
          clearCameraMarks();
        }
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
          clearCameraMarks();
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
    const onStatus = (s: any) => {
      setWsStatus(s);
      if (s === 'disconnected') {
        frameRef.current = null;
        setHasFrame(false);
        setCurrentVehicles([]);
        clearCameraMarks();
      }
    };
    wsRef.current = new DashboardWebSocket(onMessage, onImage, onStatus);
    wsRef.current.connect();
    return () => {
      wsRef.current?.stop();
      for (const url of Object.values(frameUrlsRef.current)) {
        if (url.startsWith('blob:')) URL.revokeObjectURL(url);
      }
    };
  }, [clearCameraMarks]);
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
    const scale = Math.min(sx, sy);
    const toCanvas = ([x, y]: [number, number]) => [x * sx, y * sy] as const;
    const drawPolyline = (points: [number, number][]) => {
      ctx.beginPath();
      points.forEach((point, index) => {
        const [px, py] = toCanvas(point);
        if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      });
    };
    const drawRoadArrow = (x: number, y: number, angle: number, size: number) => {
      const px = x * sx;
      const py = y * sy;
      const arrowSize = Math.max(16, size * 1.45 * scale);

      ctx.save();
      ctx.translate(px, py);
      ctx.rotate((angle * Math.PI) / 180);
      ctx.font = `700 ${arrowSize}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.lineWidth = Math.max(3, arrowSize * 0.16);
      ctx.strokeStyle = 'rgba(15, 23, 42, 0.7)';
      ctx.fillStyle = 'rgba(248, 250, 252, 0.96)';
      ctx.shadowColor = 'rgba(2, 6, 23, 0.75)';
      ctx.shadowBlur = 4 * scale;
      ctx.strokeText('->', 0, 0);
      ctx.fillText('->', 0, 0);
      ctx.shadowBlur = 0;
      ctx.restore();
    };
    const drawCrosswalk = (points: [number, number][], width: number, stripeCount: number) => {
      if (points.length < 2) return;
      const [a, b] = points;
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const length = Math.hypot(dx, dy);
      if (!length) return;

      const nx = -dy / length;
      const ny = dx / length;
      const stripeLength = width;

      ctx.save();
      ctx.lineCap = 'butt';
      for (let i = 0; i < stripeCount; i++) {
        const t = stripeCount === 1 ? 0.5 : i / (stripeCount - 1);
        const x = a[0] + dx * t;
        const y = a[1] + dy * t;
        const x1 = (x - nx * stripeLength / 2) * sx;
        const y1 = (y - ny * stripeLength / 2) * sy;
        const x2 = (x + nx * stripeLength / 2) * sx;
        const y2 = (y + ny * stripeLength / 2) * sy;

        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.strokeStyle = 'rgba(2, 6, 23, 0.92)';
        ctx.lineWidth = Math.max(5, 7 * scale);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.strokeStyle = 'rgba(248, 250, 252, 0.96)';
        ctx.lineWidth = Math.max(4, 5 * scale);
        ctx.stroke();
      }
      ctx.restore();
    };

    ctx.save();
    const asphalt = ctx.createLinearGradient(0, 0, cw, ch);
    asphalt.addColorStop(0, '#343a3d');
    asphalt.addColorStop(0.52, '#2f3538');
    asphalt.addColorStop(1, '#272d30');
    ctx.fillStyle = asphalt;
    ctx.fillRect(0, 0, cw, ch);

    ctx.fillStyle = 'rgba(255, 255, 255, 0.035)';
    for (let x = 4; x < cw; x += 11) {
      for (let y = 3; y < ch; y += 13) {
        if (((x * 17 + y * 31) % 19) < 4) ctx.fillRect(x, y, 1, 1);
      }
    }

    ctx.strokeStyle = 'rgba(226, 232, 240, 0.08)';
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

      drawPolyline(points);
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.strokeStyle = 'rgba(15, 23, 42, 0.42)';
      ctx.lineWidth = Math.max(6, 8 * scale);
      ctx.stroke();

      drawPolyline(points);
      ctx.strokeStyle = 'rgba(96, 165, 250, 0.78)';
      ctx.lineWidth = Math.max(3, 4 * scale);
      ctx.stroke();
    }

    for (const crosswalk of ROAD_MODEL.crosswalks) {
      drawCrosswalk(crosswalk.points, crosswalk.width, crosswalk.stripe_count);
    }

    for (const marking of ROAD_MODEL.lane_markings) {
      if (marking.points.length < 2) continue;
      drawPolyline(marking.points);
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.strokeStyle = marking.style === 'solid'
        ? 'rgba(250, 204, 21, 0.96)'
        : 'rgba(250, 204, 21, 0.86)';
      ctx.lineWidth = Math.max(2, 3 * scale);
      ctx.setLineDash(marking.style === 'dashed' ? [16 * scale, 14 * scale] : []);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    for (const arrow of ROAD_MODEL.road_arrows) {
      drawRoadArrow(arrow.x, arrow.y, arrow.angle, arrow.size);
    }

    for (const node of ROAD_MODEL.nodes) {
      const px = node.x * sx;
      const py = node.y * sy;
      ctx.beginPath(); ctx.arc(px, py, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(15, 23, 42, 0.86)'; ctx.fill();
      ctx.strokeStyle = 'rgba(226, 232, 240, 0.75)'; ctx.lineWidth = 1.5; ctx.stroke();
    }

    ctx.strokeStyle = 'rgba(59, 130, 246, 0.5)';
    ctx.lineWidth = 3;
    ctx.strokeRect(1.5, 1.5, cw - 3, ch - 3);
    ctx.restore();
  };

  const getRoadBaseCanvas = () => {
    if (!roadBaseCanvasRef.current) {
      const baseCanvas = createCanvasElement(WORLD_WIDTH, WORLD_HEIGHT);
      const baseCtx = baseCanvas.getContext('2d');
      if (baseCtx) drawRoadModelBackground(baseCtx, WORLD_WIDTH, WORLD_HEIGHT);
      roadBaseCanvasRef.current = baseCanvas;
    }
    return roadBaseCanvasRef.current;
  };

  const drawWorldCanvas = useCallback((canvas: HTMLCanvasElement | null) => {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const cw = canvas.width || WORLD_WIDTH;
    const ch = canvas.height || WORLD_HEIGHT;
    const roadBase = getRoadBaseCanvas();
    if (roadBase) {
      ctx.clearRect(0, 0, cw, ch);
      ctx.drawImage(roadBase, 0, 0, cw, ch);
    } else {
      drawRoadModelBackground(ctx, cw, ch);
    }

    const heatmapCanvas = heatmapAnimatedRef.current || heatmapColorRef.current;
    if (heatmapCanvas) {
      ctx.save();
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = DEFAULT_HEATMAP_CONFIG.opacity;
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(heatmapCanvas, 0, 0, cw, ch);
      ctx.restore();
    }

    drawPoints(ctx, worldPtsRef.current, 0, 0, cw, ch, WORLD_WIDTH, WORLD_HEIGHT);
    if (!heatmapVisibleRef.current) {
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
    }
  }, []);

  const handleWhiteboardPanStart = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 2) return;
    const container = e.currentTarget;
    e.preventDefault();
    container.style.cursor = 'grabbing';
    container.style.userSelect = 'none';

    const startX = e.clientX;
    const startY = e.clientY;
    const startLeft = container.scrollLeft;
    const startTop = container.scrollTop;

    const handleMove = (event: MouseEvent) => {
      event.preventDefault();
      container.scrollLeft = startLeft - (event.clientX - startX);
      container.scrollTop = startTop - (event.clientY - startY);
    };
    const stopPan = () => {
      container.style.cursor = '';
      container.style.userSelect = '';
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', stopPan);
      window.removeEventListener('blur', stopPan);
    };

    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', stopPan);
    window.addEventListener('blur', stopPan);
  };

  // Render world canvas (read-only sand-table road model background)
  useEffect(() => {
    const canvases = [worldCanvasRef.current, fullscreenWorldCanvasRef.current].filter(Boolean) as HTMLCanvasElement[];
    const observers: ResizeObserver[] = [];

    const setupCanvas = (canvas: HTMLCanvasElement) => {
      canvas.width = WORLD_WIDTH;
      canvas.height = WORLD_HEIGHT;
      drawWorldCanvas(canvas);

      const parent = canvas.parentElement;
      if (!parent) return;
      const ro = new ResizeObserver(() => {
        canvas.width = WORLD_WIDTH;
        canvas.height = WORLD_HEIGHT;
        drawWorldCanvas(canvas);
      });
      ro.observe(parent);
      observers.push(ro);
    };

    canvases.forEach(setupCanvas);
    return () => { observers.forEach(ro => ro.disconnect()); };
  }, [worldPoints, transformedVehicles, isWorldFullscreen, drawWorldCanvas]);

  useEffect(() => {
    if (!isWorldFullscreen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsWorldFullscreen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isWorldFullscreen]);

  const renderWhiteboardCanvas = (
    ref: React.RefObject<HTMLCanvasElement | null>,
    displayScale = WORLD_DISPLAY_SCALE,
    fitToContainer = false,
  ) => (
    <canvas
      ref={ref}
      onClick={handleWorldClick}
      className="block"
      style={fitToContainer
        ? {
            maxWidth: '100%',
            maxHeight: '100%',
            width: 'auto',
            height: 'auto',
            cursor: worldPoints.length < 4 ? 'crosshair' : 'default',
          }
        : {
            width: `${WORLD_WIDTH * displayScale}px`,
            height: `${WORLD_HEIGHT * displayScale}px`,
            cursor: worldPoints.length < 4 ? 'crosshair' : 'default',
          }}
    />
  );
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

  const isPointInCalibrationArea = (point: Point, polygon: Point[]) => {
    if (polygon.length < 3) return false;

    const onSegment = (a: Point, b: Point) => {
      const cross = (point.y - a.y) * (b.x - a.x) - (point.x - a.x) * (b.y - a.y);
      if (Math.abs(cross) > 1e-6) return false;
      const dot = (point.x - a.x) * (b.x - a.x) + (point.y - a.y) * (b.y - a.y);
      if (dot < 0) return false;
      const squaredLength = (b.x - a.x) ** 2 + (b.y - a.y) ** 2;
      return dot <= squaredLength;
    };

    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const a = polygon[i];
      const b = polygon[j];
      if (onSegment(a, b)) return true;
      const intersects = ((a.y > point.y) !== (b.y > point.y))
        && (point.x < ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y) + a.x);
      if (intersects) inside = !inside;
    }
    return inside;
  };

  const doTransform = useCallback(async () => {
    if (!laneId || currentVehicles.length === 0) {
      vehicleDotsRef.current = [];
      setTransformedVehicles([]);
      return [];
    }
    if (cameraPoints.length < 3) {
      vehicleDotsRef.current = [];
      setTransformedVehicles([]);
      return [];
    }

    const vehiclesInCalibrationArea = currentVehicles
      .map((vehicle: any) => {
        if (!Array.isArray(vehicle.box) || vehicle.box.length < 4) return null;
        const cameraPoint = {
          x: (vehicle.box[0] + vehicle.box[2]) / 2,
          y: vehicle.box[3],
        };
        return isPointInCalibrationArea(cameraPoint, cameraPoints)
          ? { vehicle, cameraPoint }
          : null;
      })
      .filter((item): item is { vehicle: any; cameraPoint: Point } => Boolean(item));

    if (vehiclesInCalibrationArea.length === 0) {
      vehicleDotsRef.current = [];
      setTransformedVehicles([]);
      return [];
    }

    const points = vehiclesInCalibrationArea.map(({ cameraPoint }) => [cameraPoint.x, cameraPoint.y]);
    try {
      const res = await ipmRequest('/ipm/transform', {
        method: 'POST',
        body: JSON.stringify({ camera_id: cameraId, lane_id: laneId, vehicles: points }),
      });
      if (res.code === 200 && res.data?.transformed) {
        const transformed = res.data.transformed;
        const nextVehicles = vehiclesInCalibrationArea.map(({ vehicle: v }, i: number) => ({
          id: v.id,
          class: v.class,
          camera: points[i],
          world: transformed[i] || null,
        }));
        vehicleDotsRef.current = nextVehicles;
        setTransformedVehicles(nextVehicles);
        return nextVehicles;
      } else {
        vehicleDotsRef.current = [];
        setTransformedVehicles([]);
        return [];
      }
    } catch {
      vehicleDotsRef.current = [];
      setTransformedVehicles([]);
      return [];
    }
  }, [cameraId, laneId, currentVehicles, cameraPoints]);

  const doTransformRef = useRef(doTransform);
  doTransformRef.current = doTransform;

  const redrawWorldCanvases = useCallback(() => {
    drawWorldCanvas(worldCanvasRef.current);
    drawWorldCanvas(fullscreenWorldCanvasRef.current);
  }, [drawWorldCanvas]);

  const renderAnimatedHeatmapLayer = useCallback((time: number) => {
    const source = heatmapColorRef.current;
    if (!source) return;
    if (
      !heatmapAnimatedRef.current
      || heatmapAnimatedRef.current.width !== source.width
      || heatmapAnimatedRef.current.height !== source.height
    ) {
      heatmapAnimatedRef.current = createCanvasElement(source.width, source.height);
    }
    const animated = heatmapAnimatedRef.current;
    renderAnimatedHeatmapCanvas(source, animated, time);
  }, []);

  const ensureHeatmapCanvases = useCallback(() => {
    const heatWidth = Math.max(1, Math.round(WORLD_WIDTH * DEFAULT_HEATMAP_CONFIG.internalScale));
    const heatHeight = Math.max(1, Math.round(WORLD_HEIGHT * DEFAULT_HEATMAP_CONFIG.internalScale));
    if (
      !heatmapColorRef.current
      || heatmapColorRef.current.width !== heatWidth
      || heatmapColorRef.current.height !== heatHeight
    ) {
      heatmapColorRef.current = createCanvasElement(heatWidth, heatHeight);
      heatmapAnimatedRef.current = createCanvasElement(heatWidth, heatHeight);
      heatmapRendererRef.current = null;
    }
    if (
      !heatmapAnimatedRef.current
      || heatmapAnimatedRef.current.width !== heatWidth
      || heatmapAnimatedRef.current.height !== heatHeight
    ) {
      heatmapAnimatedRef.current = createCanvasElement(heatWidth, heatHeight);
    }
    if (!heatmapRendererRef.current) {
      heatmapRendererRef.current = simpleheat(heatmapColorRef.current)
        .radius(
          Math.max(1, DEFAULT_HEATMAP_CONFIG.radius * DEFAULT_HEATMAP_CONFIG.internalScale),
          Math.max(1, DEFAULT_HEATMAP_CONFIG.blur * DEFAULT_HEATMAP_CONFIG.internalScale),
        )
        .gradient(HEATMAP_GRADIENT)
        .max(DEFAULT_HEATMAP_CONFIG.maxHeat);
    }
    return {
      canvas: heatmapColorRef.current,
      renderer: heatmapRendererRef.current,
    };
  }, []);

  const getValidHeatmapVehicles = (vehicles: any[]) => {
    const deduped = new Map<string, HeatmapVehiclePosition>();
    vehicles.forEach((vehicle, index) => {
      if (!Array.isArray(vehicle.world) || vehicle.world.length < 2) return;
      const [worldX, worldY] = vehicle.world;
      if (!Number.isFinite(worldX) || !Number.isFinite(worldY)) return;
      if (worldX < 0 || worldY < 0 || worldX > WORLD_WIDTH || worldY > WORLD_HEIGHT) return;
      const id = String(vehicle.id ?? `${vehicle.class || 'vehicle'}-${index}`);
      deduped.set(id, { id, x: worldX, y: worldY });
    });
    return [...deduped.values()];
  };

  const compactHeatmapSamples = (samples: HeatmapSample[]) => {
    const gridSize = DEFAULT_HEATMAP_CONFIG.sampleGridSize;
    const buckets = new Map<string, { x: number; y: number; value: number; updatedAt: number }>();

    for (const sample of samples) {
      const gx = Math.round(sample.x / gridSize);
      const gy = Math.round(sample.y / gridSize);
      const key = `${gx}:${gy}`;
      const current = buckets.get(key);
      if (!current) {
        buckets.set(key, { ...sample });
        continue;
      }

      const nextValue = Math.min(DEFAULT_HEATMAP_CONFIG.maxHeat, current.value + sample.value);
      const weight = current.value + sample.value || 1;
      current.x = (current.x * current.value + sample.x * sample.value) / weight;
      current.y = (current.y * current.value + sample.y * sample.value) / weight;
      current.value = nextValue;
      current.updatedAt = Math.max(current.updatedAt, sample.updatedAt);
    }

    return [...buckets.values()];
  };

  const updateHeatmapLayer = useCallback((vehicles: any[]) => {
    const { canvas, renderer } = ensureHeatmapCanvases();
    if (canvas.width === 0 || canvas.height === 0) return;

    const now = Date.now();
    const elapsedSteps = Math.max(1, (now - heatmapLastUpdateRef.current) / DEFAULT_HEATMAP_CONFIG.updateInterval);
    const decay = DEFAULT_HEATMAP_CONFIG.decayFactor ** elapsedSteps;
    heatmapSamplesRef.current = heatmapSamplesRef.current
      .map(sample => ({ ...sample, value: sample.value * decay }))
      .filter(sample => sample.value >= DEFAULT_HEATMAP_CONFIG.minSampleValue && now - sample.updatedAt <= DEFAULT_HEATMAP_CONFIG.sampleLifetime);
    heatmapLastUpdateRef.current = now;

    const validVehicles = getValidHeatmapVehicles(vehicles);
    const nextSamples = heatmapSamplesRef.current;

    for (const vehicle of validVehicles) {
      const previous = heatmapVehicleCacheRef.current.get(vehicle.id);
      const alpha = DEFAULT_HEATMAP_CONFIG.smoothingAlpha;
      const x = previous ? alpha * vehicle.x + (1 - alpha) * previous.x : vehicle.x;
      const y = previous ? alpha * vehicle.y + (1 - alpha) * previous.y : vehicle.y;
      const distance = previous ? Math.hypot(x - previous.x, y - previous.y) : 0;
      const steps = previous ? Math.max(1, Math.ceil(distance / DEFAULT_HEATMAP_CONFIG.trailStep)) : 1;

      for (let step = 1; step <= steps; step++) {
        const t = step / steps;
        const px = previous ? previous.x + (x - previous.x) * t : x;
        const py = previous ? previous.y + (y - previous.y) * t : y;
        const trailWeight = previous && step < steps ? 0.62 : 1;
        nextSamples.push({
          x: px,
          y: py,
          value: Math.min(DEFAULT_HEATMAP_CONFIG.maxHeat, DEFAULT_HEATMAP_CONFIG.intensity * trailWeight),
          updatedAt: now,
        });
      }

      heatmapVehicleCacheRef.current.set(vehicle.id, { x, y, lastSeen: now });
    }

    for (const [id, cache] of heatmapVehicleCacheRef.current) {
      if (now - cache.lastSeen > DEFAULT_HEATMAP_CONFIG.vehicleTimeout) {
        heatmapVehicleCacheRef.current.delete(id);
      }
    }

    const compactedSamples = compactHeatmapSamples(nextSamples);
    if (compactedSamples.length > DEFAULT_HEATMAP_CONFIG.maxSamples) {
      compactedSamples.splice(0, compactedSamples.length - DEFAULT_HEATMAP_CONFIG.maxSamples);
    }
    heatmapSamplesRef.current = compactedSamples;

    renderer
      .data(compactedSamples.map(sample => [
        sample.x * DEFAULT_HEATMAP_CONFIG.internalScale,
        sample.y * DEFAULT_HEATMAP_CONFIG.internalScale,
        Math.min(DEFAULT_HEATMAP_CONFIG.maxHeat, sample.value),
      ]))
      .max(DEFAULT_HEATMAP_CONFIG.maxHeat)
      .draw(DEFAULT_HEATMAP_CONFIG.minVisibleHeat);
    heatmapVisibleRef.current = compactedSamples.length > 0;
    renderAnimatedHeatmapLayer(performance.now());
    redrawWorldCanvases();
  }, [ensureHeatmapCanvases, redrawWorldCanvases, renderAnimatedHeatmapLayer]);

  const generateOnce = useCallback(async () => {
    if (generationStatus !== 'idle') return;
    clearHeatmapBuffers();
    const transformed = await doTransform();
    if (isHeatmapMode) updateHeatmapLayer(transformed);
  }, [clearHeatmapBuffers, doTransform, generationStatus, isHeatmapMode, updateHeatmapLayer]);

  useEffect(() => {
    let stopped = false;
    const frameInterval = 1000 / DEFAULT_HEATMAP_CONFIG.animationFps;

    const animateHeatmap = (time: number) => {
      if (stopped) return;
      if (heatmapVisibleRef.current && time - heatmapLastAnimationRef.current >= frameInterval) {
        heatmapLastAnimationRef.current = time;
        renderAnimatedHeatmapLayer(time);
        redrawWorldCanvases();
      }
      heatmapAnimationFrameRef.current = requestAnimationFrame(animateHeatmap);
    };

    heatmapAnimationFrameRef.current = requestAnimationFrame(animateHeatmap);
    return () => {
      stopped = true;
      if (heatmapAnimationFrameRef.current !== null) {
        cancelAnimationFrame(heatmapAnimationFrameRef.current);
      }
    };
  }, [redrawWorldCanvases, renderAnimatedHeatmapLayer]);

  const toggleVisualizationMode = () => {
    if (generationStatus !== 'idle') return;
    clearHeatmapBuffers();
    setIsHeatmapMode(prev => !prev);
    redrawWorldCanvases();
  };

  const toggleContinuousGeneration = () => {
    if (generationStatus === 'idle') {
      sessionHeatmapModeRef.current = isHeatmapMode;
      recordedFramesRef.current = [];
      setRecordedFrameCount(0);
      setGenerationElapsed(0);
      setRecordingTotalElapsed(0);
      setTrafficAnalysis(null);
      clearHeatmapBuffers();
      setGenerationStatus('recording');
      return;
    }
    if (generationStatus === 'recording' && recordedFramesRef.current.length > 0) {
      setGenerationElapsed(0);
      setGenerationStatus('replaying');
      return;
    }
    setGenerationStatus('idle');
  };

  const getReplaySnapshot = () => {
    const recordedFrames = recordedFramesRef.current;
    if (recordedFrames.length === 0) return [];
    const firstElapsed = recordedFrames[0].elapsed;
    return recordedFrames.map(frame => ({
      elapsed: Math.max(0, frame.elapsed - firstElapsed),
      vehicles: frame.vehicles.map(vehicle => ({
        ...vehicle,
        camera: Array.isArray(vehicle.camera) ? [...vehicle.camera] : vehicle.camera,
        world: Array.isArray(vehicle.world) ? [...vehicle.world] : vehicle.world,
      })),
    }));
  };

  const exportReplayVideo = async () => {
    const frames = getReplaySnapshot();
    if (frames.length === 0) {
      setMessage({ type: 'err', text: '暂无可导出的视频回放' });
      return;
    }
    if (typeof MediaRecorder === 'undefined') {
      setMessage({ type: 'err', text: '当前浏览器不支持视频导出，请使用最新版 Chrome 或 Edge' });
      return;
    }
    const mimeType = [
      'video/webm;codecs=vp9',
      'video/webm;codecs=vp8',
      'video/webm',
    ].find(type => MediaRecorder.isTypeSupported(type));
    if (!mimeType) {
      setMessage({ type: 'err', text: '当前浏览器没有可用的 WebM 视频编码器' });
      return;
    }

    setIsExportingVideo(true);
    setVideoExportProgress(0);
    const exportCanvas = createCanvasElement(WORLD_WIDTH, WORLD_HEIGHT);
    const ctx = exportCanvas.getContext('2d');
    const roadBase = getRoadBaseCanvas();
    const exportHeatWidth = Math.max(1, Math.round(WORLD_WIDTH * DEFAULT_HEATMAP_CONFIG.internalScale));
    const exportHeatHeight = Math.max(1, Math.round(WORLD_HEIGHT * DEFAULT_HEATMAP_CONFIG.internalScale));
    const exportHeatCanvas = createCanvasElement(exportHeatWidth, exportHeatHeight);
    const exportAnimatedHeatCanvas = createCanvasElement(exportHeatWidth, exportHeatHeight);
    const exportHeat = simpleheat(exportHeatCanvas)
      .radius(
        Math.max(1, DEFAULT_HEATMAP_CONFIG.radius * DEFAULT_HEATMAP_CONFIG.internalScale),
        Math.max(1, DEFAULT_HEATMAP_CONFIG.blur * DEFAULT_HEATMAP_CONFIG.internalScale),
      )
      .gradient(HEATMAP_GRADIENT)
      .max(DEFAULT_HEATMAP_CONFIG.maxHeat);
    let exportHeatSamples: HeatmapSample[] = [];
    const exportVehicleCache = new Map<string, HeatmapVehicleCache>();
    let exportHeatLastUpdate = 0;
    const heatmapMode = sessionHeatmapModeRef.current;
    const durationMs = Math.max(500, frames.at(-1)?.elapsed ?? 0);
    let lastAppliedFrame = -1;
    let stream: MediaStream | null = null;

    const updateExportHeatmap = (vehicles: any[], now: number) => {
      const elapsedSteps = Math.max(1, (now - exportHeatLastUpdate) / DEFAULT_HEATMAP_CONFIG.updateInterval);
      const decay = DEFAULT_HEATMAP_CONFIG.decayFactor ** elapsedSteps;
      exportHeatSamples = exportHeatSamples
        .map(sample => ({ ...sample, value: sample.value * decay }))
        .filter(sample => sample.value >= DEFAULT_HEATMAP_CONFIG.minSampleValue && now - sample.updatedAt <= DEFAULT_HEATMAP_CONFIG.sampleLifetime);
      exportHeatLastUpdate = now;

      const nextSamples = exportHeatSamples;
      for (const vehicle of getValidHeatmapVehicles(vehicles)) {
        const previous = exportVehicleCache.get(vehicle.id);
        const alpha = DEFAULT_HEATMAP_CONFIG.smoothingAlpha;
        const x = previous ? alpha * vehicle.x + (1 - alpha) * previous.x : vehicle.x;
        const y = previous ? alpha * vehicle.y + (1 - alpha) * previous.y : vehicle.y;
        const distance = previous ? Math.hypot(x - previous.x, y - previous.y) : 0;
        const steps = previous ? Math.max(1, Math.ceil(distance / DEFAULT_HEATMAP_CONFIG.trailStep)) : 1;

        for (let step = 1; step <= steps; step++) {
          const progress = step / steps;
          const px = previous ? previous.x + (x - previous.x) * progress : x;
          const py = previous ? previous.y + (y - previous.y) * progress : y;
          const trailWeight = previous && step < steps ? 0.62 : 1;
          nextSamples.push({
            x: px,
            y: py,
            value: Math.min(DEFAULT_HEATMAP_CONFIG.maxHeat, DEFAULT_HEATMAP_CONFIG.intensity * trailWeight),
            updatedAt: now,
          });
        }
        exportVehicleCache.set(vehicle.id, { x, y, lastSeen: now });
      }

      for (const [id, cache] of exportVehicleCache) {
        if (now - cache.lastSeen > DEFAULT_HEATMAP_CONFIG.vehicleTimeout) exportVehicleCache.delete(id);
      }

      exportHeatSamples = compactHeatmapSamples(nextSamples);
      if (exportHeatSamples.length > DEFAULT_HEATMAP_CONFIG.maxSamples) {
        exportHeatSamples.splice(0, exportHeatSamples.length - DEFAULT_HEATMAP_CONFIG.maxSamples);
      }
      exportHeat
        .data(exportHeatSamples.map(sample => [
          sample.x * DEFAULT_HEATMAP_CONFIG.internalScale,
          sample.y * DEFAULT_HEATMAP_CONFIG.internalScale,
          Math.min(DEFAULT_HEATMAP_CONFIG.maxHeat, sample.value),
        ]))
        .max(DEFAULT_HEATMAP_CONFIG.maxHeat)
        .draw(DEFAULT_HEATMAP_CONFIG.minVisibleHeat);
    };

    const drawFrame = (elapsed: number) => {
      if (!ctx) return;
      while (lastAppliedFrame + 1 < frames.length && frames[lastAppliedFrame + 1].elapsed <= elapsed) {
        lastAppliedFrame += 1;
        if (heatmapMode) {
          updateExportHeatmap(frames[lastAppliedFrame].vehicles, frames[lastAppliedFrame].elapsed);
        }
      }

      ctx.clearRect(0, 0, WORLD_WIDTH, WORLD_HEIGHT);
      if (roadBase) ctx.drawImage(roadBase, 0, 0, WORLD_WIDTH, WORLD_HEIGHT);
      else drawRoadModelBackground(ctx, WORLD_WIDTH, WORLD_HEIGHT);

      const currentIndex = Math.max(0, lastAppliedFrame);
      const currentFrame = frames[currentIndex];
      if (heatmapMode) {
        renderAnimatedHeatmapCanvas(exportHeatCanvas, exportAnimatedHeatCanvas, elapsed);
        ctx.save();
        ctx.globalAlpha = DEFAULT_HEATMAP_CONFIG.opacity;
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(exportAnimatedHeatCanvas, 0, 0, WORLD_WIDTH, WORLD_HEIGHT);
        ctx.restore();
      } else if (currentFrame) {
        for (const vehicle of currentFrame.vehicles) {
          if (!Array.isArray(vehicle.world) || vehicle.world.length < 2) continue;
          const [x, y] = vehicle.world;
          if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
          ctx.beginPath();
          ctx.arc(x, y, 8, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(239, 68, 68, 0.88)';
          ctx.fill();
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 2;
          ctx.stroke();
          ctx.fillStyle = '#ffffff';
          ctx.font = 'bold 11px ui-monospace, monospace';
          ctx.textAlign = 'center';
          ctx.fillText(`#${vehicle.id ?? '?'}`, x, y - 13);
        }
      }

      ctx.save();
      const overlay = ctx.createLinearGradient(0, 0, 0, 58);
      overlay.addColorStop(0, 'rgba(2, 6, 23, 0.88)');
      overlay.addColorStop(1, 'rgba(2, 6, 23, 0.16)');
      ctx.fillStyle = overlay;
      ctx.fillRect(0, 0, WORLD_WIDTH, 58);
      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 18px system-ui, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(`智慧交通沙盘 · ${heatmapMode ? '车辆活动热力图' : '车辆位置回放'}`, 18, 25);
      ctx.font = '13px system-ui, sans-serif';
      ctx.fillStyle = 'rgba(226, 232, 240, 0.95)';
      ctx.fillText(`${cameraId} / ${laneId}    ${(elapsed / 1000).toFixed(1)}s / ${(durationMs / 1000).toFixed(1)}s    当前 ${currentFrame?.vehicles.length ?? 0} 辆`, 18, 47);
      ctx.restore();
    };

    try {
      if (!ctx || typeof exportCanvas.captureStream !== 'function') throw new Error('浏览器不支持 Canvas 视频录制');
      drawFrame(0);
      stream = exportCanvas.captureStream(30);
      const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 4_000_000 });
      const chunks: BlobPart[] = [];
      const videoReady = new Promise<Blob>((resolve, reject) => {
        recorder.ondataavailable = event => { if (event.data.size > 0) chunks.push(event.data); };
        recorder.onerror = event => reject(new Error((event as any).error?.message || '视频编码失败'));
        recorder.onstop = () => resolve(new Blob(chunks, { type: mimeType }));
      });
      recorder.start(250);
      const startedAt = performance.now();
      await new Promise<void>(resolve => {
        const render = (now: number) => {
          const elapsed = Math.min(durationMs, now - startedAt);
          drawFrame(elapsed);
          setVideoExportProgress(Math.round(elapsed / durationMs * 100));
          if (elapsed >= durationMs) resolve();
          else requestAnimationFrame(render);
        };
        requestAnimationFrame(render);
      });
      await new Promise(resolve => window.setTimeout(resolve, 120));
      recorder.stop();
      const video = await videoReady;
      const url = URL.createObjectURL(video);
      const link = document.createElement('a');
      const safeCameraId = cameraId.replace(/[^a-zA-Z0-9_-]/g, '_') || 'camera';
      const safeLaneId = laneId.replace(/[^a-zA-Z0-9_-]/g, '_') || 'lane';
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      link.href = url;
      link.download = `traffic-replay_${safeCameraId}_${safeLaneId}_${timestamp}.webm`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage({ type: 'ok', text: `已导出 ${(durationMs / 1000).toFixed(1)} 秒 WebM 回放视频` });
    } catch (error: any) {
      setMessage({ type: 'err', text: error?.message || '视频导出失败' });
    } finally {
      stream?.getTracks().forEach(track => track.stop());
      setIsExportingVideo(false);
      setVideoExportProgress(0);
    }
  };

  const analyzeRecentTraffic = async () => {
    const frames = getReplaySnapshot();
    if (frames.length === 0) {
      setMessage({ type: 'err', text: '请先使用持续生成记录车辆数据' });
      return;
    }
    setIsAnalyzingTraffic(true);
    try {
      const response = await trafficAnalysisAPI.analyze({
        camera_id: cameraId,
        lane_id: laneId,
        capacity: 3,
        frames: frames.map(frame => ({
          timestamp_ms: Math.round(frame.elapsed),
          vehicles: frame.vehicles.map(vehicle => ({ id: vehicle.id, class: vehicle.class, world: vehicle.world })),
        })),
      });
      setTrafficAnalysis(response.data as TrafficAnalysisResult);
      setMessage({
        type: 'ok',
        text: response.data?.source === 'deepseek-v4' ? 'DeepSeek V4 拥堵分析已完成' : '规则报告已生成（DeepSeek 当前不可用）',
      });
    } catch (error: any) {
      setMessage({ type: 'err', text: error?.message || '拥堵分析失败' });
    } finally {
      setIsAnalyzingTraffic(false);
    }
  };

  // Keep recording until the user stops. Only the latest 15 seconds remain in
  // the rolling playback buffer. The chosen mode is fixed for the session.
  useEffect(() => {
    if (generationStatus !== 'recording') return;
    let stopped = false;
    let busy = false;
    const startedAt = performance.now();

    const captureFrame = async () => {
      if (stopped || busy) return;
      busy = true;
      try {
        const vehicles = await doTransformRef.current();
        if (stopped) return;
        const elapsed = performance.now() - startedAt;
        const frame = {
          elapsed,
          vehicles: vehicles.map(vehicle => ({
            ...vehicle,
            camera: Array.isArray(vehicle.camera) ? [...vehicle.camera] : vehicle.camera,
            world: Array.isArray(vehicle.world) ? [...vehicle.world] : vehicle.world,
          })),
        };
        recordedFramesRef.current.push(frame);
        const cutoff = elapsed - MAX_RECORDING_DURATION;
        if (cutoff > 0) {
          recordedFramesRef.current = recordedFramesRef.current.filter(recordedFrame => recordedFrame.elapsed >= cutoff);
        }
        const bufferDuration = recordedFramesRef.current.length > 1
          ? elapsed - recordedFramesRef.current[0].elapsed
          : 0;
        setRecordedFrameCount(recordedFramesRef.current.length);
        setRecordingTotalElapsed(elapsed);
        setGenerationElapsed(bufferDuration);
        if (sessionHeatmapModeRef.current) updateHeatmapLayer(frame.vehicles);
      } finally {
        busy = false;
      }
    };

    captureFrame();
    const captureTimer = window.setInterval(captureFrame, DEFAULT_HEATMAP_CONFIG.updateInterval);

    return () => {
      stopped = true;
      window.clearInterval(captureTimer);
    };
  }, [generationStatus, updateHeatmapLayer]);

  // Play every recorded coordinate snapshot back with its original timing.
  useEffect(() => {
    if (generationStatus !== 'replaying') return;
    const recordedFrames = recordedFramesRef.current;
    if (recordedFrames.length === 0) {
      setGenerationStatus('idle');
      return;
    }
    const firstElapsed = recordedFrames[0].elapsed;
    const frames = recordedFrames.map(frame => ({
      ...frame,
      elapsed: frame.elapsed - firstElapsed,
    }));
    recordedFramesRef.current = frames;

    clearHeatmapBuffers();
    if (sessionHeatmapModeRef.current) {
      vehicleDotsRef.current = [];
      setTransformedVehicles([]);
    }
    const timers: number[] = [];
    for (const frame of frames) {
      timers.push(window.setTimeout(() => {
        vehicleDotsRef.current = frame.vehicles;
        setTransformedVehicles(frame.vehicles);
        setGenerationElapsed(frame.elapsed);
        if (sessionHeatmapModeRef.current) updateHeatmapLayer(frame.vehicles);
      }, frame.elapsed));
    }
    timers.push(window.setTimeout(() => {
      setGenerationStatus('idle');
      setMessage({ type: 'ok', text: `已完成 ${(frames.at(-1)!.elapsed / 1000).toFixed(1)} 秒回放` });
    }, frames.at(-1)!.elapsed + DEFAULT_HEATMAP_CONFIG.updateInterval));

    return () => timers.forEach(timer => window.clearTimeout(timer));
  }, [clearHeatmapBuffers, generationStatus, updateHeatmapLayer]);

  return (
    <div className="space-y-6">
      <div className="dashboard-card p-6">
        <h2 className="text-xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
          <MapPin className="text-emerald-400" /> 热力图
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
          <label className="text-xs text-[var(--color-text-secondary)] block mb-2">已标定车道（点击选择 · {cameraLanes.length}）</label>
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

      {/* Main Layout Area */}
      <div className="flex flex-col xl:flex-row gap-6 items-start">
        
        {/* Left Column: Camera & Data Tables */}
        <div className="w-full xl:w-5/12 flex flex-col gap-6 shrink-0">
          
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
            <div className="relative w-full rounded-xl overflow-hidden bg-gray-100 dark:bg-[#0F1013] border border-[var(--color-border-card)]" style={{ aspectRatio: videoAspectRatio }}>
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

          {/* Transform verification */}
          <div className="dashboard-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-gray-900 dark:text-gray-200 flex items-center gap-2">
                <Crosshair size={16} className="text-rose-400" /> 俯视坐标验证
              </h3>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <span className="text-xs text-[var(--color-text-secondary)]">当前 {currentVehicles.length} 辆车</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={isHeatmapMode}
                  onClick={toggleVisualizationMode}
                  disabled={generationStatus !== 'idle'}
                  className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs font-semibold border border-[var(--color-border-card)] bg-white/70 dark:bg-[#17191f] text-[var(--color-text-secondary)] disabled:opacity-50 disabled:cursor-not-allowed"
                  title="关闭显示车辆红点，开启渲染热力图"
                >
                  <span className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors ${isHeatmapMode ? 'bg-amber-500' : 'bg-slate-500'}`}>
                    <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${isHeatmapMode ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
                  </span>
                  {isHeatmapMode ? '热力图' : '车辆位置'}
                </button>
                <button
                  onClick={generateOnce}
                  disabled={generationStatus !== 'idle' || !laneId || currentVehicles.length === 0}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-blue-500/20 text-blue-400 border border-blue-500/30 hover:bg-blue-500/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <Crosshair size={12} /> 生成一次
                </button>
                <button
                  onClick={toggleContinuousGeneration}
                  disabled={generationStatus === 'idle' && (!laneId || currentVehicles.length === 0)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                    generationStatus !== 'idle'
                      ? 'bg-rose-500/15 text-rose-400 border-rose-500/30 hover:bg-rose-500/25'
                      : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/25'
                  }`}
                >
                  <RefreshCw size={12} className={generationStatus !== 'idle' ? 'animate-spin' : ''} />
                  {generationStatus === 'recording' ? '停止并回放' : generationStatus === 'replaying' ? '停止回放' : '持续生成'}
                </button>
                <button
                  type="button"
                  onClick={exportReplayVideo}
                  disabled={recordedFrameCount === 0 || isExportingVideo}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-violet-500/15 text-violet-400 border border-violet-500/30 hover:bg-violet-500/25 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  title="将最近 15 秒白板回放导出为 WebM 视频"
                >
                  <Download size={12} /> {isExportingVideo ? `生成视频 ${videoExportProgress}%` : '导出视频'}
                </button>
                <button
                  type="button"
                  onClick={analyzeRecentTraffic}
                  disabled={recordedFrameCount === 0 || isAnalyzingTraffic}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-cyan-500/15 text-cyan-400 border border-cyan-500/30 hover:bg-cyan-500/25 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  title="使用最近 15 秒车辆数量生成 DeepSeek V4 拥堵报告"
                >
                  <BrainCircuit size={12} className={isAnalyzingTraffic ? 'animate-pulse' : ''} />
                  {isAnalyzingTraffic ? '分析中...' : 'AI 拥堵分析'}
                </button>
              </div>
            </div>
            {(generationStatus !== 'idle' || recordedFrameCount > 0) && (
              <div className="mb-4 rounded-lg border border-[var(--color-border-card)] bg-gray-50/70 dark:bg-[#15171c]/70 px-3 py-2">
                <div className="mb-1.5 flex items-center justify-between text-xs">
                  <span className={generationStatus === 'recording' ? 'text-rose-400' : generationStatus === 'replaying' ? 'text-blue-400' : 'text-[var(--color-text-secondary)]'}>
                    {generationStatus === 'recording' ? '正在持续记录（保留最近 15 秒）' : generationStatus === 'replaying' ? '正在回放最近 15 秒' : '最近一次记录'}
                  </span>
                  <span className="font-mono text-[var(--color-text-secondary)]">
                    {generationStatus === 'recording' && `已记录 ${(recordingTotalElapsed / 1000).toFixed(1)}s · `}
                    缓存/回放 {(generationElapsed / 1000).toFixed(1)}s · {recordedFrameCount} 帧
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-[#292c34]">
                  <div className={`h-full rounded-full transition-[width] ${generationStatus === 'replaying' ? 'bg-blue-500' : 'bg-rose-500'}`} style={{ width: `${Math.min(100, generationElapsed / MAX_RECORDING_DURATION * 100)}%` }} />
                </div>
              </div>
            )}
            {trafficAnalysis && (
              <div className="mb-4 rounded-xl border border-cyan-500/25 bg-cyan-500/5 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <BrainCircuit size={17} className="text-cyan-400" />
                      <h4 className="text-sm font-semibold text-[var(--color-text-primary)]">沙盘路段拥堵报告</h4>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${trafficAnalysis.source === 'deepseek-v4' ? 'bg-cyan-500/15 text-cyan-400' : 'bg-amber-500/15 text-amber-400'}`}>
                        {trafficAnalysis.source === 'deepseek-v4' ? 'DeepSeek V4' : '规则兜底'}
                      </span>
                    </div>
                    <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--color-text-secondary)]">{trafficAnalysis.report.summary}</p>
                  </div>
                  <div className="flex gap-2 text-center">
                    <div className="min-w-20 rounded-lg border border-[var(--color-border-card)] bg-white/60 px-3 py-2 dark:bg-[#17191f]/70">
                      <div className="text-lg font-bold text-cyan-400">{trafficAnalysis.report.score}</div>
                      <div className="text-[10px] text-[var(--color-text-muted)]">拥堵分数</div>
                    </div>
                    <div className="min-w-20 rounded-lg border border-[var(--color-border-card)] bg-white/60 px-3 py-2 dark:bg-[#17191f]/70">
                      <div className="text-sm font-bold text-amber-400">{trafficAnalysis.report.overall_level}</div>
                      <div className="mt-1 text-[10px] text-[var(--color-text-muted)]">{trafficAnalysis.report.trend}</div>
                    </div>
                  </div>
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border border-[var(--color-border-card)] p-3 text-xs">
                    <div className="mb-2 font-semibold text-[var(--color-text-primary)]">数量指标</div>
                    <div className="space-y-1 text-[var(--color-text-secondary)]">
                      <div>平均车辆：{trafficAnalysis.metrics.average_count} 辆</div>
                      <div>最高车辆：{trafficAnalysis.metrics.maximum_count} 辆</div>
                      <div>满载占比：{Math.round(trafficAnalysis.metrics.full_capacity_ratio * 100)}%</div>
                    </div>
                  </div>
                  <div className="rounded-lg border border-[var(--color-border-card)] p-3 text-xs">
                    <div className="mb-2 font-semibold text-[var(--color-text-primary)]">判断依据</div>
                    <ul className="space-y-1 text-[var(--color-text-secondary)]">
                      {trafficAnalysis.report.evidence.slice(0, 3).map((item, index) => <li key={index}>· {item}</li>)}
                    </ul>
                  </div>
                  <div className="rounded-lg border border-[var(--color-border-card)] p-3 text-xs">
                    <div className="mb-2 font-semibold text-[var(--color-text-primary)]">处置建议</div>
                    <ul className="space-y-1 text-[var(--color-text-secondary)]">
                      {trafficAnalysis.report.recommendations.slice(0, 3).map((item, index) => <li key={index}>· {item}</li>)}
                    </ul>
                  </div>
                </div>
                {trafficAnalysis.llm_error && (
                  <p className="mt-3 text-[10px] text-amber-400">DeepSeek 未调用：{trafficAnalysis.llm_error}</p>
                )}
              </div>
            )}
            {transformedVehicles.length === 0 ? (
              <p className="text-[var(--color-text-muted)] text-sm py-4 text-center">
                {!laneId ? '请先选择车道 ID' : currentVehicles.length === 0 ? '等待车辆检测数据...' : '转换中...'}
              </p>
            ) : (
              <div className="overflow-x-auto max-h-[220px] overflow-y-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-[var(--color-border-card)] text-[var(--color-text-secondary)] uppercase tracking-wider sticky top-0 bg-[var(--color-bg-card)]">
                      <th className="py-2 px-2">ID</th>
                      <th className="py-2 px-2">类型</th>
                      <th className="py-2 px-2">摄像坐标</th>
                      <th className="py-2 px-2">俯视坐标</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--color-border-card)]">
                    {transformedVehicles.map((v: any, i: number) => (
                      <tr key={i} className="hover:hover:bg-gray-100 dark:hover:bg-[#1C1E24]/40 transition-colors">
                        <td className="py-2 px-2 font-mono text-blue-400">#{v.id}</td>
                        <td className="py-2 px-2 text-[var(--color-text-primary)] capitalize">{v.class}</td>
                        <td className="py-2 px-2 font-mono text-[var(--color-text-secondary)]">
                          ({v.camera[0].toFixed(0)}, {v.camera[1].toFixed(0)})
                        </td>
                        <td className="py-2 px-2 font-mono text-emerald-400">
                          {v.world ? `(${v.world[0].toFixed(1)}, ${v.world[1].toFixed(1)})` : '-'}
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
                <RefreshCw size={16} className="text-blue-400" />
                已标定车道（{cameraId} · {cameraLanes.length}）
              </h3>
              <button onClick={loadConfigs} className="text-xs text-blue-400 hover:text-blue-300 transition-colors">刷新</button>
            </div>
            {cameraLanes.length === 0 ? (
              <p className="text-[var(--color-text-muted)] text-sm py-4 text-center">当前摄像头暂无标定车道</p>
            ) : (
              <div className="space-y-3 max-h-[180px] overflow-y-auto pr-2">
                {cameraLanes.map((lid: string) => (
                  <div key={`${cameraId}/${lid}`} className="flex items-center justify-between bg-white/90 dark:bg-[#1C1C22]/90 border border-[var(--color-border-card)] rounded-xl px-4 py-2 hover:border-[var(--color-border-card)] transition-colors">
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-mono text-blue-400">{cameraId}</span>
                      <span className="text-xs text-[var(--color-text-muted)]">/</span>
                      <span className="text-sm font-semibold text-gray-900 dark:text-gray-200">{lid}</span>
                    </div>
                    <button onClick={() => handleDelete(cameraId, lid)} className="text-rose-500/80 hover:text-rose-400 hover:bg-rose-500/10 p-1.5 rounded-lg transition-colors">
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: World panel (Whiteboard) */}
        <div className="w-full xl:w-7/12 flex flex-col">
          <div className="dashboard-card p-6 h-full min-h-[760px] flex flex-col">
            <div className="flex items-center justify-between mb-3 shrink-0">
              <h3 className="font-semibold text-gray-900 dark:text-gray-200 flex items-center gap-2"><Move size={16} className="text-blue-400" /> 俯视图（白板）</h3>
              <div className="flex items-center gap-3">
                <span className="text-xs text-[var(--color-text-secondary)]">{worldPoints.length}/4 点</span>
                <button onClick={() => setWorldPoints([])} className="text-xs text-[var(--color-text-muted)] hover:text-rose-400 transition-colors">清除</button>
                <button
                  type="button"
                  onClick={() => setIsWorldFullscreen(true)}
                  className="p-2 rounded-lg border border-[var(--color-border-card)] bg-white/90 dark:bg-[#1C1C22]/90 text-[var(--color-text-secondary)] hover:text-blue-400 hover:border-blue-500/40 transition-colors"
                  title="全屏"
                >
                  <Maximize2 size={16} />
                </button>
              </div>
            </div>
            <div
              ref={worldScrollRef}
              onMouseDown={handleWhiteboardPanStart}
              onContextMenu={e => e.preventDefault()}
              className="relative flex-1 rounded-xl overflow-auto bg-[#2f3538] border border-[var(--color-border-card)]"
            >
              {renderWhiteboardCanvas(worldCanvasRef)}
            </div>
          </div>
        </div>
      </div>

      {isWorldFullscreen && (
        <div className="fixed inset-0 z-50 bg-black/55 dark:bg-black/75 backdrop-blur-sm p-4 sm:p-6 flex items-center justify-center">
          <div className="dashboard-card w-full h-full max-w-[1600px] p-4 sm:p-5 flex flex-col shadow-2xl">
            <div className="flex items-center justify-between gap-3 mb-3 shrink-0">
              <h3 className="font-semibold text-gray-900 dark:text-gray-200 flex items-center gap-2">
                <Move size={16} className="text-blue-400" /> 俯视图（白板）
              </h3>
              <div className="flex items-center gap-3">
                <span className="text-xs text-[var(--color-text-secondary)]">{worldPoints.length}/4 点</span>
                <button
                  type="button"
                  onClick={() => setIsWorldFullscreen(false)}
                  className="p-2 rounded-lg border border-[var(--color-border-card)] bg-white/90 dark:bg-[#1C1C22]/90 text-[var(--color-text-secondary)] hover:text-rose-400 hover:border-rose-500/40 transition-colors"
                  title="关闭"
                >
                  <X size={16} />
                </button>
              </div>
            </div>
            <div
              ref={fullscreenWorldScrollRef}
              onContextMenu={e => e.preventDefault()}
              className="relative flex-1 rounded-xl overflow-hidden bg-[#2f3538] border border-[var(--color-border-card)] flex items-center justify-center"
            >
              {renderWhiteboardCanvas(fullscreenWorldCanvasRef, WORLD_DISPLAY_SCALE, true)}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
