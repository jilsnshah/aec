"""Development seed data.

Strictly a local convenience: it refuses to run unless ENVIRONMENT=development,
and every row it creates is prefixed DEMO- so it is obvious what is demo data.

    python seed.py            # create demo data
    python seed.py --reset    # delete existing DEMO- data first
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.logging_config import configure_logging
from app.models import Customer, Product, Supplier
from app.services import customers as customer_service
from app.services import deliveries as delivery_service
from app.services import enquiries as enquiry_service
from app.services import inventory as inventory_service
from app.services import orders as order_service
from app.services import purchasing as purchasing_service
from app.services import suppliers as supplier_service
from app.services import products as product_service

logger = logging.getLogger("seed")

# SKU, name, unit, MRP, opening stock, what that opening stock cost per unit.
DEMO_PRODUCTS = [
    ("DEMO-WID-1", "Widget, 10mm", "pcs", "250.00", 15, "160.00"),
    ("DEMO-WID-2", "Widget, 20mm", "pcs", "410.00", 0, "0.00"),
    ("DEMO-BOX-1", "Carton, large", "boxes", "80.00", 40, "47.50"),
    ("DEMO-GRN-1", "Loose grain", "kg", "62.50", "125.500", "41.20"),
]
DEMO_SUPPLIERS = [
    ("DEMO-SUP-1", "DEMO Northgate Mills", "R. Shah", "555-0201", "sales@northgate.test"),
    ("DEMO-SUP-2", "DEMO Keystone Packaging", "A. Iyer", "555-0202", None),
]
DEMO_CUSTOMERS = [
    ("DEMO Northgate Traders", "555-0101", "orders@northgate.test"),
    ("DEMO Riverside Supplies", "555-0102", "buying@riverside.test"),
    ("DEMO Hillcrest Retail", "555-0103", None),
]


def reset(session) -> None:
    """Remove demo rows. Archives rather than deletes anything with history."""
    for product in session.execute(
        select(Product).where(Product.sku.like("DEMO-%"))
    ).scalars():
        product_service.archive_product(session, product.id)
    for customer in session.execute(
        select(Customer).where(Customer.name.like("DEMO %"))
    ).scalars():
        customer_service.archive_customer(session, customer.id)
    for supplier in session.execute(
        select(Supplier).where(Supplier.code.like("DEMO-SUP-%"))
    ).scalars():
        supplier_service.archive_supplier(session, supplier.id)
    logger.info("Archived existing demo records")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Archive existing demo rows first.")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.environment != "development":
        logger.error(
            "Refusing to seed: ENVIRONMENT is %r, not 'development'.", settings.environment
        )
        return 1

    session = SessionLocal()
    try:
        if args.reset:
            reset(session)

        products = {}
        for sku, name, uom, mrp, opening, opening_cost in DEMO_PRODUCTS:
            existing = session.execute(select(Product).where(Product.sku == sku)).scalar_one_or_none()
            if existing is not None:
                products[sku] = existing
                continue
            products[sku] = product_service.create_product(
                session,
                sku=sku,
                name=name,
                unit_of_measure=uom,
                mrp=mrp,
                opening_stock=opening,
                opening_unit_cost=opening_cost,
            )

        customers = []
        for name, phone, email in DEMO_CUSTOMERS:
            existing = session.execute(
                select(Customer).where(Customer.name == name)
            ).scalar_one_or_none()
            customers.append(
                existing
                if existing is not None
                else customer_service.create_customer(session, name=name, phone=phone, email=email)
            )

        suppliers = []
        for code, name, contact, phone, email in DEMO_SUPPLIERS:
            existing = session.execute(
                select(Supplier).where(Supplier.code == code)
            ).scalar_one_or_none()
            suppliers.append(
                existing
                if existing is not None
                else supplier_service.create_supplier(
                    session,
                    code=code,
                    name=name,
                    contact_person=contact,
                    phone=phone,
                    email=email,
                )
            )

        # An order that outruns stock, so the dashboard shows a negative net position.
        order_service.create_order(
            session,
            customers[0].id,
            [
                {
                    "product_id": products["DEMO-WID-1"].id,
                    "quantity_ordered": 20,
                    "discount_percent": "10",
                },
                {"product_id": products["DEMO-BOX-1"].id, "quantity_ordered": 5},
            ],
            notes="Demo order with a shortfall on DEMO-WID-1 and a 10% line discount",
        )
        order_service.create_order(
            session,
            customers[1].id,
            [
                {
                    "product_id": products["DEMO-WID-2"].id,
                    "quantity_ordered": 12,
                    "unit_price": "395.00",
                    "discount_percent": "5",
                }
            ],
            notes="Demo order against a product with no stock",
        )
        order_service.create_order(
            session,
            customers[2].id,
            [
                {
                    "product_id": products["DEMO-WID-1"].id,
                    "quantity_ordered": 8,
                    "discount_percent": "2.5",
                }
            ],
            notes="Demo order queued behind an older one",
        )

        # One receipt that settles part of the backlog, for an audit trail to look at.
        inventory_service.receive_stock(
            session,
            products["DEMO-WID-2"].id,
            5,
            note="Demo goods receipt",
            purchase_unit_cost="288.00",
            supplier_reference="DEMO Supplier · INV-4471",
        )

        # Two enquiries: one still being negotiated, one already won.
        open_enquiry = enquiry_service.create_enquiry(
            session,
            customers[0].id,
            [
                {
                    "product_id": products["DEMO-WID-1"].id,
                    "quantity": 10,
                    "discount_percent": "15",
                },
                {
                    "product_id": products["DEMO-BOX-1"].id,
                    "quantity": 20,
                    "discount_percent": "10",
                },
            ],
            notes="Customer requires delivery in two batches. Call before dispatch.",
        )
        won = enquiry_service.create_enquiry(
            session,
            customers[2].id,
            [{"product_id": products["DEMO-GRN-1"].id, "quantity": "40.000",
              "discount_percent": "7.5"}],
            notes="Agreed on the phone; convert once the paperwork arrives.",
        )
        enquiry_service.convert_enquiry(session, won.id)

        # --- Purchasing: one order part-delivered, one still outstanding.
        part_received = purchasing_service.create_purchase_order(
            session,
            suppliers[0].id,
            [
                {
                    "product_id": products["DEMO-WID-1"].id,
                    "quantity_ordered": 100,
                    "unit_cost": "158.00",
                },
                {
                    "product_id": products["DEMO-WID-2"].id,
                    "quantity_ordered": 40,
                    "unit_cost": "285.00",
                },
            ],
            notes="Demo purchase order, delivered in two drops",
            confirm=True,
        )
        # The first drop: part of line one, all of line two. Waiting customer
        # orders are reserved against it by the compulsory allocation rule.
        receipt = purchasing_service.create_goods_receipt(
            session,
            part_received.id,
            [
                {"purchase_order_item_id": part_received.items[0].id, "quantity": 40},
                {"purchase_order_item_id": part_received.items[1].id, "quantity": 40},
            ],
            delivery_note_reference="DEMO-DN-4471",
            notes="Demo first delivery drop",
        )

        awaiting = purchasing_service.create_purchase_order(
            session,
            suppliers[1].id,
            [
                {
                    "product_id": products["DEMO-BOX-1"].id,
                    "quantity_ordered": 200,
                    "unit_cost": "46.00",
                }
            ],
            notes="Demo purchase order still awaiting delivery",
            confirm=True,
        )

        # --- One partial delivery, so a customer line is partly delivered,
        # partly reserved and partly still awaiting stock.
        first_order = order_service.get_order(
            session, order_service.list_orders(session)[-1].id
        )
        delivered = None
        for item in first_order.items:
            if item.quantity_reserved > 0:
                delivered = delivery_service.create_delivery(
                    session,
                    first_order.id,
                    [{"order_item_id": item.id, "quantity": item.quantity_reserved}],
                    reference="DEMO-VAN-3",
                )
                break

        logger.info(
            "Seeded %d demo products, %d demo customers, %d demo suppliers, 3 demo orders, "
            "2 demo enquiries (%s open, %s converted), 2 demo purchase orders (%s part-received "
            "via %s, %s awaiting) and %s.",
            len(products),
            len(customers),
            len(suppliers),
            open_enquiry.enquiry_number,
            won.enquiry_number,
            part_received.po_number,
            receipt["receipt_number"],
            awaiting.po_number,
            "delivery {}".format(delivered["delivery_number"])
            if delivered
            else "no delivery",
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
