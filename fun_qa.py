# -*- coding: utf-8 -*-
"""
外置插件：趣味问答
功能：脑筋急转弯 / 猜谜语
数据源：接口盒子 apihz.cn

答题交互：
- 只发题目，不显示答案；
- 题目下方按钮：答案 / 跳过；
- 作答指令带功能前缀，避免多答题功能冲突：
  · 脑筋急转弯：脑筋作答 / 脑筋答案 / 脑筋跳过 / 脑筋下一题
  · 猜谜语：谜语作答 / 谜语答案 / 谜语跳过 / 谜语下一题
- 作答后：回答正确显示答案 + [答案][下一题]；
  回答错误仅提示错误 + [答案][下一题]，不直接泄露答案；
- 答案/跳过按钮：显示当前题答案 + 发送下一题；
- 下一题按钮：直接发送下一题（不显示答案）。
"""

import json
import re
import time
import urllib.parse
import urllib.request

PLUGIN = {
    "key": "fun_qa",
    "name": "趣味问答",
    "priority": 500,
    "description": "发送「脑筋急转弯」或「猜谜语」随机抽取一条趣味问答（作答模式）",
    "category": "entertainment",
}

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ============ 自包含依赖（独立运行无需主项目框架）============
import logging as _qa_log

_QA_LOG = _qa_log.getLogger("fun_qa")
logger = _QA_LOG
ChatScene = type("ChatScene", (), {"GROUP": "group", "C2C": "c2c", "CHANNEL": "channel"})()

# 问答会话（内联自 modules.qa_common，单会话 per(chat,qtype) + 2分钟超时）
_QA_LABEL = {"brain": "脑筋急转弯", "riddle": "猜谜语"}


def _clean(s, limit=0):
    s = re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def _normalize(s):
    s = (s or "").strip()
    s = re.sub(r"^(答案|答|谜底|正确|正确答案)[:：]\s*", "", s)
    return s.strip()


def _is_correct(user, correct):
    u = _normalize(user)
    c = _normalize(correct)
    if not u or not c:
        return False
    u = re.sub(r"[\s，。！？、；：\"\"''（）()\[\]【】]", "", u).lower()
    c = re.sub(r"[\s，。！？、；：\"\"''（）()\[\]【】]", "", c).lower()
    if not u or not c:
        return False
    return u == c or c in u or u in c


def _btn(label, command):
    return {
        "id": "btn_funqa_" + command,
        "render_data": {"label": label, "visited_label": label, "style": 1},
        "action": {"type": 2, "permission": {"type": 2}, "data": command, "enter": True, "unsupport_tips": "请更新QQ版本"},
    }


def _kbd(*pairs):
    return {"content": {"rows": [{"buttons": [_btn(l, d) for l, d in pairs]}]}}


def _cmd_prefix(qtype):
    return {"brain": "脑筋", "riddle": "谜语"}.get(qtype, "")


async def _send_kb(ctx, text, pairs):
    from modules.common import send_text_with_keyboard
    try:
        await send_text_with_keyboard(ctx.api, ctx.scene, ctx.target_id, text, _kbd(*pairs), msg_id=ctx.msg_id, event_id=ctx.event_id)
    except Exception as e:
        pass  # logger 为模块级
        logger.error("[趣味问答] 发送键盘失败: %s" % e)
        await ctx.reply(text)


async def handle(ctx) -> bool:
    content = (ctx.content or "").strip()
    target_id = ctx.target_id or ctx.member_openid
    scene = getattr(ctx, "scene", None) or ChatScene.GROUP
    is_group = (scene == ChatScene.GROUP)

    # ---------- 答题交互（仅在有会话时拦截） ----------
    exact_map = {
        "脑筋答案": "brain", "谜语答案": "riddle",
        "脑筋跳过": "brain", "谜语跳过": "riddle",
        "脑筋下一题": "brain", "谜语下一题": "riddle",
    }
    submit_map = {"脑筋作答": "brain", "谜语作答": "riddle"}
    if content in exact_map:
        qtype = exact_map[content]
        if not qa_is_active(target_id, qtype):
            return False
        if is_group and not qa_is_owner(target_id, qtype, ctx.member_openid):
            return True  # 非发起者的按钮/指令忽略
        if content.endswith("答案"):
            return await _on_answer_btn(ctx, qtype)
        if content.endswith("跳过"):
            return await _on_skip_btn(ctx, qtype)
        return await _on_next_btn(ctx, qtype)
    for pfx, qtype in submit_map.items():
        if content.startswith(pfx):
            return await _on_submit(ctx, qtype, content[len(pfx):].strip())

    # ---------- 功能入口 ----------
    if content in ("脑筋急转弯", "急转弯"):
        qtype = "brain"
    elif content in ("猜谜语", "谜语", "猜谜"):
        qtype = "riddle"
    else:
        return False

    try:
        from console_server import is_feature_enabled, is_sub_feature_enabled
        if not is_feature_enabled("game", appid=ctx.bot_appid):
            return False
        sub_key = "game_brain_teaser" if qtype == "brain" else "game_riddle"
        if not is_sub_feature_enabled(sub_key, appid=ctx.bot_appid):
            return False
    except Exception:
        pass

    await _begin_qa(ctx, qtype)
    return True


async def _begin_qa(ctx, qtype):
    """入口：若该功能正在进行中则提示，否则开新题或继续当前轮。"""
    target_id = ctx.target_id or ctx.member_openid
    scene = getattr(ctx, "scene", None) or ChatScene.GROUP
    if qa_is_active(target_id, qtype):
        owner = qa_owner_openid(target_id, qtype)
        label = _QA_LABEL.get(qtype, "")
        await qa_send(ctx.api, scene, target_id, "🔔 %s正在进行中，请先完成当前作答～" % label,
                      mention_openid=(owner if scene == ChatScene.GROUP else None),
                      msg_id=ctx.msg_id, event_id=ctx.event_id)
        return
    await _ask_qa(ctx, qtype)


# ================================================================
#                        出题 / 答题
# ================================================================
async def _ask_qa(ctx, qtype):
    target_id = ctx.target_id or ctx.member_openid
    scene = getattr(ctx, "scene", None) or ChatScene.GROUP
    try:
        try:
            from modules import config
            api_id = getattr(config, "APIHZ_TQ_ID", "")
            api_key = getattr(config, "APIHZ_TQ_KEY", "")
        except Exception:
            api_id, api_key = "", ""
        if not api_id or not api_key:
            await ctx.reply("趣味问答功能未配置接口凭据，请联系管理员～")
            return

        path = "/api/zici/jizhuanwan.php" if qtype == "brain" else "/api/zici/miyu.php"
        params = {"id": api_id, "key": api_key}
        url = "https://cn.apihz.cn%s?%s" % (path, urllib.parse.urlencode(params))
        req = urllib.request.Request(url, headers={"User-Agent": _UA}, method="GET")
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        if data.get("code") != 200:
            await ctx.reply("趣味问答暂时不可用，稍后再试～")
            return

        if qtype == "brain":
            title = _clean(data.get("title"), 400)
            daan = _clean(data.get("daan"), 400)
            question = "🧠 脑筋急转弯\n━━━━━━━━━━\n%s" % title
        else:
            mimian = _clean(data.get("mimian"), 400)
            tishi = _clean(data.get("tishi"), 200)
            midi = _clean(data.get("midi"), 200)
            mtype = _clean(data.get("type"), 100)
            question = "🎭 猜谜语"
            if mtype:
                question += "（%s）" % mtype
            question += "\n━━━━━━━━━━\n谜面：%s" % mimian
            if tishi:
                question += "\n提示：%s" % tishi
            daan = midi

        pfx = _cmd_prefix(qtype)
        # 开新题或继续当前轮（下一题/答案/跳过复用同一会话）
        if qa_is_active(target_id, qtype):
            qa_continue(target_id, qtype, {"answer": daan})
        else:
            qa_start(target_id, qtype, ctx.member_openid, scene, ctx.api,
                     _QA_LABEL.get(qtype, ""), {"answer": daan})
        await _send_kb(ctx, question + "\n\n💬 发送「%s作答 你的答案」来作答" % pfx,
                       (("💡 答案", "%s答案" % pfx), ("⏭ 跳过", "%s跳过" % pfx)))
    except Exception as e:
        pass  # logger 为模块级
        logger.error("[趣味问答] 处理异常: %s" % e)
        await ctx.reply("趣味问答暂时不可用，稍后再试～")


async def _on_submit(ctx, qtype, user_ans):
    target_id = ctx.target_id or ctx.member_openid
    scene = getattr(ctx, "scene", None) or ChatScene.GROUP
    sess = qa_get(target_id, qtype)
    if not sess:
        return False
    if scene == ChatScene.GROUP and not qa_is_owner(target_id, qtype, ctx.member_openid):
        return True  # 非发起者的作答指令忽略
    pfx = _cmd_prefix(qtype)
    if not user_ans:
        await qa_send(ctx.api, scene, target_id, "💬 请发送：%s作答 你的答案" % pfx,
                      msg_id=ctx.msg_id, event_id=ctx.event_id)
        return True
    qa_touch(target_id, qtype)
    correct = _is_correct(user_ans, sess["data"].get("answer", ""))
    if correct:
        msg = "✅ 回答正确！"
        if sess["data"].get("answer"):
            msg += "\n💡 答案：%s" % sess["data"]["answer"]
        pairs = (("⏭ 下一题", "%s下一题" % pfx),)  # 答对不再发「答案」按钮
    else:
        msg = "❌ 回答错误！"
        pairs = (("💡 答案", "%s答案" % pfx), ("⏭ 下一题", "%s下一题" % pfx))
    await qa_send_kb(ctx.api, scene, target_id, msg, pairs,
                    mention_openid=(ctx.member_openid if scene == ChatScene.GROUP else None),
                    msg_id=ctx.msg_id, event_id=ctx.event_id)
    return True


async def _on_answer_btn(ctx, qtype):
    target_id = ctx.target_id or ctx.member_openid
    sess = qa_get(target_id, qtype)
    if not sess:
        return False
    qa_touch(target_id, qtype)
    await _reveal_and_next(ctx, qtype)
    return True


async def _on_skip_btn(ctx, qtype):
    target_id = ctx.target_id or ctx.member_openid
    sess = qa_get(target_id, qtype)
    if not sess:
        return False
    qa_touch(target_id, qtype)
    await _reveal_and_next(ctx, qtype)
    return True


async def _on_next_btn(ctx, qtype):
    target_id = ctx.target_id or ctx.member_openid
    sess = qa_get(target_id, qtype)
    if not sess:
        return False
    qa_touch(target_id, qtype)
    await _ask_qa(ctx, qtype)
    return True


async def _reveal_and_next(ctx, qtype):
    target_id = ctx.target_id or ctx.member_openid
    sess = qa_get(target_id, qtype)
    if not sess:
        return
    if sess["data"].get("answer"):
        await ctx.reply("💡 答案：%s" % sess["data"]["answer"])
    await _ask_qa(ctx, qtype)

# ============ 自包含发送辅助（仅依赖 botpy SDK，独立运行无需主项目）============

import time as _qa_tm

_QA_SEND_SEQ = {"n": 0}


def _qa_send_seq() -> int:
    _QA_SEND_SEQ["n"] += 1
    return int(_qa_tm.time() * 1000) % 1000000000 + _QA_SEND_SEQ["n"]


def _qa_route(scene: str, chat_id: str):
    """按场景返回 (路径模板, 路径参数)。"""
    from botpy.http import Route
    sc = (scene or "").lower()
    if sc == "c2c":
        return Route("POST", "/v2/users/{openid}/messages", openid=chat_id), sc
    return Route("POST", "/v2/groups/{group_openid}/messages", group_openid=chat_id), sc


async def send_text(api, scene, chat_id, text, msg_id=None, event_id=None):
    """自包含纯文本发送（msg_type=0）。"""
    route, sc = _qa_route(scene, chat_id)
    payload = {"msg_type": 0, "content": text or "", "msg_seq": _qa_send_seq()}
    if sc == "c2c":
        if msg_id:
            payload["msg_id"] = msg_id
        return await api._http.request(route, json=payload)
    payload["group_openid"] = chat_id
    if msg_id:
        payload["msg_id"] = msg_id
    return await api._http.request(route, json=payload)


async def send_text_with_keyboard(api, scene, chat_id, text, keyboard, msg_id=None, event_id=None):
    """自包含文本+按钮发送（msg_type=2）。"""
    route, sc = _qa_route(scene, chat_id)
    payload = {
        "msg_type": 2,
        "content": text or "",
        "markdown": {"content": text or ""},
        "msg_seq": _qa_send_seq(),
        "keyboard": keyboard,
    }
    if sc == "c2c":
        if msg_id:
            payload["msg_id"] = msg_id
        return await api._http.request(route, json=payload)
    payload["group_openid"] = chat_id
    if msg_id:
        payload["msg_id"] = msg_id
    return await api._http.request(route, json=payload)


async def send_group_markdown(api, chat_id, content, msg_id=None, event_id=None):
    """自包含 markdown 降级：纯文本发送（独立运行不支持 markdown，文本兜底）。"""
    return await send_text(api, "group", chat_id, content, msg_id=msg_id, event_id=event_id)


# -*- coding: utf-8 -*-
# (chat_id, qtype) -> 会话 dict
#   owner : 发起者 openid
#   scene : ChatScene.GROUP / C2C / CHANNEL
#   api   : botpy client 引用（用于超时主动发消息）
#   label : 功能展示名（如 小学数学 / 猜成语）
#   data  : 各模块私有数据（题目/答案/解析等）
#   ts    : 最近活动时间戳（用于超时判定的重置）
#   task  : 超时等待任务
_QA = {}
_QA_TIMEOUT = 120  # 秒


def _key(chat_id, qtype):
    return (chat_id, qtype)


# ================================================================
#                        查询 / 归属
# ================================================================
def qa_is_active(chat_id, qtype):
    return _key(chat_id, qtype) in _QA


def qa_get(chat_id, qtype):
    return _QA.get(_key(chat_id, qtype))


def qa_owner_openid(chat_id, qtype):
    s = _QA.get(_key(chat_id, qtype))
    return s.get("owner") if s else None


def qa_is_owner(chat_id, qtype, openid):
    s = _QA.get(_key(chat_id, qtype))
    return bool(s) and s.get("owner") == openid


def qa_label(chat_id, qtype):
    s = _QA.get(_key(chat_id, qtype))
    return s.get("label") if s else ""


# ================================================================
#                        生命周期
# ================================================================
def qa_start(chat_id, qtype, owner, scene, api, label, data, on_timeout=None):
    """尝试开启新会话。返回 True 成功；False 表示已有进行中会话（调用方应提示进行中）。

    on_timeout: 可选 async 回调，超时触发时调用（用于清除对应游戏/状态）。
    """
    key = _key(chat_id, qtype)
    if key in _QA:
        return False
    _QA[key] = {
        "owner": owner,
        "scene": scene,
        "api": api,
        "label": label,
        "data": data or {},
        "ts": time.time(),
        "task": None,
        "on_timeout": on_timeout,
    }
    _qa_arm(chat_id, qtype)
    return True


def qa_continue(chat_id, qtype, data):
    """更新已有会话的题目数据并重置计时（用于「下一题/答案/跳过」继续当前轮）。"""
    s = _QA.get(_key(chat_id, qtype))
    if not s:
        return False
    s["data"] = data or {}
    s["ts"] = time.time()
    _qa_arm(chat_id, qtype)
    return True


def qa_touch(chat_id, qtype):
    """仅重置时间戳与计时（用于用户作答等互动，题目不变）。"""
    s = _QA.get(_key(chat_id, qtype))
    if s:
        s["ts"] = time.time()
        _qa_arm(chat_id, qtype)


def qa_end(chat_id, qtype):
    key = _key(chat_id, qtype)
    s = _QA.pop(key, None)
    if s and s.get("task"):
        try:
            s["task"].cancel()
        except Exception:
            pass


def _qa_arm(chat_id, qtype):
    s = _QA.get(_key(chat_id, qtype))
    if not s:
        return
    if s.get("task"):
        try:
            s["task"].cancel()
        except Exception:
            pass
    try:
        loop = asyncio.get_event_loop()
        s["task"] = loop.create_task(_qa_timeout(chat_id, qtype))
    except Exception as e:
        logger.error("[QA] 创建超时任务失败: %s" % e)


async def _qa_timeout(chat_id, qtype):
    await asyncio.sleep(_QA_TIMEOUT)
    s = _QA.get(_key(chat_id, qtype))
    if not s:
        return
    # 期间若有互动，ts 会被刷新，跳过本次超时（已由新计时器接管）
    if time.time() - s.get("ts", 0) < _QA_TIMEOUT:
        return
    owner = s.get("owner")
    scene = s.get("scene")
    api = s.get("api")
    label = s.get("label", "")
    on_timeout = s.get("on_timeout")
    try:
        if scene == ChatScene.GROUP and owner:
            await send_group_markdown(
                api, chat_id, "<@!%s> %s作答超时已自动结束～" % (owner, label)
            )
        else:
            await send_text(api, scene, chat_id, "%s作答超时已自动结束～" % label)
    except Exception as e:
        logger.error("[QA] 超时消息发送失败: %s" % e)
    # 游戏/状态自定义清理（如清除棋局、成语局等）
    if on_timeout:
        try:
            await on_timeout(api, scene, chat_id, label, owner)
        except Exception as e:
            logger.error("[QA] 超时回调执行失败: %s" % e)
    _QA.pop(_key(chat_id, qtype), None)


# ================================================================
#                        @ 与发送助手
# ================================================================
def qa_mention(scene, openid):
    if scene == ChatScene.GROUP and openid:
        return "<@!%s> " % openid
    return ""


async def qa_send(api, scene, chat_id, text, mention_openid=None, msg_id=None, event_id=None):
    """发送一条普通消息，群聊可带 @。"""
    if scene == ChatScene.GROUP and mention_openid:
        await send_group_markdown(
            api, chat_id, "%s%s" % (qa_mention(scene, mention_openid), text),
            msg_id=msg_id, event_id=event_id,
        )
    else:
        await send_text(api, scene, chat_id, text, msg_id=msg_id, event_id=event_id)


async def qa_send_kb(api, scene, chat_id, text, pairs, mention_openid=None, msg_id=None, event_id=None):
    """发送带按钮的消息；群聊内容可带 @（markdown 内联 <@!openid>）。"""
    content = "%s%s" % (qa_mention(scene, mention_openid), text)
    kb = {
        "content": {
            "rows": [
                {
                    "buttons": [
                        {
                            "id": "btn_qa_" + d,
                            "render_data": {"label": l, "visited_label": l, "style": 1},
                            "action": {
                                "type": 2,
                                "permission": {"type": 2},
                                "data": d,
                                "enter": True,
                                "unsupport_tips": "请更新QQ版本",
                            },
                        }
                        for l, d in pairs
                    ]
                }
            ]
        }
    }
    try:
        await send_text_with_keyboard(api, scene, chat_id, content, kb, msg_id=msg_id, event_id=event_id)
    except Exception as e:
        logger.error("[QA] 发送键盘失败: %s" % e)
        await send_text(api, scene, chat_id, content, msg_id=msg_id, event_id=event_id)
