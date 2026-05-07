"""Single source of truth for keyboard shortcut display labels."""
from __future__ import annotations

# (display_key, description) — used by ShortcutsPanel and _setup_shortcuts comments
SHORTCUTS: list[tuple[str, str]] = [
    ("← / →",          "上一张 / 下一张"),
    ("K / Space",       "标记保留 (KEEP)"),
    ("1 – 9",           "标记到对应文件夹"),
    ("U / Del",         "取消标记"),
    ("M",               "执行移动"),
    ("Ctrl+O",          "打开文件夹"),
    ("Ctrl+Shift+O",    "添加文件夹"),
    ("Ctrl+Shift+M",    "移动（菜单）"),
    ("Ctrl+Q",          "退出"),
]
