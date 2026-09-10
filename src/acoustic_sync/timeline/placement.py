"""Order groups and orphans together without modifying acoustic offsets."""
from datetime import datetime
from acoustic_sync.recording_time import recording_time


def section_date(section, media_by_id):
    values = [(recording_time(media_by_id[mid]), mid) for mid, _ in section[2]]
    values = [(hint, mid) for hint, mid in values if hint]
    if not values:
        return None
    hint, mid = min(values, key=lambda pair: (datetime.fromisoformat(pair[0]['value']), pair[1]))
    return {**hint, 'media_id': mid}


def order_sections(sections, media_by_id):
    def key(section):
        hint = section_date(section, media_by_id)
        paths = tuple(sorted((str(media_by_id[mid].get('relative_path') or media_by_id[mid]['file_path']).replace('\\', '/').casefold(), mid) for mid, _ in section[2]))
        return (hint is None, datetime.fromisoformat(hint['value']).timestamp() if hint else 0, section[1], paths, section[0])
    return sorted(sections, key=key)
