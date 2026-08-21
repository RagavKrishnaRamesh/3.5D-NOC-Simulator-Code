/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * This file contains the implementation of the top-level of Noxim
 */

#include "ConfigurationManager.h"
#include "NoC.h"
#include "MeshNoC.h"
#include "MultiNoC.h"
#include "GlobalStats.h"
#include "DataStructs.h"
#include "Utils.h"

#include <csignal>

using namespace std;

// need to be globally visible to allow "-volume" simulation stop
unsigned int drained_volume;
unique_ptr<NoC> n;

void signalHandler( int signum )
{
    cout << "\b\b  " << endl;
    cout << endl;
    cout << "Current Statistics:" << endl;
    cout << "(" << sc_time_stamp().to_double() / GlobalParams::clock_period_ps << " sim cycles executed)" << endl;
    GlobalStats gs(n.get());
    gs.showStats(std::cout, GlobalParams::detailed);
}

int sc_main(int arg_num, char *arg_vet[])
{
#ifdef SIGQUIT
    signal(SIGQUIT, signalHandler);
#endif

    // TEMP
    drained_volume = 0;

    // Handle command-line arguments
    cout << "\t--------------------------------------------" << endl; 
    cout << "\t\tNoxim - the NoC Simulator" << endl;
    cout << "\t\t(C) University of Catania" << endl;
    cout << "\t--------------------------------------------" << endl; 

    cout << "Catania V., Mineo A., Monteleone S., Palesi M., and Patti D. (2016) Cycle-Accurate Network on Chip Simulation with Noxim. ACM Trans. Model. Comput. Simul. 27, 1, Article 4 (August 2016), 25 pages. DOI: https://doi.org/10.1145/2953878" << endl;
    cout << endl;
    cout << endl;

    configure(arg_num, arg_vet);


    // Signals
    sc_clock clock("clock", GlobalParams::clock_period_ps, SC_PS);
    sc_signal <bool> reset;

    // NoC instance
    if (GlobalParams::topology == TOPOLOGY_MESH) {
        // Create the MeshNoC
        n = make_unique<MeshNoC>("MeshNoC",
                                 GlobalParams::mesh_dim_x,
                                 GlobalParams::mesh_dim_y,
                                 GlobalParams::mesh_dim_z,
                                 GlobalParams::n_virtual_channels);
    }
    else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH) {
        // Retrieve the parameters of the base mesh / NoC of id '0'
        string base_name;
        MeshComponentConfig& base_config =
            MultiNoC::retrieveMeshConfig(0, base_name);
        // Create the Multi-NoC, starting with the base NoC of id '0'
        n = make_unique<MultiNoC>(base_name, base_config);
    } else {
       cout << GlobalParams::topology << " not supported in Main() at the moment" << endl;
       exit(-1);
    }

    // Post NoC construction checks and requirements
    n->checkRoutingRequirement();
    n->initializeRoutingAlgorithm();
    ProcessingElement::listAvailablePEs();

    n->clock(clock);
    n->reset(reset);

    // Trace signals
    sc_trace_file *tf = NULL;
    if (GlobalParams::trace_mode) {
	tf = sc_create_vcd_trace_file(GlobalParams::trace_filename.c_str());
	sc_trace(tf, reset, "reset");
	sc_trace(tf, clock, "clock");

	for (int i = 0; i < GlobalParams::mesh_dim_x; i++) {
	    for (int j = 0; j < GlobalParams::mesh_dim_y; j++) {
                for (int k = 0; k < GlobalParams::mesh_dim_z; k++) {
                    char label[64];

                    sprintf(label, "req(%02d)(%02d)(%02d).east", i, j, k);
                    sc_trace(tf, n->req[xgetId(i,j,k)].east, label);
                    sprintf(label, "req(%02d)(%02d)(%02d).west", i, j, k);
                    sc_trace(tf, n->req[xgetId(i,j,k)].west, label);
                    sprintf(label, "req(%02d)(%02d)(%02d).south", i, j, k);
                    sc_trace(tf, n->req[xgetId(i,j,k)].south, label);
                    sprintf(label, "req(%02d)(%02d)(%02d).north", i, j, k);
                    sc_trace(tf, n->req[xgetId(i,j,k)].north, label);
                    sprintf(label, "req(%02d)(%02d)(%02d).up", i, j, k);
                    sc_trace(tf, n->req[xgetId(i,j,k)].up, label);
                    sprintf(label, "req(%02d)(%02d)(%02d).down", i, j, k);
                    sc_trace(tf, n->req[xgetId(i,j,k)].down, label);

                    sprintf(label, "ack(%02d)(%02d)(%02d).east", i, j, k);
                    sc_trace(tf, n->ack[xgetId(i,j,k)].east, label);
                    sprintf(label, "ack(%02d)(%02d)(%02d).west", i, j, k);
                    sc_trace(tf, n->ack[xgetId(i,j,k)].west, label);
                    sprintf(label, "ack(%02d)(%02d)(%02d).south", i, j, k);
                    sc_trace(tf, n->ack[xgetId(i,j,k)].south, label);
                    sprintf(label, "ack(%02d)(%02d)(%02d).north", i, j, k);
                    sc_trace(tf, n->ack[xgetId(i,j,k)].north, label);
                    sprintf(label, "ack(%02d)(%02d)(%02d).up", i, j, k);
                    sc_trace(tf, n->ack[xgetId(i,j,k)].up, label);
                    sprintf(label, "ack(%02d)(%02d)(%02d).down", i, j, k);
                    sc_trace(tf, n->ack[xgetId(i,j,k)].down, label);
                }
	    }
	}
    }
    // Reset the chip and run the simulation
    reset.write(1);
    cout << "Reset for " << (int)(GlobalParams::reset_time) << " cycles... ";
    srand(GlobalParams::rnd_generator_seed);

    // fix clock periods different from 1ns
    //sc_start(GlobalParams::reset_time, SC_NS);
    sc_start(GlobalParams::reset_time * GlobalParams::clock_period_ps, SC_PS);

    reset.write(0);
    cout << " done! " << endl;
    cout << " Now running for " << GlobalParams:: simulation_time << " cycles..." << endl;
    // fix clock periods different from 1ns
    //sc_start(GlobalParams::simulation_time, SC_NS);
    sc_start(GlobalParams::simulation_time * GlobalParams::clock_period_ps, SC_PS);


    // Close the simulation
    if (GlobalParams::trace_mode) sc_close_vcd_trace_file(tf);
    cout << "Noxim simulation completed.";
    cout << " (" << sc_time_stamp().to_double() / GlobalParams::clock_period_ps << " cycles executed)" << endl;
    cout << endl;
//assert(false);
    // Show statistics
    GlobalStats gs(n.get());
    gs.showStats(std::cout, GlobalParams::detailed);


    if ((GlobalParams::max_volume_to_be_drained > 0) &&
	(sc_time_stamp().to_double() / GlobalParams::clock_period_ps - GlobalParams::reset_time >=
	 GlobalParams::simulation_time)) {
	cout << endl
         << "WARNING! the number of flits specified with -volume option" << endl
	     << "has not been reached. ( " << drained_volume << " instead of " << GlobalParams::max_volume_to_be_drained << " )" << endl
         << "You might want to try an higher value of simulation cycles" << endl
	     << "using -sim option." << endl;

#ifdef TESTING
	cout << endl
         << " Sum of local drained flits: " << gs.drained_total << endl
	     << endl
         << " Effective drained volume: " << drained_volume;
#endif

    }

    if (GlobalParams::drain_time > 0) {
        // Draining time
        GlobalParams::traffic_distribution = TRAFFIC_DRAIN;
        cout << "Starting draining." << endl;
        sc_start(GlobalParams::drain_time * GlobalParams::clock_period_ps, SC_PS);
        GlobalStats gsd(n.get());
        cout << "Post-draining statistics:" << endl;
        gsd.showStats(std::cout, GlobalParams::detailed);
    }
#ifdef DEADLOCK_AVOIDANCE
	cout << "***** WARNING: DEADLOCK_AVOIDANCE ENABLED!" << endl;
#endif
    return 0;
}
