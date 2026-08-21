/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * This file contains the implementation of the Network-on-Chip
 */

#include "NoC.h"

using namespace std;

inline int toggleKthBit(int n, int k) 
{ 
    return (n ^ (1 << (k-1))); 
}

void NoC::buildCommon()
{
	token_ring = new TokenRing("tokenring");
	token_ring->clock(clock);
	token_ring->reset(reset);


	char channel_name[16];
	for (map<int, ChannelConfig>::iterator it = GlobalParams::channel_configuration.begin();
		 it != GlobalParams::channel_configuration.end();
		 ++it)
	{
		int channel_id = it->first;
		sprintf(channel_name, "Channel_%d", channel_id);
		channel[channel_id] = new Channel(channel_name, channel_id);
	}

	char hub_name[16];
	for (map<int, HubConfig>::iterator it = GlobalParams::hub_configuration.begin();
		 it != GlobalParams::hub_configuration.end();
		 ++it)
	{
		int hub_id = it->first;
		//LOG << " hub id " <<  hub_id;
		HubConfig hub_config = it->second;

		sprintf(hub_name, "Hub_%d", hub_id);
		hub[hub_id] = new Hub(hub_name, hub_id,token_ring);
		hub[hub_id]->clock(clock);
		hub[hub_id]->reset(reset);


		// Determine, from configuration file, which Hub is connected to which Tile
		for(vector<int>::iterator iit = hub_config.attachedNodes.begin();
			iit != hub_config.attachedNodes.end();
			++iit)
		{
			GlobalParams::hub_for_tile[*iit] = hub_id;
			//LOG<<"I am hub "<<hub_id<<" and I amconnecting to "<<*iit<<endl;

		}
		//for (map<int, int>::iterator it1 = GlobalParams::hub_for_tile.begin(); it1 != GlobalParams::hub_for_tile.end(); it1++ )
		//LOG<<"it1 first "<< it1->first<< "second"<< it1->second<<endl;

		// Determine, from configuration file, which Hub is connected to which Channel
		for(vector<int>::iterator iit = hub_config.txChannels.begin();
			iit != hub_config.txChannels.end();
			++iit)
		{
			int channel_id = *iit;
			//LOG << "Binding " << hub[hub_id]->name() << " to txChannel " << channel_id << endl;
			hub[hub_id]->init[channel_id]->socket.bind(channel[channel_id]->targ_socket);
			//LOG << "Binding " << hub[hub_id]->name() << " to txChannel " << channel_id << endl;
			hub[hub_id]->setFlitTransmissionCycles(channel[channel_id]->getFlitTransmissionCycles(),channel_id);
		}

		for(vector<int>::iterator iit = hub_config.rxChannels.begin();
			iit != hub_config.rxChannels.end();
			++iit)
		{
			int channel_id = *iit;
			//LOG << "Binding " << hub[hub_id]->name() << " to rxChannel " << channel_id << endl;
			channel[channel_id]->init_socket.bind(hub[hub_id]->target[channel_id]->socket);
			channel[channel_id]->addHub(hub[hub_id]);
		}

		// TODO FIX
		// Hub Power model does not currently support different data rates for single hub
		// If multiple channels are connected to an Hub, the data rate
		// of the first channel will be used as default

		int no_channels = hub_config.txChannels.size();

		int data_rate_gbs;

		if (no_channels > 0) {
			data_rate_gbs = GlobalParams::channel_configuration[hub_config.txChannels[0]].dataRate;
		}
		else
			data_rate_gbs = NOT_VALID;

		// TODO: update power model (configureHub to support different tx/tx buffer depth in the power breakdown
		// Currently, an averaged value is used when accounting in Power class methods

		hub[hub_id]->power.configureHub(GlobalParams::flit_size,
										GlobalParams::hub_configuration[hub_id].toTileBufferSize,
										GlobalParams::hub_configuration[hub_id].fromTileBufferSize,
										GlobalParams::flit_size,
										GlobalParams::hub_configuration[hub_id].rxBufferSize,
										GlobalParams::hub_configuration[hub_id].txBufferSize,
										GlobalParams::flit_size,
										data_rate_gbs);
	}


	// Check for routing table availability
	if (GlobalParams::routing_algorithm == ROUTING_TABLE_BASED)
		assert(grtable.load(GlobalParams::routing_table_filename.c_str()));

	// Check for traffic table availability
	if (GlobalParams::traffic_distribution == TRAFFIC_TABLE_BASED)
		assert(gttable.load(GlobalParams::traffic_table_filename.c_str()));

	// Var to track Hub connected ports
	hub_connected_ports = (int *) calloc(GlobalParams::hub_configuration.size(), sizeof(int));

}

Tile *NoC::searchNode(const int id) const
{
    if (GlobalParams::topology == TOPOLOGY_MESH ||
        GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        for (int i = 0; i < GlobalParams::mesh_dim_x; i++)
            for (int j = 0; j < GlobalParams::mesh_dim_y; j++)
	        for (int k = 0; k < GlobalParams::mesh_dim_z; k++) {
                    if (t[xgetId(i,j,k)]->r->local_id == id)
                        return t[xgetId(i,j,k)].get();
                }
    }
    else // in delta topologies id equals to the vector index
	    return core[id];
    return NULL;
}

void NoC::asciiMonitor()
{
	//cout << sc_time_stamp().to_double()/GlobalParams::clock_period_ps << endl;
	system("clear");
	//
	// asciishow proof-of-concept #1 free slots

	if (GlobalParams::topology != TOPOLOGY_MESH)
	{
		cout << "Delta topologies are not supported for asciimonitor option!";
		assert(false);
	}
        for (int k = 0; k < GlobalParams::mesh_dim_z; k++)
        {
	    for (int j = 0; j < GlobalParams::mesh_dim_y; j++)
	    {
		for (int s = 0; s<3; s++)
		{
			for (int i = 0; i < GlobalParams::mesh_dim_x; i++)
			{
				if (s==0)
					std::printf("|  %d  ",t[xgetId(i,j,k)]->r->buffer[s][0].getCurrentFreeSlots());
				else
				if (s==1)
					std::printf("|%d   %d",t[xgetId(i,j,k)]->r->buffer[s][0].getCurrentFreeSlots(),t[xgetId(i,j,k)]->r->buffer[3][0].getCurrentFreeSlots());
				else
					std::printf("|__%d__",t[xgetId(i,j,k)]->r->buffer[2][0].getCurrentFreeSlots());
			}
			cout << endl;
		}
	    }
        }
}

