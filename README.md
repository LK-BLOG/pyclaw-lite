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
./install.sh                          # 装依赖 + 建目录,可反复跑
cp pyclaw.json.example pyclaw.json    # 填入你的 API Key 和 Endpoint
python main.py                        # 进 TUI
```

`install.sh` 会装三个运行时依赖：

| 包 | 用途 |
|------|------|
| `openai` | API 调用（唯一必需） |
| `prompt_toolkit` + `rich` | TUI 界面。只用 `--plain` 的话可以不装 |

手动装也行：`pip install openai prompt_toolkit rich`

## 长期记忆

`memory/` 目录下的 `.md` / `.txt` / `.json` / `.jsonl` 文件会**全文注入** system prompt（见 `pyclaw/agent.py` 的 `memory_text()`）。把持久事实写进去，下次启动 AI 就记得。

```
memory/notes/
  creator.txt     # 关于用户的事实
  site.txt        # 环境、地址等
```

支持 `exit` 或 `quit` 退出对话。

## 配置

编辑 `pyclaw.json`：

| 字段 | 说明 |
|------|------|
| `API\_KEY` | API 密钥 |
| `ENDPOINT` | API 端点 URL（兼容 OpenAI 格式） |
| `MODEL` | 模型名称 |
| `PROVIDER` | 供应商预设；选 `custom` 时只用 `ENDPOINT` |
| `APPROVAL\_MODE` | `request` / `auto` / `full` 三档权限 |
| `SHELL` | `auto` = WSL > Git Bash > PowerShell > CMD |

完整键位见 `pyclaw/config.py` 的 `SCHEMA`。

## 许可证

GNU General Public License v3.0 — 和 PyClaw 一致。

---

*Codex\&Campus匠心制作*

