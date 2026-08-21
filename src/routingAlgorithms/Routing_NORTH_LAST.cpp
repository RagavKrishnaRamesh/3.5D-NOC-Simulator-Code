#include "Routing_NORTH_LAST.h"

RoutingAlgorithmsRegister Routing_NORTH_LAST::routingAlgorithmsRegister("NORTH_LAST", getInstance());

Routing_NORTH_LAST * Routing_NORTH_LAST::routing_NORTH_LAST = 0;
RoutingAlgorithm * Routing_NORTH_LAST::xy = 0;

Routing_NORTH_LAST * Routing_NORTH_LAST::getInstance() {
	if ( routing_NORTH_LAST == 0 )
		routing_NORTH_LAST = new Routing_NORTH_LAST();

    return routing_NORTH_LAST;
}

vector<RouteEntry> Routing_NORTH_LAST::route(Router * router,
                                             const RouteData & routeData)
{
    Coord current = id2Coord(routeData.current_id);
    Coord destination = id2Coord(routeData.dst_id);
    vector<RouteEntry> directions;

    if (destination.x == current.x || destination.y <= current.y)
    {
        if(!xy)
        {
            xy = RoutingAlgorithms::get("XY");
            
            if (!xy)
                assert(false);
        }

        return xy->route(router, routeData);
    }
    if (destination.x < current.x) 
    {
        directions.push_back({DIRECTION_SOUTH, routeData.vc_in});
        directions.push_back({DIRECTION_WEST,  routeData.vc_in});
    } 
    else 
    {
        directions.push_back({DIRECTION_SOUTH, routeData.vc_in});
        directions.push_back({DIRECTION_EAST,  routeData.vc_in});
    }

    return directions;
}
