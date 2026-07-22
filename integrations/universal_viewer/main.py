"""명령행 진입점."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .cursor_value import (
    CursorValueError,
    adjust_ab_cursors_to_30min,
    focus_universal_viewer_main_window,
    move_cursor_value_window_below_graph_or_safe_area,
    open_cursor_value_window_from_universal_viewer_main_window,
    preview_ab_cursor_profile,
    read_cursor_value_absolute_time_difference,
    test_ab_cursor_drag_read,
)
from .display_group_settings import (
    DisplayGroupInspectionError,
    apply_display_group_geometry_actions_confirmed,
    apply_display_group_geometry_actions_test,
    apply_display_group_max_48_confirmed,
    inspect_display_group_geometry,
    inspect_display_group_scrollbar_points_pause,
    inspect_display_group_settings,
    preview_display_group_geometry_actions,
    preview_display_group_max_48_actions,
)
from .file_manager import RawDataValidationError, build_pdf_filename, resolve_input_files
from .logging_setup import append_csv_result, setup_logging
from .manual_pdf_workflow import ManualPdfWorkflowError, run_manual_pdf_workflow
from .models import ProcessingResult, ProcessingStatus
from .pdf_printing import PdfPrintingError, print_raw_file_to_pdf
from .ui_inspection import inspect_viewer_menu_paths, inspect_viewer_ui
from .viewer_launcher import ViewerLaunchError, ViewerOpenResult, open_prepared_raw_file
from .viewer_discovery import WindowInfo, format_viewer_candidate, inspect_windows
from .workflow import Workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Universal Viewer Raw Data-PDF 자동화 안전 골격")
    parser.add_argument("raw_files", nargs="*", type=Path, help="처리할 .DAE/.GEV 파일(생략 시 input 폴더)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="실제 복사 없이 준비 계획과 로그만 출력")
    mode.add_argument(
        "--prepare-only",
        action="store_true",
        help="작업 복사본 생성과 무결성 검증만 수행(GUI/인쇄 금지)",
    )
    mode.add_argument(
        "--open-raw-file",
        action="store_true",
        help="작업 복사본을 생성한 뒤 Universal Viewer로 작업본만 열기(Stage 3)",
    )
    mode.add_argument(
        "--print-to-pdf",
        action="store_true",
        help="작업 복사본을 Universal Viewer로 열고 Microsoft Print to PDF로 출력(Stage 4)",
    )
    mode.add_argument(
        "--inspect-display-group-settings",
        action="store_true",
        help="작업본을 열고 표시(V) > 표시 그룹 설정(D)... 창 구조만 안전 조사(Stage 5A)",
    )
    mode.add_argument(
        "--inspect-display-group-settings-pause",
        action="store_true",
        help="표시 그룹 설정창을 연 상태로 Enter 입력까지 대기한 뒤 ESC로 닫기(Stage 5A 수동 확인)",
    )
    mode.add_argument(
        "--inspect-display-group-geometry",
        action="store_true",
        help="표시 그룹 설정창 custom UI의 상대 좌표 후보만 안전 조사(Stage 5B)",
    )
    mode.add_argument(
        "--inspect-display-group-geometry-pause",
        action="store_true",
        help="표시 그룹 설정창 geometry 후보를 출력하고 Enter 입력까지 대기한 뒤 ESC로 닫기(Stage 5B)",
    )
    mode.add_argument(
        "--inspect-display-group-scrollbar-points-pause",
        action="store_true",
        help="표시 그룹 설정창 vertical scrollbar 좌표를 운영자 마우스 위치로 보정 조사(개발용, OK/인쇄 금지)",
    )
    mode.add_argument(
        "--preview-display-group-geometry-actions",
        action="store_true",
        help="표시 그룹 geometry 자동화 예정 클릭/드래그 좌표만 미리보기(실제 클릭 금지)",
    )
    mode.add_argument(
        "--preview-display-group-max-48-actions",
        action="store_true",
        help="표시 그룹 max-48 geometry 자동화 예정 좌표 미리보기(heating-point-count 불필요, 실제 클릭 금지)",
    )
    mode.add_argument(
        "--preview-display-group-profile",
        action="store_true",
        help="현재 표시 그룹 설정창 layout profile 좌표를 선택하고 mouse move만 수행하는 개발용 preview(클릭/드래그 없음)",
    )
    mode.add_argument(
        "--apply-display-group-geometry-actions-test",
        action="store_true",
        help="개발 검증용 표시 그룹 geometry 실제-click test(N=11~48, OK/인쇄 금지)",
    )
    mode.add_argument(
        "--apply-display-group-geometry-actions-confirmed",
        action="store_true",
        help="표시 그룹 geometry 작업을 확정 적용하고 OK로 저장(개발 검증 완료 후 사용, PDF 출력 금지)",
    )
    parser.add_argument("--viewer-exe", type=Path, help="UnivViewer.exe 명시 경로")
    parser.add_argument("--output-pdf", type=Path, help="Stage 4 PDF 출력 경로(.pdf)")
    parser.add_argument("--heating-point-count", type=int, help="표시 그룹 geometry preview 대상 Heating Point 개수(1~48)")
    parser.add_argument(
        "--pause-after-display-group-paste",
        action="store_true",
        help="개발 검증용 actual-click test에서 붙임 후 Enter 입력까지 대기",
    )
    parser.add_argument(
        "--pause-after-display-group-scroll",
        action="store_true",
        help="개발 검증용 actual-click test에서 보정 scrollbar drag 후 Enter 입력까지 대기",
    )
    parser.add_argument(
        "--continue-without-display-group-pause",
        action="store_true",
        help="개발 검증용 actual-click test에서 붙임 후 Enter 대기 없이 연속 진행(N>30 명시 허용)",
    )
    parser.add_argument(
        "--pause-before-display-group-button-clicks",
        action="store_true",
        help="개발 검증용 actual-click test에서 복사상세/붙임 클릭 직전 마우스 위치 확인",
    )
    parser.add_argument("--inspect-windows", action="store_true", help="열린 Windows 창 제목을 Viewer 우선으로 출력")
    parser.add_argument(
        "--inspect-viewer-ui",
        action="store_true",
        help="Universal Viewer 메인 창의 메뉴와 하위 컨트롤을 읽기 전용으로 조사",
    )
    parser.add_argument(
        "--inspect-viewer-menu-paths",
        action="store_true",
        help="파일/표시 상위 메뉴만 열어 하위 메뉴 경로를 제한적으로 조사",
    )
    mode.add_argument(
        "--apply-display-group-max-48-confirmed",
        action="store_true",
        help="Heating Point 개수 입력 없이 group/page 02~05를 max-48로 확정 적용하고 OK로 저장(PDF 출력 금지)",
    )
    mode.add_argument(
        "--inspect-cursor-value-difference",
        action="store_true",
        help="현재 열린 커서값 창을 중앙 클릭 후 Ctrl+A/C로 절대시간 차 값을 읽어 초 단위로 출력",
    )
    mode.add_argument(
        "--open-cursor-value-window-test",
        action="store_true",
        help="현재 열린 Universal Viewer에서 윈도우 > 커서값 표시 창을 열고 검증하는 임시 진단 모드",
    )
    mode.add_argument(
        "--test-ab-cursor-drag-read",
        action="store_true",
        help="이미 열린 Universal Viewer에서 A→B cursor drag 후 커서값 창 clipboard 절대시간 차 값을 읽는 임시 검증 모드",
    )
    mode.add_argument(
        "--preview-ab-cursor-profile",
        action="store_true",
        help="현재 Universal Viewer main window size에 맞는 A/B cursor profile 좌표를 mouse move만으로 확인",
    )
    mode.add_argument(
        "--adjust-ab-cursors-to-30min",
        action="store_true",
        help="이미 열린 Universal Viewer에서 A cursor를 자동 조정해 A/B 절대시간 차를 30분 범위로 맞추는 임시 검증 모드",
    )
    mode.add_argument(
        "--adjust-ab-cursors-to-30min-and-print-pdf",
        action="store_true",
        help="A/B cursor 30분 조정 성공 후 커서값 창을 이동하고 현재 열린 Universal Viewer 화면을 PDF로 출력",
    )
    mode.add_argument(
        "--run-manual-pdf-workflow",
        action="store_true",
        help="작업본 열기, 시간축 전부 표시, 표시 그룹 max-48, A/B 30분 조정, PDF 출력을 순서대로 실행",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # 외부 창 제목에 현재 Windows 콘솔 코드페이지로 표현할 수 없는 문자가 있어도
    # 조사 전체가 실패하지 않도록 출력 불가 문자만 대체한다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    config = AppConfig()
    config.ensure_directories()
    logger, log_path = setup_logging(config.logs_dir)

    inspection_mode_count = sum(
        1
        for enabled in (
            args.inspect_windows,
            args.inspect_viewer_ui,
            args.inspect_viewer_menu_paths,
            args.open_raw_file,
            args.print_to_pdf,
            args.inspect_display_group_settings,
            args.inspect_display_group_settings_pause,
            args.inspect_display_group_geometry,
            args.inspect_display_group_geometry_pause,
            args.inspect_display_group_scrollbar_points_pause,
            args.preview_display_group_geometry_actions,
            args.preview_display_group_max_48_actions,
            args.preview_display_group_profile,
            args.apply_display_group_geometry_actions_test,
            args.apply_display_group_geometry_actions_confirmed,
            args.apply_display_group_max_48_confirmed,
            args.inspect_cursor_value_difference,
            args.open_cursor_value_window_test,
            args.test_ab_cursor_drag_read,
            args.preview_ab_cursor_profile,
            args.adjust_ab_cursors_to_30min,
            args.adjust_ab_cursors_to_30min_and_print_pdf,
            args.run_manual_pdf_workflow,
        )
        if enabled
    )
    if inspection_mode_count > 1:
        print(
            "오류: --inspect-windows, --inspect-viewer-ui, --inspect-viewer-menu-paths, --open-raw-file, --print-to-pdf, --inspect-display-group-settings, --inspect-display-group-settings-pause, --inspect-display-group-geometry, --inspect-display-group-geometry-pause, --inspect-display-group-scrollbar-points-pause, --preview-display-group-geometry-actions, --apply-display-group-geometry-actions-test, --apply-display-group-geometry-actions-confirmed는 동시에 사용할 수 없습니다.",
            file=sys.stderr,
        )
        return 1
    if args.viewer_exe is not None and not (
        args.open_raw_file
        or args.print_to_pdf
        or args.inspect_display_group_settings
        or args.inspect_display_group_settings_pause
        or args.inspect_display_group_geometry
        or args.inspect_display_group_geometry_pause
        or args.inspect_display_group_scrollbar_points_pause
        or args.preview_display_group_geometry_actions
        or args.preview_display_group_max_48_actions
        or args.preview_display_group_profile
        or args.apply_display_group_geometry_actions_test
        or args.apply_display_group_geometry_actions_confirmed
        or args.apply_display_group_max_48_confirmed
        or args.run_manual_pdf_workflow
    ):
        print(
            "오류: --viewer-exe는 --open-raw-file, --print-to-pdf, --inspect-display-group-settings, --inspect-display-group-settings-pause, --inspect-display-group-geometry, --inspect-display-group-geometry-pause, --inspect-display-group-scrollbar-points-pause, --preview-display-group-geometry-actions, --apply-display-group-geometry-actions-test 또는 --apply-display-group-geometry-actions-confirmed와 함께 사용하십시오.",
            file=sys.stderr,
        )
        return 1
    if args.output_pdf is not None and not (
        args.print_to_pdf or args.adjust_ab_cursors_to_30min_and_print_pdf or args.run_manual_pdf_workflow
    ):
        print("오류: --output-pdf는 --print-to-pdf와 함께 사용하십시오.", file=sys.stderr)
        return 1
    if args.heating_point_count is not None and not (
        args.preview_display_group_geometry_actions
        or args.preview_display_group_profile
        or args.apply_display_group_geometry_actions_test
        or args.apply_display_group_geometry_actions_confirmed
    ):
        print(
            "오류: --heating-point-count는 --preview-display-group-geometry-actions, --apply-display-group-geometry-actions-test 또는 --apply-display-group-geometry-actions-confirmed와 함께 사용하십시오.",
            file=sys.stderr,
        )
        return 1
    if args.pause_after_display_group_paste and not args.apply_display_group_geometry_actions_test:
        print("오류: --pause-after-display-group-paste는 --apply-display-group-geometry-actions-test와 함께 사용하십시오.", file=sys.stderr)
        return 1
    if args.pause_after_display_group_scroll and not args.apply_display_group_geometry_actions_test:
        print("오류: --pause-after-display-group-scroll은 --apply-display-group-geometry-actions-test와 함께 사용하십시오.", file=sys.stderr)
        return 1
    if args.continue_without_display_group_pause and not args.apply_display_group_geometry_actions_test:
        print(
            "오류: --continue-without-display-group-pause는 --apply-display-group-geometry-actions-test와 함께 사용하십시오.",
            file=sys.stderr,
        )
        return 1
    if args.pause_before_display_group_button_clicks and not args.apply_display_group_geometry_actions_test:
        print(
            "오류: --pause-before-display-group-button-clicks는 --apply-display-group-geometry-actions-test와 함께 사용하십시오.",
            file=sys.stderr,
        )
        return 1

    if args.run_manual_pdf_workflow:
        if len(args.raw_files) != 1:
            print("오류: --run-manual-pdf-workflow는 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.", file=sys.stderr)
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = run_manual_pdf_workflow(
                source,
                config,
                logger,
                explicit_viewer_exe=args.viewer_exe,
                explicit_output_pdf=args.output_pdf,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except ManualPdfWorkflowError as exc:
            logger.error("Manual PDF workflow failed: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        print("Manual PDF workflow completed")
        print(f"raw file: {result.opened.source_path}")
        print(f"work copy: {result.opened.work_copy_path}")
        print(f"pdf: {result.pdf_result.output_pdf_path}")
        print(f"absolute time difference: {result.absolute_time_difference}")
        print(f"difference seconds: {format_seconds_for_console(result.difference_seconds)}")
        print(f"pdf size: {result.pdf_result.pdf_size_bytes}")
        print(f"실행 로그: {log_path}")
        return 0

    if args.open_cursor_value_window_test:
        if args.raw_files:
            print("오류: --open-cursor-value-window-test는 raw 파일 인자를 사용하지 않습니다.", file=sys.stderr)
            return 1
        try:
            result = open_cursor_value_window_from_universal_viewer_main_window(logger)
        except CursorValueError as exc:
            logger.error("Cursor value window open test failed: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        print("cursor value window opened")
        print(f"cursor value window rectangle: {result.rectangle}")
        return 0

    if args.inspect_cursor_value_difference:
        if args.raw_files:
            print("오류: --inspect-cursor-value-difference는 raw 파일 인자를 사용하지 않습니다.", file=sys.stderr)
            return 1
        try:
            result = read_cursor_value_absolute_time_difference(logger)
        except CursorValueError as exc:
            logger.error("커서값 차이 읽기 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        seconds_text = format_seconds_for_console(result.difference_seconds)
        logger.info("cursor value window found | rectangle=%s", result.window.rectangle)
        logger.info("clipboard copied")
        logger.info("absolute time difference: %s", result.absolute_time_difference)
        logger.info("difference seconds: %s", seconds_text)
        print("cursor value window found")
        print(f"cursor value window rectangle: {result.window.rectangle}")
        print("clipboard copied")
        print(f"absolute time difference: {result.absolute_time_difference}")
        print(f"difference seconds: {seconds_text}")
        return 0

    if args.adjust_ab_cursors_to_30min:
        if args.raw_files:
            print("오류: --adjust-ab-cursors-to-30min은 raw 파일 인자를 사용하지 않습니다.", file=sys.stderr)
            return 1
        try:
            result = adjust_ab_cursors_to_30min(logger)
        except CursorValueError as exc:
            logger.error("A/B cursor 30min adjustment 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        best = result.best_attempt
        if best is None:
            print("AB cursor 30min adjustment failed")
            print(f"reason={result.reason}")
            print("PDF was not printed")
            return 1
        seconds_text = format_seconds_for_console(best.seconds)
        if result.success:
            logger.info("AB cursor 30min adjustment completed")
            try:
                move_cursor_value_window_below_graph_or_safe_area(logger)
            except CursorValueError as exc:
                logger.warning("커서값 창 안전 위치 이동 실패: %s", exc)
            print("AB cursor 30min adjustment completed")
            print(f"a_candidate_rel={format_rel_for_console(best.a_candidate_rel)}")
            print(f"a_candidate_abs={best.a_candidate_abs}")
            print(f"b_release_rel={format_rel_for_console(best.b_release_rel)}")
            print(f"b_release_abs={best.b_release_abs}")
            print(f"absolute time difference: {best.absolute_time_difference}")
            print(f"difference seconds: {seconds_text}")
            print(f"accepted range: {result.accepted_min_seconds}-{result.accepted_max_seconds} seconds")
            print("PDF was not printed")
            return 0
        logger.error("AB cursor 30min adjustment failed: %s", result.reason)
        print("AB cursor 30min adjustment failed")
        print(f"best_a_candidate_rel={format_rel_for_console(best.a_candidate_rel)}")
        print(f"best_a_candidate_abs={best.a_candidate_abs}")
        print(f"best_absolute_time_difference={best.absolute_time_difference}")
        print(f"best_seconds={seconds_text}")
        print(f"reason={result.reason}")
        print("PDF was not printed")
        return 1

    if args.adjust_ab_cursors_to_30min_and_print_pdf:
        if len(args.raw_files) > 1:
            print("오류: --adjust-ab-cursors-to-30min-and-print-pdf는 raw 파일 인자를 최대 1개만 사용할 수 있습니다.", file=sys.stderr)
            return 1
        if not args.raw_files and args.output_pdf is None:
            print(
                "오류: --adjust-ab-cursors-to-30min-and-print-pdf는 기본 PDF 경로 계산용 raw 파일 1개 또는 --output-pdf가 필요합니다.",
                file=sys.stderr,
            )
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0] if args.raw_files else None
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        try:
            adjustment = adjust_ab_cursors_to_30min(logger)
        except CursorValueError as exc:
            logger.error("A/B cursor 30min adjustment 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        if not adjustment.success:
            best = adjustment.best_attempt
            logger.error("AB cursor 30min adjustment failed: %s", adjustment.reason)
            print("AB cursor 30min adjustment failed")
            if best is not None:
                print(f"best_a_candidate_rel={format_rel_for_console(best.a_candidate_rel)}")
                print(f"best_absolute_time_difference={best.absolute_time_difference}")
                print(f"best_seconds={format_seconds_for_console(best.seconds)}")
            print(f"reason={adjustment.reason}")
            print("PDF was not printed")
            return 1
        try:
            move_cursor_value_window_below_graph_or_safe_area(logger)
        except CursorValueError as exc:
            logger.warning("커서값 창 안전 위치 이동 실패, 기존 인쇄 자동화로 접근 가능하면 계속 진행합니다: %s", exc)
        try:
            main_window = focus_universal_viewer_main_window(logger)
        except CursorValueError as exc:
            logger.error("Universal Viewer 포커스 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        opened = build_current_viewer_open_result_for_printing(main_window, config, source, args.output_pdf)
        try:
            pdf_result = print_raw_file_to_pdf(
                opened.source_path,
                config,
                logger,
                explicit_output_pdf=args.output_pdf,
                open_raw_file_fn=lambda *_args, **_kwargs: opened,
            )
        except PdfPrintingError as exc:
            logger.error("A/B cursor 조정 후 PDF 출력 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        best = adjustment.best_attempt
        print("AB cursor 30min adjustment completed")
        if best is not None:
            print(f"absolute time difference: {best.absolute_time_difference}")
            print(f"difference seconds: {format_seconds_for_console(best.seconds)}")
        print("cursor value window moved away from File menu")
        print(f"PDF 출력 파일: {pdf_result.output_pdf_path}")
        print(f"PDF 크기: {pdf_result.pdf_size_bytes} bytes")
        if pdf_result.pdf_page_count is not None:
            print(f"PDF 페이지 수: {pdf_result.pdf_page_count}")
        if pdf_result.validation_warning:
            print(f"PDF 선택 검증 안내: {pdf_result.validation_warning}")
        print(f"실행 로그: {log_path}")
        return 0

    if args.preview_ab_cursor_profile:
        if args.raw_files:
            print("오류: --preview-ab-cursor-profile은 raw 파일 인자를 사용하지 않습니다.", file=sys.stderr)
            return 1
        try:
            result = preview_ab_cursor_profile(logger)
        except CursorValueError as exc:
            logger.error("A/B cursor profile preview 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        print("AB cursor profile preview completed")
        print(f"main window rectangle: {result.main_window.rectangle}")
        print(f"profile main_size: {result.profile['main_size']}")
        print(f"ab_a_start_rel={format_rel_for_console(result.a_start_rel)}")
        print(f"ab_a_start_abs={result.a_start_abs}")
        print(f"ab_a_max_rel={format_rel_for_console(result.a_max_rel)}")
        print(f"ab_a_max_abs={result.a_max_abs}")
        print(f"ab_b_release_target_rel={format_rel_for_console(result.b_release_rel)}")
        print(f"ab_b_release_target_abs={result.b_release_abs}")
        print("no click or drag was performed")
        print(f"실행 로그: {log_path}")
        return 0

    if args.test_ab_cursor_drag_read:
        if args.raw_files:
            print("오류: --test-ab-cursor-drag-read는 raw 파일 인자를 사용하지 않습니다.", file=sys.stderr)
            return 1
        try:
            result = test_ab_cursor_drag_read(logger)
        except CursorValueError as exc:
            logger.error("A/B cursor drag test 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        seconds_text = format_seconds_for_console(result.difference_seconds)
        logger.info("AB cursor drag test completed")
        logger.info("absolute time difference: %s", result.absolute_time_difference)
        logger.info("difference seconds: %s", seconds_text)
        print("AB cursor drag test completed")
        print(f"a_search_left_limit_rel={format_rel_for_console(result.a_search_left_limit_rel)}")
        print(f"a_search_left_limit_abs={result.a_search_left_limit_abs}")
        print(f"a_search_right_limit_rel={format_rel_for_console(result.a_search_right_limit_rel)}")
        print(f"a_search_right_limit_abs={result.a_search_right_limit_abs}")
        print(f"b_release_overshoot_target_rel={format_rel_for_console(result.b_release_overshoot_target_rel)}")
        print(f"b_release_overshoot_target_abs={result.b_release_overshoot_target_abs}")
        print(f"absolute time difference: {result.absolute_time_difference}")
        print(f"difference seconds: {seconds_text}")
        return 0

    if args.inspect_windows:
        try:
            inspection = inspect_windows(logger, config.universal_viewer)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1
        print("=== Universal Viewer 후보 창 ===")
        if inspection.viewer_candidates:
            for window in inspection.viewer_candidates:
                print(format_viewer_candidate(window))
        else:
            print("(후보 창 없음)")
        print("\n=== 일반 창 목록 ===")
        if inspection.general_windows:
            for window in inspection.general_windows:
                print(f"- {window.title}")
        else:
            print("(일반 창 없음)")
        return 0

    if args.inspect_viewer_ui:
        result = inspect_viewer_ui(logger, config.universal_viewer, config.logs_dir)
        print(f"UI 조사 결과 파일: {result.report_path}")
        print(f"실행 로그: {log_path}")
        return 0 if result.main_window_found else 1

    if args.inspect_viewer_menu_paths:
        print("주의: 파일(F), 표시(V) 상위 메뉴만 열고 하위 항목은 선택하지 않습니다.")
        print("파일 열기, 저장, 설정 변경, 인쇄, PDF 생성은 수행하지 않습니다.")
        result = inspect_viewer_menu_paths(logger, config.universal_viewer, config.logs_dir)
        print(f"메뉴 경로 조사 결과 파일: {result.report_path}")
        print(f"실행 로그: {log_path}")
        return 0 if result.main_window_found and result.state_unchanged else 1

    if args.print_to_pdf:
        if len(args.raw_files) != 1:
            print("오류: --print-to-pdf는 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.", file=sys.stderr)
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = print_raw_file_to_pdf(
                source,
                config,
                logger,
                explicit_viewer_exe=args.viewer_exe,
                explicit_output_pdf=args.output_pdf,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except (ViewerLaunchError, PdfPrintingError) as exc:
            logger.error("Universal Viewer PDF 출력 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        print(f"작업본: {result.opened.work_copy_path}")
        print(f"PDF 출력 파일: {result.output_pdf_path}")
        print(f"PDF 크기: {result.pdf_size_bytes} bytes")
        if result.pdf_page_count is not None:
            print(f"PDF 페이지 수: {result.pdf_page_count}")
        if result.validation_warning:
            print(f"PDF 선택 검증 안내: {result.validation_warning}")
        print(f"실행 로그: {log_path}")
        return 0

    if args.inspect_display_group_scrollbar_points_pause:
        if len(args.raw_files) != 1:
            print(
                "오류: --inspect-display-group-scrollbar-points-pause는 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.",
                file=sys.stderr,
            )
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = inspect_display_group_scrollbar_points_pause(
                source,
                config,
                logger,
                explicit_viewer_exe=args.viewer_exe,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except (ViewerLaunchError, DisplayGroupInspectionError) as exc:
            logger.error("표시 그룹 scrollbar 좌표 보정 조사 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        print("표시 그룹 scrollbar 좌표 보정 조사 완료")
        print(f"작업본: {result.opened.work_copy_path}")
        print(f"메뉴 경로: {result.menu_path}")
        print(f"대화상자 rectangle: {result.geometry.dialog_rect}")
        print(f"닫기 방식: {result.close_method}")
        print("OK/Apply/PDF 출력은 수행하지 않았습니다.")
        print(f"실행 로그: {log_path}")
        return 0

    if args.apply_display_group_max_48_confirmed:
        if len(args.raw_files) != 1:
            print("오류: --apply-display-group-max-48-confirmed는 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.", file=sys.stderr)
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = apply_display_group_max_48_confirmed(
                source,
                config,
                logger,
                explicit_viewer_exe=args.viewer_exe,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except (ViewerLaunchError, DisplayGroupInspectionError) as exc:
            logger.error("표시 그룹 max-48 confirmed apply 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        print("주의: max-48 confirmed apply mode가 실행되어 OK로 표시 그룹 설정을 저장했습니다.")
        print(f"작업본: {result.opened.work_copy_path}")
        print(f"메뉴 경로: {result.menu_path}")
        print(f"대화상자 rectangle: {result.geometry.dialog_rect}")
        print("실제 수행 action:")
        for action in result.executed_actions:
            if action.point is not None and action.drag_start is None and action.drag_end is None:
                print(f"- {action.action_type}: point={action.point}")
            else:
                print(f"- {action.action_type}: point={action.point}, drag_start={action.drag_start}, drag_end={action.drag_end}")
        print("안전 요약:")
        for line in result.safety_summary:
            print(f"- {line}")
        print(f"닫기 방식: {result.close_method}")
        print("PDF 출력은 수행하지 않았습니다.")
        print(f"실행 로그: {log_path}")
        return 0

    if args.apply_display_group_geometry_actions_confirmed:
        if len(args.raw_files) != 1:
            print("오류: --apply-display-group-geometry-actions-confirmed는 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.", file=sys.stderr)
            return 1
        if args.heating_point_count is None:
            print("오류: --apply-display-group-geometry-actions-confirmed에는 --heating-point-count N이 필요합니다.", file=sys.stderr)
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = apply_display_group_geometry_actions_confirmed(
                source,
                config,
                logger,
                heating_point_count=args.heating_point_count,
                explicit_viewer_exe=args.viewer_exe,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except (ViewerLaunchError, DisplayGroupInspectionError) as exc:
            logger.error("표시 그룹 geometry confirmed apply 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        print("주의: confirmed apply mode가 실행되어 OK로 표시 그룹 설정을 저장했습니다.")
        print(f"작업본: {result.opened.work_copy_path}")
        print(f"메뉴 경로: {result.menu_path}")
        print(f"대화상자 rectangle: {result.geometry.dialog_rect}")
        print("실제 수행 action:")
        for action in result.executed_actions:
            if action.point is not None and action.drag_start is None and action.drag_end is None:
                print(f"- {action.action_type}: point={action.point}")
            else:
                print(f"- {action.action_type}: point={action.point}, drag_start={action.drag_start}, drag_end={action.drag_end}")
        print("안전 요약:")
        for line in result.safety_summary:
            print(f"- {line}")
        print(f"닫기 방식: {result.close_method}")
        print("PDF 출력은 수행하지 않았습니다.")
        print(f"실행 로그: {log_path}")
        return 0

    if args.apply_display_group_geometry_actions_test:
        if len(args.raw_files) != 1:
            print("오류: --apply-display-group-geometry-actions-test는 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.", file=sys.stderr)
            return 1
        if args.heating_point_count is None:
            print("오류: --apply-display-group-geometry-actions-test에는 --heating-point-count N이 필요합니다.", file=sys.stderr)
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = apply_display_group_geometry_actions_test(
                source,
                config,
                logger,
                heating_point_count=args.heating_point_count,
                explicit_viewer_exe=args.viewer_exe,
                pause_after_paste=args.pause_after_display_group_paste,
                pause_after_scroll=args.pause_after_display_group_scroll,
                continue_without_pause=args.continue_without_display_group_pause,
                pause_before_button_clicks=args.pause_before_display_group_button_clicks,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except (ViewerLaunchError, DisplayGroupInspectionError) as exc:
            logger.error("표시 그룹 geometry 실제-click test 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        print("주의: 개발 검증용 실제-click test mode가 실행되었습니다.")
        print(f"작업본: {result.opened.work_copy_path}")
        print(f"메뉴 경로: {result.menu_path}")
        print(f"대화상자 rectangle: {result.geometry.dialog_rect}")
        print("실제 수행 action:")
        for action in result.executed_actions:
            if action.point is not None:
                print(f"- {action.action_type}: point={action.point}")
            else:
                print(f"- {action.action_type}: drag_start={action.drag_start}, drag_end={action.drag_end}")
        print("안전 요약:")
        for line in result.safety_summary:
            print(f"- {line}")
        print(f"닫기 방식: {result.close_method}")
        print(f"실행 로그: {log_path}")
        return 0

    if args.preview_display_group_profile:
        if len(args.raw_files) != 1:
            print("오류: --preview-display-group-profile은 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.", file=sys.stderr)
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = preview_display_group_max_48_actions(
                source,
                config,
                logger,
                explicit_viewer_exe=args.viewer_exe,
                move_through_profile_points=True,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except (ViewerLaunchError, DisplayGroupInspectionError) as exc:
            logger.error("Display Group profile preview 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        for line in result.report_lines:
            print(line)
        print(f"profile preview 보고서 파일: {result.report_path}")
        print(f"실행 로그: {log_path}")
        return 0

    if args.preview_display_group_max_48_actions:
        if len(args.raw_files) != 1:
            print("오류: --preview-display-group-max-48-actions는 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.", file=sys.stderr)
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = preview_display_group_max_48_actions(
                source,
                config,
                logger,
                explicit_viewer_exe=args.viewer_exe,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except (ViewerLaunchError, DisplayGroupInspectionError) as exc:
            logger.error("표시 그룹 max-48 geometry action preview 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        for line in result.report_lines:
            print(line)
        print(f"preview 보고서 파일: {result.report_path}")
        print(f"실행 로그: {log_path}")
        return 0

    if args.preview_display_group_geometry_actions:
        if len(args.raw_files) != 1:
            print("오류: --preview-display-group-geometry-actions는 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.", file=sys.stderr)
            return 1
        if args.heating_point_count is None:
            print("오류: --preview-display-group-geometry-actions에는 --heating-point-count N이 필요합니다.", file=sys.stderr)
            return 1
        if args.heating_point_count < 1 or args.heating_point_count > 48:
            print("오류: --heating-point-count는 1부터 48까지 지원합니다.", file=sys.stderr)
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = preview_display_group_geometry_actions(
                source,
                config,
                logger,
                heating_point_count=args.heating_point_count,
                explicit_viewer_exe=args.viewer_exe,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except (ViewerLaunchError, DisplayGroupInspectionError) as exc:
            logger.error("표시 그룹 geometry action preview 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        for line in result.report_lines:
            print(line)
        print(f"preview 보고서 파일: {result.report_path}")
        print(f"실행 로그: {log_path}")
        return 0

    if args.inspect_display_group_geometry or args.inspect_display_group_geometry_pause:
        if len(args.raw_files) != 1:
            option_name = (
                "--inspect-display-group-geometry-pause"
                if args.inspect_display_group_geometry_pause
                else "--inspect-display-group-geometry"
            )
            print(f"오류: {option_name}는 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.", file=sys.stderr)
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = inspect_display_group_geometry(
                source,
                config,
                logger,
                explicit_viewer_exe=args.viewer_exe,
                pause_before_close=args.inspect_display_group_geometry_pause,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except (ViewerLaunchError, DisplayGroupInspectionError) as exc:
            logger.error("표시 그룹 설정창 geometry 조사 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        print(f"작업본: {result.opened.work_copy_path}")
        print(f"메뉴 경로: {result.menu_path}")
        print(f"표시 그룹 geometry 조사 결과 파일: {result.report_path}")
        print(f"대화상자 rectangle: {result.geometry.dialog_rect}")
        print(f"대화상자 크기: {result.geometry.width} x {result.geometry.height}")
        print(f"닫기 방식: {result.close_method}")
        print("PDF 출력은 수행하지 않았습니다.")
        print(f"실행 로그: {log_path}")
        return 0

    if args.inspect_display_group_settings or args.inspect_display_group_settings_pause:
        if len(args.raw_files) != 1:
            option_name = (
                "--inspect-display-group-settings-pause"
                if args.inspect_display_group_settings_pause
                else "--inspect-display-group-settings"
            )
            print(f"오류: {option_name}는 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.", file=sys.stderr)
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = inspect_display_group_settings(
                source,
                config,
                logger,
                explicit_viewer_exe=args.viewer_exe,
                pause_before_close=args.inspect_display_group_settings_pause,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except (ViewerLaunchError, DisplayGroupInspectionError) as exc:
            logger.error("표시 그룹 설정창 조사 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        print(f"작업본: {result.opened.work_copy_path}")
        print(f"메뉴 경로: {result.menu_path}")
        print(f"표시 그룹 설정창 조사 결과 파일: {result.report_path}")
        print(f"닫기 방식: {result.close_method}")
        print("PDF 출력은 수행하지 않았습니다.")
        print(f"실행 로그: {log_path}")
        return 0

    if args.open_raw_file:
        if len(args.raw_files) != 1:
            print("오류: --open-raw-file은 명시적인 .DAE 또는 .GEV 파일 1개가 필요합니다.", file=sys.stderr)
            return 1
        try:
            source = resolve_input_files(args.raw_files, config.input_dir)[0]
            result = open_prepared_raw_file(
                source,
                config,
                logger,
                explicit_viewer_exe=args.viewer_exe,
            )
        except RawDataValidationError as exc:
            _record_input_validation_failure(args.raw_files, config, logger, exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1
        except ViewerLaunchError as exc:
            logger.error("Universal Viewer 작업본 열기 실패: %s", exc)
            print(f"오류: {exc}", file=sys.stderr)
            print(f"실행 로그: {log_path}")
            return 1

        print(f"작업본: {result.work_copy_path}")
        print(f"Universal Viewer 실행 파일: {result.viewer_exe_path}")
        print(f"실행 프로세스 PID: {result.process_id if result.process_id is not None else '확인 불가'}")
        print(
            "탐지된 메인 창: "
            f"{result.main_window.title} / {result.main_window.window_class} / "
            f"PID={result.main_window.pid if result.main_window.pid is not None else '확인 불가'}"
        )
        if (
            result.process_id is not None
            and result.main_window.pid is not None
            and result.process_id != result.main_window.pid
        ):
            print("참고: 실행 프로세스 PID와 메인 창 PID가 다릅니다. 기존 Viewer 인스턴스에 열린 경우 정상일 수 있습니다.")
        if result.hint_verified:
            print(f"작업본 파일명 확인: {result.work_copy_path.name} (힌트에 포함됨)")
            print(f"일치한 열린 파일 힌트: {', '.join(result.matched_raw_file_hints)}")
        if result.raw_file_hints:
            print(f"수집된 열린 파일 힌트: {', '.join(result.raw_file_hints)}")
        if result.warning_message:
            print(f"경고: {result.warning_message}")
        print(f"실행 로그: {log_path}")
        return 0

    dry_run = not args.prepare_only
    if dry_run and not args.dry_run:
        print("실행 모드를 지정하지 않아 안전 기본값인 dry-run을 적용합니다.")
    try:
        sources = resolve_input_files(args.raw_files, config.input_dir)
    except RawDataValidationError as exc:
        logger.error("입력 검증 실패: %s", exc)
        failed_source = args.raw_files[0].expanduser().resolve() if args.raw_files else config.input_dir
        append_csv_result(
            config.logs_dir / "processing_results.csv",
            ProcessingResult(
                source_extension=failed_source.suffix.upper(),
                device_family="알 수 없음",
                viewer_profile=config.universal_viewer.name,
                source_path=failed_source,
                working_path=None,
                planned_pdf_path=config.output_dir,
                status=ProcessingStatus.FAILED,
                error_message=str(exc),
                processed_at=datetime.now(),
            ),
        )
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    workflow = Workflow(config, logger, dry_run=dry_run)
    results = [workflow.process(source) for source in sources]
    print(f"처리 결과 CSV: {workflow.csv_path}")
    print(f"실행 로그: {log_path}")
    return 1 if any(result.status is ProcessingStatus.FAILED for result in results) else 0


def format_seconds_for_console(seconds: float) -> str:
    """초 값이 정수이면 소수점 없이 출력한다."""
    return str(int(seconds)) if seconds.is_integer() else f"{seconds:.3f}".rstrip("0").rstrip(".")


def format_rel_for_console(rel: tuple[float, float]) -> str:
    """상대 좌표를 요구 출력 형식에 맞춰 고정 소수점으로 표시한다."""
    return f"({rel[0]:.3f},{rel[1]:.3f})"


def build_current_viewer_open_result_for_printing(
    main_window: object,
    config: AppConfig,
    source: Path | None,
    explicit_output_pdf: Path | None,
) -> ViewerOpenResult:
    """이미 열린 Universal Viewer를 Stage 4 인쇄 함수가 사용할 수 있는 결과 객체로 감싼다."""
    if source is not None:
        source_path = source
        planned_pdf_path = config.output_dir / build_pdf_filename(source)
        work_copy_path = source
    else:
        source_path = Path("current_universal_viewer_raw")
        planned_pdf_path = explicit_output_pdf or (config.output_dir / "current_universal_viewer.pdf")
        work_copy_path = source_path
    title = str(getattr(main_window, "title"))
    pid = getattr(main_window, "pid", None)
    window_class = str(getattr(main_window, "class_name", getattr(main_window, "window_class", "")))
    handle = int(getattr(main_window, "hwnd", getattr(main_window, "handle", 0)))
    viewer_window = WindowInfo(
        title=title,
        pid=pid,
        window_class=window_class,
        backend="win32",
        handle=handle,
        main_window=True,
        helper_window=False,
    )
    return ViewerOpenResult(
        source_path=source_path,
        work_copy_path=work_copy_path,
        viewer_exe_path=Path("current_universal_viewer"),
        planned_pdf_path=planned_pdf_path,
        process_id=pid,
        main_window=viewer_window,
        raw_file_hints=(),
        hint_verified=True,
        matched_raw_file_hints=(),
        warning_message="",
    )


def _record_input_validation_failure(
    raw_files: list[Path],
    config: AppConfig,
    logger: object,
    exc: RawDataValidationError,
) -> None:
    """입력 검증 실패를 기존 CSV 형식으로 기록한다."""
    failed_source = raw_files[0].expanduser().resolve() if raw_files else config.input_dir
    logger.error("입력 검증 실패: %s", exc)  # type: ignore[attr-defined]
    append_csv_result(
        config.logs_dir / "processing_results.csv",
        ProcessingResult(
            source_extension=failed_source.suffix.upper(),
            device_family="알 수 없음",
            viewer_profile=config.universal_viewer.name,
            source_path=failed_source,
            working_path=None,
            planned_pdf_path=config.output_dir,
            status=ProcessingStatus.FAILED,
            error_message=str(exc),
            processed_at=datetime.now(),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
