import json

from planner.osm_evidence import canonical_source_name, normalized, refs


def load_shared_operator_approvals(base_dir):
    try:
        value = json.loads((base_dir / 'data/approved_shared_operator_locations.json').read_text())
        return value['records'] if set(value) == {'records'} and isinstance(value['records'], list) else []
    except (OSError, ValueError, KeyError, TypeError):
        return []


def approved_shared_operator(owners, store, approvals):
    try:
        if len(owners) != 2 or len({o.source_id for o in owners}) != 2:
            return False
        for approval in approvals:
            if set(approval) != {'owners', 'store'} or not isinstance(approval['owners'], list) or len(approval['owners']) != 2 or store != approval['store']:
                continue
            if (store.get('source') != 'https://www.kwiktrip.com/Maps-Downloads/Store-List' or store.get('number') != '748' or store.get('name') != 'KWIK TRIP #748' or store.get('address') != '1456 E LA SALLE AVE' or store.get('city') != 'BARRON' or store.get('state') != 'WI' or [store.get('latitude'), store.get('longitude')] != [45.40061, -91.83492]):
                continue
            expected = {(o['station_id'], normalized(o['address']), normalized(o['city']), normalized(o['state'])) for o in approval['owners'] if set(o) == {'station_id', 'address', 'city', 'state'}}
            actual = {(o.source_id, normalized(o.address), normalized(o.city), normalized(o.state)) for o in owners}
            if expected != {('72812', 'US 8', 'BARRON', 'WI'), ('73096', 'US 8', 'BARRON', 'WI')} or actual != expected:
                continue
            if all(o.rows and all(canonical_source_name(row['Truckstop Name']) == 'KWIK TRIP' and refs(row['Truckstop Name']) == {'748'} for row in o.rows) for o in owners):
                return True
        return False
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
