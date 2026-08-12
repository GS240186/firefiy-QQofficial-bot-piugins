# 小流萤 bot 插件市场

> 这是 **小流萤 bot** 的**远程插件下载源**。所有外置插件都通过本仓库的
> `plugins-market/` 目录发布，bot 运行时从 GitHub raw 拉取并一键安装到本地，
> 无需手动复制文件。

## 这是什么仓库

bot 启动后，控制台「插件市场」页可切换到「**远程**」模式，从此仓库下载外置插件
到本机 `plugins/` 目录并触发热加载（不重启 bot）。

### 底层拉取链路

```
控制台「插件市场 - 远程」
  → GET https://raw.githubusercontent.com/GS240186/firefiy-QQofficial-bot-piugins/main/plugins-market/index.json
  → 用户点「安装」→ 下载 <key>/<key>.py 到本地 plugins/<key>.py
  → reload_external_plugins(force=True) 热加载
  → 新插件立即可用
```

### bot 侧的固定配置

写在 `modules/plugin_registry.py` 里：

```python
REMOTE_MARKET_OWNER = "GS240186"
REMOTE_MARKET_REPO   = "firefiy-QQofficial-bot-piugins"
REMOTE_MARKET_BRANCH = "main"
REMOTE_MARKET_BASE   = "https://raw.githubusercontent.com/GS240186/firefiy-QQofficial-bot-piugins/main/plugins-market/"
```

> 如果你的仓库默认分支不是 `main`（例如 `master`），需要把
> `REMOTE_MARKET_BRANCH` 改成对应分支后重启 bot，否则拉不到目录。

## 仓库结构

```
firefiy-QQofficial-bot-piugins/
├── README.md             # 本文件：仓库总览
└── plugins-market/       # 插件市场目录（bot 实际从这里拉取）
    ├── README.md         # 字段约定 + 外置插件契约（**写插件前必看**）
    ├── index.json        # 总目录
    ├── roll/             # 示例：骰子
    │   ├── roll.py
    │   └── meta.json
    ├── ping/             # 示例：连通性自测
    └── demo_echo/        # 示例：原样回显
```

每个插件目录里：

| 文件 | 是否必填 | 说明 |
| --- | --- | --- |
| `<key>.py` | ✅ | 插件源码。须遵守**外置插件契约**：模块级 `PLUGIN` dict + `async def handle(ctx) -> bool` |
| `meta.json` | ❌（建议填）| 插件元信息，供前端展示 |

详细字段、外置插件契约见 [`plugins-market/README.md`](./plugins-market/README.md)。

## 如何贡献一个新插件

1. 在 `plugins-market/<your_key>/` 下新建目录，放：
   - `<your_key>.py` —— 插件源码
   - `meta.json` —— 元信息（建议填）

2. 在 `plugins-market/index.json` 的 `plugins` 数组里追加一项：

   ```json
   {
     "key": "your_key",
     "name": "你的插件名",
     "description": "一句话说明这个插件做什么",
     "category": "工具",
     "priority": 500,
     "path": "your_key/your_key.py",
     "meta": "your_key/meta.json"
   }
   ```

3. 提交 PR，合并到 `main` 分支后，bot 控制台「插件市场 - 远程」刷新即可看到。

## 注意事项

- **仓库名拼写**：仓库名 `firefiy-QQofficial-bot-piugins` 里 `piugins` 是创建时的小瑕疵，
  本应是 `plugins`。但**不建议改名**——改名会让 `REMOTE_MARKET_BASE` 失效，需要同步修改
  并通知所有用户更新 bot。
- **分支默认 `main`**：若 GitHub 端把默认分支改了，bot 一侧也要同步。
- **大小写**：`REMOTE_MARKET_BASE` 大小写敏感，`plugins-market` 一律小写带连字符。

## 关联项目

- bot 主仓库（控制台、本地插件契约、热加载机制等）：见 `modules/plugin_registry.py`
  中的注释与 `PluginDescriptor` / `PluginContext` 定义。
- 本地模板市场（不依赖网络、本地内置的三个示例插件 `roll` / `ping` / `demo_echo`）：
  见 `modules/plugin_registry.py` 的 `_MARKET_TEMPLATE_FILES` / `_MARKET_META`。

## 许可

与 bot 主项目保持一致。
