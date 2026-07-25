"""Fixture: 干扰函数，命名含 error/log 但不是日志调用。"""


def format_error(code: int) -> str:
    return f"ERR-{code}"


def handleError(exc: Exception) -> None:
    raise RuntimeError("re-raise") from exc


class LoginService:
    def login(self, uid: str) -> bool:
        # 这是真的日志调用
        import logging
        logging.info("uid=%s", uid)
        return True
