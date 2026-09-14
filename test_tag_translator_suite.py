import unittest
import os
import io
import json
import base64
import pandas as pd

import CNOOC_mapping as cm
import Scovan_Mapping as sm
import tag_translation_engine as tte


class TestTagTranslatorSuite(unittest.TestCase):

    def test_peng_mappings_exist_and_loaded(self):
        """Verify sensitive PENG mapping dictionaries are loaded."""
        self.assertTrue(hasattr(cm, "sequences"))
        self.assertTrue(hasattr(cm, "component_mapping"))
        self.assertTrue(hasattr(cm, "fluid_code_mapping"))
        self.assertTrue(hasattr(cm, "sequence_number_mapping"))
        self.assertTrue(hasattr(cm, "cable_number_mapping"))

        self.assertTrue(hasattr(sm, "sequences"))
        self.assertTrue(hasattr(sm, "component_mapping"))
        self.assertTrue(hasattr(sm, "fluid_code_mapping"))
        self.assertTrue(hasattr(sm, "cable_number_mapping"))

    def test_ht_line_sequence_decomposition_and_translation(self):
        """Test Scovan HT Line: HT-FG-A100-1."""
        p_sec, u_seq, u_trans, seq_key = tte.decompose_sequence("HT-FG-A100-1")
        self.assertEqual(seq_key, "heat_trace_sequence")
        self.assertEqual(p_sec, ["HT", "FG", "A100", "1"])
        self.assertEqual(u_seq, ["{HT_line}", "{fluid_code}", "{scovan_sequence_number}", "{cable_number}"])

        template, missing = tte.translate_sequence(seq_key, p_sec, u_seq, u_trans)
        self.assertEqual(template, "{plant_name}-ET-FG-{cnooc_sequence_number}-{circuit_identifier}-1")
        self.assertIn("plant_name", missing)
        self.assertIn("cnooc_sequence_number", missing)
        self.assertIn("circuit_identifier", missing)

    def test_fluid_code_translation_bfw_to_bf(self):
        """Test Scovan Boiler Feed Water (BFW) translates to CNOOC BF."""
        p_sec, u_seq, u_trans, seq_key = tte.decompose_sequence("HT-BFW-B205-2")
        template, missing = tte.translate_sequence(seq_key, p_sec, u_seq, u_trans)
        self.assertEqual(template, "{plant_name}-ET-BF-{cnooc_sequence_number}-{circuit_identifier}-2")

    def test_electrical_component_translation(self):
        """Test Scovan MIQ-PJB and HTPK map to CNOOC PWR, RTD to R."""
        # MIQ-PJB
        p1, u1, t1, k1 = tte.decompose_sequence("MIQ-PJB-FG-A100-1")
        self.assertEqual(k1, "heat_trace_component_sequence")
        tmpl1, _ = tte.translate_sequence(k1, p1, u1, t1)
        self.assertEqual(tmpl1, "{plant_name}-ET-FG-{cnooc_sequence_number}-{circuit_identifier}-PWR")

        # HTPK
        p2, u2, t2, k2 = tte.decompose_sequence("HTPK-FG-B200-2")
        self.assertEqual(k2, "heat_trace_component_sequence")
        tmpl2, _ = tte.translate_sequence(k2, p2, u2, t2)
        self.assertEqual(tmpl2, "{plant_name}-ET-FG-{cnooc_sequence_number}-{circuit_identifier}-PWR")

        # RTD
        p3, u3, t3, k3 = tte.decompose_sequence("RTD-FG-C300-1")
        tmpl3, _ = tte.translate_sequence(k3, p3, u3, t3)
        self.assertEqual(tmpl3, "{plant_name}-ET-FG-{cnooc_sequence_number}-{circuit_identifier}-R")

    def test_unidentified_tag(self):
        """Test non-matching tags are captured as unidentified."""
        p, u, t, k = tte.decompose_sequence("COMPLETELY-UNKNOWN-SYNTAX")
        self.assertIsNone(k)

    def test_dump_parsing(self):
        """Test parsing raw text dump."""
        raw_text = """
        HT-FG-A100-1
        MIQ-PJB-BFW-A100-1
        , ,
        HTPK-FG-B200-2
        """
        tags = tte.parse_raw_tag_text(raw_text)
        self.assertEqual(len(tags), 3)
        self.assertEqual(tags[0], "HT-FG-A100-1")

    def test_batch_substitution_and_final_excel(self):
        """Test missing fields substitution and excel export."""
        tags = ["HT-FG-A100-1", "MIQ-PJB-BFW-A100-1"]
        processed = tte.process_tags(tags)
        field_values = {
            "1": {"plant_name": "G02", "circuit_identifier": "CKT01", "cnooc_sequence_number": "A100"},
            "2": {"plant_name": "G02", "circuit_identifier": "CKT02", "cnooc_sequence_number": "A100"},
        }
        finalized = tte.compute_final_translations(processed["records"], field_values)
        self.assertEqual(finalized[0]["client_translation"], "G02-ET-FG-A100-CKT01-1")
        self.assertEqual(finalized[1]["client_translation"], "G02-ET-BF-A100-CKT02-PWR")
        self.assertTrue(finalized[0]["is_complete"])

        # Test Breakout Excel
        breakout_bytes = tte.build_breakout_excel_bytes(finalized)
        self.assertGreater(len(breakout_bytes), 2000)

        # Test Final 2-Column Excel
        final_bytes = tte.build_final_2column_excel_bytes(finalized)
        self.assertGreater(len(final_bytes), 2000)

        # Read back with pandas
        df = pd.read_excel(io.BytesIO(final_bytes))
        self.assertIn("Scovan Tag", df.columns)
        self.assertIn("Final Client Translation", df.columns)
        self.assertEqual(len(df), 2)
        self.assertEqual(df.iloc[0]["Final Client Translation"], "G02-ET-FG-A100-CKT01-1")

    def test_piping_line_compound_spec_decomposition(self):
        """Test tags 114-PE-C1C5-P0101 and 89-S-C1B4-I0102 decompose into dashed tokens with no PE fluid code overlap."""
        # 114-PE-C1C5-P0101
        p_sec1, u_seq1, u_trans1, seq_key1 = tte.decompose_sequence("114-PE-C1C5-P0101")
        self.assertEqual(seq_key1, "piping_line_no_insulation_sequence")
        self.assertEqual(p_sec1, ["114", "PE", "C", "1", "C", "5", "P0101"])
        self.assertEqual(u_seq1[0], "{line_size}")
        self.assertEqual(u_seq1[1], "{fluid_code}")
        self.assertEqual(u_trans1[1], "PRODUCED EMULSION")
        self.assertEqual(u_seq1[2], "{piping_category}")
        self.assertEqual(u_seq1[3], "{piping_material}")
        self.assertEqual(u_seq1[4], "{corrosion_allowance}")
        self.assertEqual(u_seq1[5], "{service_modifier}")
        self.assertEqual(u_seq1[6], "{scovan_sequence_number}")

        # 89-S-C1B4-I0102
        p_sec2, u_seq2, u_trans2, seq_key2 = tte.decompose_sequence("89-S-C1B4-I0102")
        self.assertEqual(seq_key2, "piping_line_no_insulation_sequence")
        self.assertEqual(p_sec2, ["89", "S", "C", "1", "B", "4", "I0102"])

        # Test diagnostics explosion
        diag = tte.analyze_sequence_detection(p_sec1, u_seq1, u_trans1, seq_key1, "114-PE-C1C5-P0101")
        self.assertEqual(diag["status"], "Fully Identified")
        self.assertEqual(diag["matched_count"], 7)

    def test_valve_compound_spec_decomposition(self):
        """Test valve tag 2BF-C1-CA decomposes into dashed tokens."""
        p_sec, u_seq, u_trans, seq_key = tte.decompose_sequence("2BF-C1-CA")
        self.assertEqual(seq_key, "valve_sequence")
        self.assertEqual(p_sec, ["2", "BF", "C", "1", "C", "A"])
        self.assertEqual(u_seq, [
            "{valve_size}",
            "{valve_type}",
            "{class_code}",
            "{end_connection}",
            "{body_material}",
            "{temperature_group}"
        ])

        diag = tte.analyze_sequence_detection(p_sec, u_seq, u_trans, seq_key, "2BF-C1-CA")
        self.assertEqual(diag["status"], "Fully Identified")
        self.assertEqual(diag["matched_count"], 6)
    def test_standalone_instrument_tag_decomposition(self):
        """Test standalone instrument tags using instrument_identification_mapping."""
        tags_to_test = [
            ("FT-1002", "FLOW TRANSMITTER"),
            ("PT-2001", "PRESSURE TRANSMITTER"),
            ("PSH-3001", "PRESSURE SWITCH HIGH"),
            ("ESD-4001", "VOLTAGE (EMF) SHUT DOWN"),
            ("FIC-5001", "FLOW CONTROLLER"),
        ]
        for tag, expected_desc in tags_to_test:
            p_sec, u_seq, u_trans, seq_key = tte.decompose_sequence(tag)
            self.assertIn(seq_key, ("instrument_tag_sequence", "instrument_tag_standalone"), f"Failed key for {tag}")
            self.assertEqual(u_seq, ["{instrument_type}", "{scovan_sequence_number}"])
            self.assertEqual(u_trans[0], expected_desc, f"Failed translation for {tag}")


    def test_piping_line_class_special_compound_mapping(self):
        """Test Scovan compound specs (C1C4, C2C5, A2B1, C1C5, C1B4) map to CNOOC piping line classes."""
        cases = [
            ("114-PE-C1C4-P0101", "4-PE-{cnooc_sequence_number}-CAPC0", ["cnooc_sequence_number"]),
            ("114-PE-C2C5-P0101", "4-PE-{cnooc_sequence_number}-CLPC0", ["cnooc_sequence_number"]),
            ("114-PE-A2B1-P0101", "4-PE-{cnooc_sequence_number}-ALDB0", ["cnooc_sequence_number"]),
            ("114-PG-C1C5-P0103", "4-PG-{cnooc_sequence_number}-CAPC0", ["cnooc_sequence_number"]),
            ("89-S-C1B4-I0102", "3-ST-{cnooc_sequence_number}-ALDB0", ["cnooc_sequence_number"]),
            ("114-PE-C1C6-P0101", "4-PE-{cnooc_sequence_number}-{piping_line_class}", ["cnooc_sequence_number", "piping_line_class"]),
        ]
        for tag, exp_trans, exp_missing in cases:
            p_sec, u_seq, u_trans, seq_key = tte.decompose_sequence(tag)
            trans, missing = tte.translate_sequence(seq_key, p_sec, u_seq, u_trans)
            self.assertEqual(trans, exp_trans)
            self.assertEqual(list(missing.keys()), exp_missing)


    def test_cnooc_valve_mappings(self):
        """Test Scovan valve tags translate directly to CNOOC comparable valve tags."""
        valve_pairs = [
            ("21GA-C4-C5", "GA8410"),
            ("33GA-C4-C5", "GA8410"),
            ("33GA-C4-L8", "GA8610"),
            ("89GA-C1-C5", "GA6400"),
            ("89CH-C1-C5", "CH6400"),
            ("114CH-C1-C5", "CH6400"),
            ("114GA-C1-C5", "GA6400"),
            ("27GA-C4-C5", "GA8410"),
            ("27GA-C4-L8", "GA8610"),
            ("33GA-C3-L8", "GA8600"),
            ("33NE-C2-S50", "TBC"),
            ("33NE-C3-S50", "TBC"),
            ("21BF-A2-LA", "BA6210F"),
            ("27GL-C4-C5", "GL8401"),
            ("168GA-C6-C5", "GA6521"),
            ("60GA-C1-L8", "GA6600"),
            ("60CH-C1-C5", "CH6400"),
            ("60GA-C1-C5", "GA6400"),
            ("33CH-C3-L5", "CH8620"),
            ("33BR-A2-LA", "BA6210"),
        ]
        for tag, expected in valve_pairs:
            p_sec, u_seq, u_trans, seq_key = tte.decompose_sequence(tag)
            self.assertEqual(seq_key, "valve_sequence")
            trans, missing = tte.translate_sequence(seq_key, p_sec, u_seq, u_trans)
            self.assertEqual(trans, expected, f"Failed for {tag}")
            self.assertEqual(len(missing), 0, f"Expected no missing for {tag}")

        # Test unmapped valve fallback
        p_sec, u_seq, u_trans, seq_key = tte.decompose_sequence("99GA-C4-C5")
        trans, missing = tte.translate_sequence(seq_key, p_sec, u_seq, u_trans)
        self.assertEqual(trans, "{CNOOC_valve_sequence}")
        self.assertIn("CNOOC_valve_sequence", missing)


if __name__ == "__main__":
    unittest.main()

