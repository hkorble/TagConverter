from __future__ import annotations

import subprocess
import os
import re
import ast
import uuid
import pandas as pd
import ezdxf
from ezdxf.addons import odafc
import comtypes.client

from config import BLOCK_RULES_LEGEND, ODA_EXEC_PATH
from update_translated import update_connected_pids
from workflow_common import clean_text as _clean_text, is_placeholder as _is_placeholder

ezdxf.options.set(
    'odafc-addon',
    'win_exec_path',
    ODA_EXEC_PATH,
)

def generate_spatial_registry_translation(
    dwg_path: str, 
    output_excel_path: str, 
    csv_path: str,
    large_csv_path: str
) -> pd.DataFrame:
    if not os.path.exists(dwg_path):
        raise FileNotFoundError(f'Could not find DWG file at: {dwg_path}')

    try:
        doc = odafc.readfile(dwg_path)
    except Exception as exc:
        raise RuntimeError(f'ODA converter failed to read DWG: {exc}') from exc

    msp = doc.modelspace()
    registry_records = []
    entity_spatial_map = []

    allowed_blocks = [k for k, v in BLOCK_RULES_LEGEND.items() if v.get('is_block') is True]
    allowed_texts = [k for k, v in BLOCK_RULES_LEGEND.items() if v.get('is_block') is False and k != 'DEFAULT']

    text_entities = [
        e for e in msp 
        if e.dxftype() in allowed_texts
        and e.dxf.get('layer', '').strip().upper() != 'FLAGGING'
    ]
    
    for entity in text_entities:
        if entity.dxftype() == 'TEXT':
            content = _clean_text(entity.dxf.text)
            insert = entity.dxf.insert
        else:
            content = _clean_text(entity.text)
            insert = entity.dxf.insert

        x, y = float(insert.x), float(insert.y)
        z = float(insert.z) if hasattr(insert, 'z') else 0.0
        
        raw_signature = f'TEXT|{content}|{round(x, 3)}|{round(y, 3)}'
        element_id = str(uuid.uuid5(uuid.NAMESPACE_OID, raw_signature))

        record = {
            'Unique ID': element_id,
            'Entity Category': 'Text/Label',
            'Subtype / Block Name': entity.dxftype(),
            'Content / Value': content,
            'Layer': entity.dxf.get('layer', '0'),
            'Coordinate X': round(x, 3),
            'Coordinate Y': round(y, 3),
            'Coordinate Z': round(z, 3),
        }
        registry_records.append(record)
        entity_spatial_map.append({'id': element_id, 'x': round(x, 3), 'y': round(y, 3), 'record': record})

    insert_entities = [
        e for e in msp.query('INSERT') 
        if (getattr(e, 'effective_name', e.dxf.name) in allowed_blocks or e.dxf.name in allowed_blocks)
        and e.dxf.get('layer', '').strip().upper() != 'FLAGGING'
    ]
    
    for insert in insert_entities:
        block_name = getattr(insert, 'effective_name', insert.dxf.name)
        coords = insert.dxf.insert or (0.0, 0.0, 0.0)
        x, y, z = float(coords[0]), float(coords[1]), float(coords[2])

        attr_summary = {}
        if insert.has_attrib:
            for attr in insert.attribs:
                flags = attr.dxf.get('flags', 0)
                is_invisible = bool(flags & 1)
                if not is_invisible:
                    attr_summary[attr.dxf.tag.upper()] = _clean_text(attr.dxf.text)

        raw_signature = f'BLOCK|{block_name}|{round(x, 3)}|{round(y, 3)}'
        element_id = str(uuid.uuid5(uuid.NAMESPACE_OID, raw_signature))

        content_val = str(attr_summary) if attr_summary else 'N/A'
        record = {
            'Unique ID': element_id,
            'Entity Category': 'Block Reference',
            'Subtype / Block Name': block_name,
            'Content / Value': content_val,
            'Layer': insert.dxf.get('layer', '0'),
            'Coordinate X': round(x, 3),
            'Coordinate Y': round(y, 3),
            'Coordinate Z': round(z, 3),
        }
        registry_records.append(record)
        entity_spatial_map.append({'id': element_id, 'x': round(x, 3), 'y': round(y, 3), 'record': record})

    spatial_lookup = {(item['x'], item['y']): item for item in entity_spatial_map}

    connection_records = []
    processed_coords = set()

    def process_csv_file(path_to_csv):
        if not os.path.exists(path_to_csv):
            return
        try:
            df_csv = pd.read_csv(path_to_csv)
            if df_csv.empty:
                return
            for _, row in df_csv.iterrows():
                try:
                    rx, ry = round(float(row['X']), 3), round(float(row['Y']), 3)
                except Exception:
                    continue
                
                coord_key = (rx, ry)
                if coord_key in processed_coords:
                    continue
                processed_coords.add(coord_key)

                item = spatial_lookup.get(coord_key)
                if not item:
                    best_dist = 25.0
                    for (ex, ey), candidate in spatial_lookup.items():
                        dist_sq = (ex - rx) ** 2 + (ey - ry) ** 2
                        if dist_sq < best_dist:
                            best_dist = dist_sq
                            item = candidate

                if item:
                    content_val = item['record']['Content / Value']
                    flag_sig = f"TRANSLATION_MAP|{item['id']}"
                    connection_records.append({
                        'Flag Line ID': str(uuid.uuid5(uuid.NAMESPACE_OID, flag_sig)),
                        'Detection Technique': 'CLIENT_TRANSLATION_GROUP',
                        'Placeholder ID': item['id'],
                        'Placeholder Layer': item['record']['Layer'],
                        'Placeholder Content': content_val,
                        'Placeholder X': item['x'],
                        'Placeholder Y': item['y'],
                        'Asset ID': item['id'],
                        'Asset Layer': item['record']['Layer'],
                        'Asset Subtype/Block': item['record']['Subtype / Block Name'],
                        'Asset Content/Value': content_val,
                        'Asset X': item['x'],
                        'Asset Y': item['y'],
                    })
        except Exception:
            pass

    process_csv_file(csv_path)
    process_csv_file(large_csv_path)

    df_master = pd.DataFrame(registry_records)
    df_connections = pd.DataFrame(connection_records)

    with pd.ExcelWriter(output_excel_path, engine='openpyxl') as writer:
        df_master.to_excel(writer, sheet_name='Master Registry', index=False)
        df_connections.to_excel(writer, sheet_name='Connected Elements', index=False)

    return df_master
