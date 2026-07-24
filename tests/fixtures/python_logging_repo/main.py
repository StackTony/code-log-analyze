"""Fixture: Python logging 调用。"""
import logging

LOG = logging.getLogger(__name__)


def login(uid: str) -> bool:
    LOG.info("User %s logged in", uid)
    LOG.warning("login attempt for uid=%s", uid)
    return True


def fail(uid: str) -> None:
    LOG.error("login failed for %s", uid)
    LOG.debug("debug detail %s", uid)
