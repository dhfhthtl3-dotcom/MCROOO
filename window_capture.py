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
import win32ui
import win32con
import win32process
import win32service
from typing import List, Dict, Optional, Tuple

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


def capture_window(hwnd: int, client_only: bool = True) -> Optional[np.ndarray]:
    """
    특정 윈도우(HWND)의 현재 화면을 비트맵으로 캡처하여 OpenCV BGR 형식으로 반환합니다.
    창이 뒤에 가려져 있거나 비활성화되어 있어도 PrintWindow(PW_RENDERFULLCONTENT)를 통해 캡처합니다.
    
    :param hwnd: 대상 윈도우 핸들
    :param client_only: 클라이언트(내부 캔버스) 영역만 캡처할지 여부
    :return: BGR 형식의 numpy.ndarray 또는 실패 시 None
    """
    if not win32gui.IsWindow(hwnd):
        return None

    try:
        if client_only:
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            width = right - left
            height = bottom - top
            # 클라이언트 영역의 창 기준 오프셋 (타이틀바 및 창 테두리)
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
    except Exception:
        return None

    if width <= 0 or height <= 0:
        return None

    # ----------------------------------------------------
    # 전략 1: PrintWindow (PW_CLIENTONLY / PW_RENDERFULLCONTENT)
    # ----------------------------------------------------
    hwnd_dc = None
    mfc_dc = None
    save_dc = None
    save_bitmap = None

    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        save_bitmap = win32ui.CreateBitmap()
        save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(save_bitmap)

        flags = PW_CLIENTONLY if client_only else PW_RENDERFULLCONTENT
        res = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), flags)
        
        if res:
            bmpinfo = save_bitmap.GetInfo()
            bmpstr = save_bitmap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype=np.uint8).reshape((bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4))
            
            # 유효한 픽셀이 존재하는지 검증 (전체 검은 화면 제외)
            if np.count_nonzero(img) > 0:
                img_bgr = img[:, :, :3].copy()
                return img_bgr

    except Exception:
        pass
    finally:
        if save_bitmap is not None:
            win32gui.DeleteObject(save_bitmap.GetHandle())
        if save_dc is not None:
            save_dc.DeleteDC()
        if mfc_dc is not None:
            mfc_dc.DeleteDC()
        if hwnd_dc is not None:
            win32gui.ReleaseDC(hwnd, hwnd_dc)

    # ----------------------------------------------------
    # 전략 2: PrintWindow 기본 (PW_RENDERFULLCONTENT)
    # ----------------------------------------------------
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        save_bitmap = win32ui.CreateBitmap()
        save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(save_bitmap)

        res = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        if res:
            bmpinfo = save_bitmap.GetInfo()
            bmpstr = save_bitmap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype=np.uint8).reshape((bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4))
            if np.count_nonzero(img) > 0:
                img_bgr = img[:, :, :3].copy()
                return img_bgr
    except Exception:
        pass
    finally:
        if save_bitmap is not None:
            win32gui.DeleteObject(save_bitmap.GetHandle())
        if save_dc is not None:
            save_dc.DeleteDC()
        if mfc_dc is not None:
            mfc_dc.DeleteDC()
        if hwnd_dc is not None:
            win32gui.ReleaseDC(hwnd, hwnd_dc)

    # ----------------------------------------------------
    # 전략 3: WindowDC BitBlt (타이틀바/테두리 오프셋 정확히 보정)
    # ----------------------------------------------------
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        save_bitmap = win32ui.CreateBitmap()
        save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(save_bitmap)

        # (offset_x, offset_y)부터 복사하여 타이틀바 제외 순수 클라이언트 영역만 캡처
        save_dc.BitBlt((0, 0), (width, height), mfc_dc, (offset_x, offset_y), win32con.SRCCOPY)
        bmpinfo = save_bitmap.GetInfo()
        bmpstr = save_bitmap.GetBitmapBits(True)
        img = np.frombuffer(bmpstr, dtype=np.uint8).reshape((bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4))
        if np.count_nonzero(img) > 0:
            img_bgr = img[:, :, :3].copy()
            return img_bgr
    except Exception:
        pass
    finally:
        if save_bitmap is not None:
            win32gui.DeleteObject(save_bitmap.GetHandle())
        if save_dc is not None:
            save_dc.DeleteDC()
        if mfc_dc is not None:
            mfc_dc.DeleteDC()
        if hwnd_dc is not None:
            win32gui.ReleaseDC(hwnd, hwnd_dc)

    # ----------------------------------------------------
    # 전략 4: Desktop Screen BitBlt (창이 화면에 표시 중인 경우 폴백)
    # ----------------------------------------------------
    try:
        screen_dc = win32gui.GetDC(0)
        mfc_screen = win32ui.CreateDCFromHandle(screen_dc)
        save_dc = mfc_screen.CreateCompatibleDC()
        save_bitmap = win32ui.CreateBitmap()
        save_bitmap.CreateCompatibleBitmap(mfc_screen, width, height)
        save_dc.SelectObject(save_bitmap)

        pt = win32gui.ClientToScreen(hwnd, (0, 0)) if client_only else win32gui.GetWindowRect(hwnd)[:2]
        save_dc.BitBlt((0, 0), (width, height), mfc_screen, pt, win32con.SRCCOPY)

        bmpinfo = save_bitmap.GetInfo()
        bmpstr = save_bitmap.GetBitmapBits(True)
        img = np.frombuffer(bmpstr, dtype=np.uint8).reshape((bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4))
        if np.count_nonzero(img) > 0:
            img_bgr = img[:, :, :3].copy()
            return img_bgr
    except Exception:
        pass
    finally:
        if save_bitmap is not None:
            win32gui.DeleteObject(save_bitmap.GetHandle())
        if save_dc is not None:
            save_dc.DeleteDC()
        if mfc_screen is not None:
            mfc_screen.DeleteDC()
        if screen_dc is not None:
            win32gui.ReleaseDC(0, screen_dc)

    return None
