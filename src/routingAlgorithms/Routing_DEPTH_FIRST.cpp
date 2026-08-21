/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#include "Routing_DEPTH_FIRST.h"

RoutingAlgorithmsRegister Routing_DEPTH_FIRST::routingAlgorithmsRegister(
    "DEPTH_FIRST", getInstance()
);

Routing_DEPTH_FIRST* Routing_DEPTH_FIRST::routing_DEPTH_FIRST = 0;

Routing_DEPTH_FIRST* Routing_DEPTH_FIRST::getInstance() {
    if (routing_DEPTH_FIRST == 0)
        routing_DEPTH_FIRST = new Routing_DEPTH_FIRST();
    return routing_DEPTH_FIRST;
}

void Routing_DEPTH_FIRST::allocateVC(const Router& router, Packet& packet)
{
    // If the packet is emitted on the base interposer, and the base interposer
    // has less than 2 VCs, place the packet on Z Down (VC_ID == 0).
    if (router.isOnBaseInterposer() &&
        router.getNoC().n_virtual_channels < 2)
    {
        packet.vc_id = VC_Z_DOWN;
        return;
    }

    int vdir = getVerticalDirection(router, packet.dst_id);
    directionalVCAllocation(vdir, packet.vc_id);
}

void Routing_DEPTH_FIRST::assignVCOut(const Router & router,
                                      const VCData & vc_data,
                                      vector<int> & vcs_out,
                                      int& vc_config)
{
    const int dir_out = vc_data.dir_out;
    const int vc_in   = vc_data.vc_in;

    int vc_out = vc_in;

    if (dir_out == DIRECTION_UP) {
        // Change VC to Z_UP if the current one is Z_DOWN
        if (vc_in == VC_Z_DOWN)
            directionalVCAllocation(DIRECTION_UP, vc_out);
        sc_assert(vc_out == VC_Z_UP);
    }
    else if (dir_out == DIRECTION_DOWN) {
        // No transition from Z_UP to Z_DOWN is allowed
        sc_assert(vc_in  == VC_Z_DOWN &&
                  vc_out == VC_Z_DOWN);
    }

    vcs_out.push_back(vc_out);
}

int Routing_DEPTH_FIRST::selectVCOut(const VCData& vc_data,
                                     int vc_config,
                                     vector<int> & vcs_out)
{
    sc_assert(vcs_out.size() > 0);
    return vcs_out[0];
}

void Routing_DEPTH_FIRST::directionalVCAllocation(int  vdir,
                                                  int& vc_out) const
{
    if (vdir == DIRECTION_UP)
        vc_out = VC_Z_UP;
    else if (vdir == DIRECTION_DOWN)
        vc_out = VC_Z_DOWN;
    // vdir == DIRECTION_LOCAL
    // Otherwise, keep the random VC allocated when emitting the packet
}

