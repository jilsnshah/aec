"""Import products, customers and suppliers from a running TallyPrime.

    python import_tally.py --server http://HOST:9000 --company "AIM INNOVATIONS" --dry-run
    python import_tally.py --server http://HOST:9000 --company "AIM INNOVATIONS"

Writes to the database in DATABASE_URL. Safe to run again: anything already
imported is skipped. TallyPrime must be running with the company open and its
HTTP server on (F1 > Settings > Connectivity > TallyPrime acts as Server).
"""
from __future__ import annotations

import argparse
import sys

from app.database import SessionLocal
from app.services import tally_import
from app.services.tally import TallyClient, TallyError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--token", default=None, help="bearer token, if a gateway is in front of Tally")
    parser.add_argument("--dry-run", action="store_true", help="read and count only; write nothing")
    args = parser.parse_args()

    client = TallyClient(args.server, args.company, args.token)
    try:
        companies = client.companies()
    except TallyError as exc:
        print("Could not reach Tally:", exc)
        return 1
    if args.company not in companies:
        print("Company {!r} is not open in Tally. Open: {}".format(args.company, companies))
        return 1

    with SessionLocal() as session:
        report = tally_import.run(session, client, dry_run=args.dry_run)
    verb = "Found" if args.dry_run else "Imported"
    print("{}: {} products, {} customers, {} suppliers (skipped existing: {})".format(
        verb, report.products, report.customers, report.suppliers, report.skipped))
    if report.vouchers:
        print("Vouchers in Tally:", ", ".join("{} {}".format(n, k) for k, n in sorted(report.vouchers.items())))
    for problem in report.problems:
        print("  problem:", problem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
