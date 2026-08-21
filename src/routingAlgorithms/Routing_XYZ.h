#ifndef __NOXIMROUTING_XYZ_H__
#define __NOXIMROUTING_XYZ_H__

#include "RoutingAlgorithm.h"
#include "RoutingAlgorithms.h"
#include "../Router.h"

using namespace std;

class Routing_XYZ : RoutingAlgorithm {
	public:
                vector<RouteEntry> route(Router * router,
                                         const RouteData & routeData) override;

		static Routing_XYZ * getInstance();
                std::string name() { return "Routing_XYZ"; }

	private:
		Routing_XYZ(){};
		~Routing_XYZ(){};

		static Routing_XYZ * routing_XYZ;
		static RoutingAlgorithmsRegister routingAlgorithmsRegister;
};

#endif
