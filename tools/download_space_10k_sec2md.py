#!/usr/bin/env python3
"""Download latest space-sector 10-K filings from SEC EDGAR and convert to Markdown."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_TICKERS = [
    "ASTS",  # AST SpaceMobile
    "RKLB",  # Rocket Lab USA
    "LUNR",  # Intuitive Machines
    "RDW",  # Redwire
    "PL",  # Planet Labs
    "BKSY",  # BlackSky Technology
    "SPCE",  # Virgin Galactic
    "IRDM",  # Iridium Communications
    "VSAT",  # Viasat
    "GSAT",  # Globalstar
]

DEFAULT_USER_AGENT = "rag-space-10k-downloader/1.0 contact:local@example.com"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik_padded}.json"
SEC_ARCHIVE_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_compact}/{primary_doc}"
)


@dataclass(frozen=True)
class Filing:
    ticker: str
    company: str
    cik: int
    accession_number: str
    filing_date: str
    report_date: str
    form: str
    primary_doc: str
    source_url: str


def fetch_json(url: str, user_agent: str) -> Any:
    body = fetch_bytes(url, user_agent)
    return json.loads(body.decode("utf-8"))


def fetch_bytes(url: str, user_agent: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "identity",
            "Accept": "application/json,text/html,application/xhtml+xml,*/*",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} for {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return re.sub(r"_+", "_", value).strip("_")


def load_company_lookup(user_agent: str) -> dict[str, dict[str, Any]]:
    raw = fetch_json(SEC_TICKERS_URL, user_agent)
    lookup: dict[str, dict[str, Any]] = {}
    for item in raw.values():
        ticker = item["ticker"].upper()
        lookup[ticker] = {
            "cik": int(item["cik_str"]),
            "title": item["title"],
        }
    return lookup


def latest_10k_for_ticker(
    ticker: str, company_lookup: dict[str, dict[str, Any]], user_agent: str
) -> Filing | None:
    company = company_lookup.get(ticker.upper())
    if not company:
        return None

    cik = company["cik"]
    submissions_url = SEC_SUBMISSIONS_URL.format(cik_padded=f"{cik:010d}")
    submissions = fetch_json(submissions_url, user_agent)
    recent = submissions["filings"]["recent"]

    for i, form in enumerate(recent["form"]):
        if form != "10-K":
            continue

        accession = recent["accessionNumber"][i]
        primary_doc = recent["primaryDocument"][i]
        accession_compact = accession.replace("-", "")
        source_url = SEC_ARCHIVE_URL.format(
            cik_int=cik,
            accession_compact=accession_compact,
            primary_doc=primary_doc,
        )
        return Filing(
            ticker=ticker.upper(),
            company=company["title"],
            cik=cik,
            accession_number=accession,
            filing_date=recent["filingDate"][i],
            report_date=recent["reportDate"][i],
            form=form,
            primary_doc=primary_doc,
            source_url=source_url,
        )

    return None


def convert_to_markdown(source_url: str, user_agent: str) -> str:
    try:
        import sec2md
    except ImportError as exc:
        raise RuntimeError(
            "sec2md is not installed. Install it with: python -m pip install sec2md"
        ) from exc

    if not hasattr(sec2md, "convert_to_markdown"):
        raise RuntimeError("Installed sec2md package does not expose convert_to_markdown")

    return sec2md.convert_to_markdown(source_url, user_agent=user_agent)


def write_metadata_csv(path: Path, filings: list[Filing]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "company",
                "cik",
                "form",
                "report_date",
                "filing_date",
                "accession_number",
                "primary_doc",
                "source_url",
            ],
        )
        writer.writeheader()
        for filing in filings:
            writer.writerow(filing.__dict__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="data/space_10k_reports",
        help="Folder where raw filings, Markdown, and metadata will be written.",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=DEFAULT_TICKERS,
        help="Ticker symbols to fetch. Defaults to a curated U.S.-listed space set.",
    )
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("SEC_USER_AGENT", DEFAULT_USER_AGENT),
        help="SEC User-Agent. Prefer setting SEC_USER_AGENT='Name email@example.com'.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Delay between SEC requests in seconds.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    raw_dir = output_dir / "raw"
    markdown_dir = output_dir / "markdown"
    metadata_dir = output_dir / "metadata"
    for directory in (raw_dir, markdown_dir, metadata_dir):
        directory.mkdir(parents=True, exist_ok=True)

    print(f"Using SEC User-Agent: {args.user_agent}")
    print(f"Loading SEC company ticker lookup for {len(args.tickers)} tickers...")
    company_lookup = load_company_lookup(args.user_agent)

    filings: list[Filing] = []
    misses: list[str] = []
    for ticker in args.tickers:
        try:
            filing = latest_10k_for_ticker(ticker, company_lookup, args.user_agent)
        except RuntimeError as exc:
            print(f"[{ticker}] failed to resolve filing: {exc}", file=sys.stderr)
            misses.append(ticker.upper())
            continue

        if not filing:
            print(f"[{ticker}] no 10-K found")
            misses.append(ticker.upper())
            continue

        filings.append(filing)
        print(
            f"[{filing.ticker}] latest 10-K: {filing.report_date} "
            f"filed {filing.filing_date} ({filing.accession_number})"
        )
        time.sleep(args.delay)

    for filing in filings:
        base_name = slug(
            f"{filing.ticker}_{filing.report_date or filing.filing_date}_"
            f"{filing.accession_number}"
        )
        raw_path = raw_dir / f"{base_name}.htm"
        md_path = markdown_dir / f"{base_name}.md"

        print(f"[{filing.ticker}] downloading raw filing...")
        raw_path.write_bytes(fetch_bytes(filing.source_url, args.user_agent))
        time.sleep(args.delay)

        print(f"[{filing.ticker}] converting to Markdown with sec2md...")
        markdown = convert_to_markdown(filing.source_url, args.user_agent)
        header = (
            f"---\n"
            f"ticker: {filing.ticker}\n"
            f"company: {json.dumps(filing.company)}\n"
            f"cik: {filing.cik}\n"
            f"form: {filing.form}\n"
            f"report_date: {filing.report_date}\n"
            f"filing_date: {filing.filing_date}\n"
            f"accession_number: {filing.accession_number}\n"
            f"source_url: {filing.source_url}\n"
            f"---\n\n"
        )
        md_path.write_text(header + markdown, encoding="utf-8")
        time.sleep(args.delay)

    write_metadata_csv(metadata_dir / "filings.csv", filings)
    (metadata_dir / "misses.json").write_text(
        json.dumps({"missing_10k": misses}, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {len(filings)} Markdown files to {markdown_dir}")
    if misses:
        print(f"Tickers without a downloaded 10-K: {', '.join(misses)}")
    return 0 if filings else 1


if __name__ == "__main__":
    raise SystemExit(main())
