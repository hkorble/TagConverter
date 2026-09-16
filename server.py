from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import threading
import traceback
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import PLACEHOLDER_RULES, WORKFLOW_CONFIG
from workflow_common import clean_workspace_artifacts
from workflow_engine import WorkflowPaths, finalize_workflow, prepare_workflow

ROOT = Path(__file__).resolve().parent
UI_DIST = ROOT / "tag-operations-ui" / "dist"
RUNS: dict[str, dict[str, object]] = {}
RUNS_LOCK = threading.Lock()


def wipe_transient_files() -> None:
    """Wipe transient mapping sheets, old session files, and temp artifacts to prevent stale tags from persisting."""
    clean_workspace_artifacts(ROOT, preserve_mapping=False, preserve_registry=False)
    transient_files = [
        ROOT / "Client_Mapping_Sheet.xlsx",
        ROOT / ".runtime" / "current_zip_session.json",
        ROOT / "autocad_groups.csv",
        ROOT / "large_groups.csv",
        ROOT / "Master_Registry.xlsx",
        ROOT / "Testing Drawings" / "Client_Mapping_Sheet.xlsx",
    ]
    for f in transient_files:
        try:
            if f.is_file():
                f.unlink()
        except Exception:
            pass

    # Clean any session mappings and staging directories in .runtime
    for sub in ("session_mappings", "wrapped_zips", "zip_workdir", "sessions"):
        sdir = ROOT / ".runtime" / sub
        if sdir.is_dir():
            shutil.rmtree(sdir, ignore_errors=True)

    # Clean old mapping sheets in Downloads folder that could be accidentally picked up
    downloads_dir = Path.home() / "Downloads"
    if downloads_dir.is_dir():
        for dl_file in downloads_dir.glob("Scovan_Client_Mapping_Sheet*.*"):
            try:
                if dl_file.is_file():
                    dl_file.unlink()
            except Exception:
                pass


import ctypes
from ctypes import wintypes


class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", wintypes.LPVOID),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", wintypes.LPVOID),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


class BROWSEINFOW(ctypes.Structure):
    _fields_ = [
        ("hwndOwner", wintypes.HWND),
        ("pidlRoot", wintypes.LPVOID),
        ("pszDisplayName", wintypes.LPWSTR),
        ("lpszTitle", wintypes.LPCWSTR),
        ("ulFlags", wintypes.UINT),
        ("lpfn", wintypes.LPVOID),
        ("lParam", wintypes.LPARAM),
        ("iImage", ctypes.c_int),
    ]


def _browse_path(mode: str) -> str | None:
    """Open an instant native Windows file/folder dialog via Win32 C API."""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if mode in ("file", "output"):
            buffer = ctypes.create_unicode_buffer(512)
            ofn = OPENFILENAMEW()
            ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
            ofn.hwndOwner = hwnd
            ofn.lpstrFilter = "AutoCAD Drawings & ZIP (*.dwg;*.zip)\0*.dwg;*.zip\0All Files (*.*)\0*.*\0\0"
            ofn.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
            ofn.nMaxFile = 512
            ofn.lpstrTitle = "Select Source Drawing or ZIP Package" if mode == "file" else "Select Output Drawing Location"
            ofn.Flags = 0x00000800 | 0x00000008 | (0x00001000 if mode == "file" else 0)  # OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR
            ofn.lpstrDefExt = "dwg"

            func = ctypes.windll.comdlg32.GetOpenFileNameW if mode == "file" else ctypes.windll.comdlg32.GetSaveFileNameW
            if func(ctypes.byref(ofn)):
                return buffer.value
            return None

        elif mode == "folder":
            display_name = ctypes.create_unicode_buffer(512)
            bi = BROWSEINFOW()
            bi.hwndOwner = hwnd
            bi.pszDisplayName = ctypes.cast(display_name, wintypes.LPWSTR)
            bi.lpszTitle = "Select Workspace Directory"
            bi.ulFlags = 0x0001 | 0x0040  # BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE

            pidl = ctypes.windll.shell32.SHBrowseForFolderW(ctypes.byref(bi))
            if pidl:
                path_buf = ctypes.create_unicode_buffer(512)
                if ctypes.windll.shell32.SHGetPathFromIDListW(pidl, path_buf):
                    ctypes.windll.ole32.CoTaskMemFree(pidl)
                    return path_buf.value
                ctypes.windll.ole32.CoTaskMemFree(pidl)
            return None
    except Exception:
        pass

    # Fallback to PowerShell if ctypes call fails
    try:
        if mode == "file":
            ps_code = 'Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.OpenFileDialog; $f.Filter = "AutoCAD Drawings & ZIP (*.dwg;*.zip)|*.dwg;*.zip|All Files (*.*)|*.*"; $f.Title = "Select Source Drawing or ZIP Package"; $top = New-Object System.Windows.Forms.Form; $top.TopMost = $true; if ($f.ShowDialog($top) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.FileName }'
        elif mode == "folder":
            ps_code = 'Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.FolderBrowserDialog; $f.Description = "Select Workspace Directory"; $top = New-Object System.Windows.Forms.Form; $top.TopMost = $true; if ($f.ShowDialog($top) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }'
        elif mode == "output":
            ps_code = 'Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.SaveFileDialog; $f.Filter = "AutoCAD Drawing (*.dwg)|*.dwg|All Files (*.*)|*.*"; $f.Title = "Select Output Drawing Location"; $top = New-Object System.Windows.Forms.Form; $top.TopMost = $true; if ($f.ShowDialog($top) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.FileName }'
        else:
            return None

        res = subprocess.run(
            ["powershell", "-Sta", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=60,
        )
        selected = res.stdout.strip()
        return selected if selected else None
    except Exception:
        return None


def _run_job(run_id: str, action: str, payload: dict[str, object]) -> None:
    def log(message: str) -> None:
        with RUNS_LOCK:
            RUNS[run_id]["logs"].append(str(message))

    try:
        workflow = str(payload.get("workflow", "dual_tagging"))
        payload["action"] = action
        if action == "prepare":
            wipe_transient_files()
        paths = WorkflowPaths.from_payload(payload)
        result = (prepare_workflow if action == "prepare" else finalize_workflow)(workflow, paths, log)
        if action == "finalize":
            wipe_transient_files()
        with RUNS_LOCK:
            RUNS[run_id].update({"status": "complete", "result": result})
    except Exception as exc:
        with RUNS_LOCK:
            RUNS[run_id].update({
                "status": "error",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            })


class Handler(BaseHTTPRequestHandler):
    server_version = "TagOperations/1.0"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/tag-translator", "/translator"):
            translator_html = ROOT / "web_static" / "index.html"
            if translator_html.is_file():
                body = translator_html.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

        if path == "/api/config":
            self._json({
                "workflows": WORKFLOW_CONFIG,
                "placeholder_rules": PLACEHOLDER_RULES,
                "downloads_dir": str(Path.home() / "Downloads"),
            })
            return
        if path == "/api/download":
            query = parse_qs(urlparse(self.path).query)
            target_str = query.get("path", [""])[0]
            target_path = Path(target_str).resolve() if target_str else None
            if not target_path or not target_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, f"File not found: {target_str}")
                return
            body = target_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(target_path.name)[0] or "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{target_path.name}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/browse":
            query = parse_qs(urlparse(self.path).query)
            mode = query.get("mode", ["file"])[0]
            selected = _browse_path(mode)
            self._json({"path": selected})
            return
        if path == "/api/mapping":
            query = parse_qs(urlparse(self.path).query)
            target_str = query.get("path", [""])[0]
            target_path = Path(target_str).resolve() if target_str else None
            if not target_path or not target_path.is_file():
                project_file = (ROOT / target_str).resolve()
                if project_file.is_file():
                    target_path = project_file
            if not target_path or not target_path.is_file():
                self._json({"error": f"Mapping file not found: {target_str}"}, HTTPStatus.NOT_FOUND)
                return
            try:
                import pandas as pd
                df = pd.read_excel(target_path, sheet_name="Mapping")
                df = df.fillna("")
                records = df.to_dict(orient="records")
                self._json({"path": str(target_path), "rows": records})
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/export-two-column-mapping":
            query = parse_qs(urlparse(self.path).query)
            target_str = query.get("path", [""])[0]
            target_path = Path(target_str).resolve() if target_str else None
            if not target_path or not target_path.is_file():
                project_file = (ROOT / target_str).resolve()
                if project_file.is_file():
                    target_path = project_file
            if not target_path or not target_path.is_file():
                self._json({"error": f"Mapping file not found: {target_str}"}, HTTPStatus.NOT_FOUND)
                return
            try:
                import io
                import pandas as pd
                df_raw = pd.read_excel(target_path, sheet_name="Mapping")
                export_data = []
                for _, r in df_raw.iterrows():
                    export_data.append({
                        "Scovan Tag": str(r.get("Scovan Tag") or "").strip(),
                        "Client Tag Mapping": str(r.get("Client Tag Mapping") or "").strip() if not pd.isna(r.get("Client Tag Mapping")) else ""
                    })
                df = pd.DataFrame(export_data) if export_data else pd.DataFrame(columns=["Scovan Tag", "Client Tag Mapping"])
                bio = io.BytesIO()
                with pd.ExcelWriter(bio, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False, sheet_name="Mapping")
                    ws = writer.sheets["Mapping"]
                    ws.column_dimensions["A"].width = 35
                    ws.column_dimensions["B"].width = 35
                body = bio.getvalue()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", 'attachment; filename="Scovan_Client_Mapping_Sheet.xlsx"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path.startswith("/api/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            with RUNS_LOCK:
                run = RUNS.get(run_id)
                payload = dict(run) if run else None
            self._json(payload or {"error": "Run not found"}, HTTPStatus.OK if payload else HTTPStatus.NOT_FOUND)
            return
        self._serve_ui(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/export-two-column-mapping":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                raw_rows = payload.get("rows", [])
                filename = str(payload.get("filename", "Scovan_Client_Mapping_Sheet.xlsx"))
                if not filename.lower().endswith(".xlsx"):
                    filename += ".xlsx"
                import io
                import pandas as pd
                export_data = []
                for r in raw_rows:
                    if isinstance(r, dict):
                        export_data.append({
                            "Scovan Tag": str(r.get("Scovan Tag") or "").strip(),
                            "Client Tag Mapping": str(r.get("Client Tag Mapping") or "").strip()
                        })
                df = pd.DataFrame(export_data) if export_data else pd.DataFrame(columns=["Scovan Tag", "Client Tag Mapping"])
                bio = io.BytesIO()
                with pd.ExcelWriter(bio, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False, sheet_name="Mapping")
                    ws = writer.sheets["Mapping"]
                    ws.column_dimensions["A"].width = 35
                    ws.column_dimensions["B"].width = 35
                body = bio.getvalue()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/mapping":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                target_str = str(payload.get("path", ""))
                target_path = Path(target_str).resolve()
                rows = payload.get("rows", [])
                if not isinstance(rows, list):
                    self._json({"error": "Invalid rows list"}, HTTPStatus.BAD_REQUEST)
                    return
                import pandas as pd
                df = pd.DataFrame(rows)
                with pd.ExcelWriter(target_path, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False, sheet_name="Mapping")
                    worksheet = writer.sheets["Mapping"]
                    worksheet.column_dimensions["A"].width = 16
                    worksheet.column_dimensions["B"].width = 35
                    worksheet.column_dimensions["C"].width = 35
                    worksheet.column_dimensions["A"].hidden = True
                self._json({"status": "saved", "rows": len(rows), "path": str(target_path)})
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/open-file":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                target_str = str(payload.get("path", ""))
                target_path = Path(target_str).resolve()
                if not target_path.is_file():
                    project_file = (ROOT / target_str).resolve()
                    if project_file.is_file():
                        target_path = project_file
                    else:
                        self._json({"error": f"Workbook file not found: {target_str}"}, HTTPStatus.NOT_FOUND)
                        return
                os.startfile(target_path)
                self._json({"status": "opened", "path": str(target_path)})
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path in ("/api/parse-dump", "/api/parse-upload", "/api/parse-path", "/api/export-breakout", "/api/export-final", "/api/open-in-excel"):
            try:
                import base64
                import tag_translation_engine as tte
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw_body or b"{}")

                if path == "/api/parse-dump":
                    text = str(payload.get("text", ""))
                    tags = tte.parse_raw_tag_text(text)
                    if not tags:
                        self._json({"error": "No valid tags could be parsed."}, HTTPStatus.BAD_REQUEST)
                        return
                    processed = tte.process_tags(tags)
                    self._json({"source": "dump", "tags_count": len(tags), "data": processed})
                    return

                if path == "/api/parse-upload":
                    filename = str(payload.get("filename", "upload.xlsx"))
                    b64_content = str(payload.get("content", ""))
                    file_bytes = base64.b64decode(b64_content)
                    tags = tte.parse_spreadsheet_bytes(file_bytes, filename)
                    if not tags:
                        self._json({"error": f"No tags found in '{filename}'."}, HTTPStatus.BAD_REQUEST)
                        return
                    processed = tte.process_tags(tags)
                    self._json({"source": "upload", "filename": filename, "tags_count": len(tags), "data": processed})
                    return

                if path == "/api/parse-path":
                    filepath = str(payload.get("path", "")).strip()
                    if not filepath or not os.path.exists(filepath):
                        self._json({"error": f"File does not exist: {filepath}"}, HTTPStatus.BAD_REQUEST)
                        return
                    tags = tte.parse_spreadsheet_file(filepath)
                    processed = tte.process_tags(tags)
                    self._json({"source": "file", "path": filepath, "tags_count": len(tags), "data": processed})
                    return

                if path == "/api/export-breakout":
                    records = payload.get("records", [])
                    excel_bytes = tte.build_breakout_excel_bytes(records)
                    filename = str(payload.get("filename", "breakout_sequences.xlsx"))
                    if not filename.lower().endswith(".xlsx"):
                        filename += ".xlsx"
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.send_header("Content-Length", str(len(excel_bytes)))
                    self.end_headers()
                    self.wfile.write(excel_bytes)
                    return

                if path == "/api/export-final":
                    records = payload.get("records", [])
                    excel_bytes = tte.build_final_2column_excel_bytes(records)
                    filename = str(payload.get("filename", "final-translation_sequences.xlsx"))
                    if not filename.lower().endswith(".xlsx"):
                        filename += ".xlsx"
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.send_header("Content-Length", str(len(excel_bytes)))
                    self.end_headers()
                    self.wfile.write(excel_bytes)
                    return

                if path == "/api/open-in-excel":
                    import tempfile
                    records = payload.get("records", [])
                    file_type = str(payload.get("type", "final"))
                    excel_bytes = tte.build_breakout_excel_bytes(records) if file_type == "breakout" else tte.build_final_2column_excel_bytes(records)
                    out_filename = "breakout_sequences.xlsx" if file_type == "breakout" else "final-translation_sequences.xlsx"
                    out_path = Path(tempfile.gettempdir()) / out_filename
                    out_path.write_bytes(excel_bytes)
                    os.startfile(str(out_path))
                    self._json({"status": "opened", "path": str(out_path)})
                    return

            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return

        if path not in {"/api/prepare", "/api/finalize"}:
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        run_id = uuid.uuid4().hex
        with RUNS_LOCK:
            RUNS[run_id] = {"id": run_id, "action": path[5:], "status": "running", "logs": []}
        threading.Thread(target=_run_job, args=(run_id, path[5:], payload), daemon=True).start()
        self._json({"run_id": run_id}, HTTPStatus.ACCEPTED)

    def _serve_ui(self, path: str) -> None:
        requested = (UI_DIST / path.lstrip("/")).resolve()
        if path == "/" or not requested.is_file() or UI_DIST.resolve() not in requested.parents:
            requested = UI_DIST / "index.html"
        if not requested.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Build the frontend first")
            return
        body = requested.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(requested.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    wipe_transient_files()
    parser = argparse.ArgumentParser(description="Run the local Tag Operations frontend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(f"Tag Operations is running at http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
