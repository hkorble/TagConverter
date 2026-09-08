from __future__ import annotations

import os
import sys
import time
import uuid
import zipfile
from pathlib import Path

import pandas as pd

# Add project root to Python module search path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pdf_verifier import extract_all_pdf_texts_from_zip, verify_pdf_tags
from workflow_engine import WorkflowPaths, finalize_workflow, prepare_workflow, resolve_drawing_path


def log_step(msg: str) -> None:
    print(f"  [TEST] {msg}", flush=True)


def run_test_suite() -> bool:
    print("\n" + "=" * 70)
    print("           PadXPRESS Standardized System Test Suite")
    print("=" * 70)
    print("  Pipelines Tested: Unified ZIP Archive Engine")
    print("  Validation: Deep Vector PDF Text Extraction via pypdf")
    print("  Mapping Convention: Prefix 'T#' to Scovan Tag (e.g. T#<TAG>)")
    print(f"  Project Root: {PROJECT_ROOT}\n")

    # Locate test drawings inside "Testing Drawings" folder
    test_dir = PROJECT_ROOT / "Testing Drawings"
    dwg1 = test_dir / "Testing_Drawing.dwg"
    dwg2 = test_dir / "Testing_Drawing2.dwg"

    if not dwg1.is_file() or not dwg2.is_file():
        dwg1 = resolve_drawing_path("Testing_Drawing.dwg")
        dwg2 = resolve_drawing_path("Testing_Drawing2.dwg")

    if not dwg1.is_file() or not dwg2.is_file():
        print("ERROR: Test drawings 'Testing_Drawing.dwg' and/or 'Testing_Drawing2.dwg' not found!")
        return False

    print(f"  Drawing 1: {dwg1.name}")
    print(f"  Drawing 2: {dwg2.name}\n")

    results: dict[str, str] = {}
    out_dir = Path.home() / "Downloads" / "TestSuite_Outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------
    # TEST 1: ZIP Package (Branching Subfolders) - Dual Tagging
    # -------------------------------------------------------------
    print("-" * 70)
    print("TEST 1: Multi-Drawing ZIP Package - Dual Tagging (dual_tagging)")
    print("-" * 70)
    try:
        t1_zip_in = out_dir / "Test1_Branching_DualTag_Input.zip"
        t1_zip_out = out_dir / "Test1_Branching_DualTag_Updated.zip"

        log_step("Building multi-folder branching input ZIP...")
        with zipfile.ZipFile(t1_zip_in, "w") as zf:
            zf.write(dwg1, "NATIVE/Area_North/Process_Unit_10/Testing_Drawing.dwg")
            zf.write(dwg2, "NATIVE/Area_South/Utility_Unit_20/Testing_Drawing2.dwg")
            zf.writestr("PDF/Area_North/Process_Unit_10/Testing_Drawing.pdf", b"OLD PDF A1")
            zf.writestr("PDF/Area_South/Utility_Unit_20/Testing_Drawing2.pdf", b"OLD PDF B1")
            zf.writestr("REPORTS/placeholder.txt", b"REPORTS PLACEHOLDER")

        t1_paths = WorkflowPaths.from_payload({"dwg_path": str(t1_zip_in), "output_path": str(t1_zip_out)})

        log_step("Running Prepare Phase...")
        prep1 = prepare_workflow("dual_tagging", t1_paths, log_step)
        log_step(f"Prepare complete: {prep1['mapping_rows']} unique tag(s) indexed.")

        log_step("Applying 'T#' prefix test mappings...")
        m1 = pd.read_excel(t1_paths.mapping, sheet_name="Mapping")
        m1["Client Tag Mapping"] = m1["Scovan Tag"].apply(lambda tag: f"T#{tag}" if str(tag).strip() else "")
        with pd.ExcelWriter(t1_paths.mapping, engine="openpyxl") as w:
            m1.to_excel(w, index=False, sheet_name="Mapping")

        test1_mappings = dict(zip(m1["Scovan Tag"], m1["Client Tag Mapping"]))

        log_step("Running Finalize Phase, Vector PDF Plotting & Packaging...")
        fin1 = finalize_workflow("dual_tagging", t1_paths, log_step)

        # 1. Verify ZIP archive contents
        t1_archive_ok = False
        if t1_zip_out.is_file():
            with zipfile.ZipFile(t1_zip_out, "r") as zf:
                names = zf.namelist()
                dwg1_in = "NATIVE/Area_North/Process_Unit_10/Testing_Drawing.dwg" in names
                dwg2_in = "NATIVE/Area_South/Utility_Unit_20/Testing_Drawing2.dwg" in names
                pdf1_in = "PDF/Area_North/Process_Unit_10/Testing_Drawing.pdf" in names
                pdf2_in = "PDF/Area_South/Utility_Unit_20/Testing_Drawing2.pdf" in names
                rep_in = any("PadX_Automan_Report.xlsx" in n for n in names)
                t1_archive_ok = dwg1_in and dwg2_in and pdf1_in and pdf2_in and rep_in

        if not t1_archive_ok:
            raise RuntimeError("Output ZIP archive missing expected DWGs, PDFs, or report.")

        log_step(f"Output ZIP verified ({t1_zip_out.stat().st_size:,} bytes).")

        # 2. MANDATORY CHECK: Analyze Vector PDFs with pypdf
        log_step("Executing mandatory PDF text verification (Dual Tagging)...")
        pdf_texts1 = extract_all_pdf_texts_from_zip(t1_zip_out)
        ver1 = verify_pdf_tags(pdf_texts1, test1_mappings, "dual_tagging", log_step)

        if ver1["success"]:
            results["Test 1: ZIP Package Dual Tagging"] = "PASSED"
            log_step(f"PASSED: Verified {ver1['passed_checks']} tag instances across {ver1['pdf_count']} PDF(s).\n")
        else:
            results["Test 1: ZIP Package Dual Tagging"] = f"FAILED ({ver1['failed_checks']} tag checks failed)"
            log_step(f"FAILED: {ver1['failed_checks']} tag check(s) failed in generated vector PDFs.\n")

    except Exception as exc:
        results["Test 1: ZIP Package Dual Tagging"] = f"FAILED ({exc})"
        print(f"  [ERROR] {exc}\n")

    # -------------------------------------------------------------
    # TEST 2: ZIP Package (Branching Subfolders) - Client Translation
    # -------------------------------------------------------------
    print("-" * 70)
    print("TEST 2: Multi-Drawing ZIP Package - Client Translation (client_translation)")
    print("-" * 70)
    try:
        t2_zip_in = out_dir / "Test2_Branching_Translation_Input.zip"
        t2_zip_out = out_dir / "Test2_Branching_Translation_Updated.zip"

        log_step("Building multi-folder branching input ZIP...")
        with zipfile.ZipFile(t2_zip_in, "w") as zf:
            zf.write(dwg1, "NATIVE/Plant_East/Facility_30/Testing_Drawing.dwg")
            zf.write(dwg2, "NATIVE/Plant_West/Facility_40/Testing_Drawing2.dwg")
            zf.writestr("PDF/Plant_East/Facility_30/Testing_Drawing.pdf", b"OLD PDF E30")
            zf.writestr("PDF/Plant_West/Facility_40/Testing_Drawing2.pdf", b"OLD PDF W40")
            zf.writestr("REPORTS/placeholder.txt", b"REPORTS PLACEHOLDER")

        t2_paths = WorkflowPaths.from_payload({"dwg_path": str(t2_zip_in), "output_path": str(t2_zip_out)})

        log_step("Running Prepare Phase...")
        prep2 = prepare_workflow("client_translation", t2_paths, log_step)
        log_step(f"Prepare complete: {prep2['mapping_rows']} unique tag(s) indexed.")

        log_step("Applying 'T#' prefix test mappings...")
        m2 = pd.read_excel(t2_paths.mapping, sheet_name="Mapping")
        m2["Client Tag Mapping"] = m2["Scovan Tag"].apply(lambda tag: f"T#{tag}" if str(tag).strip() else "")
        with pd.ExcelWriter(t2_paths.mapping, engine="openpyxl") as w:
            m2.to_excel(w, index=False, sheet_name="Mapping")

        test2_mappings = dict(zip(m2["Scovan Tag"], m2["Client Tag Mapping"]))

        log_step("Running Finalize Phase, Vector PDF Plotting & Packaging...")
        fin2 = finalize_workflow("client_translation", t2_paths, log_step)

        # 1. Verify ZIP archive contents
        t2_archive_ok = False
        if t2_zip_out.is_file():
            with zipfile.ZipFile(t2_zip_out, "r") as zf:
                names = zf.namelist()
                dwg1_in = "NATIVE/Plant_East/Facility_30/Testing_Drawing.dwg" in names
                dwg2_in = "NATIVE/Plant_West/Facility_40/Testing_Drawing2.dwg" in names
                pdf1_in = "PDF/Plant_East/Facility_30/Testing_Drawing.pdf" in names
                pdf2_in = "PDF/Plant_West/Facility_40/Testing_Drawing2.pdf" in names
                rep_in = any("PadX_Automan_Report.xlsx" in n for n in names)
                t2_archive_ok = dwg1_in and dwg2_in and pdf1_in and pdf2_in and rep_in

        if not t2_archive_ok:
            raise RuntimeError("Output ZIP archive missing expected DWGs, PDFs, or report.")

        log_step(f"Output ZIP verified ({t2_zip_out.stat().st_size:,} bytes).")

        # 2. MANDATORY CHECK: Analyze Vector PDFs with pypdf
        log_step("Executing mandatory PDF text verification (Client Translation)...")
        pdf_texts2 = extract_all_pdf_texts_from_zip(t2_zip_out)
        ver2 = verify_pdf_tags(pdf_texts2, test2_mappings, "client_translation", log_step)

        if ver2["success"]:
            results["Test 2: ZIP Package Client Translation"] = "PASSED"
            log_step(f"PASSED: Verified {ver2['passed_checks']} tag instances across {ver2['pdf_count']} PDF(s).\n")
        else:
            results["Test 2: ZIP Package Client Translation"] = f"FAILED ({ver2['failed_checks']} tag checks failed)"
            log_step(f"FAILED: {ver2['failed_checks']} tag check(s) failed in generated vector PDFs.\n")

    except Exception as exc:
        results["Test 2: ZIP Package Client Translation"] = f"FAILED ({exc})"
        print(f"  [ERROR] {exc}\n")

    # -------------------------------------------------------------
    # FINAL SUMMARY REPORT
    # -------------------------------------------------------------
    print("=" * 70)
    print("                 SYSTEM TEST SUITE SUMMARY")
    print("=" * 70)
    all_passed = True
    for test_title, status in results.items():
        pass_flag = status == "PASSED"
        if not pass_flag:
            all_passed = False
        symbol = "OK" if pass_flag else "FAIL"
        print(f"  [{symbol:<4}] {test_title:<48} : {status}")
    print("=" * 70)

    if all_passed and len(results) == 2:
        print("  ALL SYSTEM SCENARIOS & PDF VERIFICATIONS PASSED SUCCESSFULLY!")
    else:
        print("  SOME TEST SCENARIOS FAILED. PLEASE REVIEW LOGS ABOVE.")
    print("=" * 70 + "\n")
    return all_passed and len(results) == 2


if __name__ == "__main__":
    success = run_test_suite()
    sys.exit(0 if success else 1)
