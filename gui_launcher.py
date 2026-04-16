"""
ARAM 海克斯助手 - GUI 启动器
独立 EXE 入口点，提供图形化界面与系统托盘支持
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
import os
import sys
import io
import time
import datetime
import math
import traceback

# ============ 路径初始化 (兼容 PyInstaller 打包) ============

def get_base_dir():
    """获取应用根目录 (兼容打包与源码运行)"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

# ============ 延迟导入 (需要 path 已设置) ============

import keyboard
from PIL import Image, ImageDraw
import pystray


# ================= 日志重定向 =================

class LogRedirector(io.TextIOBase):
    """将 stdout/stderr 重定向到 Queue, 供 GUI 日志面板使用"""

    def __init__(self, log_queue, original_stream=None):
        super().__init__()
        self.log_queue = log_queue
        self.original = original_stream

    def write(self, text):
        if text and text.strip():
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.log_queue.put(f"[{ts}] {text.rstrip()}")
        if self.original:
            try:
                self.original.write(text)
                self.original.flush()
            except Exception:
                pass
        return len(text) if text else 0

    def flush(self):
        if self.original:
            try:
                self.original.flush()
            except Exception:
                pass


# ================= 后台控制器 (替代 InputController) =================

class GUIController(threading.Thread):
    """后台引擎: LCU 自动检测 + F6/F7 热键监听"""

    def __init__(self, overlay_queue, gui_queue, data_manager, analyzer, lcu_connector):
        super().__init__(daemon=True)
        self.overlay_queue = overlay_queue
        self.gui_queue = gui_queue
        self.dm = data_manager
        self.analyzer = analyzer
        self.lcu = lcu_connector
        self.current_hero = None
        self.running = True
        self._last_f6 = 0
        self._last_f7 = 0
        self._last_f8 = 0

    def run(self):
        """主循环: 自动检测 → 监听"""
        while self.running:
            self._auto_detect_phase()
            self._listening_phase()

    def stop(self):
        self.running = False

    def _gui(self, **kwargs):
        """发送消息到 GUI"""
        self.gui_queue.put(kwargs)

    def _validate_hero(self, name):
        from thefuzz import process
        if name in self.dm.hero_data:
            return name
        result = process.extractOne(name, list(self.dm.hero_data.keys()))
        if result and result[1] > 80:
            return result[0]
        return None

    def _try_auto_detect(self):
        if not self.lcu:
            return None, ""
        hero, source = self.lcu.get_champion_auto()
        if hero:
            validated = self._validate_hero(hero)
            if validated:
                return validated, source
        return None, source

    # ---------- 阶段1: 自动检测英雄 ----------

    def _auto_detect_phase(self):
        if not self.running:
            return
        self._gui(event="status", status="connecting")
        print("正在连接英雄联盟客户端...")

        for attempt in range(15):  # 30秒轮询
            if not self.running:
                return

            hero, source = self._try_auto_detect()
            if hero:
                self.current_hero = hero
                print(f"✅ 自动识别到英雄: [{hero}] (来源: {source})")
                self._gui(event="hero_found", hero=hero, source=source)
                self.overlay_queue.put({"cmd": "STATUS", "data": f"当前: {hero}\n按 F6 分析"})
                return

            # F8 中断自动检测
            if keyboard.is_pressed('f8'):
                break

            self._gui(event="status", status="waiting", attempt=attempt)
            time.sleep(2)

        # 超时未检测到
        print("暂未检测到英雄，进入后台监听模式")
        self._gui(event="status", status="idle")
        self.overlay_queue.put({"cmd": "STATUS", "data": "暂无英雄\n按 F7 自动获取"})

    # ---------- 阶段2: 热键监听 ----------

    def _listening_phase(self):
        if not self.running:
            return
        self._gui(event="status", status="listening", hero=self.current_hero)
        print(f"热键监听中... 当前英雄: {self.current_hero or '未指定'}")

        while self.running:
            now = time.time()

            # F6 - 分析海克斯
            if keyboard.is_pressed('f6') and now - self._last_f6 > 1.0:
                self._last_f6 = now
                if not self.current_hero:
                    self.overlay_queue.put({"cmd": "STATUS", "data": "⚠ 尚未锁定英雄\n请按 F7 获取"})
                    self._gui(event="status", status="no_hero_warning")
                else:
                    self._gui(event="status", status="analyzing", hero=self.current_hero)
                    self.overlay_queue.put({"cmd": "STATUS", "data": f"🔎 分析 [{self.current_hero}]..."})
                    print(f"正在分析: {self.current_hero}...")
                    results = self.analyzer.analyze(self.current_hero)
                    self.overlay_queue.put({"cmd": "UPDATE", "data": results})
                    self._gui(event="status", status="analyzed", hero=self.current_hero)
                    print(f"分析完成: {self.current_hero}")

            # F7 - 刷新英雄
            if keyboard.is_pressed('f7') and now - self._last_f7 > 1.0:
                self._last_f7 = now
                self._gui(event="status", status="refreshing")
                self.overlay_queue.put({"cmd": "STATUS", "data": "刷新英雄..."})
                hero, source = self._try_auto_detect()
                if hero and hero != self.current_hero:
                    old = self.current_hero
                    self.current_hero = hero
                    print(f"英雄已切换 ({source}): {old} → {hero}")
                    self._gui(event="hero_found", hero=hero, source=source)
                    self.overlay_queue.put({"cmd": "STATUS", "data": f"已切换: {hero}\n按 F6 分析"})
                elif hero:
                    self._gui(event="hero_confirmed", hero=hero)
                    self.overlay_queue.put({"cmd": "STATUS", "data": f"当前: {hero}\n按 F6 分析"})
                else:
                    self.overlay_queue.put({"cmd": "STATUS", "data": f"当前: {self.current_hero or '未知'}\n按 F6 分析"})

            # F8 - 重新进入自动检测
            if keyboard.is_pressed('f8') and now - self._last_f8 > 1.0:
                self._last_f8 = now
                print("F8: 重新进入自动检测阶段")
                self._gui(event="status", status="resetting")
                self.current_hero = None
                time.sleep(0.5)
                return  # 退出 listening_phase, 回到 auto_detect

            time.sleep(0.05)


# ================= 系统托盘管理 =================

class TrayManager:
    """系统托盘图标管理"""

    def __init__(self, app):
        self.app = app
        self.icon = None
        self._thread = None

    def _create_tray_image(self):
        """程序化创建托盘图标 (蓝色六边形)"""
        size = 64
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cx, cy = size // 2, size // 2
        r = size // 2 - 4
        points = []
        for i in range(6):
            angle = math.radians(60 * i - 30)
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        draw.polygon(points, fill=(13, 17, 23, 255), outline=(88, 166, 255, 255))
        # 内部小六边形
        r2 = r * 0.55
        inner = []
        for i in range(6):
            angle = math.radians(60 * i - 30)
            inner.append((cx + r2 * math.cos(angle), cy + r2 * math.sin(angle)))
        draw.polygon(inner, fill=(88, 166, 255, 200))
        return img

    def start(self):
        """启动托盘图标 (后台线程)"""
        image = self._create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", self._on_show),
            pystray.MenuItem("退出程序", self._on_quit),
        )
        self.icon = pystray.Icon("ARAM助手", image, "ARAM 海克斯助手", menu)
        self._thread = threading.Thread(target=self.icon.run, daemon=True)
        self._thread.start()

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass

    def notify(self, title, message):
        """托盘气泡通知"""
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    def _on_show(self, icon=None, item=None):
        self.app.gui_queue.put({"event": "tray_show"})

    def _on_quit(self, icon=None, item=None):
        self.app.gui_queue.put({"event": "tray_quit"})


# ================= 主 GUI 应用 =================

class LauncherApp:
    """ARAM 海克斯助手 - 主界面"""

    # 配色方案 (GitHub Dark Theme)
    BG          = "#0d1117"
    BG_CARD     = "#161b22"
    BG_INPUT    = "#0d1117"
    ACCENT      = "#58a6ff"
    ACCENT_HVR  = "#79c0ff"
    SUCCESS     = "#3fb950"
    WARNING     = "#d29922"
    ERROR       = "#f85149"
    TEXT        = "#e6edf3"
    TEXT_DIM    = "#8b949e"
    BORDER      = "#30363d"

    FONT_TITLE  = ("Microsoft YaHei", 18, "bold")
    FONT_SUB    = ("Microsoft YaHei", 10)
    FONT_HERO   = ("Microsoft YaHei", 22, "bold")
    FONT_STATUS = ("Microsoft YaHei", 11)
    FONT_BTN    = ("Microsoft YaHei", 11, "bold")
    FONT_LOG    = ("Consolas", 9)

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ARAM 海克斯助手")
        self.root.geometry("540x660")
        self.root.minsize(500, 600)
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 设置窗口图标
        icon_path = os.path.join(BASE_DIR, 'assets', 'icon.ico')
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)

        # ttk 主题
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self._configure_styles()

        # 状态变量
        self.engine_running = False
        self.controller = None
        self.overlay = None
        self.overlay_window = None
        self.dm = None
        self.analyzer = None
        self.lcu = None
        self.tray = TrayManager(self)

        # 通信队列
        self.overlay_queue = queue.Queue()
        self.gui_queue = queue.Queue()
        self.log_queue = queue.Queue()

        # UI 变量
        self.hero_var = tk.StringVar(value="—")
        self.status_var = tk.StringVar(value="等待启动")
        self.status_color = self.TEXT_DIM
        self._pulse_state = 0

        # 重定向日志
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = LogRedirector(self.log_queue, self._orig_stdout)
        sys.stderr = LogRedirector(self.log_queue, self._orig_stderr)

        # 构建 UI
        self._build_ui()

        # 启动队列轮询
        self.root.after(100, self._poll_queues)

        # 启动时加载数据
        self.root.after(300, self._load_data)

    # ==========================================
    # ttk 样式配置
    # ==========================================

    def _configure_styles(self):
        s = self.style

        # 主按钮 (蓝色)
        s.configure('Accent.TButton',
                     background=self.ACCENT,
                     foreground='white',
                     font=self.FONT_BTN,
                     padding=(16, 10),
                     borderwidth=0)
        s.map('Accent.TButton',
              background=[('active', self.ACCENT_HVR), ('disabled', self.BORDER)])

        # 次要按钮 (深灰)
        s.configure('Secondary.TButton',
                     background=self.BG_CARD,
                     foreground=self.TEXT,
                     font=self.FONT_BTN,
                     padding=(12, 8),
                     borderwidth=1)
        s.map('Secondary.TButton',
              background=[('active', self.BORDER), ('disabled', '#0d1117')])

        # 停止按钮 (红色)
        s.configure('Danger.TButton',
                     background=self.ERROR,
                     foreground='white',
                     font=self.FONT_BTN,
                     padding=(16, 10),
                     borderwidth=0)
        s.map('Danger.TButton',
              background=[('active', '#da3633')])

        # 链接按钮 (无背景)
        s.configure('Link.TButton',
                     background=self.BG,
                     foreground=self.TEXT_DIM,
                     font=self.FONT_SUB,
                     padding=(8, 4),
                     borderwidth=0)
        s.map('Link.TButton',
              foreground=[('active', self.ACCENT)],
              background=[('active', self.BG)])

    # ==========================================
    # 构建 UI
    # ==========================================

    def _build_ui(self):
        main = tk.Frame(self.root, bg=self.BG, padx=24, pady=16)
        main.pack(fill=tk.BOTH, expand=True)

        # ---- Header ----
        hdr = tk.Frame(main, bg=self.BG)
        hdr.pack(fill=tk.X, pady=(0, 16))

        # 标志六边形 (文字模拟)
        tk.Label(hdr, text="⬡", font=("Segoe UI", 28), fg=self.ACCENT,
                 bg=self.BG).pack(side=tk.LEFT, padx=(0, 12))

        title_frame = tk.Frame(hdr, bg=self.BG)
        title_frame.pack(side=tk.LEFT)
        tk.Label(title_frame, text="ARAM 海克斯助手",
                 font=self.FONT_TITLE, fg=self.TEXT, bg=self.BG).pack(anchor="w")
        tk.Label(title_frame, text="大乱斗海克斯推荐 · OCR 识别 · 自动选取",
                 font=self.FONT_SUB, fg=self.TEXT_DIM, bg=self.BG).pack(anchor="w")

        # ---- 分隔线 ----
        tk.Frame(main, bg=self.BORDER, height=1).pack(fill=tk.X, pady=(0, 16))

        # ---- 状态卡片 ----
        card = tk.Frame(main, bg=self.BG_CARD, padx=20, pady=16,
                        highlightbackground=self.BORDER, highlightthickness=1)
        card.pack(fill=tk.X, pady=(0, 16))

        # 英雄行
        hero_row = tk.Frame(card, bg=self.BG_CARD)
        hero_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(hero_row, text="当前英雄", font=self.FONT_SUB,
                 fg=self.TEXT_DIM, bg=self.BG_CARD).pack(side=tk.LEFT)
        self.hero_label = tk.Label(hero_row, textvariable=self.hero_var,
                                   font=self.FONT_HERO, fg=self.ACCENT, bg=self.BG_CARD)
        self.hero_label.pack(side=tk.RIGHT)

        # 状态行
        status_row = tk.Frame(card, bg=self.BG_CARD)
        status_row.pack(fill=tk.X)
        tk.Label(status_row, text="运行状态", font=self.FONT_SUB,
                 fg=self.TEXT_DIM, bg=self.BG_CARD).pack(side=tk.LEFT)
        self.status_dot = tk.Label(status_row, text="●", font=("Segoe UI", 10),
                                   fg=self.TEXT_DIM, bg=self.BG_CARD)
        self.status_dot.pack(side=tk.RIGHT, padx=(0, 6))
        self.status_label = tk.Label(status_row, textvariable=self.status_var,
                                     font=self.FONT_STATUS, fg=self.TEXT_DIM,
                                     bg=self.BG_CARD)
        self.status_label.pack(side=tk.RIGHT)

        # ---- 热键提示 ----
        hotkey_frame = tk.Frame(main, bg=self.BG)
        hotkey_frame.pack(fill=tk.X, pady=(0, 12))
        hotkeys = [("F6", "分析海克斯"), ("F7", "识别英雄"), ("F8", "重置")]
        for key, desc in hotkeys:
            pill = tk.Frame(hotkey_frame, bg=self.BORDER, padx=1, pady=1)
            pill.pack(side=tk.LEFT, padx=(0, 10))
            inner = tk.Frame(pill, bg=self.BG_CARD, padx=8, pady=3)
            inner.pack()
            tk.Label(inner, text=key, font=("Consolas", 9, "bold"),
                     fg=self.ACCENT, bg=self.BG_CARD).pack(side=tk.LEFT, padx=(0, 4))
            tk.Label(inner, text=desc, font=("Microsoft YaHei", 9),
                     fg=self.TEXT_DIM, bg=self.BG_CARD).pack(side=tk.LEFT)

        # ---- 按钮区域 ----
        btn_frame = tk.Frame(main, bg=self.BG)
        btn_frame.pack(fill=tk.X, pady=(0, 12))

        # 开始/停止按钮
        self.start_btn = ttk.Button(btn_frame, text="▶  开始识别",
                                     style='Accent.TButton', command=self._start_engine)
        self.start_btn.pack(fill=tk.X, pady=(0, 8))

        self.stop_btn = ttk.Button(btn_frame, text="■  停止运行",
                                    style='Danger.TButton', command=self._stop_engine)
        # 停止按钮初始隐藏

        # 更新按钮行
        update_row = tk.Frame(btn_frame, bg=self.BG)
        update_row.pack(fill=tk.X, pady=(0, 8))
        update_row.columnconfigure(0, weight=1)
        update_row.columnconfigure(1, weight=1)

        self.crawl_btn = ttk.Button(update_row, text="🔄 爬虫更新",
                                     style='Secondary.TButton', command=self._update_crawler)
        self.crawl_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.dl_btn = ttk.Button(update_row, text="📥 在线下载",
                                  style='Secondary.TButton', command=self._download_github)
        self.dl_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # 托盘按钮
        self.tray_btn = ttk.Button(btn_frame, text="最小化到系统托盘",
                                    style='Link.TButton', command=self._minimize_to_tray)
        self.tray_btn.pack()

        # ---- 日志面板 ----
        log_header = tk.Frame(main, bg=self.BG)
        log_header.pack(fill=tk.X, pady=(4, 4))
        tk.Label(log_header, text="运行日志", font=self.FONT_SUB,
                 fg=self.TEXT_DIM, bg=self.BG).pack(side=tk.LEFT)

        self.log_text = scrolledtext.ScrolledText(
            main, font=self.FONT_LOG, bg=self.BG_INPUT, fg=self.TEXT_DIM,
            insertbackground=self.TEXT_DIM, selectbackground=self.ACCENT,
            relief=tk.FLAT, borderwidth=0, height=12, wrap=tk.WORD, state=tk.DISABLED,
            highlightbackground=self.BORDER, highlightthickness=1
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 日志颜色标签
        self.log_text.tag_configure("success", foreground=self.SUCCESS)
        self.log_text.tag_configure("error", foreground=self.ERROR)
        self.log_text.tag_configure("warning", foreground=self.WARNING)
        self.log_text.tag_configure("info", foreground=self.TEXT_DIM)

    # ==========================================
    # 数据加载
    # ==========================================

    def _load_data(self):
        """后台加载数据"""
        def _load():
            try:
                from main import DataManager
                self.dm = DataManager()
                if self.dm.hero_data:
                    self._log(f"✅ 数据加载完毕: {len(self.dm.hero_data)} 个英雄")
                    self.gui_queue.put({"event": "data_loaded"})
                else:
                    self._log("❌ 未加载到英雄数据，请检查 data/ 目录")
                    self.gui_queue.put({"event": "data_error"})
            except Exception as e:
                self._log(f"❌ 数据加载失败: {e}")
                self.gui_queue.put({"event": "data_error"})

        self._log("正在加载数据资源...")
        threading.Thread(target=_load, daemon=True).start()

    # ==========================================
    # 引擎控制
    # ==========================================

    def _start_engine(self):
        """启动识别引擎"""
        if self.engine_running:
            return
        if not self.dm or not self.dm.hero_data:
            messagebox.showwarning("提示", "数据尚未加载完成，请稍候")
            return

        self.start_btn.pack_forget()
        self.stop_btn.pack(fill=tk.X, pady=(0, 8))
        self.start_btn.config(state=tk.DISABLED)
        self._set_status("启动中...", self.WARNING)
        self._log("正在初始化 OCR 引擎...")

        def _init():
            try:
                from main import GameAnalyzer, OverlayApp
                from scripts.lcu_connector import LCUConnector

                # 初始化分析器 (加载 OCR 模型)
                self.analyzer = GameAnalyzer(self.dm)
                self._log("✅ OCR 引擎就绪")

                # 初始化 LCU 连接器
                champions_json = os.path.join(self.dm.data_dir, 'champions.json')
                self.lcu = LCUConnector(champions_json)
                self._log("✅ LCU 连接器就绪")

                # 在主线程创建 overlay
                self.gui_queue.put({"event": "create_overlay"})

            except Exception as e:
                self._log(f"❌ 引擎启动失败: {e}")
                traceback.print_exc()
                self.gui_queue.put({"event": "engine_error"})

        threading.Thread(target=_init, daemon=True).start()

    def _create_overlay_and_start(self):
        """在主线程中创建 overlay 窗口并启动控制器"""
        try:
            from main import OverlayApp

            # 创建 overlay 作为 Toplevel
            self.overlay_window = tk.Toplevel(self.root)
            self.overlay = OverlayApp(self.overlay_window, self.overlay_queue)

            # 启动后台控制器
            self.controller = GUIController(
                self.overlay_queue, self.gui_queue,
                self.dm, self.analyzer, self.lcu
            )
            self.controller.start()

            self.engine_running = True
            self._set_status("运行中", self.SUCCESS)
            self._log("✅ 引擎已启动! F6=分析 | F7=识别 | F8=重置")
            self._start_pulse()

            # 启动托盘
            self.tray.start()

        except Exception as e:
            self._log(f"❌ Overlay 创建失败: {e}")
            traceback.print_exc()
            self._engine_cleanup()
            self.stop_btn.pack_forget()
            self.start_btn.pack(fill=tk.X, pady=(0, 8))
            self.start_btn.config(state=tk.NORMAL)

    def _stop_engine(self):
        """停止识别引擎"""
        self._log("正在停止引擎...")
        self._engine_cleanup()
        self.stop_btn.pack_forget()
        self.start_btn.pack(fill=tk.X, pady=(0, 8))
        self.start_btn.config(state=tk.NORMAL)
        self._set_status("已停止", self.TEXT_DIM)
        self.hero_var.set("—")
        self._log("引擎已停止")

    def _engine_cleanup(self):
        """清理引擎资源"""
        self.engine_running = False
        if self.controller:
            self.controller.stop()
            self.controller = None
        if self.overlay_window:
            try:
                self.overlay_window.destroy()
            except Exception:
                pass
            self.overlay_window = None
            self.overlay = None
        self.tray.stop()

    # ==========================================
    # 数据更新
    # ==========================================

    def _update_crawler(self):
        """使用爬虫更新数据"""
        if not messagebox.askyesno("爬虫更新",
                "爬虫更新需要安装 Chrome 浏览器。\n"
                "更新过程可能需要数分钟，期间请勿关闭程序。\n\n"
                "确定要开始吗？"):
            return

        self.crawl_btn.config(state=tk.DISABLED)
        self.dl_btn.config(state=tk.DISABLED)
        self._log("🔄 开始爬虫更新...")

        def _run():
            try:
                from scripts.updater import run_update
                success = run_update(mode='spot_check', log_func=self._log_safe)
                if success:
                    self._log("✅ 爬虫更新完成!")
                    # 重新加载数据
                    self.gui_queue.put({"event": "reload_data"})
                else:
                    self._log("⚠ 更新完成 (部分失败)")
            except Exception as e:
                self._log(f"❌ 爬虫更新失败: {e}")
                traceback.print_exc()
            finally:
                self.gui_queue.put({"event": "update_done"})

        threading.Thread(target=_run, daemon=True).start()

    def _download_github(self):
        """从 GitHub 下载最新数据"""
        self.crawl_btn.config(state=tk.DISABLED)
        self.dl_btn.config(state=tk.DISABLED)
        self._log("📥 正在从 GitHub 下载最新数据...")

        def _run():
            try:
                from scripts.updater import download_from_github
                success = download_from_github(log_func=self._log_safe)
                if success:
                    self._log("✅ 数据下载完成!")
                    self.gui_queue.put({"event": "reload_data"})
                else:
                    self._log("❌ 下载失败")
            except Exception as e:
                self._log(f"❌ 下载失败: {e}")
                traceback.print_exc()
            finally:
                self.gui_queue.put({"event": "update_done"})

        threading.Thread(target=_run, daemon=True).start()

    # ==========================================
    # 系统托盘
    # ==========================================

    def _minimize_to_tray(self):
        """最小化到系统托盘"""
        if not self.engine_running:
            messagebox.showinfo("提示", "请先点击「开始识别」再最小化到托盘")
            return
        self.root.withdraw()
        self.tray.notify("ARAM 海克斯助手", "程序已最小化到系统托盘，热键仍然有效")
        # 确保 overlay 仍然可见
        if self.overlay_window:
            self.root.after(100, self._ensure_overlay_visible)

    def _ensure_overlay_visible(self):
        """确保 overlay 在 root 隐藏后仍然可见"""
        if self.overlay_window:
            try:
                self.overlay_window.deiconify()
                self.overlay_window.attributes("-topmost", True)
            except Exception:
                pass

    def _restore_from_tray(self):
        """从托盘恢复窗口"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ==========================================
    # 队列消息处理
    # ==========================================

    def _poll_queues(self):
        """轮询所有消息队列"""
        # GUI 队列
        try:
            while True:
                msg = self.gui_queue.get_nowait()
                self._handle_gui_message(msg)
        except queue.Empty:
            pass

        # 日志队列
        try:
            while True:
                text = self.log_queue.get_nowait()
                self._append_log(text)
        except queue.Empty:
            pass

        self.root.after(80, self._poll_queues)

    def _handle_gui_message(self, msg):
        event = msg.get("event", "")

        if event == "data_loaded":
            self.start_btn.config(state=tk.NORMAL)

        elif event == "data_error":
            self.start_btn.config(state=tk.DISABLED)

        elif event == "create_overlay":
            self._create_overlay_and_start()

        elif event == "engine_error":
            self._stop_engine()

        elif event == "hero_found":
            hero = msg.get("hero", "")
            self.hero_var.set(hero)
            self._set_status("监听中", self.SUCCESS)
            self.tray.notify("英雄已识别", f"当前英雄: {hero}")

        elif event == "hero_confirmed":
            self.hero_var.set(msg.get("hero", ""))

        elif event == "status":
            status = msg.get("status", "")
            hero = msg.get("hero")
            if hero:
                self.hero_var.set(hero)
            status_map = {
                "connecting":       ("连接客户端...", self.WARNING),
                "waiting":          ("等待选取英雄...", self.WARNING),
                "listening":        ("监听中", self.SUCCESS),
                "analyzing":        ("分析中...", self.ACCENT),
                "analyzed":         ("分析完成", self.SUCCESS),
                "refreshing":       ("刷新英雄...", self.WARNING),
                "no_hero_warning":  ("未锁定英雄", self.ERROR),
                "idle":             ("运行中 (无英雄)", self.TEXT_DIM),
                "resetting":        ("重置中...", self.WARNING),
            }
            if status in status_map:
                text, color = status_map[status]
                self._set_status(text, color)

        elif event == "tray_show":
            self._restore_from_tray()

        elif event == "tray_quit":
            self._quit_app()

        elif event == "update_done":
            self.crawl_btn.config(state=tk.NORMAL)
            self.dl_btn.config(state=tk.NORMAL)

        elif event == "reload_data":
            self._log("重新加载数据...")
            self._load_data()

    # ==========================================
    # UI 辅助方法
    # ==========================================

    def _set_status(self, text, color):
        self.status_var.set(text)
        self.status_label.config(fg=color)
        self.status_dot.config(fg=color)
        self.status_color = color

    def _start_pulse(self):
        """启动状态指示灯脉冲动画"""
        def _pulse():
            if not self.engine_running:
                return
            self._pulse_state = (self._pulse_state + 1) % 20
            # 呼吸灯效果
            brightness = abs(self._pulse_state - 10) / 10.0
            if self.status_color == self.SUCCESS:
                r = int(63 + brightness * 30)
                g = int(185 + brightness * 50)
                b = int(80 + brightness * 30)
                self.status_dot.config(fg=f"#{r:02x}{g:02x}{b:02x}")
            self.root.after(100, _pulse)
        _pulse()

    def _log(self, msg):
        """线程安全的日志方法 (主线程调用)"""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._append_log(f"[{ts}] {msg}")

    def _log_safe(self, msg):
        """线程安全的日志方法 (后台线程调用)"""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{ts}] {msg}")

    def _append_log(self, text):
        """向日志面板追加文本"""
        self.log_text.config(state=tk.NORMAL)

        # 根据内容选择颜色
        tag = "info"
        if "✅" in text or "成功" in text:
            tag = "success"
        elif "❌" in text or "失败" in text or "错误" in text:
            tag = "error"
        elif "⚠" in text or "警告" in text:
            tag = "warning"

        self.log_text.insert(tk.END, text + "\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    # ==========================================
    # 窗口事件
    # ==========================================

    def _on_close(self):
        """点击关闭按钮"""
        if self.engine_running:
            if messagebox.askyesno("关闭确认",
                    "引擎正在运行中。\n\n"
                    "• 点击「是」关闭程序\n"
                    "• 点击「否」最小化到托盘"):
                self._quit_app()
            else:
                self._minimize_to_tray()
        else:
            self._quit_app()

    def _quit_app(self):
        """完全退出程序"""
        self._engine_cleanup()
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def run(self):
        self.root.mainloop()


# ================= 入口点 =================

def main():
    try:
        # 高 DPI 适配
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        app = LauncherApp()
        app.run()

    except Exception as e:
        try:
            messagebox.showerror("ARAM 海克斯助手 - 启动错误",
                                 f"程序启动时发生错误:\n\n{traceback.format_exc()}")
        except Exception:
            print(f"FATAL: {e}")
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
