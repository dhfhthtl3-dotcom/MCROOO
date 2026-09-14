"""
다중 타겟 및 하이브리드 클릭 종합 검증 테스트 스위트 (Test Suite v2.0)
- 다중 버튼(Multi-Target) 동시 탐색 검증
- 우선순위(Priority) 정렬 및 선택 검증
- 개별 쿨다운(Cooldown) 방어 검증
- 타겟 설정 저장 및 복원(JSON + 이미지) 검증
- 하이브리드 클릭 디스패처 호출 검증
"""

import os
import json
import shutil
import unittest
import numpy as np
import cv2
import time

from detector import MultiTargetDetector, TargetItem
from clicker import dispatch_click, make_lparam
from macro_core import MacroEngine


class TestMultiTargetSuite(unittest.TestCase):
    def setUp(self):
        # 500x400 크기의 가상 게임 화면 (어두운 파랑)
        self.screen = np.full((400, 500, 3), (80, 40, 20), dtype=np.uint8)

        # 1번 버튼: "확인" (빨간색 박스 40x30, 위치: (100, 150))
        cv2.rectangle(self.screen, (100, 150), (140, 180), (0, 0, 255), -1)
        cv2.putText(self.screen, "OK", (105, 172), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        self.btn_ok_img = self.screen[150:180, 100:140].copy()

        # 2번 버튼: "전투시작" (노란색 박스 50x30, 위치: (300, 150))
        cv2.rectangle(self.screen, (300, 150), (350, 180), (0, 255, 255), -1)
        cv2.putText(self.screen, "GO", (310, 172), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        self.btn_go_img = self.screen[150:180, 300:350].copy()

    def test_multi_target_simultaneous_detection(self):
        """화면에 나타난 여러 버튼이 동시에 정확한 좌표와 일치율로 감지되는지 검증"""
        detector = MultiTargetDetector()
        target_ok = TargetItem("확인 버튼", self.btn_ok_img, threshold=0.85, priority=2)
        target_go = TargetItem("전투 시작", self.btn_go_img, threshold=0.85, priority=1)

        detector.add_target(target_ok)
        detector.add_target(target_go)

        detections = detector.detect_all(self.screen)
        self.assertEqual(len(detections), 2, "2개의 버튼이 모두 감지되어야 합니다.")

        # 우선순위 1인 '전투 시작'이 먼저 반환되어야 함
        self.assertEqual(detections[0]["name"], "전투 시작")
        self.assertEqual(detections[1]["name"], "확인 버튼")

        # 좌표 확인: GO의 중심은 (300+25, 150+15) = (325, 165)
        self.assertEqual(detections[0]["center"], (325, 165))
        # OK의 중심은 (100+20, 150+15) = (120, 165)
        self.assertEqual(detections[1]["center"], (120, 165))

    def test_target_disabled_filtering(self):
        """비활성화(enabled=False)된 버튼은 화면에 있어도 감지 목록에서 제외되는지 검증"""
        detector = MultiTargetDetector()
        target_ok = TargetItem("확인 버튼", self.btn_ok_img, threshold=0.85, enabled=False)
        target_go = TargetItem("전투 시작", self.btn_go_img, threshold=0.85, enabled=True)

        detector.add_target(target_ok)
        detector.add_target(target_go)

        detections = detector.detect_all(self.screen)
        self.assertEqual(len(detections), 1, "활성화된 1개 버튼만 감지되어야 합니다.")
        self.assertEqual(detections[0]["name"], "전투 시작")

    def test_macro_multi_target_execution_and_cooldown(self):
        """매크로 엔진이 감지된 버튼을 순차적으로 클릭하고 쿨다운을 정상 적용하는지 검증"""
        engine = MacroEngine()
        engine.detector.clear_targets()
        
        target_ok = TargetItem("확인", self.btn_ok_img, threshold=0.85, priority=1, cooldown=0.2)
        engine.detector.add_target(target_ok)
        
        engine.interval = 0.05
        engine.hwnd = 99999999
        engine.click_mode = "hardware"

        # Mock capture
        import macro_core
        orig_capture = macro_core.capture_window
        macro_core.capture_window = lambda hwnd, client_only=True: self.screen.copy()

        # Mock click
        clicks = []
        orig_dispatch = macro_core.dispatch_click
        macro_core.dispatch_click = lambda h, x, y, mode="hardware", jitter=0: (clicks.append((x, y, time.time())), True)[1]

        try:
            engine.max_clicks = 2
            engine.start()
            time.sleep(0.6)
            engine.stop()

            self.assertEqual(len(clicks), 2, "총 2회의 클릭이 수행되어야 합니다.")
            # 쿨다운 0.2초 이상 간격으로 실행되었는지 검증
            interval_between_clicks = clicks[1][2] - clicks[0][2]
            self.assertGreaterEqual(interval_between_clicks, 0.18, "클릭 간격은 쿨다운 이상이어야 합니다.")
        finally:
            macro_core.capture_window = orig_capture
            macro_core.dispatch_click = orig_dispatch

    def test_targets_persistence(self):
        """타겟 등록 후 디스크에 저장 및 재로딩 검증"""
        from profile_manager import ProfileManager
        test_dir = "test_persistence_env"
        os.makedirs(test_dir, exist_ok=True)
        test_templates = os.path.join(test_dir, "templates")
        test_cfg = os.path.join(test_dir, "targets_config.json")

        pm = ProfileManager(base_dir=test_dir)
        engine = MacroEngine(profile_manager=pm)
        engine.TEMPLATES_DIR = test_templates
        engine.DATA_FILE = test_cfg
        engine.detector.clear_targets()

        try:
            target1 = engine.add_target("테스트버튼1", self.btn_ok_img, threshold=0.88, priority=1)
            target2 = engine.add_target("테스트버튼2", self.btn_go_img, threshold=0.92, priority=2)

            self.assertTrue(os.path.exists(test_cfg))
            self.assertTrue(os.path.exists(test_templates))

            # 새 엔진 인스턴스로 로딩 확인
            pm2 = ProfileManager(base_dir=test_dir)
            engine2 = MacroEngine(profile_manager=pm2)
            engine2.TEMPLATES_DIR = test_templates
            engine2.DATA_FILE = test_cfg
            engine2.detector.clear_targets()
            engine2.load_targets()

            loaded = engine2.get_all_targets()
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0].name, "테스트버튼1")
            self.assertEqual(loaded[0].threshold, 0.88)
            self.assertEqual(loaded[1].name, "테스트버튼2")
            self.assertEqual(loaded[1].threshold, 0.92)
        finally:
            if os.path.exists(test_dir):
                shutil.rmtree(test_dir, ignore_errors=True)
    def test_resolution_scaling_detection(self):
        """화면 해상도가 1.5배로 확대되거나 0.75배로 축소되어도 정상 감지되는지 검증"""
        detector = MultiTargetDetector()
        
        # 500x400 기준 화면에서 등록된 타겟 (base_width=500, base_height=400)
        target = TargetItem(
            name="확인 버튼",
            template_img=self.btn_ok_img,
            threshold=0.80,
            base_width=500,
            base_height=400
        )
        detector.add_target(target)

        # 1. 원본 해상도(500x400) 검증
        dets_orig = detector.detect_all(self.screen)
        self.assertEqual(len(dets_orig), 1)
        self.assertEqual(dets_orig[0]["scale"], 1.0)
        self.assertEqual(dets_orig[0]["center"], (120, 165))

        # 2. 1.5배 확대 해상도(750x600) 검증
        screen_15x = cv2.resize(self.screen, (750, 600), interpolation=cv2.INTER_LINEAR)
        dets_15x = detector.detect_all(screen_15x)
        self.assertEqual(len(dets_15x), 1, "1.5배 확대 해상도에서도 감지되어야 합니다.")
        self.assertAlmostEqual(dets_15x[0]["scale"], 1.5, delta=0.1)
        # 예상 중심: (120 * 1.5, 165 * 1.5) = (180, 247.5) -> 약 (180, 247)
        cx, cy = dets_15x[0]["center"]
        self.assertTrue(abs(cx - 180) <= 4, f"X좌표 1.5배 보정 확인: {cx}")
        self.assertTrue(abs(cy - 248) <= 4, f"Y좌표 1.5배 보정 확인: {cy}")

        # 3. 0.8배 축소 해상도(400x320) 검증
        screen_08x = cv2.resize(self.screen, (400, 320), interpolation=cv2.INTER_AREA)
        dets_08x = detector.detect_all(screen_08x)
        self.assertEqual(len(dets_08x), 1, "0.8배 축소 해상도에서도 감지되어야 합니다.")
        self.assertAlmostEqual(dets_08x[0]["scale"], 0.8, delta=0.1)


class TestProfileManagerSuite(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_profile_env"
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_profile_creation_and_switching(self):
        """새 프로필 생성 및 전환 검증"""
        from profile_manager import ProfileManager
        pm = ProfileManager(base_dir=self.test_dir)
        
        # 초기 상태: 1개 프로필 (default)
        self.assertEqual(len(pm.get_profile_list()), 1)
        self.assertEqual(pm.get_active_profile().name, "기본 매크로")

        # 새 프로필 생성
        p2 = pm.create_profile("에픽세븐 토벌")
        self.assertEqual(len(pm.get_profile_list()), 2)
        self.assertEqual(pm.active_profile_id, p2.id)
        self.assertEqual(pm.get_active_profile().name, "에픽세븐 토벌")

        # 프로필 전환
        pm.switch_profile("default")
        self.assertEqual(pm.get_active_profile().name, "기본 매크로")

    def test_profile_duplicate_and_rename(self):
        """프로필 복제 및 이름 변경 검증"""
        from profile_manager import ProfileManager
        pm = ProfileManager(base_dir=self.test_dir)
        
        # 타겟 추가
        cur = pm.get_active_profile()
        cur.targets = [{"id": "btn1", "name": "시작"}]
        pm.save_active_profile()

        # 복제
        p_copy = pm.duplicate_profile(cur.id, "기본 매크로 복제본")
        self.assertIsNotNone(p_copy)
        self.assertEqual(p_copy.name, "기본 매크로 복제본")
        self.assertEqual(len(p_copy.targets), 1)
        self.assertEqual(p_copy.targets[0]["name"], "시작")

        # 이름 변경
        pm.rename_profile(p_copy.id, "새이름")
        self.assertEqual(pm.get_active_profile().name, "새이름")

    def test_profile_delete_protection(self):
        """프로필 삭제 시 최소 1개 유지 및 삭제 검증"""
        from profile_manager import ProfileManager
        pm = ProfileManager(base_dir=self.test_dir)
        
        # 프로필이 1개일 때 삭제 시도 -> 실패해야 함
        self.assertFalse(pm.delete_profile("default"))
        self.assertEqual(len(pm.get_profile_list()), 1)

        # 2개로 만든 후 삭제
        p2 = pm.create_profile("임시 프로필")
        self.assertEqual(len(pm.get_profile_list()), 2)
        self.assertTrue(pm.delete_profile(p2.id))
        self.assertEqual(len(pm.get_profile_list()), 1)

    def test_legacy_migration(self):
        """기존 targets_config.json 데이터가 있을 때 첫 실행 시 자동 마이그레이션 검증"""
        import json
        from profile_manager import ProfileManager

        legacy_path = os.path.join(self.test_dir, "targets_config.json")
        sample_targets = [
            {"id": "t1", "name": "기존버튼1", "threshold": 0.85},
            {"id": "t2", "name": "기존버튼2", "threshold": 0.90}
        ]
        with open(legacy_path, "w", encoding="utf-8") as f:
            json.dump(sample_targets, f)

        pm = ProfileManager(base_dir=self.test_dir)
        active = pm.get_active_profile()
        self.assertEqual(len(active.targets), 2)
        self.assertEqual(active.targets[0]["name"], "기존버튼1")
        self.assertEqual(active.targets[1]["name"], "기존버튼2")


class TestMacroPackageSecuritySuite(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_sec_env"
        self.templates_dir = os.path.join(self.test_dir, "templates")
        os.makedirs(self.templates_dir, exist_ok=True)

        # 유효한 테스트용 버튼 이미지 생성
        self.test_img = np.full((30, 40, 3), (100, 150, 200), dtype=np.uint8)
        self.img_path = os.path.join(self.templates_dir, "target_t1.png")
        is_ok, buf = cv2.imencode(".png", self.test_img)
        with open(self.img_path, "wb") as f:
            f.write(buf)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_valid_export_and_import(self):
        """정상 .gmac 패키지의 내보내기 및 4단계 보안 검사, 안전한 가져오기 검증"""
        from profile_manager import MacroProfile, ProfileManager
        from macro_package import export_macro_package, inspect_and_verify_package, import_macro_package

        profile = MacroProfile(
            profile_id="p1",
            name="정상 매크로",
            target_window_title="에픽세븐",
            targets=[{
                "id": "t1",
                "name": "전투준비",
                "image_file": "target_t1.png",
                "threshold": 0.85,
                "priority": 1,
                "cooldown": 2.0
            }]
        )

        pkg_path = os.path.join(self.test_dir, "test_valid.gmac")
        export_macro_package(profile, self.templates_dir, pkg_path)
        self.assertTrue(os.path.exists(pkg_path))

        # 보안 검사
        res = inspect_and_verify_package(pkg_path)
        self.assertTrue(res["is_safe"], f"검증 실패 사유: {res['errors']}")
        self.assertEqual(res["meta"]["name"], "정상 매크로")
        self.assertIn("t1", res["images"])

        # 가져오기
        pm = ProfileManager(base_dir=self.test_dir)
        ok, msg, new_p = import_macro_package(pkg_path, pm, self.templates_dir, custom_name="가져온 에픽세븐")
        self.assertTrue(ok)
        self.assertEqual(new_p.name, "가져온 에픽세븐")

    def test_dangerous_script_rejection(self):
        """악성 스크립트(.bat, .exe)가 삽입된 패키지는 100% 탐지되어 차단되는지 검증"""
        import zipfile
        from macro_package import inspect_and_verify_package

        bad_pkg = os.path.join(self.test_dir, "malicious.gmac")
        with zipfile.ZipFile(bad_pkg, "w") as zf:
            zf.writestr("macro_meta.json", json.dumps({"targets": []}))
            zf.writestr("malicious_hack.bat", "@echo off\necho attack")

        res = inspect_and_verify_package(bad_pkg)
        self.assertFalse(res["is_safe"], "악성 스크립트가 감지되어 차단되어야 합니다.")
        self.assertTrue(any("위험한 실행 파일" in err for err in res["errors"]))

    def test_zip_slip_rejection(self):
        """상위 경로 탈출(Zip Slip, ../) 조작이 즉시 탐지되어 차단되는지 검증"""
        import zipfile
        from macro_package import inspect_and_verify_package

        bad_pkg = os.path.join(self.test_dir, "zip_slip.gmac")
        with zipfile.ZipFile(bad_pkg, "w") as zf:
            zf.writestr("macro_meta.json", json.dumps({"targets": []}))
            zf.writestr("../../Windows/System32/evil.png", b"fake")

        res = inspect_and_verify_package(bad_pkg)
        self.assertFalse(res["is_safe"], "경로 조작 시도가 차단되어야 합니다.")
        self.assertTrue(any("경로 조작" in err for err in res["errors"]))

    def test_dangerous_window_target_rejection(self):
        """작업 관리자, 레지스트리 편집기 등 시스템 창을 조작하려는 매크로 차단 검증"""
        from profile_manager import MacroProfile
        from macro_package import export_macro_package, inspect_and_verify_package

        profile = MacroProfile(
            profile_id="p_bad",
            name="위험한 매크로",
            target_window_title="작업 관리자 (Task Manager)",
            targets=[]
        )
        pkg_path = os.path.join(self.test_dir, "bad_window.gmac")
        export_macro_package(profile, self.templates_dir, pkg_path)

        res = inspect_and_verify_package(pkg_path)
        self.assertFalse(res["is_safe"], "시스템 창 제어 시도는 차단되어야 합니다.")
        self.assertTrue(any("시스템/보안 프로그램 창" in err for err in res["errors"]))


class TestPinpointAndAutoTapSuite(unittest.TestCase):
    def setUp(self):
        self.screen = np.full((400, 500, 3), (80, 40, 20), dtype=np.uint8)
        # (100, 150) 위치에 녹색 버튼 (40x30) 부착 -> 중심: (120, 165)
        cv2.rectangle(self.screen, (100, 150), (140, 180), (0, 255, 0), -1)
        cv2.putText(self.screen, "PIN", (104, 172), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
        self.btn_img = self.screen[150:180, 100:140].copy()

    def test_pinpoint_offset_clicking(self):
        """특정 부위 클릭 (오프셋) 반영 및 스케일링 보정 검증"""
        import macro_core
        from profile_manager import ProfileManager

        test_dir = "test_pinpoint_env"
        os.makedirs(test_dir, exist_ok=True)

        pm = ProfileManager(base_dir=test_dir)
        engine = MacroEngine(profile_manager=pm)
        engine.hwnd = 12345
        engine.interval = 0.05
        engine.max_clicks = 1

        # 오프셋 (+10, -8)을 적용한 타겟 등록 (중심 120, 165 -> 클릭 130, 157)
        target = TargetItem(
            name="우측상단클릭버튼",
            template_img=self.btn_img,
            threshold=0.85,
            offset_x=10,
            offset_y=-8
        )
        engine.detector.add_target(target)

        clicks = []
        orig_capture = macro_core.capture_window
        orig_dispatch = macro_core.dispatch_click

        try:
            macro_core.capture_window = lambda hwnd: self.screen
            macro_core.dispatch_click = lambda hwnd, x, y, mode="hardware", jitter=0: clicks.append((x, y)) or True

            engine.start()
            time.sleep(0.3)
            engine.stop()

            self.assertEqual(len(clicks), 1)
            cx, cy = clicks[0]
            # 중심 (120, 165) + offset (10, -8) = (130, 157)
            self.assertEqual(cx, 130, f"X 오프셋 적용 확인: {cx}")
            self.assertEqual(cy, 157, f"Y 오프셋 적용 확인: {cy}")
        finally:
            macro_core.capture_window = orig_capture
            macro_core.dispatch_click = orig_dispatch
            if os.path.exists(test_dir):
                shutil.rmtree(test_dir, ignore_errors=True)

    def test_auto_tap_when_idle(self):
        """감지된 버튼이 없을 때 화면 연속 탭(오토클릭) 트리거 검증"""
        import macro_core
        from profile_manager import ProfileManager

        test_dir = "test_autotap_env"
        os.makedirs(test_dir, exist_ok=True)

        pm = ProfileManager(base_dir=test_dir)
        engine = MacroEngine(profile_manager=pm)
        engine.hwnd = 12345
        engine.interval = 0.05
        engine.auto_tap_enabled = True
        engine.auto_tap_interval = 0.1
        engine.auto_tap_point = (250, 200) # 화면 특정 좌표
        engine.auto_tap_mode = "when_idle"
        engine.max_clicks = 2

        # 빈 화면 (버튼 감지 없음)
        blank_screen = np.zeros((400, 500, 3), dtype=np.uint8)

        clicks = []
        orig_capture = macro_core.capture_window
        orig_dispatch = macro_core.dispatch_click

        try:
            macro_core.capture_window = lambda hwnd: blank_screen
            macro_core.dispatch_click = lambda hwnd, x, y, mode="hardware", jitter=0: clicks.append((x, y)) or True

            engine.start()
            time.sleep(0.35)
            engine.stop()

            self.assertGreaterEqual(len(clicks), 1, "화면 연속 탭이 최소 1회 이상 트리거되어야 합니다.")
            # 클릭된 좌표가 auto_tap_point (250, 200)인지 검증
            self.assertEqual(clicks[0], (250, 200))
        finally:
            macro_core.capture_window = orig_capture
            macro_core.dispatch_click = orig_dispatch
            if os.path.exists(test_dir):
                shutil.rmtree(test_dir, ignore_errors=True)

    def test_resize_window_client(self):
        """창 크기 16:9 해상도 맞춤 기능 검증"""
        from window_capture import resize_window_client
        # 유효하지 않은 HWND 처리
        ok, msg = resize_window_client(0, 1600, 900)
        self.assertFalse(ok)
        self.assertIn("유효하지 않은", msg)

    def test_drag_clicker(self):
        """마우스 드래그 / 스와이프 디스패처 동작 검증"""
        from clicker import dispatch_drag, send_hardware_drag, send_postmessage_drag
        # 유효하지 않은 창 핸들 시 안전하게 False 반환 확인
        self.assertFalse(dispatch_drag(0, 100, 300, 100, 100, mode="hardware"))
        self.assertFalse(send_postmessage_drag(0, 100, 300, 100, 100))
        self.assertFalse(send_hardware_drag(0, 100, 300, 100, 100))

    def test_secret_shop_stats(self):
        """비상런 통계 수집기 계산 정확성 검증"""
        from secret_shop_engine import SecretShopStats
        stats = SecretShopStats()
        self.assertEqual(stats.refreshes, 0)
        self.assertEqual(stats.skystones_spent, 0)
        self.assertEqual(stats.total_gold, 0)

        # 20회 갱신, 성약 3회(15개), 신비 1회(50개) 시뮬레이션
        stats.refreshes = 20
        stats.covenant_count = 3
        stats.mystic_count = 1

        self.assertEqual(stats.skystones_spent, 60) # 20 * 3
        self.assertEqual(stats.covenant_gold, 3 * 184000)
        self.assertEqual(stats.mystic_gold, 1 * 280000)
        self.assertEqual(stats.total_gold, 3 * 184000 + 1 * 280000)

        d = stats.to_dict()
        self.assertEqual(d["refreshes"], 20)
        self.assertEqual(d["skystones_spent"], 60)
        self.assertEqual(d["total_gold"], 832000)

        stats.reset()
        self.assertEqual(stats.refreshes, 0)
        self.assertEqual(stats.total_gold, 0)

    def test_secret_shop_engine_detection_and_cycle(self):
        """비상런 엔진 템플릿 로드, 아이템 감지 및 1사이클 시뮬레이션 검증"""
        from secret_shop_engine import SecretShopEngine
        import secret_shop_engine

        engine = SecretShopEngine()
        # 템플릿 최소 2종(성약, 신비) 이상 로드되었는지 확인
        self.assertGreaterEqual(len(engine.templates), 2, "성약 및 신비 템플릿이 로드되어야 합니다.")
        self.assertIn("covenant", engine.templates)
        self.assertIn("mystic", engine.templates)

        # 가상 1600x900 화면 생성 후 성약 템플릿 합성
        test_screen = np.zeros((900, 1600, 3), dtype=np.uint8)
        cov_img = engine.templates["covenant"]["image"]
        ch, cw = cov_img.shape[:2]
        # 좌측 상점 슬롯 위치 (200, 250)에 성약 아이콘 배치
        test_screen[250:250+ch, 200:200+cw] = cov_img

        # 엔진 템플릿 매칭 검증
        engine.match_threshold = 0.70
        detected = engine.find_items_in_frame(test_screen, ["covenant", "mystic"])
        self.assertGreaterEqual(len(detected), 1, "합성된 성약의 책갈피가 감지되어야 합니다.")
        found_cov = [d for d in detected if d["type"] == "covenant"]
        self.assertTrue(len(found_cov) > 0)
        self.assertAlmostEqual(found_cov[0]["x"], 200 + cw // 2, delta=5)
        self.assertAlmostEqual(found_cov[0]["y"], 250 + ch // 2, delta=5)

        # 1사이클 모의 실행 검증
        clicks = []
        drags = []
        orig_capture = secret_shop_engine.capture_window
        orig_click = secret_shop_engine.dispatch_click
        orig_drag = secret_shop_engine.dispatch_drag

        try:
            secret_shop_engine.capture_window = lambda hwnd: test_screen
            secret_shop_engine.dispatch_click = lambda hwnd, x, y, mode="hardware": clicks.append((x, y)) or True
            secret_shop_engine.dispatch_drag = lambda hwnd, x1, y1, x2, y2, mode="hardware", duration=0.35, steps=14: drags.append((x1, y1, x2, y2)) or True

            # 윈도우 모킹 및 짧은 딜레이
            import win32gui
            orig_is_win = win32gui.IsWindow
            orig_get_client = win32gui.GetClientRect
            win32gui.IsWindow = lambda h: True
            win32gui.GetClientRect = lambda h: (0, 0, 1600, 900)

            engine.delay_post_refresh = 0.01
            engine.delay_post_drag = 0.01
            engine.delay_click = 0.01
            engine.max_refreshes = 1
            engine.hwnd = 99999

            engine.start(hwnd=99999)
            t_start = time.time()
            while time.time() - t_start < 2.0 and engine.stats.refreshes < 1:
                time.sleep(0.05)
            engine.stop()


            # 새로고침 1회 수행 확인
            self.assertEqual(engine.stats.refreshes, 1)
            # 드래그 1회 이상 수행 확인
            self.assertGreaterEqual(len(drags), 1)
            # 클릭(구매 + 확인 + 새로고침 + 새로고침확인) 수행 확인
            self.assertGreaterEqual(len(clicks), 2)
        finally:
            secret_shop_engine.capture_window = orig_capture
            secret_shop_engine.dispatch_click = orig_click
            secret_shop_engine.dispatch_drag = orig_drag
            win32gui.IsWindow = orig_is_win
            win32gui.GetClientRect = orig_get_client

    def test_resize_window_client_real(self):
        """실제 Tkinter 윈도우를 생성하여 resize_window_client의 16:9 크기 조절 및 예외 발생 여부 검증"""
        import tkinter as tk
        from window_capture import resize_window_client

        root = tk.Tk()
        root.title("UnitTestResizeWindow")
        root.geometry("400x300+100+100")
        root.update()

        hwnd = root.winfo_id()
        import win32gui
        toplevel_hwnd = win32gui.GetParent(hwnd) or hwnd

        try:
            success, msg = resize_window_client(toplevel_hwnd, 800, 450)
            self.assertTrue(success, f"창 크기 조절이 성공해야 합니다: {msg}")
            cl_rect = win32gui.GetClientRect(toplevel_hwnd)
            w = cl_rect[2] - cl_rect[0]
            h = cl_rect[3] - cl_rect[1]
            self.assertEqual(w, 800)
            self.assertEqual(h, 450)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()





