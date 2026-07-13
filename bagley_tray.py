"""
bagley_tray.py
==================
ตัวเรียกใช้ bot.py แบบ "ไอคอนถาด" (System Tray) เหมือน mic_to_bagley.py เป๊ะๆ
รันบอท Bagley เป็นโปรเซสลูกอยู่เบื้องหลัง ไม่มีหน้าต่าง Terminal ค้างโชว์
ดูบันทึกกิจกรรมสดๆของบอทได้จากไอคอน สั่งหยุด/เริ่มบอทใหม่ได้โดยไม่ต้องปิด
โปรแกรมนี้ทิ้ง (ไม่ต้องปิดหน้าต่าง Terminal ของบอทเองอีกแล้ว)

⚠️ ไฟล์นี้ "ไม่ได้แก้ไข" bot.py เลยแม้แต่บรรทัดเดียว แค่เรียกมันขึ้นมาเป็น
โปรเซสลูก (subprocess) เหมือนดับเบิลคลิกรันเองเฉยๆ แต่คุมมันได้จากไอคอนถาด

วิธีติดตั้ง (ถ้ารันเป็น .py ธรรมดา ยังไม่ได้ build เป็น .exe):
    pip install pystray pillow
(ไม่ต้องลงไลบรารีของ bot.py เพิ่มที่นี่ เพราะบอทยังถูกรันด้วย python ตัวเดิม
ในเครื่องนี้ผ่าน subprocess เท่านั้น ไม่ได้ import เข้ามาในโปรเซสนี้)

📦 อยากได้เป็นไฟล์ .exe เดียวกดรันได้เลย?
    รัน build_tray_exe.bat ที่แนบมาด้วย จะได้ dist\\bagley_tray.exe
    ก็อปไปพร้อมกับ bot.py (และไฟล์ทุกอย่างที่ bot.py ต้องใช้ เช่น .env,
    ไฟล์เสียง .mp3, bagley_memory.db) ไว้ในโฟลเดอร์เดียวกันเสมอ

การใช้งาน:
    วางไฟล์นี้ไว้ใน "โฟลเดอร์เดียวกับ bot.py" เท่านั้น (สำคัญมาก) แล้วรัน
    จะเห็นไอคอนเล็กๆที่มุมขวาล่างจอ:
        - คลิกซ้าย/ดับเบิลคลิกที่ไอคอน -> เปิด/ปิดหน้าต่างดูบันทึกกิจกรรมสดๆ
        - คลิกขวาที่ไอคอน -> เมนู:
            "🎛️ ควบคุมบอท (เริ่ม/หยุด)"  -> เปิดหน้าต่างสวิตช์เริ่ม/หยุดบอท
            "ออกจากโปรแกรม"            -> ปิดโปรแกรมนี้ (จะหยุดบอทให้อัตโนมัติ
                                            ด้วย ไม่ทิ้งโปรเซสค้างอยู่เบื้องหลัง)
        (ถ้าไอคอนไม่โผล่มาให้เห็นในแถบเล็กๆ ให้ลากมันออกมาจากช่อง
         "ไอคอนที่ซ่อนอยู่" รูปลูกศร ^ ที่มุมขวาล่างของ Windows ก่อน)

⚠️ เรื่องสำคัญที่ต้องรู้เกี่ยวกับคำสั่ง /update_bot ในตัวบอท:
    ตอนนี้ /update_bot ยังใช้วิธีเดิม (เรียก start_hidden.bat แยกออกไปเอง)
    ซึ่งจะสร้างโปรเซสใหม่ที่ "ไม่ได้อยู่ภายใต้การควบคุมของ bagley_tray.py"
    ทำให้ไอคอนถาดหลุดการติดตามสถานะบอทไปหลังจากใช้ /update_bot แต่ละครั้ง
    (บอทจะยังทำงานอยู่ปกติ แค่ไอคอนถาดจะไม่รู้ว่ามันคือตัวเดียวกัน) ถ้าจะ
    ให้ /update_bot ทำงานเข้ากันกับตัวคุมนี้แบบสมบูรณ์ ต้องแก้ /update_bot
    ในบอทให้ปิดตัวเองไปเฉยๆแทน แล้วให้ bagley_tray.py เป็นคนสั่งเริ่มใหม่
    (มี watchdog ให้พร้อมอยู่แล้วในไฟล์นี้) บอกได้เลยถ้าต้องการให้แก้จุดนี้ด้วย
"""

import os
import sys
import socket
import subprocess
import threading
import time
from collections import deque

import pystray
from PIL import Image, ImageDraw

# 🔧 [แก้บั๊ก] Windows console/exe แบบ windowed มักใช้ codec cp1252 (อังกฤษ)
# เป็นค่าเริ่มต้น ซึ่งเข้ารหัสภาษาไทยไม่ได้ ทำให้ print() ข้อความไทย crash
# ทั้งโปรแกรมด้วย UnicodeEncodeError บังคับให้ stdout/stderr ใช้ UTF-8 เสมอ
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# 🔒 [กันรันซ้ำ] ถ้าเปิด bagley_tray.exe มากกว่า 1 ตัว จะเปิดไอคอนถาดซ้อนกัน
# หลายอัน แต่ละอันพยายามรัน bot.py ของตัวเอง ชนกันที่พอร์ต Voice Relay ทันที
# ใช้การ bind socket ที่พอร์ตนี้เป็น "กลอนล็อก" ถ้า bind ไม่ได้ แปลว่ามีตัวอื่น
# รันอยู่แล้ว จะเลิกเปิดตัวใหม่ทันที (ไม่ต้องพึ่งไลบรารีเสริมอะไรเพิ่ม)
_SINGLE_INSTANCE_LOCK_PORT = 58959
_lock_socket = None


def _acquire_single_instance_lock() -> bool:
    global _lock_socket
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _lock_socket.bind(("127.0.0.1", _SINGLE_INSTANCE_LOCK_PORT))
        _lock_socket.listen(1)
        return True
    except OSError:
        return False

BOT_SCRIPT_NAME = "bot.py"


def resource_path(relative_path: str) -> str:
    """หา path ของไฟล์แนบ (เช่น tray_icon.png) ทั้งตอนรันเป็น .py ธรรมดา
    และตอนถูก build เป็น .exe ไฟล์เดียวด้วย PyInstaller"""
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def get_app_dir() -> str:
    """โฟลเดอร์ที่ไฟล์นี้ (หรือ .exe) อยู่จริงๆ ต้องเป็นโฟลเดอร์เดียวกับ bot.py"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BOT_DIR = get_app_dir()
BOT_SCRIPT_PATH = os.path.join(BOT_DIR, BOT_SCRIPT_NAME)


# ==================== ระบบบันทึกกิจกรรม (เหมือน mic_to_bagley.py) ====================
_log_lines = deque(maxlen=500)
_log_lock = threading.Lock()

_tk_root = None
_tk_text_widget = None
_tk_ready_event = threading.Event()

_tray_icon_obj = None  # อ้างอิงถึง pystray.Icon ตัวจริง เพื่ออัปเดตสี/tooltip ทีหลังได้


def log(msg: str):
    """พิมพ์ลง console เผื่อรันแบบเห็นหน้าต่าง และเก็บไว้โชว์ในหน้าต่างบันทึกด้วย
    (กัน error การพิมพ์เอาไว้ ไม่ให้ทำโปรแกรมทั้งตัว crash แม้เจอ encoding แปลกๆ)"""
    try:
        print(msg)
    except Exception:
        pass
    with _log_lock:
        _log_lines.append(msg)
    _refresh_log_widget()


def _start_gui():
    global _tk_root, _tk_text_widget
    import tkinter as tk

    _tk_root = tk.Tk()
    _tk_root.title("Bagley Tray - บันทึกกิจกรรมของบอท")
    _tk_root.geometry("640x460")
    _tk_root.configure(bg="#2b2d31")
    _tk_root.protocol("WM_DELETE_WINDOW", _tk_root.withdraw)

    _tk_text_widget = tk.Text(
        _tk_root, wrap="word", state="disabled",
        bg="#2b2d31", fg="#dbdee1", insertbackground="#dbdee1",
        font=("Consolas", 10), padx=10, pady=10, borderwidth=0,
    )
    _tk_text_widget.pack(fill="both", expand=True)

    _tk_root.withdraw()
    _tk_ready_event.set()
    _tk_root.mainloop()


def _refresh_log_widget():
    if _tk_root is None:
        return

    def _update():
        if _tk_text_widget is None:
            return
        with _log_lock:
            content = "\n".join(_log_lines)
        _tk_text_widget.config(state="normal")
        _tk_text_widget.delete("1.0", "end")
        _tk_text_widget.insert("1.0", content)
        _tk_text_widget.see("end")
        _tk_text_widget.config(state="disabled")

    try:
        _tk_root.after(0, _update)
    except RuntimeError:
        pass


def toggle_log_window(icon=None, item=None):
    if _tk_root is None:
        return

    def _toggle():
        if _tk_root.state() == "withdrawn":
            _refresh_log_widget()
            _tk_root.deiconify()
            _tk_root.lift()
            _tk_root.focus_force()
        else:
            _tk_root.withdraw()

    _tk_root.after(0, _toggle)
# =========================================================================


# ==================== ระบบควบคุมโปรเซสของ bot.py ====================
_proc = None                    # subprocess.Popen ของบอทที่กำลังรันอยู่ (หรือ None)
_proc_lock = threading.Lock()
_desired_running = True         # เจตนาว่าอยากให้บอทรันอยู่ไหม (แยกจากอาการ crash เอง)
_watchdog_started = False


def is_bot_running() -> bool:
    with _proc_lock:
        return _proc is not None and _proc.poll() is None


def _read_bot_output(proc):
    """อ่าน stdout/stderr ของบอทแบบสดๆทีละบรรทัด ป้อนเข้า log ของเรา"""
    try:
        for line in proc.stdout:
            log(line.rstrip("\n"))
    except Exception:
        pass
    log("📴 ช่องอ่าน log ของบอทถูกปิดแล้ว (บอทหยุดทำงานแล้ว)")


def _find_python_executable():
    """หา python interpreter ตัวจริงสำหรับรัน bot.py
    🔧 [แก้บั๊กสำคัญ] ตอน bagley_tray.py ถูก build เป็น .exe แล้ว (frozen)
    sys.executable จะไม่ได้ชี้ไปที่ python.exe จริง แต่ชี้กลับมาที่ bagley_tray.exe
    ตัวเอง! ถ้าใช้ sys.executable ตรงๆจะเท่ากับสั่ง "bagley_tray.exe bot.py"
    ซึ่งเปิด bagley_tray.exe ซ้อนขึ้นมาอีกตัวโดยไม่ได้ตั้งใจ (ไม่ได้รัน bot.py
    เลย!) ต้องหา python.exe ตัวจริงจาก PATH ของระบบแทนเมื่อรันเป็น .exe"""
    if not getattr(sys, "frozen", False):
        return sys.executable  # รันเป็น .py ธรรมดา sys.executable ถูกอยู่แล้ว

    import shutil
    for candidate in ("python", "python3", "py"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def start_bot():
    global _proc, _desired_running
    with _proc_lock:
        if _proc is not None and _proc.poll() is None:
            log("⚠️ บอทกำลังรันอยู่แล้ว ไม่ต้องเริ่มซ้ำนะครับเมท")
            return
        if not os.path.exists(BOT_SCRIPT_PATH):
            log(f"❌ หาไฟล์ {BOT_SCRIPT_NAME} ไม่เจอในโฟลเดอร์ {BOT_DIR} กรุณาย้าย "
                f"bagley_tray.py ไปไว้โฟลเดอร์เดียวกับ bot.py ก่อนนะครับ")
            return

        python_exe = _find_python_executable()
        if not python_exe:
            log("❌ หา python.exe ไม่เจอในระบบ (PATH) กรุณาติดตั้ง Python และ "
                "เลือก 'Add python.exe to PATH' ตอนติดตั้งด้วย ไม่งั้นตัวคุมนี้ "
                "จะรันบอทไม่ได้เลย")
            return

        _desired_running = True
        log("🟢 กำลังสั่งเริ่มบอท Bagley...")

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        # 🔧 [แก้บั๊ก] encoding="utf-8" ด้านล่างมีผลแค่ฝั่งที่เราอ่าน stdout ของ
        # บอทเท่านั้น ไม่ได้บอกให้ "ตัวบอทเอง" (โปรเซสลูก) ใช้ UTF-8 ด้วย พอบอท
        # สั่ง print() ข้อความไทย/อีโมจิ เลยยังไปชน cp1252 ของ Windows เหมือนเดิม
        # ต้องส่ง PYTHONUTF8=1 ผ่าน environment variable เข้าไปในโปรเซสลูกด้วย
        # เพื่อบังคับให้ Python ของบอทใช้ UTF-8 ทั้ง stdout/stderr ตั้งแต่เริ่มรัน
        child_env = os.environ.copy()
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONIOENCODING"] = "utf-8"

        try:
            _proc = subprocess.Popen(
                [python_exe, BOT_SCRIPT_PATH],
                cwd=BOT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                env=child_env,
            )
        except Exception as e:
            log(f"❌ เริ่มบอทไม่ได้: {e}")
            return

        threading.Thread(target=_read_bot_output, args=(_proc,), daemon=True).start()

    _update_tray_icon()


def stop_bot():
    global _proc, _desired_running
    with _proc_lock:
        _desired_running = False
        proc = _proc

    if proc is None or proc.poll() is not None:
        log("⚠️ บอทหยุดอยู่แล้วนะครับเมท")
        _update_tray_icon()
        return

    log("🔴 กำลังสั่งหยุดบอท Bagley... (รอสักครู่)")
    try:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            log("⚠️ บอทไม่ยอมปิดแบบปกติ กำลังบังคับปิด...")
            proc.kill()
        log("🛑 บอทหยุดทำงานเรียบร้อยแล้วครับ")
    except Exception as e:
        log(f"❌ หยุดบอทไม่สมบูรณ์: {e}")

    _update_tray_icon()


# รหัสลับที่ bot.py ใช้ตอนปิดตัวเองเพราะสั่ง /update_bot (ต้องตรงกับที่ตั้งไว้
# ในฝั่ง bot.py: os._exit(87) ที่ท้ายคำสั่ง /update_bot) เพื่อให้ตัวคุมนี้รู้ว่า
# "ปิดเพื่ออัปเดตโค้ด ให้เริ่มใหม่ได้เลย" แยกออกจากกรณี crash จริงๆที่ไม่ควร
# auto-restart ซ้ำๆ (กันเข้าลูปพังไม่เลิกถ้าโค้ดบอทมีปัญหาจริง)
UPDATE_RESTART_EXIT_CODE = 87


def _watchdog_loop():
    """คอยเช็คทุก 3 วิ ว่าบอทหยุดไปเองเพราะอะไร:
    - ถ้าปิดตัวเองด้วยรหัส 87 (มาจากคำสั่ง /update_bot) -> สั่งเริ่มใหม่ให้อัตโนมัติเลย
    - ถ้าปิดไปเองด้วยรหัสอื่น (น่าจะ crash จริง) -> แค่แจ้งเตือนใน log ไม่ auto-restart
      ให้ (กันเข้าลูปพังซ้ำๆถ้าโค้ดบอทมีปัญหาจริง) ต้องกดเริ่มใหม่เองจากหน้าควบคุม"""
    global _proc
    last_state = None
    while True:
        time.sleep(3)
        with _proc_lock:
            running = _proc is not None and _proc.poll() is None
            exit_code = _proc.poll() if _proc is not None else None
            stopped_unexpectedly = (
                _proc is not None and exit_code is not None and _desired_running
            )

        if stopped_unexpectedly and last_state != "handled":
            last_state = "handled"
            if exit_code == UPDATE_RESTART_EXIT_CODE:
                log("🔄 [Update Bot] บอทปิดตัวเองเพื่ออัปเดตโค้ด (/update_bot) "
                    "กำลังเริ่มบอทใหม่ให้อัตโนมัติ...")
                start_bot()
            else:
                log(f"💥 [แจ้งเตือน] บอทหยุดทำงานไปเองแบบไม่ได้ตั้งใจ (exit code: {exit_code}) "
                    f"น่าจะ crash! กดเมนู 'ควบคุมบอท' เพื่อสั่งเริ่มใหม่ได้ครับ")
                _update_tray_icon()
        elif running:
            last_state = "running"
# =========================================================================


# ==================== หน้าต่างควบคุมบอท (สวิตช์เริ่ม/หยุด) ====================
def open_control_window(icon=None, item=None):
    if _tk_root is None:
        return
    _tk_root.after(0, _build_control_window)


def _build_control_window():
    import tkinter as tk

    win = tk.Toplevel(_tk_root)
    win.title("ควบคุมบอท Bagley")
    win.geometry("380x260")
    win.configure(bg="#2b2d31")
    win.resizable(False, False)
    win.attributes("-topmost", True)

    label_opts = dict(bg="#2b2d31", fg="#dbdee1", anchor="w", font=("Segoe UI", 10))

    tk.Label(win, text="สถานะบอทตอนนี้:", **label_opts).pack(fill="x", padx=16, pady=(20, 4))

    status_var = tk.StringVar()
    status_display = tk.Label(win, textvariable=status_var, bg="#2b2d31",
                               font=("Segoe UI", 14, "bold"), anchor="w")
    status_display.pack(fill="x", padx=16)

    intended_running = tk.BooleanVar(value=is_bot_running())
    toggle_btn = tk.Button(win, text="", bg="#4e5058", fg="white",
                           relief="flat", padx=10, pady=10, font=("Segoe UI", 10, "bold"))

    def _refresh_status_text():
        running_now = is_bot_running()
        if running_now:
            status_var.set("🟢  บอทกำลังทำงานอยู่")
            status_display.config(fg="#23a55a")
        else:
            status_var.set("🔴  บอทหยุดอยู่")
            status_display.config(fg="#f23f43")
        intended_running.set(running_now)
        _update_toggle_text()

    def _update_toggle_text():
        toggle_btn.config(
            text="⏹️   สั่งหยุดบอท   " if intended_running.get() else "▶️   สั่งเริ่มบอท   "
        )

    def _flip_toggle():
        intended_running.set(not intended_running.get())
        _update_toggle_text()

    toggle_btn.config(command=_flip_toggle)
    toggle_btn.pack(fill="x", padx=16, pady=(16, 6))

    tk.Label(
        win,
        text="กด 'บันทึก' เพื่อให้การเปลี่ยนสถานะมีผลจริง\nหรือ 'ยกเลิก' เพื่อปิดหน้าต่างนี้โดยไม่ทำอะไรเลย",
        bg="#2b2d31", fg="#949ba4", font=("Segoe UI", 8), justify="left",
    ).pack(fill="x", padx=16, pady=(6, 0))

    def _apply():
        if intended_running.get():
            threading.Thread(target=start_bot, daemon=True).start()
        else:
            threading.Thread(target=stop_bot, daemon=True).start()
        win.destroy()

    btn_frame = tk.Frame(win, bg="#2b2d31")
    btn_frame.pack(fill="x", padx=16, pady=16, side="bottom")
    tk.Button(btn_frame, text="บันทึก", command=_apply, bg="#5865f2", fg="white",
              relief="flat", padx=14, pady=6).pack(side="right")
    tk.Button(btn_frame, text="ยกเลิก", command=win.destroy, bg="#4e5058", fg="white",
              relief="flat", padx=14, pady=6).pack(side="right", padx=(0, 8))

    _refresh_status_text()
    win.lift()
    win.focus_force()
# =========================================================================


# ==================== ไอคอนถาด (System Tray) ====================
def quit_app(icon, item):
    """ออกจากโปรแกรมจริงๆ: จะสั่งหยุดบอทให้อัตโนมัติก่อน ไม่ทิ้งโปรเซสค้าง"""
    log("🛑 กำลังปิด Bagley Tray... (จะหยุดบอทให้ด้วย)")
    try:
        stop_bot()
    except Exception:
        pass
    try:
        icon.stop()
    except Exception:
        pass
    try:
        if _tk_root:
            _tk_root.after(0, _tk_root.quit)
    except Exception:
        pass
    try:
        if _lock_socket:
            _lock_socket.close()
    except Exception:
        pass
    os._exit(0)


def _create_tray_image(running: bool = True):
    """โหลดไอคอนถาดจากไฟล์ tray_icon.png ถ้ามี แล้วแต้มจุดสีบอกสถานะมุมขวาล่าง
    ถ้าหาไฟล์ไม่เจอ จะวาดไอคอนหุ่นยนต์สำรองขึ้นมาแทน (ให้ต่างจากไอคอนไมค์)"""
    icon_path = resource_path("tray_icon.png")
    try:
        img = Image.open(icon_path).convert("RGBA")
    except Exception:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        bot_color = (88, 101, 242, 255)  # สีม่วง Discord
        draw.rounded_rectangle((14, 18, 50, 48), radius=8, fill=bot_color)  # หัวหุ่นยนต์
        draw.ellipse((22, 26, 30, 34), fill=(43, 45, 49, 255))   # ตาซ้าย
        draw.ellipse((34, 26, 42, 34), fill=(43, 45, 49, 255))   # ตาขวา
        draw.rectangle((28, 38, 36, 42), fill=(43, 45, 49, 255))  # ปาก
        draw.rectangle((30, 8, 34, 18), fill=bot_color)   # เสาอากาศ
        draw.ellipse((28, 2, 36, 10), fill=bot_color)

    # แต้มจุดสีสถานะที่มุมขวาล่างของไอคอน (🟢 ทำงาน / 🔴 หยุด)
    img = img.copy()
    draw = ImageDraw.Draw(img)
    dot_color = (35, 165, 90, 255) if running else (242, 63, 67, 255)
    w, h = img.size
    r = max(10, w // 5)
    draw.ellipse((w - r - 2, h - r - 2, w - 2, h - 2), fill=dot_color, outline=(43, 45, 49, 255), width=2)
    return img


def _update_tray_icon():
    """อัปเดตสีจุดสถานะ + tooltip ของไอคอนถาดให้ตรงกับสถานะบอทล่าสุด"""
    if _tray_icon_obj is None:
        return
    running = is_bot_running()
    try:
        _tray_icon_obj.icon = _create_tray_image(running)
        _tray_icon_obj.title = "Bagley Tray - 🟢 บอททำงานอยู่" if running else "Bagley Tray - 🔴 บอทหยุดอยู่"
    except Exception:
        pass


def start_tray_icon():
    global _tray_icon_obj
    image = _create_tray_image(running=is_bot_running())
    menu = pystray.Menu(
        pystray.MenuItem("แสดง/ซ่อนบันทึกกิจกรรม", toggle_log_window, default=True),
        pystray.MenuItem("🎛️ ควบคุมบอท (เริ่ม/หยุด)", open_control_window),
        pystray.MenuItem("ออกจากโปรแกรม", quit_app),
    )
    _tray_icon_obj = pystray.Icon("bagley_tray", image, "Bagley Tray (คลิกเพื่อดูบันทึก)", menu)
    _tray_icon_obj.run()
# =========================================================================


def main():
    if not _acquire_single_instance_lock():
        try:
            import tkinter as tk
            from tkinter import messagebox
            _warn_root = tk.Tk()
            _warn_root.withdraw()
            messagebox.showwarning(
                "Bagley Tray",
                "Bagley Tray กำลังทำงานอยู่แล้วครับ!\n\n"
                "เช็คไอคอนเล็กๆที่มุมขวาล่างของจอ (ถ้าไม่เห็น ให้ลองกดลูกศร ▲ "
                "ตรงช่อง 'ไอคอนที่ซ่อนอยู่' ก่อน) ไม่ต้องเปิดซ้ำอีกครับ",
            )
            _warn_root.destroy()
        except Exception:
            pass
        sys.exit(0)

    gui_thread = threading.Thread(target=_start_gui, daemon=True)
    gui_thread.start()
    _tk_ready_event.wait(timeout=5)

    log("=" * 50)
    log("Bagley Tray พร้อมทำงานแล้ว")
    log(f"📁 โฟลเดอร์บอท: {BOT_DIR}")
    log("=" * 50)

    threading.Thread(target=start_bot, daemon=True).start()
    threading.Thread(target=_watchdog_loop, daemon=True).start()

    start_tray_icon()  # บล็อกอยู่ตรงนี้จนกว่าจะกด "ออกจากโปรแกรม"


if __name__ == "__main__":
    main()
