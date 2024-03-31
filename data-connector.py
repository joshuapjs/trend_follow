import polars
import pandas as pd
import numpy as np
import ib_insync


class Asset:

    def __init__(self,
                 asset_symbol: str,
                 current_exchange: str,
                 current_currency: str,
                 last_quote: float):

        self.symbol = asset_symbol
        self.exchange = current_exchange
        self.currency = current_currency
        self.last_quote = last_quote
    
    def set_symbol(self, current_symbol):
        print("The symbol of an Asset must not be updated. Create a new Asset")

    def get_symbol(self):
        return self.symbol

    def set_exchange(self, current_symbol):
        print("The exchange of an Asset must not be updated. Create a new Asset")

    def get_exchange(self):
        return self.exchange

    def set_currency(self, current_symbol):
        print("The currency of an Asset must not be updated. Create a new Asset")

    def get_currency(self):
        return self.currency

    def set_quote(self, current_symbol):
        self.last_quote = last_quote
        print(f"last_quote of {self.symbol} was updated.") 
        return 1

    def get_currency(self):
        return self.last_quote


def connect_quote_stream(quote_symbol):
    # Setup of the client to request data from TWS
    ib_insync.util.startLoop()
    ib = ib_insync.IB()

    # Connect to local host
    ib.connect("127.0.0.1", 7496, clientId=15)

    # Prepare connection to websocket for quote_symbol
    current_stock = ib_insync.Stock(quote_symbol)
    # Request Bid/Ask quotes from TWS
    ticker = ib.reqTickByTickData(current_stock, 'BidAsk')
    
    ib.sleep(2)

    return ticker.marketPrice()


