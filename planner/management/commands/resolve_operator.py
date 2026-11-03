from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand


class Command(OperatorCommand):
    help = 'Resolve Maverik and QuikTrip stations from local operator records.'
    source_url = None
    namespaces = {'MAVERIK': 'MAVERIK', 'QUIKTRIP': 'QUIKTRIP'}
    datasource_name = 'Operator'
