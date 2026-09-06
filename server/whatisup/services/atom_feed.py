"""Atom 1.0 feed rendering — plan cap V2, 5d.

No XML generation existed anywhere in this codebase before this module, so it
sets the convention: **always** build the tree with
``xml.etree.ElementTree`` and let it serialize, **never** interpolate
operator-authored text into an XML string by hand.

The feed carries text written by the operator (announcement messages, a
maintenance window's ``public_message``, a monitor's public name). A `<` or
`&` in any of it must not break the document, and a well-chosen payload must
not be able to inject a sibling element. ``ElementTree.tostring`` escapes
``&``, ``<`` and ``>`` in text content and additionally ``"``/``\\n``/``\\t``
in attribute values — exactly the escaping XML 1.0 requires (including the
``]]>`` case: a literal ``]]>`` in content is only well-formed once its ``>``
is escaped, which ``_escape_cdata`` does unconditionally).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from xml.etree.ElementTree import Element, SubElement, tostring

ATOM_NS = "http://www.w3.org/2005/Atom"


def _aware(dt: datetime) -> datetime:
    """Normalize to a UTC-aware datetime. Naive timestamps are assumed UTC —
    SQLite (used in tests) round-trips `DateTime(timezone=True)` columns as
    naive, while a fresh `datetime.now(UTC)` is aware; mixing the two in a
    `sort()`/`max()` raises `TypeError` rather than comparing."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True)
class AtomEntry:
    """One feed entry — one object (incident / announcement / maintenance
    window), never one state change. ``entry_id`` must be stable across
    calls; ``updated`` must change whenever the underlying object does —
    that pair is how a feed reader deduplicates."""

    entry_id: str
    title: str
    updated: datetime
    published: datetime
    summary: str
    link: str | None = None

    def __post_init__(self) -> None:
        # Normalized here, once, so every caller (including the sort/merge
        # step in api/v1/public.py, before entries ever reach this module)
        # can safely compare `.updated` values regardless of source.
        object.__setattr__(self, "updated", _aware(self.updated))
        object.__setattr__(self, "published", _aware(self.published))


def _fmt(dt: datetime) -> str:
    """RFC 3339 timestamp — `dt` is always UTC-aware by the time it reaches
    here (see `AtomEntry.__post_init__` and `render_atom_feed`'s own
    `datetime.now(UTC)` fallback)."""
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def render_atom_feed(
    *,
    feed_id: str,
    title: str,
    self_url: str,
    alternate_url: str,
    entries: list[AtomEntry],
) -> str:
    """Serialize an Atom 1.0 feed. Every piece of operator-authored text
    reaches this function as plain ``str`` — it is assigned to `.text`/
    attribute values and escaped by ``tostring``, never spliced into a
    template string."""
    feed = Element("feed", {"xmlns": ATOM_NS})
    SubElement(feed, "id").text = feed_id
    SubElement(feed, "title").text = title
    updated = max((e.updated for e in entries), default=datetime.now(UTC))
    SubElement(feed, "updated").text = _fmt(updated)
    SubElement(
        feed,
        "link",
        {"rel": "self", "type": "application/atom+xml", "href": self_url},
    )
    SubElement(
        feed,
        "link",
        {"rel": "alternate", "type": "text/html", "href": alternate_url},
    )

    for entry in entries:
        entry_el = SubElement(feed, "entry")
        SubElement(entry_el, "id").text = entry.entry_id
        SubElement(entry_el, "title").text = entry.title
        SubElement(entry_el, "updated").text = _fmt(entry.updated)
        SubElement(entry_el, "published").text = _fmt(entry.published)
        if entry.link:
            SubElement(
                entry_el,
                "link",
                {"rel": "alternate", "type": "text/html", "href": entry.link},
            )
        SubElement(entry_el, "summary").text = entry.summary

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(feed, encoding="unicode")
