/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#ifndef __NOXIMROUTING_DEPTH_FIRST_H__
#define __NOXIMROUTING_DEPTH_FIRST_H__

#include "RoutingMultiNoC.h"
#include "RoutingAlgorithms.h"
#include "../NoC.h"
#include "../Router.h"

#include "../GlobalRoutingTable.h"

#define VC_Z_UP   1
#define VC_Z_DOWN 0

using namespace std;

class Routing_DEPTH_FIRST : public RoutingMultiNoC
{
public:
    void allocateVC(const Router&, Packet& packet) override;

    bool checkTopology(const Router& router) const override {
        // At least 2 virtual channels OR the router belongs to the base
        // interposer (no downward link)
        return router.getNoC().n_virtual_channels > 1 ||
               router.isOnBaseInterposer();
    }

    void assignVCOut(const Router & router,
                     const VCData & vc_data,
                     vector<int> & vcs_out,
                     int & vc_config) override;

    int selectVCOut(const VCData & vc_data,
                    int vc_config,
                    vector<int> & vcs_out) override;

    static Routing_DEPTH_FIRST * getInstance();

    string name() const override {
        return RoutingAlgorithm::name() + std::string("(DEPTH_FIRST)");
    };

private:
    Routing_DEPTH_FIRST()
        : RoutingMultiNoC(/*restrict_vc_allocation=*/true,
                          /* No need to re-assign VC as it is based on the
                             vertical direction, which stay the same between
                             the call to allocateVC and assignVCOut */
                          /*always_reassign_src_vc=*/false) {}
    ~Routing_DEPTH_FIRST() {}

    void directionalVCAllocation(int  dir,
                                 int & vc_out) const;

    static Routing_DEPTH_FIRST * routing_DEPTH_FIRST;
    static RoutingAlgorithmsRegister routingAlgorithmsRegister;
};

#endif
