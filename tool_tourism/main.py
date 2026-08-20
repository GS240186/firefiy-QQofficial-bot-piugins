# -*- coding: utf-8 -*-
"""工具·旅游（tool_tourism）—— 工具系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.tools_core import ToolsManager, ChatScene
from modules.common import send_text

PLUGIN = {
    "key": "tool_tourism",
    "name": "工具·旅游",
    "priority": 20,
    "description": "发送「旅游 城市」查景点",
    "category": "tool",
    "config_schema": [
        {"key": "tourism_timeout", "type": "int", "default": 15, "label": "查询超时（秒）", "min": 1, "max": 60},
    ],
}

_manager = ToolsManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("tools", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("tool_tourism", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    group_openid, member_openid = ctx.target_id, ctx.member_openid
    msg_id = ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    if text == "旅游" or text == "旅游查询" or text == "景点":
        await send_text(api, scene, group_openid, "🏞️ 旅游查询\n━━━━━━━━━━\n用法：旅游 城市名\n示例：旅游 成都", msg_id=msg_id)
        return True
    if text.startswith("旅游 ") or text.startswith("旅游\u3000"):
        city = text[2:].strip()
        if city:
            await _manager._query_tourism(api, city, group_openid, msg_id, scene)
        else:
            await send_text(api, scene, group_openid, "🏞️ 旅游查询\n━━━━━━━━━━\n请输入城市名，例如：旅游 成都", msg_id=msg_id)
        return True
    return False
