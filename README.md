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
