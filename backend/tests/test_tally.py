"""Tally sync and invoice delivery, against a fake TallyPrime and a fake Meta.

The fake Tally speaks the same XML protocol as TallyPrime's HTTP server:
collection exports, master and voucher imports, IMPORTRESULT replies and
LINEERROR refusals. The fake Graph API takes the media upload and the
template message. Nothing leaves the machine.
"""
from __future__ import annotations

from decimal import Decimal as D
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

import httpx
import pytest

from app.services import inbound, tally, whatsapp

TALLY_URL = "http://tally.test:9000"


class FakeTally:
    """Just enough of TallyPrime's XML server to exercise the client."""

    def __init__(self):
        self.companies = ["Labdhi Exim"]
        self.masters: Dict[str, set] = {"LEDGER": {"Sales", "Output CGST", "Output SGST"}, "STOCKITEM": set(), "UNIT": set()}
        self.vouchers: List[ET.Element] = []
        self.refuse: Optional[str] = None
        self.auth: List[Optional[str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.auth.append(request.headers.get("Authorization"))
        root = ET.fromstring(request.content)
        kind = root.findtext("HEADER/TALLYREQUEST")
        report = root.findtext("HEADER/ID")
        if kind == "Export":
            return self._export(root, report)
        message = root.find("BODY/DATA/TALLYMESSAGE")
        if self.refuse:
            return self._reply("<LINEERROR>{}</LINEERROR><IMPORTRESULT><CREATED>0</CREATED><ERRORS>1</ERRORS></IMPORTRESULT>".format(self.refuse))
        created = 0
        for node in list(message):
            if node.tag == "VOUCHER":
                self.vouchers.append(node)
            else:
                self.masters.setdefault(node.tag, set()).add(node.get("NAME"))
            created += 1
        return self._reply("<IMPORTRESULT><CREATED>{}</CREATED><ALTERED>0</ALTERED><ERRORS>0</ERRORS>"
                           "<LASTVCHID>{}</LASTVCHID></IMPORTRESULT>".format(created, len(self.vouchers)))

    def _export(self, root, report):
        if report == "AECCompanies":
            return self._reply("".join('<COMPANY NAME="{}"/>'.format(name) for name in self.companies))
        formula = root.findtext(".//SYSTEM") or ""
        if report == "AECExists":
            object_type = root.findtext(".//COLLECTION/TYPE").upper().replace(" ", "")
            name = formula.split('"')[1]
            hit = name in self.masters.get(object_type, set())
            return self._reply('<{0} NAME="{1}"/>'.format(object_type, name) if hit else "")
        if report == "AECVoucher":
            index = int(formula.split("=")[1])
            return self._reply("<VOUCHER><VOUCHERNUMBER>INV/{:04d}</VOUCHERNUMBER></VOUCHER>".format(index))
        raise AssertionError("unexpected export " + report)

    @staticmethod
    def _reply(body: str) -> httpx.Response:
        return httpx.Response(200, content="<ENVELOPE><HEADER><STATUS>1</STATUS></HEADER><BODY><DATA>{}</DATA></BODY></ENVELOPE>".format(body).encode())

    def voucher(self, vtype: str) -> ET.Element:
        return next(v for v in self.vouchers if v.get("VCHTYPE") == vtype)


class FakeMeta:
    def __init__(self):
        self.uploads: List[bytes] = []
        self.messages: List[dict] = []
        self.fail: Optional[str] = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            return httpx.Response(400, json={"error": {"message": self.fail, "code": 132001}})
        if request.url.path.endswith("/media"):
            self.uploads.append(request.content)
            return httpx.Response(200, json={"id": "media-1"})
        if request.url.path.endswith("/messages"):
            import json
            self.messages.append(json.loads(request.content))
            return httpx.Response(200, json={"messages": [{"id": "wamid.out.1"}]})
        return httpx.Response(200, json={"data": [{"name": "invoice_pdf", "status": "APPROVED", "language": "en"}]})


@pytest.fixture()
def fakes(session_factory, monkeypatch):
    fake_tally, fake_meta = FakeTally(), FakeMeta()
    monkeypatch.setattr(inbound, "session_factory", session_factory)
    monkeypatch.setattr(tally, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(fake_tally)))
    monkeypatch.setattr(whatsapp, "http_factory", lambda: httpx.Client(transport=httpx.MockTransport(fake_meta)))
    return fake_tally, fake_meta


def connect(client, **config):
    body = {"enabled": True, "config": {"server_url": TALLY_URL, "company": "Labdhi Exim",
                                         "seller_name": "Labdhi Exim", "seller_gstin": "24ABCDE1234F1Z5", **config},
            "credentials": {"auth_token": "gateway-token"}}
    response = client.put("/api/integrations/tally", json=body)
    assert response.status_code == 200, response.text


def send_invoices(client):
    response = client.put("/api/integrations/whatsapp", json={
        "enabled": True,
        "config": {"phone_number_id": "1098765432", "verify_token": "v", "business_account_id": "WABA",
                   "send_invoices": True, "invoice_template": "invoice_pdf"},
        "credentials": {"access_token": "meta-token"},
    })
    assert response.status_code == 200, response.text


@pytest.fixture()
def catalogue(client, make_product):
    cement = make_product("Cement 53 Grade", sku="OPC", unit_of_measure="bags", mrp="400.00", opening_stock=100)
    customer = client.post("/api/customers", json={"name": "Ravi Builders", "phone": "98765 43210"}).json()
    supplier = client.post("/api/suppliers", json={"name": "Shree Depot"}).json()
    return cement, customer, supplier


def place_order(client, customer, product, qty="10", discount="0"):
    response = client.post("/api/orders", json={"customer_id": customer["id"], "items": [
        {"product_id": str(product.id), "quantity_ordered": qty, "discount_percent": discount}]})
    assert response.status_code == 201, response.text
    return response.json()


def amounts(voucher: ET.Element) -> D:
    """Every posting in a voucher. Tally needs debits and credits to cancel out."""
    total = D(0)
    for entry in voucher.iter("LEDGERENTRIES.LIST"):
        total += D(entry.findtext("AMOUNT"))
    for entry in voucher.iter("ACCOUNTINGALLOCATIONS.LIST"):
        total += D(entry.findtext("AMOUNT"))
    return total


def syncs(client):
    return {row["kind"]: row for row in client.get("/api/integrations/tally/syncs").json()["items"]}


def test_test_connection_lists_the_companies_open_in_tally(client, fakes):
    connect(client)
    result = client.post("/api/integrations/tally/test").json()
    assert result == {"companies": ["Labdhi Exim"], "company_found": True}
    assert fakes[0].auth[-1] == "Bearer gateway-token"
    assert "gateway-token" not in client.get("/api/integrations").text


def test_a_placed_sales_order_reaches_tally_and_the_invoice_reaches_the_customer(client, fakes, catalogue):
    fake_tally, fake_meta = fakes
    cement, customer, _ = catalogue
    connect(client, tax_mode="cgst_sgst", gst_rate=18)
    send_invoices(client)
    order = place_order(client, customer, cement, qty="10", discount="5")  # 380 x 10 = 3800

    rows = syncs(client)
    assert rows["sales_order"]["status"] == "synced" and rows["sales_order"]["tally_number"] == order["order_number"]
    assert rows["sales_invoice"]["status"] == "synced" and rows["sales_invoice"]["tally_number"] == "INV/0002"
    assert rows["sales_invoice"]["notify_status"] == "sent" and rows["sales_invoice"]["notify_to"] == "919876543210"

    # Masters were created in Tally before the vouchers that need them.
    assert "Ravi Builders" in fake_tally.masters["LEDGER"]
    assert "Cement 53 Grade" in fake_tally.masters["STOCKITEM"] and "bags" in fake_tally.masters["UNIT"]

    sales_order = fake_tally.voucher("Sales Order")
    assert sales_order.findtext("VOUCHERNUMBER") == order["order_number"]
    invoice = fake_tally.voucher("Sales")
    assert invoice.findtext("VOUCHERNUMBER") is None  # Tally numbers its own invoices
    assert invoice.findtext("PARTYLEDGERNAME") == "Ravi Builders"
    entries = {e.findtext("LEDGERNAME"): D(e.findtext("AMOUNT")) for e in invoice.iter("LEDGERENTRIES.LIST")}
    # Customer debited with goods plus 18% GST; CGST and SGST credited 9% each.
    assert entries == {"Ravi Builders": D("-4484.00"), "Output CGST": D("342.00"), "Output SGST": D("342.00")}
    assert amounts(invoice) == 0
    line = invoice.find("ALLINVENTORYENTRIES.LIST")
    assert line.findtext("RATE") == "380.00/bags" and line.findtext("ACTUALQTY") == "10 bags"
    assert line.findtext("BATCHALLOCATIONS.LIST/ORDERNO") == order["order_number"]

    # The invoice went out on WhatsApp as the approved template with the PDF.
    assert fake_meta.uploads and b"%PDF" in fake_meta.uploads[0]
    message = fake_meta.messages[0]
    assert message["to"] == "919876543210" and message["template"]["name"] == "invoice_pdf"
    header, body = message["template"]["components"]
    assert header["parameters"][0]["document"]["filename"] == "Invoice-INV-0002.pdf"
    assert [p["text"] for p in body["parameters"]] == ["Ravi Builders", "INV/0002", "INR 4,484.00"]

    pdf = client.get("/api/integrations/invoices/{}.pdf".format(order["id"]))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_a_tally_refusal_is_kept_with_its_reason_and_can_be_retried(client, fakes, catalogue):
    fake_tally, _ = fakes
    cement, customer, _ = catalogue
    connect(client, create_invoices=False)
    fake_tally.refuse = "Ledger 'Sales' does not exist!"
    place_order(client, customer, cement)

    row = syncs(client)["sales_order"]
    assert row["status"] == "failed" and "Ledger 'Sales' does not exist!" in row["error"]
    assert row["attempts"] == 1 and row["next_attempt_at"] is not None

    fake_tally.refuse = None
    assert client.post("/api/integrations/tally/syncs/{}/retry".format(row["id"])).status_code == 200
    assert syncs(client)["sales_order"]["status"] == "synced"


def test_a_placed_purchase_order_goes_to_tally_with_the_supplier_credited(client, fakes, catalogue):
    fake_tally, _ = fakes
    cement, _, supplier = catalogue
    connect(client)
    draft = client.post("/api/purchase-orders", json={"supplier_id": supplier["id"], "confirm": False, "items": [
        {"product_id": str(cement.id), "quantity_ordered": "50", "unit_cost": "300"}]}).json()
    assert client.get("/api/integrations/tally/syncs").json()["total"] == 0  # a draft is not placed

    client.post("/api/purchase-orders/{}/confirm".format(draft["id"]))
    row = syncs(client)["purchase_order"]
    assert row["status"] == "synced" and row["tally_number"] == draft["po_number"]
    voucher = fake_tally.voucher("Purchase Order")
    entries = {e.findtext("LEDGERNAME"): D(e.findtext("AMOUNT")) for e in voucher.iter("LEDGERENTRIES.LIST")}
    assert entries == {"Shree Depot": D("15000.00")}
    assert amounts(voucher) == 0
    assert "Shree Depot" in fake_tally.masters["LEDGER"]


def test_nothing_is_queued_while_tally_is_off(client, fakes, catalogue):
    cement, customer, _ = catalogue
    place_order(client, customer, cement)
    assert client.get("/api/integrations/tally/syncs").json()["total"] == 0


def test_an_invoice_whatsapp_refused_can_be_resent(client, fakes, catalogue):
    _, fake_meta = fakes
    cement, customer, _ = catalogue
    connect(client)
    send_invoices(client)
    fake_meta.fail = "Template name does not exist in the translation"
    place_order(client, customer, cement)
    invoice = syncs(client)["sales_invoice"]
    assert invoice["status"] == "synced" and invoice["notify_status"] == "failed"
    assert "Template name does not exist" in invoice["notify_error"]

    fake_meta.fail = None
    client.post("/api/integrations/tally/syncs/{}/retry".format(invoice["id"]))
    assert syncs(client)["sales_invoice"]["notify_status"] == "sent"


def test_without_a_phone_number_the_invoice_is_not_sent(client, fakes, catalogue, make_product):
    cement, _, _ = catalogue
    connect(client)
    send_invoices(client)
    nophone = client.post("/api/customers", json={"name": "Walk-in"}).json()
    place_order(client, nophone, cement)
    invoice = syncs(client)["sales_invoice"]
    assert invoice["notify_status"] == "skipped" and "no phone" in invoice["notify_error"]


def test_the_template_approval_can_be_checked(client, fakes):
    send_invoices(client)
    assert client.get("/api/integrations/whatsapp/template").json() == {
        "template": "invoice_pdf", "status": "APPROVED (en)"}
