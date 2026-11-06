"""抓取适配器注册表。

新增一个源只有两步：写 sources/<name>.py（暴露 SOURCE + fetch），
然后在下面 REGISTRY 里加一行；config.yaml 里打开开关即可。
"""

from __future__ import annotations

import importlib
from types import ModuleType

REGISTRY = {
    "mock": "sources.mock",
    "d1ev": "sources.d1ev",
    "sina": "sources.sina",
    "cada": "sources.cada",
    # 下面三个是 2026-11-05/06 实测下来接不动的，保留文件当记录
    "cnautonews": "sources.cnautonews",
    "autoinfo": "sources.autoinfo",
    "dongchedi": "sources.dongchedi",
}


def load(source_id: str) -> ModuleType:
    return importlib.import_module(REGISTRY[source_id])