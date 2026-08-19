# -*- coding: utf-8 -*-

"""
小说系统模块（在线版）

数据源：在线小说站点（搜索 + 按章阅读）

  - 搜索：发送「小说 书名」-> 返回前 10 本匹配书，点击或「选书N」进入

  - 阅读：进入书 -> 从首章开始，整章渲染为长图（在线抓取 + PIL 渲染图片发送）

  - 翻章：上一章/下一章 流式跟随 next_id/prev_id；正文以整章长图呈现，无需翻页

设计要点：

  - 完全替代原本地古典名著库（data/classic_novels.json 不再使用）

  - 状态机：idle -> search(搜索结果) -> reading(某书某章)

  - 全局指令隔离：阅读中输入「菜单/帮助/签到」等非小说指令时，静默退出阅读交给其它功能

  - 渲染层 render_novel（data/render_novel.py）：render_chapter_long（整章长图）

  - 网络请求均为同步阻塞（urllib），调用方在 asyncio.to_thread 中执行
"""

import os
import re
import asyncio
import random
import importlib.util

from botpy import logging
from modules.common import (
    send_text,
    send_text_with_keyboard,
    send_local_image_for_scene,
    load_json,
    save_json,
    data_path,
)
from modules.qishuxia import (
    search_books,
    get_book,
    get_chapter,
    QishuXiaError,
)

logger = logging.get_logger()

# ============ 路径 ============
_STATE_FILE = data_path("novel_states.json")

# 随机推荐用的热门书名池
_POPULAR = [
    "斗破苍穹", "大奉打更人", "诡秘之主", "凡人修仙传", "全职高手",
    "雪中悍刀行", "遮天", "庆余年", "剑来", "完美世界",
]

# 渲染器 render_novel（data/render_novel.py），用绝对路径加载，避免 data 非 package 问题
_RENDER_PATH = data_path("render_novel.py")
try:
    _spec = importlib.util.spec_from_file_location("render_novel", _RENDER_PATH)
    render_novel = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(render_novel)
except Exception as e:  # noqa
    render_novel = None
    logger.error("渲染器 render_novel 加载失败: %s" % e)


# ============ 键盘构造（多行） ============
def _build_kb(buttons_config, per_row=5):
    rows = []
    for i in range(0, len(buttons_config), per_row):
        row_btns = buttons_config[i:i + per_row]
        buttons = []
        for cfg in row_btns:
            label = cfg["label"]
            cmd = cfg["command"]
            buttons.append({
                "id": "nv_" + re.sub(r"[^0-9a-zA-Z\u4e00-\u9fa5]", "", cmd)[:18],
                "render_data": {
                    "label": label,
                    "visited_label": label,
                    "style": 1,
                },
                "action": {
                    "type": 2,
                    "permission": {"type": 2},
                    "data": cmd,
                    "enter": False,
                    "unsupport_tips": "请更新QQ版本",
                },
            })
        rows.append({"buttons": buttons})
    return {"content": {"rows": rows}}


class NovelSystem:
    def __init__(self):
        self._states = {}
        self._chapter_cache = {}  # 内存缓存当前章节正文（不持久化，重启后重抓）
        self._img_cache = {}      # 已渲染的长图路径缓存，键 (book_id, chapter_id)
        self._load_states()

    # ---- 状态 ----
    def _load_states(self):
        try:
            self._states = load_json(_STATE_FILE) or {}
        except Exception:
            self._states = {}
        # 仅保留在线版结构（mode 字段）；丢弃旧版本地库残留（book_index 等）
        clean = {}
        for sid, st in self._states.items():
            if isinstance(st, dict) and st.get("mode") in ("search", "reading"):
                clean[sid] = st
        self._states = clean
        self._chapter_cache = {}

    def _save_states(self):
        try:
            save_json(_STATE_FILE, self._states)
        except Exception as e:
            logger.warning("小说状态保存失败: %s" % e)

    def _get_state(self, storage_id):
        return self._states.get(storage_id)

    def _save_state(self, storage_id, state):
        if state is None:
            self._states.pop(storage_id, None)
            self._chapter_cache.pop(storage_id, None)
            self._img_cache.pop(storage_id, None)
        else:
            self._states[storage_id] = state
        self._save_states()

    def _is_reading(self, storage_id):
        st = self._states.get(storage_id)
        return bool(st and st.get("mode") in ("search", "reading"))

    def _force_end_reading(self, storage_id):
        if storage_id in self._states:
            self._states.pop(storage_id, None)
            self._chapter_cache.pop(storage_id, None)
            self._img_cache.pop(storage_id, None)
            self._save_states()

    # ---- 主入口 ----
    async def handle_command(self, api, content, storage_id, member_openid, msg_id, scene):
        text = (content or "").strip()
        st = self._states.get(storage_id)
        if st and st.get("mode") in ("search", "reading"):
            return await self._handle_active(api, text, storage_id, msg_id, scene)

        # 精确入口
        if text in ("小说", "看小说", "读书", "看书", "在线阅读"):
            await self._show_search_guide(api, storage_id, msg_id, scene)
            return True
        # 前缀：看/读
        if text.startswith("看 ") or text.startswith("读 "):
            kw = text[2:].strip()
            if kw:
                await self._do_search(api, kw, storage_id, msg_id, scene)
            else:
                await self._show_search_guide(api, storage_id, msg_id, scene)
            return True
        if text.startswith("小说 "):
            sub = text[3:].strip()
            if sub in ("随机推荐", "随机"):
                await self._random_book(api, storage_id, msg_id, scene)
            elif sub in ("上一本", "下一本"):
                await self._show_search_guide(api, storage_id, msg_id, scene)
            elif sub:
                await self._do_search(api, sub, storage_id, msg_id, scene)
            else:
                await self._show_search_guide(api, storage_id, msg_id, scene)
            return True
        return False

    # ---- 阅读 / 搜索进行中 ----
    async def _handle_active(self, api, text, storage_id, msg_id, scene):
        st = self._states.get(storage_id)
        if st is None:
            return False
        mode = st.get("mode")

        # 退出优先
        if text in ("退出小说", "不看了", "结束阅读", "退出阅读", "退出"):
            self._force_end_reading(storage_id)
            await send_text(api, scene, storage_id,
                            "已退出阅读。发送「小说」可重新搜索。", msg_id=msg_id)
            return True

        if mode == "search":
            m = re.match(r"^选书\s*(\d+)$", text)
            if m:
                await self._pick_book(api, storage_id, int(m.group(1)), msg_id, scene)
                return True
            # 重新搜索 / 返回引导
            kw = text.strip()
            if kw in ("小说", "看小说", "读书", "看书", "在线阅读"):
                self._force_end_reading(storage_id)
                await self._show_search_guide(api, storage_id, msg_id, scene)
                return True
            if kw.startswith("看 ") or kw.startswith("读 ") or kw.startswith("小说 "):
                kw = kw.split(" ", 1)[1].strip()
            if kw:
                await self._do_search(api, kw, storage_id, msg_id, scene)
            else:
                await self._show_search_guide(api, storage_id, msg_id, scene)
            return True

        # reading 模式
        if text in ("小说", "看小说", "读书", "看书", "在线阅读"):
            self._force_end_reading(storage_id)
            await self._show_search_guide(api, storage_id, msg_id, scene)
            return True
        if text in ("返回书库", "书库", "返回"):
            self._force_end_reading(storage_id)
            await self._show_search_guide(api, storage_id, msg_id, scene)
            return True
        if text in ("上一章", "上章"):
            await self._goto_chapter_rel(api, storage_id, st, msg_id, scene, -1)
            return True
        if text in ("下一章", "下章"):
            await self._goto_chapter_rel(api, storage_id, st, msg_id, scene, 1)
            return True
        if text in ("目录", "章节列表", "章节"):
            await self._show_chapter_info(api, storage_id, st, msg_id, scene)
            return True
        if text.startswith("看 ") or text.startswith("读 "):
            kw = text[2:].strip()
            await self._do_search(api, kw, storage_id, msg_id, scene)
            return True
        if text.startswith("小说 "):
            sub = text[3:].strip()
            if sub in ("随机推荐", "随机"):
                await self._random_book(api, storage_id, msg_id, scene)
                return True
            if sub in ("上一本", "下一本"):
                await self._show_search_guide(api, storage_id, msg_id, scene)
                return True
            await self._do_search(api, sub, storage_id, msg_id, scene)
            return True
        m = re.match(r"^第\s*(\d+)\s*(回|章|卷)?$", text)
        if m:
            await send_text(api, scene, storage_id,
                            "🌐 在线模式暂不支持按序号跳章，可用「上一章 / 下一章」翻阅。",
                            msg_id=msg_id)
            return True
        # 其它指令：静默退出阅读，交给其它功能处理
        self._force_end_reading(storage_id)
        return False

    # ---- 搜索引导 ----
    async def _show_search_guide(self, api, storage_id, msg_id, scene):
        btns = [
            {"label": "🔥 斗破苍穹", "command": "小说 斗破苍穹"},
            {"label": "🔥 大奉打更人", "command": "小说 大奉打更人"},
            {"label": "🔥 诡秘之主", "command": "小说 诡秘之主"},
            {"label": "🎲 随机推荐", "command": "小说 随机推荐"},
            {"label": "❌ 退出", "command": "退出小说"},
        ]
        kb = _build_kb(btns, per_row=2)
        await send_text_with_keyboard(
            api, scene, storage_id,
            "📚 在线小说\n发送「小说 书名」即可搜索阅读，例如「小说 斗破苍穹」。\n"
            "也支持「看 书名 / 读 书名」。点击下方示例或随机推荐试试～",
            kb, msg_id=msg_id)

    # ---- 执行搜索 ----
    async def _do_search(self, api, keyword, storage_id, msg_id, scene):
        if not keyword:
            await self._show_search_guide(api, storage_id, msg_id, scene)
            return
        await send_text(api, scene, storage_id,
                        "🌐 正在搜索《%s》……" % keyword, msg_id=msg_id)
        try:
            results = await asyncio.to_thread(search_books, keyword, 10)
        except QishuXiaError as e:
            await send_text(api, scene, storage_id,
                            "🌐 搜索失败：%s\n请稍后重试，或发送「小说」查看示例。" % e,
                            msg_id=msg_id)
            return
        if not results:
            await send_text(api, scene, storage_id,
                            "🔍 没有找到与《%s》相关的书籍。\n"
                            "试试发送「小说 斗破苍穹」之类的关键词～" % keyword,
                            msg_id=msg_id)
            return

        self._save_state(storage_id, {
            "mode": "search", "results": results, "keyword": keyword})
        btns = []
        for i, b in enumerate(results):
            label = "%d.《%s》" % (i + 1, b["title"])
            if len(label) > 18:
                label = label[:17] + "…"
            btns.append({"label": label, "command": "选书%d" % (i + 1)})
        btns.append({"label": "❌ 退出", "command": "退出小说"})
        kb = _build_kb(btns, per_row=2)

        lines = []
        for i, b in enumerate(results):
            author = (" · " + b["author"]) if b.get("author") else ""
            lines.append("%d. 《%s》%s" % (i + 1, b["title"], author))
        await send_text_with_keyboard(
            api, scene, storage_id,
            "🔍 找到 %d 本相关书籍，点击或发送「选书N」开始阅读：\n%s"
            % (len(results), "\n".join(lines)),
            kb, msg_id=msg_id)

    # ---- 选书进入 ----
    async def _pick_book(self, api, storage_id, idx, msg_id, scene):
        st = self._states.get(storage_id)
        if not st or st.get("mode") != "search":
            await send_text(api, scene, storage_id,
                            "请先发送「小说 书名」搜索。", msg_id=msg_id)
            return
        results = st.get("results") or []
        if idx < 1 or idx > len(results):
            await send_text(api, scene, storage_id,
                            "没有这本书的序号，请重新选择。", msg_id=msg_id)
            return
        book = results[idx - 1]
        await self._enter_book(api, book, storage_id, msg_id, scene)

    async def _enter_book(self, api, book, storage_id, msg_id, scene):
        await send_text(api, scene, storage_id,
                        "🌐 正在获取《%s》……" % book["title"], msg_id=msg_id)
        try:
            detail = await asyncio.to_thread(get_book, book["book_id"])
        except QishuXiaError as e:
            await send_text(api, scene, storage_id,
                            "🌐 获取书籍信息失败：%s" % e, msg_id=msg_id)
            return
        st = {
            "mode": "reading",
            "book_id": book["book_id"],
            "book_title": detail.get("title") or book["title"],
            "book_author": detail.get("author") or book.get("author", ""),
            "chapter_id": detail.get("first_chapter_id") or "1",
            "chapter_idx": 1,
        }
        self._chapter_cache.pop(storage_id, None)
        self._img_cache.pop(storage_id, None)
        self._save_state(storage_id, st)
        await self._show_chapter_content(api, storage_id, st, msg_id, scene)

    # ---- 章节正文（带内存缓存） ----
    async def _ensure_chapter(self, storage_id, st):
        cache = self._chapter_cache.get(storage_id)
        if cache and cache.get("chapter_id") == st["chapter_id"]:
            return cache
        ch = await asyncio.to_thread(
            get_chapter, st["book_id"], st["chapter_id"])
        cache = dict(ch, chapter_id=st["chapter_id"])
        self._chapter_cache[storage_id] = cache
        return cache

    async def _show_chapter_content(self, api, storage_id, st, msg_id, scene):
        try:
            ch = await self._ensure_chapter(storage_id, st)
        except QishuXiaError as e:
            await send_text(api, scene, storage_id,
                            "🌐 章节加载失败：%s\n请发送「下一章」或「退出小说」。"
                            % e, msg_id=msg_id)
            return

        if render_novel is None:
            await send_text(api, scene, storage_id,
                            "渲染器不可用（缺少 Pillow），无法显示图片。",
                            msg_id=msg_id)
            return

        try:
            paths = await self._render_chapter_images(storage_id, st, ch)
        except Exception as e:
            logger.error("长图渲染失败: %s" % e)
            await send_text(api, scene, storage_id,
                            "本章渲染失败：%s" % e, msg_id=msg_id)
            return

        # 逐张发送长图（超长章节会有多张，用户可上滑连看）
        for i, p in enumerate(paths):
            await self._send_local_img(
                api, scene, storage_id, p, msg_id,
                content="《%s》· %s（%d/%d）"
                % (st["book_title"], ch.get("title", ""), i + 1, len(paths)))

        kb = _build_kb([
            {"label": "上一章", "command": "上一章"},
            {"label": "下一章", "command": "下一章"},
            {"label": "目录", "command": "目录"},
            {"label": "返回书库", "command": "返回书库"},
            {"label": "退出", "command": "退出小说"},
        ], per_row=3)
        await send_text_with_keyboard(
            api, scene, storage_id,
            "《%s》· %s\n第 %d 章（共 %d 张长图，上滑查看完整正文）"
            % (st["book_title"], ch.get("title", ""),
               st["chapter_idx"], len(paths)),
            kb, msg_id=msg_id)

    # ---- 渲染长图（带缓存，同一章不重复渲染） ----
    async def _render_chapter_images(self, storage_id, st, ch):
        key = (st["book_id"], st["chapter_id"])
        cached = self._img_cache.get(storage_id)
        if cached and cached[0] == key:
            return cached[1]
        book = {"title": st["book_title"], "author": st["book_author"]}
        paths = render_novel.render_chapter_long(book, ch)
        self._img_cache[storage_id] = (key, paths)
        return paths

    # ---- 上一章 / 下一章 ----
    async def _goto_chapter_rel(self, api, storage_id, st, msg_id, scene, delta):
        ch = await self._ensure_chapter(storage_id, st)
        if delta > 0 and ch.get("next_id"):
            st["chapter_id"] = ch["next_id"]
            st["chapter_idx"] = st["chapter_idx"] + 1
        elif delta < 0 and ch.get("prev_id"):
            st["chapter_id"] = ch["prev_id"]
            st["chapter_idx"] = max(1, st["chapter_idx"] - 1)
        else:
            await send_text(api, scene, storage_id,
                            "已经是%s章了。" % ("最后一" if delta > 0 else "第一"),
                            msg_id=msg_id)
            return
        self._chapter_cache.pop(storage_id, None)
        self._img_cache.pop(storage_id, None)
        self._save_state(storage_id, st)
        await self._show_chapter_content(api, storage_id, st, msg_id, scene)

    # ---- 目录信息（在线无完整目录） ----
    async def _show_chapter_info(self, api, storage_id, st, msg_id, scene):
        try:
            ch = await self._ensure_chapter(storage_id, st)
        except QishuXiaError as e:
            await send_text(api, scene, storage_id,
                            "🌐 章节加载失败：%s" % e, msg_id=msg_id)
            return
        has_prev = bool(ch.get("prev_id"))
        has_next = bool(ch.get("next_id"))
        kb = _build_kb([
            {"label": "上一章", "command": "上一章"},
            {"label": "下一章", "command": "下一章"},
            {"label": "返回书库", "command": "返回书库"},
            {"label": "退出", "command": "退出小说"},
        ], per_row=2)
        await send_text_with_keyboard(
            api, scene, storage_id,
            "📑 《%s》· %s（第 %d 章）\n%s\n可用「上一章 / 下一章」翻阅；"
            "在线章节为连续更新，暂无完整目录。"
            % (st["book_title"], ch.get("title", ""), st["chapter_idx"],
               "上一章可用" if has_prev else "已是首章"),
            kb, msg_id=msg_id)

    # ---- 随机 ----
    async def _random_book(self, api, storage_id, msg_id, scene):
        kw = random.choice(_POPULAR)
        await self._do_search(api, kw, storage_id, msg_id, scene)

    # ---- 本地图片发送 ----
    async def _send_local_img(self, api, scene, storage_id, path, msg_id, content=""):
        try:
            with open(path, "rb") as f:
                data = f.read()
            await send_local_image_for_scene(
                api, scene, storage_id, data, msg_id=msg_id, content=content)
        except Exception as e:
            logger.error("发送本地图片失败: %s" % e)


# 单例
novel_mgr = NovelSystem()
# ============ 插件壳（plugin_registry 目录包契约）============

PLUGIN = {
    "key": "novel",
    "name": "小说",
    "priority": 80,
    "description": "在线小说阅读",
    "category": "novel",
}

_manager = novel_mgr


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    from console_server import is_feature_enabled
    if not is_feature_enabled("novel", appid=ctx.bot_appid):
        return False
    return await ctx.bot._time_plugin(
        "novel", novel_mgr.handle_command, ctx.perf,
        ctx.api, ctx.content, ctx.storage_id, ctx.member_openid, ctx.msg_id, scene=ctx.scene,
    )

def session_check(storage_id: str) -> bool:
    return novel_mgr._is_reading(storage_id)
