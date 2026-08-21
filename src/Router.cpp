/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * This file contains the implementation of the router
 */

#include "Router.h"
#include "NoC.h"

inline int toggleKthBit(int n, int k)
{
	return (n ^ (1 << (k-1)));
}

void Router::process()
{
    txProcess();
    rxProcess();
}

void Router::rxProcess()
{
    if (reset.read()) {
	TBufferFullStatus bfs;
        TFreeSlots fs;
	// Clear outputs and indexes of receiving protocol
	for (int i = 0; i < DIRECTIONS + 2; i++) {
	    ack_rx[i].write(0);
	    current_level_rx[i] = 0;
	    buffer_full_status_rx[i].write(bfs);
	}
	for (int i = 0; i < DIRECTIONS + 1; i++) {
	    free_slots[i].write(fs);
        }
	routed_flits = 0;
	local_drained = 0;
    } 
    else 
    {
#ifdef DEBUG_VC_UTILIZATION
        stats.updateVCCumulatedNumberOfFlits(*this);
#endif
        int router_id = (GlobalParams::topology == TOPOLOGY_MULTI_MESH) ?
                         global_id : local_id;
	// This process simply sees a flow of incoming flits. All arbitration
	// and wormhole related issues are addressed in the txProcess()
	//assert(false);
	for (int i = 0; i < DIRECTIONS + 2; i++) {
	    // To accept a new flit, the following conditions must match:
	    // 1) there is an incoming request
	    // 2) there is a free slot in the input buffer of direction i
	    //LOG<<"****RX****DIRECTION ="<<i<<  endl;

	    if (req_rx[i].read() == 1 - current_level_rx[i])
	    { 
		Flit received_flit = flit_rx[i].read();
		//LOG<<"request opposite to the current_level, reading flit "<<received_flit<<endl;
                
		int vc = received_flit.vc_id;

		if (!buffer[i][vc].IsFull())
		{
		    // Store the incoming flit in the circular buffer
		    buffer[i][vc].Push(received_flit);
		    LOG << " Flit " << received_flit << " collected from Input[" << i << "][" << vc <<"]" << endl;

		    power.bufferRouterPush();

		    // Negate the old value for Alternating Bit Protocol (ABP)
		    //LOG<<"INVERTING CL FROM "<< current_level_rx[i]<< " TO "<<  1 - current_level_rx[i]<<endl;
		    current_level_rx[i] = 1 - current_level_rx[i];

		    // if a new flit is injected from local PE
		    if (received_flit.src_id == router_id) {
			power.networkInterface();
                        stats.sentFlit(sc_time_stamp().to_double() /
                                       GlobalParams::clock_period_ps,
                                       received_flit);
#ifdef DEBUG_VC_UTILIZATION
                        stats.updateVCInjectedFlits(*this, received_flit);
#endif
                    }
		}

		else  // buffer full
		{
		    // should not happen with the new TBufferFullStatus control signals    
		    // except for flit coming from local PE, which don't use it 
		    LOG << " Flit " << received_flit << " buffer full Input[" << i << "][" << vc <<"]" << endl;
		    assert(i== DIRECTION_LOCAL);
		}

	    }
	    ack_rx[i].write(current_level_rx[i]);
	    // updates the mask of VCs to prevent incoming data on full buffers
	    TBufferFullStatus bfs;
	    for (int vc=0; vc < MAX_VIRTUAL_CHANNELS; vc++)
		bfs.mask[vc] = buffer[i][vc].IsFull();
	    buffer_full_status_rx[i].write(bfs);

            // Update current input buffers level to neighbors
            // NOTE: this code was previously part of both the NOP and the
            // BUFFER LEVEL selectionStrategy. It was added here instead to
            // support an atomic flow control
            if (i < DIRECTIONS + 1) {
                TFreeSlots fs;
                for (int vc = 0;
                         vc < MAX_VIRTUAL_CHANNELS;
                       ++vc) {
                    fs.mask[vc] = buffer[i][vc].getCurrentFreeSlots();
                }
                free_slots[i].write(fs);
            }

            // Updates signal linked to the selection strategy
            selectionStrategy->perCycleUpdate(this);
	}
    }
}

RouteData Router::getRouteData(const Flit & flit,
                               int input_dir) const
{
    return RouteData {
        .current_id = (GlobalParams::topology ==
                       TOPOLOGY_MULTI_MESH) ?
            global_id : local_id,
        .src_id = flit.src_id,
        .dst_id = flit.dst_id,
        .dir_in = input_dir,
        .vc_in  = flit.vc_id,
        .routing_towards_vlink = flit.routing_towards_vlink,
        .vlink_dest = (flit.routing_towards_vlink) ? flit.vlink_dest : -1
    };
}

void Router::txProcess()
{

  if (reset.read()) 
    {
      // Clear outputs and indexes of transmitting protocol
      for (int i = 0; i < DIRECTIONS + 2; i++) 
	{
	  req_tx[i].write(0);
	  current_level_tx[i] = 0;
	}
    } 
  else 
    { 
      // 1st phase: Reservation
      for (int j = 0; j < DIRECTIONS + 2; j++) 
	{
	  int i = (start_from_port + j) % (DIRECTIONS + 2);
          int vc_nb = getNoC().n_virtual_channels;
	  for (int k = 0; k < vc_nb; k++)
	  {
	      int vc = (start_from_vc[i]+k)%(vc_nb);
	      
	      // Uncomment to enable deadlock checking on buffers. 
	      // Please also set the appropriate threshold.
	      // buffer[i].deadlockCheck();

#ifdef ATOMIC_FLOW_CONTROL_CHECK
              // Check if Atomic Flow Control is enforced for
              // Buffer[inv(dir_out)][vc]
              if ( i != DIRECTION_LOCAL && i != DIRECTION_HUB &&
                   routingAlgorithm->requireAtomicFlowCtrl(reflexDirection(i),
                                                           vc) )
                  buffer[i][vc].atomicFlowControlCheck();
#endif // ATOMIC_FLOW_CONTROL_CHECK

	      if (!buffer[i][vc].IsEmpty()) 
	      {
                  //if (string(getNoC().name()) != "I")
                  //    sc_assert(vc < 2);
		  Flit flit = buffer[i][vc].Front();
		  power.bufferRouterFront();
		  
                  // Prepare data for routing
                  RouteData route_data(getRouteData(flit, i));

                  // If applicable, a dedicated pre-routing reservation process
                  // can be executed to modify the content of the buffer and
                  // the current flit
                  routingAlgorithm->customPreRoutingRes(*this, route_data,
                                                        buffer[i][vc], flit);

                  if (flit.flit_type == FLIT_TYPE_HEAD)
                  {

		      // TODO: see PER POSTERI (adaptive routing should not recompute route if already reserved)
		      RouteEntry route_entry = route(route_data);
                      int o    = route_entry.first;
                      int vc_o = route_entry.second;

                      // If applicable, a dedicated post-routing reservation
                      // process can be executed
                      bool skip_reservation =
                          routingAlgorithm->customPostRoutingRes(route_data,
                                                                 buffer[i][vc],
                                                                 flit, o);
                      if (skip_reservation)
                          continue;

		      // manage special case of target hub not directly connected to destination
		      if (o>=DIRECTION_HUB_RELAY)
			  {
		      	Flit f = buffer[i][vc].Pop();
		      	f.hub_relay_node = o-DIRECTION_HUB_RELAY;
		      	buffer[i][vc].Push(f);
		      	o = DIRECTION_HUB;
			  }

		      TReservation r;
                      r.input  = i;
                      r.vc_in  = vc;
                      r.vc_out = vc_o;

		      LOG << " checking availability of Output[" << o << "]["
                          << r.vc_out << "] for Input[" << i << "][" << vc
                          << "] flit " << flit << endl;

                      // If there is already a reservation for the current
                      // input_port/vc_in, it will be stored in this variable.
                      ReservationTable::res_t blocking_entry;

		      int rt_status =
                          reservation_table.checkReservation(r, o,
                                                             blocking_entry);

		      if (rt_status == RT_AVAILABLE)
		      {
			  LOG << " Reservation Successful: Output[" << o
                              << "][" << vc_o << "] reserved for flit "
                              << flit << endl;
			  reservation_table.reserve(r, o);
		      }
		      else if (rt_status == RT_AR_SAME_OUTPORT_SAME_OUTVC)
		      {
			  LOG << " Reservation Failed: Output[" << o
                              << "][" << vc_o << "] already reserved by flit "
                              << flit << endl;
		      }
		      else if (rt_status == RT_AR_SAME_OUTPORT_OTHER_OUTVC)
		      {
			  LOG << " Reservation Failed: Output[" << o
                              << "] already reserved with another VC-OUT by "
                                 "flit " << flit << endl;
		      }
		      else if (rt_status == RT_AR_OTHER_OUTPORT_SAME_OUTVC ||
                               rt_status == RT_AR_OTHER_OUTPORT_OTHER_OUTVC)
		      {
			  LOG << " Reservation Failed: tried reserving Output["
                              << o << "][" << vc_o << "] but reservation "
                                 "already done for another output by flit "
                              << flit << endl;
		      }
		      else if (rt_status == RT_OUTVC_BUSY)
		      {
			  LOG << " Reservation Failed: Output[" << o << "], VC"
                              << vc_o << " busy for flit " << flit << endl;
		      }
		      else assert(false); // no meaningful status here

                      // VC Re-allocation
                      //
                      // Authorize the router to release the current
                      // reservation operated for a given input port / vc_in,
                      // and create a new one using the new routing decision.
                      // NOTE: This logic is mandatory when using a fully-
                      // adaptive routing algorithm with atomic flow control,
                      // to ensure a blocked packet has always the possibility
                      // to break-free from a deadlock using an escape VC.
                      // 
                      // If a routing algorithm is not fully-adaptive, it can
                      // still benefit from VC Re-allocation by enabling the
                      // corresponding global parameter.
                      if ( GlobalParams::enable_vc_reallocation &&
                             // A reservation must be already done for the same
                             // input port / vc_in and the new reservation does
                             // not aim the same output port / vc_out
                            (rt_status == RT_AR_SAME_OUTPORT_OTHER_OUTVC ||
                             rt_status == RT_AR_OTHER_OUTPORT_SAME_OUTVC ||
                             rt_status == RT_AR_OTHER_OUTPORT_OTHER_OUTVC) )
                      {
                          TReservation existing_r;
                          existing_r.input  = r.input;
                          existing_r.vc_in  = r.vc_in;
                          existing_r.vc_out = get<2>(blocking_entry);
                          int existing_r_o  = get<0>(blocking_entry);

                          // Assert the existing blocking reservation is valid
                          sc_assert(existing_r.vc_out > -1 &&
                                    existing_r_o > -1);

                          bool target_buffer_empty =
                              free_slots_neighbor[o].read().mask[r.vc_out] ==
                                  GlobalParams::buffer_depth;

                          bool target_buffer_full =
                              buffer_full_status_tx[o].read().mask[r.vc_out];

                          // Check if atomic flow control is necessary on the
                          // direction out / VC out
                          bool require_atomic_flow_ctrl =
                              routingAlgorithm->requireAtomicFlowCtrl(o,
                                                                      r.vc_out);
                          bool release_and_try_reallocation =
                              ( require_atomic_flow_ctrl && target_buffer_empty) ||
                              (!require_atomic_flow_ctrl && !target_buffer_full);

                          if (release_and_try_reallocation)
                          {
                              LOG << " VC re-allocation: Release reservation"
                                     " on Output[" << existing_r_o << "]["
                                  << existing_r.vc_out << "] made by Input["
                                  << existing_r.input << "]["
                                  << existing_r.vc_in << "]" << endl;

                              reservation_table.release(existing_r,
                                                        existing_r_o);

                              // Try re-allocating
		              int retry_rt_status =
                                  reservation_table.checkReservation(r, o,
                                      blocking_entry);

                              if (retry_rt_status == RT_AVAILABLE)
                              {
                                  reservation_table.reserve(r, o);
                                  LOG << " VC re-allocation: Succeeded to"
                                         " reserve Output[" << o << "]["
                                      << r.vc_out << "] for Input["
                                      << r.input << "]["
                                      << r.vc_in << "]" << endl;
                              }
                          }
                      }
                  }
              }
          }
          start_from_vc[i] = (start_from_vc[i]+1) % vc_nb;
      }

      start_from_port = (start_from_port + 1) % (DIRECTIONS + 2);

      // 2nd phase: Forwarding
      //if (local_id==6) LOG<<"*TX*****local_id="<<local_id<<"__ack_tx[0]= "<<ack_tx[0].read()<<endl;
      for (int i = 0; i < DIRECTIONS + 2; i++) 
      { 
	  vector<ReservationTable::res_t> reservations
              = reservation_table.getReservations(i);

	  if (reservations.size()!=0)
	  {
	      int rnd_idx = rand()%reservations.size();

	      int o      = get<RES_PORT_OUT>(reservations[rnd_idx]);
	      int vc_in  = get<RES_VC_IN>   (reservations[rnd_idx]);
	      int vc_out = get<RES_VC_OUT>  (reservations[rnd_idx]);

	     // LOG<< "found reservation from input= " << i << "_to output= "<<o<<endl;
	      // can happen
	      Flit flit;

	      if (!buffer[i][vc_in].IsEmpty())  
	      {
		  // power contribution already computed in 1st phase
		  //LOG<< "*****TX***Direction= "<<i<< "************"<<endl;
		  //LOG<<"_cl_tx="<<current_level_tx[o]<<"req_tx="<<req_tx[o].read()<<" _ack= "<<ack_tx[o].read()<< endFlit flit = buffer[i][vc].Front();
	          flit = buffer[i][vc_in].Front();

                  int free_slots_available =
                      free_slots_neighbor[o].read().mask[vc_out];
                  bool is_dest_buffer_full =
                      buffer_full_status_tx[o].read().mask[vc_out];
                  bool is_dest_buffer_empty =
                      free_slots_available == GlobalParams::buffer_depth;
                  bool require_atomic_flow_ctrl =
                      routingAlgorithm->requireAtomicFlowCtrl(o, vc_out);

                  // When using the BUFFER_LEVEL selectionStrategy, check that
                  // free_slots and buffer_full_status signals match, except
                  // for DIRECTION_LOCAL
                  // cout << "gid: " << global_id << " o=" << o << " free_slots_available:" << free_slots_available << " buffer_full" << is_dest_buffer_full << endl;
                  sc_assert(o == DIRECTION_LOCAL ||
                            (free_slots_available == 0 &&
                             is_dest_buffer_full == true) ||
                            (free_slots_available > 0 &&
                             is_dest_buffer_full == false));

                  // Atomic Flow Control Forwarding checks
                  bool can_forward_if_atomic_flow_ctrl =
                       !require_atomic_flow_ctrl ||
                      ( require_atomic_flow_ctrl &&
                          // Authorize the forwarding by default if the packet
                          // goes to the local port as it is a 'hacky' port
                        ( (o == DIRECTION_LOCAL) ||
                          // For header flit not going to the local port,
                          // authorize forwarding only if the target buffer is
                          // empty
                          (is_dest_buffer_empty) ||
                          // Wormhole assumption: target VC has already been
                          // allocated for the header, following flits can
                          // thus be freely inserted as long as the targeted
                          // buffer is not full (which is checked afterwards)
                          (flit.flit_type != FLIT_TYPE_HEAD) ) );

                  if ( (current_level_tx[o] == ack_tx[o].read()) &&
                       (can_forward_if_atomic_flow_ctrl) &&
                       (!is_dest_buffer_full) )
                  {
		      // Retrieve context information on routing
                      RouteData rdata(getRouteData(flit, i));

                      // Update the ID of the VC in the current Flit
                      // NOTE: This is necessary as the vc_id field is used by
                      // the rxProcess to put the flit in the correct
                      // destination buffer
                      if (vc_out != vc_in)
                          switchFlitVirtualChannel(buffer[i][vc_in],
                                                   flit, vc_out);

                      // Delegate the forwarding logic (if applicable) to the
                      // routing algorithm, which can modify both the buffer
                      // and current flit and decides if the buffer should be
                      // erased.
                      bool erase_buffer =
                          routingAlgorithm->customForwarding(rdata,
                                                             buffer[i][vc_in],
                                                             flit, o);

                      assert(!buffer[i][vc_in].IsEmpty() &&
                             "Buffer should not be empty");

		      //if (GlobalParams::verbose_mode > VERBOSE_OFF) 
		      LOG << "Input[" << i << "][" << vc_in
                          << "] forwarded to Output[" << o << "]["
                          << vc_out << "], flit: " << flit << endl;

		      flit_tx[o].write(flit);
		      current_level_tx[o] = 1 - current_level_tx[o];
		      req_tx[o].write(current_level_tx[o]);

                      // Do not pop the flit if it wasn't consumed or on the
                      // contrary, pop if it was already consumed
                      if (erase_buffer)
		          buffer[i][vc_in].Pop();

		      if (flit.flit_type == FLIT_TYPE_TAIL)
		      {
			  TReservation r;
			  r.input = i;
			  r.vc_in = vc_in;
			  r.vc_out = vc_out;
			  reservation_table.release(r,o);
		      }

		      /* Power & Stats ------------------------------------------------- */
		      if (o == DIRECTION_HUB) power.r2hLink();
		      else
			  power.r2rLink();

		      power.bufferRouterPop();
		      power.crossBar();

		      if (o == DIRECTION_LOCAL) 
		      {
			  power.networkInterface();
			  LOG << "Consumed flit " << flit << endl;
			  stats.receivedFlit(sc_time_stamp().to_double() / GlobalParams::clock_period_ps, flit);

#ifdef DEBUG_VC_UTILIZATION
                          stats.updateVCReceivedFlits(*this, flit);
#endif // DEBUG_VC_UTILIZATION

			  if (GlobalParams:: max_volume_to_be_drained) 
			  {
			      if (drained_volume >= GlobalParams:: max_volume_to_be_drained)
				  sc_stop();
			      else 
			      {
				  drained_volume++;
				  local_drained++;
			      }
			  }
		      } 
		      else if (i != DIRECTION_LOCAL) // not generated locally
			  routed_flits++;
		      /* End Power & Stats ------------------------------------------------- */
			 //LOG<<"END_OK_cl_tx="<<current_level_tx[o]<<"_req_tx="<<req_tx[o].read()<<" _ack= "<<ack_tx[o].read()<< endl;
		  }
		  else
		  {
		      LOG << " Cannot forward Input[" << i << "][" << vc_in << "] to Output[" << o << "][" << vc_out << "], flit: " << flit << endl;
		      //LOG << " **DEBUG APB: current_level_tx: " << current_level_tx[o] << " ack_tx: " << ack_tx[o].read() << endl;
		      LOG << " **DEBUG buffer_full_status_tx " << buffer_full_status_tx[o].read().mask[vc_out] << endl;
		      LOG << " **DEBUG is_dest_buffer_empty " << is_dest_buffer_empty << endl;

		  	//LOG<<"END_NO_cl_tx="<<current_level_tx[o]<<"_req_tx="<<req_tx[o].read()<<" _ack= "<<ack_tx[o].read()<< endl;
		      /*
		      if (flit.flit_type == FLIT_TYPE_HEAD)
			  reservation_table.release(i,flit.vc_id,o);
			  */
		  }
	      }
	  } // if not reserved 
	 // else LOG<<"we have no reservation for direction "<<i<< endl;
      } // for loop directions

      if ((int)(sc_time_stamp().to_double() / GlobalParams::clock_period_ps)%2==0)
	  reservation_table.updateIndex();
    }   
}

NoP_data Router::getCurrentNoPData()
{
    NoP_data NoP_data;

    for (int j = 0; j < DIRECTIONS; j++) {
        try {
            // FIXME: MAX_VIRTUAL_CHANNELS is probably too much
            for (int vc = 0; vc < MAX_VIRTUAL_CHANNELS; vc++) {
		NoP_data.channel_status_neighbor[j][vc].free_slots = free_slots_neighbor[j].read().mask[vc];
                NoP_data.channel_status_neighbor[j][vc].available  = (reservation_table.isNotReserved(j, vc));
            }
	}
	catch (int e)
	{
	    if (e!=NOT_VALID) assert(false);
	    // Nothing to do if an NOT_VALID direction is caught
	};
    }

    NoP_data.sender_id = (GlobalParams::topology == TOPOLOGY_MULTI_MESH) ?
                          global_id : local_id;

    return NoP_data;
}

void Router::perCycleUpdate()
{
    if (reset.read()) {
	for (int i = 0; i < DIRECTIONS + 1; i++) {
	    TFreeSlots fs;
	    for (int vc=0; vc < getNoC().n_virtual_channels; vc++)
		fs.mask[vc] = buffer[i][vc].GetMaxBufferSize();
	    free_slots[i].write(fs);
        }
    } else {
	power.leakageRouter();
	for (int i = 0; i < DIRECTIONS + 1; i++)
	{
	    for (int vc = 0; vc < getNoC().n_virtual_channels; vc++)
	    {
		power.leakageBufferRouter();
		power.leakageLinkRouter2Router();
	    }
	}

	power.leakageLinkRouter2Hub();
    }
}

vector<int> Router::nextDeltaHops(RouteData rd) {

	if (GlobalParams::topology == TOPOLOGY_MESH)
	{
		cout << "Mesh topologies are not supported for nextDeltaHops() ";
		assert(false);
	}
	// annotate the initial nodes
	int src = rd.src_id;
	int dst = rd.dst_id;

	int current_node = src;
	vector<RouteEntry> direction; // initially is empty
	vector<int> next_hops;

	int sw = GlobalParams::n_delta_tiles/2; //sw: switch number in each stage
	int stg = log2(GlobalParams::n_delta_tiles);
	int c;
	//---From Source to stage 0 (return the sw attached to the source)---
	//Topology omega 
	if (GlobalParams::topology == TOPOLOGY_OMEGA) 	
	{
	if(current_node < (GlobalParams::n_delta_tiles/2))	
		 c = current_node;
	else if(current_node >= (GlobalParams::n_delta_tiles/2))	
		 c = (current_node - (GlobalParams::n_delta_tiles/2));		
	}
	//Other delta topologies: Butterfly and baseline
	else if ((GlobalParams::topology == TOPOLOGY_BUTTERFLY)||(GlobalParams::topology == TOPOLOGY_BASELINE))
	{
		 c =  (current_node >>1);
	}

		Coord temp_coord;
		temp_coord.x = 0;
		temp_coord.y = c;
		int N = coord2Id(temp_coord);

		next_hops.push_back(N);
		current_node = N;
	
	
   //---From stage 0 to Destination---
	int current_stage = 0;

	while (current_stage<stg-1)
	{
		Coord new_coord;
		int y = id2Coord(current_node).y;

		rd.current_id = current_node;
		direction = routingAlgorithm->route(this, rd);

		int bit_to_check = stg - current_stage - 1;

		int bit_checked = (y & (1 << (bit_to_check - 1)))>0 ? 1:0;

		// computes next node coords
		new_coord.x = current_stage + 1;
		if (bit_checked ^ direction[0].first)
			new_coord.y = toggleKthBit(y, bit_to_check);
		else
			new_coord.y = y;

		current_node = coord2Id(new_coord);
		next_hops.push_back(current_node);
		current_stage = id2Coord(current_node).x;
	}

	next_hops.push_back(dst);

	return next_hops;

}

vector<RouteEntry> Router::routingFunction(const RouteData & route_data)
{
	if (GlobalParams::use_winoc)
	{
		// - If the current node C and the destination D are connected to an radiohub, use wireless
		// - If D is not directly connected to a radio hub, wireless
		// communication can still  be used if some intermediate node "I" in the routing
		// path is reachable from current node C.
		// - Since further wired hops will be required from I -> D, a threshold "winoc_dst_hops"
		// can be specified (via command line) to determine the max distance from the intermediate
		// node I and the destination D.
		// - NOTE: default threshold is 0, which means I=D, i.e., we explicitly ask the destination D to be connected to the
		// target radio hub
		if (hasRadioHub(local_id))
		{
			// Check if destination is directly connected to an hub
			if ( hasRadioHub(route_data.dst_id) &&
				 !sameRadioHub(local_id,route_data.dst_id) )
			{
                map<int, int>::iterator it1 = GlobalParams::hub_for_tile.find(route_data.dst_id);
                map<int, int>::iterator it2 = GlobalParams::hub_for_tile.find(route_data.current_id);

                if (connectedHubs(it1->second,it2->second))
                {
                    LOG << "Destination node " << route_data.dst_id << " is directly connected to a reachable RadioHub" << endl;
                    vector<RouteEntry> dirv;
                    dirv.push_back({DIRECTION_HUB, route_data.vc_in});
                    return dirv;
                }
			}
			// let's check whether some node in the route has an acceptable distance to the dst
            if (GlobalParams::winoc_dst_hops>0)
            {
                // TODO: for the moment, just print the set of nexts hops to check everything is ok
                LOG << "NEXT_DELTA_HOPS (from node " << route_data.src_id << " to " << route_data.dst_id << ") >>>> :";
                vector<int> nexthops;
                nexthops = nextDeltaHops(route_data);
                //for (int i=0;i<nexthops.size();i++) cout << "(" << nexthops[i] <<")-->";
                //cout << endl;
                for (int i=1;i<=GlobalParams::winoc_dst_hops;i++)
				{
                	int dest_position = nexthops.size()-1;
                	int candidate_hop = nexthops[dest_position-i];
					if ( hasRadioHub(candidate_hop) && !sameRadioHub(local_id,candidate_hop) ) {
						//LOG << "Checking candidate hop " << candidate_hop << " ... It's OK!" << endl;
						LOG << "Relaying to hub-connected node " << candidate_hop << " to reach destination " << route_data.dst_id << endl;
						vector<RouteEntry> dirv;
						dirv.push_back({DIRECTION_HUB_RELAY+candidate_hop,
                                                                route_data.vc_in});
						return dirv;
					}
					//else
					// LOG << "Checking candidate hop " << candidate_hop << " ... NOT OK" << endl;
				}
            }
		}
	}
	// TODO: fix all the deprecated verbose mode logs
	if (GlobalParams::verbose_mode > VERBOSE_OFF)
		LOG << "Wired routing for dst = " << route_data.dst_id << endl;

	// not wireless direction taken, apply normal routing
	return routingAlgorithm->route(this, route_data);
}

RouteEntry Router::route(const RouteData & route_data)
{
    int target_id = (GlobalParams::topology == TOPOLOGY_MULTI_MESH) ?
                     global_id : local_id;

    if (route_data.dst_id == target_id)
	return {DIRECTION_LOCAL, route_data.vc_in};

    power.routing();
    vector<RouteEntry> candidate_channels = routingFunction(route_data);

    power.selection();
    return selectionFunction(candidate_channels, route_data);
}

void Router::NoP_report() const
{
    NoP_data NoP_tmp;
	LOG << "NoP report: " << endl;

    for (int i = 0; i < DIRECTIONS; i++) {
	NoP_tmp = NoP_data_in[i].read();
	if (NoP_tmp.sender_id != NOT_VALID)
	    cout << NoP_tmp;
    }
}

//---------------------------------------------------------------------------

int Router::NoPScore(const NoP_data & nop_data,
			  const vector<RouteEntry> & nop_channels) const
{
    int score = 0;

    for (unsigned int i = 0; i < nop_channels.size(); i++) {
	int available;
        int dir = nop_channels[i].first;
        int vc  = nop_channels[i].second;

	if (nop_data.channel_status_neighbor[dir][vc].available)
	    available = 1;
	else
	    available = 0;

	int free_slots =
	    nop_data.channel_status_neighbor[dir][vc].free_slots;

	score += available * free_slots;
    }

    return score;
}

RouteEntry Router::selectionFunction(const vector<RouteEntry> & directions,
                                     const RouteData & route_data)
{
    // not so elegant but fast escape ;)
    if (directions.size() == 1)
	return directions[0];

    return selectionStrategy->apply(this, directions, route_data);
}

void Router::configure(const double _warm_up_time,
                       const unsigned int _max_buffer_size,
                       GlobalRoutingTable & grt)
{
    int _id = (GlobalParams::topology == TOPOLOGY_MULTI_MESH) ?
               global_id : local_id;
    stats.configure(getNoC(), _id, _warm_up_time);

    start_from_port = DIRECTION_LOCAL;


    if (grt.isValid())
	routing_table.configure(grt, _id);

    reservation_table.setSize(DIRECTIONS+2);

    for (int i = 0; i < DIRECTIONS + 2; i++)
    {
	for (int vc = 0; vc < getNoC().n_virtual_channels; vc++)
	{
	    buffer[i][vc].SetMaxBufferSize(_max_buffer_size);
	    buffer[i][vc].setLabel(string(name())+"->buffer["+i_to_string(i)+"]");
	}
	start_from_vc[i] = 0;
    }


    if (GlobalParams::topology == TOPOLOGY_MESH)
    {
	int layer =  _id / (GlobalParams::mesh_dim_x * GlobalParams::mesh_dim_y);
	int row   = (_id - (layer * GlobalParams::mesh_dim_x * GlobalParams::mesh_dim_y)) / GlobalParams::mesh_dim_x;
	int col   = (_id - (layer * GlobalParams::mesh_dim_x * GlobalParams::mesh_dim_y)) % GlobalParams::mesh_dim_x;

	for (int vc = 0; vc < getNoC().n_virtual_channels; vc++)
	{
	    if (row == 0)
	      buffer[DIRECTION_NORTH][vc].Disable();
	    if (row == GlobalParams::mesh_dim_y-1)
	      buffer[DIRECTION_SOUTH][vc].Disable();
	    if (col == 0)
	      buffer[DIRECTION_WEST][vc].Disable();
	    if (col == GlobalParams::mesh_dim_x-1)
	      buffer[DIRECTION_EAST][vc].Disable();
            if (layer == 0)
              buffer[DIRECTION_DOWN][vc].Disable();
            if (layer == GlobalParams::mesh_dim_z-1)
              buffer[DIRECTION_UP][vc].Disable();
	}
    }
}

unsigned long Router::getRoutedFlits()
{
    return routed_flits;
}


int Router::reflexDirection(int direction) const
{
    if (direction == DIRECTION_NORTH)
	return DIRECTION_SOUTH;
    if (direction == DIRECTION_EAST)
	return DIRECTION_WEST;
    if (direction == DIRECTION_WEST)
	return DIRECTION_EAST;
    if (direction == DIRECTION_SOUTH)
	return DIRECTION_NORTH;
    if (direction == DIRECTION_UP)
	return DIRECTION_DOWN;
    if (direction == DIRECTION_DOWN)
	return DIRECTION_UP;

    // you shouldn't be here
    assert(false);
    return NOT_VALID;
}

int Router::getNeighborId(int _id, int direction) const
{
    assert(GlobalParams::topology == TOPOLOGY_MESH);

    Coord my_coord = id2Coord(_id); 

    switch (direction) {
    case DIRECTION_NORTH:
	if (my_coord.y == 0)
	    return NOT_VALID;
	my_coord.y--;
	break;
    case DIRECTION_SOUTH:
	if (my_coord.y == GlobalParams::mesh_dim_y - 1)
	    return NOT_VALID;
	my_coord.y++;
	break;
    case DIRECTION_EAST:
	if (my_coord.x == GlobalParams::mesh_dim_x - 1)
	    return NOT_VALID;
	my_coord.x++;
	break;
    case DIRECTION_WEST:
	if (my_coord.x == 0)
	    return NOT_VALID;
	my_coord.x--;
	break;
    case DIRECTION_UP:
	if (my_coord.z == GlobalParams::mesh_dim_z - 1)
	    return NOT_VALID;
	my_coord.z++;
	break;
    case DIRECTION_DOWN:
	if (my_coord.z == 0)
	    return NOT_VALID;
	my_coord.z--;
	break;
    default:
	LOG << "Direction not valid : " << direction;
	assert(false);
    }

    int neighbor_id = coord2Id(my_coord);

    return neighbor_id;
}

bool Router::inCongestion()
{
    for (int i = 0; i < DIRECTIONS; i++) {
        for (int vc = 0; vc < MAX_VIRTUAL_CHANNELS; vc++)
        {
	    if (free_slots_neighbor[i].read().mask[vc] == NOT_VALID) continue;

            int flits = GlobalParams::buffer_depth -
                        free_slots_neighbor[i].read().mask[vc];
            if (flits > (int) (GlobalParams::buffer_depth * GlobalParams::dyad_threshold))
                return true;
        }
    }

    return false;
}

void Router::ShowBuffersStats(std::ostream & out)
{
  for (int i=0; i<DIRECTIONS+2; i++)
      for (int vc = 0; vc < getNoC().n_virtual_channels; vc++)
	    buffer[i][vc].ShowStats(out);
}


bool Router::connectedHubs(int src_hub, int dst_hub) {
    vector<int> &first = GlobalParams::hub_configuration[src_hub].txChannels;
    vector<int> &second = GlobalParams::hub_configuration[dst_hub].rxChannels;

    vector<int> intersection;

    for (unsigned int i = 0; i < first.size(); i++) {
        for (unsigned int j = 0; j < second.size(); j++) {
            if (first[i] == second[j])
                intersection.push_back(first[i]);
        }
    }

    if (intersection.size() == 0)
        return false;
    else
        return true;
}

int Router::computeMinimumManhattanDistance(const vector<int>& vlinks) const
{
    std::map<int, unsigned> vlink_id_dist;
    Coord src_coord = parent_noc.getCoordFromGlobalId(global_id);
    // Concatenate the vlink_id and the distance in a common data-structure
    for (auto& vlink_id : vlinks) {
        Coord vlink_coord = parent_noc.getCoordFromGlobalId(vlink_id);
        // Manhattan Distance
        unsigned dist = std::abs(src_coord.x - vlink_coord.x) +
                        std::abs(src_coord.y - vlink_coord.y);
        vlink_id_dist.insert({vlink_id, dist});
    }
    // Find the vertical link with the minimum distance
    auto it_min = min_element(vlink_id_dist.begin(),
                              vlink_id_dist.end(), 
                              [](const auto& lhs, const auto& rhs) {
                                  return lhs.second < rhs.second;
                              });
    sc_assert(it_min != vlink_id_dist.end());
    return it_min->first;
}

void Router::configureUpwardLinks(IdRangeRegister& upward_link_iic,
                                  map<IdRange, vector<int>>&
                                      id_ranges_to_vlink_ids,
                                  map<IdRange, vector<pair<int, int>>>&
                                      hidrange_link_selection)
{
    // The goal here is to select a vertical link per upward destination.
    // To this end, entry_pair is a map between a range of hierarchical IDs
    // and the set of vertical links leading to these hIDs.
    for (auto& entry_pair : id_ranges_to_vlink_ids)
    {
        int sel_vlink_id;
        int custom_vlink_id = -1;

        const IdRange& curr_target_hid = entry_pair.first;
        int router_id = global_id;
        
        auto it = hidrange_link_selection.find(curr_target_hid);

        // Determine if a vertical link was (manually) selected for the current
        // router
        if (it != hidrange_link_selection.end()) {
            const vector<pair<int, int>>& t = it->second;
            auto it_pair = find_if(t.begin(), t.end(),
                                   [&](const pair<int, int>& src_to_link) {
                                       return src_to_link.first == router_id;
                                   });
            custom_vlink_id = (it_pair != t.end()) ? it_pair->second : -1;
        }

        bool custom_mapping = custom_vlink_id != -1;

        if (custom_mapping)
            sel_vlink_id = custom_vlink_id;
        else
            sel_vlink_id = computeMinimumManhattanDistance(entry_pair.second);
        selected_upward_links[entry_pair.first] = sel_vlink_id;

        // Just for the logs
        Coord c = parent_noc.getCoordFromGlobalId(sel_vlink_id);
        if (custom_mapping) cout << "Custom ";
        else                cout << "Nearest ";
        cout << "VLink Up: " << parent_noc.name() << " Router gid:"
             << global_id << " lid:" << local_id << " target_gids:["
             << entry_pair.first.minId << "-" << entry_pair.first.maxId << "] "
             << "upward_link: gid:" << sel_vlink_id << " lid:"
             << parent_noc.getLocalId(c.x, c.y, c.z) << endl;
    }
}

void Router::configureDownwardLink(const vector<int>& vlink_pos,
                                   const vector<pair<int, int>>& link_selected)
{
    int router_id = global_id;
    auto it = find_if(link_selected.begin(), link_selected.end(),
                      [&](const pair<int, int>& src_to_link) {
                          return src_to_link.first == router_id;
                      });

    bool custom_mapping = it != link_selected.end();

    selected_downward_link =
        (custom_mapping) ? it->second :
                           computeMinimumManhattanDistance(vlink_pos);

    // Just for the logs
    if (custom_mapping) cout << "Custom ";
    else                cout << "Nearest ";
    Coord cdl = parent_noc.getCoordFromGlobalId(selected_downward_link);
    cout << "VLink Down: " << parent_noc.name() << " Router gid:"
         << global_id << " lid:" << local_id << " downward_link: gid:"
         << selected_downward_link << " lid:"
         << parent_noc.getLocalId(cdl.x, cdl.y, cdl.z) << endl;
}

void Router::configureIntraLink(const vector<pair<int, int>>& link_selected)
{
    auto it = find_if(link_selected.begin(), link_selected.end(),
                      [&](const pair<int, int>& src_to_link) {
                          return src_to_link.first == global_id;
                      });
    // In sparse intra-stack mode, every router must have a selected TSV.
    sc_assert(it != link_selected.end() &&
              "Missing intra-stack TSV selection for router");
    selected_intra_link = it->second;

    Coord c = parent_noc.getCoordFromGlobalId(selected_intra_link);
    cout << "VLink Intra: " << parent_noc.name() << " Router gid:"
         << global_id << " lid:" << local_id << " intra_link: gid:"
         << selected_intra_link << " lid:"
         << parent_noc.getLocalId(c.x, c.y, c.z) << endl;
}

void Router::switchFlitVirtualChannel(Buffer & buffer,
                                      Flit   & flit,
                                      int      vc_out)
{
    flit.vc_id = vc_out;
    buffer.UpdateFront(flit);
}


bool Router::incomingDownUpTransition(int dest_gid) const
{
    if (noc_down)
    {
        const NoC& nc = *noc_down;
        const IdRangeRegister& reg = nc.getHierarchicalSubMeshesIdRange();
        //cout << nc.getGlobalIdRange().minId << " " << nc.getGlobalIdRange().maxId << endl;
        // Destination is local
        if (nc.getGlobalIdRange().isIncluded(dest_gid)) return true;
        // Sub-meshes available
        if (reg.size() > 0) {
            auto dest_id_range = reg.find(dest_gid);
            if (dest_id_range != reg.end())
                return true;
        }
    }
    return false;
}

