# -*- coding: utf-8 -*-
"""
学习系统模块（新版）
功能：知识问答 / 驾考学习 / 小学数学 / 古诗文查询
数据源：接口盒子 apihz.cn（与天气查询共用同一账户 id/key）

答题交互（知识问答 / 驾考学习 / 小学数学）：
- 只发题目，不显示答案；
- 题目下方按钮：答案 / 跳过；
- 作答指令带功能前缀，避免多答题功能冲突：
  · 知识问答：常识作答 / 常识答案 / 常识跳过 / 常识下一题
  · 驾考学习：驾考作答 / 驾考答案 / 驾考跳过 / 驾考下一题
  · 小学数学：数学作答 / 数学答案 / 数学跳过 / 数学下一题
- 作答后：回答正确显示答案（驾考/小学数学含解析）+ [答案][下一题]；
  回答错误仅提示错误 + [答案][下一题]，不直接泄露答案；
- 答案/跳过按钮：显示当前题答案（驾考/小学数学含解析）+ 发送下一题；
- 下一题按钮：直接发送下一题（不显示答案）。
"""

import json
import random
import re
import time
import urllib.parse
import urllib.request
from modules.common import send_text, send_text_with_keyboard, logger, ChatScene
from modules import config
from modules.qa_common import (
    qa_start, qa_continue, qa_touch, qa_end, qa_is_active, qa_is_owner,
    qa_owner_openid, qa_send, qa_send_kb,
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 问答会话统一交由 modules.qa_common 管理（单会话 per(chat,qtype) + 2分钟超时）
# qtype -> 功能展示名
_QA_LABEL = {"quiz_common": "知识问答", "quiz_driving": "驾考学习", "quiz_math": "小学数学"}
# qtype -> 作答前缀
_QA_PREFIX = {"quiz_common": "常识", "quiz_driving": "驾考", "quiz_math": "数学"}


def _strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def _clean_text(s, limit=0):
    s = _strip_html(s)
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def _normalize_answer(s):
    s = (s or "").strip()
    s = re.sub(r"^(答案|答|谜底|正确|正确答案)[:：]\s*", "", s)
    return s.strip()


def _is_answer_correct(user_ans, correct_ans, qtype="text"):
    """判分：驾考按字母集合比较；文字题去标点空白后完全匹配或互相包含（容错）。"""
    user = _normalize_answer(user_ans)
    correct = _normalize_answer(correct_ans)
    if not user or not correct:
        return False
    if qtype == "driving":
        u = re.sub(r"[^A-Da-d]", "", user).upper()
        c = re.sub(r"[^A-Da-d]", "", correct).upper()
        return set(u) == set(c) and len(u) > 0
    u = re.sub(r"[\s，。！？、；：\"\"''（）()\[\]【】]", "", user).lower()
    c = re.sub(r"[\s，。！？、；：\"\"''（）()\[\]【】]", "", correct).lower()
    if not u or not c:
        return False
    return u == c or c in u or u in c


class StudyManager:
    """学习系统：知识问答、驾考学习、古诗文查询"""

    def __init__(self):
        pass

    # ================================================================
    #                        apihz 通用调用
    # ================================================================
    @staticmethod
    def _call_apihz(path, extra_params=None):
        api_id = getattr(config, "APIHZ_TQ_ID", "")
        api_key = getattr(config, "APIHZ_TQ_KEY", "")
        if not api_id or not api_key:
            return False, None
        params = {"id": api_id, "key": api_key}
        if extra_params:
            params.update(extra_params)
        url = "https://cn.apihz.cn%s?%s" % (path, urllib.parse.urlencode(params))
        headers = {"User-Agent": _UA}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            if data.get("code") == 200:
                return True, data
            return False, data
        except Exception as e:
            logger.error("[学习] apihz 请求异常 %s: %s" % (path, e))
            return False, None

    # ================================================================
    #                        入口分发
    # ================================================================
    async def handle_command(self, api, content, group_openid, member_openid, msg_id, scene=None):
        if scene is None:
            scene = ChatScene.GROUP
        text = (content or "").strip()
        target_id = group_openid or member_openid

        # ---------- 答题交互指令（有会话才拦截，否则放行给其它插件/AI） ----------
        # 命令 -> qtype 映射（常识/驾考/数学 三套独立前缀，避免多答题功能冲突）
        exact_map = {
            "常识答案": "quiz_common", "驾考答案": "quiz_driving", "数学答案": "quiz_math",
            "常识跳过": "quiz_common", "驾考跳过": "quiz_driving", "数学跳过": "quiz_math",
            "常识下一题": "quiz_common", "驾考下一题": "quiz_driving", "数学下一题": "quiz_math",
        }
        submit_map = {
            "常识作答": "quiz_common", "驾考作答": "quiz_driving", "数学作答": "quiz_math",
        }
        if text in exact_map:
            qtype = exact_map[text]
            if not qa_is_active(target_id, qtype):
                return False
            if scene == ChatScene.GROUP and not qa_is_owner(target_id, qtype, member_openid):
                return True  # 非发起者的按钮/指令直接忽略，避免误触他人答题
            if text.endswith("答案"):
                return await self._on_answer_btn(api, scene, target_id, member_openid, msg_id, qtype)
            if text.endswith("跳过"):
                return await self._on_skip_btn(api, scene, target_id, member_openid, msg_id, qtype)
            return await self._on_next_btn(api, scene, target_id, member_openid, msg_id, qtype)
        for pfx, qtype in submit_map.items():
            if text.startswith(pfx):
                return await self._on_submit(api, scene, target_id, member_openid, msg_id, qtype, text[len(pfx):].strip())

        # ---------- 功能入口 ----------
        if text == "学习菜单":
            await self._send_menu(api, scene, target_id, msg_id)
            return True

        entry_map = {
            "知识问答": "quiz_common", "常识": "quiz_common", "问答": "quiz_common",
            "驾考": "quiz_driving", "驾考学习": "quiz_driving", "考驾照": "quiz_driving",
            "小学数学": "quiz_math", "数学题": "quiz_math", "数学": "quiz_math",
        }
        if text in entry_map:
            await self._begin_quiz(api, scene, target_id, member_openid, msg_id, entry_map[text])
            return True

        if text in ("古诗文", "古诗", "诗词"):
            await send_text(api, scene, target_id,
                "📜 古诗文查询\n━━━━━━━━━━\n用法：古诗文 关键词\n示例：古诗文 李白 / 古诗文 静夜思",
                msg_id=msg_id)
            return True

        if text.startswith("古诗文 ") or text.startswith("古诗 ") or text.startswith("诗词 "):
            prefix = text.split()[0]
            word = text[len(prefix):].strip()
            if word:
                await self._query_poetry(api, scene, target_id, msg_id, word)
            else:
                await send_text(api, scene, target_id,
                    "📜 古诗文查询\n━━━━━━━━━━\n用法：古诗文 关键词\n示例：古诗文 李白 / 古诗文 静夜思",
                    msg_id=msg_id)
            return True

        return False

    # ================================================================
    #                        菜单 / 键盘
    # ================================================================
    async def _send_menu(self, api, scene, target_id, msg_id):
        title = "📚 学习系统\n━━━━━━━━━━\n选择一项开始学习～"
        rows = [{
            "buttons": [
                self._btn("❓ 知识问答", "知识问答"),
                self._btn("🚗 驾考学习", "驾考学习"),
            ]
        }, {
            "buttons": [
                self._btn("🔢 小学数学", "小学数学"),
                self._btn("📜 古诗文", "古诗文"),
            ]
        }, {
            "buttons": [self._btn("🔙 返回主菜单", "返回主菜单")],
        }]
        keyboard = {"content": {"rows": rows}}
        try:
            await send_text_with_keyboard(api, scene, target_id, title, keyboard, msg_id=msg_id)
        except Exception as e:
            logger.error("[学习] 发送菜单失败: %s" % e)
            await send_text(api, scene, target_id, title, msg_id=msg_id)

    @staticmethod
    def _btn(label, command):
        return {
            "id": "btn_study_" + command,
            "render_data": {"label": label, "visited_label": label, "style": 1},
            "action": {"type": 2, "permission": {"type": 2}, "data": command, "enter": True, "unsupport_tips": "请更新QQ版本"},
        }

    def _build_keyboard(self, *pairs):
        return {"content": {"rows": [{"buttons": [self._btn(lbl, data) for lbl, data in pairs]}]}}

    @staticmethod
    def _qa_prefix(qtype):
        return _QA_PREFIX.get(qtype, "")

    async def _send_with_kb(self, api, scene, target_id, msg_id, text, pairs):
        kb = self._build_keyboard(*pairs)
        try:
            await send_text_with_keyboard(api, scene, target_id, text, kb, msg_id=msg_id)
        except Exception as e:
            logger.error("[学习] 发送键盘失败: %s" % e)
            await send_text(api, scene, target_id, text, msg_id=msg_id)

    # ================================================================
    #                        出题
    # ================================================================
    async def _send_question(self, api, scene, target_id, msg_id, title, body, hint, pairs):
        msg = "%s\n━━━━━━━━━━\n%s\n\n%s" % (title, body, hint)
        await self._send_with_kb(api, scene, target_id, msg_id, msg, pairs)

    # ================================================================
    #                        出题 / 会话
    # ================================================================
    async def _begin_quiz(self, api, scene, target_id, member_openid, msg_id, qtype):
        """入口：若该功能正在进行中则提示，否则开新题或继续当前轮。"""
        if qa_is_active(target_id, qtype):
            owner = qa_owner_openid(target_id, qtype)
            label = _QA_LABEL.get(qtype, "")
            await qa_send(api, scene, target_id, "🔔 %s正在进行中，请先完成当前作答～" % label,
                          mention_openid=(owner if scene == ChatScene.GROUP else None))
            return
        if qtype == "quiz_driving":
            await self._quiz_driving(api, scene, target_id, member_openid, msg_id)
        elif qtype == "quiz_math":
            await self._quiz_math(api, scene, target_id, member_openid, msg_id)
        else:
            await self._quiz_common(api, scene, target_id, member_openid, msg_id)

    def _open_qa(self, target_id, qtype, member_openid, scene, api, label, data):
        """开新题或继续（下一题/答案/跳过复用同一会话）。"""
        if qa_is_active(target_id, qtype):
            qa_continue(target_id, qtype, data)
        else:
            qa_start(target_id, qtype, member_openid, scene, api, label, data)

    async def _quiz_common(self, api, scene, target_id, member_openid, msg_id):
        ok, data = self._call_apihz("/api/zici/changshi.php")
        if not ok or not data:
            await send_text(api, scene, target_id, "📚 知识问答\n━━━━━━━━━━\n题库暂不可用，稍后再试～", msg_id=msg_id)
            return
        question = _clean_text(data.get("p"), 1500)
        answer = _clean_text(data.get("a"), 200)
        self._open_qa(target_id, "quiz_common", member_openid, scene, api, "知识问答",
                      {"question": question, "answer": answer})
        await self._send_question(
            api, scene, target_id, msg_id,
            title="📚 知识问答", body=question,
            hint="💬 发送「常识作答 你的答案」来作答",
            pairs=(("💡 答案", "常识答案"), ("⏭ 跳过", "常识跳过")),
        )

    async def _quiz_driving(self, api, scene, target_id, member_openid, msg_id):
        qtype_ch = random.choice(["1", "4"])
        ok, data = self._call_apihz("/api/jiaotong/jiakao.php", {"type": qtype_ch})
        if not ok or not data:
            await send_text(api, scene, target_id, "🚗 驾考学习\n━━━━━━━━━━\n题库暂不可用，稍后再试～", msg_id=msg_id)
            return
        title = _clean_text(data.get("title"), 800)
        answer = _clean_text(data.get("answer"), 50)
        jtsl = _clean_text(data.get("jtsl"), 500)
        pic = (data.get("pic") or "").strip()
        opts = []
        for k in ("opta", "optb", "optc", "optd"):
            v = data.get(k)
            if v:
                opts.append("%s. %s" % (k[-1].upper(), _clean_text(v, 200)))
        body = title
        if opts:
            body += "\n" + "\n".join(opts)
        self._open_qa(target_id, "quiz_driving", member_openid, scene, api, "驾考学习",
                      {"question": body, "answer": answer, "options": opts, "jtsl": jtsl})
        # 含图片题目（如"如图所示"）：先发图片，再发题目与选项+按钮
        if pic:
            try:
                from modules.common import send_image_for_scene
                await send_image_for_scene(
                    api, scene, target_id, pic,
                    content="🚗 驾考学习\n━━━━━━━━━━\n题目如图所示，看图作答～",
                    msg_id=msg_id,
                )
            except Exception as e:
                logger.error("[学习] 驾考图片发送失败: %s" % e)
        await self._send_question(
            api, scene, target_id, msg_id,
            title="🚗 驾考学习", body=body,
            hint="💬 发送「驾考作答 选项」（如：驾考作答 A 或 驾考作答 ACD）",
            pairs=(("💡 答案", "驾考答案"), ("⏭ 跳过", "驾考跳过")),
        )

    async def _quiz_math(self, api, scene, target_id, member_openid, msg_id):
        ok, data = self._call_apihz("/api/zici/shuxuex.php")
        if not ok or not data:
            await send_text(api, scene, target_id, "🔢 小学数学\n━━━━━━━━━━\n题库暂不可用，稍后再试～", msg_id=msg_id)
            return
        question = _clean_text(data.get("timu"), 1500)
        answer = _clean_text(data.get("daan"), 200)
        jtsl = _clean_text(data.get("jiexi"), 500)
        if not question or not answer:
            await send_text(api, scene, target_id, "🔢 小学数学\n━━━━━━━━━━\n题目解析不完整，请重新出题～", msg_id=msg_id)
            return
        self._open_qa(target_id, "quiz_math", member_openid, scene, api, "小学数学",
                      {"question": question, "answer": answer, "jtsl": jtsl})
        await self._send_question(
            api, scene, target_id, msg_id,
            title="🔢 小学数学", body=question,
            hint="💬 发送「数学作答 你的答案」来作答",
            pairs=(("💡 答案", "数学答案"), ("⏭ 跳过", "数学跳过")),
        )

    # ================================================================
    #                        答题交互
    # ================================================================
    async def _on_submit(self, api, scene, target_id, member_openid, msg_id, qtype, user_ans):
        sess = qa_get(target_id, qtype)
        if not sess:
            return False
        if scene == ChatScene.GROUP and not qa_is_owner(target_id, qtype, member_openid):
            return True  # 非发起者的作答指令忽略，避免误触他人答题
        pfx = self._qa_prefix(qtype)
        if not user_ans:
            await qa_send(api, scene, target_id, "💬 请发送：%s作答 你的答案" % pfx)
            return True
        qa_touch(target_id, qtype)
        data = sess["data"]
        qkind = "driving" if qtype == "quiz_driving" else "text"
        correct = _is_answer_correct(user_ans, data.get("answer", ""), qtype=qkind)
        if correct:
            lines = ["✅ 回答正确！"]
            if data.get("answer"):
                lines.append("💡 答案：%s" % data["answer"])
            if data.get("jtsl"):
                lines.append("💡 解析：%s" % data["jtsl"])
            pairs = (("⏭ 下一题", "%s下一题" % pfx),)  # 答对不再发「答案」按钮
        else:
            lines = ["❌ 回答错误！"]
            pairs = (("💡 答案", "%s答案" % pfx), ("⏭ 下一题", "%s下一题" % pfx))
        await qa_send_kb(api, scene, target_id, "\n".join(lines), pairs,
                        mention_openid=(member_openid if scene == ChatScene.GROUP else None))
        return True

    async def _on_answer_btn(self, api, scene, target_id, member_openid, msg_id, qtype):
        sess = qa_get(target_id, qtype)
        if not sess:
            return False
        qa_touch(target_id, qtype)
        await self._reveal_and_next(api, scene, target_id, member_openid, msg_id, qtype)
        return True

    async def _on_skip_btn(self, api, scene, target_id, member_openid, msg_id, qtype):
        sess = qa_get(target_id, qtype)
        if not sess:
            return False
        qa_touch(target_id, qtype)
        await self._reveal_and_next(api, scene, target_id, member_openid, msg_id, qtype)
        return True

    async def _on_next_btn(self, api, scene, target_id, member_openid, msg_id, qtype):
        sess = qa_get(target_id, qtype)
        if not sess:
            return False
        qa_touch(target_id, qtype)
        if qtype == "quiz_driving":
            await self._quiz_driving(api, scene, target_id, member_openid, msg_id)
        elif qtype == "quiz_math":
            await self._quiz_math(api, scene, target_id, member_openid, msg_id)
        else:
            await self._quiz_common(api, scene, target_id, member_openid, msg_id)
        return True

    async def _reveal_and_next(self, api, scene, target_id, member_openid, msg_id, qtype):
        sess = qa_get(target_id, qtype)
        if not sess:
            return
        data = sess["data"]
        lines = []
        if data.get("answer"):
            lines.append("💡 答案：%s" % data["answer"])
        if data.get("jtsl"):
            lines.append("💡 解析：%s" % data["jtsl"])
        if lines:
            await send_text(api, scene, target_id, "\n".join(lines), msg_id=msg_id)
        # 出下一题（覆盖会话）
        if qtype == "quiz_driving":
            await self._quiz_driving(api, scene, target_id, member_openid, msg_id)
        elif qtype == "quiz_math":
            await self._quiz_math(api, scene, target_id, member_openid, msg_id)
        else:
            await self._quiz_common(api, scene, target_id, member_openid, msg_id)

    # ================================================================
    #                        古诗文查询
    # ================================================================
    async def _query_poetry(self, api, scene, target_id, msg_id, word):
        ok, data = self._call_apihz("/api/zici/poetry.php", {"words": word})
        if not ok or not data:
            await send_text(api, scene, target_id, "📜 古诗文查询\n━━━━━━━━━━\n未找到「%s」相关内容，换个关键词试试～" % word, msg_id=msg_id)
            return
        poems = data.get("data") or []
        if not poems:
            await send_text(api, scene, target_id, "📜 古诗文查询\n━━━━━━━━━━\n未找到「%s」相关内容，换个关键词试试～" % word, msg_id=msg_id)
            return
        poem = random.choice(poems) if len(poems) > 1 else poems[0]
        name = _clean_text(poem.get("name"), 100)
        author = _clean_text(poem.get("author"), 50)
        dynasty = _clean_text(poem.get("dynasty"), 20)
        content = _clean_text(poem.get("content"), 600)
        yiwen = _clean_text(poem.get("ywjzsy") or poem.get("ywjzse"), 1200)
        zhushi = _clean_text(poem.get("czbj"), 1200)
        shangxi = _clean_text(poem.get("sxy") or poem.get("sxe"), 1200)

        lines = ["📜 古诗文查询", "━━━━━━━━━━"]
        if name:
            lines.append("《%s》" % name)
        if author:
            lines.append("作者：%s%s" % (author, "（%s）" % dynasty if dynasty else ""))
        if content:
            lines.append("\n%s" % content)
        if yiwen:
            lines.append("\n【译文】\n%s" % yiwen)
        if zhushi:
            lines.append("\n【注释/背景】\n%s" % zhushi)
        if shangxi:
            lines.append("\n【赏析】\n%s" % shangxi)
        msg = "\n".join(lines)
        if len(msg) > 3800:
            msg = msg[:3700].rstrip() + "\n…（内容较多已截断）"
        await send_text(api, scene, target_id, msg, msg_id=msg_id)