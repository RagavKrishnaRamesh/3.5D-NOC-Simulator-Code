/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * This file contains the declaration of the statistics
 */

#ifndef __NOXIMSTATS_H__
#define __NOXIMSTATS_H__

#include <iostream>
#include <iomanip>
#include <vector>
#include "DataStructs.h"
#include "Power.h"
using namespace std;

class NoC;
class Router;

struct CommHistory {
    int src_id;
     vector < double >delays;
    unsigned int total_sent_flits;
    unsigned int total_received_flits;
    double last_received_flit_time;
};

class Stats {
  public:

    Stats() {
    } 

    void configure(const NoC & noc, const int node_id,
                   const double _warm_up_time);

    // Access point for stats update
    void sentFlit(const double emission_time, const Flit & flit);
    void receivedFlit(const double arrival_time, const Flit & flit);

    // Returns the average delay (cycles) for the current node as
    // regards to the communication whose source is src_id
    double getAverageDelay(const int src_id);

    // Returns the average delay (cycles) for the current node
    double getAverageDelay();

    // Returns the max delay for the current node as regards the
    // communication whose source node is src_id
    double getMaxDelay(const int src_id);

    // Returns the max delay (cycles) for the current node
    double getMaxDelay();

    // Returns the average throughput (flits/cycle) for the current node
    // and for the communication whose source is src_id
    double getAverageThroughput(const int src_id);

    // Returns the average throughput (flits/cycle) for the current node
    double getAverageThroughput();

    // Returns the number of received packets from current node
    unsigned int getReceivedPackets();

    // Returns the number of received flits from current node
    unsigned int getReceivedFlits() const;

    // Returns the number of sent flits from current node
    unsigned int getSentFlits() const;

    // Returns the number of communications whose destination is the
    // current node
    unsigned int getTotalCommunications();

    // Returns the energy consumed for communication src_id-->dst_id
    // under the following assumptions: (i) Minimal routing is
    // considered, (ii) constant packet size is considered (as the
    // average between the minimum and the maximum packet size).
    double getCommunicationEnergy(int src_id, int dst_id);

    // Shows statistics for the current node
    void showStats(int curr_node, std::ostream & out =
		   std::cout, bool header = false);

#ifdef DEBUG_VC_UTILIZATION
    void updateVCCumulatedNumberOfFlits(const Router & router);
    void updateVCInjectedFlits(const Router & router,
                               const Flit & flit);
    void updateVCReceivedFlits(const Router & router,
                               const Flit & flit);

    // Performance Counters
    map<string, vector<size_t>> flit_injected_intra;
    map<string, vector<size_t>> flit_injected_inter;

    map<string, vector<size_t>> flit_received_intra;
    map<string, vector<size_t>> flit_received_inter;

    map<string, vector<size_t>> cumulated_nb_flits_intra;
    map<string, vector<size_t>> cumulated_nb_flits_inter;
#endif // DEBUG_VC_UTILIZATION

  private:
    int id;
    vector < CommHistory > chist;
    double warm_up_time;

    int searchCommHistory(int src_id);
    bool isIntraNoC(const Router& router, const Flit & flit) const;
};

#endif
