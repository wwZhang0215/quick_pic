# QuickPic — 后续优化计划

## 已完成

| 项目 | 说明 |
|------|------|
| 扫描冻结 | worker 信号改为连接真实方法，Qt 自动使用 QueuedConnection，UI 回调回到主线程 |
| 图片无法显示 / 方向键崩溃 | `_ImageLoader` 和 `QThread` 改为实例变量强引用，防止被 GC |
| 移动后仍显示旧文件 | `execute_moves()` 返回 `moved_pair_ids`；`_on_move_done()` 调用 `session.remove_pairs()` 清除会话和 DB 标记 |
| 退出时 QThread 报错 | `_stop_threads()` 和 `stop_loading()` 改用 `findChildren(QThread)`，覆盖所有子线程 |
| 标记 DB/内存一致性 | `PhotoSession` 标记操作先写 DB、成功后写内存 |
| 侧栏布局 | 宽度 280–420px；文件夹键改为纵向列表，行高 26px，显示文件夹名 + 已标记张数 |
| 底栏高度 | 固定 24px 单行高度 |
| 底栏文件名 | 显示格式：`N / total  IMG_xxxx.JPG  ·  标记状态` |
| 快捷键焦点保护 | 所有 QShortcut 设为 `WindowShortcut` context，对话框激活时自动屏蔽 |
| 多文件夹 UX | 菜单拆为"打开文件夹…"（替换）和"添加文件夹…"（追加），不再弹 Yes/No 循环 |
| 快捷键面板同步 | 新建 `app/ui/shortcuts.py` 作为唯一定义源，`ShortcutsPanel` 和注释均从此读取 |
| StatsPanel 文件夹名 | 统一调用 `_folder_name()`，消除内联 `split("/")` |
| 缩放与平移 | 用 `QGraphicsView` + `QGraphicsScene` 替换 QLabel，支持滚轮缩放、拖拽平移、双击还原 |
| 标记角标 | 用 `QLabel` 贴在 `viewport()` 上替代 `QGraphicsSimpleTextItem`，任意缩放级别下保持可读 |
| 测试基础设施 | `conftest.py` 改为合成 fixture，34 个测试全部通过 |

---

## P1 — 体验改善

### 1. 移动进度可取消

**现状**：进度对话框无取消按钮，卡在网络盘或权限错误时只能强杀进程。

**方案**：
- `QProgressDialog` 加取消按钮，连接到 `_MoveWorker` 的 `_cancelled` 标志
- `execute_moves()` 签名加 `should_cancel: Callable[[], bool] | None = None`，每移动一个 pair 检查一次

**文件**：`app/ui/main_window.py:_move_photos()`、`app/services/move_service.py`

---

### 2. MoveConfirmDialog 汉化

**现状**：`app/ui/dialogs.py` 中的标题、提示文字、按钮仍是英文（`"Move photos"`、`"Browse…"`、`"Missing folder"` 等），与其他界面不一致。

**文件**：`app/ui/dialogs.py` 约第 88–130 行。

---

### 3. 移动文件名冲突

**现状**：`_move_file()` 遇到重名时追加 `_1`、`_2` 后缀，极端场景下存在覆盖风险。

**方案**：改用时间戳短后缀；或拒绝冲突并写入 `result.errors`，由用户手动处理。

**文件**：`app/services/move_service.py:_move_file()`

---

## P2 — 代码质量

### 4. EXIF 线程积累

**现状**：`_load_exif_async()` 快速翻页时 `wait(50)` 不足以结束旧线程，旧线程靠 `_last_exif_pair_id` 丢弃过期结果，但 QThread 对象会短暂积累。

**方案**：改用 `QThreadPool` + `QRunnable`，避免每次创建/销毁线程的开销。

**文件**：`app/ui/main_window.py:_load_exif_async()`

---

### 5. 末尾导航无反馈

**现状**：到第一张或最后一张再按方向键，界面无任何反应（session 内部 clamp）。

**方案**：状态栏短暂显示"已到第一张"/"已到末尾"，或 wrap 到另一端（加设置项）。

---

## P3 — 长期功能

### 6. 日志持久化

**现状**：错误信息只打印到控制台，用户无法在 GUI 内查看历史。

**方案**：启动时添加 `FileHandler("~/.quickpic/quickpic.log")`；移动错误对话框加"查看日志"按钮。

---

### 7. Schema 迁移机制

**现状**：`init_db()` 是幂等的 `CREATE IF NOT EXISTS`，添加新字段时旧数据库会缺列崩溃。

**方案**：引入 `PRAGMA user_version` 版本号，启动时按版本号执行 `ALTER TABLE` 迁移脚本。

---

### 8. 更多快捷键

| 按键 | 功能 |
|------|------|
| `Home` / `End` | 跳到第一张 / 最后一张 |
| `F` | 全屏切换 |
| `Esc` | 关闭当前对话框 |

---

### 9. PyInstaller 打包验证

- `quick_pic.spec` 的 `target_arch=None` 在 Apple Silicon 上产出 arm64-only 二进制，无法在 Intel Mac 上运行。需确认分发目标后改为 `"universal2"` 或保持 arm64 并在 README 说明。
- rawpy 的 `.dylib` / `.dll` 依赖需在干净虚拟机上实测打包产物能否正常读取 RAW 文件。
