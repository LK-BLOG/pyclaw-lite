"""Segmentation, prefix rules and the three approval modes."""

from __future__ import annotations

from pyclaw.permissions import Policy, derive_rule, mode_label, rule_matches, segment, tokenize


def test_segments_split_on_control_operators():
    pieces = segment("ls && rm -rf / ; echo hi | wc -l")
    assert any("rm -rf /" in piece for piece in pieces)
    assert len(pieces) >= 4


def test_segments_keep_quoted_operators():
    assert segment('echo "a && b"') == ['echo "a && b"']


def test_blocked_pattern_is_forbidden_even_in_full_mode():
    policy = Policy()
    assert policy.evaluate("rm -rf /", mode="full").decision == "forbidden"
    assert policy.evaluate("ls -la", mode="full").decision == "allow"


def test_hidden_dangerous_tail_is_caught():
    verdict = Policy().evaluate("echo hi && rm -rf /", mode="full")
    assert verdict.decision == "forbidden" and "rm -rf /" in verdict.segment


def test_request_mode_asks_about_everything():
    policy = Policy()
    assert policy.evaluate("ls", mode="request").decision == "prompt"
    assert policy.evaluate("ls", mode="auto").decision == "allow"


def test_flag_forces_prompt_in_auto_mode():
    assert Policy().evaluate("python cleanup.py", flagged=True, mode="auto").decision == "prompt"


def test_allow_rule_wins_over_request_mode():
    policy = Policy([{"pattern": ["pip", "install"], "decision": "allow", "scope": "persistent"}])
    assert policy.evaluate("pip install requests", mode="request").decision == "allow"
    assert policy.evaluate("pip uninstall requests", mode="request").decision == "prompt"


def test_strictest_rule_wins():
    policy = Policy([
        {"pattern": ["git"], "decision": "allow", "scope": "session"},
        {"pattern": ["git", "push"], "decision": "prompt", "scope": "session"},
    ])
    assert policy.evaluate("git status", mode="request").decision == "allow"
    assert policy.evaluate("git push origin main", mode="request").decision == "prompt"


def test_derive_rule_keeps_subcommands_and_drops_values():
    assert derive_rule("pip install requests -U")["pattern"] == ["pip", "install"]
    assert derive_rule("ls -la")["pattern"] == ["ls"]
    assert derive_rule("git commit -m 'x'")["pattern"] == ["git", "commit"]


def test_rule_matching_is_case_insensitive_and_prefix_only():
    rule = {"pattern": ["Git", "push"]}
    assert rule_matches(rule, tokenize("git push origin main"))
    assert not rule_matches(rule, tokenize("git status"))


def test_grants_and_revokes_by_scope():
    policy = Policy()
    policy.grant({"pattern": ["ls"], "decision": "allow", "scope": "session"})
    policy.grant({"pattern": ["cat"], "decision": "allow", "scope": "persistent"})
    assert len(policy.session_rules) == 1 and len(policy.persistent) == 1
    policy.revoke(0, "session")
    assert policy.session_rules == [] and len(policy.rules) == 1


def test_extra_blocked_fragments_are_honoured():
    policy = Policy(extra_blocked=["nc -l"])
    assert policy.evaluate("nc -l 4444", mode="full").decision == "forbidden"
    assert policy.evaluate("ls", mode="full").decision == "allow"


def test_mode_labels_are_localised():
    assert mode_label("auto", "zh-CN")["label"] == "帮我批准"
    assert mode_label("auto", "en-US")["label"] == "Approve for me"
