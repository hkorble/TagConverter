import subprocess
import os
import re
import ast
import pandas as pd
import comtypes.client

from annotation import generate_spatial_registry
from update_connected import update_connected_pids
from config import BLOCK_RULES_LEGEND

def run_pipeline():
    base_dir = r"C:\Scovan\PadXpress Source Code\Dual_Tagging_App"
    dwg_file = os.path.join(base_dir, "G02-1-PRDXXXX-M-PID-01-P01-01 (1).dwg")
    excel_file = os.path.join(base_dir, "Master_Registry.xlsx")
    mapping_excel_file = os.path.join(base_dir, "Client_Mapping_Sheet.xlsx")
    updated_dwg_file = os.path.join(base_dir, "G02-1-PRDXXXX-M-PID-01-P01-01 (1)_Updated.dwg")
    csv_file = os.path.join(base_dir, "autocad_groups.csv")
    
    lsp_file = os.path.join(base_dir, "ExportTagData.lsp")
    scr_file = os.path.join(base_dir, "run_script.scr")
    attsyn_scr_file = os.path.join(base_dir, "attsyn.scr")
    
    possible_paths = [
        r"C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe",
        r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe",
        r"C:\Program Files\Autodesk\AutoCAD 2024\accoreconsole.exe",
        r"C:\Program Files\Autodesk\AutoCAD 2023\accoreconsole.exe"
    ]
    
    accore_path = next((p for p in possible_paths if os.path.exists(p)), None)

    print("--- STEP 1: Running Headless AutoCAD Group Extraction ---")
    if accore_path:
        print(f"Found core console at: {accore_path}")
        lsp_path_str = lsp_file.replace(os.sep, '/')
        
        script_content = f'(setvar "SECURELOAD" 0)\n(load "{lsp_path_str}")\nExportTagData \nQUIT\n'
        with open(scr_file, "w") as f:
            f.write(script_content)

        cmd = [
            accore_path,
            "/i", dwg_file,
            "/tr", base_dir,
            "/s", scr_file
        ]
        
        result = subprocess.run(cmd, cwd=base_dir, capture_output=True, text=True)
        print("Core Console STDOUT:\n", result.stdout)
        if result.returncode != 0:
            print(f"Core Console Error Details: {result.stderr}")
        else:
            print("Successfully extracted AutoCAD groups to CSV.")
    else:
        print("Skipping core console: accoreconsole.exe could not be found.")

    print("\n--- STEP 2: Generating Spatial Master Registry & Connections ---")
    generate_spatial_registry(dwg_file, excel_file, csv_path=csv_file)

    print("\n--- STEP 3: Preparing Manual Client Mapping Spreadsheet ---")
    df_conn = pd.read_excel(excel_file, sheet_name='Connected Elements')
    
    mapping_rows = []
    for _, row in df_conn.iterrows():
        p_content = str(row.get("Placeholder Content", ""))
        a_sub = str(row.get("Asset Subtype/Block", ""))
        a_val = str(row.get("Asset Content/Value", ""))
        
        is_p_target = ("CLIENT" in p_content.upper() or bool(re.search(r'X{3,}', p_content.upper())))
        raw_val = a_val if is_p_target else p_content
        
        rule = BLOCK_RULES_LEGEND.get(a_sub, {})
        target_tags = rule.get("target_attributes", [rule.get("target_attribute", "VLV_TAG")])
        if isinstance(target_tags, str):
            target_tags = [target_tags]

        unpacked_str = raw_val
        if raw_val.startswith("{") and raw_val.endswith("}"):
            try:
                d = ast.literal_eval(raw_val)
                if isinstance(d, dict):
                    vals = [str(d[tag]) for tag in target_tags if tag in d and d[tag] is not None and str(d[tag]).strip() != ""]
                    if vals:
                        unpacked_str = "-".join(vals)
            except Exception:
                pass
                
        mapping_rows.append({
            "Scovan Tag": unpacked_str,
            "Client Tag Mapping": ""
        })
        
    df_map = pd.DataFrame(mapping_rows)
    
    with pd.ExcelWriter(mapping_excel_file, engine='openpyxl') as writer:
        df_map.to_excel(writer, index=False, sheet_name='Mapping')
        worksheet = writer.sheets['Mapping']
        worksheet.column_dimensions['A'].width = 35
        worksheet.column_dimensions['B'].width = 35
    
    print(f"\n[!] Created mapping spreadsheet at: {mapping_excel_file}")
    print("[!] Please open this file, fill in every cell under 'Client Tag Mapping', save, and close Excel.")

    while True:
        input(">>> Press Enter here *after* you have saved and closed the mapping spreadsheet to validate...")
        
        if not os.path.exists(mapping_excel_file):
            print("[Error] Mapping spreadsheet file missing! Please regenerate.")
            continue
            
        df_map_updated = pd.read_excel(mapping_excel_file)
        
        if "Client Tag Mapping" not in df_map_updated.columns:
            print("[Error] 'Client Tag Mapping' column missing from spreadsheet! Please do not alter column headers.")
            continue
            
        missing_count = df_map_updated["Client Tag Mapping"].isna().sum() or (df_map_updated["Client Tag Mapping"].astype(str).str.strip() == "").sum()
        
        if missing_count > 0:
            print(f"\n[Validation Error] Found {missing_count} unfilled or blank entry(ies) in 'Client Tag Mapping'.")
            print("[Action Required] Every row must be filled out completely. Please fix the spreadsheet, save, and close it.")
        else:
            print("\n[Validation Success] All mapping entries are fully populated!")
            break

    print("\n--- STEP 4: Injecting Client Mappings & Formatting Metadata Structures ---")
    mapping_dict = dict(enumerate(df_map_updated["Client Tag Mapping"]))
    
    updated_connection_records = []
    
    for idx, row in df_conn.iterrows():
        custom_mapping = str(mapping_dict.get(idx, "")).strip()
        
        asset_sub = str(row.get("Asset Subtype/Block", ""))
        rule = BLOCK_RULES_LEGEND.get(asset_sub, {})
        
        row_dict = row.to_dict()
        p_content = str(row.get("Placeholder Content", ""))
        is_p_target = ("CLIENT" in p_content.upper() or bool(re.search(r'X{3,}', p_content.upper())))
        
        if "target_attributes" in rule:
            target_tags = rule["target_attributes"]
            map_parts = [p.strip() for p in custom_mapping.split("-")]
            
            target_col = "Placeholder Content" if is_p_target else "Asset Content/Value"
            orig_raw = str(row.get(target_col, ""))
            
            val_dict = {}
            try:
                if orig_raw.startswith("{") and orig_raw.endswith("}"):
                    val_dict = ast.literal_eval(orig_raw)
            except Exception:
                pass
            if not isinstance(val_dict, dict):
                val_dict = {}

            for tag_idx, t_tag in enumerate(target_tags):
                if tag_idx < len(map_parts):
                    val_dict[t_tag] = map_parts[tag_idx]
                elif t_tag not in val_dict:
                    val_dict[t_tag] = ""
            formatted_val = str(val_dict)
        else:
            formatted_val = custom_mapping
            
        if is_p_target:
            row_dict["Placeholder Content"] = formatted_val
        else:
            row_dict["Asset Content/Value"] = formatted_val
            
        updated_connection_records.append(row_dict)

    df_final_conn = pd.DataFrame(updated_connection_records)
    
    with pd.ExcelFile(excel_file) as reader:
        sheet_names = reader.sheet_names
        
    df_master_reg = pd.read_excel(excel_file, sheet_name='Master Registry') if 'Master Registry' in sheet_names else pd.DataFrame()

    with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
        if not df_master_reg.empty:
            df_master_reg.to_excel(writer, sheet_name='Master Registry', index=False)
        df_final_conn.to_excel(writer, sheet_name='Connected Elements', index=False)

    print("\n--- STEP 5: Updating DWG Target Entities with Synced Values ---")
    if os.path.exists(updated_dwg_file):
        try:
            os.remove(updated_dwg_file)
        except OSError:
            pass
            
    update_connected_pids(dwg_file, excel_file, updated_dwg_file)

    print("\n--- STEP 6: Executing ATTSYNC via Background AutoCAD COM Automation ---")
    if not os.path.exists(attsyn_scr_file):
        print(f"[Error] Could not find script file at: {attsyn_scr_file}")
    else:
        try:
            acad = comtypes.client.GetActiveObject("AutoCAD.Application")
        except Exception:
            try:
                acad = comtypes.client.CreateObject("AutoCAD.Application")
            except Exception as e:
                acad = None
                print(f"[Error] Could not initialize AutoCAD via COM: {e}")

        if acad:
            try:
                acad.Visible = False
                doc = acad.Documents.Open(os.path.abspath(updated_dwg_file))
                
                script_path_cad = attsyn_scr_file.replace("\\", "/")
                doc.SendCommand(f'(load "{script_path_cad}")\n')
                
                doc.Save()
                doc.Close()
                print("Successfully executed ATTSYNC script and updated drawing blocks via background AutoCAD.")
            except Exception as e:
                print(f"[Error] Failed executing script through background AutoCAD COM: {e}")
        else:
            print("Skipping background AutoCAD automation: Application instance unavailable.")

    print("\nPipeline execution completed successfully!")

if __name__ == "__main__":
    run_pipeline()