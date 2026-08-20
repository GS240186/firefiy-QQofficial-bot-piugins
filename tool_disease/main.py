# -*- coding: utf-8 -*-
"""工具·疾病（tool_disease）—— 工具系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.tools_core import ToolsManager, ChatScene
from modules.common import send_text

PLUGIN = {
    "key": "tool_disease",
    "name": "工具·疾病",
    "priority": 20,
    "description": "发送「疾病信息 病名」查疾病",
    "category": "tool",
    "config_schema": [
        {"key": "disease_enable_history", "type": "bool", "default": False, "label": "是否保存查询历史"},
        {"key": "disease_timeout", "type": "int", "default": 10, "label": "API 超时（秒）", "min": 1, "max": 60},
        {"key": "disease_max_results", "type": "int", "default": 10, "label": "搜索结果数", "min": 1, "max": 50},
    ],
}

_manager = ToolsManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("tools", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("tool_disease", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    group_openid, member_openid = ctx.target_id, ctx.member_openid
    msg_id = ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    if text == "疾病信息":
        await _manager._disease_start(api, group_openid, member_openid, scene=scene, msg_id=msg_id)
        return True
    if text.startswith("疾病信息 ") or text.startswith("疾病信息\u3000"):
        rest = text[4:].strip()
        if rest.startswith("复制 "):
            word = rest[2:].strip()
            if word:
                await _manager._disease_show_copy(api, group_openid, msg_id, word, scene)
                return True
        if rest:
            await _manager.disease_info(api, group_openid, member_openid, msg_id, rest, scene)
            return True
        await send_text(api, scene, group_openid, "🏥 疾病信息\n━━━━━━━━━━\n请输入要查询的疾病名，例如：\n疾病信息 感冒", msg_id=msg_id)
        return True
    from _common.tools_core import load_json, DISEASE_STATE_FILE
    disease_states = load_json(DISEASE_STATE_FILE)
    disease_key = _manager._state_key(group_openid, member_openid)
    if disease_states.get(disease_key, {}).get("waiting"):
        if text == "取消":
            _manager._disease_clear_waiting(group_openid, member_openid)
            await send_text(api, scene, group_openid, "已退出疾病信息查询", msg_id=msg_id)
            return True
        if text == "返回主菜单":
            _manager._disease_clear_waiting(group_openid, member_openid)
        else:
            word = text.strip()
            if word:
                await _manager.disease_info(api, group_openid, member_openid, msg_id, word, scene)
                return True
            await send_text(api, scene, group_openid, "🏥 请发送要查询的疾病名称，或点击上方常用疾病按钮\n发送「取消」可退出", msg_id=msg_id)
            return True
    return False


def is_waiting(storage_id: str, member_openid: str) -> bool:
    return _manager.is_waiting(storage_id, member_openid)
