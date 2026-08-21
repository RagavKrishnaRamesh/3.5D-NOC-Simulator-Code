/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#ifndef __NOXIMROUTING_VDA_H__
#define __NOXIMROUTING_VDA_H__

#include "RoutingMultiNoC.h"
#include "RoutingAlgorithms.h"
#include "../NoC.h"
#include "../Router.h"

#include "../GlobalRoutingTable.h"

#define VN_0 0
#define VN_1 1

using namespace std;

class Routing_VDA : public RoutingMultiNoC
{
public:
    void allocateVC(const Router&, Packet& packet) override;

    bool checkTopology(const Router& router) const override {
        // 2 virtual channels on the whole NoC and 2.5D topology
        return  router.getNoC().n_virtual_channels == 2 &&
               (router.isOnBaseInterposer() || router.isOnLastLevelChiplet());
    }

    static Routing_VDA * getInstance();

    string name() const override {
        return RoutingAlgorithm::name() + std::string("(VDA)");
    };

private:
    Routing_VDA()
        : RoutingMultiNoC(/*restrict_vc_allocation=*/true,
                          /*always_reassign_src_vc=*/true)
    {
        // Enforce VC Reallocation (VDA is sensitive to deadlocks without)
        GlobalParams::enable_vc_reallocation = true;
    }

    ~Routing_VDA() {}

    void assignVCOut(const Router & router,
                     const VCData & vc_data,
                     vector<int> & vcs_out,
                     int & vc_config) override;

    int selectVCOut(const VCData & vc_data,
                    int vc_config,
                    vector<int> & vcs_out) override;

    void runtimeInit(const NoC& noc) override;

    bool requireAtomicFlowCtrl(int dir_out, int vc_out) const override;

    static Routing_VDA * routing_VDA;
    static RoutingAlgorithmsRegister routingAlgorithmsRegister;

    // Round-robin flag for VC switching of VN_0 and VN_1
    vector<bool> rr_vc_allocation;
    vec2<uint8_t> rr_vc_switching;
};

#endif

