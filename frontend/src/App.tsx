import { useState, useEffect } from 'react';
import Dashboard from './pages/Dashboard';
import VehicleMonitor from './pages/VehicleMonitor';
import AnomalyAlerts from './pages/AnomalyAlerts';
import SystemConfig from './pages/SystemConfig';
import IPMCalibration from './pages/IPMCalibration';
import EdgeDevices from './pages/EdgeDevices';
import { edgeAPI } from './services/api';
import { LayoutDashboard, Car, ShieldAlert, Sliders, MapPin, Sun, Moon, Router } from 'lucide-react';

type Tab = 'dashboard' | 'vehicles' | 'anomalies' | 'config' | 'edge' | 'ipm';

interface PendingEdgeRegistration {
  request_id: string;
  code: string;
  device_id: string;
  stream_device_id?: string;
  device_name: string;
  source_mode: string;
  client_ip: string;
  expires_at: string;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [isDarkMode, setIsDarkMode] = useState(true);
  const [pendingEdgeRegistrations, setPendingEdgeRegistrations] = useState<PendingEdgeRegistration[]>([]);

  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkMode]);

  useEffect(() => {
    const loadPendingRegistrations = async () => {
      try {
        const res = await edgeAPI.pendingRegistrations();
        if (res.code === 200 && Array.isArray(res.data)) {
          setPendingEdgeRegistrations(res.data);
        }
      } catch (err) {
        console.error('Failed to load pending edge registrations:', err);
      }
    };

    loadPendingRegistrations();
    const timer = window.setInterval(loadPendingRegistrations, 1500);
    return () => window.clearInterval(timer);
  }, []);

  const tabs = [
    { id: 'dashboard', label: '监控', icon: LayoutDashboard },
    { id: 'vehicles', label: '车辆与识别', icon: Car },
    { id: 'anomalies', label: '抛洒与异常', icon: ShieldAlert },
    { id: 'config', label: '模型控制', icon: Sliders },
    { id: 'edge', label: '边端管理', icon: Router },
    { id: 'ipm', label: '热力图', icon: MapPin },
  ];

  const renderContent = () => {
    switch (activeTab) {
      case 'dashboard':
        return <Dashboard />;
      case 'vehicles':
        return <VehicleMonitor />;
      case 'anomalies':
        return <AnomalyAlerts />;
      case 'config':
        return <SystemConfig />;
      case 'edge':
        return <EdgeDevices />;
      case 'ipm':
        return <IPMCalibration />;
      default:
        return <Dashboard />;
    }
  };

  return (
    <div className="flex flex-col min-h-screen bg-[var(--color-bg-canvas)] text-[var(--color-text-primary)] font-sans overflow-hidden transition-colors duration-300">
      <header className="bg-[var(--color-bg-card)] border-b border-[var(--color-border-card)] px-4 sm:px-6 py-3 flex items-center justify-between shrink-0 z-10 shadow-md transition-colors duration-300">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gray-200 dark:bg-[#1C1E24] border border-[var(--color-border-card)] flex items-center justify-center transition-colors">
            <span className="text-gray-900 dark:text-white font-extrabold text-lg select-none">T</span>
          </div>
          <div className="hidden lg:block">
            <h1 className="font-bold text-lg leading-none tracking-tight text-[var(--color-text-primary)]">云边端智慧交通系统</h1>
          </div>
        </div>

        <nav className="flex items-center gap-1 sm:gap-2">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id as Tab)}
                className={`flex items-center gap-2 px-3 py-1.5 sm:px-4 sm:py-2 rounded-lg text-[13px] font-semibold transition-all ${
                  isActive
                    ? 'bg-white dark:bg-[#1C1E24] text-gray-900 dark:text-white border border-gray-200 dark:border-white/5 shadow-sm'
                    : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 border border-transparent'
                }`}
              >
                <Icon size={16} />
                <span className="hidden md:inline">{tab.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="flex items-center gap-2 sm:gap-4">
          <button
            onClick={() => setIsDarkMode(!isDarkMode)}
            className="p-1.5 rounded-full text-gray-500 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#1C1E24] transition-colors focus:outline-none"
            aria-label="Toggle Dark Mode"
          >
            {isDarkMode ? <Sun size={18} /> : <Moon size={18} />}
          </button>

          <div className="flex items-center gap-3 pl-2 pr-3 py-1 rounded-full border border-[var(--color-border-card)] bg-gray-50 dark:bg-[#1C1E24]/50 hover:bg-gray-100 dark:hover:bg-[#1C1E24] transition-all shadow-sm cursor-pointer">
            <div className="w-7 h-7 rounded-full overflow-hidden bg-brand-blue flex items-center justify-center font-bold text-[11px] text-white">
              EC
            </div>
            <div className="text-left hidden sm:block">
              <p className="text-xs font-semibold leading-3 text-[var(--color-text-primary)]">Ethan Cole</p>
              <span className="text-[10px] text-gray-500 font-medium">Dispatch Officer</span>
            </div>
          </div>
        </div>
      </header>

      <div className="flex-1 flex flex-col overflow-y-auto max-h-[calc(100vh-60px)] relative bg-[var(--color-bg-canvas)]">
        <main className="p-4 sm:p-6 md:p-8 flex-1 animate-fade-in max-w-[1600px] mx-auto w-full">
          {renderContent()}
        </main>

        {pendingEdgeRegistrations.length > 0 && (
          <div className="fixed right-5 top-20 z-50 w-[min(420px,calc(100vw-40px))] space-y-3">
            {pendingEdgeRegistrations.slice(0, 3).map(item => (
              <div key={item.request_id} className="dashboard-card border border-sky-500/30 bg-white/95 dark:bg-[#111827]/95 p-5 shadow-2xl backdrop-blur-md">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-bold text-[var(--color-text-primary)] flex items-center gap-2">
                      <Router size={16} className="text-sky-400" />
                      边端推流注册
                    </h3>
                    <p className="mt-1 text-xs text-[var(--color-text-secondary)]">请把验证码输入到边端推流页面</p>
                  </div>
                  <span className="rounded-full border border-sky-500/20 bg-sky-500/10 px-2 py-1 text-[10px] font-semibold text-sky-400">
                    {item.source_mode}
                  </span>
                </div>
                <div className="my-4 rounded-xl border border-[var(--color-border-card)] bg-gray-100 dark:bg-[#0B1220] px-4 py-3 text-center">
                  <div className="font-mono text-3xl font-black tracking-[0.25em] text-sky-400">{item.code}</div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs text-[var(--color-text-secondary)]">
                  <span>设备</span>
                  <strong className="text-right text-[var(--color-text-primary)] truncate">{item.device_name || item.device_id}</strong>
                  <span>边端 UID</span>
                  <strong className="text-right font-mono text-[var(--color-text-primary)] truncate">{item.device_id}</strong>
                  <span>推流通道</span>
                  <strong className="text-right font-mono text-[var(--color-text-primary)] truncate">{item.stream_device_id || '-'}</strong>
                  <span>来源 IP</span>
                  <strong className="text-right font-mono text-[var(--color-text-primary)] truncate">{item.client_ip || '-'}</strong>
                  <span>过期时间</span>
                  <strong className="text-right text-[var(--color-text-primary)]">{new Date(item.expires_at).toLocaleTimeString()}</strong>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
