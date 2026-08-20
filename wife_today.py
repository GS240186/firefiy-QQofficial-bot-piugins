# -*- coding: utf-8 -*-
"""
外置插件：今日老婆（wife_today）

发送「今日老婆」或「抽老婆」，从本地 wife 图库按用户+日期固定随机抽取一张
二次元老婆图片。每日同一名用户抽到的角色固定，次日零点刷新。

图库默认路径已内置到项目 assets/wife 目录（img1/ + img2/）。
如需覆盖，可在 data/wife_config.json 中通过 {"wife_dir": "你的路径"} 指定。
"""

import hashlib
import os
import time

PLUGIN = {
    "key": "wife_today",
    "name": "今日老婆",
    "priority": 500,
    "description": "发送「今日老婆」抽取今日专属二次元老婆（每日固定）",
    "category": "game",
    "config_schema": [
        {"key": "wife_today_enable_history", "type": "bool", "default": False, "label": "是否保存抽取历史"},
        {"key": "wife_today_refresh_hour", "type": "int", "default": 0, "label": "每日刷新时间（小时）", "min": 0, "max": 23},
        {"key": "wife_today_show_image", "type": "bool", "default": True, "label": "是否显示图片"},
    ],
}

# 默认图库目录已内置到项目 assets/wife，支持通过 data/wife_config.json 覆盖
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_WIFE_DIR = os.path.join(_PROJECT_ROOT, "assets", "wife")
_CONFIG_FILE = os.path.join(_PROJECT_ROOT, "data", "wife_config.json")

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
_TRIGGERS = ("今日老婆", "抽老婆", "wife")

_wife_dir = _DEFAULT_WIFE_DIR
_image_cache = []
_last_scan_ts = 0


def _load_config():
    """读取 wife 图库路径配置。"""
    global _wife_dir
    try:
        import json as _json
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = _json.load(f)
        _wife_dir = cfg.get("wife_dir") or _DEFAULT_WIFE_DIR
    except Exception:
        _wife_dir = _DEFAULT_WIFE_DIR


def _get_wife_dir():
    return _wife_dir


def _scan_images():
    """扫描 wife/img1 与 wife/img2 下的图片，缓存 30 秒。"""
    global _image_cache, _last_scan_ts
    wife_dir = _get_wife_dir()
    if not os.path.isdir(wife_dir):
        return []

    now = time.time()
    if now - _last_scan_ts < 30 and _image_cache:
        return _image_cache

    paths = []
    for sub in ("img1", "img2"):
        d = os.path.join(wife_dir, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith(_IMAGE_EXTENSIONS):
                paths.append(os.path.join(d, fn))

    _image_cache = paths
    _last_scan_ts = now
    return paths


def _parse_filename(path):
    """从文件名解析作品名和角色名。
    命名约定：作品名!角色名.扩展名
    """
    base = os.path.basename(path)
    name, _ = os.path.splitext(base)
    if "!" in name:
        work, char = name.split("!", 1)
    else:
        work, char = "未知作品", name
    # 常见的 URL 编码/空格替换还原
    work = work.replace("_", " ").strip() or "未知作品"
    char = char.replace("_", " ").strip() or "未知角色"
    return work, char


def _pick_today(user_id, images):
    """按 user_id + 日期做固定随机，保证同一人同日结果不变。"""
    if not images:
        return None
    today = time.strftime("%Y-%m-%d")
    seed_str = "%s|%s|wife_today" % (user_id, today)
    seed = hashlib.md5(seed_str.encode("utf-8")).hexdigest()
    idx = int(seed, 16) % len(images)
    return images[idx]


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    content = (ctx.content or "").strip().lower()
    if content not in _TRIGGERS:
        return False

    # 延迟加载配置与开关检查，避免模块加载期依赖问题
    _load_config()
    try:
        from console_server import is_feature_enabled, is_sub_feature_enabled
        if not is_feature_enabled("game", appid=ctx.bot_appid):
            return False
        if not is_sub_feature_enabled("game_wife_today", appid=ctx.bot_appid):
            return False
    except Exception:
        pass

    images = _scan_images()
    if not images:
        await ctx.reply("咦，老婆图库还是空的呢，先检查一下 wife 目录吧～")
        return True

    user_id = (ctx.member_openid or ctx.storage_id or "unknown").strip()
    path = _pick_today(user_id, images)
    if not path:
        await ctx.reply("啊，抽签筒好像卡住了，等会儿再试试？")
        return True

    work, char = _parse_filename(path)
    text = "✨ 今日为你抽到的老婆是——\n《%s》的 %s\n希望她能给你带来好心情呀～" % (work, char)

    try:
        with open(path, "rb") as f:
            img_bytes = f.read()
    except Exception as e:
        await ctx.reply(text + "\n（图片读取失败：%s）" % e)
        return True

    try:
        await _send_image_bytes(
            ctx.api, ctx.scene, ctx.target_id, img_bytes,
            msg_id=ctx.msg_id, content=text
        )
    except Exception as e:
        await ctx.reply(text + "\n（图片发送失败：%s）" % e)
    return True

# ============ 自包含图片发送辅助（仅依赖 botpy SDK，独立运行无需主项目）============

import base64 as _b64
import logging as _log
import time as _tm

_PLUGIN_SEND_LOG = _log.getLogger("plugin.send")
_PLUGIN_SEND_SEQ = {"n": 0}


def _plugin_send_seq() -> int:
    _PLUGIN_SEND_SEQ["n"] += 1
    return int(_tm.time() * 1000) % 1000000000 + _PLUGIN_SEND_SEQ["n"]


async def _plugin_upload_file(api, route_path: str, file_type: int, file_bytes: bytes):
    """上传富媒体文件（本地 bytes -> base64），返回 file_info 或 None。"""
    from botpy.http import Route
    payload = {
        "file_type": file_type,
        "file_data": _b64.b64encode(file_bytes).decode("utf-8"),
        "srv_send_msg": False,
    }
    try:
        resp = await api._http.request(Route("POST", route_path), json=payload)
        if isinstance(resp, dict):
            return resp.get("file_info")
    except Exception as e:
        _PLUGIN_SEND_LOG.warning("上传文件失败: %s", e)
    return None


async def _plugin_send_media(api, route_path: str, payload: dict):
    from botpy.http import Route
    try:
        return await api._http.request(Route("POST", route_path), json=payload)
    except Exception as e:
        _PLUGIN_SEND_LOG.warning("发送媒体消息失败: %s", e)
        return None


async def _send_image_bytes(api, scene: str, target_id: str, image_bytes: bytes,
                            content: str = "", msg_id: str = None):
    """自包含本地图片发送（msg_type=7 富媒体）。scene: group/c2c。返回结果或 None。"""
    if not api or not target_id or not image_bytes:
        return None
    s = (scene or "").lower()
    if s not in ("group", "c2c"):
        return None
    if s == "group":
        fi = await _plugin_upload_file(api, "/v2/groups/{group_openid}/files", 1, image_bytes)
        if not fi:
            return None
        payload = {
            "group_openid": target_id,
            "msg_type": 7,
            "content": content or "",
            "media": {"file_info": fi},
            "msg_seq": _plugin_send_seq(),
        }
        if msg_id:
            payload["msg_id"] = msg_id
        return await _plugin_send_media(api, "/v2/groups/{group_openid}/messages", payload)
    fi = await _plugin_upload_file(api, "/v2/users/{openid}/files", 1, image_bytes)
    if not fi:
        return None
    payload = {
        "msg_type": 7,
        "content": content or "",
        "media": {"file_info": fi},
        "msg_seq": _plugin_send_seq(),
    }
    if msg_id:
        payload["msg_id"] = msg_id
    return await _plugin_send_media(api, "/v2/users/{openid}/messages", payload)
