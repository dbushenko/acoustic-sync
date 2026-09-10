"""Offset voting through indexed hash joins, with bounded per-pair hypotheses."""
import heapq
from acoustic_sync.runtime import Cancellation


def candidates(index, stream_id: int, sample_rate: int, cancel: Cancellation):
    connection = index.connection
    bucket = max(1, round(0.02322 * sample_rate))
    # Interrupt long SQLite operations when a UI/CLI cancellation arrives.
    def interrupt():
        try:
            cancel.check()
            return 0
        except Exception:
            return 1
    connection.set_progress_handler(interrupt, 10000)
    query = """
        SELECT p.stream, CAST(ROUND((q.t-p.t)*1.0/?) AS INTEGER) AS delta,
               COUNT(DISTINCT q.t) AS support, MIN(q.t), MAX(q.t)
        FROM postings q JOIN stats s ON s.hash=q.hash
        JOIN postings p ON p.hash=q.hash
        JOIN streams a ON a.id=q.stream JOIN streams b ON b.id=p.stream
        WHERE q.stream=? AND p.stream<q.stream AND a.media_id<>b.media_id AND s.n<=100
        GROUP BY p.stream, delta HAVING support>=4
    """
    best = {}
    try:
        for target, delta, support, first, last in connection.execute(query, (bucket, stream_id)):
            cancel.check()
            heap = best.setdefault(target, [])
            item = (support, delta, first, last)
            if len(heap) < 24:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
    finally:
        connection.set_progress_handler(None, 0)
    result = []
    for target, heap in sorted(best.items()):
        modes = []
        for support, delta, first, last in sorted(heap, reverse=True):
            offset = delta * bucket
            if any(abs(offset - m["offset_samples"]) < sample_rate * 0.15 for m in modes):
                continue
            modes.append({"a_stream": stream_id, "b_stream": target, "offset_samples": offset,
                          "support": support, "span_seconds": (last-first)/sample_rate,
                          "anchor_first": first, "anchor_last": last})
            if len(modes) == 3:
                break
        for mode in modes:
            # Recount unique anchors across neighbouring quantization bins. A true
            # offset near a bin boundary must not lose half its evidence.
            anchor_rows = connection.execute("""
                SELECT DISTINCT q.t FROM postings q JOIN postings p ON q.hash=p.hash
                JOIN stats s ON s.hash=q.hash
                WHERE q.stream=? AND p.stream=? AND s.n<=100
                  AND ABS((q.t-p.t)-?)<=? ORDER BY q.t
            """, (stream_id, target, mode["offset_samples"], 2*bucket)).fetchall()
            anchors = [r[0] for r in anchor_rows]
            if anchors:
                mode["support"] = len(anchors)
                mode["span_seconds"] = (anchors[-1]-anchors[0])/sample_rate
                # Cap verification work independently of recording duration.
                count = min(15, len(anchors))
                mode["anchor_positions"] = [anchors[round(i*(len(anchors)-1)/max(1,count-1))] for i in range(count)]
        for mode in modes:
            mode["alternative_support"] = max((other["support"] for other in modes if other is not mode), default=0)
            result.append(mode)
    return result
