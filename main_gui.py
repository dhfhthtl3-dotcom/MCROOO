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

from window_capture import get_window_list, capture_window, get_last_capture_error
from detector import MultiTargetDetector, TargetItem
from clicker import dispatch_click
from macro_core import MacroEngine
from macro_package import export_macro_package, inspect_and_verify_package, import_macro_package

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


class TargetPinpointDialog(ctk.CTkToplevel):
    """
    템플릿 이미지 내 특정 클릭 지점을 마우스로 콕 찍어 지정하는 대화상자
    """
    def __init__(self, parent, target: TargetItem, on_save_offset):
        super().__init__(parent)
        self.title(f"🎯 클릭 위치 지정 - '{target.name}'")
        self.geometry("480x560")
        self.attributes("-topmost", True)
        self.resizable(False, False)

        self.target = target
        self.on_save_offset = on_save_offset

        self.orig_img = target.template_img.copy()
        self.img_h, self.img_w = self.orig_img.shape[:2]

        self.current_off_x = target.offset_x
        self.current_off_y = target.offset_y

        # 캔버스 배율 계산
        max_w, max_h = 420, 260
        zoom_w = max_w / max(1, self.img_w)
        zoom_h = max_h / max(1, self.img_h)
        self.zoom = min(zoom_w, zoom_h)
        if self.zoom < 1.0:
            self.zoom = 1.0
        elif self.zoom > 6.0:
            self.zoom = 6.0

        self.disp_w = max(40, int(self.img_w * self.zoom))
        self.disp_h = max(40, int(self.img_h * self.zoom))

        self.photo_img = None
        self.setup_ui()

    def setup_ui(self):
        ctk.CTkLabel(
            self,
            text=f"🎯 [{self.target.name}] 클릭 지점 설정",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(16, 4))

        ctk.CTkLabel(
            self,
            text="이미지 위에서 클릭할 위치를 마우스로 직접 찍으세요.\n(우측 상단 닫기 X버튼, 체크박스 등 특정 부위 클릭 시 유용)",
            font=ctk.CTkFont(size=12),
            text_color="#aaaaaa"
        ).pack(pady=(0, 10))

        # 이미지 캔버스 프레임
        canvas_frame = ctk.CTkFrame(self, fg_color="#181822")
        canvas_frame.pack(padx=20, pady=4)

        self.canvas = tk.Canvas(
            canvas_frame,
            width=self.disp_w,
            height=self.disp_h,
            bg="#111116",
            highlightthickness=1,
            highlightbackground="#34495e",
            cursor="crosshair"
        )
        self.canvas.pack(padx=4, pady=4)
        self.canvas.bind("<Button-1>", self.on_canvas_click)

        # 상태 라벨
        self.status_lbl = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f39c12"
        )
        self.status_lbl.pack(pady=(8, 4))

        coord_box = ctk.CTkFrame(self, fg_color="#20202e", corner_radius=8)
        coord_box.pack(fill="x", padx=25, pady=6)

        c_row = ctk.CTkFrame(coord_box, fg_color="transparent")
        c_row.pack(padx=10, pady=8)

        ctk.CTkLabel(c_row, text="오프셋 X:", font=ctk.CTkFont(size=12)).pack(side="left", padx=4)
        self.entry_x = ctk.CTkEntry(c_row, width=60, height=28)
        self.entry_x.pack(side="left", padx=2)
        self.entry_x.bind("<KeyRelease>", self.on_manual_entry)

        ctk.CTkLabel(c_row, text="px  |  Y:", font=ctk.CTkFont(size=12)).pack(side="left", padx=4)
        self.entry_y = ctk.CTkEntry(c_row, width=60, height=28)
        self.entry_y.pack(side="left", padx=2)
        self.entry_y.bind("<KeyRelease>", self.on_manual_entry)
        ctk.CTkLabel(c_row, text="px", font=ctk.CTkFont(size=12)).pack(side="left", padx=2)

        ctk.CTkButton(
            c_row,
            text="중앙(0,0)",
            width=70,
            height=26,
            fg_color="#444455",
            hover_color="#555566",
            command=self.reset_to_center
        ).pack(side="left", padx=(10, 0))

        # 하단 버튼
        btn_bar = ctk.CTkFrame(self, fg_color="transparent")
        btn_bar.pack(fill="x", padx=25, pady=(15, 10))

        ctk.CTkButton(
            btn_bar,
            text="취소",
            width=100,
            height=36,
            fg_color="#555566",
            hover_color="#666677",
            command=self.destroy
        ).pack(side="left")

        ctk.CTkButton(
            btn_bar,
            text="✅ 저장 및 적용",
            height=36,
            fg_color="#2ecc71",
            hover_color="#27ae60",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.save_and_close
        ).pack(side="right", fill="x", expand=True, padx=(10, 0))

        self.update_display()

    def update_display(self):
        # 템플릿 이미지 리사이즈
        img_rgb = cv2.cvtColor(self.orig_img, cv2.COLOR_BGR2RGB)
        resample_mode = Image.Resampling.NEAREST if self.zoom > 1.5 else Image.Resampling.LANCZOS
        pil_img = Image.fromarray(img_rgb).resize((self.disp_w, self.disp_h), resample_mode)
        self.photo_img = ImageTk.PhotoImage(pil_img)

        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo_img)

        # 중심선 (약한 십자선)
        cx = self.disp_w / 2.0
        cy = self.disp_h / 2.0
        self.canvas.create_line(cx, 0, cx, self.disp_h, fill="#444455", dash=(2, 2))
        self.canvas.create_line(0, cy, self.disp_w, cy, fill="#444455", dash=(2, 2))

        # 현재 오프셋 지점 계산
        pin_x = int((self.img_w / 2.0 + self.current_off_x) * self.zoom)
        pin_y = int((self.img_h / 2.0 + self.current_off_y) * self.zoom)

        # 조준 마커 그리기 (빨간 원 + 십자선)
        r = 6
        self.canvas.create_oval(pin_x - r, pin_y - r, pin_x + r, pin_y + r, outline="#e74c3c", width=2, tags="marker")
        self.canvas.create_line(pin_x - r - 4, pin_y, pin_x + r + 4, pin_y, fill="#e74c3c", width=2, tags="marker")
        self.canvas.create_line(pin_x, pin_y - r - 4, pin_x, pin_y + r + 4, fill="#e74c3c", width=2, tags="marker")

        # 상태 및 텍스트박스 업데이트
        pos_desc = "정중앙 클릭" if (self.current_off_x == 0 and self.current_off_y == 0) else f"오프셋 적용 (X: {self.current_off_x:+d}px, Y: {self.current_off_y:+d}px)"
        self.status_lbl.configure(text=f"선택 위치: {pos_desc}")

        self.entry_x.delete(0, "end")
        self.entry_x.insert(0, str(self.current_off_x))
        self.entry_y.delete(0, "end")
        self.entry_y.insert(0, str(self.current_off_y))

    def on_canvas_click(self, event):
        orig_x = int(event.x / self.zoom)
        orig_y = int(event.y / self.zoom)
        orig_x = max(0, min(self.img_w - 1, orig_x))
        orig_y = max(0, min(self.img_h - 1, orig_y))

        self.current_off_x = orig_x - self.img_w // 2
        self.current_off_y = orig_y - self.img_h // 2
        self.update_display()

    def on_manual_entry(self, event=None):
        try:
            self.current_off_x = int(self.entry_x.get())
            self.current_off_y = int(self.entry_y.get())
            pin_x = int((self.img_w / 2.0 + self.current_off_x) * self.zoom)
            pin_y = int((self.img_h / 2.0 + self.current_off_y) * self.zoom)
            self.canvas.delete("marker")
            r = 6
            self.canvas.create_oval(pin_x - r, pin_y - r, pin_x + r, pin_y + r, outline="#e74c3c", width=2, tags="marker")
            self.canvas.create_line(pin_x - r - 4, pin_y, pin_x + r + 4, pin_y, fill="#e74c3c", width=2, tags="marker")
            self.canvas.create_line(pin_x, pin_y - r - 4, pin_x, pin_y + r + 4, fill="#e74c3c", width=2, tags="marker")
            pos_desc = "정중앙 클릭" if (self.current_off_x == 0 and self.current_off_y == 0) else f"오프셋 적용 (X: {self.current_off_x:+d}px, Y: {self.current_off_y:+d}px)"
            self.status_lbl.configure(text=f"선택 위치: {pos_desc}")
        except ValueError:
            pass

    def reset_to_center(self):
        self.current_off_x = 0
        self.current_off_y = 0
        self.update_display()

    def save_and_close(self):
        self.on_save_offset(self.target.id, self.current_off_x, self.current_off_y)
        self.destroy()


class ImportVerifyDialog(ctk.CTkToplevel):
    """
    매크로 패키지(.gmac) 4단계 보안 검증 및 시각적 미리보기 대화상자
    - 악성 스크립트/경로 조작 자동 차단 결과 시각화
    - 포함된 버튼 템플릿 썸네일과 이름, 일치율을 눈으로 직접 확인 후 승인
    """
    def __init__(self, parent, package_path: str, on_import_success):
        super().__init__(parent)
        self.title("🛡️ 매크로 패키지 보안 검증 및 가져오기")
        self.geometry("580x680")
        self.attributes("-topmost", True)
        self.resizable(False, False)

        self.package_path = package_path
        self.on_import_success = on_import_success
        self.thumb_refs = []

        # 4단계 보안 검사 수행
        self.verify_result = inspect_and_verify_package(package_path)
        self.setup_ui()

    def setup_ui(self):
        # 상단 타이틀
        ctk.CTkLabel(
            self,
            text="🛡️ 매크로 패키지 보안 검증 보고서",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(16, 6))

        # 보안 상태 배너
        if self.verify_result["is_safe"]:
            status_banner = ctk.CTkFrame(self, fg_color="#1e4620", corner_radius=8)
            status_banner.pack(fill="x", padx=20, pady=6)
            ctk.CTkLabel(
                status_banner,
                text="✅ 보안 검증 통과: 악성 스크립트 없음 / 안전한 매크로 확인됨",
                text_color="#2ecc71",
                font=ctk.CTkFont(size=13, weight="bold")
            ).pack(padx=12, pady=10)
        else:
            status_banner = ctk.CTkFrame(self, fg_color="#4d1b1b", corner_radius=8)
            status_banner.pack(fill="x", padx=20, pady=6)
            ctk.CTkLabel(
                status_banner,
                text="🚨 보안 경고: 위험한 요소가 감지되어 등록이 차단되었습니다!",
                text_color="#e74c3c",
                font=ctk.CTkFont(size=13, weight="bold")
            ).pack(padx=12, pady=8)

            err_text = "\n".join([f"• {e}" for e in self.verify_result["errors"]])
            err_box = ctk.CTkTextbox(self, height=100, fg_color="#2b1414", text_color="#ff7979", font=ctk.CTkFont(size=12))
            err_box.insert("1.0", err_text)
            err_box.configure(state="disabled")
            err_box.pack(fill="x", padx=20, pady=8)

            ctk.CTkButton(self, text="닫기", width=120, command=self.destroy).pack(pady=15)
            return

        meta = self.verify_result["meta"]
        images = self.verify_result["images"]
        targets = meta.get("targets", [])

        # 프로필 요약 정보 프레임
        summary_frame = ctk.CTkFrame(self, fg_color="#252535", corner_radius=8)
        summary_frame.pack(fill="x", padx=20, pady=6)

        # 프로필 이름 입력
        name_row = ctk.CTkFrame(summary_frame, fg_color="transparent")
        name_row.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(name_row, text="매크로 이름:", width=90, anchor="w", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.name_entry = ctk.CTkEntry(name_row, height=28)
        self.name_entry.insert(0, meta.get("name", "가져온 매크로"))
        self.name_entry.pack(side="left", fill="x", expand=True)

        # 메타 태그 요약
        info_row = ctk.CTkFrame(summary_frame, fg_color="transparent")
        info_row.pack(fill="x", padx=14, pady=(4, 10))
        target_win = meta.get("target_window_title") or "미지정"
        click_m = meta.get("click_mode", "hardware").upper()
        ctk.CTkLabel(
            info_row,
            text=f"🎯 대상 창: {target_win}  |  ⚡ 모드: {click_m}  |  버튼: {len(targets)}개",
            text_color="#aaaabb",
            font=ctk.CTkFont(size=12)
        ).pack(side="left")

        # 버튼 미리보기 섹션 라벨
        ctk.CTkLabel(
            self,
            text="👁️ 포함된 버튼 템플릿 실물 검증 (썸네일 확인):",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        ).pack(fill="x", padx=22, pady=(10, 4))

        # 버튼 스크롤 리스트
        scroll = ctk.CTkScrollableFrame(self, height=260, fg_color="#181822")
        scroll.pack(fill="both", expand=True, padx=20, pady=4)

        if not targets:
            ctk.CTkLabel(scroll, text="포함된 버튼이 없습니다.", text_color="gray").pack(pady=30)
        else:
            for t in targets:
                card = ctk.CTkFrame(scroll, fg_color="#222230", corner_radius=6)
                card.pack(fill="x", pady=4, padx=4)

                t_id = t.get("id")
                if t_id in images:
                    img_bgr = images[t_id]
                    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                    pil_img = Image.fromarray(img_rgb)
                    th = 32
                    tw = int(pil_img.width * (th / pil_img.height))
                    pil_thumb = pil_img.resize((max(1, tw), th), Image.Resampling.LANCZOS)
                    ctk_thumb = ctk.CTkImage(light_image=pil_thumb, dark_image=pil_thumb, size=(tw, th))
                    self.thumb_refs.append(ctk_thumb)
                    ctk.CTkLabel(card, image=ctk_thumb, text="").pack(side="left", padx=8, pady=6)

                t_info = ctk.CTkFrame(card, fg_color="transparent")
                t_info.pack(side="left", fill="both", expand=True, padx=6)
                ctk.CTkLabel(t_info, text=t.get("name", "버튼"), font=ctk.CTkFont(size=13, weight="bold"), anchor="w").pack(fill="x")
                thresh = int(t.get("threshold", 0.85) * 100)
                cd = t.get("cooldown", 2.0)
                res_info = f" | {t.get('base_width')}x{t.get('base_height')}" if t.get('base_width', 0) > 0 else ""
                ctk.CTkLabel(t_info, text=f"일치율: {thresh}% | 쿨다운: {cd}초{res_info}", font=ctk.CTkFont(size=11), text_color="gray", anchor="w").pack(fill="x")

        # 하단 액션 버튼
        btn_bar = ctk.CTkFrame(self, fg_color="transparent")
        btn_bar.pack(fill="x", padx=20, pady=16)

        ctk.CTkButton(
            btn_bar,
            text="취소",
            width=100,
            height=36,
            fg_color="#555566",
            hover_color="#666677",
            command=self.destroy
        ).pack(side="left")

        ctk.CTkButton(
            btn_bar,
            text="✅ 안전 확인 및 매크로 등록하기",
            height=36,
            fg_color="#2ecc71",
            hover_color="#27ae60",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.confirm_import
        ).pack(side="right", fill="x", expand=True, padx=(10, 0))

    def confirm_import(self):
        new_name = self.name_entry.get().strip()
        self.on_import_success(self.package_path, new_name)
        self.destroy()


class MacroApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("🎯 다중 버튼 감지 및 하이브리드 자동 클릭 매크로 v2.4.2 (초고속 최적화)")
        self.geometry("1240x820")
        self.minsize(1100, 720)

        self.engine = MacroEngine()
        self.windows_data = []
        self.last_frame: Optional[np.ndarray] = None
        self.target_cards = {}
        self._profile_map: Dict[str, str] = {}
        self.is_picking_autotap_point: bool = False

        # 미리보기 렌더링 최적화 상태값 (단일 버퍼 및 디바운서)
        self._pending_frame: Optional[np.ndarray] = None
        self._pending_detections: Optional[list] = None
        self._preview_render_scheduled: bool = False
        self._preview_canvas_img_id: Optional[int] = None
        self._canvas_resize_timer: Optional[str] = None

        # 엔진 콜백 연결
        self.engine.on_log = self.append_log
        self.engine.on_frame_update = self.on_frame_updated
        self.engine.on_status_change = self.on_status_updated

        self.setup_ui()
        self.refresh_profile_list()
        self.refresh_window_list()
        self.render_target_list()
        self.sync_autotap_ui()

    def setup_ui(self):
        # 1. 최상단 헤더 바
        header = ctk.CTkFrame(self, height=50, corner_radius=0, fg_color="#181824")
        header.pack(fill="x", side="top")

        ctk.CTkLabel(
            header,
            text="🎯 Multi-Button Frame Detector & Hybrid Clicker v2.4.2",
            font=ctk.CTkFont(size=17, weight="bold")
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

        # 1-1. 매크로 프로필 제어 바
        profile_bar = ctk.CTkFrame(self, height=44, corner_radius=0, fg_color="#202030")
        profile_bar.pack(fill="x", side="top", pady=(1, 0))

        ctk.CTkLabel(
            profile_bar,
            text="📋 매크로 프로필:",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(side="left", padx=(20, 8), pady=6)

        # 프로필 선택 콤보박스
        self.profile_combo_var = ctk.StringVar()
        self.profile_combo = ctk.CTkComboBox(
            profile_bar,
            variable=self.profile_combo_var,
            width=240,
            height=30,
            command=self.on_profile_selected
        )
        self.profile_combo.pack(side="left", padx=4, pady=6)

        # 프로필 관리 버튼들
        ctk.CTkButton(
            profile_bar,
            text="➕ 새 매크로",
            width=90,
            height=28,
            fg_color="#3498db",
            hover_color="#2980b9",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.on_create_profile_dialog
        ).pack(side="left", padx=4, pady=6)

        ctk.CTkButton(
            profile_bar,
            text="✏️ 이름 변경",
            width=85,
            height=28,
            fg_color="#444455",
            hover_color="#555566",
            font=ctk.CTkFont(size=12),
            command=self.on_rename_profile_dialog
        ).pack(side="left", padx=4, pady=6)

        ctk.CTkButton(
            profile_bar,
            text="💾 복제",
            width=65,
            height=28,
            fg_color="#444455",
            hover_color="#555566",
            font=ctk.CTkFont(size=12),
            command=self.on_duplicate_profile_dialog
        ).pack(side="left", padx=4, pady=6)

        ctk.CTkButton(
            profile_bar,
            text="🗑️ 삭제",
            width=65,
            height=28,
            fg_color="#c0392b",
            hover_color="#962d22",
            font=ctk.CTkFont(size=12),
            command=self.on_delete_profile_confirm
        ).pack(side="left", padx=4, pady=6)

        ctk.CTkLabel(profile_bar, text="|", text_color="#555566").pack(side="left", padx=6, pady=6)

        ctk.CTkButton(
            profile_bar,
            text="📤 내보내기",
            width=85,
            height=28,
            fg_color="#8e44ad",
            hover_color="#732d91",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.on_export_package
        ).pack(side="left", padx=4, pady=6)

        ctk.CTkButton(
            profile_bar,
            text="📥 가져오기",
            width=85,
            height=28,
            fg_color="#27ae60",
            hover_color="#1e8449",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.on_import_package
        ).pack(side="left", padx=4, pady=6)

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

        # 5. 화면 연속 탭 (오토클릭)
        ctk.CTkLabel(col1, text="5. 🔄 화면 연속 탭 (오토클릭)", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 4))
        autotap_card = ctk.CTkFrame(col1, fg_color="#20202e", corner_radius=8)
        autotap_card.pack(fill="x", padx=12, pady=2)

        # 활성화 체크박스
        self.autotap_enabled_var = ctk.BooleanVar(value=False)
        self.autotap_chk = ctk.CTkCheckBox(
            autotap_card,
            text="화면 계속 누르기 활성화",
            variable=self.autotap_enabled_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.on_autotap_toggle
        )
        self.autotap_chk.pack(anchor="w", padx=10, pady=(8, 4))

        # 설정 행 (주기 + 모드)
        at_row1 = ctk.CTkFrame(autotap_card, fg_color="transparent")
        at_row1.pack(fill="x", padx=10, pady=2)

        ctk.CTkLabel(at_row1, text="주기:", width=32, anchor="w", font=ctk.CTkFont(size=11)).pack(side="left")
        self.autotap_interval_var = ctk.StringVar(value="0.5")
        self.autotap_interval_entry = ctk.CTkEntry(at_row1, textvariable=self.autotap_interval_var, width=45, height=26)
        self.autotap_interval_entry.pack(side="left", padx=(0, 2))
        self.autotap_interval_entry.bind("<KeyRelease>", self.on_autotap_setting_changed)
        ctk.CTkLabel(at_row1, text="초", font=ctk.CTkFont(size=11), text_color="#aaaaaa").pack(side="left", padx=(0, 6))

        self.autotap_mode_var = ctk.StringVar(value="버튼 없을 때만 탭")
        self.autotap_mode_combo = ctk.CTkComboBox(
            at_row1,
            variable=self.autotap_mode_var,
            values=["버튼 없을 때만 탭", "항상 계속 탭"],
            width=135,
            height=26,
            command=self.on_autotap_mode_changed
        )
        self.autotap_mode_combo.pack(side="right")

        # 좌표 설정 행
        at_row2 = ctk.CTkFrame(autotap_card, fg_color="transparent")
        at_row2.pack(fill="x", padx=10, pady=(4, 8))

        self.autotap_pos_lbl = ctk.CTkLabel(at_row2, text="위치: 창 중앙", font=ctk.CTkFont(size=11), text_color="#f39c12", width=95, anchor="w")
        self.autotap_pos_lbl.pack(side="left")

        self.btn_pick_tap_pos = ctk.CTkButton(
            at_row2,
            text="🎯 화면에서 찍기",
            width=88,
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#34495e",
            hover_color="#2c3e50",
            command=self.start_pick_autotap_point
        )
        self.btn_pick_tap_pos.pack(side="left", padx=2)

        ctk.CTkButton(
            at_row2,
            text="중앙",
            width=42,
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#444455",
            hover_color="#555566",
            command=self.reset_autotap_point
        ).pack(side="right")

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
        self.preview_canvas.bind("<Configure>", self.on_preview_canvas_resize)
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

    # ------------------ 프로필 관리 이벤트 ------------------

    def refresh_profile_list(self):
        profiles = self.engine.get_profile_list()
        self._profile_map = {p["name"]: p["id"] for p in profiles}
        names = [p["name"] for p in profiles]
        self.profile_combo.configure(values=names)

        active_p = self.engine.get_active_profile()
        self.profile_combo_var.set(active_p.name)

    def on_profile_selected(self, selected_name: str):
        if not selected_name:
            return
        p_id = self._profile_map.get(selected_name)
        if not p_id or p_id == self.engine.get_active_profile().id:
            return

        if self.engine.is_running:
            if not messagebox.askyesno("매크로 실행 중", "프로필을 전환하면 현재 실행 중인 매크로가 정지됩니다. 계속하시겠습니까?"):
                self.profile_combo_var.set(self.engine.get_active_profile().name)
                return
            self.stop_macro()

        success = self.engine.switch_profile(p_id)
        if success:
            # 프로필 설정값 GUI에 동기화
            self.click_mode_var.set(self.engine.click_mode)
            self.offset_y_var.set(str(self.engine.global_offset_y))
            self.render_target_list()
            self.refresh_profile_list()
            self.sync_autotap_ui()
            self.append_log(f"📋 매크로 전환: '{selected_name}' (등록 타겟 {len(self.engine.get_all_targets())}개)")

            # 해당 프로필에 저장된 윈도우 제목이 있고 현재 창 목록에 있으면 자동 선택
            active_p = self.engine.get_active_profile()
            if active_p.target_window_title:
                for idx, w in enumerate(self.windows_data):
                    if active_p.target_window_title in w["title"]:
                        sel_str = f"[{w['hwnd']}] {w['title'][:32]} ({w['width']}x{w['height']})"
                        self.win_combobox.set(sel_str)
                        self.engine.set_target_window(w['hwnd'])
                        self.append_log(f"타겟 창 자동 복원: {w['title']}")
                        break

    def sync_autotap_ui(self):
        self.autotap_enabled_var.set(self.engine.auto_tap_enabled)
        self.autotap_interval_var.set(str(self.engine.auto_tap_interval))
        self.autotap_mode_var.set("버튼 없을 때만 탭" if self.engine.auto_tap_mode == "when_idle" else "항상 계속 탭")
        if self.engine.auto_tap_point:
            self.autotap_pos_lbl.configure(text=f"위치: ({self.engine.auto_tap_point[0]}, {self.engine.auto_tap_point[1]})")
        else:
            self.autotap_pos_lbl.configure(text="위치: 창 중앙")

    def on_autotap_toggle(self):
        val = self.autotap_enabled_var.get()
        self.engine.auto_tap_enabled = val
        self.engine.save_targets()
        status_txt = "활성화" if val else "비활성화"
        self.append_log(f"🔄 화면 연속 탭(오토클릭) {status_txt}")

    def on_autotap_setting_changed(self, event=None):
        try:
            val = float(self.autotap_interval_var.get())
            if val >= 0.05:
                self.engine.auto_tap_interval = val
                self.engine.save_targets()
        except ValueError:
            pass

    def on_autotap_mode_changed(self, choice):
        mode = "when_idle" if choice == "버튼 없을 때만 탭" else "always"
        self.engine.auto_tap_mode = mode
        self.engine.save_targets()
        self.append_log(f"🔄 화면 연속 탭 모드 변경: {choice}")

    def start_pick_autotap_point(self):
        self.is_picking_autotap_point = True
        self.btn_pick_tap_pos.configure(text="👉 화면 클릭 대기", fg_color="#e67e22")
        self.append_log("🎯 우측 미리보기 화면에서 화면 연속 탭을 누를 위치를 마우스로 클릭하세요.")

    def reset_autotap_point(self):
        self.is_picking_autotap_point = False
        self.engine.auto_tap_point = None
        self.engine.save_targets()
        self.btn_pick_tap_pos.configure(text="🎯 화면에서 찍기", fg_color="#34495e")
        self.autotap_pos_lbl.configure(text="위치: 창 중앙")
        self.append_log("🔄 화면 연속 탭 위치를 '창 정중앙'으로 초기화했습니다.")

    def on_create_profile_dialog(self):
        dialog = ctk.CTkInputDialog(
            text="새로 생성할 매크로 이름을 입력하세요:\n(예: 에픽세븐 토벌, 로스트아크 일퀘)",
            title="새 매크로 생성"
        )
        name = dialog.get_input()
        if name and name.strip():
            clean_name = name.strip()
            if clean_name in self._profile_map:
                messagebox.showwarning("경고", "이미 동일한 이름의 매크로가 존재합니다.")
                return

            new_p = self.engine.create_profile(clean_name)
            self.refresh_profile_list()
            self.render_target_list()
            self.append_log(f"✨ 새 매크로 생성 완료: '{new_p.name}'")

    def on_rename_profile_dialog(self):
        cur_p = self.engine.get_active_profile()
        dialog = ctk.CTkInputDialog(
            text=f"'{cur_p.name}'의 새 이름을 입력하세요:",
            title="매크로 이름 변경"
        )
        new_name = dialog.get_input()
        if new_name and new_name.strip():
            clean_name = new_name.strip()
            if clean_name == cur_p.name:
                return
            if clean_name in self._profile_map:
                messagebox.showwarning("경고", "이미 동일한 이름의 매크로가 존재합니다.")
                return

            self.engine.rename_profile(cur_p.id, clean_name)
            self.refresh_profile_list()
            self.append_log(f"✏️ 매크로 이름 변경: '{cur_p.name}' -> '{clean_name}'")

    def on_duplicate_profile_dialog(self):
        cur_p = self.engine.get_active_profile()
        dialog = ctk.CTkInputDialog(
            text=f"'{cur_p.name}'을(를) 복제할 새 매크로 이름:",
            title="매크로 복제"
        )
        new_name = dialog.get_input()
        if new_name and new_name.strip():
            clean_name = new_name.strip()
            new_p = self.engine.duplicate_profile(cur_p.id, clean_name)
            if new_p:
                self.refresh_profile_list()
                self.render_target_list()
                self.append_log(f"💾 매크로 복제 완료: '{new_p.name}' (타겟 {len(self.engine.get_all_targets())}개 복사됨)")

    def on_delete_profile_confirm(self):
        cur_p = self.engine.get_active_profile()
        if len(self.engine.get_profile_list()) <= 1:
            messagebox.showwarning("경고", "최소 1개의 매크로 프로필은 남아있어야 합니다.")
            return

        if messagebox.askyesno("삭제 확인", f"정말로 '{cur_p.name}' 매크로를 삭제하시겠습니까?\n(등록된 버튼 목록도 함께 삭제됩니다)"):
            self.engine.delete_profile(cur_p.id)
            self.refresh_profile_list()
            self.render_target_list()
            self.append_log(f"🗑️ 매크로 삭제 완료. 활성 매크로: '{self.engine.get_active_profile().name}'")

    def on_export_package(self):
        cur_p = self.engine.get_active_profile()
        default_filename = f"{cur_p.name}.gmac".replace(" ", "_")
        save_path = filedialog.asksaveasfilename(
            title="매크로 안전 공유 패키지 내보내기",
            initialfile=default_filename,
            defaultextension=".gmac",
            filetypes=[("GameMacro Package", "*.gmac"), ("All Files", "*.*")]
        )
        if save_path:
            try:
                export_macro_package(cur_p, self.engine.TEMPLATES_DIR, save_path)
                messagebox.showinfo(
                    "내보내기 성공",
                    f"매크로가 안전한 단일 패키지(.gmac)로 내보내졌습니다!\n\n"
                    f"저장 파일: {os.path.basename(save_path)}\n"
                    f"포함 버튼: {len(cur_p.targets)}개\n\n"
                    "이 파일 하나만 다른 분에게 전송하시면 상대방도 바로 사용할 수 있습니다."
                )
                self.append_log(f"📤 매크로 패키지 내보내기 성공: {os.path.basename(save_path)}")
            except Exception as e:
                messagebox.showerror("내보내기 실패", f"파일 생성 중 오류가 발생했습니다:\n{e}")

    def on_import_package(self):
        open_path = filedialog.askopenfilename(
            title="매크로 패키지(.gmac) 가져오기",
            filetypes=[("GameMacro Package", "*.gmac"), ("All Files", "*.*")]
        )
        if open_path:
            ImportVerifyDialog(self, open_path, on_import_success=self.perform_import)

    def perform_import(self, package_path: str, custom_name: str):
        success, msg, new_profile = import_macro_package(
            package_filepath=package_path,
            profile_manager=self.engine.profile_manager,
            templates_dir=self.engine.TEMPLATES_DIR,
            custom_name=custom_name
        )
        if success and new_profile:
            self.engine.switch_profile(new_profile.id)
            self.refresh_profile_list()
            self.render_target_list()
            self.click_mode_var.set(self.engine.click_mode)
            self.offset_y_var.set(str(self.engine.global_offset_y))
            messagebox.showinfo("가져오기 완료", f"'{new_profile.name}' 매크로가 안전하게 등록되었습니다!\n(버튼 {len(new_profile.targets)}개 로드됨)")
            self.append_log(f"📥 {msg}")
        else:
            messagebox.showerror("가져오기 실패", msg)

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
            off_tag = f" | 🎯 {t.offset_x:+d},{t.offset_y:+d}px" if (t.offset_x != 0 or t.offset_y != 0) else ""
            ctk.CTkLabel(
                title_box,
                text=f"우선순위: {t.priority} | 쿨다운: {t.cooldown}초{res_tag}{off_tag}",
                font=ctk.CTkFont(size=10),
                text_color="#f39c12" if off_tag else "gray",
                anchor="w"
            ).pack(fill="x")

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

            # 하단: 일치율 슬라이더 + 오프셋 버튼 + 삭제 버튼
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

            # 클릭 위치 지정 버튼
            pin_btn = ctk.CTkButton(
                bottom_row,
                text="🎯",
                width=28,
                height=24,
                fg_color="#d35400" if (t.offset_x != 0 or t.offset_y != 0) else "#34495e",
                hover_color="#ba4a00" if (t.offset_x != 0 or t.offset_y != 0) else "#2c3e50",
                command=lambda target=t: self.open_pinpoint_dialog(target)
            )
            pin_btn.pack(side="right", padx=(4, 0))

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

    def open_pinpoint_dialog(self, target: TargetItem):
        def on_saved(tid, off_x, off_y):
            self.engine.update_target_offset(tid, off_x, off_y)
            self.render_target_list()
            self.append_log(f"🎯 [{target.name}] 클릭 위치 변경 완료: (중심 기준 {off_x:+d}px, {off_y:+d}px)")

        TargetPinpointDialog(self, target, on_save_offset=on_saved)

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
            err = get_last_capture_error()
            msg = f"대상 창 화면을 캡처할 수 없습니다.\n({err})" if err else "대상 창 화면을 캡처할 수 없습니다."
            messagebox.showerror("오류", msg)
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
            err = get_last_capture_error()
            msg = f"창 캡처 실패\n({err})" if err else "창 캡처 실패"
            messagebox.showerror("오류", msg)
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
            real_x = int(click_x / scale)
            real_y = int(click_y / scale)

            if getattr(self, "is_picking_autotap_point", False):
                self.is_picking_autotap_point = False
                self.engine.auto_tap_point = (real_x, real_y)
                self.engine.save_targets()
                self.btn_pick_tap_pos.configure(text="🎯 화면에서 찍기", fg_color="#34495e")
                self.autotap_pos_lbl.configure(text=f"위치: ({real_x}, {real_y})")
                self.append_log(f"🔄 화면 연속 탭 위치 지정 완료: ({real_x}, {real_y})")
                return

            real_x += self.engine.global_offset_x
            real_y += self.engine.global_offset_y
            mode = self.click_mode_var.get()
            self.append_log(f"🖱️ 캔버스 클릭 -> 대상 창 ({real_x}, {real_y}) 좌표 [{mode.upper()}] 전송")
            dispatch_click(self.engine.hwnd, real_x, real_y, mode=mode)

    # ------------------ 일반 이벤트 핸들러 ------------------

    def append_log(self, text: str):
        def _append():
            timestamp = time.strftime("[%H:%M:%S] ")
            self.log_textbox.insert("end", timestamp + text + "\n")
            # 로그가 500줄을 초과하면 상위 100줄을 정리하여 메모리/UI 리플로우 지연 방지
            try:
                num_lines = int(self.log_textbox.index("end-1c").split(".")[0])
                if num_lines > 500:
                    self.log_textbox.delete("1.0", f"{num_lines - 400}.0")
            except Exception:
                pass
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

        # 활성 프로필에 기억된 창 제목이 있다면 우선 매칭
        active_p = self.engine.get_active_profile()
        target_idx = 0
        if active_p.target_window_title and self.windows_data:
            for idx, w in enumerate(self.windows_data):
                if active_p.target_window_title in w['title']:
                    target_idx = idx
                    break

        self.win_combobox.set(titles[target_idx])
        if self.windows_data:
            self.on_window_selected(titles[target_idx])
        self.append_log(f"윈도우 목록 갱신 완료 ({len(self.windows_data)}개)")

    def on_window_selected(self, choice_str):
        for w in self.windows_data:
            key = f"[{w['hwnd']}]"
            if choice_str.startswith(key):
                self.engine.set_target_window(w['hwnd'])
                active_p = self.engine.get_active_profile()
                active_p.target_window_title = w['title']
                self.engine.profile_manager.save_active_profile()
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
            err = get_last_capture_error()
            msg = f"창 캡처에 실패했습니다.\n({err})" if err else "창 캡처에 실패했습니다."
            self.append_log(f"❌ {msg}")
            messagebox.showerror("오류", msg)

    def test_detect_once(self):
        if not self.engine.hwnd:
            messagebox.showwarning("경고", "먼저 대상 창을 선택하세요.")
            return

        frame = capture_window(self.engine.hwnd)
        if frame is None:
            err = get_last_capture_error()
            msg = f"화면 캡처 실패\n({err})" if err else "화면 캡처 실패"
            self.append_log(f"❌ {msg}")
            messagebox.showerror("오류", msg)
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

    def on_preview_canvas_resize(self, event):
        """윈도우 리사이즈 시 캔버스 갱신을 30ms 디바운스하여 마우스 드래그 렉을 완벽 차단"""
        if self.last_frame is not None:
            if self._canvas_resize_timer is not None:
                try:
                    self.after_cancel(self._canvas_resize_timer)
                except Exception:
                    pass
            self._canvas_resize_timer = self.after(30, self._redraw_cached_preview)

    def _redraw_cached_preview(self):
        self._canvas_resize_timer = None
        if self.last_frame is not None:
            self.display_screen_preview(self.last_frame)

    def display_screen_preview(self, frame_bgr: np.ndarray):
        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        if canvas_w <= 10 or canvas_h <= 10:
            canvas_w = 480
            canvas_h = 320

        fh, fw = frame_bgr.shape[:2]
        if fh <= 0 or fw <= 0:
            return

        scale = min(canvas_w / fw, canvas_h / fh)
        dw = max(1, int(fw * scale))
        dh = max(1, int(fh * scale))

        # OpenCV C++ 고속 리사이즈 (PIL LANCZOS 대비 8~10배 빠르고 UI 스레드 블로킹 해소)
        interp = cv2.INTER_AREA if (dw < fw and dh < fh) else cv2.INTER_LINEAR
        resized_bgr = cv2.resize(frame_bgr, (dw, dh), interpolation=interp)
        resized_rgb = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(resized_rgb)
        self.preview_canvas_img = ImageTk.PhotoImage(pil_img)

        offset_x = (canvas_w - dw) // 2
        offset_y = (canvas_h - dh) // 2

        # 캔버스 객체 재사용 (delete all 오버헤드 제거)
        if self._preview_canvas_img_id is None:
            self.preview_canvas.delete("all")
            self._preview_canvas_img_id = self.preview_canvas.create_image(
                offset_x, offset_y, anchor="nw", image=self.preview_canvas_img
            )
        else:
            self.preview_canvas.coords(self._preview_canvas_img_id, offset_x, offset_y)
            self.preview_canvas.itemconfig(self._preview_canvas_img_id, image=self.preview_canvas_img)

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
        # 단일 슬롯 버퍼로 프레임 드롭 처리 (창 크기 조절 중 이벤트 큐 적체 100% 방지)
        self._pending_frame = frame_bgr
        self._pending_detections = detections
        if not self._preview_render_scheduled:
            self._preview_render_scheduled = True
            self.after(15, self._process_pending_preview)

    def _process_pending_preview(self):
        self._preview_render_scheduled = False
        if self._pending_frame is None:
            return
        frame = self._pending_frame
        dets = self._pending_detections
        self._pending_frame = None
        self._pending_detections = None

        self.last_frame = frame
        vis = self.engine.detector.draw_detections(frame, dets) if dets else frame
        self.display_screen_preview(vis)

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
