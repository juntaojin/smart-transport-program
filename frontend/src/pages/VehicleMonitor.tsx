import { useEffect, useState } from 'react';
import { statsAPI, whitelistAPI } from '../services/api';
import { Plus, Trash2, Search, CheckCircle, ShieldAlert, Award } from 'lucide-react';

interface PlateRecord {
  id: number;
  plate_number: string;
  is_whitelisted: boolean;
  timestamp: string;
}

const formatRecordDate = (timestamp: string) => {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }

  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const seconds = String(date.getSeconds()).padStart(2, '0');
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
};

export default function VehicleMonitor() {
  const [whitelist, setWhitelist] = useState<string[]>([]);
  const [newPlate, setNewPlate] = useState('');
  const [records, setRecords] = useState<PlateRecord[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [deletingRecordIds, setDeletingRecordIds] = useState<Set<number>>(new Set());

  // Load Whitelist and Records
  const loadData = async () => {
    setLoading(true);
    try {
      const wlRes = await whitelistAPI.list();
      if (wlRes.code === 200) {
        setWhitelist(wlRes.data);
      }
      
      const recordsRes = await statsAPI.plateRecords();
      if (recordsRes.code === 200 && Array.isArray(recordsRes.data)) {
        setRecords(recordsRes.data);
      }
    } catch (err) {
      console.error('Failed to load vehicle monitor data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, []);

  // Add Plate to Whitelist
  const handleAddPlate = async (e: any) => {
    e.preventDefault();
    if (!newPlate.trim()) return;
    try {
      const res = await whitelistAPI.add(newPlate.toUpperCase().trim());
      if (res.code === 200) {
        setWhitelist(res.data);
        setNewPlate('');
        // Also update local record state status if matching
        setRecords(prev => prev.map(r => r.plate_number === newPlate.toUpperCase().trim() ? { ...r, is_whitelisted: true } : r));
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : '添加失败，请重试');
    }
  };

  // Remove Plate from Whitelist
  const handleRemovePlate = async (plate: string) => {
    try {
      const res = await whitelistAPI.remove(plate);
      if (res.code === 200) {
        setWhitelist(res.data);
        setRecords(prev => prev.map(r => r.plate_number === plate ? { ...r, is_whitelisted: false } : r));
      }
    } catch (err) {
      alert('移除失败');
    }
  };

  // Delete a single plate recognition record
  const handleDeleteRecord = async (recordId: number) => {
    if (!window.confirm(`确定删除记录 #${recordId} 吗？`)) return;

    setDeletingRecordIds(prev => new Set(prev).add(recordId));
    try {
      const res = await statsAPI.deletePlateRecord(recordId);
      if (res.code === 200) {
        setRecords(prev => prev.filter(r => r.id !== recordId));
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除记录失败，请重试');
    } finally {
      setDeletingRecordIds(prev => {
        const next = new Set(prev);
        next.delete(recordId);
        return next;
      });
    }
  };

  // Filter records
  const filteredRecords = records.filter(r => 
    r.plate_number.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      
      {/* 左侧：车牌识别记录列表 */}
      <div className="lg:col-span-2 dashboard-card p-6 space-y-6">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
          <div>
            <h2 className="text-xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
              车辆识别记录
              {loading && <span className="w-3.5 h-3.5 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin inline-block" />}
            </h2>
            <p className="text-[var(--color-text-secondary)] text-sm mt-0.5">历史自动车牌识别 (OCR) 记录归档</p>
          </div>
          <div className="relative w-full sm:w-64">
            <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-[var(--color-text-muted)] pointer-events-none">
              <Search size={16} />
            </span>
            <input 
              type="text" 
              placeholder="搜索车牌号..." 
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full bg-white/90 dark:bg-[#1C1C22]/90 border border-[var(--color-border-card)] rounded-xl pl-9 pr-4 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-emerald-500 transition-colors"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-[var(--color-border-card)] text-[var(--color-text-secondary)] text-xs uppercase tracking-wider">
                <th className="py-3 px-4 font-semibold">记录ID</th>
                <th className="py-3 px-4 font-semibold">车牌号码</th>
                <th className="py-3 px-4 font-semibold">白名单状态</th>
                <th className="py-3 px-4 font-semibold">时间戳</th>
                <th className="py-3 px-4 font-semibold text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#222328]/50 text-sm">
              {filteredRecords.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-[var(--color-text-muted)]">未找到相关车牌识别记录</td>
                </tr>
              ) : (
                filteredRecords.map((r) => (
                  <tr key={r.id} className="hover:hover:bg-gray-100 dark:hover:bg-[#1C1E24]/40 transition-colors group">
                    <td className="py-3.5 px-4 font-semibold text-[var(--color-text-muted)]">#{r.id}</td>
                    <td className="py-3.5 px-4">
                      <span className="font-mono font-bold bg-gray-100 dark:bg-[#101114] border border-[var(--color-border-card)] rounded-lg px-2.5 py-1 text-emerald-400 group-hover:border-emerald-500/30 transition-colors">
                        {r.plate_number}
                      </span>
                    </td>
                    <td className="py-3.5 px-4">
                      {r.is_whitelisted ? (
                        <span className="inline-flex items-center gap-1 text-emerald-400 text-xs font-semibold bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">
                          <CheckCircle size={12} /> 已匹配白名单
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-[var(--color-text-secondary)] text-xs font-semibold bg-gray-100 dark:bg-[#101114] border border-[var(--color-border-card)] px-2 py-0.5 rounded-full">
                          <ShieldAlert size={12} /> 普通社会车辆
                        </span>
                      )}
                    </td>
                    <td className="py-3.5 px-4 text-[var(--color-text-secondary)] font-mono text-xs">
                      {formatRecordDate(r.timestamp)}
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <button
                        type="button"
                        onClick={() => handleDeleteRecord(r.id)}
                        disabled={deletingRecordIds.has(r.id)}
                        className="inline-flex items-center justify-center text-rose-500/80 hover:text-rose-400 hover:bg-rose-500/10 disabled:opacity-50 disabled:cursor-not-allowed p-1.5 rounded-lg transition-colors"
                        title="删除记录"
                      >
                        <Trash2 size={16} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 右侧：白名单管理 */}
      <div className="dashboard-card p-6 space-y-6">
        <div>
          <h2 className="text-xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
            <Award size={22} className="text-emerald-400" />
            车牌白名单配置
          </h2>
          <p className="text-[var(--color-text-secondary)] text-sm mt-0.5">白名单内车辆在可开闸</p>
        </div>

        {/* 添加新车牌 */}
        <form onSubmit={handleAddPlate} className="flex gap-2">
          <input 
            type="text" 
            placeholder="例如: 粤B88888" 
            value={newPlate}
            onChange={e => setNewPlate(e.target.value)}
            className="flex-1 bg-white/90 dark:bg-[#1C1C22]/90 border border-[var(--color-border-card)] rounded-xl px-4 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-emerald-500 uppercase transition-colors"
          />
          <button 
            type="submit" 
            className="bg-emerald-500 hover:bg-emerald-600 text-[#101114] font-bold px-4 py-2.5 rounded-xl flex items-center gap-1 text-sm hover:scale-105 transition-transform"
          >
            <Plus size={16} /> 添加
          </button>
        </form>

        {/* 白名单列表 */}
        <div className="space-y-2.5 max-h-96 overflow-y-auto pr-2">
          {whitelist.length === 0 ? (
            <p className="text-[var(--color-text-muted)] text-center py-6 text-sm">白名单数据库暂无记录</p>
          ) : (
            whitelist.map((plate, index) => (
              <div key={index} className="flex justify-between items-center bg-gray-100 dark:bg-[#101114] border border-[var(--color-border-card)] rounded-xl px-4 py-3 hover:border-[var(--color-border-card)] transition-colors">
                <span className="font-mono font-bold text-gray-900 dark:text-gray-200 tracking-wide">{plate}</span>
                <button 
                  type="button" 
                  onClick={() => handleRemovePlate(plate)}
                  className="text-rose-500/80 hover:text-rose-400 hover:bg-rose-500/10 p-1.5 rounded-lg transition-colors"
                  title="移除白名单"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

    </div>
  );
}
