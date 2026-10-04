"""不打游戏（maibot-no-games）—— 让麦麦会拒绝游戏邀约。

在消息**真正发出去之前**检查麦麦自己写的正文，命中「邀约 / 组队 / 承诺参与游戏」的
语义就拦下或删改，于是：

- 别人约麦麦打游戏，它会**拒绝**（而不是答应、上号、报位置、说"奉陪"）；
- 它也**不会主动**去约人；
- 而它自己那句拒绝话术（「我不联机的，你们玩吧」）**能正常发出去**。

最后一条最关键：如果拒绝话术也被规则拦掉，麦麦会变成彻底不吭声，
比"生硬"更糟。所以本插件内置一份「拒绝话术白名单」，识别到它在回绝时一律放行。

工作方式
--------
订阅宿主钩子 ``send_service.after_build_message``（出站消息已构建、尚未发送）：

- 命中禁止规则 → 返回 ``{"action": "abort"}``，取消本次发送；
- ``action = "strip"`` 时 → 删掉命中的那一句，剩余内容照发；
- 命中拒绝话术白名单 → 放行。

三条设计铁律
------------
1. **只看它自己写的正文**：只取 ``message["raw_message"]`` 里 ``type == "text"`` 的组件，
   跳过 ``reply`` / ``at`` / ``image`` / ``emoji``。
   绝不拿被引用的原话或别人的话来判定，否则会把"麦麦附和了一句哈哈"误杀。
2. **fail-open**：任何异常都放行，插件报错绝不能让麦麦变哑。
3. **可试跑**：``dry_run = true`` 时只记录不拦截，用于先观察命中精度再开启。

注意
----
被拦下的消息，宿主发送层会额外记一条 ``[SendService] 发送消息失败`` 的 error 日志。
这是**预期行为**（消息被主动取消），不是故障；本插件自己会打
``[不打游戏] 已拦下…`` 的日志便于对照。

配置
----
见 ``config.toml``：``enabled`` / ``dry_run`` / ``action`` /
``extra_patterns`` / ``extra_keywords`` / ``refusal_patterns``。
"""

from __future__ import annotations

import logging
import re
from typing import Any, ClassVar, Optional, Tuple

from maibot_sdk import Field, HookHandler, MaiBotPlugin, PluginConfigBase

logger = logging.getLogger("plugin.no_games")

_HOOK_NAME = "send_service.after_build_message"
_LOG_TAG = "[不打游戏]"

#: 内置规则集名称
BUILTIN_RULE_SET = "游戏邀约"

# ── 组件类型 ────────────────────────────────────────────────────────────────
# 这些组件不是麦麦自己说的话，直接跳过，不影响判定
_IGNORED_COMPONENT_TYPES = frozenset(
    {
        "reply",
        "image",
        "emoji",
        "face",
        "voice",
        "record",
        "video",
        "file",
        "json",
        "xml",
        "poke",
        "forward",
    }
)

# 这些组件存在时正文不再是「纯文本」，strip 模式会退化为 abort，避免打乱消息结构
_NON_TEXT_COMPONENT_TYPES = frozenset({"at", "mention", "mention_bot", "music", "markdown"})


# ── 内置规则：游戏邀约 ──────────────────────────────────────────────────────
def _builtin_patterns() -> list[str]:
    """内置的「约人一起玩」正则规则（邀约 / 组队 / 承诺参与）。

    全部按**邀约语义**设计，不匹配「单纯聊游戏」的说法，
    因此「这游戏这么顶」「加载20分钟也太离谱了吧」这类评论不会被误杀。
    需要拦别的行为时用配置里的 ``extra_patterns`` / ``extra_keywords`` 追加。
    """

    return [
        # 一起 XX（邀约）
        r"(一起|一块|一齐)(玩|打|来|开|搞|上号|开黑|组队|联机|上分|排位)",
        # 组队类名词（本身就是约玩）
        r"(开黑|组队|联机|双排|三排|四排|五排|上分|排位|下本|刷本|三缺一|四缺一)",
        # 上号 / 上线（参与的信号）
        r"(上号|上线|登号|上游戏|进游戏)",
        # 来一把 / 打两把 / 开一局
        r"(来|开|打|玩|整|搞)(一|两|几|三)?(把|局)",
        # 求带 / 缺人
        r"(带带我|求带|带我一个|算我一个|缺人吗|缺不缺人|还差人吗)",
        # 等你 / 喊你 / 陪你 / 奉陪（承诺参与）
        r"(等你上|等你来|喊你一起|叫你一起|拉你一起|喊你一声|陪你玩|陪你打|奉陪|打啥都|玩啥都|打什么都|玩什么都)",
        # 承诺打某个位置
        r"(我|我来|我打|我玩|我走)[^，。！？\s]{0,2}(打野|中单|上路|下路|辅助|射手|adc|上单)",
        # 开麦 / 连麦 / 语音喊你
        r"(开麦|连麦|语音喊你|语音叫你|语音开黑)",
        # 常见游戏名 + 约玩标记
        r"(一起|来|开|上号|上线|开黑|组队|双排|五排|带|走|整)[^，。！？\s]{0,3}(王者|吃鸡|三角洲|英雄联盟|lol|原神|和平精英|永劫无间|无畏契约|瓦罗兰特|csgo|cf)",
        # 游戏名 + 疑问邀约
        r"(打|玩|开)(王者|吃鸡|三角洲|英雄联盟|lol|原神|和平精英|永劫无间|无畏契约|瓦罗兰特|csgo|cf)[^，。！？\s]{0,4}(吗|不|呀|一起|来|去|走)",
    ]


# ── 拒绝话术白名单 ──────────────────────────────────────────────────────────
# 命中这些 = 麦麦在**拒绝**，不是在邀约，必须整体放行。
# 三个反直觉的坑（都踩过）：
#   1. 不能把裸「不」当标记 —— 「上线开一把不」这种问句会被漏放行；
#   2. 「你们玩/你们打」必须带「吧/去」—— 否则「先跟你们打两把找找感觉」这种**邀约**会被误放；
#   3. A-不-A 疑问式要严格回引用匹配，否则「从来不联机」会被当成「来不来」清掉。
_REFUSAL_PATTERNS = [
    # 自我否定式拒绝：不玩 / 不打 / 不来 / 不联机 / 不上号 / 不想玩 / 没法陪…
    r"(不|没|别|懒得|不想|不爱|没法|不能)\s*(再|太|怎么|想)?\s*"
    r"(玩|打|来|去|开|搞|整|联机|开黑|组队|上号|上线|登号|排位|上分|陪你|带你|带我|奉陪)",
    # 整体推辞的固定说法
    r"(算了|懒得|没空|你们(玩|打)(吧|去)|你们去吧|别算我|别带我|下次吧|改天吧|不了|不去了)",
    # 自嘲式推辞
    r"(手残|我太菜|我菜|不会玩|玩不好|坑队友)",
]

# A-不-A 疑问式（来不来 / 玩不玩 / 打不打）是**邀约**，不是拒绝；
# 做拒绝判定前先把它抹掉，否则会被当成「不来」。
_ANOT_A_PATTERN = re.compile(
    r"(?P<verb>来|玩|打|去|开|联机|开黑|上号|上线|登号)\s*不\s*(?P=verb)"
)

_SENTENCE_SPLIT_LOOKBEHIND = r"(?<=[。！？!?…；;\n，,、])"


# ── 基础工具 ────────────────────────────────────────────────────────────────
def _compile(patterns: list[str]) -> list[Tuple[str, "re.Pattern[str]"]]:
    """编译规则；单条写错只丢这一条，不影响其它规则。"""

    compiled: list[Tuple[str, "re.Pattern[str]"]] = []
    for pattern in patterns:
        text = str(pattern or "").strip()
        if not text:
            continue
        try:
            compiled.append((text, re.compile(text, re.IGNORECASE)))
        except re.error as exc:
            logger.warning(f"{_LOG_TAG} 正则无效已跳过: {text!r} -> {exc}")
    return compiled


def _all_patterns(guard: "GuardSectionConfig") -> list[str]:
    """内置规则 + 用户追加的规则。"""

    return _builtin_patterns() + list(guard.extra_patterns or [])


def _collect_text_components(message: dict[str, Any]) -> Tuple[str, bool]:
    """提取麦麦自己写的正文。

    Args:
        message: 出站消息字典（``send_service.after_build_message`` 传入）。

    Returns:
        Tuple[str, bool]: ``(正文文本, 是否只由纯文本组件构成)``。
            第二个值决定 ``strip`` 模式能否安全改写结构。
    """

    raw = message.get("raw_message")
    if not isinstance(raw, list):
        return "", False

    parts: list[str] = []
    text_only = True
    for component in raw:
        if not isinstance(component, dict):
            text_only = False
            continue
        component_type = str(component.get("type", "") or "").strip().lower()
        if component_type == "text":
            parts.append(str(component.get("data", "") or ""))
            continue
        if component_type in _IGNORED_COMPONENT_TYPES:
            continue
        if component_type in _NON_TEXT_COMPONENT_TYPES:
            text_only = False
            continue
        # 未知组件类型：跳过其内容，但不允许 strip（避免破坏消息结构）
        text_only = False

    return "".join(parts).strip(), text_only


def _split_sentences(text: str) -> list[str]:
    """按句末标点与逗号切句，保留标点。"""

    return [segment for segment in re.split(_SENTENCE_SPLIT_LOOKBEHIND, text) if segment.strip()]


def _is_refusal(text: str, extra_patterns: list[str]) -> bool:
    """判断这段文本是「拒绝/推辞」还是「邀约」。

    Args:
        text: 出站正文。
        extra_patterns: 配置里追加的额外拒绝正则。

    Returns:
        bool: 命中任一条拒绝规则则返回 ``True``（应放行）。
    """

    scrubbed = _ANOT_A_PATTERN.sub("", text)
    for pattern in _REFUSAL_PATTERNS + list(extra_patterns or []):
        try:
            if re.search(pattern, scrubbed, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


# ── 配置模型 ────────────────────────────────────────────────────────────────
class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__: ClassVar[str] = "基础设置"
    __ui_order__: ClassVar[int] = 0

    name: str = Field(
        default="maibot_no_games",
        description="插件内部名称；保持默认值即可",
    )
    config_version: str = Field(
        default="1.0.0",
        description="配置文件版本；保持默认值即可",
    )
    version: str = Field(
        default="1.0.0",
        description="插件版本；保持默认值即可",
    )
    enabled: bool = Field(
        default=True,
        description="是否启用插件；true 开启，false 关闭",
    )


class GuardSectionConfig(PluginConfigBase):
    """拒绝邀约的行为配置。"""

    __ui_label__: ClassVar[str] = "拒绝游戏邀约"
    __ui_order__: ClassVar[int] = 1

    enabled: bool = Field(
        default=True,
        description="是否启用拦截；true 开启，false 关闭（插件仍会加载）",
    )
    dry_run: bool = Field(
        default=False,
        description="true 时只把命中的消息写进日志、不拦截，用于先观察命中精度",
    )
    action: str = Field(
        default="abort",
        description="abort=整条不发；strip=删掉命中那句（删空则不发）",
    )
    extra_patterns: list[str] = Field(
        default_factory=list,
        description="额外禁止正则，追加到内置规则之后",
    )
    extra_keywords: list[str] = Field(
        default_factory=list,
        description="额外禁止关键词，子串命中即拦",
    )
    refusal_patterns: list[str] = Field(
        default_factory=list,
        description="额外「拒绝话术」正则；命中说明麦麦在回绝而非邀约，一律放行（一般留空）",
    )


class NoGamesConfig(PluginConfigBase):
    """插件完整配置。"""

    plugin: PluginSectionConfig = Field(
        default_factory=PluginSectionConfig,
        description="插件基础设置",
    )
    guard: GuardSectionConfig = Field(
        default_factory=GuardSectionConfig,
        description="拒绝游戏邀约设置",
    )


# ── 插件主体 ────────────────────────────────────────────────────────────────
class NoGamesPlugin(MaiBotPlugin):
    """让麦麦拒绝游戏邀约：不主动约、不答应、不承诺参与。"""

    config_model = NoGamesConfig

    # ── 生命周期（SDK 2.x 要求三个方法都必须覆写）────────────────────────────
    async def on_load(self) -> None:
        guard = self._guard_config()
        total = len(_builtin_patterns()) + len(guard.extra_patterns)
        logger.info(
            f"{_LOG_TAG} 插件已加载：规则集「{BUILTIN_RULE_SET}」{total} 条，"
            f"action={guard.action}，dry_run={guard.dry_run}，enabled={guard.enabled}"
        )

    async def on_unload(self) -> None:
        logger.info(f"{_LOG_TAG} 插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        """配置热重载。

        本插件在每次发送前都会重新读取配置（见 ``_guard_config``），
        因此这里不需要重启任何任务，只记录变更即可。
        """

        del config_data
        guard = self._guard_config()
        logger.info(
            f"{_LOG_TAG} 配置已更新: scope={scope}, version={version}, "
            f"enabled={guard.enabled}, dry_run={guard.dry_run}, action={guard.action}"
        )

    # ── 钩子 ────────────────────────────────────────────────────────────────
    @HookHandler(
        _HOOK_NAME,
        name="no_games_after_build",
        description="麦麦要发出游戏邀约/承诺时拦下本次发送（放行它自己的拒绝话术）",
    )
    async def handle_after_build_message(
        self,
        message: dict[str, Any] | None = None,
        stream_id: str = "",
        processed_plain_text: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """检查出站消息，命中则中止或改写；任何异常都放行。"""

        try:
            return self._inspect(message, stream_id, processed_plain_text, kwargs)
        except Exception as exc:  # noqa: BLE001 - 必须 fail-open
            logger.warning(f"{_LOG_TAG} 检查异常，已放行本条消息: {exc}")
            return {"action": "continue"}

    # ── 内部实现 ────────────────────────────────────────────────────────────
    def _guard_config(self) -> GuardSectionConfig:
        """读取拦截配置；配置不可用时退回默认值（绝不因配置问题阻断发送）。"""

        try:
            guard = getattr(self.config, "guard", None)
            if isinstance(guard, GuardSectionConfig):
                return guard
        except Exception:  # noqa: BLE001
            pass
        return GuardSectionConfig()

    def _inspect(
        self,
        message: dict[str, Any] | None,
        stream_id: str,
        processed_plain_text: str,
        raw_kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """核心检查逻辑。"""

        guard = self._guard_config()
        if not guard.enabled or not isinstance(message, dict):
            return {"action": "continue"}

        text, text_only = _collect_text_components(message)
        if not text:
            # 拿不到正文就退而用宿主的纯文本；此路径下不做结构改写
            text = str(processed_plain_text or "").strip()
            text_only = False
        if not text:
            return {"action": "continue"}

        hit = self._match_raw(text, guard)
        if hit is None:
            return {"action": "continue"}
        if _is_refusal(text, guard.refusal_patterns):
            logger.info(
                f"{_LOG_TAG} 它在拒绝，放行 stream={stream_id}（原命中 {hit[1]!r}）原文={text!r}"
            )
            return {"action": "continue"}
        rule, matched = hit

        if guard.dry_run:
            logger.info(
                f"{_LOG_TAG}[dry_run] 命中但放行 stream={stream_id} 规则={rule!r} 片段={matched!r} 原文={text!r}"
            )
            return {"action": "continue"}

        action = str(guard.action or "abort").strip().lower()
        if action == "strip" and text_only:
            remain = self._strip(text, guard)
            if remain:
                message["raw_message"] = [{"type": "text", "data": remain}]
                modified_kwargs = dict(raw_kwargs)
                modified_kwargs.update(
                    {
                        "message": message,
                        "stream_id": stream_id,
                        "processed_plain_text": processed_plain_text,
                    }
                )
                logger.info(f"{_LOG_TAG} 已删掉邀约句 stream={stream_id} 规则={rule!r} 剩余={remain!r}")
                return {"action": "continue", "modified_kwargs": modified_kwargs}

        logger.error(
            f"{_LOG_TAG} 已拦下游戏邀约 stream={stream_id} 规则={rule!r} 片段={matched!r} 原文={text!r}"
        )
        return {"action": "abort"}

    @staticmethod
    def _match_raw(text: str, guard: GuardSectionConfig) -> Optional[Tuple[str, str]]:
        """只做模式匹配，返回第一个命中的 ``(规则, 命中片段)``。"""

        for keyword in guard.extra_keywords or []:
            word = str(keyword or "").strip()
            if word and word in text:
                return f"keyword:{word}", word

        for pattern, compiled in _compile(_all_patterns(guard)):
            match = compiled.search(text)
            if match is not None:
                return pattern, match.group(0)
        return None

    @staticmethod
    def _match(text: str, guard: GuardSectionConfig) -> Optional[Tuple[str, str]]:
        """最终判定：命中禁止规则、且不是拒绝话术时才算违规。"""

        hit = NoGamesPlugin._match_raw(text, guard)
        if hit is None or _is_refusal(text, guard.refusal_patterns):
            return None
        return hit

    @staticmethod
    def _strip(text: str, guard: GuardSectionConfig) -> str:
        """删掉包含命中内容的句子，返回剩余文本（保留原有标点）。"""

        patterns = _compile(_all_patterns(guard))
        keywords = [str(word).strip() for word in (guard.extra_keywords or []) if str(word).strip()]
        remain_parts: list[str] = []
        for sentence in _split_sentences(text):
            if any(word in sentence for word in keywords):
                continue
            if any(compiled.search(sentence) for _pattern, compiled in patterns):
                continue
            remain_parts.append(sentence)
        return "".join(remain_parts).strip()


# 插件运行时（SDK 2.x）要求入口模块导出 `create_plugin` 工厂函数，
# 否则会报「缺少 create_plugin 工厂函数」而拒绝加载。
def create_plugin() -> NoGamesPlugin:
    """创建插件实例。"""

    return NoGamesPlugin()
