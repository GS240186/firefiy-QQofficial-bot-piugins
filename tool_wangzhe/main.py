# -*- coding: utf-8 -*-
"""工具·王者（tool_wangzhe）—— 工具系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.tools_core import ToolsManager, ChatScene
from modules.common import send_text

PLUGIN = {
    "key": "tool_wangzhe",
    "name": "工具·王者",
    "priority": 20,
    "description": "发送「王者 英雄」查英雄信息",
    "category": "tool",
    "config_schema": [
        {"key": "wangzhe_default_region", "type": "string", "default": "all", "label": "默认大区"},
        {"key": "wangzhe_cache_time", "type": "int", "default": 300, "label": "缓存时间（秒）", "min": 0, "max": 3600},
    ],
}

_manager = ToolsManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("tools", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("tool_wangzhe", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    group_openid, member_openid = ctx.target_id, ctx.member_openid
    msg_id = ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    if text == "王者" or text == "王者信息":
        await send_text(api, scene, group_openid, "🎮 王者信息\n━━━━━━━━━━\n用法：王者 英雄名\n示例：王者 后羿\n指定平台：王者 后羿 微信 / 安卓 / ios\n不指定则查询全部4个平台战力\n结果包含：头像、区域、背景、台词、语音、战力门槛", msg_id=msg_id)
        return True
    if text.startswith("王者 ") or text.startswith("王者\u3000"):
        await _manager._query_wangzhe(api, text[2:].strip(), group_openid, msg_id, scene)
        return True
    return False
