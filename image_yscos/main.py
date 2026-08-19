# -*- coding: utf-8 -*-
"""图片·原神cos（image_yscos）—— 图片系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.image_core import ImageManager

PLUGIN = {
    "key": "image_yscos",
    "name": "图片·原神cos",
    "priority": 60,
    "description": "发送「原神cos」原神cosplay 图片",
    "category": "image",
}

_manager = ImageManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("image", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("image_yscos", appid=ctx.bot_appid):
        return False
    content = (ctx.content or "").strip()
    if content != "原神cos":
        return False
    return await ctx.bot._time_plugin(
        "image_yscos", _manager.send_image, ctx.perf,
        ctx.api, "原神cos", ctx.target_id, ctx.msg_id, scene=ctx.scene,
    )
