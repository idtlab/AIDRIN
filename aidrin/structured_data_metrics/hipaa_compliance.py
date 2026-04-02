import re
import pandas as pd
import pgeocode

def detect_hipaa_identifiers(df, columns_to_scan, country='US'):
    """
    Scans a DataFrame for HIPAA identifiers using Regex and
    pgeocode database validation for postal codes.
    """
    nomi = pgeocode.Nominatim(country.lower())

    patterns = {
        "US_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "EMAIL_ADDRESS": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "PHONE_OR_FAX": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        "IP_ADDRESS": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
        "URL": re.compile(r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+"),
        "VIN_NUMBER": re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b"),
        "MEDICAL_IDS": re.compile(r"\b(MRN|HICN|Account|License|Device|ID)[:\s]?[A-Z0-9\-]+\b", re.IGNORECASE),
    }

    postal_candidate_re = re.compile(r"\b\d{5}(?:-\d{4})?\b")

    detected_phi = {}

    for col in columns_to_scan:
        if col not in df.columns:
            continue

        series = df[col].dropna().astype(str)
        col_findings = []
        found_entities = set()

        for value in series:
            for entity_type, regex in patterns.items():
                matches = regex.findall(value)
                if matches:
                    col_findings.extend(matches)
                    found_entities.add(entity_type)

            candidates = postal_candidate_re.findall(value)
            for cand in candidates:
                clean_zip = cand.split('-')[0]

                res = nomi.query_postal_code(clean_zip)
                if pd.notna(res.place_name):
                    col_findings.append(clean_zip)
                    found_entities.add("VALID_POSTAL_CODE")

        if col_findings:
            detected_phi[col] = {
                "total_flags": len(col_findings),
                "potential_types_detected": sorted(list(found_entities)),
                "examples": list(set(col_findings))[:5]
            }

    return detected_phi
