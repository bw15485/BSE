

import sys
import random
import csv
from datetime import datetime

from msgClasses import Assignment
from Traders import Trader_ZIP
from Exchange import Exchange


bse_sys_minprice = 1  # minimum price in the system, in cents/pennies
bse_sys_maxprice = 500  # maximum price in the system, in cents/pennies: Todo -- eliminate reliance on this
ticksize = 1  # minimum change in price, in cents/pennies


# create a bunch of traders from traders_spec
# returns tuple (n_buyers, n_sellers)
# optionally shuffles the pack of buyers and the pack of sellers
def populate_market(traders_spec, traders, shuffle, verbose):
        def trader_type(robottype, name):
                if robottype == 'ZIP':
                        return Trader_ZIP('ZIP', name, 0.00, 0)
                elif robottype == 'MAA':
                        return Trader_AA('MAA', name, 0.00, 0)
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

        if verbose:
                for t in range(n_buyers):
                        bname = 'B%02d' % t
                        print(traders[bname])
                for t in range(n_sellers):
                        bname = 'S%02d' % t
                        print(traders[bname])

        return {'n_buyers': n_buyers, 'n_sellers': n_sellers}


# customer_orders(): allocate orders to traders
# this version only issues LIM orders; LIM that crosses the spread executes as MKT
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


def customer_orders(time, last_update, traders, trader_stats, os, pending, base_oid, verbose, limitOrders):
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

        def getorderprice(i, sched_end, sched, n, mode, issuetime):
                # does the first schedule range include optional dynamic offset function(s)?
                if len(sched[0]) > 2:
                        offsetfn = sched[0][2][0]
                        offsetfn_params = [sched_end] + [p for p in sched[0][2][1]]
                        if callable(offsetfn):
                                # same offset for min and max
                                offset_min = offsetfn(issuetime, offsetfn_params)
                                offset_max = offset_min
                        else:
                                sys.exit(
                                        'FAIL: 3rd argument of sched in getorderprice() should be [callable_fn [params]]')
                        if len(sched[0]) > 3:
                                # if second offset function is specfied, that applies only to the max value
                                offsetfn = sched[0][3][0]
                                offsetfn_params = [sched_end] + [p for p in sched[0][3][1]]
                                if callable(offsetfn):
                                        # this function applies to max
                                        offset_max = offsetfn(issuetime, offsetfn_params)
                                else:
                                        sys.exit(
                                                'FAIL: 4th argument of sched in getorderprice() should be [callable_fn [params]]')
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
                # generates a set of issue times for the customer orders to arrive at
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

                        # at this point, arrtime is the *last* arrival time
                if fittointerval and mode == 'drip-poisson' and (arrtime != interval):
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
                # os is order schedules
                got_one = False
                for sched in os:
                        if (sched['from'] <= time) and (time < sched['to']):
                                # within the timezone for this schedule
                                schedrange = sched['ranges']
                                mode = sched['stepmode']
                                sched_end_time = sched['to']
                                got_one = True
                                exit  # jump out the loop -- so the first matching timezone has priority over any others
                if not got_one:
                        sys.exit('Fail: time=%5.2f not within any timezone in os=%s' % (time, os))
                return (schedrange, mode, sched_end_time)

        n_buyers = trader_stats['n_buyers']
        n_sellers = trader_stats['n_sellers']

        shuffle_times = True

        cancellations = []

        oid = base_oid

        max_qty = 1

        if len(pending) < 1:
                # list of pending (to-be-issued) customer orders is empty, so generate a new one
                new_pending = []

                # demand side (buyers)
                issuetimes = getissuetimes(n_buyers, os['timemode'], os['interval'], shuffle_times, True)
                ordertype = 'Bid'
                orderstyle = 'LIM'
                (sched, mode, sched_end) = getschedmode(time, os['dem'])
                for t in range(n_buyers):
                        issuetime = time + issuetimes[t]
                        tname = 'B%02d' % t
                        orderprice = getorderprice(t, sched_end, sched, n_buyers, mode, issuetime)
                        orderqty = random.randint(1, max_qty)
                        # order = Order(tname, ordertype, orderstyle, orderprice, orderqty, issuetime, None, oid)
                        order = Assignment("CUS", tname, ordertype, orderstyle, orderprice, orderqty, issuetime, None,
                                           oid)
                        limitOrders.write('%s, %s, %s, %s\n' % (order.trad_id, order.time, order.price, order.qty))
                        oid += 1
                        new_pending.append(order)

                # supply side (sellers)
                issuetimes = getissuetimes(n_sellers, os['timemode'], os['interval'], shuffle_times, True)
                ordertype = 'Ask'
                orderstyle = 'LIM'
                (sched, mode, sched_end) = getschedmode(time, os['sup'])
                for t in range(n_sellers):
                        issuetime = time + issuetimes[t]
                        tname = 'S%02d' % t
                        orderprice = getorderprice(t, sched_end, sched, n_sellers, mode, issuetime)
                        orderqty = random.randint(1, max_qty)
                        # order = Order(tname, ordertype, orderstyle, orderprice, orderqty, issuetime, None, oid)
                        order = Assignment("CUS", tname, ordertype, orderstyle, orderprice, orderqty, issuetime, None,
                                           oid)
                        limitOrders.write('%s, %s, %s, %s\n' % (order.trad_id, order.time, order.price, order.qty))
                        oid += 1
                        new_pending.append(order)
        else:
                # there are pending future orders: issue any whose timestamp is in the past
                new_pending = []
                for order in pending:
                        if order.time < time:
                                # this order should have been issued by now
                                # issue it to the trader
                                tname = order.trad_id
                                response = traders[tname].add_cust_order(order, verbose)
                                if verbose: print('Customer order: %s %s' % (response, order))
                                if response == 'LOB_Cancel':
                                        cancellations.append(tname)
                                        if verbose: print('Cancellations: %s' % (cancellations))
                                # and then don't add it to new_pending (i.e., delete it)
                        else:
                                # this order stays on the pending list
                                new_pending.append(order)
        return [new_pending, cancellations, oid]


# one session in the market
def market_session(sess_id, starttime, endtime, trader_spec, order_schedule, limitOrders,
                   blotterdumpfile):
        n_exchanges = 1

        tape_depth = 5  # number of most-recent items from tail of tape to be published at any one time

        verbosity = False

        verbose = verbosity  # main loop verbosity
        orders_verbose = verbosity
        lob_verbose = False
        process_verbose = False
        respond_verbose = False
        bookkeep_verbose = False

        fname = 'transactions' + sess_id + '.csv'
        transactions = open(fname, 'w')
        transactions.write('%s, %s, %s, %s, %s\n' % ('party1', 'party2', 'time', 'price', 'qty'))

        fname = 'orderPostings' + sess_id + '.csv'
        orderPostings = open(fname, 'w')
        orderPostings.write('%s, %s, %s, %s, %s\n' % ('tid', 'Otype', 'time', 'orderprice', 'qty'))

        # initialise the exchanges
        exchanges = []
        for e in range(n_exchanges):
                eid = "Exch%d" % e
                exch = Exchange(eid)
                exchanges.append(exch)
                if verbose: print('Exchange[%d] =%s' % (e, str(exchanges[e])))

        # create a bunch of traders
        traders = {}
        trader_stats = populate_market(trader_spec, traders, True, verbose)

        # timestep set so that can process all traders in one second
        # NB minimum inter-arrival time of customer orders may be much less than this!!
        timestep = 1.0 / float(trader_stats['n_buyers'] + trader_stats['n_sellers'])

        duration = float(endtime - starttime)

        last_update = -1.0

        time = starttime

        next_order_id = 0

        pending_cust_orders = []

        if verbose: print('\n%s;  ' % (sess_id))

        tid = None

        while time < endtime:

                # how much time left, as a percentage?
                time_left = (endtime - time) / duration
                if verbose: print('\n\n%s; t=%08.2f (percent remaining: %4.1f/100) ' % (sess_id, time, time_left * 100))

                trade = None

                # get any new assignments (customer orders) for traders to execute
                # and also any customer orders that require previous orders to be killed
                [pending_cust_orders, kills, noid] = customer_orders(time, last_update, traders, trader_stats,
                                                                     order_schedule, pending_cust_orders, next_order_id,
                                                                     orders_verbose, limitOrders)

                next_order_id = noid

                if verbose:
                        print('t:%f, noid=%d, pending_cust_orders:' % (time, noid))
                        for order in pending_cust_orders: print('%s; ' % str(order))

                # if any newly-issued customer orders mean quotes on the LOB need to be cancelled, kill them
                if len(kills) > 0:
                        if verbose: print('Kills: %s' % (kills))
                        for kill in kills:
                                # if verbose: print('lastquote=%s' % traders[kill].lastquote)
                                if traders[kill].lastquote != None:
                                        if verbose: print('Killing order %s' % (str(traders[kill].lastquote)))

                                        can_order = traders[kill].lastquote
                                        can_order.ostyle = "CAN"
                                        exch_response = exchanges[0].process_order(time, can_order, process_verbose, transactions)
                                        exch_msg = exch_response['trader_msgs']
                                        # do the necessary book-keeping
                                        # NB this assumes CAN results in a single message back from the exchange
                                        traders[kill].bookkeep(exch_msg[0], time, bookkeep_verbose)

                for t in traders:
                        if len(traders[t].orders) > 0:
                                # print("Tyme=%5.2d TID=%s Orders[0]=%s" % (time, traders[t].tid, traders[t].orders[0]))
                                dummy = 0  # NOP

                # get public lob data from each exchange
                lobs = []
                for e in range(n_exchanges):
                        exch = exchanges[e]
                        lob = exch.publish_lob(time, tape_depth, lob_verbose)
                        if verbose: print ('Exchange %d, Published LOB=%s' % (e, str(lob)))
                        lobs.append(lob)

                # quantity-spike injection
                # this next bit is a KLUDGE that is VERY FRAGILE and has lots of ARBITRARY CONSTANTS in it :-(
                # it is introduced for George Church's project
                # to edit this you have to know how many traders there are (specified in main loop)
                # and you have to know the details of the supply and demand curves too (again, spec in main loop)
                # before public release of this code, tidy it up and parameterise it nicely
                # triggertime = 60
                # replenish_period = 20
                # highest_buyer_index = 10  # this buyer has the highest limit price
                # highest_seller_index = 20
                # big_qty = 222
                # if time > (triggertime - 3 * timestep) and ((time + 3 * timestep) % replenish_period) <= (2 * timestep):
                #         # sys.exit('Bailing at injection trigger, time = %f' % time)
                #
                #         # here we inject big quantities nto both buyer and seller sides... hopefully the injected traders will do a deal
                #         pending_cust_orders[highest_buyer_index - 1].qty = big_qty
                #         pending_cust_orders[highest_seller_index - 1].qty = big_qty
                #
                #         if verbose: print ('t:%f SPIKE INJECTION (Post) Exchange %d, Published LOB=%s' % (
                #         time, e, str(lob)))
                #         if verbose:
                #                 print('t:%f, Spike Injection: , microp=%s, pending_cust_orders:' % (
                #                 time, lob['microprice']))
                #                 for order in pending_cust_orders: print('%s; ' % str(order))

                # get a quote (or None) from a randomly chosen trader

                # first randomly select a trader id
                old_tid = tid
                while tid == old_tid:
                        tid = list(traders.keys())[random.randint(0, len(traders) - 1)]

                # currently, all quotes/orders are issued only to the single exchange at exchanges[0]
                # it is that exchange's responsibility to then deal with Order Protection / trade-through (Reg NMS Rule611)
                # i.e. the exchange logic could/should be extended to check the best LOB price of each other exchange
                # that is yet to be implemented here
                order = traders[tid].getorder(time, time_left, lobs[0], verbose)

                if verbose: print('Trader Order: %s' % str(order))

                if order != None:
                        orderPostings.write(
                                '%s, %s, %s, %s, %s\n' % (order.tid, order.otype, order.time, order.price, order.qty))

                        order.myref = traders[tid].orders[
                                0].assignmentid  # attach customer order ID to this exchange order
                        if verbose: print('Order with myref=%s' % order.myref)

                        # Sanity check: catch bad traders here
                        traderprice = traders[tid].orders[0].price
                        if order.otype == 'Ask' and order.price < traderprice: sys.exit(
                                'Bad ask: Trader.price %s, Quote: %s' % (traderprice, order))
                        if order.otype == 'Bid' and order.price > traderprice: sys.exit(
                                'Bad bid: Trader.price %s, Quote: %s' % (traderprice, order))

                        # how many quotes does this trader already have sat on an exchange?

                        if len(traders[tid].quotes) >= traders[tid].max_quotes:
                                # need to clear a space on the trader's list of quotes, by deleting one
                                # new quote replaces trader's oldest previous quote
                                # bit of a  kludge -- just deletes oldest quote, which is at head of list
                                # THIS SHOULD BE IN TRADER NOT IN MAIN LOOP?? TODO
                                can_order = traders[tid].quotes[0]
                                if verbose: print('> can_order %s' % str(can_order))
                                can_order.ostyle = "CAN"
                                if verbose: print('> can_order %s' % str(can_order))

                                # send cancellation to exchange
                                exch_response = exchanges[0].process_order(time, can_order, process_verbose, transactions)
                                exch_msg = exch_response['trader_msgs']
                                tape_sum = exch_response['tape_summary']


                                if verbose:
                                        print('>Exchanges[0]ProcessOrder: tradernquotes=%d, quotes=[' % len(
                                                traders[tid].quotes))
                                        for q in traders[tid].quotes: print('%s' % str(q))
                                        print(']')
                                        for t in traders:
                                                if len(traders[t].orders) > 0:
                                                        # print(">Exchanges[0]ProcessOrder: Tyme=%5.2d TID=%s Orders[0]=%s" % (time, traders[t].tid, traders[t].orders[0]))
                                                        NOP = 0
                                                if len(traders[t].quotes) > 0:
                                                        # print(">Exchanges[0]ProcessOrder: Tyme=%5.2d TID=%s Quotes[0]=%s" % (time, traders[t].tid, traders[t].quotes[0]))
                                                        NOP = 0

                                # do the necessary book-keeping
                                # NB this assumes CAN results in a single message back from the exchange
                                traders[tid].bookkeep(exch_msg[0], time, bookkeep_verbose)

                        if verbose:
                                # print('post-check: tradernquotes=%d, quotes=[' % len(traders[tid].quotes))
                                for q in traders[tid].quotes: print('%s' % str(q))
                                print(']')
                                for t in traders:
                                        if len(traders[t].orders) > 0:
                                                # print("PostCheck Tyme=%5.2d TID=%s Orders[0]=%s" % (time, traders[t].tid, traders[t].orders[0]))
                                                if len(traders[t].quotes) > 0:
                                                        # print("PostCheck Tyme=%5.2d TID=%s Quotes[0]=%s" % (time, traders[t].tid, traders[t].quotes[0]))
                                                        NOP = 0

                                        if len(traders[t].orders) > 0 and traders[t].orders[0].astyle == "CAN":
                                                sys.stdout.flush()
                                                sys.exit("CAN error")

                        # add order to list of live orders issued by this trader
                        traders[tid].quotes.append(order)

                        if verbose: print('Trader %s quotes[-1]: %s' % (tid, traders[tid].quotes[-1]))

                        # send this order to exchange and receive response
                        exch_response = exchanges[0].process_order(time, order, process_verbose, transactions)
                        exch_msgs = exch_response['trader_msgs']
                        tape_sum = exch_response['tape_summary']

                        # because the order just processed might have changed things, now go through each
                        # order resting at the exchange and see if it can now be processed
                        # applies to AON, ICE, OSO, and OCO

                        if verbose:
                                print('Exch_Msgs: ')
                                if exch_msgs == None:
                                        print('None')
                                else:
                                        for msg in exch_msgs:
                                                print('Msg=%s' % msg)

                        if exch_msgs != None and len(exch_msgs) > 0:
                                # messages to process
                                for msg in exch_msgs:
                                        if verbose: print('Message: %s' % msg)
                                        traders[msg.tid].bookkeep(msg, time, bookkeep_verbose)

                        # traders respond to whatever happened
                        # needs to be updated for multiple exchanges
                        lob = exchanges[0].publish_lob(time, tape_depth, lob_verbose)

                        s = '%6.2f, ' % time
                        for t in traders:
                                # NB respond just updates trader's internal variables
                                # doesn't alter the LOB, so processing each trader in
                                # sequence (rather than random/shuffle) isn't a problem
                                traders[t].respond(time, lob, tape_sum, respond_verbose)



                time = time + timestep

        # end of an experiment -- dump the tape
        # exchanges[0].dump_tape(sess_id, tapedumpfile, 'keep')

        # traders dump their blotters
        for t in traders:
                tid = traders[t].tid
                ttype = traders[t].ttype
                balance = traders[t].balance
                blot = traders[t].blotter
                blot_len = len(blot)
                # build csv string for all events in blotter
                csv = ''
                estr = "TODO "
                for e in blot:
                        # print(blot)
                        # estr = '%s, %s, %s, %s, %s, %s, ' % (e['type'], e['time'], e['price'], e['qty'], e['party1'], e['party2'])
                        csv = csv + estr
                blotterdumpfile.write('%s, %s, %s, %s, %s, %s\n' % (sess_id, tid, ttype, balance, blot_len, csv))

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

                fname = sess_id + 'blotterDumpFile.csv'
                blotterdumpfile = open(fname, 'w')
                blotterdumpfile.write('%s, %s, %s, %s, %s\n' % ('sess_id', 'tid', 'ttype', 'balance', 'blot_len'))

                fname = sess_id + 'limitOrders.csv'
                limitOrders = open(fname, 'w')

                market_session(sess_id, start_time, end_time, traders_spec, order_sched,limitOrders, blotterdumpfile)

        print('\n Experiment Finished')


