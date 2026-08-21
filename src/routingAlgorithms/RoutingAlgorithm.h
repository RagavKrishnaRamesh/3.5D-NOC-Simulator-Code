#ifndef __NOXIMROUTINGALGORITHM_H__
#define __NOXIMROUTINGALGORITHM_H__

#include <vector>
#include "../Buffer.h"
#include "../DataStructs.h"
#include "../Utils.h"

using namespace std;

struct NoC;
struct Router;

class RoutingAlgorithm
{
	public:
                RoutingAlgorithm(const bool restrict_vc_allocation = false,
                                 const bool always_reassign_src_vc = false) :
                  restrict_vc_allocation(restrict_vc_allocation),
                  always_reassign_src_vc(always_reassign_src_vc) {}

                // Returns a series of authorized pair of DIRECTION and VCOUT
                // for the next hop 
                virtual vector<RouteEntry> route(Router * router,
                                                 const RouteData & rdata) = 0;

                // Initial VC Allocation
                virtual void allocateVC(const Router& router,
                                        Packet& packet) {}

                // Returns the set of VCs allowed for the next hop when going
                // to a given direction
                virtual void assignVCOut(const Router& router,
                                         const VCData& vc_data,
                                         vector<int>& vcs_out,
                                         int& extra_vc_config) {}

                // Select an output VC if multiple VC are available
                virtual int selectVCOut(const VCData& vc_data,
                                        int vc_config,
                                        vector<int> & vcs_out)
                {
                    sc_assert(vcs_out.size() > 0);
                    return vcs_out[0];
                }

                // Check the routing algorithm supports the current Topology
                virtual bool checkTopology(const Router& router) const
                { return true; }

                // This method customizes the router Forwarding logic.
                // Returns whether the flit should be erased from the input
                // buffer.
                virtual bool customForwarding(const RouteData & data,
                                                    Buffer    & buffer,
                                                    Flit      & flit,
                                                    int         dir_out) const
                { return true; }

                // This method allow the customization of the Reservation logic
                // before calling the main routing procedure.
                virtual void customPreRoutingRes(const Router    & router,
                                                       RouteData & data,
                                                       Buffer    & buffer,
                                                       Flit      & flit) {}

                // This method allow the customization of the Reservation logic
                // after calling the main routing procedure.
                // Returns whether the reservation should be skipped or not.
                virtual bool customPostRoutingRes(const RouteData & data,
                                                        Buffer    & buffer,
                                                        Flit      & flit,
                                                        int         dir_out)
                { return false; }

                // This method checks if an atomic control flow is required for
                // a given pair dir_out / vc_out
                virtual bool requireAtomicFlowCtrl(int dir_out,
                                                   int vc_out) const
                { return false; }

                // Returns a generic name composed of the SystemC parent object
                // with the 'Routing' suffix.
                // NOTE: name() must be defined manually as this class is not a
                // SC_MODULE.
                virtual std::string name() const {
                    auto current_process = sc_core::sc_get_current_process_b();
                    if (current_process == nullptr) return "Routing";

                    auto parent_object = current_process->get_parent_object();
                    if (parent_object == nullptr) return "Routing";

                    const char* parent_name = parent_object->name();
                    return std::string(parent_name) + ".Routing";
                }

                // Runtime initialization interface
                static void initialize(RoutingAlgorithm& R, const NoC& noc) {
                    // It delegates the initialization of routing related data
                    // at runtime to the targeted object and ensures it is called
                    // only once.
                    if (!initialized) {
                        route_using_selection_strategy =
                            GlobalParams::route_using_selection_strategy;
                        R.runtimeInit(noc);
                        initialized = true;
                    }
                }

                const bool restrict_vc_allocation;
                const bool always_reassign_src_vc;

	protected:
                static bool route_using_selection_strategy;
	private:
                // Performs runtime initialization and returns true if it
                // succeeded
                virtual void runtimeInit(const NoC& noc) {}
                static bool initialized;
};

#endif
