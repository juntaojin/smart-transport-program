import { useEffect, useState, useRef } from 'react';
import { DashboardWebSocket, type FrameMeta } from '../services/ws';
import { statsAPI, configAPI, streamAPI, anomalyAPI } from '../services/api';
import { Activity, ShieldAlert, Car, PenTool, Trash2 } from 'lucide-react';

interface Vehicle {
  id: number;
  class: string;
  box: number[];
  plate: string;
  world_coord?: number[];
}

interface RecentPlate {
  vehicle: Vehicle;
  seenAt: number;
}

interface RecentViolation {
  violation: Violation;
  seenAt: number;
}

interface RecentAnomaly {
  anomaly: Anomaly;
  seenAt: number;
}

interface SandCamera {
  id: string;
  name: string;
  url: string;
}

interface Violation {
  vehicle_id: string;
  zone_name: string;
  duration: number;
}

interface Anomaly {
  box: number[];
  confidence: number;
  label: string;
}

interface ModelConfig {
  model_name: string;
  enabled: boolean;
}

const ALERT_HOLD_MS = 1000;

const getViolationKey = (violation: Violation) =>
  `${violation.vehicle_id || ''}:${violation.zone_name || ''}`;

const getAnomalyKey = (anomaly: Anomaly) =>
  `${anomaly.label || 'road_anomaly'}:${(anomaly.box || []).map(point => Math.round(point)).join(',')}`;



export default function Dashboard() {
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');
  const [hasFrame, setHasFrame] = useState(false);
  const [fps, setFps] = useState<number>(0);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [recentPlates, setRecentPlates] = useState<Vehicle[]>([]);
  const [violations, setViolations] = useState<Violation[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [sandCameras, setSandCameras] = useState<SandCamera[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('default');
  const [activeRtspDevices, setActiveRtspDevices] = useState<string[]>([]);
  const [videoAspectRatio, setVideoAspectRatio] = useState('16 / 9');
  const [isViolationDetectionEnabled, setIsViolationDetectionEnabled] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const latestFrameRef = useRef<string | null>(null);
  const selectedDeviceRef = useRef(selectedDeviceId);
  const activeRtspDevicesRef = useRef(activeRtspDevices);
  const frameUrlsRef = useRef<Record<string, string>>({});
  const payloadsRef = useRef<Record<string, any>>({});
  const plateCacheRef = useRef<Record<string, Map<string, RecentPlate>>>({});
  const violationCacheRef = useRef<Record<string, Map<string, RecentViolation>>>({});
  const anomalyCacheRef = useRef<Record<string, Map<string, RecentAnomaly>>>({});
  const aspectRef = useRef(videoAspectRatio);
  
  // Zone drawing state (use refs for canvas render closure)
  const [isDrawing, setIsDrawing] = useState(false);
  const [currentZonePoints, setCurrentZonePoints] = useState<{x: number, y: number}[]>([]);
  const [zoneName, setZoneName] = useState('禁停区');
  const [existingZones, setExistingZones] = useState<any[]>([]);
  const frameSizeRef = useRef({ w: 1280, h: 720, offX: 0, offY: 0, scaleW: 0, scaleH: 0 });
  const zonesForRender = useRef<any[]>([]);
  const pointsForRender = useRef<{x: number, y: number}[]>([]);
  const vehiclesForRender = useRef<Vehicle[]>([]);
  const anomaliesForRender = useRef<Anomaly[]>([]);
  const isViolationDetectionEnabledRef = useRef(isViolationDetectionEnabled);
  // Keep refs in sync with state for render closure
  selectedDeviceRef.current = selectedDeviceId;
  activeRtspDevicesRef.current = activeRtspDevices;
  aspectRef.current = videoAspectRatio;
  zonesForRender.current = isViolationDetectionEnabled ? existingZones : [];
  pointsForRender.current = isViolationDetectionEnabled ? currentZonePoints : [];
  vehiclesForRender.current = vehicles;
  anomaliesForRender.current = anomalies;
  isViolationDetectionEnabledRef.current = isViolationDetectionEnabled;
  
  // System Metrics
  const [metrics, setMetrics] = useState({
    cpu_usage: 0,
    gpu_usage: null as number | null,
    memory_usage: 0,
    disk_usage: 0,
    network_rx: 0,
    network_tx: 0,
    
    // Detailed metrics from backend
    cpu_details: null as { cores_physical: number; cores_logical: number; frequency_current_mhz: number; frequency_max_mhz: number } | null,
    memory_details: null as { total_gb: number; used_gb: number; free_gb: number } | null,
    disk_details: null as { total_gb: number; used_gb: number; free_gb: number } | null,
    gpu_details: null as { name: string; load: number; memory_total: number; memory_used: number; memory_percent: number; temperature: number } | null
  });

  const wsRef = useRef<DashboardWebSocket | null>(null);

  // Fetch metrics history on mount
  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const res = await statsAPI.system(15);
        if (res.code === 200) {
          if (res.data.realtime) {
            const rt = res.data.realtime;
            setMetrics({
              cpu_usage: rt.cpu_usage,
              gpu_usage: rt.gpu_usage,
              memory_usage: rt.memory_usage,
              disk_usage: rt.disk_usage,
              network_rx: rt.network_rx,
              network_tx: rt.network_tx,
              cpu_details: rt.cpu_details,
              memory_details: rt.memory_details,
              disk_details: rt.disk_details,
              gpu_details: rt.gpu_details
            });
          }
        }
      } catch (err) {
        console.error('Failed to load metrics history:', err);
      }
    };
    fetchHistory();
    const interval = setInterval(fetchHistory, 15000);
    return () => clearInterval(interval);
  }, []);

  // Load existing no-parking zones
  useEffect(() => {
    const loadZones = async () => {
      try {
        const res = await configAPI.getZones();
        if (res.code === 200 && Array.isArray(res.data)) {
          setExistingZones(res.data);
        }
      } catch {}
    };
    loadZones();
  }, []);

  useEffect(() => {
    const loadSandCameras = async () => {
      try {
        const res = await streamAPI.cameras();
        if (res.code === 200 && Array.isArray(res.data)) {
          setSandCameras(res.data);
        }
      } catch (err) {
        console.error('Failed to load sand table cameras:', err);
      }
    };
    loadSandCameras();
  }, []);

  useEffect(() => {
    let cancelled = false;

    const loadModelControls = async () => {
      try {
        const res = await configAPI.getModels();
        if (cancelled || res.code !== 200 || !Array.isArray(res.data)) return;

        const violationConfig = (res.data as ModelConfig[])
          .find(config => config.model_name === 'violation_detection');
        const enabled = Boolean(violationConfig?.enabled);
        setIsViolationDetectionEnabled(enabled);
        if (!enabled) {
          setIsDrawing(false);
          setCurrentZonePoints([]);
        }
      } catch (err) {
        console.error('Failed to load model controls:', err);
      }
    };

    loadModelControls();
    const interval = window.setInterval(loadModelControls, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  const activeSandCameras = sandCameras.filter(camera => activeRtspDevices.includes(`rtsp_${camera.id}`));

  const normalizeDeviceId = (deviceId?: string) => deviceId?.startsWith('rtsp_') ? deviceId : 'default';

  const applyPayload = (data: any) => {
    const deviceId = normalizeDeviceId(data.device_id);
    const now = Date.now();

    if (data.fps !== undefined) setFps(data.fps);
    if (Array.isArray(data.vehicles)) {
      const cache = plateCacheRef.current[deviceId] || new Map<string, RecentPlate>();
      plateCacheRef.current[deviceId] = cache;

      const currentVehicles = data.vehicles.map((vehicle: Vehicle) => {
        if (vehicle.id == null) return vehicle;
        const key = String(vehicle.id);
        if (vehicle.plate) {
          cache.set(key, { vehicle, seenAt: now });
          return vehicle;
        }
        const cached = cache.get(key);
        return cached && now - cached.seenAt < 1000
          ? { ...vehicle, plate: cached.vehicle.plate }
          : vehicle;
      });

      for (const [key, entry] of cache) {
        if (now - entry.seenAt >= 1000) cache.delete(key);
      }
      setVehicles(currentVehicles);
      setRecentPlates(Array.from(cache.values()).map(entry => entry.vehicle));
    }
    if (Array.isArray(data.violations)) {
      const cache = violationCacheRef.current[deviceId] || new Map<string, RecentViolation>();
      violationCacheRef.current[deviceId] = cache;

      for (const violation of data.violations) {
        cache.set(getViolationKey(violation), { violation, seenAt: now });
      }
      for (const [key, entry] of cache) {
        if (now - entry.seenAt >= ALERT_HOLD_MS) cache.delete(key);
      }
      setViolations(Array.from(cache.values()).map(entry => entry.violation));
    }
    if (Array.isArray(data.anomalies)) {
      const cache = anomalyCacheRef.current[deviceId] || new Map<string, RecentAnomaly>();
      anomalyCacheRef.current[deviceId] = cache;

      for (const anomaly of data.anomalies) {
        cache.set(getAnomalyKey(anomaly), { anomaly, seenAt: now });
      }
      for (const [key, entry] of cache) {
        if (now - entry.seenAt >= ALERT_HOLD_MS) cache.delete(key);
      }
      setAnomalies(Array.from(cache.values()).map(entry => entry.anomaly));
    }

    if (data.system_metrics) {
      setMetrics({
        cpu_usage: data.system_metrics.cpu.percent,
        gpu_usage: data.system_metrics.gpu ? data.system_metrics.gpu.load : null,
        memory_usage: data.system_metrics.memory.percent,
        disk_usage: data.system_metrics.disk.percent,
        network_rx: data.system_metrics.network.rx_mbps,
        network_tx: data.system_metrics.network.tx_mbps,
        cpu_details: data.system_metrics.cpu,
        memory_details: data.system_metrics.memory,
        disk_details: data.system_metrics.disk,
        gpu_details: data.system_metrics.gpu
      });
    }
  };

  const clearStreamResults = () => {
    latestFrameRef.current = null;
    setHasFrame(false);
    setFps(0);
    setVehicles([]);
    setRecentPlates([]);
    setViolations([]);
    setAnomalies([]);
    delete plateCacheRef.current[selectedDeviceRef.current];
    delete violationCacheRef.current[selectedDeviceRef.current];
    delete anomalyCacheRef.current[selectedDeviceRef.current];
  };

  const removeCachedStream = (deviceId: string) => {
    const frameUrl = frameUrlsRef.current[deviceId];
    if (frameUrl?.startsWith('blob:')) URL.revokeObjectURL(frameUrl);
    delete frameUrlsRef.current[deviceId];
    delete payloadsRef.current[deviceId];
    delete plateCacheRef.current[deviceId];
    delete violationCacheRef.current[deviceId];
    delete anomalyCacheRef.current[deviceId];
  };

  useEffect(() => {
    const timer = window.setInterval(() => {
      const deviceId = selectedDeviceRef.current;
      const now = Date.now();
      const plateCache = plateCacheRef.current[deviceId];
      let platesChanged = false;
      if (plateCache) {
        for (const [key, entry] of plateCache) {
          if (now - entry.seenAt >= ALERT_HOLD_MS) {
            plateCache.delete(key);
            platesChanged = true;
          }
        }
      }
      if (platesChanged && plateCache) {
        setRecentPlates(Array.from(plateCache.values()).map(entry => entry.vehicle));
      }

      const violationCache = violationCacheRef.current[deviceId];
      let violationsChanged = false;
      if (violationCache) {
        for (const [key, entry] of violationCache) {
          if (now - entry.seenAt >= ALERT_HOLD_MS) {
            violationCache.delete(key);
            violationsChanged = true;
          }
        }
      }
      if (violationsChanged && violationCache) {
        setViolations(Array.from(violationCache.values()).map(entry => entry.violation));
      }

      const anomalyCache = anomalyCacheRef.current[deviceId];
      let anomaliesChanged = false;
      if (anomalyCache) {
        for (const [key, entry] of anomalyCache) {
          if (now - entry.seenAt >= ALERT_HOLD_MS) {
            anomalyCache.delete(key);
            anomaliesChanged = true;
          }
        }
      }
      if (anomaliesChanged && anomalyCache) {
        setAnomalies(Array.from(anomalyCache.values()).map(entry => entry.anomaly));
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, []);

  const handleStreamStopped = (deviceId: string) => {
    removeCachedStream(deviceId);

    let fallback: string | undefined;
    if (deviceId.startsWith('rtsp_')) {
      const remainingRtspDevices = activeRtspDevicesRef.current.filter(id => id !== deviceId);
      activeRtspDevicesRef.current = remainingRtspDevices;
      setActiveRtspDevices(remainingRtspDevices);
      fallback = remainingRtspDevices[0];
    }

    if (selectedDeviceRef.current !== deviceId) return;
    if (fallback) {
      selectedDeviceRef.current = fallback;
      setSelectedDeviceId(fallback);
      latestFrameRef.current = frameUrlsRef.current[fallback] || null;
      setHasFrame(Boolean(latestFrameRef.current));
      const payload = payloadsRef.current[fallback];
      if (payload) applyPayload(payload);
      return;
    }

    selectedDeviceRef.current = 'default';
    setSelectedDeviceId('default');
    removeCachedStream('default');
    clearStreamResults();
  };

  const selectDevice = (deviceId: string) => {
    if (deviceId.startsWith("rtsp_")) anomalyAPI.reset(deviceId).catch(() => {});
    selectedDeviceRef.current = deviceId;
    setSelectedDeviceId(deviceId);
    const frameUrl = frameUrlsRef.current[deviceId];
    latestFrameRef.current = frameUrl || null;
    setHasFrame(Boolean(frameUrl));
    const payload = payloadsRef.current[deviceId];
    if (payload) applyPayload(payload);
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

        activeRtspDevicesRef.current = activeIds;
        setActiveRtspDevices(activeIds);

        const selectedDevice = selectedDeviceRef.current;
        const shouldSelectFirstSandCamera = selectedDevice === 'default'
          && activeIds.length > 0;
        const selectedRtspStopped = selectedDevice.startsWith('rtsp_')
          && !activeSet.has(selectedDevice);

        if (shouldSelectFirstSandCamera || selectedRtspStopped) {
          const fallback = activeIds[0] || 'default';
          selectedDeviceRef.current = fallback;
          setSelectedDeviceId(fallback);
          if (fallback === 'default') {
            removeCachedStream('default');
            clearStreamResults();
          } else {
            latestFrameRef.current = frameUrlsRef.current[fallback] || null;
            setHasFrame(Boolean(latestFrameRef.current));
            const payload = payloadsRef.current[fallback];
            if (payload) applyPayload(payload);
          }
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

  // Connect WebSocket
  useEffect(() => {
    const onImage = (blob: Blob, meta: FrameMeta) => {
      const deviceId = normalizeDeviceId(meta.deviceId);
      const url = URL.createObjectURL(blob);
      const previous = frameUrlsRef.current[deviceId];
      if (previous) URL.revokeObjectURL(previous);
      frameUrlsRef.current[deviceId] = url;
      if (deviceId.startsWith('rtsp_')) {
        if (!activeRtspDevicesRef.current.includes(deviceId)) {
          activeRtspDevicesRef.current = [...activeRtspDevicesRef.current, deviceId];
          setActiveRtspDevices(activeRtspDevicesRef.current);
        }
        if (selectedDeviceRef.current === 'default') {
          selectedDeviceRef.current = deviceId;
          setSelectedDeviceId(deviceId);
          latestFrameRef.current = url;
          setHasFrame(true);
        }
      }
      if (selectedDeviceRef.current === deviceId) {
        latestFrameRef.current = url;
        setHasFrame(true);
      }
    };

    const onMessage = (data: any) => {
      const deviceId = normalizeDeviceId(data.device_id);
      if (data.type === 'stream_status' && data.status === 'stopped') {
        handleStreamStopped(deviceId);
        return;
      }
      if (data.image) {
        frameUrlsRef.current[deviceId] = data.image;
        if (selectedDeviceRef.current === deviceId) {
          latestFrameRef.current = data.image;
          setHasFrame(true);
        }
      }
      payloadsRef.current[deviceId] = data;
      if (deviceId.startsWith('rtsp_')) {
        if (!activeRtspDevicesRef.current.includes(deviceId)) {
          activeRtspDevicesRef.current = [...activeRtspDevicesRef.current, deviceId];
          setActiveRtspDevices(activeRtspDevicesRef.current);
        }
        if (selectedDeviceRef.current === 'default') {
          selectedDeviceRef.current = deviceId;
          setSelectedDeviceId(deviceId);
          latestFrameRef.current = frameUrlsRef.current[deviceId] || null;
          setHasFrame(Boolean(latestFrameRef.current));
          applyPayload(data);
        }
      }
      if (selectedDeviceRef.current === deviceId) applyPayload(data);
    };

    const onStatus = (status: any) => {
      setWsStatus(status);
    };

    wsRef.current = new DashboardWebSocket(onMessage, onImage, onStatus);
    wsRef.current.connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.stop();
      }
      for (const url of Object.values(frameUrlsRef.current)) {
        if (url.startsWith('blob:')) URL.revokeObjectURL(url);
      }
      frameUrlsRef.current = {};
    };
  }, []);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const img = new Image();
    let pendingFrame: string | null = null;
    let animating = true;
    let canvasW = 0;
    let canvasH = 0;

    // Use ResizeObserver to detect actual container size changes
    const parent = canvas.parentElement;
    if (parent) {
      const ro = new ResizeObserver(entries => {
        for (const entry of entries) {
          const w = entry.contentRect.width;
          const h = entry.contentRect.height;
          if (Math.abs(canvasW - w) > 2 || Math.abs(canvasH - h) > 2) {
            canvasW = w;
            canvasH = h;
            canvas.width = w;
            canvas.height = h;
          }
        }
      });
      ro.observe(parent);
    }

    const render = () => {
      if (!animating) return;
      const currentFrame = latestFrameRef.current;
      if (currentFrame && currentFrame !== pendingFrame) {
        pendingFrame = currentFrame;
        img.onload = () => {
          if (!animating || !canvasW || !canvasH) return;
          const scale = Math.min(
            canvasW / img.naturalWidth,
            canvasH / img.naturalHeight
          );
          const sw = img.naturalWidth * scale;
          const sh = img.naturalHeight * scale;
          const sx = (canvasW - sw) / 2;
          const sy = (canvasH - sh) / 2;
          ctx.clearRect(0, 0, canvasW, canvasH);
          ctx.drawImage(img, sx, sy, sw, sh);
          
          // Draw zones overlay (use refs to avoid stale closure)
          const fw = img.naturalWidth;
          const fh = img.naturalHeight;
          const nextAspect = `${fw} / ${fh}`;
          if (aspectRef.current !== nextAspect) {
            aspectRef.current = nextAspect;
            setVideoAspectRatio(nextAspect);
          }
          frameSizeRef.current = { w: fw, h: fh, offX: sx, offY: sy, scaleW: sw, scaleH: sh };
          // AI results update independently from the video. Reuse the latest boxes
          // on every incoming frame so slow inference never stalls video playback.
          for (const vehicle of vehiclesForRender.current) {
            if (!vehicle.box || vehicle.box.length < 4) continue;
            const [x1, y1, x2, y2] = vehicle.box;
            const left = sx + x1 / fw * sw;
            const top = sy + y1 / fh * sh;
            const width = (x2 - x1) / fw * sw;
            const height = (y2 - y1) / fh * sh;
            ctx.strokeStyle = '#22c55e';
            ctx.lineWidth = 2;
            ctx.strokeRect(left, top, width, height);
            const label = [
              vehicle.id != null ? `ID:${vehicle.id}` : '',
              vehicle.class,
              vehicle.plate || '',
            ].filter(Boolean).join(' ');
            if (label) {
              ctx.font = '12px monospace';
              const labelWidth = ctx.measureText(label).width + 8;
              ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
              ctx.fillRect(left, Math.max(0, top - 18), labelWidth, 18);
              ctx.fillStyle = '#86efac';
              ctx.fillText(label, left + 4, Math.max(12, top - 5));
            }
          }
          for (const anomaly of anomaliesForRender.current) {
            if (!anomaly.box || anomaly.box.length < 4) continue;
            const [x1, y1, x2, y2] = anomaly.box;
            const left = sx + x1 / fw * sw;
            const top = sy + y1 / fh * sh;
            const width = (x2 - x1) / fw * sw;
            const height = (y2 - y1) / fh * sh;
            ctx.strokeStyle = '#ef4444';
            ctx.lineWidth = 3;
            ctx.setLineDash([]);
            ctx.strokeRect(left, top, width, height);
            const label = `${anomaly.label || 'road_anomaly'} ${(anomaly.confidence * 100).toFixed(0)}%`;
            ctx.font = 'bold 12px monospace';
            const labelWidth = ctx.measureText(label).width + 8;
            const labelTop = Math.max(0, top - 20);
            ctx.fillStyle = 'rgba(127, 29, 29, 0.9)';
            ctx.fillRect(left, labelTop, labelWidth, 20);
            ctx.fillStyle = '#fecaca';
            ctx.fillText(label, left + 4, labelTop + 14);
          }
          const drawZones = () => {
            if (!isViolationDetectionEnabledRef.current) return;
            const zones = zonesForRender.current;
            const points = pointsForRender.current;
            // Draw existing zones
            for (const zone of zones) {
              if (!zone.points || zone.points.length < 3) continue;
              ctx.beginPath();
              for (let i = 0; i < zone.points.length; i++) {
                const px = sx + (zone.points[i][0]) * sw;
                const py = sy + (zone.points[i][1]) * sh;
                if (i === 0) ctx.moveTo(px, py);
                else ctx.lineTo(px, py);
              }
              ctx.closePath();
              ctx.fillStyle = 'rgba(239, 68, 68, 0.15)';
              ctx.fill();
              ctx.strokeStyle = 'rgba(239, 68, 68, 0.7)';
              ctx.lineWidth = 2;
              ctx.setLineDash([6, 3]);
              ctx.stroke();
              ctx.setLineDash([]);
              const cx = zone.points.reduce((a: number, p: number[]) => a + p[0], 0) / zone.points.length;
              const cy = zone.points.reduce((a: number, p: number[]) => a + p[1], 0) / zone.points.length;
              ctx.fillStyle = 'rgba(239, 68, 68, 0.9)';
              ctx.font = 'bold 13px monospace';
              ctx.fillText(zone.name || '禁停区', sx + cx * sw - 20, sy + cy * sh);
            }
            // Draw current polygon being drawn
            if (points.length >= 2) {
              ctx.beginPath();
              ctx.setLineDash([4, 4]);
              ctx.strokeStyle = 'rgba(34, 197, 94, 0.9)';
              ctx.lineWidth = 2.5;
              for (let i = 0; i < points.length; i++) {
                const px = sx + points[i].x / fw * sw;
                const py = sy + points[i].y / fh * sh;
                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
              }
              ctx.stroke();
              ctx.setLineDash([]);
            }
            // Draw vertices
            for (const pt of points) {
              const px = sx + pt.x / fw * sw;
              const py = sy + pt.y / fh * sh;
              ctx.beginPath();
              ctx.arc(px, py, 6, 0, Math.PI * 2);
              ctx.fillStyle = 'rgba(34, 197, 94, 0.9)';
              ctx.fill();
              ctx.strokeStyle = '#fff';
              ctx.lineWidth = 2;
              ctx.stroke();
            }
          };
          drawZones();
        };
        img.src = currentFrame;
      }
      requestAnimationFrame(render);
    };

    requestAnimationFrame(render);

    return () => {
      animating = false;
    };
  }, []);



  // Helper values
  const platedVehicles = recentPlates;

  // Zone drawing handlers
  const handleCanvasClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isViolationDetectionEnabled || !isDrawing) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;
    const fs = frameSizeRef.current;
    if (fs.scaleW === 0) return;
    // Convert to image pixel coordinates
    const imgX = (clickX - fs.offX) / fs.scaleW * fs.w;
    const imgY = (clickY - fs.offY) / fs.scaleH * fs.h;
    if (imgX < 0 || imgY < 0 || imgX > fs.w || imgY > fs.h) return;
    setCurrentZonePoints(prev => [...prev, { x: imgX, y: imgY }]);
  };

  const handleSaveZone = async () => {
    if (currentZonePoints.length < 3) return;
    if (frameSizeRef.current.w === 0) {
      alert('视频画面尚未加载，请等待画面出现后再绘制');
      return;
    }
    const normPoints = currentZonePoints.map(p => [
      Math.round(p.x / frameSizeRef.current.w * 10000) / 10000,
      Math.round(p.y / frameSizeRef.current.h * 10000) / 10000,
    ]);
    const newZone = { name: zoneName || '禁停区', points: normPoints };
    const updatedZones = [...existingZones, newZone];
    try {
      const res = await configAPI.updateZones(updatedZones);
      if (res.code === 200) {
        setExistingZones(updatedZones);
        setCurrentZonePoints([]);
        setIsDrawing(false);
      } else {
        alert('保存失败: ' + (res.message || '未知错误'));
      }
    } catch (err: any) {
      console.error('Zone save error:', err);
      alert('保存禁停区失败: ' + (err?.message || '网络错误'));
    }
  };



  const handleRemoveAllZones = async () => {
    try {
      const res = await configAPI.updateZones([]);
      if (res.code === 200) {
        setExistingZones([]);
        setCurrentZonePoints([]);
        setIsDrawing(false);
      }
    } catch (err: any) {
      console.error('Zone remove error:', err);
      alert('清除禁停区失败: ' + (err?.message || '网络错误'));
    }
  };

  return (
    <div className="w-full max-w-[1440px] mx-auto bg-transparent text-[var(--color-text-primary)] rounded-[32px] overflow-hidden">
      
      {/* ================= MAIN DASHBOARD GRID ================= */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        
        {/* ----------------- LEFT SIDE PANEL (4 columns) ----------------- */}
        <section className="lg:col-span-4 flex flex-col gap-6 w-full">
          
          {/* System Load */}
          <div className="dashboard-card p-6 flex flex-col justify-between min-h-[380px]">
            <div className="flex justify-between items-start">
              <div>
                <h3 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">服务器核心负载</h3>
              </div>
              <button className="p-1 rounded-full border border-[var(--color-border-card)] hover:bg-white/5">
                <Activity className="w-4 h-4 text-[var(--color-text-secondary)]" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3 my-4">
              <div className="bg-yellow-50 dark:bg-[#1C1A16] border border-yellow-200 dark:border-[#3C321E] px-3 py-2 rounded-xl flex items-center justify-between">
                <div>
                  <span className="text-[10px] text-yellow-600 block uppercase font-bold tracking-wider">CPU使用</span>
                  <span className="text-xs font-semibold">{metrics.cpu_usage.toFixed(1)}%</span>
                </div>
              </div>
              <div className="bg-teal-50 dark:bg-[#161B1C] border border-teal-200 dark:border-[#1E3A3C] px-3 py-2 rounded-xl flex items-center justify-between">
                <div>
                  <span className="text-[10px] text-teal-500 block uppercase font-bold tracking-wider">内存占用</span>
                  <span className="text-xs font-semibold">{metrics.memory_usage.toFixed(1)}%</span>
                </div>
              </div>
              <div className="bg-violet-50 dark:bg-[#191724] border border-violet-200 dark:border-violet-500/20 px-3 py-2 rounded-xl">
                <span className="text-[10px] text-violet-500 block uppercase font-bold tracking-wider">GPU 使用</span>
                <span className="text-xs font-semibold">{metrics.gpu_usage === null ? '不可用' : `${metrics.gpu_usage.toFixed(1)}%`}</span>
              </div>
              <div className="bg-sky-50 dark:bg-[#151C24] border border-sky-200 dark:border-sky-500/20 px-3 py-2 rounded-xl">
                <span className="text-[10px] text-sky-500 block uppercase font-bold tracking-wider">GPU 显存</span>
                <span className="text-xs font-semibold">{metrics.gpu_details ? `${metrics.gpu_details.memory_percent.toFixed(1)}%` : '不可用'}</span>
              </div>
            </div>

            <div className="relative flex flex-col items-center justify-center pt-2">
              <svg className="w-full max-w-[200px]" viewBox="0 0 100 50">
                <path d="M10,45 A40,40 0 0,1 90,45" fill="none" stroke="#222328" strokeWidth="6" strokeLinecap="round" />
                <path 
                  d="M10,45 A40,40 0 0,1 90,45" 
                  fill="none" 
                  stroke="url(#progress-gradient)" 
                  strokeWidth="6" 
                  strokeLinecap="round" 
                  strokeDasharray="126" 
                  strokeDashoffset={126 - (126 * (metrics.cpu_usage / 100))}
                />
                <defs>
                  <linearGradient id="progress-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#EA580C" />
                    <stop offset="50%" stopColor="#CCA43B" />
                    <stop offset="100%" stopColor="#10B981" />
                  </linearGradient>
                </defs>
              </svg>
              <div className="absolute top-[48%] flex flex-col items-center">
                <span className="text-xs font-bold bg-gray-200 dark:bg-[#26272B] px-2.5 py-0.5 rounded-full border border-[var(--color-border-card)] text-[var(--color-text-primary)] shadow-lg">
                  {metrics.cpu_usage.toFixed(1)}%
                </span>
              </div>
              <p className="text-[10px] text-[var(--color-text-secondary)] text-center mt-3 font-medium">
                {metrics.cpu_details ? `物理 ${metrics.cpu_details.cores_physical} / 逻辑 ${metrics.cpu_details.cores_logical} | ${metrics.cpu_details.frequency_current_mhz} MHz` : 'Waiting for CPU stats'}
              </p>
            </div>

            <div className="mt-4 rounded-xl border border-[var(--color-border-card)] bg-violet-500/5 px-3 py-3 text-[10px]">
              {metrics.gpu_details ? (
                <>
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <span className="truncate font-semibold text-[var(--color-text-primary)]">{metrics.gpu_details.name}</span>
                    <span className="shrink-0 text-orange-400">{metrics.gpu_details.temperature}°C</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-[#26272B]">
                    <div className="h-full rounded-full bg-violet-500 transition-all" style={{ width: `${Math.min(100, metrics.gpu_details.memory_percent)}%` }} />
                  </div>
                  <p className="mt-2 text-[var(--color-text-secondary)]">
                    显存 {metrics.gpu_details.memory_used.toFixed(2)} / {metrics.gpu_details.memory_total.toFixed(2)} GB
                  </p>
                </>
              ) : (
                <p className="text-[var(--color-text-muted)]">未检测到 NVIDIA GPU 监控数据，请检查驱动和 NVML。</p>
              )}
            </div>
          </div>

          {/* Realtime Vehicles */}
          <div className="dashboard-card p-6 flex flex-col justify-between min-h-[300px]">
            <div className="flex justify-between items-start mb-6">
              <h3 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">实时车牌识别 ({platedVehicles.length})</h3>
              <button className="p-1 rounded-full border border-[var(--color-border-card)] hover:bg-white/5">
                <Car className="w-4 h-4 text-[var(--color-text-secondary)]" />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3 max-h-[220px] overflow-y-auto">
              {platedVehicles.length === 0 ? (
                <span className="text-[var(--color-text-muted)] text-xs">暂无识别结果</span>
              ) : (
                platedVehicles.map((v, i) => (
                  <div key={i} className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-2 text-center">
                    <span className="text-[10px] text-[var(--color-text-secondary)] block uppercase mb-1">{v.class}</span>
                    <span className="text-sm font-bold text-emerald-400 tracking-wider">{v.plate}</span>
                  </div>
                ))
              )}
            </div>
          </div>
          
          {/* Traffic Anomalies/Violations */}
          <div className="dashboard-card p-6 flex flex-col justify-between max-h-[300px]">
            <div className="flex justify-between items-start mb-6">
              <h3 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">超时滞留告警</h3>
              <button className="p-1 rounded-full border border-[var(--color-border-card)] hover:bg-white/5">
                <ShieldAlert className="w-4 h-4 text-rose-400" />
              </button>
            </div>
            <div className="space-y-3 overflow-y-auto pr-2 h-[150px]">
              {violations.length === 0 ? (
                <p className="text-[var(--color-text-muted)] text-xs text-center">暂无超时违停</p>
              ) : (
                violations.map((v, i) => (
                  <div key={i} className="flex justify-between items-center bg-rose-500/10 border border-rose-500/20 rounded-xl p-3">
                    <div>
                      <strong className="text-xs text-slate-200">ID: {v.vehicle_id}</strong>
                      <p className="text-[10px] text-[var(--color-text-secondary)] mt-1">{v.zone_name}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-bold text-rose-400">{v.duration.toFixed(0)}s</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

        </section>

        {/* ----------------- RIGHT PANEL (8 columns) ----------------- */}
        <section className="lg:col-span-8 flex flex-col gap-6 w-full">
          
          {/* Video Stream Map */}
          <div className="dashboard-card overflow-hidden relative flex flex-col justify-between" style={{ minHeight: '620px' }}>
            
            <div className="absolute top-6 left-6 right-6 z-10 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center bg-white/90 dark:bg-[#1C1C22]/90 backdrop-blur-md border border-[var(--color-border-card)] rounded-full px-4 py-2">
                <span className={`w-2 h-2 rounded-full mr-3 ${wsStatus === 'connected' ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />
                <span className="text-xs font-semibold text-[var(--color-text-primary)]">视频源推流 (FPS: {fps.toFixed(1)})</span>
              </div>

              <div className="flex items-center gap-2 flex-wrap bg-white/90 dark:bg-[#1C1C22]/90 backdrop-blur-md border border-[var(--color-border-card)] rounded-full p-1">
                {activeRtspDevices.length === 0 && (
                  <button
                    onClick={() => selectDevice('default')}
                    className={`text-xs px-3.5 py-1.5 rounded-full font-medium transition-all ${selectedDeviceId === 'default' ? 'bg-gray-800 dark:bg-white text-white dark:text-black font-bold' : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}`}
                  >边端默认</button>
                )}
                {activeSandCameras.map(camera => {
                  const deviceId = `rtsp_${camera.id}`;
                  return (
                    <button
                      key={camera.id}
                      onClick={() => selectDevice(deviceId)}
                      className={`text-xs px-3.5 py-1.5 rounded-full font-medium transition-all ${selectedDeviceId === deviceId ? 'bg-gray-800 dark:bg-white text-white dark:text-black font-bold' : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}`}
                    >
                      {camera.id}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="absolute inset-0 bg-gray-100 dark:bg-[#0F1013] overflow-hidden flex items-center justify-center">
              <div className="relative w-full h-full flex justify-center items-center" onClick={handleCanvasClick} style={{ cursor: isViolationDetectionEnabled && isDrawing ? 'crosshair' : 'default' }}>
                <canvas ref={canvasRef} className="absolute inset-0 w-full h-full block object-contain" />
                {!hasFrame && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-center bg-gray-100 dark:bg-[#0F1013]">
                    <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                    <p className="text-[var(--color-text-secondary)] text-sm">等待边缘推流信号源输入...</p>
                  </div>
                )}
              </div>
            </div>

            {/* Drawing Controls */}
            {isViolationDetectionEnabled && (
            <div className="absolute left-6 bottom-6 flex flex-wrap gap-2 z-10 bg-white/90 dark:bg-[#1C1C22]/90 backdrop-blur-md border border-[var(--color-border-card)] px-4 py-3 rounded-2xl">
              {!isDrawing ? (
                <button onClick={() => { setIsDrawing(true); setCurrentZonePoints([]); }} className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)] hover:text-emerald-400 transition-colors">
                  <PenTool size={14} /> 绘制禁停区
                </button>
              ) : (
                <div className="flex items-center gap-3">
                  <input type="text" value={zoneName} onChange={e => setZoneName(e.target.value)} className="bg-transparent border-b border-[var(--color-border-card)] text-xs text-[var(--color-text-primary)] outline-none focus:border-emerald-400 w-24" placeholder="区域名称" />
                  <button onClick={handleSaveZone} disabled={currentZonePoints.length < 3} className="text-xs font-bold text-emerald-400 hover:text-emerald-300 disabled:opacity-50">保存</button>
                  <button onClick={() => { setIsDrawing(false); setCurrentZonePoints([]); }} className="text-xs font-bold text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]">取消</button>
                </div>
              )}
              {existingZones.length > 0 && !isDrawing && (
                <>
                  <div className="w-px h-4 bg-white/20 mx-2" />
                  <button onClick={handleRemoveAllZones} className="flex items-center gap-1.5 text-xs font-semibold text-rose-400 hover:text-rose-300 transition-colors">
                    <Trash2 size={14} /> 清空 ({existingZones.length})
                  </button>
                </>
              )}
            </div>
            )}
          </div>

          {/* Anomalies Tracking Board */}
          <div className="dashboard-card p-6 flex flex-col justify-between">
            <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
              <h3 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">路面抛洒物异常</h3>
            </div>
            <div className="overflow-x-auto w-full h-[180px]">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-[var(--color-border-card)] text-[var(--color-text-secondary)] font-semibold uppercase tracking-wider">
                    <th className="pb-3 font-medium">类别</th>
                    <th className="pb-3 font-medium">坐标</th>
                    <th className="pb-3 font-medium">置信度</th>
                    <th className="pb-3 font-medium text-right">状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {anomalies.length > 0 ? (
                    anomalies.map((a, i) => (
                      <tr key={i} className="group hover:hover:bg-gray-100 dark:hover:bg-[#1C1E24]/40 transition-colors">
                        <td className="py-4 font-bold flex items-center gap-2 text-[var(--color-text-primary)] capitalize">
                          <Activity className="w-4 h-4 text-amber-500" />
                          {a.label}
                        </td>
                        <td className="py-4 text-[var(--color-text-secondary)] font-mono">
                          x:{((a.box[0]+a.box[2])/2).toFixed(0)} y:{a.box[3].toFixed(0)}
                        </td>
                        <td className="py-4 font-bold text-amber-500">
                          {(a.confidence * 100).toFixed(1)}%
                        </td>
                        <td className="py-4 text-right">
                          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-bold border bg-amber-500/10 text-amber-400 border-amber-500/20">
                            已上报
                          </span>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={4} className="py-8 text-center text-[var(--color-text-muted)] font-medium">
                        当前路面安全，无异常物
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

        </section>
      </div>
    </div>
  );
}
