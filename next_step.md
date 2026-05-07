# QuickPic — 后续优化计划

## 已完成

| 项目 | 说明 |
|------|------|
| 扫描冻结 | worker 信号改为连接真实方法，Qt 自动使用 QueuedConnection，UI 回调回到主线程 |
| 图片无法显示 / 方向键崩溃 | `_ImageLoader` 和 `QThread` 改为实例变量强引用，防止被 GC |
| 移动后仍显示旧文件 | `execute_moves()` 返回 `moved_pair_ids`；`_on_move_done()` 调用 `session.remove_pairs()` 清除会话和 DB 标记 |
| 退出时 QThread 报错 | `_stop_threads()` 和 `stop_loading()` 改用 `findChildren(QThread)`，覆盖所有子线程包括被替换的旧 loader |
| 标记 DB/内存一致性 | `PhotoSession` 标记操作先写 DB、成功后写内存 |
| 侧栏布局 | 宽度 280–420px；文件夹键改为纵向列表，行高 26px，显示文件夹名 + 已标记张数 |
| 底栏高度 | 固定 24px 单行高度 |
| 底栏文件名 | 显示格式：`N / total  IMG_xxxx.JPG  ·  标记状态` |
| 测试基础设施 | `conftest.py` 改为合成文件 fixture，不依赖外部测试照片文件夹；34 个测试全部通过 |

---

## P0 — 影响核心工作流（建议尽快处理）

### 1. 标记后自动前进

**现状**：按 K / 数字键标记后停在当前照片，需手动按 → 翻到下一张。

**影响**：筛图效率低下，Lightroom / Photo Mechanic 均默认自动前进。

**方案**：
```python
# main_window.py _setup_shortcuts() 内
QShortcut(QKeySequence("K"), self).activated.connect(self._mark_and_advance_keep)

def _mark_and_advance_keep(self) -> None:
    self._mark_service.toggle_keep()
    if self._session.current and self._session.current.mark_type != MarkType.NONE:
        self._session.next()
```
取消标记（U / Del）**不**自动前进。可加设置项控制开关。

---

### 2. 快捷键误触焦点问题

**现状**：`M`、`1`–`9` 等单字符快捷键注册在主窗口层级，当对话框中的文本输入框获得焦点时仍会触发。例如在 MoveConfirmDialog 路径输入框里打"2020"会触发数字键 2 的标记。

**方案**：把所有 QShortcut 的 parent 改为 `self._viewer`（PhotoViewer widget），并设置：
```python
sc = QShortcut(QKeySequence("K"), self._viewer)
sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
```
这样焦点在对话框或文本输入时不触发。

---

## P1 — 体验改善

### 3. 多文件夹选择 UX

**现状**：每次选完一个文件夹弹一次"是否继续添加"确认框，选 3 个文件夹需操作 5 步。

**方案**：菜单拆成两个 action：
- **打开文件夹…**（替换当前会话）
- **添加文件夹…**（追加到当前会话）

---

### 4. 移动进度可取消

**现状**：进度对话框无取消按钮，卡在网络盘或权限错误时只能强杀进程。

**方案**：
- `QProgressDialog` 加取消按钮，连接到 `_MoveWorker` 的 `_cancelled` 标志
- `execute_moves()` 签名加 `should_cancel: Callable[[], bool] | None = None`，每移动一个 pair 检查一次

---

### 5. MoveConfirmDialog 汉化

**现状**：`app/ui/dialogs.py` 中 MoveConfirmDialog 的标题、提示文字、按钮仍是英文（`"Move photos"`、`"Browse…"`、`"Missing folder"` 等），与其他界面不一致。

**文件**：`app/ui/dialogs.py` 约第 88–130 行。

---

### 6. 移动文件名冲突

**现状**：`_move_file()` 遇到重名时追加 `_1`、`_2` 后缀。若目标已有 `IMG_001_1.jpg`，新文件 `IMG_001_1.jpg` 会继续递增，但存在极端竞态场景下的覆盖风险。

**方案**：改用 UUID 4位短后缀或时间戳后缀；或拒绝冲突并写入 `result.errors`。

**文件**：`app/services/move_service.py:_move_file()`

---

## P2 — 代码质量

### 7. 快捷键定义与面板同步

**现状**：`ShortcutsPanel` 中的快捷键说明是硬编码字符串，与 `_setup_shortcuts()` 无任何关联，改一处漏改另一处不会报错。本次已有过一次漂移（Ctrl+M → Ctrl+Shift+M）。

**方案**：新建 `app/ui/shortcuts.py`，定义 `SHORTCUTS: list[tuple[str, str, Callable]]`，`_setup_shortcuts()` 和 `ShortcutsPanel` 均从此读取。

---

### 8. StatsPanel 文件夹名截取内联

**现状**：`toolbar.py:StatsPanel` 内联了 `path.split("/")[-1]` 逻辑，与已有的 `_folder_name()` 重复。

**方案**：统一调用 `_folder_name(path)`。

**文件**：`app/ui/toolbar.py:115`

---

### 9. EXIF 线程积累

**现状**：`_load_exif_async()` 快速翻页时 `wait(50)` 不足以结束旧线程，旧线程继续运行到自然结束，靠 `_last_exif_pair_id` 丢弃过期结果。快速翻页时 QThread 对象会短暂积累。

**方案**：改用 `QThreadPool` + `QRunnable`，避免每次创建/销毁线程的开销。

**文件**：`app/ui/main_window.py:_load_exif_async()`

---

### 10. 末尾导航无反馈

**现状**：到第一张或最后一张再按方向键，界面无任何反应（session 内部 clamp）。

**方案**：状态栏短暂显示"已到第一张"/"已到末尾"，或 wrap 到另一端（加设置项）。

---

## P3 — 长期功能

### 11. 照片缩放与平移

当前 viewer 只做等比缩放填满区域，无法 1:1 查看细节。对 RAW 摄影是核心缺失。

**方案**：用 `QGraphicsView` + `QGraphicsScene` 替换 QLabel，实现鼠标滚轮缩放和拖拽平移。

---

### 12. 日志持久化

错误信息当前只打印到控制台或 debug.log，用户无法在 GUI 内查看。

**方案**：程序启动时 `logging.FileHandler("~/.quickpic/quickpic.log")`，移动错误对话框加"查看日志"按钮。

---

### 13. Schema 迁移机制

当前 `init_db()` 是幂等的 `CREATE IF NOT EXISTS`，添加新字段时旧数据库会缺列导致崩溃。

**方案**：引入 `PRAGMA user_version` 版本号，启动时按版本号执行 `ALTER TABLE` 迁移脚本。

---

### 14. 更多快捷键

| 按键 | 功能 |
|------|------|
| `Home` / `End` | 跳到第一张 / 最后一张 |
| `F` | 全屏切换 |
| `Esc` | 关闭当前对话框 |

---

### 15. PyInstaller 打包验证

- `quick_pic.spec` 的 `target_arch=None` 在 Apple Silicon 上产出 arm64-only 二进制，无法在 Intel Mac 上运行。需确认分发目标后改为 `"universal2"` 或保持 arm64 并在 README 说明。
- rawpy 的 `.dylib` / `.dll` 依赖需在干净虚拟机上实测打包产物能否正常读取 RAW 文件。
