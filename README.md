# Tag Operations

One local application for the dual-tagging and client-translation drawing workflows.

## Start the app

Double-click `start_app.bat`. The project runtime includes portable
Python and the ODA File Converter, so no system-wide installation is required.

The app runs locally at `http://127.0.0.1:8765`. When AutoCAD is installed, Core
Console performs group extraction and COM automation performs the final ATTSYNC.
The portable ODA File Converter reads and writes DWGs and remains available as an
extraction fallback when AutoCAD is temporarily unavailable. No drawing data is
uploaded.

## Workflow

1. Choose **Dual tagging** or **Client translation**.
2. Paste the DWG path and optionally its workspace folder.
3. Select **Prepare mapping**.
4. Fill and save `Client_Mapping_Sheet.xlsx`, then close Excel.
5. Select **Validate & finish drawing**.

Shared placeholder rules, workflow metadata, AutoCAD versions, and block rules are
in `config.py`. The common extraction/mapping code is in `workflow_common.py`, and
both workflows are orchestrated by `workflow_engine.py`.

---

## Scovan → CNOOC Tag Sequence Translator Web App

A dedicated web app for decomposing Scovan tag sequences, mapping them into CNOOC client syntax, filling in missing client attributes, and generating breakout workbooks.

### Start the Translator
Double-click `start_tag_translator.bat` (or run `.\.runtime\python\python.exe tag_translator_server.py --port 8770`).
The web app opens automatically at `http://127.0.0.1:8770`.

### Features
1. **Spreadsheet Upload**: Drag & drop or upload any `.xlsx`, `.xls`, or `.csv` drawing/line list.
2. **File Explorer Browse**: Open native Windows File Explorer dialog directly from the browser to select files.
3. **Copy/Paste Dump**: Paste a list of tags directly from Excel or text.
4. **Interactive Breakout Table**: View categorized sequence tags with missing fields highlighted in real-time.
5. **Batch Fill**: Quickly fill required attributes (such as `plant_name` or `circuit_identifier`) across all tags or specific sequence categories.
6. **Multi-Format Export**:
   - Download multi-sheet **Breakout Excel** (`breakout_sequences.xlsx`).
   - Download final 2-column **Translation Excel** (`final-translation_sequences.xlsx`).
   - Copy 2-column TSV directly to clipboard.
   - One-click launch in Microsoft Excel.

