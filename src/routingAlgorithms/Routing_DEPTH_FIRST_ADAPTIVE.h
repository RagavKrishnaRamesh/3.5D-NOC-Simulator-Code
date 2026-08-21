/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#ifndef __NOXIMROUTING_DEPTH_FIRST_ADAPTIVE_H__
#define __NOXIMROUTING_DEPTH_FIRST_ADAPTIVE_H__

#include "RoutingMultiNoC.h"
#include "RoutingAlgorithms.h"
#include "../NoC.h"
#include "../Router.h"

#include "../GlobalRoutingTable.h"

#define EVC0 0
#define EVC1 1
#define AVC  2

#define CONFIG_EVC0_AVC 0
#define CONFIG_EVC1_AVC 1
#define CONFIG_EVC0_EVC1_AVC 2

using namespace std;

class Routing_DEPTH_FIRST_ADAPTIVE : public RoutingMultiNoC
{
public:
    void allocateVC(const Router&, Packet& packet) override;

    bool checkTopology(const Router& router) const override
    {
        // At least 2 virtual channels on the whole NoC
        return router.getNoC().n_virtual_channels >= 2;
    }

    static Routing_DEPTH_FIRST_ADAPTIVE * getInstance();

    string name() const override {
        return RoutingAlgorithm::name() +
               std::string("(DEPTH_FIRST_ADAPTIVE)");
    };

private:
    // In the Noxim implementation, we need to re-assign the VCOut after being
    // allocated as the protocol supports heterogeneous VC. The number of VCOut
    // available is known only when dir_out is known, which is only the case
    // when the routing function has been called.
    Routing_DEPTH_FIRST_ADAPTIVE()
        : RoutingMultiNoC(/*restrict_vc_allocation=*/true,
                          /*always_reassign_src_vc=*/true)
    {
        // Enforce VC Reallocation (AVCs of Depth-First Adaptive are sensitive
        // to deadlocks without VC Reallocation)
        GlobalParams::enable_vc_reallocation = true;
    }

    ~Routing_DEPTH_FIRST_ADAPTIVE() {}

    void assignVCOut(const Router& router,
                     const VCData& vc_data,
                     vector<int> & vcs_out,
                     int&  extra_vc_config) override;

    int selectVCOut(const VCData& vc_data,
                    int   extra_vc_config,
                    vector<int> & vcs_out) override;

    void runtimeInit(const NoC& noc) override;

    bool requireAtomicFlowCtrl(int dir_out, int vc_out) const override;

    void selectVirtualChannels(const Router& router,
                               const VCData& vc_data,
                               int   extra_vc_config,
                               vector<int>& vcs_out) const;

    static Routing_DEPTH_FIRST_ADAPTIVE * routing_DEPTH_FIRST_ADAPTIVE;
    static RoutingAlgorithmsRegister routingAlgorithmsRegister;

    // Round-robin flag for VC switching between EVCs/AVCs
    vec2<uint8_t> rr_vc_allocation;
    vec3<uint8_t> rr_vc_switching;
    vec3<uint8_t> nb_vcs;
};

#endif

