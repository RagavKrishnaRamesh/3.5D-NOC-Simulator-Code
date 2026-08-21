/*
 * Noxim - the NoC Simulator
 *
 * (C) 2005-2018 by the University of Catania
 * For the complete list of authors refer to file ../doc/AUTHORS.txt
 * For the license applied to these sources refer to file ../doc/LICENSE.txt
 *
 * This file contains the implementation of the command line parser
 */

#include "ConfigurationManager.h"
#include <systemc.h> //Included for the function time()
#include "MultiNoC.h"

YAML::Node config;
YAML::Node power_config;

void loadConfiguration() {

    cout << "Loading configuration from file \"" << GlobalParams::config_filename << "\"...";
    try {
        config = YAML::LoadFile(GlobalParams::config_filename);
        cout << " Done" << endl;
    } catch (YAML::BadFile &e) {
        cout << " Failed" << endl;
        cerr << "The specified YAML configuration file was not found!" << endl;
        exit(0);
    } catch (YAML::ParserException &pe) {
        cout << " Failed" << endl;
        cerr << "ERROR at line " << pe.mark.line +1 << " column " << pe.mark.column + 1 << ": "<< pe.msg << ". Please check identation." << endl;
        exit(0);
    }

    cout << "Loading power configurations from file \"" << GlobalParams::power_config_filename << "\"...";
    try {
        power_config = YAML::LoadFile(GlobalParams::power_config_filename);
        cout << " Done" << endl;
    } catch (YAML::BadFile &e){
        cout << " Failed" << endl;
        cerr << "The specified YAML power configurations file was not found!" << endl;
        exit(0);
    } catch (YAML::ParserException &pe) {
        cout << " Failed" << endl;
        cerr << "ERROR at line " << pe.mark.line +1 << " column " << pe.mark.column + 1 << ": "<< pe.msg << ". Please check identation." << endl;
        exit(0);
    }

    // Initialize global configuration parameters (can be overridden with command-line arguments)
    GlobalParams::verbose_mode = readParam<string>(config, "verbose_mode");
    GlobalParams::trace_mode = readParam<bool>(config, "trace_mode");
    GlobalParams::trace_filename = readParam<string>(config, "trace_filename");

    GlobalParams::topology = readParam<string>(config, "topology", TOPOLOGY_MESH);

    //Mesh network params
    if (GlobalParams::topology == TOPOLOGY_MESH) {
        GlobalParams::mesh_dim_x = readParam<int>(config, "mesh_dim_x");
        GlobalParams::mesh_dim_y = readParam<int>(config, "mesh_dim_y");
        GlobalParams::mesh_dim_z = readParam<int>(config, "mesh_dim_z");
    }

    if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
    {
        vector<string> mesh_component_names;

        for (YAML::const_iterator cp  = config["multi_mesh"].begin();
                                  cp != config["multi_mesh"].end();
                                ++cp)
        {
            string mesh_name = cp->first.as<string>("");

            auto it = find(mesh_component_names.begin(),
                     mesh_component_names.end(), mesh_name);

            if (it == mesh_component_names.end()) {
                mesh_component_names.push_back(mesh_name);
                it = find(mesh_component_names.begin(),
                          mesh_component_names.end(), mesh_name);
            }

            YAML::Node hub_config_node = cp->second;
            // Use the 'tag' to communicate the current mesh name
            hub_config_node.SetTag(mesh_name);

            GlobalParams::mesh_component_config[mesh_name] =
                hub_config_node.as<MeshComponentConfig>();

            size_t id = distance(mesh_component_names.begin(), it);
            GlobalParams::mesh_component_config[mesh_name].mesh_id = id;

            const MeshComponentConfig& curr_config =
                GlobalParams::mesh_component_config[mesh_name];

            cout << "Configuration parsed for " << mesh_name << ":" << endl
                 << " dim x: " << curr_config.dim_x << endl
                 << " dim y: " << curr_config.dim_y << endl
                 << " dim z: " << curr_config.dim_z << endl
                 << " NoC id: " << curr_config.mesh_id << endl
                 << " vertical links placement: " << endl;

            for (auto& links_type : {curr_config.upward_links_placement,
                                     curr_config.downward_links_placement})
            {
                for (auto& name_links : links_type)
                {
                    for (auto& link : name_links.second)
                        cout << "  " << link.first << " (" << mesh_name
                             << ") => " << link.second << " ("
                             << name_links.first << ")" << endl;
                }
            }

            if (!curr_config.intra_links_placement.empty()) {
                cout << " intra-stack links placement: ";
                for (auto& lid : curr_config.intra_links_placement)
                    cout << lid << " ";
                cout << endl;
            }

            if (curr_config.upward_links_selection.size() ||
                curr_config.downward_links_selection.size() ||
                curr_config.intra_links_selection.size())
            {
                cout << " vertical links selection: " << endl;

                for (auto& links_type : {curr_config.upward_links_selection,
                                         curr_config.downward_links_selection})
                {
                    for (auto& name_links : links_type)
                    {
                        for (auto& link : name_links.second)
                            cout << "  " << link.first << " (" << mesh_name
                                 << " -> " << name_links.first << ") => "
                                 << link.second << " (" << mesh_name << ")" << endl;
                    }
                }

                for (auto& link : curr_config.intra_links_selection)
                    cout << "  " << link.first << " (" << mesh_name
                         << " -> intra) => " << link.second << " ("
                         << mesh_name << ")" << endl;
            }
        }
    }

	//Delta network params
    if (GlobalParams::topology == TOPOLOGY_BASELINE  ||
        GlobalParams::topology == TOPOLOGY_BUTTERFLY ||
        GlobalParams::topology == TOPOLOGY_OMEGA      ) {
        //GlobalParams::mesh_dim_x = readParam<int>(config, "mesh_dim_x");
        //GlobalParams::mesh_dim_y = readParam<int>(config, "mesh_dim_y");
        GlobalParams::n_delta_tiles = readParam<int>(config, "n_delta_tiles");
    }

    GlobalParams::r2r_link_length = readParam<double>(config, "r2r_link_length");
    GlobalParams::r2h_link_length = readParam<double>(config, "r2h_link_length");
    GlobalParams::buffer_depth = readParam<int>(config, "buffer_depth");
    GlobalParams::flit_size = readParam<int>(config, "flit_size");
    GlobalParams::min_packet_size = readParam<int>(config, "min_packet_size");
    GlobalParams::max_packet_size = readParam<int>(config, "max_packet_size");
    GlobalParams::routing_algorithm = readParam<string>(config, "routing_algorithm");
    GlobalParams::routing_table_filename = readParam<string>(config, "routing_table_filename"); 
    GlobalParams::selection_strategy = readParam<string>(config, "selection_strategy");
    GlobalParams::packet_injection_rate = readParam<double>(config, "packet_injection_rate");
    GlobalParams::probability_of_retransmission = readParam<double>(config, "probability_of_retransmission");
    GlobalParams::traffic_distribution = readParam<string>(config, "traffic_distribution");
    // For single packet traffic, we can specify the local src id and the local dst id
    if (GlobalParams::traffic_distribution == "TRAFFIC_SINGLE_PACKET")
    {
        GlobalParams::traffic_single_packet_src_id =
            readParam<int>(config, "traffic_single_packet_src_lid");
        GlobalParams::traffic_single_packet_dst_id =
            readParam<int>(config, "traffic_single_packet_dst_lid");

        if (GlobalParams::topology == TOPOLOGY_MULTI_MESH) {
            GlobalParams::traffic_single_packet_src_chip =
                readParam<string>(config, "traffic_single_packet_src_chip");
            GlobalParams::traffic_single_packet_dst_chip =
                readParam<string>(config, "traffic_single_packet_dst_chip");
        }
    }
    else if (GlobalParams::traffic_distribution == "TRAFFIC_LOCAL_CHIPLET")
    {
        GlobalParams::locality = readParam<double>(config, "traffic_localized_chiplet_ratio");
    }
    GlobalParams::traffic_table_filename = readParam<string>(config, "traffic_table_filename");
    GlobalParams::clock_period_ps = readParam<int>(config, "clock_period_ps");
    GlobalParams::simulation_time = readParam<int>(config, "simulation_time");
    GlobalParams::drain_time      = readParam<int>(config, "drain_time");
    GlobalParams::n_virtual_channels = readParam<int>(config, "n_virtual_channels");
    GlobalParams::reset_time = readParam<int>(config, "reset_time");
    GlobalParams::stats_warm_up_time = readParam<int>(config, "stats_warm_up_time");
    GlobalParams::rnd_generator_seed = time(NULL);
    GlobalParams::detailed = readParam<bool>(config, "detailed");
    GlobalParams::dyad_threshold = readParam<double>(config, "dyad_threshold");
    GlobalParams::max_volume_to_be_drained = readParam<unsigned int>(config, "max_volume_to_be_drained");
    //GlobalParams::hotspots;
    GlobalParams::show_buffer_stats = readParam<bool>(config, "show_buffer_stats");
    GlobalParams::use_winoc = readParam<bool>(config, "use_winoc");
    GlobalParams::winoc_dst_hops = readParam<int>(config, "winoc_dst_hops",0);
    GlobalParams::use_powermanager = readParam<bool>(config, "use_wirxsleep");
    GlobalParams::route_using_selection_strategy = readParam<bool>(config, "route_using_selection_strategy");
    GlobalParams::enable_vc_reallocation = readParam<bool>(config, "enable_vc_reallocation");

    set<int> channelSet;

    GlobalParams::default_hub_configuration = config["Hubs"]["defaults"].as<HubConfig>();

    for(YAML::const_iterator hubs_it = config["Hubs"].begin(); 
        hubs_it != config["Hubs"].end();
        ++hubs_it)
    {   
        int hub_id = hubs_it->first.as<int>(-1);
        if (hub_id < 0)
            continue;

        YAML::Node hub_config_node = hubs_it->second;

        GlobalParams::hub_configuration[hub_id] = hub_config_node.as<HubConfig>();

        copy(GlobalParams::hub_configuration[hub_id].rxChannels.begin(), GlobalParams::hub_configuration[hub_id].rxChannels.end(), inserter(channelSet, channelSet.end()));
        copy(GlobalParams::hub_configuration[hub_id].txChannels.begin(), GlobalParams::hub_configuration[hub_id].txChannels.end(), inserter(channelSet, channelSet.end()));
    }

    YAML::Node default_channel_config_node = config["RadioChannels"]["defaults"];
    GlobalParams::default_channel_configuration = default_channel_config_node.as<ChannelConfig>();

    for (set<int>::iterator it = channelSet.begin(); it != channelSet.end(); ++it) {
        GlobalParams::channel_configuration[*it] = default_channel_config_node.as<ChannelConfig>();
    }

    for(YAML::const_iterator channels_it= config["RadioChannels"].begin(); 
        channels_it != config["RadioChannels"].end();
        ++channels_it)
    {    
        int channel_id = channels_it->first.as<int>(-1);
        if (channel_id < 0)
            continue;

        YAML::Node channel_config_node = channels_it->second;

        GlobalParams::channel_configuration[channel_id] = channel_config_node.as<ChannelConfig>(); 
    }

    GlobalParams::power_configuration = power_config["Energy"].as<PowerConfig>();
}

void setBufferToTile(int depth)
{
    for(YAML::const_iterator hubs_it = config["Hubs"].begin(); hubs_it != config["Hubs"].end(); ++hubs_it)
    {   
        int hub_id = hubs_it->first.as<int>(-1);
        if (hub_id < 0)
            continue;

        YAML::Node hub_config_node = hubs_it->second;

	GlobalParams::hub_configuration[hub_id].toTileBufferSize = depth;

    }

}
void setBufferFromTile(int depth)
{
    for(YAML::const_iterator hubs_it = config["Hubs"].begin(); hubs_it != config["Hubs"].end(); ++hubs_it)
    {   
        int hub_id = hubs_it->first.as<int>(-1);
        if (hub_id < 0)
            continue;

        YAML::Node hub_config_node = hubs_it->second;

	GlobalParams::hub_configuration[hub_id].fromTileBufferSize = depth;

    }

}
void setBufferAntenna(int depth)
{
    for(YAML::const_iterator hubs_it = config["Hubs"].begin(); hubs_it != config["Hubs"].end(); ++hubs_it)
    {   
        int hub_id = hubs_it->first.as<int>(-1);
        if (hub_id < 0)
            continue;

        YAML::Node hub_config_node = hubs_it->second;

	GlobalParams::hub_configuration[hub_id].rxBufferSize = depth;
	GlobalParams::hub_configuration[hub_id].txBufferSize = depth;

    }

}


void showHelp(char selfname[])
{
    cout << "Usage: " << selfname << " [options]" << endl
         << "Where [options] is one or more of the following ones:" << endl
         << "\t-help\t\t\tShow this help and exit" << endl
         << "\t-config\t\t\tLoad the specified configuration file" << endl
         << "\t-power\t\t\tLoad the specified power configurations file" << endl
         << "\t-verbose N\t\tVerbosity level (1=low, 2=medium, 3=high)" << endl
         << "\t-trace FILENAME\t\tTrace signals to a VCD file named 'FILENAME.vcd'" << endl
         << "\t-dimx N\t\t\tSet the mesh X dimension" << endl
         << "\t-dimy N\t\t\tSet the mesh Y dimension" << endl
         << "\t-dimz N\t\t\tSet the mesh Z dimension" << endl
         << "\t-buffer N\t\tSet the depth of router input buffers [flits]" << endl
         << "\t-buffer_tt N\t\tSet the depth of hub buffers to tile [flits]" << endl
         << "\t-buffer_ft N\t\tSet the depth of hub buffers to tile [flits]" << endl
         << "\t-buffer_antenna N\tSet the depth of hub antenna buffers (RX/TX) [flits]" << endl
	 << "\t-vc N\t\t\tNumber of virtual channels" << endl
         << "\t-winoc\t\t\tEnable radio hub wireless transmission" << endl
         << "\t-winoc_dst_hops\t\t\tMax number of hops between target RadioHub and destination node" << endl
         << "\t-wirxsleep\t\tEnable radio hub wireless power manager" << endl
         << "\t-size Nmin Nmax\t\tSet the minimum and maximum packet size [flits]" << endl
         << "\t-flit N\t\t\tSet the flit size [bit]" << endl
         << "\t-topology TYPE\t\tSet the topology to one of the following:" << endl
         << "\t\tMESH\t\t2D Mesh" << endl
         << "\t\tBUTTERFLY\tDelta network Butterfly (radix 2)" << endl
         << "\t\tBASELINE\tDelta network Baseline" << endl
         << "\t\tOMEGA\t\tDelta network Omega" << endl
         << "\t-routing TYPE\t\tSet the routing algorithm to one of the following:" << endl
         << "\t\tXYZ\t\tXYZ routing algorithm" << endl
         << "\t\tWEST_FIRST\tWest-First routing algorithm" << endl
         << "\t\tNORTH_LAST\tNorth-Last routing algorithm" << endl
         << "\t\tNEGATIVE_FIRST\tNegative-First routing algorithm" << endl
         << "\t\tODD_EVEN\tOdd-Even routing algorithm" << endl
         << "\t\tDYAD T\t\tDyAD routing algorithm with threshold T" << endl
         << "\t\tTABLE_BASED FILENAME\tRouting Table Based routing algorithm with table in the specified file" << endl
         << "\t\tELEVATOR_FIRST\tElevator-First algorithm" << endl
         << "\t\tDEPTH_FIRST\tDepth-First algorithm" << endl
         << "\t-sel TYPE\t\tSet the selection strategy to one of the following:" << endl
         << "\t\tRANDOM\t\tRandom selection strategy" << endl
         << "\t\tBUFFER_LEVEL\tBuffer-Level Based selection strategy" << endl
         << "\t\tNOP\t\tNeighbors-on-Path selection strategy" << endl
         <<	"\t-pir R TYPE\t\tSet the packet injection rate R [0..1] and the time distribution TYPE where TYPE is one of the following:" << endl
         << "\t\tpoisson\t\tMemory-less Poisson distribution" << endl
         << "\t\tburst R\t\tBurst distribution with given real burstness" << endl
         << "\t\tpareto on off r\tSelf-similar Pareto distribution with given real parameters (alfa-on alfa-off r)" << endl
         << "\t\tcustom R\tCustom distribution with given real probability of retransmission" << endl
         << "\t-traffic TYPE\t\tSet the spatial distribution of traffic to TYPE where TYPE is one of the following:" << endl
         << "\t\trandom\t\tRandom traffic distribution" << endl
         << "\t\tlocal L\t\tRandom traffic with a fraction L (0..1) of packets having a destination connected to the local hub, i.e. not using wireless" << endl
         << "\t\tulocal\t\tRandom traffic with locality smooth distribution" << endl
         << "\t\ttranspose1\tTranspose matrix 1 traffic distribution" << endl
         << "\t\ttranspose2\tTranspose matrix 2 traffic distribution" << endl
         << "\t\tbitreversal\tBit-reversal traffic distribution" << endl
         << "\t\tbutterfly\tButterfly traffic distribution" << endl
         << "\t\tshuffle\t\tShuffle traffic distribution" << endl
         <<	"\t\ttable FILENAME\tTraffic Table Based traffic distribution with table in the specified file" << endl
         << "\t-hs ID P\t\tAdd node ID to hotspot nodes, with percentage P (0..1) (Only for 'random' traffic)" << endl
         << "\t-warmup N\t\tStart to collect statistics after N cycles" << endl
         << "\t-seed N\t\t\tSet the seed of the random generator (default time())" << endl
         << "\t-detailed\t\tShow detailed statistics" << endl
         << "\t-show_buf_stats\t\tShow buffers statistics" << endl
         << "\t-volume N\t\tStop the simulation when either the maximum number of cycles has been reached or N flits have" << endl
         << "\t\t\t\tbeen delivered" << endl
         << "\t-asciimonitor\t\tShow status of the network while running (experimental)" << endl
         << "\t-sim N\t\t\tRun for the specified simulation time [cycles]" << endl
         << endl
         << "If you find this program useful please don't forget to mention in your paper Maurizio Palesi <maurizio.palesi@unikore.it>" << endl
         <<	"If you find this program useless please feel free to complain with Davide Patti <davide.patti@dieei.unict.it>" << endl
         <<	"If you want to send money please feel free to PayPal to Fabrizio Fazzino <fabrizio@fazzino.it>" << endl
         <<	"and if need to solve any other problem of your life please contact Turi Monteleone <salvatore.monteleone@dieei.unict.it>" << endl;
}

void showConfig()
{
    cout << "Using the following configuration: " << endl
         << "- verbose_mode = " << GlobalParams::verbose_mode << endl
         << "- trace_mode = " << GlobalParams::trace_mode << endl
      // << "- trace_filename = " << GlobalParams::trace_filename << endl
         << "- mesh_dim_x = " << GlobalParams::mesh_dim_x << endl
         << "- mesh_dim_y = " << GlobalParams::mesh_dim_y << endl
         << "- mesh_dim_z = " << GlobalParams::mesh_dim_z << endl
         << "- buffer_depth = " << GlobalParams::buffer_depth << endl
         << "- n_virtual_channels = " << GlobalParams::n_virtual_channels << endl
         << "- max_packet_size = " << GlobalParams::max_packet_size << endl
         << "- routing_algorithm = " << GlobalParams::routing_algorithm << endl
      // << "- routing_table_filename = " << GlobalParams::routing_table_filename << endl
         << "- selection_strategy = " << GlobalParams::selection_strategy << endl
         << "- packet_injection_rate = " << GlobalParams::packet_injection_rate << endl
         << "- probability_of_retransmission = " << GlobalParams::probability_of_retransmission << endl
         << "- traffic_distribution = " << GlobalParams::traffic_distribution << endl
         << "- clock_period = " << GlobalParams::clock_period_ps << "ps" << endl
         << "- simulation_time = " << GlobalParams::simulation_time << endl
         << "- warm_up_time = " << GlobalParams::stats_warm_up_time << endl
         << "- rnd_generator_seed = " << GlobalParams::rnd_generator_seed << endl;
}

void checkConfiguration()
{
	if (GlobalParams::topology==TOPOLOGY_MESH)
	{
		if (GlobalParams::mesh_dim_x <= 1) {
			cerr << "Error: dimx must be greater than 1" << endl;
			exit(1);
		}

		if (GlobalParams::mesh_dim_y <= 1) {
			cerr << "Error: dimy must be greater than 1" << endl;
			exit(1);
		}
		if (GlobalParams::mesh_dim_z < 1) {
			cerr << "Error: dimz must be greater than 0" << endl;
			exit(1);
		}
		if (GlobalParams::winoc_dst_hops>0)
		{
			cerr << "Error: winoc_dst_hops currently supported only in delta topologies" << endl;
			exit(1);
		}
	}
        else if (GlobalParams::topology == TOPOLOGY_MULTI_MESH)
        {
                for (auto& mesh_component : GlobalParams::mesh_component_config) {
                        // check
                        const string& mesh_name = mesh_component.first;
                        MeshComponentConfig& config = mesh_component.second;
                        if (config.dim_x <= 1) {
                                cerr << "Error [" << mesh_name << "]: dimx must be greater than 1" << endl;
                                exit(1);
                        }
                        if (config.dim_y <= 1) {
                                cerr << "Error [" << mesh_name << "]: dimy must be greater than 1" << endl;
                                exit(1);
                        }
                        if (config.dim_z < 1) {
                                cerr << "Error [" << mesh_name << "]: dimz must be greater than 0" << endl;
                                exit(1);
                        }
                        if (config.n_virtual_channels > MAX_VIRTUAL_CHANNELS) {
	                        cerr << "Error [" << mesh_name << "]: number of virtual channels must be less than " << MAX_VIRTUAL_CHANNELS <<endl;
	                        exit(1);
                        }
                        if (config.n_virtual_channels < 1) {
	                        cerr << "Error [" << mesh_name << "]: number of virtual channels must be larger than 0" <<endl;
                                exit(1);
                        }

                        int mesh_dim = config.dim_x * config.dim_y * config.dim_z;
                        if (!config.intra_links_placement.empty() &&
                            config.dim_z < 2) {
                                cerr << "Error [" << mesh_name << "]: intra links placement is defined but dim_z < 2" << endl;
                                exit(1);
                        }
                        if (!config.intra_links_selection.empty() &&
                            config.dim_z < 2) {
                                cerr << "Error [" << mesh_name << "]: intra links selection is defined but dim_z < 2" << endl;
                                exit(1);
                        }
                        for (auto& lid : config.intra_links_placement) {
                                if (lid < 0 || lid >= mesh_dim) {
                                        cerr << "Error [" << mesh_name << "]: invalid intra link placement local id " << lid << endl;
                                        exit(1);
                                }
                        }
                        for (auto& sel : config.intra_links_selection) {
                                if (sel.first < 0 || sel.first >= mesh_dim ||
                                    sel.second < 0 || sel.second >= mesh_dim) {
                                        cerr << "Error [" << mesh_name << "]: invalid intra link selection pair [" << sel.first << ", " << sel.second << "]" << endl;
                                        exit(1);
                                }
                        }
                        if (!config.intra_links_selection.empty()) {
                                vector<int> src_count(mesh_dim, 0);
                                for (auto& sel : config.intra_links_selection) {
                                        src_count[sel.first]++;
                                        if (src_count[sel.first] > 1) {
                                                cerr << "Error [" << mesh_name << "]: duplicated intra selection source local id " << sel.first << endl;
                                                exit(1);
                                        }
                                }
                                for (int lid = 0; lid < mesh_dim; lid++) {
                                        if (src_count[lid] == 0) {
                                                cerr << "Error [" << mesh_name << "]: missing intra selection for source local id " << lid << endl;
                                                exit(1);
                                        }
                                }
                        }
                }
        }
	else // other delta topologies
	{
		int x = GlobalParams::n_delta_tiles;
		while( x != 1)
		{
			//checks whether a number is divisible by 2
			if(x % 2 != 0)
			{
				cerr << "Error: n_delta_tiles must be a power of 2 " << endl;
				exit(1);
			}
			x /= 2;
		}
		if (GlobalParams::routing_algorithm!="DELTA")
		{
			cerr << "Error: BUTTERFLY/OMEGA/BASELINE topologies only supported in DELTA routing algorithm " << endl;
			exit(1);
		}
	}

	if (GlobalParams::winoc_dst_hops>0) {
		if (GlobalParams::topology != TOPOLOGY_BUTTERFLY)
		{
			cerr << "Error: winoc_dst_hops currently supported only in BUTTERFLY topology" << endl;
            exit(1);
        }
		if (!GlobalParams::use_winoc)
		{
			cerr << "Error: winoc_dst_hops makes sense only when -winoc is enabled!" << endl;
			exit(1);
		}
	}

    if (GlobalParams::buffer_depth < 1) {
	cerr << "Error: buffer must be >= 1" << endl;
	exit(1);
    }
    if (GlobalParams::flit_size <= 0) {
	cerr << "Error: flit_size must be > 0" << endl;
	exit(1);
    }

    if (GlobalParams::min_packet_size < 2 ||
	GlobalParams::max_packet_size < 2) {
	cerr << "Error: packet size must be >= 2" << endl;
	exit(1);
    }

    if (GlobalParams::min_packet_size >
	GlobalParams::max_packet_size) {
	cerr << "Error: min packet size must be less than max packet size"
	    << endl;
	exit(1);
    }

    if (GlobalParams::selection_strategy.compare("INVALID_SELECTION") == 0) {
	cerr << "Error: invalid selection policy" << endl;
	exit(1);
    }

    if (GlobalParams::packet_injection_rate <= 0.0 ||
	GlobalParams::packet_injection_rate > 1.0) {
	cerr <<
	    "Error: packet injection rate mmust be in the interval ]0,1]"
	    << endl;
	exit(1);
    }

    for (unsigned int i = 0; i < GlobalParams::hotspots.size(); i++) {
	if (GlobalParams::topology==TOPOLOGY_MESH){
		if (GlobalParams::hotspots[i].first >=
		    GlobalParams::mesh_dim_x *
		    GlobalParams::mesh_dim_y *
		    GlobalParams::mesh_dim_z) {
		    cerr << "Error: hotspot node " << GlobalParams::
			hotspots[i].first << " is invalid (out of range)" << endl;
		    exit(1);
		}
	}
	else {
		if (GlobalParams::hotspots[i].first >= GlobalParams::n_delta_tiles){
		    cerr << "Error: hotspot node " << GlobalParams::hotspots[i].first << " is invalid (out of range)" << endl;
		    exit(1);
		}
	}

	if (GlobalParams::hotspots[i].second < 0.0
	    || GlobalParams::hotspots[i].second > 1.0) {
	    cerr <<
		"Error: hotspot percentage must be in the interval [0,1]"
		<< endl;
	    exit(1);
	}
    }

    if (GlobalParams::stats_warm_up_time < 0) {
	cerr << "Error: warm-up time must be positive" << endl;
	exit(1);
    }

    if (GlobalParams::simulation_time < 0) {
	cerr << "Error: simulation time must be positive" << endl;
	exit(1);
    }
    if (GlobalParams::n_virtual_channels > MAX_VIRTUAL_CHANNELS) {
	cerr << "Error: number of virtual channels must be less than " << MAX_VIRTUAL_CHANNELS <<endl;
	exit(1);
    }

    if (GlobalParams::stats_warm_up_time >
	GlobalParams::simulation_time) {
	cerr << "Error: warmup time must be less than simulation time" <<
	    endl;
	exit(1);
    }

    if (GlobalParams::locality<0 || GlobalParams::locality>1)
    {
	cerr << "Error: traffic locality must be in the range 0..1" << endl;
	exit(1);
    }


    if (GlobalParams::n_virtual_channels>1 && GlobalParams::selection_strategy.compare("NOP")==0)
    {
	cerr << "Error: NoP selection strategy can be used only with a single virtual channel" << endl;
	exit(1);
    }

    /*if (GlobalParams::n_virtual_channels>1 && GlobalParams::selection_strategy.compare("BUFFER_LEVEL")==0)
    {
	cerr << "Error: Buffer level selection strategy can be used only with a single virtual channel" << endl;
	exit(1);
    }*/
    if (GlobalParams::n_virtual_channels>MAX_VIRTUAL_CHANNELS) 
    {
	cerr << "Error: cannot use more than " << MAX_VIRTUAL_CHANNELS << " virtual channels." << endl
	     << "If you need more vc please modify the MAX_VIRTUAL_CHANNELS definition in " << endl
	     << "GlobalParams.h and compile again " << endl;
	exit(1);
    }
    if (GlobalParams::n_virtual_channels>1 && GlobalParams::use_powermanager)
    {
	cerr << "Error: Power manager (-wirxsleep) option only supports a single virtual channel" << endl;
	exit(1);
    }

    if (GlobalParams::ascii_monitor)
    {
#ifdef DEBUG
	cerr << "-ascii_monitor option need DEBUG flag to be disabled in Makefile " << endl;
	exit(1);
#endif
    }

    if (GlobalParams::traffic_distribution == "TRAFFIC_SINGLE_PACKET")
    {
        if (GlobalParams::topology == TOPOLOGY_MULTI_MESH) {
            // Test if chip id exists
            vector<string> noc_names = MeshNoC::retrieveNoCsNames();
            auto it_src_chip = find(
                noc_names.begin(),
                noc_names.end(),
                GlobalParams::traffic_single_packet_src_chip
            );
            auto it_dst_chip = find(
                noc_names.begin(),
                noc_names.end(),
                GlobalParams::traffic_single_packet_dst_chip
            );
            sc_assert(it_src_chip != noc_names.end() && "Incorrect single packet src chip");
            sc_assert(it_dst_chip != noc_names.end() && "Incorrect single packet dst chip");

            // Test if local src/dst ids are legal
            MeshComponentConfig& src_config = MultiNoC::retrieveMeshConfig(
                GlobalParams::traffic_single_packet_src_chip
            );
            MeshComponentConfig& dst_config = MultiNoC::retrieveMeshConfig(
                GlobalParams::traffic_single_packet_dst_chip
            );
            int mesh_dim_src = src_config.dim_x * src_config.dim_y *
                               src_config.dim_z;
            int mesh_dim_dst = dst_config.dim_x * dst_config.dim_y *
                               dst_config.dim_z;
            sc_assert(GlobalParams::traffic_single_packet_src_id < mesh_dim_src &&
                      "Illegal single packet src id");
            sc_assert(GlobalParams::traffic_single_packet_dst_id < mesh_dim_dst &&
                      "Illegal single packet dst id");
        }
        else {
            int mesh_dim = GlobalParams::mesh_dim_x * GlobalParams::mesh_dim_y *
                           GlobalParams::mesh_dim_z;
            sc_assert(GlobalParams::traffic_single_packet_src_id < mesh_dim &&
                      "Illegal single packet src id");
            sc_assert(GlobalParams::traffic_single_packet_dst_id < mesh_dim &&
                      "Illegal single packet dst id");
        }
    }
}

void parseCmdLine(int arg_num, char *arg_vet[])
{
    if (arg_num == 1)
	cout <<
	    "Running with default parameters (use '-help' option to see how to override them)"
	    << endl;
    else 
    {
	for (int i = 1; i < arg_num; i++) 
	{
	    if (!strcmp(arg_vet[i], "-verbose"))
		GlobalParams::verbose_mode = atoi(arg_vet[++i]);
	    else if (!strcmp(arg_vet[i], "-trace")) 
	    {
		GlobalParams::trace_mode = true;
		GlobalParams::trace_filename = arg_vet[++i];
	    } 
	    else if (!strcmp(arg_vet[i], "-dimx"))
		GlobalParams::mesh_dim_x = atoi(arg_vet[++i]);
	    else if (!strcmp(arg_vet[i], "-dimy"))
		GlobalParams::mesh_dim_y = atoi(arg_vet[++i]);
	    else if (!strcmp(arg_vet[i], "-dimz"))
		GlobalParams::mesh_dim_z = atoi(arg_vet[++i]);

	    else if (!strcmp(arg_vet[i], "-dtiles"))
		GlobalParams::n_delta_tiles = atoi(arg_vet[++i]);

	    else if (!strcmp(arg_vet[i], "-buffer"))
		GlobalParams::buffer_depth = atoi(arg_vet[++i]);
	    else if (!strcmp(arg_vet[i], "-buffer_tt"))
		setBufferToTile(atoi(arg_vet[++i]));
	    else if (!strcmp(arg_vet[i], "-buffer_ft"))
		setBufferFromTile(atoi(arg_vet[++i]));
	    else if (!strcmp(arg_vet[i], "-buffer_antenna"))
		setBufferAntenna(atoi(arg_vet[++i]));
	    else if (!strcmp(arg_vet[i], "-vc"))
		GlobalParams::n_virtual_channels = (atoi(arg_vet[++i]));
	    else if (!strcmp(arg_vet[i], "-flit"))
		GlobalParams::flit_size = atoi(arg_vet[++i]);
	    else if (!strcmp(arg_vet[i], "-winoc")) 
		GlobalParams::use_winoc = true;
	    else if (!strcmp(arg_vet[i], "-winoc_dst_hops")) 
	    {
            GlobalParams::winoc_dst_hops = atoi(arg_vet[++i]);
	    }
	    else if (!strcmp(arg_vet[i], "-wirxsleep")) 
	    {
		GlobalParams::use_powermanager = true;
	    }
	    else if (!strcmp(arg_vet[i], "-size")) 
	    {
		GlobalParams::min_packet_size = atoi(arg_vet[++i]);
		GlobalParams::max_packet_size = atoi(arg_vet[++i]);
	    } 
	    else if (!strcmp(arg_vet[i], "-topology")) 
	    {
		    GlobalParams::topology = arg_vet[++i];
            cout << "Changing topology to " << GlobalParams::topology << endl;
        }
	    else if (!strcmp(arg_vet[i], "-routing")) 
	    {
		GlobalParams::routing_algorithm = arg_vet[++i];
		if (GlobalParams::routing_algorithm == ROUTING_DYAD)
		    GlobalParams::dyad_threshold = atof(arg_vet[++i]);
		else if (GlobalParams::routing_algorithm == ROUTING_TABLE_BASED) 
		{
		    GlobalParams::routing_table_filename = arg_vet[++i];
		    GlobalParams::packet_injection_rate = 0;
		} 
	    } 
	    else if (!strcmp(arg_vet[i], "-sel")) {
		GlobalParams::selection_strategy = arg_vet[++i];
	    } 
	    else if (!strcmp(arg_vet[i], "-pir")) 
	    {
		
		GlobalParams::packet_injection_rate = atof(arg_vet[++i]);
		char *distribution = arg_vet[i+1<arg_num?++i:i];
		
		if (!strcmp(distribution, "poisson"))
		    GlobalParams::probability_of_retransmission = GlobalParams::packet_injection_rate;
		else if (!strcmp(distribution, "burst")) 
		{
		    double burstness = atof(arg_vet[++i]);
		    GlobalParams::probability_of_retransmission = GlobalParams::packet_injection_rate / (1 - burstness);
		} 
		else if (!strcmp(distribution, "pareto")) {
		    double Aon = atof(arg_vet[++i]);
		    double Aoff = atof(arg_vet[++i]);
		    double r = atof(arg_vet[++i]);
		    GlobalParams::probability_of_retransmission =
			GlobalParams::packet_injection_rate *
			pow((1 - r), (1 / Aoff - 1 / Aon));
		} 
		else if (!strcmp(distribution, "custom"))
		    GlobalParams::probability_of_retransmission = atof(arg_vet[++i]);
		else assert("Invalid pir format" && false);
	    } 
	    else if (!strcmp(arg_vet[i], "-traffic")) 
	    {
		char *traffic = arg_vet[++i];
		if (!strcmp(traffic, "random")) GlobalParams::traffic_distribution = TRAFFIC_RANDOM;
		else if (!strcmp(traffic, "transpose1"))
		    GlobalParams::traffic_distribution =
			TRAFFIC_TRANSPOSE1;
		else if (!strcmp(traffic, "transpose2"))
		    GlobalParams::traffic_distribution =
			TRAFFIC_TRANSPOSE2;
		else if (!strcmp(traffic, "bitreversal"))
		    GlobalParams::traffic_distribution =
			TRAFFIC_BIT_REVERSAL;
		else if (!strcmp(traffic, "butterfly"))
		    GlobalParams::traffic_distribution =
			TRAFFIC_BUTTERFLY;
		else if (!strcmp(traffic, "shuffle"))
		    GlobalParams::traffic_distribution =
			TRAFFIC_SHUFFLE;
		else if (!strcmp(traffic, "ulocal"))
		    GlobalParams::traffic_distribution =
			TRAFFIC_ULOCAL;
		else if (!strcmp(traffic, "table")) {
		    GlobalParams::traffic_distribution =
			TRAFFIC_TABLE_BASED;
		    GlobalParams::traffic_table_filename = arg_vet[++i];
		} else if (!strcmp(traffic, "local_chiplet")) {
		    GlobalParams::traffic_distribution = TRAFFIC_LOCAL_CHIPLET;
		    GlobalParams::locality=atof(arg_vet[++i]);
		} else if (!strcmp(traffic, "local")) {
		    GlobalParams::traffic_distribution = TRAFFIC_LOCAL;
		    GlobalParams::locality=atof(arg_vet[++i]);
		} else if (!strcmp(traffic, "singlepacket")) {
		    GlobalParams::traffic_distribution = TRAFFIC_SINGLE_PACKET;
		}
		else assert(false);
	    }
            else if (!strcmp(arg_vet[i], "-tsp_src_lid"))
		GlobalParams::traffic_single_packet_src_id = atoi(arg_vet[++i]);
            else if (!strcmp(arg_vet[i], "-tsp_dst_lid"))
		GlobalParams::traffic_single_packet_dst_id = atoi(arg_vet[++i]);
            else if (!strcmp(arg_vet[i], "-tsp_src_chip"))
		GlobalParams::traffic_single_packet_src_chip = string(arg_vet[++i]);
            else if (!strcmp(arg_vet[i], "-tsp_dst_chip"))
		GlobalParams::traffic_single_packet_dst_chip = string(arg_vet[++i]);
	    else if (!strcmp(arg_vet[i], "-hs")) 
	    {
		int node = atoi(arg_vet[++i]);
		double percentage = atof(arg_vet[++i]);
		pair < int, double >t(node, percentage);
		GlobalParams::hotspots.push_back(t);
	    } 
	    else if (!strcmp(arg_vet[i], "-warmup"))
		GlobalParams::stats_warm_up_time = atoi(arg_vet[++i]);
	    else if (!strcmp(arg_vet[i], "-seed"))
		GlobalParams::rnd_generator_seed = atoi(arg_vet[++i]);
	    else if (!strcmp(arg_vet[i], "-detailed"))
		GlobalParams::detailed = true;
	    else if (!strcmp(arg_vet[i], "-show_buf_stats"))
		GlobalParams::show_buffer_stats = true;
	    else if (!strcmp(arg_vet[i], "-volume"))
		GlobalParams::max_volume_to_be_drained =
		    atoi(arg_vet[++i]);
	    else if (!strcmp(arg_vet[i], "-sim"))
		GlobalParams::simulation_time = atoi(arg_vet[++i]);
	    else if (!strcmp(arg_vet[i], "-asciimonitor")) 
		GlobalParams::ascii_monitor = true;
	    else if (!strcmp(arg_vet[i], "-config") || !strcmp(arg_vet[i], "-power"))
		// -config is managed from configure function
		// i++ skips the configuration file name 
		i++;
	    else {
		cerr << "Error: Invalid option: " << arg_vet[i] << endl;
		exit(1);
	    }
	}
    }

}


void configure(int arg_num, char *arg_vet[]) {

    bool config_found = false;
    bool power_config_found = false;

    for (int i = 1; i < arg_num; i++) {
	    if (!strcmp(arg_vet[i], "-help")) {
		showHelp(arg_vet[0]);
		exit(0);
        }
    }

    for (int i = 1; i < arg_num; i++) {
	    if (!strcmp(arg_vet[i], "-config")) {
            GlobalParams::config_filename = arg_vet[++i];
            config_found = true;
            break;
        }
    }

    if (!config_found)
    {
        std::ifstream infile(CONFIG_FILENAME);
        if (infile.good())
            GlobalParams::config_filename = CONFIG_FILENAME;
        else
        {
            cerr << "No YAML configuration file found!\n Use -config to load examples from config_examples folder" << endl;
            exit(0);
        }
    }

    for (int i = 1; i < arg_num; i++) {
	    if (!strcmp(arg_vet[i], "-power")) {
            GlobalParams::power_config_filename = arg_vet[++i];
            power_config_found = true;
            break;
        }
    }

    if (!power_config_found)
    {
        std::ifstream infile(POWER_CONFIG_FILENAME);
        if (infile.good())
            GlobalParams::power_config_filename = POWER_CONFIG_FILENAME;
        else
        {
            cerr << "No YAML power configurations file found!\n Use -power to load examples from config_examples folder" << endl;
            exit(0);
        }
    }

    loadConfiguration();
    parseCmdLine(arg_num, arg_vet);

    checkConfiguration();

    // Show configuration
    if (GlobalParams::verbose_mode > VERBOSE_OFF)
	showConfig();
}

template <typename T> 
T readParam(YAML::Node node, string param, T default_value) {
   try {
       return node[param].as<T>();
   } catch(exception &e) {
       /*
       cerr << "WARNING: parameter " << param << " not present in YAML configuration file." << endl;
       cerr << "Using command line value or default value " << default_value << endl;
        */
       return default_value;
   }
}

template <typename T> 
T readParam(YAML::Node node, string param) {
   try {
       return node[param].as<T>();
   } catch(exception &e) {
       cerr << "ERROR: Cannot read param " << param << ". " << endl;
       exit(0);
   }
}
