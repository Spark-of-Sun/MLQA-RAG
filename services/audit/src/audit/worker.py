"""audit-anchor and alerting worker (blueprint 4.2, 13.3, 13.6, 12.9): monthly audit partitions created ahead of
time, hourly Merkle anchors to the Object Lock bucket, tombstone mirroring to the ledger outside backups, alert
evaluation and delivery.

    python -m audit.worker [--once]
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from audit.alerts import Alerting
from audit.anchor import Anchorer, ensure_partitions, mirror_tombstones
from lmqa_db import Claims, Database
from lmqa_models.envfile import merged_env
from lmqa_models.settings import load_settings
from lmqa_security.redact import configure_logging

log = logging.getLogger("audit.worker")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    configure_logging(logging.INFO)
    env = merged_env()
    db = Database(load_settings(), services=("audit",))
    db.open()

    @contextmanager
    def conn() -> Iterator[Any]:
        with db.as_service("audit", Claims(actor="audit:worker")) as c:
            yield c

    anchor_bucket, tomb_bucket = env.get("AUDIT_ANCHOR_BUCKET"), env.get("TOMBSTONE_BUCKET")
    s3 = None
    if anchor_bucket or tomb_bucket:
        import boto3

        s3 = boto3.client("s3", region_name=env.get("AWS_REGION", "us-east-1"))
    anchorer = Anchorer(conn, s3, anchor_bucket) if s3 and anchor_bucket else None
    alerting = Alerting(conn, env.get("ONCALL_WEBHOOK_URL"))
    try:
        while True:
            created = ensure_partitions(conn)
            if created:
                log.info("audit partitions created: %d", created)
            if anchorer:
                log.info("anchor: %s", anchorer.anchor())
            if s3 and tomb_bucket:
                log.info("tombstones mirrored: %d", mirror_tombstones(conn, s3, tomb_bucket))
            log.info("alerts raised %d, delivered %d", alerting.evaluate(), alerting.deliver())
            if args.once:
                return 0
            time.sleep(60)
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
