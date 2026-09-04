# config.py
from __future__ import annotations

import os
from pathlib import Path

# ==========================================
# METADATA & BLOCK RULES LEGEND CONFIGURATION
# ==========================================
BLOCK_RULES_LEGEND = {
    "Dyn_Vlv_ATTV": {
        "target_attribute": "VLV_TAG",
        "is_block": True,
        "instrument": False,
    },
    "Dyn_Vlv_ATTH": {
        "target_attribute": "VLV_TAG",
        "is_block": True,
        "instrument": False,
    },
    "dyn_instr shared disp": {
        "target_attributes": ["TOP", "BTM"],
        "is_block": True,
        "instrument": True,
    },
    "Dyn_Discrete Instr": {
        "target_attributes": ["TOP", "BTM"],
        "is_block": True,
        "instrument": True,
    },
    "dyn_instr plc": {
        "target_attributes": ["TOP", "BTM"],
        "is_block": True,
        "instrument": True,
    },
    "dyn_meter": {
        "target_attributes": ["TXT1", "TXT2"],
        "is_block": True,
        "instrument": True,
    }, 
    "dyn-vlv-bw": {
            "target_attribute": "VLV_NUM",
            "is_block": True,
            "instrument": False,
        },
    
    "MTEXT": {
        "target_attribute": "TEXT",
        "is_block": False,
        "instrument": False,
    },
    "TEXT": {
        "target_attribute": "TEXT",
        "is_block": False,
        "instrument": False,
    },
}

_PROJECT_ROOT = Path(__file__).resolve().parent
_PORTABLE_ODA = _PROJECT_ROOT / ".runtime" / "oda" / "ODAFileConverter.exe"
ODA_EXEC_PATH = os.environ.get(
    "ODA_FILE_CONVERTER",
    str(_PORTABLE_ODA if _PORTABLE_ODA.exists() else Path(r"C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe")),
)

# Client placeholder detection lives here so both workflows interpret drawings
# the same way. Add/remove tokens or patterns without touching pipeline code.
PLACEHOLDER_RULES = {
    "empty_is_placeholder": True,
    "case_sensitive": False,
    "contains": ["CLIENT"],
    "regex": [r"X{3,}"],
}

AUTOCAD_CORE_PATHS = [
    rf"C:\Program Files\Autodesk\AutoCAD {year}\accoreconsole.exe"
    for year in (2027, 2026, 2025, 2024, 2023)
]

WORKFLOW_CONFIG = {
    "dual_tagging": {
        "label": "Dual tagging",
        "description": "Pair client placeholders with source assets and synchronize both tags.",
        "uses_large_groups": False,
        "mapping_mode": "all_connections",
    },
    "client_translation": {
        "label": "Client translation",
        "description": "Translate each tagged entity in place using a client mapping sheet.",
        "uses_large_groups": True,
        "mapping_mode": "non_placeholder_assets",
    },
}
