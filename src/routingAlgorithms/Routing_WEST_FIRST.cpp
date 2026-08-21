#include "Routing_WEST_FIRST.h"

RoutingAlgorithmsRegister Routing_WEST_FIRST::routingAlgorithmsRegister("WEST_FIRST", getInstance());

Routing_WEST_FIRST * Routing_WEST_FIRST::routing_WEST_FIRST = 0;
RoutingAlgorithm * Routing_WEST_FIRST::xyz = 0;

Routing_WEST_FIRST * Routing_WEST_FIRST::getInstance() {
	if ( routing_WEST_FIRST == 0 )
        routing_WEST_FIRST = new Routing_WEST_FIRST();

    return routing_WEST_FIRST;
}

vector<RouteEntry> Routing_WEST_FIRST::route(Router * router,
                                             const RouteData & routeData)
{
    Coord current = id2Coord(routeData.current_id);
    Coord destination = id2Coord(routeData.dst_id);
    vector<RouteEntry> directions;
    int default_vc = routeData.vc_in;

    if (destination.x <= current.x || destination.y == current.y)
    {
        if(!xyz)
        {
            xyz = RoutingAlgorithms::get("XYZ");
            
            if (!xyz)
                assert(false);
        }

        return xyz->route(router, routeData);
    }
    if (destination.y < current.y)
    {
        directions.push_back({DIRECTION_NORTH, default_vc});
        directions.push_back({DIRECTION_EAST,  default_vc});
    }
    else 
    {
        directions.push_back({DIRECTION_SOUTH, default_vc});
        directions.push_back({DIRECTION_EAST,  default_vc});
    }

    return directions;
}
