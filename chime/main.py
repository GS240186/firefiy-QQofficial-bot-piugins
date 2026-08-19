# -*- coding: utf-8 -*-
"""整点报时（chime）—— 群管系统独立插件

发送「整点报时」打开报时菜单（开关/设置/立即报时），仅群主/群管理员/控制台管理员可操作。
自动整点报时由 console_server 调度（仅当本插件已安装时生效）。
"""

import sys as _sys
import os as _os

_PLUGINS_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PLUGINS_DIR not in _sys.path:
    _sys.path.insert(0, _PLUGINS_DIR)

from modules.common import (
    send_group_text,
    send_group_text_with_keyboard,
    send_group_image,
    build_keyboard_multi,
    clean_content,
    logger,
)

PLUGIN = {
    "key": "chime",
    "name": "整点报时",
    "priority": 95,
    "description": "整点报时（报时开关/设置/立即报时），仅群主/管理员可操作",
    "category": "admin",
}

_CHIME_API_URL = "https://api.yuafeng.cn/API/ly/time.php"


def _has_privilege(member_role: str, is_console_admin: bool) -> bool:
    """整点报时仅限群主 / 群管理员 / 控制台管理员。"""
    if is_console_admin:
        return True
    return member_role in ("owner", "admin")


async def _send_chime_menu(api, group_openid: str, msg_id: str):
    try:
        from console_server import get_chime_group_config, _coerce_int
        cfg = get_chime_group_config(group_openid)
        state = "✅ 已开启" if cfg.get("enabled") else "⏹ 已关闭"
        iv = _coerce_int(cfg.get("interval_hours", 1), 1)
        ps = _coerce_int(cfg.get("period_start", 0), 0)
        pe = _coerce_int(cfg.get("period_end", 23), 23)
        text = ("⏰ 整点报时（自动）\n当前状态：%s｜每 %d 小时｜时段 %02d:00–%02d:00\n"
                "点击下方按钮操作（仅群主/管理员可改）：" % (state, iv, ps, pe))
    except Exception:
        text = "⏰ 整点报时（自动）\n点击下方按钮操作（仅群主/管理员可改）："
    keyboard = build_keyboard_multi([
        {"label": "报时开关", "command": "报时开关", "id": "btn_chime_toggle", "enter": False},
        {"label": "报时设置", "command": "报时设置", "id": "btn_chime_set", "enter": False},
        {"label": "立即报时", "command": "立即报时", "id": "btn_chime_now", "enter": False},
    ])
    await send_group_text_with_keyboard(api, group_openid, text, keyboard, msg_id=msg_id)


async def _send_chime_settings_menu(api, group_openid: str, msg_id: str):
    text = "⚙️ 报时设置\n选择要修改的项目："
    keyboard = build_keyboard_multi([
        {"label": "报时间隔设置", "command": "报时间隔设置", "id": "btn_chime_iv", "enter": False},
        {"label": "报时时段设置", "command": "报时时段设置", "id": "btn_chime_pd", "enter": False},
    ])
    await send_group_text_with_keyboard(api, group_openid, text, keyboard, msg_id=msg_id)


async def _chime(api, group_openid: str, msg_id: str):
    """立即报时：调用第三方 API 获取整点报时图并发送。"""
    try:
        result = await send_group_image(api, group_openid, _CHIME_API_URL, msg_id=msg_id)
        if not result:
            await send_group_text(api, group_openid, "⏰ 整点报时获取失败，请稍后再试", msg_id=msg_id)
    except Exception as e:
        logger.error("整点报时失败: %s" % e)
        await send_group_text(api, group_openid, "⏰ 整点报时获取失败：%s" % e, msg_id=msg_id)


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not ctx.is_group:
        return False
    if not is_feature_enabled("chime", appid=ctx.bot_appid):
        return False
    api, group_openid, msg_id = ctx.api, ctx.target_id, ctx.msg_id
    member_role, is_console_admin = ctx.member_role, ctx.is_console_admin
    content = clean_content(ctx.content or "").strip()
    if not content:
        return False

    is_menu = (content == "整点报时")
    is_toggle = (content == "报时开关")
    is_settings = (content == "报时设置")
    is_interval_cmd = (content == "报时间隔设置")
    is_period_cmd = (content == "报时时段设置")
    is_now = (content == "立即报时")
    is_interval_set = content.startswith("间隔")
    is_period_set = content.startswith("时段")
    if not (is_menu or is_toggle or is_settings or is_interval_cmd or is_period_cmd
            or is_now or is_interval_set or is_period_set):
        return False

    if not _has_privilege(member_role, is_console_admin):
        await send_group_text(api, group_openid,
                              "⚠️ 整点报时仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                              msg_id=msg_id)
        return True

    if is_menu:
        await _send_chime_menu(api, group_openid, msg_id)
        return True

    if is_toggle:
        try:
            from console_server import set_chime_group_enabled, get_chime_group_config, _coerce_int
            cfg = get_chime_group_config(group_openid)
            new_cfg = set_chime_group_enabled(group_openid, not cfg.get("enabled"))
            state = "✅ 已开启" if new_cfg.get("enabled") else "⏹ 已关闭"
            iv = _coerce_int(new_cfg.get("interval_hours", 1), 1)
            ps = _coerce_int(new_cfg.get("period_start", 0), 0)
            pe = _coerce_int(new_cfg.get("period_end", 23), 23)
            tip = ""
            if new_cfg.get("enabled"):
                tip = ("\n⚠️ 自动报时会由机器人在整点向本群主动推送报时图，需要机器人「主动发言权限」"
                       "（每日 %02d:00–%02d:00，每 %d 小时一次）。" % (ps, pe, iv))
            await send_group_text(api, group_openid,
                                  "⏰ 本群整点报时（自动）%s（每 %d 小时，时段 %02d:00–%02d:00）。%s" % (state, iv, ps, pe, tip),
                                  msg_id=msg_id)
        except Exception as e:
            logger.error("报时开关切换失败: %s" % e)
            await send_group_text(api, group_openid, "⏰ 报时开关切换失败：%s" % e, msg_id=msg_id)
        return True

    if is_settings:
        await _send_chime_settings_menu(api, group_openid, msg_id)
        return True

    if is_interval_cmd:
        try:
            from console_server import get_chime_group_config, _coerce_int
            cfg = get_chime_group_config(group_openid)
            iv = _coerce_int(cfg.get("interval_hours", 1), 1)
            await send_group_text(api, group_openid,
                                  "⏰ 本群当前报时间隔：每 %d 小时在整点报时一次。\n请直接回复『间隔 N』设置（N 为 1-24 的整数，例如：间隔 2）。" % iv,
                                  msg_id=msg_id)
        except Exception as e:
            logger.error("报时间隔设置提示失败: %s" % e)
            await send_group_text(api, group_openid, "⏰ 操作失败：%s" % e, msg_id=msg_id)
        return True

    if is_period_cmd:
        try:
            from console_server import get_chime_group_config, _coerce_int
            cfg = get_chime_group_config(group_openid)
            ps = _coerce_int(cfg.get("period_start", 0), 0)
            pe = _coerce_int(cfg.get("period_end", 23), 23)
            await send_group_text(api, group_openid,
                                  "⏰ 本群当前可报时时段：%02d:00–%02d:00。\n请直接回复『时段 起-止』设置（0-23 小时，24 小时制，例如：时段 9-21）。" % (ps, pe),
                                  msg_id=msg_id)
        except Exception as e:
            logger.error("报时时段设置提示失败: %s" % e)
            await send_group_text(api, group_openid, "⏰ 操作失败：%s" % e, msg_id=msg_id)
        return True

    if is_interval_set:
        try:
            from console_server import set_chime_group_interval, _coerce_int
            num = content[len("间隔"):].strip()
            iv = _coerce_int(num, 0)
            if iv < 1 or iv > 24:
                await send_group_text(api, group_openid, "⏰ 间隔需为 1-24 的整数（小时）。请回复例如：间隔 2", msg_id=msg_id)
                return True
            cfg = set_chime_group_interval(group_openid, iv)
            await send_group_text(api, group_openid,
                                  "⏰ 已设置本群报时间隔：每 %d 小时在整点报时一次。" % _coerce_int(cfg.get("interval_hours", iv), iv),
                                  msg_id=msg_id)
        except Exception as e:
            logger.error("设置报时间隔失败: %s" % e)
            await send_group_text(api, group_openid, "⏰ 设置失败：%s" % e, msg_id=msg_id)
        return True

    if is_period_set:
        try:
            import re as _re
            from console_server import set_chime_group_period, _coerce_int
            seg = content[len("时段"):].strip()
            m = _re.search(r"(\d{1,2})\s*[-~到至]\s*(\d{1,2})", seg)
            if not m:
                m = _re.match(r"(\d{1,2})\s+(\d{1,2})", seg)
            if not m:
                await send_group_text(api, group_openid, "⏰ 格式有误。请回复例如：时段 9-21（0-23 小时）", msg_id=msg_id)
                return True
            s = _coerce_int(m.group(1), -1)
            e = _coerce_int(m.group(2), -1)
            if s < 0 or s > 23 or e < 0 or e > 23:
                await send_group_text(api, group_openid, "⏰ 小时需在 0-23 之间。请回复例如：时段 9-21", msg_id=msg_id)
                return True
            cfg = set_chime_group_period(group_openid, s, e)
            await send_group_text(api, group_openid,
                                  "⏰ 已设置本群可报时时段：%02d:00–%02d:00。" % (_coerce_int(cfg.get("period_start"), s), _coerce_int(cfg.get("period_end"), e)),
                                  msg_id=msg_id)
        except Exception as e:
            logger.error("设置报时时段失败: %s" % e)
            await send_group_text(api, group_openid, "⏰ 设置失败：%s" % e, msg_id=msg_id)
        return True

    if is_now:
        await _chime(api, group_openid, msg_id)
        return True

    return False
