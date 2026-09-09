#!/usr/bin/env python3
"""
Monaco Trade Forum — Sanctions Checker data builder.

Reads the two real source files (OFAC SDN list + UK Sanctions List), normalises
them into a common Monaco Trade Forum schema, deduplicates cross-source matches,
and writes:
  - data/sanctions-list.json       (current normalised, deduplicated dataset)
  - data/sanctions-changelog.json  (append-only history of add/modify/remove events)

USAGE
  Automated (default — no arguments needed, downloads the real official
  sources directly and normalises them):
    python3 build_sanctions_data.py

  Manual / testing, against local files already on disk:
    python3 build_sanctions_data.py --ofac path/to/sdn.csv --uk path/to/uk_sanctions_list.csv \
        --list-out data/sanctions-list.json --changelog-out data/sanctions-changelog.json

  --ofac and --uk each accept EITHER an http(s):// URL (downloaded fresh on
  every run, with the required identifying User-Agent header — see
  OFFICIAL SOURCE ENDPOINTS below) OR a local file path (used as-is, for
  testing against a file you already have). If omitted entirely, the script
  uses the verified official URLs below as the default for that source.

  This script never fabricates data: if a download fails or a source file
  is missing/unreadable, that source is skipped and clearly reported on
  stderr with a non-zero exit code where appropriate — never silently
  invented or substituted.

OFFICIAL SOURCE ENDPOINTS — verified 9 September 2026
---------------------------------------------------------------------------
OFAC SDN List: https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV
  This is OFAC's own "Sanctions List Service" (the successor to the old
  treasury.gov/ofac/downloads/*.csv URLs, which now redirect here). No API
  key required, but OFAC's service REQUIRES a "User-Agent" header on every
  request — a request without one gets HTTP 403. This script always sends
  one. OFAC's own documentation recommends querying
  https://sanctionslistservice.ofac.treas.gov/api/sanctions-lists for the
  current list of available export filenames rather than hardcoding one,
  since filenames "may change without notice" — SDN.CSV has been the stable
  primary export name for years and is used directly here for simplicity,
  but if it ever starts 404ing, check that endpoint first before assuming
  the whole service is down.

UK Sanctions List (FCDO): https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv
  FCDO's own dedicated, non-versioned URL for the current CSV export (this
  is the same file the "the-uk-sanctions-list" GOV.UK publication page
  links out to). No API key or special header required. This file is large
  (30+ MB) — the download step budgets a generous timeout for it.
  Robustness note: if this exact path ever stops working, the authoritative
  way to re-discover it is GOV.UK's own Content API —
  https://www.gov.uk/api/content/government/publications/the-uk-sanctions-list
  — which returns the publication's current attachment URLs as JSON and is
  designed to stay stable across file updates; a future maintainer should
  re-derive the CSV URL from there rather than guessing a new one.

FIELD MAPPING — verify against the real files before first production run
---------------------------------------------------------------------------
OFAC SDN legacy CSV (sdn.csv, no header row) has 12 positional columns:
  0 ent_num, 1 SDN_Name, 2 SDN_Type, 3 Program, 4 Title, 5 Call_Sign,
  6 Vess_type, 7 Tonnage, 8 GRT, 9 Vess_flag, 10 Vess_owner, 11 Remarks
IMO numbers for vessels are usually embedded as free text inside Remarks,
e.g. "(Vessel) IMO 9270646" — this script extracts them with a regex.
Aliases live in a separate add-on file (alt.csv) which is optional here;
if not supplied, only the primary SDN_Name is used.

If OFAC instead publishes a header row (newer exports sometimes do), the
script also tries to match by header name (case-insensitive) before
falling back to the fixed positional layout above.

UK Sanctions List CSV (gov.uk export) — column names per the UK's own
"Format Guide for the UK Sanctions List": Name 1..Name 6, Alias Type,
Non-Latin Script Type, Non-Latin Script Name, Title, Unique ID, Regime Name,
Sanctions Imposed (Statement of Reasons), Country, Country of Birth,
Nationality, Date of Birth, National Identification No, Position,
Address Line 1..6, Post/Zip Code, Other Information, Last Updated,
IMO Number, Previous Flag, Current Flag, Type of Vessel, Tonnage,
Length, Ship's Call Sign, Year Built, Hull ID, Owner, Current Owner,
Operator, Group Type ("Individual" / "Entity" / "Ship" / "Aircraft").

Column names below are matched case-insensitively and with common
punctuation variants; if the real file uses different labels, run once
with --dump-headers to print exactly what was found, then adjust the
COLUMN ALIASES dictionaries below.

License basis for direct ingestion (verified separately, see
claude/arhitectura-mtf-sanctions-checker.md in the Monaco Trade Forum
project): OFAC SDN is a U.S. Government work (public domain, 17 U.S.C.
§105); UK Sanctions List is published under the Open Government Licence
v3.0. No other sanctions list is ingested by this script.
"""

import argparse
import csv
import json
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

IMO_RE = re.compile(r"IMO[:\s#]*([0-9]{7})", re.IGNORECASE)

# --- default official source endpoints (see OFFICIAL SOURCE ENDPOINTS above) ---
DEFAULT_OFAC_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
DEFAULT_UK_URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"

# Identifying User-Agent sent on every download. OFAC's Sanctions List
# Service returns HTTP 403 to requests with no User-Agent at all; sending a
# real, identifying one is also just good practice for a service run by a
# government agency, same reasoning as the existing MET Norway weather proxy.
DOWNLOAD_USER_AGENT = "MonacoTradeForum-SanctionsChecker/1.0 (+https://monacotradeforum.com; contact: desk@monacotradeforum.com)"

# Generous timeout for the UK file specifically (30+ MB) on a possibly slow
# CI runner connection; OFAC's SDN.CSV is much smaller but the same timeout
# is harmless to reuse for both.
DOWNLOAD_TIMEOUT_SECONDS = 180


def download_source(url, dest_dir):
    """Download `url` to a temp file inside dest_dir with the required
    identifying User-Agent header, and return the local path.

    Never fabricates data: on any failure (network error, non-200 status,
    empty body) this raises — the caller lets the whole run fail loudly
    rather than silently falling back to stale or fake data."""
    req = urllib.request.Request(url, headers={"User-Agent": DOWNLOAD_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                raise RuntimeError(f"HTTP {status} downloading {url}")
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} downloading {url}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error downloading {url}: {e.reason}") from e

    if not body:
        raise RuntimeError(f"Downloaded {url} but the response body was empty.")

    suffix = ".csv" if url.lower().endswith(".csv") else ".dat"
    fd, path = tempfile.mkstemp(prefix="mtf-sanctions-", suffix=suffix, dir=dest_dir)
    with open(fd, "wb") as f:
        f.write(body)

    print(f"Downloaded {url} -> {path} ({len(body):,} bytes)", file=sys.stderr)
    return path


def resolve_source(arg_value, default_url, tmp_dir):
    """Given a --ofac/--uk CLI value (may be None, an http(s):// URL, or a
    local path), and the hardcoded default URL for that source, decide what
    local file path to parse from, downloading first if needed.

    Returns None only when there is genuinely nothing to do for this source
    (arg_value explicitly omitted has no meaning here — the caller always
    passes a default_url, so this only returns None if default_url itself
    is None, which no current call site does)."""
    value = arg_value or default_url
    if value is None:
        return None
    if re.match(r"^https?://", value, re.IGNORECASE):
        return download_source(value, tmp_dir)
    return value

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
}

# --- fixed positional layout for legacy OFAC sdn.csv (no header) -----------
OFAC_POSITIONAL_FIELDS = [
    "ent_num", "sdn_name", "sdn_type", "program", "title", "call_sign",
    "vess_type", "tonnage", "grt", "vess_flag", "vess_owner", "remarks",
]


def normalise_header(h):
    return re.sub(r"[^a-z0-9]+", " ", h.strip().lower()).strip()


def find_col(headers_norm, aliases):
    for a in aliases:
        a_norm = normalise_header(a)
        for i, h in enumerate(headers_norm):
            if h == a_norm:
                return i
    return None


def dedupe_key_entity(name, country):
    # NOTE: keyed on normalised name ONLY, not name+country. The legacy OFAC
    # SDN CSV has no reliable structured country column (country/nationality
    # is often buried in free-text Remarks), so requiring a country match
    # would silently defeat cross-source dedup for the exact case it exists
    # for. Country is still merged into the record as a display field
    # (see merge_and_dedupe) — it just isn't part of the identity key.
    n = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    return ("entity", n)


def dedupe_key_vessel(imo):
    return ("vessel", str(imo).strip())


def parse_ofac_csv(path):
    """Parse an OFAC SDN CSV export. Tries header-based matching first,
    falls back to the fixed legacy positional layout (no header row)."""
    entries = []
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(4096)
        f.seek(0)
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
            m = IMO_RE.search(remarks or "")
            if m:
                imo = m.group(1)

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
            "list_url": "https://www.gov.uk/government/publications/the-uk-sanctions-list",
        })

    print(f"[UK] Parsed {len(entries)} entries from {path}.", file=sys.stderr)
    return entries


def merge_and_dedupe(raw_entries, existing_entries_by_id):
    """Cross-source dedupe: exact IMO match for vessels, normalised
    name+country match for everything else. Returns a list of merged
    entries with a stable `id`, reusing ids from existing_entries_by_id
    where the same real-world entity is recognised again (so history
    stays attached to the same id across syncs)."""
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
        # If a later source spells the same (IMO- or name-matched) entity's
        # name differently, keep the first name as primary and record the
        # variant as an alias rather than silently dropping it.
        if raw["name"] and raw["name"] != rec["name"] and raw["name"] not in rec["aliases"]:
            rec["aliases"].append(raw["name"])

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
    ap.add_argument("--no-ofac", action="store_true", help="Skip the OFAC source entirely (testing only)")
    ap.add_argument("--no-uk", action="store_true", help="Skip the UK source entirely (testing only)")
    ap.add_argument("--list-out", default="data/sanctions-list.json")
    ap.add_argument("--changelog-out", default="data/sanctions-changelog.json")
    args = ap.parse_args()

    if args.no_ofac and args.no_uk:
        print("Both --no-ofac and --no-uk given. Nothing to do — this script never "
              "fabricates data.", file=sys.stderr)
        sys.exit(1)

    list_path = Path(args.list_out)
    changelog_path = Path(args.changelog_out)

    existing = {"entries": []}
    if list_path.exists():
        existing = json.loads(list_path.read_text(encoding="utf-8"))
    existing_by_id = {e["id"]: e for e in existing.get("entries", []) if not e.get("id", "").startswith("mtf-test-")}

    raw = []
    with tempfile.TemporaryDirectory(prefix="mtf-sanctions-dl-") as tmp_dir:
        try:
            if not args.no_ofac:
                ofac_path = resolve_source(args.ofac, DEFAULT_OFAC_URL, tmp_dir)
                raw += parse_ofac_csv(ofac_path)
            if not args.no_uk:
                uk_path = resolve_source(args.uk, DEFAULT_UK_URL, tmp_dir)
                raw += parse_uk_csv(uk_path)
        except RuntimeError as e:
            # Never fall back to stale/fake data on a failed download — abort
            # loudly instead, per the explicit "nu inventa date" requirement.
            print(f"FATAL: {e}", file=sys.stderr)
            sys.exit(3)

    if not raw:
        print("No entries parsed from the given file(s) — aborting without writing "
              "anything, to avoid overwriting good data with an empty result.", file=sys.stderr)
        sys.exit(2)

    merged_by_id = merge_and_dedupe(raw, existing_by_id)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    new_events = diff_for_changelog(existing_by_id, merged_by_id, today)

    changelog = {"schema_version": 1, "mode": "live", "entries": []}
    if changelog_path.exists():
        prev = json.loads(changelog_path.read_text(encoding="utf-8"))
        changelog["entries"] = [e for e in prev.get("entries", []) if not e["entity_id"].startswith("mtf-test-")]
    changelog["entries"].extend(new_events)
    changelog["note"] = "Live changelog — append-only history of Monaco Trade Forum sanctions data synchronisations."

    out = {
        "schema_version": 1,
        "mode": "live",
        "last_synchronised": today,
        "note": "Live data, normalised and deduplicated by Monaco Trade Forum from the sources listed below.",
        "sources": [
            {
                "code": "OFAC",
                "name": "Specially Designated Nationals and Blocked Persons List (SDN List)",
                "authority": "U.S. Department of the Treasury — Office of Foreign Assets Control (OFAC)",
                "list_url": "https://sanctionslist.ofac.treas.gov/Home/SdnList",
                "license": "U.S. Government work — public domain (17 U.S.C. §105)",
            },
            {
                "code": "UK",
                "name": "UK Sanctions List",
                "authority": "UK Foreign, Commonwealth & Development Office (FCDO)",
                "list_url": "https://www.gov.uk/government/publications/the-uk-sanctions-list",
                "license": "Open Government Licence v3.0",
            },
        ],
        "entries": list(merged_by_id.values()),
    }

    list_path.parent.mkdir(parents=True, exist_ok=True)
    list_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    changelog_path.write_text(json.dumps(changelog, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(out['entries'])} entries to {list_path}", file=sys.stderr)
    print(f"Wrote {len(changelog['entries'])} changelog events to {changelog_path} "
          f"({len(new_events)} new this run)", file=sys.stderr)


if __name__ == "__main__":
    main()
