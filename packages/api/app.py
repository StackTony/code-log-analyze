"""FastAPI app — F001.1 HTTP 服务层入口（spec §六 + §三）。"""
from __future__ import annotations

import logging
import multiprocessing
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import start_http_server

from packages.api.routes.ops import router as ops_router
from packages.m1.config_loader import load_config

logger = logging.getLogger("packages.api")
logger.setLevel(logging.INFO)

_config = load_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 metrics server 独立进程 + console 警告（spec §六 + AC-7 + AC-10 + AC-11）。"""
    # AC-7：未启用认证警告
    if not _config.api.enable_auth:
        logger.warning("⚠️  未启用认证，dev-only 模式 — 禁止暴露公网")  # noqa: RUF001

    # AC-10：metrics server 独立进程（multiprocessing.Process，避免 --reload 丢累积值）
    metrics_process: multiprocessing.Process | None = None
    try:
        if _config.metrics.enabled and _config.metrics.port:
            metrics_process = multiprocessing.Process(
                target=start_http_server,
                args=(_config.metrics.port,),
                daemon=True,
            )
            metrics_process.start()
            logger.info("Metrics server started on port %s (pid=%s)",
                        _config.metrics.port, metrics_process.pid)
    except Exception as e:
        # AC-11：graceful degradation，metrics 启动失败不阻断 API
        logger.warning("Metrics server failed to start: %s. Continuing without metrics.", e)

    yield

    # cleanup
    if metrics_process and metrics_process.is_alive():
        metrics_process.terminate()
        metrics_process.join(timeout=2)


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
