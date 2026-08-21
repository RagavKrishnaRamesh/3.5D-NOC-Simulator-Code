#include "Routing_XYZ.h"

RoutingAlgorithmsRegister Routing_XYZ::routingAlgorithmsRegister("XYZ", getInstance());

Routing_XYZ * Routing_XYZ::routing_XYZ = 0;

Routing_XYZ * Routing_XYZ::getInstance() {
	if ( routing_XYZ == 0 )
		routing_XYZ = new Routing_XYZ();
    
	return routing_XYZ;
}

vector<RouteEntry> Routing_XYZ::route(Router * router,
                                      const RouteData & routeData)
{
    Coord current = id2Coord(routeData.current_id);
    Coord destination = id2Coord(routeData.dst_id);
    vector<RouteEntry> directions;
    int default_vc = routeData.vc_in;

    if (destination.x > current.x)
       directions.push_back({DIRECTION_EAST, default_vc});
    else if (destination.x < current.x)
        directions.push_back({DIRECTION_WEST, default_vc});
    else if (destination.y > current.y)
        directions.push_back({DIRECTION_SOUTH, default_vc});
    else if (destination.y < current.y)
        directions.push_back({DIRECTION_NORTH, default_vc});
    else if (destination.z > current.z)
        directions.push_back({DIRECTION_UP, default_vc});
    else if (destination.z < current.z)
        directions.push_back({DIRECTION_DOWN, default_vc});
    else
        // NOTE: redundant with the definition of Router::route()
        directions.push_back({DIRECTION_LOCAL, default_vc});

    LOG << "cx="  << current.x
        << " cy=" << current.y
        << " cz=" << current.z
        << " dx=" << destination.x
        << " dy=" << destination.y
        << " dz=" << destination.z
        << " directions=" << directions[0].first
        << " vc=" << directions[0].second << endl;

    return directions;
}
