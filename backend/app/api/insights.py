"""Business intelligence endpoints. The Insights page and the assistant both
read these, so the numbers always agree."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import insights

router = APIRouter(prefix="/api/insights", tags=["insights"])

PERIOD = Query(default="month", description="today, week, month, quarter, year, last_7, last_30 or last_90.")


@router.get("/overview")
def overview(
    period: str = PERIOD,
    start: Optional[date] = Query(default=None, description="First day of a custom range (overrides period)."),
    end: Optional[date] = Query(default=None, description="Last day of a custom range."),
    db: Session = Depends(get_db),
):
    """This period against the previous one of the same length: orders, booked
    value, delivered revenue, cost, gross profit and margin, enquiries and
    conversion, new customers, purchasing; with a daily series."""
    return insights.overview(db, period, start, end)


@router.get("/inventory")
def inventory(include_archived: bool = Query(default=False), db: Session = Depends(get_db)):
    """Inventory health per product: free, reserved, on order and short
    quantities; value at cost; stock age buckets; sales rate; days of cover;
    flags (short, dead, slow, low_cover, reorder) and a reorder quantity."""
    return insights.inventory_health(db, include_archived)


@router.get("/sales")
def sales(
    group_by: str = Query(default="product", description="product, customer, month or day."),
    period: str = Query(default="last_90", description="As for overview."),
    start: Optional[date] = Query(default=None),
    end: Optional[date] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Booked value, delivered revenue, cost and profit grouped by product,
    customer, month or day."""
    return insights.sales_breakdown(db, group_by, period, start, end, limit)


@router.get("/enquiries")
def enquiries(
    period: Optional[str] = Query(default=None, description="Limit to enquiries created in this period."),
    start: Optional[date] = Query(default=None),
    end: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
):
    """The enquiry funnel: counts, conversion by source, days to convert, open
    pipeline value, lost reasons and stale open enquiries."""
    return insights.enquiry_funnel(db, period, start, end)


@router.get("/customers")
def customers(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)):
    """Customers ranked by value, with outstanding deliveries, last order and
    dormant customers."""
    return insights.customer_insights(db, limit)


@router.get("/suppliers")
def suppliers(db: Session = Depends(get_db)):
    """Supplier performance: spend, lead time, fill rate, on-time rate, what is
    still due, and late purchase orders."""
    return insights.supplier_insights(db)


@router.get("/alerts")
def alerts(db: Session = Depends(get_db)):
    """What needs attention now, most urgent first."""
    return insights.alerts(db)


@router.get("/briefing")
def briefing(db: Session = Depends(get_db)):
    """Today at a glance."""
    return insights.briefing(db)
