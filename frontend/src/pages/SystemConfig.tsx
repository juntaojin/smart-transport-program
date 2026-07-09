import { useEffect, useState } from 'react';
import { configAPI } from '../services/api';
import { Sliders, ToggleLeft, ToggleRight, Check, Cpu } from 'lucide-react';

interface ModelConfig {
  model_name: string;
  enabled: boolean;
  confidence_threshold: number;
  iou_threshold: number;
}

export default function SystemConfig() {
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState<string | null>(null);

  const loadConfigs = async () => {
    setLoading(true);
    try {
      const res = await configAPI.getModels();
      if (res.code === 200) {
        setConfigs(res.data);
      }
    } catch (err) {
      console.error('Failed to load system configs:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConfigs();
  }, []);

  const handleToggle = async (name: string, currentVal: boolean) => {
    try {
      // Find current config thresholds
      const current = configs.find(c => c.model_name === name);
      if (!current) return;

      const updatedVal = !currentVal;
      
      // Update local state first for fast response
      setConfigs(prev => prev.map(c => c.model_name === name ? { ...c, enabled: updatedVal } : c));

      // Call API
      const res = await configAPI.updateModel(name, updatedVal, current.confidence_threshold);
      if (res.code === 200) {
        triggerSuccess(name);
      }
    } catch (err) {
      alert('修改配置失败');
      // Rollback
      setConfigs(prev => prev.map(c => c.model_name === name ? { ...c, enabled: currentVal } : c));
    }
  };

  const handleThresholdChange = (name: string, val: number) => {
    setConfigs(prev => prev.map(c => c.model_name === name ? { ...c, confidence_threshold: val } : c));
  };

  const saveThreshold = async (name: string) => {
    const current = configs.find(c => c.model_name === name);
    if (!current) return;

    try {
      const res = await configAPI.updateModel(name, current.enabled, current.confidence_threshold);
      if (res.code === 200) {
        triggerSuccess(`${name}-thresh`);
      }
    } catch (err) {
      alert('更新阈值失败');
    }
  };

  const triggerSuccess = (key: string) => {
    setSavedSuccess(key);
    setTimeout(() => setSavedSuccess(null), 2000);
  };

  // Node display name mapping
  const getDisplayName = (name: string) => {
    const maps: Record<string, { title: string, desc: string, hardware: string }> = {
      vehicle_detection: {
        title: 'YOLOv8 车辆检测',
        desc: '基础节点，负责在图像帧中自动圈出机动车与非机动车。',
        hardware: 'CPU / GPU 推理'
      },
      tracking: {
        title: 'SORT 目标跟踪器',
        desc: '卡尔曼滤波与匈牙利算法，在多帧间对车辆分配唯一的 ID 并平滑轨迹。',
        hardware: '轻量计算节点'
      },
      plate_ocr: {
        title: 'EasyOCR 车牌识别',
        desc: '对车辆底部进行局部裁剪后识别出中英文车牌号。',
        hardware: '较重计算负载'
      },
      anomaly_detection: {
        title: 'Grounding DINO 异常物体检测',
        desc: '使用文本提示词，在路面上无监督地捕捉障碍物、货物撒落及垃圾等。',
        hardware: '深度学习大模型 (显存占比大)'
      },
      violation_detection: {
        title: '禁停区违停研判',
        desc: '判定车辆在自定义多边形禁停区内驻车时间是否超出指定上限的逻辑引擎。',
        hardware: '纯数学计算'
      }
    };
    return maps[name] || { title: name, desc: '系统推理算法节点', hardware: '标准节点' };
  };

  return (
    <div className="space-y-6">
      
      {/* 头部说明 */}
      <div className="glass-panel rounded-3xl p-6">
        <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
          <Sliders className="text-blue-400" />
          推理流水线动态资源管控
        </h2>
        <p className="text-slate-400 text-sm mt-1">
          本页面可实时管控 FastAPI 的推理引擎。**禁用不常用节点将立即释放对应的显存与算力**，实现极高的运行效能。
        </p>
      </div>

      {loading && configs.length === 0 ? (
        <div className="text-center py-12">
          <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-slate-500 text-sm">正在加载流水线参数配置...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {configs.map((config, index) => {
            const info = getDisplayName(config.model_name);
            const isSaved = savedSuccess === config.model_name || savedSuccess === `${config.model_name}-thresh`;
            return (
              <div 
                key={index} 
                className={`glass-panel rounded-3xl p-6 border transition-all duration-300 ${
                  config.enabled 
                    ? 'border-blue-500/20 shadow-lg shadow-blue-500/5' 
                    : 'border-white/5 bg-slate-900/10'
                }`}
              >
                
                {/* 标题 & 开关 */}
                <div className="flex justify-between items-start gap-4">
                  <div>
                    <h3 className="text-lg font-bold text-slate-100">{info.title}</h3>
                    <span className="text-[10px] text-slate-500 mt-1 uppercase tracking-wider block font-mono">
                      系统标识: {config.model_name}
                    </span>
                  </div>

                  <button 
                    type="button" 
                    onClick={() => handleToggle(config.model_name, config.enabled)}
                    className={`focus:outline-none transition-colors duration-250 ${
                      config.enabled ? 'text-blue-500' : 'text-slate-600'
                    }`}
                  >
                    {config.enabled ? <ToggleRight size={44} /> : <ToggleLeft size={44} />}
                  </button>
                </div>

                {/* 描述 */}
                <p className="text-xs text-slate-400 mt-3 leading-relaxed">
                  {info.desc}
                </p>

                {/* 控制与数值调节 */}
                {config.enabled && (
                  <div className="mt-5 pt-4 border-t border-white/5 space-y-4">
                    {/* Threshold slider */}
                    <div>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-slate-400">检测置信度阈值 (Confidence)</span>
                        <span className="font-bold text-blue-400">{config.confidence_threshold.toFixed(2)}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <input 
                          type="range" 
                          min="0.1" 
                          max="0.9" 
                          step="0.05"
                          value={config.confidence_threshold}
                          onChange={e => handleThresholdChange(config.model_name, parseFloat(e.target.value))}
                          className="flex-1 accent-blue-500"
                        />
                        <button 
                          type="button"
                          onClick={() => saveThreshold(config.model_name)}
                          className="bg-white/5 hover:bg-blue-500 hover:text-dark-900 border border-white/10 px-3 py-1 rounded-lg text-xs font-semibold hover-scale"
                        >
                          保存
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Footer status */}
                <div className="mt-6 flex justify-between items-center text-[10px] text-slate-500">
                  <span className="flex items-center gap-1">
                    <Cpu size={10} /> {info.hardware}
                  </span>
                  {isSaved ? (
                    <span className="text-emerald-400 flex items-center gap-0.5">
                      <Check size={10} /> 配置更新成功
                    </span>
                  ) : (
                    <span>
                      当前状态: <strong className={config.enabled ? 'text-emerald-400' : 'text-slate-500'}>
                        {config.enabled ? '已加载且工作中' : '挂起并闲置释放'}
                      </strong>
                    </span>
                  )}
                </div>

              </div>
            );
          })}
        </div>
      )}

    </div>
  );
}
