from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import importlib
import sys
import os

# Ensure the directory containing this server script is always on sys.path
# so that local modules (CNOOC_mapping, Scovan_Mapping, tag_translation_engine)
# are importable regardless of the working directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import CNOOC_mapping
import Scovan_Mapping
import tag_translation_engine as tte

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "web_static"


def _reload_engine():
    global tte
    try:
        importlib.reload(CNOOC_mapping)
        importlib.reload(Scovan_Mapping)
        tte = importlib.reload(tte)
    except Exception as exc:
        print(f"Failed to reload engine: {exc}")



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


def _browse_excel_file() -> str | None:
    """Open an instant native Windows file dialog for Excel / CSV via Win32 C API."""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        buffer = ctypes.create_unicode_buffer(512)
        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        ofn.hwndOwner = hwnd
        ofn.lpstrFilter = "Excel Workbooks & CSV (*.xlsx;*.xls;*.csv)\0*.xlsx;*.xls;*.csv\0All Files (*.*)\0*.*\0\0"
        ofn.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
        ofn.nMaxFile = 512
        ofn.lpstrTitle = "Select Tag Spreadsheet"
        ofn.Flags = 0x00000800 | 0x00000008 | 0x00001000  # OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_FILEMUSTEXIST
        ofn.lpstrDefExt = "xlsx"

        func = ctypes.windll.comdlg32.GetOpenFileNameW
        if func(ctypes.byref(ofn)):
            return buffer.value
        return None
    except Exception:
        pass

    # Fallback to PowerShell
    try:
        ps_code = 'Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.OpenFileDialog; $f.Filter = "Excel Workbooks & CSV (*.xlsx;*.xls;*.csv)|*.xlsx;*.xls;*.csv|All Files (*.*)|*.*"; $f.Title = "Select Tag Spreadsheet"; $top = New-Object System.Windows.Forms.Form; $top.TopMost = $true; if ($f.ShowDialog($top) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.FileName }'
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


class TagTranslatorHandler(BaseHTTPRequestHandler):
    server_version = "ScovanTagTranslator/1.0"

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/api/browse":
            selected = _browse_excel_file()
            if selected and os.path.exists(selected):
                try:
                    tags = tte.parse_spreadsheet_file(selected)
                    processed = tte.process_tags(tags)
                    self._json({"path": selected, "tags": tags, "data": processed})
                except Exception as exc:
                    self._json({"path": selected, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            else:
                self._json({"path": selected})
            return

        if path == "/api/status":
            self._json({"status": "running", "version": "1.0"})
            return

        self._serve_static(path)

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
        except Exception as exc:
            self._json({"error": f"Failed reading request body: {exc}"}, HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/"):
            _reload_engine()

        if path == "/api/parse-dump":
            try:
                payload = json.loads(raw_body or b"{}")
                text = str(payload.get("text", ""))
                tags = tte.parse_raw_tag_text(text)
                if not tags:
                    self._json({"error": "No valid tags could be parsed from the provided text."}, HTTPStatus.BAD_REQUEST)
                    return
                processed = tte.process_tags(tags)
                self._json({"source": "dump", "tags_count": len(tags), "data": processed})
            except Exception as exc:
                self._json({"error": str(exc), "trace": traceback.format_exc()}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/parse-upload":
            try:
                payload = json.loads(raw_body or b"{}")
                filename = str(payload.get("filename", "upload.xlsx"))
                b64_content = str(payload.get("content", ""))
                file_bytes = base64.b64decode(b64_content)
                tags = tte.parse_spreadsheet_bytes(file_bytes, filename)
                if not tags:
                    self._json({"error": f"No tags found in the uploaded file '{filename}'."}, HTTPStatus.BAD_REQUEST)
                    return
                processed = tte.process_tags(tags)
                self._json({"source": "upload", "filename": filename, "tags_count": len(tags), "data": processed})
            except Exception as exc:
                self._json({"error": str(exc), "trace": traceback.format_exc()}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/parse-path":
            try:
                payload = json.loads(raw_body or b"{}")
                filepath = str(payload.get("path", "")).strip()
                if not filepath or not os.path.exists(filepath):
                    self._json({"error": f"File path does not exist: {filepath}"}, HTTPStatus.BAD_REQUEST)
                    return
                tags = tte.parse_spreadsheet_file(filepath)
                if not tags:
                    self._json({"error": f"No tags found in '{filepath}'."}, HTTPStatus.BAD_REQUEST)
                    return
                processed = tte.process_tags(tags)
                self._json({"source": "file", "path": filepath, "tags_count": len(tags), "data": processed})
            except Exception as exc:
                self._json({"error": str(exc), "trace": traceback.format_exc()}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/recompute":
            try:
                payload = json.loads(raw_body or b"{}")
                records = payload.get("records", [])
                field_values = payload.get("field_values", {})
                updated_records = tte.compute_final_translations(records, field_values)
                self._json({"records": updated_records})
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/export-breakout":
            try:
                payload = json.loads(raw_body or b"{}")
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
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/export-final":
            try:
                payload = json.loads(raw_body or b"{}")
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
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/open-in-excel":
            try:
                payload = json.loads(raw_body or b"{}")
                records = payload.get("records", [])
                file_type = str(payload.get("type", "final"))
                if file_type == "breakout":
                    excel_bytes = tte.build_breakout_excel_bytes(records)
                    out_filename = "breakout_sequences.xlsx"
                else:
                    excel_bytes = tte.build_final_2column_excel_bytes(records)
                    out_filename = "final-translation_sequences.xlsx"

                out_path = Path(tempfile.gettempdir()) / out_filename
                out_path.write_bytes(excel_bytes)
                os.startfile(str(out_path))
                self._json({"status": "opened", "path": str(out_path)})
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._json({"error": "Endpoint not found"}, HTTPStatus.NOT_FOUND)

    def _serve_static(self, path: str) -> None:
        clean_path = path.lstrip("/")
        if not clean_path or clean_path == "/":
            clean_path = "index.html"

        file_path = (STATIC_DIR / clean_path).resolve()
        if not file_path.is_file() or STATIC_DIR.resolve() not in file_path.parents and file_path != STATIC_DIR / "index.html":
            file_path = STATIC_DIR / "index.html"

        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Web UI not found")
            return

        content = file_path.read_bytes()
        mime_type, _ = mimetypes.guess_type(file_path.name)
        if not mime_type:
            mime_type = "application/octet-stream"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str = "127.0.0.1", port: int = 8770) -> None:
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, TagTranslatorHandler)
    print(f"============================================================")
    print(f" Scovan -> CNOOC Tag Translator Web App is LIVE")
    print(f" URL: http://{host}:{port}")
    print(f"============================================================")
    httpd.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scovan to CNOOC Tag Translation Web App Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface")
    parser.add_argument("--port", type=int, default=8770, help="Port number")
    args = parser.parse_args()
    run_server(args.host, args.port)
