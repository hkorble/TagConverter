from __future__ import annotations

import os
import uuid
import pandas as pd
import ezdxf
from ezdxf.addons import odafc

from config import BLOCK_RULES_LEGEND, ODA_EXEC_PATH
from workflow_common import clean_text as _clean_text, is_placeholder as _is_placeholder

ezdxf.options.set(
    'odafc-addon',
    'win_exec_path',
    ODA_EXEC_PATH,
)

def generate_spatial_registry(dwg_path: str, output_excel_path: str, csv_path: str = 'autocad_groups.csv') -> pd.DataFrame:
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

    attribute_to_block = {}
    for bname, rule in BLOCK_RULES_LEGEND.items():
        if rule.get('is_block') is True:
            attrs = rule.get('target_attributes', [rule.get('target_attribute')])
            for attr in attrs:
                if attr:
                    attribute_to_block[str(attr).upper()] = bname

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
        entity_spatial_map.append({
            'id': element_id, 
            'x': round(x, 3), 
            'y': round(y, 3), 
            'record': record
        })

    insert_entities = []
    for e in msp.query('INSERT'):
        if e.dxf.get('layer', '').strip().upper() == 'FLAGGING':
            continue
        raw_name = e.dxf.name
        eff_name = getattr(e, 'effective_name', raw_name)

        is_allowed = False
        if eff_name in allowed_blocks or raw_name in allowed_blocks:
            is_allowed = True
        elif e.has_attrib:
            for attr in e.attribs:
                if attr.dxf.tag.upper() in attribute_to_block:
                    is_allowed = True
                    break

        if is_allowed:
            insert_entities.append(e)

    for insert in insert_entities:
        raw_name = insert.dxf.name
        eff_name = getattr(insert, 'effective_name', raw_name)
        if eff_name in allowed_blocks:
            block_name = eff_name
        elif raw_name in allowed_blocks:
            block_name = raw_name
        elif insert.has_attrib:
            block_name = raw_name
            for attr in insert.attribs:
                tag_name = attr.dxf.tag.upper()
                if tag_name in attribute_to_block:
                    block_name = attribute_to_block[tag_name]
                    break
        else:
            block_name = eff_name
        coords = insert.dxf.insert or (0.0, 0.0, 0.0)
        x, y, z = float(coords[0]), float(coords[1]), float(coords[2])

        attr_summary = {}
        if insert.has_attrib:
            for attr in insert.attribs:
                flags = attr.dxf.get('flags', 0)
                is_invisible = bool(flags & 1)
                if not is_invisible:
                    tag = attr.dxf.tag.upper()
                    val = _clean_text(attr.dxf.text)
                    attr_summary[tag] = val

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
        entity_spatial_map.append({
            'id': element_id, 
            'x': round(x, 3), 
            'y': round(y, 3), 
            'record': record
        })

    spatial_lookup = {(item['x'], item['y']): item for item in entity_spatial_map}

    connection_records = []
    
    if os.path.exists(csv_path):
        try:
            df_csv = pd.read_csv(csv_path)
            for _, grouped_rows in df_csv.groupby('GroupName', sort=False):
                if len(grouped_rows) != 2:
                    continue
                row_a = grouped_rows.iloc[0]
                row_b = grouped_rows.iloc[1]
                
                try:
                    ax, ay = round(float(row_a['X']), 3), round(float(row_a['Y']), 3)
                    bx, by = round(float(row_b['X']), 3), round(float(row_b['Y']), 3)
                except Exception:
                    continue
                    
                item_a = spatial_lookup.get((ax, ay))
                item_b = spatial_lookup.get((bx, by))
                
                if item_a and item_b:
                    flag_sig = f"CSV_PAIR|{item_a['id']}|{item_b['id']}"
                    
                    item_a_is_placeholder = _is_placeholder(item_a['record']['Content / Value'])
                    item_b_is_placeholder = _is_placeholder(item_b['record']['Content / Value'])

                    if item_a_is_placeholder and not item_b_is_placeholder:
                        p_item, a_item = item_a, item_b
                    elif item_b_is_placeholder and not item_a_is_placeholder:
                        p_item, a_item = item_b, item_a
                    else:
                        p_item = item_a if item_a['record']['Entity Category'] == 'Text/Label' else item_b
                        a_item = item_b if p_item == item_a else item_a

                    connection_records.append({
                        'Flag Line ID': str(uuid.uuid5(uuid.NAMESPACE_OID, flag_sig)),
                        'Detection Technique': 'CSV_GROUP_PAIR',
                        'Placeholder ID': p_item['id'],
                        'Placeholder Layer': p_item['record']['Layer'],
                        'Placeholder Content': p_item['record']['Content / Value'],
                        'Placeholder X': p_item['x'],
                        'Placeholder Y': p_item['y'],
                        'Asset ID': a_item['id'],
                        'Asset Layer': a_item['record']['Layer'],
                        'Asset Subtype/Block': a_item['record']['Subtype / Block Name'],
                        'Asset Content/Value': a_item['record']['Content / Value'],
                        'Asset X': a_item['x'],
                        'Asset Y': a_item['y'],
                    })
        except Exception:
            pass

    print(f'-> Total paired connections mapped: {len(connection_records)}')

    df_master = pd.DataFrame(registry_records)
    df_connections = pd.DataFrame(connection_records)

    with pd.ExcelWriter(output_excel_path, engine='openpyxl') as writer:
        df_master.to_excel(writer, sheet_name='Master Registry', index=False)
        df_connections.to_excel(writer, sheet_name='Connected Elements', index=False)

    print(f'Successfully generated multi-sheet workbook with {len(df_master)} master records and {len(df_connections)} paired connections!')
    return df_master
