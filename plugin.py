"""Suki 预约查询插件 - 从 Supabase 获取预约数据，以 HTML 渲染 PNG 图片形式回复用户"""

import asyncio
import hashlib
import io
import math
import os
import random
from base64 import b64encode
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

# 单张女仆图片下载超时（秒）
IMAGE_DOWNLOAD_TIMEOUT = 10 * 60

# 每次查库前的轻量延迟（秒），避免数据库随机与本地随机在同一瞬时触发
DB_QUERY_DELAY_SECONDS = 0.3

# HTML 渲染宽度（iPhone 14 竖屏 CSS 像素宽度）
RENDER_WIDTH = 390

# ── 概率/权重设置 ─────────────────────────────────
# 暂时保持为空，所有女仆都会使用 DEFAULT_DRAW_WEIGHT，确保公平抽取。
# 之后如需单独调整，可按女仆名称配置，例如 {"女仆名称": 2.0}。
DEFAULT_DRAW_WEIGHT = 1.0
CUSTOM_WEIGHTS: dict[str, float] = {
    "茶壶": 0.2,
    "浩瀚": 0.5,
    # "依卡卡卡": 1.2,
    # "玉藻夏夜": 1.2,
    # "肆桉": 1.2,
    # "布拉克": 1.1,
    "南熙": 0.4,
    "雾山": 0.4,
    "瑶瑶": 0.4,
}

# ── CSS 加载（从 static/style.css 读取，按宽度缓存） ─────────────────
_CSS_CACHE: dict[int, str] = {}


def _load_css(width: int) -> str:
    """读取 CSS 文件并替换 {width} 占位符，按宽度缓存"""
    if width not in _CSS_CACHE:
        css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "style.css")
        with open(css_path, "r", encoding="utf-8") as f:
            _CSS_CACHE[width] = f.read().replace("{width}", str(width))
    return _CSS_CACHE[width]


class SukiBookingPlugin(MaiBotPlugin):
    """Suki 预约查询插件"""

    async def on_load(self) -> None:
        self.ctx.logger.info("Suki 预约查询插件已加载")
        self._image_cache: dict[str, str] = {}
        self._image_cache_hd: dict[str, str] = {}
        try:
            await self._download_images()
        except Exception as e:
            self.ctx.logger.error("图片缓存初始化失败: %s", e)

    async def on_unload(self) -> None:
        self.ctx.logger.info("Suki 预约查询插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        if scope == "self":
            self.ctx.logger.info("插件配置已更新: version=%s", version)

    # ── 图片缓存 ──────────────────────────────────────────────────────

    async def _download_images(self) -> None:
        """插件加载时缓存所有女仆图片，建立双版本 base64 内存缓存

        - self._image_cache: 400px 宽缩略图，用于一览模式（双栏/单栏）
        - self._image_cache_hd: 800px 宽高清图，用于单个女仆详情页
        """
        pic_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pic")
        os.makedirs(pic_dir, exist_ok=True)
        self._image_cache = {}
        self._image_cache_hd = {}

        data = await self._fetch_booking(limit=1)
        if not data:
            self.ctx.logger.warning("图片缓存: 无法获取预约数据，跳过图片下载")
            return

        seen_urls: set[str] = set()
        for item in data:
            for m in item.get("maids", []) or []:
                url = m.get("image", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                # 从 URL 提取文件扩展名
                url_path = url.split("?")[0]
                ext = "png"
                filename = url_path.rsplit("/", 1)[-1]
                if "." in filename:
                    raw_ext = filename.rsplit(".", 1)[-1].lower()
                    if raw_ext in ("jpg", "jpeg", "png", "gif", "webp", "bmp"):
                        ext = raw_ext

                url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
                orig_filepath = os.path.join(pic_dir, f"{url_hash}_orig.{ext}")
                hd_filepath = os.path.join(pic_dir, f"{url_hash}_hd.jpg")
                thumb_filepath = os.path.join(pic_dir, f"{url_hash}_thumb.jpg")
                # 向后兼容旧格式
                legacy_filepath = os.path.join(pic_dir, f"{url_hash}.jpg")

                need_download = not os.path.exists(orig_filepath)

                if need_download:
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(
                                url,
                                timeout=aiohttp.ClientTimeout(total=IMAGE_DOWNLOAD_TIMEOUT),
                            ) as resp:
                                if resp.status == 200:
                                    content = await resp.read()
                                    # 保存原图
                                    with open(orig_filepath, "wb") as f:
                                        f.write(content)
                                    self.ctx.logger.info("原图已缓存: %s -> %s", url, orig_filepath)
                                else:
                                    self.ctx.logger.warning("下载图片失败: %s, status=%d", url, resp.status)
                                    continue
                    except Exception as e:
                        self.ctx.logger.error("下载图片异常: %s, %s", url, e)
                        continue

                # ── 生成高清版（从原图缩放至 800px 宽，quality 90） ──
                if not os.path.exists(hd_filepath) and os.path.exists(orig_filepath):
                    try:
                        from PIL import Image as PILImage

                        img = PILImage.open(orig_filepath)
                        if not getattr(img, "is_animated", False):
                            if img.mode in ("RGBA", "P", "LA"):
                                bg = PILImage.new("RGBA", img.size, (255, 255, 255, 255))
                                if img.mode == "P":
                                    img = img.convert("RGBA")
                                bg.paste(img, mask=img if img.mode == "RGBA" else None)
                                img = bg
                            img = img.convert("RGB")
                            if img.width > 800:
                                ratio = 800 / img.width
                                new_h = int(img.height * ratio)
                                img = img.resize((800, new_h), PILImage.LANCZOS)
                            buf = io.BytesIO()
                            img.save(buf, format="JPEG", quality=90, optimize=True)
                            with open(hd_filepath, "wb") as f:
                                f.write(buf.getvalue())
                            self.ctx.logger.debug(
                                "高清版已生成: %dx%d JPEG, %d bytes",
                                img.width,
                                img.height,
                                len(buf.getvalue()),
                            )
                    except Exception as e:
                        self.ctx.logger.debug("高清版生成失败（%s），降级使用原图", e)

                # ── 生成缩略版（从原图缩放至 400px 宽，quality 85） ──
                if not os.path.exists(thumb_filepath) and os.path.exists(orig_filepath):
                    # 尝试迁移旧格式文件
                    if os.path.exists(legacy_filepath):
                        try:
                            os.rename(legacy_filepath, thumb_filepath)
                            self.ctx.logger.debug(
                                "旧缩略图已迁移: %s -> %s",
                                legacy_filepath,
                                thumb_filepath,
                            )
                        except OSError:
                            pass
                    if not os.path.exists(thumb_filepath):
                        try:
                            from PIL import Image as PILImage

                            img = PILImage.open(orig_filepath)
                            if not getattr(img, "is_animated", False):
                                if img.mode in ("RGBA", "P", "LA"):
                                    bg = PILImage.new("RGBA", img.size, (255, 255, 255, 255))
                                    if img.mode == "P":
                                        img = img.convert("RGBA")
                                    bg.paste(img, mask=img if img.mode == "RGBA" else None)
                                    img = bg
                                img = img.convert("RGB")
                                if img.width > 400:
                                    ratio = 400 / img.width
                                    new_h = int(img.height * ratio)
                                    img = img.resize((400, new_h), PILImage.LANCZOS)
                                buf = io.BytesIO()
                                img.save(buf, format="JPEG", quality=85, optimize=True)
                                with open(thumb_filepath, "wb") as f:
                                    f.write(buf.getvalue())
                                self.ctx.logger.debug(
                                    "缩略版已生成: %dx%d JPEG, %d bytes",
                                    img.width,
                                    img.height,
                                    len(buf.getvalue()),
                                )
                        except Exception as e:
                            self.ctx.logger.debug("缩略版生成失败（%s），降级使用原图", e)

                # ── 加载高清版到内存缓存 ──
                hd_src = hd_filepath if os.path.exists(hd_filepath) else orig_filepath
                if os.path.exists(hd_src):
                    try:
                        with open(hd_src, "rb") as f:
                            hd_content = f.read()
                        mime = "image/jpeg" if hd_src.endswith(".jpg") or hd_src.endswith(".jpeg") else f"image/{ext}"
                        hd_b64 = b64encode(hd_content).decode("ascii")
                        self._image_cache_hd[url] = f"data:{mime};base64,{hd_b64}"
                    except Exception as e:
                        self.ctx.logger.error("读取高清缓存失败: %s, %s", hd_src, e)

                # ── 加载缩略版到内存缓存 ──
                thumb_src = thumb_filepath
                if not os.path.exists(thumb_src):
                    thumb_src = legacy_filepath
                if not os.path.exists(thumb_src):
                    thumb_src = orig_filepath
                if os.path.exists(thumb_src):
                    try:
                        with open(thumb_src, "rb") as f:
                            thumb_content = f.read()
                        mime = (
                            "image/jpeg"
                            if thumb_src.endswith(".jpg") or thumb_src.endswith(".jpeg")
                            else f"image/{ext}"
                        )
                        thumb_b64 = b64encode(thumb_content).decode("ascii")
                        self._image_cache[url] = f"data:{mime};base64,{thumb_b64}"
                    except Exception as e:
                        self.ctx.logger.error("读取缩略缓存失败: %s, %s", thumb_src, e)

        self.ctx.logger.info(
            "图片缓存完成: 共缓存 %d 张（高清 %d / 缩略 %d）",
            len(seen_urls),
            len(self._image_cache_hd),
            len(self._image_cache),
        )

    # ── 数据获取 ──────────────────────────────────────────────────────

    async def _fetch_booking(self, limit: int = 1) -> list | None:
        """从 Supabase 获取预约数据，过滤无关字段后返回 JSON 列表或 None（失败时）

        保留字段:
          - maids: name, image, disabled, vrcid, tags, signature, weight
          - reservations: maidName, maidVrcid, timeSlot, guestUsername
          - booking_enabled

        Args:
            limit: 返回记录数量上限，默认 1
        """
        self.ctx.logger.debug("开始请求 Supabase API，limit=%d", limit)
        url = f"{SUPABASE_URL}/rest/v1/suki_booking?select=*&limit={limit}"
        try:
            await asyncio.sleep(DB_QUERY_DELAY_SECONDS)
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
                    "vrcid": m.get("vrcid", ""),
                    "tags": m.get("tags", []) or [],
                    "signature": m.get("signature", "") or "",
                    "weight": m.get("weight", DEFAULT_DRAW_WEIGHT),
                }
            )

        reservations = []
        for r in raw.get("reservations", []) or []:
            reservations.append(
                {
                    "maidName": r.get("maidName", ""),
                    "maidVrcid": r.get("maidVrcid", ""),
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
    def _count_reservations_per_maid(maids: list, reservations: list) -> dict[str, int]:
        """按女仆 vrcid 统计预约数量

        Returns:
            {"女仆名称": 预约数}
        """
        vrcid_to_name = {
            m.get("vrcid", ""): m.get("name", "") for m in maids if m.get("vrcid", "") and m.get("name", "")
        }
        known_names = {m.get("name", "") for m in maids if m.get("name", "")}

        counts: dict[str, int] = {}
        for r in reservations:
            vrcid = r.get("maidVrcid", "")
            name = vrcid_to_name.get(vrcid, "")
            if not name:
                # 兼容旧测试数据或旧缓存：只有缺少 vrcid 时才退回名称精确匹配。
                fallback_name = r.get("maidName", "")
                if fallback_name in known_names:
                    name = fallback_name
            if name:
                counts[name] = counts.get(name, 0) + 1
        return counts

    @staticmethod
    def _normalized_draw_weights(maids: list[dict]) -> list[float]:
        """为随机抽取生成可用权重，非法/缺失权重统一回落到公平权重"""
        weights: list[float] = []
        for maid in maids:
            name = maid.get("name", "")
            raw_weight = CUSTOM_WEIGHTS.get(name, maid.get("weight", DEFAULT_DRAW_WEIGHT))
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError):
                weight = DEFAULT_DRAW_WEIGHT

            if not math.isfinite(weight) or weight <= 0:
                weight = DEFAULT_DRAW_WEIGHT
            weights.append(weight)

        if not weights or sum(weights) <= 0:
            return [DEFAULT_DRAW_WEIGHT] * len(maids)
        return weights

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
    def _generate_available_maids_html(data: dict, image_cache: dict[str, str] | None = None) -> str:
        """生成女仆一览 HTML（≤12 人单栏，>12 人双栏）

        Args:
            data: _filter_booking 返回的单条记录
            image_cache: {图片URL: base64_data_uri} 缓存，用于内嵌图片

        Returns:
            完整的 HTML 字符串
        """
        maids = data.get("maids", []) or []
        reservations = data.get("reservations", []) or []
        booking_enabled = data.get("booking_enabled", False)

        reserve_counts = SukiBookingPlugin._count_reservations_per_maid(maids, reservations)
        active_maids = [m for m in maids if not m.get("disabled")]
        use_two_col = len(active_maids) > 12

        # 可预约人数统计
        avail_count = sum(1 for m in active_maids if reserve_counts.get(m.get("name", ""), 0) == 0)

        # ── 构建卡片 ──
        cards_html = ""
        for m in active_maids:
            name = m.get("name", "")
            image = m.get("image", "")
            tags = m.get("tags", []) or []
            maid_vrcid = m.get("vrcid", "")
            count = reserve_counts.get(name, 0)

            # 标签（两栏只显示 2 个）
            tag_limit = 2 if use_two_col else 3
            tags_html = "".join(f'<span class="card-tag">{_escape_html(t)}</span>' for t in tags[:tag_limit])

            # 图片
            if image and image_cache and image in image_cache:
                img_src = image_cache[image]
            # elif image:
            #     img_src = _escape_html(image)
            else:
                img_src = ""

            # 徽章
            if count == 0:
                badge_html = '<span class="badge-avail">可预约</span>'
            elif count == 1:
                badge_html = f'<span class="badge-booked">已约 {count}/2</span>'
            else:
                badge_html = '<span class="badge-full">已约满</span>'

            if use_two_col:
                # ── 双栏模式：紧凑卡片 ──
                img_tag = (
                    f'<img class="card-img-2col" src="{img_src}" '
                    f'alt="{_escape_html(name)}" onerror="this.style.display=\'none\'">'
                    if img_src
                    else '<div class="card-img-2col"></div>'
                )
                cards_html += f"""
    <div class="card-2col">
      {img_tag}
      <div class="card-info">
        <div class="card-name">{_escape_html(name)}</div>
        <div class="card-tags">{tags_html}</div>
      </div>
      <div class="card-badge">{badge_html}</div>
    </div>"""
            else:
                # ── 单栏模式：含预约槽位 ──
                # 提取该女仆的预约记录（最多 2 条），按时间排序
                maid_resv = sorted(
                    [
                        r
                        for r in reservations
                        if (maid_vrcid and r.get("maidVrcid", "") == maid_vrcid)
                        or (not maid_vrcid and r.get("maidName", "") == name)
                    ],
                    key=lambda r: r.get("timeSlot", ""),
                )
                slot1_html = '<div class="slot-row slot-free">可预约</div>'
                slot2_html = '<div class="slot-row slot-free">可预约</div>'
                for i, res in enumerate(maid_resv[:2]):
                    ts = _escape_html(res.get("timeSlot", ""))
                    guest = _escape_html(res.get("guestUsername", ""))
                    slot_html = f'<div class="slot-row slot-occupied">{ts}  {guest}</div>'
                    if i == 0:
                        slot1_html = slot_html
                    elif i == 1:
                        slot2_html = slot_html

                img_tag = (
                    f'<img class="card-img-single" src="{img_src}" '
                    f'alt="{_escape_html(name)}" onerror="this.style.display=\'none\'">'
                    if img_src
                    else '<div class="card-img-single"></div>'
                )
                cards_html += f"""
    <div class="card">
      {img_tag}
      <div class="card-info">
        <div class="card-name">{_escape_html(name)}</div>
        <div class="card-tags">{tags_html}</div>
        {slot1_html}
        {slot2_html}
      </div>
      <div class="card-badge">{badge_html}</div>
    </div>"""

        if not active_maids:
            cards_html = '<div class="empty-state">🌻 暂无女仆信息</div>'

        # ── Header ──
        stats_html = (
            f'共 <span class="stat-em">{len(active_maids)}</span> 位'
            f'　可预约 <span class="stat-em">{avail_count}</span> 位'
        )
        status_html = (
            '<span style="font-size:11px;color:#1769AA;font-weight:600">预约开放中</span>'
            if booking_enabled
            else '<span style="font-size:11px;color:#4F6580;font-weight:600">预约已关闭</span>'
        )

        now_str = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M")
        css = _load_css(RENDER_WIDTH)

        cards_container = f'<div class="grid-2col">{cards_html}</div>' if use_two_col else cards_html

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width={RENDER_WIDTH}">
<style>{css}</style>
</head>
<body>
<div class="header">
  <div class="brand">Suki猫娘咖啡厅</div>
  <div class="stats">{stats_html}</div>
  <div>{status_html}</div>
</div>
{cards_container}
<div class="footer">更新时间 {now_str}（UTC）</div>
</body>
</html>"""

    # ── HTML 生成：模板二 - 单个女仆预约详情 ──────────────────────────

    @staticmethod
    def _generate_maid_detail_html(data: dict, maid_name: str, image_cache: dict[str, str] | None = None) -> str:
        """生成「单个女仆预约详情」HTML

        Args:
            data: _filter_booking 返回的单条记录
            maid_name: 目标女仆名称
            image_cache: {图片URL: base64_data_uri} 缓存

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
            css = _load_css(RENDER_WIDTH)
            return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><style>{css}</style></head>
<body>
<div class="header">
  <div class="brand">Suki猫娘咖啡厅</div>
</div>
<div class="empty-state">未找到女仆「{_escape_html(maid_name)}」的信息</div>
<div class="footer">请确认女仆名称是否正确</div>
</body>
</html>"""

        # 该女仆的预约记录
        target_vrcid = target.get("vrcid", "")
        maid_reservations = [
            r
            for r in reservations
            if (target_vrcid and r.get("maidVrcid", "") == target_vrcid)
            or (not target_vrcid and r.get("maidName", "") == maid_name)
        ]

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
            status_html = '<span class="maid-disabled-tag">今日休息</span>'
        elif not booking_enabled:
            status_html = '<span class="status-tag status-closed">预约已关闭</span>'
        elif len(maid_reservations) >= 2:
            status_html = '<span class="status-tag status-full">已约满</span>'
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
            resv_html = '<div class="empty-state" style="padding:24px 20px">🌊 暂无预约记录</div>'

        # 优先使用缓存的 base64 图片
        if image and image_cache and image in image_cache:
            img_src = image_cache[image]
        # elif image:
        #     img_src = _escape_html(image)
        else:
            img_src = ""
        img_tag = (
            f'<img class="detail-img" src="{img_src}" alt="{_escape_html(name)}" onerror="this.style.display=\'none\'">'
            if img_src
            else '<div class="detail-img" style="height:200px"></div>'
        )

        now_str = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M")

        css = _load_css(RENDER_WIDTH)

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width={RENDER_WIDTH}">
<style>{css}</style>
</head>
<body>
<div class="header">
  <div class="brand">Suki猫娘咖啡厅</div>
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

    async def _render_png_only(self, html: str) -> str | None:
        """将 HTML 渲染为 PNG，返回 base64 数据，不发送到聊天流"""
        try:
            result = await self.ctx.render.html2png(
                html=html,
                wait_until="load",
                # timeout_ms=10000,
                allow_network=True,
            )
        except Exception as e:
            self.ctx.logger.error("_render_png_only 渲染异常: %s", e)
            return None

        if not result:
            self.ctx.logger.error("_render_png_only 返回空结果")
            return None

        if isinstance(result, str):
            image_base64 = result
        elif isinstance(result, dict):
            image_base64 = result.get("image_base64") or result.get("data") or result.get("image") or ""
        elif isinstance(result, bytes):
            image_base64 = b64encode(result).decode("ascii")
        else:
            self.ctx.logger.error("_render_png_only 返回了未知类型: %s", type(result))
            return None

        if not image_base64:
            self.ctx.logger.error("未能从 _render_png_only 结果中提取图片数据")
            return None

        return image_base64

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
                wait_until="load",
                # timeout_ms=10000,
                allow_network=True,
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
            "不指定 maid_name 时返回全体女仆一览（含可预约/已约 1 次/已约满三种状态）；"
            "指定 maid_name 时返回该女仆的详细预约情况（含所有预约记录）。"
            "每位女仆最多可被预约 2 次，预约数 ≥ 2 表示已约满。"
            "先调用 list_suki_maids 工具获取正确名称，再传入准确的 maid_name 查询详情。"
            "返回结果中已包含所有女仆的预约状态和抽到的女仆信息，直接使用即可，无需重复调用。"
        ),
        parameters=[
            ToolParameterInfo(
                name="maid_name",
                param_type=ToolParamType.STRING,
                description="要查询的女仆名称（需精确匹配）。不填则返回全体女仆一览",
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
            html = self._generate_maid_detail_html(item, maid_name.strip(), self._image_cache_hd)
            desc = f"已生成女仆「{maid_name}」的预约详情图片"
        else:
            html = self._generate_available_maids_html(item, self._image_cache)
            desc = "已生成女仆一览图片"

        # 构建文本摘要，供 LLM 理解返回内容
        maids = item.get("maids", []) or []
        reservations = item.get("reservations", []) or []
        text_summary_parts: list[str] = []

        def reservations_for_maid(maid: dict) -> list[dict]:
            maid_vrcid = maid.get("vrcid", "")
            maid_name_for_match = maid.get("name", "")
            return [
                r
                for r in reservations
                if (maid_vrcid and r.get("maidVrcid", "") == maid_vrcid)
                or (not maid_vrcid and maid_name_for_match and r.get("maidName", "") == maid_name_for_match)
            ]

        target_maid_name = (maid_name and maid_name.strip()) or ""
        if target_maid_name:
            # 指定了女仆名称：只返回该女仆的信息
            target_maid = None
            for m in maids:
                if m.get("name") == target_maid_name:
                    target_maid = m
                    break

            if target_maid is None:
                text_summary_parts.append(f"未找到女仆「{target_maid_name}」的信息。")
            else:
                m_reservations = reservations_for_maid(target_maid)
                count = len(m_reservations)
                disabled = target_maid.get("disabled", False)
                if disabled:
                    status = "今日休息"
                elif count >= 2:
                    status = "已约满"
                elif count >= 1:
                    status = f"已约{count}次"
                else:
                    status = "可预约"
                text_summary_parts.append(f"当前查询的女仆: {target_maid_name} - {status}（{count}/2 次预约）")
                if m_reservations:
                    for r in m_reservations:
                        time_slot = r.get("timeSlot", "")
                        guest = r.get("guestUsername", "")
                        text_summary_parts.append(f"  预约记录: {time_slot} | {guest}")
        else:
            # 未指定女仆：返回全体一览
            text_summary_parts.append(f"【全体女仆一览 - 共 {len(maids)} 位女仆，{len(reservations)} 条预约记录】")
            for m in maids:
                mname = m.get("name", "未知")
                disabled = m.get("disabled", False)
                m_reservations = reservations_for_maid(m)
                count = len(m_reservations)
                if disabled:
                    status = "今日休息"
                elif count >= 2:
                    status = "已约满"
                elif count >= 1:
                    status = f"已约{count}次"
                else:
                    status = "可预约"
                text_summary_parts.append(f"  {mname}: {status}")

        text_summary = "\n".join(text_summary_parts)

        # 只渲染，不发送——由 LLM 的 tool response 机制控制发送
        image_base64 = await self._render_png_only(html)

        # 构建返回结果
        if image_base64:
            self.ctx.logger.info("Tool query_suki_booking: 图片渲染成功（未发送）")
            return {
                "success": True,
                "content": desc + "\n" + text_summary,
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
            return {"success": True, "content": text_summary + "\n" + formatted}

    @Tool(
        "list_suki_maids",
        description=(
            "获取 Suki 猫娘咖啡厅当前全部女仆的名称列表。"
            "在查询特定女仆的预约详情之前，优先调用此工具获取正确的女仆名称，"
            "以应对用户输入错误、简繁体差异、别名等情况。"
            "获取名称列表后，从中选取一个准确的名称作为 maid_name，"
            "再调用 query_suki_booking 工具查询该女仆的详情。"
        ),
        parameters=[
            ToolParameterInfo(
                name="limit",
                param_type=ToolParamType.INTEGER,
                description="返回记录数量上限，默认 1",
                required=False,
                default=1,
            ),
        ],
    )
    async def handle_tool_list_maids(self, limit: int = 1, **kwargs):
        """AI 工具调用：获取所有女仆名称列表，仅返回数据给 LLM，不发送消息"""
        self.ctx.logger.info("Tool list_suki_maids 被调用: limit=%d", limit)

        data = await self._fetch_booking(limit=limit)
        if data is None:
            return {"success": False, "content": "查询失败，请稍后重试。"}

        items: list = data if isinstance(data, list) else [data]
        if not items:
            return {"success": False, "content": "暂无女仆数据。"}

        item = items[0]
        maids = item.get("maids", []) or []

        if not maids:
            return {"success": True, "content": "当前暂无女仆数据。"}

        # 构建名称列表（不含图片等重数据）
        names: list[str] = []
        for m in maids:
            name = m.get("name", "")
            if name:
                status = "在线" if not m.get("disabled") else "离线"
                names.append(f"- {name}（{status}）")

        return {
            "success": True,
            "content": (
                f"Suki 猫娘咖啡厅当前共有 {len(names)} 位女仆：\n"
                + "\n".join(names)
                + "\n\n请从中选择准确的名称作为 maid_name 参数调用 query_suki_booking。"
            ),
        }

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

        html = self._generate_available_maids_html(item, self._image_cache)
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

    # ── Command: /猫娘占卜 ──────────────────────────────────────────────

    @Command("draw_maid", pattern=r"^/猫娘占卜")
    async def handle_draw_maid(self, **kwargs):
        """随机抽取一位女仆并展示详情 PNG 图片"""
        stream_id: str = kwargs["stream_id"]
        self.ctx.logger.info("Command /猫娘占卜 被触发，stream_id=%s", stream_id)

        await self.ctx.send.text("🔮 正在为你占卜猫娘...", stream_id)

        data = await self._fetch_booking()
        if data is None:
            self.ctx.logger.warning("Command /猫娘占卜: 数据获取失败")
            await self.ctx.send.text("❌ 查询失败，请稍后重试。", stream_id)
            return False, "查询失败", 1

        items: list = data if isinstance(data, list) else [data]
        if not items:
            await self.ctx.send.text("暂无女仆数据。", stream_id)
            return True, "暂无数据", 1

        item = items[0]
        maids = item.get("maids", []) or []

        if not maids:
            await self.ctx.send.text("当前没有女仆数据。", stream_id)
            return True, "无女仆数据", 1

        weights = self._normalized_draw_weights(maids)
        chosen = random.choices(maids, weights=weights, k=1)[0]
        maid_name = chosen.get("name", "")
        self.ctx.logger.info(
            "Command /猫娘占卜: 抽中「%s」（disabled=%s）",
            maid_name,
            chosen.get("disabled", False),
        )

        html = self._generate_maid_detail_html(item, maid_name, self._image_cache_hd)
        image_base64 = await self._render_and_send_png(html, stream_id)

        if image_base64:
            self.ctx.logger.info("Command /猫娘占卜: PNG 图片发送成功")
            return True, f"抽取成功: {maid_name}（图片）", 1
        else:
            # 降级为文本
            self.ctx.logger.warning("Command /猫娘占卜: 图片渲染失败，降级为文本")
            formatted = self._format_booking(items)
            await self.ctx.send.text(formatted, stream_id)
            return True, f"抽取成功: {maid_name}（文本降级）", 1

    # ── Tool: 随机抽取女仆 ─────────────────────────────────────────────

    @Tool(
        "draw_suki_maid",
        description=(
            "从 Suki 猫娘咖啡厅随机抽取(也就是占卜的意思）一位女仆，返回其预约详情。"
            "默认从全部女仆（含今日休息）中抽取；"
            "设置 include_disabled=false 则只从可接单女仆中抽取。"
            "建议先调用 list_suki_maids 工具查看可用女仆范围。若用户明确要求或可接单女仆小于6人或预约关闭，则从全部女仆范围中抽取"
        ),
        parameters=[
            ToolParameterInfo(
                name="include_disabled",
                param_type=ToolParamType.BOOLEAN,
                description="是否包含今日休息的女仆。默认 true（全部女仆均可被抽到），设为 false 则只抽可接单的",
                required=False,
                default=True,
            ),
            ToolParameterInfo(
                name="limit",
                param_type=ToolParamType.INTEGER,
                description="API 查询返回记录数量上限，默认 1",
                required=False,
                default=1,
            ),
        ],
    )
    async def handle_tool_draw_maid(self, include_disabled: bool = True, limit: int = 1, **kwargs):
        """AI 工具调用：随机抽取女仆并返回详情 PNG 图片"""
        self.ctx.logger.info(
            "Tool draw_suki_maid 被调用: include_disabled=%s, limit=%d",
            include_disabled,
            limit,
        )

        data = await self._fetch_booking(limit=limit)
        if data is None:
            self.ctx.logger.warning("Tool draw_suki_maid: 数据获取失败")
            return {"success": False, "content": "查询失败，请稍后重试。"}

        items: list = data if isinstance(data, list) else [data]
        if not items:
            return {"success": False, "content": "暂无女仆数据。"}

        item = items[0]
        maids = item.get("maids", []) or []

        # 根据参数过滤候选池
        if include_disabled:
            candidates = maids
        else:
            candidates = [m for m in maids if not m.get("disabled")]

        if not candidates:
            desc = "当前没有符合条件可抽取的女仆"
            return {"success": True, "content": desc}

        weights = self._normalized_draw_weights(candidates)
        chosen = random.choices(candidates, weights=weights, k=1)[0]
        maid_name = chosen.get("name", "")
        self.ctx.logger.info(
            "Tool draw_suki_maid: 抽中「%s」（disabled=%s）",
            maid_name,
            chosen.get("disabled", False),
        )

        html = self._generate_maid_detail_html(item, maid_name, self._image_cache_hd)
        desc = f"已抽取女仆「{maid_name}」并生成预约详情图片"

        # 只渲染，不发送——由 LLM 的 tool response 机制控制发送
        image_base64 = await self._render_png_only(html)

        if image_base64:
            self.ctx.logger.info("Tool draw_suki_maid: 图片渲染成功（未发送）")
            return {
                "success": True,
                "content": desc,
                "content_items": [
                    {
                        "type": "image",
                        "data": image_base64,
                        "mime_type": "image/png",
                        "name": "suki_maid_draw.png",
                        "description": desc,
                    }
                ],
            }
        else:
            # 降级：返回文本
            self.ctx.logger.warning("Tool draw_suki_maid: 图片渲染失败，降级为文本")
            formatted = self._format_booking(items)
            return {"success": True, "content": formatted}


# ── HTML 转义 ────────────────────────────────────────────────────────


def _escape_html(s: str) -> str:
    """转义 HTML 特殊字符"""
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
    )


def create_plugin():
    return SukiBookingPlugin()
