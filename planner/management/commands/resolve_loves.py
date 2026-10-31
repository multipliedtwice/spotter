import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from planner.core import in_us, load_boundary
from planner.evidence import COLUMNS
from planner.management.commands.load_data import norm, station_match
from planner.models import Station

SOURCE = 'https://www.loves.com/api/fetch_stores'


def is_loves(station):
    return any(re.search(r'\bLOVES\b', norm(row['Truckstop Name']).replace("'", '').replace('’', '')) for row in station.rows)


def source_numbers(station):
    found = set()
    for row in station.rows:
        name = norm(row['Truckstop Name']).replace("'", '').replace('’', '')
        if re.search(r'\bLOVES\b', name):
            found.update(re.findall(r'(?<![A-Z0-9])\d+[A-Z]?(?![A-Z0-9])', name))
    return found


def match_store(station, store, state_boundary):
    if not isinstance(store, dict) or store.get('isLoveStore') is not True:
        return None
    number = store.get('number')
    if isinstance(number, bool) or not isinstance(number, (int, str)) or not re.fullmatch(r'\d+', str(number)) or str(number) not in source_numbers(station):
        return None
    city, state = store.get('city'), store.get('state')
    city_key = lambda value: re.sub(r'[^A-Z0-9]', '', norm(value))
    if not isinstance(city, str) or not isinstance(state, str) or city_key(city) != city_key(station.city) or norm(state) != norm(station.state):
        return None
    try:
        lat, lon = store['latitude'], store['longitude']
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lat, lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
    except KeyError:
        return None
    name = f"Love's #{number}"
    names = {row['Truckstop Name'] for row in station.rows}
    address = store.get('address1')
    addresses = [address] if isinstance(address, str) else []
    highway, exit_value = store.get('highway'), store.get('exitNumber')
    if isinstance(highway, str) and isinstance(exit_value, (str, int)) and not isinstance(exit_value, bool):
        raw_marker = str(exit_value).strip()
        if re.match(r'^(?:MM|MILE)', raw_marker, re.IGNORECASE):
            addresses.append(f'{highway} {raw_marker}')
        elif re.match(r'^\d', raw_marker):
            addresses.append(f'{highway} EXIT {raw_marker}')
    matched_address = next((value for value in addresses if station_match(names, station.address, name, value)), None)
    if not matched_address or not state_boundary or not in_us([lat, lon], state_boundary):
        return None
    return {'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state,
            'latitude': lat, 'longitude': lon, 'matched_name': name, 'matched_address': matched_address,
            'source': SOURCE, 'source_row_ids': '|'.join(f'{station.source_id}:{i+1}' for i in range(len(station.rows))),
            'place_id': str(number), 'datasource_name': "Love's Travel Stops", 'datasource_license': '',
            'datasource_attribution': '', 'datasource_url': SOURCE}


class Command(BaseCommand):
    help = "Resolve source station evidence offline from Love's operator store data."

    def add_arguments(self, parser):
        parser.add_argument('--input', required=True)
        parser.add_argument('--output', required=True)
        parser.add_argument('--unresolved', required=True)

    def handle(self, input, output, unresolved, **options):
        source, output_path, unresolved_path = map(Path, (input, output, unresolved))
        if len({path.resolve() for path in (source, output_path, unresolved_path)}) != 3:
            raise CommandError('Input and output paths must be distinct.')
        if output_path.exists() or unresolved_path.exists():
            raise CommandError('Output exists; choose new output paths.')
        try:
            with source.open(encoding='utf-8') as stream:
                asset = json.load(stream)
            if not isinstance(asset, dict) or not isinstance(asset.get('stores'), list):
                raise ValueError()
            boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
            features = boundary.get('features') if boundary.get('type') == 'FeatureCollection' else None
            if not isinstance(features, list):
                raise ValueError()
            states = {feature['properties']['STUSPS']: feature for feature in features if isinstance(feature, dict) and isinstance(feature.get('properties'), dict) and isinstance(feature['properties'].get('STUSPS'), str)}
            if not states:
                raise ValueError()
        except (OSError, UnicodeError, ValueError) as exc:
            raise CommandError('Valid operator asset and state boundary data required.') from exc
        stores = defaultdict(list)
        for store in asset['stores']:
            if isinstance(store, dict):
                stores[str(store.get('number', ''))].append(store)
        stations = [station for station in Station.objects.order_by('pk') if is_loves(station)]
        candidates, owners = defaultdict(list), defaultdict(set)
        for station in stations:
            for number in source_numbers(station):
                for index, store in enumerate(stores[number]):
                    evidence = match_store(station, store, states.get(station.state))
                    if evidence:
                        identity = (number, index)
                        candidates[station.pk].append((identity, evidence))
                        owners[identity].add(station.pk)
        rows, missing = [], []
        for station in stations:
            matches = candidates[station.pk]
            if len(matches) == 1 and len(owners[matches[0][0]]) == 1:
                rows.append(matches[0][1])
            else:
                missing.append({'station_id': station.source_id, 'address': station.address, 'city': station.city, 'state': station.state,
                                'reason': 'ambiguous_match' if matches else 'no_matching_operator_store'})
        for path, columns, entries in ((output_path, COLUMNS, rows), (unresolved_path, ('station_id', 'address', 'city', 'state', 'reason'), missing)):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(entries)
        self.stdout.write(f'Evidence rows: {len(rows)}. Unresolved groups: {len(missing)}.')
