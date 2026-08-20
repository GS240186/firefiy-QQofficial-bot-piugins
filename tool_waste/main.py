# -*- coding: utf-8 -*-
"""工具·垃圾分类（tool_waste）—— 工具系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.tools_core import ToolsManager, ChatScene
from modules.common import send_text

PLUGIN = {
    "key": "tool_waste",
    "name": "工具·垃圾分类",
    "priority": 20,
    "description": "发送「垃圾分类 垃圾名」查分类",
    "category": "tool",
    "config_schema": [
        {"key": "waste_timeout", "type": "int", "default": 15, "label": "查询超时（秒）", "min": 1, "max": 60},
    ],
}

_manager = ToolsManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("tools", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("tool_waste", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    group_openid, member_openid = ctx.target_id, ctx.member_openid
    msg_id = ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    if text == "垃圾分类":
        await _manager._waste_start(api, group_openid, member_openid, scene=scene, msg_id=msg_id)
        return True
    if text.startswith("垃圾分类 ") or text.startswith("垃圾分类\u3000"):
        rest = text[4:].strip()
        if rest:
            await _manager._waste_query(api, rest, group_openid, member_openid, msg_id, scene)
            return True
        await send_text(api, scene, group_openid, "🗱️ 垃圾分类\n━━━━━━━━━━\n请输入要查询的垃圾名称，例如：\n垃圾分类 电池", msg_id=msg_id)
        return True
    from _common.tools_core import load_json, WASTE_STATE_FILE
    waste_states = load_json(WASTE_STATE_FILE)
    waste_key = _manager._state_key(group_openid, member_openid)
    if waste_states.get(waste_key, {}).get("waiting"):
        if text == "取消":
            _manager._waste_clear_waiting(group_openid, member_openid)
            await send_text(api, scene, group_openid, "已退出垃圾分类查询", msg_id=msg_id)
            return True
        if text == "返回主菜单":
            _manager._waste_clear_waiting(group_openid, member_openid)
        else:
            if text.isdigit():
                await _manager._waste_pick(api, int(text), group_openid, member_openid, msg_id, scene)
                return True
            word = text.strip()
            if word:
                await _manager._waste_query(api, word, group_openid, member_openid, msg_id, scene)
                return True
            await send_text(api, scene, group_openid, "🗱️ 请发送要查询的垃圾名称，或点击上方常用垃圾按钮\n发送「取消」可退出", msg_id=msg_id)
            return True
    return False


def is_waiting(storage_id: str, member_openid: str) -> bool:
    return _manager.is_waiting(storage_id, member_openid)
