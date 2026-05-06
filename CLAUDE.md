# QuickPic — Claude 开发指南

## 项目概述

照片筛图工具，Python + PySide6 桌面应用，支持 Windows / macOS。
主要功能：多文件夹加载、JPG/RAW 配对、键盘驱动标记、一键移动文件。

## 运行方式

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python main.py
```

依赖安装：`pip install -e .`

## 技术栈

| 层次 | 技术 |
|------|------|
| GUI | PySide6 (Qt6) |
| RAW 缩略图 | rawpy（提取内嵌 JPEG，不解码全图） |
| EXIF | exifread |
| 持久化 | sqlite3（内置），DB 路径 `~/.quickpic/data.db` |
| 打包 | PyInstaller，配置见 `quick_pic.spec` |

## 项目结构

```
app/
├── core/          # 纯 Python，无 Qt 依赖
│   ├── models.py       # PhotoPair dataclass, MarkType enum
│   ├── scanner.py      # 扫描文件夹，JPG/RAW 配对，EXIF 排序
│   ├── exif_reader.py  # 读取 DateTimeOriginal
│   └── thumbnail.py    # RAW 内嵌 JPEG 提取，is_raw()/is_jpg() 判断
├── db/            # 纯 Python，无 Qt 依赖
│   ├── schema.sql      # 建表 DDL
│   └── repository.py   # 所有 DB 读写，其他模块不直接操作 SQL
├── services/      # 纯 Python，无 Qt 依赖
│   ├── session.py      # 管理 PhotoPair 列表、当前索引、标记操作
│   ├── mark_service.py # 标记逻辑 facade，调用 session + repository
│   └── move_service.py # 文件移动，resolve_moves() + execute_moves()
└── ui/            # PySide6，不被 core/db/services 导入
    ├── main_window.py  # 主窗口，快捷键，扫描/移动后台线程
    ├── viewer.py       # 图片显示 Widget，后台线程加载图片
    ├── toolbar.py      # 1-9 键绑定面板 + 状态栏
    └── dialogs.py      # 文件夹绑定对话框、移动确认对话框
```

## 核心约束（必须遵守）

**`app/core/`、`app/db/`、`app/services/` 中禁止导入任何 PySide6 / Qt 内容。**

理由：将来 LAN 传输功能会把 services 层复用为 FastAPI 服务端，保持这三层无 Qt 依赖是前提。

## 数据模型

```python
# app/core/models.py
class MarkType(str, Enum):
    NONE = "none"
    KEEP = "keep"
    FOLDER_KEY = "folder_key"

@dataclass
class PhotoPair:
    stem: str            # 文件名（无后缀）
    folder: str          # 来源文件夹绝对路径
    jpg_path: str | None
    raw_path: str | None
    capture_date: datetime | None
    mark_type: MarkType  # 当前标记状态
    folder_key: int | None  # 1-9，mark_type=FOLDER_KEY 时有效

    pair_id: str         # property: "{folder}::{stem}"，数据库主键
    display_path: str    # property: jpg_path or raw_path
```

## 数据库 Schema

```sql
-- 键位绑定（1-9 → 目标文件夹）
folder_bindings(key INTEGER PK, path TEXT, label TEXT)

-- 标记结果（每次标记立即写入）
marks(pair_id TEXT PK, mark_type TEXT, folder_key INTEGER, marked_at TEXT)

-- 单行会话状态（重启恢复位置）
session_state(id=1, last_index INTEGER, source_folders TEXT/JSON)
```

`repository.py` 是唯一合法的 DB 入口，其他文件不直接写 SQL。

## 常见任务

### 添加新的快捷键

在 `app/ui/main_window.py` 的 `_setup_shortcuts()` 方法中添加：

```python
QShortcut(QKeySequence("X"), self).activated.connect(self._your_handler)
```

### 支持新的 RAW 格式

在 `app/core/thumbnail.py` 的 `RAW_EXTENSIONS` 集合中添加后缀（小写）。

### 添加新的标记类型

1. 在 `app/core/models.py` 的 `MarkType` 枚举中添加新值
2. 在 `app/db/schema.sql` 的 `marks.mark_type` CHECK 约束中加入
3. 在 `app/services/move_service.py` 的 `resolve_moves()` 中处理新类型
4. 在 `app/ui/viewer.py` 的 `_MARK_COLORS` 和 `_update_display()` 中添加视觉样式

### 未来 LAN 传输

在 `app/services/` 新建 `lan_server.py`，使用 FastAPI 暴露 HTTP 端点，直接调用 `repository.py` 和 `move_service.py`，无需修改任何现有代码。

## 打包

```bash
pip install pyinstaller
pyinstaller quick_pic.spec   # 必须在目标平台上运行
# 产物：dist/QuickPic/（文件夹形式，zip 后分发）
```

GitHub Actions 自动构建配置见 `.github/workflows/build.yml`。
