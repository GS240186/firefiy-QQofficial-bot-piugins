# -*- coding: utf-8 -*-
"""学习·知识问答（study_quiz）—— 学习系统细粒度插件"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.study_core import StudyManager, ChatScene
from modules.common import send_text
from modules.qa_common import qa_is_active, qa_is_owner

PLUGIN = {
    "key": "study_quiz",
    "name": "学习·知识问答",
    "priority": 30,
    "description": "发送「知识问答」开始答题",
    "category": "study",
}

_manager = StudyManager()


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("study", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("study_quiz", appid=ctx.bot_appid):
        return False
    api, scene = ctx.api, ctx.scene or ChatScene.GROUP
    target_id = ctx.target_id or ctx.member_openid
    member_openid, msg_id = ctx.member_openid, ctx.msg_id
    text = (ctx.content or "").strip()
    if not text:
        return False
    QTYPE = "quiz_common"
    # 答题交互指令（有会话才拦截）
    exact_map = {"常识答案": QTYPE, "常识跳过": QTYPE, "常识下一题": QTYPE}
    submit_map = {"常识作答": QTYPE}
    if text in exact_map:
        if not qa_is_active(target_id, QTYPE):
            return False
        if scene == ChatScene.GROUP and not qa_is_owner(target_id, QTYPE, member_openid):
            return True
        if text.endswith("答案"):
            return await _manager._on_answer_btn(api, scene, target_id, member_openid, msg_id, QTYPE)
        if text.endswith("跳过"):
            return await _manager._on_skip_btn(api, scene, target_id, member_openid, msg_id, QTYPE)
        return await _manager._on_next_btn(api, scene, target_id, member_openid, msg_id, QTYPE)
    for pfx, qtype in submit_map.items():
        if text.startswith(pfx):
            return await _manager._on_submit(api, scene, target_id, member_openid, msg_id, qtype, text[len(pfx):].strip())
    # 功能入口
    entry_map = {"知识问答": QTYPE, "常识": QTYPE, "问答": QTYPE}
    if text in entry_map:
        await _manager._begin_quiz(api, scene, target_id, member_openid, msg_id, entry_map[text])
        return True
    return False
