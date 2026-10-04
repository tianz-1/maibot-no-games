# -*- coding: utf-8 -*-
"""麦麦出站守卫：规则精度自测。

直接 import 仓库里的 ``plugin.py``（不需要启动 MaiBot），
用正例 / 负例断言验证规则集的命中精度。

前置条件：需要能 import 到 ``maibot_sdk``（插件基类）。没有它会报
``ModuleNotFoundError: maibot_sdk``，可先 ``pip install maibot-plugin-sdk``。

用法：
    python tests/test_rules.py

改完 ``_builtin_patterns`` 或 ``_REFUSAL_PATTERNS`` 后跑一遍，
能立刻看出有没有把正常聊天误杀、有没有漏掉邀约。
"""

import importlib.util
import sys
from pathlib import Path

# Windows 中文控制台（cp936）无法输出 ✅/❌ 等符号，会 UnicodeEncodeError 崩掉
# 整个脚本。强制 stdout 走 UTF-8 且遇不可编码字符降级替换。
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

PLUGIN_PATH = Path(__file__).resolve().parent.parent / "plugin.py"

spec = importlib.util.spec_from_file_location("maibot_no_games_plugin", PLUGIN_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules["maibot_no_games_plugin"] = module
spec.loader.exec_module(module)


def make_plugin(action: str = "abort", *, enabled: bool = True, dry_run: bool = False, **kwargs):
    """造一个注入了指定配置的插件实例。

    ⚠️ 必须这样注入：``_inspect`` 读的是 ``self._guard_config()``，
    直接 new 一个 ``GuardSectionConfig`` 传给函数是**无效**的 ——
    那样测的还是默认配置，断言会变成"默认值恰好等于期望值"的假通过。
    """

    cfg = module.GuardSectionConfig()
    cfg.action = action
    cfg.enabled = enabled
    cfg.dry_run = dry_run
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    inst = module.NoGamesPlugin()
    inst._guard_config = lambda: cfg
    return inst


def text_message(text: str) -> dict:
    return {"raw_message": [{"type": "text", "data": text}]}


guard = module.GuardSectionConfig()
plugin = make_plugin()

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
    "你们去吧，我不去",
]


def run() -> int:
    print("=" * 66)
    print(f"插件文件：{PLUGIN_PATH}")
    print(f"内置规则集：{getattr(module, 'BUILTIN_RULE_SET', '?')}")
    print("=" * 66)

    failures: list[str] = []
    # 真实计数：每条用例记一次，下面的每段专项检查也各记一次。
    # 早先这里是 `+ 5` 硬编码，加了用例而不同步数字就会"永远通过"。
    checked = 0

    def check(ok: bool, message: str) -> bool:
        nonlocal checked
        checked += 1
        if not ok:
            failures.append(message)
        return ok

    print("\n正例（应当命中并被拦下）")
    print("-" * 66)
    for text in POSITIVE:
        got = plugin._inspect(text_message(text), "test_stream", "", {}).get("action", "continue")
        ok = check(got == "abort", f"漏报（该拦没拦）: {text}")
        print(f"  {'✅' if ok else '❌'} {text}   -> {got}")

    print("\n负例（应当放行）")
    print("-" * 66)
    for text in NEGATIVE:
        got = plugin._inspect(text_message(text), "test_stream", "", {}).get("action", "continue")
        ok = check(got == "continue", f"误杀（不该拦）: {text}")
        print(f"  {'✅' if ok else '❌'} {text}   -> {got}")

    print("\n出站消息结构")
    print("-" * 66)
    for title, message, expect in STRUCTURE_CASES:
        got = plugin._inspect(message, "test_stream", "", {}).get("action", "continue")
        ok = check(got == expect, f"结构用例失败: {title}（期望 {expect}，实际 {got}）")
        print(f"  {'✅' if ok else '❌'} {title}  -> {got}")

    print("\n拒绝话术全链路（_inspect）")
    print("-" * 66)
    for text in REFUSAL_CASES:
        got = plugin._inspect(
            {"raw_message": [{"type": "text", "data": text}]}, "test_stream", "", {}
        ).get("action", "continue")
        ok = check(got == "continue", f"拒绝话术被误拦: {text}")
        print(f"  {'✅' if ok else '❌'} {'放行' if ok else '被拦(错)'}  {text}")

    print("\nstrip 模式（删掉命中句，保留其余与标点）")
    print("-" * 66)
    remain = module.NoGamesPlugin._strip("今天掉分掉麻了。走呗，上线开一把。我先睡了。", guard)
    ok = check(
        "上线开一把" not in remain and "今天掉分掉麻了" in remain and "我先睡了" in remain,
        f"strip 结果异常: {remain!r}",
    )
    print(f"  {'✅' if ok else '❌'} 剩余正文 = {remain!r}")

    print("\n新增行为：缓存 / 非法配置 / 无副作用 / 日志摘要")
    print("-" * 66)

    # 1) 正则编译缓存：重复判定不应重复编译
    module._compile_cached.cache_clear()
    first = module.NoGamesPlugin._match_raw("走呗，上线开一把", guard)
    info_after_first = module._compile_cached.cache_info()
    for _ in range(20):
        module.NoGamesPlugin._match_raw("今天掉分掉麻了", guard)
    info_after_many = module._compile_cached.cache_info()
    ok = first is not None and info_after_many.misses == info_after_first.misses
    if not ok:
        failures.append("正则编译未命中缓存（每条消息重复编译）")
    print(
        f"  {'✅' if ok else '❌'} 编译缓存：misses {info_after_first.misses} -> {info_after_many.misses}"
        f"（21 次判定只编译 {info_after_many.misses} 次）"
    )

    # 2) 非法 action 值：应回退 abort 并给出告警，不静默
    #    ⚠️ 关键：必须用 make_plugin(action="block") 真正注入配置。
    #    早先版本造了个局部 guard 却没注入，_inspect 读的仍是默认 abort，
    #    于是"默认值恰好等于期望值"，断言成了假通过。
    p_bad = make_plugin(action="block")
    got = p_bad._inspect(text_message("走呗，上线开一把"), "s", "", {}).get("action")
    ok = got == "abort"
    if not ok:
        failures.append(f"非法 action 未回退 abort，实际 {got}")
    print(f"  {'✅' if ok else '❌'} 非法 action='block'（已注入）-> 回退 {got}")

    # 反证：同一个非法值，若真的没注入配置则拿不到这个结果。
    # 换成 enabled=False 应当放行 —— 证明注入确实生效。
    p_off = make_plugin(enabled=False)
    got_off = p_off._inspect(text_message("走呗，上线开一把"), "s", "", {}).get("action")
    ok_inject = got_off == "continue"
    if not ok_inject:
        failures.append(f"enabled=False 未生效（配置注入失败），实际 {got_off}")
    print(f"  {'✅' if ok_inject else '❌'} 配置注入有效性：enabled=False -> {got_off}")

    # 3) strip 模式：真的能改写 modified_kwargs，且不修改入参
    strip_text = "今天掉分掉麻了。走呗，上线开一把。我先睡了。"
    p_strip = make_plugin(action="strip")
    original = text_message(strip_text)
    snapshot = [dict(c) for c in original["raw_message"]]
    res = p_strip._inspect(original, "s", strip_text, {"processed_plain_text": strip_text})
    ok_mk = "modified_kwargs" in res
    if not ok_mk:
        failures.append(f"strip 模式未返回 modified_kwargs（实际 action={res.get('action')}）")
    else:
        new_body = res["modified_kwargs"]["message"]["raw_message"][0]["data"]
        ok_body = "上线开一把" not in new_body and "今天掉分掉麻了" in new_body
        if not ok_body:
            failures.append(f"strip 剩余正文不对: {new_body!r}")
        # processed_plain_text 必须同步，否则写入存储的仍是含邀约的原文
        ok_plain = res["modified_kwargs"]["processed_plain_text"] == new_body
        if not ok_plain:
            failures.append(
                f"processed_plain_text 未同步改写: {res['modified_kwargs']['processed_plain_text']!r}"
            )
        print(f"  {'✅' if ok_body and ok_plain else '❌'} strip 集成路径：剩余={new_body!r}（纯文本已同步={ok_plain}）")
    ok_no_side_effect = original["raw_message"] == snapshot
    if not ok_no_side_effect:
        failures.append("strip 模式修改了入参 message（应复制后再改）")
    print(f"  {'✅' if ok_no_side_effect else '❌'} strip 不改入参：{ok_no_side_effect}")

    # 4) strip 遇 at 组件会退化为 abort（文档必须写明）
    p_at = make_plugin(action="strip")
    at_msg = {
        "raw_message": [
            {"type": "at", "data": {"qq": "123"}},
            {"type": "text", "data": "走呗，上线开一把"},
        ]
    }
    got_at = p_at._inspect(at_msg, "s", "", {}).get("action")
    ok_at = got_at == "abort"
    if not ok_at:
        failures.append(f"带 at 组件时 strip 应退化为 abort，实际 {got_at}")
    print(f"  {'✅' if ok_at else '❌'} strip 遇 at 组件 -> 退化 {got_at}")

    # 5) 日志摘要：超长正文必须截断（断言真实上限 120 字）
    long_text = "啊" * 500
    short = module._excerpt("短句")
    clipped = module._excerpt(long_text)
    ok_clip = short == "短句" and clipped.startswith("啊" * 120) and len(clipped) < len(long_text)
    if not ok_clip:
        failures.append(f"日志摘要未正确截断: {clipped[:40]!r}… 长度={len(clipped)}")
    print(f"  {'✅' if ok_clip else '❌'} 日志摘要 500 字 -> 正文保留 {clipped.count('啊')} 字（上限 120）")

    # ── 新增：多义词误杀回归（外部审查发现）─────────────────────────────
    ambiguity_cases = [
        "这游戏开局就崩了",
        "开局先发育，别急着团",
        "我把新版本上线了，明天就能用",
        "我先上线看看服务器状态",
        "上线时间改到周五了",
        "我来把椅子搬过来",
        "组队报名参加了公司比赛",
        "算我一个，明天的评审我来做",
        "这局我玩辅助位吗？",
    ]
    amb_fail = []
    for t in ambiguity_cases:
        if plugin._inspect(text_message(t), "s", "", {}).get("action") != "continue":
            amb_fail.append(t)
    for t in amb_fail:
        failures.append(f"多义词误杀（应放行却拦了）: {t}")
    print(f"  {'✅' if not amb_fail else '❌'} 多义词误杀回归：{len(ambiguity_cases)} 条日常用语，误杀 {len(amb_fail)} 条")

    # ── 新增：拒绝词不可成为整条放行的后门（外部审查发现）─────────────
    bypass_cases = [
        "我不玩单机的，不过一起开黑也行",
        "你们打两把吧，我不来",
        "我手残，所以你带我打两把吧",
        "算了算了，开黑走",
        "我不联机，但你上号我也来",
        "下次吧，今天上线开一把",
    ]
    bypass_ok = 0
    for t in bypass_cases:
        if plugin._inspect(text_message(t), "s", "", {}).get("action") == "abort":
            bypass_ok += 1
        else:
            failures.append(f"拒绝话术后门：含邀约却整条放行了 -> {t}")
    print(f"  {'✅' if bypass_ok == len(bypass_cases) else '❌'} 拒绝词后门：{bypass_ok}/{len(bypass_cases)} 条被正确拦下")

    # ── 新增：按句判定——拒绝句放行但同段邀约句仍要拦（strip 模式）────
    p_sentence = make_plugin(action="strip")
    mixed = "我不玩单机的。不过一起开黑也行。"
    res_mixed = p_sentence._inspect(text_message(mixed), "s", mixed, {"processed_plain_text": mixed})
    ok_mixed = (
        "modified_kwargs" in res_mixed
        and "我不玩单机的" in res_mixed["modified_kwargs"]["message"]["raw_message"][0]["data"]
        and "开黑" not in res_mixed["modified_kwargs"]["message"]["raw_message"][0]["data"]
    )
    if not ok_mixed:
        failures.append(f"按句判定失败：拒绝句应保留、邀约句应删除，实际 {res_mixed}")
    print(f"  {'✅' if ok_mixed else '❌'} 按句判定：拒绝句保留 + 邀约句删除")

    total = checked
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
