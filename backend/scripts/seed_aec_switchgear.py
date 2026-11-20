"""Demo data for AEC Switchgear (Ahmedabad Electric Corporation).

Fills a fresh database with the company's real profile, brands and catalogue
structure (from aecswitchgear.com), the 12 models listed on its site, and a
realistic but INVENTED history: customers, suppliers' orders, stock, six
months of sales, deliveries, payments, overdue bills and open enquiries.

Prices are approximate list prices for demonstration, not AEC's prices.
Customers are fictional. Phone numbers use the 90000-xxxxx range.

Run against an EMPTY database only:

    DATABASE_URL=postgresql+psycopg://.../aec_switchgear python -m scripts.seed_aec_switchgear
"""
from __future__ import annotations

import os
import random
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, text

from app.database import SessionLocal
from app.models import (Address, Customer, Product, ProductUnit, PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus, SalesOrder,
                        SalesOrderItem, Supplier, User)
from app.services import auth, customers as customer_service, deliveries, enquiries, finance, groups, integration_settings as settings_service
from app.services import orders as order_service, products as product_service, purchasing, suppliers as supplier_service, warehouses

random.seed(17)
NOW = datetime.now(timezone.utc)
START = NOW - timedelta(days=182)

# ---------------------------------------------------------------------------
# Catalogue: (category, brand, sku, name, unit, mrp, cost, hsn, reorder, specs, units)
# The first 12 are the models listed on aecswitchgear.com.
# ---------------------------------------------------------------------------
SG, MC, DR, AU, RL, SI, ME, WC, PF, AC, MV = (
    "Switchgear & circuit protection", "Motor control & protection", "Drives & soft starters", "Automation & control",
    "Control & industrial relays", "Control & signalling", "Meters & measurement", "Wires, cables & accessories",
    "Power factor & power quality", "Switchgear accessories", "Medium voltage switchgear")


def mcb(sku, model, poles, amps, curve, mrp):
    return (SG, "ABB", sku, "ABB {} MCB {} {}A {}-curve 10kA".format(model, poles, amps, curve), "pcs", mrp, round(mrp * 0.62),
            "85362000", 40, [("Poles", poles), ("Rating", "{} A".format(amps)), ("Curve", curve), ("Breaking capacity", "10 kA")], [("box of 12", 12)])


CATALOGUE = [
    (SG, "ABB", "1SYS271122R0204", "ABB SB201M-I C20 MCB 1P+N 20A C-curve 10kA", "pcs", 980, 610, "85362000", 30,
     [("Poles", "1P+N"), ("Rating", "20 A"), ("Curve", "C"), ("Breaking capacity", "10 kA")], [("box of 12", 12)]),
    mcb("1SYS271022R0164", "SB201M-I C16", "1P", 16, "C", 420),
    mcb("1SYS274012R0021", "SB204M D2", "4P", 2, "D", 3150),
    mcb("1SYS271012R0041", "SB201M D4", "1P", 4, "D", 560),
    mcb("1SYS274012R0504", "SB204M C50", "4P", 50, "C", 3480),
    mcb("1SYS272012R0404", "SB202M C40", "2P", 40, "C", 1420),
    mcb("1SYS271012R0504", "SB201M C50", "1P", 50, "C", 640),
    mcb("1SYS272012R0105", "SB202M B10", "2P", 10, "B", 1080),
    (SG, "ABB", "1SYS271112R0325", "ABB SB201M B32 MCB 1P+N 32A B-curve 10kA", "pcs", 1060, 655, "85362000", 30,
     [("Poles", "1P+N"), ("Rating", "32 A"), ("Curve", "B"), ("Breaking capacity", "10 kA")], [("box of 12", 12)]),
    mcb("1SYS271012R0065", "SB201M B6", "1P", 6, "B", 410),
    (AU, "Schneider Electric", "HMIGTO2300", "Schneider Harmony GTO HMIGTO2300 5.7\" QVGA HMI", "pcs", 61500, 41800, "85371000", 2,
     [("Display", "5.7 inch QVGA colour"), ("Range", "Harmony GTO")], []),
    (AU, "Schneider Electric", "HMISTM6200", "Schneider Harmony STM6 HMISTM6200 4.3\" modular HMI", "pcs", 38800, 26400, "85371000", 2,
     [("Display", "4.3 inch"), ("Range", "Harmony STM6 modular")], []),
    # More of the range they stock (illustrative models).
    (SG, "Schneider Electric", "A9F74206", "Schneider Acti9 iC60N MCB 2P 6A C-curve", "pcs", 1350, 860, "85362000", 20, [("Poles", "2P"), ("Rating", "6 A"), ("Curve", "C")], []),
    (SG, "Schneider Electric", "LV429630", "Schneider ComPacT NSX100F MCCB 3P 100A 36kA", "pcs", 23800, 15900, "85362000", 4,
     [("Poles", "3P"), ("Rating", "100 A"), ("Breaking capacity", "36 kA")], []),
    (SG, "Schneider Electric", "LV430630", "Schneider ComPacT NSX160F MCCB 3P 160A 36kA", "pcs", 31200, 20800, "85362000", 3,
     [("Poles", "3P"), ("Rating", "160 A"), ("Breaking capacity", "36 kA")], []),
    (SG, "ABB", "1SDA066798R1", "ABB Tmax XT1B MCCB 3P 125A 18kA", "pcs", 14900, 9700, "85362000", 4, [("Poles", "3P"), ("Rating", "125 A")], []),
    (SG, "Lauritz Knudsen", "LK-DX63-4P", "Lauritz Knudsen DX3 MCCB 4P 63A 25kA", "pcs", 12400, 8100, "85362000", 4, [("Poles", "4P"), ("Rating", "63 A")], []),
    (SG, "ABB", "2CSF204101R1400", "ABB F204 RCCB 4P 40A 30mA", "pcs", 5900, 3850, "85362000", 6, [("Poles", "4P"), ("Rating", "40 A"), ("Sensitivity", "30 mA")], []),
    (SG, "Schneider Electric", "A9R11463", "Schneider Acti9 RCCB 4P 63A 100mA", "pcs", 7200, 4700, "85362000", 6, [("Poles", "4P"), ("Rating", "63 A"), ("Sensitivity", "100 mA")], []),
    (SG, "Lauritz Knudsen", "LK-RCBO-1N-16", "Lauritz Knudsen RCBO 1P+N 16A 30mA", "pcs", 3100, 2050, "85362000", 6, [("Poles", "1P+N"), ("Rating", "16 A")], []),
    (MC, "Schneider Electric", "LC1D09M7", "Schneider TeSys D contactor LC1D09 9A 220V AC coil", "pcs", 1760, 1120, "85364900", 25, [("Rating", "9 A AC-3"), ("Coil", "220 V AC")], [("box of 10", 10)]),
    (MC, "Schneider Electric", "LC1D18M7", "Schneider TeSys D contactor LC1D18 18A 220V AC coil", "pcs", 2650, 1700, "85364900", 20, [("Rating", "18 A AC-3"), ("Coil", "220 V AC")], []),
    (MC, "Schneider Electric", "LC1D32M7", "Schneider TeSys D contactor LC1D32 32A 220V AC coil", "pcs", 5200, 3350, "85364900", 12, [("Rating", "32 A AC-3")], []),
    (MC, "Schneider Electric", "LRD10", "Schneider TeSys LRD10 overload relay 4-6A", "pcs", 2150, 1380, "85364900", 15, [("Range", "4–6 A")], []),
    (MC, "Schneider Electric", "GV2ME10", "Schneider TeSys GV2ME10 MPCB 4-6.3A", "pcs", 4600, 2950, "85362000", 10, [("Range", "4–6.3 A")], []),
    (MC, "ABB", "1SBL137001R1309", "ABB AF09 contactor 9A 100-250V AC/DC", "pcs", 1850, 1190, "85364900", 20, [("Rating", "9 A AC-3")], []),
    (MC, "ABB", "1SAM250000R1009", "ABB MS132-6.3 MPCB 4-6.3A", "pcs", 4200, 2700, "85362000", 10, [("Range", "4–6.3 A")], []),
    (MC, "Siemens", "3RT2016-1AP01", "Siemens SIRIUS 3RT2016 contactor 9A 230V AC", "pcs", 2100, 1350, "85364900", 12, [("Rating", "9 A AC-3")], []),
    (DR, "Schneider Electric", "ATV320U15N4B", "Schneider Altivar ATV320 VFD 1.5kW 3-phase 415V", "pcs", 34500, 23900, "85044090", 3, [("Power", "1.5 kW"), ("Supply", "3-phase 415 V")], []),
    (DR, "Schneider Electric", "ATV320U75N4B", "Schneider Altivar ATV320 VFD 7.5kW 3-phase 415V", "pcs", 76800, 53200, "85044090", 2, [("Power", "7.5 kW")], []),
    (DR, "ABB", "ACS580-01-12A7-4", "ABB ACS580 VFD 5.5kW 3-phase 415V", "pcs", 69800, 48200, "85044090", 2, [("Power", "5.5 kW")], []),
    (DR, "Schneider Electric", "ATS22D17Q", "Schneider Altistart ATS22 soft starter 7.5kW", "pcs", 41200, 28600, "85044090", 2, [("Power", "7.5 kW")], []),
    (AU, "Schneider Electric", "TM221CE16R", "Schneider Modicon M221 PLC 16 I/O Ethernet", "pcs", 21800, 14900, "85371000", 3, [("I/O", "9 in / 7 relay out"), ("Comms", "Ethernet")], []),
    (AU, "Schneider Electric", "TM3DI16", "Schneider TM3 digital input module 16 DI", "pcs", 6900, 4600, "85371000", 4, [("Inputs", "16 DI")], []),
    (AU, "Schneider Electric", "TM3AI4", "Schneider TM3 analog input module 4 AI", "pcs", 11800, 7900, "85371000", 3, [("Inputs", "4 AI")], []),
    (RL, "Schneider Electric", "RXM4AB2BD", "Schneider Zelio RXM4 miniature relay 24V DC 4C/O", "pcs", 420, 255, "85364900", 50, [("Coil", "24 V DC"), ("Contacts", "4 C/O")], [("box of 10", 10)]),
    (RL, "Schneider Electric", "RXZE2S114M", "Schneider Zelio relay socket for RXM4", "pcs", 310, 190, "85369090", 50, [], [("box of 10", 10)]),
    (RL, "Schneider Electric", "RE22R1AMR", "Schneider Zelio RE22 timer relay multi-function", "pcs", 3400, 2200, "85364900", 8, [("Function", "multi-function")], []),
    (RL, "ABB", "1SVR730700R0200", "ABB CT-ERS.21 timer relay", "pcs", 3900, 2550, "85364900", 6, [], []),
    (SI, "Schneider Electric", "XB5AA31", "Schneider Harmony XB5 push button green 1NO", "pcs", 290, 175, "85365090", 60, [("Colour", "green"), ("Contact", "1 NO")], [("box of 10", 10)]),
    (SI, "Schneider Electric", "XB5AA42", "Schneider Harmony XB5 push button red 1NC", "pcs", 290, 175, "85365090", 60, [("Colour", "red"), ("Contact", "1 NC")], [("box of 10", 10)]),
    (SI, "Schneider Electric", "XB5AS8442", "Schneider Harmony XB5 emergency stop 40mm red", "pcs", 980, 610, "85365090", 20, [("Type", "turn to release")], []),
    (SI, "Schneider Electric", "XB7EV63P", "Schneider Harmony XB7 pilot lamp LED red 230V", "pcs", 340, 205, "85365090", 60, [("Colour", "red"), ("Supply", "230 V")], [("box of 10", 10)]),
    (SI, "Schneider Electric", "XB5AD21", "Schneider Harmony XB5 selector switch 2-position", "pcs", 460, 285, "85365090", 30, [], [("box of 10", 10)]),
    (ME, "Schneider Electric", "METSEEM6400H", "Schneider EasyLogic EM6400NG multifunction meter", "pcs", 9800, 6400, "90303390", 6, [("Class", "1.0")], []),
    (ME, "Schneider Electric", "METSECT5MA020", "Schneider Tropical CT 200/5A class 1", "pcs", 1150, 720, "85043100", 20, [("Ratio", "200/5 A")], []),
    (ME, "ABB", "2CSG299903R0000", "ABB digital voltmeter 96x96", "pcs", 2400, 1550, "90303390", 8, [], []),
    (PF, "Lauritz Knudsen", "LK-CAP-25", "Lauritz Knudsen heavy duty capacitor 25 kVAr 440V", "pcs", 5900, 3850, "85321000", 8, [("Rating", "25 kVAr"), ("Voltage", "440 V")], []),
    (PF, "Schneider Electric", "VPL12N", "Schneider VarPlus Logic APFC relay 12 step", "pcs", 18900, 12600, "90328990", 3, [("Steps", "12")], []),
    (PF, "Schneider Electric", "LC1DLKM7", "Schneider TeSys capacitor duty contactor 25 kVAr", "pcs", 6200, 4050, "85364900", 6, [], []),
    (WC, "Polycab", "PCB-FRLS-1.5", "Polycab FRLS PVC insulated copper wire 1.5 sq mm", "m", 22, 15, "85444999", 2700, [("Conductor", "copper"), ("Size", "1.5 sq mm")], [("coil (90 m)", 90)]),
    (WC, "Polycab", "PCB-FRLS-2.5", "Polycab FRLS PVC insulated copper wire 2.5 sq mm", "m", 35, 24, "85444999", 2700, [("Conductor", "copper"), ("Size", "2.5 sq mm")], [("coil (90 m)", 90)]),
    (WC, "KEI Cable", "KEI-4CX16-AL-ARM", "KEI 4-core 16 sq mm aluminium armoured LT cable", "m", 265, 182, "85444999", 500, [("Cores", "4"), ("Size", "16 sq mm"), ("Conductor", "aluminium")], [("drum (500 m)", 500)]),
    (WC, "KEI Cable", "KEI-12CX1.5-CU-CTRL", "KEI 12-core 1.5 sq mm copper control cable", "m", 310, 214, "85444999", 300, [("Cores", "12"), ("Size", "1.5 sq mm")], [("drum (500 m)", 500)]),
    (AC, "Schneider Electric", "LV429387", "Schneider ComPacT NSX auxiliary contact OF/SD", "pcs", 1650, 1060, "85369090", 10, [], []),
    (AC, "Schneider Electric", "LV429387-ST", "Schneider ComPacT NSX shunt trip MX 220-240V", "pcs", 4300, 2800, "85369090", 6, [], []),
    (AC, "ABB", "1SDA066461R1", "ABB Tmax XT rotary handle direct", "pcs", 2900, 1880, "85369090", 6, [], []),
    (MV, "Siemens", "3AH5-11KV-630", "Siemens 3AH5 vacuum circuit breaker 11kV 630A", "pcs", 385000, 298000, "85352100", 0, [("Voltage", "11 kV"), ("Rating", "630 A")], []),
]
SUPPLIERS = {
    "Schneider Electric": ("Schneider Electric India Pvt Ltd", "SEI", 5),
    "ABB": ("ABB India Ltd", "ABB", 6),
    "Lauritz Knudsen": ("Lauritz Knudsen Electrical & Automation", "LK", 7),
    "Siemens": ("Siemens Ltd", "SIE", 10),
    "Polycab": ("Polycab India Ltd", "PCB", 4),
    "KEI Cable": ("KEI Industries Ltd", "KEI", 5),
}
CUSTOMERS = [  # (name, city, area, kind, terms, credit_limit, ordering weight, pays late)
    ("Shree Ganesh Panel Industries", "Ahmedabad", "Odhav GIDC", "panel", 30, 800000, 9, False),
    ("Narmada Control Systems", "Ahmedabad", "Vatva GIDC", "panel", 30, 600000, 8, False),
    ("Om Sai Electricals", "Ahmedabad", "Naroda", "contractor", 15, 200000, 6, True),
    ("Patel Power Panels", "Ahmedabad", "Kathwada GIDC", "panel", 45, 900000, 8, False),
    ("Vishwakarma Automation", "Ahmedabad", "Changodar", "integrator", 30, 500000, 6, False),
    ("Sabar Pumps & Motors", "Ahmedabad", "Sanand GIDC", "oem", 45, 1500000, 7, False),
    ("Jalaram Engineering Works", "Rajkot", "Aji GIDC", "oem", 30, 700000, 5, True),
    ("Kutch Salt & Chemicals", "Gandhidham", "Kandla Road", "industry", 30, 400000, 3, False),
    ("Tapi Infra Projects", "Surat", "Sachin GIDC", "epc", 60, 2500000, 5, False),
    ("Mahi Electrical Contractors", "Vadodara", "Makarpura GIDC", "contractor", 15, 250000, 4, True),
    ("Shakti Textile Mills", "Ahmedabad", "Narol", "industry", 30, 500000, 3, False),
    ("Riddhi Siddhi Enterprises", "Ahmedabad", "Bapunagar", "contractor", 0, 100000, 3, False),
    ("Gujarat Agro Processing", "Mehsana", "GIDC Phase 2", "industry", 30, 300000, 2, False),
    ("Krishna Switchboards", "Ahmedabad", "Rakhial", "panel", 30, 600000, 6, False),
    ("Aakash Elevators", "Ahmedabad", "Odhav", "oem", 30, 800000, 4, False),
    ("Sunrise Solar EPC", "Gandhinagar", "Sector 26 GIDC", "epc", 45, 1200000, 4, False),
]
KIND_LIKES = {  # which categories each kind of customer buys most
    "panel": [SG, MC, SI, RL, AC, ME, WC], "contractor": [SG, WC, SI], "integrator": [AU, DR, RL, SI],
    "oem": [MC, DR, AU, SI, RL], "industry": [SG, MC, PF, ME, WC], "epc": [SG, WC, PF, ME, MV],
}


def backdate(session, marker: datetime, when: datetime) -> None:
    """Move everything written since ``marker`` to ``when`` (the seed runs alone)."""
    tables = session.execute(text("SELECT table_name FROM information_schema.columns WHERE column_name='created_at' AND table_schema='public'")).scalars().all()
    for table in tables:
        session.execute(text('UPDATE "{}" SET created_at = :when WHERE created_at >= :marker'.format(table)), {"when": when, "marker": marker})
    for table, column in (("sales_orders", "updated_at"), ("purchase_orders", "ordered_at"), ("payments", "paid_on")):
        try:
            session.execute(text('UPDATE "{t}" SET {c} = :when WHERE created_at = :when'.format(t=table, c=column)),
                            {"when": when.date() if column == "paid_on" else when})
        except Exception:
            session.rollback()
    session.commit()


def stamp() -> datetime:
    return datetime.now(timezone.utc)


def main() -> None:
    session = SessionLocal()
    if session.execute(select(func.count()).select_from(Product)).scalar_one():
        sys.exit("This database already has products. Seed only an empty database.")

    if not session.execute(select(User).limit(1)).first():
        auth.create_user(session, "admin", os.environ.get("SEED_ADMIN_PASSWORD", "aec-demo-2026"), is_admin=True)

    # Company settings ------------------------------------------------------
    settings_service.update(session, settings_service.TALLY, config={
        "seller_name": "Ahmedabad Electric Corporation",
        "seller_address": "301-302, Akshar Matrix, Odhav Road, Odhav, Ahmedabad, Gujarat 382415",
        "company": "Ahmedabad Electric Corporation", "godown": "Central Warehouse"})
    settings_service.update(session, settings_service.AI, config={
        "agent_name": "Asha",
        "company_profile": ("AEC Switchgear (Ahmedabad Electric Corporation), established 2017: authorized distributor of Schneider Electric, ABB and "
                            "Lauritz Knudsen; also supplies Siemens, Polycab and KEI. Switchgear and circuit protection, motor control, drives, "
                            "automation (PLC/HMI), relays, control and signalling, meters, power factor, wires and cables, MV switchgear. "
                            "Serves panel builders, OEMs, EPC and electrical contractors and industries across 20+ states."),
        "company_hours": "Monday to Saturday, 10:30 AM to 7:00 PM. Closed on Sunday.",
        "company_delivery": "Same-day dispatch from our 50,000+ sq ft central warehouse in Odhav, Ahmedabad for ready-stock items.",
        "company_payment": "Payment as per the agreed credit terms; new customers pay in advance.",
        "company_policies": "100% genuine products with manufacturer warranty and original test certificates.",
    })
    settings_service.update(session, settings_service.MARKETING, config={
        "brand_name": "AEC Switchgear", "brand_tone": "expert, reliable and to the point; trade buyers, not consumers",
        "brand_hashtags": ["#AECSwitchgear", "#Ahmedabad", "#Switchgear"], "brand_signature": "AEC Switchgear · Odhav, Ahmedabad"})

    # Warehouses ------------------------------------------------------------
    main_wh = warehouses.save(session, {"name": "Central Warehouse", "code": "CWH", "kind": "godown", "is_default": True,
                                        "address": "Plot 25-38, Adarsh Gold Estate, Odhav Industrial Area, Ahmedabad 382415", "tally_godown": "Central Warehouse"})
    warehouses.save(session, {"name": "Corporate Office Counter", "code": "OFC", "kind": "shop",
                              "address": "301-302, Akshar Matrix, Odhav Road, Ahmedabad 382415"})

    # Suppliers -------------------------------------------------------------
    supplier_of = {}
    for n, (brand, (name, code, lead)) in enumerate(SUPPLIERS.items(), start=1):
        s = supplier_service.create_supplier(session, name=name, code=code, phone="90000100{:02d}".format(n), email="orders.{}@example.com".format(code.lower()))
        supplier_of[brand] = (s, lead)
    session.execute(text("UPDATE suppliers SET payment_terms_days = 30"))
    session.commit()

    # Products (opening stock seven months ago) ------------------------------
    marker = stamp()
    products = []
    for category, brand, sku, name, unit, mrp, cost, hsn, reorder, specs, units in CATALOGUE:
        opening = 0 if reorder == 0 else reorder * random.choice([4, 5, 6])
        p = product_service.create_product(session, sku=sku, name=name, unit_of_measure=unit, mrp=str(mrp), opening_stock=str(opening),
                                           opening_unit_cost=str(cost), category=category, gst_rate=18, reorder_level=str(reorder),
                                           preferred_supplier_id=supplier_of[brand][0].id, lead_time_days=supplier_of[brand][1],
                                           specs=[{"name": k, "value": v} for k, v in specs])
        p.brand, p.hsn_code, p.last_purchase_price = brand, hsn, Decimal(str(cost))
        p.description = "{} by {}. Genuine product with manufacturer warranty.".format(name, brand)
        for unit_name, factor in units:
            session.add(ProductUnit(product_id=p.id, name=unit_name, factor=Decimal(str(factor)), for_sales=True, for_purchase=True))
        if units and unit == "m":
            p.sales_unit = None
            p.purchase_unit = units[0][0]
        products.append((p, category, cost))
        session.commit()
    backdate(session, marker, START - timedelta(days=30))

    # Customers ---------------------------------------------------------------
    customer_rows = []
    for n, (name, city, area, kind, terms, limit, weight, late) in enumerate(CUSTOMERS, start=1):
        c = customer_service.create_customer(session, name=name, phone="90000200{:02d}".format(n), email="purchase{}@example.com".format(n),
                                             payment_terms_days=terms, credit_limit=Decimal(str(limit)))
        session.add(Address(customer_id=c.id, kind="billing", label="Office", line="{}, {}".format(area, city), city=city, state="Gujarat", is_default=True))
        customer_rows.append((c, kind, weight, late))
    session.commit()

    by_category = {}
    for p, category, cost in products:
        by_category.setdefault(category, []).append(p)

    # Six months of trading -------------------------------------------------
    po_count = order_count = 0
    day = START
    while day < NOW - timedelta(days=1):
        # Restock every ~10 days: one PO per brand that is running low.
        if (day - START).days % 7 == 0:
            session.expire_all()
            short = dict(session.execute(select(SalesOrderItem.product_id, func.sum(
                SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_fulfilled - SalesOrderItem.quantity_cancelled - SalesOrderItem.quantity_reserved))
                .group_by(SalesOrderItem.product_id)).all())
            on_order = dict(session.execute(select(PurchaseOrderItem.product_id, func.sum(PurchaseOrderItem.quantity_ordered - PurchaseOrderItem.quantity_received))
                                            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
                                            .where(PurchaseOrder.status.notin_((PurchaseOrderStatus.CANCELLED, PurchaseOrderStatus.DRAFT)))
                                            .group_by(PurchaseOrderItem.product_id)).all())
            for brand, (supplier, lead) in supplier_of.items():
                need = []
                for p, _, _ in products:
                    if p.brand != brand or not p.reorder_level:
                        continue
                    p = session.get(Product, p.id)
                    want = int(p.reorder_level * 4 + (short.get(p.id) or 0) - p.physical_stock - (on_order.get(p.id) or 0))
                    if p.physical_stock - (short.get(p.id) or 0) < p.reorder_level * 2 and want > 0:
                        need.append((p, want))
                if not need:
                    continue
                marker = stamp()
                lines = [{"product_id": p.id, "quantity_ordered": str(want), "unit_cost": str(p.last_purchase_price)} for p, want in need[:12]]
                if not lines:
                    continue
                po = purchasing.create_purchase_order(session, supplier.id, lines, notes="Stock replenishment", confirm=True)
                backdate(session, marker, day)
                po_count += 1
                arrive = day + timedelta(days=lead)
                if arrive < NOW:
                    marker = stamp()
                    session.refresh(po)
                    purchasing.create_goods_receipt(session, po.id, [{"purchase_order_item_id": item.id, "quantity": str(item.quantity_ordered)} for item in po.items],
                                                    delivery_note_reference="DN-{}".format(random.randint(10000, 99999)), warehouse_id=main_wh["id"])
                    backdate(session, marker, arrive)
                    # Back-orders waiting for these goods go out the next day.
                    session.expire_all()
                    for waiting in session.execute(select(SalesOrder).join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id)
                                                   .where(SalesOrderItem.quantity_reserved > 0).distinct()).scalars().all():
                        lines_out = [{"order_item_id": i.id, "quantity": str(i.quantity_reserved)} for i in waiting.items if i.quantity_reserved > 0]
                        when_out = arrive + timedelta(days=1)
                        if not lines_out or when_out >= NOW:
                            continue
                        marker = stamp()
                        try:
                            deliveries.create_delivery(session, waiting.id, lines_out, warehouse_id=main_wh["id"])
                            backdate(session, marker, when_out)
                        except Exception:
                            session.rollback()
                    if arrive < NOW - timedelta(days=35):
                        marker = stamp()
                        total = sum(item.quantity_ordered * item.unit_cost for item in po.items)
                        finance.record_payment(session, "out", str(total), supplier_id=supplier.id, method="bank", reference="NEFT", purchase_order_id=po.id)
                        backdate(session, marker, arrive + timedelta(days=30))
        # Orders: 2-5 on a working day.
        if day.weekday() != 6:
            for _ in range(random.randint(2, 5)):
                customer, kind, weight, late = random.choices(customer_rows, weights=[r[2] for r in customer_rows])[0]
                cats = KIND_LIKES[kind]
                lines, seen = [], set()
                for _ in range(random.randint(1, 4)):
                    pool = by_category.get(random.choice(cats)) or []
                    pool = [p for p in pool if p.id not in seen and p.reorder_level]
                    if not pool:
                        continue
                    p = random.choice(pool)
                    seen.add(p.id)
                    qty = (random.choice([90, 180, 270]) if p.unit_of_measure == "m" and p.mrp < 100 else
                           random.choice([50, 100, 150]) if p.unit_of_measure == "m" else
                           random.choice([10, 12, 20, 24]) if p.mrp < 1000 else
                           random.choice([1, 2, 3, 4]) if p.mrp < 20000 else random.choice([1, 1, 2]))
                    disc = random.choice([0, 0, 2, 5, 8])
                    lines.append({"product_id": p.id, "quantity_ordered": str(qty), "unit_price": str(p.mrp), "discount_percent": str(disc)})
                if not lines:
                    continue
                marker = stamp()
                try:
                    order = order_service.create_order(session, customer.id, lines)
                except Exception as exc:  # credit block etc.: skip, like a real day
                    session.rollback()
                    continue
                when = day + timedelta(hours=random.randint(4, 10))
                backdate(session, marker, when)
                order_count += 1
                ship = when + timedelta(days=random.choice([0, 0, 1, 2]))
                if ship < NOW - timedelta(hours=2):
                    session.expire_all()
                    order = session.get(SalesOrder, order.id)
                    deliver = [{"order_item_id": item.id, "quantity": str(item.quantity_reserved)} for item in order.items if item.quantity_reserved > 0]
                    if deliver:
                        marker = stamp()
                        try:
                            deliveries.create_delivery(session, order.id, deliver, warehouse_id=main_wh["id"],
                                                       transport={"vehicle_number": "GJ01{}{}".format(random.choice("ABCDEFGH"), random.randint(1000, 9999))})
                            backdate(session, marker, ship)
                        except Exception:
                            session.rollback()
                            continue
                        session.expire_all()
                        order = session.get(SalesOrder, order.id)
                        value = sum(float(i.quantity_fulfilled * i.unit_price_net) for i in order.items)
                        terms = customer.payment_terms_days or 0
                        pay_day = ship + timedelta(days=terms + (random.randint(25, 70) if late else random.randint(-5, 10)))
                        if value > 0 and pay_day < NOW and not (late and random.random() < 0.5):
                            marker = stamp()
                            finance.record_payment(session, "in", "{:.2f}".format(value), customer_id=customer.id, method=random.choice(["bank", "bank", "cheque", "upi"]),
                                                   reference=random.choice(["NEFT", "RTGS", "CHQ"]) + str(random.randint(100000, 999999)), sales_order_id=order.id)
                            backdate(session, marker, pay_day)
        day += timedelta(days=1)

    # Open enquiries this week ---------------------------------------------
    for n in range(7):
        customer, kind, _, _ = random.choice(customer_rows)
        pool = [p for c in KIND_LIKES[kind] for p in by_category.get(c, []) if p.reorder_level]
        items = [{"product_id": p.id, "quantity": str(random.choice([5, 10, 24]) if p.unit_of_measure != "m" else 180)} for p in random.sample(pool, min(3, len(pool)))]
        marker = stamp()
        enquiries.create_enquiry(session, customer.id, items, source=random.choice(["whatsapp", "email", "manual"]), notes="Please share best rates and availability.")
        backdate(session, marker, NOW - timedelta(days=random.randint(0, 6), hours=random.randint(1, 8)))

    groups.save(session, {"name": "Panel builders", "description": "Panel builders who buy regularly",
                          "rules": [{"field": "orders_12m", "op": ">=", "value": 10}], "match": "all"})
    groups.save(session, {"name": "Key accounts", "description": "Spend over Rs 10 lakh in 12 months",
                          "rules": [{"field": "spend_12m", "op": ">=", "value": 1000000}], "match": "all"})
    groups.recompute(session)
    print("Seeded: {} products, {} customers, {} suppliers, {} purchase orders, {} sales orders.".format(
        len(products), len(customer_rows), len(supplier_of), po_count, order_count))
    session.close()


if __name__ == "__main__":
    main()
