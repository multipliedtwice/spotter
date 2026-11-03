import re

from planner.core import in_us
from planner.osm_evidence import canonical_source_name, evidence_city_key, normalized, refs, street_key, supported_street_address, valid_point

BILLING_SOURCE = 'https://www.roadrangerusa.com/locations-amenities/station-codes'
LOCATOR_SOURCE = 'https://www.roadrangerusa.com/locations-amenities/find-a-road-ranger'
BILLING_FIELDS = {'number', 'address', 'city', 'state', 'zip', 'opis', 'source'}
LOCATOR_FIELDS = {'number', 'address', 'city', 'state', 'zip', 'latitude', 'longitude', 'source'}


def address_parts(value):
    match = re.fullmatch(r'(.+),\s*([^,]+?)(?:,\s*|\s+)([A-Za-z]{2})(?:\s+(\d{5}(?:-\d{4})?))?\s*', value)
    return (match.group(1).strip(), match.group(2).strip(), match.group(3).upper(), match.group(4)) if match else None


def roadranger_address_key(store):
    try:
        parts = address_parts(store['billing']['address'])
        if not parts or not supported_street_address(parts[0]):
            return None
        return (street_key(parts[0]), evidence_city_key(parts[1]), parts[2])
    except (KeyError, TypeError):
        return None


def roadranger_key(store):
    if not isinstance(store, dict) or store.get('source') != LOCATOR_SOURCE or not isinstance(store.get('billing'), dict):
        return None
    billing = store['billing']
    number = billing.get('number')
    if billing.get('source') != BILLING_SOURCE or not isinstance(number, str) or not re.fullmatch(r'\d+', number):
        return None
    return ('ROAD RANGER', str(int(number)))


def roadranger_display(store):
    loc, billing = store['locator'], store['billing']
    return {'number': billing['number'], 'name': 'Road Ranger', 'address': loc['address'], 'city': loc['city'], 'state': loc['state'], 'latitude': loc['latitude'], 'longitude': loc['longitude'], 'source': LOCATOR_SOURCE}


def valid_roadranger_record(station, context, point, state_boundary):
    try:
        if not isinstance(context, dict) or set(context) != {'store', 'identity_only'} or context['identity_only'] is not True:
            return False
        store = context['store']
        if not isinstance(store, dict) or set(store) != {'source', 'billing', 'locator'} or not roadranger_key(store):
            return False
        b, loc = store['billing'], store['locator']
        if not isinstance(b, dict) or set(b) != BILLING_FIELDS or not isinstance(loc, dict) or set(loc) != LOCATOR_FIELDS or loc['source'] != LOCATOR_SOURCE or loc['number'] is not None:
            return False
        for item in (b, loc):
            if any(not isinstance(item[k], str) or not item[k].strip() for k in ('address', 'city', 'state', 'source')):
                return False
            parts = address_parts(item['address'])
            if not parts or not supported_street_address(parts[0]) or evidence_city_key(parts[1]) != evidence_city_key(item['city']) or parts[2] != normalized(item['state']) or parts[3] != item['zip']:
                return False
        first, second = address_parts(b['address']), address_parts(loc['address'])
        if street_key(first[0]) != street_key(second[0]) or evidence_city_key(first[1]) != evidence_city_key(second[1]) or first[2] != second[2] or (first[3] and second[3] and first[3] != second[3]):
            return False
        if evidence_city_key(loc['city']) != evidence_city_key(station.city) or normalized(loc['state']) != normalized(station.state):
            return False
        coords = [loc['latitude'], loc['longitude']]
        if not valid_point(coords) or coords != list(point) or not state_boundary or not in_us(coords, state_boundary):
            return False
        names = [row['Truckstop Name'] for row in station.rows]
        number = roadranger_key(store)[1]
        numbers = set().union(*(refs(name) for name in names))
        if numbers != {number} or not any(refs(name) == {number} for name in names) or not all(canonical_source_name(name) == 'ROAD RANGER' for name in names):
            return False
        opis = b['opis']
        if opis is not None and (not isinstance(opis, str) or not re.fullmatch(r'\d+', opis) or not re.fullmatch(r'\d+', station.source_id) or int(opis) != int(station.source_id)):
            return False
        return True
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
