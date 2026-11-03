import csv
import json
import re
from collections import Counter, defaultdict
from statistics import median
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from planner.models import City, Station
from planner.core import in_us, load_boundary
from planner.road import marker_keys_match, road_marker_keys
from planner.osm_evidence import compound_routes_match, normalize_ref, street_key, supported_street_address
from django.conf import settings

STATES = set('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split())

def norm(value):
    return re.sub(r'\s+', ' ', value.strip()).upper()

def station_match(source_names, source_address, matched_name, matched_address, state=None):
    name = norm(matched_name).replace("'", '').replace('’', '')
    address = norm(matched_address)
    if not name or not address:
        return False
    def numbers(value):
        return {normalize_ref(number) for number in re.findall(r'(?<![A-Z0-9])\d+[A-Z]?(?![A-Z0-9])', value)}
    matched_numbers = numbers(name)
    generic = {'TRAVEL', 'CENTER', 'CENTRE', 'TRUCK', 'STOP', 'FUEL', 'GAS', 'STATION', 'THE', 'AND', 'INC'}
    def words(value):
        return {word for word in re.findall(r'[A-Z]+', value) if len(word) >= 3 and word not in generic}
    brands = {'PILOT', 'LOVE', 'LOVES', 'KWIK', 'TRIP', 'TRAVELCENTERS', 'SPEEDWAY', 'FLYING', 'SHELL', 'MOBIL', 'EXXON', 'CHEVRON', 'MARATHON'}
    names_match = any((normalized == name and len(words(name) - brands) >= 2) or bool(numbers(normalized) & matched_numbers and words(normalized) & words(name)) for normalized in (norm(source).replace("'", "").replace("’", "") for source in source_names))
    source_keys, matched_keys = road_marker_keys(source_address), road_marker_keys(address)
    marker_match = marker_keys_match(source_keys, matched_keys, source_address) and compound_routes_match(source_address, address, state)
    address_match = source_keys is not None and matched_keys is not None and (
        (len(source_address) >= 6 and source_address == address)
        or (supported_street_address(source_address) and supported_street_address(address)
            and street_key(source_address) == street_key(address))
    )
    return names_match and (marker_match or address_match)

GOVERNMENT_SUFFIX = re.compile(r'\s+(?:metropolitan government|metro government|unified government|consolidated government|urban county)$')
PLAIN_SUFFIX = re.compile(r'\s+(?:city and|city|corporation)$')

def alias_name(name):
    name = name.strip()
    if GOVERNMENT_SUFFIX.search(name):
        return re.split(r'[-/,]', GOVERNMENT_SUFFIX.sub('', name))[0].strip()
    return PLAIN_SUFFIX.sub('', name).strip()

def gazetteer_aliases(rows):
    taken = {(norm(row['name']), norm(row['state'])) for row in rows}
    aliases = []
    for row in rows:
        alias = alias_name(row['name'])
        key = (norm(alias), norm(row['state']))
        if alias and key not in taken:
            taken.add(key)
            aliases.append({**row, 'name': alias})
    return aliases

class Command(BaseCommand):
    help = 'Import source stations or verified evidence or local gazetteer.'

    def add_arguments(self, parser):
        parser.add_argument('kind', choices=['stations', 'evidence', 'gazetteer'])
        parser.add_argument('path')

    @transaction.atomic
    def handle(self, kind, path, **options):
        with open(path, newline='', encoding='utf-8-sig') as stream:
            rows = list(csv.DictReader(stream))
        if kind == 'stations':
            groups = defaultdict(list)
            ids = defaultdict(set)
            for row in rows:
                state = norm(row['State'])
                if state not in STATES:
                    continue
                key = (row['OPIS Truckstop ID'].strip(), norm(row['Address']), norm(row['City']), state)
                groups[key].append(row)
                ids[key[0]].add(key[1:])
            Station.objects.all().delete()
            objects = []
            for (source_id, address, city, state), source in groups.items():
                unique = {json.dumps(row, sort_keys=True): row for row in source}
                prices = [float(row['Retail Price']) for row in unique.values()]
                objects.append(Station(source_id=source_id, name=source[0]['Truckstop Name'].strip(), address=address, city=city, state=state, rows=source, price=median(prices), price_min=min(prices), price_max=max(prices)))
            Station.objects.bulk_create(objects)
            self.stdout.write(f'Imported {len(objects)} station groups; {sum(len(v) > 1 for v in ids.values())} IDs have conflicting locations.')
        elif kind == 'gazetteer':
            rows = rows + gazetteer_aliases(rows)
            City.objects.all().delete()
            City.objects.bulk_create([City(name=r['name'].strip(), state=norm(r['state']), latitude=float(r['latitude']), longitude=float(r['longitude'])) for r in rows])
            self.stdout.write(f'Imported {len(rows)} cities.')
        else:
            try:
                boundary = load_boundary(settings.BASE_DIR / 'data/us_boundary.geojson')
                if boundary.get('type') != 'FeatureCollection':
                    raise ValueError('State features required')
                states = {}
                for feature in boundary['features']:
                    properties = feature.get('properties') if isinstance(feature, dict) and feature.get('type') == 'Feature' else None
                    state = properties.get('STUSPS') if isinstance(properties, dict) else None
                    if not isinstance(state, str) or state not in STATES or state in states:
                        raise ValueError('Invalid state feature')
                    states[state] = feature
                required = set(Station.objects.values_list('state', flat=True).distinct())
                if not required <= states.keys():
                    raise ValueError('Missing state feature')
            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                raise CommandError('Valid state boundary features required for evidence import.') from exc
            from planner.osm_evidence import evidence_city_key, identity_tags, matched_values, valid_context
            from planner.directory_evidence import OPIS_SOURCE, directory_key, directory_record, valid_directory_record
            from planner.ambest_evidence import SOURCE as AMBEST_SOURCE, native_point, observed_point
            from planner.wex_evidence import ENDPOINT as WEX_ENDPOINT, SOURCE as WEX_SOURCE, native_point as wex_native_point, observed_point as wex_observed_point
            from planner.onvo_evidence import onvo_observed_point, onvo_view
            from planner.operator_evidence import LOVES_SOURCE, operator_display, operator_store_key, valid_loves_route_record, valid_operator_record
            from planner.operator_approval import load_operator_approvals
            from planner.roadranger_evidence import roadranger_address_key
            from planner.shared_operator_approval import approved_shared_operator, load_shared_operator_approvals
            approvals = load_operator_approvals(settings.BASE_DIR)
            shared_approvals = load_shared_operator_approvals(settings.BASE_DIR)
            directory_sources = Counter()
            try:
                ambest_asset = json.loads((settings.BASE_DIR / 'data/source_ambest_locations.json').read_text())
                ambest_records = ambest_asset['records'] if set(ambest_asset) == {'source', 'records'} and ambest_asset['source'] == AMBEST_SOURCE and isinstance(ambest_asset['records'], list) else []
                ambest_ids = Counter(record['id'] for record in ambest_records if isinstance(record, dict) and type(record.get('id')) is int)
                ambest_points = Counter(tuple(point) for record in ambest_records if (point := observed_point(record)) is not None)
            except (OSError, ValueError, KeyError, TypeError):
                ambest_records, ambest_ids, ambest_points = [], Counter(), Counter()
            try:
                wex_asset = json.loads((settings.BASE_DIR / 'data/source_wex_locations.json').read_text())
                wex_records = wex_asset['records'] if isinstance(wex_asset, dict) and wex_asset.get('source') == WEX_SOURCE and wex_asset.get('endpoint') == WEX_ENDPOINT and isinstance(wex_asset.get('records'), list) else []
                wex_ids = Counter(record['siteId'] for record in wex_records if isinstance(record, dict) and isinstance(record.get('siteId'), str))
                wex_points = Counter(tuple(point) for record in wex_records if (point := wex_observed_point(record)) is not None)
            except (OSError, ValueError, KeyError, TypeError):
                wex_records, wex_ids, wex_points = [], Counter(), Counter()
            try:
                onvo_asset = json.loads((settings.BASE_DIR / 'data/source_onvo_locations.json').read_text())
                onvo_records = onvo_asset['records'] if isinstance(onvo_asset, dict) and set(onvo_asset) == {'records'} and isinstance(onvo_asset['records'], list) else []
                onvo_urls = Counter(record['source_url'] for record in onvo_records if isinstance(record, dict) and isinstance(record.get('source_url'), str))
                onvo_points = Counter(tuple(point) for record in onvo_records if (point := onvo_observed_point(record)) is not None)
            except (OSError, ValueError, KeyError, TypeError):
                onvo_records, onvo_urls, onvo_points = [], Counter(), Counter()
            from planner.raw_operator_evidence import KENTKWIK_SOURCE, PARKERS_SOURCE, validated_kentkwik_records, validated_parkers_records
            try:
                parkers_records = validated_parkers_records(json.loads((settings.BASE_DIR / 'data/source_parkers_locations.json').read_text()))
            except (OSError, ValueError, KeyError, TypeError):
                parkers_records = []
            try:
                kentkwik_records = validated_kentkwik_records(json.loads((settings.BASE_DIR / 'data/source_kentkwik_locations.json').read_text()))
            except (OSError, ValueError, KeyError, TypeError):
                kentkwik_records = []
            for row in rows:
                try:
                    key = directory_key(json.loads(row.get('directory_evidence', '') or '{}'))
                    if key:
                        directory_sources[key] += 1
                except (ValueError, TypeError):
                    pass
            operator_numbers = Counter()
            operator_owner_rows = defaultdict(list)
            operator_points = Counter()
            roadranger_addresses = Counter()
            for row in rows:
                try:
                    context = json.loads(row.get('operator_evidence', '') or '{}')
                    store = context.get('store', {})
                    key = operator_store_key(store, context.get('source'))
                    if key is not None:
                        operator_numbers[key] += 1
                        operator_owner_rows[key].append((row, store))
                        if key[0] in ('ROAD RANGER', 'RACETRAC', 'RACEWAY', 'RUTTERS', 'THORNTONS', 'PUMP PANTRY', 'SUNSTOP', 'TOOTN TOTUM', 'ROYAL FARMS', '7FLEET', 'TEX BEST', 'ASAP GENERAL STORE', 'HUCKS', 'JET FOOD', 'GOOD 2 GO', 'SPINX', 'PETES', 'DUCK THRU', 'DANDY', 'PARKERS', 'KENT KWIK'):
                            view = operator_display(store)
                            coords = [view.get('latitude'), view.get('longitude')]
                            from planner.osm_evidence import valid_point
                            if valid_point(coords):
                                operator_points[tuple(coords)] += 1
                            if key[0] == 'ROAD RANGER':
                                address_key = roadranger_address_key(store)
                                if address_key:
                                    roadranger_addresses[address_key] += 1
                except (ValueError, AttributeError, KeyError, TypeError):
                    pass
            city_points = defaultdict(list)
            for city in City.objects.all():
                city_points[(evidence_city_key(city.name), norm(city.state))].append([city.latitude, city.longitude])
            coordinates = defaultdict(set)
            for row in rows:
                try:
                    point = (float(row['latitude']), float(row['longitude']))
                except (ValueError, TypeError, KeyError):
                    point = (str(row.get('latitude', '')).strip(), str(row.get('longitude', '')).strip())
                coordinates[(row['station_id'].strip(), norm(row['address']), norm(row['city']), norm(row['state']))].add(point)
            conflicts = sorted(key for key, points in coordinates.items() if len(points) > 1)
            if conflicts:
                raise CommandError('Conflicting evidence coordinates for station groups: ' + '; '.join('|'.join(key) for key in conflicts))
            Station.objects.update(latitude=None, longitude=None, evidence={})
            accepted = 0
            for row in rows:
                matches = Station.objects.filter(source_id=row['station_id'].strip(), address=norm(row['address']), city=norm(row['city']), state=norm(row['state']))
                station = matches.first() if matches.count() == 1 else None
                names = {norm(r['Truckstop Name']) for r in station.rows} if station else set()
                if not station or not row['source'].strip():
                    continue
                try:
                    lat, lon = float(row['latitude']), float(row['longitude'])
                except (ValueError, TypeError, KeyError):
                    continue
                osm_text = row.get('osm_evidence', '').strip()
                directory_text = row.get('directory_evidence', '').strip()
                operator_text = row.get('operator_evidence', '').strip()
                if sum(bool(value) for value in (osm_text, directory_text, operator_text)) > 1:
                    continue
                if osm_text:
                    try:
                        context = json.loads(osm_text)
                        source = f"https://www.openstreetmap.org/{context['type']}/{context['id']}"
                        if row['source'] != source or not valid_context(station, context, [lat, lon], states[station.state], city_points[(evidence_city_key(station.city), norm(station.state))]):
                            continue
                    except (ValueError, KeyError, TypeError):
                        continue
                elif directory_text:
                    try:
                        context = json.loads(directory_text)
                        record = directory_record(context)
                        if not isinstance(context, dict) or not isinstance(record, dict) or directory_sources[directory_key(context)] != 1 or row['source'] != record.get('source') or not valid_directory_record(station, context, [lat, lon], states[station.state]):
                            continue
                        if record.get('source') == AMBEST_SOURCE:
                            raw = record.get('record')
                            point = native_point(raw)
                            if point is None or raw not in ambest_records or ambest_ids[raw['id']] != 1 or ambest_points[tuple(point)] != 1:
                                continue
                        if record.get('source') == WEX_SOURCE:
                            raw = record.get('record')
                            point = wex_native_point(raw)
                            if point is None or raw not in wex_records or wex_ids[raw['siteId']] != 1 or wex_points[tuple(point)] != 1:
                                continue
                        if directory_key(context)[0] == 'ONVO':
                            raw = record.get('record')
                            view = onvo_view(raw)
                            if view is None or raw not in onvo_records or onvo_urls[view['source']] != 1 or onvo_points[(view['latitude'], view['longitude'])] != 1:
                                continue
                    except (ValueError, KeyError, TypeError):
                        continue
                elif operator_text:
                    try:
                        context = json.loads(operator_text)
                        if not isinstance(context, dict) or not isinstance(context.get('store'), dict):
                            continue
                        number = operator_display(context['store']).get('number', context['store'].get('id'))
                        source = context.get('source', context['store'].get('source'))
                        key = operator_store_key(context['store'], context.get('source'))
                        valid = valid_loves_route_record(station, context, [lat, lon], states[station.state], approvals) if source == LOVES_SOURCE else valid_operator_record(station, context, [lat, lon], states[station.state])
                        shared = False
                        if key is not None and operator_numbers[key] == 2:
                            entries = operator_owner_rows[key]
                            owners = []
                            for owner_row, owner_store in entries:
                                owner_matches = Station.objects.filter(source_id=owner_row['station_id'], address__iexact=owner_row['address'], city__iexact=owner_row['city'], state__iexact=owner_row['state'])
                                if owner_store != context['store'] or owner_matches.count() != 1 or [float(owner_row['latitude']), float(owner_row['longitude'])] != [lat, lon]:
                                    break
                                owners.append(owner_matches.first())
                            shared = approved_shared_operator(owners, context['store'], shared_approvals)
                        if isinstance(number, bool) or not isinstance(number, (int, str)) or not isinstance(source, str) or key is None or (operator_numbers[key] != 1 and not shared) or row['source'] != source or not valid:
                            continue
                        if key[0] in ('ROAD RANGER', 'RACETRAC', 'RACEWAY', 'RUTTERS', 'THORNTONS', 'PUMP PANTRY', 'SUNSTOP', 'TOOTN TOTUM', 'ROYAL FARMS', '7FLEET', 'TEX BEST', 'ASAP GENERAL STORE', 'HUCKS', 'JET FOOD', 'GOOD 2 GO', 'SPINX', 'PETES', 'DUCK THRU', 'DANDY', 'PARKERS', 'KENT KWIK') and operator_points[(lat, lon)] != 1:
                            continue
                        if source == PARKERS_SOURCE:
                            if context['store'].get('record') not in parkers_records:
                                continue
                        if source == KENTKWIK_SOURCE and context['store'].get('record') not in kentkwik_records:
                            continue
                        if key[0] == 'ROAD RANGER' and roadranger_addresses[roadranger_address_key(context['store'])] != 1:
                            continue
                    except (ValueError, KeyError, TypeError):
                        continue
                elif not station_match(names, station.address, row['matched_name'], row['matched_address'], station.state):
                    continue
                if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not in_us([lat, lon], states[station.state]):
                    continue
                station.latitude, station.longitude = lat, lon
                station.evidence = {'matched_name': row['matched_name'], 'matched_address': row['matched_address'], 'source': row['source'], **{field: row[field] for field in ('source_row_ids', 'place_id', 'datasource_name', 'datasource_license', 'datasource_attribution', 'datasource_url') if row.get(field)}}
                if osm_text:
                    station.evidence['matched_name'], station.evidence['matched_address'] = matched_values(identity_tags(context))
                    station.evidence.update({'place_id': str(context['id']), 'datasource_name': 'OpenStreetMap', 'datasource_license': 'ODbL', 'datasource_attribution': 'OpenStreetMap contributors', 'datasource_url': 'https://www.openstreetmap.org/copyright', 'osm_evidence': context})
                elif directory_text:
                    record = directory_record(context)
                    if directory_key(context)[0] == 'ONVO':
                        view = onvo_view(record['record'])
                        station.evidence.update({'matched_name': view['name'], 'matched_address': view['address'], 'verification_scope': 'operator_branch_and_address', 'directory_evidence': context})
                    elif record.get('source') in (AMBEST_SOURCE, WEX_SOURCE):
                        address_field = 'directory_address' if record['source'] == AMBEST_SOURCE else 'address'
                        station.evidence.update({'matched_name': record['record']['name'], 'matched_address': record['record'][address_field], 'directory_evidence': context})
                    else:
                        station.evidence.update({'matched_name': record['name'], 'matched_address': record['address2'] if record['source'] == OPIS_SOURCE else record['address'], 'directory_evidence': context})
                elif operator_text:
                    if context.get('source') == LOVES_SOURCE:
                        store = context['store']
                        raw_marker = store.get('exitNumber')
                        marker = str(raw_marker).strip() if isinstance(raw_marker, (str, int)) and not isinstance(raw_marker, bool) else ''
                        station.evidence.update({'matched_name': f"Love's #{store['number']}", 'matched_address': ' '.join(value for value in (store.get('address1', ''), store['highway'], marker) if value), 'operator_evidence': context})
                        if context.get('approved_primary_exit') is True:
                            station.evidence.update({'verification_scope': 'operator_identity_and_primary_exit', 'unverified_source_address_details': station.address})
                        if context.get('approved_named_plaza') is True:
                            station.evidence.update({'verification_scope': 'operator_identity_and_named_plaza', 'operator_postal_city': store['city'], 'operator_location_label': store['preferredName']})
                    else:
                        view = operator_display(context['store'])
                        station.evidence.update({'matched_name': view['name'], 'matched_address': view['address'], 'operator_evidence': context})
                        if 'roads' in context:
                            station.evidence['verification_scope'] = 'operator_identity_and_nearby_named_roads'
                    if context.get('identity_only') is True:
                        street = context['store']['address1'] if context.get('source') == LOVES_SOURCE else operator_display(context['store'])['address']
                        station.evidence.update({'matched_address': street, 'verification_scope': 'operator_identity_only', 'unverified_source_address_details': station.address})
                station.save(update_fields=['latitude', 'longitude', 'evidence'])
                accepted += 1
            self.stdout.write(f'Accepted {accepted} evidence records of {len(rows)}.')
