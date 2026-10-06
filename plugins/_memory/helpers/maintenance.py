"""Memory health report: duplicates, possible conflicts, stale, low-trust and
legacy (no provenance) memories. Report only - nothing is changed or deleted
here; the user reviews it in the memory dashboard and acts there.

Similarity uses the vectors already in the FAISS index (no re-embedding),
on the store's relevance scale ((1 + cosine) / 2, Memory._cosine_normalizer):
- >= DUPLICATE_SCORE  : near-duplicates, cosine >= ~0.94 (consolidation
                        should have merged them)
- >= CONFLICT_SCORE   : same topic, different wording, cosine >= ~0.80 - may
                        contradict; the user judges, because deciding
                        contradiction needs reading, not a threshold
"""

from __future__ import annotations

from datetime import datetime, timedelta

DUPLICATE_SCORE = 0.97
CONFLICT_SCORE = 0.90
MEMORY_AREAS = ("main", "fragments", "solutions")


def _parse(ts) -> datetime | None:
    try:
        return datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _brief(doc, score: float | None = None) -> dict:
    meta = doc.metadata or {}
    out = {
        "id": meta.get("id", ""),
        "area": meta.get("area", ""),
        "text": str(doc.page_content or "")[:200],
        "trust": meta.get("trust", ""),
        "source": meta.get("source", ""),
        "timestamp": meta.get("timestamp", ""),
        "last_used": meta.get("last_used", ""),
    }
    if score is not None:
        out["score"] = round(float(score), 3)
    return out


def build_report(memory, stale_days: int = 90, max_scan: int = 400, now: datetime | None = None) -> dict:
    db = memory.db
    docs = {k: v for k, v in db.get_all_docs().items()
            if (v.metadata or {}).get("area") in MEMORY_AREAS and not (v.metadata or {}).get("knowledge_source")}
    now = now or datetime.now()
    cutoff = now - timedelta(days=stale_days)

    stale, low, legacy = [], [], []
    for doc in docs.values():
        meta = doc.metadata or {}
        last = _parse(meta.get("last_used")) or _parse(meta.get("timestamp"))
        if last and last < cutoff:
            stale.append(_brief(doc))
        if meta.get("trust") == "low":
            low.append(_brief(doc))
        if not meta.get("source"):
            legacy.append(meta.get("id", ""))

    duplicates, conflicts = _similar_pairs(db, docs, max_scan)
    return {
        "total": len(docs),
        "stale_days": stale_days,
        "stale": stale,
        "low_trust": low,
        "duplicates": duplicates,
        "possible_conflicts": conflicts,
        "without_provenance": len(legacy),
        "scanned_for_similarity": min(len(docs), max_scan),
    }


def _similar_pairs(db, docs: dict, max_scan: int) -> tuple[list, list]:
    duplicates, conflicts, seen = [], [], set()
    index = getattr(db, "index", None)
    id_map = getattr(db, "index_to_docstore_id", None)
    if index is None or not id_map:
        return duplicates, conflicts
    try:
        relevance = db._select_relevance_score_fn()
    except Exception:
        return duplicates, conflicts

    scanned = 0
    for pos, doc_id in list(id_map.items()):
        if doc_id not in docs:
            continue
        if scanned >= max_scan:
            break
        scanned += 1
        try:
            vector = index.reconstruct(int(pos))
            hits = db.similarity_search_with_score_by_vector(vector, k=4)
        except Exception:
            continue
        for other, raw in hits:
            other_id = (other.metadata or {}).get("id")
            if not other_id or other_id == doc_id or other_id not in docs:
                continue
            key = tuple(sorted((doc_id, other_id)))
            if key in seen:
                continue
            seen.add(key)
            score = relevance(raw)
            pair = {"a": _brief(docs[doc_id]), "b": _brief(other), "score": round(float(score), 3)}
            if score >= DUPLICATE_SCORE:
                duplicates.append(pair)
            elif score >= CONFLICT_SCORE:
                conflicts.append(pair)
    duplicates.sort(key=lambda p: -p["score"])
    conflicts.sort(key=lambda p: -p["score"])
    return duplicates[:50], conflicts[:50]
