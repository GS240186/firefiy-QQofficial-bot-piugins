# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
"""
鸣潮模拟抽卡（小流萤 · 外置插件，plugins/）

参考 AstrBot 插件 astrbot_plugin_ww_gacha_sim（作者 Ruafafa，MIT）的核心抽卡算法移植而来。
已彻底剥离原插件对 astrbot / SQLite / WebUI / node 渲染 的依赖，改为「纯 dict + PIL 渲染」，
直接复用项目外置插件契约（PLUGIN dict + async handle(ctx) + ctx.reply / send_local_image_for_scene）。

卡池数据：本目录下的 ww_gacha_data/*.json（从参考插件 src/assets/presets/ 复制，未改动结构）。
物品身份完全编码在 external_id 中（cha_名称_hash = 角色，wea_名称_hash = 武器），
无需数据库，按需从预设 included_item_ids 即时合成物品 dict。

渲染：纯 PIL 自绘（5x2 网格 + 5星金/4星紫/3星蓝配色 + UP 徽标 + 保底进度条），
优先 C:\\Windows\\Fonts\\msyh.ttc，缺则降级 simhei / Deng 等系统字体。
立绘：从参考插件 src/assets/data/default.csv 的 portrait_url（鸣潮官方立绘，第三方整理仓库
TomyJan/WutheringWaves-UIResources，MIT）预下载到 ww_gacha_data/portraits/<name>.png，
渲染时按物品名贴入卡片主体（cover 缩放 + 圆角遮罩）；缺失立绘的物品回退色块+名字。
无需 puppeteer / playwright / art-template；运行环境（Python 3.11）自带 PIL 11.x。

触发方式（群里或私聊 @机器人，前导 # 可选）：
· 鸣潮单抽            —— 抽 1 次
· 鸣潮十连            —— 抽 10 次
· 鸣潮卡池            —— 查看可用卡池
· 鸣潮卡池 <名称>     —— 切换当前卡池（如：鸣潮卡池 默认卡池）
· 鸣潮状态            —— 查看当前保底进度
· 鸣潮重置            —— 重置当前卡池保底
· 鸣潮 / 鸣潮帮助      —— 查看用法

说明：抽奖结果随机、仅供娱乐，概率规则与鸣潮一致（5★ 软保底 66~79 抽、硬保底 80 抽；4★ 硬保底 10 抽）。
"""

import io
import json as _json
import os
import random
import threading

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except Exception as _e:  # pragma: no cover
    Image = ImageDraw = ImageFont = None
    _HAS_PIL = False
    print("[ww_gacha] PIL 不可用，抽卡图片渲染将禁用: %s" % _e, flush=True)
PLUGIN = {
    "key": "ww_gacha",
    "name": "鸣潮模拟抽卡",
    "priority": 500,
    "description": "鸣潮模拟抽卡：发送「鸣潮十连」抽 10 次，「鸣潮卡池」切换卡池",
    "category": "game",
}

_TRIGGER = "鸣潮"

# 项目根（modules/ -> 根）与 data 目录，用于持久化保底状态
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_STATE_FILE = os.path.join(_DATA_DIR, "ww_gacha_state.json")

# 卡池预设目录（与本插件同目录下的 ww_gacha_data/）
_PRESET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ww_gacha_data")
# 立绘缓存目录：name.png（从参考插件 default.csv 的 portrait_url 预下载，详见 _load_portrait_map）
_PORTRAIT_DIR = os.path.join(_PRESET_DIR, "portraits")

_STATE_LOCK = threading.Lock()


# ----------------------------------------------------------------------------
# 图片渲染（纯 PIL，无需 puppeteer / playwright / SVG 模板）
# ----------------------------------------------------------------------------
_CJK_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\Deng.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)
_DIGIT_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\Dengl.ttf",
    r"C:\Windows\Fonts\Deng.ttf",
    r"C:\Windows\Fonts\msyhl.ttc",
)


def _pick_font(candidates, size):
    """从候选字体路径列表中加载第一个可用的 TrueType 字体。PIL 不可用时回退 default。"""
    if not _HAS_PIL:
        return None
    for fp in candidates:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


_F_CJK = _pick_font(_CJK_FONT_CANDIDATES, 22)        # 卡内名/正文
_F_CJK_BIG = _pick_font(_CJK_FONT_CANDIDATES, 30)    # 标题
_F_CJK_SM = _pick_font(_CJK_FONT_CANDIDATES, 16)     # 角标/提示
_F_DIG = _pick_font(_DIGIT_FONT_CANDIDATES, 18)      # 数字


# 抽卡配色（按稀有度）
_RARITY_THEME = {
    "5star": {
        "top": (255, 219, 105), "mid": (212, 175, 55), "bot": (95, 67, 25),
        "text": (255, 240, 200), "border": (255, 232, 140), "star": (255, 240, 160),
        "tag_bg": (90, 56, 18), "tag_fg": (255, 232, 160),
    },
    "4star": {
        "top": (190, 165, 255), "mid": (156, 122, 230), "bot": (62, 43, 102),
        "text": (245, 235, 255), "border": (188, 158, 255), "star": (220, 200, 255),
        "tag_bg": (54, 36, 96), "tag_fg": (220, 200, 255),
    },
    "3star": {
        "top": (140, 175, 210), "mid": (91, 124, 156), "bot": (42, 56, 80),
        "text": (225, 235, 245), "border": (150, 185, 220), "star": (200, 220, 240),
        "tag_bg": (34, 46, 68), "tag_fg": (200, 220, 240),
    },
}
_UP_BG = (235, 60, 80)
_UP_FG = (255, 255, 255)


def _hgrad_rect(draw, box, top_rgb, bot_rgb):
    """在 box=(x0,y0,x1,y1) 内画垂直渐变 (PIL 默认 RGB 模式)."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if h <= 0 or w <= 0:
        return
    for i in range(h):
        t = i / max(h - 1, 1)
        r = int(top_rgb[0] * (1 - t) + bot_rgb[0] * t)
        g = int(top_rgb[1] * (1 - t) + bot_rgb[1] * t)
        b = int(top_rgb[2] * (1 - t) + bot_rgb[2] * t)
        draw.line([(x0, y0 + i), (x1, y0 + i)], fill=(r, g, b))


def _vgrad_bg(w, h):
    """背景：深紫蓝 → 黑。"""
    img = Image.new("RGB", (w, h), (12, 8, 28))
    draw = ImageDraw.Draw(img)
    top = (30, 24, 56)
    bot = (10, 7, 22)
    for i in range(h):
        t = i / max(h - 1, 1)
        r = int(top[0] * (1 - t) + bot[0] * t)
        g = int(top[1] * (1 - t) + bot[1] * t)
        b = int(top[2] * (1 - t) + bot[2] * t)
        draw.line([(0, i), (w, i)], fill=(r, g, b))
    # 顶部装饰条（暗金）
    draw.rectangle([(0, 0), (w, 3)], fill=(212, 175, 55))
    return img


def _fit_text(draw, text, font, max_w):
    """缩到不超过 max_w 的 PIL font，返回 (font, width, height)。"""
    if not text:
        return font, 0, 0
    w, h = draw.textbbox((0, 0), text, font=font)[2:]
    if w <= max_w:
        return font, w, h
    # 二分缩小字号
    size = getattr(font, "size", 24)
    lo, hi = 8, size
    best = font
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            f = ImageFont.truetype(font.path, mid) if getattr(font, "path", None) else font
        except Exception:
            break
        bw, bh = draw.textbbox((0, 0), text, font=f)[2:]
        if bw <= max_w:
            best = f
            lo = mid + 1
        else:
            hi = mid - 1
    w, h = draw.textbbox((0, 0), text, font=best)[2:]
    return best, w, h


def _star_str(rarity):
    n = {"3star": 3, "4star": 4, "5star": 5}.get(rarity, 0)
    return "★" * n


def _load_portrait_map():
    """扫描 _PORTRAIT_DIR，建立 name -> 本地 png 绝对路径 映射（立绘预缓存）。"""
    m = {}
    try:
        if os.path.isdir(_PORTRAIT_DIR):
            for fn in os.listdir(_PORTRAIT_DIR):
                if fn.lower().endswith(".png") and os.path.getsize(
                        os.path.join(_PORTRAIT_DIR, fn)) > 2000:
                    m[fn[:-4]] = os.path.join(_PORTRAIT_DIR, fn)
    except Exception:
        pass
    return m


_PORTRAIT_MAP = _load_portrait_map()

_PORTRAIT_BASE_URL = "https://cdn.jsdelivr.net/gh/TomyJan/WutheringWaves-UIResources@3.3/"
_PORTRAIT_RELPATHS = {
    "万物持存的注释": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040046_UI.png",
    "不屈命定之冠": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020056_UI.png",
    "不归孤军": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020044_UI.png",
    "不灭航路": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020025_UI.png",
    "东落": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010064_UI.png",
    "丹瑾": "UIResources/Common/Image/Luckdraw/T_Luckdraw_danjin_UI.png",
    "仇远": "UIResources/Common/Image/Luckdraw/T_Luckdraw_QiuYuan_UI.png",
    "今州守望": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050044_UI.png",
    "今汐": "UIResources/Common/Image/Luckdraw/T_Luckdraw_jinxi_UI.png",
    "停驻之烟": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030015_UI.png",
    "光影双生": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030036_UI.png",
    "凋亡频移": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010084_UI.png",
    "凌阳": "UIResources/Common/Image/Luckdraw/T_Luckdraw_lingyang_UI.png",
    "千古洑流": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020015_UI.png",
    "千咲": "UIResources/Common/Image/Luckdraw/T_Luckdraw_QianXiao_UI.png",
    "华彩乐段": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030024_UI.png",
    "卜灵": "UIResources/Common/Image/Luckdraw/T_Luckdraw_BuLing_UI.png",
    "卡卡罗": "UIResources/Common/Image/Luckdraw/T_Luckdraw_kakaluo_UI.png",
    "卡提希娅": "UIResources/Common/Image/Luckdraw/T_Luckdraw_katixiya_UI.png",
    "县切": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010056_UI.png",
    "吟霖": "UIResources/Common/Image/Luckdraw/T_Luckdraw_yinlin_UI.png",
    "呼啸重音": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040024_UI.png",
    "和光回唱": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050029_UI.png",
    "嘉贝莉娜": "UIResources/Common/Image/Luckdraw/T_Luckdraw_JiaBeiLiNa_UI.png",
    "坎特蕾拉": "UIResources/Common/Image/Luckdraw/T_Luckdraw_kanteleila_UI.png",
    "夏空": "UIResources/Common/Image/Luckdraw/T_Luckdraw_xiakong_UI.png",
    "奇幻变奏": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050024_UI.png",
    "奥古斯塔": "UIResources/Common/Image/Luckdraw/T_Luckdraw_Aogusita_UI.png",
    "守岸人": "UIResources/Common/Image/Luckdraw/T_Luckdraw_shouanren_UI.png",
    "安可": "UIResources/Common/Image/Luckdraw/T_Luckdraw_anke_UI.png",
    "宙算仪轨": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010066_UI.png",
    "尘云旋臂": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040084_UI.png",
    "尤诺": "UIResources/Common/Image/Luckdraw/T_Luckdraw_Younuo_UI.png",
    "布兰特": "UIResources/Common/Image/Luckdraw/T_Luckdraw_bulante_UI.png",
    "幽冥的忘忧章": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050066_UI.png",
    "异响空灵": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010024_UI.png",
    "异度": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050064_UI.png",
    "弗洛洛": "UIResources/Common/Image/Luckdraw/T_Luckdraw_fuluoluo_UI.png",
    "忌炎": "UIResources/Common/Image/Luckdraw/T_Luckdraw_jiyan_UI.png",
    "悖论喷流": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030084_UI.png",
    "悲喜剧": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040018_UI.png",
    "折枝": "UIResources/Common/Image/Luckdraw/T_Luckdraw_zhezhi_UI.png",
    "掣傀之手": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050016_UI.png",
    "擎渊怒涛": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040015_UI.png",
    "散华": "UIResources/Common/Image/Luckdraw/T_Luckdraw_sanhua_UI.png",
    "无眠烈火": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030044_UI.png",
    "时和岁稔": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010026_UI.png",
    "星序协响": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050027_UI.png",
    "昭日译注": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040066_UI.png",
    "暗夜佩枪·暗星": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030013_UI.png",
    "暗夜矩阵·暝光": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050013_UI.png",
    "暗夜臂铠·夜芒": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040013_UI.png",
    "暗夜迅刀·黑闪": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020013_UI.png",
    "暗夜长刃·玄明": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010013_UI.png",
    "林间的咏叹调": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030026_UI.png",
    "核熔星盘": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050084_UI.png",
    "桃祈": "UIResources/Common/Image/Luckdraw/T_Luckdraw_taohua_UI.png",
    "椿": "UIResources/Common/Image/Luckdraw/T_Luckdraw_chun_UI.png",
    "死与舞": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030017_UI.png",
    "永夜长明": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010044_UI.png",
    "永续坍缩": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020084_UI.png",
    "永远的启明星": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020076_UI.png",
    "洛可可": "UIResources/Common/Image/Luckdraw/T_Luckdraw_luokeke_UI.png",
    "浩境粼光": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010015_UI.png",
    "海的呢喃": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050030_UI.png",
    "渊武": "UIResources/Common/Image/Luckdraw/T_Luckdraw_yuanwu_UI.png",
    "源能佩枪·测参": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030023_UI.png",
    "源能机锋": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010045_UI.png",
    "源能臂铠·测肆": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040023_UI.png",
    "源能迅刀·测贰": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020023_UI.png",
    "源能长刃·测壹": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010023_UI.png",
    "源能音感仪·测五": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050023_UI.png",
    "溢彩荧辉": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030046_UI.png",
    "漪澜浮录": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050015_UI.png",
    "灯灯": "UIResources/Common/Image/Luckdraw/T_Luckdraw_dengdeng_UI.png",
    "灼霜": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020086_UI.png",
    "炽霞": "UIResources/Common/Image/Luckdraw/T_Luckdraw_maxiaofang_UI.png",
    "焰光裁定": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040019_UI.png",
    "焰痕": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010036_UI.png",
    "爱弥斯": "UIResources/Common/Image/Luckdraw/T_Luckdraw_AiMiSi_UI.png",
    "玻色星仪": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050045_UI.png",
    "珂莱塔": "UIResources/Common/Image/Luckdraw/T_Luckdraw_kelaita_UI.png",
    "琳奈": "UIResources/Common/Image/Luckdraw/T_Luckdraw_linnai_UI.png",
    "琼枝冰绡": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050026_UI.png",
    "白昼之脊": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040056_UI.png",
    "白芷": "UIResources/Common/Image/Luckdraw/T_Luckdraw_bailian_UI.png",
    "相位涟漪": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030045_UI.png",
    "相里要": "UIResources/Common/Image/Luckdraw/T_Luckdraw_xiangliyao_UI.png",
    "秋水": "UIResources/Common/Image/Luckdraw/T_Luckdraw_qiushui_UI.png",
    "秧秧": "UIResources/Common/Image/Luckdraw/T_Luckdraw_yanyan_UI.png",
    "绯雪": "UIResources/Common/Image/Luckdraw/T_Luckdraw_FeiXue_UI.png",
    "维里奈": "UIResources/Common/Image/Luckdraw/T_Luckdraw_jueyuan_UI.png",
    "脉冲协臂": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040045_UI.png",
    "苍鳞千嶂": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010016_UI.png",
    "莫宁": "UIResources/Common/Image/Luckdraw/T_Luckdraw_MoNing_UI.png",
    "莫特斐": "UIResources/Common/Image/Luckdraw/T_Luckdraw_baer_UI.png",
    "菲比": "UIResources/Common/Image/Luckdraw/T_Luckdraw_feibi_UI.png",
    "行进序曲": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020024_UI.png",
    "袍泽之固": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040044_UI.png",
    "裁春": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020017_UI.png",
    "裁竹": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020066_UI.png",
    "西升": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020064_UI.png",
    "西格莉卡": "UIResources/Common/Image/Luckdraw/T_Luckdraw_XiGeLiKa_UI.png",
    "诸方玄枢": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040016_UI.png",
    "赝作的矮星": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050076_UI.png",
    "赞妮": "UIResources/Common/Image/Luckdraw/T_Luckdraw_zanni_UI.png",
    "赫奕流明": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020016_UI.png",
    "达妮娅": "UIResources/Common/Image/Luckdraw/T_Luckdraw_DaNiYa_UI.png",
    "远行者佩枪·洞察": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030043_UI.png",
    "远行者矩阵·探幽": "UIResources/Common/Image/Luckdraw/T_Luckdraw21050043_UI.png",
    "远行者臂铠·破": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040043_UI.png",
    "远行者迅刀·旅": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020043_UI.png",
    "远行者长刃·辟路": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010043_UI.png",
    "釉瑚": "UIResources/Common/Image/Luckdraw/T_Luckdraw_youhu_UI.png",
    "鉴心": "UIResources/Common/Image/Luckdraw/T_Luckdraw_jianxin_UI.png",
    "镭射切变": "UIResources/Common/Image/Luckdraw/T_Luckdraw21020045_UI.png",
    "长离": "UIResources/Common/Image/Luckdraw/T_Luckdraw_changli_UI.png",
    "陆·赫斯": "UIResources/Common/Image/Luckdraw/T_Luckdraw_LuHeSi_UI.png",
    "露帕": "UIResources/Common/Image/Luckdraw/T_Luckdraw_Lupa_UI.png",
    "飞逝": "UIResources/Common/Image/Luckdraw/T_Luckdraw21030064_UI.png",
    "驭冕铸雷之权": "UIResources/Common/Image/Luckdraw/T_Luckdraw21010046_UI.png",
    "骇行": "UIResources/Common/Image/Luckdraw/T_Luckdraw21040064_UI.png",
}
_portrait_dl_lock = threading.Lock()
def _ensure_portrait(name):
    """本地优先；缺失则按内联映射从 jsDelivr 下载并缓存到 _PORTRAIT_DIR/<name>.png。"""
    local = _PORTRAIT_MAP.get(name or "")
    if local and os.path.isfile(local):
        return local
    rel = _PORTRAIT_RELPATHS.get(name or "")
    if not rel:
        return None
    dest = os.path.join(_PORTRAIT_DIR, (name or "") + ".png")
    url = _PORTRAIT_BASE_URL + rel
    try:
        os.makedirs(_PORTRAIT_DIR, exist_ok=True)
    except Exception:
        pass
    try:
        import urllib.request, urllib.parse
        req = urllib.request.Request(urllib.parse.quote(url, safe=":/?&=#@%"), headers={"User-Agent": "ww-gacha"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        if len(data) < 2000:
            return None
        with open(dest, "wb") as _f:
            _f.write(data)
        _PORTRAIT_MAP[name] = dest
        return dest
    except Exception as _e:
        print("[ww_gacha] 立绘下载失败 %s: %s" % (name, _e), flush=True)
        return None



def _portrait_for(name):
    return _PORTRAIT_MAP.get(name or "")


def _paste_portrait(img, x, y, w, h, portrait_path):
    """把立绘（RGBA）cover 缩放并圆角贴入卡片主体区 (x, y+24) ~ (x+w, y+h-34)。"""
    try:
        pim = Image.open(portrait_path).convert("RGBA")
        pw, ph = pim.size
        if pw <= 0 or ph <= 0:
            return False
        top = y + 24
        bottom = y + h - 34
        ih = max(1, bottom - top)
        # cover 缩放
        scale = max(w / pw, ih / ph)
        nw, nh = max(1, int(pw * scale)), max(1, int(ph * scale))
        pim = pim.resize((nw, nh), Image.LANCZOS)
        cx = max(0, (nw - w) // 2)
        cy = max(0, (nh - ih) // 2)
        crop = pim.crop((cx, cy, cx + w, min(nh, cy + ih)))
        if crop.size[0] != w or crop.size[1] != ih:
            # 极端比例保护
            tmp = Image.new("RGBA", (w, ih), (0, 0, 0, 0))
            tmp.paste(crop, ((w - crop.size[0]) // 2, 0))
            crop = tmp
        # 圆角遮罩
        mask = Image.new("L", (w, ih), 0)
        ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (w - 1, ih - 1)],
                                                radius=10, fill=255)
        layer = Image.new("RGBA", (w, ih), (0, 0, 0, 0))
        layer.paste(crop, (0, 0))
        layer.putalpha(mask)
        img.paste(layer, (x, top), layer)
        return True
    except Exception as e:
        print("[ww_gacha] 贴立绘失败 %s: %s" % (portrait_path, e), flush=True)
        return False


def _draw_cell(img, draw, x, y, w, h, item, theme, is_up, portrait):
    """绘制单个抽卡结果格子（img 用于贴立绘，draw 用于矢量层）。"""
    # 底色渐变
    _hgrad_rect(draw, (x, y, x + w, y + h), theme["mid"], theme["bot"])
    # 边框
    draw.rectangle([(x, y), (x + w - 1, y + h - 1)], outline=theme["border"], width=2)
    # 立绘（若有，贴入主体区，覆盖底色）
    has_img = False
    if portrait and os.path.isfile(portrait):
        has_img = _paste_portrait(img, x, y, w, h, portrait)
    # 顶部条（覆盖在立绘上方）
    _hgrad_rect(draw, (x, y, x + w, y + 22), theme["top"], theme["mid"])
    # 边框重绘（立绘可能越界）
    draw.rectangle([(x, y), (x + w - 1, y + h - 1)], outline=theme["border"], width=2)
    # 右上角 UP 徽标
    if is_up:
        pad = 6
        up_w = 36
        up_box = (x + w - up_w - pad, y + pad, x + w - pad, y + pad + 22)
        draw.rectangle(up_box, fill=_UP_BG)
        uw, uh = draw.textbbox((0, 0), "UP", font=_F_DIG)[2:]
        draw.text(
            (up_box[0] + (up_box[2] - up_box[0] - uw) // 2,
             up_box[1] + (up_box[3] - up_box[1] - uh) // 2 - 1),
            "UP", fill=_UP_FG, font=_F_DIG,
        )
    # 星级（顶部居中，覆盖在顶部条上）
    star = _star_str(item.get("rarity"))
    sw, sh = draw.textbbox((0, 0), star, font=_F_DIG)[2:]
    draw.text(
        (x + (w - sw) // 2, y + 36),
        star, fill=theme["star"], font=_F_DIG,
    )
    # 物品名（无立绘时显示在中间，自动缩字；有立绘时显示在底部标签上方）
    name = (item.get("name") or "—")[:14]
    if not has_img:
        f, nw, nh = _fit_text(draw, name, _F_CJK, w - 16)
        if nw:
            draw.text(
                (x + (w - nw) // 2, y + 80),
                name, fill=theme["text"], font=f,
            )
    # 类型标签（底部圆角条）
    label = "角色" if item.get("type") == "character" else "武器"
    tag_h = 24
    tag_w = w - 24
    tx = x + 12
    ty = y + h - tag_h - 10
    draw.rounded_rectangle([(tx, ty), (tx + tag_w, ty + tag_h)],
                           radius=4, fill=theme["tag_bg"])
    lw, lh = draw.textbbox((0, 0), label, font=_F_CJK_SM)[2:]
    draw.text(
        (tx + (tag_w - lw) // 2, ty + (tag_h - lh) // 2 - 1),
        label, fill=theme["tag_fg"], font=_F_CJK_SM,
    )


def _draw_empty_cell(draw, x, y, w, h):
    """空槽位（用淡灰色）."""
    draw.rectangle([(x, y), (x + w - 1, y + h - 1)],
                   fill=(36, 30, 52), outline=(60, 50, 90), width=2)
    draw.text((x + w // 2 - 8, y + h // 2 - 8),
              "—", fill=(120, 110, 150), font=_F_CJK)


def _draw_progress_bar(draw, x, y, w, h, cur, total, fill_rgb, bg_rgb, label):
    """画一个保底进度条（左：标签文字  | 中：进度条  | 右：当前/总数）。"""
    # 底槽
    draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=h // 2, fill=bg_rgb)
    # 填充
    p = 0.0 if total <= 0 else max(0.0, min(1.0, cur / total))
    if p > 0:
        fw = max(2, int(w * p))
        draw.rounded_rectangle([(x, y), (x + fw, y + h)], radius=h // 2, fill=fill_rgb)
    # 边框
    draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=h // 2,
                           outline=(180, 180, 200), width=1)
    # 左：标签文字（位于进度条上方）
    label_text = label
    lw, lh = draw.textbbox((0, 0), label_text, font=_F_CJK)[2:]
    draw.text((x, y - lh - 4), label_text, fill=(220, 220, 235), font=_F_CJK)
    # 右：当前/总数（也位于进度条上方）
    right_text = "%d/%d" % (cur, total)
    rw, rh = draw.textbbox((0, 0), right_text, font=_F_CJK)[2:]
    draw.text((x + w - rw, y - rh - 4), right_text, fill=(220, 220, 235), font=_F_CJK)


def render_pulls_image(pool, results, pity):
    """核心：把一次抽卡结果渲染成 PNG bytes（720 宽，5x2 网格 + 进度条）。

    results 为 list[dict|None]，长度可能 1（单抽）/ 10（十连）。不足 10 个自动用空槽填充。
    """
    # 布局常量
    W = 720
    M = 24
    GAP = 8
    COLS = 5
    CELL_W = (W - 2 * M - (COLS - 1) * GAP) // COLS
    CELL_H = 168
    HEADER_H = 90
    PROGRESS_H = 96
    H = HEADER_H + 2 * CELL_H + GAP + PROGRESS_H + M

    img = _vgrad_bg(W, H)
    draw = ImageDraw.Draw(img)

    # === 头部 ===
    title = "鸣潮 · 模拟抽卡"
    tw, th = draw.textbbox((0, 0), title, font=_F_CJK_BIG)[2:]
    draw.text((M + 4, 18), title, fill=(255, 232, 160), font=_F_CJK_BIG)
    # 顶部右侧：卡池名
    pool_name = "卡池：%s" % (pool.name if pool else "")
    pw, ph = draw.textbbox((0, 0), pool_name, font=_F_CJK_SM)[2:]
    draw.text((W - M - pw - 4, 18 + (th - ph) // 2),
              pool_name, fill=(200, 210, 230), font=_F_CJK_SM)
    # 副标题
    sub = "Wuthering Waves · Simulator Gacha"
    sw, sh = draw.textbbox((0, 0), sub, font=_F_DIG)[2:]
    draw.text((M + 4, 18 + th + 2), sub, fill=(140, 145, 170), font=_F_DIG)

    # === 网格 ===
    grid_y = HEADER_H
    padded = list(results) + [None] * (10 - len(results))
    for idx, it in enumerate(padded[:10]):
        r = idx // COLS
        c = idx % COLS
        x = M + c * (CELL_W + GAP)
        y = grid_y + r * (CELL_H + GAP)
        if it:
            theme = _RARITY_THEME.get(it.get("rarity", "3star"),
                                      _RARITY_THEME["3star"])
            portrait = _ensure_portrait(it.get("name"))
            _draw_cell(img, draw, x, y, CELL_W, CELL_H, it, theme,
                       is_up=it["external_id"] in pool.up_ids if pool else False,
                       portrait=portrait)
        else:
            _draw_empty_cell(draw, x, y, CELL_W, CELL_H)

    # === 底部进度条 ===
    pb_top = grid_y + 2 * CELL_H + GAP + 12
    h5 = (pool.pp.get("5star", {}) or {}).get("hard_pity_pull", 80) if pool else 80
    h4 = (pool.pp.get("4star", {}) or {}).get("hard_pity_pull", 10) if pool else 10
    _draw_progress_bar(draw, M, pb_top, W - 2 * M, 14,
                       pity.get("pity_5", 0), h5,
                       (212, 175, 55), (50, 40, 22), "5★ 保底")
    _draw_progress_bar(draw, M, pb_top + 46, W - 2 * M, 14,
                       pity.get("pity_4", 0), h4,
                       (156, 122, 230), (40, 30, 64), "4★ 保底")

    # UP 提示（必出）
    flags = []
    if pity.get("g5"):
        flags.append(("5★ 下次必出 UP", (235, 60, 80)))
    if pity.get("g4"):
        flags.append(("4★ 下次必出 UP", (235, 60, 80)))
    if flags:
        x_cursor = M
        for txt, col in flags:
            f, fw, fh = _fit_text(draw, txt, _F_CJK_SM, W // 2)
            draw.rounded_rectangle(
                [(x_cursor, pb_top + 84), (x_cursor + fw + 18, pb_top + 84 + 22)],
                radius=4, fill=col,
            )
            draw.text((x_cursor + 9, pb_top + 84 + 3),
                      txt, fill=(255, 255, 255), font=f)
            x_cursor += fw + 30

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_pulls_image_safe(pool, results, pity):
    """带异常护栏的版本——失败返回 None（调用方回退到文本）。"""
    if not _HAS_PIL:
        return None
    try:
        return render_pulls_image(pool, results, pity)
    except Exception as e:
        print("[ww_gacha] 图片渲染异常: %s: %s" % (type(e).__name__, e), flush=True)
        import traceback
        traceback.print_exc()
        return None


# ----------------------------------------------------------------------------
# 物品解析：从 external_id 推导 type / name（无需数据库）
# ----------------------------------------------------------------------------
def _parse_external_id(eid):
    """cha_散华_4888 -> ('character', '散华')；wea_异响空灵_5f37 -> ('weapon', '异响空灵')。

    external_id 形如 <前缀>_<名称>_<哈希>：前缀 cha_=角色、wea_=武器；
    名称可能含 ·（如 暗夜长刃·玄明），哈希为末尾 _xxxx，用 rsplit 截断。
    """
    if eid.startswith("cha_"):
        item_type = "character"
        rest = eid[4:]
    elif eid.startswith("wea_"):
        item_type = "weapon"
        rest = eid[4:]
    else:
        item_type = "weapon"
        rest = eid
    if "_" in rest:
        name = rest.rsplit("_", 1)[0]
    else:
        name = rest
    return item_type, name


# ----------------------------------------------------------------------------
# 卡池：从预设 JSON 合成物品分组（items_by_rarity / up_items_by_rarity）
# ----------------------------------------------------------------------------
class GachaPool:
    """一个卡池。构造时即从 included_item_ids 合成物品 dict 并按稀有度/UP 分组。"""

    def __init__(self, raw):
        self.raw = raw
        self.name = raw.get("name", "未命名卡池")
        self.cp_id = raw.get("cp_id", "")
        self.ps = raw.get("probability_settings", {}) or {}
        self.pp = raw.get("probability_progression", {}) or {}
        self.rate_up = raw.get("rate_up_item_ids", {}) or {}
        self.included = raw.get("included_item_ids", {}) or {}
        self.enable = raw.get("enable", True)

        # rarity -> [item_dict]
        self.items_by_rarity = {}
        # rarity -> [item_dict]（仅 UP 物品）
        self.up_items_by_rarity = {}
        # 全部 UP 物品 external_id 集合（渲染 UP 标记用）
        self.up_ids = set()
        for rarity, ids in self.included.items():
            up_ids = set(self.rate_up.get(rarity, []) or [])
            for eid in ids:
                itype, name = _parse_external_id(eid)
                item = {
                    "external_id": eid,
                    "name": name,
                    "rarity": rarity,
                    "type": itype,
                    "affiliated_type": itype,
                }
                self.items_by_rarity.setdefault(rarity, []).append(item)
                if eid in up_ids:
                    self.up_items_by_rarity.setdefault(rarity, []).append(item)
                    self.up_ids.add(eid)

    # ---- 概率：五星 ----
    def calculate_rate_5star(self, rate_number):
        star_cfg = self.pp.get("5star", {}) or {}
        hard_pull = star_cfg.get("hard_pity_pull", 95)
        hard_rate = star_cfg.get("hard_pity_rate", 1.0)
        current = rate_number + 1
        if current >= hard_pull:
            return hard_rate
        final = self.ps.get("base_5star_rate", 0.008)
        soft = star_cfg.get("soft_pity", []) or []
        if not soft:
            return min(final, 1.0)
        soft = sorted(soft, key=lambda x: x["start_pull"])
        for interval in soft:
            start = interval["start_pull"]
            end = interval["end_pull"]
            increment = interval["increment"]
            if current >= start:
                steps = min(current, end) - start + 1
                final += steps * increment
                if current <= end:
                    break
            else:
                break
        return min(final, 1.0)

    # ---- 概率：四星 ----
    def calculate_rate_4star(self, rate_number):
        probs = self.pp.get("4star", {}) or {}
        hard_pull = probs.get("hard_pity_pull", 0)
        hard_rate = probs.get("hard_pity_rate", 1)
        base = self.ps.get("base_4star_rate", 0.06)
        current = rate_number + 1
        if current < hard_pull:
            return base
        # current == hard 或意外超过 hard，均按硬保底率返回（防御性，参考实现此处会抛异常）
        return hard_rate

    # ---- 核心：执行一次抽卡 ----
    def execute_pull(self, pity_5star, pity_4star, g5, g4):
        """返回 (item_dict|None, new_pity_5, new_pity_4, new_g5, new_g4)。

        算法严格移植自参考插件 GachaMechanics.execute_pull，仅把 Item 对象替换为 dict。
        """
        local_random = random.random()
        ps = self.ps
        up_5star_rate = ps.get("up_5star_rate", 0.5)
        up_4star_rate = ps.get("up_4star_rate", 0.5)
        # 四星角色占比（预设用 four_star_character_rate），武器占比 = 1 - 它
        char_rate = ps.get("four_star_character_rate", 0.5)
        weapon_rate = 1.0 - char_rate
        h4 = self.pp.get("4star", {}).get("hard_pity_pull", 10)
        h5 = self.pp.get("5star", {}).get("hard_pity_pull", 80)

        rate_up_5_ids = self.rate_up.get("5star", []) or []
        rate_up_4_ids = self.rate_up.get("4star", []) or []

        new_pity_5 = pity_5star
        new_pity_4 = pity_4star
        local_item = None

        if self.calculate_rate_5star(pity_5star) > local_random:
            # 抽到五星：重置五星保底；若同时到四星硬保底也重置四星
            new_pity_5 = 0
            if new_pity_4 == h4:
                new_pity_4 = 0
            local_item = self._get_item_with_fallback(
                base_rarity="5star",
                is_up=(not g5 and random.random() < up_5star_rate),
                fallback_path=["4star", "3star"],
            )
            if local_item and local_item["external_id"] in rate_up_5_ids:
                g5 = False
            else:
                g5 = True

        elif self.calculate_rate_4star(pity_4star) > local_random:
            # 抽到四星：重置四星保底，五星保底 +1
            new_pity_4 = 0
            new_pity_5 += 1
            item_type = "character" if random.random() > weapon_rate else "weapon"
            is_up = (not g4 and rate_up_4_ids and random.random() < up_4star_rate)
            local_item = self._get_item_with_fallback(
                base_rarity="4star",
                is_up=is_up,
                fallback_path=["3star", "5star"],
                item_type=item_type,
            )
            if is_up:
                g4 = False
            else:
                g4 = True

        else:
            # 三星：四星与五星保底均 +1
            new_pity_4 += 1
            new_pity_5 += 1
            local_item = self._get_item_with_fallback(
                base_rarity="3star",
                is_up=False,
                fallback_path=["4star", "5star"],
            )

        return local_item, new_pity_5, new_pity_4, g5, g4

    def _get_item_with_fallback(self, base_rarity, is_up, fallback_path, item_type=None):
        """多级优先级回退选物品（移植自 GachaMechanics._get_item_with_fallback）。"""
        priority = []
        if is_up:
            priority.append((base_rarity, True))
            priority.append((base_rarity, False))
        else:
            priority.append((base_rarity, False))
            priority.append((base_rarity, True))
        for fr in fallback_path:
            priority.append((fr, False))
            priority.append((fr, True))

        for rarity, is_up_item in priority:
            if is_up_item:
                candidates = self.up_items_by_rarity.get(rarity, [])
            else:
                candidates = self.items_by_rarity.get(rarity, [])
            if item_type:
                filtered = [c for c in candidates if c["type"] == item_type]
                if filtered:
                    candidates = filtered
            if candidates:
                return random.choice(candidates)

        # 极端兜底：从所有可用物品随机
        all_items = []
        for r in self.items_by_rarity:
            all_items.extend(self.items_by_rarity[r])
        for r in self.up_items_by_rarity:
            all_items.extend(self.up_items_by_rarity[r])
        seen = {}
        for it in all_items:
            seen[it["external_id"]] = it
        unique = list(seen.values())
        if unique:
            return random.choice(unique)
        return None


# ----------------------------------------------------------------------------
# 卡池加载（启动时一次性加载；插件热重载会重新 import 从而刷新）
# ----------------------------------------------------------------------------
_EMBEDDED_PRESETS = {
    "常驻武器池.json": '{\n  "cp_id": "d47efaeae752",\n  "name": "常驻武器池",\n  "probability_settings": {\n    "base_3star_rate": 0.932,\n    "base_4star_rate": 0.06,\n    "base_5star_rate": 0.008,\n    "four_star_character_rate": 0.25,\n    "up_4star_rate": 0,\n    "up_5star_rate": 0\n  },\n  "rate_up_item_ids": {\n    "4star": [],\n    "5star": [],\n    "3star": []\n  },\n  "included_item_ids": {\n    "3star": [\n      "wea_暗夜长刃·玄明_75d8",\n      "wea_源能长刃·测壹_bdef",\n      "wea_远行者长刃·辟路_76f5",\n      "wea_暗夜迅刀·黑闪_5292",\n      "wea_源能迅刀·测贰_c02e",\n      "wea_远行者迅刀·旅_b821",\n      "wea_暗夜佩枪·暗星_eb3b",\n      "wea_源能佩枪·测参_0a4f",\n      "wea_远行者佩枪·洞察_b5b4",\n      "wea_暗夜臂铠·夜芒_a314",\n      "wea_源能臂铠·测肆_f36c",\n      "wea_远行者臂铠·破_e23c",\n      "wea_源能音感仪·测五_4eca",\n      "wea_远行者矩阵·探幽_7307"\n    ],\n    "4star": [\n      "cha_散华_4888",\n      "cha_白芷_5511",\n      "cha_釉瑚_6253",\n      "cha_炽霞_1cba",\n      "cha_莫特斐_bcd0",\n      "cha_渊武_55e4",\n      "cha_灯灯_c425",\n      "cha_卜灵_c0f9",\n      "cha_秋水_1b68",\n      "cha_秧秧_400c",\n      "cha_丹瑾_6d1d",\n      "cha_桃祈_19b5",\n      "wea_异响空灵_5f37",\n      "wea_永夜长明_76bf",\n      "wea_东落_1962",\n      "wea_凋亡频移_1e77",\n      "wea_行进序曲_f511",\n      "wea_不归孤军_0160",\n      "wea_西升_eda7",\n      "wea_永续坍缩_bbae",\n      "wea_华彩乐段_2af2",\n      "wea_无眠烈火_f37d",\n      "wea_飞逝_dace",\n      "wea_悖论喷流_b977",\n      "wea_呼啸重音_2716",\n      "wea_袍泽之固_2ed1",\n      "wea_骇行_1392",\n      "wea_尘云旋臂_866b",\n      "wea_暗夜矩阵·暝光_af11",\n      "wea_奇幻变奏_cb77",\n      "wea_今州守望_fa3e",\n      "wea_异度_3042",\n      "wea_核熔星盘_8c7b"\n    ],\n    "5star": [\n      "cha_凌阳_c697",\n      "cha_折枝_0f4b",\n      "cha_珂莱塔_9250",\n      "cha_安可_c422",\n      "cha_长离_f225",\n      "cha_布兰特_fb76",\n      "cha_露帕_c1ca",\n      "cha_嘉贝莉娜_006c",\n      "cha_莫宁_8b8d",\n      "cha_卡卡罗_a38a",\n      "cha_吟霖_aa05",\n      "cha_相里要_2de1",\n      "cha_奥古斯塔_5370",\n      "cha_忌炎_21da",\n      "cha_鉴心_c6e7",\n      "cha_仇远_79a8",\n      "cha_夏空_358d",\n      "cha_卡提希娅_dc34",\n      "cha_尤诺_e9ef",\n      "cha_今汐_cb53",\n      "cha_维里奈_6ef9",\n      "cha_守岸人_55ce",\n      "cha_赞妮_a139",\n      "cha_菲比_f6b7",\n      "cha_琳奈_98d3",\n      "cha_椿_3681",\n      "cha_千咲_9473",\n      "cha_坎特蕾拉_3c67",\n      "cha_弗洛洛_e2ba",\n      "cha_洛可可_2355",\n      "wea_浩境粼光_4e1d",\n      "wea_苍鳞千嶂_fbcf",\n      "wea_时和岁稔_b04b",\n      "wea_焰痕_847b",\n      "wea_源能机锋_4456",\n      "wea_驭冕铸雷之权_a6b5",\n      "wea_县切_ef30",\n      "wea_宙算仪轨_2e71",\n      "wea_千古洑流_9615",\n      "wea_赫奕流明_d656",\n      "wea_裁春_b8d5",\n      "wea_不灭航路_f97b",\n      "wea_镭射切变_ce5e",\n      "wea_不屈命定之冠_c91c",\n      "wea_裁竹_8283",\n      "wea_停驻之烟_4ce3",\n      "wea_死与舞_4755",\n      "wea_林间的咏叹调_93b7",\n      "wea_光影双生_0b5a",\n      "wea_相位涟漪_e8c2",\n      "wea_溢彩荧辉_bd8e",\n      "wea_擎渊怒涛_2d45",\n      "wea_诸方玄枢_7320",\n      "wea_悲喜剧_b4cb",\n      "wea_焰光裁定_c3a5",\n      "wea_脉冲协臂_d0b7",\n      "wea_万物持存的注释_0b2b",\n      "wea_漪澜浮录_8d15",\n      "wea_掣傀之手_c530",\n      "wea_琼枝冰绡_05ca",\n      "wea_星序协响_f2af",\n      "wea_和光回唱_fc3d",\n      "wea_海的呢喃_ab69",\n      "wea_玻色星仪_92d8",\n      "wea_幽冥的忘忧章_704e"\n    ]\n  },\n  "probability_progression": {\n    "4star": {\n      "hard_pity_pull": 10,\n      "hard_pity_rate": 1,\n      "soft_pity": []\n    },\n    "5star": {\n      "hard_pity_pull": 80,\n      "hard_pity_rate": 1,\n      "soft_pity": [\n        {\n          "end_pull": 70,\n          "increment": 0.04,\n          "start_pull": 66\n        },\n        {\n          "end_pull": 75,\n          "increment": 0.08,\n          "start_pull": 71\n        },\n        {\n          "end_pull": 79,\n          "increment": 0.1,\n          "start_pull": 76\n        }\n      ]\n    }\n  },\n  "config_group": "default",\n  "enable": true\n}',
    "常驻角色池.json": '{\n  "cp_id": "e11ded092098",\n  "name": "常驻角色池",\n  "probability_settings": {\n    "base_3star_rate": 0.932,\n    "base_4star_rate": 0.06,\n    "base_5star_rate": 0.008,\n    "four_star_character_rate": 0.75,\n    "up_4star_rate": 0,\n    "up_5star_rate": 0\n  },\n  "rate_up_item_ids": {\n    "4star": [],\n    "5star": [],\n    "3star": []\n  },\n  "included_item_ids": {\n    "3star": [\n      "wea_暗夜长刃·玄明_75d8",\n      "wea_源能长刃·测壹_bdef",\n      "wea_远行者长刃·辟路_76f5",\n      "wea_暗夜迅刀·黑闪_5292",\n      "wea_源能迅刀·测贰_c02e",\n      "wea_远行者迅刀·旅_b821",\n      "wea_暗夜佩枪·暗星_eb3b",\n      "wea_源能佩枪·测参_0a4f",\n      "wea_远行者佩枪·洞察_b5b4",\n      "wea_暗夜臂铠·夜芒_a314",\n      "wea_源能臂铠·测肆_f36c",\n      "wea_远行者臂铠·破_e23c",\n      "wea_源能音感仪·测五_4eca",\n      "wea_远行者矩阵·探幽_7307"\n    ],\n    "4star": [\n      "cha_散华_4888",\n      "cha_白芷_5511",\n      "cha_釉瑚_6253",\n      "cha_炽霞_1cba",\n      "cha_莫特斐_bcd0",\n      "cha_渊武_55e4",\n      "cha_灯灯_c425",\n      "cha_卜灵_c0f9",\n      "cha_秋水_1b68",\n      "cha_秧秧_400c",\n      "cha_丹瑾_6d1d",\n      "cha_桃祈_19b5",\n      "wea_异响空灵_5f37",\n      "wea_永夜长明_76bf",\n      "wea_东落_1962",\n      "wea_凋亡频移_1e77",\n      "wea_行进序曲_f511",\n      "wea_不归孤军_0160",\n      "wea_西升_eda7",\n      "wea_永续坍缩_bbae",\n      "wea_华彩乐段_2af2",\n      "wea_无眠烈火_f37d",\n      "wea_飞逝_dace",\n      "wea_悖论喷流_b977",\n      "wea_呼啸重音_2716",\n      "wea_袍泽之固_2ed1",\n      "wea_骇行_1392",\n      "wea_尘云旋臂_866b",\n      "wea_暗夜矩阵·暝光_af11",\n      "wea_奇幻变奏_cb77",\n      "wea_今州守望_fa3e",\n      "wea_异度_3042",\n      "wea_核熔星盘_8c7b"\n    ],\n    "5star": [\n      "cha_凌阳_c697",\n      "cha_折枝_0f4b",\n      "cha_珂莱塔_9250",\n      "cha_安可_c422",\n      "cha_长离_f225",\n      "cha_布兰特_fb76",\n      "cha_露帕_c1ca",\n      "cha_嘉贝莉娜_006c",\n      "cha_莫宁_8b8d",\n      "cha_卡卡罗_a38a",\n      "cha_吟霖_aa05",\n      "cha_相里要_2de1",\n      "cha_奥古斯塔_5370",\n      "cha_忌炎_21da",\n      "cha_鉴心_c6e7",\n      "cha_仇远_79a8",\n      "cha_夏空_358d",\n      "cha_卡提希娅_dc34",\n      "cha_尤诺_e9ef",\n      "cha_今汐_cb53",\n      "cha_维里奈_6ef9",\n      "cha_守岸人_55ce",\n      "cha_赞妮_a139",\n      "cha_菲比_f6b7",\n      "cha_琳奈_98d3",\n      "cha_椿_3681",\n      "cha_千咲_9473",\n      "cha_坎特蕾拉_3c67",\n      "cha_弗洛洛_e2ba",\n      "cha_洛可可_2355",\n      "wea_浩境粼光_4e1d",\n      "wea_苍鳞千嶂_fbcf",\n      "wea_时和岁稔_b04b",\n      "wea_焰痕_847b",\n      "wea_源能机锋_4456",\n      "wea_驭冕铸雷之权_a6b5",\n      "wea_县切_ef30",\n      "wea_宙算仪轨_2e71",\n      "wea_千古洑流_9615",\n      "wea_赫奕流明_d656",\n      "wea_裁春_b8d5",\n      "wea_不灭航路_f97b",\n      "wea_镭射切变_ce5e",\n      "wea_不屈命定之冠_c91c",\n      "wea_裁竹_8283",\n      "wea_停驻之烟_4ce3",\n      "wea_死与舞_4755",\n      "wea_林间的咏叹调_93b7",\n      "wea_光影双生_0b5a",\n      "wea_相位涟漪_e8c2",\n      "wea_溢彩荧辉_bd8e",\n      "wea_擎渊怒涛_2d45",\n      "wea_诸方玄枢_7320",\n      "wea_悲喜剧_b4cb",\n      "wea_焰光裁定_c3a5",\n      "wea_脉冲协臂_d0b7",\n      "wea_万物持存的注释_0b2b",\n      "wea_漪澜浮录_8d15",\n      "wea_掣傀之手_c530",\n      "wea_琼枝冰绡_05ca",\n      "wea_星序协响_f2af",\n      "wea_和光回唱_fc3d",\n      "wea_海的呢喃_ab69",\n      "wea_玻色星仪_92d8",\n      "wea_幽冥的忘忧章_704e"\n    ]\n  },\n  "probability_progression": {\n    "4star": {\n      "hard_pity_pull": 10,\n      "hard_pity_rate": 1,\n      "soft_pity": []\n    },\n    "5star": {\n      "hard_pity_pull": 80,\n      "hard_pity_rate": 1,\n      "soft_pity": [\n        {\n          "end_pull": 70,\n          "increment": 0.04,\n          "start_pull": 66\n        },\n        {\n          "end_pull": 75,\n          "increment": 0.08,\n          "start_pull": 71\n        },\n        {\n          "end_pull": 79,\n          "increment": 0.1,\n          "start_pull": 76\n        }\n      ]\n    }\n  },\n  "config_group": "default",\n  "enable": true\n}',
    "自定义卡池-示例1.json": '{\n  "cp_id": "1b84608f742b",\n  "name": "自定义卡池-示例1",\n  "probability_settings": {\n    "base_3star_rate": 0.8400000000000001,\n    "base_4star_rate": 0.06,\n    "base_5star_rate": 0.1,\n    "four_star_character_rate": 0.75,\n    "up_4star_rate": 0.5,\n    "up_5star_rate": 1\n  },\n  "rate_up_item_ids": {\n    "4star": [\n      "cha_散华_1f21",\n      "cha_白芷_0981",\n      "cha_釉瑚_0c31",\n      "cha_散华_4888",\n      "cha_白芷_5511",\n      "cha_秧秧_400c"\n    ],\n    "5star": [\n      "cha_莫宁_8b8d"\n    ]\n  },\n  "included_item_ids": {\n    "3star": [\n      "wea_暗夜长刃·玄明_75d8",\n      "wea_源能长刃·测壹_bdef",\n      "wea_远行者长刃·辟路_76f5",\n      "wea_暗夜迅刀·黑闪_5292",\n      "wea_源能迅刀·测贰_c02e",\n      "wea_远行者迅刀·旅_b821",\n      "wea_暗夜佩枪·暗星_eb3b",\n      "wea_源能佩枪·测参_0a4f",\n      "wea_远行者佩枪·洞察_b5b4",\n      "wea_暗夜臂铠·夜芒_a314",\n      "wea_源能臂铠·测肆_f36c",\n      "wea_远行者臂铠·破_e23c",\n      "wea_源能音感仪·测五_4eca",\n      "wea_远行者矩阵·探幽_7307"\n    ],\n    "4star": [\n      "cha_散华_4888",\n      "cha_白芷_5511",\n      "cha_釉瑚_6253",\n      "cha_炽霞_1cba",\n      "cha_莫特斐_bcd0",\n      "cha_渊武_55e4",\n      "cha_灯灯_c425",\n      "cha_卜灵_c0f9",\n      "cha_秋水_1b68",\n      "cha_秧秧_400c",\n      "cha_丹瑾_6d1d",\n      "cha_桃祈_19b5",\n      "wea_异响空灵_5f37",\n      "wea_永夜长明_76bf",\n      "wea_东落_1962",\n      "wea_凋亡频移_1e77",\n      "wea_行进序曲_f511",\n      "wea_不归孤军_0160",\n      "wea_西升_eda7",\n      "wea_永续坍缩_bbae",\n      "wea_华彩乐段_2af2",\n      "wea_无眠烈火_f37d",\n      "wea_飞逝_dace",\n      "wea_悖论喷流_b977",\n      "wea_呼啸重音_2716",\n      "wea_袍泽之固_2ed1",\n      "wea_骇行_1392",\n      "wea_尘云旋臂_866b",\n      "wea_暗夜矩阵·暝光_af11",\n      "wea_奇幻变奏_cb77",\n      "wea_今州守望_fa3e",\n      "wea_异度_3042",\n      "wea_核熔星盘_8c7b"\n    ],\n    "5star": [\n      "cha_凌阳_c697",\n      "cha_安可_c422",\n      "cha_鉴心_c6e7",\n      "cha_卡卡罗_a38a",\n      "cha_维里奈_6ef9",\n      "cha_莫宁_8b8d"\n    ]\n  },\n  "probability_progression": {\n    "4star": {\n      "hard_pity_pull": 10,\n      "hard_pity_rate": 1,\n      "soft_pity": []\n    },\n    "5star": {\n      "hard_pity_pull": 80,\n      "hard_pity_rate": 1,\n      "soft_pity": [\n        {\n          "end_pull": 5,\n          "increment": 0.8,\n          "start_pull": 5\n        }\n      ]\n    }\n  },\n  "config_group": "example",\n  "enable": true\n}',
    "限定武器池-示例1.json": '{\n  "cp_id": "e9eb44ba55c2",\n  "name": "限定武器池-示例1",\n  "probability_settings": {\n    "base_3star_rate": 0.932,\n    "base_4star_rate": 0.06,\n    "base_5star_rate": 0.008,\n    "four_star_character_rate": 0.25,\n    "up_4star_rate": 0,\n    "up_5star_rate": 1\n  },\n  "rate_up_item_ids": {\n    "4star": [\n      "wea_奇幻变奏_cb77",\n      "wea_行进序曲_f511",\n      "wea_不归孤军_0160"\n    ],\n    "5star": [\n      "wea_宙算仪轨_2e71"\n    ]\n  },\n  "included_item_ids": {\n    "3star": [\n      "wea_暗夜长刃·玄明_75d8",\n      "wea_源能长刃·测壹_bdef",\n      "wea_远行者长刃·辟路_76f5",\n      "wea_暗夜迅刀·黑闪_5292",\n      "wea_源能迅刀·测贰_c02e",\n      "wea_远行者迅刀·旅_b821",\n      "wea_暗夜佩枪·暗星_eb3b",\n      "wea_源能佩枪·测参_0a4f",\n      "wea_远行者佩枪·洞察_b5b4",\n      "wea_暗夜臂铠·夜芒_a314",\n      "wea_源能臂铠·测肆_f36c",\n      "wea_远行者臂铠·破_e23c",\n      "wea_源能音感仪·测五_4eca",\n      "wea_远行者矩阵·探幽_7307"\n    ],\n    "4star": [\n      "cha_散华_4888",\n      "cha_白芷_5511",\n      "cha_釉瑚_6253",\n      "cha_炽霞_1cba",\n      "cha_莫特斐_bcd0",\n      "cha_渊武_55e4",\n      "cha_灯灯_c425",\n      "cha_卜灵_c0f9",\n      "cha_秋水_1b68",\n      "cha_秧秧_400c",\n      "cha_丹瑾_6d1d",\n      "cha_桃祈_19b5",\n      "wea_异响空灵_5f37",\n      "wea_永夜长明_76bf",\n      "wea_东落_1962",\n      "wea_凋亡频移_1e77",\n      "wea_行进序曲_f511",\n      "wea_不归孤军_0160",\n      "wea_西升_eda7",\n      "wea_永续坍缩_bbae",\n      "wea_华彩乐段_2af2",\n      "wea_无眠烈火_f37d",\n      "wea_飞逝_dace",\n      "wea_悖论喷流_b977",\n      "wea_呼啸重音_2716",\n      "wea_袍泽之固_2ed1",\n      "wea_骇行_1392",\n      "wea_尘云旋臂_866b",\n      "wea_暗夜矩阵·暝光_af11",\n      "wea_奇幻变奏_cb77",\n      "wea_今州守望_fa3e",\n      "wea_异度_3042",\n      "wea_核熔星盘_8c7b"\n    ],\n    "5star": [\n      "wea_宙算仪轨_2e71"\n    ]\n  },\n  "probability_progression": {\n    "4star": {\n      "hard_pity_pull": 10,\n      "hard_pity_rate": 1,\n      "soft_pity": []\n    },\n    "5star": {\n      "hard_pity_pull": 80,\n      "hard_pity_rate": 1,\n      "soft_pity": [\n        {\n          "end_pull": 70,\n          "increment": 0.04,\n          "start_pull": 66\n        },\n        {\n          "end_pull": 75,\n          "increment": 0.08,\n          "start_pull": 71\n        },\n        {\n          "end_pull": 79,\n          "increment": 0.1,\n          "start_pull": 76\n        }\n      ]\n    }\n  },\n  "config_group": "example",\n  "enable": true\n}',
    "限定角色池-示例1.json": '{\n  "cp_id": "ce119ed6ba9b",\n  "name": "限定角色池-示例1",\n  "probability_settings": {\n    "base_3star_rate": 0.932,\n    "base_4star_rate": 0.06,\n    "base_5star_rate": 0.008,\n    "four_star_character_rate": 0.75,\n    "up_4star_rate": 0.5,\n    "up_5star_rate": 0.5\n  },\n  "rate_up_item_ids": {\n    "4star": [\n      "cha_秧秧_a5b4",\n      "cha_卜灵_d5f7",\n      "cha_秋水_98e5",\n      "cha_秧秧_400c",\n      "cha_散华_4888",\n      "cha_白芷_5511"\n    ],\n    "5star": [\n      "cha_守岸人_ff48",\n      "cha_莫宁_8b8d"\n    ]\n  },\n  "included_item_ids": {\n    "3star": [\n      "wea_暗夜长刃·玄明_75d8",\n      "wea_源能长刃·测壹_bdef",\n      "wea_远行者长刃·辟路_76f5",\n      "wea_暗夜迅刀·黑闪_5292",\n      "wea_源能迅刀·测贰_c02e",\n      "wea_远行者迅刀·旅_b821",\n      "wea_暗夜佩枪·暗星_eb3b",\n      "wea_源能佩枪·测参_0a4f",\n      "wea_远行者佩枪·洞察_b5b4",\n      "wea_暗夜臂铠·夜芒_a314",\n      "wea_源能臂铠·测肆_f36c",\n      "wea_远行者臂铠·破_e23c",\n      "wea_源能音感仪·测五_4eca",\n      "wea_远行者矩阵·探幽_7307"\n    ],\n    "4star": [\n      "cha_散华_4888",\n      "cha_白芷_5511",\n      "cha_釉瑚_6253",\n      "cha_炽霞_1cba",\n      "cha_莫特斐_bcd0",\n      "cha_渊武_55e4",\n      "cha_灯灯_c425",\n      "cha_卜灵_c0f9",\n      "cha_秋水_1b68",\n      "cha_秧秧_400c",\n      "cha_丹瑾_6d1d",\n      "cha_桃祈_19b5",\n      "wea_异响空灵_5f37",\n      "wea_永夜长明_76bf",\n      "wea_东落_1962",\n      "wea_凋亡频移_1e77",\n      "wea_行进序曲_f511",\n      "wea_不归孤军_0160",\n      "wea_西升_eda7",\n      "wea_永续坍缩_bbae",\n      "wea_华彩乐段_2af2",\n      "wea_无眠烈火_f37d",\n      "wea_飞逝_dace",\n      "wea_悖论喷流_b977",\n      "wea_呼啸重音_2716",\n      "wea_袍泽之固_2ed1",\n      "wea_骇行_1392",\n      "wea_尘云旋臂_866b",\n      "wea_暗夜矩阵·暝光_af11",\n      "wea_奇幻变奏_cb77",\n      "wea_今州守望_fa3e",\n      "wea_异度_3042",\n      "wea_核熔星盘_8c7b"\n    ],\n    "5star": [\n      "cha_守岸人_ff48",\n      "cha_凌阳_9dec",\n      "cha_安可_11de",\n      "cha_鉴心_a8f5",\n      "cha_卡卡罗_656b",\n      "cha_维里奈_c2c4",\n      "cha_莫宁_8b8d",\n      "cha_凌阳_c697",\n      "cha_安可_c422",\n      "cha_鉴心_c6e7",\n      "cha_卡卡罗_a38a",\n      "cha_维里奈_6ef9"\n    ]\n  },\n  "probability_progression": {\n    "4star": {\n      "hard_pity_pull": 10,\n      "hard_pity_rate": 1,\n      "soft_pity": []\n    },\n    "5star": {\n      "hard_pity_pull": 80,\n      "hard_pity_rate": 1,\n      "soft_pity": [\n        {\n          "end_pull": 70,\n          "increment": 0.04,\n          "start_pull": 66\n        },\n        {\n          "end_pull": 75,\n          "increment": 0.08,\n          "start_pull": 71\n        },\n        {\n          "end_pull": 79,\n          "increment": 0.1,\n          "start_pull": 76\n        }\n      ]\n    }\n  },\n  "config_group": "example",\n  "enable": true\n}',
    "默认卡池.json": '{\n  "cp_id": "fd571cd10578",\n  "name": "默认卡池",\n  "probability_settings": {\n    "base_3star_rate": 0.932,\n    "base_4star_rate": 0.06,\n    "base_5star_rate": 0.008,\n    "four_star_character_rate": 0.5,\n    "up_4star_rate": 0.8,\n    "up_5star_rate": 0\n  },\n  "rate_up_item_ids": {\n    "3star": [],\n    "4star": [\n      "cha_散华_4888",\n      "cha_白芷_5511",\n      "cha_釉瑚_6253",\n      "cha_炽霞_1cba",\n      "cha_莫特斐_bcd0",\n      "cha_渊武_55e4",\n      "cha_灯灯_c425",\n      "cha_卜灵_c0f9",\n      "cha_秋水_1b68",\n      "cha_秧秧_400c",\n      "cha_丹瑾_6d1d",\n      "cha_桃祈_19b5",\n      "wea_异响空灵_5f37",\n      "wea_永夜长明_76bf",\n      "wea_东落_1962",\n      "wea_凋亡频移_1e77",\n      "wea_行进序曲_f511",\n      "wea_不归孤军_0160",\n      "wea_西升_eda7",\n      "wea_永续坍缩_bbae",\n      "wea_华彩乐段_2af2",\n      "wea_无眠烈火_f37d",\n      "wea_飞逝_dace",\n      "wea_悖论喷流_b977",\n      "wea_呼啸重音_2716",\n      "wea_袍泽之固_2ed1",\n      "wea_骇行_1392",\n      "wea_尘云旋臂_866b",\n      "wea_暗夜矩阵·暝光_af11",\n      "wea_奇幻变奏_cb77",\n      "wea_今州守望_fa3e",\n      "wea_异度_3042",\n      "wea_核熔星盘_8c7b"\n    ],\n    "5star": []\n  },\n  "included_item_ids": {\n    "3star": [\n      "wea_暗夜长刃·玄明_75d8",\n      "wea_源能长刃·测壹_bdef",\n      "wea_远行者长刃·辟路_76f5",\n      "wea_暗夜迅刀·黑闪_5292",\n      "wea_源能迅刀·测贰_c02e",\n      "wea_远行者迅刀·旅_b821",\n      "wea_暗夜佩枪·暗星_eb3b",\n      "wea_源能佩枪·测参_0a4f",\n      "wea_远行者佩枪·洞察_b5b4",\n      "wea_暗夜臂铠·夜芒_a314",\n      "wea_源能臂铠·测肆_f36c",\n      "wea_远行者臂铠·破_e23c",\n      "wea_源能音感仪·测五_4eca",\n      "wea_远行者矩阵·探幽_7307"\n    ],\n    "4star": [\n      "cha_散华_4888",\n      "cha_白芷_5511",\n      "cha_釉瑚_6253",\n      "cha_炽霞_1cba",\n      "cha_莫特斐_bcd0",\n      "cha_渊武_55e4",\n      "cha_灯灯_c425",\n      "cha_卜灵_c0f9",\n      "cha_秋水_1b68",\n      "cha_秧秧_400c",\n      "cha_丹瑾_6d1d",\n      "cha_桃祈_19b5",\n      "wea_异响空灵_5f37",\n      "wea_永夜长明_76bf",\n      "wea_东落_1962",\n      "wea_凋亡频移_1e77",\n      "wea_行进序曲_f511",\n      "wea_不归孤军_0160",\n      "wea_西升_eda7",\n      "wea_永续坍缩_bbae",\n      "wea_华彩乐段_2af2",\n      "wea_无眠烈火_f37d",\n      "wea_飞逝_dace",\n      "wea_悖论喷流_b977",\n      "wea_呼啸重音_2716",\n      "wea_袍泽之固_2ed1",\n      "wea_骇行_1392",\n      "wea_尘云旋臂_866b",\n      "wea_暗夜矩阵·暝光_af11",\n      "wea_奇幻变奏_cb77",\n      "wea_今州守望_fa3e",\n      "wea_异度_3042",\n      "wea_核熔星盘_8c7b"\n    ],\n    "5star": [\n      "cha_凌阳_c697",\n      "cha_折枝_0f4b",\n      "cha_珂莱塔_9250",\n      "cha_安可_c422",\n      "cha_长离_f225",\n      "cha_布兰特_fb76",\n      "cha_露帕_c1ca",\n      "cha_嘉贝莉娜_006c",\n      "cha_莫宁_8b8d",\n      "cha_卡卡罗_a38a",\n      "cha_吟霖_aa05",\n      "cha_相里要_2de1",\n      "cha_奥古斯塔_5370",\n      "cha_忌炎_21da",\n      "cha_鉴心_c6e7",\n      "cha_仇远_79a8",\n      "cha_夏空_358d",\n      "cha_卡提希娅_dc34",\n      "cha_尤诺_e9ef",\n      "cha_今汐_cb53",\n      "cha_维里奈_6ef9",\n      "cha_守岸人_55ce",\n      "cha_赞妮_a139",\n      "cha_菲比_f6b7",\n      "cha_琳奈_98d3",\n      "cha_椿_3681",\n      "cha_千咲_9473",\n      "cha_坎特蕾拉_3c67",\n      "cha_弗洛洛_e2ba",\n      "cha_洛可可_2355",\n      "wea_浩境粼光_4e1d",\n      "wea_苍鳞千嶂_fbcf",\n      "wea_时和岁稔_b04b",\n      "wea_焰痕_847b",\n      "wea_源能机锋_4456",\n      "wea_驭冕铸雷之权_a6b5",\n      "wea_县切_ef30",\n      "wea_宙算仪轨_2e71",\n      "wea_千古洑流_9615",\n      "wea_赫奕流明_d656",\n      "wea_裁春_b8d5",\n      "wea_不灭航路_f97b",\n      "wea_镭射切变_ce5e",\n      "wea_不屈命定之冠_c91c",\n      "wea_裁竹_8283",\n      "wea_停驻之烟_4ce3",\n      "wea_死与舞_4755",\n      "wea_林间的咏叹调_93b7",\n      "wea_光影双生_0b5a",\n      "wea_相位涟漪_e8c2",\n      "wea_溢彩荧辉_bd8e",\n      "wea_擎渊怒涛_2d45",\n      "wea_诸方玄枢_7320",\n      "wea_悲喜剧_b4cb",\n      "wea_焰光裁定_c3a5",\n      "wea_脉冲协臂_d0b7",\n      "wea_万物持存的注释_0b2b",\n      "wea_漪澜浮录_8d15",\n      "wea_掣傀之手_c530",\n      "wea_琼枝冰绡_05ca",\n      "wea_星序协响_f2af",\n      "wea_和光回唱_fc3d",\n      "wea_海的呢喃_ab69",\n      "wea_玻色星仪_92d8",\n      "wea_幽冥的忘忧章_704e"\n    ]\n  },\n  "probability_progression": {\n    "4star": {\n      "hard_pity_pull": 10,\n      "hard_pity_rate": 1,\n      "soft_pity": []\n    },\n    "5star": {\n      "hard_pity_pull": 80,\n      "hard_pity_rate": 1,\n      "soft_pity": [\n        {\n          "end_pull": 70,\n          "increment": 0.04,\n          "start_pull": 66\n        },\n        {\n          "end_pull": 75,\n          "increment": 0.08,\n          "start_pull": 71\n        },\n        {\n          "end_pull": 79,\n          "increment": 0.1,\n          "start_pull": 76\n        }\n      ]\n    }\n  },\n  "config_group": "default",\n  "enable": true\n}',
}

def _load_pools():
    pools = {}
    def _add(raw):
        if isinstance(raw, str):
            try:
                raw = _json.loads(raw)
            except Exception as _e:
                print("[ww_gacha] 内联预设解析失败: %s" % _e, flush=True)
                return
        if not raw.get("name") or not raw.get("enable", True):
            return
        try:
            pool = GachaPool(raw)
        except Exception as _e:
            print("[ww_gacha] 卡池构造失败 %s: %s" % (raw.get("name"), _e), flush=True)
            return
        pools[pool.name] = pool
    # 内联预设优先（市场分发保证可用，无需外部文件）
    for _fn, _raw in _EMBEDDED_PRESETS.items():
        _add(_raw)
    # 本地 ww_gacha_data/ 若存在则用文件覆盖/补充（本地开发或后续更新）
    if os.path.isdir(_PRESET_DIR):
        try:
            for _fn in sorted(os.listdir(_PRESET_DIR)):
                if not _fn.endswith(".json"):
                    continue
                _fp = os.path.join(_PRESET_DIR, _fn)
                try:
                    with io.open(_fp, "r", encoding="utf-8-sig", errors="replace") as _f:
                        _raw = _json.loads(_f.read())
                except Exception as _e:
                    print("[ww_gacha] 预设解析失败 %s: %s" % (_fn, _e), flush=True)
                    continue
                _add(_raw)
        except Exception as _e:
            print("[ww_gacha] 加载卡池目录失败: %s" % _e, flush=True)
    return pools

_POOLS = _load_pools()


def _pool_names():
    return sorted(_POOLS.keys())


def _resolve_pool(keyword):
    """按名称精确/包含匹配卡池；返回 GachaPool 或 None。"""
    if not keyword:
        return None
    if keyword in _POOLS:
        return _POOLS[keyword]
    for name in _pool_names():
        if keyword in name or name in keyword:
            return _POOLS[name]
    return None


# ----------------------------------------------------------------------------
# 状态持久化（每用户保底计数 + 当前卡池，原子写）
# ----------------------------------------------------------------------------
def _load_state():
    try:
        if os.path.isfile(_STATE_FILE):
            with io.open(_STATE_FILE, "r", encoding="utf-8-sig", errors="replace") as f:
                return _json.loads(f.read()) or {}
    except Exception:
        pass
    return {}


def _save_state(state):
    try:
        if not os.path.isdir(_DATA_DIR):
            os.makedirs(_DATA_DIR, exist_ok=True)
        tmp = _STATE_FILE + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(_json.dumps(state, ensure_ascii=False, indent=2))
        os.replace(tmp, _STATE_FILE)
    except Exception as e:
        print("[ww_gacha] 状态保存失败: %s" % e, flush=True)


def _default_pool_name():
    names = _pool_names()
    return names[0] if names else None


def _get_user_state(state, storage_id):
    """返回用户记录 dict（含 current + pools）。不存在则按默认卡池初始化。"""
    rec = state.get(storage_id)
    if not isinstance(rec, dict):
        rec = {"current": _default_pool_name(), "pools": {}}
        state[storage_id] = rec
    if not rec.get("current") or rec["current"] not in _POOLS:
        rec["current"] = _default_pool_name()
    if "pools" not in rec or not isinstance(rec["pools"], dict):
        rec["pools"] = {}
    return rec


def _get_pity(rec, pool_name):
    p = rec["pools"].get(pool_name)
    if not isinstance(p, dict):
        p = {"pity_5": 0, "pity_4": 0, "g5": False, "g4": False}
        rec["pools"][pool_name] = p
    # 兜底字段
    p.setdefault("pity_5", 0)
    p.setdefault("pity_4", 0)
    p.setdefault("g5", False)
    p.setdefault("g4", False)
    return p


# ----------------------------------------------------------------------------
# 渲染
# ----------------------------------------------------------------------------
def _stars(rarity):
    try:
        return "★" * int(str(rarity)[0])
    except Exception:
        return "☆"


def _kind_label(item):
    return "角色" if item.get("type") == "character" else "武器"


def _render_pulls(pool, results, pity):
    h5 = pool.pp.get("5star", {}).get("hard_pity_pull", 80)
    h4 = pool.pp.get("4star", {}).get("hard_pity_pull", 10)
    lines = ["【鸣潮·模拟抽卡】卡池：%s" % pool.name]
    for i, item in enumerate(results, 1):
        if not item:
            lines.append("  第%d抽：—（无物品）" % i)
            continue
        up = " (UP!)" if item["external_id"] in pool.up_ids else ""
        lines.append("  第%d抽 %s %s [%s]%s" % (
            i, _stars(item["rarity"]), item["name"], _kind_label(item), up))
    lines.append("— 保底：5★ %d/%d，4★ %d/%d%s%s" % (
        pity["pity_5"], h5, pity["pity_4"], h4,
        " · 5★必出UP" if pity["g5"] else "",
        " · 4★必出UP" if pity["g4"] else "",
    ))
    return "\n".join(lines)


_HELP_TEXT = (
    "【鸣潮模拟抽卡 · 用法】\n"
    "· 鸣潮单抽 —— 抽 1 次\n"
    "· 鸣潮十连 —— 抽 10 次\n"
    "· 鸣潮卡池 —— 查看可用卡池\n"
    "· 鸣潮卡池 <名称> —— 切换卡池（如：鸣潮卡池 默认卡池）\n"
    "· 鸣潮状态 —— 查看当前保底进度\n"
    "· 鸣潮重置 —— 重置当前卡池保底\n"
    "说明：基于鸣潮抽卡概率（5★ 软保底 66~79 抽、硬保底 80 抽；4★ 硬保底 10 抽），结果随机仅供娱乐。"
)


# ----------------------------------------------------------------------------
# 命令分发
# ----------------------------------------------------------------------------
async def handle(ctx) -> bool:
    content = (ctx.content or "").strip()
    if content.startswith("#"):
        content = content[1:].strip()
    if not content.startswith(_TRIGGER):
        return False

    rest = content[len(_TRIGGER):].strip()

    # 帮助
    if rest in ("", "帮助", "help", "用法", "菜单"):
        if not _POOLS:
            await ctx.reply("❌ 鸣潮抽卡：未找到任何卡池预设（请检查 plugins/ww_gacha_data/）。")
            return True
        await ctx.reply(_HELP_TEXT + "\n\n当前可用卡池：\n" + "\n".join("  · " + n for n in _pool_names()))
        return True

    # 卡池列表
    if rest == "卡池":
        if not _POOLS:
            await ctx.reply("❌ 鸣潮抽卡：未找到任何卡池预设。")
            return True
        await ctx.reply("【鸣潮·可用卡池】\n" + "\n".join("  · " + n for n in _pool_names())
                        + "\n切换卡池：鸣潮卡池 <名称>")
        return True

    # 切换卡池
    if rest.startswith("卡池"):
        kw = rest[2:].strip()
        if not kw:
            await ctx.reply("请指定卡池名称，如：鸣潮卡池 默认卡池")
            return True
        pool = _resolve_pool(kw)
        if pool is None:
            await ctx.reply("❌ 未找到卡池「%s」。发送「鸣潮卡池」查看可用卡池。" % kw)
            return True
        with _STATE_LOCK:
            state = _load_state()
            rec = _get_user_state(state, ctx.storage_id)
            rec["current"] = pool.name
            _get_pity(rec, pool.name)
            _save_state(state)
        await ctx.reply("✅ 已切换卡池为「%s」。" % pool.name)
        return True

    # 状态 / 保底
    if rest in ("状态", "保底", "进度"):
        with _STATE_LOCK:
            state = _load_state()
            rec = _get_user_state(state, ctx.storage_id)
            pool = _POOLS.get(rec["current"])
            if pool is None:
                await ctx.reply("❌ 当前没有可用卡池。")
                return True
            pity = _get_pity(rec, pool.name)
            h5 = pool.pp.get("5star", {}).get("hard_pity_pull", 80)
            h4 = pool.pp.get("4star", {}).get("hard_pity_pull", 10)
        await ctx.reply(
            "【鸣潮·保底进度】卡池：%s\n5★ 距保底 %d/%d%s\n4★ 距保底 %d/%d%s" % (
                pool.name, pity["pity_5"], h5,
                "（下次必出UP）" if pity["g5"] else "",
                pity["pity_4"], h4,
                "（下次必出UP）" if pity["g4"] else "",
            )
        )
        return True

    # 重置
    if rest in ("重置", "清空", "重置保底"):
        with _STATE_LOCK:
            state = _load_state()
            rec = _get_user_state(state, ctx.storage_id)
            pool = _POOLS.get(rec["current"])
            if pool is None:
                await ctx.reply("❌ 当前没有可用卡池。")
                return True
            rec["pools"][pool.name] = {"pity_5": 0, "pity_4": 0, "g5": False, "g4": False}
            _save_state(state)
        await ctx.reply("✅ 已重置卡池「%s」的保底进度。" % pool.name)
        return True

    # 单抽
    if rest in ("单抽", "抽1", "1抽", "单"):
        return await _do_pull(ctx, 1)

    # 十连
    if rest in ("十连", "十连抽", "10连", "抽10", "十"):
        return await _do_pull(ctx, 10)

    # 未知子命令
    await ctx.reply("❓ 未识别的鸣潮指令「%s」。发送「鸣潮」查看用法。" % rest)
    return True


async def _do_pull(ctx, count):
    if not _POOLS:
        await ctx.reply("❌ 鸣潮抽卡：未找到任何卡池预设。")
        return True
    with _STATE_LOCK:
        state = _load_state()
        rec = _get_user_state(state, ctx.storage_id)
        pool = _POOLS.get(rec["current"])
        if pool is None:
            await ctx.reply("❌ 当前没有可用卡池。")
            return True
        pity = _get_pity(rec, pool.name)
        results = []
        for _ in range(count):
            item, pity["pity_5"], pity["pity_4"], pity["g5"], pity["g4"] = pool.execute_pull(
                pity["pity_5"], pity["pity_4"], pity["g5"], pity["g4"])
            results.append(item)
        _save_state(state)

    # 1) 尝试发图片（只保留图片，不带文字摘要）
    summary = _render_pulls(pool, results, pity)
    png = render_pulls_image_safe(pool, results, pity)
    if png:
        sent = await _send_image(ctx, png, content="")
        if not sent:
            # 发图失败回退文本
            await ctx.reply(summary)
        return True

    # 2) 降级：纯文本
    await ctx.reply(summary)
    return True


async def _send_image(ctx, image_bytes, content=""):
    """通过 modules.common.send_local_image_for_scene 发送图片 bytes（场景无关）。
    返回 True/False；channel 等不支持图片的场景静默降级。"""
    try:
        from modules.common import send_local_image_for_scene
    except Exception as e:
        print("[ww_gacha] 导入 send_local_image_for_scene 失败: %s" % e, flush=True)
        return False
    try:
        api = getattr(ctx, "api", None)
        scene = getattr(ctx, "scene", "") or ""
        target_id = getattr(ctx, "target_id", "") or ""
        if not api or not scene or not target_id:
            return False
        res = await send_local_image_for_scene(
            api, scene, target_id, image_bytes,
            msg_id=getattr(ctx, "msg_id", None),
            content=content or "",
        )
        # 视作发送失败：函数返回 None 或抛出
        return bool(res)
    except Exception as e:
        print("[ww_gacha] 发送图片异常: %s: %s" % (type(e).__name__, e), flush=True)
        return False
