"""Fixture: 裸 print（默认不识别；config include_print=True 时识别）。"""
def debug_print(msg: str) -> None:
    print(msg)
    print("done", msg)
