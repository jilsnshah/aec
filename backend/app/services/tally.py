"""Talking to TallyPrime over its built-in HTTP server (XML).

TallyPrime has no hosted cloud API: every integration talks to a running
TallyPrime with the company open, through the HTTP server it can expose
(F1 > Settings > Connectivity > "TallyPrime acts as" Server, port 9000 by
default). XML works on every release; JSON only from Release 7.0, so this
client uses XML.

The protocol, from Tally's integration documentation:

* imports go as ``TALLYREQUEST Import``, ``TYPE Data`` and ``ID Vouchers`` or
  ``All Masters``, with ``SVCURRENTCOMPANY`` naming the company;
* debit lines carry ``ISDEEMEDPOSITIVE Yes`` and a negative ``AMOUNT``,
  credit lines ``No`` and a positive amount;
* the reply holds an ``IMPORTRESULT`` (``CREATED``, ``ERRORS``,
  ``LASTVCHID``), and any ``LINEERROR`` carries Tally's reason for refusing.

Tally's HTTP server has no authentication of its own. It must only be
reachable by this application (firewall or IP allow-list), or sit behind a
gateway; ``auth_token`` is sent as a bearer token for such a gateway.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence
from xml.sax.saxutils import escape, quoteattr

import httpx
from defusedxml import ElementTree

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30

#: Builds the HTTP client. Tests replace it with one on a mock transport.
client_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=TIMEOUT_SECONDS)


class TallyError(Exception):
    """Tally could not be reached, or refused the request (message from Tally)."""


@dataclass
class Line:
    item: str
    unit: str
    quantity: Decimal
    rate: Decimal
    amount: Decimal


@dataclass
class ImportResult:
    created: int
    altered: int
    master_id: Optional[str]


def _text(value: Any) -> str:
    return escape("" if value is None else str(value))


def _money(value: Decimal) -> str:
    return str(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _qty(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


def _tally_date(value: date) -> str:
    return value.strftime("%Y%m%d")


class TallyClient:
    def __init__(self, server_url: str, company: str, auth_token: Optional[str] = None):
        self.url = server_url.rstrip("/")
        self.company = company
        self.auth_token = auth_token

    # --- transport -------------------------------------------------------------

    def _post(self, body: str):
        headers = {"Content-Type": "text/xml; charset=utf-8"}
        if self.auth_token:
            headers["Authorization"] = "Bearer " + self.auth_token
        try:
            with client_factory() as client:
                response = client.post(self.url, content=body.encode("utf-8"), headers=headers)
        except httpx.HTTPError as exc:
            raise TallyError("Could not reach Tally at {}: {}".format(self.url, exc)) from exc
        if response.status_code >= 400:
            raise TallyError("Tally answered HTTP {}.".format(response.status_code))
        try:
            return ElementTree.fromstring(response.content)
        except Exception as exc:  # not XML: something else is listening there
            raise TallyError("The reply from {} is not Tally XML.".format(self.url)) from exc

    def _envelope(self, request: str, kind: str, report_id: str, desc: str = "", data: str = "") -> str:
        static = "<STATICVARIABLES><SVCURRENTCOMPANY>{}</SVCURRENTCOMPANY></STATICVARIABLES>".format(
            _text(self.company)
        ) if self.company else ""
        return (
            "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>{}</TALLYREQUEST>"
            "<TYPE>{}</TYPE><ID>{}</ID></HEADER><BODY><DESC>{}{}</DESC>{}</BODY></ENVELOPE>"
        ).format(request, kind, _text(report_id), static, desc, data)

    def _import(self, report_id: str, message: str) -> ImportResult:
        root = self._post(
            self._envelope("Import", "Data", report_id, data="<DATA><TALLYMESSAGE>{}</TALLYMESSAGE></DATA>".format(message))
        )
        errors = [node.text.strip() for node in root.iter("LINEERROR") if node.text and node.text.strip()]
        result = next(root.iter("IMPORTRESULT"), root)

        def number(tag: str) -> int:
            node = result.find(tag) if result is not root else next(root.iter(tag), None)
            try:
                return int((node.text or "0").strip()) if node is not None else 0
            except ValueError:
                return 0

        if errors or number("ERRORS"):
            raise TallyError("Tally refused it: " + ("; ".join(errors) or "{} error(s), no detail.".format(number("ERRORS"))))
        if not (number("CREATED") or number("ALTERED")):
            raise TallyError("Tally created nothing. Check that the company '{}' is open.".format(self.company))
        last = result.find("LASTVCHID") if result is not root else next(root.iter("LASTVCHID"), None)
        master_id = (last.text or "").strip() if last is not None else None
        return ImportResult(number("CREATED"), number("ALTERED"), master_id if master_id not in ("", "0") else None)

    def _collection(self, name: str, object_type: str, fetch: str, filter_formula: Optional[str] = None):
        tdl = '<COLLECTION NAME={}><TYPE>{}</TYPE><FETCH>{}</FETCH>{}</COLLECTION>'.format(
            quoteattr(name), object_type, fetch, "<FILTER>Match</FILTER>" if filter_formula else ""
        )
        if filter_formula:
            tdl += '<SYSTEM TYPE="Formulae" NAME="Match">{}</SYSTEM>'.format(_text(filter_formula))
        return self._post(self._envelope("Export", "Collection", name, desc="<TDL><TDLMESSAGE>{}</TDLMESSAGE></TDL>".format(tdl)))

    # --- reading -----------------------------------------------------------------

    def companies(self) -> List[str]:
        """The companies open in this Tally."""
        saved, self.company = self.company, ""
        try:
            root = self._collection("AECCompanies", "Company", "Name")
        finally:
            self.company = saved
        return [node.get("NAME") or (node.findtext("NAME") or "") for node in root.iter("COMPANY")]

    def exists(self, object_type: str, name: str) -> bool:
        tag = object_type.upper().replace(" ", "")
        formula = "$Name = {}".format('"' + name.replace('"', "") + '"')
        root = self._collection("AECExists", object_type, "Name", formula)
        return any(True for _ in root.iter(tag))

    def voucher_number(self, master_id: str) -> Optional[str]:
        """The number Tally gave a voucher, by its master id."""
        root = self._collection("AECVoucher", "Voucher", "VoucherNumber", "$MasterId = {}".format(int(master_id)))
        for node in root.iter("VOUCHERNUMBER"):
            if node.text and node.text.strip():
                return node.text.strip()
        return None

    # --- masters -----------------------------------------------------------------

    def ensure_unit(self, unit: str) -> None:
        if not self.exists("Unit", unit):
            self._import("All Masters", '<UNIT NAME={0} ACTION="Create"><NAME>{1}</NAME><ISSIMPLEUNIT>Yes</ISSIMPLEUNIT></UNIT>'.format(quoteattr(unit), _text(unit)))

    def ensure_ledger(self, name: str, group: str, phone: Optional[str] = None, email: Optional[str] = None) -> None:
        if self.exists("Ledger", name):
            return
        extra = ""
        if phone:
            extra += "<LEDGERMOBILE>{}</LEDGERMOBILE>".format(_text(phone))
        if email:
            extra += "<EMAIL>{}</EMAIL>".format(_text(email))
        self._import(
            "All Masters",
            '<LEDGER NAME={0} ACTION="Create"><NAME.LIST><NAME>{1}</NAME></NAME.LIST><PARENT>{2}</PARENT>'
            "<ISBILLWISEON>Yes</ISBILLWISEON>{3}</LEDGER>".format(quoteattr(name), _text(name), _text(group), extra),
        )

    def ensure_stock_item(self, name: str, unit: str) -> None:
        if self.exists("Stock Item", name):
            return
        self.ensure_unit(unit)
        self._import(
            "All Masters",
            '<STOCKITEM NAME={0} ACTION="Create"><NAME.LIST><NAME>{1}</NAME></NAME.LIST>'
            "<BASEUNITS>{2}</BASEUNITS></STOCKITEM>".format(quoteattr(name), _text(name), _text(unit)),
        )

    # --- vouchers ----------------------------------------------------------------

    def create_voucher(
        self,
        voucher_type: str,
        on: date,
        party: str,
        item_ledger: str,
        lines: Sequence[Line],
        party_is_debit: bool,
        godown: str,
        number: Optional[str] = None,
        reference: Optional[str] = None,
        narration: Optional[str] = None,
        order_number: Optional[str] = None,
        order_due: Optional[date] = None,
        taxes: Sequence[tuple] = (),
    ) -> ImportResult:
        """Create an invoice-style voucher: a party, stock lines and their ledger.

        ``party_is_debit`` is True for sales (the customer owes) and False for
        purchases (we owe the supplier). ``taxes`` are (ledger, amount) pairs on
        the side opposite the party.
        """
        item_total = sum((line.amount for line in lines), Decimal("0"))
        tax_total = sum((Decimal(amount) for _, amount in taxes), Decimal("0"))
        total = item_total + tax_total
        # Debits are negative with ISDEEMEDPOSITIVE Yes; credits the reverse.
        party_sign, item_sign = ("-", "") if party_is_debit else ("", "-")
        party_deemed, item_deemed = ("Yes", "No") if party_is_debit else ("No", "Yes")

        inventory = []
        for line in lines:
            batch = (
                "<BATCHALLOCATIONS.LIST><GODOWNNAME>{godown}</GODOWNNAME><BATCHNAME>Primary Batch</BATCHNAME>"
                "{order}<AMOUNT>{sign}{amount}</AMOUNT><ACTUALQTY>{qty}</ACTUALQTY><BILLEDQTY>{qty}</BILLEDQTY>"
                "</BATCHALLOCATIONS.LIST>"
            ).format(
                godown=_text(godown),
                order=(
                    "<ORDERNO>{}</ORDERNO>".format(_text(order_number))
                    + ("<ORDERDUEDATE>{}</ORDERDUEDATE>".format(_tally_date(order_due)) if order_due else "")
                ) if order_number else "",
                sign=item_sign,
                amount=_money(line.amount),
                qty=_text("{} {}".format(_qty(line.quantity), line.unit)),
            )
            inventory.append(
                "<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>{item}</STOCKITEMNAME>"
                "<ISDEEMEDPOSITIVE>{deemed}</ISDEEMEDPOSITIVE><RATE>{rate}</RATE>"
                "<AMOUNT>{sign}{amount}</AMOUNT><ACTUALQTY>{qty}</ACTUALQTY><BILLEDQTY>{qty}</BILLEDQTY>"
                "{batch}<ACCOUNTINGALLOCATIONS.LIST><LEDGERNAME>{ledger}</LEDGERNAME>"
                "<ISDEEMEDPOSITIVE>{deemed}</ISDEEMEDPOSITIVE><AMOUNT>{sign}{amount}</AMOUNT>"
                "</ACCOUNTINGALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>".format(
                    item=_text(line.item),
                    deemed=item_deemed,
                    rate=_text("{}/{}".format(_money(line.rate), line.unit)),
                    sign=item_sign,
                    amount=_money(line.amount),
                    qty=_text("{} {}".format(_qty(line.quantity), line.unit)),
                    batch=batch,
                    ledger=_text(item_ledger),
                )
            )
        tax_lines = "".join(
            "<LEDGERENTRIES.LIST><LEDGERNAME>{}</LEDGERNAME><ISDEEMEDPOSITIVE>{}</ISDEEMEDPOSITIVE>"
            "<AMOUNT>{}{}</AMOUNT></LEDGERENTRIES.LIST>".format(_text(ledger), item_deemed, item_sign, _money(amount))
            for ledger, amount in taxes
        )
        voucher = (
            '<VOUCHER VCHTYPE={vtype} ACTION="Create" OBJVIEW="Invoice Voucher View">'
            "<DATE>{date}</DATE><EFFECTIVEDATE>{date}</EFFECTIVEDATE><VOUCHERTYPENAME>{vtype_text}</VOUCHERTYPENAME>"
            "{number}{reference}{narration}<PARTYLEDGERNAME>{party}</PARTYLEDGERNAME>"
            "<PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW><ISINVOICE>Yes</ISINVOICE>"
            "<LEDGERENTRIES.LIST><LEDGERNAME>{party}</LEDGERNAME><ISDEEMEDPOSITIVE>{party_deemed}</ISDEEMEDPOSITIVE>"
            "<ISPARTYLEDGER>Yes</ISPARTYLEDGER><AMOUNT>{party_sign}{total}</AMOUNT></LEDGERENTRIES.LIST>"
            "{taxes}{inventory}</VOUCHER>"
        ).format(
            vtype=quoteattr(voucher_type),
            vtype_text=_text(voucher_type),
            date=_tally_date(on),
            number="<VOUCHERNUMBER>{}</VOUCHERNUMBER>".format(_text(number)) if number else "",
            reference="<REFERENCE>{}</REFERENCE>".format(_text(reference)) if reference else "",
            narration="<NARRATION>{}</NARRATION>".format(_text(narration)) if narration else "",
            party=_text(party),
            party_deemed=party_deemed,
            party_sign=party_sign,
            total=_money(total),
            taxes=tax_lines,
            inventory="".join(inventory),
        )
        return self._import("Vouchers", voucher)


def client_for(config: Dict[str, Any], auth_token: Optional[str]) -> TallyClient:
    return TallyClient(config["server_url"], config["company"], auth_token)
