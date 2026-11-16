"""xno-call-binding: bind a Nano (XNO) payment to the call it paid for.

Standard library only. No module holds a key, and importing the package opens
no socket: only the read-only node and price helpers (finality_facts,
four_check, usd_quote) touch the network, and only when called.

    from xno_call_binding import call_binding
    from xno_call_binding.call_binding import QuoteLedger, derive_quote_id
"""

__version__ = "0.2.0"

from . import (
    ap2_nano_mandate,
    binding_options,
    call_binding,
    finality_facts,
    four_check,
    presigned_send,
    quote_service,
    usd_quote,
)
from .call_binding import (
    BindingError,
    QuoteLedger,
    amount_tail,
    bound_amount,
    derive_quote_id,
    tail_of_amount,
)
from .presigned_send import check_presigned, verify_signature
from .quote_service import QuoteService, usd_quote_id

__all__ = [
    "__version__",
    "ap2_nano_mandate",
    "binding_options",
    "call_binding",
    "finality_facts",
    "four_check",
    "presigned_send",
    "quote_service",
    "usd_quote",
    "BindingError",
    "QuoteLedger",
    "amount_tail",
    "bound_amount",
    "derive_quote_id",
    "tail_of_amount",
    "check_presigned",
    "verify_signature",
    "QuoteService",
    "usd_quote_id",
]
