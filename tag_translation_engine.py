from __future__ import annotations

import io
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from openpyxl.utils import get_column_letter

# Import sensitive mapping files verbatim without modification
import CNOOC_mapping as cnooc_mod
import Scovan_Mapping as scovan_mod

def _normalize_scovan_sequences(raw_seqs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Internally normalizes syntax formats so that concatenated tokens like {thing}{thing2}
    become dashed {thing}-{thing2} in our system, avoiding un-dashed sub-string collisions.
    """
    normalized = {}
    for k, v in raw_seqs.items():
        raw_fmt = v.get("syntax_format", "")
        dashed_fmt = re.sub(r"\}\{", "}-{", raw_fmt)
        normalized[k] = {
            **v,
            "syntax_format": dashed_fmt,
            "raw_syntax_format": raw_fmt,
        }
        if "{service_modifier}-" in dashed_fmt:
            no_serv_fmt = dashed_fmt.replace("{service_modifier}-", "")
            normalized[f"{k}_no_modifier"] = {
                **v,
                "syntax_format": no_serv_fmt,
                "alias_of": k,
            }
    return normalized

scovan_sequences = _normalize_scovan_sequences(getattr(scovan_mod, "sequences", {}))
scovan_component_mapping = getattr(scovan_mod, "component_mapping", {})
scovan_fluid_code_mapping = getattr(scovan_mod, "fluid_code_mapping", {})
scovan_cable_number_mapping = getattr(scovan_mod, "cable_number_mapping", {})
scovan_sequence_number_mapping = getattr(
    scovan_mod, "sequence_number_mapping", getattr(scovan_mod, "scovan_sequence_number_mapping", {})
)
scovan_end_connection_mapping = getattr(scovan_mod, "end_connection_mapping", {})
scovan_body_material_mapping = getattr(scovan_mod, "body_material_mapping", {})
scovan_temperature_group_mapping = getattr(scovan_mod, "temperature_group_mapping", {})
scovan_piping_category_mapping = getattr(scovan_mod, "piping_category_mapping", {})
scovan_piping_material_mapping = getattr(scovan_mod, "piping_material_mapping", {})
scovan_corrosion_allowance_mapping = getattr(scovan_mod, "corrosion_allowance_mapping", {})
scovan_service_modifier_mapping = getattr(scovan_mod, "service_modifier_mapping", {})
scovan_class_code_mapping = getattr(scovan_mod, "class_code_mapping", {})
scovan_valve_type_mapping = getattr(scovan_mod, "valve_type_mapping", {})
scovan_instrument_identification_mapping = getattr(scovan_mod, "instrument_identification_mapping", {})
scovan_line_size_mapping = getattr(scovan_mod, "line_size_mapping", {})


def match_instrument_identification(token: str) -> Optional[Tuple[str, str]]:
    """
    Matches an instrument type code against scovan_instrument_identification_mapping.
    Handles:
    - Direct matches and slash alternatives: 'FT' -> 'FLOW TRANSMITTER', 'FC/FIC' -> 'FLOW CONTROLLER'
    - Bracket modifiers: 'PS()' -> 'PRESSURE SWITCH', 'PSH' -> 'PRESSURE SWITCH HIGH', etc.
    """
    if not scovan_instrument_identification_mapping:
        return None

    u = token.upper().strip()

    # 1. Exact match against explicit codes or slashed alternatives
    for desc, code in scovan_instrument_identification_mapping.items():
        if "/" in code:
            if u in [p.strip().upper() for p in code.split("/")]:
                return "{instrument_type}", desc
        else:
            base = code.replace("()", "").strip().upper()
            if u == base or u == code.strip().upper():
                return "{instrument_type}", desc

    # 2. Bracket suffix match: sort by base length descending so longer bases match before shorter ones
    bracket_entries = [
        (desc, code.replace("()", "").strip().upper())
        for desc, code in scovan_instrument_identification_mapping.items()
        if "()" in code
    ]
    bracket_entries.sort(key=lambda x: len(x[1]), reverse=True)

    for desc, base in bracket_entries:
        if u.startswith(base):
            suffix = u[len(base):]
            if suffix and all(ch in "HLD" for ch in suffix):
                suffix_map = {
                    "H": " HIGH",
                    "L": " LOW",
                    "HH": " HIGH-HIGH",
                    "LL": " LOW-LOW",
                    "D": " DIFFERENTIAL",
                }
                clean_desc = desc.replace("()", "").strip()
                return "{instrument_type}", f"{clean_desc}{suffix_map.get(suffix, ' ' + suffix)}"

    return None


# Extract CNOOC mappings
cnooc_sequences = _normalize_scovan_sequences(getattr(cnooc_mod, "sequences", {}))
if "instrument_tag_sequence" in cnooc_sequences and "instrument_tag_standalone" not in cnooc_sequences:
    cnooc_sequences["instrument_tag_standalone"] = cnooc_sequences["instrument_tag_sequence"]
cnooc_component_mapping = getattr(cnooc_mod, "component_mapping", {})
cnooc_fluid_code_mapping = getattr(cnooc_mod, "fluid_code_mapping", {})
cnooc_cable_number_mapping = getattr(cnooc_mod, "cable_number_mapping", {})
cnooc_sequence_number_mapping = getattr(cnooc_mod, "sequence_number_mapping", {})
cnooc_line_size_mapping = getattr(cnooc_mod, "line_size_mapping", {})
cnooc_piping_line_class_mapping = getattr(cnooc_mod, "piping_line_class_mapping", {})
cnooc_valve_mapping = getattr(cnooc_mod, "valve_mapping", getattr(cnooc_mod, "CNOOC_valve_sequence_mapping", {}))
cnooc_instrument_identification_mapping = getattr(
    cnooc_mod, "instrument_identification_mapping", getattr(cnooc_mod, "cnooc_instrument_identification_mapping", {})
)

# Semantic alias bridging: Scovan token labels <-> CNOOC token labels
# This satisfies the requirement that data transformations are performed outside the mapping files.
LABEL_BRIDGES = {
    "{scovan_sequence_number}": "{sequence_number}",
    "{sequence_number}": "{scovan_sequence_number}",
}


def _match_value_in_mapping(token: str, mapping_obj: Any) -> Optional[Tuple[str, str]]:
    """
    Recursively checks if a token matches keys, values, or regex in a mapping dictionary.
    Returns a tuple of (syntax_label, translated_meaning) or None.
    """
    if not isinstance(mapping_obj, dict):
        return None

    if "name" not in mapping_obj:
        for sub_map in mapping_obj.values():
            if isinstance(sub_map, dict):
                match = _match_value_in_mapping(token, sub_map)
                if match:
                    return match
        return None

    syntax_label = mapping_obj.get("name")

    for k, v in mapping_obj.items():
        if k in ("name", "keep_scovan"):
            continue

        # Regex pattern (e.g. sequence number or cable number)
        if isinstance(v, str) and (v.startswith("^") or "$" in v):
            if re.match(v, token):
                return (syntax_label, token)
            # Support numeric or alphanumeric sequence numbers (e.g. 1002, A100, P0101)
            if syntax_label in ("{scovan_sequence_number}", "{sequence_number}") and re.match(r"^[A-Za-z]{0,2}\d{3,5}[A-Za-z]?$", token):
                return (syntax_label, f"Sequence Number {token}")

        # Exact match to value or key
        if token == v:
            return (syntax_label, str(k))

        if token == k:
            return (syntax_label, str(v))

    return None


def _lookup_client_token(syntax_label: str, universal_meaning: str, raw_scovan_val: str, mapping_obj: Any) -> Optional[str]:
    """
    Looks up client code. If keep_scovan is True and valid, keeps original Scovan token.
    Otherwise, translates universal meaning to the client's specific short code.
    """
    if not isinstance(mapping_obj, dict):
        return None

    if "name" not in mapping_obj:
        for sub_map in mapping_obj.values():
            if isinstance(sub_map, dict):
                res = _lookup_client_token(syntax_label, universal_meaning, raw_scovan_val, sub_map)
                if res:
                    return res
        return None

    if str(mapping_obj.get("name", "")).lower() != str(syntax_label).lower():
        return None

    if mapping_obj.get("keep_scovan", False):
        regex_pat = mapping_obj.get(syntax_label.strip("{}"))
        if regex_pat and isinstance(regex_pat, str) and (regex_pat.startswith("^") or "$" in regex_pat):
            if re.match(regex_pat, str(raw_scovan_val)):
                return str(raw_scovan_val)
        return str(raw_scovan_val)

    # For fluid code and line size mapping: keys are CNOOC codes ('FG', '4'), values are meanings ('FUEL GAS', '114mm')
    if syntax_label in ("{fluid_code}", "{line_size}"):
        for k, v in mapping_obj.items():
            if k in ("name", "keep_scovan"):
                continue
            clean_v = str(v).upper().replace("MM", "").strip()
            clean_meaning = str(universal_meaning).upper().replace("MM", "").strip()
            clean_raw = str(raw_scovan_val).upper().replace("MM", "").strip()
            if clean_meaning in (str(v).upper(), clean_v):
                return str(k)
            if clean_raw in (str(v).upper(), clean_v, str(k).upper()):
                return str(k)
            if universal_meaning.upper() == str(k).upper():
                return str(k)
        return None

    if syntax_label == "{piping_line_class}":
        for k, v in mapping_obj.items():
            if k in ("name", "keep_scovan"):
                continue
            raw_upper = str(raw_scovan_val).upper().replace("-", "").strip()
            if raw_upper == str(k).upper():
                return str(v)
            if raw_upper == str(v).upper():
                return str(k)
        return None

    if syntax_label.lower() in ("{cnooc_valve_sequence}", "{valve_sequence}"):
        raw_upper = str(raw_scovan_val).upper().strip().rstrip("#")
        for k, v in mapping_obj.items():
            if k in ("name", "keep_scovan"):
                continue
            if raw_upper == str(k).upper().strip().rstrip("#"):
                return str(v)
            if raw_upper == str(v).upper().strip().rstrip("#"):
                return str(k)
        return None

    if syntax_label.lower() == "{instrument_type}":
        clean_meaning = str(universal_meaning).upper().strip()
        clean_raw = str(raw_scovan_val).upper().strip()

        # 1. Match by universal meaning (description)
        for k, v in mapping_obj.items():
            if k in ("name", "keep_scovan"):
                continue
            clean_k = str(k).upper().strip()
            clean_v = str(v).replace("()", "").strip().upper()
            if clean_meaning == clean_k:
                return clean_v
            # Handle bracket suffixes in meaning like "HAND SWITCH HIGH" -> "HSH"
            if "()" in str(v) and clean_meaning.startswith(clean_k):
                suffix_part = clean_meaning[len(clean_k):].strip()
                suffix_letters = {"HIGH": "H", "LOW": "L", "HIGH-HIGH": "HH", "LOW-LOW": "LL", "DIFFERENTIAL": "D"}
                s_code = suffix_letters.get(suffix_part, suffix_part)
                return f"{clean_v}{s_code}"

        # 2. Match by raw code (if meaning was generic or matched directly)
        for k, v in mapping_obj.items():
            if k in ("name", "keep_scovan"):
                continue
            clean_v = str(v).replace("()", "").strip().upper()
            if clean_raw == clean_v or clean_raw == str(v).strip().upper():
                return clean_v

        return None

    # For component mappings: keys are descriptions ('PWR Kit'), values are CNOOC codes ('PWR')
    for k, v in mapping_obj.items():
        if k in ("name", "keep_scovan"):
            continue

        if universal_meaning.upper() == str(k).upper():
            return str(v)

        if universal_meaning.upper() == str(v).upper():
            return str(v)

        if str(raw_scovan_val).upper() == str(v).upper():
            return str(v)

    return None


def _get_single_hardcoded_default(syntax_label: str, mapping_obj: Any) -> Optional[str]:
    """
    Checks if a mapping object has exactly one concrete static value.
    """
    if not isinstance(mapping_obj, dict):
        return None

    if "name" not in mapping_obj:
        for sub_map in mapping_obj.values():
            if isinstance(sub_map, dict):
                val = _get_single_hardcoded_default(syntax_label, sub_map)
                if val:
                    return val
        return None

    if mapping_obj.get("name") == syntax_label:
        entries = {k: v for k, v in mapping_obj.items() if k not in ("name", "keep_scovan")}
        if len(entries) == 1:
            _, val = next(iter(entries.items()))
            if isinstance(val, str) and not (val.startswith("^") or "$" in val):
                return str(val)
    return None


def identify_sequence_type(universal_sequence: List[str], sequences_mapping: Dict[str, Any] = scovan_sequences) -> Optional[str]:
    """
    Joins the universal sequence list and checks for a matching syntax_format.
    """
    reconstructed_syntax = "-".join(universal_sequence)
    for seq_key, seq_data in sequences_mapping.items():
        if seq_data.get("syntax_format") == reconstructed_syntax:
            return seq_data.get("alias_of", seq_key)
    return None


def expand_tag_internal_dashes(tag: str) -> List[str]:
    """
    Splits a tag by '-' and expands compound blocks like piping spec C1C5 or valve 2BF-C1-CA
    into individual tokens with internal dashes, preventing un-dashed collisions like 'PE'.
    """
    clean_tag = tag.strip().rstrip("#")
    raw_tokens = [t.strip().rstrip("#") for t in clean_tag.split("-") if t.strip()]

    # 3-segment valve structure check (e.g. 2BF-C1-CA)
    if len(raw_tokens) == 3:
        m1 = re.match(r"^(\d+(?:/\d+)?|\d+\.\d+)([A-Za-z]{2})$", raw_tokens[0])
        m2 = re.match(r"^([A-Fa-f])(\d{1,2})$", raw_tokens[1])
        m3 = re.match(r"^([A-Za-z])([A-Za-z]|\d{1,2})$", raw_tokens[2])
        if m1 and m2 and m3:
            vsize, vtype = m1.groups()
            cc, ec = m2.groups()
            bm, tg = m3.groups()
            if (vtype.upper() in scovan_valve_type_mapping and
                cc.upper() in scovan_class_code_mapping and ec in scovan_end_connection_mapping and
                bm.upper() in scovan_body_material_mapping and tg.upper() in scovan_temperature_group_mapping):
                return [vsize, vtype.upper(), cc.upper(), ec, bm.upper(), tg.upper()]

    expanded: List[str] = []
    for tok in raw_tokens:
        # Compound piping spec check: Category + Material + Corrosion + optional Service Modifier
        m = re.match(r"^([A-Za-z])(\d{1,2})([A-Za-z])(\d{1,2})?$", tok)
        if m:
            c, mat, corr, serv = m.groups()
            if (c.upper() in scovan_piping_category_mapping and
                mat in scovan_piping_material_mapping and
                corr.upper() in scovan_corrosion_allowance_mapping and
                (serv is None or serv in scovan_service_modifier_mapping)):
                expanded.extend([c.upper(), mat, corr.upper()])
                if serv:
                    expanded.append(serv)
                continue
        expanded.append(tok)
    return expanded



WORD_ADDER_PATTERNS = [
    r'(\s*[(][^)]*[)]\s*)$',
    r'(\s*[-–—:]?\s*(?:(?:PLEASE\s+)?SEE\b|TO\b|FROM\b|NOTE\b|REF\b|CONT\b|TYP\b).*)$',
]

PREFIX_ADDER_PATTERNS = [
    r'^([(][^)]*[)]\s*[-–—:]?\s*)',
    r'^((?:(?:PLEASE\s+)?SEE\b|TO\b|FROM\b|NOTE\b|REF\b|CONT\b|TYP\b).*?(?::\s*|\s+[-–—]\s*))',
]

PREFIX_WORD_RE = re.compile(r'^(?:(?:PLEASE\s+)?SEE|TO|FROM|NOTE|REF|CONT|TYP)\b', re.IGNORECASE)


def _decompose_sequence_direct(
    sequence_string: str,
    mapping_sources: Optional[List[Dict[str, Any]]] = None,
    sequences_mapping: Dict[str, Any] = scovan_sequences,
) -> Tuple[List[str], List[str], List[str], Optional[str]]:
    """
    Directly splits a tag string by '-' and matches individual tokens against Scovan mappings.
    """
    if mapping_sources is None:
        mapping_sources = [
            scovan_component_mapping,
            scovan_fluid_code_mapping,
            scovan_cable_number_mapping,
            scovan_sequence_number_mapping,
            scovan_end_connection_mapping,
            scovan_body_material_mapping,
            scovan_temperature_group_mapping,
            scovan_piping_category_mapping,
            scovan_piping_material_mapping,
            scovan_corrosion_allowance_mapping,
            scovan_service_modifier_mapping,
            scovan_class_code_mapping,
            scovan_valve_type_mapping,
            scovan_line_size_mapping,
        ]

    tokens = expand_tag_internal_dashes(sequence_string)
    n = len(tokens)

    parsed_sections: List[str] = []
    universal_sequence: List[str] = []
    universal_translation: List[str] = []

    is_piping = (n >= 5 and re.match(r"^\d+(?:\.\d+)?(?:/\d+)?\"?$", tokens[0]) and tokens[1] in scovan_fluid_code_mapping)
    is_valve = (n == 6 and re.match(r"^\d+(?:/\d+)?|\d+\.\d+$", tokens[0]) and tokens[1].upper() in scovan_valve_type_mapping)

    i = 0
    while i < n:
        tok = tokens[i]

        if is_piping and i == 0:
            parsed_sections.append(tok)
            universal_sequence.append("{line_size}")
            meaning = scovan_line_size_mapping.get(tok, f"{tok}mm" if tok.isdigit() else f"{tok} mm/NPS Line Size")
            universal_translation.append(meaning)
            i += 1
            continue

        if is_piping and i == 1:
            parsed_sections.append(tok)
            universal_sequence.append("{fluid_code}")
            universal_translation.append(scovan_fluid_code_mapping.get(tok, tok))
            i += 1
            continue

        if is_piping and i == 2:
            cat_val = scovan_piping_category_mapping.get(tok.upper())
            cat_str = list(cat_val)[0] if isinstance(cat_val, (set, list, tuple)) else str(cat_val)
            parsed_sections.append(tok)
            universal_sequence.append("{piping_category}")
            universal_translation.append(f"ASME Class {cat_str}")
            i += 1
            continue

        if is_piping and i == 3:
            parsed_sections.append(tok)
            universal_sequence.append("{piping_material}")
            universal_translation.append(scovan_piping_material_mapping.get(tok, tok))
            i += 1
            continue

        if is_piping and i == 4:
            parsed_sections.append(tok)
            universal_sequence.append("{corrosion_allowance}")
            corr_val = scovan_corrosion_allowance_mapping.get(tok.upper(), tok)
            universal_translation.append(f"{corr_val} Corrosion Allowance")
            i += 1
            continue

        if is_piping and i == 5 and tok in scovan_service_modifier_mapping and (i + 1 < n and re.match(r"^[A-Za-z]{1,2}\d{3,5}$", tokens[i + 1])):
            parsed_sections.append(tok)
            universal_sequence.append("{service_modifier}")
            universal_translation.append(scovan_service_modifier_mapping.get(tok, tok))
            i += 1
            continue

        if is_valve:
            valve_labels = ["{valve_size}", "{valve_type}", "{class_code}", "{end_connection}", "{body_material}", "{temperature_group}"]
            lbl = valve_labels[i]
            parsed_sections.append(tok)
            universal_sequence.append(lbl)
            if lbl == "{valve_size}":
                universal_translation.append(f'{tok}" NPS')
            elif lbl == "{valve_type}":
                universal_translation.append(scovan_valve_type_mapping.get(tok.upper(), tok))
            elif lbl == "{class_code}":
                universal_translation.append(f"Class {scovan_class_code_mapping.get(tok.upper(), tok)}")
            elif lbl == "{end_connection}":
                universal_translation.append(scovan_end_connection_mapping.get(tok, tok))
            elif lbl == "{body_material}":
                universal_translation.append(scovan_body_material_mapping.get(tok.upper(), tok))
            elif lbl == "{temperature_group}":
                universal_translation.append(scovan_temperature_group_mapping.get(tok.upper(), tok))
            i += 1
            continue

        # Insulation spec or ET following scovan_sequence_number
        if i >= 3 and universal_sequence and universal_sequence[-1] == "{scovan_sequence_number}":
            if tok.upper() == "ET":
                parsed_sections.append(tok)
                universal_sequence.append("ET")
                universal_translation.append("Electric Heat Trace")
                i += 1
                continue
            elif re.match(r"^[A-Za-z]{1,3}\d{1,3}$", tok):
                parsed_sections.append(tok)
                universal_sequence.append("{insulation_spec}")
                universal_translation.append(f"Insulation ({tok})")
                i += 1
                continue

        if i >= 4 and universal_sequence and universal_sequence[-1] == "{insulation_spec}" and tok.upper() == "ET":
            parsed_sections.append(tok)
            universal_sequence.append("ET")
            universal_translation.append("Electric Heat Trace")
            i += 1
            continue

        # Standalone instrument tag check: {instrument_type}-{scovan_sequence_number}
        if i == 0 and n >= 2:
            inst_match = match_instrument_identification(tok)
            seq_match = _match_value_in_mapping(tokens[i + 1], scovan_sequence_number_mapping)
            if inst_match and seq_match:
                parsed_sections.append(tok)
                universal_sequence.append(inst_match[0])
                universal_translation.append(inst_match[1])
                i += 1
                continue
            elif n == 2 and re.match(r"^[A-Z]{2,5}$", tok) and seq_match:
                parsed_sections.append(tok)
                universal_sequence.append("{instrument_type}")
                universal_translation.append(f"Instrument Type ({tok})")
                i += 1
                continue

        # Multi-token / greedy match from mapping sources
        matched = False
        for j in range(n, i, -1):
            candidate = "-".join(tokens[i:j])
            for mapping in mapping_sources:
                if i == 0 and mapping is scovan_cable_number_mapping:
                    continue
                match_result = _match_value_in_mapping(candidate, mapping)
                if match_result:
                    label, translation = match_result
                    parsed_sections.append(candidate)
                    universal_sequence.append(label)
                    universal_translation.append(translation)
                    i = j
                    matched = True
                    break
            if matched:
                break

        if not matched:
            parsed_sections.append(tokens[i])
            universal_sequence.append("unknown")
            universal_translation.append("unknown")
            i += 1

    matched_sequence_key = identify_sequence_type(universal_sequence, sequences_mapping)

    return parsed_sections, universal_sequence, universal_translation, matched_sequence_key


def resolve_tag_with_adders(
    raw_tag: str,
    mapping_sources: Optional[List[Dict[str, Any]]] = None,
    sequences_mapping: Dict[str, Any] = scovan_sequences,
) -> Tuple[str, str, str, List[str], List[str], List[str], Optional[str]]:
    """
    Identifies if a tag matches a known Scovan sequence directly or via adders
    (such as appended '-1', '-01', '-A', or prefix/suffix words like 'TO P-101', 'FROM WELLHEAD',
    'PLEASE SEE DWG-002', '(TO PUMP)', '(TYP)', etc.).

    Returns:
        (core_tag, prefix_adder, suffix_adder, parsed_sections, universal_sequence, universal_translation, matched_sequence_key)
    """
    clean = raw_tag.strip().strip('"\'')
    if not clean:
        return clean, "", "", [], [], [], None

    # 1. Direct match on clean tag
    p, u, tr, k = _decompose_sequence_direct(clean, mapping_sources, sequences_mapping)
    if k is not None:
        return clean, "", "", p, u, tr, k

    # 2. Extract prefix or suffix word annotations
    prefix_adder = ""
    suffix_adder = ""
    work_tag = clean

    for pat in PREFIX_ADDER_PATTERNS:
        m = re.match(pat, work_tag, re.IGNORECASE)
        if m:
            prefix_adder = m.group(1)
            work_tag = work_tag[m.end():].strip()
            break

    while True:
        matched_suff = False
        for pat in WORD_ADDER_PATTERNS:
            m = re.search(pat, work_tag, re.IGNORECASE)
            if m and m.start() > 0:
                suffix_adder = m.group(1) + suffix_adder
                work_tag = work_tag[:m.start()].strip()
                matched_suff = True
                break
        if not matched_suff:
            break

    # Strip leftover trailing / leading separators
    work_tag = re.sub(r"[\s:\-–—]+$", "", work_tag).strip()
    work_tag = re.sub(r"^[\s:\-–—]+", "", work_tag).strip()

    # If work_tag starts with a word adder keyword without delimiter (e.g. 'TO P-101 114-PE-...')
    if PREFIX_WORD_RE.match(work_tag):
        words = work_tag.split()
        if len(words) >= 2:
            for cut in range(1, len(words)):
                pre_cand = " ".join(words[:cut])
                post_cand = " ".join(words[cut:])
                p_c, u_c, tr_c, k_c = _decompose_sequence_direct(post_cand, mapping_sources, sequences_mapping)
                if k_c is not None:
                    prefix_adder = prefix_adder + pre_cand + " "
                    work_tag = post_cand
                    return work_tag, prefix_adder, suffix_adder, p_c, u_c, tr_c, k_c
                dash_parts = [part for part in post_cand.split("-") if part.strip()]
                for dcut in range(len(dash_parts) - 1, 0, -1):
                    sub_cand = "-".join(dash_parts[:dcut])
                    sub_trail = "-" + "-".join(dash_parts[dcut:])
                    p_c, u_c, tr_c, k_c = _decompose_sequence_direct(sub_cand, mapping_sources, sequences_mapping)
                    if k_c is not None:
                        prefix_adder = prefix_adder + pre_cand + " "
                        return sub_cand, prefix_adder, sub_trail + suffix_adder, p_c, u_c, tr_c, k_c

    # Check if work_tag matches directly after word extraction
    p, u, tr, k = _decompose_sequence_direct(work_tag, mapping_sources, sequences_mapping)
    if k is not None:
        return work_tag, prefix_adder, suffix_adder, p, u, tr, k

    # 3. Check for dash-separated trailing adders (e.g. -1, -01, -A, etc.)
    dash_parts = [part for part in work_tag.split("-") if part.strip()]
    for cut in range(len(dash_parts) - 1, 0, -1):
        cand = "-".join(dash_parts[:cut])
        trail = "-" + "-".join(dash_parts[cut:])
        p_c, u_c, tr_c, k_c = _decompose_sequence_direct(cand, mapping_sources, sequences_mapping)
        if k_c is not None:
            full_suffix = trail + suffix_adder
            return cand, prefix_adder, full_suffix, p_c, u_c, tr_c, k_c

    # If still unmatched, return clean tag with direct decomposition
    p, u, tr, k = _decompose_sequence_direct(clean, mapping_sources, sequences_mapping)
    return clean, "", "", p, u, tr, None


def decompose_sequence(
    sequence_string: str,
    mapping_sources: Optional[List[Dict[str, Any]]] = None,
    sequences_mapping: Dict[str, Any] = scovan_sequences,
    allow_adders: bool = True,
) -> Tuple[List[str], List[str], List[str], Optional[str]]:
    """
    Splits a tag string by '-' and matches individual tokens separated by dashes,
    relying on internally dashed syntax formats ({thing}-{thing2}).
    Supports recognizing tags with adders (such as '-1' or word notes) when allow_adders=True.
    """
    if allow_adders:
        core_tag, pre, suff, p_sec, u_seq, u_trans, seq_key = resolve_tag_with_adders(
            sequence_string, mapping_sources, sequences_mapping
        )
        return p_sec, u_seq, u_trans, seq_key

    return _decompose_sequence_direct(sequence_string, mapping_sources, sequences_mapping)


def translate_sequence(
    sequence_key: str,
    parsed_sections: List[str],
    universal_sequence: List[str],
    universal_translation: List[str],
    client_sequences: Dict[str, Any] = cnooc_sequences,
    client_mappings: Optional[List[Dict[str, Any]]] = None,
    prefix_adder: str = "",
    suffix_adder: str = "",
) -> Tuple[str, Dict[str, str]]:
    """
    Translates a decomposed Scovan sequence into the client (CNOOC) syntax.
    Returns (template_with_placeholders, missing_fields_dict).
    """
    if client_mappings is None:
        client_mappings = [
            cnooc_component_mapping,
            cnooc_fluid_code_mapping,
            cnooc_line_size_mapping,
            cnooc_piping_line_class_mapping,
            cnooc_valve_mapping,
            cnooc_instrument_identification_mapping,
            cnooc_cable_number_mapping,
            cnooc_sequence_number_mapping,
        ]

    target_entry = client_sequences.get(sequence_key)
    if not target_entry and sequence_key == "instrument_tag_standalone":
        target_entry = client_sequences.get("instrument_tag_sequence")
    if not target_entry:
        scovan_name = scovan_sequences.get(sequence_key, {}).get("name", sequence_key)
        return f"[Pending CNOOC Mapping for {scovan_name}]", {}

    target_syntax = re.sub(r"\}\{", "}-{", target_entry.get("syntax_format", ""))

    extracted_meanings: Dict[str, str] = {}
    extracted_raw: Dict[str, str] = {}
    for raw_sec, label, val in zip(parsed_sections, universal_sequence, universal_translation):
        if label != "unknown":
            extracted_meanings[label] = val
            extracted_raw[label] = raw_sec

            # Bridge alias label if applicable (e.g. scovan_sequence_number <-> sequence_number)
            bridged_label = LABEL_BRIDGES.get(label)
            if bridged_label and bridged_label not in extracted_meanings:
                extracted_meanings[bridged_label] = val
                extracted_raw[bridged_label] = raw_sec

    # Synthesize compound piping specification: {piping_category}{piping_material}{corrosion_allowance}{service_modifier}
    compound_piping_spec = (
        f"{extracted_raw.get('{piping_category}', '')}"
        f"{extracted_raw.get('{piping_material}', '')}"
        f"{extracted_raw.get('{corrosion_allowance}', '')}"
        f"{extracted_raw.get('{service_modifier}', '')}"
    ).strip()
    if compound_piping_spec:
        extracted_raw["{piping_line_class}"] = compound_piping_spec
        extracted_meanings["{piping_line_class}"] = compound_piping_spec

    # Reconstruct Scovan valve tag if sequence is valve_sequence
    reconstructed_valve_tag = ""
    if sequence_key == "valve_sequence" and len(parsed_sections) >= 6:
        reconstructed_valve_tag = f"{parsed_sections[0]}{parsed_sections[1]}-{parsed_sections[2]}{parsed_sections[3]}-{parsed_sections[4]}{parsed_sections[5]}"
    elif sequence_key == "valve_sequence" and len(parsed_sections) >= 3:
        reconstructed_valve_tag = "-".join(parsed_sections)

    if reconstructed_valve_tag:
        for v_lbl in ("{CNOOC_valve_sequence}", "{cnooc_valve_sequence}"):
            extracted_raw[v_lbl] = reconstructed_valve_tag
            extracted_meanings[v_lbl] = reconstructed_valve_tag

    client_tokens = target_syntax.split("-")
    client_universal_list = [f"{{{t.strip('{}')}}}" if not t.startswith("{") else t for t in client_tokens]

    translated_tokens: List[str] = []
    missing_fields: Dict[str, str] = {}

    for raw_token, u_label in zip(client_tokens, client_universal_list):
        field_name = u_label.strip("{}")

        # Static literal tokens without brackets
        if not raw_token.startswith("{") and not raw_token.endswith("}"):
            translated_tokens.append(raw_token)
            continue

        # Case 1: Matched from source tag (direct or bridged)
        lookup_label = u_label
        if lookup_label not in extracted_meanings and LABEL_BRIDGES.get(u_label) in extracted_meanings:
            lookup_label = LABEL_BRIDGES[u_label]

        if lookup_label in extracted_meanings:
            meaning = extracted_meanings[lookup_label]
            raw_scovan_val = extracted_raw[lookup_label]
            client_code = None

            for mapping in client_mappings:
                client_code = _lookup_client_token(u_label, meaning, raw_scovan_val, mapping)
                if client_code:
                    break

            if client_code:
                translated_tokens.append(str(client_code))
            elif u_label in ("{piping_line_class}", "{CNOOC_valve_sequence}", "{cnooc_valve_sequence}", "{instrument_type}"):
                translated_tokens.append(f"{{{field_name}}}")
                missing_fields[field_name] = ""
            else:
                val_to_insert = str(meaning)
                translated_tokens.append(val_to_insert)

        # Case 2: Missing from source tag -> check for static hardcoded default
        else:
            default_match = None
            for mapping in client_mappings:
                default_match = _get_single_hardcoded_default(u_label, mapping)
                if default_match:
                    break

            if default_match:
                translated_tokens.append(default_match)
            else:
                translated_tokens.append(f"{{{field_name}}}")
                missing_fields[field_name] = ""

    core_client_sequence = "-".join(translated_tokens)
    final_client_sequence = f"{prefix_adder}{core_client_sequence}{suffix_adder}"
    return final_client_sequence, missing_fields


def parse_raw_tag_text(text: str) -> List[str]:
    """
    Parses pasted text (multi-line, tab/comma separated) and extracts tag candidates.
    Skips common header titles.
    """
    tags: List[str] = []
    lines = text.strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Split by tabs or commas if present
        tokens = [t.strip().strip('"\'') for t in re.split(r"[\t,]+", line) if t.strip()]
        if not tokens:
            continue
        first_token = tokens[0]
        if first_token.lower() in ("tag", "tags", "scovan tag", "sequence", "sequences", "scovan", "client tag mapping"):
            continue
        tags.append(first_token)
    return tags


def parse_spreadsheet_bytes(file_bytes: bytes, filename: str) -> List[str]:
    """
    Parses uploaded Excel (.xlsx, .xls) or CSV bytes and returns the tag list.
    """
    bio = io.BytesIO(file_bytes)
    fn_lower = filename.lower()

    if fn_lower.endswith(".csv"):
        df = pd.read_csv(bio, header=None)
    else:
        df = pd.read_excel(bio, header=None)

    if df.empty:
        return []

    # Detect header row vs raw data
    first_cell = str(df.iloc[0, 0]).strip().lower()
    start_row = 1 if first_cell in ("tag", "tags", "scovan tag", "sequence", "sequences", "scovan") else 0

    tags: List[str] = []
    for val in df.iloc[start_row:, 0]:
        val_str = str(val).strip()
        if val_str and val_str.lower() != "nan":
            tags.append(val_str)
    return tags


def parse_spreadsheet_file(filepath: str) -> List[str]:
    """
    Reads local spreadsheet file.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Spreadsheet file not found: {filepath}")

    if filepath.lower().endswith(".csv"):
        df = pd.read_csv(filepath, header=None)
    else:
        df = pd.read_excel(filepath, header=None)

    first_col = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
    if not first_col:
        return []

    if first_col[0].lower() in ("tag", "tags", "scovan tag", "sequence", "sequences", "scovan"):
        first_col = first_col[1:]

    return [t for t in first_col if t]


def analyze_sequence_detection(
    p_sec: List[str],
    u_seq: List[str],
    u_trans: List[str],
    seq_key: Optional[str],
    tag: str,
    sequences_mapping: Dict[str, Any] = scovan_sequences,
) -> Dict[str, Any]:
    """
    Produces detailed diagnostic and exploded breakdown data for debugging tags,
    especially when no full sequence could be matched.
    """
    total_sections = len(p_sec)
    sections_breakdown = []
    matched_sections_count = 0

    for idx, (raw_token, label, trans) in enumerate(zip(p_sec, u_seq, u_trans)):
        is_matched = label != "unknown"
        if is_matched:
            matched_sections_count += 1

        sub_sections = None

        # Check why it might have failed if unknown
        failure_hint = None
        if not is_matched:
            # Check if it was close to a compound piping spec
            m_spec = re.match(r"^([A-Za-z])(\d{1,2})([A-Za-z])(\d{1,2})?$", raw_token)
            if m_spec:
                c, m_code, corr, s_code = m_spec.groups()
                spec_failures = []
                if c.upper() not in scovan_piping_category_mapping:
                    spec_failures.append(f"Category '{c}' not in piping_category_mapping")
                if m_code not in scovan_piping_material_mapping:
                    spec_failures.append(f"Material '{m_code}' not in piping_material_mapping")
                if corr.upper() not in scovan_corrosion_allowance_mapping:
                    spec_failures.append(f"Corrosion '{corr}' not in corrosion_allowance_mapping")
                if s_code and s_code not in scovan_service_modifier_mapping:
                    spec_failures.append(f"Service Modifier '{s_code}' not in service_modifier_mapping")
                if spec_failures:
                    failure_hint = "Piping spec syntax, but: " + "; ".join(spec_failures)

            if not failure_hint:
                # Check if it looks like a sequence number but failed regex
                if re.match(r"^\d+$", raw_token) or re.search(r"\d{3,}", raw_token):
                    failure_hint = "Resembles sequence number, but did not match regex ^[A-Za-z]{1,2}\\d{3,5}$"
                elif any(ch in raw_token for ch in ("#", "/", "\\", "@", "$", "*")):
                    failure_hint = f"Contains special character ({[ch for ch in ('#', '/', '@') if ch in raw_token]})"
                else:
                    failure_hint = "Value not found in Scovan mapping dictionaries or syntax rules"

        sections_breakdown.append({
            "index": idx + 1,
            "token": raw_token,
            "label": label,
            "meaning": trans,
            "is_matched": is_matched,
            "failure_hint": failure_hint,
            "sub_sections": sub_sections,
        })

    reconstructed_syntax = "-".join(u_seq)

    # Find closest known sequence candidate if not matched
    closest_candidate = None
    best_overlap_score = -1

    for s_key, s_data in sequences_mapping.items():
        fmt = s_data.get("syntax_format", "")
        fmt_tokens = fmt.split("-")
        # Position matching score
        pos_matches = sum(1 for a, b in zip(u_seq, fmt_tokens) if a == b and a != "unknown")
        # Set matching score
        set_matches = sum(1 for a in u_seq if a != "unknown" and a in fmt_tokens)
        score = pos_matches * 2 + set_matches

        if score > best_overlap_score:
            best_overlap_score = score
            mismatches = []
            max_len = max(len(u_seq), len(fmt_tokens))
            for p_idx in range(max_len):
                curr_lbl = u_seq[p_idx] if p_idx < len(u_seq) else "(missing)"
                curr_tok = p_sec[p_idx] if p_idx < len(p_sec) else ""
                exp_lbl = fmt_tokens[p_idx] if p_idx < len(fmt_tokens) else "(extra)"
                if curr_lbl != exp_lbl:
                    if curr_tok:
                        mismatches.append(f"Position {p_idx + 1} ('{curr_tok}'): Expected {exp_lbl}, got {curr_lbl}")
                    else:
                        mismatches.append(f"Position {p_idx + 1}: Expected {exp_lbl}, but tag ended early")

            closest_candidate = {
                "sequence_key": s_key,
                "sequence_name": s_data.get("name", s_key),
                "syntax_format": fmt,
                "expected_tokens_count": len(fmt_tokens),
                "mismatches": mismatches,
                "match_percentage": round((pos_matches / max(1, len(fmt_tokens))) * 100),
            }

    if seq_key:
        diagnostic_status = "Fully Identified"
        summary_note = f"All {total_sections} section(s) matched format for '{sequences_mapping.get(seq_key, {}).get('name', seq_key)}'."
    elif matched_sections_count > 0:
        diagnostic_status = "Partial Match (Broken Sequence)"
        closest_name = closest_candidate["sequence_name"] if closest_candidate else "Unknown"
        summary_note = (
            f"Detected {matched_sections_count} of {total_sections} section(s). "
            f"Closest template is '{closest_name}' ({closest_candidate['match_percentage']}% match)."
            if closest_candidate
            else f"Detected {matched_sections_count} of {total_sections} section(s)."
        )
    else:
        diagnostic_status = "Completely Unrecognized"
        summary_note = f"None of the {total_sections} section(s) in this tag matched any Scovan rule."

    return {
        "status": diagnostic_status,
        "matched_count": matched_sections_count,
        "total_count": total_sections,
        "reconstructed_syntax": reconstructed_syntax,
        "sections": sections_breakdown,
        "closest_candidate": closest_candidate,
        "summary_note": summary_note,
    }


def process_tags(tags: List[str]) -> Dict[str, Any]:
    """
    Processes a list of Scovan tags: decomposes them, determines sequences,
    calculates translations and missing fields, and returns structured data for UI.
    """
    records: List[Dict[str, Any]] = []
    category_counts: Dict[str, int] = {}
    all_missing_field_names: set[str] = set()

    for idx, tag in enumerate(tags):
        core_tag, prefix_adder, suffix_adder, p_sec, u_seq, u_trans, seq_key = resolve_tag_with_adders(tag)

        has_adder = bool(prefix_adder or suffix_adder)
        raw_adder = (prefix_adder + suffix_adder).strip()

        if not seq_key:
            seq_category = "unidentified_sequences"
            category_title = "Unidentified Sequence"
            final_translation = "N/A"
            missing_info: Dict[str, str] = {}
        else:
            seq_category = seq_key
            seq_meta = scovan_sequences.get(seq_key, {})
            category_title = seq_meta.get("name", seq_key.replace("_", " ").title())
            final_translation, missing_info = translate_sequence(
                seq_key,
                p_sec,
                u_seq,
                u_trans,
                cnooc_sequences,
                prefix_adder=prefix_adder,
                suffix_adder=suffix_adder,
            )

        category_counts[seq_category] = category_counts.get(seq_category, 0) + 1
        for field in missing_info.keys():
            all_missing_field_names.add(field)

        # Generate exploded debug diagnostics on core_tag
        diagnostics = analyze_sequence_detection(p_sec, u_seq, u_trans, seq_key, core_tag)
        if has_adder and seq_key:
            diagnostics["summary_note"] += f" (Adder detected & preserved: '{raw_adder}')"

        records.append({
            "id": idx + 1,
            "scovan_tag": tag,
            "core_tag": core_tag,
            "has_adder": has_adder,
            "adder": raw_adder,
            "prefix_adder": prefix_adder,
            "suffix_adder": suffix_adder,
            "sequence_key": seq_category,
            "sequence_name": category_title,
            "parsed_sections": p_sec,
            "universal_sequence": u_seq,
            "universal_translation": u_trans,
            "template_translation": final_translation,
            "client_translation": final_translation,
            "missing_fields": missing_info,
            "is_identified": seq_key is not None,
            "diagnostics": diagnostics,
        })

    return {
        "total_count": len(tags),
        "records": records,
        "category_counts": category_counts,
        "available_missing_fields": sorted(list(all_missing_field_names)),
    }


def compute_final_translations(records: List[Dict[str, Any]], field_values_by_id: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Substitutes field values into placeholder tokens for each record.
    Returns updated records with computed client_translation and unfilled_fields list.
    """
    updated: List[Dict[str, Any]] = []

    for r in records:
        rec_id = str(r.get("id"))
        template = r.get("template_translation", "")
        if template == "N/A":
            updated.append({
                **r,
                "client_translation": "N/A",
                "unfilled_fields": [],
                "is_complete": False,
            })
            continue

        row_fields = field_values_by_id.get(rec_id, {})
        final_str = template
        unfilled: List[str] = []

        # Find all placeholders {name}
        placeholders = re.findall(r"\{([^{}]+)\}", template)
        for ph in placeholders:
            val = str(row_fields.get(ph, "")).strip()
            if val:
                final_str = final_str.replace(f"{{{ph}}}", val)
            else:
                unfilled.append(ph)

        updated.append({
            **r,
            "client_translation": final_str,
            "missing_fields": {ph: str(row_fields.get(ph, "")) for ph in placeholders},
            "unfilled_fields": unfilled,
            "is_complete": len(unfilled) == 0,
        })

    return updated


def build_breakout_excel_bytes(records: List[Dict[str, Any]]) -> bytes:
    """
    Builds the breakout Excel workbook in memory with separate sheets per sequence key.
    """
    sheets_data: Dict[str, List[Dict[str, Any]]] = {}

    for r in records:
        sheet_name = str(r["sequence_key"])[:31]
        row: Dict[str, Any] = {
            "Scovan Tag": r["scovan_tag"],
            "Final Client Translation": r["client_translation"],
        }
        # Add missing fields as individual editable columns
        for k, v in r.get("missing_fields", {}).items():
            row[k] = v

        if sheet_name not in sheets_data:
            sheets_data[sheet_name] = []
        sheets_data[sheet_name].append(row)

    BASE_WIDTH = 8.43
    WIDTH_COL_1 = BASE_WIDTH * 5    # ~42
    WIDTH_COL_2 = BASE_WIDTH * 11   # ~59
    WIDTH_COL_REST = BASE_WIDTH * 3  # ~25

    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for sheet_name, rows in sheets_data.items():
            df = pd.DataFrame(rows)
            df.to_excel(writer, sheet_name=sheet_name, index=False)

            ws = writer.sheets[sheet_name]
            for col_idx in range(1, df.shape[1] + 1):
                col_letter = get_column_letter(col_idx)
                if col_idx == 1:
                    ws.column_dimensions[col_letter].width = WIDTH_COL_1
                elif col_idx == 2:
                    ws.column_dimensions[col_letter].width = WIDTH_COL_2
                else:
                    ws.column_dimensions[col_letter].width = WIDTH_COL_REST

    return bio.getvalue()


def build_final_2column_excel_bytes(records: List[Dict[str, Any]]) -> bytes:
    """
    Builds the clean 2-column final translation Excel sheet ('Scovan Tag', 'Final Client Translation').
    """
    rows = []
    for r in records:
        rows.append({
            "Scovan Tag": r["scovan_tag"],
            "Final Client Translation": r["client_translation"],
        })

    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Scovan Tag", "Final Client Translation"])

    BASE_WIDTH = 8.43
    WIDTH_COL_1 = BASE_WIDTH * 5   # ~42.15
    WIDTH_COL_2 = BASE_WIDTH * 7   # ~59.01

    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Final Translations", index=False)
        ws = writer.sheets["Final Translations"]
        ws.column_dimensions["A"].width = WIDTH_COL_1
        ws.column_dimensions["B"].width = WIDTH_COL_2

    return bio.getvalue()
