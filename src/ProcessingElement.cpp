/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * This file contains the implementation of the processing element
 */

#include "ProcessingElement.h"
#include "MeshNoC.h"
#include "MultiNoC.h"

vector<int> ProcessingElement::multi_noc_pe_list;

ProcessingElement::ProcessingElement(const sc_module_name& name,
                                     Tile& tile)
    : sc_module(name),
      local_id(tile.local_id),
      global_id(tile.global_id),
      routing_algorithm(*tile.getRouter().routingAlgorithm),
      tile(tile), gen(rd())
{
    // Check the validity of the Routing Algorithm
    sc_assert(tile.getRouter().routingAlgorithm != nullptr);

    SC_METHOD(rxProcess);
    sensitive << reset;
    sensitive << clock.pos();

    SC_METHOD(txProcess);
    sensitive << reset;
    sensitive << clock.pos();

    disable_pe = false;

    if (GlobalParams::traffic_distribution == TRAFFIC_LOCAL_CHIPLET)
    {
        vector<double> global_probabilities;
        unsigned num_chiplet = GlobalParams::mesh_component_config.size();
        global_probabilities.resize(num_chiplet, 0.);

        double inter_chiplet_proba = GlobalParams::locality;
        double per_chiplet_proba =
            (1. - inter_chiplet_proba)/static_cast<double>(num_chiplet-1);

        const unsigned curr_chiplet_id = tile.getNoC().getId();
        global_probabilities[curr_chiplet_id] = inter_chiplet_proba;
        for (size_t i = 0; i < num_chiplet; i++)
            if (i != curr_chiplet_id)
                global_probabilities[i] = per_chiplet_proba;

        std::discrete_distribution<unsigned> d1 {global_probabilities.begin(), global_probabilities.end()};
        d.param(d1.param());
    }
}

void ProcessingElement::listAvailablePEs()
{
    if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        for (auto& mesh_id_config : GlobalParams::mesh_component_config)
        {
            MeshNoC& nc = *mesh_id_config.second.nc;
            const set<int>& custom_pe = mesh_id_config.second.custom_pe;
            // In the case of a custom PE list
            if (custom_pe.size()) {
                // First, disable all the PEs
                for (auto it_tile  = nc.begin();
                          it_tile != nc.end(); it_tile++)
                    (*it_tile)->pe->disable_pe = true;

                for (auto pe : custom_pe) {
                    Tile* t = nc.searchNode(pe);
                    // Then, only enable the valid one in the list
                    if (t) {
                        t->pe->disable_pe = false;
                        multi_noc_pe_list.push_back(pe + nc.getGlobalIdOffset());
                    }
                }
            }
            // No PE list
            else
            {
                for (auto it_tile  = nc.begin();
                          it_tile != nc.end(); it_tile++)
                    multi_noc_pe_list.push_back((*it_tile)->global_id);
            }
        }
    }
}

int ProcessingElement::randInt(int min, int max)
{
    return min +
	(int) ((double) (max - min + 1) * rand() / (RAND_MAX + 1.0));
}

void ProcessingElement::rxProcess()
{
    //cout << "rxProcess called from " << name() << endl;
    if (reset.read()) {
	ack_rx.write(0);
	current_level_rx = 0;
    } else {
	if (req_rx.read() == 1 - current_level_rx) {
	    Flit flit_tmp = flit_rx.read();
	    current_level_rx = 1 - current_level_rx;	// Negate the old value for Alternating Bit Protocol (ABP)
	}
	ack_rx.write(current_level_rx);
    }
}

void ProcessingElement::txProcess()
{
    if (reset.read()) {
	req_tx.write(0);
	current_level_tx = 0;
	transmittedAtPreviousCycle = false;
    } else {
	Packet packet;

	if (canShot(packet)) {
            // Some routing algorithms requires that freshly emitted flits
            // must have a proper VC allocation. In such case, regardless
            // of the choice made by the PE, we let the routing algorithm
            // override the packet's vc_id.
            if (routing_algorithm.restrict_vc_allocation)
                routing_algorithm.allocateVC(tile.getRouter(), packet);
	    packet_queue.push(packet);
	    transmittedAtPreviousCycle = true;
	} else
	    transmittedAtPreviousCycle = false;


	if (ack_tx.read() == current_level_tx) {
	    if (!packet_queue.empty()) {
		Flit flit = nextFlit();	// Generate a new flit
		flit_tx->write(flit);	// Send the generated flit
		current_level_tx = 1 - current_level_tx;	// Negate the old value for Alternating Bit Protocol (ABP)
		req_tx.write(current_level_tx);
	    }
	}
    }
}

Flit ProcessingElement::nextFlit()
{
    Flit flit;
    Packet packet = packet_queue.front();

    flit.src_id = packet.src_id;
    flit.dst_id = packet.dst_id;
    flit.vc_id  = packet.vc_id;
    flit.timestamp = packet.timestamp;
    flit.sequence_no = packet.size - packet.flit_left;
    flit.sequence_length = packet.size;
    flit.hop_no = 0;
    //  flit.payload     = DEFAULT_PAYLOAD;

    flit.hub_relay_node = NOT_VALID;

    if (packet.size == packet.flit_left)
	flit.flit_type = FLIT_TYPE_HEAD;
    else if (packet.flit_left == 1)
	flit.flit_type = FLIT_TYPE_TAIL;
    else
	flit.flit_type = FLIT_TYPE_BODY;

    packet_queue.front().flit_left--;
    if (packet_queue.front().flit_left == 0)
	packet_queue.pop();

    return flit;
}

bool ProcessingElement::canShot(Packet & packet)
{
   // assert(false);
    if(never_transmit || GlobalParams::traffic_distribution == TRAFFIC_DRAIN)
        return false;

    if (disable_pe)
        return false;

    //if(local_id!=16) return false;
    /* DEADLOCK TEST 
	double current_time = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;

	if (current_time >= 4100) 
	{
	    //if (current_time==3500)
	         //cout << name() << " IN CODA " << packet_queue.size() << endl;
	    return false;
	}
	//*/

#ifdef DEADLOCK_AVOIDANCE
    if (local_id%2==0)
	return false;
#endif
    bool shot;
    double threshold;

    double now = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;

    static bool has_been_shot = false;
    if (GlobalParams::traffic_distribution == TRAFFIC_SINGLE_PACKET)
    {
        int pe_src_id = (GlobalParams::topology == TOPOLOGY_MULTI_MESH) ?
                         global_id : local_id;
        packet = trafficSinglePacket();
        if (!has_been_shot &&
            packet.src_id == pe_src_id)
        {
            has_been_shot = true;
            return true;
        }
        return false;
    }

    if (GlobalParams::traffic_distribution != TRAFFIC_TABLE_BASED) {
	if (!transmittedAtPreviousCycle)
	    threshold = GlobalParams::packet_injection_rate;
	else
	    threshold = GlobalParams::probability_of_retransmission;

	shot = (((double) rand()) / RAND_MAX < threshold);
	if (shot) {
	    if (GlobalParams::traffic_distribution == TRAFFIC_RANDOM)
		    packet = trafficRandom();
        else if (GlobalParams::traffic_distribution == TRAFFIC_TRANSPOSE1)
		    packet = trafficTranspose1();
        else if (GlobalParams::traffic_distribution == TRAFFIC_TRANSPOSE2)
    		packet = trafficTranspose2();
        else if (GlobalParams::traffic_distribution == TRAFFIC_BIT_REVERSAL)
		    packet = trafficBitReversal();
        else if (GlobalParams::traffic_distribution == TRAFFIC_SHUFFLE)
		    packet = trafficShuffle();
        else if (GlobalParams::traffic_distribution == TRAFFIC_BUTTERFLY)
		    packet = trafficButterfly();
        else if (GlobalParams::traffic_distribution == TRAFFIC_LOCAL)
		    packet = trafficLocal();
        else if (GlobalParams::traffic_distribution == TRAFFIC_ULOCAL)
		    packet = trafficULocal();
        else if (GlobalParams::traffic_distribution == TRAFFIC_LOCAL_CHIPLET)
		    packet = trafficLocalChiplet();
        else {
            cout << "Invalid traffic distribution: " << GlobalParams::traffic_distribution << endl;
            exit(-1);
        }
	}
    } else {			// Table based communication traffic
	if (never_transmit)
	    return false;

	bool use_pir = (transmittedAtPreviousCycle == false);
	vector < pair < int, double > > dst_prob;
        int src_id = (GlobalParams::topology == TOPOLOGY_MULTI_MESH) ?
            global_id : local_id;
	double threshold =
	    traffic_table->getCumulativePirPor(src_id, (int) now, use_pir, dst_prob);

	double prob = (double) rand() / RAND_MAX;
	shot = (prob < threshold);
	if (shot) {
	    for (unsigned int i = 0; i < dst_prob.size(); i++) {
		if (prob < dst_prob[i].second) {
                    int vc = randInt(0, tile.getNoC().n_virtual_channels-1);
		    packet.make(src_id, dst_prob[i].first, vc, now, getRandomSize());
		    break;
		}
	    }
	}
    }
    return shot;
}

Packet ProcessingElement::trafficLocalChiplet()
{
    assert(GlobalParams::topology == TOPOLOGY_MULTI_MESH);

    unsigned v = d(gen);

    string dummy;
    const MeshNoC& nc = *MultiNoC::retrieveMeshConfig(v, dummy).nc;
    const IdRange& chip_min_max = nc.getGlobalIdRange();
    
    int res = randInt(chip_min_max.minId, chip_min_max.maxId - 1);

    Packet p;
    p.src_id = global_id;

    p.dst_id = res;
    p.timestamp = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;
    p.size = p.flit_left = getRandomSize();
    p.vc_id = randInt(0, tile.getNoC().n_virtual_channels-1);
    
    return p;
}

Packet ProcessingElement::trafficLocal()
{
    Packet p;
    p.src_id = local_id;
    double rnd = rand() / (double) RAND_MAX;

    vector<int> dst_set;

    int max_id = (GlobalParams::mesh_dim_x * GlobalParams::mesh_dim_y);

    for (int i=0;i<max_id;i++)
    {
	if (rnd<=GlobalParams::locality)
	{
	    if (local_id!=i && sameRadioHub(local_id,i))
		dst_set.push_back(i);
	}
	else
	    if (!sameRadioHub(local_id,i))
		dst_set.push_back(i);
    }


    int i_rnd = rand()%dst_set.size();

    p.dst_id = dst_set[i_rnd];
    p.timestamp = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;
    p.size = p.flit_left = getRandomSize();
    p.vc_id = randInt(0, tile.getNoC().n_virtual_channels-1);
    
    return p;
}


int ProcessingElement::findRandomDestination(int id, int hops)
{
    assert(GlobalParams::topology == TOPOLOGY_MESH);

    int inc_y = rand()%2?-1:1;
    int inc_x = rand()%2?-1:1;
    
    Coord current =  id2Coord(id);
    


    for (int h = 0; h<hops; h++)
    {

	if (current.x==0)
	    if (inc_x<0) inc_x=0;

	if (current.x== GlobalParams::mesh_dim_x-1)
	    if (inc_x>0) inc_x=0;

	if (current.y==0)
	    if (inc_y<0) inc_y=0;

	if (current.y==GlobalParams::mesh_dim_y-1)
	    if (inc_y>0) inc_y=0;

	if (rand()%2)
	    current.x +=inc_x;
	else
	    current.y +=inc_y;
    }
    return coord2Id(current);
}


int roulette()
{
    int slices = GlobalParams::mesh_dim_x + GlobalParams::mesh_dim_y -2;


    double r = rand()/(double)RAND_MAX;


    for (int i=1;i<=slices;i++)
    {
	if (r< (1-1/double(2<<i)))
	{
	    return i;
	}
    }
    assert(false);
    return 1;
}


Packet ProcessingElement::trafficULocal()
{
    Packet p;
    p.src_id = local_id;

    int target_hops = roulette();

    p.dst_id = findRandomDestination(local_id,target_hops);

    p.timestamp = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;
    p.size = p.flit_left = getRandomSize();
    p.vc_id = randInt(0, tile.getNoC().n_virtual_channels-1);

    return p;
}

Packet ProcessingElement::trafficRandom()
{
    Packet p;
    if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
        p.src_id = global_id;
    else
        p.src_id = local_id;
    double rnd = rand() / (double) RAND_MAX;
    double range_start = 0.0;
    int max_id;

    if (GlobalParams::topology == TOPOLOGY_MESH)
	max_id = (GlobalParams::mesh_dim_x * GlobalParams::mesh_dim_y * GlobalParams::mesh_dim_z) - 1; //Mesh
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH) {
	max_id = multi_noc_pe_list.size() - 1;
    }
    else    // other delta topologies
	max_id = GlobalParams::n_delta_tiles-1; 

    // Random destination distribution
    do {
        if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
	    p.dst_id = multi_noc_pe_list[randInt(0, max_id)];
        else
	    p.dst_id = randInt(0, max_id);

	// check for hotspot destination
	for (size_t i = 0; i < GlobalParams::hotspots.size(); i++) {

	    if (rnd >= range_start && rnd < range_start + GlobalParams::hotspots[i].second) {
		if (local_id != GlobalParams::hotspots[i].first ) {
		    p.dst_id = GlobalParams::hotspots[i].first;
		}
		break;
	    } else
		range_start += GlobalParams::hotspots[i].second;	// try next
	}
#ifdef DEADLOCK_AVOIDANCE
	assert((GlobalParams::topology == TOPOLOGY_MESH));
	if (p.dst_id%2!=0)
	{
	    p.dst_id = (p.dst_id+1)%256;
	}
#endif

    } while (p.dst_id == p.src_id);

    p.timestamp = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;
    p.size = p.flit_left = getRandomSize();
    p.vc_id = randInt(0, tile.getNoC().n_virtual_channels-1);

    return p;
}

Packet ProcessingElement::trafficSinglePacket()
{
    Packet p;

    if (GlobalParams::topology == TOPOLOGY_MULTI_MESH) {
        p.src_id = MeshNoC::convertLocalToGlobalId(
            GlobalParams::traffic_single_packet_src_id,
            GlobalParams::traffic_single_packet_src_chip
        );
        p.dst_id = MeshNoC::convertLocalToGlobalId(
            GlobalParams::traffic_single_packet_dst_id,
            GlobalParams::traffic_single_packet_dst_chip
        );
    }
    else {
        p.src_id = GlobalParams::traffic_single_packet_src_id;
        p.dst_id = GlobalParams::traffic_single_packet_dst_id;
    }

    p.timestamp = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;
    p.size = p.flit_left = getRandomSize();
    p.vc_id = randInt(0, tile.getNoC().n_virtual_channels-1);

    return p;
}

Packet ProcessingElement::trafficTranspose1()
{
    assert(GlobalParams::topology == TOPOLOGY_MESH);
    Packet p;
    p.src_id = local_id;
    Coord src, dst;

    // Transpose 1 destination distribution
    src.x = id2Coord(p.src_id).x;
    src.y = id2Coord(p.src_id).y;
    dst.x = GlobalParams::mesh_dim_x - 1 - src.y;
    dst.y = GlobalParams::mesh_dim_y - 1 - src.x;
    fixRanges(src, dst);
    p.dst_id = coord2Id(dst);

    p.vc_id = randInt(0, tile.getNoC().n_virtual_channels-1);
    p.timestamp = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;
    p.size = p.flit_left = getRandomSize();

    return p;
}

Packet ProcessingElement::trafficTranspose2()
{
    assert(GlobalParams::topology == TOPOLOGY_MESH);
    Packet p;
    p.src_id = local_id;
    Coord src, dst;

    // Transpose 2 destination distribution
    src.x = id2Coord(p.src_id).x;
    src.y = id2Coord(p.src_id).y;
    dst.x = src.y;
    dst.y = src.x;
    fixRanges(src, dst);
    p.dst_id = coord2Id(dst);

    p.vc_id = randInt(0, tile.getNoC().n_virtual_channels-1);
    p.timestamp = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;
    p.size = p.flit_left = getRandomSize();

    return p;
}

void ProcessingElement::setBit(int &x, int w, int v)
{
    int mask = 1 << w;

    if (v == 1)
	x = x | mask;
    else if (v == 0)
	x = x & ~mask;
    else
	assert(false);
}

int ProcessingElement::getBit(int x, int w)
{
    return (x >> w) & 1;
}

inline double ProcessingElement::log2ceil(double x)
{
    return ceil(log(x) / log(2.0));
}

Packet ProcessingElement::trafficBitReversal()
{

    int nbits =
	(int)
	log2ceil((double)
		 (GlobalParams::mesh_dim_x *
		  GlobalParams::mesh_dim_y));
    int dnode = 0;
    for (int i = 0; i < nbits; i++)
	setBit(dnode, i, getBit(local_id, nbits - i - 1));

    Packet p;
    p.src_id = local_id;
    p.dst_id = dnode;

    p.vc_id = randInt(0, tile.getNoC().n_virtual_channels-1);
    p.timestamp = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;
    p.size = p.flit_left = getRandomSize();

    return p;
}

Packet ProcessingElement::trafficShuffle()
{

    int nbits =
	(int)
	log2ceil((double)
		 (GlobalParams::mesh_dim_x *
		  GlobalParams::mesh_dim_y));
    int dnode = 0;
    for (int i = 0; i < nbits - 1; i++)
	setBit(dnode, i + 1, getBit(local_id, i));
    setBit(dnode, 0, getBit(local_id, nbits - 1));

    Packet p;
    p.src_id = local_id;
    p.dst_id = dnode;

    p.vc_id = randInt(0, tile.getNoC().n_virtual_channels-1);
    p.timestamp = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;
    p.size = p.flit_left = getRandomSize();

    return p;
}

Packet ProcessingElement::trafficButterfly()
{

    int nbits = (int) log2ceil((double)
		 (GlobalParams::mesh_dim_x *
		  GlobalParams::mesh_dim_y));
    int dnode = 0;
    for (int i = 1; i < nbits - 1; i++)
	setBit(dnode, i, getBit(local_id, i));
    setBit(dnode, 0, getBit(local_id, nbits - 1));
    setBit(dnode, nbits - 1, getBit(local_id, 0));

    Packet p;
    p.src_id = local_id;
    p.dst_id = dnode;

    p.vc_id = randInt(0, tile.getNoC().n_virtual_channels-1);
    p.timestamp = sc_time_stamp().to_double() / GlobalParams::clock_period_ps;
    p.size = p.flit_left = getRandomSize();

    return p;
}

void ProcessingElement::fixRanges(const Coord src,
				       Coord & dst)
{
    // Fix ranges
    if (dst.x < 0)
	dst.x = 0;
    if (dst.y < 0)
	dst.y = 0;
    if (dst.z < 0)
        dst.z = 0;
    if (dst.x >= GlobalParams::mesh_dim_x)
	dst.x = GlobalParams::mesh_dim_x - 1;
    if (dst.y >= GlobalParams::mesh_dim_y)
	dst.y = GlobalParams::mesh_dim_y - 1;
    if (dst.z >= GlobalParams::mesh_dim_z)
        dst.z = GlobalParams::mesh_dim_z - 1;
}

int ProcessingElement::getRandomSize()
{
    return randInt(GlobalParams::min_packet_size,
		   GlobalParams::max_packet_size);
}

unsigned int ProcessingElement::getQueueSize() const
{
    return packet_queue.size();
}

