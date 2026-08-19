# -*- coding: utf-8 -*-
"""图片·二次元（image_acg）—— 图片系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.image_core import ImageManager

PLUGIN = {
    "key": "image_acg",
    "name": "图片·二次元",
    "priority": 60,
    "description": "发送「二次元」随机二次元插画",
    "category": "image",
}

_manager = ImageManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("image", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("image_acg", appid=ctx.bot_appid):
        return False
    content = (ctx.content or "").strip()
    if content != "二次元":
        return False
    return await ctx.bot._time_plugin(
        "image_acg", _manager.send_image, ctx.perf,
        ctx.api, "二次元", ctx.target_id, ctx.msg_id, scene=ctx.scene,
    )
