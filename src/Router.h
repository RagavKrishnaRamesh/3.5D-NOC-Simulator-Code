/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * This file contains the declaration of the router
 */

#ifndef __NOXIMROUTER_H__
#define __NOXIMROUTER_H__

#include <systemc.h>
#include "DataStructs.h"
#include "Buffer.h"
#include "Stats.h"
#include "GlobalRoutingTable.h"
#include "LocalRoutingTable.h"
#include "ReservationTable.h"
#include "Utils.h"
#include "routingAlgorithms/RoutingAlgorithm.h"
#include "routingAlgorithms/RoutingAlgorithms.h"
#include "selectionStrategies/SelectionStrategy.h"
#include "selectionStrategies/SelectionStrategy.h"
#include "selectionStrategies/Selection_NOP.h"
#include "selectionStrategies/Selection_BUFFER_LEVEL.h"

using namespace std;

extern unsigned int drained_volume;

class NoC;

SC_MODULE(Router)
{
    friend class MultiNoC;
    friend class Selection_NOP;
    friend class Selection_BUFFER_LEVEL;

    // I/O Ports
    sc_in_clk clock;		                  // The input clock for the router
    sc_in <bool> reset;                           // The reset signal for the router

    // number of ports: 6 mesh directions + local + wireless 
    sc_in <Flit> flit_rx[DIRECTIONS + 2];	  // The input channels 
    sc_in <bool> req_rx[DIRECTIONS + 2];	  // The requests associated with the input channels
    sc_out <bool> ack_rx[DIRECTIONS + 2];	  // The outgoing ack signals associated with the input channels
    sc_out <TBufferFullStatus> buffer_full_status_rx[DIRECTIONS+2];

    sc_out <Flit> flit_tx[DIRECTIONS + 2];   // The output channels
    sc_out <bool> req_tx[DIRECTIONS + 2];	  // The requests associated with the output channels
    sc_in <bool> ack_tx[DIRECTIONS + 2];	  // The outgoing ack signals associated with the output channels
    sc_in <TBufferFullStatus> buffer_full_status_tx[DIRECTIONS+2];

    sc_out <TFreeSlots> free_slots[DIRECTIONS + 1];
    sc_in  <TFreeSlots> free_slots_neighbor[DIRECTIONS + 1];

    // Neighbor-on-Path related I/O
    sc_out < NoP_data > NoP_data_out[DIRECTIONS];
    sc_in < NoP_data > NoP_data_in[DIRECTIONS];

    // Registers

    const int local_id;  // Unique ID for any topology except MULTI_MESH
    const int global_id; // Unique ID used when using TOPOLOGY_MULTI_MESH

    int routing_type;		                // Type of routing algorithm
    int selection_type;
    BufferBank buffer[DIRECTIONS + 2];		// buffer[direction][virtual_channel] 
    bool current_level_rx[DIRECTIONS + 2];	// Current level for Alternating Bit Protocol (ABP)
    bool current_level_tx[DIRECTIONS + 2];	// Current level for Alternating Bit Protocol (ABP)
    Stats stats;		                // Statistics
    Power power;
    LocalRoutingTable routing_table;		// Routing table
    ReservationTable reservation_table;		// Switch reservation table
    unsigned long routed_flits;
    RoutingAlgorithm * routingAlgorithm; 
    SelectionStrategy * selectionStrategy; 
    
    // Functions

    void process();
    void rxProcess();		// The receiving process
    void txProcess();		// The transmitting process
    void perCycleUpdate();
    void configure(const double _warm_up_time,
		   const unsigned int _max_buffer_size,
		   GlobalRoutingTable & grt);

    unsigned long getRoutedFlits();	// Returns the number of routed flits 

    // Constructor
    typedef Router SC_CURRENT_USER_MODULE;
    Router(sc_module_name nm, const NoC& noc, int local_id, int global_id)
      : sc_module(nm), local_id(local_id), global_id(global_id),
        parent_noc(noc), selected_downward_link(-1),
        selected_intra_link(-1),
        is_reached_by_upward_link(false),
        has_upward_link(false),
        is_reached_by_downward_link(false),
        nb_vcout_up(0), nb_vcout_down(0),
        noc_down(nullptr)
    {
        SC_METHOD(process);
        sensitive << reset;
        sensitive << clock.pos();

        SC_METHOD(perCycleUpdate);
        sensitive << reset;
        sensitive << clock.pos();

        routingAlgorithm = retrieveRoutingAlgorithm();

        selectionStrategy = SelectionStrategies::get(GlobalParams::selection_strategy);

        if (selectionStrategy == 0)
        {
            cerr << " FATAL: invalid selection strategy -sel " << GlobalParams::selection_strategy << ", check with noxim -help" << endl;
            exit(-1);
        }
    }

    static RoutingAlgorithm* retrieveRoutingAlgorithm()
    {
        RoutingAlgorithm* r = RoutingAlgorithms::get(GlobalParams::routing_algorithm);

        if (!r) {
            cerr << " FATAL: invalid routing -routing "
                 << GlobalParams::routing_algorithm
                 << ", check with noxim -help" << endl;
            exit(-1);
        }
        return r;
    }

    void checkRoutingRequirement() const {
        // Check that the current router satisfies the requirement of
        // the given routing algorithm
        if (!routingAlgorithm->checkTopology(*this))
        {
            cerr << " FATAL: incorrect topology for " << GlobalParams::routing_algorithm << endl;
            exit(-1);
        }
    }

    const NoC& getNoC() const {
        return parent_noc;
    }

    const map<IdRange, int>& upward_links() const {
        return selected_upward_links;
    }

    int downward_link() const {
        sc_assert(selected_downward_link > -1);
        return selected_downward_link;
    }

    int intra_link() const {
        return selected_intra_link;
    }

    inline int hasDownwardLink() const {
        return selected_downward_link == global_id;
    }

    inline int hasUpwardLink() const {
        return has_upward_link;
    }

    inline bool isOnBaseInterposer() const {
        return selected_downward_link == -1;
    }

    inline bool isOnLastLevelChiplet() const {
        return selected_downward_link != -1 &&
               selected_upward_links.empty();
    }

    inline bool isBoundary() const {
        if (hasDownwardLink() ||
            has_upward_link   ||
            isReachedByUpwardLink() || isReachedByDownwardLink())
            return true;
        return false;
    }

    inline bool isReachedByUpwardLink() const {
        return is_reached_by_upward_link;
    }

    inline bool isReachedByDownwardLink() const {
        return is_reached_by_downward_link;
    }

  private:

    // performs actual routing + selection
    RouteEntry route(const RouteData & route_data);

    // wrappers
    RouteEntry selectionFunction(const vector<RouteEntry> & directions,
                                 const RouteData & route_data);
    vector<RouteEntry> routingFunction(const RouteData & route_data);
 
    NoP_data getCurrentNoPData();
    void NoP_report() const;
    int NoPScore(const NoP_data & nop_data, const vector<RouteEntry> & nop_channels) const;
    int reflexDirection(int direction) const;
    int getNeighborId(int _id, int direction) const;
    RouteData getRouteData(const Flit& flit, int input_dir) const;
    int computeMinimumManhattanDistance(const vector<int>& vlinks) const;

    vector<int> getNextHops(int src, int dst);
    int start_from_port;	     // Port from which to start the reservation cycle
    int start_from_vc[DIRECTIONS+2]; // VC from which to start the reservation cycle for the specific port

    vector<int> nextDeltaHops(RouteData rd);

    // Parent NoC
    const NoC & parent_noc;
    // Returns the upward link selected for each hierarchical interval of global
    // ids
    map<IdRange, int> selected_upward_links;
    // Selected downward link from the routeur
    int selected_downward_link;
    // Selected intra-stack vertical link (same mesh), optional.
    int selected_intra_link;
    // Is the router reached by an upward link
    bool is_reached_by_upward_link;
    // Specify whether the router has an upward link
    // NOTE: faster to check this variable than traversing
    // selected_upward_links
    bool has_upward_link;
    // Specify whether the router has a downward link
    bool is_reached_by_downward_link;

    int nb_vcout_up;
    int nb_vcout_down;
    const NoC* noc_down;

  public:
    unsigned int local_drained;

    int getNumberVCOutUp()   const { return nb_vcout_up;   }
    int getNumberVCOutDown() const { return nb_vcout_down; }

    bool incomingDownUpTransition(int dest_gid) const;

    bool inCongestion();
    void ShowBuffersStats(std::ostream & out);

    // Configure all upward links selected for this router.
    // Each selected upward link targets a different chiplet.
    void configureUpwardLinks(IdRangeRegister& upward_link_iic,
                              map<IdRange, vector<int>>& ii_ids,
                              map<IdRange, vector<pair<int, int>>>&
                                             hidrange_link_selection);

    // Configure the selected downward link.
    void configureDownwardLink(const vector<int>& vlinks_pos,
                               const vector<pair<int, int>>& link_selected);
    void configureIntraLink(const vector<pair<int, int>>& link_selected);

    void switchFlitVirtualChannel(Buffer & buffer,
                                  Flit   & flit,
                                  int      vc_out);
    bool connectedHubs(int src_hub, int dst_hub);
};

#endif

