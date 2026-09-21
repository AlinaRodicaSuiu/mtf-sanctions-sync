#!/usr/bin/env python3
"""
Monaco Trade Forum — Sanctions Checker data builder.

Reads FOUR real source files — OFAC SDN list, UK Sanctions List, EU
Consolidated Financial Sanctions List (FSF) and the UN Security Council
Consolidated List — normalises them into a common Monaco Trade Forum
schema, deduplicates cross-source matches, and writes:
  - data/sanctions-list.json       (current normalised, deduplicated dataset)
  - data/sanctions-changelog.json  (append-only history of add/modify/remove events)

USAGE
  Automated (default — no arguments needed, downloads all four real official
  sources directly and normalises them):
    python3 build_sanctions_data.py

  Manual / testing, against local files already on disk:
    python3 build_sanctions_data.py --ofac path/to/sdn.csv --uk path/to/uk_sanctions_list.csv \
        --eu path/to/eu_fsf.csv --un path/to/un_consolidated.xml \
        --list-out data/sanctions-list.json --changelog-out data/sanctions-changelog.json

  --ofac / --uk / --eu / --un each accept EITHER an http(s):// URL (downloaded
  fresh on every run, with the required identifying User-Agent header — see
  OFFICIAL SOURCE ENDPOINTS below) OR a local file path (used as-is, for
  testing against a file you already have). If omitted entirely, the script
  uses the verified official URLs below as the default for that source.
  --no-ofac / --no-uk / --no-eu / --no-un skip a source entirely (testing only).

  This script never fabricates data: if a source's download or parse fails,
  that ONE source is skipped for this run (clearly reported on stderr) and
  the run continues with whichever sources succeeded — entries that exist
  ONLY in a skipped source are carried over unchanged from the previous
  output rather than being dropped (which would otherwise show up as a
  false "removed" event in the changelog just because one government
  website had a bad day). The run only aborts (non-zero exit, nothing
  written) if EVERY source fails.

OFFICIAL SOURCE ENDPOINTS — verified 9 September 2026 (OFAC/UK) and
21 September 2026 (EU/UN)
---------------------------------------------------------------------------
OFAC SDN List: https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV
  OFAC's own "Sanctions List Service". No API key required, but REQUIRES a
  "User-Agent" header on every request — a request without one gets HTTP
  403. This script always sends one.

UK Sanctions List (FCDO): https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv
  FCDO's own dedicated, non-versioned URL for the current CSV export. No
  API key required. This file is large (30+ MB).

EU Consolidated Financial Sanctions List (FSF):
  https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw
  Published by the European Commission (Financial Sanctions Database / FSF).
  The token in the URL is not a secret — it is the European Commission's own
  fixed, published token for this permanent CSV export endpoint (see
  https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions
  ), not per-user credentials. No other header required. Updated by the
  Commission "on the hour, every 2 hours".

UN Security Council Consolidated List:
  https://scsanctions.un.org/resources/xml/en/consolidated.xml
  Published by the UN Secretariat (Security Council subsidiary organs
  branch). XML only — no CSV export is offered. The URL redirects to a
  time-limited signed Azure blob storage link; this script follows
  redirects transparently, same as any browser would.

LICENSE / REUSE BASIS — verified separately per source, 21 September 2026
---------------------------------------------------------------------------
OFAC SDN: U.S. Government work, public domain (17 U.S.C. §105).
UK Sanctions List: Open Government Licence v3.0 (explicit, permissive,
  attribution required).
EU FSF: European Commission-owned content on this site defaults to
  Creative Commons Attribution 4.0 International (CC BY 4.0) under
  Commission Decision 2011/833/EU, with an explicit carve-out for content
  "depicting identifiable private individuals" needing separate clearance —
  which is exactly the category most FSF entries fall into. The FSF exists
  specifically so third parties (banks, businesses, screening tools) can
  screen against it; this is treated here as the dataset's intended use,
  consistent with how every other sanctions-screening product uses it, but
  this has not been separately confirmed in writing with the Commission.
UN Security Council Consolidated List: **not a clean case** — the UN's own
  general website Terms of Use (un.org/en/about-us/terms-of-use) permits
  downloading/copying materials only for "personal, non-commercial use...
  without any right to resell or redistribute them or to compile or create
  derivative works therefrom." No sanctions-list-specific reuse permission
  was found published anywhere on scsanctions.un.org or main.un.org as of
  this writing. In practice, virtually every bank and compliance vendor
  worldwide screens against this exact list — screening against it is the
  entire reason UN Security Council resolutions require it to be published
  in machine-readable form — but that general ToU wording has NOT been
  reconciled with that practice in anything this script's author could
  find in writing. Monaco Trade Forum has NOT sought written confirmation
  from the UN (sc-sanctionslists@un.org, as the UN's own consolidated-list
  page suggests contacting for licensing questions). Flagged explicitly to
  Alina Suiu on 21 September 2026 as a decision point, not resolved
  unilaterally by this script. See claude/arhitectura-mtf-sanctions-checker.md.

FIELD MAPPING — verify against the real files before first production run
---------------------------------------------------------------------------
OFAC SDN legacy CSV (sdn.csv, no header row) has 12 positional columns:
  0 ent_num, 1 SDN_Name, 2 SDN_Type, 3 Program, 4 Title, 5 Call_Sign,
  6 Vess_type, 7 Tonnage, 8 GRT, 9 Vess_flag, 10 Vess_owner, 11 Remarks
IMO numbers for vessels are usually embedded as free text inside Remarks,
e.g. "(Vessel) IMO 9270646" — this script extracts them with a regex.
If OFAC instead publishes a header row (newer exports sometimes do), the
script also tries to match by header name (case-insensitive) before
falling back to the fixed positional layout above.

UK Sanctions List CSV (gov.uk export) — column names per the UK's own
"Format Guide for the UK Sanctions List": Name 1..Name 6, Alias Type,
Unique ID, Regime Name, Country, Date of Birth, National Identification No,
Address Line 1..6, Last Updated, IMO Number, Current/Previous Flag, Type
of Vessel, Tonnage, and more. Matched case-insensitively.

EU FSF CSV — semicolon-delimited (NOT comma), 118 columns, one row per
name/alias per listed subject (rows sharing the same Entity_LogicalId are
the same real-world subject — aggregate, don't dedupe-away). Verified
against a genuine EU FSF export (column header row inspected directly,
21 September 2026): fileGenerationDate, Entity_LogicalId,
Entity_EU_ReferenceNumber, Entity_DesignationDate, Entity_DesignationDetails,
Entity_Remark, Entity_SubjectType (P/E), Entity_SubjectType_ClassificationCode
("person"/"enterprise"), Entity_Regulation_Programme,
Entity_Regulation_PublicationDate, Entity_Regulation_PublicationUrl,
NameAlias_WholeName (+ LastName/FirstName/MiddleName), Address_CountryDescription,
Citizenship_CountryDescription, Identification_Number,
Identification_TypeDescription, Identification_CountryDescription, and more.
The EU FSF has NO dedicated vessel/IMO columns — but IMO numbers for
sanctioned shipping companies do appear as free text inside
Entity_Remark / Entity_DesignationDetails (e.g. an entity remark reading
"...operator/manager of the following vessels with IMO Number: ... 8606173,
...") and are extracted from there with a regex into that entity's
`identifiers` list — never promoted to the single `imo` field, since the
listed subject in these cases is the operating company, not the vessel
itself.

UN Security Council Consolidated List XML — root <CONSOLIDATED_LIST
dateGenerated="...">, with <INDIVIDUALS><INDIVIDUAL> and
<ENTITIES><ENTITY> children. Verified against a genuine UN SC Consolidated
List XML export (structure inspected directly, 21 September 2026):
DATAID, FIRST_NAME..FOURTH_NAME (individuals) / FIRST_NAME (entity name),
UN_LIST_TYPE, REFERENCE_NUMBER, LISTED_ON, COMMENTS1, NATIONALITY/VALUE,
INDIVIDUAL_ALIAS or ENTITY_ALIAS (ALIAS_NAME). No dedicated vessel/IMO
schema field either — IMO numbers occasionally appear as free text inside
COMMENTS1 for DPRK-related shipping entities and are extracted the same
way as for EU, into `identifiers`, never into the single `imo` field.

Column/tag names below are matched defensively (case-insensitively for
CSVs, with graceful `.get()`/`.find()` fallbacks for XML); if a real file
ever uses different labels or structure, this script prints a clear
WARNING to stderr naming the field it could not find rather than silently
guessing or inventing a value.
"""

import argparse
import csv
import json
import re
import sys
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

IMO_RE = re.compile(r"IMO[^0-9]{0,20}([0-9]{7})", re.IGNORECASE)

# --- default official source endpoints (see OFFICIAL SOURCE ENDPOINTS above) ---
DEFAULT_OFAC_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
DEFAULT_UK_URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"
DEFAULT_EU_URL = "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"
DEFAULT_UN_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"

# Identifying User-Agent sent on every download. OFAC's Sanctions List
# Service returns HTTP 403 to requests with no User-Agent at all; sending a
# real, identifying one is also just good practice for a service run by a
# government agency, same reasoning as the existing MET Norway weather proxy.
DOWNLOAD_USER_AGENT = "MonacoTradeForum-SanctionsChecker/1.0 (+https://monacotradeforum.com; contact: desk@monacotradeforum.com)"

# Generous timeout — the UK file specifically is 30+ MB, and the UN file
# redirects through a signed blob-storage link; same timeout is harmless to
# reuse for all four sources.
DOWNLOAD_TIMEOUT_SECONDS = 180

SOURCE_META = {
    "OFAC": {
        "name": "Specially Designated Nationals and Blocked Persons List (SDN List)",
        "authority": "U.S. Department of the Treasury — Office of Foreign Assets Control (OFAC)",
        "list_url": "https://sanctionslist.ofac.treas.gov/Home/SdnList",
        "license": "U.S. Government work — public domain (17 U.S.C. §105)",
    },
    "UK": {
        "name": "UK Sanctions List",
        "authority": "UK Foreign, Commonwealth & Development Office (FCDO)",
        "list_url": "https://www.gov.uk/government/publications/the-uk-sanctions-list",
        "license": "Open Government Licence v3.0",
    },
    "EU": {
        "name": "Consolidated list of persons, groups and entities subject to EU financial sanctions (FSF)",
        "authority": "European Commission — Financial Sanctions Database (FSF)",
        "list_url": "https://webgate.ec.europa.eu/fsd/fsf",
        "license": "EU document reuse policy — CC BY 4.0 (Commission Decision 2011/833/EU); attribution required",
    },
    "UN": {
        "name": "United Nations Security Council Consolidated List",
        "authority": "United Nations Security Council — Sanctions Committees",
        "list_url": "https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list",
        "license": "UN Terms of Use (un.org/en/about-us/terms-of-use) — not an explicit open-data license; see script docstring",
    },
}


def download_source(url, dest_dir):
    """Download `url` to a temp file inside dest_dir with the required
    identifying User-Agent header, and return (local_path, http_headers).

    Never fabricates data: on any failure (network error, non-200 status,
    empty body) this raises — the caller decides whether that failure takes
    down the whole run (nothing at all succeeded) or just skips this one
    source for this run."""
    req = urllib.request.Request(url, headers={"User-Agent": DOWNLOAD_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                raise RuntimeError(f"HTTP {status} downloading {url}")
            body = resp.read()
            headers = dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} downloading {url}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error downloading {url}: {e.reason}") from e

    if not body:
        raise RuntimeError(f"Downloaded {url} but the response body was empty.")

    suffix = ".xml" if url.lower().split("?")[0].endswith(".xml") else (
        ".csv" if url.lower().split("?")[0].endswith(".csv") or "csv" in url.lower() else ".dat"
    )
    fd, path = tempfile.mkstemp(prefix="mtf-sanctions-", suffix=suffix, dir=dest_dir)
    with open(fd, "wb") as f:
        f.write(body)

    print(f"Downloaded {url} -> {path} ({len(body):,} bytes)", file=sys.stderr)
    return path, headers


def resolve_source(arg_value, default_url, tmp_dir):
    """Given a --ofac/--uk/--eu/--un CLI value (may be None, an http(s)://
    URL, or a local path), decide what local file path to parse from,
    downloading first if needed. Returns (path, http_last_modified_or_None).
    A local-path value (testing) always returns last_modified=None — the
    caller falls back to any date embedded in the file itself, or to the
    previous run's recorded value."""
    value = arg_value or default_url
    if value is None:
        return None, None
    if re.match(r"^https?://", value, re.IGNORECASE):
        path, headers = download_source(value, tmp_dir)
        last_mod = headers.get("Last-Modified") or headers.get("last-modified")
        return path, last_mod
    return value, None

# --- column-name aliases for the UK CSV (header-based) ---------------------
UK_COLUMN_ALIASES = {
    "unique_id": ["unique id", "unique id#", "uk sanctions list ref", "uk id"],
    "group_type": ["group type", "type"],
    "name1": ["name 1", "name1"],
    "name2": ["name 2", "name2"],
    "name3": ["name 3", "name3"],
    "name4": ["name 4", "name4"],
    "name5": ["name 5", "name5"],
    "name6": ["name 6", "name6"],
    "regime_name": ["regime name", "regime"],
    "country": ["country"],
    "last_updated": ["last updated"],
    "date_designated": ["date designated", "designation date"],
    "imo_number": ["imo number", "imo no", "imo"],
    "current_flag": ["current flag", "flag"],
    "previous_flag": ["previous flag"],
    "type_of_vessel": ["type of vessel", "vessel type", "ship type"],
    "tonnage": ["tonnage"],
    "sanctions_imposed": ["sanctions imposed", "statement of reasons", "sanctions type"],
    "national_id": ["national identification no", "national identification number", "national id no"],
}

# --- column-name aliases for the EU FSF CSV (header-based, ';' delimited) --
EU_COLUMN_ALIASES = {
    "logical_id": ["entity_logicalid"],
    "reference_number": ["entity_eu_referencenumber"],
    "un_id": ["entity_unitednationid"],
    "designation_date": ["entity_designationdate"],
    "designation_details": ["entity_designationdetails"],
    "remark": ["entity_remark"],
    "subject_type": ["entity_subjecttype"],
    "subject_type_code": ["entity_subjecttype_classificationcode"],
    "regulation_programme": ["entity_regulation_programme"],
    "regulation_pub_date": ["entity_regulation_publicationdate"],
    "regulation_pub_url": ["entity_regulation_publicationurl"],
    "file_generation_date": ["filegenerationdate"],
    "name_whole": ["namealias_wholename"],
    "name_last": ["namealias_lastname"],
    "name_first": ["namealias_firstname"],
    "address_country": ["address_countrydescription"],
    "citizenship_country": ["citizenship_countrydescription"],
    "id_number": ["identification_number"],
    "id_type_desc": ["identification_typedescription"],
    "id_country": ["identification_countrydescription"],
}

# --- fixed positional layout for legacy OFAC sdn.csv (no header) -----------
OFAC_POSITIONAL_FIELDS = [
    "ent_num", "sdn_name", "sdn_type", "program", "title", "call_sign",
    "vess_type", "tonnage", "grt", "vess_flag", "vess_owner", "remarks",
]


def normalise_header(h):
    return re.sub(r"[^a-z0-9]+", " ", h.strip().lower()).strip()


def normalise_header_nospace(h):
    return re.sub(r"[^a-z0-9]+", "", h.strip().lower()).strip()


def find_col(headers_norm, aliases):
    for a in aliases:
        a_norm = normalise_header(a)
        for i, h in enumerate(headers_norm):
            if h == a_norm:
                return i
    return None


def find_col_nospace(headers_norm, aliases):
    for a in aliases:
        a_norm = normalise_header_nospace(a)
        for i, h in enumerate(headers_norm):
            if h == a_norm:
                return i
    return None


def extract_imos(text):
    """Find every IMO-like 7-digit number mentioned near the word "IMO" in
    free text (used for EU/UN entity remarks that describe vessels a
    sanctioned shipping company operates). Returns a de-duplicated list,
    empty if none found — never invents one."""
    if not text:
        return []
    seen = []
    for m in IMO_RE.finditer(text):
        v = m.group(1)
        if v not in seen:
            seen.append(v)
    # The OFAC/EU remark style also lists bare 7-digit numbers after the
    # first "IMO Number:" mention, comma-separated, e.g. "...8606173, (b)
    # Chong Bong ... 8909575, ...". Catch those too, but only once an "IMO"
    # anchor has already been seen in this text, to avoid matching
    # unrelated 7-digit numbers.
    if seen:
        for m in re.finditer(r"\b([0-9]{7})\b", text):
            v = m.group(1)
            if v not in seen:
                seen.append(v)
    return seen


def dedupe_key_entity(name, country):
    # NOTE: keyed on normalised name ONLY, not name+country — see OFAC note:
    # several sources have no reliable structured country column, so
    # requiring a country match would silently defeat cross-source dedup.
    # Country is still merged into the record as a display field, it just
    # isn't part of the identity key.
    n = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    return ("entity", n)


def dedupe_key_vessel(imo):
    return ("vessel", str(imo).strip())


def parse_ofac_csv(path):
    """Parse an OFAC SDN CSV export. Tries header-based matching first,
    falls back to the fixed legacy positional layout (no header row)."""
    entries = []
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        print(f"[OFAC] WARNING: {path} is empty — no entries parsed.", file=sys.stderr)
        return entries

    first = [c.strip().lower() for c in rows[0]]
    has_header = any(h in ("sdn_name", "sdn name", "name") for h in first)

    body = rows[1:] if has_header else rows
    header_map = None
    if has_header:
        header_map = {normalise_header(h): i for i, h in enumerate(first)}

    def get(row, field, positional_idx):
        if header_map is not None and field in header_map:
            idx = header_map[field]
            return row[idx] if idx < len(row) else ""
        return row[positional_idx] if positional_idx < len(row) else ""

    for row in body:
        if not row or not any(row):
            continue
        ent_num = get(row, "ent_num", 0)
        name = get(row, "sdn_name", 1)
        sdn_type = get(row, "sdn_type", 2)
        program = get(row, "program", 3)
        vess_type = get(row, "vess_type", 6)
        vess_flag = get(row, "vess_flag", 9)
        remarks = get(row, "remarks", 11)

        if not name:
            continue

        is_vessel = "vessel" in (sdn_type or "").lower()
        entry_type = "vessel" if is_vessel else ("person" if "individual" in (sdn_type or "").lower() else "entity")

        imo = None
        if is_vessel:
            found = extract_imos(remarks or "")
            if found:
                imo = found[0]

        entries.append({
            "source": "OFAC",
            "source_id": f"SDN-{ent_num}".strip("-") or None,
            "type": entry_type,
            "name": name.strip(),
            "aliases": [],
            "country": None,
            "program": (program or "").strip() or None,
            "listing_date": None,
            "imo": imo,
            "flag": (vess_flag or "").strip() or None,
            "vessel_type": (vess_type or "").strip() or None,
            "identifiers": [],
            "list_url": "https://sanctionslist.ofac.treas.gov/Home/SdnList",
        })

    print(f"[OFAC] Parsed {len(entries)} entries from {path} (header row: {has_header}).", file=sys.stderr)
    return entries


def parse_uk_csv(path):
    entries = []
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        print(f"[UK] WARNING: {path} is empty — no entries parsed.", file=sys.stderr)
        return entries

    headers = rows[0]
    headers_norm = [normalise_header(h) for h in headers]

    def col(field):
        return find_col(headers_norm, UK_COLUMN_ALIASES.get(field, [field]))

    idx = {field: col(field) for field in UK_COLUMN_ALIASES}
    missing = [f for f, i in idx.items() if i is None and f in ("unique_id", "name1")]
    if missing:
        print(f"[UK] WARNING: expected columns not found: {missing}. "
              f"Headers seen: {headers}. Adjust UK_COLUMN_ALIASES and re-run.", file=sys.stderr)

    def get(row, field):
        i = idx.get(field)
        return row[i].strip() if i is not None and i < len(row) else ""

    for row in rows[1:]:
        if not row or not any(row):
            continue
        name_parts = [get(row, f"name{n}") for n in range(1, 7)]
        name = " ".join([p for p in name_parts if p]).strip()
        if not name:
            continue

        group_type = get(row, "group_type").lower()
        imo = get(row, "imo_number") or None
        is_vessel = bool(imo) or "ship" in group_type or "vessel" in group_type
        entry_type = "vessel" if is_vessel else ("person" if "individual" in group_type else "entity")

        identifiers = []
        national_id = get(row, "national_id")
        if national_id:
            identifiers.append({"type": "National identification no.", "value": national_id})

        entries.append({
            "source": "UK",
            "source_id": get(row, "unique_id") or None,
            "type": entry_type,
            "name": name,
            "aliases": [],
            "country": get(row, "country") or None,
            "program": get(row, "regime_name") or None,
            "listing_date": get(row, "date_designated") or None,
            "imo": imo,
            "flag": get(row, "current_flag") or get(row, "previous_flag") or None,
            "vessel_type": get(row, "type_of_vessel") or None,
            "identifiers": identifiers,
            "list_url": "https://www.gov.uk/government/publications/the-uk-sanctions-list",
        })

    print(f"[UK] Parsed {len(entries)} entries from {path}.", file=sys.stderr)
    return entries


def parse_eu_csv(path):
    """Parse the EU FSF CSV export. Semicolon-delimited; one row per
    name/alias per listed subject, grouped here by Entity_LogicalId into
    one merged record per real-world subject (matching the EU's own file
    design — see FIELD MAPPING in the module docstring)."""
    entries = []
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f, delimiter=";")
        try:
            headers = next(reader)
        except StopIteration:
            print(f"[EU] WARNING: {path} is empty — no entries parsed.", file=sys.stderr)
            return entries
        headers_norm = [normalise_header_nospace(h) for h in headers]

        def col(field):
            return find_col_nospace(headers_norm, EU_COLUMN_ALIASES.get(field, [field]))

        idx = {field: col(field) for field in EU_COLUMN_ALIASES}
        missing = [f for f, i in idx.items() if i is None and f in ("logical_id", "name_whole")]
        if missing:
            print(f"[EU] WARNING: expected columns not found: {missing}. "
                  f"Headers seen: {headers}. Adjust EU_COLUMN_ALIASES and re-run.", file=sys.stderr)
            return entries

        def get(row, field):
            i = idx.get(field)
            return row[i].strip() if i is not None and i < len(row) else ""

        grouped = {}
        row_order = []
        for row in reader:
            if not row or not any(row):
                continue
            logical_id = get(row, "logical_id")
            if not logical_id:
                continue
            if logical_id not in grouped:
                grouped[logical_id] = {
                    "names": [], "subject_type_code": "", "reference_number": "",
                    "designation_date": "", "regulation_programme": "",
                    "regulation_pub_date": "", "regulation_pub_url": "",
                    "address_country": "", "citizenship_country": "",
                    "remark_text": [], "id_numbers": [], "file_generation_date": "",
                }
                row_order.append(logical_id)
            g = grouped[logical_id]

            name = get(row, "name_whole")
            if name and name not in g["names"]:
                g["names"].append(name)
            for simple_field in ("subject_type_code", "reference_number", "designation_date",
                                  "regulation_programme", "regulation_pub_date",
                                  "regulation_pub_url", "file_generation_date"):
                if not g[simple_field]:
                    v = get(row, simple_field)
                    if v:
                        g[simple_field] = v
            for country_field in ("address_country", "citizenship_country"):
                if not g[country_field]:
                    v = get(row, country_field)
                    if v:
                        g[country_field] = v
            remark = get(row, "designation_details") or get(row, "remark")
            if remark and remark not in g["remark_text"]:
                g["remark_text"].append(remark)
            id_num = get(row, "id_number")
            if id_num:
                id_type = get(row, "id_type_desc") or "Identification document"
                pair = (id_type, id_num)
                if pair not in g["id_numbers"]:
                    g["id_numbers"].append(pair)

    for logical_id in row_order:
        g = grouped[logical_id]
        if not g["names"]:
            continue
        name = g["names"][0]
        aliases = g["names"][1:]

        subj = (g["subject_type_code"] or "").lower()
        entry_type = "person" if subj == "person" else "entity"

        full_remark = " ".join(g["remark_text"])
        imos = extract_imos(full_remark)
        identifiers = [{"type": t, "value": v} for t, v in g["id_numbers"]]
        for imo_val in imos:
            identifiers.append({"type": "IMO (vessel operated by this entity)", "value": imo_val})

        entries.append({
            "source": "EU",
            "source_id": g["reference_number"] or logical_id,
            "type": entry_type,
            "name": name,
            "aliases": aliases,
            "country": g["address_country"] or g["citizenship_country"] or None,
            "program": g["regulation_programme"] or None,
            "listing_date": g["designation_date"] or None,
            "imo": None,  # EU FSF has no dedicated vessel subject type — see docstring
            "flag": None,
            "vessel_type": None,
            "identifiers": identifiers,
            "list_url": g["regulation_pub_url"] or "https://webgate.ec.europa.eu/fsd/fsf",
            "_file_generation_date": g["file_generation_date"] or None,
        })

    print(f"[EU] Parsed {len(entries)} entries from {path} (grouped from CSV alias rows).", file=sys.stderr)
    return entries


def _un_text(el, tag):
    child = el.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def parse_un_xml(path):
    """Parse the UN Security Council Consolidated List XML export."""
    entries = []
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        print(f"[UN] WARNING: could not parse {path} as XML: {e}", file=sys.stderr)
        return entries, None
    root = tree.getroot()
    date_generated = root.attrib.get("dateGenerated")

    for ind in root.findall("./INDIVIDUALS/INDIVIDUAL"):
        name_parts = [_un_text(ind, t) for t in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")]
        name = " ".join([p for p in name_parts if p]).strip()
        if not name:
            continue
        aliases = []
        for al in ind.findall("./INDIVIDUAL_ALIAS"):
            an = _un_text(al, "ALIAS_NAME")
            if an and an not in aliases:
                aliases.append(an)
        nationalities = [_un_text(n, "VALUE") for n in ind.findall("./NATIONALITY")]
        nationality = next((n for n in nationalities if n), None)
        comments = _un_text(ind, "COMMENTS1")
        imos = extract_imos(comments)
        entries.append({
            "source": "UN",
            "source_id": _un_text(ind, "REFERENCE_NUMBER") or _un_text(ind, "DATAID") or None,
            "type": "person",
            "name": name,
            "aliases": aliases,
            "country": nationality,
            "program": _un_text(ind, "UN_LIST_TYPE") or None,
            "listing_date": _un_text(ind, "LISTED_ON") or None,
            "imo": None,
            "flag": None,
            "vessel_type": None,
            "identifiers": [{"type": "IMO (vessel operated by this entity)", "value": v} for v in imos],
            "list_url": "https://scsanctions.un.org/consolidated",
        })

    for ent in root.findall("./ENTITIES/ENTITY"):
        name = _un_text(ent, "FIRST_NAME")  # entities use FIRST_NAME for the org name
        if not name:
            continue
        aliases = []
        for al in ent.findall("./ENTITY_ALIAS"):
            an = _un_text(al, "ALIAS_NAME")
            if an and an not in aliases:
                aliases.append(an)
        comments = _un_text(ent, "COMMENTS1")
        imos = extract_imos(comments)
        entries.append({
            "source": "UN",
            "source_id": _un_text(ent, "REFERENCE_NUMBER") or _un_text(ent, "DATAID") or None,
            "type": "entity",
            "name": name,
            "aliases": aliases,
            "country": None,
            "program": _un_text(ent, "UN_LIST_TYPE") or None,
            "listing_date": _un_text(ent, "LISTED_ON") or None,
            "imo": None,
            "flag": None,
            "vessel_type": None,
            "identifiers": [{"type": "IMO (vessel operated by this entity)", "value": v} for v in imos],
            "list_url": "https://scsanctions.un.org/consolidated",
        })

    print(f"[UN] Parsed {len(entries)} entries from {path} "
          f"({len(root.findall('./INDIVIDUALS/INDIVIDUAL'))} individuals, "
          f"{len(root.findall('./ENTITIES/ENTITY'))} entities).", file=sys.stderr)
    return entries, date_generated


def merge_identifiers(existing, new_list):
    for item in new_list:
        pair = (item.get("type"), item.get("value"))
        if not any((x.get("type"), x.get("value")) == pair for x in existing):
            existing.append(item)


def merge_and_dedupe(raw_entries, existing_entries_by_id):
    """Cross-source dedupe: exact IMO match for vessels, normalised
    name match for everything else. Returns a dict of merged entries with a
    stable `id`, reusing ids from existing_entries_by_id where the same
    real-world entity is recognised again (so history stays attached to the
    same id across syncs)."""
    by_dedupe_key = {}
    id_by_dedupe_key = {}
    for eid, e in existing_entries_by_id.items():
        if e.get("type") == "vessel" and e.get("imo"):
            id_by_dedupe_key[dedupe_key_vessel(e["imo"])] = eid
        else:
            id_by_dedupe_key[dedupe_key_entity(e.get("name"), e.get("country"))] = eid

    merged = {}
    next_seq = max(
        [int(m.group(1)) for eid in existing_entries_by_id
         for m in [re.match(r"mtf-(\d+)", eid)] if m] or [0]
    ) + 1

    for raw in raw_entries:
        if raw["type"] == "vessel" and raw.get("imo"):
            key = dedupe_key_vessel(raw["imo"])
        else:
            key = dedupe_key_entity(raw["name"], raw.get("country"))

        eid = id_by_dedupe_key.get(key)
        if eid is None:
            eid = f"mtf-{next_seq:05d}"
            next_seq += 1
            id_by_dedupe_key[key] = eid

        if eid not in merged:
            merged[eid] = {
                "id": eid,
                "type": raw["type"],
                "name": raw["name"],
                "aliases": [],
                "country": raw.get("country"),
                "program": raw.get("program"),
                "listing_date": raw.get("listing_date"),
                "imo": raw.get("imo"),
                "flag": raw.get("flag"),
                "vessel_type": raw.get("vessel_type"),
                "identifiers": [],
                "sources": [],
            }
        rec = merged[eid]
        rec["sources"].append({
            "code": raw["source"],
            "source_id": raw.get("source_id"),
            "list_url": raw["list_url"],
        })
        for field in ("country", "program", "listing_date", "flag", "vessel_type"):
            if not rec.get(field) and raw.get(field):
                rec[field] = raw[field]
        for alias in raw.get("aliases") or []:
            if alias and alias != rec["name"] and alias not in rec["aliases"]:
                rec["aliases"].append(alias)
        # If a later source spells the same (IMO- or name-matched) entity's
        # name differently, keep the first name as primary and record the
        # variant as an alias rather than silently dropping it.
        if raw["name"] and raw["name"] != rec["name"] and raw["name"] not in rec["aliases"]:
            rec["aliases"].append(raw["name"])
        merge_identifiers(rec["identifiers"], raw.get("identifiers") or [])

    return merged


def diff_for_changelog(old_entries_by_id, new_entries_by_id, today):
    events = []
    old_ids = set(old_entries_by_id)
    new_ids = set(new_entries_by_id)
    for eid in sorted(new_ids - old_ids):
        events.append({"date": today, "entity_id": eid, "action": "added",
                        "note": f"New listing detected: {new_entries_by_id[eid]['name']}"})
    for eid in sorted(old_ids - new_ids):
        events.append({"date": today, "entity_id": eid, "action": "removed",
                        "note": f"No longer present in source lists: {old_entries_by_id[eid]['name']}"})
    for eid in sorted(old_ids & new_ids):
        old, new = old_entries_by_id[eid], new_entries_by_id[eid]
        if json.dumps(old, sort_keys=True) != json.dumps(new, sort_keys=True):
            events.append({"date": today, "entity_id": eid, "action": "modified",
                            "note": f"Record updated: {new['name']}"})
    return events


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ofac", help="OFAC SDN source: an http(s):// URL to download, or a local CSV "
                                   f"path. Default when omitted: {DEFAULT_OFAC_URL}")
    ap.add_argument("--uk", help="UK Sanctions List source: an http(s):// URL to download, or a "
                                  f"local CSV path. Default when omitted: {DEFAULT_UK_URL}")
    ap.add_argument("--eu", help="EU FSF source: an http(s):// URL to download, or a local CSV "
                                  f"path. Default when omitted: {DEFAULT_EU_URL}")
    ap.add_argument("--un", help="UN Consolidated List source: an http(s):// URL to download, or a "
                                  f"local XML path. Default when omitted: {DEFAULT_UN_URL}")
    ap.add_argument("--no-ofac", action="store_true", help="Skip the OFAC source entirely (testing only)")
    ap.add_argument("--no-uk", action="store_true", help="Skip the UK source entirely (testing only)")
    ap.add_argument("--no-eu", action="store_true", help="Skip the EU source entirely (testing only)")
    ap.add_argument("--no-un", action="store_true", help="Skip the UN source entirely (testing only)")
    ap.add_argument("--list-out", default="data/sanctions-list.json")
    ap.add_argument("--changelog-out", default="data/sanctions-changelog.json")
    args = ap.parse_args()

    if args.no_ofac and args.no_uk and args.no_eu and args.no_un:
        print("All four sources disabled. Nothing to do — this script never "
              "fabricates data.", file=sys.stderr)
        sys.exit(1)

    list_path = Path(args.list_out)
    changelog_path = Path(args.changelog_out)

    existing = {"entries": [], "sources": []}
    if list_path.exists():
        existing = json.loads(list_path.read_text(encoding="utf-8"))
    existing_by_id = {e["id"]: e for e in existing.get("entries", []) if not e.get("id", "").startswith("mtf-test-")}
    existing_sources_by_code = {s["code"]: s for s in existing.get("sources", [])}

    raw = []
    fetched_codes = set()
    failed = {}
    source_last_updated = {}

    with tempfile.TemporaryDirectory(prefix="mtf-sanctions-dl-") as tmp_dir:
        if not args.no_ofac:
            try:
                path, http_last_mod = resolve_source(args.ofac, DEFAULT_OFAC_URL, tmp_dir)
                raw += parse_ofac_csv(path)
                fetched_codes.add("OFAC")
                if http_last_mod:
                    source_last_updated["OFAC"] = http_last_mod
            except Exception as e:
                print(f"[OFAC] SKIPPED this run: {e}", file=sys.stderr)
                failed["OFAC"] = str(e)

        if not args.no_uk:
            try:
                path, http_last_mod = resolve_source(args.uk, DEFAULT_UK_URL, tmp_dir)
                raw += parse_uk_csv(path)
                fetched_codes.add("UK")
                if http_last_mod:
                    source_last_updated["UK"] = http_last_mod
            except Exception as e:
                print(f"[UK] SKIPPED this run: {e}", file=sys.stderr)
                failed["UK"] = str(e)

        if not args.no_eu:
            try:
                path, http_last_mod = resolve_source(args.eu, DEFAULT_EU_URL, tmp_dir)
                eu_entries = parse_eu_csv(path)
                file_gen_date = next((e.pop("_file_generation_date", None) for e in eu_entries[:1]), None)
                for e in eu_entries:
                    e.pop("_file_generation_date", None)
                raw += eu_entries
                fetched_codes.add("EU")
                source_last_updated["EU"] = file_gen_date or http_last_mod
            except Exception as e:
                print(f"[EU] SKIPPED this run: {e}", file=sys.stderr)
                failed["EU"] = str(e)

        if not args.no_un:
            try:
                path, http_last_mod = resolve_source(args.un, DEFAULT_UN_URL, tmp_dir)
                un_entries, date_generated = parse_un_xml(path)
                raw += un_entries
                fetched_codes.add("UN")
                source_last_updated["UN"] = date_generated or http_last_mod
            except Exception as e:
                print(f"[UN] SKIPPED this run: {e}", file=sys.stderr)
                failed["UN"] = str(e)

    if not fetched_codes:
        print("FATAL: every source failed this run — nothing to do. Never falling back to "
              "stale or fake data.", file=sys.stderr)
        for code, msg in failed.items():
            print(f"  {code}: {msg}", file=sys.stderr)
        sys.exit(3)

    if not raw and fetched_codes:
        print("No entries parsed from the source(s) that did download — aborting without "
              "writing anything, to avoid overwriting good data with an empty result.", file=sys.stderr)
        sys.exit(2)

    # Carry over, unchanged, any existing entry whose sources are ENTIRELY
    # within sources that were NOT fetched this run (so a transient outage
    # at one government website doesn't look like a mass delisting).
    skipped_codes = set(failed.keys())
    carried_over = {}
    if skipped_codes:
        for eid, e in existing_by_id.items():
            entry_codes = {s.get("code") for s in e.get("sources", [])}
            if entry_codes and entry_codes.issubset(skipped_codes):
                carried_over[eid] = e
        if carried_over:
            print(f"Carrying over {len(carried_over)} existing entries unchanged "
                  f"(sourced only from {sorted(skipped_codes)}, skipped this run).", file=sys.stderr)

    merged_by_id = merge_and_dedupe(raw, existing_by_id)
    merged_by_id.update(carried_over)  # carried-over entries win their own ids, no rebuild

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_events = diff_for_changelog(existing_by_id, merged_by_id, today)

    changelog = {"schema_version": 1, "mode": "live", "entries": []}
    if changelog_path.exists():
        prev = json.loads(changelog_path.read_text(encoding="utf-8"))
        changelog["entries"] = [e for e in prev.get("entries", []) if not e["entity_id"].startswith("mtf-test-")]
    changelog["entries"].extend(new_events)
    changelog["note"] = "Live changelog — append-only history of Monaco Trade Forum sanctions data synchronisations."

    sources_out = []
    for code in ("OFAC", "UK", "EU", "UN"):
        meta = dict(SOURCE_META[code])
        meta["code"] = code
        if code in source_last_updated and source_last_updated[code]:
            meta["last_updated"] = source_last_updated[code]
        elif code in existing_sources_by_code and existing_sources_by_code[code].get("last_updated"):
            meta["last_updated"] = existing_sources_by_code[code]["last_updated"]
        else:
            meta["last_updated"] = None
        meta["fetched_this_run"] = code in fetched_codes
        sources_out.append(meta)

    note = "Live data, normalised and deduplicated by Monaco Trade Forum from the sources listed below."
    if failed:
        note += (" NOTE: " + ", ".join(f"{c} could not be fetched this run ({m})" for c, m in failed.items())
                 + " — that source's previously-known entries were kept unchanged rather than removed.")

    out = {
        "schema_version": 2,
        "mode": "live",
        "last_synchronised": today,
        "note": note,
        "sources": sources_out,
        "entries": list(merged_by_id.values()),
    }

    list_path.parent.mkdir(parents=True, exist_ok=True)
    list_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    changelog_path.write_text(json.dumps(changelog, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(out['entries'])} entries to {list_path} "
          f"(sources fetched this run: {sorted(fetched_codes)})", file=sys.stderr)
    print(f"Wrote {len(changelog['entries'])} changelog events to {changelog_path} "
          f"({len(new_events)} new this run)", file=sys.stderr)


if __name__ == "__main__":
    main()
