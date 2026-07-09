# 智能交通系统 (Intelligent Transportation System)

这是一个基于“云边端”架构的智慧交通视频流分析与状态控制系统。系统通过边缘端设备采集路面画面，利用 WebSockets 将视频帧高速推送到云端服务，云端利用 AI 推理流水线进行实时多对象分析，最后将标注画面和结构化分析指标推送到前端驾驶舱（Cockpit）显示。

---

## 系统组件

1. **云端核心服务 (`cloud_server/`)**：
   - 基于 **FastAPI**，运行于端口 `8000`。
   - **推理流水线**：以 `FrameContext` 上下文属性包形式流经各个 AI 推理节点（`YOLOv8 车辆检测` -> `SORT 目标跟踪` -> `EasyOCR 车牌识别` -> `Grounding DINO 异常检测` -> `违停逻辑研判`）。
   - **多路数据分发**：利用 WebSockets 接收边端 JPEG 二进制视频帧，在云端处理、渲染绘制标注框后，再将编码的 Base64 画面与解析结果广播给前端看板。
   - **数据持久化**：使用 SQLite 配合 SQLAlchemy 异步查询（`aiosqlite`），定期归档保存拥堵数据、车牌记录、违章告警与硬件负载监控。
   - **内置推流页面**：提供 `/phone` 端点，支持手机浏览器直接调用摄像头推流，或选择本地视频文件模拟推流。

2. **高颜值前端驾驶舱 (`frontend/`)**：
   - 基于 **React + Vite + TypeScript + Tailwind CSS**，监听端口 `5173`。
   - 深色磨砂玻璃（Glassmorphism）极客视觉设计。
   - 通过 WebSockets 接收高速重绘标注帧并呈现在 HTML5 Canvas 视图中。
   - 支持 AI 节点算力实时动态热拔插（可一键开启/关闭车牌 OCR 或 Grounding DINO 节点以释放后端显存）。
   - 内置纯 SVG 动态渲染的曲线图与指标监控面板，避免依赖臃肿的第三方原生图表库。

---

## 快速开始

### 1. 环境准备 (macOS / Windows 通用)

本系统在开发时已完全对路径分隔符、换行符和跨平台脚本进行了解耦，确保在 macOS 和 Windows 系统下的一致运行。

#### A. 安装 Node.js
确保您的机器安装了 Node.js（推荐使用 LTS 版本，或在 Mac 下运行 `brew install node`）。

#### B. 安装 Python 依赖
推荐创建虚拟环境并进行依赖安装：
```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境 (macOS)
source venv/bin/activate

# 激活虚拟环境 (Windows)
# venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

---

## 运行步骤

系统需要按照 **云端后台 -> 推流采集 -> 前端驾驶舱** 的顺序启动：

### 步骤一：启动云端主服务 (FastAPI)
```bash
# 激活虚拟环境后运行
python3 -m cloud_server.main
python -m cloud_server.main
```
云端会自动初始化 SQLite 数据库文件（位于 `data/its.db`），并在端口 `8000` 启动，同时动态构建和预加载基础 AI 节点。

### 步骤二：启动视频推流采集
在手机或电脑浏览器中打开推流页面：
```
https://<服务器IP>:8000/phone
```
- 可选择 **摄像头模式**：授予摄像头权限后直接推流
- 或选择 **本地视频模式**：选取视频文件模拟交通场景推流
- 输入服务器地址和通道编号后，点击 **开始推流**

### 步骤三：启动前端驾驶舱 (React)
```bash
cd frontend

# 安装前端依赖
npm install

# 启动 Vite 开发调试服务器
npm run dev
```
启动后访问：`http://localhost:5173` 即可进入智慧交通大屏驾驶舱，体验极具未来感的数据联动。

---

## 系统设计说明

- **开发原则**：系统强制使用 Unix `LF` 换行符（提供 `.editorconfig`），前端配置文件 `vite.config.ts` 使用 Node 内置 `path` 模块以解耦路径，严禁硬编码反斜杠或端口 API。
- **显存精细控制**：推理流水线中每个节点均实现 `load_model()` 和 `unload_model()`，当在前端关闭异常检测（Grounding DINO）或车牌识别（EasyOCR）时，后台会自动释放 PyTorch 的显存缓存，避免显存泄露。
- **纯 Python 版 SORT 跟踪器**：跟踪节点使用纯 Python + NumPy/SciPy 封装，避免在 macOS/Windows 环境下构建 `lap` 或 `scikit-image` 产生的底层 C++ 编译器错误。
