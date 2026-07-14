import { useEffect, useState } from 'react';
import { configAPI } from '../services/api';
import { Sliders, ToggleLeft, ToggleRight, Check, Cpu } from 'lucide-react';

interface ModelConfig {
  model_name: string;
  enabled: boolean;
  requires_vehicle_pipeline: boolean;
  parameters: Record<string, number>;
  parameter_schema: Record<string, ParameterDefinition>;
  runtime_status: {
    state: 'ready' | 'error' | 'unloaded';
    loaded: boolean;
    path: string | null;
    error: string | null;
  } | null;
}

interface ParameterDefinition {
  label: string;
  type: 'number';
  min: number;
  max: number;
  step: number;
  apply_mode: 'hot';
}

export default function SystemConfig() {
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
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
      const current = configs.find(c => c.model_name === name);
      if (!current) return;

      const updatedVal = !currentVal;
      
      // Update local state first for fast response
      setConfigs(prev => prev.map(c => c.model_name === name ? { ...c, enabled: updatedVal } : c));

      // Call API
      const res = await configAPI.updateModel(name, updatedVal);
      if (res.code === 200) {
        triggerSuccess(name);
        await loadConfigs();
      }
    } catch {
      alert('修改配置失败');
      // Rollback
      setConfigs(prev => prev.map(c => c.model_name === name ? { ...c, enabled: currentVal } : c));
    }
  };

  const handleParameterChange = (modelName: string, key: string, value: number) => {
    setConfigs(prev => prev.map(config => config.model_name === modelName
      ? { ...config, parameters: { ...config.parameters, [key]: value } }
      : config));
  };

  const handleSaveParameters = async (config: ModelConfig) => {
    setSaving(config.model_name);
    try {
      const res = await configAPI.updateModel(config.model_name, undefined, config.parameters);
      if (res.code === 200) {
        triggerSuccess(config.model_name);
        await loadConfigs();
      }
    } catch (err: any) {
      alert(`参数保存失败: ${err?.message || '网络错误'}`);
      await loadConfigs();
    } finally {
      setSaving(null);
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
        title: '车辆识别与持续追踪',
        desc: '追踪属于车辆识别基础链路，无需单独配置。',
        hardware: 'YOLO + ByteTrack · GPU 推理'
      },
      plate_ocr: {
        title: '车牌识别',
        desc: '开启时会自动启用车辆识别与追踪。',
        hardware: 'HyperLPR3 · 依赖车辆识别'
      },
      anomaly_detection: {
        title: '异常物体检测',
        desc: '泛化异常检测',
        hardware: ''
      },
      violation_detection: {
        title: '禁停区超时研判',
        desc: '根据持续追踪 ID 判断车辆在禁停区内的停留时间。开启时会自动启用车辆识别与追踪。',
        hardware: '规则引擎 · 依赖车辆识别'
      }
    };
    return maps[name] || { title: name, desc: '系统推理算法节点', hardware: '标准节点' };
  };

  return (
    <div className="space-y-6">
      
      {/* 头部说明 */}
      <div className="dashboard-card p-6">
        <h2 className="text-xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
          <Sliders className="text-blue-400" />
          推理流水线动态资源管控
        </h2>
        <p className="text-[var(--color-text-secondary)] text-sm mt-1">
          模型参数保存后从下一帧热更新，无需重启服务。
        </p>
      </div>

      {loading && configs.length === 0 ? (
        <div className="text-center py-12">
          <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-[var(--color-text-muted)] text-sm">正在加载流水线参数配置...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {configs.map((config, index) => {
            const info = getDisplayName(config.model_name);
            const isSaved = savedSuccess === config.model_name;
            return (
              <div 
                key={index} 
                className={`dashboard-card p-6 border transition-all duration-300 ${
                  config.enabled 
                    ? 'border-blue-500/20 shadow-lg shadow-blue-500/5' 
                    : 'border-[var(--color-border-card)] bg-gray-100 dark:bg-[#101114]/50'
                }`}
              >
                
                {/* 标题 & 开关 */}
                <div className="flex justify-between items-start gap-4">
                  <div>
                    <h3 className="text-lg font-bold text-[var(--color-text-primary)]">{info.title}</h3>
                    <span className="text-[10px] text-[var(--color-text-muted)] mt-1 uppercase tracking-wider block font-mono">
                      系统标识: {config.model_name}
                    </span>
                    {config.runtime_status && (
                      <span className={`mt-2 inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold ${
                        config.runtime_status.state === 'ready'
                          ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
                          : config.runtime_status.state === 'error'
                            ? 'border-rose-500/20 bg-rose-500/10 text-rose-400'
                            : 'border-gray-500/20 bg-gray-500/10 text-[var(--color-text-muted)]'
                      }`} title={config.runtime_status.error || config.runtime_status.path || undefined}>
                        {config.runtime_status.state === 'ready'
                          ? '模型已加载'
                          : config.runtime_status.state === 'error'
                            ? '模型加载失败'
                            : '模型未加载'}
                      </span>
                    )}
                  </div>

                  <button 
                    type="button" 
                    onClick={() => handleToggle(config.model_name, config.enabled)}
                    className={`focus:outline-none transition-colors duration-250 ${
                      config.enabled ? 'text-blue-500' : 'text-gray-600'
                    }`}
                  >
                    {config.enabled ? <ToggleRight size={44} /> : <ToggleLeft size={44} />}
                  </button>
                </div>

                {/* 描述 */}
                <p className="text-xs text-[var(--color-text-secondary)] mt-3 leading-relaxed">
                  {info.desc}
                </p>

                {Object.keys(config.parameter_schema).length > 0 && (
                  <div className="mt-5 space-y-4 border-t border-[var(--color-border-card)] pt-4">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-[var(--color-text-primary)]">运行参数</span>
                      <span className="text-[10px] text-emerald-400">下一帧生效</span>
                    </div>
                    {Object.entries(config.parameter_schema).map(([key, definition]) => (
                      <label key={key} className="block">
                        <div className="mb-2 flex items-center justify-between gap-3 text-xs">
                          <span className="text-[var(--color-text-secondary)]">{definition.label}</span>
                          <input
                            type="number"
                            min={definition.min}
                            max={definition.max}
                            step={definition.step}
                            value={config.parameters[key]}
                            onChange={event => handleParameterChange(config.model_name, key, Number(event.target.value))}
                            className="w-24 rounded-lg border border-[var(--color-border-card)] bg-transparent px-2 py-1 text-right text-[var(--color-text-primary)] outline-none focus:border-blue-500"
                          />
                        </div>
                        <input
                          type="range"
                          min={definition.min}
                          max={definition.max}
                          step={definition.step}
                          value={config.parameters[key]}
                          onChange={event => handleParameterChange(config.model_name, key, Number(event.target.value))}
                          className="w-full accent-blue-500"
                        />
                      </label>
                    ))}
                    <button
                      type="button"
                      disabled={saving === config.model_name}
                      onClick={() => handleSaveParameters(config)}
                      className="w-full rounded-xl bg-blue-500/15 px-3 py-2 text-xs font-semibold text-blue-400 transition-colors hover:bg-blue-500/25 disabled:cursor-wait disabled:opacity-60"
                    >
                      {saving === config.model_name ? '正在保存...' : '保存并热更新'}
                    </button>
                  </div>
                )}

                {/* Footer status */}
                <div className="mt-6 flex justify-between items-center text-[10px] text-[var(--color-text-muted)]">
                  <span className="flex items-center gap-1">
                    <Cpu size={10} /> {info.hardware}
                  </span>
                  {isSaved ? (
                    <span className="text-emerald-400 flex items-center gap-0.5">
                      <Check size={10} /> 配置更新成功
                    </span>
                  ) : (
                    <span>
                      当前状态: <strong className={config.enabled ? 'text-emerald-400' : 'text-[var(--color-text-muted)]'}>
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
