from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from config import WORKFLOW_CONFIG
from workflow_common import (
    apply_mapping_sheet,
    clean_workspace_artifacts,
    extract_groups,
    find_accoreconsole,
    format_mapping,
    is_placeholder,
    unpack_tag,
    write_mapping_sheet,
)

Log = Callable[[str], None]


def resolve_drawing_path(raw_path: str) -> Path:
    """Locate drawing or zip package independently of exact file path or browser upload name."""
    if not raw_path.strip():
        return Path(raw_path)
    p = Path(raw_path).expanduser()
    if p.is_file():
        return p.resolve()

    filename = p.name
    candidates: list[Path] = []

    downloads_dir = Path.home() / "Downloads"
    project_root = Path(__file__).resolve().parent
    desktop_dir = Path.home() / "Desktop"

    for root_dir in (downloads_dir, project_root, desktop_dir):
        if root_dir.is_dir():
            candidates.extend([f for f in root_dir.rglob(filename) if f.is_file()])

    if candidates:
        candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return candidates[0].resolve()

    return p.resolve()


@dataclass(frozen=True)
class WorkflowPaths:
    base_dir: Path
    dwg: Path
    registry: Path
    mapping: Path
    output: Path
    groups: Path
    large_groups: Path
    lisp: Path
    script: Path
    attsync: Path

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "WorkflowPaths":
        app_root = Path(__file__).resolve().parent
        dwg = resolve_drawing_path(str(payload.get("dwg_path", "")))
        base = Path(str(payload.get("workspace_path") or app_root)).expanduser().resolve()
        
        is_zip = dwg.suffix.lower() == ".zip"
        ext = ".zip" if is_zip else ".dwg"
        raw_stem = dwg.stem
        clean_stem = re.sub(r"_Updated$", "", raw_stem, flags=re.IGNORECASE)
        clean_stem = re.sub(r"_(dualtagged|translated|DualTagged|ClientTranslated)$", "", clean_stem, flags=re.IGNORECASE)
        raw_output = str(payload.get("output_path", "")).strip()

        workflow_str = str(payload.get("workflow", ""))
        suffix = "_translated" if "client_translation" in workflow_str else "_dualtagged"

        if not raw_output:
            output_path = (Path.home() / "Downloads" / f"{clean_stem}{suffix}{ext}").resolve()
        else:
            p_out = Path(raw_output).expanduser()
            if p_out.is_absolute() or ("\\" in raw_output or "/" in raw_output):
                output_path = p_out.resolve()
            else:
                output_path = (Path.home() / "Downloads" / raw_output).resolve()

        return cls(
            base_dir=base,
            dwg=dwg,
            registry=Path(str(payload.get("registry_path") or base / "Master_Registry.xlsx")).resolve(),
            mapping=Path(str(payload.get("mapping_path") or base / "Client_Mapping_Sheet.xlsx")).resolve(),
            output=output_path,
            groups=base / "autocad_groups.csv",
            large_groups=base / "large_groups.csv",
            lisp=Path(str(payload.get("lisp_path") or app_root / "ExportTagData.lsp")).resolve(),
            script=base / "run_script.scr",
            attsync=Path(str(payload.get("attsync_path") or app_root / "attsyn.scr")).resolve(),
        )

    def public(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


def _validate_workflow(workflow: str) -> None:
    if workflow not in WORKFLOW_CONFIG:
        raise ValueError(f"Unknown workflow: {workflow}")


def prepare_workflow_zip(workflow: str, paths: WorkflowPaths, log: Log = print) -> dict[str, object]:
    from annotation import generate_spatial_registry
    from main_translation import generate_spatial_registry_translation

    _validate_workflow(workflow)
    if not paths.dwg.is_file():
        raise FileNotFoundError(f"ZIP package file not found: {paths.dwg}")

    session_id = uuid.uuid4().hex[:8]
    work_dir = paths.base_dir / ".runtime" / "zip_workdir" / session_id
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    extract_dir = work_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    log(f"01  Extracting ZIP package: {paths.dwg.name}")
    with zipfile.ZipFile(paths.dwg, "r") as zf:
        zf.extractall(extract_dir)

    dwg_files = sorted([f for f in extract_dir.rglob("*.dwg") if f.is_file() and not f.name.startswith("._")])
    if not dwg_files:
        raise FileNotFoundError(f"No .DWG files found inside ZIP package: {paths.dwg.name}")

    log(f"Found {len(dwg_files)} DWG drawing(s) inside ZIP archive.")

    unique_tags: dict[str, list[dict[str, object]]] = {}
    dwg_manifest = []

    for idx, dwg_file in enumerate(dwg_files, 1):
        rel_path = dwg_file.relative_to(extract_dir).as_posix()
        dwg_sub_base = work_dir / "workspaces" / f"dwg_{idx}"
        dwg_sub_base.mkdir(parents=True, exist_ok=True)

        dwg_registry = dwg_sub_base / "Master_Registry.xlsx"
        dwg_groups = dwg_sub_base / "autocad_groups.csv"
        dwg_large_groups = dwg_sub_base / "large_groups.csv"

        log(f"[{idx}/{len(dwg_files)}] Extracting & indexing {rel_path}...")
        extract_groups(dwg_file, dwg_sub_base, paths.lisp, paths.script, log)

        if workflow == "client_translation":
            generate_spatial_registry_translation(
                str(dwg_file), str(dwg_registry), str(dwg_groups), str(dwg_large_groups)
            )
        else:
            generate_spatial_registry(str(dwg_file), str(dwg_registry), str(dwg_groups))

        dwg_manifest.append({
            "rel_path": rel_path,
            "dwg_file": str(dwg_file.resolve()),
            "registry": str(dwg_registry.resolve()),
            "sub_base": str(dwg_sub_base.resolve()),
        })

        if dwg_registry.is_file():
            connections = pd.read_excel(dwg_registry, sheet_name="Connected Elements")
            for conn_idx, row in connections.iterrows():
                block = str(row.get("Asset Subtype/Block", ""))
                asset_value = row.get("Asset Content/Value", "")
                placeholder_value = row.get("Placeholder Content", "")
                raw_value = asset_value if workflow == "client_translation" else (
                    asset_value if is_placeholder(placeholder_value) else placeholder_value
                )
                source_tag = unpack_tag(raw_value, block)
                if not source_tag or is_placeholder(source_tag) or is_placeholder(raw_value):
                    continue
                if source_tag not in unique_tags:
                    unique_tags[source_tag] = []
                unique_tags[source_tag].append({
                    "dwg_idx": idx,
                    "rel_path": rel_path,
                    "conn_idx": int(conn_idx),
                    "block": block
                })

    manifest_path = work_dir / "zip_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "session_id": session_id,
            "dwg_files": dwg_manifest,
            "unique_tags": unique_tags,
            "extract_dir": str(extract_dir.resolve())
        }, f, indent=2)

    curr_session_file = paths.base_dir / ".runtime" / "current_zip_session.json"
    curr_session_file.parent.mkdir(parents=True, exist_ok=True)
    with open(curr_session_file, "w", encoding="utf-8") as f:
        json.dump({"session_id": session_id, "manifest_path": str(manifest_path.resolve())}, f, indent=2)

    mapping_rows = []
    for tag in sorted(unique_tags.keys()):
        mapping_rows.append({"Connection Row": 0, "Scovan Tag": tag, "Client Tag Mapping": ""})

    paths.mapping.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(paths.mapping, engine="openpyxl") as writer:
        pd.DataFrame(mapping_rows).to_excel(writer, index=False, sheet_name="Mapping")
        worksheet = writer.sheets["Mapping"]
        worksheet.column_dimensions["A"].width = 16
        worksheet.column_dimensions["B"].width = 35
        worksheet.column_dimensions["C"].width = 35
        worksheet.column_dimensions["A"].hidden = True

    log(f"03  Creating deduplicated mapping sheet with {len(unique_tags)} unique tag(s) across {len(dwg_files)} drawing(s).")
    return {"mapping_rows": len(unique_tags), "phase": "mapping_ready", "paths": paths.public()}


def get_pdf_rel_path(rel_path: str) -> str:
    path_obj = Path(rel_path)
    parts = list(path_obj.parts)
    if not parts:
        return "PDF/" + Path(rel_path).with_suffix(".pdf").name
    if parts[0].upper() == "NATIVE":
        parts[0] = "PDF"
    else:
        parts.insert(0, "PDF")
    pdf_obj = Path(*parts).with_suffix(".pdf")
    return pdf_obj.as_posix()


def finalize_workflow_zip(workflow: str, paths: WorkflowPaths, log: Log = print) -> dict[str, object]:
    from update_connected import update_connected_pids

    _validate_workflow(workflow)
    curr_session_file = paths.base_dir / ".runtime" / "current_zip_session.json"
    if not curr_session_file.is_file():
        raise FileNotFoundError("ZIP session metadata not found. Please re-run Prepare Mapping.")

    with open(curr_session_file, "r", encoding="utf-8") as f:
        sess_info = json.load(f)

    manifest_path = Path(sess_info["manifest_path"])
    if not manifest_path.is_file():
        raise FileNotFoundError("ZIP session manifest not found. Please re-run Prepare Mapping.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    dwg_files = manifest["dwg_files"]
    extract_dir = Path(manifest["extract_dir"])

    mapping_df = pd.read_excel(paths.mapping, sheet_name="Mapping")
    user_mappings: dict[str, str] = {}
    for _, row in mapping_df.iterrows():
        scovan = str(row.get("Scovan Tag", "")).strip()
        client = str(row.get("Client Tag Mapping", "")).strip()
        if scovan and client and not pd.isna(client):
            user_mappings[scovan] = client

    log(f"04  Loaded {len(user_mappings)} active tag mapping(s) from mapping workbook.")

    work_dir = manifest_path.parent
    out_staging = work_dir / "out_staging"
    if out_staging.exists():
        shutil.rmtree(out_staging, ignore_errors=True)

    shutil.copytree(extract_dir, out_staging)

    summary_records = []
    file_records = []

    for idx, dwg_info in enumerate(dwg_files, 1):
        rel_path = dwg_info["rel_path"]
        dwg_file = Path(dwg_info["dwg_file"])
        dwg_registry = Path(dwg_info["registry"])

        out_dwg = out_staging / rel_path
        out_dwg.parent.mkdir(parents=True, exist_ok=True)

        rel_pdf = get_pdf_rel_path(rel_path)
        out_pdf = None
        if rel_pdf:
            out_pdf = out_staging / rel_pdf
            out_pdf.parent.mkdir(parents=True, exist_ok=True)

        log(f"[{idx}/{len(dwg_files)}] Applying tags, regenerating PDF & synchronizing {rel_path}...")

        wf_dwg_registry = dwg_registry.parent / f"Master_Registry_{workflow}.xlsx"
        shutil.copy2(dwg_registry, wf_dwg_registry)

        reg_df = pd.read_excel(wf_dwg_registry, sheet_name="Connected Elements")
        dwg_updates_count = 0

        for conn_idx, row in reg_df.iterrows():
            block = str(row.get("Asset Subtype/Block", ""))
            asset_value = row.get("Asset Content/Value", "")
            placeholder_value = row.get("Placeholder Content", "")
            source_tag = unpack_tag(asset_value, block)
            if source_tag in user_mappings:
                mapped_client_tag = user_mappings[source_tag]
                if workflow == "client_translation":
                    formatted_tag = format_mapping(mapped_client_tag, asset_value, block)
                    reg_df.at[conn_idx, "Mapping Status"] = "VALID_OVERWRITE"
                    reg_df.at[conn_idx, "Placeholder Content"] = formatted_tag
                    reg_df.at[conn_idx, "Asset Content/Value"] = formatted_tag
                else:
                    formatted_tag = format_mapping(mapped_client_tag, placeholder_value, block)
                    reg_df.at[conn_idx, "Mapping Status"] = "VALID_MATCH"
                    reg_df.at[conn_idx, "Placeholder Content"] = formatted_tag

                dwg_updates_count += 1
                summary_records.append({
                    "Relative Path": rel_path,
                    "Drawing Filename": dwg_file.name,
                    "Scovan Tag": source_tag,
                    "Client Tag Mapping": mapped_client_tag,
                    "Block / Entity Type": block,
                    "Status": "Updated & Synced"
                })

        file_records.append({
            "File Category": "NATIVE Drawing (.dwg)",
            "Relative Path": rel_path,
            "Filename": dwg_file.name,
            "Tag Changes Applied": dwg_updates_count,
            "Status": "Updated & Synced",
        })
        if rel_pdf:
            file_records.append({
                "File Category": "PDF Output (.pdf)",
                "Relative Path": rel_pdf,
                "Filename": Path(rel_pdf).name,
                "Tag Changes Applied": dwg_updates_count,
                "Status": "Regenerated & Synced",
            })

        with pd.ExcelWriter(wf_dwg_registry, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
            reg_df.to_excel(writer, index=False, sheet_name="Connected Elements")

        freeze_dual = (workflow == "client_translation")
        update_connected_pids(str(dwg_file), str(wf_dwg_registry), str(out_dwg), freeze_dual=freeze_dual)
        _run_attsync(out_dwg, paths.attsync, log, pdf_path=out_pdf)

    # Check for REPORTS folder in staging directory (case-insensitive)
    reports_dir = None
    for p in out_staging.iterdir():
        if p.is_dir() and p.name.upper() == "REPORTS":
            reports_dir = p
            break

    if reports_dir is None:
        report_path = out_staging / "PadX_Automan_Report.xlsx"
    else:
        report_path = reports_dir / "PadX_Automan_Report.xlsx"

    report_path.parent.mkdir(parents=True, exist_ok=True)

    summary_kpis = [
        {"Batch Metric": "Total DWG Drawings Updated", "Value": len(dwg_files)},
        {"Batch Metric": "Total PDFs Regenerated", "Value": len(dwg_files)},
        {"Batch Metric": "Unique Scovan Tags Mapped", "Value": len(user_mappings)},
        {"Batch Metric": "Total Tag Replacement Instances", "Value": len(summary_records)},
    ]

    with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
        pd.DataFrame(summary_kpis).to_excel(writer, index=False, sheet_name="Overview", startrow=0)
        pd.DataFrame(file_records).to_excel(writer, index=False, sheet_name="Overview", startrow=6)
        pd.DataFrame(summary_records).to_excel(writer, index=False, sheet_name="Detailed Tag Mappings")

        sheet_ov = writer.sheets["Overview"]
        sheet_ov.column_dimensions["A"].width = 32
        sheet_ov.column_dimensions["B"].width = 35
        sheet_ov.column_dimensions["C"].width = 30
        sheet_ov.column_dimensions["D"].width = 24
        sheet_ov.column_dimensions["E"].width = 24

        sheet_det = writer.sheets["Detailed Tag Mappings"]
        sheet_det.column_dimensions["A"].width = 32
        sheet_det.column_dimensions["B"].width = 25
        sheet_det.column_dimensions["C"].width = 30
        sheet_det.column_dimensions["D"].width = 30
        sheet_det.column_dimensions["E"].width = 28
        sheet_det.column_dimensions["F"].width = 20

    log(f"Generated PadX Automan Report: {report_path.relative_to(out_staging).as_posix()}")

    if paths.output.exists():
        paths.output.unlink()
    paths.output.parent.mkdir(parents=True, exist_ok=True)

    log(f"Packaging updated package into output ZIP: {paths.output.name}")
    with zipfile.ZipFile(paths.output, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in out_staging.rglob("*"):
            if fpath.is_file() and not fpath.name.endswith(".bak"):
                arcname = fpath.relative_to(out_staging).as_posix()
                zf.write(fpath, arcname)

    log(f"Complete ZIP package generated: {paths.output}")
    return {"mapped_rows": len(user_mappings), "phase": "complete", "paths": paths.public()}


def parse_workflows(workflow_input: str | list[str] | None) -> list[str]:
    if not workflow_input:
        return ["dual_tagging"]
    if isinstance(workflow_input, list):
        items = workflow_input
    else:
        items = str(workflow_input).split(",")
    parsed = [w.strip() for w in items if w.strip()]
    return parsed if parsed else ["dual_tagging"]


def prepare_workflow(workflow: str | list[str], paths: WorkflowPaths, log: Log = print) -> dict[str, object]:
    workflows = parse_workflows(workflow)
    effective_workflow = "client_translation" if "client_translation" in workflows else workflows[0]

    _validate_workflow(effective_workflow)
    if paths.dwg.suffix.lower() == ".zip":
        return prepare_workflow_zip(effective_workflow, paths, log)

    from annotation import generate_spatial_registry
    from main_translation import generate_spatial_registry_translation

    if not paths.dwg.is_file():
        raise FileNotFoundError(f"Drawing not found: {paths.dwg}")
    log("00  Cleaning workspace artifacts to prevent cross-contamination")
    clean_workspace_artifacts(paths.base_dir, preserve_mapping=False)
    log("01  Extracting tagged groups from the drawing")
    extract_groups(paths.dwg, paths.base_dir, paths.lisp, paths.script, log)
    log("02  Building the shared spatial registry")
    if effective_workflow == "client_translation":
        generate_spatial_registry_translation(
            str(paths.dwg), str(paths.registry), str(paths.groups), str(paths.large_groups)
        )
    else:
        generate_spatial_registry(str(paths.dwg), str(paths.registry), str(paths.groups))
    log("03  Creating the client mapping workbook")
    rows = write_mapping_sheet(paths.registry, paths.mapping, effective_workflow)
    log(f"Mapping workbook ready with {rows} tag(s): {paths.mapping}")
    return {"mapping_rows": rows, "phase": "mapping_ready", "paths": paths.public()}


def _finalize_workflow_single(workflow: str, paths: WorkflowPaths, log: Log = print) -> dict[str, object]:
    _validate_workflow(workflow)
    from update_connected import update_connected_pids

    if not paths.mapping.is_file():
        raise FileNotFoundError(f"Mapping workbook not found: {paths.mapping}")
    if not paths.registry.is_file():
        raise FileNotFoundError(f"Registry workbook not found: {paths.registry}")

    log("04  Validating and applying client mappings")
    mapped = apply_mapping_sheet(paths.registry, paths.mapping, workflow)
    if paths.output.exists():
        paths.output.unlink()
    log("05  Writing mapped tags into the updated drawing")
    freeze_dual = (workflow == "client_translation")
    update_connected_pids(str(paths.dwg), str(paths.registry), str(paths.output), freeze_dual=freeze_dual)

    pdf_output = paths.output.with_suffix(".pdf")
    log("06  Synchronizing AutoCAD block attributes & plotting vector PDF")
    _run_attsync(paths.output, paths.attsync, log, pdf_path=pdf_output)

    # Clean up any AutoCAD .bak backup files created during export/save
    bak_patterns = [
        paths.output.with_suffix(".bak"),
        paths.output.parent / f"{paths.output.name}.bak",
        paths.dwg.with_suffix(".bak"),
        paths.dwg.parent / f"{paths.dwg.name}.bak",
        paths.base_dir / f"{paths.output.stem}.bak",
    ]
    for bak_path in bak_patterns:
        try:
            if bak_path.is_file():
                bak_path.unlink()
        except Exception:
            pass

    pub_paths = paths.public()
    pdf_str = str(pdf_output.resolve()) if pdf_output.is_file() else None
    if pdf_str:
        pub_paths["pdf"] = pdf_str

    clean_workspace_artifacts(paths.base_dir, preserve_mapping=True, preserve_registry=True)
    log(f"Complete: DWG -> {paths.output}, PDF -> {pdf_output}")
    return {"mapped_rows": mapped, "phase": "complete", "paths": pub_paths, "pdf": pdf_str}


def finalize_workflow(workflow: str | list[str], paths: WorkflowPaths, log: Log = print) -> dict[str, object]:
    workflows = parse_workflows(workflow)
    for wf in workflows:
        _validate_workflow(wf)

    is_zip = paths.dwg.suffix.lower() == ".zip"
    ext = ".zip" if is_zip else ".dwg"

    if len(workflows) > 1:
        log(f"Running multi-workflow batch for: {', '.join(workflows)}")
        outputs = {}
        mapped_rows = 0

        raw_out = paths.output
        raw_stem = re.sub(r"_Updated$", "", raw_out.stem, flags=re.IGNORECASE)
        raw_stem = re.sub(r"_(DualTagged|ClientTranslated|dualtagged|translated)$", "", raw_stem, flags=re.IGNORECASE)

        for wf in workflows:
            label = "dualtagged" if wf == "dual_tagging" else "translated"
            out_file = raw_out.parent / f"{raw_stem}_{label}{ext}"

            wf_registry = paths.registry
            if not is_zip and paths.registry.is_file():
                wf_registry = paths.registry.parent / f"Master_Registry_{wf}.xlsx"
                shutil.copy2(paths.registry, wf_registry)

            wf_paths = WorkflowPaths(
                base_dir=paths.base_dir,
                dwg=paths.dwg,
                registry=wf_registry,
                mapping=paths.mapping,
                output=out_file,
                groups=paths.groups,
                large_groups=paths.large_groups,
                lisp=paths.lisp,
                script=paths.script,
                attsync=paths.attsync,
            )
            log(f"\n=========================================")
            log(f"Processing Workflow: {wf.upper()} -> {out_file.name}")
            log(f"=========================================")
            res = (finalize_workflow_zip if is_zip else _finalize_workflow_single)(wf, wf_paths, log)
            outputs[wf] = str(out_file.resolve())
            if not is_zip and res.get("pdf"):
                outputs[f"{wf}_pdf"] = str(res["pdf"])
            mapped_rows = max(mapped_rows, int(res.get("mapped_rows", res.get("mapping_rows", 0))))

        pub_paths = paths.public()
        pub_paths["outputs"] = outputs
        clean_workspace_artifacts(paths.base_dir, preserve_mapping=True, preserve_registry=False)
        return {"mapped_rows": mapped_rows, "phase": "complete", "paths": pub_paths, "outputs": outputs}
    else:
        wf = workflows[0]
        res = (finalize_workflow_zip if is_zip else _finalize_workflow_single)(wf, paths, log)
        pub_paths = paths.public()
        outs = {wf: str(paths.output.resolve())}
        if not is_zip and res.get("pdf"):
            outs[f"{wf}_pdf"] = str(res["pdf"])
            pub_paths["pdf"] = str(res["pdf"])
        pub_paths["outputs"] = outs
        res["outputs"] = outs
        res["paths"] = pub_paths
        clean_workspace_artifacts(paths.base_dir, preserve_mapping=True, preserve_registry=False)
        return res


def _run_attsync(drawing: Path, script: Path, log: Log, pdf_path: Path | None = None) -> None:
    """Run COM automation out-of-process so a blocked COM call cannot hang the API."""
    if not drawing.is_file():
        raise FileNotFoundError(f"Updated drawing not found: {drawing}")
    if not script.is_file():
        raise FileNotFoundError(f"ATTSYNC script not found: {script}")

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--attsync-worker",
        str(drawing.resolve()),
        str(script.resolve()),
    ]
    if pdf_path is not None:
        command.append(str(pdf_path.resolve()))

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=210)
    except subprocess.TimeoutExpired as exc:
        partial_output = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        created_match = re.search(r"TAGOPS_CREATED_AUTOCAD_PID=(\d+)", partial_output)
        if created_match:
            subprocess.run(
                ["taskkill", "/PID", created_match.group(1), "/T", "/F"],
                capture_output=True,
                timeout=15,
            )
        raise RuntimeError("AutoCAD ATTSYNC exceeded the 210-second safety timeout.") from exc

    messages = [
        line for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("TAGOPS_CREATED_AUTOCAD_PID=")
    ]
    for message in messages:
        log(message)
    if result.returncode:
        log(f"AutoCAD COM ATTSYNC warning: {result.stderr.strip()}. Falling back to AutoCAD Core Console.")
        executable = find_accoreconsole()
        if executable:
            attsync_scr = drawing.parent / f"attsync_{uuid.uuid4().hex[:8]}.scr"
            attsync_scr.write_text(f'(setvar "SECURELOAD" 0)\n(command "ATTSYNC" "N" "*")\n(command "QSAVE")\nQUIT\n', encoding="utf-8")
            res_ac = subprocess.run([executable, "/i", str(drawing), "/s", str(attsync_scr)], cwd=drawing.parent, capture_output=True)
            try:
                attsync_scr.unlink(missing_ok=True)
            except Exception:
                pass
            if res_ac.returncode == 0:
                log("AutoCAD Core Console ATTSYNC completed successfully.")
                return
        detail = result.stderr.strip() or "The AutoCAD COM worker exited without details."
        raise RuntimeError(f"AutoCAD ATTSYNC failed: {detail}")


def _run_attsync_com(drawing: Path, script: Path, log: Log, pdf_path: Path | None = None) -> None:
    """Execute ATTSYNC inside the supervised worker process."""
    if not drawing.is_file():
        raise FileNotFoundError(f"Updated drawing not found: {drawing}")
    if not script.is_file():
        raise FileNotFoundError(f"ATTSYNC script not found: {script}")
    import comtypes
    import comtypes.client

    retryable = {
        -2147418111, 2147549185,  # RPC_E_CALL_REJECTED
        -2147417846, 2147551450,  # RPC_E_SERVERCALL_RETRYLATER
        -2147023170, 2147944126,  # RPC_S_SERVER_UNAVAILABLE
        -2147418105, 2147549191,  # RPC_E_SERVERFAULT
    }

    def retry_com(action, timeout: float = 60.0):
        deadline = time.monotonic() + timeout
        while True:
            try:
                return action()
            except Exception as exc:
                err_str = str(exc).lower()
                code = getattr(exc, "hresult", exc.args[0] if exc.args else None)
                if isinstance(code, int) and code > 0x7FFFFFFF:
                    code -= 0x100000000
                is_retryable = (code in retryable) or ("rejected by callee" in err_str) or ("retrylater" in err_str) or ("busy" in err_str)
                if not is_retryable or time.monotonic() >= deadline:
                    raise
                time.sleep(1.0)

    created_application = False
    document = None
    acad = None
    acad_hwnd = 0
    marker = drawing.parent / f".{drawing.stem}.{uuid.uuid4().hex}.attsync.done"
    primary_error: Exception | None = None
    cleanup_errors: list[str] = []
    comtypes.CoInitialize()
    try:
        try:
            acad = retry_com(lambda: comtypes.client.GetActiveObject("AutoCAD.Application"), timeout=5.0)
            log("Connected to active AutoCAD session.")
            idle_deadline = time.monotonic() + 15
            while time.monotonic() < idle_deadline:
                try:
                    st = acad.GetAcadState()
                    if bool(st.IsQuiescent):
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            document = retry_com(lambda: acad.Documents.Open(os.path.abspath(drawing)), timeout=60.0)
        except Exception:
            acad = comtypes.client.CreateObject("AutoCAD.Application")
            retry_com(lambda: setattr(acad, "Visible", False))
            created_application = True
            log("Started dedicated AutoCAD session for ATTSYNC.")
            try:
                import ctypes

                hwnd = retry_com(lambda: int(acad.HWND))
                process_id = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
                if process_id.value:
                    print(f"TAGOPS_CREATED_AUTOCAD_PID={process_id.value}", flush=True)
            except Exception:
                pass

            idle_deadline = time.monotonic() + 30
            while time.monotonic() < idle_deadline:
                try:
                    st = retry_com(lambda: acad.GetAcadState(), timeout=5.0)
                    if bool(retry_com(lambda: st.IsQuiescent, timeout=5.0)):
                        break
                except Exception:
                    pass
                time.sleep(0.5)

            document = retry_com(lambda: acad.Documents.Open(os.path.abspath(drawing)), timeout=60.0)

        log("AutoCAD is idle; submitting ATTSYNC commands.")
        marker_lisp = marker.as_posix().replace('"', '\\"')

        pdf_command = ""
        if pdf_path is not None:
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_lisp = pdf_path.as_posix().replace('"', '\\"')
            pdf_command = f'(command "._-PLOT" "Y" "" "AutoCAD PDF (General Documentation).pc3" "ANSI A (8.50 x 11.00 Inches)" "I" "L" "N" "E" "F" "C" "Y" "." "Y" "N" "N" "N" "{pdf_lisp}" "N" "Y") '

        command = (
            f'(progn '
            f'(setvar "SECURELOAD" 0) '
            f'(command "_.attsync" "_Name" "dyn_instr shared disp") '
            f'(command "_.attsync" "_Name" "Dyn_Discrete Instr") '
            f'(command "_.attsync" "_Name" "dyn_instr plc") '
            f'(command "_.attsync" "_Name" "dyn_meter") '
            f'(command "_.regenall") '
            f'{pdf_command}'
            f'(setq tagops-marker (open "{marker_lisp}" "w")) '
            f'(write-line "complete" tagops-marker) '
            f'(close tagops-marker) '
            f'(princ))\n'
        )
        retry_com(lambda: document.SendCommand(command), timeout=60)

        deadline = time.monotonic() + 90
        while not marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.25)
        if not marker.is_file():
            raise TimeoutError("AutoCAD did not finish ATTSYNC within 90 seconds.")

        log("ATTSYNC commands finished; saving the drawing.")
        retry_com(lambda: document.Save(), timeout=30)
    except Exception as exc:
        primary_error = exc
    finally:
        if document is not None:
            try:
                retry_com(lambda: document.Close(False), timeout=30)
            except Exception as first_close_error:
                # A timed-out command can keep the document modal. Cancel only
                # in the AutoCAD window used by this worker, then retry cleanup.
                if acad_hwnd:
                    try:
                        import ctypes

                        for _ in range(2):
                            ctypes.windll.user32.PostMessageW(acad_hwnd, 0x0100, 0x1B, 0)
                            ctypes.windll.user32.PostMessageW(acad_hwnd, 0x0101, 0x1B, 0)
                            time.sleep(0.35)
                    except Exception:
                        pass
                try:
                    retry_com(lambda: document.Close(False), timeout=15)
                except Exception as second_close_error:
                    cleanup_errors.append(
                        f"could not close the drawing: {second_close_error} (initially {first_close_error})"
                    )
        if created_application and acad is not None:
            try:
                retry_com(lambda: acad.Quit(), timeout=30)
            except Exception as exc:
                cleanup_errors.append(f"could not close AutoCAD: {exc}")
        try:
            marker.unlink(missing_ok=True)
        except Exception as exc:
            cleanup_errors.append(f"could not remove the ATTSYNC marker: {exc}")
        comtypes.CoUninitialize()

    if primary_error is not None:
        suffix = f"; cleanup: {'; '.join(cleanup_errors)}" if cleanup_errors else ""
        raise RuntimeError(f"AutoCAD ATTSYNC failed: {primary_error}{suffix}") from primary_error
    if cleanup_errors:
        log(f"AutoCAD ATTSYNC completed with cleanup warning: {'; '.join(cleanup_errors)}")
    else:
        log("AutoCAD ATTSYNC completed successfully.")


def _run_worker_cli() -> int:
    if len(sys.argv) < 4 or sys.argv[1] != "--attsync-worker":
        return -1
    dwg = Path(sys.argv[2])
    script = Path(sys.argv[3])
    pdf = Path(sys.argv[4]) if len(sys.argv) >= 5 else None
    try:
        _run_attsync_com(dwg, script, lambda message: print(message, flush=True), pdf_path=pdf)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    worker_status = _run_worker_cli()
    if worker_status < 0:
        raise SystemExit("workflow_engine.py is an internal module")
    raise SystemExit(worker_status)
