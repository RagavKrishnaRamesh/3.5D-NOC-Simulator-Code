/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#ifndef __NOXIMROUTING_DEFT_H__
#define __NOXIMROUTING_DEFT_H__

#include "RoutingMultiNoC.h"
#include "RoutingAlgorithms.h"
#include "../NoC.h"
#include "../Router.h"

#include "../GlobalRoutingTable.h"

#define VN_0 0
#define VN_1 1

using namespace std;

class Routing_DEFT : public RoutingMultiNoC
{
public:
    void allocateVC(const Router&, Packet& packet) override;

    bool checkTopology(const Router& router) const override {
        // 2 virtual channels on the whole NoC and 2.5D topology
        return  router.getNoC().n_virtual_channels == 2 &&
               (router.isOnBaseInterposer() || router.isOnLastLevelChiplet());
    }

    void assignVCOut(const Router & router,
                     const VCData & vc_data,
                     vector<int> & vcs_out,
                     int& extra_vc_config) override;

    int selectVCOut(const VCData & vc_data,
                    int vc_config,
                    vector<int> & vcs_out) override;

    static Routing_DEFT * getInstance();

    string name() const override {
        return RoutingAlgorithm::name() + std::string("(DEFT)");
    };

private:
    Routing_DEFT()
        : RoutingMultiNoC(/*restrict_vc_allocation=*/true,
                          /*always_reassign_src_vc=*/false) {}
    ~Routing_DEFT() {}

    bool goingToInterposer(const Router* router) const;
    bool comingFromInterposer(const Router* router) const;

    void runtimeInit(const NoC& noc) override;

    static Routing_DEFT * routing_DEFT;
    static RoutingAlgorithmsRegister routingAlgorithmsRegister;

    // Set of round-robin flags (1 per tile) for VC allocation of VN_0 and VN_1
    vector<bool> rr_vc_allocation;
    // Set of round-robin flags (1 per tile) for VC switching of VN_0 and VN_1
    vec2<uint8_t> rr_vc_switching;
};

#endif
