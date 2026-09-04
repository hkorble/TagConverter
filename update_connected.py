from __future__ import annotations

import os
import re
import math
import ast
from typing import Tuple
import pandas as pd
import ezdxf
from ezdxf.addons import odafc

from config import BLOCK_RULES_LEGEND, ODA_EXEC_PATH

# Configure ODA File Converter path for ezdxf
ezdxf.options.set(
    "odafc-addon",
    "win_exec_path",
    ODA_EXEC_PATH,
)


def _clean_text(raw_text: object) -> str:
    """Strip AutoCAD MTEXT formatting codes."""
    text_str = str(raw_text or "")
    if not text_str:
        return ""
    cleaned = re.sub(r'\\[A-Za-z][^;]*;|[{}]', '', text_str)
    return cleaned.strip()


def _is_placeholder(val: str) -> bool:
    """Returns True if the text indicates a placeholder ('CLIENT' or 3+ consecutive 'x'/'X')."""
    if pd.isna(val) or not val:
        return True
    s = str(val).upper()
    if "CLIENT" in s:
        return True
    if re.search(r'X{3,}', s):
        return True
    return False


def _split_tag_at_first_dash(raw_str: str) -> Tuple[str, str]:
    """Splits a combined tag string (e.g., 'PT-P0116') into top and bottom parts."""
    text = str(raw_str).strip()
    if not text:
        return "", ""
    
    # If it's stored as a dictionary representation string, extract values if possible
    if text.startswith("{") and text.endswith("}"):
        try:
            d = ast.literal_eval(text)
            if isinstance(d, dict):
                vals = [str(v) for v in d.values() if v is not None and str(v).strip() != ""]
                if len(vals) >= 2:
                    return vals[0], vals[1]
                elif len(vals) == 1:
                    return vals[0], ""
        except Exception:
            pass

    parts = text.split("-", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return text, ""


def update_connected_pids(dwg_path: str, excel_path: str, output_dwg_path: str, freeze_dual: bool = False) -> None:
    """
    Reads connection rows from the updated 'Connected Elements' sheet layout, 
    applies fine-tuned character-length offsets for instrument blocks, 
    and updates target entities in the DWG.
    """
    if not os.path.exists(dwg_path):
        raise FileNotFoundError(f"Could not find DWG file at: {dwg_path}")
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Could not find Excel registry at: {excel_path}")

    print(f"Loading connection data from Excel sheet 'Connected Elements': {excel_path}...")
    df_connections = pd.read_excel(excel_path, sheet_name='Connected Elements')
    df_master = pd.read_excel(excel_path, sheet_name='Master Registry')
    print(f"Loaded {len(df_connections)} connection records and {len(df_master)} master registry records.")

    master_lookup = {}
    for _, row in df_master.iterrows():
        uid = str(row.get("Unique ID", ""))
        if uid:
            master_lookup[uid] = {
                "category": row.get("Entity Category"),
                "subtype": row.get("Subtype / Block Name"),
                "x": float(row.get("Coordinate X", 0.0)),
                "y": float(row.get("Coordinate Y", 0.0)),
                "content": str(row.get("Content / Value", ""))
            }

    print(f"Opening DWG file via ODA converter: {dwg_path}...")
    try:
        doc = odafc.readfile(dwg_path)
    except Exception as exc:
        raise RuntimeError(f"ODA converter failed to read DWG: {exc}") from exc

    msp = doc.modelspace()
    updates_applied = 0

    for idx, row in df_connections.iterrows():
        targets = []
        p_id = str(row.get("Placeholder ID", ""))
        p_val = str(row.get("Placeholder Content", ""))
        if p_id and not pd.isna(p_val) and str(p_val) and str(p_val) != "N/A" and "COORDINATES" not in str(p_val).upper():
            targets.append((p_id, str(p_val).strip()))

        if freeze_dual:
            a_id = str(row.get("Asset ID", ""))
            a_val = str(row.get("Asset Content/Value", ""))
            if a_id and not pd.isna(a_val) and str(a_val) and str(a_val) != "N/A" and a_id != p_id:
                targets.append((a_id, str(a_val).strip()))

        for target_id, actual_source_text in targets:
            if target_id not in master_lookup:
                print(f"Skipping target [{target_id}] not found in Master Registry.")
                continue

            target_info = master_lookup[target_id]
            target_cat = target_info["category"]
            target_sub = target_info["subtype"]
            target_x = target_info["x"]
            target_y = target_info["y"]

            rule = BLOCK_RULES_LEGEND.get(target_sub, {})
            is_instrument = rule.get("instrument", False)

            matched = False
            if target_cat == "Block Reference":
                if "target_attributes" in rule:
                    target_attr_tags = rule["target_attributes"]
                else:
                    target_attr_tags = [rule.get("target_attribute")]

                for insert in msp.query("INSERT"):
                    ins_name = getattr(insert, "effective_name", insert.dxf.name)
                    name_match = (ins_name == target_sub or insert.dxf.name == target_sub)
                    if not name_match and insert.has_attrib:
                        for attr in insert.attribs:
                            if attr.dxf.tag.upper() in target_attr_tags:
                                name_match = True
                                break

                    if name_match and insert.has_attrib:
                        coords = insert.dxf.insert or (0.0, 0.0, 0.0)
                        if abs(float(coords[0]) - target_x) < 0.01 and abs(float(coords[1]) - target_y) < 0.01:
                            
                            attrib_map = {}
                            for attr in insert.attribs:
                                attrib_map[attr.dxf.tag.upper()] = attr

                            if is_instrument:
                                new_top, new_btm = _split_tag_at_first_dash(actual_source_text)
                                block_rotation = insert.dxf.rotation or 0.0

                                # Apply to TOP attributes
                                for tag_name in ["TOP", "TXT1"]:
                                    if tag_name in attrib_map and attrib_map[tag_name]:
                                        attr = attrib_map[tag_name]
                                        attr.dxf.text = new_top
                                        attr.dxf.rotation = block_rotation
                                        updates_applied += 1

                                # Apply to BTM attributes
                                for tag_name in ["BTM", "TXT2"]:
                                    if tag_name in attrib_map and attrib_map[tag_name]:
                                        attr = attrib_map[tag_name]
                                        attr.dxf.text = new_btm
                                        attr.dxf.rotation = block_rotation
                                        updates_applied += 1
                            else:
                                # Standard block attribute update
                                attr_dict = {}
                                if actual_source_text.startswith("{") and actual_source_text.endswith("}"):
                                    try:
                                        parsed_dict = ast.literal_eval(actual_source_text)
                                        if isinstance(parsed_dict, dict):
                                            attr_dict = parsed_dict
                                    except Exception:
                                        pass

                                for attr in insert.attribs:
                                    tag_upper = attr.dxf.tag.upper()
                                    for t_tag in target_attr_tags:
                                        if tag_upper == t_tag.upper():
                                            new_val = actual_source_text
                                            if attr_dict:
                                                for k, v in attr_dict.items():
                                                    if k.upper() == tag_upper:
                                                        new_val = str(v)
                                                        break
                                            
                                            attr.dxf.text = new_val
                                            updates_applied += 1
                                            break

                            matched = True
                            break
                    if matched:
                        break

            elif target_cat == "Text/Label":
                for entity in msp:
                    if entity.dxftype() in ('TEXT', 'MTEXT'):
                        insert = entity.dxf.insert
                        if abs(float(insert.x) - target_x) < 0.01 and abs(float(insert.y) - target_y) < 0.01:
                            new_val = actual_source_text
                            
                            if entity.dxftype() == 'TEXT':
                                entity.dxf.text = new_val
                            else:
                                entity.text = new_val
                            updates_applied += 1
                            matched = True
                            break

    print(f"Total elements updated: {updates_applied}")
    if freeze_dual:
        frozen_dual_count = 0
        for layer in doc.layers:
            if "dual" in layer.dxf.name.lower():
                layer.freeze()
                layer.off()
                frozen_dual_count += 1
        print(f"Client translation: Froze and turned off {frozen_dual_count} dual tagging layer(s) matching keyword 'dual'.")

    try:
        odafc.export_dwg(doc, output_dwg_path, replace=True)
    except Exception as exc:
        raise RuntimeError(f"ODA converter failed to export DWG: {exc}") from exc