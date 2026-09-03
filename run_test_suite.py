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

from workflow_engine import WorkflowPaths, finalize_workflow, prepare_workflow, resolve_drawing_path


def log_step(msg: str) -> None:
    print(f"  [TEST] {msg}", flush=True)


def run_test_suite() -> bool:
    print("\n" + "=" * 65)
    print("        PadX Automan Standardized System Test Suite")
    print("=" * 65)
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
    # TEST 1: Standalone DWG - Dual Tagging
    # -------------------------------------------------------------
    print("-" * 65)
    print("TEST 1: Standalone DWG - Dual Tagging (dual_tagging)")
    print("-" * 65)
    try:
        t1_out = out_dir / "Test1_Single_DualTagging_Updated.dwg"
        t1_paths = WorkflowPaths.from_payload({"dwg_path": str(dwg1), "output_path": str(t1_out)})
        
        log_step("Running Prepare Phase...")
        prep1 = prepare_workflow("dual_tagging", t1_paths, log_step)
        log_step(f"Prepare complete: {prep1['mapping_rows']} tag(s) indexed.")

        log_step("Applying 'T#' prefix test mappings...")
        m1 = pd.read_excel(t1_paths.mapping, sheet_name="Mapping")
        m1["Client Tag Mapping"] = m1["Scovan Tag"].apply(lambda tag: f"T#{tag}" if str(tag).strip() else "")
        with pd.ExcelWriter(t1_paths.mapping, engine="openpyxl") as w:
            m1.to_excel(w, index=False, sheet_name="Mapping")

        log_step("Running Finalize Phase & ATTSYNC...")
        fin1 = finalize_workflow("dual_tagging", t1_paths, log_step)
        
        t1_ok = t1_out.is_file() and t1_out.stat().st_size > 0
        if t1_ok:
            results["Test 1: Single DWG Dual Tagging"] = "PASSED"
            log_step(f"PASSED: Output generated ({t1_out.stat().st_size:,} bytes)\n")
        else:
            results["Test 1: Single DWG Dual Tagging"] = "FAILED"
            log_step("FAILED: Output file missing or zero bytes\n")
    except Exception as exc:
        results["Test 1: Single DWG Dual Tagging"] = f"FAILED ({exc})"
        print(f"  [ERROR] {exc}\n")

    # -------------------------------------------------------------
    # TEST 2: Standalone DWG - Client Translation
    # -------------------------------------------------------------
    print("-" * 65)
    print("TEST 2: Standalone DWG - Client Translation (client_translation)")
    print("-" * 65)
    try:
        t2_out = out_dir / "Test2_Single_Translation_Updated.dwg"
        t2_paths = WorkflowPaths.from_payload({"dwg_path": str(dwg1), "output_path": str(t2_out)})

        log_step("Running Prepare Phase...")
        prep2 = prepare_workflow("client_translation", t2_paths, log_step)
        log_step(f"Prepare complete: {prep2['mapping_rows']} tag(s) indexed.")

        log_step("Applying 'T#' prefix test mappings...")
        m2 = pd.read_excel(t2_paths.mapping, sheet_name="Mapping")
        m2["Client Tag Mapping"] = m2["Scovan Tag"].apply(lambda tag: f"T#{tag}" if str(tag).strip() else "")
        with pd.ExcelWriter(t2_paths.mapping, engine="openpyxl") as w:
            m2.to_excel(w, index=False, sheet_name="Mapping")

        log_step("Running Finalize Phase & ATTSYNC...")
        fin2 = finalize_workflow("client_translation", t2_paths, log_step)

        t2_ok = t2_out.is_file() and t2_out.stat().st_size > 0
        if t2_ok:
            results["Test 2: Single DWG Client Translation"] = "PASSED"
            log_step(f"PASSED: Output generated ({t2_out.stat().st_size:,} bytes)\n")
        else:
            results["Test 2: Single DWG Client Translation"] = "FAILED"
            log_step("FAILED: Output file missing or zero bytes\n")
    except Exception as exc:
        results["Test 2: Single DWG Client Translation"] = f"FAILED ({exc})"
        print(f"  [ERROR] {exc}\n")

    # -------------------------------------------------------------
    # TEST 3: ZIP Package (Branching Subfolders) - Dual Tagging
    # -------------------------------------------------------------
    print("-" * 65)
    print("TEST 3: ZIP Package (Branching NATIVE Subfolders) - Dual Tagging")
    print("-" * 65)
    try:
        t3_zip_in = out_dir / "Test3_Branching_Input.zip"
        t3_zip_out = out_dir / "Test3_Branching_Updated.zip"

        log_step("Building multi-folder branching input ZIP...")
        with zipfile.ZipFile(t3_zip_in, "w") as zf:
            zf.write(dwg1, "NATIVE/Area_North/Process_Unit_10/Testing_Drawing.dwg")
            zf.write(dwg2, "NATIVE/Area_South/Utility_Unit_20/Testing_Drawing2.dwg")
            zf.writestr("PDF/Area_North/Process_Unit_10/Testing_Drawing.pdf", b"OLD PDF A1")
            zf.writestr("PDF/Area_South/Utility_Unit_20/Testing_Drawing2.pdf", b"OLD PDF B1")
            zf.writestr("REPORTS/placeholder.txt", b"REPORTS PLACEHOLDER")

        t3_paths = WorkflowPaths.from_payload({"dwg_path": str(t3_zip_in), "output_path": str(t3_zip_out)})

        log_step("Running Prepare Phase...")
        prep3 = prepare_workflow("dual_tagging", t3_paths, log_step)
        log_step(f"Prepare complete: {prep3['mapping_rows']} unique tag(s) indexed.")

        log_step("Applying 'T#' prefix test mappings...")
        m3 = pd.read_excel(t3_paths.mapping, sheet_name="Mapping")
        m3["Client Tag Mapping"] = m3["Scovan Tag"].apply(lambda tag: f"T#{tag}" if str(tag).strip() else "")
        with pd.ExcelWriter(t3_paths.mapping, engine="openpyxl") as w:
            m3.to_excel(w, index=False, sheet_name="Mapping")

        log_step("Running Finalize Phase, Vector PDF Plotting & Re-zipping...")
        fin3 = finalize_workflow("dual_tagging", t3_paths, log_step)

        t3_ok = False
        if t3_zip_out.is_file():
            with zipfile.ZipFile(t3_zip_out, "r") as zf:
                names = zf.namelist()
                dwg1_in = "NATIVE/Area_North/Process_Unit_10/Testing_Drawing.dwg" in names
                dwg2_in = "NATIVE/Area_South/Utility_Unit_20/Testing_Drawing2.dwg" in names
                pdf1_in = "PDF/Area_North/Process_Unit_10/Testing_Drawing.pdf" in names
                pdf2_in = "PDF/Area_South/Utility_Unit_20/Testing_Drawing2.pdf" in names
                rep_in = "REPORTS/PadX_Automan_Report.xlsx" in names
                t3_ok = dwg1_in and dwg2_in and pdf1_in and pdf2_in and rep_in

        if t3_ok:
            results["Test 3: ZIP Package Dual Tagging"] = "PASSED"
            log_step(f"PASSED: Output package verified ({t3_zip_out.stat().st_size:,} bytes)\n")
        else:
            results["Test 3: ZIP Package Dual Tagging"] = "FAILED"
            log_step("FAILED: Output ZIP missing expected branching files or report\n")
    except Exception as exc:
        results["Test 3: ZIP Package Dual Tagging"] = f"FAILED ({exc})"
        print(f"  [ERROR] {exc}\n")

    # -------------------------------------------------------------
    # TEST 4: ZIP Package (Branching Subfolders) - Client Translation
    # -------------------------------------------------------------
    print("-" * 65)
    print("TEST 4: ZIP Package (Branching NATIVE Subfolders) - Client Translation")
    print("-" * 65)
    try:
        t4_zip_in = out_dir / "Test4_Branching_Input.zip"
        t4_zip_out = out_dir / "Test4_Branching_Updated.zip"

        log_step("Building multi-folder branching input ZIP...")
        with zipfile.ZipFile(t4_zip_in, "w") as zf:
            zf.write(dwg1, "NATIVE/Plant_East/Facility_30/Testing_Drawing.dwg")
            zf.write(dwg2, "NATIVE/Plant_West/Facility_40/Testing_Drawing2.dwg")
            zf.writestr("PDF/Plant_East/Facility_30/Testing_Drawing.pdf", b"OLD PDF E30")
            zf.writestr("PDF/Plant_West/Facility_40/Testing_Drawing2.pdf", b"OLD PDF W40")

        t4_paths = WorkflowPaths.from_payload({"dwg_path": str(t4_zip_in), "output_path": str(t4_zip_out)})

        log_step("Running Prepare Phase...")
        prep4 = prepare_workflow("client_translation", t4_paths, log_step)
        log_step(f"Prepare complete: {prep4['mapping_rows']} unique tag(s) indexed.")

        log_step("Applying 'T#' prefix test mappings...")
        m4 = pd.read_excel(t4_paths.mapping, sheet_name="Mapping")
        m4["Client Tag Mapping"] = m4["Scovan Tag"].apply(lambda tag: f"T#{tag}" if str(tag).strip() else "")
        with pd.ExcelWriter(t4_paths.mapping, engine="openpyxl") as w:
            m4.to_excel(w, index=False, sheet_name="Mapping")

        log_step("Running Finalize Phase, Vector PDF Plotting & Re-zipping...")
        fin4 = finalize_workflow("client_translation", t4_paths, log_step)

        t4_ok = False
        if t4_zip_out.is_file():
            with zipfile.ZipFile(t4_zip_out, "r") as zf:
                names = zf.namelist()
                dwg1_in = "NATIVE/Plant_East/Facility_30/Testing_Drawing.dwg" in names
                dwg2_in = "NATIVE/Plant_West/Facility_40/Testing_Drawing2.dwg" in names
                pdf1_in = "PDF/Plant_East/Facility_30/Testing_Drawing.pdf" in names
                pdf2_in = "PDF/Plant_West/Facility_40/Testing_Drawing2.pdf" in names
                rep_in = "PadX_Automan_Report.xlsx" in names
                t4_ok = dwg1_in and dwg2_in and pdf1_in and pdf2_in and rep_in

        if t4_ok:
            results["Test 4: ZIP Package Client Translation"] = "PASSED"
            log_step(f"PASSED: Output package verified ({t4_zip_out.stat().st_size:,} bytes)\n")
        else:
            results["Test 4: ZIP Package Client Translation"] = "FAILED"
            log_step("FAILED: Output ZIP missing expected branching files or report\n")
    except Exception as exc:
        results["Test 4: ZIP Package Client Translation"] = f"FAILED ({exc})"
        print(f"  [ERROR] {exc}\n")

    # -------------------------------------------------------------
    # FINAL SUMMARY REPORT
    # -------------------------------------------------------------
    print("=" * 65)
    print("                 SYSTEM TEST SUITE SUMMARY")
    print("=" * 65)
    all_passed = True
    for test_title, status in results.items():
        pass_flag = status == "PASSED"
        if not pass_flag:
            all_passed = False
        symbol = "OK" if pass_flag else "FAIL"
        print(f"  [{symbol:<4}] {test_title:<45} : {status}")
    print("=" * 65)

    if all_passed:
        print("  ALL 4 SYSTEM SCENARIOS PASSED SUCCESSFULLY! SYSTEM IS HEALTHY.")
    else:
        print("  SOME TEST SCENARIOS FAILED. PLEASE REVIEW LOGS ABOVE.")
    print("=" * 65 + "\n")
    return all_passed


if __name__ == "__main__":
    success = run_test_suite()
    sys.exit(0 if success else 1)
