/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * This file contains the implementaton of the global statistics
 */

#include "GlobalStats.h"
#include "MultiNoC.h"
using namespace std;

GlobalStats::GlobalStats(const NoC * _noc)
{
    noc = _noc;

	#ifdef TESTING
    drained_total = 0;
	#endif
}

double GlobalStats::getAverageDelay()
{
    unsigned int total_packets = 0;
    double avg_delay = 0.0;

    if (GlobalParams::topology == TOPOLOGY_MESH)
    {
        for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
        {
            for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
            {
                for (int x = 0; x < GlobalParams::mesh_dim_x; x++)
                {
                    int id = xgetId(x,y,z);
                    unsigned int received_packets =
                        noc->t[id]->r->stats.getReceivedPackets();

                    if (received_packets) {
                        avg_delay += received_packets * noc->t[id]->r->stats.getAverageDelay();
                        total_packets += received_packets;
                    }
                }
	    }
        }
    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        for (auto& mesh_id_config : GlobalParams::mesh_component_config)
        {
            MeshComponentConfig& mesh_config = mesh_id_config.second;
            assert(mesh_config.nc != nullptr);
            MeshNoC& nc = *mesh_config.nc;

            for (auto tile_it = nc.begin(); tile_it != nc.end(); ++tile_it) {
                auto& tile = *tile_it;
                int id = tile->local_id;
                unsigned int received_packets =
                    nc.t[id]->r->stats.getReceivedPackets();

                if (received_packets) {
                    avg_delay += received_packets * nc.t[id]->r->stats.getAverageDelay();
                    total_packets += received_packets;
                }
            }
        }
    }
    else // other delta topologies
    { 
	for (int y = 0; y < GlobalParams::n_delta_tiles; y++)
	{
	    unsigned int received_packets =
		noc->core[y]->r->stats.getReceivedPackets();

	    if (received_packets) 
	    {
		avg_delay +=
		    received_packets *
		    noc->core[y]->r->stats.getAverageDelay();
		total_packets += received_packets;
	    }
	}

    }


    avg_delay /= (double) total_packets;

    return avg_delay;
}



double GlobalStats::getAverageDelay(const int src_id,
					 const int dst_id)
{
    Tile *tile = noc->searchNode(dst_id);

    assert(tile != NULL);

    return tile->r->stats.getAverageDelay(src_id);
}

double GlobalStats::getMaxDelay()
{
    double maxd = -1.0;

    if (GlobalParams::topology == TOPOLOGY_MESH) 
    {
        for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
            for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
                for (int x = 0; x < GlobalParams::mesh_dim_x; x++) 
                {
                    Coord coord;
                    coord.x = x;
                    coord.y = y;
                    coord.z = z;
                    int node_id = coord2Id(coord);
                    double d = getMaxDelay(node_id);
                    if (d > maxd)
                        maxd = d;
                }

    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        for (auto& mesh_id_config : GlobalParams::mesh_component_config)
        {
            MeshComponentConfig& mesh_config = mesh_id_config.second;
            assert(mesh_config.nc != nullptr);
            MeshNoC& nc = *mesh_config.nc;

            for (auto tile_it = nc.begin(); tile_it != nc.end(); ++tile_it) {
                auto& tile = *tile_it;
                int id = tile->local_id;
                unsigned int received_packets =
                    nc.t[id]->r->stats.getReceivedPackets();

                if (received_packets) {
                    double d = nc.t[id]->r->stats.getMaxDelay();
                    if (d > maxd)
                        maxd = d;
                }
            }
        }
    }
    else  // other delta topologies 
    {
	for (int y = 0; y < GlobalParams::n_delta_tiles; y++)
	{
	    double d = getMaxDelay(y);
	    if (d > maxd)
		maxd = d;
	}
    }

    return maxd;
}

double GlobalStats::getMaxDelay(const int node_id)
{
    if (GlobalParams::topology == TOPOLOGY_MESH) 
    {
	unsigned int received_packets =
	    noc->t[node_id]->r->stats.getReceivedPackets();

	if (received_packets)
	    return noc->t[node_id]->r->stats.getMaxDelay();
	else
	    return -1.0;
    }
    else // other delta topologies
    {
	unsigned int received_packets =
	    noc->core[node_id]->r->stats.getReceivedPackets();
	if (received_packets)
	    return noc->core[node_id]->r->stats.getMaxDelay();
	else
	    return -1.0;
    }

}

double GlobalStats::getMaxDelay(const int src_id, const int dst_id)
{
    Tile *tile = noc->searchNode(dst_id);

    assert(tile != NULL);

    return tile->r->stats.getMaxDelay(src_id);
}

vector < vector < vector < double > > > GlobalStats::getMaxDelayMtx()
{
    vector < vector < vector < double > > > mtx;

    assert(GlobalParams::topology == TOPOLOGY_MESH); 

    mtx.resize(GlobalParams::mesh_dim_z);
    for (int z = 0; z < GlobalParams::mesh_dim_z; z++) {
        mtx[z].resize(GlobalParams::mesh_dim_y);
        for (int y = 0; y < GlobalParams::mesh_dim_y; y++) {
            mtx[z][y].resize(GlobalParams::mesh_dim_x);
        }
    }

    for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
        for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
            for (int x = 0; x < GlobalParams::mesh_dim_x; x++)
            {
                Coord coord;
                coord.x = x;
                coord.y = y;
                coord.y = z;
                int id = coord2Id(coord);
                mtx[z][y][x] = getMaxDelay(id);
            }

    return mtx;
}

double GlobalStats::getAverageThroughput(const int src_id, const int dst_id)
{
    Tile *tile = noc->searchNode(dst_id);

    assert(tile != NULL);

    return tile->r->stats.getAverageThroughput(src_id);
}

/*
double GlobalStats::getAverageThroughput()
{
    unsigned int total_comms = 0;
    double avg_throughput = 0.0;

    for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
	for (int x = 0; x < GlobalParams::mesh_dim_x; x++) {
	    unsigned int ncomms =
		noc->t[x][y]->r->stats.getTotalCommunications();

	    if (ncomms) {
		avg_throughput +=
		    ncomms * noc->t[x][y]->r->stats.getAverageThroughput();
		total_comms += ncomms;
	    }
	}

    avg_throughput /= (double) total_comms;

    return avg_throughput;
}
*/

double GlobalStats::getAggregatedThroughput()
{
    int total_cycles = GlobalParams::simulation_time - GlobalParams::stats_warm_up_time;

    return (double)getReceivedFlits()/(double)(total_cycles);
}

unsigned int GlobalStats::getReceivedPackets()
{
    unsigned int n = 0;

    if (GlobalParams::topology == TOPOLOGY_MESH) 
    {
    	for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
            for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
                for (int x = 0; x < GlobalParams::mesh_dim_x; x++) {
                    n += noc->t[xgetId(x,y,z)]->r->stats.getReceivedPackets();
                }
    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        for (auto& mesh_id_config : GlobalParams::mesh_component_config)
        {
            MeshComponentConfig& mesh_config = mesh_id_config.second;
            assert(mesh_config.nc != nullptr);
            MeshNoC& nc = *mesh_config.nc;

            for (auto tile_it = nc.begin(); tile_it != nc.end(); ++tile_it) {
                auto& tile = *tile_it;
                n += nc.t[tile->local_id]->r->stats.getReceivedPackets();
            }
        }
    }
    else // other delta topologies
    {
    	for (int y = 0; y < GlobalParams::n_delta_tiles; y++)
	    n += noc->core[y]->r->stats.getReceivedPackets();
    }

    return n;
}

unsigned int GlobalStats::getSentFlits()
{
    unsigned int n = 0;
    if (GlobalParams::topology == TOPOLOGY_MESH) 
    {
    	for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
            for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
                for (int x = 0; x < GlobalParams::mesh_dim_x; x++) {
                    n += noc->t[xgetId(x,y,z)]->r->stats.getSentFlits();
                }
    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        const MultiNoC* multi_noc = dynamic_cast<const MultiNoC*>(noc);
        auto f = [&n](const Tile& tile) {
            n += tile.r->stats.getSentFlits();
        };

        multi_noc->evaluateOnTiles(f);
    }
    else // other delta topologies
    {
	for (int y = 0; y < GlobalParams::n_delta_tiles; y++)
	{
	    n += noc->core[y]->r->stats.getSentFlits();
#ifdef TESTING
	    drained_total += noc->core[y]->r->local_drained;
#endif
	}
    }

    return n;
}

unsigned int GlobalStats::getNumberOfReservations() const {
    unsigned int n = 0;

    if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        const MultiNoC* multi_noc = dynamic_cast<const MultiNoC*>(noc);
        auto f = [&n](const Tile& tile) {
            for (int i = 0; i < DIRECTIONS+2; i++)
                n += tile.r->reservation_table.getReservations(i).size();
        };

        multi_noc->evaluateOnTiles(f);
    }

    return n;
}

unsigned int GlobalStats::getReceivedFlits()
{
    unsigned int n = 0;
    if (GlobalParams::topology == TOPOLOGY_MESH) 
    {
    	for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
            for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
                for (int x = 0; x < GlobalParams::mesh_dim_x; x++) {
                    n += noc->t[xgetId(x,y,z)]->r->stats.getReceivedFlits();
#ifdef TESTING
                    drained_total += noc->t[xgetId(x,y,z)]->r->local_drained;
#endif
                }
    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        for (auto& mesh_id_config : GlobalParams::mesh_component_config)
        {
            MeshComponentConfig& mesh_config = mesh_id_config.second;
            assert(mesh_config.nc != nullptr);
            MeshNoC& nc = *mesh_config.nc;

            for (auto tile_it = nc.begin(); tile_it != nc.end(); ++tile_it) {
                auto& tile = *tile_it;
                n += nc.t[tile->local_id]->r->stats.getReceivedFlits();
#ifdef TESTING
                drained_total += noc->t[xgetId(x,y,z)]->r->local_drained;
#endif
            }
        }
    }
    else // other delta topologies
    {
	for (int y = 0; y < GlobalParams::n_delta_tiles; y++)
	{
	    n += noc->core[y]->r->stats.getReceivedFlits();
#ifdef TESTING
	    drained_total += noc->core[y]->r->local_drained;
#endif
	}
    }

    return n;
}

double GlobalStats::getThroughput()
{
    if (GlobalParams::topology == TOPOLOGY_MESH) 
    {
	int number_of_ip = GlobalParams::mesh_dim_x * GlobalParams::mesh_dim_y * GlobalParams::mesh_dim_z;
	return (double)getAggregatedThroughput()/(double)(number_of_ip);
    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH) 
    {
	int number_of_ip = 0;

        for (auto& mesh_id_config : GlobalParams::mesh_component_config)
        {
            MeshComponentConfig& mesh_config = mesh_id_config.second;
            assert(mesh_config.nc != nullptr);
            MeshNoC& nc = *mesh_config.nc;
            number_of_ip += nc.mesh_dim_x * nc.mesh_dim_y * nc.mesh_dim_z;
        }
	return (double)getAggregatedThroughput()/(double)(number_of_ip);
    }
    else // other delta topologies
    {
	int number_of_ip = GlobalParams::n_delta_tiles;
	return (double)getAggregatedThroughput()/(double)(number_of_ip);
    }
}

// Only accounting IP that received at least one flit
double GlobalStats::getActiveThroughput()
{
    int total_cycles =
	GlobalParams::simulation_time -
	GlobalParams::stats_warm_up_time;
    unsigned int n = 0;
    unsigned int trf = 0;
    unsigned int rf ;
    if (GlobalParams::topology == TOPOLOGY_MESH) 
    {
    	for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
            for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
                for (int x = 0; x < GlobalParams::mesh_dim_x; x++)
                {
                    rf = noc->t[xgetId(x,y,z)]->r->stats.getReceivedFlits();

                    if (rf != 0)
                        n++;

                    trf += rf;
                }
    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        for (auto& mesh_id_config : GlobalParams::mesh_component_config)
        {
            MeshComponentConfig& mesh_config = mesh_id_config.second;
            assert(mesh_config.nc != nullptr);
            MeshNoC& nc = *mesh_config.nc;

            for (auto tile_it = nc.begin(); tile_it != nc.end(); ++tile_it) {
                auto& tile = *tile_it;
                rf = nc.t[tile->local_id]->r->stats.getReceivedFlits();
                if (rf != 0)
                    n++;

                trf += rf;
            }
        }
    }
    else // other delta topologies
    {
	for (int y = 0; y < GlobalParams::n_delta_tiles; y++)
	{
	    rf = noc->core[y]->r->stats.getReceivedFlits();

	    if (rf != 0)
		n++;

	    trf += rf;
	}
    }

    return (double) trf / (double) (total_cycles * n);

}

vector < vector < vector < unsigned long > > > GlobalStats::getRoutedFlitsMtx()
{

    vector < vector < vector < unsigned long > > > mtx;
    assert (GlobalParams::topology == TOPOLOGY_MESH); 

    mtx.resize(GlobalParams::mesh_dim_z);
    for (int z = 0; z < GlobalParams::mesh_dim_z; z++) {
        mtx[z].resize(GlobalParams::mesh_dim_y);
        for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
	    mtx[z][y].resize(GlobalParams::mesh_dim_x);
    }

    for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
        for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
            for (int x = 0; x < GlobalParams::mesh_dim_x; x++)
                mtx[z][y][x] = noc->t[xgetId(x,y,z)]->r->getRoutedFlits();

    return mtx;
}

unsigned int GlobalStats::getWirelessPackets()
{
    unsigned int packets = 0;

    // Wireless noc
    for (map<int, HubConfig>::iterator it = GlobalParams::hub_configuration.begin();
            it != GlobalParams::hub_configuration.end();
            ++it)
    {
	int hub_id = it->first;

	map<int,Hub*>::const_iterator i = noc->hub.find(hub_id);
	Hub * h = i->second;

	packets+= h->wireless_communications_counter;
    }
    return packets;
}

double GlobalStats::getDynamicPower()
{
    double power = 0.0;

    // Electric noc
    if (GlobalParams::topology == TOPOLOGY_MESH)
    {
        for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
            for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
                for (int x = 0; x < GlobalParams::mesh_dim_x; x++)
                    power += noc->t[xgetId(x,y,z)]->r->power.getDynamicPower();
    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        for (auto& mesh_id_config : GlobalParams::mesh_component_config)
        {
            MeshComponentConfig& mesh_config = mesh_id_config.second;
            assert(mesh_config.nc != nullptr);
            MeshNoC& nc = *mesh_config.nc;

            for (auto tile_it = nc.begin(); tile_it != nc.end(); ++tile_it) {
                auto& tile = *tile_it;
                power += nc.t[tile->local_id]->r->power.getDynamicPower();
            }
        }
    }
    else // other delta topologies
    {
	int stg = log2(GlobalParams::n_delta_tiles);
	int sw = GlobalParams::n_delta_tiles/2; //sw: switch number in each stage
	// Dimensions of the delta switch block network
	int dimX = stg;
	int dimY = sw;

	// power for delta topologies cores
	for (int y = 0; y < GlobalParams::n_delta_tiles; y++)
	    power += noc->core[y]->r->power.getDynamicPower();

	// power for delta topologies switches 
	for (int y = 0; y < dimY; y++)
	    for (int x = 0; x < dimX; x++)
		power += noc->t[xgetId(x,y,0)]->r->power.getDynamicPower();
    }

    // Wireless noc
    for (map<int, HubConfig>::iterator it = GlobalParams::hub_configuration.begin();
	    it != GlobalParams::hub_configuration.end();
	    ++it)
    {
	int hub_id = it->first;

	map<int,Hub*>::const_iterator i = noc->hub.find(hub_id);
	Hub * h = i->second;

	power+= h->power.getDynamicPower();
    }
    return power;
}

double GlobalStats::getStaticPower()
{
    double power = 0.0;

    if (GlobalParams::topology == TOPOLOGY_MESH) 
    {
        for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
            for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
                for (int x = 0; x < GlobalParams::mesh_dim_x; x++)
                    power += noc->t[xgetId(x,y,z)]->r->power.getStaticPower();
    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        for (auto& mesh_id_config : GlobalParams::mesh_component_config)
        {
            MeshComponentConfig& mesh_config = mesh_id_config.second;
            assert(mesh_config.nc != nullptr);
            MeshNoC& nc = *mesh_config.nc;

            for (auto tile_it = nc.begin(); tile_it != nc.end(); ++tile_it) {
                auto& tile = *tile_it;
                power += nc.t[tile->local_id]->r->power.getStaticPower();
            }
        }
    }
    else // other delta topologies
    {
	int stg = log2(GlobalParams::n_delta_tiles);
	int sw = GlobalParams::n_delta_tiles/2; //sw: switch number in each stage
	// Dimensions of the delta switch block network
	int dimX = stg;
	int dimY = sw;
	// power for delta topologies switches 
	for (int y = 0; y < dimY; y++)
	    for (int x = 0; x < dimX; x++)
		power += noc->t[xgetId(x,y,0)]->r->power.getDynamicPower();

	// delta cores
    	for (int y = 0; y < GlobalParams::n_delta_tiles; y++)
	    power += noc->core[y]->r->power.getStaticPower();
    }

    // Wireless noc
    for (map<int, HubConfig>::iterator it = GlobalParams::hub_configuration.begin();
            it != GlobalParams::hub_configuration.end();
            ++it)
    {
	int hub_id = it->first;

	map<int,Hub*>::const_iterator i = noc->hub.find(hub_id);
	Hub * h = i->second;

	power+= h->power.getStaticPower();
    }
    return power;
}

void GlobalStats::showStats(std::ostream & out, bool detailed)
{
    if (detailed) 
    {
	assert (GlobalParams::topology == TOPOLOGY_MESH); 
	out << endl << "detailed = [" << endl;

        for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
            for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
                for (int x = 0; x < GlobalParams::mesh_dim_x; x++)
                    noc->t[xgetId(x,y,z)]->r->stats.showStats(
                        z * (GlobalParams::mesh_dim_x * GlobalParams::mesh_dim_y) +
                        y *  GlobalParams::mesh_dim_x + x, out, true);
	out << "];" << endl;

	// show MaxDelay matrix
	vector < vector < vector < double > > > md_mtx = getMaxDelayMtx();

	out << endl << "max_delay = [" << endl;
        for (unsigned int z = 0; z < md_mtx.size(); z++)
        {
            for (unsigned int y = 0; y < md_mtx[z].size(); y++) 
            {
                out << "   ";
                for (unsigned int x = 0; x < md_mtx[z][y].size(); x++)
                    out << setw(6) << md_mtx[z][y][x];
                // FIXME (Davy): need to figure something out about the formatting of this stuff
	        out << endl;
            }
        }
	out << "];" << endl;

	// show RoutedFlits matrix
	vector < vector < vector < unsigned long > > > rf_mtx = getRoutedFlitsMtx();

	out << endl << "routed_flits = [" << endl;
        for (unsigned int z = 0; z < rf_mtx.size(); z++) 
            for (unsigned int y = 0; y < rf_mtx[z].size(); y++) 
            {
                out << "   ";
                for (unsigned int x = 0; x < rf_mtx[z][y].size(); x++)
                    out << setw(10) << rf_mtx[z][y][x];
                out << endl;
            }
	out << "];" << endl;

	showPowerBreakDown(out);
	showPowerManagerStats(out);
    }

#ifdef DEBUG

    if (GlobalParams::topology == TOPOLOGY_MESH)
    {
        for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
            for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
                for (int x = 0; x < GlobalParams::mesh_dim_x; x++)
                    out << "PE[" << x << "," << y << "," << z << "]"
                        << noc->t[xgetId(x,y,z)]->pe->getQueueSize()<< ",";
    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        for (auto& mesh_id_config : GlobalParams::mesh_component_config)
        {
            const string& mesh_name = mesh_id_config.first;
            MeshComponentConfig& mesh_config = mesh_id_config.second;
            assert(mesh_config.nc != nullptr);
            MeshNoC& nc = *mesh_config.nc;

            for (auto tile_it = nc.begin(); tile_it != nc.end(); ++tile_it) {
                auto& tile = *tile_it;
                Coord coord = tile->getCoord();
                out << mesh_name << "-PE[" << coord.x << "," << coord.y << "," << coord.z << "]"
                    << nc.t[tile->local_id]->pe->getQueueSize() << ",";
            }
        }
    }
    else // other delta topologies
    {
	out << "Queue sizes: " ;
	for (int i=0;i<GlobalParams::n_delta_tiles;i++)
		out << "PE"<<i << ": " << noc->core[i]->pe->getQueueSize()<< ",";
	out << endl;
    }
	
    out << endl;
#endif

    //int total_cycles = GlobalParams::simulation_time - GlobalParams::stats_warm_up_time;
#ifdef DEBUG_VC_UTILIZATION
    string name;
    MeshNoC* n;
    vector<size_t> i_inter;
    vector<size_t> i_intra;
    vector<size_t> r_inter;
    vector<size_t> r_intra;
    vector<size_t> cumulated_nb_flits_intra;
    vector<size_t> cumulated_nb_flits_inter;

    for (auto it_mesh  = GlobalParams::mesh_component_config.begin();
              it_mesh != GlobalParams::mesh_component_config.end();
            ++it_mesh)
    {
        i_inter.resize(MAX_VIRTUAL_CHANNELS, 0);
        i_intra.resize(MAX_VIRTUAL_CHANNELS, 0);
        r_inter.resize(MAX_VIRTUAL_CHANNELS, 0);
        r_intra.resize(MAX_VIRTUAL_CHANNELS, 0);
        cumulated_nb_flits_intra.resize(MAX_VIRTUAL_CHANNELS, 0);
        cumulated_nb_flits_inter.resize(MAX_VIRTUAL_CHANNELS, 0);

        n = it_mesh->second.nc;
        name = it_mesh->first;

        for (auto it = n->begin(); it != n->end(); it++) {
            for (size_t vc = 0; vc < MAX_VIRTUAL_CHANNELS; vc++) {
		i_inter[vc] += (*it)->r->stats.flit_injected_inter[name][vc];
		i_intra[vc] += (*it)->r->stats.flit_injected_intra[name][vc];
		
		r_inter[vc] += (*it)->r->stats.flit_received_inter[name][vc];
		r_intra[vc] += (*it)->r->stats.flit_received_intra[name][vc];

		cumulated_nb_flits_intra[vc] +=
                    (*it)->r->stats.cumulated_nb_flits_intra[name][vc];
		cumulated_nb_flits_inter[vc] +=
                    (*it)->r->stats.cumulated_nb_flits_inter[name][vc];
            }
        }

        out << "\% VC Utilization of NoC " << name << ":" << endl;

        for (size_t vc = 0; vc < MAX_VIRTUAL_CHANNELS; vc++)
        {
            if (i_inter[vc] == 0 && i_intra[vc] == 0 &&
                r_inter[vc] == 0 && r_intra[vc] == 0)
            {
                out << "\% \tSkip VC" << vc
                    << " as no flit were injected or consumed" << endl;
                continue;
            }
            out << "\% \tVC" << vc << ":" << endl;
            out << "\% \t\tInter-chiplet flits injected: " << i_inter[vc] << " ("
                << ((double)i_inter[vc]/(double)(i_inter[vc]+r_inter[vc]))*100
                << "\% VC" << vc << " inter-chiplet traffic)" << endl;
            out << "\% \t\tInter-chiplet flits received: " << r_inter[vc] << " ("
                << ((double)r_inter[vc]/(double)(i_inter[vc]+r_inter[vc]))*100
                << "\% VC" << vc << " inter-chiplet traffic)" << endl;
            out << "\% \t\tIntra-chiplet flits injected: " << i_intra[vc] << " ("
                << ((double)i_intra[vc]/(double)(i_intra[vc]+r_intra[vc]))*100
                << "\% VC" << vc << " intra-chiplet traffic)" << endl;
            out << "\% \t\tIntra-chiplet flits received: " << r_intra[vc] << " ("
                << ((double)r_intra[vc]/(double)(i_intra[vc]+r_intra[vc]))*100
                << "\% VC" << vc << " intra-chiplet traffic)" << endl;
            out << "\% \t\tTotal flits injected: " << i_inter[vc]+i_intra[vc]
                << " ("
                << ((double)(i_inter[vc]+i_intra[vc])/(double)(i_intra[vc]+r_intra[vc]+i_inter[vc]+r_inter[vc]))*100
                << "\% VC" << vc << " traffic)" << endl;
            out << "\% \t\tTotal flits received: " << r_inter[vc]+r_intra[vc]
                << " ("
                << ((double)(r_inter[vc]+r_intra[vc])/(double)(i_intra[vc]+r_intra[vc]+i_inter[vc]+r_inter[vc]))*100
                << "\% VC" << vc << " traffic)" << endl;
        }

        out << "\% \tPercentage of VC injection/reception when compared to total traffic (including every VCs):" << endl;
        size_t n_total = 0;

        for (size_t vc = 0; vc < MAX_VIRTUAL_CHANNELS; vc++)   
            n_total += i_inter[vc]+i_intra[vc]+r_inter[vc]+r_intra[vc];

        for (size_t vc = 0; vc < MAX_VIRTUAL_CHANNELS; vc++)
        {   
            size_t n = i_inter[vc]+i_intra[vc]+r_inter[vc]+r_intra[vc];
            if (n)
                out << "\% \t\tVC" << vc << ": " << ((double)n/(double)n_total)*100 << "\%" << endl;
        }

        out << "\% \tCumulated number of flits in any buffer at each cycle:" << endl;

        for (size_t vc = 0; vc < MAX_VIRTUAL_CHANNELS; vc++)
        {
            if (!cumulated_nb_flits_inter[vc] &&
                !cumulated_nb_flits_intra[vc]) {
                out << "\% \t\tSkip VC" << vc << endl;
                continue;
            }
            out << "\% \t\tInter-NoC on VC" << vc << ": " << cumulated_nb_flits_inter[vc] << endl;
            out << "\% \t\tIntra-NoC on VC" << vc << ": " << cumulated_nb_flits_intra[vc] << endl;
        }

        i_inter.clear();
        i_intra.clear();
        r_inter.clear();
        r_intra.clear();
        cumulated_nb_flits_inter.clear();
        cumulated_nb_flits_intra.clear();
    }
#endif // DEBUG_VC_UTILIZATION

    out << "\% Number of directions still reserved: " << getNumberOfReservations() << endl;
    out << "\% Total sent flits: " << getSentFlits() << endl;
    out << "\% Total received packets: " << getReceivedPackets() << endl;
    out << "\% Total received flits: " << getReceivedFlits() << endl;
    out << "\% Received/Ideal flits Ratio: " << getReceivedIdealFlitRatio() << endl;
    out << "\% Average wireless utilization: " << getWirelessPackets()/(double)getReceivedPackets() << endl;
    out << "\% Global average delay (cycles): " << getAverageDelay() << endl;
    out << "\% Max delay (cycles): " << getMaxDelay() << endl;
    out << "\% Network throughput (flits/cycle): " << getAggregatedThroughput() << endl;
    out << "\% Average IP throughput (flits/cycle/IP): " << getThroughput() << endl;
    out << "\% Total energy (J): " << getTotalPower() << endl;
    out << "\% \tDynamic energy (J): " << getDynamicPower() << endl;
    out << "\% \tStatic energy (J): " << getStaticPower() << endl;

    if (GlobalParams::show_buffer_stats)
      showBufferStats(out);

}

void GlobalStats::updatePowerBreakDown(map<string,double> &dst,PowerBreakdown* src)
{
    for (int i=0;i!=src->size;i++)
    {
		dst[src->breakdown[i].label]+=src->breakdown[i].value;
    }
}

void GlobalStats::showPowerManagerStats(std::ostream & out)
{
    std::streamsize p = out.precision();
    int total_cycles = sc_time_stamp().to_double() / GlobalParams::clock_period_ps - GlobalParams::reset_time;

    out.precision(4);

    out << "powermanager_stats_tx = [" << endl;
    out << "%\tFraction of: TX Transceiver off (TTXoff), AntennaBufferTX off (ABTXoff) " << endl;
    out << "%\tHUB\tTTXoff\tABTXoff\t" << endl;

    for (map<int, HubConfig>::iterator it = GlobalParams::hub_configuration.begin();
            it != GlobalParams::hub_configuration.end();
            ++it)
    {
	int hub_id = it->first;

	map<int,Hub*>::const_iterator i = noc->hub.find(hub_id);
	Hub * h = i->second;

	out << "\t" << hub_id << "\t" << std::fixed << (double)h->total_ttxoff_cycles/total_cycles << "\t";

	int s = 0;
	for (map<int,int>::iterator i = h->abtxoff_cycles.begin(); i!=h->abtxoff_cycles.end();i++) s+=i->second;

	out << (double)s/h->abtxoff_cycles.size()/total_cycles << endl;
    }

    out << "];" << endl;



    out << "powermanager_stats_rx = [" << endl;
    out << "%\tFraction of: RX Transceiver off (TRXoff), AntennaBufferRX off (ABRXoff), BufferToTile off (BTToff) " << endl;
    out << "%\tHUB\tTRXoff\tABRXoff\tBTToff\t" << endl;



    for (map<int, HubConfig>::iterator it = GlobalParams::hub_configuration.begin();
            it != GlobalParams::hub_configuration.end();
            ++it)
    {
	string bttoff_str;

	out.precision(4);

	int hub_id = it->first;

	map<int,Hub*>::const_iterator i = noc->hub.find(hub_id);
	Hub * h = i->second;

	out << "\t" << hub_id << "\t" << std::fixed << (double)h->total_sleep_cycles/total_cycles << "\t";

	int s = 0;
	for (map<int,int>::iterator i = h->buffer_rx_sleep_cycles.begin();
		i!=h->buffer_rx_sleep_cycles.end();i++)
	    s+=i->second;

	out << (double)s/h->buffer_rx_sleep_cycles.size()/total_cycles << "\t";

	s = 0;
	for (map<int,int>::iterator i = h->buffer_to_tile_poweroff_cycles.begin();
		i!=h->buffer_to_tile_poweroff_cycles.end();i++)
	{
	    double bttoff_fraction = i->second/(double)total_cycles;
	    s+=i->second;
	    if (bttoff_fraction<0.25)
		bttoff_str+=" ";
	    else if (bttoff_fraction<0.5)
		    bttoff_str+=".";
	    else if (bttoff_fraction<0.75)
		    bttoff_str+="o";
	    else if (bttoff_fraction<0.90)
		    bttoff_str+="O";
	    else 
		bttoff_str+="0";
	    

	}
	out << (double)s/h->buffer_to_tile_poweroff_cycles.size()/total_cycles << "\t" << bttoff_str << endl;
    }

    out << "];" << endl;

    out.unsetf(std::ios::fixed);

    out.precision(p);

}

void GlobalStats::showPowerBreakDown(std::ostream & out)
{
    map<string,double> power_dynamic;
    map<string,double> power_static;

    if (GlobalParams::topology == TOPOLOGY_MESH) 
    {
        for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
            for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
                for (int x = 0; x < GlobalParams::mesh_dim_x; x++)
                {
                    updatePowerBreakDown(power_dynamic, noc->t[xgetId(x,y,z)]->r->power.getDynamicPowerBreakDown());
                    updatePowerBreakDown(power_static, noc->t[xgetId(x,y,z)]->r->power.getStaticPowerBreakDown());
                }
    }
    else // other delta topologies
    {
	for (int y = 0; y < GlobalParams::n_delta_tiles; y++)
	{
	    updatePowerBreakDown(power_dynamic, noc->core[y]->r->power.getDynamicPowerBreakDown());
	    updatePowerBreakDown(power_static, noc->core[y]->r->power.getStaticPowerBreakDown());
	}
    }

    for (map<int, HubConfig>::iterator it = GlobalParams::hub_configuration.begin();
	    it != GlobalParams::hub_configuration.end();
	    ++it)
    {
	int hub_id = it->first;

	map<int,Hub*>::const_iterator i = noc->hub.find(hub_id);
	Hub * h = i->second;

	updatePowerBreakDown(power_dynamic, 
		h->power.getDynamicPowerBreakDown());

	updatePowerBreakDown(power_static, 
		h->power.getStaticPowerBreakDown());
    }

    printMap("power_dynamic",power_dynamic,out);
    printMap("power_static",power_static,out);

}



void GlobalStats::showBufferStats(std::ostream & out)
{
  out << "Router id\tBuffer N\t\tBuffer E\t\tBuffer S\t\tBuffer W\t\tBuffer L" << endl;
  out << "         \tMean\tMax\tMean\tMax\tMean\tMax\tMean\tMax\tMean\tMax" << endl;
  
  if (GlobalParams::topology == TOPOLOGY_MESH) 
    {
    	for (int z = 0; z < GlobalParams::mesh_dim_z; z++)
    	for (int y = 0; y < GlobalParams::mesh_dim_y; y++)
    	for (int x = 0; x < GlobalParams::mesh_dim_x; x++)
      	{
			out << noc->t[xgetId(x,y,z)]->r->local_id;
			noc->t[xgetId(x,y,z)]->r->ShowBuffersStats(out);
			out << endl;
     	}
    }
    else // other delta topologies
    {
    	for (int y = 0; y < GlobalParams::n_delta_tiles; y++)
    	{
			out << noc->core[y]->r->local_id;
			noc->core[y]->r->ShowBuffersStats(out);
			out << endl;
     	}
    }

}

double GlobalStats::getReceivedIdealFlitRatio()
{
    int total_cycles;
    total_cycles= GlobalParams::simulation_time - GlobalParams::stats_warm_up_time;
    double ratio;
    if (GlobalParams::topology == TOPOLOGY_MESH) 
    {
	ratio = getReceivedFlits() /(GlobalParams::packet_injection_rate * (GlobalParams::min_packet_size +
		    GlobalParams::max_packet_size)/2 * total_cycles * GlobalParams::mesh_dim_y * GlobalParams::mesh_dim_x * GlobalParams::mesh_dim_z);
    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH) 
    {
        //int multi_mesh_dim = 0;

        /*for (auto& mesh_id_config : GlobalParams::mesh_component_config)
        {
            MeshComponentConfig& mesh_config = mesh_id_config.second;
            MeshNoC& nc = *mesh_config.nc;
            multi_mesh_dim += nc.mesh_dim_x * nc.mesh_dim_y * nc.mesh_dim_z;
        }*/
        int multi_mesh_dim = ProcessingElement::multi_noc_pe_list.size();
	ratio = getReceivedFlits() / (GlobalParams::packet_injection_rate * (GlobalParams::min_packet_size +
		    GlobalParams::max_packet_size)/2 * total_cycles * multi_mesh_dim);
    }
    else // other delta topologies
    {
	ratio = getReceivedFlits() /(GlobalParams::packet_injection_rate * (GlobalParams::min_packet_size +
		    GlobalParams::max_packet_size)/2 * total_cycles * GlobalParams::n_delta_tiles);
    }
    return ratio;
}
