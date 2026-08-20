# -*- coding: utf-8 -*-
"""
趣味问答 - 猜谜语（独立插件）

触发指令：
  开题：猜谜语 / 谜语 / miyu / riddle
  作答：直接发答案文本；或前缀"谜底" / "答案" / "答"
  换题：fun_riddle 换一题
  看答案：fun_riddle 看答案
  结束：fun_riddle 结束
"""
import json
import logging
import re
import urllib.request

from modules.qa_common import (
    _is_correct,
    ChatScene,
    logger,
    qa_continue,
    qa_end,
    qa_get,
    qa_is_active,
    qa_is_owner,
    qa_send,
    qa_send_kb,
    qa_start,
    qa_touch,
)

QTYPE = "riddle"
LABEL = "猜谜语"
API_LIST = "https://v.api.aa1.cn/api/miyu/index.php?type=txt"
API_TIMEOUT = 8

PLUGIN = {
    "key": "game_riddle",
    "name": "猜谜语",
    "priority": 200,
    "description": "发送「猜谜语」随机抽取一条谜语，输入谜底即可作答（超时 120s）",
    "category": "game",
    "config_schema": [
        {"key": "riddle_timeout_seconds", "type": "int", "default": 120, "label": "答题超时（秒）", "min": 30, "max": 600},
        {"key": "riddle_show_category", "type": "bool", "default": True, "label": "是否显示谜语分类"},
        {"key": "riddle_difficulty", "type": "select", "default": "all",
         "label": "难度筛选", "options": ["all", "easy", "medium", "hard"]},
    ],
}

# 开题触发词
TRIGGERS = ("猜谜语", "谜语", "miyu", "riddle")
# 谜底前缀
ANSWER_PREFIXES = ("谜底", "答案", "答")


# ============================================================
#                        拉取题目
# ============================================================
def _fetch_one():
    try:
        req = urllib.request.Request(API_LIST, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as r:
            raw = r.read().decode("utf-8", errors="replace")
        if "=" in raw and not raw.lstrip().startswith(("{", "[")):
            body = raw.split("=", 1)[1].strip()
        else:
            body = raw
        items = json.loads(body)
        if not isinstance(items, list):
            items = [items]
        for it in items:
            if not isinstance(it, dict):
                continue
            q = (it.get("title") or it.get("question") or it.get("问题") or it.get("content") or it.get("谜面") or "").strip()
            a = (it.get("answer") or it.get("答案") or it.get("ans") or it.get("谜底") or "").strip()
            cat = (it.get("category") or it.get("分类") or "").strip()
            q = re.sub(r"<[^>]+>", "", q).replace("&nbsp;", " ").strip()
            a = re.sub(r"<[^>]+>", "", a).replace("&nbsp;", " ").strip()
            if q and a:
                return {"question": q, "answer": a, "category": cat}
    except Exception as e:
        logger.error("[fun_riddle] 拉取失败: %s" % e)
    return None


# ============================================================
#                        命令
# ============================================================
async def cmd_start(api, scene, chat_id, owner, msg_id=None, event_id=None):
    item = _fetch_one()
    if not item:
        await qa_send(api, scene, chat_id,
                       "%s开题失败，请稍后再试～" % LABEL,
                       mention_openid=owner, msg_id=msg_id, event_id=event_id)
        return
    started = qa_start(chat_id, QTYPE, owner, scene, api, LABEL, item)
    if not started:
        await qa_send(api, scene, chat_id,
                       "当前已经有 %s 题目在进行了，请先作答或等待超时～" % LABEL,
                       mention_openid=owner, msg_id=msg_id, event_id=event_id)
        return
    cat_line = "🏷 <b>分类</b>：%s\n\n" % item["category"] if item.get("category") else ""
    text = "🔮 <b>%s</b>\n\n%s<b>谜面</b>：%s\n\n📝 直接输入谜底（120 秒内有效，超时自动结束）" % (
        LABEL, cat_line, item["question"])
    pairs = (
        ("换一个", "fun_riddle 换一题"),
        ("看谜底", "fun_riddle 看答案"),
        ("结束", "fun_riddle 结束"),
    )
    await qa_send_kb(api, scene, chat_id, text, pairs,
                     mention_openid=owner, msg_id=msg_id, event_id=event_id,
                     btn_prefix="riddle")


async def cmd_next(api, scene, chat_id, owner, msg_id=None, event_id=None):
    item = _fetch_one()
    if not item:
        await qa_send(api, scene, chat_id,
                       "%s换题失败，请稍后再试～" % LABEL,
                       mention_openid=owner, msg_id=msg_id, event_id=event_id)
        return
    if not qa_is_active(chat_id, QTYPE):
        await cmd_start(api, scene, chat_id, owner, msg_id=msg_id, event_id=event_id)
        return
    qa_continue(chat_id, QTYPE, item)
    cat_line = "🏷 <b>分类</b>：%s\n\n" % item["category"] if item.get("category") else ""
    text = "🔮 <b>%s</b> · 已换题\n\n%s<b>新谜面</b>：%s\n\n📝 直接输入谜底（120 秒内有效）" % (
        LABEL, cat_line, item["question"])
    pairs = (
        ("换一个", "fun_riddle 换一题"),
        ("看谜底", "fun_riddle 看答案"),
        ("结束", "fun_riddle 结束"),
    )
    await qa_send_kb(api, scene, chat_id, text, pairs,
                     mention_openid=owner, msg_id=msg_id, event_id=event_id,
                     btn_prefix="riddle")


async def cmd_show(api, scene, chat_id, owner, msg_id=None, event_id=None):
    s = qa_get(chat_id, QTYPE)
    if not s:
        await qa_send(api, scene, chat_id,
                       "当前没有进行中的 %s题目～" % LABEL,
                       mention_openid=owner, msg_id=msg_id, event_id=event_id)
        return
    ans = s.get("data", {}).get("answer", "（无）")
    text = "🔍 <b>%s 谜底</b>：%s\n\n本题已自动结束～" % (LABEL, ans)
    qa_end(chat_id, QTYPE)
    await qa_send(api, scene, chat_id, text,
                  mention_openid=owner, msg_id=msg_id, event_id=event_id)


async def cmd_end(api, scene, chat_id, owner, msg_id=None, event_id=None):
    qa_end(chat_id, QTYPE)
    await qa_send(api, scene, chat_id, "已结束 %s 题目～" % LABEL,
                  mention_openid=owner, msg_id=msg_id, event_id=event_id)


async def cmd_answer(api, scene, chat_id, owner, answer_text,
                     msg_id=None, event_id=None):
    s = qa_get(chat_id, QTYPE)
    if not s:
        return False
    if not qa_is_owner(chat_id, QTYPE, owner):
        return False
    ans = s.get("data", {}).get("answer", "")
    if not ans:
        return False
    if _is_correct(answer_text, ans):
        qa_touch(chat_id, QTYPE)
        text = "🎉 恭喜，谜底正确！\n\n<b>谜底</b>：%s\n\n题库已自动结束～" % ans
        qa_end(chat_id, QTYPE)
        await qa_send(api, scene, chat_id, text,
                      mention_openid=owner, msg_id=msg_id, event_id=event_id)
        return True
    text = "❌ 谜底不对，再想想～\n\n💡 可点「看谜底」或「换一个」"
    pairs = (
        ("换一个", "fun_riddle 换一题"),
        ("看谜底", "fun_riddle 看答案"),
        ("结束", "fun_riddle 结束"),
    )
    qa_touch(chat_id, QTYPE)
    await qa_send_kb(api, scene, chat_id, text, pairs,
                     mention_openid=owner, msg_id=msg_id, event_id=event_id,
                     btn_prefix="riddle")
    return True


# ============================================================
#                        触发器
# ============================================================
def is_start(text):
    t = (text or "").strip()
    return t in TRIGGERS


def is_command(text):
    t = (text or "").strip()
    return t.startswith("fun_riddle ")


def parse_command(text):
    """'fun_riddle 换一题' -> 'next' / 'show' / 'end'"""
    t = (text or "").strip()
    if not t.startswith("fun_riddle "):
        return None
    arg = t[len("fun_riddle "):].strip()
    if arg in ("换一题", "换一个", "next"):
        return "next"
    if arg in ("看答案", "看谜底", "show", "答案", "谜底"):
        return "show"
    if arg in ("结束", "end", "退出"):
        return "end"
    if arg in ("开题", "start", "再来一题"):
        return "start"
    return None


def extract_answer(text):
    """'谜底 X' / '答案 X' / '答 X' -> 'X'；否则 None。"""
    t = (text or "").strip()
    for p in ANSWER_PREFIXES:
        if t.startswith(p) and t != p:
            rest = t[len(p):].lstrip(" :：,，")
            if rest:
                return rest
    return None


async def handle(ctx):
    """插件主入口（PLUGIN 注册时会被包装为 dispatch）。"""
    try:
        scene = ctx.scene
        if hasattr(scene, "value"):
            scene = scene.value
        if scene == "group":
            chat_id = getattr(ctx, "group_openid", None) or getattr(ctx, "chat_id", None)
        elif scene == "c2c":
            chat_id = getattr(ctx, "openid", None) or getattr(ctx, "chat_id", None)
        else:
            chat_id = getattr(ctx, "chat_id", None)
        owner = getattr(ctx, "author_openid", None) or getattr(ctx, "openid", None) or getattr(ctx, "user_id", None) or "user"
        text = (getattr(ctx, "content", "") or "").strip()
        msg_id = getattr(ctx, "msg_id", None) or getattr(ctx, "message_id", None)
        event_id = getattr(ctx, "event_id", None)
        api = getattr(ctx, "api", None) or getattr(ctx, "bot", None)

        # 1. 走「fun_riddle 换一题/看答案/结束/开题」命令（来自按钮回调）
        cmd = parse_command(text)
        if cmd == "start":
            await cmd_start(api, scene, chat_id, owner, msg_id=msg_id, event_id=event_id)
            return True
        if cmd == "next":
            await cmd_next(api, scene, chat_id, owner, msg_id=msg_id, event_id=event_id)
            return True
        if cmd == "show":
            await cmd_show(api, scene, chat_id, owner, msg_id=msg_id, event_id=event_id)
            return True
        if cmd == "end":
            await cmd_end(api, scene, chat_id, owner, msg_id=msg_id, event_id=event_id)
            return True

        # 2. 检查是不是进行中题目的"答题"（owner 才能作答）
        if qa_is_active(chat_id, QTYPE):
            # 2a. 作答前缀（"谜底 X" / "答案 X" / "答 X"）
            ans = extract_answer(text)
            if ans and qa_is_owner(chat_id, QTYPE, owner):
                await cmd_answer(api, scene, chat_id, owner, ans, msg_id=msg_id, event_id=event_id)
                return True
            # 2b. 如果是开题触发词（"猜谜语"），当作"换一题"
            if is_start(text) and qa_is_owner(chat_id, QTYPE, owner):
                await cmd_next(api, scene, chat_id, owner, msg_id=msg_id, event_id=event_id)
                return True
            # 2c. 兜底：如果 owner 直接发了短文本（非命令词），也作为答案尝试
            if text and qa_is_owner(chat_id, QTYPE, owner) and len(text) <= 50:
                if not text.startswith("fun_") and not any(t in text for t in ("猜谜语", "谜语", "miyu", "riddle")):
                    await cmd_answer(api, scene, chat_id, owner, text, msg_id=msg_id, event_id=event_id)
                    return True

        # 3. 全新开题
        if is_start(text):
            await cmd_start(api, scene, chat_id, owner, msg_id=msg_id, event_id=event_id)
            return True

        return False
    except Exception as e:
        logger.error("[fun_riddle] handle 异常: %s" % e)
        return False
