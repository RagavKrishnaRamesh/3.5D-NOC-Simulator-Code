/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#include "RoutingMultiNoC.h"

static int routeXYZ(const Coord & curr, const Coord & dest)
{
    if (dest.x > curr.x)
        return DIRECTION_EAST;
    if (dest.x < curr.x)
        return DIRECTION_WEST;
    if (dest.y > curr.y)
        return DIRECTION_SOUTH;
    if (dest.y < curr.y)
        return DIRECTION_NORTH;
    if (dest.z > curr.z)
        return DIRECTION_UP;
    if (dest.z < curr.z)
        return DIRECTION_DOWN;

    return DIRECTION_LOCAL;
}

vector<RouteEntry> RoutingMultiNoC::route(Router* router, 
                                          const RouteData& routeData)
{
    assert(router != nullptr && "Invalid arguments");
    const NoC& curr_nc = router->getNoC();

    // Retrieve current and destination global Ids
    int curr_gid = routeData.current_id;
    int dest_gid = routeData.dst_id;
    // Retrieve local mesh coordinates of the current router
    Coord coord_curr = curr_nc.getCoordFromGlobalId(curr_gid);
    // Retrieve the vertical direction
    int vdir = getVerticalDirection(*router, dest_gid);
    // Default initialization
    int direction_out = DIRECTION_LOCAL;
    // Vector of routing decisions performed
    vector<RouteEntry> routing_decisions;

    // Routing logic
    //
    bool is_dest_local = !routeData.routing_towards_vlink;
    // The flit is in the destination mesh/chiplet
    if (is_dest_local) {
        Coord coord_dest = curr_nc.getCoordFromGlobalId(dest_gid);
        // Intra-stack routing with sparse TSV mapping:
        // if crossing layers locally, first reach the selected TSV on the
        // current layer, then elevate.
        if (coord_curr.z != coord_dest.z && router->intra_link() > -1) {
            Coord coord_vlink =
                curr_nc.getCoordFromGlobalId(router->intra_link());
            sc_assert(coord_vlink.z == coord_curr.z &&
                      "Intra TSV selection must stay on current layer");
            if (coord_curr.x == coord_vlink.x &&
                coord_curr.y == coord_vlink.y) {
                direction_out = vdir;
            } else {
                direction_out = routeXYZ(coord_curr, coord_vlink);
            }
        } else {
            // Legacy behavior (fully connected Z links)
            direction_out = routeXYZ(coord_curr, coord_dest);
        }
    }
    else // Non-local destination
    {
        int vdest = routeData.vlink_dest;
        sc_assert(vdest > -1);

        // The flit reached its local destination which contains an upward or a
        // downward link
        if (routeData.current_id == vdest) {
            direction_out = vdir;
        }
        // Continue to route locally towards the nearest vertical link
        else {
            direction_out = routeXYZ(coord_curr,
                                     curr_nc.getCoordFromGlobalId(vdest));
        }
    }

    // Output VC Selection logic
    //
    vector<int> vcs_out;
    vcs_out.reserve(MAX_VIRTUAL_CHANNELS);
    int extra_vc_config = -1;

    const VCData vc_data {
        .curr_id = curr_gid,
        .dest_id = dest_gid,
        .dir_in  = routeData.dir_in,
        .dir_out = direction_out,
        .ver_dir = vdir,
        .vc_in   = routeData.vc_in
    };

    if (always_reassign_src_vc || router->global_id != routeData.src_id)
        assignVCOut(*router, vc_data, vcs_out, extra_vc_config);

    if (vcs_out.empty())
        // Stay in the same VC by default
        vcs_out.push_back(routeData.vc_in);

    // Delegate the choice of selecting the VC to the selection strategy
    // (performed after routing)
    if (route_using_selection_strategy) {
        for (auto& vc_out : vcs_out)
            routing_decisions.emplace_back(direction_out, vc_out);
    // Or call the specific method of the routingAlgorithm to output only one
    // decision
    } else {
        int vc_out = selectVCOut(vc_data, extra_vc_config, vcs_out);
        routing_decisions.emplace_back(direction_out, vc_out);
    }

    return routing_decisions;
}

bool RoutingMultiNoC::isDestinationLocal(const NoC& nc,
                                         int dest_gid) const
{
    // Check if the destination Id is included in the idRange (not
    // hierarchical) of the current mesh
    return nc.getGlobalIdRange().isIncluded(dest_gid);
}

int RoutingMultiNoC::getVerticalDirection(const Router& router,
                                          int dest_gid) const
{
    const NoC& nc = router.getNoC();
    const IdRangeRegister& reg = nc.getHierarchicalSubMeshesIdRange();
    // Destination is local
    if (isDestinationLocal(nc, dest_gid)) {
        Coord curr = nc.getCoordFromGlobalId(router.global_id);
        Coord dest = nc.getCoordFromGlobalId(dest_gid);
        if (dest.z > curr.z) return DIRECTION_UP;
        if (dest.z < curr.z) return DIRECTION_DOWN;
        return DIRECTION_LOCAL;
    }
    // Sub-meshes available
    if (reg.size() > 0) {
        auto dest_id_range = reg.find(dest_gid);
        if (dest_id_range != reg.end())
            return DIRECTION_UP;
    }
    // Current mesh has no sub-mesh, i.e. no UP destination OR no sub-mesh
    // contains the destination id
    return DIRECTION_DOWN;
}

int RoutingMultiNoC::selectVerticalLink(const Router& router,
                                              int     vdir,
                                              int     dest_gid) const
{
    assert((vdir == DIRECTION_UP || vdir == DIRECTION_DOWN) &&
           "Invalid vertical direction input");
    const NoC& nc = router.getNoC();

    if (vdir == DIRECTION_UP) {
        // Retrieve the set of IdRanges covered by any sub-mesh
        const IdRangeRegister& reg = nc.getHierarchicalSubMeshesIdRange();
        assert(reg.size() > 0);
        // Find the destination IdRange among the sub-meshes. The destination
        // IdRange is the IdRange that contains the destination id.
        auto dest_id_range = reg.find(dest_gid);
        assert(dest_id_range != reg.end() && "Destination IdRange not found");
        const map<IdRange, int> upward_links_lookup = router.upward_links();
        // Lookup for the nearest Vertical Link targeting the destination
        // IdRange.
        auto nearest_vlink_up = upward_links_lookup.find(dest_id_range->second);
        assert(nearest_vlink_up != upward_links_lookup.end() &&
               "Destination IdRange not found when looking up for the nearest "
               "upward vertical link");
        return nearest_vlink_up->second;
    }
    // vdir == DIRECTION_DOWN
    return router.downward_link();
}

