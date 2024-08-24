"""
This module contains the relevant functions to size the current positions that should be taken,
according to the alpha_model properly.
"""
import os
import copy
from data_connector import Pair
from tws_connection import ib, build_connection
import pandas as pd


# Check if a connection exists already
if not ib.isConnected():
    build_connection()


class Portfolio:
    """
    This class is used to manage the current Portfolio.
    """

    def __init__(self, account_number,
                 slots, 
                 budget):

        self.profile = account_number
        # Check if a session is logged, if true, loads the session.
        path = "./log/followed_signals_log.csv"
        log_df = pd.read_csv(path)
        if not log_df.empty:
            self.followed_signals = log_df.to_dict() 
            for ticker, raw_log_string in self.followed_signals.items():
                deviation, sign, pair, const, slope, threshold = eval(raw_log_string)
                tickers, currency = pair
                current_pair = Pair(tickers, currency, (const, slope, threshold))
                current_pair.connect_data()
                recovered_signal = (deviation, sign, pair, {ticker_a: copy.copy(pair.quotes_a),
                                                            ticker_b: copy.copy(pair.quotes_b)
                                                            },
                                    const,
                                    slope,
                                    threshold)
                self.followed_signals[ticker] = recovered_signal

        else:
            self.followed_signals = {}

        self.ignored_signals = {}
        self.all_slots = slots
        self.empty_slots = self.all_slots - (len(self.followed_signals) / 2)  # Each signal involves two stocks.
        self.budget = budget
        self.position_pnl = {}
        self.pairs_traded = {}
        if ib.positions(account_number):
            self.portfolio = {}
            current_positions = ib.positions(account_number)
            for position in current_positions:
                ticker = position.account
                shares = position.position
                self.portfolio[ticker] = shares
                

    def create_new_log(self):
        """
        To log properly which signal was followed the class "pair" must be exported,
        otherwise the reference is saved and the information lost.
        """
        log = {}
        for ticker, signal in self.followed_signals.items():
            deviation, sign, pair, quotes, const, slope, threshold = signal

            # Conection to quotes has to be reestablished at a later point in time.
            signal_log_version = (deviation, sign, pair.export(), const, slope, threshold)

            log[ticker] = signal_log_version
            
        pd.DataFrame(log).to_csv(r"./log/followed_signals_log.csv")


    def analyze_signals(self, alpha_model_output):
        """
        Receives new Signals generated by alpha_model and determines how they will be handled.
        :param alpha_model_output: List of signals generated by the alpha model.
        :return: Execution update (Information for the Execution Model which transactions to do)
        """
        new_signals, pairs = alpha_model_output  # TODO find a better name this sounds stupid.
        portfolio_adjustment = {}

        # Retrieve and sort the signals generated by the alpha model.
        if isinstance(new_signals, dict):
            signals = list(new_signals.values())
        else:
            signals = new_signals

        if signals == []:
            return {}

        # store the pairs traded by the model to access market data.
        self.pairs_traded.update(pairs)
        
        signals.sort(key=lambda a: a[0], reverse=True)
        # Calculate the amounts of shares need for each trade as long as there are still slots open.
        # Slot is the wording for each budget that can be traded on a pair. The risk strategy is at this point
        # equal weighting.
        for signal in signals:
            # Calculation of the amount of shares for each stock.

            # First we unpack each signal.
            deviation, sign, pair, quotes, const, slope, threshold = signal
            if self.empty_slots > 0:  # TODO it should be factored in how (im)probable the deviation is! Through Percentile in the distribution.
                # TODO The Ignored signals should be compared too, while discriminating after timeliness.
                ticker_a, ticker_b = pair.tickers
                # Formel zur Berechnung des Anteils von b.
                shares_b = ((self.budget / self.all_slots - const * quotes[ticker_a].ask) *
                            (1 / (slope * quotes[ticker_a].ask + quotes[ticker_b].ask)))
                shares_a = const + slope * shares_b
                # Preparation of the output.
                portfolio_adjustment[ticker_a] = int(shares_a)
                portfolio_adjustment[ticker_b] = int(shares_b)
                self.followed_signals[pair.export()[0][0]] = signal
                self.followed_signals[pair.export()[0][1]] = signal
                self.empty_slots -= 1
            else:
                self.ignored_signals[frozenset(pair.export()[0][0])] = signal
                self.ignored_signals[frozenset(pair.export()[0][1])] = signal
                break

        self.create_new_log()

        return portfolio_adjustment


    def optimize(self):
        portfolio_adjustment = {}

        # Get the current positions from IBKR.
        current_positions = ib.positions(self.profile)

        # Exception if there is no portfolio to optimize.
        if current_positions == []:
            return {}  # This is crucial because the execution_model requires a dict as input.
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
            deviation, sign, pair, quotes, const, slope, threshold = signal  # TODO Eigentlich muss dass nicht entpackt werden.
            tickers, currency = pair
            ticker_a, ticker_b = tickers

            # Get the projected retorn of the signal.
            expected_return = deviation
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

