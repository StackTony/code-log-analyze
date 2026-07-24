"""Fixture: Python loguru 调用。"""
from loguru import logger


def process(task_id: str) -> None:
    logger.info("processing task {}", task_id)
    logger.error("task {} failed", task_id)
