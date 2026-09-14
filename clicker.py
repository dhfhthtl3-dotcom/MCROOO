"""
하이브리드 마우스 클릭 모듈 (Hybrid Click Engine v2.1)
- 가상 데스크톱 전역 절대 좌표(MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_ABSOLUTE) 지원
- SendInput 하드웨어 수준 원자적 마우스 이동 및 다운/업 이벤트 전송
- DPI 인식 및 다중 모니터 좌표 완벽 대응
"""

import time
import random
import ctypes
from ctypes import wintypes
import win32api
import win32gui
import win32con
import win32process
from typing import Tuple, Optional

# DPI 인식 설정
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

PUL = ctypes.POINTER(ctypes.c_ulong)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", INPUT_UNION)]


INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000


def make_lparam(x: int, y: int) -> int:
    return (int(y) << 16) | (int(x) & 0xFFFF)


def to_virtual_screen_absolute(screen_x: int, screen_y: int) -> Tuple[int, int]:
    """다중 모니터 및 가상 스크린 전체 해상도에 맞춘 0~65535 절대 좌표 변환"""
    v_left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    v_top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    v_width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    v_height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)

    if v_width <= 0:
        v_width = 1920
    if v_height <= 0:
        v_height = 1080

    abs_x = int((screen_x - v_left) * 65535 / v_width)
    abs_y = int((screen_y - v_top) * 65535 / v_height)
    return abs_x, abs_y


def send_hardware_click(
    hwnd: int,
    client_x: int,
    client_y: int,
    restore_cursor: bool = True,
    jitter: int = 1,
    hold_time: float = 0.04
) -> bool:
    """
    [모드 1: 초고속 하드웨어 클릭 - 권장]
    원자적 SendInput을 통해 마우스 이동과 클릭을 동시에 수행하고 원래 마우스 위치로 복귀합니다.
    """
    if not win32gui.IsWindow(hwnd):
        return False

    try:
        orig_x, orig_y = win32api.GetCursorPos()

        # 클라이언트 좌표 -> 화면 절대 좌표
        screen_x, screen_y = win32gui.ClientToScreen(hwnd, (client_x, client_y))

        if jitter > 0:
            screen_x += random.randint(-jitter, jitter)
            screen_y += random.randint(-jitter, jitter)

        abs_x, abs_y = to_virtual_screen_absolute(screen_x, screen_y)

        # 1. 커서 이동 (SetCursorPos + SendInput 결합으로 1픽셀 오차도 허용하지 않음)
        try:
            win32api.SetCursorPos((screen_x, screen_y))
        except Exception:
            pass

        flags_down = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_LEFTDOWN
        extra = ctypes.c_ulong(0)
        inp_down = INPUT()
        inp_down.type = INPUT_MOUSE
        inp_down.u.mi = MOUSEINPUT(abs_x, abs_y, 0, flags_down, 0, ctypes.pointer(extra))
        ctypes.windll.user32.SendInput(1, ctypes.pointer(inp_down), ctypes.sizeof(inp_down))

        # 누름 유지
        time.sleep(hold_time)

        # 2. 마우스 업
        flags_up = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_LEFTUP
        inp_up = INPUT()
        inp_up.type = INPUT_MOUSE
        inp_up.u.mi = MOUSEINPUT(abs_x, abs_y, 0, flags_up, 0, ctypes.pointer(extra))
        ctypes.windll.user32.SendInput(1, ctypes.pointer(inp_up), ctypes.sizeof(inp_up))

        # 3. 원래 마우스 커서 위치 복원
        if restore_cursor:
            time.sleep(0.01)
            try:
                win32api.SetCursorPos((orig_x, orig_y))
            except Exception:
                pass
            orig_abs_x, orig_abs_y = to_virtual_screen_absolute(orig_x, orig_y)
            inp_restore = INPUT()
            inp_restore.type = INPUT_MOUSE
            inp_restore.u.mi = MOUSEINPUT(
                orig_abs_x, orig_abs_y, 0,
                MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                0, ctypes.pointer(extra)
            )
            ctypes.windll.user32.SendInput(1, ctypes.pointer(inp_restore), ctypes.sizeof(inp_restore))

        return True
    except Exception as e:
        print(f"[Clicker] SendInput 오류: {e}")
        return False


def send_activate_and_click(
    hwnd: int,
    client_x: int,
    client_y: int,
    restore_focus: bool = True,
    hold_time: float = 0.04
) -> bool:
    """[모드 2: 창 활성화 후 클릭]"""
    if not win32gui.IsWindow(hwnd):
        return False

    try:
        prev_hwnd = win32gui.GetForegroundWindow()

        # 창 복원 및 전면 활성화
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.04)

        # 하드웨어 클릭 실행
        send_hardware_click(hwnd, client_x, client_y, restore_cursor=True, hold_time=hold_time)

        # 이전 포커스 복원
        if restore_focus and prev_hwnd and prev_hwnd != hwnd and win32gui.IsWindow(prev_hwnd):
            time.sleep(0.04)
            try:
                win32gui.SetForegroundWindow(prev_hwnd)
            except Exception:
                pass

        return True
    except Exception as e:
        print(f"[Clicker] ActivateClick 오류: {e}")
        return False


def send_background_postmessage(
    hwnd: int,
    client_x: int,
    client_y: int,
    jitter: int = 1,
    hold_time: float = 0.04
) -> bool:
    """[모드 3: 비활성 백그라운드 클릭]"""
    if not win32gui.IsWindow(hwnd):
        return False

    try:
        actual_x = client_x + random.randint(-jitter, jitter) if jitter > 0 else client_x
        actual_y = client_y + random.randint(-jitter, jitter) if jitter > 0 else client_y
        lparam = make_lparam(actual_x, actual_y)

        win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
        time.sleep(0.01)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
        time.sleep(hold_time)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
        return True
    except Exception as e:
        print(f"[Clicker] PostMessage 오류: {e}")
        return False


def send_hardware_drag(
    hwnd: int,
    client_x1: int,
    client_y1: int,
    client_x2: int,
    client_y2: int,
    duration: float = 0.35,
    steps: int = 14,
    restore_cursor: bool = True
) -> bool:
    """
    [하드웨어 수준 마우스 드래그 / 스와이프]
    SendInput을 통해 (client_x1, client_y1)부터 (client_x2, client_y2)까지
    부드러운 다단계 보간 드래그를 수행하고 마우스 커서를 원위치로 복귀시킵니다.
    """
    if not win32gui.IsWindow(hwnd):
        return False

    try:
        orig_x, orig_y = win32api.GetCursorPos()

        # 화면 절대 좌표로 변환
        screen_x1, screen_y1 = win32gui.ClientToScreen(hwnd, (client_x1, client_y1))
        screen_x2, screen_y2 = win32gui.ClientToScreen(hwnd, (client_x2, client_y2))

        # 1. 시작점으로 커서 이동
        try:
            win32api.SetCursorPos((screen_x1, screen_y1))
        except Exception:
            pass

        abs_x1, abs_y1 = to_virtual_screen_absolute(screen_x1, screen_y1)
        extra = ctypes.c_ulong(0)
        inp_move = INPUT()
        inp_move.type = INPUT_MOUSE
        inp_move.u.mi = MOUSEINPUT(
            abs_x1, abs_y1, 0,
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            0, ctypes.pointer(extra)
        )
        ctypes.windll.user32.SendInput(1, ctypes.pointer(inp_move), ctypes.sizeof(inp_move))
        time.sleep(0.02)

        # 2. 마우스 왼쪽 버튼 다운
        inp_down = INPUT()
        inp_down.type = INPUT_MOUSE
        inp_down.u.mi = MOUSEINPUT(
            abs_x1, abs_y1, 0,
            MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_LEFTDOWN,
            0, ctypes.pointer(extra)
        )
        ctypes.windll.user32.SendInput(1, ctypes.pointer(inp_down), ctypes.sizeof(inp_down))
        time.sleep(0.02)

        # 3. 보간 이동 (Linear Interpolation Drag)
        step_delay = max(0.005, duration / max(1, steps))
        for step in range(1, steps + 1):
            t = step / float(steps)
            cur_sx = int(screen_x1 + (screen_x2 - screen_x1) * t)
            cur_sy = int(screen_y1 + (screen_y2 - screen_y1) * t)

            try:
                win32api.SetCursorPos((cur_sx, cur_sy))
            except Exception:
                pass

            cur_abs_x, cur_abs_y = to_virtual_screen_absolute(cur_sx, cur_sy)
            inp_step = INPUT()
            inp_step.type = INPUT_MOUSE
            inp_step.u.mi = MOUSEINPUT(
                cur_abs_x, cur_abs_y, 0,
                MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                0, ctypes.pointer(extra)
            )
            ctypes.windll.user32.SendInput(1, ctypes.pointer(inp_step), ctypes.sizeof(inp_step))
            time.sleep(step_delay)

        # 4. 마우스 왼쪽 버튼 업
        abs_x2, abs_y2 = to_virtual_screen_absolute(screen_x2, screen_y2)
        inp_up = INPUT()
        inp_up.type = INPUT_MOUSE
        inp_up.u.mi = MOUSEINPUT(
            abs_x2, abs_y2, 0,
            MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_LEFTUP,
            0, ctypes.pointer(extra)
        )
        ctypes.windll.user32.SendInput(1, ctypes.pointer(inp_up), ctypes.sizeof(inp_up))
        time.sleep(0.02)

        # 5. 원래 커서 복원
        if restore_cursor:
            time.sleep(0.01)
            try:
                win32api.SetCursorPos((orig_x, orig_y))
            except Exception:
                pass
            orig_abs_x, orig_abs_y = to_virtual_screen_absolute(orig_x, orig_y)
            inp_restore = INPUT()
            inp_restore.type = INPUT_MOUSE
            inp_restore.u.mi = MOUSEINPUT(
                orig_abs_x, orig_abs_y, 0,
                MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                0, ctypes.pointer(extra)
            )
            ctypes.windll.user32.SendInput(1, ctypes.pointer(inp_restore), ctypes.sizeof(inp_restore))

        return True
    except Exception as e:
        print(f"[Clicker] SendInput Drag 오류: {e}")
        return False


def send_postmessage_drag(
    hwnd: int,
    client_x1: int,
    client_y1: int,
    client_x2: int,
    client_y2: int,
    duration: float = 0.35,
    steps: int = 14
) -> bool:
    """[비활성 백그라운드 PostMessage 드래그]"""
    if not win32gui.IsWindow(hwnd):
        return False

    try:
        lp_start = make_lparam(client_x1, client_y1)
        win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lp_start)
        time.sleep(0.02)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp_start)
        time.sleep(0.02)

        step_delay = max(0.005, duration / max(1, steps))
        for step in range(1, steps + 1):
            t = step / float(steps)
            cur_x = int(client_x1 + (client_x2 - client_x1) * t)
            cur_y = int(client_y1 + (client_y2 - client_y1) * t)
            lp_cur = make_lparam(cur_x, cur_y)
            win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, lp_cur)
            time.sleep(step_delay)

        lp_end = make_lparam(client_x2, client_y2)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp_end)
        return True
    except Exception as e:
        print(f"[Clicker] PostMessage Drag 오류: {e}")
        return False


def dispatch_drag(
    hwnd: int,
    client_x1: int,
    client_y1: int,
    client_x2: int,
    client_y2: int,
    mode: str = "hardware",
    duration: float = 0.35,
    steps: int = 14
) -> bool:
    """사용자 선택 모드에 따라 마우스 드래그를 실행합니다."""
    if mode == "postmessage":
        return send_postmessage_drag(hwnd, client_x1, client_y1, client_x2, client_y2, duration=duration, steps=steps)
    elif mode == "activate":
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.04)
        except Exception:
            pass
        return send_hardware_drag(hwnd, client_x1, client_y1, client_x2, client_y2, duration=duration, steps=steps, restore_cursor=True)
    else:
        return send_hardware_drag(hwnd, client_x1, client_y1, client_x2, client_y2, duration=duration, steps=steps, restore_cursor=True)


def dispatch_click(
    hwnd: int,
    client_x: int,
    client_y: int,
    mode: str = "hardware",
    jitter: int = 1
) -> bool:
    if mode == "hardware":
        return send_hardware_click(hwnd, client_x, client_y, restore_cursor=True, jitter=jitter)
    elif mode == "activate":
        return send_activate_and_click(hwnd, client_x, client_y)
    elif mode == "postmessage":
        return send_background_postmessage(hwnd, client_x, client_y, jitter=jitter)
    else:
        return send_hardware_click(hwnd, client_x, client_y, restore_cursor=True, jitter=jitter)

