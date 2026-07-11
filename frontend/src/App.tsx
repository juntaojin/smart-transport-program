import { useState } from 'react';
import Dashboard from './pages/Dashboard';
import VehicleMonitor from './pages/VehicleMonitor';
import AnomalyAlerts from './pages/AnomalyAlerts';
import SystemConfig from './pages/SystemConfig';
import IPMCalibration from './pages/IPMCalibration';
import { LayoutDashboard, Car, ShieldAlert, Sliders, Radio, MapPin } from 'lucide-react';

type Tab = 'dashboard' | 'vehicles' | 'anomalies' | 'config' | 'ipm';

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');

  const tabs = [
    { id: 'dashboard', label: '实时驾驶舱', icon: LayoutDashboard },
    { id: 'vehicles', label: '车辆与识别', icon: Car },
    { id: 'anomalies', label: '抛洒与异常', icon: ShieldAlert },
    { id: 'config', label: '大模型引擎', icon: Sliders },
    { id: 'ipm', label: 'IPM 标定', icon: MapPin },
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
      case 'ipm':
        return <IPMCalibration />;
      default:
        return <Dashboard />;
    }
  };

  return (
    <div className="flex min-height-screen bg-dark-900 text-slate-100 min-h-screen">
      
      {/* 左侧侧边栏 Navigation */}
      <aside className="w-64 bg-slate-950/80 border-r border-white/5 p-6 flex flex-col justify-between hidden md:flex">
        
        <div className="space-y-8">
          {/* Logo Header */}
          <div className="flex items-center gap-3 px-2">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 to-cyan-400 flex items-center justify-center shadow-lg shadow-blue-500/25">
              <Radio size={20} className="text-white animate-pulse" />
            </div>
            <div>
              <h1 className="font-bold text-base leading-none">智慧交通系统</h1>
              <span className="text-[10px] text-slate-500 font-semibold tracking-wider uppercase">Cloud-Edge-Device V1.0</span>
            </div>
          </div>

          {/* Nav Items */}
          <nav className="space-y-1">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id as Tab)}
                  className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition-all ${
                    isActive 
                      ? 'bg-blue-600/10 text-blue-400 border border-blue-500/25 shadow-sm shadow-blue-500/5' 
                      : 'text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent'
                  }`}
                >
                  <Icon size={18} />
                  {tab.label}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Footer */}
        <div className="border-t border-white/5 pt-4 text-[10px] text-slate-600 px-2">
          <p>© 2026 Intelligent Transport</p>
          <p className="mt-1">Environment: macOS Dev</p>
        </div>

      </aside>

      {/* 右侧主视窗 Content Area */}
      <div className="flex-1 flex flex-col overflow-y-auto max-h-screen">
        
        {/* Top Header Navbar */}
        <header className="bg-slate-950/40 backdrop-blur-md border-b border-white/5 py-4 px-6 sm:px-8 flex justify-between items-center sticky top-0 z-50">
          <div>
            <h2 className="font-bold text-lg text-slate-200">
              {tabs.find(t => t.id === activeTab)?.label}
            </h2>
          </div>

          <div className="flex items-center gap-4">
            <span className="text-xs bg-slate-900 border border-white/10 text-slate-400 font-semibold px-2.5 py-1 rounded-lg">
              Deployment: Windows Cloud
            </span>
          </div>
        </header>

        {/* Dynamic Page Viewer */}
        <main className="p-6 sm:p-8 flex-1 animate-fade-in">
          {renderContent()}
        </main>
        
      </div>
    </div>
  );
}
