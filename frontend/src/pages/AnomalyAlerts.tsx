import { useEffect, useState, useRef } from 'react';
import { statsAPI } from '../services/api';
import { Volume2, VolumeX, ShieldAlert, Sparkles, RefreshCw, Trash } from 'lucide-react';

interface AnomalyRecord {
  id: number;
  anomaly_type: string;
  confidence: number;
  location_x: number;
  location_y: number;
  affected_lane: string;
  timestamp: string;
}

export default function AnomalyAlerts() {
  const [alerts, setAlerts] = useState<AnomalyRecord[]>([]);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const previousAlertCount = useRef(0);

  // Play browser synthesizer warning sound
  const playAlertSound = () => {
    if (!soundEnabled) return;
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      
      // Multi-frequency alarm tone
      const osc1 = ctx.createOscillator();
      const osc2 = ctx.createOscillator();
      const gainNode = ctx.createGain();

      osc1.type = 'sawtooth';
      osc1.frequency.setValueAtTime(660, ctx.currentTime);
      
      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(880, ctx.currentTime);

      gainNode.gain.setValueAtTime(0.12, ctx.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);

      osc1.connect(gainNode);
      osc2.connect(gainNode);
      gainNode.connect(ctx.destination);

      osc1.start();
      osc2.start();
      osc1.stop(ctx.currentTime + 0.35);
      osc2.stop(ctx.currentTime + 0.35);
    } catch (e) {
      console.warn('Browser Audio playback rejected (needs user interaction):', e);
    }
  };

  const fetchAlerts = async () => {
    setLoading(true);
    try {
      const res = await statsAPI.anomalies(60); // fetch last 60 minutes
      if (res.code === 200 && res.data) {
        setAlerts(res.data);
        
        // If count increased, trigger sound
        if (res.data.length > previousAlertCount.current && previousAlertCount.current > 0) {
          playAlertSound();
        }
        previousAlertCount.current = res.data.length;
      }
    } catch (err) {
      console.error('Failed to query road anomalies:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 5000);
    return () => clearInterval(interval);
  }, [soundEnabled]);

  const clearAllLocal = () => {
    setAlerts([]);
    previousAlertCount.current = 0;
  };

  return (
    <div className="space-y-6">
      
      {/* 顶部控制栏 */}
      <div className="dashboard-card p-6 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
            <ShieldAlert className="text-amber-500 animate-pulse" />
            路面异常状况看板
          </h2>
          <p className="text-[var(--color-text-secondary)] text-sm mt-0.5">Grounding DINO 自动识别障碍物、撒落物及危险异常记录</p>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Sound Toggle */}
          <button 
            type="button" 
            onClick={() => setSoundEnabled(!soundEnabled)}
            className={`p-2.5 rounded-xl border transition-all flex items-center gap-1.5 text-sm font-semibold ${
              soundEnabled 
                ? 'bg-blue-500/10 border-blue-500/30 text-blue-400' 
                : 'bg-white/90 dark:bg-[#1C1C22]/90 border-[var(--color-border-card)] text-[var(--color-text-muted)]'
            }`}
          >
            {soundEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
            {soundEnabled ? '声学报警开' : '声学报警关'}
          </button>
          
          {/* Refresh */}
          <button 
            type="button" 
            onClick={fetchAlerts}
            disabled={loading}
            className="bg-white/90 dark:bg-[#1C1C22]/90 border border-[var(--color-border-card)] hover:bg-[#222328] text-gray-900 dark:text-gray-200 p-2.5 rounded-xl flex items-center gap-1.5 text-sm font-semibold hover:scale-105 disabled:opacity-50 transition-all"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>

          {/* Clear */}
          <button 
            type="button" 
            onClick={clearAllLocal}
            className="bg-rose-500/10 border border-rose-500/20 hover:bg-rose-500/20 text-rose-400 p-2.5 rounded-xl flex items-center gap-1.5 text-sm font-semibold hover:scale-105 transition-all"
          >
            <Trash size={16} />
            清空视图
          </button>
        </div>
      </div>

      {/* 异常卡片列表 */}
      {alerts.length === 0 ? (
        <div className="dashboard-card p-16 text-center text-[var(--color-text-muted)] space-y-4">
          <Sparkles size={40} className="mx-auto text-gray-600" />
          <p className="font-semibold text-[var(--color-text-secondary)]">目前没有路面异常或抛洒物告警</p>
          <p className="text-xs text-[var(--color-text-muted)] max-w-sm mx-auto">云端 AI 大模型将全天候监控道路状况，任何障碍物、轮胎、货物或垃圾掉落均将在此进行归档展示。</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {alerts.map((alert, index) => {
            const isHighConfidence = alert.confidence > 0.45;
            return (
              <div 
                key={index} 
                className={`dashboard-card p-5 border relative overflow-hidden transition-all duration-300 ${
                  isHighConfidence 
                    ? 'border-rose-500/30 hover:border-rose-500/50 bg-rose-950/10' 
                    : 'border-amber-500/30 hover:border-amber-500/50 bg-amber-950/10'
                }`}
              >
                {/* Confidence overlay */}
                <div className={`absolute top-0 right-0 w-24 h-24 -mr-6 -mt-6 rounded-full opacity-[0.08] ${
                  isHighConfidence ? 'bg-rose-500' : 'bg-amber-500'
                }`} />

                <div className="flex justify-between items-start">
                  <div>
                    <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded tracking-wide ${
                      isHighConfidence ? 'bg-rose-500 text-[var(--color-text-primary)]' : 'bg-amber-500 text-[#101114]'
                    }`}>
                      {isHighConfidence ? '高度危险' : '轻度警告'}
                    </span>
                    <h3 className="text-xl font-bold text-[var(--color-text-primary)] capitalize mt-2.5">{alert.anomaly_type}</h3>
                  </div>
                  <div className="text-right">
                    <span className="text-xs text-[var(--color-text-muted)]">置信度</span>
                    <p className={`text-lg font-bold ${isHighConfidence ? 'text-rose-400' : 'text-amber-400'}`}>
                      {(alert.confidence * 100).toFixed(1)}%
                    </p>
                  </div>
                </div>

                <div className="mt-5 space-y-2 border-t border-[var(--color-border-card)] pt-4 text-xs text-[var(--color-text-secondary)]">
                  <div className="flex justify-between">
                    <span>受影响区域</span>
                    <strong className="text-gray-900 dark:text-gray-200">{alert.affected_lane || '主干道 (Main Road)'}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span>几何中心相对坐标</span>
                    <strong className="text-gray-900 dark:text-gray-200">X: {alert.location_x.toFixed(0)}, Y: {alert.location_y.toFixed(0)}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span>识别时间</span>
                    <span className="text-gray-900 dark:text-gray-200">{new Date(alert.timestamp).toLocaleString()}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

    </div>
  );
}
