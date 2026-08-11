# plugins-market

小流萤 bot 的「插件市场」远程下载源。

## 目录结构

```
plugins-market/
├── index.json              # 总目录（bot 运行时拉取它）
├── README.md               # 本文件
├── <key>/
│   ├── <key>.py            # 插件源码（外置插件契约：模块级 PLUGIN dict + async handle(ctx)）
│   └── meta.json           # 插件元信息（可选，供前端展示）
```

## index.json 字段

```json
{
  "version": 1,
  "plugins": [
    {
      "key": "roll",
      "name": "Roll 骰子",
      "description": "发送「roll 100」随机抽 1~N 的整数（默认 100）",
      "category": "test",
      "priority": 500,
      "path": "roll/roll.py",        // 相对 plugins-market/ 的源码路径
      "meta": "roll/meta.json"       // 可选
    }
  ]
}
```

## 外置插件契约

`plugins-market/<key>/<key>.py` 需暴露：

```python
PLUGIN = {
    "key": "<key>",
    "name": "显示名",
    "priority": 500,
    "description": "一句话描述",
    "category": "test",        # 可选，用于控制台分组
}

async def handle(ctx) -> bool:
    # ctx.content 已是去掉前缀的指令文本
    # ctx.reply(text) 直接回复
    return True  # 已处理（不再往下传）
```

## 如何让 bot 拉到这个市场

1. 把整个 `plugins-market/` 文件夹推送到仓库根目录（默认分支 `main`）。
2. bot 代码里已配置远程源：
   - owner = `GS240186`
   - repo = `firefiy-QQofficial-bot-piugins`
   - branch = `main`
3. 控制台「插件市场」页切换「远程」即可看到目录；点安装会从
   `https://raw.githubusercontent.com/GS240186/firefiy-QQofficial-bot-piugins/main/plugins-market/<path>`
   下载源码到 `plugins/<key>.py` 并热加载。

> 若仓库默认分支是 `master` 而不是 `main`，改 `modules/plugin_registry.py` 里
> `REMOTE_MARKET_BRANCH = "main"` 为 `"master"` 后重启 bot。
