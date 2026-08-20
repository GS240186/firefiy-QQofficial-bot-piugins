# -*- coding: utf-8 -*-
"""图片·风景（image_wallpaper）—— 图片系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.image_core import ImageManager

PLUGIN = {
    "key": "image_wallpaper",
    "name": "图片·风景",
    "priority": 60,
    "description": "发送「风景」随机风景壁纸",
    "category": "image",
    "config_schema": [
        {"key": "image_wallpaper_enable_cache", "type": "bool", "default": False, "label": "是否启用缓存"},
        {"key": "image_wallpaper_cache_ttl", "type": "int", "default": 300, "label": "缓存时间（秒）", "min": 0, "max": 86400},
        {"key": "image_wallpaper_max_retries", "type": "int", "default": 3, "label": "最大重试次数", "min": 0, "max": 10},
    ],
}

_manager = ImageManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("image", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("image_wallpaper", appid=ctx.bot_appid):
        return False
    content = (ctx.content or "").strip()
    if content != "风景":
        return False
    return await ctx.bot._time_plugin(
        "image_wallpaper", _manager.send_image, ctx.perf,
        ctx.api, "风景", ctx.target_id, ctx.msg_id, scene=ctx.scene,
    )
