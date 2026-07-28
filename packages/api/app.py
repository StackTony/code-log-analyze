"""FastAPI app — F001.1 HTTP 服务层入口（spec §六 + §三）。"""
from __future__ import annotations

import atexit
import logging
import multiprocessing
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import start_http_server

from packages.api.error_handlers import register_exception_handlers
from packages.api.routes.analysis import router as analysis_router
from packages.api.routes.call_context import router as call_context_router
from packages.api.routes.candidates import router as candidates_router
from packages.api.routes.confirm import router as confirm_router
from packages.api.routes.ingest import router as ingest_router
from packages.api.routes.log_points import router as log_points_router
from packages.api.routes.ops import router as ops_router
from packages.api.routes.revoke import router as revoke_router
from packages.m1.config_loader import load_config

logger = logging.getLogger("packages.api")
logger.setLevel(logging.INFO)

_config = load_config()

# Module-level handle for atexit fallback cleanup（v1.1 B-4 修订）
_metrics_process_ref: multiprocessing.Process | None = None


def _is_port_in_use(port: int) -> bool:
    """检查端口是否被占用（v1.1 B-4 修订：避免重复启动 metrics process 留下孤儿）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def _cleanup_metrics_process(process: multiprocessing.Process | None) -> None:
    """统一清理逻辑（lifespan cleanup + atexit fallback 共用）。"""
    if process and process.is_alive():
        process.terminate()
        process.join(timeout=2)
        # Windows terminate 强杀，prometheus_client 是 pull 模式无数据丢失风险（spec §六 B-3 注释）


@atexit.register
def _atexit_cleanup_metrics() -> None:
    """进程退出兜底清理（v1.1 B-4 修订：uvicorn worker 异常退出时也能回收 9464 进程）。"""
    global _metrics_process_ref
    if _metrics_process_ref is not None:
        _cleanup_metrics_process(_metrics_process_ref)
        _metrics_process_ref = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 metrics server 独立进程 + console 警告（spec §六 + AC-7 + AC-10 + AC-11）。"""
    global _metrics_process_ref

    # AC-7：未启用认证警告
    if not _config.api.enable_auth:
        logger.warning("⚠️  未启用认证，dev-only 模式 — 禁止暴露公网")

    # AC-10：metrics server 独立进程（multiprocessing.Process，避免 --reload 丢累积值）
    metrics_process: multiprocessing.Process | None = None
    try:
        if _config.metrics.enabled and _config.metrics.port:
            # v1.1 B-4：端口已占用时跳过启动（避免 lifespan 重入留孤儿进程）
            if _is_port_in_use(_config.metrics.port):
                logger.warning(
                    "Metrics port %s already in use — skipping metrics server start "
                    "(likely orphan from previous lifespan; Prometheus 抓取仍可用)",
                    _config.metrics.port,
                )
            else:
                metrics_process = multiprocessing.Process(
                    target=start_http_server,
                    args=(_config.metrics.port,),
                    daemon=True,
                )
                metrics_process.start()
                _metrics_process_ref = metrics_process  # 给 atexit 兜底用
                logger.info("Metrics server started on port %s (pid=%s)",
                            _config.metrics.port, metrics_process.pid)
    except Exception as e:
        # AC-11：graceful degradation，metrics 启动失败不阻断 API
        logger.warning("Metrics server failed to start: %s. Continuing without metrics.", e)

    yield

    # cleanup
    _cleanup_metrics_process(metrics_process)
    _metrics_process_ref = None


app = FastAPI(
    title="代码飞轮 M1 API",
    description="F001 代码仓日志解析模块 HTTP 服务层",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS（云长 I-3 修订）
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_config.api.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由聚合（其他 routes 在后续 task 加）
app.include_router(ops_router, tags=["ops"])
app.include_router(ingest_router)
app.include_router(confirm_router)
app.include_router(revoke_router)
app.include_router(candidates_router)
app.include_router(log_points_router)
app.include_router(call_context_router)
app.include_router(analysis_router)  # F002 M2

# F003 M3 scan router（spec §六 8 端点）
# 注：get_online_log_scanner 内部用 SessionLocal 单例，dev/test 用 mock 注入
try:
    from packages.api.deps import get_online_log_scanner
    from packages.api.routes.scan import build_scan_router
    _scan_scanner = get_online_log_scanner()
    app.include_router(build_scan_router(_scan_scanner))
except RuntimeError:
    # dev 测试 / postgres 未配置时跳过 — 测试用 build_scan_router(mock) 直接注入
    pass

# 统一异常处理器（spec §五 + AC-5）
register_exception_handlers(app)
