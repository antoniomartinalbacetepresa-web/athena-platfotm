from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree


class Sec13fInformationTableService:
    """Parse SEC 13F information tables without inventing instrument identity.

    The parser deliberately keeps CUSIP as the holding identifier. Mapping a
    CUSIP to an ATHENA instrument is a separate identity step and must be backed
    by authoritative evidence; issuer-name or ticker heuristics are forbidden.
    """

    _MAX_XML_BYTES = 10 * 1024 * 1024
    _CUSIP_PATTERN = re.compile(r"^[A-Z0-9*@#]{9}$")
    _ALLOWED_SEC_HOSTS = {"sec.gov", "www.sec.gov"}

    def parse(
        self,
        xml_text: str,
        *,
        filing: dict[str, Any],
        retrieved_at: datetime,
        source_url: str,
    ) -> dict[str, Any]:
        if not isinstance(xml_text, str) or not xml_text.strip():
            raise ValueError("SEC 13F information table XML is empty.")
        if len(xml_text.encode("utf-8")) > self._MAX_XML_BYTES:
            raise ValueError("SEC 13F information table exceeds the size limit.")

        upper_xml = xml_text.upper()
        if "<!DOCTYPE" in upper_xml or "<!ENTITY" in upper_xml:
            raise ValueError("SEC 13F XML declarations with DTD/entities are forbidden.")

        retrieved = self._require_utc_datetime(retrieved_at, "retrieved_at")
        self._validate_source_url(source_url)
        normalized_filing = self._normalize_filing(filing, retrieved)

        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as exc:
            raise ValueError("SEC 13F information table XML is malformed.") from exc

        holdings: list[dict[str, Any]] = []
        seen_rows: set[tuple[Any, ...]] = set()
        for node in root.iter():
            if self._local_name(node.tag) != "infoTable":
                continue
            holding = self._parse_holding(node)
            row_key = (
                holding["cusip"],
                holding["issuerName"],
                holding["titleOfClass"],
                holding["valueThousandsUsd"],
                holding["shareOrPrincipalAmount"],
                holding["shareOrPrincipalType"],
                holding["putCall"],
                holding["investmentDiscretion"],
                holding["votingAuthority"]["sole"],
                holding["votingAuthority"]["shared"],
                holding["votingAuthority"]["none"],
            )
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            holdings.append(holding)

        if not holdings:
            raise ValueError("SEC 13F information table contains no holdings.")

        return {
            "status": "sec_13f_information_table_parsed",
            "form": normalized_filing["form"],
            "accessionNumber": normalized_filing["accessionNumber"],
            "positionDate": normalized_filing["reportDate"],
            "filingDate": normalized_filing["filingDate"],
            "publicationDateTime": normalized_filing["acceptanceDateTime"],
            "retrievedAt": retrieved.isoformat().replace("+00:00", "Z"),
            "sourceUrl": source_url,
            "sourceProvider": "SEC EDGAR",
            "valueUnit": "thousands_usd_as_reported_by_sec_13f",
            "holdingCount": len(holdings),
            "holdings": holdings,
            "identityPolicy": {
                "identifier": "cusip_as_reported",
                "canonicalInstrumentResolved": False,
                "tickerResolution": "disabled_until_authoritative_identity_evidence",
                "isWeightingReady": False,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "athenaRecommendationInfluence": False,
            "automaticScoring": False,
            "automaticTrading": False,
        }

    def _parse_holding(self, node: ElementTree.Element) -> dict[str, Any]:
        issuer_name = self._required_text(node, "nameOfIssuer")
        title_of_class = self._required_text(node, "titleOfClass")
        cusip = self._required_text(node, "cusip").upper()
        if not self._CUSIP_PATTERN.fullmatch(cusip):
            raise ValueError("SEC 13F holding contains an invalid CUSIP.")

        value_thousands = self._nonnegative_integer(
            self._required_text(node, "value"), "value"
        )
        amount = self._nonnegative_number(
            self._required_text(node, "sshPrnamt"), "sshPrnamt"
        )
        amount_type = self._required_text(node, "sshPrnamtType").upper()
        if amount_type not in {"SH", "PRN"}:
            raise ValueError("SEC 13F holding has an unsupported sshPrnamtType.")

        voting_node = self._first_descendant(node, "votingAuthority")
        if voting_node is None:
            raise ValueError("SEC 13F holding is missing votingAuthority.")

        return {
            "cusip": cusip,
            "issuerName": issuer_name,
            "titleOfClass": title_of_class,
            "valueThousandsUsd": value_thousands,
            "shareOrPrincipalAmount": amount,
            "shareOrPrincipalType": amount_type,
            "putCall": self._optional_text(node, "putCall"),
            "investmentDiscretion": self._required_text(node, "investmentDiscretion"),
            "otherManager": self._optional_text(node, "otherManager"),
            "votingAuthority": {
                "sole": self._nonnegative_number(
                    self._required_text(voting_node, "Sole"), "votingAuthority.Sole"
                ),
                "shared": self._nonnegative_number(
                    self._required_text(voting_node, "Shared"), "votingAuthority.Shared"
                ),
                "none": self._nonnegative_number(
                    self._required_text(voting_node, "None"), "votingAuthority.None"
                ),
            },
            "canonicalInstrumentId": None,
            "ticker": None,
            "identityResolved": False,
        }

    def _normalize_filing(
        self, filing: dict[str, Any], retrieved_at: datetime
    ) -> dict[str, str]:
        if not isinstance(filing, dict):
            raise ValueError("SEC filing metadata must be an object.")
        form = str(filing.get("form") or "").strip().upper()
        if form not in {"13F-HR", "13F-HR/A"}:
            raise ValueError("SEC filing is not a 13F-HR filing.")

        accession = str(filing.get("accessionNumber") or "").strip()
        filing_date = str(filing.get("filingDate") or "").strip()
        report_date = str(filing.get("reportDate") or "").strip()
        acceptance_raw = str(filing.get("acceptanceDateTime") or "").strip()
        if not accession or not filing_date or not report_date or not acceptance_raw:
            raise ValueError("SEC 13F filing metadata is incomplete.")

        self._parse_iso_date(filing_date, "filingDate")
        self._parse_iso_date(report_date, "reportDate")
        acceptance = self._parse_sec_acceptance(acceptance_raw)
        if acceptance > retrieved_at:
            raise ValueError("SEC 13F retrieval precedes filing publication.")

        return {
            "form": form,
            "accessionNumber": accession,
            "filingDate": filing_date,
            "reportDate": report_date,
            "acceptanceDateTime": acceptance.isoformat().replace("+00:00", "Z"),
        }

    @staticmethod
    def _parse_iso_date(value: str, field: str) -> None:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"SEC 13F {field} is invalid.") from exc

    @staticmethod
    def _parse_sec_acceptance(value: str) -> datetime:
        try:
            parsed = datetime.strptime(value, "%Y%m%d%H%M%S")
        except ValueError as exc:
            raise ValueError("SEC 13F acceptanceDateTime is invalid.") from exc
        return parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _require_utc_datetime(value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"{field} must be timezone-aware UTC.")
        normalized = value.astimezone(timezone.utc)
        if value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError(f"{field} must be expressed in UTC.")
        return normalized

    def _validate_source_url(self, source_url: str) -> None:
        parsed = urlparse(str(source_url).strip())
        if (
            parsed.scheme.lower() != "https"
            or (parsed.hostname or "").lower() not in self._ALLOWED_SEC_HOSTS
            or not parsed.path.startswith("/Archives/edgar/data/")
        ):
            raise ValueError("SEC 13F source URL is not an approved EDGAR archive URL.")

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def _first_descendant(
        self, node: ElementTree.Element, local_name: str
    ) -> ElementTree.Element | None:
        for child in node.iter():
            if child is node:
                continue
            if self._local_name(child.tag) == local_name:
                return child
        return None

    def _required_text(self, node: ElementTree.Element, local_name: str) -> str:
        value = self._optional_text(node, local_name)
        if not value:
            raise ValueError(f"SEC 13F holding is missing {local_name}.")
        return value

    def _optional_text(self, node: ElementTree.Element, local_name: str) -> str | None:
        child = self._first_descendant(node, local_name)
        if child is None or child.text is None:
            return None
        value = child.text.strip()
        return value or None

    @staticmethod
    def _nonnegative_integer(value: str, field: str) -> int:
        if not re.fullmatch(r"[0-9]+", value.strip()):
            raise ValueError(f"SEC 13F {field} must be a non-negative integer.")
        return int(value)

    @staticmethod
    def _nonnegative_number(value: str, field: str) -> int | float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"SEC 13F {field} must be numeric.") from exc
        if not math.isfinite(parsed) or parsed < 0:
            raise ValueError(f"SEC 13F {field} must be finite and non-negative.")
        if parsed.is_integer():
            return int(parsed)
        return parsed
