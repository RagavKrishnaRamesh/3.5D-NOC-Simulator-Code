/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * Modified by CEA LIST, Contributor(s): Davy Million (davy.million@cea.fr)
 */

#ifndef __NOXIMMULTINOC_H__
#define __NOXIMMULTINOC_H__

#include <stack>
#include <systemc.h>
#include <memory>
#include <random>
#include <functional>
#include "Tile.h"
#include "GlobalRoutingTable.h"
#include "GlobalTrafficTable.h"
#include "Hub.h"
#include "Channel.h"
#include "TokenRing.h"
#include "MeshNoC.h"

using namespace std;

struct MultiNoC : public MeshNoC
{
    // Constructor
    MultiNoC(const string& name, const MeshComponentConfig& config)
       : MeshNoC(name, config, /*gid_offset=*/0)
    {
        buildMultiMesh();
    }

    // Returns the configuration information of a given Mesh based on its id
    static MeshComponentConfig& retrieveMeshConfig(size_t mesh_id,
                                                   string& mesh_name)
    {
        auto it = find_if(GlobalParams::mesh_component_config.begin(),
                          GlobalParams::mesh_component_config.end(),
                          [&](const pair<string,
                                         MeshComponentConfig> & t) -> bool {
                              return t.second.mesh_id == mesh_id;
                          });
        assert(it != GlobalParams::mesh_component_config.end() &&
               "Illegal mesh_id");
        mesh_name = it->first;
        return it->second;
    }

    // Returns the configuration information of a given Mesh based on its name
    static MeshComponentConfig& retrieveMeshConfig(const string& mesh_name)
    {
        auto it = find_if(GlobalParams::mesh_component_config.begin(),
                          GlobalParams::mesh_component_config.end(),
                          [&](const pair<string,
                                         MeshComponentConfig> & t) -> bool {
                              return t.first == mesh_name;
                          });
        assert(it != GlobalParams::mesh_component_config.end() &&
               "Illegal mesh_name");
        return it->second;
    }

    void checkRoutingRequirement() const override {
        for (auto it_mesh  = GlobalParams::mesh_component_config.begin();
                  it_mesh != GlobalParams::mesh_component_config.end();
                ++it_mesh)
        {
            MeshNoC& nc = *it_mesh->second.nc;
            for (auto it_tile = nc.begin(); it_tile != nc.end(); it_tile++)
                (*it_tile)->r->checkRoutingRequirement();
        }
    }

    void evaluateOnNoCs(const function<void(const MeshNoC&)>& noc_functor) const
    {
        for (auto it_mesh  = GlobalParams::mesh_component_config.begin();
                  it_mesh != GlobalParams::mesh_component_config.end();
                ++it_mesh)
        {
            MeshNoC& nc = *it_mesh->second.nc;
            noc_functor(nc);
        }
    }

    void evaluateOnTiles(const function<void(const Tile&)>& tile_functor) const
    {
        auto noc_functor = [&](const MeshNoC& nc) -> void {
            for (auto it_tile = nc.begin(); it_tile != nc.end(); it_tile++)
                tile_functor(**it_tile);
        };
        evaluateOnNoCs(noc_functor);
    }

    size_t getNumberOfTiles() const override {
        size_t nb_tile = 0;
        evaluateOnNoCs([&nb_tile](const MeshNoC& noc) -> void {
            nb_tile += noc.mesh_dim_x * noc.mesh_dim_y * noc.mesh_dim_z;
        });
        return nb_tile;
    }

    virtual Tile *searchGlobalNode(const int gid) const override {
        for (auto it_mesh  = GlobalParams::mesh_component_config.begin();
                  it_mesh != GlobalParams::mesh_component_config.end();
                ++it_mesh)
        {
            MeshNoC& nc = *it_mesh->second.nc;
            int gid_offset = nc.getGlobalIdOffset();
            int lid = gid - gid_offset;
            if (lid >= 0 && lid < nc.mesh_dim_x * nc.mesh_dim_y * nc.mesh_dim_z)
                return nc.t[lid].get();
        }

        return nullptr;
    }

private:
    // Adds an Upward/a Downward Vertical Link between tile src and tile dst
    // from different NoCs.
    // NOTE: When building the NoC, the ports must have been left unbound.
    // Otherwise, SystemC will report an error when launching the simulation.
    void addVerticalLinkUp  (Tile& src, Tile& dst);
    void addVerticalLinkDown(Tile& src, Tile& dst);
    void buildMultiMesh();
};


#endif

