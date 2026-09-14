"""
윈도우 백그라운드 화면 캡처 모듈 (Window Capture Engine)
- 비활성/가려진 창 백그라운드 캡처 (PrintWindow PW_RENDERFULLCONTENT)
- GDI / WindowDC BitBlt 및 화면 크롭 폴백 지원
- 메모리 누수 방지 (GDI 핸들 안전 해제)
- DPI Scaling 자동 보정
"""

import ctypes
from ctypes import wintypes
import numpy as np
import win32gui
import win32con
import win32process
import win32service
from typing import List, Dict, Optional, Tuple

def sync_thread_desktop():
    """현재 스레드를 시스템의 활성 입력 데스크톱(Default)으로 동기화합니다."""
    try:
        hdesk = win32service.OpenInputDesktop(0, False, win32con.GENERIC_ALL)
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(int(hdesk))
    except Exception:
        pass

# 스레드 데스크톱 동기화 (win32ui MFC 초기화 전 필수 호출)
sync_thread_desktop()

import win32ui

# DPI 인식 설정
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2) # Per-monitor DPI aware
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

PW_RENDERFULLCONTENT = 0x00000002
PW_CLIENTONLY = 0x00000001


def get_window_list() -> List[Dict[str, any]]:
    """
    현재 실행 중인 유효한 가시적 윈도우 목록을 검색하여 반환합니다.
    (서비스/터미널 세션에서도 사용자 데스크톱 윈도우를 안전하게 검색)
    """
    windows = []
    seen_hwnds = set()

    def filter_and_add(hwnd):
        if hwnd in seen_hwnds:
            return
        if not win32gui.IsWindow(hwnd):
            return
        if not win32gui.IsWindowVisible(hwnd):
            return
        
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return

        try:
            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width <= 10 or height <= 10:
                return

            class_name = win32gui.GetClassName(hwnd)
            if class_name in ["Progman", "WorkerW", "Shell_TrayWnd", "Windows.UI.Core.CoreWindow"]:
                return

            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            seen_hwnds.add(hwnd)
            windows.append({
                "hwnd": hwnd,
                "title": title,
                "class_name": class_name,
                "pid": pid,
                "width": width,
                "height": height
            })
        except Exception:
            pass

    # 1. OpenInputDesktop을 통한 윈도우 검색
    try:
        hdesk = win32service.OpenInputDesktop(0, False, win32con.GENERIC_ALL)
        if hdesk:
            def cb(hwnd, _):
                filter_and_add(hwnd)
                return True
            win32gui.EnumDesktopWindows(hdesk, cb, None)
    except Exception:
        pass

    # 2. 표준 EnumWindows 보완 검색
    def enum_cb(hwnd, _):
        filter_and_add(hwnd)
        return True
    try:
        win32gui.EnumWindows(enum_cb, None)
    except Exception:
        pass

    # 제목 가나다/알파벳 순 정렬
    windows.sort(key=lambda x: x["title"].lower())
    return windows


_last_capture_error: str = ""


def get_last_capture_error() -> str:
    """마지막 화면 캡처 실패 사유를 반환합니다."""
    return _last_capture_error


def capture_window(hwnd: int, client_only: bool = True) -> Optional[np.ndarray]:
    """
    특정 윈도우(HWND)의 현재 화면을 비트맵으로 캡처하여 OpenCV BGR 형식으로 반환합니다.
    GDI 자원 누수를 원천 차단하고 DWM/PrintWindow/Desktop/BitBlt 5단계 폴백을 지원합니다.
    
    :param hwnd: 대상 윈도우 핸들
    :param client_only: 클라이언트(내부 캔버스) 영역만 캡처할지 여부
    :return: BGR 형식의 numpy.ndarray 또는 실패 시 None
    """
    global _last_capture_error
    _last_capture_error = ""

    sync_thread_desktop()

    if not win32gui.IsWindow(hwnd):
        _last_capture_error = f"창 핸들({hwnd})이 유효하지 않거나 창이 종료되었습니다."
        return None

    if win32gui.IsIconic(hwnd):
        _last_capture_error = "대상 창이 최소화(아이콘화)되어 있어 화면을 캡처할 수 없습니다. 창을 화면에 복원해 주세요."
        return None

    try:
        if client_only:
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            width = right - left
            height = bottom - top
            wrect = win32gui.GetWindowRect(hwnd)
            pt = win32gui.ClientToScreen(hwnd, (0, 0))
            offset_x = max(0, pt[0] - wrect[0])
            offset_y = max(0, pt[1] - wrect[1])
        else:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top
            offset_x = 0
            offset_y = 0
            pt = (left, top)
    except Exception as e:
        _last_capture_error = f"창 크기 및 좌표 계산 오류: {e}"
        return None

    if width <= 16 or height <= 16:
        _last_capture_error = f"창이 최소화되었거나 크기 조절 중입니다. ({width}x{height})"
        return None

    def _safe_gdi_capture(src_dc_handle, src_x: int, src_y: int, w: int, h: int, use_printwindow: bool = False, pw_flags: int = 0) -> Optional[np.ndarray]:
        """GDI 자원 누수 없이 안전하게 비트맵을 복사하는 내부 헬퍼"""
        if not src_dc_handle:
            return None
        save_dc = None
        save_bitmap = None
        old_bmp = None
        try:
            src_mfc = win32ui.CreateDCFromHandle(src_dc_handle)
            save_dc = src_mfc.CreateCompatibleDC()
            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(src_mfc, w, h)
            old_bmp = save_dc.SelectObject(save_bitmap)

            if use_printwindow:
                res = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), pw_flags)
                if not res:
                    return None
            else:
                save_dc.BitBlt((0, 0), (w, h), src_mfc, (src_x, src_y), win32con.SRCCOPY)

            bmpinfo = save_bitmap.GetInfo()
            bmpstr = save_bitmap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype=np.uint8).reshape((bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4))
            if np.count_nonzero(img) > 0:
                return img[:, :, :3].copy()
            return None
        except Exception:
            return None
        finally:
            if save_dc is not None:
                if old_bmp is not None:
                    try:
                        save_dc.SelectObject(old_bmp)
                    except Exception:
                        pass
                try:
                    save_dc.DeleteDC()
                except Exception:
                    pass
            if save_bitmap is not None:
                try:
                    win32gui.DeleteObject(save_bitmap.GetHandle())
                except Exception:
                    pass
            # 중요: src_mfc.DeleteDC()는 절대 호출하지 않음 (ReleaseDC만 수행)

    # ----------------------------------------------------
    # 전략 1: PrintWindow (PW_RENDERFULLCONTENT | PW_CLIENTONLY = 3 또는 2)
    # ----------------------------------------------------
    hwnd_dc = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        if hwnd_dc:
            # 1-A: PW_RENDERFULLCONTENT (0x02)
            img = _safe_gdi_capture(hwnd_dc, 0, 0, width, height, use_printwindow=True, pw_flags=PW_RENDERFULLCONTENT)
            if img is not None:
                return img

            # 1-B: PW_CLIENTONLY (0x01)
            if client_only:
                img = _safe_gdi_capture(hwnd_dc, 0, 0, width, height, use_printwindow=True, pw_flags=PW_CLIENTONLY)
                if img is not None:
                    return img
    except Exception:
        pass
    finally:
        if hwnd_dc is not None:
            win32gui.ReleaseDC(hwnd, hwnd_dc)

    # ----------------------------------------------------
    # 전략 2: WindowDC BitBlt (타이틀바/테두리 오프셋 보정)
    # ----------------------------------------------------
    hwnd_dc = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        if hwnd_dc:
            img = _safe_gdi_capture(hwnd_dc, offset_x, offset_y, width, height, use_printwindow=False)
            if img is not None:
                return img
    except Exception:
        pass
    finally:
        if hwnd_dc is not None:
            win32gui.ReleaseDC(hwnd, hwnd_dc)

    # ----------------------------------------------------
    # 전략 3: Desktop Screen BitBlt (화면 좌표 복사)
    # ----------------------------------------------------
    screen_dc = None
    try:
        screen_dc = win32gui.GetDC(0)
        if screen_dc:
            img = _safe_gdi_capture(screen_dc, pt[0], pt[1], width, height, use_printwindow=False)
            if img is not None:
                return img
    except Exception:
        pass
    finally:
        if screen_dc is not None:
            win32gui.ReleaseDC(0, screen_dc)

    # ----------------------------------------------------
    # 전략 4: mss 고속 화면 영역 캡처 (DirectX/DWM 보완)
    # ----------------------------------------------------
    try:
        import mss
        with mss.mss() as sct:
            monitor = {"left": int(pt[0]), "top": int(pt[1]), "width": int(width), "height": int(height)}
            shot = sct.grab(monitor)
            arr = np.array(shot)
            if arr is not None and np.count_nonzero(arr) > 0:
                return arr[:, :, :3].copy()
    except Exception:
        pass

    _last_capture_error = "모든 캡처 전략에서 검은 화면(0px)이 반환되었거나 화면 접근이 제한되었습니다."
    return None


def resize_window_client(hwnd: int, target_w: int = 1600, target_h: int = 900) -> Tuple[bool, str]:
    """
    대상 윈도우의 클라이언트(순수 게임 화면) 영역이 정확히 target_w x target_h(16:9)가 되도록 창 크기를 조절합니다.
    테두리, 타이틀바, DPI 오프셋을 역산하여 잘림 현상을 완벽히 방지합니다.
    """
    if not win32gui.IsWindow(hwnd):
        return False, "유효하지 않은 윈도우 핸들입니다."

    try:
        # 최소화/최대화 상태인 경우 일반 크기로 복원
        if win32gui.IsIconic(hwnd) or win32gui.IsZoomed(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            import time
            time.sleep(0.05)

        # 현재 창 전체 영역 및 순수 클라이언트 영역 측정
        w_left, w_top, w_right, w_bottom = win32gui.GetWindowRect(hwnd)
        cl_rect = win32gui.GetClientRect(hwnd)

        current_win_w = w_right - w_left
        current_win_h = w_bottom - w_top
        current_cl_w = cl_rect[2] - cl_rect[0]
        current_cl_h = cl_rect[3] - cl_rect[1]

        # 테두리 및 타이틀바 두께 계산
        border_w = current_win_w - current_cl_w
        border_h = current_win_h - current_cl_h

        # 목표 창 전체 크기
        new_win_w = target_w + border_w
        new_win_h = target_h + border_h

        # 창 위치 및 크기 적용
        win32gui.SetWindowPos(
            hwnd, 0,
            w_left, w_top,
            new_win_w, new_win_h,
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
        )

        import time
        time.sleep(0.05)

        # 2단계 미세 오차 보정 (일부 윈도우 스타일의 미세 오차 흡수)
        updated_cl = win32gui.GetClientRect(hwnd)
        actual_cl_w = updated_cl[2] - updated_cl[0]
        actual_cl_h = updated_cl[3] - updated_cl[1]

        if actual_cl_w != target_w or actual_cl_h != target_h:
            delta_w = target_w - actual_cl_w
            delta_h = target_h - actual_cl_h
            new_win_w += delta_w
            new_win_h += delta_h
            win32gui.SetWindowPos(
                hwnd, 0,
                w_left, w_top,
                new_win_w, new_win_h,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
            )
            time.sleep(0.03)

        final_cl = win32gui.GetClientRect(hwnd)
        f_w = final_cl[2] - final_cl[0]
        f_h = final_cl[3] - final_cl[1]

        return True, f"창 내부 해상도가 {f_w}x{f_h} (16:9)로 맞춤 설정되었습니다."
    except Exception as e:
        return False, f"창 크기 조절 실패: {e}"

