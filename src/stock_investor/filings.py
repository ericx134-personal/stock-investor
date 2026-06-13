from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


MONITORED_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A"}

ITEM_CATEGORIES = {
    "1.01": "MATERIAL_AGREEMENT",
    "1.02": "MATERIAL_AGREEMENT_TERMINATED",
    "1.03": "BANKRUPTCY_OR_RECEIVERSHIP",
    "1.05": "MATERIAL_CYBERSECURITY_INCIDENT",
    "2.01": "ACQUISITION_OR_DISPOSITION",
    "2.02": "EARNINGS_RELEASE",
    "2.03": "NEW_FINANCIAL_OBLIGATION",
    "2.04": "FINANCIAL_OBLIGATION_TRIGGER",
    "2.05": "RESTRUCTURING_COSTS",
    "2.06": "MATERIAL_IMPAIRMENT",
    "3.01": "DELISTING_OR_LISTING_FAILURE",
    "3.02": "UNREGISTERED_SECURITY_SALE",
    "3.03": "SHAREHOLDER_RIGHTS_MODIFIED",
    "4.01": "AUDITOR_CHANGE",
    "4.02": "FINANCIAL_STATEMENTS_NOT_RELIABLE",
    "5.01": "CHANGE_IN_CONTROL",
    "5.02": "LEADERSHIP_CHANGE",
    "5.03": "GOVERNANCE_DOCUMENT_CHANGE",
    "5.07": "SHAREHOLDER_VOTE",
    "5.08": "DIRECTOR_NOMINATION_DEADLINE",
    "7.01": "REGULATION_FD_DISCLOSURE",
    "8.01": "OTHER_MATERIAL_EVENT",
    "9.01": "FINANCIAL_STATEMENTS_AND_EXHIBITS",
}

HIGH_IMPORTANCE_ITEMS = {
    "1.03",
    "1.05",
    "2.01",
    "2.04",
    "2.06",
    "3.01",
    "4.02",
    "5.01",
}


@dataclass(frozen=True)
class FilingEvent:
    symbol: str
    cik: str
    accession_number: str
    form: str
    filed_at: str
    primary_document: str
    url: str
    items: tuple[str, ...] = ()
    event_categories: tuple[str, ...] = ()
    importance: str = "INFO"


def _classify_filing(
    form: str, raw_items: str
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    items = tuple(
        dict.fromkeys(item.strip() for item in raw_items.split(",") if item.strip())
    )
    if form.startswith(("10-K", "10-Q")):
        return items, ("PERIODIC_FINANCIAL_REPORT",), "MEDIUM"
    categories = tuple(
        dict.fromkeys(
            ITEM_CATEGORIES.get(item, f"UNMAPPED_8K_ITEM_{item}")
            for item in items
        )
    )
    if not categories:
        categories = ("UNCLASSIFIED_CURRENT_REPORT",)
    importance = (
        "HIGH"
        if any(item in HIGH_IMPORTANCE_ITEMS for item in items)
        else "MEDIUM"
    )
    return items, categories, importance


def extract_recent_filings(symbol: str, cik: str, payload: dict) -> list[FilingEvent]:
    recent = payload.get("filings", {}).get("recent", {})
    keys = (
        "accessionNumber",
        "form",
        "filingDate",
        "primaryDocument",
    )
    if any(key not in recent for key in keys):
        return []
    events = []
    padded_cik = cik.zfill(10)
    archive_cik = str(int(cik))
    raw_items = recent.get("items", ())
    for index, (accession, form, filed_at, document) in enumerate(
        zip(
            recent["accessionNumber"],
            recent["form"],
            recent["filingDate"],
            recent["primaryDocument"],
        )
    ):
        if form not in MONITORED_FORMS:
            continue
        items, categories, importance = _classify_filing(
            form, raw_items[index] if index < len(raw_items) else ""
        )
        accession_path = accession.replace("-", "")
        events.append(
            FilingEvent(
                symbol=symbol,
                cik=padded_cik,
                accession_number=accession,
                form=form,
                filed_at=filed_at,
                primary_document=document,
                url=(
                    f"https://www.sec.gov/Archives/edgar/data/{archive_cik}/"
                    f"{accession_path}/{document}"
                ),
                items=items,
                event_categories=categories,
                importance=importance,
            )
        )
    return sorted(events, key=lambda event: event.filed_at, reverse=True)


def update_filing_state(
    events: list[FilingEvent], path: str | Path
) -> list[FilingEvent]:
    """Return unseen filings and persist all accession numbers.

    The first run establishes a baseline and intentionally returns no alerts.
    """
    output = Path(path)
    existing = set()
    initialized = output.exists()
    if initialized:
        existing = set(json.loads(output.read_text()).get("seen_accessions", ()))
    unseen = [event for event in events if event.accession_number not in existing]
    existing.update(event.accession_number for event in events)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"seen_accessions": sorted(existing)}, indent=2) + "\n"
    )
    return unseen if initialized else []


def append_filing_alerts(events: list[FilingEvent], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a") as handle:
        for event in events:
            handle.write(json.dumps(asdict(event), sort_keys=True) + "\n")
