"""Date hints for approximate ordering, never acoustic alignment."""
from datetime import datetime, timezone
from pathlib import PureWindowsPath
import re


def parse_date(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r'^(\d{4}):(\d{2}):(\d{2})', r'\1-\2-\3', value.strip())
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[Tt ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?', value):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        naive = dt.tzinfo is None
        dt = dt.replace(tzinfo=timezone.utc) if naive else dt.astimezone(timezone.utc)
        return {'value': dt.isoformat(), 'precision': 'day' if len(value) == 10 else 'second', 'timezone_assumed': naive}
    except (ValueError, OverflowError):
        return None


def recording_time(media):
    candidates = []
    for item in media.get('recording_time_candidates', []) + [{'value': media.get('creation_time'), 'source': 'metadata:creation_time'}]:
        parsed = parse_date(item.get('value'))
        if parsed:
            candidates.append({**parsed, 'source': item.get('source', 'metadata')})
    name = PureWindowsPath(media.get('file_path', '')).stem
    patterns = [
        (r'(?<!\d)(\d{4})(\d{2})(\d{2})[_-]?(\d{2})(\d{2})(\d{2})(?!\d)', False),
        (r'(?<!\d)(\d{4})[-_](\d{2})[-_](\d{2})[T _-](\d{2})[-_.](\d{2})[-_.](\d{2})(?!\d)', False),
        (r'^(\d{2})(\d{2})(\d{2})[-_](\d{2})(\d{2})(\d{2})(?!\d)', True),
    ]
    for pattern, short in patterns:
        match = re.search(pattern, name)
        if match:
            y, m, d, h, minute, s = match.groups()
            parsed = parse_date(f"{'20' if short else ''}{y}-{m}-{d}T{h}:{minute}:{s}")
            if parsed:
                candidates.append({**parsed, 'source': 'filename'})
    for pattern in [r'(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)', r'(?<!\d)(\d{4})[-_](\d{2})[-_](\d{2})(?!\d)']:
        match = re.search(pattern, name)
        if match:
            parsed = parse_date('-'.join(match.groups()))
            if parsed:
                candidates.append({**parsed, 'source': 'filename'})
    return next((c for c in candidates if c['precision'] == 'second'), next(iter(candidates), None))


def metadata_candidates(format_tags, streams):
    result = []
    for label, tags in [('format', format_tags)] + [(f"stream:{s['index']}", s.get('tags', {})) for s in streams]:
        tags = {k.lower(): v for k, v in tags.items()}
        for key in ('com.apple.quicktime.creationdate', 'datetime_original', 'date_time_original', 'date_recorded', 'creation_time', 'date'):
            if tags.get(key):
                result.append({'source': f'metadata:{label}:{key}', 'value': tags[key]})
        if tags.get('origination_date'):
            value = tags['origination_date']
            if tags.get('origination_time'):
                value += 'T' + tags['origination_time']
            result.insert(0, {'source': f'metadata:{label}:bwf', 'value': value})
    return result
