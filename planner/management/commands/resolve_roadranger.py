from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand


class Command(OperatorCommand):
    help = 'Resolve Road Ranger stations from local billing and locator facts.'
    source_url = None
    namespaces = {'ROAD RANGER': 'ROAD RANGER'}
    datasource_name = 'Road Ranger'
    unique_operator_points = True
    unique_operator_addresses = True
