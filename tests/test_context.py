"""Truncation, token accounting and the shell table."""

from __future__ import annotations

from pyclaw import context as ctx


def test_truncate_keeps_head_only():
    text = "\n".join(f"line {i}" for i in range(1000))
    head, omitted, truncated = ctx.truncate(text, max_lines=500, max_bytes=65536, line_max=500)
    assert head.splitlines()[0] == "line 0"
    assert len(head.splitlines()) == 500
    assert omitted > 0 and truncated == 500


def test_truncate_byte_cap_wins_on_fat_lines():
    text = "\n".join("x" * 900 for _ in range(500))
    head, omitted, _ = ctx.truncate(text, max_lines=500, max_bytes=4096, line_max=900)
    assert len(head.encode("utf-8")) <= 4096
    assert omitted > 0


def test_truncate_long_single_line_is_clipped():
    head, _, _ = ctx.truncate("y" * 5000, max_lines=10, max_bytes=65536, line_max=500)
    assert head.endswith("...")
    assert len(head) <= 503


def test_truncate_short_text_is_untouched():
    head, omitted, truncated = ctx.truncate("hello\nworld")
    assert (head, omitted, truncated) == ("hello\nworld", 0, 0)


def test_estimate_prefers_cjk_density():
    assert ctx.estimate_tokens("字" * 100) > ctx.estimate_tokens("a" * 100)
    assert ctx.estimate_tokens("") == 0


def test_spill_writes_full_output_and_pointer(workspace):
    spiller = ctx.Spiller(workspace / "history" / "tool", max_lines=2, max_bytes=65536)
    result = ctx.format_tool_result("dir", 0, "a\nb\nc\nd", 0.4, "/tmp", spiller, "sess1", workspace)
    assert "[exit 0]" in result and "[cwd /tmp]" in result
    assert "Omitted" in result
    files = list((workspace / "history" / "tool" / "sess1").glob("*.log"))
    assert files and files[0].read_text(encoding="utf-8") == "a\nb\nc\nd"
    assert files[0].relative_to(workspace).as_posix() in result


def test_spill_skips_reading_its_own_output(workspace):
    spiller = ctx.Spiller(workspace / "history" / "tool", max_lines=1)
    result = ctx.format_tool_result("cat history/tool/sess1/x.log", 0, "a\nb\nc", 0.1, "/tmp",
                                    spiller, "sess1", workspace)
    assert "Omitted" in result
    assert not list((workspace / "history" / "tool").rglob("*.log"))


def test_empty_output_is_labelled():
    spiller = ctx.Spiller("history/tool")
    assert "(no output)" in ctx.format_tool_result("true", 0, "", 0.1, "/tmp", spiller, "s", ".")


def test_ansi_is_stripped():
    spiller = ctx.Spiller("history/tool")
    cleaned = ctx.format_tool_result("ls", 0, "\x1b[31mred\x1b[0m", 0.1, "/tmp", spiller, "s", ".")
    assert "31m" not in cleaned and "red" in cleaned


def test_breakdown_splits_roles_and_keeps_free_tail():
    messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
                {"role": "tool", "content": "out"}]
    data = ctx.breakdown(messages, [{"type": "function"}], "system", pressure_tokens=100, window=1000)
    assert data["user"] > 0 and data["assistant"] > 0 and data["tool"] > 0
    assert data["used"] == 100 and data["free"] == 900 and data["percent"] == 10.0


def test_wsl_path_mapping():
    assert ctx._wsl_mount(r"D:\pyclaw-lite") == "/mnt/d/pyclaw-lite"
    assert ctx._wsl_mount("/already/posix") == "/already/posix"
