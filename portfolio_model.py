"""
This module contains the relevant functions to size the current positions that should be taken,
according to the alpha_model properly.
"""
import os
import copy
from data_connector import Pair
from tws_connection import ib, build_connection
import pandas as pd

ACCOUNT_NUMBER = "DU8322667" # TODO: Create a data file that has all constants
PORTFOLIO_VALUE = 1000000.
ASSETS_TRADED = 10

# Check if a connection exists already
if not ib.isConnected():
    build_connection()


class Portfolio:
    """
    This class is used to manage the current Portfolio.
    """

    def __init__(self):
        self.profile = ACCOUNT_NUMBER
        self.empty_slots = copy.copy(ASSETS_TRADED)
        # TODO This should be improved if there is a risk model.
        self.followed_signals = {}
        self.ignored_signals = {}
        self.position_pnl = {}
        self.pairs_traded = {}
        self.portfolio = {}  # TODO The Amount of shares should be logged as well

    def analyze_signals(self, alpha_model_output):
        """
        Receives new Signals generated by alpha_model and determines how they will be handled.
        :param new_signals: list of signals of type: (deviation, sign, pair, quote_a, quote_b)
                            deviation: means the potential return, as the divergence between two stocks.
                            sign: is the direction with respect to ticker_a and ticker_b.
                            pair: is the Pair-Class-Object.
                            quote_a and quote_b: the respective most recent quotes.
                            const and slope: Parameters of the relationship between the stocks
        :return: Execution update (Information for the Execution Model which transactions to do)
        """
        new_signals, pairs = alpha_model_output  # TODO find a better name this sounds stupid.
        portfolio_adjustment = {}

        # Retrieve and sort the signals generated by the alpha model.
        if isinstance(new_signals, dict):
            signals = list(new_signals.values())
        else:
            signals = new_signals

        # store the pairs traded by the model to access market data.
        self.pairs_traded.update(pairs)
        
        signals.sort(key=lambda a: a[0], reverse=True)
        # Calculate the amounts of shares need for each trade as long as there are still slots open.
        # Slot is the wording for each budget that can be traded on a pair. The risk strategy is at this point
        # equal weighting.
        for signal in signals:
            # Calculation of the amount of shares for each stock.
            deviation, sign, pair, quotes, const, slope = signal
            # To log properly which signal was followed the class "pair" in the "signal"
            # must be exported, otherwise the reference is saved and the information lost.
            signal_log_version = (deviation, sign, pair.export(), quotes, const, slope)
            if self.empty_slots > 0:  # TODO it should be factored in how (im)probable the deviation is! Through Percentile in the distribution.
                # TODO The Ignored signals should be compared too, while discriminating after timeliness.
                ticker_a, ticker_b = pair.tickers
                # Formel zur Berechnung des Anteils von b.
                shares_b = ((PORTFOLIO_VALUE / ASSETS_TRADED - const * quotes[ticker_a].ask) *
                            (1 / (slope * quotes[ticker_a].ask + quotes[ticker_b].ask)))
                shares_a = const + slope * shares_b
                # Preparation of the output.
                portfolio_adjustment[ticker_a] = int(shares_a)
                portfolio_adjustment[ticker_b] = int(shares_b)
                self.followed_signals[pair.export()[0][0]] = signal_log_version
                self.followed_signals[pair.export()[0][1]] = signal_log_version
                self.empty_slots -= 1
            else:
                self.ignored_signals[frozenset(pair.export()[0][0])] = signal_log_version
                self.ignored_signals[frozenset(pair.export()[0][1])] = signal_log_version
                break

        pd.DataFrame(self.followed_signals).to_csv(r"./log/followed_signals_log.csv")

        return portfolio_adjustment

    def optimize(self):
        portfolio_adjustment = {}
        # Get the current positions from IBKR.
        current_positions = ib.positions(self.profile)
        # Get the current signals that where discovered but not followed yet.
        current_ignored_signals = list(copy.copy(list(self.ignored_signals.values())))
        current_ignored_signals.sort(key=lambda a: a[0], reverse=True)

        # Instantiate a new list to gather the signals that 
        # should be followed in following optimization process.
        signals_to_follow = []
       
        # First the pnl of the positions has the be calculated
        # as there is no out-of-the-box support.
        for position in current_positions:
            # Get the ticker of the current position looked at.
            ticker = position.contract.symbol
            # Get the average price that was realized while creating the position.
            buy_in = position.avgCost
            # Get the current price of the Asset.
            current_price = self.followed_signals[ticker][3][ticker].ask
            # TODO As the pairs are available the realtime price could be used.
            # Calculate the current pnl of the position and safe it.
            current_pnl = (current_price - buy_in) / buy_in
            self.position_pnl[ticker] = current_pnl
        stocks_to_check = copy.copy(self.followed_signals)
        
        # Now the pnls have to be aggregated for each signal that was followed
        # and has to be compared to the projected pnl.
        for signal in list(stocks_to_check.values()):
            # Get the tickers for both positions.
            tickers, currency = signal[2]
            ticker_a, ticker_b = tickers
            # Get the projected retorn of the signal.
            expected_return = signal[0]
            current_pnl = self.position_pnl[ticker_a] + self.position_pnl[ticker_b]
            expected_potential = expected_return - current_pnl
            if expected_potential <= 0:
                # If the unrealized return tops or fulfills the prognosis the position should be cleared.
                portfolio_adjustment[ticker_a] = 0
                portfolio_adjustment[ticker_b] = 0
                self.empty_slots += 1  # As the position ought to be clear we can increase this.
                continue
            elif expected_potential < current_ignored_signals[0][0] or expected_potential > (expected_return * 1.5):
                # TODO Trading costs are not factored in.
                # TODO Threshold how much divergence is okay must be given. Tasks of the Risk Model at some point.
                portfolio_adjustment[ticker_a] = 0
                portfolio_adjustment[ticker_b] = 0
                # TODO Should the following really happen here or when new Signals are generated ?
                # The Signal should be replaced immediately as elif checks if the position is malicious.
                replacement_signal = current_ignored_signals[0]  # The List with the signals ignored is sorted.
                signals_to_follow.append(replacement_signal)
                current_ignored_signals.remove(replacement_signal)
                # The Signal must be removed from the followed signals list.
                self.followed_signals.pop(ticker_a)
                self.followed_signals.pop(ticker_b)
                # The replacement Signal must be removed from the ignored signals list.
                ignored_ticker_a, ignored_ticker_b = current_ignored_signals[0][2]
                self.ignored_signals.pop(frozenset([ignored_ticker_a, ignored_ticker_b]))
                continue

        # The Model has to calculate the positions size for each signal that should be followed.
        new_positions = self.analyze_signals((signals_to_follow, {}))  # self.pairs will be updated with {} (der Alpha Model Output soll modelliert werden)
        portfolio_adjustment.update(new_positions)  # This is not the only occasion portfolio_adjustment receives data.

        return portfolio_adjustment

