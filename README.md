# PyClaw Lite

**一把 exec 走天下。**

PyClaw 的轻量版。没有花哨的工具链，没有预置的插件生态——只有一个 `exec` 工具，和一颗能自己动手的 AI 脑袋。

## 哲学

市面上的 Agent 框架们都给你准备好了一整套餐具：文件读写工具、网络搜索工具、代码执行工具、数据库工具…… 看起来很全，但遇到真正的活，你还得自己再造。

PyClaw Lite 反过来。它只有一把刀——`exec`。想读文件？`cat`。想装包？`pip`。想爬网页？`curl`。想分析数据？写个 Python 脚本然后 `python` 跑。AI 自己动手，什么都能切。

这就是 **Hermes 和 PyClaw Lite 的区别**：

> Hermes：有很多餐具，但遇到新菜还得自己造。
> PyClaw Lite：只有一把刀，剩下什么都自己做。

## 自进化的 Skill 系统

AI 可以把复杂或可复用的逻辑保存到 `skills/` 目录下。下次启动时，`skills/` 里的所有 `.py` 文件会自动列在 system prompt 里，AI 就知道自己有什么能力了。

能力积累从代码挪到了 AI 行为里——代码量不会增长，能力却会变多。

## 使用

```bash
pip install openai
cp pyclaw.json.example pyclaw.json   # 填入你的 API Key 和 Endpoint
python main.py
```

支持 `exit` 或 `quit` 退出对话。

## 配置

编辑 `pyclaw.json`：

| 字段 | 说明 |
|------|------|
| `API\_KEY` | API 密钥 |
| `ENDPOINT` | API 端点 URL（兼容 OpenAI 格式） |
| `MODEL` | 模型名称 |

## WebUI（实验性）

```bash
python webui.py
```

| 字段 | 默认 | 说明 |
|------|------|------|
| `WEBUI\_PORT` | `8765` | 端口 |
| `WEBUI\_HOST` | `127.0.0.1` | 只监听本机；\*\*改成 `0.0.0.0` 等于把 shell 暴露给整个网络\*\* |
| `WEBUI\_TOKEN` | 空 | 留空时仅本机能访问；绑到非本机地址时必须设置，否则拒绝启动 |
| `WEBUI\_CONFIRM\_TIMEOUT` | `120` | 危险命令确认弹窗的等待秒数，超时默认拒绝 |

WebUI 里 AI 会通过 `exec` 执行命令，且 AI 会先按上下文审核：普通命令直接执行；
破坏性/不可逆操作（批量删除、覆盖、force-push、把远程脚本管道给 shell 等）只有你在对话里明确授权才会执行，
否则 AI 调用 `exec` 时会带上 `requires_confirmation=true`，页面弹出确认框，你点放行才跑。
命中内置黑名单（`rm -rf /`、格式化、关机等，可用 `WEBUI_EXEC_BLOCKED` 追加）的命令同样会弹确认框。
确认超时默认 120 秒，可用 `WEBUI_CONFIRM_TIMEOUT` 调整。
默认只绑回环、只有本机能连；非要对外暴露，必须配 `WEBUI_TOKEN`。

## 许可证

GNU General Public License v3.0 — 和 PyClaw 一致。

---

*Codex\&Campus匠心制作*

