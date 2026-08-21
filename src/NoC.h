/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * This file represents the top-level testbench
 */

#ifndef __NOXIMNOC_H__
#define __NOXIMNOC_H__

#include <stack>
#include <systemc.h>
#include <memory>
#include <random>
#include "Tile.h"
#include "GlobalRoutingTable.h"
#include "GlobalTrafficTable.h"
#include "Hub.h"
#include "Channel.h"
#include "TokenRing.h"

using namespace std;

template <typename T>
struct sc_signal_NSWE
{
    sc_signal<T> east;
    sc_signal<T> west;
    sc_signal<T> south;
    sc_signal<T> north;
    sc_signal<T> up;
    sc_signal<T> down;
};

template <typename T>
struct sc_signal_NSWEH
{
    sc_signal<T> east;
    sc_signal<T> west;
    sc_signal<T> south;
    sc_signal<T> north;
    sc_signal<T> to_hub;
    sc_signal<T> from_hub;
    sc_signal<T> up;
    sc_signal<T> down;
};


SC_MODULE(NoC)
{
    template <typename T>
    using array_ptr_t = std::unique_ptr<T[]>;

    public: bool SwitchOnly; //true if the tile are switch only 
    // I/O Ports
    sc_in_clk clock;		// The input clock for the NoC
    sc_in < bool > reset;	// The reset signal for the NoC

    // Signals mesh and switch bloc in delta topologies
    array_ptr_t<sc_signal_NSWEH<bool>> req;
    array_ptr_t<sc_signal_NSWEH<bool>> ack;
    array_ptr_t<sc_signal_NSWEH<TBufferFullStatus>> buffer_full_status;
    array_ptr_t<sc_signal_NSWEH<Flit>> flit;
    array_ptr_t<sc_signal_NSWE<TFreeSlots>> free_slots;

    // NoP
    array_ptr_t<sc_signal_NSWE<NoP_data>> nop_data;

    //signals for connecting Core2Hub (just to test wireless in Butterfly)
    sc_signal<Flit> *flit_from_hub;
    sc_signal<Flit> *flit_to_hub;

    sc_signal<bool> *req_from_hub;
    sc_signal<bool> *req_to_hub;

    sc_signal<bool> *ack_from_hub;
    sc_signal<bool> *ack_to_hub;

    sc_signal<TBufferFullStatus> *buffer_full_status_from_hub;
    sc_signal<TBufferFullStatus> *buffer_full_status_to_hub;

    // Dummy signals
    sc_signal<bool> dummy_req;
    sc_signal<Flit> dummy_flit;
    sc_signal<bool> dummy_ack;
    sc_signal<TBufferFullStatus> dummy_buffer_status;
    sc_signal<NoP_data> dummy_nop_data;
    sc_signal<TFreeSlots> dummy_free_slots;

    // Matrix of tiles
    vector<unique_ptr<Tile>> t;
    Tile ** core;

    map<int, Hub*> hub;
    map<int, Channel*> channel;

    TokenRing* token_ring;

    // Global tables
    GlobalRoutingTable grtable;
    GlobalTrafficTable gttable;

    string topology;
    const int n_virtual_channels;
    size_t nb_signals;

    // Constructor
    typedef NoC SC_CURRENT_USER_MODULE;
    NoC(sc_module_name name, size_t nb_signals, size_t nb_tiles,
        int n_virtual_channels)
        : sc_module(name),
          req(make_unique<sc_signal_NSWEH<bool>[]>(nb_signals)),
          ack(make_unique<sc_signal_NSWEH<bool>[]>(nb_signals)),
          buffer_full_status(
              make_unique<sc_signal_NSWEH<TBufferFullStatus>[]>(nb_signals)),
          flit(make_unique<sc_signal_NSWEH<Flit>[]>(nb_signals)),
          free_slots(make_unique<sc_signal_NSWE<TFreeSlots>[]>(nb_signals)),
          nop_data(make_unique<sc_signal_NSWE<NoP_data>[]>(nb_signals)),
          t(nb_tiles), n_virtual_channels(n_virtual_channels),
	  nb_signals(nb_signals)
    {
        buildCommon();
	GlobalParams::channel_selection = CHSEL_RANDOM;
	// out of yaml configuration (experimental features)
	//GlobalParams::channel_selection = CHSEL_FIRST_FREE;

	if (GlobalParams::ascii_monitor)
	{
	    SC_METHOD(asciiMonitor);
	    sensitive << clock.pos();
	}
    }

    // Support methods
    virtual Tile *searchNode(const int id) const = 0;
    virtual Tile *searchGlobalNode(const int gid) const = 0;

    virtual int getLocalId (int x, int y, int z) const = 0;
    virtual int getGlobalId(int x, int y, int z) const = 0;
    //virtual int coord2Id(Coord const& coord) const = 0;
    virtual Coord getCoordFromLocalId (int id) const = 0;
    virtual Coord getCoordFromGlobalId(int id) const = 0;

    virtual const IdRange& getGlobalIdRange() const = 0;
    virtual const IdRangeRegister& getHierarchicalSubMeshesIdRange() const = 0;

    virtual void checkRoutingRequirement() const = 0;
    virtual unsigned getId() const = 0;

    // Tile iterator
    virtual decltype(t)::iterator begin() = 0;
    virtual decltype(t)::iterator end()   = 0;
    virtual decltype(t)::const_iterator begin() const = 0;
    virtual decltype(t)::const_iterator end()   const = 0;

    void initializeRoutingAlgorithm() const {
        RoutingAlgorithm& r = *Router::retrieveRoutingAlgorithm();
        RoutingAlgorithm::initialize(r, *this);
    }

    virtual size_t getNumberOfTiles() const { return t.size(); }

  protected:
    int * hub_connected_ports;

  private:
    //void buildButterfly();
    //void buildBaseline();
    //void buildOmega();
    void buildCommon();
    void asciiMonitor();
};

//Hub * dd;

#endif
