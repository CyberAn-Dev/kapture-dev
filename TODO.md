# TODO

## P0 截图界面（Capture）

- [ ] **标注画笔无法自由画线。**
  - **无法复现**：pen 的 press/move/release/绘制链路经 sendEvent 实测正常（含点真实
    工具栏按钮切 pen、大图 scale=0.328 缩放画布，均得到 15~28 个点的 polyline），
    代码层面无 bug，不敢盲改。
  - **待用户实机区分根因**：①只有 pen 不行，还是 rect/箭头/直线也不行？都不行→事件
    传递问题；只有 pen→疑为 3px 细线+无抗锯齿导致"画上了看不见"，改法是完全不同的
    一种（加 SmoothLine/加粗/平滑）。②拖动过程中有没有出现临时线条？

## 待办（Next）

- [ ] **截屏顶栏问题的逐项口头确认（低优先级）。** 用户已确认"现在修好了"；选区层
  bypass 改动在实机可用，但"顶栏/dock 完全盖住、框选与内容零错位、Esc 取消正常"
  尚未逐项确认，后续使用中留意即可。
- [ ] **常驻自启。** `~/.config/systemd/user/kapture.service`（跑 /opt/kapture，
  WantedBy=default.target）已起草未安装启用；当前验证实例是手起的
  `kapture.py --background`（借用 /opt venv），注销/重启后不会自启。

## 分发 / 持久化

- [ ] `/opt/kapture/kapture.py` 归上游 `.deb` 所有，同步修复会被未来的 kapture 包升级覆盖。
  重建 fork 的 `.deb` 仍是唯一的持久分发路径。

---

## 已完成（沉底）

- [x] **截屏时顶栏和下方应用栏弹出，挤占界面导致截图内容出错。** 根因：选区覆盖层是
  WM 托管的 `Qt.Tool`，被钳制到工作区（顶栏以下），与整屏冻结帧错位。改为
  `X11BypassWindowManagerHint`（与 ManualBar/RecordBar/WindowPicker 一致）；bypass
  窗口无 WM 键盘焦点，补 StrongFocus + grabKeyboard/releaseKeyboard 保住 Esc。
  用户实机确认可用。新增 3 项离屏测试（共 28 项）。
- [x] **Alt+\` 第三次失效（本轮）。** 两层原因：① 设置页"空值即注销"策略把显示空白
  的 region 从主数组摘除——已改为"空白保留并重新登记、仅 ✕ 注销"，且
  `gnome_current_key` 直接读子路径使被摘绑定仍显示；② 快捷键 command 指向 dev 仓库
  run.sh，而新签出仓库无 `.venv`（被 gitignore），GNOME 触发即 127——已建软链
  `.venv → /opt/kapture/.venv`。用户实机确认恢复。

- [x] **Alt+\` 全局截图失效。** 两层根因均已修复并经用户实机确认：
  ① `gnome_accelerator()` 写标点字面量而非 keysym 名（keysym=0 死绑定），已加
  标点→keysym 映射；② region 路径不在 `custom-keybindings` 主数组里，已恢复登记。
- [x] **钉到屏幕快捷键（PixPin 风格）。** Ctrl+1 钉系统剪贴板最新图、Ctrl+2 钉上一张
  （`QClipboard.dataChanged` 维护的内存历史，最新在前上限 10）；Esc 关闭钉图；默认值
  写进设置页并在首启自动注册。用户已实机确认可用。测试 23 项全绿。
- [x] **截图后不再自动弹出主界面。** 自动 OCR 改为静默加载编辑器（不弹窗口），
  仅"截图后打开编辑器"设置开启时才显示；左下角小窗与点击小图打开主界面不受影响。
  已部署 /opt 并重启验证。
- [x] **设置页已注册标点快捷键显示空白。** `gnome_key_sequence()` 缺 keysym 名→字面
  字符的反向映射，致 `<Alt>grave` 显示空白、保存时被误注销。已修复并加往返测试。
- [x] **托盘后台化（启动后隐藏主窗驻留）。** `start_hidden` 偏好 + `--background`
  启动可用，当前实例即以此方式运行。
- [x] **/opt 部署。** 实机验证方式已改为：直接运行仓库 kapture.py（解释器借用
  /opt/kapture/.venv，不写 root 文件、不需密码）；/opt/kapture/kapture.py 仍是
  9 月 24 日的旧版，等本批改动 commit 后再一次性同步。
