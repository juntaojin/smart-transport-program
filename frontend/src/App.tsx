import { useState, useEffect } from 'react';
import Dashboard from './pages/Dashboard';
import VehicleMonitor from './pages/VehicleMonitor';
import AnomalyAlerts from './pages/AnomalyAlerts';
import SystemConfig from './pages/SystemConfig';
import IPMCalibration from './pages/IPMCalibration';
import { LayoutDashboard, Car, ShieldAlert, Sliders, MapPin, Sun, Moon } from 'lucide-react';

type Tab = 'dashboard' | 'vehicles' | 'anomalies' | 'config' | 'ipm';

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [isDarkMode, setIsDarkMode] = useState(true);

  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkMode]);

  const tabs = [
    { id: 'dashboard', label: '实时驾驶舱 (Transcope)', icon: LayoutDashboard },
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
    <div className="flex flex-col min-h-screen bg-[var(--color-bg-canvas)] text-[var(--color-text-primary)] font-sans overflow-hidden transition-colors duration-300">
      
      {/* 顶部导航栏 Navigation */}
      <header className="bg-[var(--color-bg-card)] border-b border-[var(--color-border-card)] px-4 sm:px-6 py-3 flex items-center justify-between shrink-0 z-10 shadow-md transition-colors duration-300">
        
        {/* Logo Header */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gray-200 dark:bg-[#1C1E24] border border-[var(--color-border-card)] flex items-center justify-center transition-colors">
            <span className="text-gray-900 dark:text-white font-extrabold text-lg select-none">T</span>
          </div>
          <div className="hidden lg:block">
            <h1 className="font-bold text-lg leading-none tracking-tight text-[var(--color-text-primary)]">Transcope.</h1>
          </div>
        </div>

        {/* Nav Items */}
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

        {/* Actions & User Profile */}
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

      {/* 主视窗 Content Area */}
      <div className="flex-1 flex flex-col overflow-y-auto max-h-[calc(100vh-60px)] relative bg-[var(--color-bg-canvas)]">
        
        {/* Dynamic Page Viewer */}
        <main className="p-4 sm:p-6 md:p-8 flex-1 animate-fade-in max-w-[1600px] mx-auto w-full">
          {renderContent()}
        </main>
        
      </div>
    </div>
  );
}
