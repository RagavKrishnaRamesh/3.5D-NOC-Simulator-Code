/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#ifndef __NOXIMROUTING_MULTI_NOC_H__
#define __NOXIMROUTING_MULTI_NOC_H__

#include "RoutingAlgorithm.h"
#include "RoutingAlgorithms.h"
#include "../NoC.h"
#include "../Router.h"

#include "../GlobalRoutingTable.h"

using namespace std;

class RoutingMultiNoC : public RoutingAlgorithm
{
public:
    RoutingMultiNoC(bool restrict_vc_allocation,
                    bool always_reassign_src_vc) :
        RoutingAlgorithm(restrict_vc_allocation,
                         always_reassign_src_vc) {}

    ~RoutingMultiNoC() {}

    vector<RouteEntry> route(Router * router,
                             const RouteData & routeData) override;

    void customPreRoutingRes(const Router    & router,
                                   RouteData & rdata,
                                   Buffer    & buffer,
                                   Flit      & flit) override
    {
        const NoC& curr_nc = router.getNoC();
        int dst_gid = flit.dst_id;

        // Current header flit has a non-local destination and is not already
        // configured to be router towards a vertical link
        if (rdata.routing_towards_vlink == false &&
            !isDestinationLocal(curr_nc, dst_gid))
        {
            int vdir = getVerticalDirection(router, dst_gid);
            int vlink_id = selectVerticalLink(router, vdir, dst_gid);
            // Update both routeData and flit header
            flit.routing_towards_vlink =
                rdata.routing_towards_vlink = true;
            flit.vlink_dest = rdata.vlink_dest = vlink_id;
            // Update the buffer with the new header flit
            buffer.UpdateFront(flit);
        }
    }

    bool customForwarding(const RouteData & rdata,
                                Buffer    & buffer,
                                Flit      & flit,
                                int         dir_out) const override
    {
        // Current header flit is arrived to the vertical link node and is
        // ready to be elevated
        if (rdata.routing_towards_vlink == true &&
            (dir_out == DIRECTION_DOWN || dir_out == DIRECTION_UP))
        {
            sc_assert(rdata.current_id == flit.vlink_dest);
            // Remove the local routing metadata from the header
            flit.routing_towards_vlink = false;
            flit.vlink_dest = -1;
            // Update the buffer with the new header flit
            buffer.UpdateFront(flit);
        }
        // after sending it, erase the flit from the buffer
        return true;
    }

    bool isDestinationLocal(const NoC& nc,
                                  int dest_gid) const;

    int getVerticalDirection(const Router& router,
                                   int dest_gid) const;

    int selectVerticalLink(const Router& router,
                                 int     vdir,
                                 int     dest_gid) const;
};

#endif

