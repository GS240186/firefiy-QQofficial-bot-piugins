# -*- coding: utf-8 -*-
"""学习·古诗文（study_poetry）—— 学习系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.study_core import StudyManager, ChatScene
from modules.common import send_text
from modules.qa_common import qa_is_active, qa_is_owner

PLUGIN = {
    "key": "study_poetry",
    "name": "学习·古诗文",
    "priority": 30,
    "description": "发送「古诗文 关键词」查诗词",
    "category": "study",
}

_manager = StudyManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("study", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("study_poetry", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    target_id = ctx.target_id or ctx.member_openid
    member_openid, msg_id = ctx.member_openid, ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    if text in ("古诗文", "古诗", "诗词"):
        await send_text(api, scene, target_id,
            "📜 古诗文查询\n━━━━━━━━━━\n用法：古诗文 关键词\n示例：古诗文 李白 / 古诗文 静夜思",
            msg_id=msg_id)
        return True
    if text.startswith("古诗文 ") or text.startswith("古诗 ") or text.startswith("诗词 "):
        prefix = text.split()[0]
        word = text[len(prefix):].strip()
        if word:
            await _manager._query_poetry(api, scene, target_id, msg_id, word)
        else:
            await send_text(api, scene, target_id,
                "📜 古诗文查询\n━━━━━━━━━━\n用法：古诗文 关键词\n示例：古诗文 李白 / 古诗文 静夜思",
                msg_id=msg_id)
        return True
    return False
