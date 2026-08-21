#ifndef __NOXIMROUTING_WEST_FIRST_H__
#define __NOXIMROUTING_WEST_FIRST_H__

#include "RoutingAlgorithm.h"
#include "RoutingAlgorithms.h"
#include "../Router.h"

using namespace std;

class Routing_WEST_FIRST : RoutingAlgorithm {
	public:
                vector<RouteEntry> route(Router * router,
                                         const RouteData & routeData) override;

		static Routing_WEST_FIRST * getInstance();

	private:
		Routing_WEST_FIRST(){};
		~Routing_WEST_FIRST(){};

		static Routing_WEST_FIRST * routing_WEST_FIRST;
		static RoutingAlgorithmsRegister routingAlgorithmsRegister;
        static RoutingAlgorithm * xyz;
};

#endif
