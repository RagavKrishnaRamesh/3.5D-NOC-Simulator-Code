/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * This file contains the implementation of the Multi Network-on-Chip Topology
 *
 * Modified by CEA LIST, Contributor(s): Davy Million (davy.million@cea.fr)
 */

#include "MultiNoC.h"

using namespace std;

void MultiNoC::addVerticalLinkUp(Tile& src, Tile& dst)
{
    const NoC& dst_nc = dst.getNoC();
    // Connect TX and RX port from an upward link to the signal on the same Id
    // as the destination, in the same manner it is done in buildMesh().
    int        dst_id = dst.local_id;

    LOG << "Linking (upward) src tile " << src.local_id
        << " from mesh " << src.getNoC().name()
        << " to tile " << dst.local_id << " from mesh " << dst_nc.name()
        << endl;

    // TX signals
    src.req_tx[DIRECTION_UP]  (dst_nc.req[dst_id].up);
    src.flit_tx[DIRECTION_UP] (dst_nc.flit[dst_id].up);
    src.ack_tx[DIRECTION_UP]  (dst_nc.ack[dst_id].down);
    src.buffer_full_status_tx[DIRECTION_UP] (dst_nc.buffer_full_status[dst_id].down);
    // RX signals
    dst.req_rx[DIRECTION_DOWN]  (dst_nc.req[dst_id].up);
    dst.flit_rx[DIRECTION_DOWN] (dst_nc.flit[dst_id].up);
    dst.ack_rx[DIRECTION_DOWN]  (dst_nc.ack[dst_id].down);
    dst.buffer_full_status_rx[DIRECTION_DOWN] (dst_nc.buffer_full_status[dst_id].down);
    // NoP
    src.NoP_data_out[DIRECTION_UP]  (dst_nc.nop_data[dst_id].up);
    dst.NoP_data_in[DIRECTION_DOWN] (dst_nc.nop_data[dst_id].up);
    // free_slots
    src.free_slots_neighbor[DIRECTION_UP] (dst_nc.free_slots[dst_id].down);
    dst.free_slots[DIRECTION_DOWN]        (dst_nc.free_slots[dst_id].down);

    // Update the source and destination flags
    src.r->has_upward_link = true;
    dst.r->is_reached_by_upward_link = true;

    // Retrieve the number of VCs in the chiplet up
    MeshComponentConfig& dst_mesh_config =
        retrieveMeshConfig(dst.getNoC().name());
    src.r->nb_vcout_up = dst_mesh_config.n_virtual_channels;
}

void MultiNoC::addVerticalLinkDown(Tile& src,
                                   Tile& dst)
{
    const NoC& src_nc = src.getNoC();
    // Connect TX and RX port from a downward link to the signal on the same Id
    // as the source, in the same manner it is done in buildMesh().
    int        src_id  = src.local_id;

    LOG << "Linking (downward) src tile " << src.local_id
        << " from mesh " << src.getNoC().name()
        << " to tile " << dst.local_id << " from mesh " << dst.getNoC().name()
        << endl;

    // TX signals
    src.req_tx[DIRECTION_DOWN]  (src_nc.req[src_id].down);
    src.flit_tx[DIRECTION_DOWN] (src_nc.flit[src_id].down);
    src.ack_tx[DIRECTION_DOWN]  (src_nc.ack[src_id].up);
    src.buffer_full_status_tx[DIRECTION_DOWN] (src_nc.buffer_full_status[src_id].up);
    // RX signals
    dst.req_rx[DIRECTION_UP]  (src_nc.req[src_id].down);
    dst.flit_rx[DIRECTION_UP] (src_nc.flit[src_id].down);
    dst.ack_rx[DIRECTION_UP]  (src_nc.ack[src_id].up);
    dst.buffer_full_status_rx[DIRECTION_UP] (src_nc.buffer_full_status[src_id].up);
    // NoP
    src.NoP_data_out[DIRECTION_DOWN] (src_nc.nop_data[src_id].down);
    dst.NoP_data_in[DIRECTION_UP]    (src_nc.nop_data[src_id].down);
    // free_slots
    src.free_slots_neighbor[DIRECTION_DOWN] (src_nc.free_slots[src_id].up);
    dst.free_slots[DIRECTION_UP]            (src_nc.free_slots[src_id].up);

    // Update the destination flag
    dst.r->is_reached_by_downward_link = true;

    // Retrieve the number of VCs in the chiplet down
    MeshComponentConfig& dst_mesh_config =
        retrieveMeshConfig(dst.getNoC().name());
    src.r->nb_vcout_down = dst_mesh_config.n_virtual_channels;
    src.r->noc_down = &dst.getNoC();
}

struct MultiNoCBuilder
{
    MultiNoCBuilder(const string & name,
                    int dim_size) :
        name(name), dim_size(dim_size) {}
    const string name;
    const int dim_size;
    set<MultiNoCBuilder*> sub_nocs;
    int gid_offset = -1;
};

void MultiNoC::buildMultiMesh()
{
    // Helper Data-structure to Pre-allocate the Global Ids
    map<string, unique_ptr<MultiNoCBuilder>> multi_noc_builder_components;

    // (1) Global Ids Pre-allocation: allocate a global Id to any tile in the multi-
    // mesh topology. The Ids are allocated in a depth-first manner using DFS
    // on a mesh tree. Each node in this tree is a mesh and two nodes a, b are
    // linked together iff there is an upward link between them.
    for (auto& mesh_id_config : GlobalParams::mesh_component_config)
    {
        // Retrieve Id, the source mesh and its corresponding configuration
        const string& src_mesh_id = mesh_id_config.first;
        const MeshComponentConfig& src_mesh_config = mesh_id_config.second;
        // Create a new NoC entry with the NoC information
        multi_noc_builder_components.emplace(
            src_mesh_id,
            make_unique<MultiNoCBuilder>(
                src_mesh_id,
                src_mesh_config.dim_x * src_mesh_config.dim_y *
                src_mesh_config.dim_z
        ));
    }

    for (auto& mesh_id_config : GlobalParams::mesh_component_config)
    {
        // Retrieve Id, the source mesh and its corresponding configuration
        const string& src_mesh_id = mesh_id_config.first;
        const MeshComponentConfig& src_mesh_config = mesh_id_config.second;
        MultiNoCBuilder* src_mesh = multi_noc_builder_components[src_mesh_id].get();

        // Iterate over any couple of <destination mesh, upward_links>,
        // starting in the current mesh
        for (auto& dst_up_links : src_mesh_config.upward_links_placement)
        {
            // Retrieve the destination mesh and the coordinates of the upward
            // links leading to this mesh
            const string& dst_mesh_id = dst_up_links.first;
            MultiNoCBuilder* dst_mesh = multi_noc_builder_components[dst_mesh_id].get();
            src_mesh->sub_nocs.insert(dst_mesh);
        }
    }

    // DFS tree traversal, compute the gid_offset of each NoC
    stack<MultiNoCBuilder*> pre_b;
    vector<MultiNoCBuilder*> visited_nodes;
    int gid_offset = 0;
    MultiNoCBuilder* base_b = multi_noc_builder_components[name()].get();
    pre_b.push(base_b);

    while (!pre_b.empty()) {
        MultiNoCBuilder* curr_b = pre_b.top();
        pre_b.pop();
        // Cycle detection logic
        if (find(visited_nodes.begin(), visited_nodes.end(), curr_b) !=
            visited_nodes.end())
            assert(false && "NoC visited twice: cycle detected in the "
                            "Multi-NoC Topology");
        visited_nodes.push_back(curr_b);
        // Pre-order Visit
        curr_b->gid_offset = gid_offset;
        gid_offset += curr_b->dim_size;
        for (auto& sub_noc: curr_b->sub_nocs)
            pre_b.push(sub_noc);
    }

    // (2) Using Global Id offsets, build each mesh components independently
    // Whole NoC Instanciation
    map<string, MeshNoC*> mesh_components;
    // FIXME: change this if we want to move to unique_ptr / shared_ptr
    MeshComponentConfig& base_config = retrieveMeshConfig(name());
    mesh_components[name()] = base_config.nc = this;
    for (auto& mesh_id_config : GlobalParams::mesh_component_config)
    {
        const string& mesh_name = mesh_id_config.first;
        MeshComponentConfig& mesh_config = mesh_id_config.second;

        // Base mesh was already built
        if (mesh_name == name()) continue;

        // Instanciate the new mesh with the configuration parsed
        MeshNoC* sub_mesh =
            new MeshNoC(mesh_name.c_str(),
                        mesh_config,
                        multi_noc_builder_components[mesh_name]->gid_offset);

        // Forward clock and reset signals to the sub-mesh
        sub_mesh->clock(clock);
        sub_mesh->reset(reset);

        // Add the mesh components to the list of meshes and update the NoC
        // attribute of the mesh configuration to point to the current NoC
        // address
        mesh_components[mesh_name] = mesh_config.nc = sub_mesh;
    }

    // (3) Create the upward/downward links linking meshes together
    // Iterate over any mesh components in the multi-mesh topology
    for (auto& mesh_id_config : GlobalParams::mesh_component_config)
    {
        // Retrieve Id, the source mesh and its corresponding configuration
        const string& src_mesh_id = mesh_id_config.first;
        MeshNoC* src_mesh = mesh_components[src_mesh_id];
        const MeshComponentConfig& src_mesh_config = mesh_id_config.second;

        // Iterate over any couple of <destination mesh, upward_links>,
        // starting in the current mesh
        for (auto& dst_up_links : src_mesh_config.upward_links_placement)
        {
            // Retrieve the destination mesh and the coordinates of the upward
            // links leading to this mesh
            const string& dst_mesh_id = dst_up_links.first;
            MeshNoC* dst_mesh = mesh_components[dst_mesh_id];
            const vector<pair<int,int>>& up_links = dst_up_links.second;

            // Iterate over any vertical upward link leaving the mesh
            for (auto& link : up_links) {
                // Local source Id in mesh source
                int link_src_id = link.first;
                // Local destination Id in destination mesh
                int link_dst_id = link.second;
                // Retrieve the tiles pointed by the local Ids
                Tile * const src_tile = src_mesh->searchNode(link_src_id);
                Tile * const dst_tile = dst_mesh->searchNode(link_dst_id);
                // Check correctness
                assert(src_tile != nullptr && dst_tile != nullptr &&
                       "Invalid source and destination tile");
                // Connect the two tiles together with an upward link
                addVerticalLinkUp(*src_tile, *dst_tile);
                // Insertion of the dst_mesh as a child of src_mesh
                // NOTE: The Set data-structure ensures unicity of the
                // insertion
                src_mesh->sub_meshes.insert(dst_mesh);
            }
        }

        // Iterate over any couple of <destination mesh, downward_links>,
        // starting in the current mesh
        for (auto& dst_down_links : src_mesh_config.downward_links_placement)
        {
            // Retrieve the destination mesh and the coordinates of the
            // downward links leading to this mesh
            const string& dst_mesh_id = dst_down_links.first;
            MeshNoC* dst_mesh = mesh_components[dst_mesh_id];
            const vector<pair<int,int>>& down_links = dst_down_links.second;
            // Iterate over any vertical downward link leaving the mesh
            for (auto& link : down_links) {
                // Local source Id in mesh source
                int link_src_id = link.first;
                // Local destination Id in destination mesh
                int link_dst_id = link.second;
                // Retrieve the tiles pointed by the local Ids
                Tile* const src_tile = src_mesh->searchNode(link_src_id);
                Tile* const dst_tile = dst_mesh->searchNode(link_dst_id);
                // Check correctness
                assert(src_tile != nullptr && dst_tile != nullptr &&
                       "Invalid source and destination tile");
                // Connect the two tiles together with a downward link
                addVerticalLinkDown(*src_tile, *dst_tile);
            }
        }
    }

    // (4) Ids Finalization using DFS post-order
    // This pass computes the hierarchical IdRange of each nodes based on the
    // values of their sub-NoCs.
    stack<MeshNoC*> pre;
    stack<MeshNoC*> post;
    MeshNoC* base = mesh_components[name()];
    pre.push(base);

    while (!pre.empty()) {
        MeshNoC* curr_nc = pre.top();
        pre.pop();
        post.push(curr_nc);
        for (auto& sub_mesh: curr_nc->sub_meshes)
            pre.push(sub_mesh);
    }

    while (!post.empty()) {
        MeshNoC* curr_nc = post.top();
        post.pop();
        // DFS Post-order Visit
        curr_nc->finalizeHierarchicalGlobalIDs();
    }

    // (5) Compute, for each mesh, the "lookup-table" mapping a given range
    // of hierarchical global Ids of a given sub-mesh [min(ids: tree_sub_mesh),
    // max(ids: tree_sub_mesh)] to the list of upward links leading to this sub
    // -mesh.
    //   ------------                  ------------
    //  | sub-mesh A |                | sub-mesh B |
    //  |  [x2,x_m]  |                |  [x3,x_j]  |
    //   ------------x                x------------ 
    //                \Up_A      Up_B/
    //                 x------------x 
    //   hierar_A_gid= | sub-mesh C | hierar_B_gid=[x3, x_j]
    //   [x2, x_m]     |  [x1,x_n]  |
    //                  ------------x
    //                               \ Up_C
    //  hierar_C_gid=[min(x1,x2,x3),  x------------
    //    max(x_m,x_n,x_j)]           |   mesh 0   |
    //                                 ------------
    //
    for (auto& mesh_id_config : GlobalParams::mesh_component_config)
    {
        const string& src_mesh_id = mesh_id_config.first;
        MeshNoC* src_mesh = mesh_components[src_mesh_id];
        const MeshComponentConfig& src_mesh_config = mesh_id_config.second;

        // Upward Links placement
        for (auto& up_link : src_mesh_config.upward_links_placement) {
            for (auto& link : up_link.second) {
                int src = link.first;
                // Search with the local id
                Tile* src_tile = src_mesh->searchNode(src);
                int src_gid = src_tile->global_id;
                // child mesh
                auto gid_range = mesh_components[up_link.first]->hierarchical_gid_range;
                // Complete the list of upward links leading to the sub-mesh
                src_mesh->upward_links_placement[gid_range].push_back(src_gid);
            }
        }

        // Upward Links selection
        for (auto& up_link_sel : src_mesh_config.upward_links_selection) {
            for (auto& src_dst : up_link_sel.second) {
                int src  = src_dst.first;
                int link = src_dst.second;
                // Search with the local id
                Tile* src_tile = src_mesh->searchNode(src);
                int src_gid = src_tile->global_id;
                Tile* link_tile = src_mesh->searchNode(link);
                int link_gid = link_tile->global_id;
                // child mesh
                auto gid_range = mesh_components[up_link_sel.first]->hierarchical_gid_range;
                // Complete the list of prefered links made by the user
                src_mesh->upward_links_selection[gid_range].push_back(
                    make_pair(src_gid, link_gid)
                );
            }
        }

        // Downward Links placement
        for (auto& down_link : src_mesh_config.downward_links_placement) {
            for (auto& link : down_link.second) {
                int src = link.first;
                Tile* src_tile = src_mesh->searchNode(src);
                int src_gid = src_tile->global_id;
                // ...
                src_mesh->downward_links_placement.push_back(src_gid);
            }
        }

        // Downward Links selection
        for (auto& down_link_sel : src_mesh_config.downward_links_selection)
        {
            for (auto& src_dst : down_link_sel.second)
            {
                int src  = src_dst.first;
                int link = src_dst.second;
                Tile* src_tile = src_mesh->searchNode(src);
                int src_gid = src_tile->global_id;
                Tile* link_tile = src_mesh->searchNode(link);
                int link_gid = link_tile->global_id;

                src_mesh->downward_links_selection.push_back(
                    make_pair(src_gid, link_gid)
                );
            }
        }

        // Intra-stack links selection
        for (auto& src_dst : src_mesh_config.intra_links_selection)
        {
            int src  = src_dst.first;
            int link = src_dst.second;

            Tile* src_tile = src_mesh->searchNode(src);
            int src_gid = src_tile->global_id;
            Tile* link_tile = src_mesh->searchNode(link);
            int link_gid = link_tile->global_id;

            src_mesh->intra_links_selection.push_back(
                make_pair(src_gid, link_gid)
            );
        }
    }

    // (6) Configure the routers to set the selected (or the nearest) vertical
    // Upward/Downward link position
    for (auto& mesh_id_nc : mesh_components)
    {
        sc_assert(mesh_id_nc.second != nullptr);
        MeshNoC& nc = *mesh_id_nc.second;
        // Compute hierarchical ranges
        IdRangeRegister& hierarchical_ranges = nc.hierar_sub_meshes_id_range;
        // Mapping between a range of Ids destination and the set of upward
        // vertical link ids reaching that destination
        //map<IdRange, vector<int>>& upward_links = nc.upward_links_placement;
        // Set of Ids, each representing a downward vertical link
        //vector<int>& downward_links = nc.downward_links;

        for (int y = 0; y < nc.mesh_dim_y; y++) {
            for (int x = 0; x < nc.mesh_dim_x; x++)
            {
                if (!nc.upward_links_placement.empty()) {
                    int tile_id_zmax =
                        nc.getLocalId(x, y, nc.mesh_dim_z - 1);
                    Router& r = *nc.t[tile_id_zmax]->r;
                    r.configureUpwardLinks(hierarchical_ranges,
                                           nc.upward_links_placement,
                                           nc.upward_links_selection);
                }
                if (!nc.downward_links_placement.empty()) {
                    int z_start = 0;
                    int z_end = 1;
                    if (!nc.intra_links_selection.empty()) {
                        z_end = nc.mesh_dim_z;
                    }
                    for (int z = z_start; z < z_end; z++) {
                        int tile_id = nc.getLocalId(x, y, z);
                        Router& r = *nc.t[tile_id]->r;
                        r.configureDownwardLink(nc.downward_links_placement,
                                                nc.downward_links_selection);
                    }
                }
                if (!nc.intra_links_selection.empty()) {
                    for (int z = 0; z < nc.mesh_dim_z; z++) {
                        int tile_id = nc.getLocalId(x, y, z);
                        Router& r = *nc.t[tile_id]->r;
                        r.configureIntraLink(nc.intra_links_selection);
                    }
                }
            }
        }
    }
}

