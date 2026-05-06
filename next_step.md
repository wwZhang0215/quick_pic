# QuickPic 设计与代码优化分析

## Context

QuickPic 经过几轮迭代功能基本可用。本次审计在不引入新功能的前提下，
排查架构、并发、持久化、UX、国际化、打包六个维度的问题，并给出按优先级
排序的优化建议。整体结论：**架构分层守得很好，主要问题集中在 UX 工作流、
线程清理、I18N 不彻底和移动后状态残留**。

---

## 整体评价

**做得好的地方**
- `app/core` / `app/db` / `app/services` 全部无 Qt 依赖，CLAUDE.md 的核心约束严格遵守
- `repository.py` 是唯一 SQL 入口，没有任何外部模块直接写 SQL
- `PhotoViewer` 用 `_pending_pair_id` 检查防止过时图片覆盖新图片，思路正确
- 文件大小控制良好：所有文件都在 421 行以内（main_window.py 略超 400）
- WAL 模式 + 外键约束 + CHECK 约束已就绪

**主要问题**
- 工作流不顺手（标记后不自动前进、打开多文件夹要循环点 Yes/No）
- macOS 系统快捷键冲突（`Ctrl+M`/`M` 与最小化、文本输入冲突）
- 移动完成后标记和会话列表未清理，下次打开会显示已不存在的文件
- 关闭程序时 scan / move 线程未 join，可能造成数据损坏
- 国际化只做了一半，菜单和 MoveConfirmDialog 仍是英文
- 数据库无 schema 迁移机制，未来加字段会直接崩溃

---

## P0 — 必须修（阻塞用户体验或可能丢数据）

### 1. 标记后自动前进
**问题**：`MarkService.toggle_keep()` / `apply_folder_key()` 调用后停在当前照片，
违反摄影师筛图直觉（Lightroom / Photo Mechanic 都是自动前进）。

**位置**：`app/services/mark_service.py`、`app/ui/main_window.py:128-146`

**思路**：在 MainWindow 的快捷键 handler 中，标记成功后调用 `self._session.next()`。
取消标记（U / Del）不前进。可加一个设置项控制是否自动前进。

### 2. macOS 快捷键冲突
**问题**：
- `Ctrl+M` 在 Mac 是最小化，与"移动照片"冲突（main_window.py:124）
- 单字符 `M` 全局快捷键无 widget 焦点保护，QFileDialog 输入框打字会误触
  （main_window.py:146）
- 数字键 1-9 同样会被 MoveConfirmDialog 中的输入框误触
  （dialogs.py:102 输入"2020"会触发键 2）

**位置**：`app/ui/main_window.py:_setup_shortcuts()`

**思路**：
- 用 `QKeySequence.fromString("Ctrl+M")` 改为 `Cmd+Shift+M` 或独立菜单项
- 给所有 QShortcut 设 `setContext(Qt.WidgetWithChildrenShortcut)`，并把
  shortcut owner 改为 `self._viewer` 或主窗口的 central widget，使焦点在文本
  输入控件时不触发

### 3. 移动后状态未清理
**问题**：`_on_move_done()`（main_window.py:321-333）只弹结果对话框，
没有：
- 从 session 列表里移除已移动的 pair
- 从 DB 里删除对应 mark 记录
- 重置 PhotoSession 的 index

下次打开同一文件夹会显示已不存在的文件，viewer 报"Cannot display image"
但角标仍在，用户极度困惑。

**位置**：`app/ui/main_window.py:321-333`、`app/services/session.py`、
`app/services/move_service.py:execute_moves()`

**思路**：
- `execute_moves()` 返回成功移动的 `pair_id` 集合
- `_on_move_done()` 调用新方法 `session.remove_pairs(pair_ids)`，
  内部同时调 `repository.delete_mark()`
- 移动后 index 需要重新规整（停在原位置或下一个未移动的照片）

### 4. closeEvent 不 join 线程
**问题**：`closeEvent`（main_window.py:419-421）只调 `save_state()`，没等
`_scan_thread` / `_move_thread` / `_exif_thread` 退出。移动进行到一半关窗
可能损坏文件。

**位置**：`app/ui/main_window.py:closeEvent()`

**思路**：closeEvent 里依次 `quit()` + `wait(timeout)` 三个线程；
move_thread 还在跑时弹确认对话框（"还有 N 张正在移动，确定退出吗？"）。

### 5. 标记内存/DB 不原子
**问题**：`PhotoSession.mark_keep()`（session.py:91-98）先改内存 `pair.mark_type`，
再调 `repository.save_mark()`。后者抛异常时内存状态已脏。

**位置**：`app/services/session.py:91-116`

**思路**：调换顺序——先 save_mark，成功后再写内存。或者用 try/except 把
内存回滚到旧值。从用户视角看，"按 K 看到角标但重启没了"比"按 K 没角标"
更糟。

---

## P1 — 强烈建议修

### 6. 打开多文件夹的 Yes/No 循环
**问题**：main_window.py:174-193 — 每选一个文件夹后弹一次 Yes/No。
选 3 个文件夹要 3 次 picker + 2 次确认。

**思路**：菜单里改成两个 action：
- "打开文件夹..." — 单选，替换当前会话
- "添加文件夹..." — 单选，追加到当前会话
列表显示在侧栏顶部，可逐项删除。

### 7. 移动进度对话框不可取消
**问题**：main_window.py:307 `QProgressDialog(..., None, ...)` 第二个参数
传 None = 没有取消按钮。卡在网络盘或权限错误时只能强杀。

**位置**：`app/ui/main_window.py:_move_photos()`、
`app/services/move_service.py:execute_moves()`

**思路**：
- 进度对话框带"取消"按钮，连到 `_MoveWorker` 的中断标志
- `execute_moves()` 接受 `should_cancel: Callable[[], bool]`，每移动一个
  pair 检查一次

### 8. I18N 残留
**位置和清单**：
- main_window.py:69 `setWindowTitle("QuickPic")` — 保留（产品名）
- main_window.py:122-126 File 菜单："Open Folder(s)…", "Move Marked Photos…", "Quit"
- main_window.py:163 `"Restore session"` 对话框
- dialogs.py:91 `"Move photos"` 标题
- dialogs.py:101 `"Photos marked KEEP have no folder assigned…"`
- dialogs.py:103 `"Browse…"` / dialogs.py:119 `"Select keep folder"`
- dialogs.py:127 `"Missing folder"` 警告
- main_window.py:215 `"No photos found in selected folder(s)."`
- main_window.py:235 `"Key [X] not bound"` 系列
- main_window.py:280 `"Nothing to move"`
- main_window.py:330 `"Move complete (with errors)"`

**思路**：要么全英文要么全中文。当前侧栏、toolbar、ShortcutsPanel 已是中文，
建议菜单和 dialogs 也统一成中文。

### 9. 文件夹名缩短逻辑重复
**位置**：
- `app/ui/toolbar.py:_folder_name()`（已抽出）
- `app/ui/toolbar.py:115` StatsPanel 内联用 `path.split("/")[-1] or path.split("\\")[-1]`
- toolbar.py:198-199 截 18 字符
- toolbar.py:213-214 截 24 字符（同一个组件内长度不一致）

**思路**：统一用 `_folder_name()`，并把"显示名 + 截断"封装成一个
`display_label(path, max_len)` 工具函数。

### 10. 移动文件防重名 corner case
**位置**：`app/services/move_service.py:_move_file()` 行 117-120

**问题**：`IMG_001_1.jpg` 已存在的情况下，两次冲突可能互相覆盖。

**思路**：用 UUID 短后缀或时间戳后缀替代 `_1/_2`，或在生成新名前先 glob
冲突空间。或更简单：直接拒绝并把这条记入 errors，让用户手动处理。

---

## P2 — 建议修（体验改善）

### 11. 末尾导航无反馈
**问题**：到最后一张再按 → 没动静（session.py:75-79 的 clamp）。

**思路**：到边界时在状态栏闪一下"已到末尾"，或简单 wrap 到第一张
（加配置项）。

### 12. EXIF / 移动错误的可见性
- EXIF 读取失败时 ExifPanel 显示 "—"，用户不知道是真没数据还是读失败
- `result.errors[:10]` 只显示前 10 条，没有日志路径
- 建议：把 logger 输出落到 `~/.quickpic/quickpic.log`，错误对话框带
  "查看完整日志"按钮

### 13. ShortcutsPanel 与实际 shortcut 漂移
**问题**：toolbar.py:246-255 的快捷键列表是硬编码字符串，和
`_setup_shortcuts()` 里的注册值无任何关联。改一处忘改另一处时不会报错。

**思路**：把快捷键定义集中在 `app/ui/shortcuts.py`，提供
`SHORTCUTS: list[tuple[QKeySequence, str, Callable]]`，
`_setup_shortcuts()` 和 `ShortcutsPanel` 都从这里读。

### 14. 移除冗余 import
- `app/core/exif_reader.py:4` `dataclasses.field` 未使用
- `app/services/move_service.py:19` `errors: list[str] = None  # type: ignore` 用
  `__post_init__` 绕过 dataclass 限制。改为 `field(default_factory=list)` 更
  Pythonic（注意：因为这里仍用 list[str]，需要 `from dataclasses import field`）

### 15. 类型注解补全
- `app/core/exif_reader.py:140-156` 三个 `_str/_ratio_*/_format_shutter` helper
  缺类型注解
- 可加 `mypy --strict` CI 后续逐步补齐

### 16. EXIF 线程的 wait(50) 弱保护
**位置**：`app/ui/main_window.py:_load_exif_async()` 行 391-408

**问题**：50ms 不够长时旧线程还在跑，靠 `_last_exif_pair_id` 兜底虽然有效，
但残留 QThread 对象等到自然结束才被 deleteLater 回收，快速翻页时积累。

**思路**：换成 QThreadPool + QRunnable 避免每次创建/销毁线程；或者把 EXIF
读取改成在 Scanner 一次性预读完缓存到 PhotoPair 上（适合中等数量照片，
占内存换响应）。

---

## P3 — 锦上添花

### 17. 缺常用快捷键
- Home / End → 跳到第一张 / 最后一张
- F11 → 全屏
- Esc → 关闭对话框 / 取消移动
- + / - → 缩放（需配套 zoom/pan 实现）

### 18. 缩放和平移
当前 viewer.py 只有 KeepAspectRatio 缩放到 label，无法 1:1 看细节。
对 RAW 摄影来说是硬伤。`QGraphicsView` + `QGraphicsScene` 可以低成本实现
鼠标滚轮缩放和拖拽平移。

### 19. Schema 迁移
当前 `init_db()` 是 idempotent 的 CREATE IF NOT EXISTS。加字段时旧数据库
会缺列。建议引入 `pragma user_version` + 迁移脚本表，或干脆每次启动前比对
schema 并打印警告。

### 20. 同步 EXIF 扫描的性能
5000 张照片 + RAW 时单线程读 EXIF 可能要分钟级。
**当前不需立刻修**，但若用户反馈慢，可改为：
- ThreadPoolExecutor 并发读 EXIF（受 IO bound 限制，4-8 worker 即可）
- 或者把 EXIF 读取从 scan 阶段挪到首次显示时按需加载（lazy）

### 21. PyInstaller spec 与 README 不一致
**位置**：`quick_pic.spec:49` `target_arch=None` vs `README.md` 说
`--target-architecture universal2`

**思路**：要么把 spec 改成 universal2，要么把 README 删掉对应说明。
Apple Silicon 用户跑当前 spec 会得到 arm64-only 二进制，分发给 Intel Mac
会无法运行。

### 22. rawpy 原生库
PyInstaller spec 没有显式收集 rawpy 的 `.dylib` / `.dll`。一般 PyInstaller
hook 能自动处理，但建议打包后实测一次（在干净的 Windows / macOS 虚拟机）。

---

## 验证方案

完成 P0 优化后的回归测试：
1. **快捷键**：在 Move 对话框输入框中打字"2020"，确认不触发数字键标记
2. **自动前进**：连按 K 三次，验证连续标记并显示 4 张照片
3. **移动后清理**：标记 5 张 → 移动 → 关闭并重开，session 不应包含已移动
   照片
4. **关闭中断**：开始大批量移动，关窗，验证弹出确认对话框
5. **macOS Ctrl+M**：在 Mac 上测试 Ctrl+M 是最小化还是触发移动
6. **多文件夹**：用新的"添加文件夹"action 加 3 个文件夹，全程不出现
   Yes/No 弹窗

P1+P2 完成后：
7. 用 Charles / 进程监视器观察关闭程序时无遗留 Python 子线程
8. `~/.quickpic/quickpic.log` 出现错误日志
9. macOS 暗色模式下文字可读，对比度通过 macOS 辅助功能检查器

---

## 关键修改文件清单

| 文件 | 涉及优化项 |
|------|-----------|
| `app/ui/main_window.py` | 1, 2, 3, 4, 6, 7, 8, 13, 17 |
| `app/ui/dialogs.py` | 7, 8 |
| `app/ui/toolbar.py` | 9, 13 |
| `app/ui/viewer.py` | 18 |
| `app/services/session.py` | 1, 3, 5 |
| `app/services/mark_service.py` | 1, 5 |
| `app/services/move_service.py` | 3, 7, 10 |
| `app/core/exif_reader.py` | 14, 15, 16 |
| `app/db/repository.py` | 19 |
| `quick_pic.spec` | 21, 22 |
