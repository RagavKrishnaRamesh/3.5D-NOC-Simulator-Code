/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#include "Routing_DEFT.h"

RoutingAlgorithmsRegister Routing_DEFT::routingAlgorithmsRegister(
    "DEFT", getInstance()
);

Routing_DEFT* Routing_DEFT::routing_DEFT = 0;

Routing_DEFT* Routing_DEFT::getInstance() {
    if (routing_DEFT == 0)
        routing_DEFT = new Routing_DEFT();
    return routing_DEFT;
}

void Routing_DEFT::runtimeInit(const NoC& noc)
{
    size_t tile_nb = noc.getNumberOfTiles();
    // VCs allocation round-robin arbiter
    // NOTE: This arbiter will only be used to arbitrate packets going to the
    // to the DIRECTION_LOCAL.
    rr_vc_allocation.resize(tile_nb, 0);

    // VCs switching round-robin arbiter
    rr_vc_switching.resize(tile_nb);
    for (auto& flag : rr_vc_switching)
        flag.resize(DIRECTIONS+2, 0);
}

void Routing_DEFT::allocateVC(const Router& router, Packet& packet)
{
    // Current router is the source
    sc_assert(router.global_id == packet.src_id);
    int curr_gid = packet.src_id;

    const NoC& curr_nc = router.getNoC();
    bool is_dst_chip = isDestinationLocal(curr_nc, packet.dst_id);

    // Router is on the interposer, or on the destination chip or is a boundary
    // NOTE: There is an implicit assumption here. It is that the vertical link
    // on the boundary router will be taken. If that is not the case, and the
    // selected vertical link is elsewhere, the packet will have to be routed
    // from a horizontal port to a downward port, which is prohibited on VN_1.
    if (router.isOnBaseInterposer() || is_dst_chip ||
        router.isBoundary())
    {
        packet.vc_id = (rr_vc_allocation[curr_gid]) ? VN_0 : VN_1;
        rr_vc_allocation[curr_gid] = !rr_vc_allocation[curr_gid];
    }
    else // !is_dst_chip
    {
        packet.vc_id = VN_0;
    }
}

int Routing_DEFT::selectVCOut(const VCData& vc_data, int vc_config,
                              vector<int> & vcs_out)
{
    const int curr_gid = vc_data.curr_id;
    const int direction_o = vc_data.dir_out;

    sc_assert(vcs_out.size() > 0 && vcs_out.size() < 3);
    if (vcs_out.size() == 1) return vcs_out[0];

    int vc_out = (rr_vc_switching[curr_gid][direction_o]) ? vcs_out[0] : vcs_out[1];
    // Flip the round-robin arbiter
    rr_vc_switching[curr_gid][direction_o] =
        !rr_vc_switching[curr_gid][direction_o];
    return vc_out;
}

void Routing_DEFT::assignVCOut(const Router & router,
                               const VCData& vc_data,
                               vector<int> & vcs_out,
                               int& extra_vc_config)
{
    const int dir_in  = vc_data.dir_in;
    const int dir_out = vc_data.dir_out;
    const int vc_in   = vc_data.vc_in;

    const bool is_dest_local = vc_data.ver_dir == DIRECTION_LOCAL;

    // Current router is a boundary, but not the source
    // (if source, VC already allocated through ::allocateVC and this function
    // should not be called)
    if (router.isBoundary())
    {
        // 2.5D: going to the interposer
        if (dir_out == DIRECTION_DOWN)
        {
            sc_assert(!router.isOnBaseInterposer());

            // NOTE: Current VC cannot be VN_1 as the only way the packet goes
            // now to the interposer is because the source router wasn't a
            // boundary.
            //
            // NOTE2: if VN_1 was possible, this would mean that it is allowed
            // to go from VN_1 to VN_0, which is not supported by DeFT due to
            // the risk of deadlock.
            sc_assert(vc_in != VN_1);

            // Re-assign VN_0 -> VN_0 or VN_0 -> VN_1
            vcs_out.push_back(VN_0);
            vcs_out.push_back(VN_1);
        }
        // 2.5D: coming from the interposer
        // ==> previous hop direction was DIRECTION_UP, dir_in is thus DOWN
        else if (dir_in == DIRECTION_DOWN)
        {
            sc_assert(is_dest_local && !router.isOnBaseInterposer());
            vcs_out.push_back(VN_1);
        }
    }
}

