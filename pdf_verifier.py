from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Callable

import pypdf

Log = Callable[[str], None]


def normalize_text(text: str) -> str:
    """Normalize whitespace and line endings for robust text matching."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().upper()


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract all text across all pages from PDF bytes."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    full_text = []
    for page in reader.pages:
        t = page.extract_text() or ""
        full_text.append(t)
    return "\n".join(full_text)


def extract_all_pdf_texts_from_zip(zip_path: Path) -> dict[str, str]:
    """Extract all text from every PDF file found in a ZIP archive."""
    pdf_texts: dict[str, str] = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.lower().endswith(".pdf") and not Path(name).name.startswith("._"):
                pdf_bytes = zf.read(name)
                pdf_texts[name] = extract_text_from_pdf_bytes(pdf_bytes)
    return pdf_texts


def check_tag_presence(tag: str, text: str) -> bool:
    """Check if tag is present in text either verbatim, with hyphens replaced by space, or across lines."""
    clean = str(tag).strip()
    if not clean:
        return False
    norm = normalize_text(clean)
    if norm in text:
        return True
    if norm.replace("-", " ") in text:
        return True
    parts = [p.strip() for p in re.split(r"[\s\-_]+", norm) if p.strip()]
    if len(parts) >= 2:
        regex_pat = r"(?<![A-Z0-9#])" + r"[\s\-_]+".join(re.escape(p) for p in parts) + r"(?![A-Z0-9#])"
        if re.search(regex_pat, text):
            return True
        if all(re.search(r"(?<![A-Z0-9#])" + re.escape(p) + r"(?![A-Z0-9#])", text) for p in parts):
            return True
    return False


def verify_pdf_tags(
    pdf_texts: dict[str, str],
    mappings: dict[str, str],
    workflow: str,
    log: Log = print,
) -> dict[str, object]:
    """
    Verify tag text in plotted vector PDFs.
    
    For 'dual_tagging':
        - Original Scovan tag AND translated Client tag MUST both be detected in the PDF.
    For 'client_translation':
        - Translated Client tag MUST be detected in the PDF.
        - Original Scovan tag must NOT be detected (after removing translated occurrences).
    """
    is_client_translation = (workflow == "client_translation")
    combined_raw_text = "\n".join(pdf_texts.values())
    combined_normalized = normalize_text(combined_raw_text)

    passed_checks = 0
    failed_checks = 0
    details: list[str] = []

    log(f"Analyzing {len(pdf_texts)} PDF(s) for {len(mappings)} active tag mappings (Workflow: {workflow})...")

    for scovan_tag, client_tag in mappings.items():
        scovan_clean = str(scovan_tag).strip()
        client_clean = str(client_tag).strip()
        if not scovan_clean or not client_clean:
            continue

        scovan_norm = normalize_text(scovan_clean)
        client_norm = normalize_text(client_clean)

        client_detected = check_tag_presence(client_clean, combined_normalized)
        if not client_detected:
            failed_checks += 1
            msg = f"MISSING TRANSLATED TAG: '{client_clean}' was not detected in any plotted PDF."
            details.append(msg)
            log(f"    [FAIL] {msg}")
            continue
        else:
            passed_checks += 1

        if is_client_translation:
            masked_text = combined_normalized.replace(client_norm, " [MASKED_CLIENT_TAG] ")
            masked_text = masked_text.replace(client_norm.replace("-", " "), " [MASKED_CLIENT_TAG] ")
            client_parts = [p.strip() for p in re.split(r"[\s\-_]+", client_norm) if len(p.strip()) > 1]
            for part in client_parts:
                masked_text = masked_text.replace(part, " [MASKED_PART] ")

            scovan_parts = [normalize_text(p) for p in scovan_clean.split("-") if len(p) > 2]
            
            original_still_present = False
            if re.search(r"(?<![A-Z0-9#_-])" + re.escape(scovan_norm) + r"(?![A-Z0-9#_-])", masked_text):
                original_still_present = True
            elif len(scovan_parts) >= 2 and all(
                re.search(r"(?<![A-Z0-9#_-])" + re.escape(part) + r"(?![A-Z0-9#_-])", masked_text)
                for part in scovan_parts
            ):
                original_still_present = True

            if original_still_present:
                failed_checks += 1
                msg = f"ORIGINAL TAG LEAKED: '{scovan_clean}' was still detected in Client Translation PDF!"
                details.append(msg)
                log(f"    [FAIL] {msg}")
            else:
                passed_checks += 1
                log(f"    [OK] Verified '{scovan_clean}' -> '{client_clean}': Replaced cleanly, original absent.")
        else:
            scovan_detected = check_tag_presence(scovan_clean, combined_normalized)
            if not scovan_detected:
                failed_checks += 1
                msg = f"ORIGINAL TAG MISSING: '{scovan_clean}' was not detected in Dual Tagging PDF."
                details.append(msg)
                log(f"    [FAIL] {msg}")
            else:
                passed_checks += 1
                log(f"    [OK] Dual tag verified: Both '{scovan_clean}' and '{client_clean}' detected in PDF.")

    success = (failed_checks == 0 and passed_checks > 0)
    return {
        "success": success,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "details": details,
        "pdf_count": len(pdf_texts),
    }
