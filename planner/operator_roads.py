import math
import re

from planner.core import distance, in_us
from planner.osm_evidence import normalized, typed_roads, valid_point
from planner.road import expand_shared_routes, normalize_us_route

ROUTE = r'(?:INTERSTATE|HIGHWAY|HWY|US|SR|I)[ -]*\d+[A-Z]?'
ROAD_KINDS = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link'}


def whole_source_routes(address):
    text = expand_shared_routes(normalize_us_route(normalized(address)))
    if not re.fullmatch(rf'{ROUTE}(?:\s*(?:&|,|/|\bAND\b)\s*{ROUTE})*', text):
        return set()
    return typed_roads(text, state='')


def nearby_road_refs(way, point, state, state_boundary):
    try:
        if not isinstance(way, dict) or set(way) != {'id', 'url', 'tags', 'nodes', 'geometry'}:
            return set()
        identifier = way['id']
        if type(identifier) is not int or identifier <= 0 or way['url'] != f'https://www.openstreetmap.org/way/{identifier}':
            return set()
        tags, nodes, geometry = way['tags'], way['nodes'], way['geometry']
        if not isinstance(tags, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items()) or tags.get('highway') not in ROAD_KINDS or not tags.get('ref'):
            return set()
        if re.search(r'\b(?:BUS|BUSINESS|ALT|ALTERNATE|BYPASS|BYP|SPUR|TRUCK)\b', tags['ref'], re.I):
            return set()
        if not isinstance(nodes, list) or len(nodes) < 2 or not all(type(n) is int and n > 0 for n in nodes) or not isinstance(geometry, list) or len(nodes) != len(geometry) or not all(valid_point(p) for p in geometry):
            return set()
        cosine = math.cos(math.radians(point[0]))
        best = None
        for a, b in zip(geometry, geometry[1:]):
            ax, ay = (a[1] - point[1]) * cosine, a[0] - point[0]
            bx, by = (b[1] - point[1]) * cosine, b[0] - point[0]
            dx, dy = bx - ax, by - ay
            denominator = dx * dx + dy * dy
            t = max(0, min(1, -(ax * dx + ay * dy) / denominator)) if denominator else 0
            closest = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]
            miles = distance(point, closest)
            if best is None or miles < best[0]:
                best = (miles, closest)
        if best is None or best[0] > 1 or not in_us(best[1], state_boundary):
            return set()
        return typed_roads(tags['ref'], state)
    except (KeyError, TypeError, ValueError, OverflowError):
        return set()


def roads_match(station, roads, point, state_boundary):
    required = whole_source_routes(station.address)
    if not required or not isinstance(roads, list) or not roads:
        return False
    found = set()
    for way in roads:
        present = nearby_road_refs(way, point, station.state, state_boundary)
        if not present:
            return False
        found.update(present)
    return required <= found
