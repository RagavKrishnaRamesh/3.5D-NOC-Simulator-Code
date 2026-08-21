/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * Modified by CEA LIST, Contributor(s): Davy Million (davy.million@cea.fr)
 */

#ifndef __NOXIMMESHNOC_H__
#define __NOXIMMESHNOC_H__

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
#include "NoC.h"

using namespace std;

struct MeshNoC : public NoC
{
    friend class MultiNoC;

    using iterator       = decltype(t)::iterator;
    using const_iterator = decltype(t)::const_iterator;

    typedef MeshNoC SC_CURRENT_USER_MODULE;

    // Standalone Constructor
    MeshNoC(const string& name, int mesh_dim_x, int mesh_dim_y, int mesh_dim_z,
            int n_virtual_channels) :
        MeshNoC(name, mesh_dim_x, mesh_dim_y, mesh_dim_z,
                n_virtual_channels, /*gid_offset=*/0, /*noc_id=*/0)
    {
        sc_assert(GlobalParams::topology != TOPOLOGY_MULTI_MESH);
        initializeLateBindings();
        buildMesh();
    }

    // Multi-NoC Constructor
    MeshNoC(const string& name, const MeshComponentConfig& config,
            int gid_offset)
        : MeshNoC(name, config.dim_x, config.dim_y, config.dim_z,
                  config.n_virtual_channels, gid_offset, config.mesh_id)
    {
        sc_assert(GlobalParams::topology == TOPOLOGY_MULTI_MESH);
        // Check which ports must be left unbound for a late initialization
        // NOTE: This is necessary as SystemC does not allow to re-bind ports
        // during elaboration.
        configureIntraVerticalLinks(config);
        checkPortsToLeaveUnbound(config);
        buildMesh();
    }

    // Returns the range of Global Ids of the current Mesh
    const IdRange& getGlobalIdRange() const override {
        return mesh_gid_range;
    }

    // Returns the hierarchical range of Global Ids of each Sub-mesh
    const IdRangeRegister& getHierarchicalSubMeshesIdRange() const override {
        return hierar_sub_meshes_id_range;
    }

    // Returns the list of NoC names of the system
    static vector<string> retrieveNoCsNames()
    {
        vector<string> noc_names;

        transform(GlobalParams::mesh_component_config.begin(),
                  GlobalParams::mesh_component_config.end(),
                  back_inserter(noc_names),
                  [](map<string, MeshComponentConfig>::value_type const& p) {
                      return p.first;
                  });
        return noc_names;
    }

    // Search Local Node using the Id and if found, returns the Tile address.
    // Returns nullptr otherwise.
    virtual Tile *searchNode(const int id) const;
    virtual Tile *searchGlobalNode(const int gid) const override {
        return searchNode(gid);
    }

    // Returns the mesh global Id offset
    int getGlobalIdOffset() const { return gid_offset; }

    // Tile iterator begin()
    iterator begin() override {
        return t.begin();
    }

    // Tile iterator end()
    iterator end() override {
        return t.end();
    }

    // Tile const_iterator begin()
    const_iterator begin() const override {
        return t.begin();
    }

    // Tile const_iterator end()
    const_iterator end() const override {
        return t.end();
    }

    // Returns the local id based on the (x, y, z) coordinates
    int getLocalId(int x, int y, int z) const override {
        int layer_id = y * mesh_dim_x + x;
        return z * (mesh_dim_y * mesh_dim_x) + layer_id;
    }

    // Returns the global id based on the (x, y, z) coordinates
    int getGlobalId(int x, int y, int z) const override {
        return getLocalId(x, y, z) + gid_offset;
    }

    // Get the local (x,y,z) coordinates from a tile/router/pe local id
    Coord getCoordFromLocalId(int local_id) const override {
        return getCoord(local_id, false);
    }

    // Get the local (x,y,z) coordinates from a tile/router/pe global id
    Coord getCoordFromGlobalId(int global_id) const override {
        return getCoord(global_id, true);
    }

    // Convert a local Id in a given NoC to a Global Id
    static int convertLocalToGlobalId(int local_id, const string& noc_name) {
        sc_assert(GlobalParams::topology == TOPOLOGY_MULTI_MESH);
        auto it = find_if(GlobalParams::mesh_component_config.begin(),
                          GlobalParams::mesh_component_config.end(),
                          [&](const pair<string,
                                         MeshComponentConfig> & t) -> bool {
                              return t.first == noc_name;
                          });
        sc_assert(it != GlobalParams::mesh_component_config.end() &&
                  "Illegal NoC name");
        sc_assert(it->second.nc != nullptr && "NoC not set in config");
        MeshNoC& noc = *it->second.nc;
        int noc_dimension = noc.mesh_dim_x * noc.mesh_dim_y * noc.mesh_dim_z;
        sc_assert(local_id < noc_dimension && "Illegal local_id");
        return local_id + it->second.nc->gid_offset;
    }

    virtual void checkRoutingRequirement() const override {
        for (auto tile_it = begin(); tile_it != end(); tile_it++)
            (*tile_it)->getRouter().checkRoutingRequirement();
    }

    unsigned getId() const override {
        return noc_id;
    }

    // Mesh size dimensions
    const int mesh_dim_x;
    const int mesh_dim_y;
    const int mesh_dim_z;

private:
    // Private Constructor
    MeshNoC(const string& name, int mesh_dim_x, int mesh_dim_y, int mesh_dim_z,
            int n_virtual_channels, int gid_offset, int noc_id)
        : NoC(name.c_str(), 
              /*nb_signals=*/(mesh_dim_x+1)*(mesh_dim_y+1)*(mesh_dim_z+1),
              /*nb_tiles=*/mesh_dim_x*mesh_dim_y*mesh_dim_z,
              n_virtual_channels),
          mesh_dim_x(mesh_dim_x), mesh_dim_y(mesh_dim_y), mesh_dim_z(mesh_dim_z),
          gid_offset(gid_offset), noc_id(noc_id) {}

    // Range of global Ids [min, max] of the current mesh
    IdRange mesh_gid_range;
    // Range of global Ids [min, max] in the sub-tree rooted by this mesh
    // (current mesh + sub-meshes)
    IdRange hierarchical_gid_range;
    // Set of pair of upward links associated to each IdRange
    map<IdRange, vector<int>> upward_links_placement;
    map<IdRange, vector<pair<int, int>>> upward_links_selection;
    // Global Ids of the mesh outbound downward links
    vector<int> downward_links_placement;
    vector<pair<int, int>> downward_links_selection;
    // Intra-stack vertical links placement (local ids) and selection
    // (global ids) used by 3D meshes.
    set<int> intra_links_placement;
    vector<pair<int, int>> intra_links_selection;
    // Lookup a given Id in the hierarchical ranges of sub-mesh Ids
    IdRangeRegister hierar_sub_meshes_id_range;

    // Local Ids of ports that will be bind afterwards to upward/downward link
    // to/from other meshes
    // NOTE: SystemC does not allow to unbind signals
    vector<int> late_binding_up_link_tx;
    vector<int> late_binding_up_link_rx;
    vector<int> late_binding_down_link_tx;
    vector<int> late_binding_down_link_rx;

    // Set of sub-meshes
    set<MeshNoC*> sub_meshes;

    // Global offset value of the local Ids in the current Mesh
    const int gid_offset;
    // NoC Id
    const unsigned noc_id;

    // Retrieve local (x, y, z) coordinates from a tile/router/pe local or
    // global ids
    Coord getCoord(int id, bool is_global) const
    {
        Coord coord;
        if (is_global) {
            assert(gid_offset > -1);
            id = id - gid_offset;
        }
        sc_assert(id < mesh_dim_x * mesh_dim_y * mesh_dim_z &&
                  "Invalid Id");
        coord.z =  id / (mesh_dim_x * mesh_dim_y);
        coord.y = (id - (coord.z * mesh_dim_x * mesh_dim_y)) / mesh_dim_x;
        coord.x = (id - (coord.z * mesh_dim_x * mesh_dim_y)) % mesh_dim_x;
        return coord;
    }

    void checkPortsToLeaveUnbound(const MeshComponentConfig& config)
    {
        initializeLateBindings();

        for (auto& elem_map : config.upward_links_placement)
            for (auto& elem_vec : elem_map.second)
                late_binding_up_link_tx[elem_vec.first] = 1;

        for (auto& elem_map : config.downward_links_placement)
            for (auto& elem_vec : elem_map.second)
                late_binding_down_link_tx[elem_vec.first] = 1;

        for (auto& elem : GlobalParams::mesh_component_config) {
            if (elem.first == name()) continue;
            const MeshComponentConfig & elem_config
                = elem.second;
            for (auto& elem_map : elem_config.upward_links_placement)
                if (elem_map.first == name())
                    for (auto& elem_vec : elem_map.second)
                        late_binding_up_link_rx[elem_vec.second] = 1;

            for (auto& elem_map : elem_config.downward_links_placement) {
                if (elem_map.first == name())
                    for (auto& elem_vec : elem_map.second)
                        late_binding_down_link_rx[elem_vec.second] = 1;
            }
        }
    }

    void initializeLateBindings() {
        // Reserve enough spaces for any tile
        // FIXME: full size is quite overkill because we are only listing
        // outbound links, which can be placed only on the border of the mesh
        late_binding_up_link_tx.resize(nb_signals, 0);
        late_binding_up_link_rx.resize(nb_signals, 0);
        late_binding_down_link_tx.resize(nb_signals, 0);
        late_binding_down_link_rx.resize(nb_signals, 0);
    }

    void configureIntraVerticalLinks(const MeshComponentConfig& config) {
        intra_links_placement.clear();
        for (auto& lid : config.intra_links_placement)
            intra_links_placement.insert(lid);
        // Allow defining only the selection mapping and infer the set of TSV
        // local ids from selected destinations.
        if (intra_links_placement.empty()) {
            for (auto& src_link : config.intra_links_selection)
                intra_links_placement.insert(src_link.second);
        }
    }

    bool hasIntraVerticalLinkPlacement(int local_id) const {
        return intra_links_placement.find(local_id) !=
               intra_links_placement.end();
    }

    void finalizeHierarchicalGlobalIDs() {
        // NOTE: This method should be called in a post order traversal (i.e.
        // child nodes must have been evaluated before the parent)
        hierarchical_gid_range.minId = mesh_gid_range.minId;
        int max = mesh_gid_range.maxId;
        for (auto& sub_mesh : sub_meshes) {
            if (sub_mesh->hierarchical_gid_range.maxId > max)
                max = sub_mesh->hierarchical_gid_range.maxId;
        }
        hierarchical_gid_range.maxId = max;

        for (auto& sub_mesh: sub_meshes) {
            int min = sub_mesh->hierarchical_gid_range.minId;
            int max = sub_mesh->hierarchical_gid_range.maxId;
            hierar_sub_meshes_id_range.insert({min, max});
        }
        // FIXME: put a finalized flag to True
    }

    void buildMesh();
};


#endif

