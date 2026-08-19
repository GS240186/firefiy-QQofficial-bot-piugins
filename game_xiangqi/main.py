# -*- coding: utf-8 -*-
"""娱乐·中国象棋（game_xiangqi）—— 娱乐系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.game_core import make_manager, ChatScene

PLUGIN = {
    "key": "game_xiangqi",
    "name": "娱乐·中国象棋",
    "priority": 72,
    "description": "发送「象棋」开始对战（AI/双人）",
    "category": "game",
}

_manager = make_manager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("game", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("game_xiangqi", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    target_id = ctx.target_id or ctx.member_openid
    member_openid, msg_id = ctx.member_openid, ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    return await _manager.handle_xiangqi_cmd(
        api, text, target_id, member_openid, msg_id,
        scene=scene, member_nick=ctx.username,
    )


def session_check(storage_id: str) -> bool:
    """象棋进行中会话预检（供 is_gaming 聚合判断）。"""
    try:
        return _manager.has_xiangqi_session(storage_id)
    except Exception:
        return False
