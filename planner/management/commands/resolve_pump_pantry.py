from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import PUMP_PANTRY_SOURCE


class Command(OperatorCommand):
    help = 'Resolve Pump & Pantry stations from local published locator records.'
    source_url = PUMP_PANTRY_SOURCE
    namespaces = {'PUMP PANTRY': 'PUMP PANTRY'}
    datasource_name = 'Pump & Pantry'
    unique_operator_points = True
    wrap_raw_records = True
