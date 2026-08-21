# 2D5 Baseline: Avg latency versus PIR for Depth-First (I:1,C:2), DeFT (I:2,C:2), VDA (I:2,C:2) with Uniform Traffic
python3 ./performance_plot.py -o soa_comparison_uniform.pdf depth_first_0/2d5DepthFirstUniform.csv depth_first_0/2d5DEFTUniform.csv depth_first_0/2d5VDAUniform.csv --names Depth-First DeFT VDA
python3 ./performance_avg_delay_plot.py -o soa_comparison_avg_delay_uniform.pdf depth_first_0/2d5DepthFirstUniform.csv depth_first_0/2d5DEFTUniform.csv depth_first_0/2d5VDAUniform.csv --names Depth-First DeFT VDA

# 2D5 Baseline: Avg latency versus PIR for Depth-First (I:1,C:2), DeFT (I:2,C:2), VDA (I:2,C:2) with Localized Traffic
python3 ./performance_plot.py -o soa_comparison_localized.pdf depth_first_0/2d5DepthFirstLocalized.csv depth_first_0/2d5DEFTLocalized.csv depth_first_0/2d5VDALocalized.csv --names Depth-First DeFT VDA
python3 ./performance_avg_delay_plot.py -o soa_comparison_avg_delay_localized.pdf depth_first_0/2d5DepthFirstLocalized.csv depth_first_0/2d5DEFTLocalized.csv depth_first_0/2d5VDALocalized.csv --names Depth-First DeFT VDA

# 3D5 Baseline: Avg latency versus PIR for Random Uniform and Localized Traffic
python3 ./performance_plot.py -o depth_first_3d5_localized_uniform.pdf depth_first_1/3d5Localized25.csv depth_first_1/3d5Localized50.csv depth_first_1/3d5Localized75.csv depth_first_1/3d5Uniform.csv --names "25% Intra-chiplet" "50% Intra-chiplet" "75% Intra-chiplet" "Random Uniform"
python3 ./performance_avg_delay_plot.py -o depth_first_3d5_localized_uniform_avg_delay.pdf depth_first_1/3d5Localized25.csv depth_first_1/3d5Localized50.csv depth_first_1/3d5Localized75.csv depth_first_1/3d5Uniform.csv --names "25% Intra-chiplet" "50% Intra-chiplet" "75% Intra-chiplet" "Random Uniform"

# 3D5 Baseline: Removing VLs between base interposer and IODs, Localized Traffic
python3 ./performance_plot.py -o depth_first_localized_vl_interposer.pdf depth_first_1/3d5Localized50.csv depth_first_2/3d5Localized5025.csv depth_first_2/3d5Localized5050.csv depth_first_2/3d5Localized5075.csv --names "No VL Removed" "25% VLs Removed" "50% VLs Removed" "75% VLs Removed"
python3 ./performance_avg_delay_plot.py -o depth_first_localized_vl_interposer_avg_delay.pdf depth_first_1/3d5Localized50.csv depth_first_2/3d5Localized5025.csv depth_first_2/3d5Localized5050.csv depth_first_2/3d5Localized5075.csv --names "No VL Removed" "25% VLs Removed" "50% VLs Removed" "75% VLs Removed"

# 3D5 Baseline: Removing VLs between base interposer and IODs, Uniform Traffic
python3 ./performance_plot.py -o depth_first_uniform_vl_interposer.pdf depth_first_1/3d5Uniform.csv depth_first_2/3d5Uniform25.csv depth_first_2/3d5Uniform50.csv depth_first_2/3d5Uniform75.csv --names "No VL Removed" "25% VLs Removed" "50% VLs Removed" "75% VLs Removed"
python3 ./performance_avg_delay_plot.py -o depth_first_uniform_vl_interposer_avg_delay.pdf depth_first_1/3d5Uniform.csv depth_first_2/3d5Uniform25.csv depth_first_2/3d5Uniform50.csv depth_first_2/3d5Uniform75.csv --names "No VL Removed"  "25% VLs Removed" "50% VLs Removed" "75% VLs Removed"

# 3D5 Baseline: Removing VLs between IODs and upper chiplets, Localized Traffic
python3 ./performance_plot.py -o depth_first_localized_vl_iod.pdf depth_first_1/3d5Localized50.csv depth_first_3/3d5Localized5025.csv depth_first_3/3d5Localized5050.csv depth_first_3/3d5Localized5075.csv --names "No VL Removed" "25% VLs Removed" "50% VLs Removed" "75% VLs Removed"
python3 ./performance_avg_delay_plot.py -o depth_first_localized_vl_iod_avg_delay.pdf depth_first_1/3d5Localized50.csv depth_first_3/3d5Localized5025.csv depth_first_3/3d5Localized5050.csv depth_first_3/3d5Localized5075.csv --names "No VL Removed" "25% VLs Removed" "50% VLs Removed" "75% VLs Removed"

# 3D5 Baseline: Removing VLs between IODs and upper chiplets, Random Uniform Traffic
python3 ./performance_plot.py -o depth_first_uniform_vl_iod.pdf depth_first_1/3d5Uniform.csv depth_first_3/3d5Uniform25.csv  depth_first_3/3d5Uniform50.csv depth_first_3/3d5Uniform75.csv --names "No VL Removed" "25% VLs Removed" "50% VLs Removed" "75% VLs Removed"
python3 ./performance_avg_delay_plot.py -o depth_first_uniform_vl_iod_avg_delay.pdf depth_first_1/3d5Uniform.csv depth_first_3/3d5Uniform25.csv depth_first_3/3d5Uniform50.csv depth_first_3/3d5Uniform75.csv --names "No VL Removed" "25% VLs Removed" "50% VLs Removed" "75% VLs Removed"

# 3D5 Baseline: More IODs+Acc chiplets, Localized Traffic
python3 ./performance_plot.py -o depth_first_localized_more_iod.pdf depth_first_1/3d5Localized50.csv  depth_first_4/3d5Localized504C.csv depth_first_4/3d5Localized505C.csv --names "Baseline (3 IODs)" "+1 IODs (2 Acc)" "+2 IODs (4 Acc)"
python3 ./performance_avg_delay_plot.py -o depth_first_localized_more_iod_avg_delay.pdf depth_first_1/3d5Localized50.csv  depth_first_4/3d5Localized504C.csv depth_first_4/3d5Localized505C.csv --names "Baseline (3 IODs)" "+1 IODs (2 Acc)" "+2 IODs (4 Acc)"

# 3D5 Baseline: More IODs+Acc chiplets, Random Uniform Traffic
python3 ./performance_plot.py -o depth_first_uniform_more_iod.pdf depth_first_1/3d5Uniform.csv depth_first_4/3d5Uniform4C.csv depth_first_4/3d5Uniform5C.csv --names "Baseline (3 IODs)" "+1 IODs (2 Acc)" "+2 IODs (4 Acc)"
python3 ./performance_avg_delay_plot.py -o depth_first_uniform_more_iod_avg_delay.pdf depth_first_1/3d5Uniform.csv depth_first_4/3d5Uniform4C.csv depth_first_4/3d5Uniform5C.csv --names "Baseline (3 IODs)" "+1 IODs (2 Acc)" "+2 IODs (4 Acc)"

# 3D5 Baseline: VLs selection: Nearest vs Optimized
python3 ./performance_plot.py -o depth_first_localized_uniform_vl_strategy.pdf depth_first_5/3d5BaselineLocalized.csv depth_first_5/3d5VLMappingLocalized.csv depth_first_5/3d5BaselineUniform.csv depth_first_5/3d5VLMappingUniform.csv --names "Nearest VLs - 50% Intra-chiplet" "Optimized VLs - 50% Intra-chiplet" "Nearest VLs - Random Uniform" "Optimized VLs - Random Uniform"
python3 ./performance_avg_delay_plot.py -o depth_first_localized_uniform_vl_strategy_avg_delay.pdf depth_first_5/3d5BaselineLocalized.csv depth_first_5/3d5VLMappingLocalized.csv depth_first_5/3d5BaselineUniform.csv depth_first_5/3d5VLMappingUniform.csv --names "Nearest VLs - 50% Intra-chiplet" "Optimized VLs - 50% Intra-chiplet" "Nearest VLs - Random Uniform" "Optimized VLs - Random Uniform"

# Runtime Execution Comparison: MILP vs Exhaustive search
python3 vlink_selection/plot_method_comparison.py milp_vs_rexhaustive.csv milp_vs_rexhaustive.pdf

