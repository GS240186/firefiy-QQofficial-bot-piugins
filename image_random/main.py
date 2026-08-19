# -*- coding: utf-8 -*-
"""图片·随机图库（image_random）—— 角色图库/随机图片/看图"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from _common.image_core import ImageManager

PLUGIN = {
    "key": "image_random",
    "name": "图片·随机图库",
    "priority": 60,
    "description": "发送「角色图库/随机图片/看图」查看分类图库",
    "category": "image",
}

_manager = ImageManager()

_RANDOM_ALIASES = ("角色图库", "随机图片", "随机图", "看图")


async def prewarm_photo():
    """启动预热角色图库分类缓存（失败静默）。"""
    try:
        await _manager.prewarm_photo()
    except Exception:
        pass


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("image", appid=ctx.bot_appid):
        return False
    if not is_feature_enabled("image_random", appid=ctx.bot_appid):
        return False
    content = (ctx.content or "").strip()
    if content in _RANDOM_ALIASES:
        await _manager.send_random_photo_menu(ctx.api, ctx.target_id, ctx.msg_id, scene=ctx.scene)
        return True
    for _p in _RANDOM_ALIASES:
        if content.startswith(_p + " ") or content.startswith(_p + "　"):
            keyword = content[len(_p):].strip()
            if not keyword or keyword == "全部":
                await _manager.send_random_photo(ctx.api, ctx.target_id, ctx.msg_id, scene=ctx.scene)
                return True
            if not _manager.photo_categories:
                await _manager._photo_fetch_categories(force=True)
            cat = _manager._photo_match_category(keyword)
            if cat:
                await _manager.send_random_photo(ctx.api, ctx.target_id, ctx.msg_id, category=cat, scene=ctx.scene)
                return True
            from modules.common import send_text
            await send_text(ctx.api, ctx.scene, ctx.target_id,
                            "😢 没找到「%s」相关的分类，发送「角色图库」查看分类菜单～" % keyword,
                            msg_id=ctx.msg_id)
            return True
    return False
