"""Reject external references and active markup in unreviewed model output."""
import re
import unicodedata
from html import unescape
from urllib.parse import unquote

_REFERENCE = re.compile(r"(?i)(?:\b(?:https?|ftp|javascript|data):|\bwww\.|\b(?:https?|ftp)\s*:\s*/|(?<!:)//[a-z0-9])")
_MARKUP = re.compile(r"<\s*/?\s*[a-z][a-z0-9:-]*(?=[\s/>])", re.I)


def contains_unreviewed_reference(value):
    if isinstance(value, dict):
        return any(contains_unreviewed_reference(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_unreviewed_reference(v) for v in value)
    if not isinstance(value, str):
        return False
    normalized = unicodedata.normalize("NFKC", unquote(unescape(value)))
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
    return bool(_REFERENCE.search(normalized) or _MARKUP.search(normalized))
