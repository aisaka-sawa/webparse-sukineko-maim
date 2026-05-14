"""Suki 预约查询插件 - 从 Supabase 获取预约数据，以 HTML 渲染 PNG 图片形式回复用户"""

from datetime import datetime, timezone

import aiohttp
from maibot_sdk import Command, MaiBotPlugin, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

# Supabase API 配置
SUPABASE_URL = "https://uzlzkjuijruqanetagxh.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_6_fvEEW8e1DNGvtVhXPzxw_h2i04w7b"

# 请求头（模拟浏览器行为，携带 Supabase 认证信息）
HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Accept": "*/*",
    "accept-profile": "public",
    "x-client-info": "supabase-js-web/2.39.3",
    "Origin": "https://vrcsuki.chat",
}

# 请求超时（秒）
REQUEST_TIMEOUT = 10

# HTML 渲染宽度（iPhone 14 竖屏 CSS 像素宽度）
RENDER_WIDTH = 390

# ── HTML CSS 常量（咖啡厅主题） ──────────────────────────────────────
CSS_COMMON = """
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    width: {width}px;
    font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
                 "Noto Sans SC", sans-serif;
    background: #FDF6F0;
    color: #4A3728;
    padding: 20px 16px 24px;
    line-height: 1.5;
  }
  .header {
    text-align: center;
    margin-bottom: 20px;
    padding-bottom: 16px;
    border-bottom: 2px solid #E8D5C4;
  }
  .header .brand {
    font-size: 20px;
    font-weight: 700;
    color: #6B4226;
    letter-spacing: 0.5px;
  }
  .header .subtitle {
    font-size: 13px;
    color: #8B7355;
    margin-top: 4px;
  }
  .header .status-tag {
    display: inline-block;
    margin-top: 8px;
    padding: 3px 14px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
  }
  .status-open {
    background: #E8F5E9;
    color: #2E7D32;
  }
  .status-closed {
    background: #FFEBEE;
    color: #C62828;
  }
  .card {
    background: #FFFFFF;
    border-radius: 14px;
    padding: 14px;
    margin-bottom: 14px;
    box-shadow: 0 2px 8px rgba(107,66,38,0.08);
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }
  .card-img {
    width: 72px;
    height: 72px;
    border-radius: 10px;
    object-fit: cover;
    flex-shrink: 0;
    background: #F0E6DA;
  }
  .card-info {
    flex: 1;
    min-width: 0;
  }
  .card-name {
    font-size: 16px;
    font-weight: 700;
    color: #4A3728;
    margin-bottom: 4px;
  }
  .card-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-bottom: 6px;
  }
  .card-tag {
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 8px;
    background: #F5EDE3;
    color: #8B7355;
    white-space: nowrap;
  }
  .card-signature {
    font-size: 12px;
    color: #A08C7A;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .card-badge {
    flex-shrink: 0;
    margin-top: 18px;
    text-align: center;
  }
  .badge-avail {
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 10px;
    background: #E8F5E9;
    color: #388E3C;
    font-weight: 600;
    white-space: nowrap;
  }
  .badge-booked {
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 10px;
    background: #FFF3E0;
    color: #E65100;
    font-weight: 600;
    white-space: nowrap;
  }
  /* 详情页样式 */
  .detail-img-wrap {
    text-align: center;
    margin-bottom: 16px;
  }
  .detail-img {
    width: 100%;
    max-height: 280px;
    border-radius: 14px;
    object-fit: cover;
    background: #F0E6DA;
  }
  .detail-header {
    text-align: center;
    margin-bottom: 18px;
  }
  .detail-name {
    font-size: 22px;
    font-weight: 700;
    color: #6B4226;
  }
  .detail-tags {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 6px;
    margin-top: 8px;
  }
  .detail-tag {
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 10px;
    background: #F5EDE3;
    color: #8B7355;
  }
  .detail-signature {
    font-size: 13px;
    color: #A08C7A;
    margin-top: 6px;
    text-align: center;
  }
  .section-title {
    font-size: 14px;
    font-weight: 600;
    color: #6B4226;
    margin-bottom: 10px;
    padding-left: 4px;
    border-left: 3px solid #C87941;
  }
  .resv-card {
    background: #FFFFFF;
    border-radius: 12px;
    padding: 12px 14px;
    margin-bottom: 10px;
    box-shadow: 0 1px 4px rgba(107,66,38,0.06);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .resv-time {
    font-size: 14px;
    font-weight: 600;
    color: #4A3728;
  }
  .resv-guest {
    font-size: 12px;
    color: #8B7355;
  }
  .empty-state {
    text-align: center;
    padding: 40px 20px;
    color: #A08C7A;
    font-size: 14px;
  }
  .footer {
    text-align: center;
    margin-top: 18px;
    padding-top: 12px;
    border-top: 1px solid #E8D5C4;
    font-size: 11px;
    color: #B8A590;
  }
  .summary-row {
    display: flex;
    justify-content: center;
    gap: 20px;
    margin-bottom: 16px;
  }
  .summary-item {
    text-align: center;
    font-size: 12px;
    color: #8B7355;
  }
  .summary-num {
    font-size: 18px;
    font-weight: 700;
    color: #6B4226;
  }
  .maid-disabled-tag {
    display: inline-block;
    margin-top: 8px;
    padding: 3px 14px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    background: #F5F5F5;
    color: #9E9E9E;
  }
"""


class SukiBookingPlugin(MaiBotPlugin):
    """Suki 预约查询插件"""

    async def on_load(self) -> None:
        self.ctx.logger.info("Suki 预约查询插件已加载")

    async def on_unload(self) -> None:
        self.ctx.logger.info("Suki 预约查询插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        if scope == "self":
            self.ctx.logger.info("插件配置已更新: version=%s", version)

    # ── 数据获取 ──────────────────────────────────────────────────────

    async def _fetch_booking(self, limit: int = 1) -> list | None:
        """从 Supabase 获取预约数据，过滤无关字段后返回 JSON 列表或 None（失败时）

        保留字段:
          - maids: name, image, disabled, tags, signature
          - reservations: maidName, timeSlot, guestUsername
          - booking_enabled

        Args:
            limit: 返回记录数量上限，默认 1
        """
        self.ctx.logger.debug("开始请求 Supabase API，limit=%d", limit)
        url = f"{SUPABASE_URL}/rest/v1/suki_booking?select=*&limit={limit}"
        try:
            async with aiohttp.ClientSession() as session:
                self.ctx.logger.debug("发起 HTTP GET: %s", url)
                async with session.get(
                    url,
                    headers=HEADERS,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    self.ctx.logger.debug("收到响应: status=%d", resp.status)
                    if resp.status == 200:
                        raw: list = await resp.json()
                        data = [self._filter_booking(item) for item in raw]
                        self.ctx.logger.info(
                            "API 请求成功，获取到 %d 条记录",
                            len(data),
                        )
                        return data
                    else:
                        self.ctx.logger.error(
                            "API 请求失败: status=%d, body=%s",
                            resp.status,
                            await resp.text(),
                        )
                        return None
        except aiohttp.ClientError as e:
            self.ctx.logger.error("网络请求异常: %s", e)
            return None
        except Exception as e:
            self.ctx.logger.error("未知异常: %s", e)
            return None

    @staticmethod
    def _filter_booking(raw: dict) -> dict:
        """从原始 API 数据中提取需要的字段，清除无关字段

        Returns:
            {"maids": [...], "reservations": [...], "booking_enabled": bool}
        """
        maids = []
        for m in raw.get("maids", []) or []:
            maids.append(
                {
                    "name": m.get("name", ""),
                    "image": m.get("image", ""),
                    "disabled": m.get("disabled", False),
                    "tags": m.get("tags", []) or [],
                    "signature": m.get("signature", "") or "",
                }
            )

        reservations = []
        for r in raw.get("reservations", []) or []:
            reservations.append(
                {
                    "maidName": r.get("maidName", ""),
                    "timeSlot": r.get("timeSlot", ""),
                    "guestUsername": r.get("guestUsername", ""),
                }
            )

        return {
            "maids": maids,
            "reservations": reservations,
            "booking_enabled": raw.get("booking_enabled", False),
        }

    # ── 数据统计辅助 ──────────────────────────────────────────────────

    @staticmethod
    def _count_reservations_per_maid(reservations: list) -> dict[str, int]:
        """按女仆名称统计预约数量

        Returns:
            {"女仆名称": 预约数}
        """
        counts: dict[str, int] = {}
        for r in reservations:
            name = r.get("maidName", "")
            if name:
                counts[name] = counts.get(name, 0) + 1
        return counts

    # ── 文本格式化（保留兼容） ────────────────────────────────────────

    @staticmethod
    def _format_booking(data: list) -> str:
        """将过滤后的预约数据列表格式化为可读文本（保留用于降级场景）"""
        if not data:
            return "暂无预约数据。"

        lines: list[str] = []
        for idx, item in enumerate(data):
            if len(data) > 1:
                lines.append(f"📋 预约 #{idx + 1}")
            else:
                lines.append("📋 **Suki 预约信息**")

            enabled = item.get("booking_enabled", False)
            status_text = "✅ 已开启" if enabled else "❌ 已关闭"
            lines.append(f"• 预约状态: {status_text}")

            maids = item.get("maids", []) or []
            online = [m for m in maids if not m.get("disabled")]
            offline = [m for m in maids if m.get("disabled")]
            lines.append(f"• 猫娘: 共 {len(maids)} 位（在线 {len(online)} / 离线 {len(offline)}）")

            for m in maids:
                icon = "🟢" if not m.get("disabled") else "🔴"
                name = m.get("name", "未知")
                lines.append(f"  {icon} {name}")

            reservations = item.get("reservations", []) or []
            lines.append(f"• 预约记录: 共 {len(reservations)} 条")

            for r in reservations:
                maid_name = r.get("maidName", "")
                time_slot = r.get("timeSlot", "")
                guest = r.get("guestUsername", "")
                lines.append(f"  🕐 {maid_name} | {time_slot} | {guest}")

            if idx < len(data) - 1:
                lines.append("")

        return "\n".join(lines)

    # ── HTML 生成：模板一 - 可预约女仆一览 ────────────────────────────

    @staticmethod
    def _generate_available_maids_html(data: dict) -> str:
        """生成「可预约女仆一览」HTML

        筛选条件: disabled=false 且预约数 ≤ 1

        Args:
            data: _filter_booking 返回的单条记录

        Returns:
            完整的 HTML 字符串
        """
        maids = data.get("maids", []) or []
        reservations = data.get("reservations", []) or []
        booking_enabled = data.get("booking_enabled", False)

        # 统计预约数
        reserve_counts = SukiBookingPlugin._count_reservations_per_maid(reservations)

        # 筛选可预约女仆（未禁用 且 预约数 ≤ 1）
        available = [m for m in maids if not m.get("disabled") and reserve_counts.get(m.get("name", ""), 0) <= 1]

        # 构建卡片
        cards_html = ""
        for m in available:
            name = m.get("name", "")
            image = m.get("image", "")
            tags = m.get("tags", []) or []
            signature = m.get("signature", "")
            count = reserve_counts.get(name, 0)

            tags_html = ""
            for t in tags[:3]:  # 最多显示 3 个标签
                tags_html += f'<span class="card-tag">{_escape_html(t)}</span>'

            if count == 0:
                badge_html = '<span class="badge-avail">可预约</span>'
            else:
                badge_html = f'<span class="badge-booked">已约 {count}/2</span>'

            sig_text = _escape_html(signature) if signature else "暂无签名"
            img_tag = (
                f'<img class="card-img" src="{_escape_html(image)}" '
                f'alt="{_escape_html(name)}" onerror="this.style.display=\'none\'">'
                if image
                else '<div class="card-img"></div>'
            )

            cards_html += f"""
    <div class="card">
      {img_tag}
      <div class="card-info">
        <div class="card-name">{_escape_html(name)}</div>
        <div class="card-tags">{tags_html}</div>
        <div class="card-signature">{sig_text}</div>
      </div>
      <div class="card-badge">{badge_html}</div>
    </div>"""

        if not available:
            cards_html = '<div class="empty-state">🌸 当前所有女仆均已约满<br>请稍后再来看看吧~</div>'

        # 汇总信息
        total_maids = len(maids)
        online_maids = len([m for m in maids if not m.get("disabled")])
        total_resv = len(reservations)

        status_html = (
            '<span class="status-tag status-open">预约开放中</span>'
            if booking_enabled
            else '<span class="status-tag status-closed">预约已关闭</span>'
        )

        now_str = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M")

        css = CSS_COMMON.replace("{width}", str(RENDER_WIDTH))

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width={RENDER_WIDTH}">
<style>{css}</style>
</head>
<body>
<div class="header">
  <div class="brand">☕ Suki 猫娘咖啡厅</div>
  <div class="subtitle">可预约女仆一览</div>
  {status_html}
</div>
<div class="summary-row">
  <div class="summary-item">
    <div class="summary-num">{online_maids}</div>
    <div>位女仆</div>
  </div>
  <div class="summary-item">
    <div class="summary-num">{len(available)}</div>
    <div>可预约</div>
  </div>
  <div class="summary-item">
    <div class="summary-num">{total_resv}</div>
    <div>条预约</div>
  </div>
</div>
{cards_html}
<div class="footer">更新时间 {now_str}（UTC）</div>
</body>
</html>"""

    # ── HTML 生成：模板二 - 单个女仆预约详情 ──────────────────────────

    @staticmethod
    def _generate_maid_detail_html(data: dict, maid_name: str) -> str:
        """生成「单个女仆预约详情」HTML

        Args:
            data: _filter_booking 返回的单条记录
            maid_name: 目标女仆名称

        Returns:
            完整的 HTML 字符串，若未找到目标女仆则返回空状态
        """
        maids = data.get("maids", []) or []
        reservations = data.get("reservations", []) or []
        booking_enabled = data.get("booking_enabled", False)

        # 查找目标女仆
        target = None
        for m in maids:
            if m.get("name", "") == maid_name:
                target = m
                break

        if target is None:
            css = CSS_COMMON.replace("{width}", str(RENDER_WIDTH))
            return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><style>{css}</style></head>
<body>
<div class="header">
  <div class="brand">☕ Suki 猫娘咖啡厅</div>
</div>
<div class="empty-state">未找到女仆「{_escape_html(maid_name)}」的信息</div>
<div class="footer">请确认女仆名称是否正确</div>
</body>
</html>"""

        # 该女仆的预约记录
        maid_reservations = [r for r in reservations if r.get("maidName", "") == maid_name]

        name = target.get("name", "")
        image = target.get("image", "")
        tags = target.get("tags", []) or []
        signature = target.get("signature", "")
        disabled = target.get("disabled", False)

        # 标签
        tags_html = ""
        for t in tags:
            tags_html += f'<span class="detail-tag">{_escape_html(t)}</span>'

        sig_text = _escape_html(signature) if signature else ""

        # 状态标签
        if disabled:
            status_html = '<span class="maid-disabled-tag">暂不接单</span>'
        elif not booking_enabled:
            status_html = '<span class="status-tag status-closed">预约已关闭</span>'
        else:
            status_html = '<span class="status-tag status-open">可预约</span>'

        # 预约记录列表
        resv_html = ""
        if maid_reservations:
            for r in maid_reservations:
                time_slot = _escape_html(r.get("timeSlot", ""))
                guest = _escape_html(r.get("guestUsername", ""))
                resv_html += f"""
    <div class="resv-card">
      <div>
        <div class="resv-time">🕐 {time_slot}</div>
        <div class="resv-guest">👤 {guest}</div>
      </div>
    </div>"""
        else:
            resv_html = '<div class="empty-state" style="padding:24px 20px">📭 暂无预约记录</div>'

        img_tag = (
            f'<img class="detail-img" src="{_escape_html(image)}" '
            f'alt="{_escape_html(name)}" onerror="this.style.display=\'none\'">'
            if image
            else '<div class="detail-img" style="height:200px"></div>'
        )

        now_str = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M")

        css = CSS_COMMON.replace("{width}", str(RENDER_WIDTH))

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width={RENDER_WIDTH}">
<style>{css}</style>
</head>
<body>
<div class="header">
  <div class="brand">☕ Suki 猫娘咖啡厅</div>
  <div class="subtitle">女仆预约详情</div>
</div>
<div class="detail-img-wrap">
  {img_tag}
</div>
<div class="detail-header">
  <div class="detail-name">{_escape_html(name)}</div>
  {status_html}
  <div class="detail-tags">{tags_html}</div>
  {f'<div class="detail-signature">「{sig_text}」</div>' if sig_text else ""}
</div>
<div class="section-title">📋 预约记录（{len(maid_reservations)} 条）</div>
{resv_html}
<div class="footer">更新时间 {now_str}（UTC）</div>
</body>
</html>"""

    # ── 渲染 & 发送 ───────────────────────────────────────────────────

    async def _render_and_send_png(self, html: str, stream_id: str) -> str | None:
        """将 HTML 渲染为 PNG 并发送到聊天流

        Args:
            html: 完整的 HTML 字符串
            stream_id: 当前聊天流 ID

        Returns:
            成功时返回 base64 图片数据，失败时返回 None
        """
        try:
            result = await self.ctx.render.html2png(
                html=html,
                # allow_network=True,
                wait_until="domcontentloaded",  # 同时改这个，避免外部资源加载慢导致超时
            )
        except Exception as e:
            self.ctx.logger.error("html2png 渲染异常: %s", e)
            return None

        if not result:
            self.ctx.logger.error("html2png 返回空结果")
            return None

        # 解析返回结果：可能是 base64 字符串，也可能是 dict
        if isinstance(result, str):
            image_base64 = result
        elif isinstance(result, dict):
            image_base64 = result.get("image_base64") or result.get("data") or result.get("image") or ""
        elif isinstance(result, bytes):
            from base64 import b64encode

            image_base64 = b64encode(result).decode("ascii")
        else:
            self.ctx.logger.error("html2png 返回了未知类型: %s", type(result))
            return None

        if not image_base64:
            self.ctx.logger.error("未能从 html2png 结果中提取图片数据")
            return None

        try:
            await self.ctx.send.image(image_data=image_base64, stream_id=stream_id)
            self.ctx.logger.info("PNG 图片已发送到 stream_id=%s", stream_id)
        except Exception as e:
            self.ctx.logger.error("发送图片失败: %s", e)
            return None

        return image_base64

    # ── Tool 组件 ─────────────────────────────────────────────────────

    @Tool(
        "query_suki_booking",
        description=(
            "查询 Suki 猫娘咖啡厅的预约信息。"
            "不指定 maid_name 时返回当前可预约女仆一览（预约数 0~1 的女仆列表）；"
            "指定 maid_name 时返回该女仆的详细预约情况。"
            "适用于用户询问 Suki 预约状态、某女仆是否可约、预约时间安排等场景。"
        ),
        parameters=[
            ToolParameterInfo(
                name="maid_name",
                param_type=ToolParamType.STRING,
                description="要查询的女仆名称。不填则返回所有可预约女仆列表",
                required=False,
            ),
            ToolParameterInfo(
                name="limit",
                param_type=ToolParamType.INTEGER,
                description="返回记录数量上限，默认 1",
                required=False,
                default=1,
            ),
        ],
    )
    async def handle_tool_query_booking(self, maid_name: str = "", limit: int = 1, **kwargs):
        """AI 工具调用：查询 Suki 预约信息，生成 PNG 图片返回"""
        stream_id: str = kwargs.get("stream_id", "")
        self.ctx.logger.info("Tool query_suki_booking 被调用: maid_name=%s, limit=%d", maid_name, limit)

        data = await self._fetch_booking(limit=limit)
        if data is None:
            self.ctx.logger.warning("Tool query_suki_booking: 数据获取失败")
            return {"success": False, "content": "查询失败，请稍后重试。"}

        items: list = data if isinstance(data, list) else [data]
        if not items:
            return {"success": False, "content": "暂无预约数据。"}

        item = items[0]  # 取第一条记录
        self.ctx.logger.debug(
            "Tool query_suki_booking: 获取到数据，maids=%d, reservations=%d",
            len(item.get("maids", [])),
            len(item.get("reservations", [])),
        )

        # 根据是否指定 maid_name 选择模板
        if maid_name and maid_name.strip():
            html = self._generate_maid_detail_html(item, maid_name.strip())
            desc = f"已生成女仆「{maid_name}」的预约详情图片"
        else:
            html = self._generate_available_maids_html(item)
            desc = "已生成可预约女仆一览图片"

        # 尝试渲染并发送 PNG
        image_base64 = None
        if stream_id:
            image_base64 = await self._render_and_send_png(html, stream_id)

        # 构建返回结果
        if image_base64:
            self.ctx.logger.info("Tool query_suki_booking: 图片生成并发送成功")
            return {
                "success": True,
                "content": desc,
                "content_items": [
                    {
                        "type": "image",
                        "data": image_base64,
                        "mime_type": "image/png",
                        "name": "suki_booking.png",
                        "description": desc,
                    }
                ],
            }
        else:
            # 降级：返回文本
            self.ctx.logger.warning("Tool query_suki_booking: 图片渲染失败，降级为文本")
            formatted = self._format_booking(items)
            return {"success": True, "content": formatted}

    # ── Command 组件 ──────────────────────────────────────────────────

    @Command("suki", pattern=r"^/suki")
    async def handle_suki(self, **kwargs):
        """查询 Suki 预约信息 — 以可预约女仆一览 PNG 图片形式返回"""
        stream_id: str = kwargs["stream_id"]
        self.ctx.logger.info("Command /suki 被触发，stream_id=%s", stream_id)

        self.ctx.logger.debug("Command /suki: 发送查询提示")
        await self.ctx.send.text("🔍 正在查询 Suki 预约信息...", stream_id)

        data = await self._fetch_booking()
        if data is None:
            self.ctx.logger.warning("Command /suki: 数据获取失败")
            await self.ctx.send.text("❌ 查询失败，请稍后重试。", stream_id)
            return False, "查询失败", 1

        items: list = data if isinstance(data, list) else [data]
        if not items:
            await self.ctx.send.text("暂无预约数据。", stream_id)
            return True, "暂无数据", 1

        item = items[0]
        self.ctx.logger.debug("Command /suki: 获取到数据，开始生成可预约女仆一览 HTML")

        html = self._generate_available_maids_html(item)
        image_base64 = await self._render_and_send_png(html, stream_id)

        if image_base64:
            self.ctx.logger.info("Command /suki: PNG 图片发送成功")
            return True, "查询成功（图片）", 1
        else:
            # 降级为文本
            self.ctx.logger.warning("Command /suki: 图片渲染失败，降级为文本")
            formatted = self._format_booking(items)
            await self.ctx.send.text(formatted, stream_id)
            return True, "查询成功（文本降级）", 1


# ── HTML 转义 ────────────────────────────────────────────────────────


def _escape_html(s: str) -> str:
    """转义 HTML 特殊字符"""
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
    )


def create_plugin():
    return SukiBookingPlugin()
