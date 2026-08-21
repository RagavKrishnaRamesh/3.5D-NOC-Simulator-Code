/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#include "Routing_VDA.h"

RoutingAlgorithmsRegister Routing_VDA::routingAlgorithmsRegister(
    "VDA", getInstance()
);

Routing_VDA* Routing_VDA::routing_VDA = 0;

Routing_VDA* Routing_VDA::getInstance() {
    if (routing_VDA == 0)
        routing_VDA = new Routing_VDA();
    return routing_VDA;
}

void Routing_VDA::runtimeInit(const NoC& noc)
{
    size_t tile_nb = noc.getNumberOfTiles();

    rr_vc_switching.resize(tile_nb);
    for (auto& flag : rr_vc_switching)
        flag.resize(DIRECTIONS+2, 0);

    rr_vc_allocation.resize(tile_nb, false);
}

int Routing_VDA::selectVCOut(const VCData& vc_data,
                             int vc_config,
                             vector<int> & vcs_out)
{
    const int curr_gid    = vc_data.curr_id;
    const int direction_o = vc_data.dir_out;

    sc_assert(vcs_out.size() > 0 && vcs_out.size() < 3);
    if (vcs_out.size() == 1) return vcs_out[0];

    int vc_out = (rr_vc_switching[curr_gid][direction_o]) ?
                 vcs_out[0] : vcs_out[1];
    // Flip the round-robin arbiter
    rr_vc_switching[curr_gid][direction_o] =
        !rr_vc_switching[curr_gid][direction_o];
    return vc_out;
}

void Routing_VDA::allocateVC(const Router& router, Packet& packet)
{
    int src_gid  = packet.src_id;
    int dest_gid = packet.dst_id;

    vector<int> vcs_out;

    int vdir = getVerticalDirection(router, dest_gid);

    VCData vc_data {
        .curr_id = src_gid,
        .dest_id = dest_gid,
        .dir_in  = -1,
        .dir_out = DIRECTION_LOCAL,
        .ver_dir = vdir,
        .vc_in   = -1
    };

    int dummy_config;
    assignVCOut(router, vc_data, vcs_out, dummy_config);

    if (vcs_out.size() > 1) {
        packet.vc_id = (rr_vc_allocation[src_gid]) ? vcs_out[0] : vcs_out[1];
        // Flip the round-robin arbiter
        rr_vc_allocation[src_gid] = !rr_vc_allocation[src_gid];
    }
    else {
        packet.vc_id = vcs_out[0];
    }
}

void Routing_VDA::assignVCOut(const Router & router,
                              const VCData & vc_data,
                              vector<int>  & vcs_out,
                              int & vc_config)
{
    const int dir_out = vc_data.dir_out;
    const int is_dest_local = vc_data.ver_dir == DIRECTION_LOCAL;

    // Router is on a given chiplet
    if (!router.isOnBaseInterposer())
    {
        // Local destination and the next hop is not descending
        if (!is_dest_local && dir_out != DIRECTION_DOWN) {
            vcs_out.push_back(VN_1);
        }
        // Router is on the destination chip or next hop is descending
        else {
            vcs_out.push_back(VN_0);
            vcs_out.push_back(VN_1);
        }
    }
    // Router is on the interposer
    else {
        // We assume the same VC switching on the interposer
        vcs_out.push_back(VN_0);
        vcs_out.push_back(VN_1);
    }
}

bool Routing_VDA::requireAtomicFlowCtrl(int dir_out, int vc_out) const {
    // VDA authors told us VDA requires an atomic flow control for any port / VC
    return true;
}

