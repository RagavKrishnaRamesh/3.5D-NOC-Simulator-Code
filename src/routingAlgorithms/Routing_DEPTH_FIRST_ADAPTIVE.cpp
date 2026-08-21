/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#include "Routing_DEPTH_FIRST_ADAPTIVE.h"

RoutingAlgorithmsRegister
Routing_DEPTH_FIRST_ADAPTIVE::routingAlgorithmsRegister(
    "DEPTH_FIRST_ADAPTIVE", getInstance()
);

Routing_DEPTH_FIRST_ADAPTIVE*
    Routing_DEPTH_FIRST_ADAPTIVE::routing_DEPTH_FIRST_ADAPTIVE = 0;

Routing_DEPTH_FIRST_ADAPTIVE* Routing_DEPTH_FIRST_ADAPTIVE::getInstance() {
    if (routing_DEPTH_FIRST_ADAPTIVE == 0)
        routing_DEPTH_FIRST_ADAPTIVE = new Routing_DEPTH_FIRST_ADAPTIVE();
    return routing_DEPTH_FIRST_ADAPTIVE;
}

void Routing_DEPTH_FIRST_ADAPTIVE::runtimeInit(const NoC& noc)
{
    size_t tile_nb = noc.getNumberOfTiles();

    rr_vc_switching.resize(tile_nb);
    for (auto& rr_per_tile : rr_vc_switching) {
        // VCs config entries
        rr_per_tile.resize(3);
        for (auto& rr_per_config : rr_per_tile) {
            rr_per_config.resize(DIRECTIONS+2, 0);
        }
    }

    rr_vc_allocation.resize(tile_nb);
    for (auto& rr_per_tile : rr_vc_allocation) {
        // VCs config entries, initialized at 0.
        // No need to create one for each direction as only the LOCAL_DIRECTION
        // is used when doing the initial allocation
        rr_per_tile.resize(3, 0);
    }

    nb_vcs.resize(tile_nb);
    for (size_t tile_i = 0; tile_i < tile_nb; tile_i++) {
        auto& nb_vcs_per_tile = nb_vcs[tile_i];
        // VCs config entries
        nb_vcs_per_tile.resize(3);
        for (size_t vc_config_i = 0;
                    vc_config_i < nb_vcs_per_tile.size();
                    vc_config_i++)
        {
            nb_vcs_per_tile[vc_config_i].resize(DIRECTIONS+2, 0);
            auto& nb_vcs_config = nb_vcs_per_tile[vc_config_i];
            for (size_t dir = 0; dir < nb_vcs_config.size(); dir++)
            {
                auto& nb_vcs_per_dir = nb_vcs_config[dir];
                int nb_vc_out = -1;
                // FIXME: does not support 3D Chiplet
                if (dir == DIRECTION_UP)
                    nb_vc_out =
                        noc.searchGlobalNode(tile_i)->getRouter().getNumberVCOutUp();
                else if (dir == DIRECTION_DOWN)
                    nb_vc_out =
                        noc.searchGlobalNode(tile_i)->getRouter().getNumberVCOutDown();
                else {
                    const NoC& local_noc = noc.searchGlobalNode(tile_i)->getNoC();
                    nb_vc_out = local_noc.n_virtual_channels;
                }
                // In both of these cases, there is one VC not used
                // We assume here that there is one VC for EVC0 and one VC for
                // EVC1
                if (nb_vc_out > 0 && ( vc_config_i == CONFIG_EVC0_AVC ||
                    vc_config_i == CONFIG_EVC1_AVC) )
                    nb_vc_out--;
                //cout << "tile_nb:" << tile_i << " config:" << vc_config_i << " dir:" << dir << " vc_out: " << nb_vc_out << endl;
                nb_vcs_per_dir = nb_vc_out;
            }
        }
    }
}

void Routing_DEPTH_FIRST_ADAPTIVE::selectVirtualChannels(const Router& router,
                                                         const VCData& vc_data,
                                                         int extra_vc_config,
                                                         vector<int>& vcs_out) const
{
    if (extra_vc_config == CONFIG_EVC0_AVC)
        vcs_out.push_back(EVC0);
    else if (extra_vc_config == CONFIG_EVC1_AVC)
        vcs_out.push_back(EVC1);
    else {
        vcs_out.push_back(EVC0);
        vcs_out.push_back(EVC1);
    }

    int nb_vc_out = -1;
    const int dir_out = vc_data.dir_out;
    // Selects the appropriate number of VCs depending on the output direction
    // NOTE: the assumption here is that the number of VCs is constant in a
    // chiplet, but not between chiplets.
    //
    // FIXME: This does not take into account a 3D chiplet as the router must
    // be check to be on the upper or lower layer in that case
    if (dir_out == DIRECTION_UP) {
        nb_vc_out = router.getNumberVCOutUp();
    }
    else if (dir_out == DIRECTION_DOWN) {
        nb_vc_out = router.getNumberVCOutDown();
    }
    else
        nb_vc_out = router.getNoC().n_virtual_channels;

    for (int avc = AVC; avc < nb_vc_out; avc++)
        vcs_out.push_back(avc);
}

void Routing_DEPTH_FIRST_ADAPTIVE::allocateVC(const Router& router,
                                              Packet& packet)
{
    int src_gid  = packet.src_id;
    int dest_gid = packet.dst_id;

    vector<int> vcs_out;

    int vdir = getVerticalDirection(router, dest_gid);
    int vc_config = -1;

    // Same assumption as for DeFT here. The routing algorithm will use the
    // downward link to route the packet down, therefore we can use EVC1.
    if (vdir == DIRECTION_DOWN && router.hasDownwardLink() &&
        router.incomingDownUpTransition(dest_gid)) {
        vc_config = CONFIG_EVC0_EVC1_AVC;
    }
    else if (vdir == DIRECTION_DOWN) {
        vc_config = CONFIG_EVC0_AVC;
    }
    else { // vdir == UP / Local
        vc_config = CONFIG_EVC0_EVC1_AVC;
    }

    VCData data {
        // current router is the src
        .curr_id = src_gid,
        .dest_id = dest_gid,
        .dir_in  = -1,
        .dir_out = DIRECTION_LOCAL,
        .ver_dir = vdir,
        .vc_in   = -1
    };

    selectVirtualChannels(router, data, vc_config, vcs_out);

    if (vcs_out.size() > 1) {
        assert(rr_vc_allocation[src_gid][vc_config] < vcs_out.size());
        packet.vc_id = vcs_out[rr_vc_allocation[src_gid][vc_config]];
        // Update the round-robin arbiter
        rr_vc_allocation[src_gid][vc_config] =
            (rr_vc_allocation[src_gid][vc_config] + 1)
                % nb_vcs[src_gid][vc_config][DIRECTION_LOCAL];
        return;
    }
    packet.vc_id = vcs_out[0];
}

void Routing_DEPTH_FIRST_ADAPTIVE::assignVCOut(const Router& router,
                                               const VCData& vc_data,
                                               vector<int>& vcs_out,
                                               int&  vc_config)
{
    const int vc_in   = vc_data.vc_in;
    const int dir_in  = vc_data.dir_in;
    const int dir_out = vc_data.dir_out;
    const int vdir    = vc_data.ver_dir;
    const int dst_id  = vc_data.dest_id;

    //assert(dir_out != DIRECTION_DOWN || router.incomingDownUpTransition(dst_id));

    if (vc_in == EVC0) {
        // (1) We cannot stay in EVC0 if we have to transit from an Up port to
        // an horizontal port
        // Implicit condition: vdir == UP
        if (dir_in == DIRECTION_DOWN && dir_out != DIRECTION_UP)
            vc_config = CONFIG_EVC1_AVC;
        // (2) Direct transition or indirect transition to EVC1 must be done
        // once we are sure that the packet will no transit from an horizontal
        // port to a Down port. Here is the earliest where it can happened.
        // Implicit condition: vdir == DOWN
        // FIXME: On a 3D chiplet, we should be on the base layer to allow this
        else if (dir_out == DIRECTION_DOWN &&
                 router.incomingDownUpTransition(dst_id))
            vc_config = CONFIG_EVC0_EVC1_AVC;
        // (3) We still have to go Down and there will be more transitions from
        // an Horizontal port to a Downward port. Hence, we have to stay in
        // EVC0 or go to an AVC.
        // The implicit condition here is: ( vdir == DIRECTION_DOWN &&
        //                                   ( dir_out != DIRECTION_DOWN ||
        //                                    !incoming ) )
        else if (vdir == DIRECTION_DOWN) {
            vc_config = CONFIG_EVC0_AVC;
        }
        // (4) As (1) was not executed here, we thus either did not go Up or
        // we came Up and we are still going Up. The packet can stay in EVC0,
        // go to an AVC or go to EVC1.
        // Implicit condition: vdir == UP or LOCAL
        else 
            vc_config = CONFIG_EVC0_EVC1_AVC;
    }
    else if (vc_in == EVC1) {
        // Continue in EVC1 or select an AVC
        vc_config = CONFIG_EVC1_AVC;
    }
    else // vc_in in AVCs
    {
        // FIXME: On a 3D chiplet, we should be on the base layer to allow this
        if (vdir == DIRECTION_DOWN &&
            dir_out == DIRECTION_DOWN &&
            router.incomingDownUpTransition(dst_id))
        {
            vc_config = CONFIG_EVC0_EVC1_AVC;
        }
        else if (vdir == DIRECTION_DOWN) {
            vc_config = CONFIG_EVC0_AVC;
        }
        else {
            vc_config = CONFIG_EVC1_AVC;
        }
    }

    // NOTE: an indirect transition of the kind EVC1 => AVCs => EVC0 is
    // impossible
    selectVirtualChannels(router, vc_data, vc_config, vcs_out);

    if (dir_in == DIRECTION_DOWN && dir_out != DIRECTION_UP)
        sc_assert(vc_config == CONFIG_EVC1_AVC);
}

int Routing_DEPTH_FIRST_ADAPTIVE::selectVCOut(const VCData& vc_data,
                                              int extra_vc_config,
                                              vector<int> & vcs_out)
{
    if (vcs_out.size() == 1)
        return vcs_out[0];

    const int curr_gid = vc_data.curr_id;
    const int dir_o    = vc_data.dir_out;
    unsigned rr_value  = rr_vc_switching[curr_gid][extra_vc_config][dir_o];
    assert(rr_value < vcs_out.size());
    int vc_out = vcs_out[rr_value];
    // Update the round-robin arbiter
    rr_vc_switching[curr_gid][extra_vc_config][dir_o] =
        (rr_vc_switching[curr_gid][extra_vc_config][dir_o] + 1)
            % nb_vcs[curr_gid][extra_vc_config][dir_o];
    return vc_out;
}

bool Routing_DEPTH_FIRST_ADAPTIVE::requireAtomicFlowCtrl(int dir_out,
                                                         int vc_out) const
{
    return vc_out >= AVC && (dir_out == DIRECTION_UP ||
                             dir_out == DIRECTION_DOWN);
}

