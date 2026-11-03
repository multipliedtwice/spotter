import re


def normalize_us_route(value):
    return re.sub(r'\bU\.?S\.?\s*(?:HIGHWAY|HWY|ROUTE)[.\s-]*(?=\d)', 'US ', value.upper())


def normalize_local_routes(value):
    text = re.sub(r'\bCOUNTY[ -]+ROAD\b', 'CR', value.upper())
    return re.sub(r'\bFARM[ -]+TO[ -]+MARKET\b', 'FM', text)


def expand_shared_routes(value):
    pattern = r'\b(INTERSTATE|HIGHWAY|HWY|US|SR|I)([ -]*)(\d+[A-Z]?)((?:\s*/\s*\d+[A-Z]?(?![A-Z0-9]))+)'
    def expand(match):
        prefix, separator, first, tail = match.groups()
        return '/'.join(prefix + separator + number for number in [first, *re.findall(r'/\s*(\d+[A-Z]?)', tail)])
    return re.sub(pattern, expand, value.upper())


def normalize_exit_suffix(value):
    return re.sub(r'(\bEXIT\s*#?\s*\d+)(?:\s+|\s*-\s*)([A-D])(?=\s*(?:$|,|&|\bOR\b|\bAT\b|\)))', r'\1\2', value.upper())


def marker_keys_match(source_keys, target_keys, source_text=''):
    if not source_keys or not target_keys:
        return False
    marker_occurrences = re.findall(r'\b(?:EXIT|MM|MILE\s*(?:MARKER)?)\s*#?\s*\d+[A-Z]?(?![A-Z0-9])', normalize_exit_suffix(source_text))
    if len({key[2:] for key in source_keys}) > 1 or len(marker_occurrences) > 1:
        return source_keys <= target_keys
    return bool(source_keys & target_keys)


def road_marker_keys(value):
    text = normalize_local_routes(normalize_us_route(normalize_exit_suffix(value)))
    road_pattern = r'\b(INTERSTATE|HIGHWAY|HWY|US|SR|FM|CR|I)[ -]*(\d+[A-Z]?)(?![A-Z0-9])((?:\s*/\s*\d+[A-Z]?(?![A-Z0-9]))*)'
    aliases = {'INTERSTATE': 'I', 'HIGHWAY': 'HWY'}
    clauses = re.split(r'\s*(?:&|\bOR\b|,(?=\s*(?:INTERSTATE|HIGHWAY|HWY|US|SR|FM|CR|I)[ -]*\d))\s*', text)
    keys = set()
    for clause in clauses:
        marker_start = re.search(r'\b(?:EXIT|MM|MILE)(?=\b|\d)', clause)
        later_road = re.search(road_pattern, clause[marker_start.end():]) if marker_start else None
        if later_road:
            clause = clause[:marker_start.end() + later_road.start()]
        roads = set()
        for match in re.finditer(road_pattern, clause[:marker_start.start()] if marker_start else clause):
            kind = aliases.get(match.group(1), match.group(1))
            roads.add((kind, match.group(2)))
            roads.update((kind, number) for number in re.findall(r'/\s*(\d+[A-Z]?)', match.group(3)))
        markers = set()
        for match in re.finditer(r'\bEXIT\s*#?\s*(\d+[A-Z]?)(?![A-Z0-9])((?:\s*(?:NB|SB|EB|WB)?\s*/\s*\d+[A-Z]?(?![A-Z0-9]))*)', clause):
            markers.add(('exit', match.group(1)))
            markers.update(('exit', number) for number in re.findall(r'/\s*(\d+[A-Z]?)', match.group(2)))
        markers.update(('mile', match.group(1)) for match in re.finditer(r'\b(?:MM|MILE\s*(?:MARKER)?)\s*#?\s*(\d+[A-Z]?)(?![A-Z0-9])', clause))
        if len(roads) > 1 and len(markers) > 1:
            return None
        keys.update((kind, number, marker_type, marker) for kind, number in roads for marker_type, marker in markers)
    return keys
