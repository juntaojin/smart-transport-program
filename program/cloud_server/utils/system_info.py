import time
import psutil
from loguru import logger

# Initialize NVML for Nvidia GPU monitoring
nvml_initialized = False
try:
    import pynvml
    pynvml.nvmlInit()
    nvml_initialized = True
    logger.info("NVML initialized successfully. Nvidia GPU hardware monitoring active.")
except Exception as e:
    logger.warning("NVML could not be initialized. Nvidia GPU metrics will be unavailable on this platform.")

def get_gpu_metrics():
    """Retrieve Nvidia GPU load, memory, temperature, and model name using NVML"""
    if not nvml_initialized:
        return None
    try:
        import pynvml
        # Query primary GPU (index 0)
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        
        # GPU name
        gpu_name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(gpu_name, bytes):
            gpu_name = gpu_name.decode('utf-8')
            
        # Utilization Rates
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        gpu_util = float(util.gpu)
        
        # Memory Info
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        mem_total = mem.total / (1024 ** 3)  # Convert to GB
        mem_used = mem.used / (1024 ** 3)
        mem_free = mem.free / (1024 ** 3)
        mem_percent = (mem.used / mem.total) * 100
        
        # Temperature
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        
        return {
            "name": gpu_name,
            "load": round(gpu_util, 1),
            "memory_total": round(mem_total, 2),
            "memory_used": round(mem_used, 2),
            "memory_free": round(mem_free, 2),
            "memory_percent": round(mem_percent, 1),
            "temperature": int(temp)
        }
    except Exception as e:
        logger.debug(f"Error querying GPU via NVML: {e}")
        return None


# Cache for network I/O speed calculation
last_net_time = time.time()
last_net_bytes_recv = psutil.net_io_counters().bytes_recv
last_net_bytes_sent = psutil.net_io_counters().bytes_sent

def get_network_speed():
    """Calculate average download (rx) and upload (tx) speeds in Mbps since last call"""
    global last_net_time, last_net_bytes_recv, last_net_bytes_sent
    
    current_time = time.time()
    current_net = psutil.net_io_counters()
    
    elapsed = current_time - last_net_time
    if elapsed <= 0.05:
        return 0.0, 0.0
        
    rx_bytes = current_net.bytes_recv - last_net_bytes_recv
    tx_bytes = current_net.bytes_sent - last_net_bytes_sent
    
    # Bytes to Mbps: (bytes * 8) / (1024 * 1024 * elapsed)
    rx_speed = (rx_bytes * 8) / (1024 * 1024 * elapsed)
    tx_speed = (tx_bytes * 8) / (1024 * 1024 * elapsed)
    
    # Update cache
    last_net_time = current_time
    last_net_bytes_recv = current_net.bytes_recv
    last_net_bytes_sent = current_net.bytes_sent
    
    return round(rx_speed, 2), round(tx_speed, 2)


def get_detailed_metrics():
    """Retrieve comprehensive CPU, RAM, Disk, Network and GPU status"""
    # 1. CPU Metrics
    cpu_percent = psutil.cpu_percent()
    cpu_cores_physical = psutil.cpu_count(logical=False)
    cpu_cores_logical = psutil.cpu_count(logical=True)
    
    cpu_freq = psutil.cpu_freq()
    cpu_freq_current = cpu_freq.current if cpu_freq else 0.0
    cpu_freq_max = cpu_freq.max if cpu_freq else 0.0
    
    # 2. RAM Metrics
    vm = psutil.virtual_memory()
    ram_total = vm.total / (1024 ** 3)
    ram_used = vm.used / (1024 ** 3)
    ram_free = vm.available / (1024 ** 3)
    ram_percent = vm.percent
    
    # 3. Disk Metrics
    disk = psutil.disk_usage("/")
    disk_total = disk.total / (1024 ** 3)
    disk_used = disk.used / (1024 ** 3)
    disk_free = disk.free / (1024 ** 3)
    disk_percent = disk.percent
    
    # 4. Network Metrics
    rx, tx = get_network_speed()
    
    # 5. GPU Metrics
    gpu = get_gpu_metrics()
    
    return {
        "cpu": {
            "percent": cpu_percent,
            "cores_physical": cpu_cores_physical,
            "cores_logical": cpu_cores_logical,
            "frequency_current_mhz": round(cpu_freq_current, 0),
            "frequency_max_mhz": round(cpu_freq_max, 0)
        },
        "memory": {
            "percent": ram_percent,
            "total_gb": round(ram_total, 2),
            "used_gb": round(ram_used, 2),
            "free_gb": round(ram_free, 2)
        },
        "disk": {
            "percent": disk_percent,
            "total_gb": round(disk_total, 2),
            "used_gb": round(disk_used, 2),
            "free_gb": round(disk_free, 2)
        },
        "network": {
            "rx_mbps": rx,
            "tx_mbps": tx
        },
        "gpu": gpu
    }
