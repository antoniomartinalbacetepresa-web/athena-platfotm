from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from app.services.sec_13f_information_table_service import (
    Sec13fInformationTableService,
)
from app.services.sec_edgar_service import SecEdgarService


class Sec13fFilingService:
    """Resolve and parse one SEC 13F information table from an accession.

    ATHENA never assumes that the first XML document in a filing is the 13F
    information table. The official accession index is inspected, candidate
    XML documents are fetched only from the same SEC archive directory, and
    exactly one document containing one or more ``infoTable`` elements must be
    identifiable. Ambiguity fails closed.
    """

    _ARCHIVE_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
    _ACCESSION_PATTERN = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    _SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
    _MAX_INDEX_ITEMS = 250
    _MAX_XML_BYTES = 10 * 1024 * 1024

    def __init__(
        self,
        client: httpx.Client | None = None,
        parser: Sec13fInformationTableService | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=20.0)
        self._parser = parser or Sec13fInformationTableService()
        self._user_agent = (
            user_agent
            or os.getenv("ATHENA_SEC_USER_AGENT")
            or "ATHENA-TYCHE research-client"
        ).strip()

    def fetch_and_parse(
        self,
        *,
        cik: str | int,
        filing: dict[str, Any],
        retrieved_at: datetime,
    ) -> dict[str, Any]:
        retrieved = self._require_utc_datetime(retrieved_at)
        accession = self._validate_filing_and_accession(filing)
        archive_cik = str(int(SecEdgarService.normalize_cik(cik)))
        accession_compact = accession.replace("-", "")
        directory_url = f"{self._ARCHIVE_BASE_URL}/{archive_cik}/{accession_compact}"
        index_url = f"{directory_url}/index.json"

        index_payload = self._get_json(index_url)
        names = self._candidate_xml_names(index_payload, filing)
        if not names:
            raise ValueError("SEC 13F accession contains no candidate XML documents.")

        matches: list[tuple[str, str]] = []
        for name in names:
            source_url = f"{directory_url}/{name}"
            xml_text = self._get_text(source_url)
            if self._looks_like_information_table(xml_text):
                matches.append((source_url, xml_text))

        if len(matches) != 1:
            if not matches:
                raise ValueError(
                    "SEC 13F accession contains no verifiable information table XML."
                )
            raise ValueError(
                "SEC 13F accession contains multiple information table XML documents."
            )

        source_url, xml_text = matches[0]
        parsed = self._parser.parse(
            xml_text,
            filing=filing,
            retrieved_at=retrieved,
            source_url=source_url,
        )

        if parsed.get("advisoryStatus") != "no_advice":
            raise ValueError("SEC 13F parser violated no_advice invariant.")
        if parsed.get("productionEligible") is not False:
            raise ValueError("SEC 13F parser violated production eligibility invariant.")
        if parsed.get("athenaRecommendationInfluence") is not False:
            raise ValueError("SEC 13F parser attempted to influence ATHENA scoring.")
        if parsed.get("automaticTrading") is not False:
            raise ValueError("SEC 13F parser attempted to enable automatic trading.")
        identity_policy = parsed.get("identityPolicy")
        if not isinstance(identity_policy, dict) or identity_policy.get("isWeightingReady") is not False:
            raise ValueError("SEC 13F parser violated weighting readiness invariant.")

        return {
            **parsed,
            "accessionIndexUrl": index_url,
            "documentSelectionPolicy": (
                "official_accession_index_then_unique_information_table_xml"
            ),
        }

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _candidate_xml_names(
        self,
        payload: dict[str, Any],
        filing: dict[str, Any],
    ) -> list[str]:
        directory = payload.get("directory")
        if not isinstance(directory, dict):
            raise ValueError("SEC accession index directory is missing.")
        items = directory.get("item")
        if not isinstance(items, list):
            raise ValueError("SEC accession index items are missing.")
        if len(items) > self._MAX_INDEX_ITEMS:
            raise ValueError("SEC accession index contains too many documents.")

        primary_document = str(filing.get("primaryDocument") or "").strip()
        names: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name == primary_document:
                continue
            if not name.lower().endswith(".xml"):
                continue
            if not self._SAFE_FILENAME_PATTERN.fullmatch(name):
                raise ValueError("SEC accession index contains an unsafe filename.")
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    def _get_json(self, url: str) -> dict[str, Any]:
        self._validate_sec_archive_url(url)
        response = self._client.get(url, headers=self._headers("application/json"))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected SEC accession index response format.")
        return payload

    def _get_text(self, url: str) -> str:
        self._validate_sec_archive_url(url)
        response = self._client.get(
            url,
            headers=self._headers("application/xml,text/xml;q=0.9,*/*;q=0.1"),
        )
        response.raise_for_status()
        content = response.content
        if len(content) > self._MAX_XML_BYTES:
            raise ValueError("SEC 13F candidate XML exceeds the size limit.")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("SEC 13F candidate XML is not valid UTF-8.") from exc

    def _looks_like_information_table(self, xml_text: str) -> bool:
        if not xml_text.strip():
            return False
        upper = xml_text.upper()
        if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
            raise ValueError("SEC 13F XML declarations with DTD/entities are forbidden.")
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return False

        has_information_table_root = self._local_name(root.tag) == "informationTable"
        has_holding = any(
            self._local_name(node.tag) == "infoTable" for node in root.iter()
        )
        return has_information_table_root and has_holding

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def _headers(self, accept: str) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": accept,
        }

    @classmethod
    def _validate_filing_and_accession(cls, filing: dict[str, Any]) -> str:
        if not isinstance(filing, dict):
            raise ValueError("SEC filing metadata must be an object.")
        form = str(filing.get("form") or "").strip().upper()
        if form not in {"13F-HR", "13F-HR/A"}:
            raise ValueError("SEC filing is not a 13F-HR filing.")
        accession = str(filing.get("accessionNumber") or "").strip()
        if not cls._ACCESSION_PATTERN.fullmatch(accession):
            raise ValueError("SEC 13F accession number is invalid.")
        return accession

    @staticmethod
    def _require_utc_datetime(value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware UTC.")
        if value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("retrieved_at must be expressed in UTC.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _validate_sec_archive_url(url: str) -> None:
        parsed = urlparse(url)
        if (
            parsed.scheme.lower() != "https"
            or (parsed.hostname or "").lower() != "www.sec.gov"
            or not parsed.path.startswith("/Archives/edgar/data/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("SEC archive URL is not approved.")
