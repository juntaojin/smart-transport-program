import time
import psutil
from loguru import logger

nvml_initialized = False
try:
    import pynvml
    pynvml.nvmlInit()
    nvml_initialized = True
    logger.info("NVML initialized successfully. Nvidia GPU hardware monitoring active.")
except Exception as e:
    logger.warning("NVML could not be initialized. Nvidia GPU metrics will be unavailable on this platform.")

def get_gpu_metrics():
    if not nvml_initialized:
        return None
    try:
        import pynvml
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        gpu_name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(gpu_name, bytes):
            gpu_name = gpu_name.decode('utf-8')
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        gpu_util = float(util.gpu)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        mem_total = mem.total / (1024 ** 3)
        mem_used = mem.used / (1024 ** 3)
        mem_free = mem.free / (1024 ** 3)
        mem_percent = (mem.used / mem.total) * 100
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


last_net_time = time.time()
last_net_bytes_recv = psutil.net_io_counters().bytes_recv
last_net_bytes_sent = psutil.net_io_counters().bytes_sent

def get_network_speed():
    global last_net_time, last_net_bytes_recv, last_net_bytes_sent
    current_time = time.time()
    current_net = psutil.net_io_counters()
    elapsed = current_time - last_net_time
    if elapsed <= 0.05:
        return 0.0, 0.0
    rx_bytes = current_net.bytes_recv - last_net_bytes_recv
    tx_bytes = current_net.bytes_sent - last_net_bytes_sent
    rx_speed = (rx_bytes * 8) / (1024 * 1024 * elapsed)
    tx_speed = (tx_bytes * 8) / (1024 * 1024 * elapsed)
    last_net_time = current_time
    last_net_bytes_recv = current_net.bytes_recv
    last_net_bytes_sent = current_net.bytes_sent
    return round(rx_speed, 2), round(tx_speed, 2)


_metrics_cache = None
_metrics_cache_time = 0.0
_METRICS_CACHE_TTL = 2.0


def get_detailed_metrics():
    global _metrics_cache, _metrics_cache_time
    now = time.time()
    if _metrics_cache is not None and (now - _metrics_cache_time) < _METRICS_CACHE_TTL:
        return _metrics_cache

    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_cores_physical = psutil.cpu_count(logical=False)
    cpu_cores_logical = psutil.cpu_count(logical=True)
    cpu_freq = psutil.cpu_freq()
    cpu_freq_current = cpu_freq.current if cpu_freq else 0.0
    cpu_freq_max = cpu_freq.max if cpu_freq else 0.0

    vm = psutil.virtual_memory()
    ram_total = vm.total / (1024 ** 3)
    ram_used = vm.used / (1024 ** 3)
    ram_free = vm.available / (1024 ** 3)
    ram_percent = vm.percent

    disk = psutil.disk_usage("/")
    disk_total = disk.total / (1024 ** 3)
    disk_used = disk.used / (1024 ** 3)
    disk_free = disk.free / (1024 ** 3)
    disk_percent = disk.percent

    rx, tx = get_network_speed()
    gpu = get_gpu_metrics()

    _metrics_cache = {
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
    _metrics_cache_time = now
    return _metrics_cache
