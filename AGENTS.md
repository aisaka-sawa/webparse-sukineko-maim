# AGENTS.md — webparse-sukineko-maim 改动记录

## 改动概要

将 Suki 预约查询插件的回复形式从**纯文本**改为 **HTML → PNG 图片**，提升可读性和美观度。

| 项目 | 改动前 | 改动后 |
|------|--------|--------|
| 输出形式 | `ctx.send.text(...)` 发送纯文本 | `ctx.render.html2png(...)` → `ctx.send.image(...)` 发送 PNG 图片 |
| Tool 返回 | `{"success": True, "content": "文本..."}` | `{"success": True, "content": "描述", "content_items": [图片base64]}` |
| 女仆字段 | name, image, disabled | 新增 vrcid, tags, signature（vrcid 用于预约关联，tags/signature 用于丰富卡片展示） |
| Tool 参数 | 仅 `limit` | 新增可选 `maid_name`，不填→一览，填入→详情 |
| 降级策略 | 无 | 图片渲染失败时自动降级为原文本格式 |

## 文件变更

- **`plugin.py`**: 244 行 → 828 行，全部改动集中于此文件
- 其他文件未修改

## 架构

```
用户/AI 请求
  │
  ├─ /suki 命令 ──→ _fetch_booking() ──→ _generate_available_maids_html()
  │                                            │
  └─ Tool 调用  ──→ _fetch_booking() ──→ maid_name 指定?
                                               │
                                    ┌──────────┴──────────┐
                                    │ 无                    │ 有
                          模板一：一览              模板二：详情
                                    │                     │
                                    └──────────┬──────────┘
                                               │
                                    _render_and_send_png()
                                               │
                                    html2png → send.image
                                               │
                                    失败 → 文本降级
```

## 新增常量

- **`RENDER_WIDTH = 390`** — 一览页渲染宽度（iPhone 14 竖屏）
- **`_load_css() → static/style.css`** — 咖啡厅主题内联样式模板，通过 `{width}` 占位符注入渲染宽度

## 新增方法速查

| 方法 | 类型 | 职责 |
|------|------|------|
| `_count_reservations_per_maid(maids, reservations)` | 静态 | 通过 `maids[].vrcid` 与 `reservations[].maidVrcid` 统计每位女仆的预约数量，返回 `{名称: 计数}` |
| `_generate_available_maids_html(data)` | 静态 | 模板一：筛选 disabled=false 且预约数 ≤1 的女仆，生成卡片列表 HTML |
| `_generate_maid_detail_html(data, maid_name)` | 静态 | 模板二：查找指定女仆，生成含大图、标签、签名、预约记录的详情 HTML |
| `_render_and_send_png(html, stream_id)` | 实例 | 渲染管线：html2png → 解析结果(str/dict/bytes) → send.image |
| `_load_css(width)` | 模块函数 | 从 static/style.css 加载 CSS，替换 {width} 占位符，按宽度缓存 |
| `_escape_html(s)` | 模块函数 | HTML 特殊字符转义，防止 XSS |

## 两套 HTML 模板详情

### 模板一：可预约女仆一览

触发条件：`/suki` 命令，或 Tool 不传 `maid_name`

布局（390×N px）：
```
┌────────────────────────────────┐
│  ☕ Suki 猫娘咖啡厅             │
│  可预约女仆一览    [预约状态]    │
│  ──────────────────────────── │
│  [在线数]  [可预约数]  [预约数] │
│  ┌──79px──┬──────────────────┐│
│  │[头像]  │ 女仆名             ││
│  │ 72×72  │ 标签1 标签2       ││
│  │        │ 签名...  [可预约]  ││
│  └────────┴──────────────────┘│
│  ... 更多卡片 ...              │
│  更新时间                      │
└────────────────────────────────┘
```

设计要点：
- 筛选条件：`disabled == False` 且该女仆预约数 ≤ 1
- 标签最多显示 3 个（`tags[:3]`）
- 预约数 = 0 显示绿色「可预约」徽章，= 1 显示橙色「已约 1/2」
- 无可用女仆时显示樱花空状态提示
- 顶部数字汇总：在线女仆数 / 可预约数 / 总预约数

### 模板二：单个女仆预约详情

触发条件：Tool 传入 `maid_name`

布局（390×N px）：
```
┌────────────────────────────────┐
│  ☕ Suki 猫娘咖啡厅             │
│  女仆预约详情                   │
│  ┌──────────────────────────┐ │
│  │ [女仆大图 max-h:280px]   │ │
│  └──────────────────────────┘ │
│  女仆名  [可预约/今日休息/关闭] │
│  标签1  标签2  标签3           │
│  「签名内容」                   │
│  ── 📋 预约记录（N 条）         │
│  ┌──────────────────────────┐ │
│  │ 🕐 时间段   👤 客人名      │ │
│  └──────────────────────────┘ │
│  更新时间                      │
└────────────────────────────────┘
```

设计要点：
- 未找到女仆时返回友好空状态（不是崩溃）
- 状态分三层：`disabled` →「今日休息」, 非 disabled 但 `booking_enabled=false` →「预约已关闭」, 否则 →「可预约」
- 无预约记录时显示 📭 空状态

## 渲染 & 发送管线 (`_render_and_send_png`)

```
html2png(html)
  │
  ├─ 异常 ──→ 日志记录 → 返回 None
  ├─ 空结果 ──→ 返回 None
  └─ 成功
       │
       ├─ str ──→ 直接作为 image_base64
       ├─ dict ──→ 尝试 image_base64 / data / image 键
       ├─ bytes ──→ b64encode 编码
       └─ 其他 ──→ 返回 None
              │
         send.image(image_base64, stream_id)
              │
         成功 → 返回 image_base64
         失败 → 返回 None
```

兼容性策略：不假设 `html2png` 的具体返回类型，覆盖 `str`/`dict`/`bytes` 三种可能。

## 降级策略

当 `html2png` 渲染失败或 `send.image` 发送失败时：
- **Command `/suki`**：降级为 `_format_booking()` 文本格式发送
- **Tool**：降级为 `{"success": True, "content": formatted_text}` 纯文本返回

原有的 `_format_booking()` 方法完整保留，未删除。

## 色彩主题

咖啡厅暖色调，全部通过 `_load_css() → static/style.css` 内联样式定义：

| 用途 | 色值 | 说明 |
|------|------|------|
| 页面背景 | `#FDF6F0` | 暖奶油白 |
| 卡片背景 | `#FFFFFF` | 纯白 |
| 主标题 | `#6B4226` | 咖啡棕 |
| 次级文字 | `#8B7355` | 中棕 |
| 辅助文字 | `#A08C7A` | 浅棕灰 |
| 强调色 | `#C87941` | 焦糖橙（section-title 左边框） |
| 可预约徽章 | `#E8F5E9` 底 / `#388E3C` 字 | 柔绿 |
| 已预约徽章 | `#FFF3E0` 底 / `#E65100` 字 | 柔橙 |
| 预约关闭 | `#FFEBEE` 底 / `#C62828` 字 | 柔红 |
| 分隔线 | `#E8D5C4` | 浅棕色 |
| 卡片阴影 | `rgba(107,66,38,0.08)` | 极淡棕阴影 |

## 数据流变更

**`_filter_booking` 扩展字段：**
- 旧：`maids: [{name, image, disabled}]`
- 新：`maids: [{name, image, disabled, vrcid, tags, signature}]`
- 预约记录新增保留 `maidVrcid`，用于和 `maids[].vrcid` 稳定关联
- `tags` 默认 `[]`，`signature` 默认 `""`

**Tool description 更新：**
- 明确告知 LLM 不指定 `maid_name` 时返回一览，指定时返回详情
- 有助于 LLM 根据用户意图正确传参

## /抽猫娘 命令

| 项目 | 说明 |
|------|------|
| 触发 | `/抽猫娘` |
| 逻辑 | 从 `disabled=false` 的女仆中 `random.choice`，走详情页渲染管线 |
| 渲染 | 详情页与一览页统一使用 `RENDER_WIDTH = 390`，图片缓存单独区分 `_image_cache`（400px）/ `_image_cache_hd`（800px） |
| 降级 | 同 `/suki`，渲染失败降级为文本 |

## 注意事项

1. **html2png 返回值类型不确定**：`_render_and_send_png` 做了 str/dict/bytes 三分支兼容，如果 MaiBot 未来改变返回格式，可能需要调整
2. **外部图片加载**：女仆头像来自 Supabase 图片 URL（`pic7.fukit.cn` 等），html2png 渲染时需要能访问外网
3. **图片 onerror**：`<img>` 标签设置了 `onerror="this.style.display='none'"` 降级，图片加载失败时不显示裂图
4. **HTML 转义**：所有用户数据（名称、标签、签名等）通过 `_escape_html()` 转义后嵌入 HTML，防止特殊字符破坏结构
5. **`content_items` 返回**：Tool 成功时通过 `content_items` 返回 base64 图片，供 Maisaka 视觉模型观察；失败时只返回纯文本
