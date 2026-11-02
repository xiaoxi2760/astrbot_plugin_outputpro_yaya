from astrbot.core.message.components import (
    At,
    Face,
    Image,
    Plain,
    Reply,
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..config import PluginConfig
from ..model import OutContext, StepName, StepResult
from .base import BaseStep


class ReplyStep(BaseStep):
    name = StepName.REPLY

    # 不支持引用组件的平台（插入 Reply 会被平台直接忽略或报错）
    unsupported_platforms = {"dingtalk", "qqofficial_webhook", "wecom"}

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self.cfg = config.reply

    # -------------------------
    # 工具方法
    # -------------------------
    def _insert_quote(self, ctx: OutContext, msg_id: str) -> None:
        """在消息链头部插入引用组件，按配置附带艾特"""
        ctx.chain.insert(0, Reply(id=msg_id))
        if self.cfg.include_at and isinstance(ctx.event, AiocqhttpMessageEvent):
            ctx.chain.insert(1, At(qq=ctx.event.get_sender_id()))
            # 在 At 后添加带零宽空格包裹的空格，确保与后续内容有间距
            ctx.chain.insert(2, Plain(text="\u200b \u200b"))

    def _advance_queue(self, ctx: OutContext, msg_id: str) -> None:
        """推进消息队列：移除已处理的消息，并记录 bot 的插话标记"""
        queue = ctx.group.msg_queue
        if not queue:
            return

        # 仅移除已引用的消息及其之前的记录，保留之后的消息用于后续引用判断
        while queue and str(queue[0]) != msg_id:
            queue.popleft()
        if queue and str(queue[0]) == msg_id:
            queue.popleft()

        # 追加 bot 插嘴标记，确保后续回复也能判断“被插嘴”
        if ctx.group.last_reply_mark_msg_id != msg_id:
            queue.append(f"__bot_reply__{msg_id}")
            ctx.group.last_reply_mark_msg_id = msg_id

    # -------------------------
    # 主入口
    # -------------------------
    async def handle(self, ctx: OutContext) -> StepResult:
        platform_name = ctx.event.get_platform_name()
        if platform_name in self.unsupported_platforms:
            return StepResult(msg=f"平台不支持智能引用，已跳过: {platform_name}")

        # 链中已有引用组件（AstrBot 自带引用或其他插件插入）→ 不重复引用
        if any(isinstance(x, Reply) for x in ctx.chain):
            return StepResult(msg="消息链中已存在引用组件，跳过智能引用")

        # 仅处理由文本/图片/表情/艾特组成的简单消息链
        if not all(isinstance(x, Plain | Image | Face | At) for x in ctx.chain):
            return StepResult()

        msg_id = str(ctx.event.message_obj.message_id or "")
        if not msg_id:
            return StepResult(msg="未取到消息 ID，跳过智能引用")

        # ===== 始终引用：凡是经过本步骤的回复都引用被回复的那条消息 =====
        if self.cfg.always_quote:
            self._insert_quote(ctx, msg_id)
            self._advance_queue(ctx, msg_id)
            return StepResult(msg=f"已插入Reply组件, 引用消息{msg_id}")

        # ===== 阈值模式：被插嘴条数达到阈值才引用 =====
        if self.cfg.threshold <= 0:
            return StepResult()

        queue = ctx.group.msg_queue
        queue_str = [str(x) for x in queue]
        if msg_id not in queue_str:
            return StepResult()

        idx = queue_str.index(msg_id)
        pushed = len(queue) - idx - 1
        if pushed < self.cfg.threshold:
            return StepResult()

        self._insert_quote(ctx, msg_id)
        self._advance_queue(ctx, msg_id)
        return StepResult(msg=f"已插入Reply组件, 引用消息{msg_id}")
