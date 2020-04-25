
import sys
import math
import random

from Traders import Trader_ZIP
from msgClasses import Order


bse_sys_minprice = 1  # minimum price in the system, in cents/pennies
bse_sys_maxprice = 1000  # maximum price in the system, in cents/pennies
ticksize = 1  # minimum change in price, in cents/pennies





# Orderbook_half is one side of the book: a list of bids or a list of asks, each sorted best-first

class Orderbook_half:

        def __init__(self, booktype, worstprice):
                # booktype: bids or asks?
                self.booktype = booktype
                # dictionary of orders received, indexed by Trader ID
                self.orders = {}
                # limit order book, dictionary indexed by price, with order info
                self.lob = {}
                # anonymized LOB, lists, with only price/qty info
                self.lob_anon = []
                # summary stats
                self.best_price = None
                self.best_tid = None
                self.worstprice = worstprice
                self.n_orders = 0  # how many orders?
                self.lob_depth = 0  # how many different prices on lob?


        def anonymize_lob(self):
                # anonymize a lob, strip out order details, format as a sorted list
                # NB for asks, the sorting should be reversed
                self.lob_anon = []
                for price in sorted(self.lob):
                        qty = self.lob[price][0]
                        self.lob_anon.append([price, qty])


        def build_lob(self):
                lob_verbose = False
                # take a list of orders and build a limit-order-book (lob) from it
                # NB the exchange needs to know arrival times and trader-id associated with each order
                # returns lob as a dictionary (i.e., unsorted)
                # also builds anonymized version (just price/quantity, sorted, as a list) for publishing to traders
                self.lob = {}
                for tid in self.orders:
                        order = self.orders.get(tid)
                        price = order.price
                        if price in self.lob:
                                # update existing entry
                                qty = self.lob[price][0]
                                orderlist = self.lob[price][1]
                                orderlist.append([order.time, order.qty, order.tid, order.qid])
                                self.lob[price] = [qty + order.qty, orderlist]
                        else:
                                # create a new dictionary entry
                                self.lob[price] = [order.qty, [[order.time, order.qty, order.tid, order.qid]]]
                # create anonymized version
                self.anonymize_lob()
                # record best price and associated trader-id
                if len(self.lob) > 0 :
                        if self.booktype == 'Bid':
                                self.best_price = self.lob_anon[-1][0]
                        else :
                                self.best_price = self.lob_anon[0][0]
                        self.best_tid = self.lob[self.best_price][1][0][2]
                else :
                        self.best_price = None
                        self.best_tid = None

                if lob_verbose : print self.lob


        def book_add(self, order):
                # add order to the dictionary holding the list of orders
                # either overwrites old order from this trader
                # or dynamically creates new entry in the dictionary
                # so, max of one order per trader per list
                # checks whether length or order list has changed, to distinguish addition/overwrite
                #print('book_add > %s %s' % (order, self.orders))
                n_orders = self.n_orders
                self.orders[order.tid] = order
                self.n_orders = len(self.orders)
                self.build_lob()
                #print('book_add < %s %s' % (order, self.orders))
                if n_orders != self.n_orders :
                    return('Addition')
                else:
                    return('Overwrite')



        def book_del(self, order):
                # delete order from the dictionary holding the orders
                # assumes max of one order per trader per list
                # checks that the Trader ID does actually exist in the dict before deletion
                # print('book_del %s',self.orders)
                if self.orders.get(order.tid) != None :
                        del(self.orders[order.tid])
                        self.n_orders = len(self.orders)
                        self.build_lob()
                # print('book_del %s', self.orders)


        def delete_best(self):
                # delete order: when the best bid/ask has been hit, delete it from the book
                # the TraderID of the deleted order is return-value, as counterparty to the trade
                best_price_orders = self.lob[self.best_price]
                best_price_qty = best_price_orders[0]
                best_price_counterparty = best_price_orders[1][0][2]
                if best_price_qty == 1:
                        # here the order deletes the best price
                        del(self.lob[self.best_price])
                        del(self.orders[best_price_counterparty])
                        self.n_orders = self.n_orders - 1
                        if self.n_orders > 0:
                                if self.booktype == 'Bid':
                                        self.best_price = max(self.lob.keys())
                                else:
                                        self.best_price = min(self.lob.keys())
                                self.lob_depth = len(self.lob.keys())
                        else:
                                self.best_price = self.worstprice
                                self.lob_depth = 0
                else:
                        # best_bid_qty>1 so the order decrements the quantity of the best bid
                        # update the lob with the decremented order data
                        self.lob[self.best_price] = [best_price_qty - 1, best_price_orders[1][1:]]

                        # update the bid list: counterparty's bid has been deleted
                        del(self.orders[best_price_counterparty])
                        self.n_orders = self.n_orders - 1
                self.build_lob()
                return best_price_counterparty



# Orderbook for a single instrument: list of bids and list of asks

class Orderbook(Orderbook_half):

        def __init__(self):
                self.bids = Orderbook_half('Bid', bse_sys_minprice)
                self.asks = Orderbook_half('Ask', bse_sys_maxprice)
                self.tape = []
                self.quote_id = 0  #unique ID code for each quote accepted onto the book



# Exchange's internal orderbook

class Exchange(Orderbook):

        def add_order(self, order, verbose):
                # add a quote/order to the exchange and update all internal records; return unique i.d.
                order.qid = self.quote_id
                self.quote_id = order.qid + 1
                # if verbose : print('QUID: order.quid=%d self.quote.id=%d' % (order.qid, self.quote_id))
                tid = order.tid
                if order.otype == 'Bid':
                        response=self.bids.book_add(order)
                        best_price = self.bids.lob_anon[-1][0]
                        self.bids.best_price = best_price
                        self.bids.best_tid = self.bids.lob[best_price][1][0][2]
                else:
                        response=self.asks.book_add(order)
                        best_price = self.asks.lob_anon[0][0]
                        self.asks.best_price = best_price
                        self.asks.best_tid = self.asks.lob[best_price][1][0][2]
                return [order.qid, response]


        def del_order(self, time, order, verbose):
                # delete a trader's quot/order from the exchange, update all internal records
                tid = order.tid
                if order.otype == 'Bid':
                        self.bids.book_del(order)
                        if self.bids.n_orders > 0 :
                                best_price = self.bids.lob_anon[-1][0]
                                self.bids.best_price = best_price
                                self.bids.best_tid = self.bids.lob[best_price][1][0][2]
                        else: # this side of book is empty
                                self.bids.best_price = None
                                self.bids.best_tid = None
                        cancel_record = { 'type': 'Cancel', 'time': time, 'order': order }
                        self.tape.append(cancel_record)

                elif order.otype == 'Ask':
                        self.asks.book_del(order)
                        if self.asks.n_orders > 0 :
                                best_price = self.asks.lob_anon[0][0]
                                self.asks.best_price = best_price
                                self.asks.best_tid = self.asks.lob[best_price][1][0][2]
                        else: # this side of book is empty
                                self.asks.best_price = None
                                self.asks.best_tid = None
                        cancel_record = { 'type': 'Cancel', 'time': time, 'order': order }
                        self.tape.append(cancel_record)
                else:
                        # neither bid nor ask?
                        sys.exit('bad order type in del_quote()')



        def process_order2(self, time, order, verbose):
                # receive an order and either add it to the relevant LOB (ie treat as limit order)
                # or if it crosses the best counterparty offer, execute it (treat as a market order)
                oprice = order.price
                counterparty = None
                [qid, response] = self.add_order(order, verbose)  # add it to the order lists -- overwriting any previous order
                order.qid = qid
                if verbose :
                        print('QUID: order.quid=%d' % order.qid)
                        print('RESPONSE: %s' % response)
                best_ask = self.asks.best_price
                best_ask_tid = self.asks.best_tid
                best_bid = self.bids.best_price
                best_bid_tid = self.bids.best_tid
                if order.otype == 'Bid':
                        if self.asks.n_orders > 0 and best_bid >= best_ask:
                                # bid lifts the best ask
                                if verbose: print("Bid $%s lifts best ask" % oprice)
                                counterparty = best_ask_tid
                                price = best_ask  # bid crossed ask, so use ask price
                                if verbose: print('counterparty, price', counterparty, price)
                                # delete the ask just crossed
                                self.asks.delete_best()
                                # delete the bid that was the latest order
                                self.bids.delete_best()
                elif order.otype == 'Ask':
                        if self.bids.n_orders > 0 and best_ask <= best_bid:
                                # ask hits the best bid
                                if verbose: print("Ask $%s hits best bid" % oprice)
                                # remove the best bid
                                counterparty = best_bid_tid
                                price = best_bid  # ask crossed bid, so use bid price
                                if verbose: print('counterparty, price', counterparty, price)
                                # delete the bid just crossed, from the exchange's records
                                self.bids.delete_best()
                                # delete the ask that was the latest order, from the exchange's records
                                self.asks.delete_best()
                else:
                        # we should never get here
                        sys.exit('process_order() given neither Bid nor Ask')
                # NB at this point we have deleted the order from the exchange's records
                # but the two traders concerned still have to be notified
                if verbose: print('counterparty %s' % counterparty)
                if counterparty != None:
                        # process the trade
                        if verbose: print('>>>>>>>>>>>>>>>>>TRADE t=%5.2f $%d %s %s' % (time, price, counterparty, order.tid))
                        transaction_record = { 'type': 'Trade',
                                               'time': time,
                                               'price': price,
                                               'party1':counterparty,
                                               'party2':order.tid,
                                               'qty': order.qty
                                              }
                        self.tape.append(transaction_record)
                        return transaction_record
                else:
                        return None



        def tape_dump(self, fname, fmode, tmode):
                dumpfile = open(fname, fmode)
                dumpfile.write('%s, %s, %s, %s, %s\n' % ('party1', 'party2', 'time', 'price', 'qty'))
                for tapeitem in self.tape:
                        if tapeitem['type'] == 'Trade' :
                                dumpfile.write('%s, %s, %s, %s, %s\n' % (tapeitem['party1'], tapeitem['party2'], tapeitem['time'], tapeitem['price'], tapeitem['qty']))
                dumpfile.close()
                if tmode == 'wipe':
                        self.tape = []


        # this returns the LOB data "published" by the exchange,
        # i.e., what is accessible to the traders
        def publish_lob(self, time, verbose):
                public_data = {}
                public_data['time'] = time
                public_data['bids'] = {'best':self.bids.best_price,
                                     'worst':self.bids.worstprice,
                                     'n': self.bids.n_orders,
                                     'lob':self.bids.lob_anon}
                public_data['asks'] = {'best':self.asks.best_price,
                                     'worst':self.asks.worstprice,
                                     'n': self.asks.n_orders,
                                     'lob':self.asks.lob_anon}
                public_data['QID'] = self.quote_id
                public_data['tape'] = self.tape
                if verbose:
                        print('publish_lob: t=%d' % time)
                        print('BID_lob=%s' % public_data['bids']['lob'])
                        # print('best=%s; worst=%s; n=%s ' % (self.bids.best_price, self.bids.worstprice, self.bids.n_orders))
                        print('ASK_lob=%s' % public_data['asks']['lob'])
                        # print('qid=%d' % self.quote_id)

                return public_data


##########################---Below lies the experiment/test-rig---##################



# trade_stats()
# dump CSV statistics on exchange data and trader population to file for later analysis
# this makes no assumptions about the number of types of traders, or
# the number of traders of any one type -- allows either/both to change
# between successive calls, but that does make it inefficient as it has to
# re-analyse the entire set of traders on each call
def trade_stats(expid, traders, dumpfile, time, lob):

        for t in traders:

                balance = traders[t].balance
                blot = traders[t].blotter
                blot_len = len(blot)
                ttype = traders[t].ttype
                tid = traders[t].tid

                blotterdumpfile.write(
                        '%s, %s, %s, %s, %s\n' % (sess_id, tid, ttype, balance, blot_len))
        trader_types = {}


        # n_traders = len(traders)
        # for t in traders:
        #         ttype = traders[t].ttype
        #         if ttype in trader_types.keys():
        #                 t_balance = trader_types[ttype]['balance_sum'] + traders[t].balance
        #                 n = trader_types[ttype]['n'] + 1
        #         else:
        #                 t_balance = traders[t].balance
        #                 n = 1
        #         trader_types[ttype] = {'n':n, 'balance_sum':t_balance}
        #
        #
        # dumpfile.write('%s, %06d, ' % (expid, time))
        # for ttype in sorted(list(trader_types.keys())):
        #         n = trader_types[ttype]['n']
        #         s = trader_types[ttype]['balance_sum']
        #         dumpfile.write('%s, %d, %d, %f, ' % (ttype, s, n, s / float(n)))
        #
        # if lob['bids']['best'] != None :
        #         dumpfile.write('%d, ' % (lob['bids']['best']))
        # else:
        #         dumpfile.write('N, ')
        # if lob['asks']['best'] != None :
        #         dumpfile.write('%d, ' % (lob['asks']['best']))
        # else:
        #         dumpfile.write('N, ')
        # dumpfile.write('\n');





# create a bunch of traders from traders_spec
# returns tuple (n_buyers, n_sellers)
# optionally shuffles the pack of buyers and the pack of sellers
def populate_market(traders_spec, traders, shuffle, verbose):

        def trader_type(robottype, name):
                if robottype == 'ZIP':
                        return Trader_ZIP('ZIP', name, 0.00, 0)
                else:
                        sys.exit('FATAL: don\'t know robot type %s\n' % robottype)


        def shuffle_traders(ttype_char, n, traders):
                for swap in range(n):
                        t1 = (n - 1) - swap
                        t2 = random.randint(0, t1)
                        t1name = '%c%02d' % (ttype_char, t1)
                        t2name = '%c%02d' % (ttype_char, t2)
                        traders[t1name].tid = t2name
                        traders[t2name].tid = t1name
                        temp = traders[t1name]
                        traders[t1name] = traders[t2name]
                        traders[t2name] = temp


        n_buyers = 0
        for bs in traders_spec['buyers']:
                ttype = bs[0]
                for b in range(bs[1]):
                        tname = 'B%02d' % n_buyers  # buyer i.d. string
                        traders[tname] = trader_type(ttype, tname)
                        n_buyers = n_buyers + 1

        if n_buyers < 1:
                sys.exit('FATAL: no buyers specified\n')

        if shuffle: shuffle_traders('B', n_buyers, traders)


        n_sellers = 0
        for ss in traders_spec['sellers']:
                ttype = ss[0]
                for s in range(ss[1]):
                        tname = 'S%02d' % n_sellers  # buyer i.d. string
                        traders[tname] = trader_type(ttype, tname)
                        n_sellers = n_sellers + 1

        if n_sellers < 1:
                sys.exit('FATAL: no sellers specified\n')

        if shuffle: shuffle_traders('S', n_sellers, traders)

        if verbose :
                for t in range(n_buyers):
                        bname = 'B%02d' % t
                        print(traders[bname])
                for t in range(n_sellers):
                        bname = 'S%02d' % t
                        print(traders[bname])


        return {'n_buyers':n_buyers, 'n_sellers':n_sellers}



# customer_orders(): allocate orders to traders
# parameter "os" is order schedule
# os['timemode'] is either 'periodic', 'drip-fixed', 'drip-jitter', or 'drip-poisson'
# os['interval'] is number of seconds for a full cycle of replenishment
# drip-poisson sequences will be normalised to ensure time of last replenishment <= interval
# parameter "pending" is the list of future orders (if this is empty, generates a new one from os)
# revised "pending" is the returned value
#
# also returns a list of "cancellations": trader-ids for those traders who are now working a new order and hence
# need to kill quotes already on LOB from working previous order
#
#
# if a supply or demand schedule mode is "random" and more than one range is supplied in ranges[],
# then each time a price is generated one of the ranges is chosen equiprobably and
# the price is then generated uniform-randomly from that range
#
# if len(range)==2, interpreted as min and max values on the schedule, specifying linear supply/demand curve
# if len(range)==3, first two vals are min & max, third value should be a function that generates a dynamic price offset
#                   -- the offset value applies equally to the min & max, so gradient of linear sup/dem curve doesn't vary
# if len(range)==4, the third value is function that gives dynamic offset for schedule min,
#                   and fourth is a function giving dynamic offset for schedule max, so gradient of sup/dem linear curve can vary
#
# the interface on this is a bit of a mess... could do with refactoring


def customer_orders(time, last_update, traders, trader_stats, os, pending, verbose, limit_orders):


        def sysmin_check(price):
                if price < bse_sys_minprice:
                        print('WARNING: price < bse_sys_min -- clipped')
                        price = bse_sys_minprice
                return price


        def sysmax_check(price):
                if price > bse_sys_maxprice:
                        print('WARNING: price > bse_sys_max -- clipped')
                        price = bse_sys_maxprice
                return price

        

        def getorderprice(i, sched, n, mode, issuetime):
                # does the first schedule range include optional dynamic offset function(s)?
                if len(sched[0]) > 2:
                        offsetfn = sched[0][2]
                        if callable(offsetfn):
                                # same offset for min and max
                                offset_min = offsetfn(issuetime)
                                offset_max = offset_min
                        else:
                                sys.exit('FAIL: 3rd argument of sched in getorderprice() not callable')
                        if len(sched[0]) > 3:
                                # if second offset function is specfied, that applies only to the max value
                                offsetfn = sched[0][3]
                                if callable(offsetfn):
                                        # this function applies to max
                                        offset_max = offsetfn(issuetime)
                                else:
                                        sys.exit('FAIL: 4th argument of sched in getorderprice() not callable')
                else:
                        offset_min = 0.0
                        offset_max = 0.0

                pmin = sysmin_check(offset_min + min(sched[0][0], sched[0][1]))
                pmax = sysmax_check(offset_max + max(sched[0][0], sched[0][1]))
                prange = pmax - pmin
                stepsize = prange / (n - 1)
                halfstep = round(stepsize / 2.0)

                if mode == 'fixed':
                        orderprice = pmin + int(i * stepsize) 
                elif mode == 'jittered':
                        orderprice = pmin + int(i * stepsize) + random.randint(-halfstep, halfstep)
                elif mode == 'random':
                        if len(sched) > 1:
                                # more than one schedule: choose one equiprobably
                                s = random.randint(0, len(sched) - 1)
                                pmin = sysmin_check(min(sched[s][0], sched[s][1]))
                                pmax = sysmax_check(max(sched[s][0], sched[s][1]))
                        orderprice = random.randint(pmin, pmax)
                else:
                        sys.exit('FAIL: Unknown mode in schedule')
                orderprice = sysmin_check(sysmax_check(orderprice))
                return orderprice



        def getissuetimes(n_traders, mode, interval, shuffle, fittointerval):
                interval = float(interval)
                if n_traders < 1:
                        sys.exit('FAIL: n_traders < 1 in getissuetime()')
                elif n_traders == 1:
                        tstep = interval
                else:
                        tstep = interval / (n_traders - 1)
                arrtime = 0
                issuetimes = []
                for t in range(n_traders):
                        if mode == 'periodic':
                                arrtime = interval
                        elif mode == 'drip-fixed':
                                arrtime = t * tstep
                        elif mode == 'drip-jitter':
                                arrtime = t * tstep + tstep * random.random()
                        elif mode == 'drip-poisson':
                                # poisson requires a bit of extra work
                                interarrivaltime = random.expovariate(n_traders / interval)
                                arrtime += interarrivaltime
                        else:
                                sys.exit('FAIL: unknown time-mode in getissuetimes()')
                        issuetimes.append(arrtime) 
                        
                # at this point, arrtime is the last arrival time
                if fittointerval and ((arrtime > interval) or (arrtime < interval)):
                        # generated sum of interarrival times longer than the interval
                        # squish them back so that last arrival falls at t=interval
                        for t in range(n_traders):
                                issuetimes[t] = interval * (issuetimes[t] / arrtime)
                # optionally randomly shuffle the times
                if shuffle:
                        for t in range(n_traders):
                                i = (n_traders - 1) - t
                                j = random.randint(0, i)
                                tmp = issuetimes[i]
                                issuetimes[i] = issuetimes[j]
                                issuetimes[j] = tmp
                return issuetimes
        

        def getschedmode(time, os):
                got_one = False
                for sched in os:
                        if (sched['from'] <= time) and (time < sched['to']) :
                                # within the timezone for this schedule
                                schedrange = sched['ranges']
                                mode = sched['stepmode']
                                got_one = True
                                exit  # jump out the loop -- so the first matching timezone has priority over any others
                if not got_one:
                        sys.exit('Fail: time=%5.2f not within any timezone in os=%s' % (time, os))
                return (schedrange, mode)
        

        n_buyers = trader_stats['n_buyers']
        n_sellers = trader_stats['n_sellers']

        shuffle_times = True

        cancellations = []

        max_qty = 1

        if len(pending) < 1:
                # list of pending (to-be-issued) customer orders is empty, so generate a new one
                new_pending = []

                # demand side (buyers)
                issuetimes = getissuetimes(n_buyers, os['timemode'], os['interval'], shuffle_times, True)
                
                ordertype = 'Bid'
                (sched, mode) = getschedmode(time, os['dem'])             
                for t in range(n_buyers):
                        issuetime = time + issuetimes[t]
                        tname = 'B%02d' % t
                        orderprice = getorderprice(t, sched, n_buyers, mode, issuetime)
                        orderQty = random.randint(1, max_qty)
                        order = Order(tname, ordertype, orderprice, 1, issuetime, -3.14)
                        new_pending.append(order)
                        limit_orders.write('%s, %s, %s, %s\n' % (tname, issuetime, orderprice, orderQty))

                        
                # supply side (sellers)
                issuetimes = getissuetimes(n_sellers, os['timemode'], os['interval'], shuffle_times, True)
                ordertype = 'Ask'
                (sched, mode) = getschedmode(time, os['sup'])
                for t in range(n_sellers):
                        issuetime = time + issuetimes[t]
                        tname = 'S%02d' % t
                        orderprice = getorderprice(t, sched, n_sellers, mode, issuetime)
                        orderQty = random.randint(1, max_qty)
                        order = Order(tname, ordertype, orderprice, 1, issuetime, -3.14)
                        new_pending.append(order)
                        limit_orders.write('%s, %s, %s, %s\n' % (tname, issuetime, orderprice, orderQty))
        else:
                # there are pending future orders: issue any whose timestamp is in the past
                new_pending = []
                for order in pending:
                        if order.time < time:
                                # this order should have been issued by now
                                # issue it to the trader
                                tname = order.tid
                                response = traders[tname].add_order(order, verbose)
                                if verbose: print('Customer order: %s %s' % (response, order) )
                                if response == 'LOB_Cancel' :
                                    cancellations.append(tname)
                                    if verbose: print('Cancellations: %s' % (cancellations))
                                # and then don't add it to new_pending (i.e., delete it)
                        else:
                                # this order stays on the pending list
                                new_pending.append(order)
        return [new_pending, cancellations]



# one session in the market
def market_session(sess_id, starttime, endtime, trader_spec, order_schedule, dump_each_trade, verbose, limitOrders, blotterdumpfile):


        limitOrders.write('%s, %s, %s, %s\n' % ('tname', 'issuetime', 'orderprice', 'orderqty'))

        fname = sess_id + 'orderPostings.csv'
        orderPostings = open(fname, 'w')
        orderPostings.write('%s, %s, %s, %s, %s\n' % ('tid', 'Otype', 'time', 'orderprice', 'orderqty'))

        # initialise the exchange
        exchange = Exchange()


        # create a bunch of traders
        traders = {}
        trader_stats = populate_market(trader_spec, traders, True, verbose)


        # timestep set so that can process all traders in one second
        # NB minimum interarrival time of customer orders may be much less than this!! 
        timestep = 1.0 / float(trader_stats['n_buyers'] + trader_stats['n_sellers'])
        
        duration = float(endtime - starttime)

        last_update = -1.0

        time = starttime

        orders_verbose = False
        lob_verbose = False
        process_verbose = False
        respond_verbose = False
        bookkeep_verbose = False

        pending_cust_orders = []

        if verbose: print('\n%s;  ' % (sess_id))

        while time < endtime:

                # how much time left, as a percentage?
                time_left = (endtime - time) / duration

                # if verbose: print('\n\n%s; t=%08.2f (%4.1f/100) ' % (sess_id, time, time_left*100))

                trade = None

                [pending_cust_orders, kills] = customer_orders(time, last_update, traders, trader_stats,
                                                 order_schedule, pending_cust_orders, orders_verbose, limitOrders)

                # if any newly-issued customer orders mean quotes on the LOB need to be cancelled, kill them
                if len(kills) > 0 :
                        # if verbose : print('Kills: %s' % (kills))
                        for kill in kills :
                                # if verbose : print('lastquote=%s' % traders[kill].lastquote)
                                if traders[kill].lastquote != None :
                                        # if verbose : print('Killing order %s' % (str(traders[kill].lastquote)))
                                        exchange.del_order(time, traders[kill].lastquote, verbose)


                # get a limit-order quote (or None) from a randomly chosen trader
                tid = list(traders.keys())[random.randint(0, len(traders) - 1)]
                print('traders' + str(traders))
                order = traders[tid].getorder(time, time_left, exchange.publish_lob(time, lob_verbose), True)



                # if verbose: print('Trader Quote: %s' % (order))

                if order != None:
                        orderPostings.write(
                                '%s, %s, %s, %s, %s\n' % (order.tid, order.otype, order.time, order.price, order.qty))
                        if order.otype == 'Ask' and order.price < traders[tid].orders[0].price: sys.exit('Bad ask')
                        if order.otype == 'Bid' and order.price > traders[tid].orders[0].price: sys.exit('Bad bid')
                        # send order to exchange
                        traders[tid].n_quotes = 1
                        trade = exchange.process_order2(time, order, process_verbose)
                        if trade != None:
                                # trade occurred,
                                # so the counterparties update order lists and blotters
                                traders[trade['party1']].bookkeep(trade, order, bookkeep_verbose, time)
                                traders[trade['party2']].bookkeep(trade, order, bookkeep_verbose, time)
                                # if dump_each_trade: trade_stats(sess_id, traders, dumpfile, time, exchange.publish_lob(time, lob_verbose))

                        # traders respond to whatever happened
                        lob = exchange.publish_lob(time, lob_verbose)
                        for t in traders:
                                # NB respond just updates trader's internal variables
                                # doesn't alter the LOB, so processing each trader in
                                # sequence (rather than random/shuffle) isn't a problem
                                traders[t].respond(time, lob, trade, respond_verbose)


                time = time + timestep
        # for t in traders:
        #
        #         balance = traders[t].balance
        #         blot = traders[t].blotter
        #         blot_len = len(blot)
        #         ttype = traders[t].ttype
        #         tid = traders[t].tid
        #
        #         blotterdumpfile.write(
        #                 '%s, %s, %s, %s, %s\n' % (sess_id, tid, ttype, balance, blot_len))


        # end of an experiment -- dump the tape
        exchange.tape_dump('transactions.csv', 'w', 'keep')


        # write trade_stats for this experiment NB end-of-session summary only
        trade_stats(sess_id, traders, blotterdumpfile, time, exchange.publish_lob(time, lob_verbose))



#############################

# # Below here is where we set up and run a series of experiments


if __name__ == "__main__":

        start_time = 0.0
        end_time = 180.0  # 80

        # end_time=25200  hours x 60 min x 60 sec /
        duration = end_time - start_time

        # range1 = (95, 95, [bronco_schedule_offsetfn, [] ] )
        # range1 = (50, 150)

        # range1 = (85,95)
        # range2 = (85,95)
        # range3 = (80,90)
        # range4 = (75,85)
        # range5 = (70,80)
        # range6 = (65,75)
        # range7 = (60,70)

        # demand flat and supply sloped

        # 4th supply and demand schedule
        # range1 = (75,75)
        # range2 = (100,100)

        # 5th supply and demand sched
        # range1 = (60, 60)
        # range2 = (100,100)

        # flat demand
        # range1 = (90, 100)
        # range2 = (100,100)

        # flat supply
        range1 = (75, 125)
        range2 = (75, 125)

        # symmetric supply and demand
        # range1 = (90,110)
        # range2 = (90,110)

        # supply flat and demand sloped

        # range1 = (110,110)
        # range2 = (75,125)
        #
        #
        # #supply dies demand shoots
        # range1 = (120,120)
        # range2 = (10,10)
        #
        # range3 = (80,80)
        # range4 = (1000,1000)

        # range3 = (65, 115)
        # range4 = (55, 105)
        # range5 = (45, 95)
        # range6 = (35, 85)
        # range7 = (25,75)
        # range8 = (15, 65)

        # , range2, range3, range4, range5, range6, range7
        # range1 = [75,125]

        supply_schedule = [{'from': start_time, 'to': end_time, 'ranges': [range1], 'stepmode': 'fixed'}]

        # range1 = (105, 105, [bronco_schedule_offsetfn, [] ] )
        # range1 = (50, 150)
        # range1 = (75, 125)
        demand_schedule = [{'from': start_time, 'to': end_time, 'ranges': [range2], 'stepmode': 'fixed'}]

        order_sched = {'sup': supply_schedule, 'dem': demand_schedule,
                       'interval': 30,
                       # 'timemode': 'drip-poisson'}
                       'timemode': 'periodic'}

        # buyers_spec = [('QSHV', 10), ('SHVR',2)]

        buyers_spec = [('ZIP', 5)]
        sellers_spec = buyers_spec
        traders_spec = {'sellers': sellers_spec, 'buyers': buyers_spec}

        sys.stdout.flush()

        sess_id = 00


        for session in range(1):
                sess_id = 'Test%02d' % session
                print('Session %s; ' % sess_id)

                fname = sess_id + 'blotterDumpFile.csv'
                blotterdumpfile = open(fname, 'w')
                blotterdumpfile.write('%s, %s, %s, %s, %s\n' % ('sess_id', 'tid', 'ttype', 'balance', 'blot_len'))

                fname = sess_id + 'limitOrders.csv'
                limitOrders = open(fname, 'w')

                # fname = sess_id + 'balances.csv'
                # summary_data_file = open(fname, 'w')
                # summary_data_file.write('%s, %s, %s, %s, %s, %s, %s, %s\n' % ('testname', 'time', 'trader type', 'sum balance', 'number of traders', 'profit per trader', 'best bid', 'best ask'))


                market_session(sess_id, start_time, end_time, traders_spec, order_sched, True, True, limitOrders, blotterdumpfile)


        print('\n Experiment Finished')


