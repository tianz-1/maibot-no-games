# -*- coding: utf-8 -*-
"""麦麦出站守卫：规则精度自测。

直接 import 仓库里的 ``plugin.py``（不需要启动 MaiBot），
用正例 / 负例断言验证规则集的命中精度。

用法：
    python tests/test_rules.py

改完 ``_builtin_patterns`` 或 ``_REFUSAL_PATTERNS`` 后跑一遍，
能立刻看出有没有把正常聊天误杀、有没有漏掉邀约。
"""

import importlib.util
import sys
from pathlib import Path

PLUGIN_PATH = Path(__file__).resolve().parent.parent / "plugin.py"

spec = importlib.util.spec_from_file_location("maibot_no_games_plugin", PLUGIN_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules["maibot_no_games_plugin"] = module
spec.loader.exec_module(module)

guard = module.GuardSectionConfig()
plugin = module.NoGamesPlugin()

# ── 正例：必须命中并被拦下 ──────────────────────────────────────────────────
POSITIVE = [
    # 真实聊天里麦麦实际说过的邀约
    "走呗，上线开一把",
    "现在来一把补偿你",
    "你说打啥我都奉陪",
    "先跟你们打两把找找感觉",
    "那我上线等你",
    "QQ语音喊你",
    "就上线了喊你一声开一把呀，我打中单",
    "今天有空，要不现在来一把？",
    "我这不是在认错嘛，走呗，上线开一把",
    "行，那我上线等你",
    # 其他常见邀约
    "组队吗",
    "带你上分",
    "等你上号",
    "开黑走",
    "要不一起玩",
    "我打辅助",
    "三缺一，来不来",
    "开一把不",
    "别磨叽了，上线开一把",
]

# ── 负例：必须放行 ─────────────────────────────────────────────────────────
NEGATIVE = [
    # 麦麦自己的拒绝话术——最容易被规则误杀，必须放行（否则它会彻底不吭声）
    "我不联机的，你们玩吧",
    "算了，我都是自己玩单机的",
    "别算我，我手残",
    "我打游戏从来不联机",
    "你们打两把吧，我不来",
    "不了不了，我自己玩",
    "下次吧，我不太会玩",
    "我这技术还是别祸害你们了",
    "我不上号，你们玩",
    # 正常的游戏闲聊
    "这游戏这么顶？",
    "加载20分钟也太离谱了吧",
    "这不得泡杯茶慢慢等",
    "能补回来也算稳住心态了",
    "我前两天掉了200分，才补了一点",
    "从赛车又转到飞机了",
    "这代码怕是机器人连夜写的吧",
    "上限非常高 听说配特定组合能无限刷资源？",
    # 与游戏无关的日常
    "我这不是在认错嘛",
    "昨天真是临时有急事",
    "我信誉分都要被你扣光了",
    "这表情包看着怎么像在跟我撒娇啊",
    "我这不是还没女朋友嘛",
    "你们先聊，我去看看书",
    "这篇论文写到半夜，困死了",
]

# ── 出站消息结构用例 ───────────────────────────────────────────────────────
STRUCTURE_CASES = [
    (
        "纯正文邀约 -> 应 abort",
        {"raw_message": [{"type": "text", "data": "走呗，上线开一把"}]},
        "abort",
    ),
    (
        "引用别人的约玩原话 + 自己只回「哈哈」 -> 应放行",
        {
            "raw_message": [
                {"type": "reply", "data": {"content": "上线开一把不"}},
                {"type": "text", "data": "哈哈"},
            ]
        },
        "continue",
    ),
    (
        "图文消息且无邀约 -> 应放行",
        {
            "raw_message": [
                {"type": "text", "data": "这张图拍得不错"},
                {"type": "image", "data": "abc.png"},
            ]
        },
        "continue",
    ),
    (
        "@某人 + 邀约 -> 应 abort",
        {
            "raw_message": [
                {"type": "at", "data": "12345"},
                {"type": "text", "data": " 上线开一把"},
            ]
        },
        "abort",
    ),
]

# ── 拒绝话术全链路（不能被自己的规则误杀）──────────────────────────────────
REFUSAL_CASES = [
    "我不联机的，你们玩吧",
    "算了，我都是自己玩单机的",
    "别算我，我手残",
    "你们打两把吧，我不来",
]


def run() -> int:
    print("=" * 66)
    print(f"插件文件：{PLUGIN_PATH}")
    print(f"内置规则集：{getattr(module, 'BUILTIN_RULE_SET', '?')}")
    print("=" * 66)

    failures: list[str] = []

    print("\n正例（应当命中并被拦下）")
    print("-" * 66)
    for text in POSITIVE:
        hit = plugin._match(text, guard)
        ok = hit is not None
        if not ok:
            failures.append(f"漏报（该拦没拦）: {text}")
        print(f"  {'✅' if ok else '❌'} {text}   -> {hit[1] if hit else '未命中'}")

    print("\n负例（应当放行）")
    print("-" * 66)
    for text in NEGATIVE:
        hit = plugin._match(text, guard)
        ok = hit is None
        if not ok:
            failures.append(f"误杀（不该拦）: {text} 命中 {hit[1]!r}")
        print(f"  {'✅' if ok else '❌'} {text}   -> {'放行' if hit is None else '误杀: ' + hit[1]}")

    print("\n出站消息结构")
    print("-" * 66)
    for title, message, expect in STRUCTURE_CASES:
        got = plugin._inspect(message, "test_stream", "", {}).get("action", "continue")
        ok = got == expect
        if not ok:
            failures.append(f"结构用例失败: {title}（期望 {expect}，实际 {got}）")
        print(f"  {'✅' if ok else '❌'} {title}  -> {got}")

    print("\n拒绝话术全链路（_inspect）")
    print("-" * 66)
    for text in REFUSAL_CASES:
        got = plugin._inspect(
            {"raw_message": [{"type": "text", "data": text}]}, "test_stream", "", {}
        ).get("action", "continue")
        ok = got == "continue"
        if not ok:
            failures.append(f"拒绝话术被误拦: {text}")
        print(f"  {'✅' if ok else '❌'} {'放行' if ok else '被拦(错)'}  {text}")

    print("\nstrip 模式（删掉命中句，保留其余与标点）")
    print("-" * 66)
    remain = plugin._strip("今天掉分掉麻了。走呗，上线开一把。我先睡了。", guard)
    ok = "上线开一把" not in remain and "今天掉分掉麻了" in remain and "我先睡了" in remain
    if not ok:
        failures.append(f"strip 结果异常: {remain!r}")
    print(f"  {'✅' if ok else '❌'} 剩余正文 = {remain!r}")

    total = len(POSITIVE) + len(NEGATIVE) + len(STRUCTURE_CASES) + len(REFUSAL_CASES) + 1
    print("\n" + "=" * 66)
    if failures:
        print(f"存在 {len(failures)} 项未通过（共 {total} 项断言）：")
        for item in failures:
            print("   -", item)
    else:
        print(f"全部通过：共 {total} 项断言")
    print("=" * 66)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
