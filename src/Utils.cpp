/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#include "Utils.h"
#include "MeshNoC.h"

Coord id2Coord(int id, const string& mesh_id)
{
    assert(GlobalParams::topology == TOPOLOGY_MULTI_MESH);

    auto it = GlobalParams::mesh_component_config.find(mesh_id);
    if (it == GlobalParams::mesh_component_config.end())
        assert("Mesh not found");
    const MeshComponentConfig& mesh_config = it->second;

    Coord coord;
    assert(mesh_config.nc != nullptr);
    id = id - mesh_config.nc->getGlobalIdOffset();
    coord.z =  id / (mesh_config.dim_x * mesh_config.dim_y);
    coord.y = (id - (coord.z * mesh_config.dim_x * mesh_config.dim_y)) / mesh_config.dim_x;
    coord.x = (id - (coord.z * mesh_config.dim_x * mesh_config.dim_y)) % mesh_config.dim_x;

    assert(coord.x < mesh_config.dim_x);
    assert(coord.y < mesh_config.dim_y);
    assert(coord.z < mesh_config.dim_z);
    return coord;
}

int coord2Id(const Coord & coord, const string& mesh_id)
{
    assert(GlobalParams::topology == TOPOLOGY_MULTI_MESH);

    auto it = GlobalParams::mesh_component_config.find(mesh_id);
    if (it == GlobalParams::mesh_component_config.end())
        assert("Mesh not found");
    const MeshComponentConfig& mesh_config = it->second;

    assert(coord.x < mesh_config.dim_x && coord.y < mesh_config.dim_y &&
           coord.z < mesh_config.dim_z && "illegal mesh coordinnates");

    assert(mesh_config.nc != nullptr);
    assert(mesh_config.nc->getGlobalIdOffset() > -1 && "uninitialized id_offset");

    int id = coord.z * (mesh_config.dim_x * mesh_config.dim_y) +
             coord.y *  mesh_config.dim_x + coord.x + mesh_config.nc->getGlobalIdOffset();
    return id;
}

