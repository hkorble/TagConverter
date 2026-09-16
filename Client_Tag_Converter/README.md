# Client Tag Converter

Pure software tool for converting instrument, equipment, piping, heat trace, and electrical tags between Scovan and Client (CNOOC) tag standards.

**No dependency on CAD drawings, AutoCAD, or vector graphics.**

## Quick Start

Double-click **`start_tag_translator.bat`** to launch the web app on port 8770 and open your browser automatically.

Or run directly with Python:
```bash
python tag_translator_server.py --port 8770
```

> **Python path**: The bundled runtime at `..\Project\.runtime\python\python.exe` is used automatically by the `.bat` file.  
> You can also use any Python ≥ 3.9 with `pip install -r requirements.txt`.

## Running Tests
```bash
python -m unittest discover -s . -p "test_*.py"
```

## Project Files
| File | Purpose |
|------|---------|
| `tag_translation_engine.py` | Core parsing, decomposition, and translation engine |
| `Scovan_Mapping.py` | Scovan sequences, lookup tables, abbreviations |
| `CNOOC_mapping.py` | CNOOC sequences, lookup tables, abbreviations |
| `tag_translator_server.py` | HTTP server with REST endpoints |
| `web_static/index.html` | Responsive single-page web app |
| `main_logic.py` | Standalone CLI batch processing pipeline |
| `test_tag_translator_suite.py` | Comprehensive unit test suite |
| `start_tag_translator.bat` | One-click launcher |
