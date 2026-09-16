from __future__ import annotations

import os
import re
import pandas as pd
from openpyxl.utils import get_column_letter

from Scovan_Mapping import sequences as scovan_sequences
from Scovan_Mapping import component_mapping as scovan_component_mapping
from Scovan_Mapping import fluid_code_mapping as scovan_fluid_code_mapping
from Scovan_Mapping import cable_number_mapping as scovan_cable_number_mapping
try:
    from Scovan_Mapping import sequence_number_mapping as scovan_sequence_number_mapping
except ImportError:
    from Scovan_Mapping import scovan_sequence_number_mapping

from CNOOC_mapping import sequences as cnooc_sequences
from CNOOC_mapping import component_mapping as cnooc_component_mapping
from CNOOC_mapping import fluid_code_mapping as cnooc_fluid_code_mapping
from CNOOC_mapping import cable_number_mapping as cnooc_cable_number_mapping
from CNOOC_mapping import sequence_number_mapping as cnooc_sequence_number_mapping

import tag_translation_engine as tte


def decompose_sequence(sequence_string, mapping_sources=None, sequences_mapping=scovan_sequences):
    return tte.decompose_sequence(sequence_string, mapping_sources, sequences_mapping)


def translate_sequence(
    sequence_key,
    parsed_sections,
    universal_sequence,
    universal_translation,
    client_sequences=cnooc_sequences,
    client_mappings=None
):
    return tte.translate_sequence(
        sequence_key, parsed_sections, universal_sequence, universal_translation, client_sequences, client_mappings
    )


def load_input_sequences_from_excel(input_filepath):
    return tte.parse_spreadsheet_file(input_filepath)


def process_and_export_sequences(input_sequences, output_filepath="breakout_sequences.xlsx"):
    res = tte.process_tags(input_sequences)
    excel_bytes = tte.build_breakout_excel_bytes(res["records"])
    with open(output_filepath, "wb") as f:
        f.write(excel_bytes)
    print(f"\n[Export Successful] Generated breakout file: '{output_filepath}'.")
    return output_filepath


def finalize_and_export_completed_translations(
    input_filepath="breakout_sequences.xlsx",
    output_filepath="final-translation_sequences.xlsx"
):
    if not os.path.exists(input_filepath):
        print(f"[Error] File '{input_filepath}' not found.")
        return

    excel_file = pd.ExcelFile(input_filepath)
    all_final_rows = []
    unfilled_warnings = []

    for sheet_name in excel_file.sheet_names:
        df = pd.read_excel(excel_file, sheet_name=sheet_name).fillna("")

        if df.empty or "Scovan Tag" not in df.columns or "Final Client Translation" not in df.columns:
            continue

        extra_cols = [c for c in df.columns if c not in ("Scovan Tag", "Final Client Translation")]

        for idx, row in df.iterrows():
            scovan_tag = str(row["Scovan Tag"]).strip()
            client_trans = str(row["Final Client Translation"]).strip()

            for col in extra_cols:
                val = str(row[col]).strip()
                if not val:
                    unfilled_warnings.append(
                        f"Sheet: '{sheet_name}' | Row {idx + 2} | Tag: '{scovan_tag}' | Missing Column: '{col}'"
                    )
                else:
                    client_trans = client_trans.replace(f"{{{col}}}", val)
                    client_trans = client_trans.replace(col, val)

            all_final_rows.append({
                "Scovan Tag": scovan_tag,
                "Final Client Translation": client_trans
            })

    if unfilled_warnings:
        print("\n" + "!" * 60)
        print(f"[WARNING] Detected {len(unfilled_warnings)} missing information cell(s):")
        for warn in unfilled_warnings[:15]:
            print(f"  - {warn}")
        if len(unfilled_warnings) > 15:
            print(f"  ... and {len(unfilled_warnings) - 15} more.")
        print("!" * 60)

    final_df = pd.DataFrame(all_final_rows)

    BASE_WIDTH = 8.43
    WIDTH_COL_1 = BASE_WIDTH * 5   # ~42.15
    WIDTH_COL_2 = BASE_WIDTH * 7   # ~59.01

    with pd.ExcelWriter(output_filepath, engine="openpyxl") as writer:
        final_df.to_excel(writer, sheet_name="Final Translations", index=False)
        ws = writer.sheets["Final Translations"]
        ws.column_dimensions["A"].width = WIDTH_COL_1
        ws.column_dimensions["B"].width = WIDTH_COL_2

    print(f"\n[Success] Final 2-column spreadsheet exported to '{output_filepath}'.")


if __name__ == "__main__":
    input_file = "input_tags.xlsx"
    working_file = "breakout_sequences.xlsx"
    final_output = "final-translation_sequences.xlsx"

    if os.path.exists(input_file):
        tags_to_process = load_input_sequences_from_excel(input_file)
        process_and_export_sequences(tags_to_process, working_file)
        input(f"\n>>> Fill in the missing columns in '{working_file}', save it, and press [ENTER] to create '{final_output}'...")
        finalize_and_export_completed_translations(working_file, final_output)
    else:
        print(f"To run CLI, create '{input_file}' with tags in column A.")
