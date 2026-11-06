import logging
from threading import Event

from .extraction import InvalidPdf, parse_invoice
from .storage import Store


logger = logging.getLogger(__name__)


def run_worker(store: Store, stopped: Event) -> None:
    while not stopped.is_set():
        try:
            claim = store.claim()
            if claim is None:
                stopped.wait(0.25)
                continue

            try:
                result = parse_invoice(claim.pdf)
            except InvalidPdf as exc:
                store.fail(claim, str(exc))
            except Exception:
                logger.exception("Invoice %s could not be processed", claim.id)
                store.fail(claim, "Processing failed. Retry the job or upload a new PDF.")
            else:
                store.complete(
                    claim,
                    invoice_number=result.invoice_number,
                    invoice_date=result.invoice_date,
                    total=result.total,
                    currency=result.currency,
                    source_text=result.source_text,
                    issues=result.issues,
                )
        except Exception:
            logger.exception("The invoice worker could not update the queue")
            stopped.wait(1)
