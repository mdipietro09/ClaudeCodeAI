
'''
[{'symbol': 'IT000553414=MI',
  'full_name': 'Milan:IT000553414=MI',
  'description': 'Italy 4.5 01-Oct-2053',
  'type': 'Bond Yield',
  'ticker': '1200542',
  'exchange': 'Milan'}]
'''

from datetime import datetime

today = datetime.today().strftime("%m/%d/%Y")

import investiny

investing_id = "1200542"

start = "01/01/2026"

data = investiny.historical_data(investing_id=investing_id, from_date=start, to_date=today)
print(data)