from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import ASAP_SOURCE


class Command(OperatorCommand):
    help = 'Resolve ASAP General Store stations from local locator records.'
    source_url = ASAP_SOURCE
    namespaces = {'ASAP GENERAL STORE': 'ASAP GENERAL STORE'}
    datasource_name = 'ASAP'
    unique_operator_points = True
    wrap_raw_records = True
