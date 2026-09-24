# PyClaw Lite v0.0.1-beta.2

把 330 行的玩具重写成「短提示词 + 高密度环境反馈 + 缓存友好上下文」的核心，并把入口换成终端 UI。
**WebUI 已移除**，Lite 现在是可嵌入的 headless 核心 + 一个 Claude Code 风格的 TUI。

## 这次最大的变化

- 删掉 WebUI（`webui.py`、`webui/index.html`），不再维护浏览器界面
- 新增 `pyclaw/` 包：config / providers / context / sessions / permissions / hooks / mcp / plugins / agent / cli / tui
- 入口统一：`python main.py` 进 TUI，`python main.py --plain` 走行式 CLI，`--continue` 续最近会话

## TUI

- 面板流布局：顶部 logo 与信息栏，中间每条消息一个面板（用户 / 助手 / 工具），底部命令栏
- **思考强度滑块**（照 Claude Code 的 `/effort` 面板移植）：轨道 + `▲` 游标、左右 `Faster`/`Smarter`、
  顶级档前有 `┊` 分界、`←/→ to adjust · Enter to confirm · Esc to cancel`
- 模型选择器复用同一套方向键选择器，列表来自 provider 的 `/models`
- 命令：`/help /model /effort /permissions /compact /context /cost /status /new /resume /rules /clear /exit`

## 核心能力

- 仍然只有一把刀：`exec`。插件可以贡献 tools / hooks / mcp / skills
- 插件清单同时认 `.pyclaw-plugin` / `.codex-plugin` / `.claude-plugin`，可扫仓库 `plugins/`、`~/.pyclaw/plugins`、`~/.codex/plugins`
- 钩子：12 个事件 × 4 种 handler，兼容 Codex/Claude 的 JSON 协议，永不阻塞
- MCP：stdio 与 HTTP，工具以 `mcp__<server>__<tool>` 暴露
- 权限：请求批准 / 帮我批准 / 完全访问三档，命令按 `| && || ; ()` 分段判定，授权可抽成「结构类似命令」的前缀规则
- 上下文：工具输出保留前 500 行或 64KB，全文落盘 `history/tool/<会话>/`，返回体带指针
- 压缩：阈值 80% / 保留 16%，**逐字回放前缀以复用 provider 的 KV cache**，摘要失败降级为丢旧历史
- 会话：服务端 jsonl + 索引，**修复了并发写用内存快照整份覆盖导致的丢会话**

## DeepSeek 适配

- 不发送 `temperature` / `max_tokens`（思考模式下无效）
- 思考模式带 `reasoning_content` 回传，缺失补空串（否则 400）
- 强度映射：请求侧接受 `minimal/low/medium/high/xhigh/max/ultra`，实际映射到 `low/high/max`，滑块上标注真实落点

## 破坏性变更

- `python webui.py` 不存在了，改用 `python main.py`
- 新增依赖：`rich`、`prompt_toolkit`（仅 TUI 使用）

## 安装 / 升级

```bash
git pull
./install.sh
python main.py
```

## 测试

85 项通过，全程本地打桩、零 API 调用。

## 已知限制

- Claude Code 有约 84 个命令，Lite 目前兑现 13 个
- `/context` 用本地估算，不是 provider 真值
- 给 MollyPaw 那类前端用的 HTTP/WS 后端接口还没做
- 图片走自带 vision 插件；超限的图片只给路径
