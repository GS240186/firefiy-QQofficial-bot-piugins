# -*- coding: utf-8 -*-
"""工具·导航（tool_navigation）—— 工具系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.tools_core import ToolsManager, ChatScene
from modules.common import send_text

PLUGIN = {
    "key": "tool_navigation",
    "name": "工具·导航",
    "priority": 20,
    "description": "发送「导航」查询路线规划",
    "category": "tool",
}

_manager = ToolsManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("tools", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("tool_navigation", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    group_openid, member_openid = ctx.target_id, ctx.member_openid
    msg_id = ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    if text == "导航" or text == "导航规划":
        await send_text(api, scene, group_openid, "🧭 导航规划\n━━━━━━━━━━\n用法：导航 起点经度,起点纬度 终点经度,终点纬度\n示例：导航 104.06,30.67 104.07,30.68\n提示：需输入经纬度坐标（可从地图 App 复制）", msg_id=msg_id)
        return True
    if text.startswith("导航 ") or text.startswith("导航\u3000"):
        await _manager._query_navigation(api, text[2:].strip(), group_openid, msg_id, scene)
        return True
    return False
