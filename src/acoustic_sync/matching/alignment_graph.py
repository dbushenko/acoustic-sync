"""Resolve robust relative offsets without assuming a single global recorder."""
from collections import deque


def _path(adjacency, source, target):
    queue = deque([(source, 0, 100.0, [source])])
    seen = {source}
    while queue:
        node, offset, confidence, path = queue.popleft()
        if node == target:
            return offset, confidence, path
        for neighbour, delta, score in adjacency.get(node, []):
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append((neighbour, offset+delta, min(confidence, score), path+[neighbour]))
    return None


def align(media: list[dict], matches: list[dict], sample_rate: int, tolerance_seconds: float):
    adjacency = {m["id"]: [] for m in media}
    tolerance = round(tolerance_seconds * sample_rate)
    for match in sorted((m for m in matches if m["accepted"]), key=lambda m: (-m["confidence"], m["a_id"], m["b_id"])):
        a, b, delta = match["a_id"], match["b_id"], match["offset_samples"]
        existing = _path(adjacency, a, b)
        if existing:
            residual = abs(existing[0]-delta)
            match["cycle_residual_samples"] = residual
            if residual > tolerance:
                match["accepted"] = False
                match["reason"] = "inconsistent_graph_cycle"
            continue
        adjacency[a].append((b, delta, match["confidence"]))
        adjacency[b].append((a, -delta, match["confidence"]))
    by_id = {m["id"]: m for m in media}
    seen = set()
    groups, aligned, unmatched, masters = [], [], [], []
    for item in media:
        identity = item["id"]
        if identity in seen:
            continue
        if not adjacency[identity]:
            related = [m for m in matches if identity in (m["a_id"], m["b_id"])]
            strongest = max(related, key=lambda m: m["confidence"], default=None)
            reason = item.get("error") or (strongest["reason"] if strongest else
                     "no_audio" if not item["audio_streams"] else "no_acoustic_match")
            unmatched.append({"media_id": identity, "file_path": item["file_path"],
                              "confidence": strongest["confidence"] if strongest else 0, "reason": reason})
            seen.add(identity)
            continue
        component = []
        pending = [identity]
        while pending:
            node = pending.pop()
            if node in seen:
                continue
            seen.add(node)
            component.append(node)
            pending.extend(n for n, _, _ in adjacency[node] if n not in seen)
        reference = min(component, key=lambda n: (by_id[n]["kind"] != "audio", -len(adjacency[n]),
                                                  -by_id[n]["duration_seconds"], by_id[n]["relative_path"]))
        positions = {n: _path(adjacency, reference, n) for n in component}
        minimum = min(v[0] for v in positions.values())
        group_id = f"group-{len(groups)+1}"
        members = []
        for node in sorted(component, key=lambda n: (positions[n][0], by_id[n]["relative_path"])):
            offset, score, path = positions[node]
            members.append({"media_id": node, "offset_samples": offset-minimum, "confidence": score})
            aligned.append({"media_id": node, "file_path": by_id[node]["file_path"],
                            "matched_to": by_id[reference]["file_path"], "matched_to_id": reference,
                            "offset_samples": offset, "offset_seconds": offset/sample_rate,
                            "confidence": score, "group_id": group_id, "indirect": len(path)>2, "alignment_path": path})
        groups.append({"id": group_id, "reference_id": reference, "members": members,
                       "relative_timing_known": False})
        masters.append(by_id[reference]["file_path"])
    return groups, aligned, unmatched, masters
