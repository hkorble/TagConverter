from __future__ import annotations

import ast
import csv
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from config import AUTOCAD_CORE_PATHS, BLOCK_RULES_LEGEND, ODA_EXEC_PATH, PLACEHOLDER_RULES

Log = Callable[[str], None]


def clean_text(raw_text: object) -> str:
    text = str(raw_text or "")
    return re.sub(r"\\[A-Za-z][^;]*;|[{}]", "", text).strip() if text else ""


def is_placeholder(value: object) -> bool:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return bool(PLACEHOLDER_RULES.get("empty_is_placeholder", True))
    text = str(value)
    flags = 0 if PLACEHOLDER_RULES.get("case_sensitive") else re.IGNORECASE
    for token in PLACEHOLDER_RULES.get("contains", []):
        if (token in text) if flags == 0 else (token.upper() in text.upper()):
            return True
    return any(re.search(pattern, text, flags) for pattern in PLACEHOLDER_RULES.get("regex", []))


def target_attributes(block_name: str) -> list[str]:
    rule = BLOCK_RULES_LEGEND.get(block_name, {})
    tags = rule.get("target_attributes", [rule.get("target_attribute", "VLV_TAG")])
    return [tags] if isinstance(tags, str) else [str(tag) for tag in tags if tag]


def unpack_tag(raw_value: object, block_name: str) -> str:
    text = str(raw_value or "")
    if text.startswith("{") and text.endswith("}"):
        try:
            values = ast.literal_eval(text)
            if isinstance(values, dict):
                selected = [str(values[tag]) for tag in target_attributes(block_name) if values.get(tag) not in (None, "")]
                if selected:
                    return "-".join(selected)
        except (SyntaxError, ValueError):
            pass
    return text


def format_mapping(mapping: object, original: object, block_name: str) -> str:
    text = str(mapping).strip()
    tags = target_attributes(block_name)
    if len(tags) == 1:
        return text
    values: dict[str, object] = {}
    original_text = str(original or "")
    if original_text.startswith("{") and original_text.endswith("}"):
        try:
            parsed = ast.literal_eval(original_text)
            if isinstance(parsed, dict):
                values = parsed
        except (SyntaxError, ValueError):
            pass
    parts = [part.strip() for part in text.split("-")]
    for index, tag in enumerate(tags):
        values[tag] = parts[index] if index < len(parts) else values.get(tag, "")
    return str(values)


def write_mapping_sheet(connections_path: Path, mapping_path: Path, workflow: str) -> int:
    connections = pd.read_excel(connections_path, sheet_name="Connected Elements")
    rows: list[dict[str, object]] = []
    for index, row in connections.iterrows():
        block = str(row.get("Asset Subtype/Block", ""))
        asset_value = row.get("Asset Content/Value", "")
        placeholder_value = row.get("Placeholder Content", "")
        raw_value = asset_value if workflow == "client_translation" else (
            asset_value if is_placeholder(placeholder_value) else placeholder_value
        )
        source_tag = unpack_tag(raw_value, block)
        if not source_tag or is_placeholder(source_tag) or is_placeholder(raw_value):
            continue
        rows.append({"Connection Row": int(index), "Scovan Tag": source_tag, "Client Tag Mapping": ""})

    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(mapping_path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="Mapping")
        worksheet = writer.sheets["Mapping"]
        worksheet.column_dimensions["A"].width = 16
        worksheet.column_dimensions["B"].width = 35
        worksheet.column_dimensions["C"].width = 35
        worksheet.column_dimensions["A"].hidden = True
    return len(rows)


def apply_mapping_sheet(registry_path: Path, mapping_path: Path, workflow: str) -> int:
    mappings = pd.read_excel(mapping_path, sheet_name="Mapping")
    required = {"Connection Row", "Client Tag Mapping"}
    if missing := required.difference(mappings.columns):
        raise ValueError(f"Mapping sheet is missing column(s): {', '.join(sorted(missing))}")
    blank = mappings["Client Tag Mapping"].isna() | (mappings["Client Tag Mapping"].astype(str).str.strip() == "")
    if blank.any():
        raise ValueError(f"Fill in all client mappings first ({int(blank.sum())} blank row(s)).")

    connections = pd.read_excel(registry_path, sheet_name="Connected Elements")
    master = pd.read_excel(registry_path, sheet_name="Master Registry")
    for _, mapping_row in mappings.iterrows():
        index = int(mapping_row["Connection Row"])
        if index not in connections.index:
            continue
        row = connections.loc[index]
        block = str(row.get("Asset Subtype/Block", ""))
        value = str(mapping_row["Client Tag Mapping"]).strip()
        if workflow == "client_translation":
            formatted = format_mapping(value, row.get("Asset Content/Value", ""), block)
            connections.at[index, "Placeholder Content"] = formatted
            connections.at[index, "Asset Content/Value"] = formatted
        else:
            formatted = format_mapping(value, row.get("Placeholder Content", ""), block)
            connections.at[index, "Placeholder Content"] = formatted

    with pd.ExcelWriter(registry_path, engine="openpyxl") as writer:
        master.to_excel(writer, sheet_name="Master Registry", index=False)
        connections.to_excel(writer, sheet_name="Connected Elements", index=False)
    return len(mappings)


def find_accoreconsole(paths: Iterable[str] = AUTOCAD_CORE_PATHS) -> str | None:
    configured = next((path for path in paths if os.path.exists(path)), None)
    if configured:
        return configured
    discovered = sorted(
        Path(r"C:\Program Files\Autodesk").glob("AutoCAD */accoreconsole.exe"),
        reverse=True,
    )
    return str(discovered[0]) if discovered else None


def extract_groups(dwg_path: Path, base_dir: Path, lsp_path: Path, script_path: Path, log: Log = print) -> None:
    header = ["GroupName", "Handle", "Layer", "TextContent", "X", "Y"]
    for filename in ("autocad_groups.csv", "large_groups.csv"):
        csv_file = base_dir / filename
        csv_file.parent.mkdir(parents=True, exist_ok=True)
        with csv_file.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)

    executable = find_accoreconsole()
    if executable:
        log(f"AutoCAD Core Console: {executable}")
        script = f'(setvar "SECURELOAD" 0)\n(load "{lsp_path.as_posix()}")\nExportTagData \nQUIT\n'
        script_path.write_text(script, encoding="utf-8")
        environment = os.environ.copy()
        environment["TAGOPS_WORKSPACE"] = str(base_dir)
        result = subprocess.run(
            [executable, "/i", str(dwg_path), "/tr", str(base_dir), "/s", str(script_path)],
            cwd=base_dir,
            capture_output=True,
            env=environment,
        )
        output = result.stdout.decode("utf-16", errors="replace") if b"\x00" in result.stdout else result.stdout.decode(errors="replace")
        error = result.stderr.decode("utf-16", errors="replace") if b"\x00" in result.stderr else result.stderr.decode(errors="replace")
        if output.strip():
            log(output.strip())
        if result.returncode:
            raise RuntimeError(error.strip() or "AutoCAD group extraction failed.")
        return
    if Path(ODA_EXEC_PATH).is_file():
        log("AutoCAD Core Console is unavailable; using the ODA extraction fallback.")
        _extract_groups_native(dwg_path, base_dir, log)
        return
    raise FileNotFoundError("Neither AutoCAD Core Console nor ODA File Converter was found.")


def _extract_groups_native(dwg_path: Path, base_dir: Path, log: Log = print) -> None:
    """Export AutoCAD group members through ODA, without requiring AutoCAD."""
    import ezdxf
    from ezdxf.addons import odafc

    ezdxf.options.set("odafc-addon", "win_exec_path", ODA_EXEC_PATH)
    document = odafc.readfile(dwg_path)
    all_rows: list[list[object]] = []
    large_rows: list[list[object]] = []

    for group_name, group in document.groups:
        members = list(group)
        rows: list[list[object]] = []
        for entity in members:
            point = None
            if entity.dxf.hasattr("insert"):
                point = entity.dxf.get("insert")
            elif entity.dxf.hasattr("start"):
                point = entity.dxf.get("start")
            x = round(float(point[0]), 3) if point is not None else 0.0
            y = round(float(point[1]), 3) if point is not None else 0.0
            if entity.dxf.hasattr("text"):
                content = entity.dxf.get("text")
            else:
                content = getattr(entity, "text", "")
            rows.append([
                group_name,
                entity.dxf.get("handle", ""),
                entity.dxf.get("layer", ""),
                str(content or ""),
                x,
                y,
            ])
        all_rows.extend(rows)
        if len(members) > 2:
            large_rows.extend(rows)

    header = ["GroupName", "Handle", "Layer", "TextContent", "X", "Y"]
    for filename, rows in (("autocad_groups.csv", all_rows), ("large_groups.csv", large_rows)):
        with (base_dir / filename).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
    log(f"ODA extracted {len(all_rows)} member(s) from {len(document.groups)} AutoCAD group(s).")


def clean_workspace_artifacts(base_dir: Path, preserve_mapping: bool = False, preserve_registry: bool = False) -> None:
    """Purge temporary extraction, script, backup, and registry files to prevent cross-contamination."""
    if not base_dir.is_dir():
        return

    files_to_remove = [
        base_dir / "autocad_groups.csv",
        base_dir / "large_groups.csv",
        base_dir / "run_script.scr",
        base_dir / "align_blocks.scr",
        base_dir / "align_blocks1.scr",
    ]
    if not preserve_registry:
        files_to_remove.append(base_dir / "Master_Registry.xlsx")
    if not preserve_mapping:
        files_to_remove.append(base_dir / "Client_Mapping_Sheet.xlsx")

    for file_path in files_to_remove:
        try:
            if file_path.is_file():
                file_path.unlink()
        except Exception:
            pass

    for pattern in ("*.bak", "*.attsync.done"):
        for p in base_dir.glob(pattern):
            try:
                if p.is_file():
                    p.unlink()
            except Exception:
                pass
