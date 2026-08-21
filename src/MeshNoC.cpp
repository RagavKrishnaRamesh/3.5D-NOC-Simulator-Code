/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * This file contains the implementation of the Network-on-Chip Mesh Topology
 * Modified by CEA LIST, Contributor(s): Davy Million (davy.million@cea.fr)
 */

#include "MeshNoC.h"

using namespace std;

void MeshNoC::buildMesh()
{
    // Initialize signals
    const int dim_x = mesh_dim_x;
    const int dim_y = mesh_dim_y;
    const int dim_z = mesh_dim_z;

    // Dummy signals initialization (TBufferFullStatus and TFreeSlots already
    // have a default constructor)
    dummy_req = 0;
    dummy_ack = 0;
    dummy_flit.write({0});

    // Create the mesh as a matrix of tiles
    for (int z = 0; z < dim_z; z++) {
        for (int y = 0; y < dim_y; y++) {
            for (int x = 0; x < dim_x; x++) {
                // Compute the Ids
                // [x][y][z]
                int tile_id       = getLocalId(x, y, z);
                // [x+1][y][z]
                int tile_adj_x_id = getLocalId(x + 1, y, z);
                // [x][y+1][z]
                int tile_adj_y_id = getLocalId(x, y + 1, z);
                // [x][y][z+1]
                int tile_adj_z_id = getLocalId(x, y, z + 1);
                // [x][y][z-1]
                int tile_prev_z_id = (z > 0) ? getLocalId(x, y, z - 1) :
                                     NOT_VALID;

                // NOTE: When using topologies != TOPOLOGY_MULTI_MESH,
                // global_id is the same as local_id because the gid_offset
                // default initialization is 0
                int global_id = tile_id + gid_offset;

                // Create the single Tile with a proper name
                char tile_name[64];
                sprintf(tile_name, "%s:Tile[%02d][%02d][%02d]_(G:%d-L:%d)",
                        name(), x, y, z, global_id, tile_id);
                t[tile_id] = make_unique<Tile>(tile_name, tile_id,
                                               *this, global_id);

                // Tell to the router its coordinates
                t[tile_id]->r->configure(GlobalParams::stats_warm_up_time,
                                         GlobalParams::buffer_depth,
                                         grtable);

                t[tile_id]->r->power.configureRouter(GlobalParams::flit_size,
                                                     GlobalParams::buffer_depth,
                                                     GlobalParams::flit_size,
                                                     string(GlobalParams::routing_algorithm),
                                                     "default");

                // Check for traffic table availability
   		if (GlobalParams::traffic_distribution == TRAFFIC_TABLE_BASED) {
                    t[tile_id]->pe->traffic_table = &gttable; // Needed to choose destination
                    int src_id = (GlobalParams::topology == TOPOLOGY_MULTI_MESH) ?
                        t[tile_id]->pe->global_id : t[tile_id]->pe->local_id;
                    t[tile_id]->pe->never_transmit =
                        (gttable.occurrencesAsSource(src_id) == 0);
                }
                else {
                    t[tile_id]->pe->never_transmit = false;
                }

                // Map clock and reset
                t[tile_id]->clock(clock);
                t[tile_id]->reset(reset);

                // Map Rx signals
                t[tile_id]->req_rx[DIRECTION_NORTH]  (req[tile_id].south);
                t[tile_id]->flit_rx[DIRECTION_NORTH] (flit[tile_id].south);
                t[tile_id]->ack_rx[DIRECTION_NORTH]  (ack[tile_id].north);
                t[tile_id]->buffer_full_status_rx[DIRECTION_NORTH] (buffer_full_status[tile_id].north);

                t[tile_id]->req_rx[DIRECTION_EAST]  (req[tile_adj_x_id].west);
                t[tile_id]->flit_rx[DIRECTION_EAST] (flit[tile_adj_x_id].west);
                t[tile_id]->ack_rx[DIRECTION_EAST]  (ack[tile_adj_x_id].east);
                t[tile_id]->buffer_full_status_rx[DIRECTION_EAST] (buffer_full_status[tile_adj_x_id].east);

                t[tile_id]->req_rx[DIRECTION_SOUTH]  (req[tile_adj_y_id].north);
                t[tile_id]->flit_rx[DIRECTION_SOUTH] (flit[tile_adj_y_id].north);
                t[tile_id]->ack_rx[DIRECTION_SOUTH]  (ack[tile_adj_y_id].south);
                t[tile_id]->buffer_full_status_rx[DIRECTION_SOUTH] (buffer_full_status[tile_adj_y_id].south);

                t[tile_id]->req_rx[DIRECTION_WEST]  (req[tile_id].east);
                t[tile_id]->flit_rx[DIRECTION_WEST] (flit[tile_id].east);
                t[tile_id]->ack_rx[DIRECTION_WEST]  (ack[tile_id].west);
                t[tile_id]->buffer_full_status_rx[DIRECTION_WEST] (buffer_full_status[tile_id].west);

                // Generates vertical links if:
                // i) Up: the tile is not on the highest tier
                bool wire_z_up   = z < (dim_z - 1);
                // ii) Down: the tile is not on the first tier
                bool wire_z_down = z > 0;

                // In multi-mesh mode, a 3D chiplet can define sparse intra-
                // stack TSVs. In this case, bind vertical links only on the
                // selected TSV local ids.
                if (GlobalParams::topology == TOPOLOGY_MULTI_MESH &&
                    dim_z > 1 && !intra_links_placement.empty())
                {
                    bool curr_has_tsv = hasIntraVerticalLinkPlacement(tile_id);
                    bool up_has_tsv =
                        wire_z_up &&
                        hasIntraVerticalLinkPlacement(tile_adj_z_id);
                    bool down_has_tsv =
                        wire_z_down &&
                        hasIntraVerticalLinkPlacement(tile_prev_z_id);

                    wire_z_up = wire_z_up &&
                                curr_has_tsv &&
                                up_has_tsv;
                    wire_z_down = wire_z_down &&
                                  curr_has_tsv &&
                                  down_has_tsv;
                }
                // When the condition is not met, either wire the port to
                // dummy signals or leave the port unbound so it can be wired
                // to other meshes (TOPOLOGY_MULTI_MESH case)

                if (wire_z_up) {
                    t[tile_id]->req_rx[DIRECTION_UP]  (req[tile_adj_z_id].down);
                    t[tile_id]->flit_rx[DIRECTION_UP] (flit[tile_adj_z_id].down);
                    t[tile_id]->ack_rx[DIRECTION_UP]  (ack[tile_adj_z_id].up);
                    t[tile_id]->buffer_full_status_rx[DIRECTION_UP] (buffer_full_status[tile_adj_z_id].up);
                } else if (!late_binding_down_link_rx[tile_id]) {
                    t[tile_id]->req_rx[DIRECTION_UP]                (dummy_req);
                    t[tile_id]->flit_rx[DIRECTION_UP]               (dummy_flit);
                    t[tile_id]->ack_rx[DIRECTION_UP]                (dummy_ack);
                    t[tile_id]->buffer_full_status_rx[DIRECTION_UP] (dummy_buffer_status);
                } else {
                    LOG << "Leaving port req_rx[DIRECTION_UP] of tile "
                        << tile_id << " unbound from " << name() << endl;
                }

                // A down tier exists and there is a downward link
                if (wire_z_down) {
                    t[tile_id]->req_rx[DIRECTION_DOWN]  (req[tile_id].up);
                    t[tile_id]->flit_rx[DIRECTION_DOWN] (flit[tile_id].up);
                    t[tile_id]->ack_rx[DIRECTION_DOWN]  (ack[tile_id].down);
                    t[tile_id]->buffer_full_status_rx[DIRECTION_DOWN] (buffer_full_status[tile_id].down);
                } else if (!late_binding_up_link_rx[tile_id]) {
                    t[tile_id]->req_rx[DIRECTION_DOWN]                (dummy_req);
                    t[tile_id]->flit_rx[DIRECTION_DOWN]               (dummy_flit);
                    t[tile_id]->ack_rx[DIRECTION_DOWN]                (dummy_ack);
                    t[tile_id]->buffer_full_status_rx[DIRECTION_DOWN] (dummy_buffer_status);
                } else {
                    LOG << "Leaving port req_rx[DIRECTION_DOWN] of tile "
                        << tile_id << " unbound from " << name() << endl;
                }

                // Map Tx signals
                t[tile_id]->req_tx[DIRECTION_NORTH]  (req[tile_id].north);
                t[tile_id]->flit_tx[DIRECTION_NORTH] (flit[tile_id].north);
                t[tile_id]->ack_tx[DIRECTION_NORTH]  (ack[tile_id].south);
                t[tile_id]->buffer_full_status_tx[DIRECTION_NORTH] (buffer_full_status[tile_id].south);

                t[tile_id]->req_tx[DIRECTION_EAST]  (req[tile_adj_x_id].east);
                t[tile_id]->flit_tx[DIRECTION_EAST] (flit[tile_adj_x_id].east);
                t[tile_id]->ack_tx[DIRECTION_EAST]  (ack[tile_adj_x_id].west);
                t[tile_id]->buffer_full_status_tx[DIRECTION_EAST] (buffer_full_status[tile_adj_x_id].west);

                t[tile_id]->req_tx[DIRECTION_SOUTH]  (req[tile_adj_y_id].south);
                t[tile_id]->flit_tx[DIRECTION_SOUTH] (flit[tile_adj_y_id].south);
                t[tile_id]->ack_tx[DIRECTION_SOUTH]  (ack[tile_adj_y_id].north);
                t[tile_id]->buffer_full_status_tx[DIRECTION_SOUTH] (buffer_full_status[tile_adj_y_id].north);

                t[tile_id]->req_tx[DIRECTION_WEST]  (req[tile_id].west);
                t[tile_id]->flit_tx[DIRECTION_WEST] (flit[tile_id].west);
                t[tile_id]->ack_tx[DIRECTION_WEST]  (ack[tile_id].east);
                t[tile_id]->buffer_full_status_tx[DIRECTION_WEST] (buffer_full_status[tile_id].east);

                if (wire_z_up) {
                    t[tile_id]->req_tx[DIRECTION_UP]  (req[tile_adj_z_id].up); // req to up
                    t[tile_id]->flit_tx[DIRECTION_UP] (flit[tile_adj_z_id].up);
                    t[tile_id]->ack_tx[DIRECTION_UP]  (ack[tile_adj_z_id].down);
                    t[tile_id]->buffer_full_status_tx[DIRECTION_UP] (buffer_full_status[tile_adj_z_id].down);
                } else if (!late_binding_up_link_tx[tile_id]) {
                    t[tile_id]->req_tx[DIRECTION_UP]                (dummy_req); // req to up
                    t[tile_id]->flit_tx[DIRECTION_UP]               (dummy_flit);
                    t[tile_id]->ack_tx[DIRECTION_UP]                (dummy_ack);
                    t[tile_id]->buffer_full_status_tx[DIRECTION_UP] (dummy_buffer_status);
                } else {
                    LOG << "Leaving port req_tx[DIRECTION_UP] of tile "
                        << tile_id << " unbound from " << name() << endl;
                }

                if (wire_z_down) {
                    t[tile_id]->req_tx[DIRECTION_DOWN]  (req[tile_id].down);
                    t[tile_id]->flit_tx[DIRECTION_DOWN] (flit[tile_id].down);
                    t[tile_id]->ack_tx[DIRECTION_DOWN]  (ack[tile_id].up);
                    t[tile_id]->buffer_full_status_tx[DIRECTION_DOWN] (buffer_full_status[tile_id].up);
                } else if (!late_binding_down_link_tx[tile_id]) {
                    t[tile_id]->req_tx[DIRECTION_DOWN]                (dummy_req);
                    t[tile_id]->flit_tx[DIRECTION_DOWN]               (dummy_flit);
                    t[tile_id]->ack_tx[DIRECTION_DOWN]                (dummy_ack);
                    t[tile_id]->buffer_full_status_tx[DIRECTION_DOWN] (dummy_buffer_status);
                } else {
                    LOG << "Leaving port req_tx[DIRECTION_DOWN] of tile "
                        << tile_id << " unbound from " << name() << endl;
                }

                // FIXME(Davy): for now, let's put aside the hub functionality
                // TODO: check if hub signal is always required
                // signals/port when tile receives(rx) from hub
                t[tile_id]->hub_req_rx(req[tile_id].from_hub);
                t[tile_id]->hub_flit_rx(flit[tile_id].from_hub);
                t[tile_id]->hub_ack_rx(ack[tile_id].to_hub);
                t[tile_id]->hub_buffer_full_status_rx(buffer_full_status[tile_id].to_hub);

                // signals/port when tile transmits(tx) to hub
                t[tile_id]->hub_req_tx(req[tile_id].to_hub); // 7, sc_out
                t[tile_id]->hub_flit_tx(flit[tile_id].to_hub);
                t[tile_id]->hub_ack_tx(ack[tile_id].from_hub);
                t[tile_id]->hub_buffer_full_status_tx(buffer_full_status[tile_id].from_hub);

                // TODO: Review port index. Connect each Hub to all its Channels 
                map<int, int>::iterator it = GlobalParams::hub_for_tile.find(tile_id);
                if (it != GlobalParams::hub_for_tile.end())
                {
                    int hub_id = GlobalParams::hub_for_tile[tile_id];

                    // The next time that the same HUB is considered, the next
                    // port will be connected
                    int port = hub_connected_ports[hub_id]++;

                    hub[hub_id]->tile2port_mapping[t[tile_id]->local_id] = port;

                    hub[hub_id]->req_rx[port](req[tile_id].to_hub);
                    hub[hub_id]->flit_rx[port](flit[tile_id].to_hub);
                    hub[hub_id]->ack_rx[port](ack[tile_id].from_hub);
                    hub[hub_id]->buffer_full_status_rx[port](buffer_full_status[tile_id].from_hub);

                    hub[hub_id]->flit_tx[port](flit[tile_id].from_hub);
                    hub[hub_id]->req_tx[port](req[tile_id].from_hub);
                    hub[hub_id]->ack_tx[port](ack[tile_id].to_hub);
                    hub[hub_id]->buffer_full_status_tx[port](buffer_full_status[tile_id].to_hub);
                }

                // Map buffer level signals (analogy with req_tx/rx port mapping)
                t[tile_id]->free_slots[DIRECTION_NORTH] (free_slots[tile_id].north);
                t[tile_id]->free_slots[DIRECTION_EAST]  (free_slots[tile_adj_x_id].east);
                t[tile_id]->free_slots[DIRECTION_SOUTH] (free_slots[tile_adj_y_id].south);
                t[tile_id]->free_slots[DIRECTION_WEST]  (free_slots[tile_id].west);
                if (wire_z_up)
                    t[tile_id]->free_slots[DIRECTION_UP] (free_slots[tile_adj_z_id].up);
                else if (!late_binding_down_link_rx[tile_id])
                    t[tile_id]->free_slots[DIRECTION_UP] (dummy_free_slots);
                else
                    LOG << "Leaving port free_slots_tx[DIRECTION_UP] of tile "
                        << tile_id << " unbound from " << name() << endl;
                if (wire_z_down)
                    t[tile_id]->free_slots[DIRECTION_DOWN] (free_slots[tile_id].down);
                else if (!late_binding_up_link_rx[tile_id])
                    t[tile_id]->free_slots[DIRECTION_DOWN] (dummy_free_slots);
                else
                    LOG << "Leaving port free_slots_tx[DIRECTION_DOWN] of tile "
                        << tile_id << " unbound from " << name() << endl;

                t[tile_id]->free_slots_neighbor[DIRECTION_NORTH] (free_slots[tile_id].south);
                t[tile_id]->free_slots_neighbor[DIRECTION_EAST]  (free_slots[tile_adj_x_id].west);
                t[tile_id]->free_slots_neighbor[DIRECTION_SOUTH] (free_slots[tile_adj_y_id].north);
                t[tile_id]->free_slots_neighbor[DIRECTION_WEST]  (free_slots[tile_id].east);
                if (wire_z_up)
                    t[tile_id]->free_slots_neighbor[DIRECTION_UP] (free_slots[tile_adj_z_id].down);
                else if (!late_binding_up_link_tx[tile_id])
                    t[tile_id]->free_slots_neighbor[DIRECTION_UP] (dummy_free_slots);
                else
                    LOG << "Leaving port free_slots_neighbor[DIRECTION_UP] of tile "
                          << tile_id << " unbound from " << name() << endl;
                if (wire_z_down)
                    t[tile_id]->free_slots_neighbor[DIRECTION_DOWN] (free_slots[tile_id].up);
                else if (!late_binding_down_link_tx[tile_id])
                    t[tile_id]->free_slots_neighbor[DIRECTION_DOWN] (dummy_free_slots);
                else
                    LOG << "Leaving port free_slots_neighbor[DIRECTION_DOWN] of tile "
                          << tile_id << " unbound from " << name() << endl;

                // NoP 
                t[tile_id]->NoP_data_out[DIRECTION_NORTH] (nop_data[tile_id].north);
                t[tile_id]->NoP_data_out[DIRECTION_EAST]  (nop_data[tile_adj_x_id].east);
                t[tile_id]->NoP_data_out[DIRECTION_SOUTH] (nop_data[tile_adj_y_id].south);
                t[tile_id]->NoP_data_out[DIRECTION_WEST]  (nop_data[tile_id].west);
                if (wire_z_up)
                    t[tile_id]->NoP_data_out[DIRECTION_UP] (nop_data[tile_adj_z_id].up);
                else if (!late_binding_up_link_tx[tile_id])
                    t[tile_id]->NoP_data_out[DIRECTION_UP] (dummy_nop_data);
                else
                    LOG << "Leaving port NoP_data_tx[DIRECTION_UP] of tile "
                          << tile_id << " unbound from " << name() << endl;
                if (wire_z_down)
                    t[tile_id]->NoP_data_out[DIRECTION_DOWN] (nop_data[tile_id].down);
                else if (!late_binding_down_link_tx[tile_id])
                    t[tile_id]->NoP_data_out[DIRECTION_DOWN] (dummy_nop_data);
                else
                    LOG << "Leaving port NoP_data_tx[DIRECTION_DOWN] of tile "
                          << tile_id << " unbound from " << name() << endl;

                t[tile_id]->NoP_data_in[DIRECTION_NORTH] (nop_data[tile_id].south);
                t[tile_id]->NoP_data_in[DIRECTION_EAST]  (nop_data[tile_adj_x_id].west);
                t[tile_id]->NoP_data_in[DIRECTION_SOUTH] (nop_data[tile_adj_y_id].north);
                t[tile_id]->NoP_data_in[DIRECTION_WEST]  (nop_data[tile_id].east);
                if (wire_z_up)
                    t[tile_id]->NoP_data_in[DIRECTION_UP] (nop_data[tile_adj_z_id].down);
                else if (!late_binding_down_link_rx[tile_id])
                    t[tile_id]->NoP_data_in[DIRECTION_UP] (dummy_nop_data);
                else
                    LOG << "Leaving port NoP_data_rx[DIRECTION_UP] of tile "
                          << tile_id << " unbound from " << name() << endl;
                if (wire_z_down)
                    t[tile_id]->NoP_data_in[DIRECTION_DOWN] (nop_data[tile_id].up);
                else if (!late_binding_up_link_rx[tile_id])
                    t[tile_id]->NoP_data_in[DIRECTION_DOWN] (dummy_nop_data);
                else
                    LOG << "Leaving port NoP_data_rx[DIRECTION_DOWN] of tile "
                          << tile_id << " unbound from " << name() << endl;
            }
	}
    }

    // dummy NoP_data structure
    NoP_data tmp_NoP;

    tmp_NoP.sender_id = NOT_VALID;

    for (int i = 0; i < DIRECTIONS; i++) {
        for (int vc = 0; vc < MAX_VIRTUAL_CHANNELS; vc++) {
            tmp_NoP.channel_status_neighbor[i][vc].free_slots = NOT_VALID;
            tmp_NoP.channel_status_neighbor[i][vc].available = false;
        }
    }

    TFreeSlots tmp_fs;
    for (int vc = 0;
             vc < n_virtual_channels;
           ++vc)
        tmp_fs.mask[vc] = NOT_VALID;

    // Clear signals for borderline nodes
    for (int x = 0; x <= dim_x; x++) {
        for (int y = 0; y <= dim_y; y++) {
            // [x][y][0]
            int mesh_z_null_id = getLocalId(x, y, 0);
            // [x][y][dim_z]
            int mesh_z_max_id  = getLocalId(x, y, dim_z);

            if (!late_binding_up_link_rx[mesh_z_null_id])
                ack[mesh_z_null_id].down = 0;

            if (!late_binding_down_link_tx[mesh_z_null_id]) {
                free_slots[mesh_z_null_id].down.write(tmp_fs);
                nop_data[mesh_z_null_id].down.write(tmp_NoP);
            }

            if (!late_binding_down_link_rx[mesh_z_max_id])
                ack[mesh_z_max_id].up = 0;

            if (!late_binding_up_link_tx[mesh_z_max_id]) {
                free_slots[mesh_z_max_id].up.write(tmp_fs);
                nop_data[mesh_z_max_id].up.write(tmp_NoP);
            }
        }
    }

    for (int z = 0; z <= dim_z; z++) {
        for (int x = 0; x <= dim_x; x++) {
            // [x][0][z]
            int mesh_y_null_id = getLocalId(x, 0, z);
            // [x][dim_y][z]
            int mesh_y_max_id  = getLocalId(x, dim_y, z);

            req[mesh_y_null_id].south = 0;
            ack[mesh_y_null_id].north = 0;
            req[mesh_y_max_id].north  = 0;
            ack[mesh_y_max_id].south  = 0;

            free_slots[mesh_y_null_id].south.write(tmp_fs);
            free_slots[mesh_y_max_id].north.write(tmp_fs);

            nop_data[mesh_y_null_id].south.write(tmp_NoP);
            nop_data[mesh_y_max_id].north.write(tmp_NoP);
        }
    }

    for (int z = 0; z <= dim_z; z++) {
        for (int y = 0; y <= dim_y; y++) {
            // [0][y][z]
            int mesh_x_null_id = getLocalId(0, y, z);
            // [dim_x][y][z]
            int mesh_x_max_id  = getLocalId(dim_x, y, z);

            req[mesh_x_null_id].east = 0;
            ack[mesh_x_null_id].west = 0;
            req[mesh_x_max_id].west  = 0;
            ack[mesh_x_max_id].east  = 0;

            free_slots[mesh_x_null_id].east.write(tmp_fs);
            free_slots[mesh_x_max_id].west.write(tmp_fs);

            nop_data[mesh_x_null_id].east.write(tmp_NoP);
            nop_data[mesh_x_max_id].west.write(tmp_NoP);
        }
    }

    // Update intra-chiplet global Id range
    int last_local_id = getLocalId(mesh_dim_x-1, mesh_dim_y-1, mesh_dim_z-1);
    mesh_gid_range.minId = t[0]->global_id;
    mesh_gid_range.maxId = t[last_local_id]->global_id;
}

Tile* MeshNoC::searchNode(const int id) const
{
    assert(id < mesh_dim_x * mesh_dim_y * mesh_dim_z);
    return t[id].get();
}

