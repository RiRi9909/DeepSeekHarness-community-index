# dsh-sentiment-cockpit

**r/DeepSeek 社区情绪驾驶舱** —— DeepSeek Harness (DSH) 网页插件。

> [English](./README.md)

在设置面板注册「社区情绪驾驶舱」分区，实时展示 r/DeepSeek 社区的 **DSI 乐观/愤怒指数**（0–100 多信号加权结构，参照 Crypto Fear & Greed Index 设计），并内置数据管道按周期自动刷新（默认每 60 分钟）。管道失败时自动回退到包内快照，**永不出白屏**。

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![dsh](https://img.shields.io/badge/DeepSeek%20Harness-plugin-4d6bfe)](https://github.com/deepseek-ai/deepseek-harness)

## 截图

![DSI 指数历史曲线](docs/cockpit.png)

## 功能

- **设置面板分区**：设置 → 社区情绪驾驶舱。DSI 指数、愤怒指数、数据更新时间一目了然，支持手动刷新与新标签页打开快照。
- **桌面小组件（macOS）**：原生无边框悬浮窗常驻桌面，实时显示 DSI 指数，随管道自动更新。可拖动、可缩放，支持「贴桌面」（普通窗口盖住它，类似传统桌面小组件）与「置顶悬浮」两种层级。**启动时默认以 📈 迷你胶囊出现，点击才展开完整仪表盘**。窗口由插件附带的原生二进制（`assets/desktop/`，源码 `main.swift`）提供，无 Electron、无额外依赖。
- **自动刷新**：Host 端通过 `cordis-plugin-timer` 定时驱动 Python 数据管道（抓取 Arctic Shift 镜像 API → 计算指数 → 生成自包含 HTML 快照），默认每 60 分钟一次。
- **永不白屏**：管道失败或缓存损坏时自动回退到包内内置快照（`assets/fallback/`）。
- **零构建授权安装**：纯 JavaScript 实现、无构建脚本，Git 方式安装不需要任何 `allowBuilds` 授权。

## 安装

推荐使用 Git 方式（本仓库）：

```bash
dsh plugin --profile web add github:RiRi9909/DeepSeekHarness-community-index
```

> 也可以锁定到某个 commit，防止后续推送改变你实际运行的内容：
> `dsh plugin --profile web add github:RiRi9909/DeepSeekHarness-community-index#<commit-sha>`

其他两种方式（详见[官方发布文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.zh.md)）：

```bash
# 本地路径
dsh plugin --profile web add /path/to/dsh-sentiment-cockpit

# tarball（pnpm pack 打包后）
dsh plugin --profile web add ./dsh-sentiment-cockpit-0.2.3.tgz
```

安装后重启 DSH，即可在 设置 → 插件 中看到本插件，设置面板中出现「社区情绪驾驶舱」分区。

## 使用

- 打开 **设置 → 社区情绪驾驶舱** 查看面板；数据每 60 秒轮询更新。
- 点 **刷新数据** 立即重跑管道（约 1–20 分钟，期间按钮显示「刷新中」）。
- 点 **新标签页打开** 以独立页面查看自包含 HTML 快照。
- 设置命名空间 `sentiment-cockpit`：`enabled`（默认 true）、`intervalMinutes`（默认 60，范围 10–1440）。

### 桌面小组件

在设置命名空间 `sentiment-cockpit` 中配置：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `desktopEnabled` | `false` | 是否在 DSH 启动时打开桌面小组件 |
| `desktopMode` | `"desktop"` | `"desktop"` 贴桌面（普通窗口盖住它）；`"floating"` 置顶悬浮 |
| `desktopScale` | `1` | 缩放（0.7–1.6） |
| `desktopX` / `desktopY` | `-1` | 窗口位置；负数表示右下角自动定位 |

修改后重启 DSH 生效。小组件有两种状态，**启动时默认以迷你状态出现**：

- **迷你状态**：一个 📈 + DSI 数值的小胶囊（默认停在屏幕右下角）；点击胶囊展开完整卡片，拖动胶囊可移动位置。
- **完整状态**：顶栏显示实时 DSI 指数，提供 收起（—）/ 刷新（⟳）/ 浏览器打开快照（⧉）/ 关闭（✕）四个按钮；拖动顶栏可移动位置。

两种状态各自的位置都会记住，重启后保持原样（每次启动都从迷你状态开始）。

若附带二进制缺失（例如非 arm64 Mac），插件会尝试用本机 `swiftc` 从 `assets/desktop/main.swift` 现场编译。

## 依赖契约

- **Host**：`@deepseek-ai/cordis`、`@deepseek-ai/dsh-settings`、`@deepseek-ai/dsh-typert-protocol`、`schemastery`（由 profile 的共享 node_modules 解析）。
- **Client**：`react`（模块加载器共享）、`dsh-client-runtime` / `dsh-client-connection` / `dsh-client-locale` / `dsh-client-ui-slots`（`dsh.client.inject` 声明）。客户端通过 `ctx.connection.rpc.call("/api", "cockpit/<method>", …)` 直连 Host 的 Typert 网关 SRC 通道。
- **数据管道**：系统 `python3`（仅标准库，无第三方依赖）。

## 架构

| 部分 | 文件 | 职责 |
| --- | --- | --- |
| Host | `lib/index.js` | Cordis 插件，暴露 Typert RPC `remote.cockpit`（`getSnapshot` / `refresh` / `status`），定时驱动管道，管理桌面小组件进程 |
| Client | `lib/client.js` | 注册 `settings.section` 槽位，iframe srcDoc 渲染快照 |
| 桌面小组件 | `assets/desktop/main.swift`（+ 预编译 `DSHCockpitWidget`） | 原生 macOS 悬浮窗，渲染快照并自动刷新 |
| 管道 | `lib/pipeline/` | `fetch_posts.py` → `fetch_comments.py` → `sentiment_index.py` → `build_snapshot.py`（编排器 `run_pipeline.py`） |
| 回退 | `assets/fallback/` | 内置快照；缓存目录 `~/.dsh/storages/dsh-sentiment-cockpit/` 不可用时兜底 |

## 手动更新快照

```bash
python3 lib/pipeline/run_pipeline.py --out ~/.dsh/storages/dsh-sentiment-cockpit
```

## 常见问题

- **面板显示「宿主插件未加载」**：重启 DSH（Host 插件需重新引导）。
- **数据长时间不变**：检查系统是否安装 `python3`；手动跑一次上方的管道命令查看报错。
- **想关闭自动刷新**：设置命名空间 `sentiment-cockpit` 的 `enabled` 改为 `false`。

## 许可证

[MIT](./LICENSE) © 2026 RiRi9909
