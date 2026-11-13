"""Exact source quotation verification shared by ingestion and application code."""


def verify_quote(quote: str | None, section_text: str | None) -> bool:
    """Reject blank quotes; compare original characters without normalization."""
    return bool(quote and quote.strip() and section_text is not None and quote in section_text)
