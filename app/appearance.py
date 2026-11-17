# Yumi的L4D2工具箱
# Copyright (C) 2026 ZengDeRong
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""外观模式：夜间 / 日间 / 跟随系统.

三种模式存在配置的 `appearance` 里：
- `"system"`（**默认**）：跟随 Windows 的「应用模式」（设置 → 个性化 → 颜色）
- `"dark"`：强制夜间
- `"light"`：强制日间

「跟随系统」靠两种手段拿状态，互为兜底：
1. `QGuiApplication.styleHints().colorScheme()` —— Qt 6.5+ 的原生接口，最准，
   还能拿到系统切换时的信号；
2. 读注册表 `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize`
   的 `AppsUseLightTheme` —— 万一 Qt 后端没上报，也能自己问出来。

这里只负责「算出当前该用深色还是浅色」，具体配色在 `qml/L4D2/Theme.qml` 里。
"""
from __future__ import annotations

import sys

# 配置里允许的三种值
MODE_SYSTEM = "system"
MODE_DARK = "dark"
MODE_LIGHT = "light"
MODES = (MODE_SYSTEM, MODE_DARK, MODE_LIGHT)

_MODE_LABELS = {
    MODE_SYSTEM: "跟随系统",
    MODE_DARK: "夜间模式",
    MODE_LIGHT: "日间模式",
}

# 注册表里读出来的值（1 = 浅色）
_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_REG_KEY = "AppsUseLightTheme"


def normalize_mode(value: object) -> str:
    """把任意输入收成三种合法模式之一，认不出就用「跟随系统」。"""
    raw = str(value or "").strip().lower()
    return raw if raw in MODES else MODE_SYSTEM


def mode_label(mode: str) -> str:
    return _MODE_LABELS.get(normalize_mode(mode), _MODE_LABELS[MODE_SYSTEM])


def system_prefers_light() -> bool:
    """系统当前是不是浅色（日间）？读不到就按深色处理（原来是深色主题，别突然变白）。"""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg  # noqa: PLC0415

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            value, _ = winreg.QueryValueEx(key, _REG_KEY)
            return int(value) == 1
    except (OSError, ValueError, TypeError, ImportError):
        return False


def resolve_is_dark(mode: str, style_hints_light: bool | None = None) -> bool:
    """根据模式决定最终用不用深色。

    `style_hints_light` 是调用方从 Qt 的 styleHints 拿到并缓存下来的值
    （None 表示拿不到），拿不到时才回落到注册表。
    """
    m = normalize_mode(mode)
    if m == MODE_DARK:
        return True
    if m == MODE_LIGHT:
        return False
    # 跟随系统：优先用 Qt 上报的，其次查注册表
    is_light = style_hints_light if style_hints_light is not None else system_prefers_light()
    return not is_light
