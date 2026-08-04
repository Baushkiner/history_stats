"""Сбор данных из внешних источников."""

from .wikidata import SparqlClient, SparqlError, rows_to_records, verify_qids

__all__ = ["SparqlClient", "SparqlError", "rows_to_records", "verify_qids"]
