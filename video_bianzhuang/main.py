# -*- coding: utf-8 -*-
"""视频·变装（video_bianzhuang）—— 视频系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.video_core import VideoManager, ChatScene, clean_content

PLUGIN = {
    "key": "video_bianzhuang",
    "name": "视频·变装",
    "priority": 50,
    "description": "发送「变装视频」推送",
    "category": "video",
}

_manager = VideoManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("video", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("video_bianzhuang", appid=ctx.bot_appid):
        return False
    content = clean_content(ctx.content or "").strip()
    if content != "变装视频":
        return False
    return await ctx.bot._time_plugin(
        "video_bianzhuang", _manager.send_video, ctx.perf,
        ctx.api, "变装视频", ctx.target_id, ctx.msg_id, scene=ctx.scene,
    )
