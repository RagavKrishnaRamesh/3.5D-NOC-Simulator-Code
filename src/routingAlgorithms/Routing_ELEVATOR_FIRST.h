/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#ifndef __NOXIMROUTING_ELEVATOR_FIRST_H__
#define __NOXIMROUTING_ELEVATOR_FIRST_H__

#include "RoutingAlgorithm.h"
#include "RoutingAlgorithms.h"
#include "../NoC.h"
#include "../Router.h"

#include "../GlobalRoutingTable.h"

using namespace std;

class Routing_ELEVATOR_FIRST : RoutingAlgorithm {
	public:
		vector<RouteEntry> route(Router * router,
                                         const RouteData & routeData) override;

		void allocateVC(const Router & router, Packet& packet) override;

                bool checkTopology(const Router& router) const override {
                    // For now, we only support 2 VCs (original algorithm).
                    // FIXME: the algorithm could be generalized to any power
                    // of two number of VCs
                    return router.getNoC().n_virtual_channels == 2;
                }

                bool customForwarding(const RouteData & data,
                                            Buffer    & buffer,
                                            Flit      & flit,
                                            int         dir_o) const override;

                void customPreRoutingRes(const Router    & router,
                                               RouteData & rdata,
                                               Buffer    & buffer,
                                               Flit      & flit) override;

                bool customPostRoutingRes(const RouteData & rdata,
                                                Buffer    & buffer,
                                                Flit      & flit,
                                                int         dir_out) override;

		static Routing_ELEVATOR_FIRST * getInstance();

                string name() const override {
                    return RoutingAlgorithm::name() +
                           std::string("(ELEVATOR_FIRST)");
                };


	private:
		Routing_ELEVATOR_FIRST() :
                    RoutingAlgorithm(/*restrictVCAllocation=*/true)
                {}

		~Routing_ELEVATOR_FIRST(){};

                void runtimeInit(const NoC&) override;

                int getVerticalDirection(const Coord & curr,
                                         const Coord & dest) const;

                int getVerticalDirection(const Flit & flit,
                                         int current_id) const;

                int selectElevator(int vdir, const RouteData & rdata) const;

		static Routing_ELEVATOR_FIRST * routing_ELEVATOR_FIRST;
		static RoutingAlgorithmsRegister routingAlgorithmsRegister;

                // Global data structure keeping track of whether a local
                // routing header was absorbed for a given router/direction/vc.
                // This is used to convert back the following flit to a header.
                // NOTE: we do not use vec3<bool> as it does not offer bool&
                // when iterating
                vec3<uint8_t> headers_absorbed;
};

#endif

