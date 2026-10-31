import re


def road_marker_keys(value):
    text = value.upper()
    road_pattern = r'\b(INTERSTATE|HIGHWAY|HWY|US|SR|I)[ -]*(\d+[A-Z]?)(?![A-Z0-9])((?:\s*/\s*\d+[A-Z]?(?![A-Z0-9]))*)'
    aliases = {'INTERSTATE': 'I', 'HIGHWAY': 'HWY'}
    clauses = re.split(r'\s*(?:&|\bOR\b|,(?=\s*(?:INTERSTATE|HIGHWAY|HWY|US|SR|I)[ -]*\d))\s*', text)
    keys, all_roads, all_markers = set(), set(), set()
    for clause in clauses:
        roads = set()
        for match in re.finditer(road_pattern, clause):
            kind = aliases.get(match.group(1), match.group(1))
            roads.add((kind, match.group(2)))
            roads.update((kind, number) for number in re.findall(r'/\s*(\d+[A-Z]?)', match.group(3)))
        markers = set()
        for match in re.finditer(r'\bEXIT\s*#?\s*(\d+[A-Z]?)(?![A-Z0-9])((?:\s*(?:NB|SB|EB|WB)?\s*/\s*\d+[A-Z]?(?![A-Z0-9]))*)', clause):
            markers.add(('exit', match.group(1)))
            markers.update(('exit', number) for number in re.findall(r'/\s*(\d+[A-Z]?)', match.group(2)))
        markers.update(('mile', match.group(1)) for match in re.finditer(r'\b(?:MM|MILE\s*(?:MARKER)?)\s*#?\s*(\d+[A-Z]?)(?![A-Z0-9])', clause))
        all_roads.update(roads)
        all_markers.update(markers)
        if len(roads) > 1 and len(markers) > 1:
            return None
        keys.update((kind, number, marker_type, marker) for kind, number in roads for marker_type, marker in markers)
    if len(all_markers) == 1 and not re.search(r'\bOR\b', text):
        marker_type, marker = next(iter(all_markers))
        return {(kind, number, marker_type, marker) for kind, number in all_roads}
    return keys
