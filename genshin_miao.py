# -*- coding: utf-8 -*-
"""
小流萤 · 原神 M1 主插件 (聚合 miao-plugin 风格本地功能到外置插件)
触发方式 (双路, 与 miao 风格一致):
  - #<命令>              主触发, 群/私聊都可
  - 原神<命令> / ys<命令> 别名 (与现有「原神 角色名」「原神绑定」不冲突的子集)

高优先级前缀:  #  开头 (原神主插件 priority=500 管 '原神' 起头, 不冲突)
优先级: 400 (排在原神主插件 500 之后, 重叠时主插件先响应)

M1 13 个本地数据驱动功能:
  #今日素材 / 原神今日素材
  #五星 / 原神五星            五星角色图鉴
  #武器 / 原神武器            五星武器图鉴
  #<角色>技能 / #<角色>命座  miao 角色详情 (本地) [例 #胡桃命座]
  #<角色>图鉴 / #<武器>图鉴   角色或武器图片    [例 #心海图鉴 / #护摩]
  #<角色>照片                角色图片           [例 #甘雨照片]
  #<角色>攻略                西风驿站攻略       [例 #刻晴攻略]
  #老婆/#老公                查已设置老婆
  #老婆列表                  同 #老婆
  #老婆设置 <名1>,<名2>...   设置
  #老婆添加 <名>
  #老婆删除 <名>
  #老婆清空
  #老婆照片  随机发一张      (已设置老婆优先)
  #五星列表                  玩家展示 5 星角色
  #练度统计                  展示角色等级分布
  #圣遗物列表                展示角色套装汇总
  #角色持有 / #角色0命        全角色持有率
  #版本 / #原神版本 / #喵喵版本   显示当前 bot 版本
  #帮助 / #原神帮助          列出 miao 风格功能清单 (M1+M2 注明计划)
  #面板帮助                  扩展原有帮助

失败容错:
  - 任何 IO / 渲染失败回退到文本片段并附原因
"""

import asyncio
import os
import re

from modules.common import send_text, send_local_image_for_scene

# =============================================================================
# 依赖模块容错导入
# 这些 lib.genshin_panel_miao.{miao_features,wiki_data,wife,gacha} 模块在本仓库
# 当前版本尚未实现（早期设计的占位接口）。为避免 external_plugin_watcher 每 3 秒
# 热重试时报 ERROR 刷屏，所有依赖都用 try/except 包住；缺失时降级为占位函数，
# 使导入永不抛异常——后续若补齐真实模块，重启 bot 即自动生效。
# =============================================================================

_missing_modules = set()  # 启动期一次性收集，运行期不再重复 warning


def _try_import(symbol_qualname):
    """'lib.genshin_panel_miao.miao_features.today_materials_text' → 函数 / None."""
    try:
        mod_path, _, attr = symbol_qualname.rpartition(".")
        if not mod_path:
            return None
        mod = __import__(mod_path, fromlist=[attr])
        return getattr(mod, attr)
    except Exception:
        if mod_path not in _missing_modules:
            _missing_modules.add(mod_path)
            try:
                import logging
                logging.getLogger("plugin.genshin_miao").debug(
                    "可选依赖缺失，功能降级为占位: %s", mod_path)
            except Exception:
                pass
        return None


# 文本类: 真模块存在时直接调; 不存在时返回 (None, "降级提示")
def _placeholder_text(_name):
    return (None, "⚠️ 该功能依赖的 lib.genshin_panel_miao 模块尚未实现，请联系开发者补齐。")


# 1) miao_features 8 个文本/图函数: 全部允许返回 (mode,text)
today_materials_text = _try_import("lib.genshin_panel_miao.miao_features.today_materials_text")
five_star_text = _try_import("lib.genshin_panel_miao.miao_features.five_star_text")
talent_or_constellation_text = _try_import("lib.genshin_panel_miao.miao_features.talent_or_constellation_text")
collection_image = _try_import("lib.genshin_panel_miao.miao_features.collection_image")
player_five_star_lines = _try_import("lib.genshin_panel_miao.miao_features.player_five_star_lines")
player_training_stats_text = _try_import("lib.genshin_panel_miao.miao_features.player_training_stats_text")
artifact_list_text = _try_import("lib.genshin_panel_miao.miao_features.artifact_list_text")
player_zero_const_stats = _try_import("lib.genshin_panel_miao.miao_features.player_zero_const_stats")
guide_text = _try_import("lib.genshin_panel_miao.miao_features.guide_text")

# 2) wiki_data 5 个查询/资源函数
resolve_alias = _try_import("lib.genshin_panel_miao.wiki_data.resolve_alias")
load_weapon = _try_import("lib.genshin_panel_miao.wiki_data.load_weapon")
get_char_face_img = _try_import("lib.genshin_panel_miao.wiki_data.get_char_face_img")
get_char_card_img = _try_import("lib.genshin_panel_miao.wiki_data.get_char_card_img")
get_char_splash_img = _try_import("lib.genshin_panel_miao.wiki_data.get_char_splash_img")
resolve_weapon_alias = _try_import("lib.genshin_panel_miao.wiki_data.resolve_weapon_alias")
MIAO_RES_marker = _try_import("lib.genshin_panel_miao.wiki_data.MIAO_RES")  # 仅检测可用性

# 3) wife 系统 6 个
get_wife = _try_import("lib.genshin_panel_miao.wife.get_wife")
set_wife = _try_import("lib.genshin_panel_miao.wife.set_wife")
add_wife = _try_import("lib.genshin_panel_miao.wife.add_wife")
remove_wife = _try_import("lib.genshin_panel_miao.wife.remove_wife")
clear_wife = _try_import("lib.genshin_panel_miao.wife.clear_wife")
pick_random_wife = _try_import("lib.genshin_panel_miao.wife.pick_random_wife")

# 4) gacha 2 个
gacha_pull = _try_import("lib.genshin_panel_miao.gacha.gacha_pull")
gacha_summary = _try_import("lib.genshin_panel_miao.gacha.gacha_summary")


# =============================================================================
# 降级占位: 当任一缺失函数被调用时, 返回最简 (mode,text) 让 handle 仍能 return True
# 不抛异常 → 不刷 ERROR 日志.
# =============================================================================

def _ensure_callable(fn, name, fallback):
    """若 fn 为 None, 返回一个永远返回 fallback 的包装函数 (避免 handle 报 NameError)."""
    if fn is not None:
        return fn
    def _wrap(*_a, **_kw):
        return fallback
    _wrap.__name__ = "_placeholder_" + name
    return _wrap


# 真占位: 文本类 8 + 资源类 5 + 老婆/抽卡 占位回退
today_materials_text = _ensure_callable(today_materials_text, "today_materials_text", _placeholder_text("today"))
five_star_text = _ensure_callable(five_star_text, "five_star_text", _placeholder_text("five"))
talent_or_constellation_text = _ensure_callable(talent_or_constellation_text, "talent_or_constellation_text", (None, _placeholder_text("talent")[1]))


def _placeholder_collection_image(*_a, **_kw):
    return None


collection_image = _ensure_callable(collection_image, "collection_image", None)
player_five_star_lines = _ensure_callable(player_five_star_lines, "player_five_star_lines", _placeholder_text("5星列表")[1])
player_training_stats_text = _ensure_callable(player_training_stats_text, "player_training_stats_text", _placeholder_text("练度统计")[1])
artifact_list_text = _ensure_callable(artifact_list_text, "artifact_list_text", _placeholder_text("圣遗物列表")[1])
player_zero_const_stats = _ensure_callable(player_zero_const_stats, "player_zero_const_stats", _placeholder_text("角色持有")[1])
guide_text = _ensure_callable(guide_text, "guide_text", _placeholder_text("攻略")[1])

# 资源/查询占位: 都返回空集合/None, 让 dispatch 自然退路走原神主插件
resolve_alias = _ensure_callable(resolve_alias, "resolve_alias", lambda *_a, **_kw: "")
load_weapon = _ensure_callable(load_weapon, "load_weapon", lambda *_a, **_kw: {})
get_char_face_img = _ensure_callable(get_char_face_img, "get_char_face_img", lambda *_a, **_kw: "")
get_char_card_img = _ensure_callable(get_char_card_img, "get_char_card_img", lambda *_a, **_kw: "")
get_char_splash_img = _ensure_callable(get_char_splash_img, "get_char_splash_img", lambda *_a, **_kw: "")
resolve_weapon_alias = _ensure_callable(resolve_weapon_alias, "resolve_weapon_alias", lambda *_a, **_kw: "")

# 老婆系统占位: get/set/add/remove 返回空 list/false, 不修改任何持久化
get_wife = _ensure_callable(get_wife, "get_wife", lambda *_a, **_kw: [])
set_wife = _ensure_callable(set_wife, "set_wife", lambda *_a, **_kw: [])
add_wife = _ensure_callable(add_wife, "add_wife", lambda *_a, **_kw: [])
remove_wife = _ensure_callable(remove_wife, "remove_wife", lambda *_a, **_kw: [])
clear_wife = _ensure_callable(clear_wife, "clear_wife", lambda *_a, **_kw: None)
pick_random_wife = _ensure_callable(pick_random_wife, "pick_random_wife", lambda *_a, **_kw: "")

# 抽卡占位: 返回空结果, 让 _dispatch_gacha 跳过图片发送并打占位说明
def _placeholder_gacha_pull(*_a, **_kw):
    return []
def _placeholder_gacha_summary(_res, *_a, **_kw):
    return "⚠️ 抽卡功能依赖的 gacha 模块尚未实现。"
gacha_pull = _ensure_callable(gacha_pull, "gacha_pull", _placeholder_gacha_pull)
gacha_summary = _ensure_callable(gacha_summary, "gacha_summary", _placeholder_gacha_summary)


# adapter / maps 真实存在, 沿用原写法
from lib.genshin_panel_miao.adapter import build_render_data
from lib.genshin_panel_miao import maps as _MAPS


PLUGIN = {
    "key": "genshin_miao",
    "name": "原神·M1 聚合",
    "priority": 400,
    "description": "聚合 miao-plugin 本地数据驱动功能到原神插件（#今日素材 / #五星 / #<角色>技能 / #老婆 等 13 项）",
    "config_schema": [
        {"key": "genshin_miao_enable_panel", "type": "bool", "default": True, "label": "是否启用角色面板"},
        {"key": "genshin_miao_panel_timeout", "type": "int", "default": 30, "label": "面板查询超时（秒）", "min": 5, "max": 120},
        {"key": "genshin_miao_max_skills", "type": "int", "default": 5, "label": "单次查询技能数", "min": 1, "max": 10},
    ],
}


# ============================================================================
# 工具: 把路径转 bytes; 把 # / 原神 / ys 前缀去掉
# ============================================================================

def _read_image_bytes(p):
    if not p:
        return None
    try:
        with open(p, "rb") as f:
            return f.read()
    except Exception:
        return None


def _strip_prefix(content):
    s = (content or "").strip()
    if not s:
        return ""
    if not s.startswith("#"):
        return ""  # 强制 # 前缀：原神指令必须以 # 开头
    for _ in range(2):
        s = s.lstrip("#").strip()
        s = re.sub(r"^(?:原神|ys|genshin)\s*", "", s, flags=re.IGNORECASE).strip()
    return s


# 纯静态本地功能 (不依赖玩家 UID)
_RE_TODAY = re.compile(r"^(?:今日素材|今日材料)$", re.IGNORECASE)
_RE_FIVE_STAR = re.compile(r"^五星$", re.IGNORECASE)
_RE_WEAPON = re.compile(r"^(?:武器|五星武器)$", re.IGNORECASE)
_RE_VERSION = re.compile(r"^(?:版本|喵喵版本|原神版本)$", re.IGNORECASE)
# 新免鉴权功能: 抽卡 / 圣遗物评分 / 伤害计算
_RE_GACHA = re.compile(r"^(?:十连|单抽|抽卡|十连抽|来一发|十连一发)$")
_RE_SCORE = re.compile(r"^圣遗物评分$|^评分$")
_RE_DMG = re.compile(r"^伤害计算(?:\s+(.+))?$|^伤害$|^算伤害$")

# 角色/武器详情命令
#  匹配: '胡桃命座', '胡桃技能', '胡桃天赋', '心海图鉴', '护摩图鉴', '甘雨照片',
#  以及 '胡桃' （无后缀）按"角色卡"处理（只查命座+天赋文本）
_RE_TALENT = re.compile(r"^(.{1,8}?)(?:技能|天赋)$")
_RE_CONST = re.compile(r"^(.{1,8}?)命座$")
# 武器图鉴, 例: 护摩 / 雾切 之回光 / 薙草之稻光
_RE_WEAPON_COLL = re.compile(r"^(.{1,12}?)图鉴$")

# 老婆/老公 (在 CHART_PHOTO 之前匹配, 避免 #老婆照片 被误当 "老婆" 的照片)
_RE_WIFE_LIST = re.compile(r"^(?:老婆|老公|老婆列表|老公列表)$", re.IGNORECASE)
_RE_WIFE_SET = re.compile(r"^老婆(?:设置|设定)\s+(.+)$")
_RE_WIFE_ADD = re.compile(r"^(?:老婆|老公)(?:添加|新增)\s+(.+)$")
_RE_WIFE_RM = re.compile(r"^(?:老婆|老公)(?:删除|移除)\s+(.+)$")
_RE_WIFE_CLEAR = re.compile(r"^(?:老婆|老公)(?:清空|清除|清零|清)$", re.IGNORECASE)
_RE_WIFE_PHOTO = re.compile(r"^(?:老婆|老公)(?:照片|相片)$", re.IGNORECASE)

# 角色图鉴 / 照片 (注意: 必须放在 WIFE_PHOTO 之后, 否则 #老婆照片 会先撞)
_RE_CHAR_COLL = re.compile(r"^(.{1,8}?)图鉴$")
_RE_CHAR_PHOTO = re.compile(r"^((?!^老婆照片$|^老公照片$|^老婆相片$|^老公相片$)[一-龥A-Za-z·\u3000]{1,8})(?:照片|相片)$")

# 攻略
_RE_GUIDE = re.compile(r"^(.{1,8}?)攻略$")

# 玩家绑定 UID 后的功能
_RE_FIVE_LIST = re.compile(r"^五星列表$", re.IGNORECASE)
_RE_TRAIN_STATS = re.compile(r"^练度统计$", re.IGNORECASE)
_RE_ARTIFACT_LIST = re.compile(r"^圣遗物(?:列表|汇总|总览)?$", re.IGNORECASE)
_RE_HOLD_RATE = re.compile(r"^(?:角色持有|角色0命)$", re.IGNORECASE)

# 帮助
_RAW_HELP_RE = re.compile(r"^#\s*(?:原神|ys|genshin)\s*(?:菜单|帮助|功能|help|menu|usage)$", re.IGNORECASE)
_RE_PANEL_HELP = re.compile(r"^面板(?:帮助|help)$", re.IGNORECASE)


# ============================================================================
# 老婆系统
# ============================================================================

def _wife_text(openid):
    wife = get_wife(openid)
    if not wife:
        return (
            "你还没设置老婆。\n"
            "发送「#老婆设置 心海,雷电将军,芙宁娜」设置。\n"
            "或单独发送「#老婆」随机分配一位。"
        )
    return (
        "【%s 老婆列表】%d 位\n  · %s\n"
        "（新增「#老婆添加 <名>」/ 删除「#老婆删除 <名>」/ 清空「#老婆清空」）" % (
            "💍" if "老婆" else "💏",
            len(wife),
            "、".join(wife),
        )
    )


def _parse_name_list(raw):
    """'心海, 雷电将军 、芙宁娜' / '心海 雷电将军 芙宁娜' 统一解析."""
    if not raw:
        return []
    parts = re.split(r"[,，、\s]+", raw)
    out = []
    seen = set()
    for p in parts:
        p = p.strip()
        if not p:
            continue
        canon = resolve_alias(p) or p
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


async def _send_random_wife_photo(ctx, openid):
    """发送一张老婆的图片: 优先已设置, 否则随机."""
    wife = get_wife(openid)
    target = random.choice(wife) if wife else pick_random_wife()
    canon = resolve_alias(target) or target
    # 优先发 character-img 下的实拍图, 找不到再发 face
    p = get_char_card_img(canon) or get_char_face_img(canon)
    if not p:
        await ctx.reply("❌ 「%s」图片资源缺失，请尝试其他角色。" % canon)
        return True
    data = _read_image_bytes(p)
    if not data:
        await ctx.reply("❌ 图片读取失败：「%s」" % canon)
        return True
    try:
        await send_local_image_for_scene(
            ctx.api, ctx.scene, ctx.target_id, data,
            content="💖 %s 的老婆照（一辈子的人就是她）" % canon,
        )
    except Exception as e:
        await ctx.reply("（老婆图片发送失败: %s）" % e)
    return True


# ============================================================================
# 帮助文本
# ============================================================================

_HELP_TEXT = (
    "【原神 · M1 聚合菜单】\n"
    "\n"
    "══════ 本地数据驱动 (无需 CK) ══════\n"
    "#今日素材           今日突破素材 + 天赋书\n"
    "#五星               五星角色图鉴 (按元素)\n"
    "#武器               五星武器图鉴 (按类型)\n"
    "#<角色>技能 / 天赋  角色天赋详情 (例 #胡桃技能)\n"
    "#<角色>命座         角色命座详情 (例 #胡桃命座)\n"
    "#<角色>图鉴         角色图片    (例 #心海图鉴)\n"
    "#<武器>图鉴         武器图片    (例 #护摩图鉴)\n"
    "#<角色>照片         角色图片    (例 #甘雨照片)\n"
    "#<角色>攻略         攻略数据    (例 #刻晴攻略)\n"
    "\n"
    "══════ 需先「原神绑定 UID」══════\n"
    "#五星列表           玩家展示 5 星角色\n"
    "#练度统计           等级分布\n"
    "#圣遗物列表         套装汇总\n"
    "#角色持有 / #角色0命  持有率\n"
    "\n"
    "══════ 老婆系统 ══════\n"
    "#老婆 / #老公       查已设置老婆\n"
    "#老婆设置 心海,雷神  设置老婆\n"
    "#老婆添加 <名>      追加\n"
    "#老婆删除 <名>      删除\n"
    "#老婆清空           清空\n"
    "#老婆照片           随机一张老婆图\n"
    "\n"
    "══════ 版本 / 帮助 ══════\n"
    "#版本 / #喵喵版本   bot 版本号\n"
    "#帮助               本菜单\n"
    "\n"
    "（所有命令必须以 # 开头，例：#胡桃技能 / #圣遗物评分 / #十连）"
)

_HELP_TEXT_NEW = _HELP_TEXT + (
    "\n"
    "══════ 抽卡 / 评分 / 伤害 (免 CK) ══════\n"
    "#十连 / #单抽        抽卡模拟 (本地, 标准概率+保底)\n"
    "#圣遗物评分          绑定角色圣遗物评分 (miao 权重)\n"
    "#伤害计算 [角色]     理论伤害估算 (node 引擎)\n"
)


_VERSION_TEXT = "小流萤 bot · 原神 M1 聚合 · 13 个本地功能已上线 · " \
                 "完整面板图请用原神主插件 (Enka)"


# ============================================================================
# 新免鉴权功能: 抽卡 / 评分 / 伤害 / 活动 辅助
# ============================================================================

def _default_char_name(raw):
    """取展示首位角色 (Enka avatarInfoList[0]) 的标准名."""
    if not isinstance(raw, dict):
        return ""
    avs = raw.get("avatarInfoList") or []
    if not avs:
        return ""
    aid = str((avs[0] or {}).get("avatarId", ""))
    return _MAPS.AVATAR_ID2NAME.get(aid, "")


async def _dispatch_gacha(ctx, count):
    """模拟抽卡并发送立绘(5★/4★) + 汇总文本."""
    res = gacha_pull(count, openid=ctx.member_openid)
    imgs = [x for x in res if x["img"]]
    sent = 0
    for x in imgs:
        if sent >= 8:  # 至多发 8 张, 避免刷屏
            break
        data = _read_image_bytes(x["img"])
        if not data:
            continue
        rarity_tag = "★5" if x["rarity"] == "5" else "★4"
        try:
            await send_local_image_for_scene(
                ctx.api, ctx.scene, ctx.target_id, data,
                content="【%s】%s" % (rarity_tag, x["name"]),
            )
            sent += 1
        except Exception as e:
            await ctx.reply("（立绘发送失败: %s）" % e)
    await ctx.reply(gacha_summary(res))


async def _send_score(ctx, render, char_name):
    ad = render.get("artisDetail") or {}
    total = ad.get("mark", "—")
    cls = ad.get("markClass", "")
    artis = ad.get("artis") or []
    piece_names = ["花", "羽", "沙", "杯", "冠"]
    lines = ["【圣遗物评分】%s" % char_name, "总分：%s（%s）" % (total, cls or "—")]
    for a in artis:
        pos = a.get("pos", 0)
        pn = piece_names[pos - 1] if 1 <= pos <= 5 else "?"
        mark = a.get("mark", 0)
        try:
            mark_f = float(mark)
        except (TypeError, ValueError):
            mark_f = 0.0
        lines.append("  %s %s：%.1f" % (pn, a.get("name", ""), mark_f))
    if not artis:
        lines.append("（该角色未公开圣遗物数据）")
    await ctx.reply("\n".join(lines))


async def _send_dmg(ctx, render, char_name):
    dc = render.get("dmgCalc") or {}
    rows = dc.get("dmgData") or []
    if not rows:
        await ctx.reply(
            "⚠️ 伤害引擎暂不可用（需 node 运行环境执行 miao_panel/dmg_calc.mjs）。\n"
            "确认运行环境已装 node 与 Yunzai 依赖后重试。"
        )
        return
    lines = ["【伤害估算】%s（娱乐向，非精确）" % char_name,
             "敌 Lv%s · %s" % (dc.get("enemyLv", 103), dc.get("enemyName", ""))]
    for r in rows:
        dmg = r.get("dmg")
        avg = r.get("avg")
        if dmg in ("NaN", None, ""):
            # 护盾/治疗等非伤害项: 用均值近似显示
            dmg_disp = ("≈%s" % avg) if (avg and avg != "—") else "—"
            avg_s = ""
        else:
            dmg_disp = str(dmg)
            avg_s = (" (均%s)" % avg) if (avg and avg != "—") else ""
        lines.append("· %s：%s%s" % (r.get("title", ""), dmg_disp, avg_s))
    await ctx.reply("\n".join(lines))


# ============================================================================
# 主分发
# ============================================================================

import random


async def handle(ctx) -> bool:
    if not ctx or not ctx.content:
        return False
    raw = (ctx.content or "").strip()
    if not raw:
        return False

    # === 原神专属帮助 (raw 形式, 不吞通用词 菜单/功能/帮助/用法) ===
    if _RAW_HELP_RE.match(raw):
        await ctx.reply(_HELP_TEXT_NEW)
        return True

    # 先统一剥前缀 (# / 原神 / ys / genshin), 命中所有命令的 cmd 形式.
    cmd = _strip_prefix(raw)
    if not cmd:
        return False

    # === 顶层: 版本 / 面板帮助 ===
    if _RE_VERSION.match(cmd):
        await ctx.reply(_VERSION_TEXT)
        return True
    if _RE_PANEL_HELP.match(cmd):
        await ctx.reply(
            "【原神面板 · 帮助】\n"
            "#原神绑定 <UID>：绑定后无需每次发 UID\n"
            "#原神 <角色名>：直查练度 (图+文本)\n"
            "#原神 <角色名> 面板 / #<角色名>面板：单角色图\n"
            "#原神 <角色名> 极限面板 / #<角色名>极限面板：理论极限图\n"
            "#更新面板 [角色名]：强制刷新\n"
            "#原神解绑 / #原神帮助\n"
            "\n"
            "M1 扩展命令请发「#帮助」查看。"
        )
        return True

    # === 老婆系统 (在 CHART_PHOTO 之前匹配) ===
    m = _RE_WIFE_SET.match(cmd)
    if m:
        names = _parse_name_list(m.group(1))
        if not names:
            await ctx.reply("⚠️ 请在「#老婆设置」后填写至少一个角色名 (标准名或别名)。")
            return True
        wife = set_wife(ctx.member_openid, names)
        await ctx.reply(
            "✅ 已设置老婆 (%d 位)：\n  · %s\n"
            "（发送「#老婆照片」随机抽一位发图）" % (len(wife), "、".join(wife))
        )
        return True
    m = _RE_WIFE_ADD.match(cmd)
    if m:
        new = _parse_name_list(m.group(1))
        if not new:
            await ctx.reply("⚠️ 请在「#老婆添加」后填写角色名。")
            return True
        wife = add_wife(ctx.member_openid, new[0])
        await ctx.reply("✅ 已添加（当前 %d 位）：\n  · %s" % (len(wife), "、".join(wife)))
        return True
    m = _RE_WIFE_RM.match(cmd)
    if m:
        names = _parse_name_list(m.group(1))
        if not names:
            await ctx.reply("⚠️ 请在「#老婆删除」后填写角色名。")
            return True
        wife = remove_wife(ctx.member_openid, names[0])
        await ctx.reply("✅ 已删除（当前 %d 位）：\n  · %s" % (len(wife), "、".join(wife) if wife else "（空）"))
        return True
    if _RE_WIFE_CLEAR.match(cmd):
        clear_wife(ctx.member_openid)
        await ctx.reply("✅ 已清空。")
        return True
    if _RE_WIFE_LIST.match(cmd):
        await ctx.reply(_wife_text(ctx.member_openid))
        return True
    if _RE_WIFE_PHOTO.match(cmd):
        return await _send_random_wife_photo(ctx, ctx.member_openid)

    # === 纯静态本地 ===
    if _RE_TODAY.match(cmd):
        await ctx.reply(today_materials_text())
        return True
    if _RE_FIVE_STAR.match(cmd):
        await ctx.reply(five_star_text("char"))
        return True
    if _RE_WEAPON.match(cmd):
        await ctx.reply(five_star_text("weapon"))
        return True

    # === 抽卡模拟 (本地, 免鉴权) ===
    if _RE_GACHA.match(cmd):
        count = 10 if "十连" in cmd else 1
        await _dispatch_gacha(ctx, count)
        return True

    # === 角色详情: 技能 / 命座 ===
    m = _RE_TALENT.match(cmd)
    if m:
        nm = m.group(1)
        mode, text = talent_or_constellation_text(nm, "talent")
        if mode is None:
            return False  # 让原神主插件接管 (角色名直接面板)
        await ctx.reply(text)
        return True
    m = _RE_CONST.match(cmd)
    if m:
        mode, text = talent_or_constellation_text(m.group(1), "constellation")
        if mode is None:
            return False
        await ctx.reply(text)
        return True
    m = _RE_GUIDE.match(cmd)
    if m:
        txt = guide_text(m.group(1))
        if txt is None:
            return False
        await ctx.reply(txt)
        return True

    # === 角色/武器图鉴 (智能鉴别: 武器 alias 优先) ===
    m = _RE_WEAPON_COLL.match(cmd) or _RE_CHAR_COLL.match(cmd)
    if m:
        await _dispatch_collection_image(ctx, m.group(1))
        return True

    m = _RE_CHAR_PHOTO.match(cmd)
    if m:
        await _dispatch_collection_image(ctx, m.group(1), photo=True)
        return True

    # === 玩家绑定 UID 后功能 ===
    if _RE_FIVE_LIST.match(cmd) or _RE_TRAIN_STATS.match(cmd) or _RE_ARTIFACT_LIST.match(cmd) or _RE_HOLD_RATE.match(cmd):
        from plugins.genshin import get_binding, query_enka, parse_enka
        uid = get_binding(ctx.member_openid)
        if not uid:
            await ctx.reply("⚠️ 请先发「原神绑定 <UID>」绑定你的 UID。")
            return True
        raw_panel, source = await query_enka(uid, use_cache=True)
        if isinstance(raw_panel, dict) and "error" in raw_panel:
            await ctx.reply("❌ " + raw_panel["error"])
            return True
        panel = parse_enka(raw_panel, uid)
        if _RE_FIVE_LIST.match(cmd):
            await ctx.reply(player_five_star_lines(panel))
            return True
        if _RE_TRAIN_STATS.match(cmd):
            await ctx.reply(player_training_stats_text(panel))
            return True
        if _RE_ARTIFACT_LIST.match(cmd):
            await ctx.reply(artifact_list_text(panel))
            return True
        if _RE_HOLD_RATE.match(cmd):
            await ctx.reply(player_zero_const_stats(panel))
            return True

    # === 圣遗物评分 / 伤害计算 (需绑定 UID, 走 Enka 公开数据, 免 cookie) ===
    md = _RE_DMG.match(cmd)
    if _RE_SCORE.match(cmd) or md:
        from plugins.genshin import get_binding, query_enka
        uid = get_binding(ctx.member_openid)
        if not uid:
            await ctx.reply("⚠️ 请先发「原神绑定 <UID>」绑定你的 UID。")
            return True
        raw_panel, source = await query_enka(uid, use_cache=True)
        if isinstance(raw_panel, dict) and "error" in raw_panel:
            await ctx.reply("❌ " + raw_panel["error"])
            return True
        char_arg = ""
        if md and md.group(1):
            char_arg = md.group(1).strip()
        detail = resolve_alias(char_arg) if char_arg else ""
        if not detail:
            detail = _default_char_name(raw_panel)
        render = build_render_data(raw_panel, uid, detail)
        if not render:
            await ctx.reply("⚠️ 未找到角色「%s」的面板数据（可能未公开或别名未收录）。"
                           % (char_arg or detail or "默认"))
            return True
        if _RE_SCORE.match(cmd):
            await _send_score(ctx, render, detail)
        else:
            await _send_dmg(ctx, render, detail)
        return True

    return False


# ============================================================================
# 图鉴分发: 武器 alias 优先, 否则角色 alias, 再走文件
# ============================================================================

async def _dispatch_collection_image(ctx, name, photo=False):
    """统一处理 #X图鉴 / #X照片. 优先尝试武器, 再尝试角色."""
    wcanon = resolve_weapon_alias(name)
    char_canon = resolve_alias(name)
    # 1) 武器
    if wcanon and not char_canon:
        # 仅当不在角色 alias 中, 才走武器路径
        wd = load_weapon()
        info = next((v for v in wd.values() if v.get("name") == wcanon), None)
        if info:
            t = info.get("type", "")
            base = os.path.normpath(os.path.join(
                os.path.dirname(__file__), "..", "lib", "genshin_panel_miao",
            ))
            # 图片从 miao 资源拿
            from lib.genshin_panel_miao.wiki_data import MIAO_RES
            imgs_dir = os.path.join(MIAO_RES, "meta-gs", "weapon", t, "imgs")
            p = None
            for ext in (".png", ".jpg", ".webp", ".jpeg"):
                cand = os.path.join(imgs_dir, wcanon + ext)
                if os.path.isfile(cand):
                    p = cand
                    break
            data = _read_image_bytes(p) if p else None
            if data:
                try:
                    await send_local_image_for_scene(
                        ctx.api, ctx.scene, ctx.target_id, data,
                        content="【%s 图鉴】" % wcanon,
                    )
                    return
                except Exception as e:
                    await ctx.reply("（武器图鉴发送失败: %s）" % e)
                    return
            await ctx.reply(
                "【%s】\n类型：%s\n星级：%d"
                % (wcanon, WEAPON_LOC.get(info.get("type", ""), info.get("type", "")), int(info.get("star", 0)))
            )
            return
    # 2) 角色 (or 武器未命中图, 退路 char)
    target = char_canon or wcanon or name
    for getter in (get_char_card_img, get_char_face_img, get_char_splash_img):
        p = getter(target)
        if p:
            data = _read_image_bytes(p)
            if data:
                try:
                    await send_local_image_for_scene(
                        ctx.api, ctx.scene, ctx.target_id, data,
                        content="【%s】" % target,
                    )
                    return
                except Exception as e:
                    await ctx.reply("（图鉴发送失败: %s）" % e)
                    return
    # 3) 文本 fallback
    if char_canon:
        mode, text = talent_or_constellation_text(name, "mixed")
        if mode:
            await ctx.reply("⚠️ 图片资源缺失, 以下为该角色文本详情:\n\n" + text)
            return
    await ctx.reply("⚠️ 未找到「%s」图鉴资源 (角色/武器皆未命中)。" % name)


# Weapon type chinese label (cache)
WEAPON_LOC = {"sword": "单手剑", "claymore": "双手剑", "polearm": "长柄武器",
              "catalyst": "法器", "bow": "弓"}
