import json
import re

from planner.osm_evidence import normalized, typed_roads
from planner.road import road_marker_keys


def load_operator_approvals(base_dir):
    records = []
    for name in ('approved_operator_locations.json', 'approved_named_plazas.json'):
        try:
            with (base_dir / 'data' / name).open(encoding='utf-8') as stream:
                asset = json.load(stream)
            if isinstance(asset, dict) and isinstance(asset.get('records'), list):
                records.extend(asset['records'])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return records


def approved_named_plaza(station, store, approvals):
    try:
        fields = {'kind', 'station_id', 'address', 'city', 'state', 'source', 'store'}
        entries = [entry for entry in approvals if isinstance(entry, dict) and set(entry) == fields and entry['kind'] == 'named_plaza' and entry['station_id'] == '293' and normalized(entry['address']) == 'I-35, MILE MARKER 97' and normalized(entry['city']) == 'MATFIELD GREEN' and normalized(entry['state']) == 'KS' and entry['source'] == 'https://www.loves.com/api/fetch_stores' and entry['store'] == store]
        if len(entries) != 1 or station.source_id != '293' or normalized(station.address) != 'I-35, MILE MARKER 97' or normalized(station.city) != 'MATFIELD GREEN' or normalized(station.state) != 'KS':
            return False
        if store.get('number') != 176 or store.get('city') != 'Cassoday' or store.get('preferredName') != 'Matfield Green Turnpike - SRI' or store.get('address1') != 'Mile 97 Kansas Turnpike' or store.get('state') != 'KS' or store.get('highway') != 'I-35' or store.get('exitNumber') != 'Mile 97' or [store.get('latitude'), store.get('longitude')] != [38.095391, -96.579511] or store.get('isLoveStore') is not True or store.get('isCountryStore') is not False:
            return False
        expected = {('I', '35', 'mile', '97')}
        return road_marker_keys(station.address) == expected and road_marker_keys(store['highway'] + ' ' + store['exitNumber']) == expected
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return False


def approved_primary_exit(station, store, approvals):
    fields = {'station_id', 'address', 'city', 'state', 'number', 'latitude', 'longitude', 'source', 'highway', 'exitNumber', 'unverified_source_details'}
    try:
        number = store['number']
        if isinstance(number, bool) or not isinstance(number, (str, int)) or not re.fullmatch(r'\d+', str(number)):
            return False
        marker = store['exitNumber']
        if isinstance(marker, bool) or not isinstance(marker, (str, int)):
            return False
        matches = []
        for entry in approvals:
            if not isinstance(entry, dict) or set(entry) != fields:
                continue
            approved_number = entry['number']
            if isinstance(approved_number, bool) or not isinstance(approved_number, (str, int)) or not re.fullmatch(r'\d+', str(approved_number)):
                continue
            if not all(isinstance(entry[k], str) for k in ('station_id', 'address', 'city', 'state', 'source', 'highway', 'unverified_source_details')):
                continue
            if (entry['station_id'] == station.source_id and normalized(entry['address']) == normalized(station.address)
                and normalized(entry['city']) == normalized(station.city) and normalized(entry['state']) == normalized(station.state)
                and normalized(entry['unverified_source_details']) == normalized(station.address)
                and int(approved_number) == int(number) and entry['source'] == 'https://www.loves.com/api/fetch_stores'
                and type(entry['latitude']) in (int, float) and type(entry['longitude']) in (int, float)
                and [entry['latitude'], entry['longitude']] == [store['latitude'], store['longitude']]
                and entry['highway'] == store['highway'] and type(entry['exitNumber']) is type(marker) and entry['exitNumber'] == marker):
                matches.append(entry)
        if len(matches) != 1:
            return False
        source_markers = re.findall(r'\bEXIT\s*#?\s*(\d+[A-Z]?)(?![A-Z0-9])', normalized(station.address))
        if len(source_markers) != 1:
            return False
        keys = road_marker_keys(f"{store['highway']} EXIT {marker}")
        if not keys or len(keys) != 1:
            return False
        kind, road, marker_type, exit_number = next(iter(keys))
        return marker_type == 'exit' and exit_number == source_markers[0] and (kind, road) in typed_roads(station.address, station.state)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
