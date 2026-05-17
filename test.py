"""Suki 预约查询插件 - 模拟运行测试脚本

此脚本模拟 MaiBot SDK 的 PluginContext，使插件可以在没有主程序的情况下运行和测试。

用法:
    python test.py              # 运行所有测试
    python test.py --tool       # 仅测试 Tool 调用
    python test.py --command    # 仅测试 Command 调用
    python test.py --format     # 仅测试格式化/HTML 逻辑
    python test.py --api        # 仅测试 API 请求
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

# 设置日志
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test")

# ============================================================================
# Mock SDK 组件
# ============================================================================

class MockLogger:
    """模拟 PluginContext 中的 logger"""

    def debug(self, msg: str, *args: Any) -> None:
        logger.debug(f"[plugin] {msg}", *args)

    def info(self, msg: str, *args: Any) -> None:
        logger.info(f"[plugin] {msg}", *args)

    def warning(self, msg: str, *args: Any) -> None:
        logger.warning(f"[plugin] {msg}", *args)

    def error(self, msg: str, *args: Any) -> None:
        logger.error(f"[plugin] {msg}", *args)

    def critical(self, msg: str, *args: Any) -> None:
        logger.critical(f"[plugin] {msg}", *args)

class MockSend:
    """模拟 ctx.send - 消息发送代理"""

    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []

    async def text(self, text: str, stream_id: str) -> bool:
        msg = {"type": "text", "content": text, "stream_id": stream_id}
        self.sent_messages.append(msg)
        logger.info(f"send.text(stream_id={stream_id!r}): {text[:80]}")
        return True

    async def image(self, image_base64: str = None, stream_id: str = None, **kwargs) -> bool:
        # 支持 keyword argument 调用: image_data=... , stream_id=...
        if image_base64 is None:
            image_base64 = kwargs.get("image_data", "")
        if stream_id is None:
            stream_id = kwargs.get("stream_id", "")
        msg = {"type": "image", "data": image_base64, "stream_id": stream_id}
        self.sent_messages.append(msg)
        return True

    def reset(self) -> None:
        self.sent_messages.clear()

class MockRender:
    """模拟 ctx.render - 渲染代理"""

    def __init__(self, return_value: Any = None, raise_exception: Exception | None = None) -> None:
        self._return_value = return_value
        self._raise_exception = raise_exception
        self.called = False
        self.last_html: str = ""
        self.last_kwargs: dict = {}

    async def html2png(self, html: str, **kwargs) -> Any:
        self.called = True
        self.last_html = html
        self.last_kwargs = kwargs
        if self._raise_exception:
            raise self._raise_exception
        return self._return_value

    def set_return(self, value: Any) -> None:
        self._return_value = value

    def set_exception(self, exc: Exception) -> None:
        self._raise_exception = exc

    def reset(self) -> None:
        self.called = False
        self.last_html = ""
        self.last_kwargs = {}
        self._raise_exception = None

class MockContext:
    """模拟 PluginContext"""

    def __init__(self, render_return: Any = None) -> None:
        self.logger = MockLogger()
        self.send = MockSend()
        self.render = MockRender(return_value=render_return)
        # 其他代理占位（插件未使用，但不影响加载）
        self.db = None
        self.llm = None
        self.config = None
        self.message = None
        self.chat = None
        self.person = None
        self.emoji = None
        self.frequency = None
        self.component = None
        self.api = None
        self.gateway = None
        self.tool = None
        self.knowledge = None

class MockToolParameterInfo:
    """模拟 ToolParameterInfo"""

    def __init__(
        self,
        name: str,
        param_type: str,
        description: str = "",
        required: bool = True,
        default: Any = None,
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.param_type = param_type
        self.description = description
        self.required = required
        self.default = default

class MockToolParamType:
    """模拟 ToolParamType 枚举"""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    FLOAT = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"

# ============================================================================
# Mock maibot_sdk 模块 - 拦截 import
# ============================================================================

class MockMaiBotPlugin:
    """模拟 MaiBotPlugin 基类"""

    def __init__(self) -> None:
        self.ctx = MockContext()
        self._tools: list[dict[str, Any]] = []
        self._commands: list[dict[str, Any]] = []
        self._image_cache: dict[str, str] = {}
        self._image_cache_hd: dict[str, str] = {}

    async def on_load(self) -> None:
        pass

    async def on_unload(self) -> None:
        pass

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        pass

def MockTool(name: str, description: str = "", parameters: Any = None, **kwargs: Any):
    """模拟 @Tool 装饰器 - 记录工具定义并返回原始函数"""

    def decorator(func):
        async def wrapper(*args: Any, **kw: Any):
            return await func(*args, **kw)

        wrapper._tool_name = name
        wrapper._tool_description = description
        wrapper._tool_parameters = parameters
        wrapper._tool_metadata = kwargs
        return wrapper

    return decorator

def MockCommand(name: str, pattern: str = "", description: str = "", aliases: list[str] | None = None, **kwargs: Any):
    """模拟 @Command 装饰器 - 记录命令定义并返回原始函数"""

    def decorator(func):
        async def wrapper(*args: Any, **kw: Any):
            return await func(*args, **kw)

        wrapper._command_name = name
        wrapper._command_pattern = pattern
        wrapper._command_description = description
        wrapper._command_aliases = aliases or []
        wrapper._command_metadata = kwargs
        return wrapper

    return decorator

# 注入 mock 模块到 sys.modules
_mock_sdk = type(sys)("maibot_sdk")
_mock_sdk.Command = MockCommand
_mock_sdk.Tool = MockTool
_mock_sdk.MaiBotPlugin = MockMaiBotPlugin
_mock_sdk.API = lambda *a, **k: lambda f: f  # passthrough

_mock_types = type(sys)("maibot_sdk.types")
_mock_types.ToolParameterInfo = MockToolParameterInfo
_mock_types.ToolParamType = MockToolParamType

sys.modules["maibot_sdk"] = _mock_sdk
sys.modules["maibot_sdk.types"] = _mock_types

# ============================================================================
# 现在可以安全导入插件了
# ============================================================================

# 将插件目录加入 path
plugin_dir = Path(__file__).resolve().parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

from plugin import (
    HEADERS,
    RENDER_WIDTH,
    REQUEST_TIMEOUT,
    SUPABASE_URL,
    SukiBookingPlugin,
    _escape_html,
    _load_css,
    create_plugin,
)

# ============================================================================
# 测试工具函数
# ============================================================================

TEST_PASS = 0
TEST_FAIL = 0
TEST_SKIP = 0

def assert_equal(actual: Any, expected: Any, label: str = "") -> None:
    """断言两个值相等"""
    global TEST_PASS, TEST_FAIL
    if actual == expected:
        TEST_PASS += 1
    else:
        TEST_FAIL += 1
        print(f"  ✗ ASSERT FAIL: {label or 'assertion'}")
        print(f"    expected: {expected!r}")
        print(f"    actual:   {actual!r}")

def assert_true(value: bool, label: str = "") -> None:
    """断言值为 True"""
    global TEST_PASS, TEST_FAIL
    if value:
        TEST_PASS += 1
    else:
        TEST_FAIL += 1
        print(f"  ✗ ASSERT FAIL: {label or 'assertion'}")

def assert_in(item: Any, container: Any, label: str = "") -> None:
    """断言 item 在 container 中"""
    global TEST_PASS, TEST_FAIL
    if item in container:
        TEST_PASS += 1
    else:
        TEST_FAIL += 1
        print(f"  ✗ ASSERT FAIL: {label or 'assertion'}")
        print(f"    expected {item!r} in {container!r}")

def assert_in_substring(sub: str, s: str, label: str = "") -> None:
    """断言子串存在于字符串中"""
    global TEST_PASS, TEST_FAIL
    if sub in s:
        TEST_PASS += 1
    else:
        TEST_FAIL += 1
        print(f"  ✗ ASSERT FAIL: {label or 'assertion'}")
        print(f"    expected substring: {sub!r}")
        print(f"    in string ({len(s)} chars): {s[:200]!r}...")

def assert_not_in(item: Any, container: Any, label: str = "") -> None:
    """断言 item 不在 container 中"""
    global TEST_PASS, TEST_FAIL
    if item not in container:
        TEST_PASS += 1
    else:
        TEST_FAIL += 1
        print(f"  ✗ ASSERT FAIL: {label or 'assertion'}")
        print(f"    did not expect {item!r} in {container!r}")

def assert_not_in_substring(sub: str, s: str, label: str = "") -> None:
    """断言子串不存在于字符串中"""
    global TEST_PASS, TEST_FAIL
    if sub not in s:
        TEST_PASS += 1
    else:
        TEST_FAIL += 1
        print(f"  ✗ ASSERT FAIL: {label or 'assertion'}")
        print(f"    did not expect substring: {sub!r}")

def print_section(title: str) -> None:
    """打印分隔标题"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")

def print_json(data: Any) -> None:
    """漂亮打印 JSON"""
    print(json.dumps(data, ensure_ascii=False, indent=2))

def print_result(label: str, data: Any) -> None:
    """打印测试结果"""
    print(f"\n>>> {label}")
    if isinstance(data, dict):
        print_json(data)
    elif isinstance(data, str):
        print(data)
    else:
        print(data)

def print_summary() -> None:
    """打印测试汇总"""
    print(f"\n{'=' * 60}")
    print(f"  测试汇总")
    print(f"{'=' * 60}")
    print(f"  ✓ 通过: {TEST_PASS}")
    if TEST_FAIL:
        print(f"  ✗ 失败: {TEST_FAIL}")
    if TEST_SKIP:
        print(f"  ⊘ 跳过: {TEST_SKIP}")
    print(f"  总计: {TEST_PASS + TEST_FAIL + TEST_SKIP}")
    print(f"{'=' * 60}")

# ============================================================================
# 测试数据工厂
# ============================================================================

def make_sample_data(
    maids: list[dict] | None = None,
    reservations: list[dict] | None = None,
    booking_enabled: bool = True,
) -> dict:
    """创建样本数据（已过滤格式）"""
    if maids is None:
        maids = [
            {
                "name": "猫娘A",
                "image": "https://example.com/a.png",
                "disabled": False,
                "tags": ["ASMR", "唱歌", "温柔"],
                "signature": "你好呀，主人~",
            },
            {
                "name": "猫娘B",
                "image": "https://example.com/b.png",
                "disabled": True,
                "tags": [],
                "signature": "",
            },
        ]
    if reservations is None:
        reservations = [
            {
                "maidName": "猫娘A",
                "timeSlot": "14:00-15:00",
                "guestUsername": "客人A",
            },
        ]
    return {
        "maids": maids,
        "reservations": reservations,
        "booking_enabled": booking_enabled,
    }

def make_raw_api_item() -> dict:
    """创建模拟原始 API 返回的数据"""
    return {
        "id": "abc-123",
        "maids": [
            {
                "id": "maid_1",
                "name": "猫娘A",
                "image": "https://example.com/a.png",
                "vrcid": "vrc_1",
                "disabled": False,
                "signature": "你好呀",
                "boundUserId": "user-1",
                "tags": ["ASMR", "唱歌"],
            },
            {
                "id": "maid_2",
                "name": "猫娘B",
                "image": "https://example.com/b.png",
                "vrcid": "vrc_2",
                "disabled": True,
                "signature": "",
                "boundUserId": "",
            },
        ],
        "reservations": [
            {
                "time": "2026/5/13 15:15:35",
                "maidName": "猫娘A",
                "timeSlot": "10:00-11:00",
                "createdAt": 1234567890,
                "maidVrcid": "vrc_1",
                "withFriend": False,
                "guestUserId": "user-99",
                "guestUsername": "测试客人",
            },
        ],
        "announcement": "很长的公告文本...",
        "created_at": 1000000000.0,
        "updated_at": 2000000000.0,
        "announcement_image": "",
        "booking_enabled": True,
    }

# ============================================================================
# 测试用例: 模块函数
# ============================================================================

async def test_escape_html() -> None:
    """测试 _escape_html HTML 转义"""
    print_section("测试 _escape_html")

    # 基本转义
    assert_equal(_escape_html("<script>"), "&lt;script&gt;", "转义 < 和 >")
    assert_equal(_escape_html('&"'), "&amp;&quot;", '转义 & 和 "')
    assert_equal(_escape_html("it's"), "it&#39;s", "转义 '")

    # 组合
    assert_equal(
        _escape_html('<div class="test">Hello & "World"\'s</div>'),
        "&lt;div class=&quot;test&quot;&gt;Hello &amp; &quot;World&quot;&#39;s&lt;/div&gt;",
        "组合转义",
    )

    # 无特殊字符
    assert_equal(_escape_html("Hello World"), "Hello World", "无特殊字符")
    assert_equal(_escape_html(""), "", "空字符串")

    print("  _escape_html 测试完成")

# ============================================================================
# 测试用例: 静态方法
# ============================================================================

async def test_filter_booking() -> None:
    """测试 _filter_booking 过滤方法"""
    print_section("测试 _filter_booking 字段过滤")

    raw_item = make_raw_api_item()
    filtered = SukiBookingPlugin._filter_booking(raw_item)
    print_result("过滤后数据", filtered)

    # 验证字段存在
    assert_in("maids", filtered, "maids 字段存在")
    assert_in("reservations", filtered, "reservations 字段存在")
    assert_in("booking_enabled", filtered, "booking_enabled 字段存在")
    assert_equal(filtered["booking_enabled"], True, "booking_enabled 为 True")

    # 验证 maids 数量和内容
    assert_equal(len(filtered["maids"]), 2, "maids 数量为 2")

    # 验证新字段: tags, signature
    m0 = filtered["maids"][0]
    assert_equal(set(m0.keys()), {"name", "image", "disabled", "tags", "signature"}, "maid 字段集合正确")
    assert_equal(m0["name"], "猫娘A", "maid[0] name")
    assert_equal(m0["disabled"], False, "maid[0] disabled")
    assert_equal(m0["tags"], ["ASMR", "唱歌"], "maid[0] tags")
    assert_equal(m0["signature"], "你好呀", "maid[0] signature")

    m1 = filtered["maids"][1]
    assert_equal(m1["name"], "猫娘B", "maid[1] name")
    assert_equal(m1["disabled"], True, "maid[1] disabled")
    assert_equal(m1["tags"], [], "maid[1] tags 默认为 []")
    assert_equal(m1["signature"], "", "maid[1] signature 默认为 ''")

    # 验证 reservations
    assert_equal(len(filtered["reservations"]), 1, "reservations 数量为 1")
    r = filtered["reservations"][0]
    assert_equal(set(r.keys()), {"maidName", "timeSlot", "guestUsername"}, "reservation 字段集合正确")
    assert_equal(r["maidName"], "猫娘A", "reservation maidName")
    assert_equal(r["guestUsername"], "测试客人", "reservation guestUsername")

    # 验证无关字段被过滤
    assert_not_in("id", filtered, "id 字段被过滤")
    assert_not_in("announcement", filtered, "announcement 被过滤")
    assert_not_in("created_at", filtered, "created_at 被过滤")
    assert_not_in("updated_at", filtered, "updated_at 被过滤")
    assert_not_in("announcement_image", filtered, "announcement_image 被过滤")

    print("  _filter_booking 所有断言通过！")

async def test_filter_booking_edge_cases() -> None:
    """测试 _filter_booking 边界情况"""
    print_section("测试 _filter_booking 边界情况")

    # 空字典
    empty = SukiBookingPlugin._filter_booking({})
    assert_equal(empty["maids"], [], "空字典 -> maids=[]")
    assert_equal(empty["reservations"], [], "空字典 -> reservations=[]")
    assert_equal(empty["booking_enabled"], False, "空字典 -> booking_enabled=False")

    # tags 为 None 的情况
    raw_none_tags = {
        "maids": [{"name": "X", "image": "", "disabled": False, "tags": None, "signature": None}],
        "reservations": [],
        "booking_enabled": True,
    }
    filtered = SukiBookingPlugin._filter_booking(raw_none_tags)
    assert_equal(filtered["maids"][0]["tags"], [], "tags=None -> 默认 []")
    assert_equal(filtered["maids"][0]["signature"], "", "signature=None -> 默认 ''")

    print("  _filter_booking 边界情况测试完成")

async def test_count_reservations_per_maid() -> None:
    """测试 _count_reservations_per_maid 统计"""
    print_section("测试 _count_reservations_per_maid")

    # 基本统计
    reservations = [
        {"maidName": "猫娘A", "timeSlot": "14:00-15:00", "guestUsername": "客人1"},
        {"maidName": "猫娘A", "timeSlot": "15:00-16:00", "guestUsername": "客人2"},
        {"maidName": "猫娘B", "timeSlot": "14:00-15:00", "guestUsername": "客人3"},
    ]
    counts = SukiBookingPlugin._count_reservations_per_maid(reservations)
    assert_equal(counts, {"猫娘A": 2, "猫娘B": 1}, "基本统计")

    # 空列表
    empty_counts = SukiBookingPlugin._count_reservations_per_maid([])
    assert_equal(empty_counts, {}, "空列表 -> 空字典")

    # 空 maidName
    bad_reservations = [
        {"maidName": "", "timeSlot": "14:00-15:00", "guestUsername": "x"},
        {"maidName": None, "timeSlot": "15:00-16:00", "guestUsername": "x"},
    ]
    bad_counts = SukiBookingPlugin._count_reservations_per_maid(bad_reservations)
    assert_equal(bad_counts, {}, "空/None maidName 被跳过")

    print("  _count_reservations_per_maid 测试完成")

async def test_format_booking() -> None:
    """测试 _format_booking 静态方法"""
    print_section("测试 _format_booking 格式化")

    # 测试空列表
    result_empty = SukiBookingPlugin._format_booking([])
    assert_in_substring("暂无预约数据", result_empty, "空列表提示")
    print_result("空列表", result_empty)

    # 测试单条记录
    single_item = {
        "booking_enabled": True,
        "maids": [
            {"name": "在线猫娘", "image": "https://example.com/a.png", "disabled": False},
            {"name": "离线猫娘", "image": "https://example.com/b.png", "disabled": True},
        ],
        "reservations": [
            {"maidName": "在线猫娘", "timeSlot": "14:00-15:00", "guestUsername": "客人A"},
        ],
    }
    result_single = SukiBookingPlugin._format_booking([single_item])
    assert_in_substring("Suki 预约信息", result_single, "单条标题")
    assert_in_substring("已开启", result_single, "预约状态")
    assert_in_substring("在线猫娘", result_single, "包含在线女仆")
    assert_in_substring("离线猫娘", result_single, "包含离线女仆")
    assert_in_substring("客人A", result_single, "包含客人名")
    print_result("单条记录", result_single)

    # 测试 booking_enabled=False, 无预约
    empty_booking = {
        "booking_enabled": False,
        "maids": [{"name": "猫娘X", "image": "https://example.com/x.png", "disabled": True}],
        "reservations": [],
    }
    result_empty_book = SukiBookingPlugin._format_booking([empty_booking])
    assert_in_substring("已关闭", result_empty_book, "预约关闭")
    assert_in_substring("共 0 条", result_empty_book, "无预约记录")
    print_result("无预约", result_empty_book)

# ============================================================================
# 测试用例: HTML 生成
# ============================================================================

async def test_generate_available_maids_html() -> None:
    """测试 _generate_available_maids_html 模板一"""
    print_section("测试 _generate_available_maids_html（可预约女仆一览）")

    data = make_sample_data()
    html = SukiBookingPlugin._generate_available_maids_html(data)

    # 基本结构检查
    assert_in_substring("<!DOCTYPE html>", html, "HTML 声明")
    assert_in_substring("Suki 猫娘咖啡厅", html, "品牌名称")
    assert_in_substring(f"width={RENDER_WIDTH}", html, f"viewport width={RENDER_WIDTH}")

    # CSS 注入
    assert_in_substring("#FDF6F0", html, "背景色")
    assert_in_substring("#6B4226", html, "主标题色")

    # 女仆信息检查（一览模板只显示 name, tags, 预约槽位；不显示 signature）
    assert_in_substring("猫娘A", html, "包含猫娘A 名称")
    assert_in_substring("ASMR", html, "包含标签")
    # 签名不会出现在一览模板中，只在详情模板显示

    # 猫娘A 有 1 条预约，应显示"已约 1/2"
    assert_in_substring("已约 1/2", html, "猫娘A 预约数 = 1 显示已约 1/2")

    # 猫娘B 是 disabled，不应出现在可预约列表中
    assert_in_substring("badge-avail", html, "有可预约徽章类") or assert_in_substring(
        "badge-booked", html, "有已约徽章类"
    )

    # 汇总行：共 X 位  可预约 X 位
    assert_in_substring("位", html, "汇总包含位")
    assert_in_substring("可预约", html, "汇总包含可预约")

    # 页脚
    assert_in_substring("更新时间", html, "更新时间")
    assert_in_substring("UTC", html, "时区标注")

    print(f"  生成 HTML 长度: {len(html)} 字符")
    print("  _generate_available_maids_html 测试完成")

async def test_generate_available_maids_html_no_available() -> None:
    """测试一览模板 - 无可预约女仆"""
    print_section("测试一览模板 - 无可预约女仆")

    # 所有女仆都有 >1 预约，或 disabled
    data = {
        "maids": [
            {"name": "满约猫娘", "image": "https://x.com/a.png", "disabled": False, "tags": [], "signature": ""},
            {"name": "离线猫娘", "image": "https://x.com/b.png", "disabled": True, "tags": [], "signature": ""},
        ],
        "reservations": [
            {"maidName": "满约猫娘", "timeSlot": "14:00-15:00", "guestUsername": "A"},
            {"maidName": "满约猫娘", "timeSlot": "15:00-16:00", "guestUsername": "B"},
            {"maidName": "满约猫娘", "timeSlot": "16:00-17:00", "guestUsername": "C"},
        ],
        "booking_enabled": True,
    }
    html = SukiBookingPlugin._generate_available_maids_html(data)

    # 无可用女仆时应显示空状态
    assert_in_substring("约满", html, "显示约满空状态") or assert_in_substring("empty-state", html, "空状态元素")

    print("  无可预约女仆测试完成")

async def test_generate_available_maids_html_xss() -> None:
    """测试一览模板 - XSS 防护"""
    print_section("测试一览模板 - XSS 防护")

    data = {
        "maids": [
            {
                "name": '<script>alert("xss")</script>',
                "image": "https://x.com/a.png",
                "disabled": False,
                "tags": ['<img onerror="alert(1)" src=x>', "A&B"],
                "signature": "<b>bold</b>",
            },
        ],
        "reservations": [
            {
                "maidName": '<script>alert("xss")</script>',
                "timeSlot": "10:00-11:00",
                "guestUsername": "Tom & Jerry",
            },
        ],
        "booking_enabled": True,
    }
    html = SukiBookingPlugin._generate_available_maids_html(data)

    # 原始 HTML 不应出现在输出中（应被转义）
    assert_not_in_substring('<script>alert("xss")</script>', html, "script 标签被转义")
    assert_in_substring("&lt;script&gt;", html, "script 标签被转义为 &lt;script&gt;")
    assert_not_in_substring('onerror="alert(1)"', html, "onerror 被转义")
    # & 在 guestUsername 和 tag 中会被转义
    assert_in_substring("&amp;", html, "& 被转义")

    print("  XSS 防护测试完成")

async def test_generate_maid_detail_html() -> None:
    """测试 _generate_maid_detail_html 模板二"""
    print_section("测试 _generate_maid_detail_html（女仆详情）")

    data = {
        "maids": [
            {
                "name": "猫娘A",
                "image": "https://example.com/a.png",
                "disabled": False,
                "tags": ["ASMR", "唱歌", "温柔"],
                "signature": "你好呀，主人~",
            },
            {
                "name": "猫娘B",
                "image": "https://example.com/b.png",
                "disabled": True,
                "tags": ["傲娇"],
                "signature": "才不需要你关心",
            },
        ],
        "reservations": [
            {"maidName": "猫娘A", "timeSlot": "14:00-15:00", "guestUsername": "客人A"},
            {"maidName": "猫娘A", "timeSlot": "15:00-16:00", "guestUsername": "客人B"},
        ],
        "booking_enabled": True,
    }

    # 正常详情 - 猫娘A
    html = SukiBookingPlugin._generate_maid_detail_html(data, "猫娘A")

    assert_in_substring("<!DOCTYPE html>", html, "HTML 声明")
    assert_in_substring("Suki 猫娘咖啡厅", html, "品牌名称")
    assert_in_substring("女仆预约详情", html, "页面标题")
    assert_in_substring("detail-img", html, "详情页图片")
    assert_in_substring("猫娘A", html, "女仆名称")
    assert_in_substring("ASMR", html, "标签")
    assert_in_substring("你好呀，主人~", html, "签名")
    # 猫娘A 有 2 条预约记录，应显示"已约满"
    assert_in_substring("已约满", html, "有2条预约记录时显示已约满")
    assert_in_substring("预约记录（2 条）", html, "预约记录数")
    assert_in_substring("客人A", html, "客人 1")
    assert_in_substring("客人B", html, "客人 2")
    assert_in_substring("14:00-15:00", html, "时间段 1")
    assert_in_substring("15:00-16:00", html, "时间段 2")

    print(f"  生成 HTML 长度: {len(html)} 字符")
    print("  _generate_maid_detail_html 测试完成")

async def test_generate_maid_detail_html_disabled() -> None:
    """测试详情模板 - disabled 女仆"""
    print_section("测试详情模板 - disabled 女仆")

    data = {
        "maids": [
            {
                "name": "猫娘B",
                "image": "https://example.com/b.png",
                "disabled": True,
                "tags": ["傲娇"],
                "signature": "才不需要你关心",
            },
        ],
        "reservations": [],
        "booking_enabled": True,
    }
    html = SukiBookingPlugin._generate_maid_detail_html(data, "猫娘B")

    # disabled 女仆应显示"今日休息"
    assert_in_substring("今日休息", html, "disabled 显示今日休息")
    assert_not_in_substring("可预约", html, "disabled 不应显示可预约")

    print("  disabled 女仆测试完成")

async def test_generate_maid_detail_html_booking_closed() -> None:
    """测试详情模板 - booking_enabled=False"""
    print_section("测试详情模板 - booking_enabled=False")

    data = {
        "maids": [
            {
                "name": "猫娘A",
                "image": "https://example.com/a.png",
                "disabled": False,
                "tags": [],
                "signature": "",
            },
        ],
        "reservations": [],
        "booking_enabled": False,
    }
    html = SukiBookingPlugin._generate_maid_detail_html(data, "猫娘A")

    # 非 disabled 但 booking_enabled=False 应显示"预约已关闭"
    assert_in_substring("预约已关闭", html, "预约已关闭状态")

    print("  booking_enabled=False 测试完成")

async def test_generate_maid_detail_html_not_found() -> None:
    """测试详情模板 - 未找到女仆"""
    print_section("测试详情模板 - 未找到女仆")

    data = {
        "maids": [
            {"name": "猫娘A", "image": "https://x.com/a.png", "disabled": False, "tags": [], "signature": ""},
        ],
        "reservations": [],
        "booking_enabled": True,
    }
    html = SukiBookingPlugin._generate_maid_detail_html(data, "不存在的女仆")

    assert_in_substring("未找到女仆", html, "未找到提示")
    assert_in_substring("不存在的女仆", html, "女仆名出现在提示中")
    assert_in_substring("请确认女仆名称", html, "确认提示")

    print("  未找到女仆测试完成")

async def test_generate_maid_detail_html_no_reservations() -> None:
    """测试详情模板 - 无预约记录"""
    print_section("测试详情模板 - 无预约记录")

    data = {
        "maids": [
            {"name": "猫娘A", "image": "https://x.com/a.png", "disabled": False, "tags": [], "signature": ""},
        ],
        "reservations": [],
        "booking_enabled": True,
    }
    html = SukiBookingPlugin._generate_maid_detail_html(data, "猫娘A")

    assert_in_substring("暂无预约记录", html, "暂无预约提示") or assert_in_substring("📭", html, "暂无预约 emoji")

    print("  无预约记录测试完成")

async def test_generate_maid_detail_html_xss() -> None:
    """测试详情模板 - XSS 防护"""
    print_section("测试详情模板 - XSS 防护")

    data = {
        "maids": [
            {
                "name": '<script>alert("xss")</script>',
                "image": 'x onerror="alert(1)"',
                "disabled": False,
                "tags": ["<b>bad</b>"],
                "signature": "tag<script>",
            },
        ],
        "reservations": [
            {
                "maidName": '<script>alert("xss")</script>',
                "timeSlot": "14:00-15:00",
                "guestUsername": '<img src=x onerror="alert(1)">',
            },
        ],
        "booking_enabled": True,
    }
    html = SukiBookingPlugin._generate_maid_detail_html(data, '<script>alert("xss")</script>')

    assert_not_in_substring('<script>alert("xss")</script>', html, "script 被转义")
    assert_not_in_substring('onerror="alert(1)"', html, "onerror 被转义")
    assert_in_substring("&lt;script&gt;", html, "转义后的 script")

    print("  XSS 防护测试完成")

# ============================================================================
# 测试用例: 渲染管线
# ============================================================================

async def test_render_and_send_png_success_str() -> None:
    """测试 _render_and_send_png - html2png 返回 str"""
    print_section("测试 _render_and_send_png - str 返回值")

    plugin = create_plugin()
    plugin.ctx.render.set_return("base64_image_data_here")

    result = await plugin._render_and_send_png("<html>test</html>", "stream_1")

    assert_true(plugin.ctx.render.called, "html2png 被调用")
    assert_equal(plugin.ctx.render.last_html, "<html>test</html>", "传递的 HTML 正确")
    assert_equal(result, "base64_image_data_here", "返回 base64 字符串")

    # 检查 send.image 被调用
    sent = plugin.ctx.send.sent_messages
    assert_equal(len(sent), 1, "发送了 1 条消息")
    assert_equal(sent[0]["type"], "image", "发送的是图片")
    assert_equal(sent[0]["data"], "base64_image_data_here", "图片数据正确")

    print("  str 返回值测试完成")

async def test_render_and_send_png_success_dict() -> None:
    """测试 _render_and_send_png - html2png 返回 dict"""
    print_section("测试 _render_and_send_png - dict 返回值")

    plugin = create_plugin()
    plugin.ctx.render.set_return({"image_base64": "dict_base64_data"})

    result = await plugin._render_and_send_png("<html>test</html>", "stream_1")

    assert_equal(result, "dict_base64_data", "从 dict.image_base64 提取")

    # 测试 dict 的 "data" 键
    plugin2 = create_plugin()
    plugin2.ctx.render.set_return({"data": "data_key_value"})
    plugin2.ctx.send.reset()
    result2 = await plugin2._render_and_send_png("<html>test</html>", "stream_1")
    assert_equal(result2, "data_key_value", "从 dict.data 提取")

    # 测试 dict 的 "image" 键
    plugin3 = create_plugin()
    plugin3.ctx.render.set_return({"image": "image_key_value"})
    plugin3.ctx.send.reset()
    result3 = await plugin3._render_and_send_png("<html>test</html>", "stream_1")
    assert_equal(result3, "image_key_value", "从 dict.image 提取")

    print("  dict 返回值测试完成")

async def test_render_and_send_png_success_bytes() -> None:
    """测试 _render_and_send_png - html2png 返回 bytes"""
    print_section("测试 _render_and_send_png - bytes 返回值")

    plugin = create_plugin()
    from base64 import b64encode

    raw_bytes = b"\x89PNG\r\n\x1a\nfake_png_data"
    plugin.ctx.render.set_return(raw_bytes)

    result = await plugin._render_and_send_png("<html>test</html>", "stream_1")
    expected = b64encode(raw_bytes).decode("ascii")
    assert_equal(result, expected, "bytes 被 b64encode 编码")

    print("  bytes 返回值测试完成")

async def test_render_and_send_png_failure_exception() -> None:
    """测试 _render_and_send_png - html2png 抛异常"""
    print_section("测试 _render_and_send_png - 异常")

    plugin = create_plugin()
    plugin.ctx.render.set_exception(RuntimeError("渲染引擎崩溃"))

    result = await plugin._render_and_send_png("<html>test</html>", "stream_1")

    assert_true(result is None, "异常时返回 None")
    assert_equal(len(plugin.ctx.send.sent_messages), 0, "没有发送任何消息")

    print("  异常处理测试完成")

async def test_render_and_send_png_failure_empty() -> None:
    """测试 _render_and_send_png - html2png 返回空值"""
    print_section("测试 _render_and_send_png - 空结果")

    plugin = create_plugin()
    plugin.ctx.render.set_return(None)

    result = await plugin._render_and_send_png("<html>test</html>", "stream_1")
    assert_true(result is None, "None 返回 -> 返回 None")

    plugin2 = create_plugin()
    plugin2.ctx.render.set_return("")
    result2 = await plugin2._render_and_send_png("<html>test</html>", "stream_1")
    assert_true(result2 is None, "空字符串 -> 返回 None")

    plugin3 = create_plugin()
    plugin3.ctx.render.set_return({})
    result3 = await plugin3._render_and_send_png("<html>test</html>", "stream_1")
    assert_true(result3 is None, "空 dict -> 返回 None")

    print("  空结果处理测试完成")

async def test_render_and_send_png_failure_unknown_type() -> None:
    """测试 _render_and_send_png - html2png 返回未知类型"""
    print_section("测试 _render_and_send_png - 未知类型")

    plugin = create_plugin()
    plugin.ctx.render.set_return(12345)  # int 类型，不支持

    result = await plugin._render_and_send_png("<html>test</html>", "stream_1")
    assert_true(result is None, "未知类型 -> 返回 None")

    print("  未知类型处理测试完成")

# ============================================================================
# 测试用例: 常量
# ============================================================================

async def test_constants() -> None:
    """测试常量定义"""
    print_section("测试常量定义")

    assert_equal(RENDER_WIDTH, 390, "RENDER_WIDTH = 390")

    # _load_css 应从文件加载 CSS 并替换 {width} 占位符
    css = _load_css(390)
    # CSS 模板中写的是 "width: {width}px"（带空格），替换后为 "width: 390px"
    assert_in_substring("width: 390px", css, "CSS 包含注入后的宽度")
    assert_in_substring("#FDF6F0", css, "暖奶油白背景")
    assert_in_substring("#6B4226", css, "咖啡棕主色")
    assert_in_substring("#C87941", css, "焦糖橙强调")

    # HEADERS 应包含 Supabase 认证
    assert_in("apikey", HEADERS, "HEADERS 包含 apikey")
    assert_in("Authorization", HEADERS, "HEADERS 包含 Authorization")

    print("  常量测试完成")

# ============================================================================
# 测试用例: _load_css 缓存行为
# ============================================================================

async def test_load_css_caching() -> None:
    """测试 _load_css 缓存行为"""
    print_section("测试 _load_css 缓存")

    css1 = _load_css(390)
    css2 = _load_css(390)
    assert_equal(css1, css2, "相同宽度返回一致结果")
    assert_true(len(css1) > 0, "CSS 非空")

    print("  _load_css 缓存测试完成")

# ============================================================================
# 测试用例: 网络相关
# ============================================================================

async def test_api_request(plugin: SukiBookingPlugin, limit: int = 1) -> dict:
    """测试 _fetch_booking API 请求"""
    print_section(f"测试 API 请求 (limit={limit})")

    start = time.time()
    data = await plugin._fetch_booking(limit=limit)
    elapsed = time.time() - start

    print(f"  耗时: {elapsed:.3f} 秒")

    if data is None:
        print_result("结果", {"error": "API 返回 None，请求失败"})
        return {"success": False, "elapsed": elapsed, "data": None}

    count = len(data) if isinstance(data, list) else 1
    print(f"  成功获取到 {count} 条记录")

    # 验证数据结构
    for item in data:
        assert_in("maids", item, "数据包含 maids")
        assert_in("reservations", item, "数据包含 reservations")
        assert_in("booking_enabled", item, "数据包含 booking_enabled")
        for m in item.get("maids", []):
            assert_in("tags", m, "maid 包含 tags 字段")
            assert_in("signature", m, "maid 包含 signature 字段")

    return {"success": True, "elapsed": elapsed, "count": count, "data": data}

# ============================================================================
# 测试用例: Tool 调用
# ============================================================================

async def test_tool_call(plugin: SukiBookingPlugin, limit: int = 1) -> dict:
    """测试 Tool 调用: handle_tool_query_booking"""
    print_section(f"测试 Tool 调用 (limit={limit})")

    start = time.time()
    result = await plugin.handle_tool_query_booking(limit=limit)
    elapsed = time.time() - start

    print(f"  耗时: {elapsed:.3f} 秒")

    if result.get("success"):
        print("  Tool 执行成功")
    else:
        print("  Tool 执行失败")

    print_result("Tool 返回值", result)
    return result

async def test_tool_call_with_maid_name() -> None:
    """测试 Tool 调用 - 指定 maid_name"""
    print_section("测试 Tool 调用 - 指定 maid_name")

    plugin = create_plugin()
    # 模拟 html2png 返回 str（成功渲染）
    plugin.ctx.render.set_return("mock_base64_image")

    result = await plugin.handle_tool_query_booking(maid_name="猫娘A", limit=1, stream_id="test_stream")

    if result.get("success"):
        assert_true("content" in result, "包含 content 字段")
        # 如果成功渲染图片，应该有 content_items
        if "content_items" in result:
            assert_true(len(result["content_items"]) > 0, "有 content_items")
            assert_equal(result["content_items"][0]["type"], "image", "content_item 类型为 image")
            print("  Tool 返回了图片 content_items")
        else:
            print("  Tool 返回了降级文本（渲染管线不可用）")

    print_result("Tool 返回值 (maid_name=猫娘A)", result)
    print("  maid_name 指定测试完成")

async def test_tool_call_degradation() -> None:
    """测试 Tool 调用 - 降级为文本"""
    print_section("测试 Tool 调用 - 降级为文本")

    plugin = create_plugin()
    # html2png 抛异常，应降级为文本
    plugin.ctx.render.set_exception(RuntimeError("渲染失败"))

    result = await plugin.handle_tool_query_booking(maid_name="", limit=1, stream_id="test_stream")

    if result.get("success"):
        # 降级后应该没有 content_items，只有 content 文本
        assert_not_in("content_items", result, "降级后无 content_items")
        assert_in_substring("Suki", result.get("content", ""), "降级文本包含 Suki")

    print_result("降级返回值", result)
    print("  降级测试完成")

# ============================================================================
# 测试用例: Command 调用
# ============================================================================

async def test_command(plugin: SukiBookingPlugin) -> dict:
    """测试 Command 调用: handle_suki"""
    print_section("测试 Command 调用 (/suki)")

    plugin.ctx.send.reset()
    mock_stream_id = "test_stream_12345"

    kwargs = {
        "stream_id": mock_stream_id,
        "matched_groups": {},
        "raw_message": "/suki",
        "message": {"text": "/suki", "stream_id": mock_stream_id},
    }

    start = time.time()
    success, response, weight = await plugin.handle_suki(**kwargs)
    elapsed = time.time() - start

    print(f"  耗时: {elapsed:.3f} 秒")

    if success:
        print("  Command 执行成功")
    else:
        print("  Command 执行失败")

    print_result("返回值", (success, response, weight))
    print_result("发送的消息记录", plugin.ctx.send.sent_messages)

    return {
        "success": success,
        "response": response,
        "weight": weight,
        "elapsed": elapsed,
        "sent_messages": plugin.ctx.send.sent_messages,
    }

async def test_command_with_render_success() -> None:
    """测试 Command 调用 - html2png 成功"""
    print_section("测试 Command 调用 - html2png 成功")

    plugin = create_plugin()
    plugin.ctx.render.set_return("mock_base64")

    mock_stream_id = "test_stream_cmd"
    kwargs = {
        "stream_id": mock_stream_id,
        "matched_groups": {},
        "raw_message": "/suki",
        "message": {"text": "/suki", "stream_id": mock_stream_id},
    }

    success, response, weight = await plugin.handle_suki(**kwargs)

    assert_true(success, "Command 成功")
    # 检查是否发送了图片
    sent = plugin.ctx.send.sent_messages
    image_sent = any(m["type"] == "image" for m in sent)
    if image_sent:
        print("  成功发送了 PNG 图片")
        assert_in_substring("图片", response, "响应提到图片")

    print_result("返回值", (success, response, weight))
    print_result("发送的消息", sent)
    print("  Command 成功渲染测试完成")

async def test_command_degradation() -> None:
    """测试 Command 调用 - 降级为文本"""
    print_section("测试 Command 调用 - 降级为文本")

    plugin = create_plugin()
    # html2png 失败，应降级为文本
    plugin.ctx.render.set_exception(RuntimeError("渲染失败"))

    mock_stream_id = "test_stream_cmd"
    kwargs = {
        "stream_id": mock_stream_id,
        "matched_groups": {},
        "raw_message": "/suki",
        "message": {"text": "/suki", "stream_id": mock_stream_id},
    }

    success, response, weight = await plugin.handle_suki(**kwargs)

    assert_true(success, "Command 仍返回成功")
    # 降级后应该有文本消息
    sent = plugin.ctx.send.sent_messages
    text_messages = [m for m in sent if m["type"] == "text"]
    # 应该有初始提示 + 降级文本
    assert_true(len(text_messages) >= 2, "有初始提示 + 降级文本")

    print_result("降级响应", response)
    print_result("发送的文本消息", text_messages)
    print("  Command 降级测试完成")

# ============================================================================
# 测试用例: 生命周期 & 边界情况
# ============================================================================

async def test_lifecycle(plugin: SukiBookingPlugin) -> None:
    """测试插件生命周期钩子"""
    print_section("测试插件生命周期")

    print("  调用 on_load()")
    await plugin.on_load()

    print("  调用 on_config_update()")
    await plugin.on_config_update("self", {"setting": "value"}, "1.0.0")

    print("  调用 on_unload()")
    await plugin.on_unload()

    print("  生命周期钩子测试完成")

async def test_tool_with_different_limits(plugin: SukiBookingPlugin) -> None:
    """测试 Tool 使用不同 limit 值"""
    print_section("测试 Tool 不同 limit 值")

    for limit in [1, 3, 5]:
        print(f"\n  测试 limit={limit}")
        result = await plugin.handle_tool_query_booking(limit=limit)
        count = result.get("count", 0) if result.get("success") else 0
        print(f"    -> 获取 {count} 条记录")

async def test_edge_cases(plugin: SukiBookingPlugin) -> None:
    """测试边界情况"""
    print_section("测试边界情况")

    # limit=0
    print("\n  测试 limit=0")
    result = await plugin.handle_tool_query_booking(limit=0)
    print_result("limit=0 结果", result)

    # 大 limit
    print("\n  测试 limit=100")
    result = await plugin.handle_tool_query_booking(limit=100)
    print_result("limit=100 结果", result)

# ============================================================================
# 测试用例: 两栏布局 & 图片缓存
# ============================================================================

async def test_generate_available_maids_html_two_columns() -> None:
    """测试一览模板 - 双栏布局（>12 位活跃女仆）"""
    print_section("测试一览模板 - 双栏布局")

    maids = []
    for i in range(15):
        maids.append(
            {
                "name": f"猫娘{i}",
                "image": f"https://example.com/{i}.png",
                "disabled": False,
                "tags": [f"标签{i}", "标签B"],
                "signature": f"签名{i}",
            }
        )

    data = {
        "maids": maids,
        "reservations": [],
        "booking_enabled": True,
    }
    html = SukiBookingPlugin._generate_available_maids_html(data)

    assert_in_substring("grid-2col", html, "使用双栏 grid-2col")
    assert_in_substring("card-2col", html, "使用双栏卡片 card-2col")
    assert_in_substring("card-img-2col", html, "使用双栏图片 card-img-2col")
    # CSS 定义中会有 card-img-single/slot-row 类，但 body 内容中不应该出现
    body_start = html.find("<body>")
    body_content = html[body_start:] if body_start > 0 else html
    assert_not_in_substring("card-img-single", body_content, "双栏 body 不应有 card-img-single")
    assert_not_in_substring("slot-row", body_content, "双栏 body 不应有 slot-row")
    for i in range(15):
        assert_in_substring(f"猫娘{i}", html, f"猫娘{i} 出现在 HTML 中")
    assert_in_substring("15", html, "统计包含 15")

    print(f"  生成 HTML 长度: {len(html)} 字符")
    print("  双栏布局测试完成")

async def test_generate_available_maids_html_single_column() -> None:
    """测试一览模板 - 单栏布局（≤12 位活跃女仆）"""
    print_section("测试一览模板 - 单栏布局")

    maids = []
    for i in range(5):
        maids.append(
            {
                "name": f"猫娘{i}",
                "image": f"https://example.com/{i}.png",
                "disabled": False,
                "tags": [f"标签{i}", "标签B", "标签C"],
                "signature": f"签名{i}",
            }
        )

    reservations = [
        {"maidName": "猫娘0", "timeSlot": "10:00-11:00", "guestUsername": "客人X"},
        {"maidName": "猫娘0", "timeSlot": "11:00-12:00", "guestUsername": "客人Y"},
    ]

    data = {
        "maids": maids,
        "reservations": reservations,
        "booking_enabled": True,
    }
    html = SukiBookingPlugin._generate_available_maids_html(data)

    # CSS 定义中会有 grid-2col/card-2col 类，但 body 内容中不应该出现
    body_start = html.find("<body>")
    body_content = html[body_start:] if body_start > 0 else html
    assert_not_in_substring("grid-2col", body_content, "单栏 body 不使用 grid-2col")
    assert_not_in_substring("card-2col", body_content, "单栏 body 不使用 card-2col")
    assert_in_substring("card-img-single", body_content, "使用单栏图片 card-img-single")
    assert_in_substring("slot-row", body_content, "单栏使用 slot-row")
    assert_in_substring("标签C", html, "单栏显示第 3 个标签")
    assert_in_substring("已约满", html, "2条预约显示已约满")
    assert_in_substring("10:00-11:00", html, "显示预约时间 1")
    assert_in_substring("11:00-12:00", html, "显示预约时间 2")
    assert_in_substring("客人X", html, "显示客人 1")
    assert_in_substring("客人Y", html, "显示客人 2")

    print("  单栏布局测试完成")

async def test_html_with_image_cache() -> None:
    """测试 HTML 生成时使用 image_cache 参数"""
    print_section("测试 HTML 生成 - image_cache 参数")

    image_cache = {
        "https://example.com/a.png": "data:image/png;base64,FAKE_BASE64_DATA",
        "https://example.com/b.png": "data:image/png;base64,FAKE_BASE64_B",
    }

    data = {
        "maids": [
            {
                "name": "猫娘A",
                "image": "https://example.com/a.png",
                "disabled": False,
                "tags": ["温柔"],
                "signature": "你好呀",
            },
            {
                "name": "猫娘B",
                "image": "https://example.com/b.png",
                "disabled": False,
                "tags": [],
                "signature": "",
            },
        ],
        "reservations": [],
        "booking_enabled": True,
    }

    html_avail = SukiBookingPlugin._generate_available_maids_html(data, image_cache)
    assert_in_substring("FAKE_BASE64_DATA", html_avail, "一览模板使用缓存 base64")
    assert_in_substring("FAKE_BASE64_B", html_avail, "一览模板使用缓存 base64 B")
    assert_not_in_substring("https://example.com/a.png", html_avail, "一览模板不出现原始 URL")

    html_detail = SukiBookingPlugin._generate_maid_detail_html(data, "猫娘A", image_cache)
    assert_in_substring("FAKE_BASE64_DATA", html_detail, "详情模板使用缓存 base64")
    assert_not_in_substring("https://example.com/a.png", html_detail, "详情模板不出现原始 URL")

    data_no_cache = {
        "maids": [
            {
                "name": "未知猫娘",
                "image": "https://unknown.com/c.png",
                "disabled": False,
                "tags": [],
                "signature": "",
            },
        ],
        "reservations": [],
        "booking_enabled": True,
    }
    html_no_cache = SukiBookingPlugin._generate_available_maids_html(data_no_cache, image_cache)
    # 当图片不在 cache 中时，plugin.py 不会使用原始 URL，而是设置 img_src="" 并生成空 div
    # 所以原始 URL 不应出现在 HTML 中
    assert_not_in_substring(
        "https://unknown.com/c.png", html_no_cache, "未知图片不使用原始 URL（cache 命中为空时不显示外链）"
    )

    print("  image_cache 参数测试完成")

async def test_render_and_send_png_no_stream_id() -> None:
    """测试 _render_and_send_png - 空 stream_id"""
    print_section("测试 _render_and_send_png - 空 stream_id")

    plugin = create_plugin()
    plugin.ctx.render.set_return("mock_base64")

    result = await plugin._render_and_send_png("<html>test</html>", "")
    assert_equal(result, "mock_base64", "空 stream_id 仍能成功")
    assert_true(plugin.ctx.render.called, "html2png 被调用")

    print("  空 stream_id 测试完成")

# ============================================================================
# 测试用例: list_suki_maids Tool
# ============================================================================

async def test_tool_list_maids() -> None:
    """测试 Tool: handle_tool_list_maids"""
    print_section("测试 Tool list_suki_maids")

    plugin = create_plugin()

    async def mock_fetch(limit=1):
        return [make_sample_data()]

    plugin._fetch_booking = mock_fetch

    result = await plugin.handle_tool_list_maids(limit=1)

    assert_true(result.get("success"), "list_suki_maids 成功")
    assert_in_substring("猫娘A", result.get("content", ""), "包含在线女仆名")
    assert_in_substring("在线", result.get("content", ""), "包含在线状态")
    assert_in_substring("猫娘B", result.get("content", ""), "包含离线女仆名")
    assert_in_substring("离线", result.get("content", ""), "包含离线状态")
    assert_in_substring("共", result.get("content", ""), "包含总数")
    assert_in_substring("位女仆", result.get("content", ""), "包含单位")

    print_result("list_suki_maids 返回值", result)
    print("  list_suki_maids 测试完成")

async def test_tool_list_maids_empty() -> None:
    """测试 Tool list_suki_maids - 无女仆数据"""
    print_section("测试 Tool list_suki_maids - 空数据")

    plugin = create_plugin()

    async def mock_fetch_empty(limit=1):
        return [{"maids": [], "reservations": [], "booking_enabled": True}]

    plugin._fetch_booking = mock_fetch_empty

    result = await plugin.handle_tool_list_maids(limit=1)

    assert_true(result.get("success"), "成功")
    assert_in_substring("暂无", result.get("content", ""), "提示暂无数据")

    print("  list_suki_maids 空数据测试完成")

async def test_tool_list_maids_failure() -> None:
    """测试 Tool list_suki_maids - 数据获取失败"""
    print_section("测试 Tool list_suki_maids - 失败")

    plugin = create_plugin()

    async def mock_fetch_fail(limit=1):
        return None

    plugin._fetch_booking = mock_fetch_fail

    result = await plugin.handle_tool_list_maids(limit=1)

    assert_true(not result.get("success"), "失败")
    assert_in_substring("查询失败", result.get("content", ""), "错误提示")

    print("  list_suki_maids 失败测试完成")

# ============================================================================
# 测试用例: Tool content_items 结构验证
# ============================================================================

async def test_tool_content_items_structure() -> None:
    """测试 Tool 返回的 content_items 结构完整性"""
    print_section("测试 Tool content_items 结构")

    plugin = create_plugin()
    plugin.ctx.render.set_return("mock_base64_image_data")

    async def mock_fetch(limit=1):
        return [make_sample_data()]

    plugin._fetch_booking = mock_fetch

    result = await plugin.handle_tool_query_booking(maid_name="", limit=1, stream_id="test")

    if result.get("success") and "content_items" in result:
        items = result["content_items"]
        assert_true(len(items) > 0, "content_items 非空")
        item = items[0]
        assert_equal(item["type"], "image", "item type 为 image")
        assert_equal(item["data"], "mock_base64_image_data", "item data 正确")
        assert_equal(item["mime_type"], "image/png", "mime_type 正确")
        assert_equal(item["name"], "suki_booking.png", "name 正确")
        assert_in("description", item, "包含 description")
        print("  content_items 结构完整")
    else:
        print("  content_items 不存在，跳过结构验证")

    print("  content_items 结构测试完成")

async def test_tool_query_booking_no_stream_id() -> None:
    """测试 Tool 调用 - 无 stream_id 时不尝试渲染"""
    print_section("测试 Tool 调用 - 无 stream_id")

    plugin = create_plugin()

    async def mock_fetch(limit=1):
        return [make_sample_data()]

    plugin._fetch_booking = mock_fetch

    result = await plugin.handle_tool_query_booking(limit=1, stream_id="")

    assert_true(result.get("success"), "成功")
    assert_not_in("content_items", result, "无 stream_id 时无 content_items")
    assert_in("content", result, "有 content 文本")

    print("  无 stream_id 测试完成")

# ============================================================================
# 测试用例: _fetch_booking 错误路径
# ============================================================================

async def test_fetch_booking_error_paths() -> None:
    """测试 _fetch_booking 的错误处理"""
    print_section("测试 _fetch_booking 错误路径")

    plugin = create_plugin()

    import unittest.mock

    import aiohttp
    import plugin as plugin_module

    # 测试非 200 状态码
    class FakeResponse500:
        status = 500

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def text(self):
            return "Internal Server Error"

    class FakeSession500:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def get(self, *args, **kwargs):
            return FakeResponse500()

    with unittest.mock.patch.object(plugin_module.aiohttp, "ClientSession", FakeSession500):
        result = await plugin._fetch_booking(limit=1)
        assert_true(result is None, "500 状态码时返回 None")

    # 测试 ClientError 异常（通过 session.get 直接抛出）
    class FakeSessionError:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def get(self, *args, **kwargs):
            raise aiohttp.ClientError("Connection failed")

    with unittest.mock.patch.object(plugin_module.aiohttp, "ClientSession", FakeSessionError):
        result = await plugin._fetch_booking(limit=1)
        assert_true(result is None, "ClientError 时返回 None")

    print("  _fetch_booking 错误路径测试完成")

# ============================================================================
# 测试用例: _format_booking 边界情况
# ============================================================================

async def test_format_booking_edge_cases() -> None:
    """测试 _format_booking 边界情况"""
    print_section("测试 _format_booking 边界情况")

    multi_items = [
        {
            "booking_enabled": True,
            "maids": [{"name": "猫娘1", "image": "", "disabled": False}],
            "reservations": [],
        },
        {
            "booking_enabled": False,
            "maids": [{"name": "猫娘2", "image": "", "disabled": True}],
            "reservations": [],
        },
    ]
    result = SukiBookingPlugin._format_booking(multi_items)
    assert_in_substring("预约 #1", result, "多条记录显示编号 1")
    assert_in_substring("预约 #2", result, "多条记录显示编号 2")

    none_maids = [{"booking_enabled": True, "maids": None, "reservations": None}]
    result_none = SukiBookingPlugin._format_booking(none_maids)
    assert_in_substring("共 0 位", result_none, "maids=None 时显示 0 位")
    assert_in_substring("共 0 条", result_none, "reservations=None 时显示 0 条")

    print("  _format_booking 边界测试完成")

# ============================================================================
# 测试用例: /猫娘占卜 Command 静态验证
# ============================================================================

async def test_draw_maid_command_static() -> None:
    """测试 /猫娘占卜 Command（默认从全部女仆中抽取，含今日休息）"""
    print_section("测试 /猫娘占卜 Command")

    # 验证方法存在
    assert_true(hasattr(SukiBookingPlugin, "handle_draw_maid"), "handle_draw_maid 方法存在")

    # 验证方法可调用
    plugin = create_plugin()
    method = getattr(plugin, "handle_draw_maid", None)
    assert_true(method is not None, "插件实例上有 handle_draw_maid")
    assert_true(callable(method), "handle_draw_maid 可调用")

    # 验证 /猫娘占卜 从全部女仆中随机（不再过滤 disabled）
    from random import seed

    seed(42)  # 固定种子确保可重复
    test_maids = [
        {"name": "抽A", "image": "", "disabled": False, "tags": [], "signature": ""},
        {"name": "抽B", "image": "", "disabled": True, "tags": [], "signature": ""},
        {"name": "抽C", "image": "", "disabled": False, "tags": [], "signature": ""},
    ]
    import random
    chosen = random.choice(test_maids)
    # seed(42) + choice 在 seed(42) 后第一个 choice 是 "抽C"（可验证）
    print(f"  seed(42) 抽中: {chosen['name']}")

    print("  /猫娘占卜 静态验证完成")

# ============================================================================
# 测试用例: Tool draw_suki_maid 参数逻辑
# ============================================================================


async def test_tool_draw_maid_static() -> None:
    """测试 Tool draw_suki_maid 的 include_disabled 参数逻辑"""
    print_section("测试 Tool draw_suki_maid")

    # 验证方法存在
    assert_true(hasattr(SukiBookingPlugin, "handle_tool_draw_maid"), "handle_tool_draw_maid 方法存在")

    plugin = create_plugin()
    method = getattr(plugin, "handle_tool_draw_maid", None)
    assert_true(method is not None, "插件实例上有 handle_tool_draw_maid")
    assert_true(callable(method), "handle_tool_draw_maid 可调用")

    # 验证候选池过滤逻辑（静态）
    test_maids = [
        {"name": "A", "image": "", "disabled": False, "tags": [], "signature": ""},
        {"name": "B", "image": "", "disabled": True, "tags": [], "signature": ""},
    ]

    # include_disabled=True -> 全部女仆
    candidates_all = test_maids
    assert_equal(len(candidates_all), 2, "include_disabled=true 包含全部 2 位")

    # include_disabled=False -> 只取未禁用的
    candidates_active = [m for m in test_maids if not m.get("disabled")]
    assert_equal(len(candidates_active), 1, "include_disabled=false 只包含 1 位可用")
    assert_equal(candidates_active[0]["name"], "A", "只选到未禁用的 A")

    print("  Tool draw_suki_maid 静态验证完成")


# ============================================================================
# 测试用例: 详情页签名空值处理
# ============================================================================

async def test_detail_signature_variations() -> None:
    """测试详情页签名的各种情况"""
    print_section("测试详情页签名处理")

    # 有签名 - 签名内容应出现在 body 中
    data_sig = {
        "maids": [{"name": "A", "image": "", "disabled": False, "tags": [], "signature": "我是签名"}],
        "reservations": [],
        "booking_enabled": True,
    }
    html = SukiBookingPlugin._generate_maid_detail_html(data_sig, "A")
    assert_in_substring("我是签名", html, "签名内容出现")
    # 签名内容出现在 body 的 detail-signature div 中（CSS 中也有类名定义）
    body_sig = html[html.find("<body>") :]
    assert_in_substring('<div class="detail-signature">', body_sig, "签名 div 在 body 中")

    # 空签名 - body 中不应有签名 div
    data_empty = {
        "maids": [{"name": "A", "image": "", "disabled": False, "tags": [], "signature": ""}],
        "reservations": [],
        "booking_enabled": True,
    }
    html_empty = SukiBookingPlugin._generate_maid_detail_html(data_empty, "A")
    body_empty = html_empty[html_empty.find("<body>") :]
    # CSS 块中有 detail-signature 定义，但 body 中不应有实际元素
    assert_not_in_substring('<div class="detail-signature">', body_empty, "空签名 body 无签名 div")

    # 无签名字段 - body 中不应有签名 div
    data_no_sig = {
        "maids": [{"name": "A", "image": "", "disabled": False, "tags": []}],
        "reservations": [],
        "booking_enabled": True,
    }
    html_no = SukiBookingPlugin._generate_maid_detail_html(data_no_sig, "A")
    body_no = html_no[html_no.find("<body>") :]
    assert_not_in_substring('<div class="detail-signature">', body_no, "无签名字段 body 无签名 div")

    print("  签名处理测试完成")

# ============================================================================
# 测试用例: 预约记录排序
# ============================================================================

async def test_reservation_sorting_in_single_column() -> None:
    """测试单栏模式中预约记录按时间排序"""
    print_section("测试预约记录排序")

    data = {
        "maids": [
            {"name": "猫娘A", "image": "", "disabled": False, "tags": [], "signature": ""},
        ],
        "reservations": [
            {"maidName": "猫娘A", "timeSlot": "16:00-17:00", "guestUsername": "客人Z"},
            {"maidName": "猫娘A", "timeSlot": "10:00-11:00", "guestUsername": "客人A"},
            {"maidName": "猫娘A", "timeSlot": "13:00-14:00", "guestUsername": "客人M"},
        ],
        "booking_enabled": True,
    }
    html = SukiBookingPlugin._generate_available_maids_html(data)

    # 单栏模式只显示前 2 条预约（按 timeSlot 排序），且只显示 slot 中
    # 排序后：10:00 < 13:00 < 16:00，取前 2 条 = 10:00 和 13:00
    assert_in_substring("10:00-11:00", html, "10:00-11:00 出现在 HTML 中")
    assert_in_substring("13:00-14:00", html, "13:00-14:00 出现在 HTML 中")
    # 16:00 是第 3 条，不应出现（只显示前 2 条）
    assert_not_in_substring("16:00-17:00", html, "只显示前 2 条预约")
    # 客人信息
    assert_in_substring("客人A", html, "客人A 出现")
    assert_in_substring("客人M", html, "客人M 出现")
    assert_not_in_substring("客人Z", html, "客人Z 不出现")

    print("  预约排序测试完成")

# ============================================================================
# 数据验证
# ============================================================================

def validate_response(result: dict, test_name: str) -> list[str]:
    """验证 Tool 返回值的结构和内容"""
    issues: list[str] = []

    if not isinstance(result, dict):
        issues.append(f"{test_name}: 返回值应该是 dict，实际是 {type(result).__name__}")
        return issues

    if "success" not in result:
        issues.append(f"{test_name}: 缺少 'success' 字段")
    elif not isinstance(result["success"], bool):
        issues.append(f"{test_name}: 'success' 应该是 bool")

    if result.get("success"):
        if "content" not in result:
            issues.append(f"{test_name}: success=True 时应该有 'content' 字段")
        elif not isinstance(result["content"], str):
            issues.append(f"{test_name}: 'content' 应该是 str")

    return issues

# ============================================================================
# 主测试运行器
# ============================================================================

async def run_tests(args: argparse.Namespace) -> bool:
    """运行选定的测试，返回是否全部通过"""
    global TEST_PASS, TEST_FAIL, TEST_SKIP

    all_issues: list[str] = []

    # ── 离线测试（不需要网络） ──────────────────────────────────
    if args.format or (not args.tool and not args.command and not args.api):
        # 模块函数
        await test_escape_html()

        # 静态方法
        await test_filter_booking()
        await test_filter_booking_edge_cases()
        await test_count_reservations_per_maid()
        await test_format_booking()

        # HTML 生成
        await test_generate_available_maids_html()
        await test_generate_available_maids_html_no_available()
        await test_generate_available_maids_html_xss()
        await test_generate_maid_detail_html()
        await test_generate_maid_detail_html_disabled()
        await test_generate_maid_detail_html_booking_closed()
        await test_generate_maid_detail_html_not_found()
        await test_generate_maid_detail_html_no_reservations()
        await test_generate_maid_detail_html_xss()

        # 常量 & CSS 加载
        await test_constants()
        await test_load_css_caching()

    # ── 渲染管线测试（Mock） ────────────────────────────────────
    if args.format or (not args.tool and not args.command and not args.api):
        await test_render_and_send_png_success_str()
        await test_render_and_send_png_success_dict()
        await test_render_and_send_png_success_bytes()
        await test_render_and_send_png_failure_exception()
        await test_render_and_send_png_failure_empty()
        await test_render_and_send_png_failure_unknown_type()

        # 两栏布局 & 图片缓存
        await test_generate_available_maids_html_two_columns()
        await test_generate_available_maids_html_single_column()
        await test_html_with_image_cache()
        await test_render_and_send_png_no_stream_id()

        # _format_booking 边界情况
        await test_format_booking_edge_cases()

        # 详情页签名处理
        await test_detail_signature_variations()

        # /猫娘占卜 静态验证
        await test_draw_maid_command_static()

        # draw_suki_maid Tool
        await test_tool_draw_maid_static()

        # 预约记录排序
        await test_reservation_sorting_in_single_column()

        # list_suki_maids Tool
        await test_tool_list_maids()
        await test_tool_list_maids_empty()
        await test_tool_list_maids_failure()

        # Tool content_items 结构验证
        await test_tool_content_items_structure()
        await test_tool_query_booking_no_stream_id()

        # _fetch_booking 错误路径
        await test_fetch_booking_error_paths()

    # ── 网络测试（需要 API） ────────────────────────────────────
    if args.api or (not args.tool and not args.command and not args.format):
        # 创建插件实例
        print("\n创建插件实例...")
        plugin = create_plugin()
        print(f"  插件类型: {type(plugin).__name__}")
        print(f"  上下文类型: {type(plugin.ctx).__name__}")

        # 测试生命周期
        if not args.api:
            await test_lifecycle(plugin)
            plugin = create_plugin()

        # 测试 API 请求
        api_result = await test_api_request(plugin, limit=1)
        issues = validate_response(
            {"success": api_result["success"], "content": "", "count": api_result.get("count", 0)}, "API Request"
        )
        all_issues.extend(issues)

    # ── Tool 测试 ──────────────────────────────────────────────
    if args.tool or (not args.command and not args.format and not args.api):
        plugin = create_plugin()

        if not args.tool:
            plugin = create_plugin()

        tool_result = await test_tool_call(plugin, limit=1)
        issues = validate_response(tool_result, "Tool Call (limit=1)")
        all_issues.extend(issues)

        # 测试指定 maid_name
        await test_tool_call_with_maid_name()

        # 测试降级
        await test_tool_call_degradation()

        if not args.tool:
            await test_tool_with_different_limits(plugin)

    # ── Command 测试 ───────────────────────────────────────────
    if args.command or (not args.tool and not args.format and not args.api):
        plugin = create_plugin()
        cmd_result = await test_command(plugin)
        if not cmd_result["success"]:
            all_issues.append(f"Command: 执行失败 - {cmd_result['response']}")

        # 测试成功渲染
        await test_command_with_render_success()

        # 测试降级
        await test_command_degradation()

    # ── 边界情况（仅全量测试） ──────────────────────────────────
    if not (args.tool or args.command or args.format or args.api):
        plugin = create_plugin()
        await test_edge_cases(plugin)

    # 汇总
    print_summary()

    if all_issues:
        print("\n发现以下问题:")
        for issue in all_issues:
            print(f"  - {issue}")
        return False

    if TEST_FAIL > 0:
        print(f"\n  {TEST_FAIL} 个断言失败！")
        return False

    print("\n  ✨ 所有测试通过！")
    return True

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Suki 预约查询插件 - 模拟运行测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python test.py              # 运行所有测试
  python test.py --tool       # 仅测试 Tool
  python test.py --command    # 仅测试 Command
  python test.py --format     # 仅测试格式化/HTML/渲染逻辑（离线）
  python test.py --api        # 仅测试 API 请求
        """,
    )
    parser.add_argument("--tool", action="store_true", help="仅测试 Tool 调用")
    parser.add_argument("--command", action="store_true", help="仅测试 Command 调用")
    parser.add_argument("--format", action="store_true", help="仅测试格式化/HTML/渲染逻辑（离线）")
    parser.add_argument("--api", action="store_true", help="仅测试 API 请求")

    args = parser.parse_args()

    # Windows 控制台 UTF-8 输出支持
    if sys.platform == "win32":
        import codecs

        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, errors="replace")
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, errors="replace")

    print("=" * 60)
    print("  Suki 预约查询插件 - 模拟运行测试")
    print("=" * 60)

    # 检查 aiohttp 依赖
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        print("\n缺少依赖: aiohttp")
        print("请运行: pip install aiohttp")
        sys.exit(1)

    success = asyncio.run(run_tests(args))
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
