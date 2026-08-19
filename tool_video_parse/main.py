# -*- coding: utf-8 -*-
"""工具·视频解析（tool_video_parse）—— 工具系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.tools_core import ToolsManager, ChatScene
from modules.common import send_text

PLUGIN = {
    "key": "tool_video_parse",
    "name": "工具·视频解析",
    "priority": 20,
    "description": "发送「视频解析」解析无水印视频",
    "category": "tool",
}

_manager = ToolsManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("tools", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("tool_video_parse", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    group_openid, member_openid = ctx.target_id, ctx.member_openid
    msg_id = ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    if text == "视频解析":
        await _manager._video_parse_start(api, group_openid, member_openid, scene=scene, msg_id=msg_id)
        return True
    from _common.tools_core import load_json, save_json, VIDEO_PARSE_STATE_FILE
    video_states = load_json(VIDEO_PARSE_STATE_FILE)
    video_key = _manager._state_key(group_openid, member_openid)
    if video_key in video_states and video_states[video_key].get("waiting"):
        if text == "取消":
            del video_states[video_key]
            save_json(VIDEO_PARSE_STATE_FILE, video_states)
            await send_text(api, scene, group_openid, "已取消视频解析", msg_id=msg_id)
            return True
        url = _manager._extract_video_url(text)
        if url:
            if _manager._detect_platform(url) == "未知平台":
                await send_text(api, scene, group_openid, "暂不支持该链接，目前支持抖音/快手/B站/小红书/视频号/油管/TikTok等20+平台\n发送「取消」可取消解析", msg_id=msg_id)
                return True
            await _manager._video_parse_query(api, url, group_openid, member_openid, msg_id, scene)
            return True
        await send_text(api, scene, group_openid, "未识别到视频链接，请发送抖音/快手/B站/小红书等平台的分享链接\n发送「取消」可取消解析", msg_id=msg_id)
        return True
    return False


def is_waiting(storage_id: str, member_openid: str) -> bool:
    return _manager.is_waiting(storage_id, member_openid)


async def handle_callback(api, button_data: str, target_id: str, user_id: str,
                          scene=None, event_id=None) -> bool:
    return await _manager.handle_callback(
        api, button_data, target_id, user_id, scene=scene, event_id=event_id)
