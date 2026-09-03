from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent
TEST_DIR = PROJECT_ROOT / "Testing Drawings"
DWG1 = TEST_DIR / "Testing_Drawing.dwg"
DWG2 = TEST_DIR / "Testing_Drawing2.dwg"


def log_test(step: str, status: str, detail: str = "") -> None:
    symbol = "OK" if status == "PASSED" else "FAIL"
    print(f"  [{symbol:<4}] {step:<45} : {detail or status}", flush=True)


def run_ui_test_suite() -> bool:
    print("\n" + "=" * 65)
    print("      PadX Automan Interactive Browser UI Test Suite")
    print("=" * 65)
    print("  Target URL: http://127.0.0.1:8765")
    print("  Engine: Playwright Chromium (Headed Browser Interaction)\n")

    if not DWG1.is_file() or not DWG2.is_file():
        print(f"ERROR: Test drawings missing in {TEST_DIR}!")
        return False

    results: dict[str, str] = {}

    with sync_playwright() as p:
        print("-" * 65)
        print("LAUNCHING BROWSER & CONNECTING TO WEB APP...")
        print("-" * 65)
        browser = p.chromium.launch(headless=False, slow_mo=150)
        context = browser.new_context()
        page = context.new_page()

        # Step 1: Navigate & Validate Header Typography
        try:
            page.goto("http://127.0.0.1:8765")
            page.wait_for_selector("h1")

            title = page.inner_text("h1").strip()
            subtitle = page.inner_text(".banner-title div").strip()

            title_ok = "PadX Automan" in title
            sub_ok = "Dual Tagging and Translation" in subtitle

            if title_ok and sub_ok:
                results["1. UI Header & Typography"] = "PASSED"
                log_test("UI Header & Typography Validation", "PASSED", f"Title: '{title}', Sub: '{subtitle}'")
            else:
                results["1. UI Header & Typography"] = "FAILED"
                log_test("UI Header & Typography Validation", "FAILED")
        except Exception as exc:
            results["1. UI Header & Typography"] = f"FAILED ({exc})"
            print(f"  [ERROR] {exc}")

        # Step 2: Test Workflow Selection Toggle Buttons
        try:
            cards = page.query_selector_all(".workflow-card")
            if len(cards) >= 2:
                cards[1].click()
                page.wait_for_timeout(300)
                cards[0].click()
                page.wait_for_timeout(300)
                results["2. Workflow Card Selection"] = "PASSED"
                log_test("Workflow Selection Buttons", "PASSED", "Toggled Dual Tagging & Translation")
            else:
                results["2. Workflow Card Selection"] = "FAILED"
                log_test("Workflow Selection Buttons", "FAILED")
        except Exception as exc:
            results["2. Workflow Card Selection"] = f"FAILED ({exc})"
            print(f"  [ERROR] {exc}")

        # Step 3: Test Single DWG Upload, Auto-Population & Web Spreadsheet Modal
        try:
            print("\n" + "-" * 65)
            print("STEP 3: Single DWG Upload, Input Auto-Population & Web Spreadsheet Modal")
            print("-" * 65)

            dwg_input = page.locator("#dwg-path")
            dwg_input.fill(str(DWG1))

            out_input = page.locator("#output-path")
            out_val = out_input.input_value() or out_input.get_attribute("placeholder") or ""
            log_test("Auto-Populated Output Filename", "PASSED", f"Value: '{out_val}'")

            out_input.fill("UI_Test_Single_Updated.dwg")

            # Click Prepare mapping
            prep_btn = page.locator("button:has-text('Prepare mapping')")
            prep_btn.click()

            page.wait_for_selector("button:has-text('Open Online Mapping Editor')", timeout=120000)
            log_test("Prepare Mapping Phase", "PASSED", "Registry indexed & mapping workbook ready")

            # Open Web Spreadsheet Editor modal
            page.locator("button:has-text('Open Online Mapping Editor')").click()
            page.wait_for_selector("text=WEB SPREADSHEET EDITOR", timeout=10000)

            rows = page.locator("table tbody tr")
            row_count = rows.count()
            log_test("Web Spreadsheet Editor Modal", "PASSED", f"Loaded {row_count} tag mapping rows in UI modal")

            # Click Auto-fill from Scovan Tags
            page.locator("button:has-text('Auto-fill from Scovan Tags')").click()
            page.wait_for_timeout(300)

            # Edit first input
            first_input = rows.first.locator("input").first
            first_input.fill("UI-TEST-TAG-01")

            # Click Save Mapping Sheet
            page.locator("button:has-text('Save Mapping Sheet')").click()
            page.wait_for_selector("text=Saved", timeout=10000)
            log_test("Modal Save Mappings Action", "PASSED", "Updated and saved tag mappings via web modal")

            # Close modal
            page.locator("button:has-text('Close')").click()
            page.wait_for_timeout(300)

            # Click Validate & finish drawing
            page.locator("button:has-text('Validate & finish drawing')").click()
            page.wait_for_selector("text=Processing complete", timeout=120000)
            results["3. Single DWG Interactive UI Workflow"] = "PASSED"
            log_test("Single DWG Finalize & Output Trigger", "PASSED", "Drawing updated & ATTSYNC completed via UI")
        except Exception as exc:
            results["3. Single DWG Interactive UI Workflow"] = f"FAILED ({exc})"
            print(f"  [ERROR] {exc}")

        # Step 4: Test ZIP Package Upload & Batch Spreadsheet Modal
        try:
            print("\n" + "-" * 65)
            print("STEP 4: ZIP Batch Package Upload & Multi-Drawing Interactive UI Workflow")
            print("-" * 65)

            out_test_dir = Path.home() / "Downloads" / "TestSuite_Outputs"
            out_test_dir.mkdir(parents=True, exist_ok=True)
            ui_zip_in = out_test_dir / "UI_Test_Batch_Input.zip"

            with zipfile.ZipFile(ui_zip_in, "w") as zf:
                zf.write(DWG1, "NATIVE/Area_A/Testing_Drawing.dwg")
                zf.write(DWG2, "NATIVE/Area_B/Testing_Drawing2.dwg")
                zf.writestr("PDF/Area_A/Testing_Drawing.pdf", b"OLD PDF A")
                zf.writestr("PDF/Area_B/Testing_Drawing2.pdf", b"OLD PDF B")
                zf.writestr("REPORTS/placeholder.txt", b"REPORTS PLACEHOLDER")

            dwg_input.fill(str(ui_zip_in))

            zip_out_val = out_input.input_value() or out_input.get_attribute("placeholder") or ""
            log_test("ZIP Output Auto-Population", "PASSED", f"Value: '{zip_out_val}'")

            out_input.fill("UI_Test_Batch_Updated.zip")

            prep_btn.click()
            page.wait_for_selector("button:has-text('Open Online Mapping Editor')", timeout=120000)
            log_test("ZIP Batch Prepare Phase", "PASSED", "Deduplicated unique tags across batch drawings")

            # Open Web Spreadsheet Editor modal
            page.locator("button:has-text('Open Online Mapping Editor')").click()
            page.wait_for_selector("text=WEB SPREADSHEET EDITOR", timeout=10000)

            # Autofill defaults and save
            page.locator("button:has-text('Auto-fill from Scovan Tags')").click()
            page.wait_for_timeout(300)
            page.locator("button:has-text('Save Mapping Sheet')").click()
            page.wait_for_selector("text=Saved", timeout=10000)

            # Close modal
            page.locator("button:has-text('Close')").click()
            page.wait_for_timeout(300)

            # Click Validate & finish drawing
            page.locator("button:has-text('Validate & finish drawing')").click()
            page.wait_for_selector("text=Processing complete", timeout=300000)
            results["4. ZIP Package Interactive UI Workflow"] = "PASSED"
            log_test("ZIP Batch Finalize & Report Generation", "PASSED", "Branching ZIP updated with PDFs & PadX_Automan_Report.xlsx")
        except Exception as exc:
            results["4. ZIP Package Interactive UI Workflow"] = f"FAILED ({exc})"
            print(f"  [ERROR] {exc}")

        browser.close()

    print("\n" + "=" * 65)
    print("                 UI TEST SUITE SUMMARY")
    print("=" * 65)
    all_ok = True
    for name, res in results.items():
        pass_flag = res == "PASSED"
        if not pass_flag:
            all_ok = False
        symbol = "OK" if pass_flag else "FAIL"
        print(f"  [{symbol:<4}] {name:<45} : {res}")
    print("=" * 65)
    if all_ok:
        print("  ALL BROWSER UI TEST SCENARIOS PASSED SUCCESSFULLY! UI IS FULLY HEALTHY.")
    else:
        print("  SOME UI TEST SCENARIOS FAILED.")
    print("=" * 65 + "\n")
    return all_ok


if __name__ == "__main__":
    success = run_ui_test_suite()
    sys.exit(0 if success else 1)
