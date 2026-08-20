# -*- coding: utf-8 -*-
"""图片·壁纸（image_bizhi）—— 图片系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.image_core import ImageManager

PLUGIN = {
    "key": "image_bizhi",
    "name": "图片·壁纸",
    "priority": 60,
    "description": "发送「随机壁纸」随机壁纸",
    "category": "image",
    "config_schema": [
        {"key": "image_bizhi_enable_cache", "type": "bool", "default": False, "label": "是否启用缓存"},
        {"key": "image_bizhi_cache_ttl", "type": "int", "default": 300, "label": "缓存时间（秒）", "min": 0, "max": 86400},
        {"key": "image_bizhi_max_retries", "type": "int", "default": 3, "label": "最大重试次数", "min": 0, "max": 10},
    ],
}

_manager = ImageManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("image", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("image_bizhi", appid=ctx.bot_appid):
        return False
    content = (ctx.content or "").strip()
    if content != "随机壁纸":
        return False
    return await ctx.bot._time_plugin(
        "image_bizhi", _manager.send_image, ctx.perf,
        ctx.api, "随机壁纸", ctx.target_id, ctx.msg_id, scene=ctx.scene,
    )
