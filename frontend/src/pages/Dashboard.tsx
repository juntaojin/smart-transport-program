import { useEffect, useState, useRef } from 'react';
import { DashboardWebSocket } from '../services/ws';
import { statsAPI, configAPI } from '../services/api';
import { Cpu, Database, Activity, HardDrive, Wifi, ShieldAlert, Car, Navigation, FileText, PenTool, Save, X, Trash2 } from 'lucide-react';

interface Vehicle {
  id: number;
  class: string;
  box: number[];
  plate: string;
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

interface MetricHistoryItem {
  cpu_usage: number;
  memory_usage: number;
  network_rx: number;
  video_fps: number;
  timestamp: string;
}

export default function Dashboard() {
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');
  const [hasFrame, setHasFrame] = useState(false);
  const [fps, setFps] = useState<number>(0);
  const [congestion, setCongestion] = useState<string>('low');
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [violations, setViolations] = useState<Violation[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [plateOcrEnabled, setPlateOcrEnabled] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const latestFrameRef = useRef<string | null>(null);
  
  // Zone drawing state (use refs for canvas render closure)
  const [isDrawing, setIsDrawing] = useState(false);
  const [currentZonePoints, setCurrentZonePoints] = useState<{x: number, y: number}[]>([]);
  const [zoneName, setZoneName] = useState('禁停区');
  const [existingZones, setExistingZones] = useState<any[]>([]);
  const frameSizeRef = useRef({ w: 1280, h: 720, offX: 0, offY: 0, scaleW: 0, scaleH: 0 });
  const zonesForRender = useRef<any[]>([]);
  const pointsForRender = useRef<{x: number, y: number}[]>([]);
  // Keep refs in sync with state for render closure
  zonesForRender.current = existingZones;
  pointsForRender.current = currentZonePoints;
  
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

  const [metricsHistory, setMetricsHistory] = useState<MetricHistoryItem[]>([]);
  const wsRef = useRef<DashboardWebSocket | null>(null);

  // Fetch metrics history on mount
  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const res = await statsAPI.system(15);
        if (res.code === 200) {
          if (res.data.history) {
            setMetricsHistory(res.data.history);
          }
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

  useEffect(() => {
    const checkModels = async () => {
      try {
        const res = await configAPI.getModels();
        if (res.code === 200 && Array.isArray(res.data)) {
          const ocrNode = res.data.find((m: any) => m.model_name === 'plate_ocr');
          setPlateOcrEnabled(ocrNode?.enabled ?? false);
        }
      } catch {}
    };
    checkModels();
    const interval = setInterval(checkModels, 5000);
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

  // Connect WebSocket
  useEffect(() => {
    const onMessage = (data: any) => {
      if (data.image) {
        latestFrameRef.current = data.image;
        if (!hasFrame) setHasFrame(true);
      }
      if (data.fps !== undefined) setFps(data.fps);
      if (data.congestion_level) setCongestion(data.congestion_level);
      if (data.vehicles) setVehicles(data.vehicles);
      if (data.violations) setViolations(data.violations);
      if (data.anomalies) setAnomalies(data.anomalies);
      
      // Update system metrics real-time values from websocket broadcast
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

    const onStatus = (status: any) => {
      setWsStatus(status);
    };

    wsRef.current = new DashboardWebSocket(onMessage, onStatus);
    wsRef.current.connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.stop();
      }
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
          const scale = Math.max(
            canvasW / img.naturalWidth,
            canvasH / img.naturalHeight
          );
          const sw = img.naturalWidth * scale;
          const sh = img.naturalHeight * scale;
          const sx = (canvasW - sw) / 2;
          const sy = (canvasH - sh) / 2;
          ctx.drawImage(img, sx, sy, sw, sh);
          
          // Draw zones overlay (use refs to avoid stale closure)
          const fw = img.naturalWidth;
          const fh = img.naturalHeight;
          frameSizeRef.current = { w: fw, h: fh, offX: sx, offY: sy, scaleW: sw, scaleH: sh };
          const drawZones = () => {
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

  // Render SVG Chart using pure SVG paths (no heavy libraries)
  const renderLineChart = (data: number[], color: string, maxVal = 100) => {
    if (data.length === 0) return null;
    const width = 500;
    const height = 120;
    const padding = 10;
    const points = data.map((val, idx) => {
      const x = padding + (idx / (data.length - 1)) * (width - padding * 2);
      const y = height - padding - (val / maxVal) * (height - padding * 2);
      return `${x},${y}`;
    }).join(' ');

    return (
      <svg className="w-full h-28" viewBox={`0 0 ${width} ${height}`}>
        {/* Grid lines */}
        <line x1={padding} y1={height/2} x2={width-padding} y2={height/2} stroke="rgba(255,255,255,0.05)" strokeDasharray="3,3" />
        <line x1={padding} y1={height - padding} x2={width-padding} y2={height - padding} stroke="rgba(255,255,255,0.1)" />
        
        {/* Gradient fill */}
        <path
          d={`M ${padding},${height - padding} L ${points} L ${width - padding},${height - padding} Z`}
          fill={`url(#grad-${color})`}
          opacity="0.15"
        />
        
        {/* Main Line */}
        <polyline
          fill="none"
          stroke={color}
          strokeWidth="2.5"
          points={points}
          className="transition-all duration-300"
        />
        
        <defs>
          <linearGradient id={`grad-${color}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} />
            <stop offset="100%" stopColor="transparent" />
          </linearGradient>
        </defs>
      </svg>
    );
  };

  // Helper values
  const totalVehiclesCount = vehicles.length;
  const activeViolationsCount = violations.length;
  const activeAnomaliesCount = anomalies.length;
  const platedVehicles = vehicles.filter(v => v.plate);

  // Zone drawing handlers
  const handleCanvasClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDrawing) return;
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

  const handleClearCurrent = () => {
    setCurrentZonePoints([]);
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
    <div className="space-y-6">
      
      {/* 顶部指标卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
        
        <div className="glass-panel hover-scale rounded-2xl p-5 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">实时车流量</p>
            <h3 className="text-3xl font-bold mt-1 text-slate-100">{totalVehiclesCount} <span className="text-xs font-normal text-slate-400">辆</span></h3>
          </div>
          <div className="p-3 bg-blue-500/10 rounded-xl text-blue-400">
            <Car size={24} />
          </div>
        </div>

        <div className="glass-panel hover-scale rounded-2xl p-5 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">拥堵程度</p>
            <h3 className={`text-2xl font-bold mt-1 uppercase ${
              congestion === 'high' ? 'text-rose-500' : congestion === 'medium' ? 'text-amber-500' : 'text-emerald-500'
            }`}>
              {congestion === 'high' ? '严重拥堵' : congestion === 'medium' ? '中度拥堵' : '道路顺畅'}
            </h3>
          </div>
          <div className={`p-3 rounded-xl ${
            congestion === 'high' ? 'bg-rose-500/10 text-rose-400' : congestion === 'medium' ? 'bg-amber-500/10 text-amber-400' : 'bg-emerald-500/10 text-emerald-400'
          }`}>
            <Navigation size={24} />
          </div>
        </div>

        <div className="glass-panel hover-scale rounded-2xl p-5 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">违停车辆</p>
            <h3 className="text-3xl font-bold mt-1 text-rose-500">{activeViolationsCount} <span className="text-xs font-normal text-slate-400">起</span></h3>
          </div>
          <div className="p-3 bg-rose-500/10 rounded-xl text-rose-400">
            <ShieldAlert size={24} />
          </div>
        </div>

        <div className="glass-panel hover-scale rounded-2xl p-5 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">路面异常</p>
            <h3 className="text-3xl font-bold mt-1 text-amber-500">{activeAnomaliesCount} <span className="text-xs font-normal text-slate-400">处</span></h3>
          </div>
          <div className="p-3 bg-amber-500/10 rounded-xl text-amber-400">
            <Activity size={24} />
          </div>
        </div>

      </div>

      {/* 主面板内容 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* 视频推流区 (占 2/3 宽度) */}
        <div className="lg:col-span-2 glass-panel-glow rounded-3xl p-5 flex flex-col justify-between">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full ${wsStatus === 'connected' ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />
              <h2 className="font-semibold text-lg">实时监控画面接收</h2>
            </div>
            <div className="text-sm text-slate-400 flex items-center gap-4">
              <span>FPS: <strong className="text-blue-400">{fps.toFixed(1)}</strong></span>
              <span>状态: 
                <strong className={wsStatus === 'connected' ? 'text-emerald-400' : 'text-rose-400'}>
                  {wsStatus === 'connected' ? ' 已连通' : wsStatus === 'connecting' ? ' 正在重连...' : ' 未连通'}
                </strong>
              </span>
            </div>
          </div>
          
          <div className="relative aspect-video rounded-2xl overflow-hidden bg-slate-950 border border-slate-800 flex justify-center items-center" onClick={handleCanvasClick} style={{ cursor: isDrawing ? 'crosshair' : 'default' }}>
            <canvas ref={canvasRef} className="w-full h-full block" />
            {!hasFrame && (
              <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-8 bg-slate-950">
                <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                <p className="text-slate-400 text-sm">等待边缘推流信号源输入...</p>
                <p className="text-xs text-slate-600 mt-2">请访问 /phone 页面启动摄像头或本地视频推流</p>
              </div>
            )}
            
            {/* Float HUD */}
            {hasFrame && (
              <div className="absolute top-4 left-4 bg-slate-900/80 backdrop-blur-md px-3 py-1.5 rounded-lg border border-white/10 text-xs flex gap-4">
                <span>白名单匹配: <span className="text-emerald-400">已启用</span></span>
                <span>检测节点: <span className="text-cyan-400">YOLOv8 + SORT</span></span>
              </div>
            )}
          </div>
        </div>

        {/* 资源监控 & 事件警告 */}
        <div className="space-y-6">
          
          {/* 服务器硬件指标 */}
          <div className="glass-panel rounded-3xl p-5">
            <h2 className="font-semibold text-lg mb-4 flex items-center gap-2">
              <Database size={20} className="text-blue-400" />
              服务器硬件状态 (云端/Windows)
            </h2>
            
            <div className="space-y-4">
              {/* CPU */}
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-slate-400 flex items-center gap-1.5">
                    <Cpu size={14} /> CPU 使用率
                  </span>
                  <span className="font-semibold">{metrics.cpu_usage.toFixed(1)}%</span>
                </div>
                <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                  <div 
                    className="bg-blue-500 h-full transition-all duration-500 ease-out" 
                    style={{ width: `${metrics.cpu_usage}%` }}
                  />
                </div>
                {metrics.cpu_details && (
                  <span className="text-[10px] text-slate-500 mt-1 block">
                    核心: 物理 {metrics.cpu_details.cores_physical} / 逻辑 {metrics.cpu_details.cores_logical} | 频率: {metrics.cpu_details.frequency_current_mhz} MHz
                  </span>
                )}
              </div>

              {/* Memory */}
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-slate-400 flex items-center gap-1.5">
                    <HardDrive size={14} /> 内存使用率
                  </span>
                  <span className="font-semibold">{metrics.memory_usage.toFixed(1)}%</span>
                </div>
                <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                  <div 
                    className="bg-cyan-400 h-full transition-all duration-500 ease-out" 
                    style={{ width: `${metrics.memory_usage}%` }}
                  />
                </div>
                {metrics.memory_details && (
                  <span className="text-[10px] text-slate-500 mt-1 block">
                    已用: {metrics.memory_details.used_gb.toFixed(1)} GB / 共 {metrics.memory_details.total_gb.toFixed(1)} GB
                  </span>
                )}
              </div>

              {/* Disk */}
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-slate-400 flex items-center gap-1.5">
                    <HardDrive size={14} className="text-emerald-400" /> 磁盘空间
                  </span>
                  <span className="font-semibold">{metrics.disk_usage.toFixed(1)}%</span>
                </div>
                <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                  <div 
                    className="bg-emerald-500 h-full transition-all duration-500 ease-out" 
                    style={{ width: `${metrics.disk_usage}%` }}
                  />
                </div>
                {metrics.disk_details && (
                  <span className="text-[10px] text-slate-500 mt-1 block">
                    已用: {metrics.disk_details.used_gb.toFixed(0)} GB / 共 {metrics.disk_details.total_gb.toFixed(0)} GB
                  </span>
                )}
              </div>

              {/* Network */}
              <div className="grid grid-cols-2 gap-4 pt-2">
                <div className="bg-slate-900/50 rounded-xl p-3 border border-white/5">
                  <span className="text-xs text-slate-400 flex items-center gap-1">
                    <Wifi size={12} className="rotate-45" /> 下行速度
                  </span>
                  <p className="text-lg font-bold text-slate-100 mt-1">{metrics.network_rx.toFixed(1)} <span className="text-xs font-normal text-slate-400">Mbps</span></p>
                </div>
                <div className="bg-slate-900/50 rounded-xl p-3 border border-white/5">
                  <span className="text-xs text-slate-400 flex items-center gap-1">
                    <Wifi size={12} className="-rotate-45" /> 上行速度
                  </span>
                  <p className="text-lg font-bold text-slate-100 mt-1">{metrics.network_tx.toFixed(1)} <span className="text-xs font-normal text-slate-400">Mbps</span></p>
                </div>
              </div>

              {/* Nvidia GPU Details */}
              {metrics.gpu_details && (
                <div className="mt-4 pt-4 border-t border-white/5 space-y-3">
                  <div className="flex justify-between text-xs font-bold text-slate-200">
                    <span className="flex items-center gap-1.5">
                      <Cpu size={14} className="text-emerald-400 animate-pulse" /> 
                      显卡: {metrics.gpu_details.name}
                    </span>
                  </div>
                  
                  <div className="grid grid-cols-2 gap-4">
                    {/* GPU Load */}
                    <div>
                      <div className="flex justify-between text-[11px] mb-1">
                        <span className="text-slate-400">GPU 使用率</span>
                        <span className="font-semibold text-slate-300">{metrics.gpu_details.load}%</span>
                      </div>
                      <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                        <div 
                          className="bg-emerald-400 h-full transition-all duration-500 ease-out" 
                          style={{ width: `${metrics.gpu_details.load}%` }}
                        />
                      </div>
                    </div>
                    
                    {/* GPU VRAM */}
                    <div>
                      <div className="flex justify-between text-[11px] mb-1">
                        <span className="text-slate-400">显存 (VRAM)</span>
                        <span className="font-semibold text-slate-300">{metrics.gpu_details.memory_percent}%</span>
                      </div>
                      <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                        <div 
                          className="bg-emerald-400 h-full transition-all duration-500 ease-out" 
                          style={{ width: `${metrics.gpu_details.memory_percent}%` }}
                        />
                      </div>
                      <span className="text-[9px] text-slate-500 mt-0.5 block">
                        已用: {metrics.gpu_details.memory_used.toFixed(1)} GB / 共 {metrics.gpu_details.memory_total.toFixed(0)} GB
                      </span>
                    </div>
                  </div>
                  
                  <div className="flex justify-between text-[10px] text-slate-500">
                    <span>GPU 温度: <strong className="text-amber-500">{metrics.gpu_details.temperature} °C</strong></span>
                    <span>监控源: Nvidia NVML</span>
                  </div>
                </div>
            )}
          </div>

          {/* 禁停区绘制工具栏 */}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            {!isDrawing ? (
              <button
                type="button"
                onClick={() => { setIsDrawing(true); setCurrentZonePoints([]); }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-500/20 text-rose-400 border border-rose-500/30 hover:bg-rose-500/30 transition-colors"
              >
                <PenTool size={14} /> 绘制禁停区
              </button>
            ) : (
              <>
                <input
                  type="text"
                  value={zoneName}
                  onChange={e => setZoneName(e.target.value)}
                  className="bg-slate-900/60 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-slate-200 w-28 outline-none focus:border-blue-500"
                  placeholder="区域名称"
                />
                <span className="text-xs text-slate-400">
                  {currentZonePoints.length} 个顶点
                  {currentZonePoints.length < 3 ? ' (至少3个)' : ''}
                </span>
                <button
                  type="button"
                  onClick={handleSaveZone}
                  disabled={currentZonePoints.length < 3}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Save size={14} /> 保存
                </button>
                <button
                  type="button"
                  onClick={handleClearCurrent}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30 transition-colors"
                >
                  <X size={14} /> 清空当前
                </button>
                <button
                  type="button"
                  onClick={() => { setIsDrawing(false); setCurrentZonePoints([]); }}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-700/30 text-slate-400 border border-slate-500/30 hover:bg-slate-600/30 transition-colors"
                >
                  取消绘制
                </button>
              </>
            )}
            {existingZones.length > 0 && (
              <button
                type="button"
                onClick={handleRemoveAllZones}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20 hover:bg-rose-500/20 transition-colors"
              >
                <Trash2 size={14} /> 清除全部 ({existingZones.length}个区域)
              </button>
            )}
            {existingZones.length > 0 && !isDrawing && (
              <span className="text-xs text-slate-500">
                已配置: {existingZones.map(z => z.name).join(', ')}
              </span>
            )}
          </div>
        </div>

          {/* 实时硬件历史曲线图 */}
          <div className="glass-panel rounded-3xl p-5">
            <h2 className="font-semibold text-lg mb-3">服务器负载趋势</h2>
            <div className="relative">
              {metricsHistory.length > 0 ? (
                renderLineChart(metricsHistory.map(h => h.cpu_usage), '#3b82f6')
              ) : (
                <div className="h-28 flex items-center justify-center text-xs text-slate-500">
                  收集性能趋势数据中...
                </div>
              )}
              <div className="flex justify-between text-[10px] text-slate-500 mt-2 px-1">
                <span>15分钟前</span>
                <span>当前</span>
              </div>
            </div>
          </div>

        </div>
      </div>
      
      {/* 车牌识别结果 */}
      <div className="glass-panel rounded-3xl p-6">
        <h3 className="font-semibold text-lg text-emerald-400 mb-4 flex items-center gap-2">
          <FileText size={20} />
          实时车牌识别
          {plateOcrEnabled && (
            <span className="text-xs bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full ml-2">已启用</span>
          )}
        </h3>
        {!plateOcrEnabled ? (
          <div className="text-center py-8">
            <div className="w-10 h-10 rounded-full bg-slate-800 flex items-center justify-center mx-auto mb-3">
              <FileText size={20} className="text-slate-500" />
            </div>
            <p className="text-slate-500 text-sm">未启用车牌识别</p>
            <p className="text-xs text-slate-600 mt-1">请在系统配置中开启 plate_ocr 节点</p>
          </div>
        ) : platedVehicles.length === 0 ? (
          <p className="text-slate-500 text-sm py-4 text-center">等待车牌识别结果...</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {platedVehicles.map((v, i) => (
              <div key={i} className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3 text-center">
                <span className="text-xs text-slate-400 block mb-1 capitalize">{v.class}</span>
                <span className="text-sm font-bold text-emerald-400 tracking-wider">{v.plate}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 实时预警滚屏 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="glass-panel rounded-3xl p-6">
          <h3 className="font-semibold text-lg text-rose-500 mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping" />
            当前区域违规停放告警 ({violations.length})
          </h3>
          <div className="space-y-3 max-h-56 overflow-y-auto pr-2">
            {violations.length === 0 ? (
              <p className="text-slate-500 text-sm py-4 text-center">当前没有正在违规停放的车辆</p>
            ) : (
              violations.map((v, i) => (
                <div key={i} className="flex justify-between items-center bg-rose-500/10 border border-rose-500/20 rounded-xl p-3.5">
                  <div>
                    <span className="text-xs bg-rose-500 text-white font-semibold px-2 py-0.5 rounded mr-2">违停</span>
                    <strong className="text-sm text-slate-200">车辆 ID: {v.vehicle_id}</strong>
                    <p className="text-xs text-slate-400 mt-1">所在区域: {v.zone_name}</p>
                  </div>
                  <div className="text-right">
                    <span className="text-xs text-slate-400">停放时长</span>
                    <p className="text-sm font-bold text-rose-400">{v.duration.toFixed(1)} 秒</p>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="glass-panel rounded-3xl p-6">
          <h3 className="font-semibold text-lg text-amber-500 mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-500 animate-ping" />
            当前路面障碍与异常 ({anomalies.length})
          </h3>
          <div className="space-y-3 max-h-56 overflow-y-auto pr-2">
            {anomalies.length === 0 ? (
              <p className="text-slate-500 text-sm py-4 text-center">路面完好，未检测到障碍物/抛洒物</p>
            ) : (
              anomalies.map((a, i) => (
                <div key={i} className="flex justify-between items-center bg-amber-500/10 border border-amber-500/20 rounded-xl p-3.5">
                  <div>
                    <span className="text-xs bg-amber-500 text-dark-900 font-semibold px-2 py-0.5 rounded mr-2">异常物</span>
                    <strong className="text-sm text-slate-200 capitalize">{a.label}</strong>
                    <p className="text-xs text-slate-400 mt-1">坐标位置: x={(a.box[0]+a.box[2]/2).toFixed(0)}, y={a.box[3].toFixed(0)}</p>
                  </div>
                  <div className="text-right">
                    <span className="text-xs text-slate-400">置信度</span>
                    <p className="text-sm font-bold text-amber-400">{(a.confidence * 100).toFixed(1)}%</p>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
      
    </div>
  );
}
