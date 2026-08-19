# 小流萤插件市场

本目录是「小流萤」QQ 机器人的**远程插件仓库内容**，整体上传到 GitHub
后即作为控制台「插件市场」的远程来源（默认仓库：`GS240186/firefiy-QQofficial-bot-piugins`）。

## 结构

```
plugins-market/
├── index.json              # 市场索引（富索引，含 name/description/category/priority/files）
├── README.md
│
├── ── 单文件插件（kind=file）──
├── fun_qa.py / .meta.json       # ✅ 独立：内联问答会话，仅依赖 botpy SDK
├── starrail.py / .meta.json     # ✅ 独立：内联图片发送，仅依赖 botpy SDK
├── wife_today.py / .meta.json   # ✅ 独立：内联图片发送，仅依赖 botpy SDK
├── ww_gacha.py / .meta.json     # ✅ 独立：内联图片发送 + ww_gacha_data/ 数据目录
├── genshin.py / .meta.json      # ⚠️ 需主项目 lib.genshin_panel_miao
├── genshin_miao.py / .meta.json # ⚠️ 需主项目 lib + 本机 Yunzai 资源
│
├── ── 目录包插件（kind=dir，<key>/manifest.json + main.py）──
├── _common/                     # 🔗 共享库（game_core/image_core/study_core/tools_core/video_core）
├── checkin/                     # ✅ 独立：签到与积分
├── chime/                       # ✅ 独立：整点报时
├── group_admin/                 # ✅ 独立：群管与入群欢迎
├── music/                       # ✅ 独立：点歌与音乐
├── novel/                       # ✅ 独立：在线小说阅读
├── tool_weather/  ... tool_word/    # 🔗 工具×8（依赖 _common）
├── study_driving/ ... study_quiz/    # 🔗 学习×4（依赖 _common）
├── image_acg/    ... image_yscos/   # 🔗 图片×7（依赖 _common）
├── video_bianzhuang/ ... video_youxi/ # 🔗 视频×6（依赖 _common）
└── game_daanzi/  ... game_horoscope/  # 🔗 娱乐×7（依赖 _common）
```

## 依赖说明

| 标记 | 含义 |
|------|------|
| ✅ 独立 | 仅依赖 botpy SDK + 标准库，下载即用 |
| 🔗 依赖 _common | 目录包插件通过 `from _common.xxx import` 引用共享库；安装时自动下载 `_common/` |
| ⚠️ 需主项目 | 依赖 `lib.genshin_panel_miao` + 本机 Yunzai，无法独立运行 |

## index.json 格式

```json
{
  "version": 4,
  "plugins": [
    {
      "key": "tool_weather",
      "path": "tool_weather/main.py",
      "kind": "dir",
      "files": ["main.py", "manifest.json"],
      "name": "工具·天气",
      "description": "发送「天气 城市」查询天气",
      "category": "tool",
      "priority": 20,
      "requires_common": true
    },
    {
      "key": "fun_qa",
      "path": "fun_qa.py",
      "name": "趣味问答",
      "category": "chat",
      "priority": 500
    }
  ]
}
```

- `kind` 省略时自动按 `path` 结尾判断：`/main.py` → `dir`，否则 `file`
- `files` 列出目录包内所有文件（相对路径），供远程安装逐个下载
- `requires_common: true` 表示依赖 `_common/` 共享库，安装时自动拉取
- 富索引内联 `name`/`description`/`category`/`priority`，无需额外请求 meta.json
