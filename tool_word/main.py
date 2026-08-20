# -*- coding: utf-8 -*-
"""工具·单词（tool_word）—— 工具系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.tools_core import ToolsManager, ChatScene
from modules.common import send_text

PLUGIN = {
    "key": "tool_word",
    "name": "工具·单词",
    "priority": 20,
    "description": "发送「单词 英文」查单词详解",
    "category": "tool",
    "config_schema": [
        {"key": "word_daily_limit", "type": "int", "default": 20, "label": "每日学习数", "min": 1, "max": 100},
        {"key": "word_enable_audio", "type": "bool", "default": True, "label": "是否开启发音"},
        {"key": "word_difficulty", "type": "string", "default": "auto", "label": "难度等级"},
    ],
}

_manager = ToolsManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("tools", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("tool_word", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    group_openid, member_openid = ctx.target_id, ctx.member_openid
    msg_id = ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    if text == "单词" or text == "单词查询" or text == "查词":
        await send_text(api, scene, group_openid, "🔤 单词详解\n━━━━━━━━━━\n用法：单词 英文单词\n示例：单词 cancel / 单词 beautiful", msg_id=msg_id)
        return True
    if text.startswith("单词 "):
        w = text[2:].strip()
        if w:
            await _manager._query_word(api, w, group_openid, msg_id, scene)
        else:
            await send_text(api, scene, group_openid, "🔤 单词详解\n━━━━━━━━━━\n请输入要查询的英文单词，例如：\n单词 cancel", msg_id=msg_id)
        return True
    return False
