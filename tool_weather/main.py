# -*- coding: utf-8 -*-
"""工具·天气（tool_weather）—— 工具系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.tools_core import ToolsManager, ChatScene
from modules.common import send_text

PLUGIN = {
    "key": "tool_weather",
    "name": "工具·天气",
    "priority": 20,
    "description": "发送「天气 城市」查询天气",
    "category": "tool",
}

_manager = ToolsManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("tools", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("tool_weather", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    group_openid, member_openid = ctx.target_id, ctx.member_openid
    msg_id = ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    if text == "天气":
        await send_text(api, scene, group_openid, "🌤 天气查询\n━━━━━━━━━━\n用法：天气 城市名 [天数]\n示例：天气 南昌\n多天预报：天气 绵阳 3（最多7天，含预警信息）", msg_id=msg_id)
        return True
    if text.startswith("天气 ") or text.startswith("天气\u3000"):
        city = text[2:].strip()
        if city:
            parts = city.split()
            days = 1
            if len(parts) >= 2 and parts[-1].isdigit():
                days = int(parts[-1]); city = " ".join(parts[:-1]).strip()
            ok = await _manager._query_weather_apihz(api, city, group_openid, msg_id, scene, days)
            if not ok:
                await _manager._query_weather(api, city, group_openid, msg_id, scene)
            return True
    return False
