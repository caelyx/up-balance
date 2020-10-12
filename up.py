#!/usr/bin/env python3
# Check the balance of your Up accounts from the terminal
# Get an API Key at https://api.up.com.au/ and put it in config.py
# Usage ./up.py

import requests
from config import APIKEY

def requestAccounts():
  headers = {"Authorization": "Bearer %s" % APIKEY}
  r = requests.get('https://api.up.com.au/api/v1/accounts', headers=headers)
  output = r.json()
  return output

def main():
  output = requestAccounts()

  balances = {}
  for a in output['data']:
    if not a['type'] == 'accounts':
      next
    balances[a['attributes']['displayName']] = float(a['attributes']['balance']['value'])

  total = 0
  for b in balances:
    print ("{:8.2f} {}".format(balances[b], b))
    total += balances[b]
  print ("--------")
  print ("{:8.02f}".format(total))

  return balances



if __name__ == "__main__":
  main()