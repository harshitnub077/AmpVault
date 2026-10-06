import datetime
import uuid

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.ledger.models import JournalEntry, PostingDirection


class GatewayPaymentRecord(BaseModel):
    gateway_payment_id: str
    escrow_order_id: str
    amount_paise: int
    status: str  # CAPTURED, REFUNDED
    captured_at: datetime.datetime


class Discrepancy(BaseModel):
    discrepancy_type: str  # MISSING_IN_LEDGER, MISSING_IN_GATEWAY, AMOUNT_MISMATCH
    escrow_order_id: str
    gateway_payment_id: str | None = None
    ledger_amount_paise: int = 0
    gateway_amount_paise: int = 0
    drift_paise: int = 0
    notes: str


class DriftReport(BaseModel):
    reconciliation_id: str
    run_at: datetime.datetime
    total_gateway_records: int
    total_ledger_records: int
    matched_count: int
    unmatched_count: int
    total_drift_paise: int
    is_balanced: bool
    discrepancies: list[Discrepancy]

    model_config = ConfigDict(from_attributes=True)


class ReconciliationEngine:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run_reconciliation(self, gateway_records: list[GatewayPaymentRecord]) -> DriftReport:
        """
        Compare payment gateway settlement records against internal double-entry ledger postings.
        Audits:
        1. Ledger deposits without corresponding gateway capture.
        2. Gateway captured payments missing in ledger.
        3. Amount mismatches between gateway gross and ledger debit.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        rec_id = f"REC-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"

        # Query all funding entries from journal
        stmt = (
            select(JournalEntry)
            .where(JournalEntry.reference_type == "ESCROW_FUNDING")
            .options(selectinload(JournalEntry.postings))
        )
        res = await self.session.execute(stmt)
        ledger_entries = list(res.scalars().all())

        # Map by reference_id (escrow_order_id)
        ledger_map: dict[str, int] = {}
        for entry in ledger_entries:
            # Total debits in this entry
            debit_sum = sum(p.amount_paise for p in entry.postings if p.direction == PostingDirection.DEBIT)
            ledger_map[entry.reference_id] = debit_sum

        gateway_map: dict[str, GatewayPaymentRecord] = {
            r.escrow_order_id: r for r in gateway_records if r.status == "CAPTURED"
        }

        matched_count = 0
        total_drift_paise = 0
        discrepancies: list[Discrepancy] = []

        all_order_ids = set(ledger_map.keys()) | set(gateway_map.keys())

        for order_id in all_order_ids:
            in_ledger = order_id in ledger_map
            in_gateway = order_id in gateway_map

            if in_ledger and in_gateway:
                ledger_amt = ledger_map[order_id]
                gw_record = gateway_map[order_id]
                if ledger_amt == gw_record.amount_paise:
                    matched_count += 1
                else:
                    drift = abs(ledger_amt - gw_record.amount_paise)
                    total_drift_paise += drift
                    discrepancies.append(
                        Discrepancy(
                            discrepancy_type="AMOUNT_MISMATCH",
                            escrow_order_id=order_id,
                            gateway_payment_id=gw_record.gateway_payment_id,
                            ledger_amount_paise=ledger_amt,
                            gateway_amount_paise=gw_record.amount_paise,
                            drift_paise=drift,
                            notes=f"Ledger ({ledger_amt} paise) != Gateway ({gw_record.amount_paise} paise)",
                        )
                    )
            elif in_gateway and not in_ledger:
                gw_record = gateway_map[order_id]
                total_drift_paise += gw_record.amount_paise
                discrepancies.append(
                    Discrepancy(
                        discrepancy_type="MISSING_IN_LEDGER",
                        escrow_order_id=order_id,
                        gateway_payment_id=gw_record.gateway_payment_id,
                        ledger_amount_paise=0,
                        gateway_amount_paise=gw_record.amount_paise,
                        drift_paise=gw_record.amount_paise,
                        notes="Payment captured at gateway but missing corresponding ledger funding entry",
                    )
                )
            elif in_ledger and not in_gateway:
                ledger_amt = ledger_map[order_id]
                total_drift_paise += ledger_amt
                discrepancies.append(
                    Discrepancy(
                        discrepancy_type="MISSING_IN_GATEWAY",
                        escrow_order_id=order_id,
                        ledger_amount_paise=ledger_amt,
                        gateway_amount_paise=0,
                        drift_paise=ledger_amt,
                        notes="Ledger records funding deposit but no matching gateway capture record exists",
                    )
                )

        return DriftReport(
            reconciliation_id=rec_id,
            run_at=now,
            total_gateway_records=len(gateway_records),
            total_ledger_records=len(ledger_entries),
            matched_count=matched_count,
            unmatched_count=len(discrepancies),
            total_drift_paise=total_drift_paise,
            is_balanced=(len(discrepancies) == 0 and total_drift_paise == 0),
            discrepancies=discrepancies,
        )
