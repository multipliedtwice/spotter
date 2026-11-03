from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import ROYAL_SOURCE


class Command(OperatorCommand):
    help = 'Resolve Royal Farms stations from local locator records.'
    source_url = ROYAL_SOURCE
    namespaces = {'ROYAL FARMS': 'ROYAL FARMS'}
    datasource_name = 'Royal Farms'
    unique_operator_points = True
    wrap_raw_records = True
