"""
다중 버튼 감지 및 하이브리드 자동 클릭 매크로 (GUI 대시보드 v2.0)
- 복수의 버튼(확인, 다음, 시작 등) 등록 및 개별 임계치/우선순위/쿨다운 관리
- 하이브리드 클릭 모드 (SendInput / Activate / PostMessage)
- 화면 내 프리뷰 클릭 테스트 기능
- 창 내 직접 영역 캡처(Snipping Tool) 지원
"""

import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image, ImageTk

from window_capture import get_window_list, capture_window
from detector import MultiTargetDetector, TargetItem
from clicker import dispatch_click
from macro_core import MacroEngine

import ctypes

# DPI 인식 설정 (고해상도 125%/150% 모니터 좌표 오차 방지)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def is_admin() -> bool:
    """현재 프로세스가 관리자 권한으로 실행 중인지 확인"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def request_admin_elevation():
    """관리자 권한이 아닐 경우 Windows UAC 프롬프트를 통해 관리자 권한으로 자동 승격 재실행"""
    if not is_admin() and "--no-elevate" not in sys.argv:
        try:
            script = os.path.abspath(sys.argv[0])
            params = f'"{script}"'
            # Windows API ShellExecuteW(runas)로 UAC 승격 요청
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, None, 1
            )
            if ret > 32:  # UAC '예' 승인 완료 -> 기존 일반 권한 프로세스 종료
                sys.exit(0)
        except Exception:
            pass


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class CropSnippingDialog(ctk.CTkToplevel):
    """현재 창 화면에서 버튼/프레임 영역을 마우스로 잘라내는 스니핑 대화상자"""
    def __init__(self, parent, frame_img: np.ndarray, on_crop_done):
        super().__init__(parent)
        self.title("✂️ 버튼 영역 드래그 캡처")
        self.geometry("960x700")
        self.attributes("-topmost", True)

        self.frame_img = frame_img.copy()
        self.on_crop_done = on_crop_done
        self.orig_h, self.orig_w = frame_img.shape[:2]

        self.display_w = min(920, self.orig_w)
        self.scale = self.display_w / self.orig_w
        self.display_h = int(self.orig_h * self.scale)

        img_rgb = cv2.cvtColor(self.frame_img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb).resize((self.display_w, self.display_h), Image.Resampling.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(pil_img)

        ctk.CTkLabel(
            self,
            text="마우스로 등록할 버튼 영역을 드래그한 후 [선택 완료]를 누르세요.",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(pady=8)

        self.canvas = tk.Canvas(
            self,
            width=self.display_w,
            height=self.display_h,
            cursor="cross",
            bg="#181818",
            highlightthickness=0
        )
        self.canvas.pack(padx=10, pady=5)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)

        self.start_x = None
        self.start_y = None
        self.rect_id = None
        self.crop_box = None

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        btn_box = ctk.CTkFrame(self)
        btn_box.pack(fill="x", padx=20, pady=10)

        ctk.CTkButton(
            btn_box,
            text="선택 완료 (다음)",
            fg_color="#2ecc71",
            hover_color="#27ae60",
            width=130,
            command=self.confirm_crop
        ).pack(side="right", padx=10)

        ctk.CTkButton(
            btn_box,
            text="취소",
            fg_color="#e74c3c",
            hover_color="#c0392b",
            width=100,
            command=self.destroy
        ).pack(side="right")

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="#00ffcc", width=2
        )

    def on_drag(self, event):
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)

        orig_x1 = int(x1 / self.scale)
        orig_y1 = int(y1 / self.scale)
        orig_x2 = int(x2 / self.scale)
        orig_y2 = int(y2 / self.scale)

        if orig_x2 - orig_x1 > 5 and orig_y2 - orig_y1 > 5:
            self.crop_box = (orig_x1, orig_y1, orig_x2, orig_y2)

    def confirm_crop(self):
        if not self.crop_box:
            messagebox.showwarning("경고", "먼저 영역을 마우스로 드래그하여 지정하세요.", parent=self)
            return

        x1, y1, x2, y2 = self.crop_box
        cropped = self.frame_img[y1:y2, x1:x2]
        fh, fw = self.frame_img.shape[:2]
        self.on_crop_done(cropped, fw, fh)
        self.destroy()


class AddTargetDialog(ctk.CTkToplevel):
    """새 버튼/타겟의 이름, 임계치, 우선순위, 쿨다운을 입력받는 대화상자"""
    def __init__(self, parent, target_img: np.ndarray, on_save_target, base_width: int = 0, base_height: int = 0):
        super().__init__(parent)
        self.title("새 버튼 등록 상세 설정")
        self.geometry("450x570")
        self.attributes("-topmost", True)
        self.resizable(False, False)

        self.target_img = target_img
        self.on_save_target = on_save_target
        self.base_width = base_width
        self.base_height = base_height

        th, tw = target_img.shape[:2]

        ctk.CTkLabel(self, text="➕ 새 버튼 등록", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(15, 5))

        # 이미지 썸네일
        img_rgb = cv2.cvtColor(target_img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        thumb_h = min(80, th)
        thumb_w = int(tw * (thumb_h / th))
        pil_thumb = pil_img.resize((max(1, thumb_w), max(1, thumb_h)), Image.Resampling.LANCZOS)
        self.ctk_thumb = ctk.CTkImage(light_image=pil_thumb, dark_image=pil_thumb, size=(thumb_w, thumb_h))

        ctk.CTkLabel(self, image=self.ctk_thumb, text="").pack(pady=5)
        res_text = f" | 기준 화면: {base_width}x{base_height}px (자동 보정)" if base_width > 0 else ""
        ctk.CTkLabel(self, text=f"이미지 크기: {tw} x {th} px{res_text}", text_color="gray").pack(pady=(0, 10))

        # 폼 컨테이너
        form = ctk.CTkFrame(self)
        form.pack(fill="both", expand=True, padx=25, pady=5)

        # 1. 버튼 이름
        ctk.CTkLabel(form, text="버튼 이름 (예: 확인, 시작, 닫기):", anchor="w").pack(fill="x", padx=15, pady=(10, 2))
        self.name_entry = ctk.CTkEntry(form, placeholder_text="버튼 이름을 입력하세요")
        self.name_entry.insert(0, f"버튼_{int(time.time())%1000}")
        self.name_entry.pack(fill="x", padx=15, pady=(0, 8))

        # 2. 일치율 슬라이더
        self.thresh_lbl = ctk.CTkLabel(form, text="감지 기준 일치율: 85%", anchor="w")
        self.thresh_lbl.pack(fill="x", padx=15, pady=(5, 2))
        self.thresh_slider = ctk.CTkSlider(form, from_=50, to=99, number_of_steps=49, command=self.on_thresh_change)
        self.thresh_slider.set(85)
        self.thresh_slider.pack(fill="x", padx=15, pady=(0, 8))

        # 3. 우선순위 (1~10)
        prio_box = ctk.CTkFrame(form, fg_color="transparent")
        prio_box.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(prio_box, text="우선순위 (1이 최우선):", width=180, anchor="w").pack(side="left")
        self.prio_entry = ctk.CTkEntry(prio_box, width=70)
        self.prio_entry.insert(0, "1")
        self.prio_entry.pack(side="right")

        # 4. 개별 쿨다운 (초)
        cd_box = ctk.CTkFrame(form, fg_color="transparent")
        cd_box.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(cd_box, text="재클릭 방지 쿨다운 (초):", width=180, anchor="w").pack(side="left")
        self.cd_entry = ctk.CTkEntry(cd_box, width=70)
        self.cd_entry.insert(0, "2.0")
        self.cd_entry.pack(side="right")

        # 등록 버튼
        ctk.CTkButton(
            self,
            text="완료 및 등록하기",
            fg_color="#2ecc71",
            hover_color="#27ae60",
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.submit
        ).pack(fill="x", padx=25, pady=15)

    def on_thresh_change(self, val):
        self.thresh_lbl.configure(text=f"감지 기준 일치율: {int(val)}%")

    def submit(self):
        name = self.name_entry.get().strip()
        if not name:
            name = "이름 없는 버튼"

        thresh = self.thresh_slider.get() / 100.0

        try:
            priority = int(self.prio_entry.get())
        except ValueError:
            priority = 1

        try:
            cooldown = float(self.cd_entry.get())
        except ValueError:
            cooldown = 2.0

        self.on_save_target(name, self.target_img, thresh, priority, cooldown, self.base_width, self.base_height)
        self.destroy()


class MacroApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("🎯 다중 버튼 감지 및 하이브리드 자동 클릭 매크로 v2.0")
        self.geometry("1240x820")
        self.minsize(1100, 720)

        self.engine = MacroEngine()
        self.windows_data = []
        self.last_frame: Optional[np.ndarray] = None
        self.target_cards = {}

        # 엔진 콜백 연결
        self.engine.on_log = self.append_log
        self.engine.on_frame_update = self.on_frame_updated
        self.engine.on_status_change = self.on_status_updated

        self.setup_ui()
        self.refresh_window_list()
        self.render_target_list()

    def setup_ui(self):
        # 1. 최상단 헤더 바
        header = ctk.CTkFrame(self, height=52, corner_radius=0, fg_color="#181824")
        header.pack(fill="x", side="top")

        ctk.CTkLabel(
            header,
            text="🎯 Multi-Button Frame Detector & Hybrid Clicker",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left", padx=20, pady=10)

        self.status_badge = ctk.CTkLabel(
            header,
            text="대기 중",
            fg_color="#555555",
            corner_radius=6,
            width=90,
            height=28,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.status_badge.pack(side="right", padx=(0, 20), pady=10)

        # 관리자 권한 상태 표시 배지
        admin_active = is_admin()
        admin_text = "🛡️ 관리자 권한" if admin_active else "⚠️ 일반 권한"
        admin_color = "#27ae60" if admin_active else "#d35400"
        self.admin_badge = ctk.CTkLabel(
            header,
            text=admin_text,
            fg_color=admin_color,
            corner_radius=6,
            width=110,
            height=28,
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.admin_badge.pack(side="right", padx=(0, 8), pady=10)

        # 2. 메인 3컬럼 레이아웃
        main_layout = ctk.CTkFrame(self, fg_color="transparent")
        main_layout.pack(fill="both", expand=True, padx=12, pady=10)

        # ==========================================
        # [컬럼 1] 창 선택 & 전역 클릭 엔진 설정 (320px)
        # ==========================================
        col1 = ctk.CTkFrame(main_layout, width=320)
        col1.pack(side="left", fill="y", padx=(0, 10))
        col1.pack_propagate(False)

        # 창 선택 섹션
        ctk.CTkLabel(col1, text="1. 대상 윈도우 선택", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 4))
        
        self.win_combobox = ctk.CTkComboBox(col1, values=["창 목록 검색 중..."], command=self.on_window_selected, height=32)
        self.win_combobox.pack(fill="x", padx=12, pady=4)

        win_btn_row = ctk.CTkFrame(col1, fg_color="transparent")
        win_btn_row.pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(win_btn_row, text="🔄 목록 갱신", width=120, command=self.refresh_window_list).pack(side="left", padx=(0, 6))
        ctk.CTkButton(win_btn_row, text="📷 화면 캡처", width=120, fg_color="#2980b9", hover_color="#1f618d", command=self.test_capture_window).pack(side="left")

        # 클릭 방식 선택 (핵심!)
        ctk.CTkLabel(col1, text="2. 클릭 모드 (엔진)", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(15, 4))
        
        self.click_mode_var = ctk.StringVar(value="hardware")
        
        mode_box = ctk.CTkFrame(col1, fg_color="#222230")
        mode_box.pack(fill="x", padx=12, pady=4)

        ctk.CTkRadioButton(
            mode_box,
            text="⚡ 초고속 하드웨어 클릭 (추천)",
            variable=self.click_mode_var,
            value="hardware",
            command=self.on_click_mode_changed
        ).pack(anchor="w", padx=10, pady=(8, 2))
        ctk.CTkLabel(mode_box, text="   10ms 커서 이동 후 원위치 복귀 (모든 게임 100% 호환)", font=ctk.CTkFont(size=11), text_color="#aaaaaa").pack(anchor="w", padx=10, pady=(0, 6))

        ctk.CTkRadioButton(
            mode_box,
            text="🎯 창 활성화 후 클릭",
            variable=self.click_mode_var,
            value="activate",
            command=self.on_click_mode_changed
        ).pack(anchor="w", padx=10, pady=(4, 2))
        ctk.CTkLabel(mode_box, text="   창을 전면으로 가져와 포커스 후 클릭", font=ctk.CTkFont(size=11), text_color="#aaaaaa").pack(anchor="w", padx=10, pady=(0, 6))

        ctk.CTkRadioButton(
            mode_box,
            text="👻 비활성 백그라운드 클릭",
            variable=self.click_mode_var,
            value="postmessage",
            command=self.on_click_mode_changed
        ).pack(anchor="w", padx=10, pady=(4, 2))
        ctk.CTkLabel(mode_box, text="   커서 미이동 Win32 메시지 전송 (게임에 따라 무시될 수 있음)", font=ctk.CTkFont(size=11), text_color="#aaaaaa").pack(anchor="w", padx=10, pady=(0, 8))

        # 클릭 테스트 버튼
        test_click_box = ctk.CTkFrame(col1, fg_color="transparent")
        test_click_box.pack(fill="x", padx=12, pady=(6, 8))
        ctk.CTkButton(
            test_click_box,
            text="🎯 대상 창 클릭 테스트 (화면 중앙)",
            fg_color="#e67e22",
            hover_color="#d35400",
            command=self.test_click_on_window
        ).pack(fill="x")

        # 클릭 좌표 미세보정 (X, Y 오프셋)
        ctk.CTkLabel(col1, text="3. 클릭 좌표 미세보정 (상/하 오프셋)", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 4))
        offset_card = ctk.CTkFrame(col1, fg_color="#20202e")
        offset_card.pack(fill="x", padx=12, pady=4)

        y_row = ctk.CTkFrame(offset_card, fg_color="transparent")
        y_row.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(y_row, text="Y (상/하):", width=65, anchor="w", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        
        self.offset_y_var = ctk.StringVar(value="0")
        self.offset_y_entry = ctk.CTkEntry(y_row, textvariable=self.offset_y_var, width=55, height=28)
        self.offset_y_entry.pack(side="left", padx=4)
        self.offset_y_entry.bind("<KeyRelease>", self.on_offset_entry_changed)
        ctk.CTkLabel(y_row, text="px (음수=위, 양수=아래)", font=ctk.CTkFont(size=11), text_color="#aaaaaa").pack(side="left")

        quick_btn_row = ctk.CTkFrame(offset_card, fg_color="transparent")
        quick_btn_row.pack(fill="x", padx=8, pady=(0, 8))
        for val_txt, val_int in [("▲-30px", -30), ("▲-15px", -15), ("0px", 0), ("▼+15px", 15)]:
            ctk.CTkButton(
                quick_btn_row,
                text=val_txt,
                width=55,
                height=24,
                font=ctk.CTkFont(size=10),
                fg_color="#34495e",
                hover_color="#2c3e50",
                command=lambda v=val_int: self.set_global_offset_y(v)
            ).pack(side="left", padx=2)

        # 전역 옵션
        ctk.CTkLabel(col1, text="4. 스캔 및 제어", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 4))
        
        opt_row = ctk.CTkFrame(col1, fg_color="transparent")
        opt_row.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(opt_row, text="스캔 주기 (초):", width=110, anchor="w").pack(side="left")
        self.interval_entry = ctk.CTkEntry(opt_row, width=80)
        self.interval_entry.insert(0, "0.4")
        self.interval_entry.pack(side="left")

        # 매크로 시작 / 정지 버튼
        ctrl_box = ctk.CTkFrame(col1, fg_color="transparent")
        ctrl_box.pack(fill="x", padx=12, pady=(15, 10))

        self.start_btn = ctk.CTkButton(
            ctrl_box,
            text="▶ 매크로 시작",
            height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#2ecc71",
            hover_color="#27ae60",
            command=self.toggle_macro_start
        )
        self.start_btn.pack(fill="x", pady=(0, 6))

        self.pause_btn = ctk.CTkButton(
            ctrl_box,
            text="⏸ 일시정지",
            state="disabled",
            fg_color="#f39c12",
            hover_color="#d68910",
            command=self.toggle_pause
        )
        self.pause_btn.pack(fill="x")

        # ==========================================
        # [컬럼 2] 등록된 버튼 관리자 (380px)
        # ==========================================
        col2 = ctk.CTkFrame(main_layout, width=380)
        col2.pack(side="left", fill="both", padx=(0, 10))
        col2.pack_propagate(False)

        col2_header = ctk.CTkFrame(col2, fg_color="transparent")
        col2_header.pack(fill="x", padx=12, pady=(12, 6))
        
        ctk.CTkLabel(col2_header, text="등록된 버튼 목록", font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")

        add_btn_row = ctk.CTkFrame(col2, fg_color="transparent")
        add_btn_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkButton(
            add_btn_row,
            text="✂️ 창에서 직접 캡처 추가",
            width=170,
            fg_color="#9b59b6",
            hover_color="#8e44ad",
            command=self.start_crop_add
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            add_btn_row,
            text="📂 파일로 추가",
            width=130,
            command=self.start_file_add
        ).pack(side="left")

        # 타겟 카드 목록 스크롤 프레임
        self.targets_scroll = ctk.CTkScrollableFrame(col2)
        self.targets_scroll.pack(fill="both", expand=True, padx=8, pady=4)

        # ==========================================
        # [컬럼 3] 실시간 모니터링 & 활동 로그 (잔여 폭)
        # ==========================================
        col3 = ctk.CTkFrame(main_layout)
        col3.pack(side="right", fill="both", expand=True)

        monitor_header = ctk.CTkFrame(col3, fg_color="transparent")
        monitor_header.pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkLabel(monitor_header, text="실시간 감지 화면 (미리보기)", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkButton(monitor_header, text="🔍 1회 감지 테스트", width=120, height=24, fg_color="#34495e", command=self.test_detect_once).pack(side="right")

        self.preview_canvas = tk.Canvas(col3, height=360, bg="#111116", highlightthickness=0)
        self.preview_canvas.pack(fill="x", padx=12, pady=4)
        self.preview_canvas.bind("<Button-1>", self.on_canvas_click_test)
        self.preview_canvas_img = None

        ctk.CTkLabel(
            col3,
            text="💡 팁: 미리보기 화면의 임의의 위치를 마우스로 클릭하면 해당 위치로 즉시 테스트 클릭을 전송합니다.",
            font=ctk.CTkFont(size=11),
            text_color="#8888aa"
        ).pack(anchor="w", padx=15, pady=(0, 4))

        # 하단 로그
        log_header = ctk.CTkFrame(col3, fg_color="transparent")
        log_header.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(log_header, text="동작 로그 (Activity Log)", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        ctk.CTkButton(log_header, text="지우기", width=60, height=20, command=self.clear_log).pack(side="right")

        self.log_textbox = ctk.CTkTextbox(col3, height=180, font=ctk.CTkFont(family="Consolas", size=11))
        self.log_textbox.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    # ------------------ 타겟 카드 렌더링 ------------------

    def render_target_list(self):
        # 기존 위젯 정리
        for w in self.targets_scroll.winfo_children():
            w.destroy()
        self.target_cards.clear()

        targets = self.engine.get_all_targets()
        if not targets:
            ctk.CTkLabel(
                self.targets_scroll,
                text="등록된 버튼이 없습니다.\n[✂️ 창에서 직접 캡처 추가] 버튼을 눌러\n클릭할 버튼들을 등록하세요!",
                text_color="gray"
            ).pack(pady=40)
            return

        for t in targets:
            card = ctk.CTkFrame(self.targets_scroll, fg_color="#20202e", corner_radius=8)
            card.pack(fill="x", pady=5, padx=2)

            # 상단: 썸네일 + 이름 + ON/OFF 스위치
            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=8, pady=(8, 4))

            # 썸네일
            img_rgb = cv2.cvtColor(t.template_img, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            thumb_h = 36
            thumb_w = int(t.w * (thumb_h / t.h))
            pil_thumb = pil_img.resize((max(1, thumb_w), thumb_h), Image.Resampling.LANCZOS)
            ctk_thumb = ctk.CTkImage(light_image=pil_thumb, dark_image=pil_thumb, size=(thumb_w, thumb_h))
            self.target_cards[t.id + "_thumb"] = ctk_thumb # 참조 보존

            ctk.CTkLabel(top_row, image=ctk_thumb, text="").pack(side="left", padx=(0, 8))
            
            title_box = ctk.CTkFrame(top_row, fg_color="transparent")
            title_box.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(title_box, text=t.name, font=ctk.CTkFont(size=13, weight="bold"), anchor="w").pack(fill="x")
            res_tag = f" | {t.base_width}x{t.base_height}" if t.base_width > 0 else " | 자동비율"
            ctk.CTkLabel(title_box, text=f"우선순위: {t.priority} | 쿨다운: {t.cooldown}초{res_tag}", font=ctk.CTkFont(size=10), text_color="gray", anchor="w").pack(fill="x")

            # 스위치
            switch_var = ctk.BooleanVar(value=t.enabled)
            sw = ctk.CTkSwitch(
                top_row,
                text="",
                variable=switch_var,
                width=40,
                command=lambda tid=t.id, sv=switch_var: self.engine.toggle_target(tid, sv.get())
            )
            sw.pack(side="right", padx=2)

            # 하단: 일치율 슬라이더 + 삭제 버튼
            bottom_row = ctk.CTkFrame(card, fg_color="transparent")
            bottom_row.pack(fill="x", padx=8, pady=(2, 6))

            thresh_lbl = ctk.CTkLabel(bottom_row, text=f"일치율: {int(t.threshold*100)}%", font=ctk.CTkFont(size=11), width=75, anchor="w")
            thresh_lbl.pack(side="left")

            def on_card_slider(val, tid=t.id, lbl=thresh_lbl):
                pct = int(val)
                lbl.configure(text=f"일치율: {pct}%")
                self.engine.update_target(tid, threshold=pct / 100.0)

            slider = ctk.CTkSlider(bottom_row, from_=50, to=99, number_of_steps=49, command=on_card_slider)
            slider.set(int(t.threshold * 100))
            slider.pack(side="left", fill="x", expand=True, padx=4)

            # 삭제 버튼
            del_btn = ctk.CTkButton(
                bottom_row,
                text="🗑️",
                width=28,
                height=24,
                fg_color="#c0392b",
                hover_color="#962d22",
                command=lambda tid=t.id: self.delete_target_card(tid)
            )
            del_btn.pack(side="right", padx=(4, 0))

    def delete_target_card(self, target_id: str):
        self.engine.remove_target(target_id)
        self.render_target_list()

    # ------------------ 타겟 추가 흐름 ------------------

    def start_crop_add(self):
        if not self.engine.hwnd:
            messagebox.showwarning("경고", "먼저 상단에서 대상 창을 선택하세요.")
            return

        frame = capture_window(self.engine.hwnd)
        if frame is None:
            messagebox.showerror("오류", "대상 창 화면을 캡처할 수 없습니다.")
            return

        CropSnippingDialog(self, frame, on_crop_done=self.on_crop_completed)

    def on_crop_completed(self, cropped_img: np.ndarray, base_w: int = 0, base_h: int = 0):
        AddTargetDialog(self, cropped_img, on_save_target=self.save_new_target, base_width=base_w, base_height=base_h)

    def start_file_add(self):
        path = filedialog.askopenfilename(
            title="버튼 이미지 파일 선택",
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp"), ("All Files", "*.*")]
        )
        if path:
            img_array = np.fromfile(path, np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is not None:
                # 파일 추가 시 현재 선택된 창이 있으면 창의 해상도를 기준 해상도로 설정
                fw, fh = 0, 0
                if self.engine.hwnd and self.last_frame is not None:
                    fh, fw = self.last_frame.shape[:2]
                AddTargetDialog(self, img, on_save_target=self.save_new_target, base_width=fw, base_height=fh)

    def save_new_target(self, name, img, thresh, priority, cooldown, base_w: int = 0, base_h: int = 0):
        self.engine.add_target(
            name=name,
            template_img=img,
            threshold=thresh,
            priority=priority,
            cooldown=cooldown,
            base_width=base_w,
            base_height=base_h
        )
        self.render_target_list()

    # ------------------ 클릭 테스트 및 창 제어 ------------------

    def on_click_mode_changed(self):
        mode = self.click_mode_var.get()
        self.engine.click_mode = mode
        self.append_log(f"클릭 모드 변경: {mode.upper()}")

    def set_global_offset_y(self, val: int):
        self.offset_y_var.set(str(val))
        self.engine.global_offset_y = val
        self.append_log(f"📐 Y축 클릭 오프셋 보정: {val:+d}px 적용")

    def on_offset_entry_changed(self, event=None):
        try:
            val = int(self.offset_y_var.get())
            self.engine.global_offset_y = val
        except ValueError:
            pass

    def test_click_on_window(self):
        if not self.engine.hwnd:
            messagebox.showwarning("경고", "먼저 대상 창을 선택하세요.")
            return

        frame = capture_window(self.engine.hwnd)
        if frame is None:
            messagebox.showerror("오류", "창 캡처 실패")
            return

        h, w = frame.shape[:2]
        cx = w // 2 + self.engine.global_offset_x
        cy = h // 2 + self.engine.global_offset_y
        mode = self.click_mode_var.get()

        self.append_log(f"🎯 [{mode.upper()} 모드] 창 중앙 ({cx}, {cy}) 클릭 테스트 시도 중...")
        success = dispatch_click(self.engine.hwnd, cx, cy, mode=mode)
        if success:
            self.append_log(f"✅ 클릭 신호 전송 완료! 게임 화면의 반응을 확인하세요.")
        else:
            self.append_log(f"❌ 클릭 신호 전송 실패.")

    def on_canvas_click_test(self, event):
        """미리보기 캔버스를 클릭했을 때 해당 위치로 즉시 클릭 신호 전송"""
        if not self.engine.hwnd or self.last_frame is None:
            return

        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        fh, fw = self.last_frame.shape[:2]

        scale = min(canvas_w / fw, canvas_h / fh)
        dw = int(fw * scale)
        dh = int(fh * scale)
        offset_x = (canvas_w - dw) // 2
        offset_y = (canvas_h - dh) // 2

        click_x = event.x - offset_x
        click_y = event.y - offset_y

        if 0 <= click_x < dw and 0 <= click_y < dh:
            real_x = int(click_x / scale) + self.engine.global_offset_x
            real_y = int(click_y / scale) + self.engine.global_offset_y
            mode = self.click_mode_var.get()
            self.append_log(f"🖱️ 캔버스 클릭 -> 대상 창 ({real_x}, {real_y}) 좌표 [{mode.upper()}] 전송")
            dispatch_click(self.engine.hwnd, real_x, real_y, mode=mode)

    # ------------------ 일반 이벤트 핸들러 ------------------

    def append_log(self, text: str):
        def _append():
            timestamp = time.strftime("[%H:%M:%S] ")
            self.log_textbox.insert("end", timestamp + text + "\n")
            self.log_textbox.see("end")
        self.after(0, _append)

    def clear_log(self):
        self.log_textbox.delete("1.0", "end")

    def refresh_window_list(self):
        self.windows_data = get_window_list()
        titles = [f"[{w['hwnd']}] {w['title'][:32]} ({w['width']}x{w['height']})" for w in self.windows_data]
        if not titles:
            titles = ["실행 중인 창을 찾을 수 없습니다."]
        self.win_combobox.configure(values=titles)
        self.win_combobox.set(titles[0])
        if self.windows_data:
            self.on_window_selected(titles[0])
        self.append_log(f"윈도우 목록 갱신 완료 ({len(self.windows_data)}개)")

    def on_window_selected(self, choice_str):
        for w in self.windows_data:
            key = f"[{w['hwnd']}]"
            if choice_str.startswith(key):
                self.engine.set_target_window(w['hwnd'])
                self.append_log(f"타겟 창 지정: {w['title']} (HWND: {w['hwnd']})")
                return

    def test_capture_window(self):
        if not self.engine.hwnd:
            messagebox.showwarning("경고", "먼저 대상 창을 선택하세요.")
            return

        frame = capture_window(self.engine.hwnd)
        if frame is not None:
            self.last_frame = frame
            self.display_screen_preview(frame)
            self.append_log(f"창 캡처 성공! (크기: {frame.shape[1]}x{frame.shape[0]})")
        else:
            messagebox.showerror("오류", "창 캡처에 실패했습니다.")

    def test_detect_once(self):
        if not self.engine.hwnd:
            messagebox.showwarning("경고", "먼저 대상 창을 선택하세요.")
            return

        frame = capture_window(self.engine.hwnd)
        if frame is None:
            messagebox.showerror("오류", "화면 캡처 실패")
            return

        self.last_frame = frame
        detections = self.engine.detector.detect_all(frame)
        vis = self.engine.detector.draw_detections(frame, detections)
        self.display_screen_preview(vis)

        if detections:
            det_names = [f"{d['name']} ({d['confidence']*100:.1f}%)" for d in detections]
            self.append_log(f"🔍 1회 감지 결과: {len(detections)}개 발견 -> {', '.join(det_names)}")
        else:
            self.append_log("🔍 1회 감지 결과: 화면에서 일치하는 버튼을 찾지 못했습니다.")

    def display_screen_preview(self, frame_bgr: np.ndarray):
        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        if canvas_w <= 10 or canvas_h <= 10:
            canvas_w = 480
            canvas_h = 320

        fh, fw = frame_bgr.shape[:2]
        scale = min(canvas_w / fw, canvas_h / fh)
        dw = int(fw * scale)
        dh = int(fh * scale)

        img_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb).resize((dw, dh), Image.Resampling.LANCZOS)
        self.preview_canvas_img = ImageTk.PhotoImage(pil_img)

        self.preview_canvas.delete("all")
        offset_x = (canvas_w - dw) // 2
        offset_y = (canvas_h - dh) // 2
        self.preview_canvas.create_image(offset_x, offset_y, anchor="nw", image=self.preview_canvas_img)

    def toggle_macro_start(self):
        if not self.engine.is_running:
            if not self.engine.hwnd:
                messagebox.showwarning("경고", "대상 윈도우를 선택하세요.")
                return

            active = [t for t in self.engine.get_all_targets() if t.enabled]
            if not active:
                messagebox.showwarning("경고", "등록되거나 활성화된 버튼이 없습니다.\n[➕ 버튼 추가]를 먼저 진행하세요.")
                return

            try:
                self.engine.interval = float(self.interval_entry.get())
            except ValueError:
                self.engine.interval = 0.4

            self.engine.click_mode = self.click_mode_var.get()
            success = self.engine.start()
            if success:
                self.start_btn.configure(text="⏹ 매크로 정지", fg_color="#e74c3c", hover_color="#c0392b")
                self.pause_btn.configure(state="normal", text="⏸ 일시정지")
        else:
            self.engine.stop()
            self.start_btn.configure(text="▶ 매크로 시작", fg_color="#2ecc71", hover_color="#27ae60")
            self.pause_btn.configure(state="disabled", text="⏸ 일시정지")

    def toggle_pause(self):
        if not self.engine.is_running:
            return

        if not self.engine.is_paused:
            self.engine.pause()
            self.pause_btn.configure(text="▶ 재개", fg_color="#2ecc71", hover_color="#27ae60")
        else:
            self.engine.resume()
            self.pause_btn.configure(text="⏸ 일시정지", fg_color="#f39c12", hover_color="#d68910")

    def on_frame_updated(self, frame_bgr: np.ndarray, detections: list):
        def _update():
            self.last_frame = frame_bgr
            vis = self.engine.detector.draw_detections(frame_bgr, detections)
            self.display_screen_preview(vis)
        self.after(0, _update)

    def on_status_updated(self, status_text: str):
        def _update():
            color_map = {
                "동작 중": "#2ecc71",
                "일시정지": "#f39c12",
                "정지됨": "#e74c3c",
                "대기 중": "#555555"
            }
            color = color_map.get(status_text, "#555555")
            self.status_badge.configure(text=status_text, fg_color=color)
        self.after(0, _update)


if __name__ == "__main__":
    # 관리자 권한이 아닐 경우 Windows UAC 승격 요청 (에픽세븐 등 관리자 게임 제어 필수)
    request_admin_elevation()

    app = MacroApp()
    app.mainloop()
