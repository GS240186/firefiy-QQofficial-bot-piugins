# 小流萤 Bot 插件市场仓库

为 [小流萤 bot](https://github.com/...) 提供远程插件安装源。

## 仓库地址

- **gitee (主用,国内)**: https://gitee.com/geng-dan/firefiy-qqofficial-bot-piugins/raw/main
- **GitHub (镜像)**: https://raw.githubusercontent.com/GS240186/firefiy-QQofficial-bot-piugins/main/

## 目录结构

```
firefiy-qqofficial-bot-piugins/
├── index.json              # 插件目录索引（43 个插件）
├── _common/                # 共享库（32 个目录包插件依赖）
├── <key>/                  # 目录包插件（37 个）
│   ├── main.py             # 入口
│   └── manifest.json       # 元数据
└── <key>.py                # 单文件插件（6 个）
```

## 插件统计

- **总计**: 44 个插件
- **目录包**: 37 个
- **单文件**: 7 个
- **依赖 _common**: 32 个
- **fun_qa 已拆分**: fun_brainteaser(脑筋急转弯) + fun_riddle(猜谜语)

## 安装到 bot

在 bot 控制台「插件市场」页，配置仓库地址为本仓库的 raw 链接：
```
https://gitee.com/geng-dan/firefiy-qqofficial-bot-piugins/raw/main
```

然后在插件市场页点击「刷新」即可拉取最新目录。

## 镜像（备份）

- jsDelivr CDN: `https://cdn.jsdelivr.net/gh/GS240186/firefiy-QQofficial-bot-piugins@main/`
- raw.githubusercontent.com: `https://raw.githubusercontent.com/GS240186/firefiy-QQofficial-bot-piugins/main/`

## 插件分类

| 分类 | 数量 | 说明 |
|------|------|------|
| life | 1 | 签到 |
| tool | 9 | 工具类(疾病/导航/旅游/视频解析/王者/垃圾分类/天气/单词) |
| study | 4 | 学习类(驾考/数学/古诗文/知识问答) |
| music | 1 | 音乐 |
| video | 6 | 视频推送(变装/cos/风景/漫剪/帅哥/游戏) |
| image | 7 | 图片(二次元/壁纸/小姐姐/随机/风景/原神/原神cos) |
| game | 7 | 娱乐游戏(成语/五子棋/象棋/求签/塔罗/答案书/运势) |
| novel | 1 | 小说 |
| admin | 2 | 群管/整点报时 |
| chat/fun | 2 | 趣味问答/今日老婆 |
| game | 3 | 原神/星铁/鸣潮(需主项目) |

## 上传指南

1. 在 gitee 创建仓库 `firefiy-qqofficial-bot-piugins`
2. 把本目录内容全部上传到仓库根目录
3. 仓库默认分支设为 `main`
4. 在 bot 控制台配置仓库地址

## 注意事项

- 每个目录包必须包含 `main.py` 和 `manifest.json`
- 依赖 `_common` 的插件需要保证 `_common/` 目录已上传
- 单文件插件以 `<key>.py` 命名,直接放在根目录
- 修改插件后,bot 端可能因 CDN 缓存需要等待
