/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#include "Routing_ELEVATOR_FIRST.h"

RoutingAlgorithmsRegister Routing_ELEVATOR_FIRST::routingAlgorithmsRegister("ELEVATOR_FIRST", getInstance());

Routing_ELEVATOR_FIRST * Routing_ELEVATOR_FIRST::routing_ELEVATOR_FIRST = 0;

Routing_ELEVATOR_FIRST * Routing_ELEVATOR_FIRST::getInstance() {
	if ( routing_ELEVATOR_FIRST == 0 )
		routing_ELEVATOR_FIRST = new Routing_ELEVATOR_FIRST();

	return routing_ELEVATOR_FIRST;
}

int routeXY(const Coord & curr, const Coord & dest)
{
    assert(curr.z == dest.z);

    if (dest.x > curr.x)
        return DIRECTION_EAST;
    if (dest.x < curr.x)
        return DIRECTION_WEST;
    if (dest.y > curr.y)
        return DIRECTION_SOUTH;
    if (dest.y < curr.y)
        return DIRECTION_NORTH;

    return DIRECTION_LOCAL;
}

vector<RouteEntry> Routing_ELEVATOR_FIRST::route(Router * router,
                                                 const RouteData & routeData)
{
    Coord current = id2Coord(routeData.current_id);
    Coord destination = id2Coord(routeData.dst_id);

    int direction = DIRECTION_LOCAL;
    int vdir = getVerticalDirection(current, destination);
    int vc_out = routeData.vc_in;

    // Route the packet locally if the local routing header is here
    // or if the destination is on the same planar layer
    if (routeData.routing_towards_vlink || vdir == DIRECTION_LOCAL) {
        direction = routeXY(current, destination);
    }
    // Otherwise, if the header is missing due to:
    // 1) header has been popped when reaching the elevator node ;
    // 2) To cross a given layer, the extra header has never been generated:
    //     a) elevator on the source node
    //     b) elevators in the same direction are chained and no local routing
    //        between them is necessary;
    // 3) ::route() was called just before the insertion of the new header.
    else {

        // Packet must go up and stands on an elevator up node [(1) & (2)]
        if (vdir == DIRECTION_UP && router->hasUpwardLink()) {
            assert(routeData.vc_in == 0);
            direction = vdir;
        }
        // Or packet must go down and is on an elevator down node [(1) & (2)]
        else if (vdir == DIRECTION_DOWN && router->hasDownwardLink()) {
            assert(routeData.vc_in == 1);
            direction = vdir;
        }
        // Or packet has been freshly emitted or has just crossed a vertical
        // link (header popped before crossing)
        //
        // NOTE: The routing process is split in two stages: Reservation,
        // followed by Forwarding. This method (::route) is called during
        // Reservation and the new header is inserted during Forwarding (see
        // ::customForwarding). Due to this decoupling, there are two cases
        // where the packet does not have an extra header but the reservation
        // stage must still take into account that the packet should be routed
        // to the next elevator, before the header is inserted. This happens
        // either 1) when the packet has been freshly emitted or 2) right after
        // being elevated (up/down).
        else if (vdir != DIRECTION_LOCAL &&
                 ((routeData.src_id == routeData.current_id) ||
                  (routeData.dir_in == DIRECTION_UP) ||
                  (routeData.dir_in == DIRECTION_DOWN)))
        {
            // Select preemptively the directions to reach the targeted
            // elevator
            int   elevator_id   = selectElevator(vdir, routeData);
            Coord elevator_dest = id2Coord(elevator_id);
            direction = routeXY(current, elevator_dest);
        }
        else {
            LOG << "Should be unreachable" << std::endl;
            assert(false && "Should be unreachable");
        }
    }
    vector<RouteEntry> routing_decision;
    routing_decision.emplace_back(direction, vc_out);
    return routing_decision;
}

void Routing_ELEVATOR_FIRST::allocateVC(const Router& router, Packet& packet)
{
    Coord current     = id2Coord(packet.src_id);
    Coord destination = id2Coord(packet.dst_id);

    int dir = getVerticalDirection(current, destination);

    if (dir == DIRECTION_UP)
        packet.vc_id = 0;
    else if (dir == DIRECTION_DOWN)
        packet.vc_id = 1;
}

int Routing_ELEVATOR_FIRST::getVerticalDirection(const Coord & curr,
                                                 const Coord & dest) const
{
    if (dest.z > curr.z)
        return DIRECTION_UP;
    if (dest.z < curr.z)
        return DIRECTION_DOWN;
    return DIRECTION_LOCAL; // local as default when dest.z == src.z
}

int Routing_ELEVATOR_FIRST::getVerticalDirection(const Flit & flit,
                                                 int current_id) const
{
    Coord dest_coord = id2Coord(flit.dst_id);
    Coord curr_coord = id2Coord(current_id);
    return getVerticalDirection(curr_coord, dest_coord);
}

int Routing_ELEVATOR_FIRST::selectElevator(int vdir,
                                           const RouteData & rdata) const
{
    assert(vdir == DIRECTION_UP || vdir == DIRECTION_DOWN);
    if (vdir == DIRECTION_UP)
        return 0; /* FIXME: REWRITE THIS*/
    return 0;//rdata.vlink_down;
}

// In the forwarding stage, we added the logic to insert a new header, in
// compliance with the original Elevator-First algorithm.
bool Routing_ELEVATOR_FIRST::customForwarding(const RouteData & rdata,
                                                    Buffer    & buffer,
                                                    Flit      & flit,
                                                    int         dir_out) const
{
    bool erase_buffer = true;
    int vdir = getVerticalDirection(flit, rdata.current_id);

    // Incoming flit is a regular header, whose destination is on a different
    // layer
    if (flit.flit_type == FLIT_TYPE_HEAD && !flit.routing_towards_vlink &&
        vdir != DIRECTION_LOCAL)
    {
        Flit new_header(flit);
        new_header.dst_id = selectElevator(vdir, rdata);

        // Emits the elevator header only if the packet is not emitted on the
        // elevator node
        if (new_header.dst_id != rdata.current_id)
        {
            new_header.routing_towards_vlink = true;
            LOG << "Header flit "        << new_header
                << " inserted based on " << flit
                << " at Input[" << rdata.dir_in << "][" << rdata.vc_in <<"]"
                << endl;
            // Replace current flit by the new header
            flit = new_header;
            // Retrieve the original header in the buffer
            Flit buffered_flit = buffer.Front();
            Flit old_buffered_flit(buffered_flit);
            // Converts previous header flit (still buffered) to a body flit
            buffered_flit.flit_type = FLIT_TYPE_BODY;
            LOG << "Convert previous header flit " << old_buffered_flit
                << " to body flit " << buffered_flit << endl;
            // Update the changes on the buffer
            buffer.UpdateFront(buffered_flit);
            // Do not erase the buffer as it contains the old header
            erase_buffer = false;
        }
    }
    return erase_buffer;
}

void Routing_ELEVATOR_FIRST::customPreRoutingRes(const Router    & router,
                                                       RouteData & rdata,
                                                       Buffer    & buffer,
                                                       Flit      & flit)
{
    auto& header_popped
        = headers_absorbed[rdata.current_id][rdata.dir_in][rdata.vc_in];
    
    // Extra local header has been popped: converts back the first body flit to
    // the header flit
    if (header_popped) {
        assert(flit.flit_type == FLIT_TYPE_BODY);
        // Switch the flit type to HEAD...
        flit.flit_type = FLIT_TYPE_HEAD;
        // ...and then update the buffer front flit
        buffer.UpdateFront(flit);
        LOG << "Convert back BODY to HEAD, Input["
            << rdata.dir_in << "][" << rdata.vc_in << "], flit: "
            << flit << endl;
        header_popped = false;
    }
}

bool Routing_ELEVATOR_FIRST::customPostRoutingRes(const RouteData & rdata,
                                                        Buffer    & buffer,
                                                        Flit      & flit,
                                                        int         dir_out)
{
    // Extra local header HEAD flit arriving to its local destination
    if (flit.flit_type == FLIT_TYPE_HEAD &&
        flit.routing_towards_vlink && dir_out == DIRECTION_LOCAL)
    {
        auto& header_popped
            = headers_absorbed[rdata.current_id][rdata.dir_in][rdata.vc_in];
        // A local routing header cannot be preeceded by a local routing header
        assert(header_popped == false);
        // Discards the flit without sending it
        buffer.Pop();
        LOG << "Pop header on Input[" << rdata.dir_in
            << "][" << rdata.vc_in << "], flit: " << flit << endl;
        // Report that the next flit on this port must be
        // interpreted as a header.
        header_popped = true;
        return true;
    }
    return false;
}

void Routing_ELEVATOR_FIRST::runtimeInit(const NoC& noc)
{
    int tile_nb = noc.getNumberOfTiles();

    headers_absorbed.resize(tile_nb);
    for (auto& headers_per_tile : headers_absorbed) {
        headers_per_tile.resize(DIRECTIONS+2);
        for (auto& headers_per_dir : headers_per_tile) {
            headers_per_dir.resize(noc.n_virtual_channels);
            for (auto& header_per_vc : headers_per_dir)
                header_per_vc = 0;
        }
    }
}

