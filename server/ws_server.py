#!/usr/bin/env python3
"""
WebSocket 视频流服务器 (通用版)
- HTTP 和 WebSocket 共用同一端口
- 本地无需 TLS（内网穿透 frp 负责 TLS 终止）
- 也可本地 HTTPS 直连（自动生成自签名证书）
- 接收手机端摄像头图像，OpenCV 实时预览
"""

import asyncio
import time
import logging
import json
import ssl
import socket
import subprocess
from pathlib import Path
from http import HTTPStatus

import numpy as np
import cv2
import websockets
from websockets.asyncio.server import serve

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("video-server")

# 抑制 websockets 库内部的 TCP 探测噪音
logging.getLogger("websockets").setLevel(logging.WARNING)

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "phone-client"
CERT_DIR = Path(__file__).parent / "certs"
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE = CERT_DIR / "key.pem"


def generate_self_signed_cert():
    if CERT_FILE.exists() and KEY_FILE.exists():
        return
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("生成自签名证书...")
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(KEY_FILE), "-out", str(CERT_FILE),
        "-days", "365", "-nodes",
        "-subj", "/CN=localhost",
        "-addext", "subjectAltName=IP:127.0.0.1",
    ], check=True, capture_output=True)
    logger.info("证书生成完成")


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


class VideoStreamServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080,
                 enable_tls: bool = False, show_preview: bool = True):
        self.host = host
        self.port = port
        self.enable_tls = enable_tls
        self.show_preview = show_preview
        self.clients: dict = {}
        self.frame_count = 0
        self.prev_frame_count = 0
        self.fps_timestamp = time.time()

    # ── HTTP 页面请求处理（与 WebSocket 同端口） ──

    async def process_request(self, connection, request):
        """拦截普通 HTTP 请求返回页面，WebSocket 升级请求放行"""
        path = request.path
        addr = connection.remote_address

        # 带 Upgrade: websocket 头的是 WebSocket 连接，放行
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None

        # 健康检查端点（frp 探测用）
        if path == "/ping":
            logger.debug(f"健康检查来自 {addr[0]}")
            return connection.respond(HTTPStatus.OK, "ok")

        # 页面请求
        if path in ("/", "/index.html"):
            logger.info(f"HTTP 页面请求来自 {addr[0]}")
            file_path = STATIC_DIR / "index.html"
            if file_path.exists():
                html = file_path.read_text(encoding="utf-8")
                html = html.replace("__SERVER_PORT__", str(self.port))
                html = html.replace("__USE_TLS__", "true" if self.enable_tls else "false")
                response = connection.respond(HTTPStatus.OK, html)
                del response.headers["Content-Type"]
                response.headers["Content-Type"] = "text/html; charset=utf-8"
                return response

        return None

    # ── WebSocket 处理 ──

    async def ws_handler(self, websocket):
        addr = websocket.remote_address
        client_id = f"{addr[0]}:{addr[1]}"
        self.clients[client_id] = {"connected_at": time.time(), "frame_count": 0}
        logger.info(f"客户端已连接: {client_id} (共 {len(self.clients)} 个)")

        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    self.frame_count += 1
                    self.clients[client_id]["frame_count"] += 1
                    self._process_frame(message)
                    self._log_fps()
                elif isinstance(message, str):
                    if message == "ping":
                        await websocket.send("pong")
                    else:
                        try:
                            data = json.loads(message)
                            if data.get("type") == "device_info":
                                logger.info(f"设备信息 ({client_id}): {data}")
                        except json.JSONDecodeError:
                            pass
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"客户端断开: {client_id}")
        except Exception as e:
            logger.error(f"连接异常 ({client_id}): {e}")
        finally:
            self.clients.pop(client_id, None)
            logger.info(f"客户端已移除: {client_id} (剩余 {len(self.clients)} 个)")

    def _process_frame(self, jpeg_bytes: bytes):
        if not self.show_preview:
            return
        try:
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is not None:
                cv2.imshow("实时画面 (手机摄像头)", frame)
                cv2.waitKey(1)
        except Exception:
            pass

    def _log_fps(self):
        now = time.time()
        elapsed = now - self.fps_timestamp
        if elapsed >= 3.0:
            fps = (self.frame_count - self.prev_frame_count) / elapsed
            self.prev_frame_count = self.frame_count
            self.fps_timestamp = now
            logger.info(f"接收: {fps:.1f} FPS | 总帧: {self.frame_count} | 客户端: {len(self.clients)}")

    # ── 启动 ──

    async def start(self):
        local_ip = get_local_ip()

        ssl_ctx = None
        if self.enable_tls:
            generate_self_signed_cert()
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.load_cert_chain(str(CERT_FILE), str(KEY_FILE))

        proto = "wss" if self.enable_tls else "ws"
        http_proto = "https" if self.enable_tls else "http"

        logger.info("=" * 55)
        logger.info("  视频流 WebSocket 服务器")
        logger.info("=" * 55)
        logger.info(f"  本机 IP:      {local_ip}")
        logger.info(f"  服务端口:     {self.port}  ({'/'.join([http_proto, proto])})")
        logger.info(f"  本地直连:     {http_proto}://{local_ip}:{self.port}")
        logger.info("=" * 55)

        ws_server = await serve(
            self.ws_handler,
            self.host,
            self.port,
            ssl=ssl_ctx,
            process_request=self.process_request,
        )
        logger.info("服务器就绪，等待手机端连接...")

        await ws_server.serve_forever()

    def run(self):
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            logger.info("服务器正在关闭...")
        finally:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    # enable_tls=True: frp TCP 透传模式下，TLS 由本地服务器处理
    server = VideoStreamServer(port=8080, enable_tls=True, show_preview=True)
    server.run()
