"""Search over live knowledge sections (PostgreSQL full-text + trigram).

How a question becomes a query (plain language):
  "Can I return the product after 15 days?"
    -> to_tsvector('english', ...)   = 'day':7 'product':5 'return':3 '15':6
       (stop words like "can", "I", "the" removed; words reduced to stems)
    -> 'return' | 'product' | '15' | 'day'   (OR: any word may match)
    -> ts_rank_cd ranks sections higher when MORE words match, and when they
       match in the title/heading (weight A) rather than the body (weight B).
  Trigram similarity on the heading adds tolerance for typos ("waranty").

This is the "keyword" half of knowledge discovery. In Phase 5 Claude Haiku
picks the best sections from these candidates plus the document catalog, which
covers paraphrases that share no words with the text.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SEARCH_SQL = text(
    """
    WITH q AS (
        SELECT to_tsquery('english', coalesce(string_agg(lexeme, ' | '), '')) AS tsq
          FROM unnest(to_tsvector('english', :query))
    )
    SELECT s.id, s.document_id, d.path, d.doc_type, s.doc_title, s.heading, s.anchor,
           s.heading_path, s.body, s.source_pages,
           ts_rank_cd(s.search_vector, q.tsq, 32) AS fts_rank,
           similarity(s.heading, :query) AS heading_similarity
      FROM knowledge_sections s
      JOIN knowledge_documents d ON d.id = s.document_id, q
     WHERE d.status = 'live'
       AND (:include_internal OR s.audience = 'customer')
       AND (:include_sources OR d.doc_type <> 'Source Document')
       AND (s.search_vector @@ q.tsq OR similarity(s.heading, :query) > 0.3)
     ORDER BY ts_rank_cd(s.search_vector, q.tsq, 32) + 0.3 * similarity(s.heading, :query) DESC,
              s.position
     LIMIT :limit
    """
)


@dataclass(frozen=True)
class SearchHit:
    section_id: uuid.UUID
    document_id: uuid.UUID
    path: str
    doc_type: str
    doc_title: str
    heading: str
    anchor: str
    heading_path: list[str]
    body: str
    source_pages: list[int]
    score: float


async def search_sections(
    session: AsyncSession,
    query: str,
    *,
    limit: int = 10,
    include_internal: bool = False,
    include_sources: bool = False,
) -> list[SearchHit]:
    """Search live sections of the CURRENT organization (RLS scopes the tables)."""
    query = query.strip()[:500]
    if not query:
        return []
    rows = await session.execute(
        SEARCH_SQL,
        {
            "query": query,
            "limit": max(1, min(limit, 50)),
            "include_internal": include_internal,
            "include_sources": include_sources,
        },
    )
    return [
        SearchHit(
            section_id=r.id,
            document_id=r.document_id,
            path=r.path,
            doc_type=r.doc_type,
            doc_title=r.doc_title,
            heading=r.heading,
            anchor=r.anchor,
            heading_path=list(r.heading_path),
            body=r.body,
            source_pages=list(r.source_pages),
            score=round(float(r.fts_rank) + 0.3 * float(r.heading_similarity), 4),
        )
        for r in rows
    ]
