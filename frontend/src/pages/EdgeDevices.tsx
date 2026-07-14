import { useEffect, useState } from 'react';
import { edgeAPI } from '../services/api';
import { RefreshCw, Router, ShieldCheck, ShieldX, Trash2 } from 'lucide-react';

interface EdgeDevice {
  device_id: string;
  device_name: string;
  source_mode: string;
  last_ip: string;
  allowed: boolean;
  first_registered_at: string | null;
  last_verified_at: string | null;
  last_stream_at: string | null;
}

interface EdgeStreamRecord {
  id: number;
  device_id: string;
  device_name: string;
  source_mode: string;
  client_ip: string;
  started_at: string | null;
  ended_at: string | null;
  status: string;
  frames_received: number;
}

const formatDate = (value: string | null) => {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

export default function EdgeDevices() {
  const [devices, setDevices] = useState<EdgeDevice[]>([]);
  const [records, setRecords] = useState<EdgeStreamRecord[]>([]);
  const [loading, setLoading] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await edgeAPI.devices(200);
      if (res.code === 200) {
        setDevices(res.data.devices || []);
        setRecords(res.data.records || []);
      }
    } catch (err) {
      console.error('Failed to load edge devices:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const timer = window.setInterval(loadData, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const handleRevoke = async (deviceId: string) => {
    if (!window.confirm(`确定撤销边端 ${deviceId} 的推流权限吗？`)) return;
    try {
      const res = await edgeAPI.revokeDevice(deviceId);
      if (res.code === 200) await loadData();
    } catch (err) {
      alert(err instanceof Error ? err.message : '撤销失败');
    }
  };

  return (
    <div className="space-y-6">
      <div className="dashboard-card p-6 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
            <Router className="text-sky-400" />
            边端信息管理
          </h2>
          <p className="text-[var(--color-text-secondary)] text-sm mt-0.5">管理已通过验证码授权的推流设备与历史推流记录</p>
        </div>
        <button
          type="button"
          onClick={loadData}
          disabled={loading}
          className="bg-white/90 dark:bg-[#1C1C22]/90 border border-[var(--color-border-card)] hover:bg-[#222328] text-gray-900 dark:text-gray-200 px-4 py-2.5 rounded-xl flex items-center gap-2 text-sm font-semibold disabled:opacity-50 transition-all"
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      <div className="dashboard-card p-6">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">允许推流设备 ({devices.length})</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b border-[var(--color-border-card)] text-[var(--color-text-secondary)] text-xs uppercase tracking-wider">
                <th className="py-3 px-4 font-semibold">设备</th>
                <th className="py-3 px-4 font-semibold">来源</th>
                <th className="py-3 px-4 font-semibold">IP</th>
                <th className="py-3 px-4 font-semibold">状态</th>
                <th className="py-3 px-4 font-semibold">最近授权</th>
                <th className="py-3 px-4 font-semibold">最近推流</th>
                <th className="py-3 px-4 font-semibold text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#222328]/50">
              {devices.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-[var(--color-text-muted)]">暂无已授权边端设备</td>
                </tr>
              ) : devices.map(device => (
                <tr key={device.device_id} className="hover:bg-gray-100 dark:hover:bg-[#1C1E24]/40 transition-colors">
                  <td className="py-3.5 px-4">
                    <div className="font-semibold text-[var(--color-text-primary)]">{device.device_name || device.device_id}</div>
                    <div className="text-xs font-mono text-[var(--color-text-muted)]">{device.device_id}</div>
                  </td>
                  <td className="py-3.5 px-4 text-[var(--color-text-secondary)]">{device.source_mode}</td>
                  <td className="py-3.5 px-4 font-mono text-xs text-[var(--color-text-secondary)]">{device.last_ip || '-'}</td>
                  <td className="py-3.5 px-4">
                    {device.allowed ? (
                      <span className="inline-flex items-center gap-1 text-emerald-400 text-xs font-semibold bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">
                        <ShieldCheck size={12} /> 已授权
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-rose-400 text-xs font-semibold bg-rose-500/10 border border-rose-500/20 px-2 py-0.5 rounded-full">
                        <ShieldX size={12} /> 已撤销
                      </span>
                    )}
                  </td>
                  <td className="py-3.5 px-4 text-xs text-[var(--color-text-secondary)]">{formatDate(device.last_verified_at)}</td>
                  <td className="py-3.5 px-4 text-xs text-[var(--color-text-secondary)]">{formatDate(device.last_stream_at)}</td>
                  <td className="py-3.5 px-4 text-right">
                    <button
                      type="button"
                      onClick={() => handleRevoke(device.device_id)}
                      disabled={!device.allowed}
                      className="inline-flex items-center justify-center text-rose-500/80 hover:text-rose-400 hover:bg-rose-500/10 disabled:opacity-40 disabled:cursor-not-allowed p-1.5 rounded-lg transition-colors"
                      title="撤销推流权限"
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="dashboard-card p-6">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">推流记录 ({records.length})</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b border-[var(--color-border-card)] text-[var(--color-text-secondary)] text-xs uppercase tracking-wider">
                <th className="py-3 px-4 font-semibold">记录ID</th>
                <th className="py-3 px-4 font-semibold">设备</th>
                <th className="py-3 px-4 font-semibold">来源</th>
                <th className="py-3 px-4 font-semibold">开始</th>
                <th className="py-3 px-4 font-semibold">结束</th>
                <th className="py-3 px-4 font-semibold">帧数</th>
                <th className="py-3 px-4 font-semibold">状态</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#222328]/50">
              {records.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-[var(--color-text-muted)]">暂无推流记录</td>
                </tr>
              ) : records.map(record => (
                <tr key={record.id} className="hover:bg-gray-100 dark:hover:bg-[#1C1E24]/40 transition-colors">
                  <td className="py-3.5 px-4 font-semibold text-[var(--color-text-muted)]">#{record.id}</td>
                  <td className="py-3.5 px-4">
                    <div className="font-semibold text-[var(--color-text-primary)]">{record.device_name || record.device_id}</div>
                    <div className="text-xs font-mono text-[var(--color-text-muted)]">{record.device_id}</div>
                  </td>
                  <td className="py-3.5 px-4 text-[var(--color-text-secondary)]">{record.source_mode}</td>
                  <td className="py-3.5 px-4 text-xs text-[var(--color-text-secondary)]">{formatDate(record.started_at)}</td>
                  <td className="py-3.5 px-4 text-xs text-[var(--color-text-secondary)]">{formatDate(record.ended_at)}</td>
                  <td className="py-3.5 px-4 font-mono text-xs text-[var(--color-text-secondary)]">{record.frames_received}</td>
                  <td className="py-3.5 px-4">
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold border bg-sky-500/10 text-sky-400 border-sky-500/20">
                      {record.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
