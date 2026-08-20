# -*- coding: utf-8 -*-
"""娱乐·五子棋（game_gomoku）—— 娱乐系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.game_core import make_manager, ChatScene

PLUGIN = {
    "key": "game_gomoku",
    "name": "娱乐·五子棋",
    "priority": 71,
    "description": "发送「五子棋」开始对战（AI/双人）",
    "category": "game",
    "config_schema": [
        {"key": "gomoku_board_size", "type": "int", "default": 15, "label": "棋盘大小", "min": 9, "max": 19},
        {"key": "gomoku_allow_undo", "type": "bool", "default": True, "label": "是否允许悔棋"},
        {"key": "gomoku_timeout", "type": "int", "default": 120, "label": "单局超时（秒）", "min": 30, "max": 600},
    ],
}

_manager = make_manager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("game", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("game_gomoku", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    target_id = ctx.target_id or ctx.member_openid
    member_openid, msg_id = ctx.member_openid, ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    return await _manager.handle_gomoku_cmd(
        api, text, target_id, member_openid, msg_id,
        scene=scene, member_nick=ctx.username,
    )


def session_check(storage_id: str) -> bool:
    """五子棋进行中会话预检（供 is_gaming 聚合判断）。"""
    try:
        return _manager.has_gomoku_session(storage_id)
    except Exception:
        return False
