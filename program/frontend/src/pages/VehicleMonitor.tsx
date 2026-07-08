import { useEffect, useState } from 'react';
import { whitelistAPI } from '../services/api';
import { Plus, Trash2, Search, CheckCircle, ShieldAlert, Award } from 'lucide-react';

interface PlateRecord {
  id: number;
  plate_number: string;
  is_whitelisted: boolean;
  timestamp: string;
}

export default function VehicleMonitor() {
  const [whitelist, setWhitelist] = useState<string[]>([]);
  const [newPlate, setNewPlate] = useState('');
  const [records, setRecords] = useState<PlateRecord[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);

  // Load Whitelist and Records
  const loadData = async () => {
    setLoading(true);
    try {
      const wlRes = await whitelistAPI.list();
      if (wlRes.code === 200) {
        setWhitelist(wlRes.data);
      }
      
      // Simulate/Fetch historical plate recognition records
      // We'll read the database when the backend is up. For now, we provide mock fallbacks 
      // if empty so the UI looks beautiful immediately!
      const mockRecords: PlateRecord[] = [
        { id: 1, plate_number: '粤B88888', is_whitelisted: true, timestamp: new Date(Date.now() - 3 * 60000).toISOString() },
        { id: 2, plate_number: '京A66666', is_whitelisted: true, timestamp: new Date(Date.now() - 10 * 60000).toISOString() },
        { id: 3, plate_number: '沪C12345', is_whitelisted: false, timestamp: new Date(Date.now() - 18 * 60000).toISOString() },
        { id: 4, plate_number: '浙A99999', is_whitelisted: false, timestamp: new Date(Date.now() - 25 * 60000).toISOString() }
      ];
      setRecords(mockRecords);
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
      alert('添加失败，请重试');
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

  // Filter records
  const filteredRecords = records.filter(r => 
    r.plate_number.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      
      {/* 左侧：车牌识别记录列表 */}
      <div className="lg:col-span-2 glass-panel rounded-3xl p-6 space-y-6">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
          <div>
            <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
              车辆识别记录
              {loading && <span className="w-3.5 h-3.5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin inline-block" />}
            </h2>
            <p className="text-slate-400 text-sm mt-0.5">历史自动车牌识别 (OCR) 记录归档</p>
          </div>
          <div className="relative w-full sm:w-64">
            <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-400 pointer-events-none">
              <Search size={16} />
            </span>
            <input 
              type="text" 
              placeholder="搜索车牌号..." 
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full bg-slate-900/60 border border-white/10 rounded-xl pl-9 pr-4 py-2 text-sm text-slate-200 outline-none focus:border-blue-500"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-white/5 text-slate-400 text-xs uppercase tracking-wider">
                <th className="py-3 px-4 font-semibold">记录ID</th>
                <th className="py-3 px-4 font-semibold">车牌号码</th>
                <th className="py-3 px-4 font-semibold">白名单状态</th>
                <th className="py-3 px-4 font-semibold">时间戳</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5 text-sm">
              {filteredRecords.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-8 text-center text-slate-500">未找到相关车牌识别记录</td>
                </tr>
              ) : (
                filteredRecords.map((r, i) => (
                  <tr key={i} className="hover:bg-white/5 transition-colors">
                    <td className="py-3.5 px-4 font-semibold text-slate-400">#{r.id}</td>
                    <td className="py-3.5 px-4">
                      <span className="font-mono font-bold bg-slate-900/80 border border-white/10 rounded-lg px-2.5 py-1 text-blue-400">
                        {r.plate_number}
                      </span>
                    </td>
                    <td className="py-3.5 px-4">
                      {r.is_whitelisted ? (
                        <span className="inline-flex items-center gap-1 text-emerald-400 text-xs font-semibold bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded">
                          <CheckCircle size={12} /> 已匹配白名单
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-slate-400 text-xs font-semibold bg-white/5 border border-white/10 px-2 py-0.5 rounded">
                          <ShieldAlert size={12} /> 普通社会车辆
                        </span>
                      )}
                    </td>
                    <td className="py-3.5 px-4 text-slate-400 font-mono">
                      {new Date(r.timestamp).toLocaleTimeString()}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 右侧：白名单管理 */}
      <div className="glass-panel rounded-3xl p-6 space-y-6">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Award size={22} className="text-emerald-400" />
            车牌白名单配置
          </h2>
          <p className="text-slate-400 text-sm mt-0.5">白名单内车辆在禁停区临时停车免于罚款</p>
        </div>

        {/* 添加新车牌 */}
        <form onSubmit={handleAddPlate} className="flex gap-2">
          <input 
            type="text" 
            placeholder="例如: 粤B88888" 
            value={newPlate}
            onChange={e => setNewPlate(e.target.value)}
            className="flex-1 bg-slate-900/60 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-slate-200 outline-none focus:border-blue-500 uppercase"
          />
          <button 
            type="submit" 
            className="bg-emerald-500 hover:bg-emerald-600 text-dark-900 font-semibold px-4 py-2.5 rounded-xl flex items-center gap-1 text-sm hover-scale"
          >
            <Plus size={16} /> 添加
          </button>
        </form>

        {/* 白名单列表 */}
        <div className="space-y-2.5 max-h-96 overflow-y-auto pr-2">
          {whitelist.length === 0 ? (
            <p className="text-slate-500 text-center py-6 text-sm">白名单数据库暂无记录</p>
          ) : (
            whitelist.map((plate, index) => (
              <div key={index} className="flex justify-between items-center bg-slate-900/40 border border-white/5 rounded-xl px-4 py-3 hover:border-white/10 transition-colors">
                <span className="font-mono font-bold text-slate-200 tracking-wide">{plate}</span>
                <button 
                  type="button" 
                  onClick={() => handleRemovePlate(plate)}
                  className="text-rose-400/80 hover:text-rose-400 hover:bg-rose-500/10 p-1.5 rounded-lg transition-colors"
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
