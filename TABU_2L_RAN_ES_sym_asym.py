import math
import numpy as np
import random
import sys
import time
import resource

#SEED = 10
#random.seed(SEED)
#np.random.seed(SEED)

valid_edges=[]
adj_matrix=[]
num_rows=0
num_cols=0
n=0
# gb_best_effective_cost = float('inf')
# Detect whether the input graph should be treated as symmetric.
def is_symmetric_matrix(adj_matrix, tolerance=1e-9):
    size = adj_matrix.shape[0]
    for i in range(size):
        for j in range(i + 1, size):
            left = adj_matrix[i][j]
            right = adj_matrix[j][i]

            if np.isinf(left) and np.isinf(right):
                continue
            if np.isinf(left) != np.isinf(right):
                return False
            if not np.isclose(left, right, atol=tolerance, rtol=0.0):
                return False

    return True

# Parsing input file
def parse_input_file(filename):
    try:
        with open(filename, 'r') as file:
            lines = file.readlines()
        num_nodes = int(lines[0].strip())
        adj_matrix = []
        matrix_lines = lines[1:1 + num_nodes]
        for line in matrix_lines:
            adj_matrix.append([float(x) if x.upper() != 'INF' else float('inf') for x in line.split()])
        adj_matrix = np.array(adj_matrix, dtype=float)
        return num_nodes, adj_matrix, is_symmetric_matrix(adj_matrix)
    except Exception as e:
        print(f"Error in parsing input file: {e}")
        raise

# TSV Placement on 2D grid
def generate_tsv_placements_2d(num_rows, num_cols, num_tsvs):
    print("Generating TSV placements on a 2D grid...")

    if num_rows <= 0 or num_cols <= 0:
        raise ValueError("Number of rows and columns must be positive integers.")

    if num_tsvs <= 0 or num_tsvs > num_rows * num_cols:
        raise ValueError("Number of TSVs must be a positive integer and cannot exceed the total grid capacity.")

    tsv_placements = np.zeros((num_rows, num_cols), dtype=int)

    def is_valid_placement(x, y):
        for i in range(max(0, x-1), min(num_rows, x+2)):
            for j in range(max(0, y-1), min(num_cols, y+2)):
                if tsv_placements[i, j] == 1 and (i == x or j == y):
                    return False
        return True

    placed_tsvs = 0
    attempts = 0
    max_attempts = num_rows * num_cols * 10

    while placed_tsvs < num_tsvs and attempts < max_attempts:
        x = random.randint(0, num_rows - 1)
        y = random.randint(0, num_cols - 1)
        if is_valid_placement(x, y):
            tsv_placements[x, y] = 1
            placed_tsvs += 1
        attempts += 1

    if attempts >= max_attempts:
        print("Warning: Max attempts reached. Could not place all TSVs.")
        return tsv_placements.flatten(), tsv_placements, False

    return tsv_placements.flatten(), tsv_placements, True

# Generate coordinates for routers in 3D space
def generate_coordinates(num_layers, num_rows, num_cols):
    coordinates = {}
    for z in range(num_layers):
        for y in range(num_rows):
            for x in range(num_cols):
                router_index = z * num_rows * num_cols + y * num_cols + x
                coordinates[router_index] = (x, y, z)
    return coordinates


# Assign TSV routers  ##for Random assignment
def generate_tsv_assignment(n, num_layers, num_rows, num_cols, core_to_router, valid_edges, router_coordinates):
    nodes_per_layer = num_rows * num_cols
    tsv_assignment = [0] * n
    # Apply 25% TSV density constraint
    if nodes_per_layer <= 6:
        num_tsvs=1
    else:
        max_tsvs_25_percent = max(1, nodes_per_layer // 4)
        upper_bound = min(nodes_per_layer - 1, max_tsvs_25_percent)
        num_tsvs=random.randint(2,upper_bound)
    
    print(f"Using {num_tsvs} TSVs (min 2, max 25% of {nodes_per_layer} nodes per layer)")   
    tsv_placements_flat, tsv_placements_2d, valid = generate_tsv_placements_2d(num_rows, num_cols, num_tsvs)

    if not valid:
        print("Failed to generate valid TSV placements.")
        tsv_placements_flat, tsv_placements_2d, valid = generate_tsv_placements_2d(num_rows, num_cols, num_tsvs)

    print(f"TSV Placement Array (1D): {tsv_placements_flat}")
    print(f"TSV Placement Grid (2D):\n{tsv_placements_2d}")

    layer_tsv_routers = {}
    for layer in range(num_layers):
        start_index = layer * nodes_per_layer
        end_index = start_index + nodes_per_layer
        layer_tsv_routers[layer] = [start_index + i for i, val in enumerate(tsv_placements_flat) if val == 1]

    print(f"Layer TSV Routers Dictionary: {layer_tsv_routers}")

    # Calculate the limit for assignments based on actual traffic
    max_assignments_per_tsv = math.ceil(nodes_per_layer / num_tsvs)
    print(f"Balancing TSV assignments with max {max_assignments_per_tsv} routers per TSV ")
    
    # ============ DEADLOCK-FREE TSV ASSIGNMENT (REDELF Ruleset B) ============
    # Rule B1: Each router can only use TSVs that are south-or-due-east of it
    # Rule B2: If no valid TSV exists, use the pivot TSV (Def. 12)
    # Rule B3: If a TSV chosen by B1 (not self-node) is south-or-due-east of the
    #          pivot in the opposite direction, use the pivot instead.
    #          NOTE: In our pillar model (same positions for up/down), up-pivot =
    #          down-pivot = southernmost-easternmost TSV, so no other TSV can be
    #          south-or-due-east of it. B3 is included for REDELF completeness
    #          but will never trigger in this architecture.
    # This eliminates WU, WD, NU, ND turns and guarantees deadlock freedom.
    
    def get_valid_tsvs_for_router(router_local_idx, tsv_local_indices, num_cols_local, num_rows_local):
        """Return TSVs that are south-or-due-east of the router (REDELF Rule B1)."""
        router_x = router_local_idx % num_cols_local
        router_y = router_local_idx // num_cols_local
        
        valid = []
        for tsv_local in tsv_local_indices:
            tsv_x = tsv_local % num_cols_local
            tsv_y = tsv_local // num_cols_local
            
            # South-or-due-east: same position, OR south (y > router_y), OR due-east (same row, x > router_x)
            if (tsv_x == router_x and tsv_y == router_y):
                valid.append(tsv_local)
            elif tsv_y > router_y:  # south
                valid.append(tsv_local)
            elif tsv_y == router_y and tsv_x > router_x:  # due-east
                valid.append(tsv_local)
        return valid
    
    def get_pivot_tsv(tsv_local_indices, num_cols_local):
        """Return the pivot TSV (southernmost, then easternmost) - REDELF Def. 12.
        The pivot has no other TSV to its south-or-due-east."""
        best_tsv = None
        best_y, best_x = -1, -1
        for tsv_local in tsv_local_indices:
            tsv_x = tsv_local % num_cols_local
            tsv_y = tsv_local // num_cols_local
            if (tsv_y > best_y) or (tsv_y == best_y and tsv_x > best_x):
                best_y, best_x = tsv_y, tsv_x
                best_tsv = tsv_local
        return best_tsv

    def apply_rule_b3(selected_tsv_local, router_local_idx, pivot_local, num_cols_local):
        """REDELF Rule B3: If a TSV chosen by B1 is NOT at the self-node AND is
        south-or-due-east of the pivot (opposite-direction pivot), redirect to
        the pivot instead. In our pillar model up-pivot == down-pivot, so no TSV
        can be south-or-due-east of the pivot (it is already the most south-east).
        This check is defensive and included for full REDELF compliance."""
        if selected_tsv_local == router_local_idx:
            return selected_tsv_local  # self-node exemption
        sel_x = selected_tsv_local % num_cols_local
        sel_y = selected_tsv_local // num_cols_local
        piv_x = pivot_local % num_cols_local
        piv_y = pivot_local // num_cols_local
        is_south_of_pivot = sel_y > piv_y
        is_due_east_of_pivot = (sel_y == piv_y and sel_x > piv_x)
        if is_south_of_pivot or is_due_east_of_pivot:
            return pivot_local  # B3 redirect
        return selected_tsv_local
    
    # Get TSV base indices (local to layer)
    tsv_base_indices = [i for i, val in enumerate(tsv_placements_flat) if val == 1]
    pivot_tsv_local = get_pivot_tsv(tsv_base_indices, num_cols)
    print(f"Pivot TSV (local index): {pivot_tsv_local}")
    
    # Track assignments for each TSV
    tsv_assignment_count = {}
    
    for layer in range(num_layers):
        start_index = layer * nodes_per_layer
        my_list = layer_tsv_routers[layer]
        
        # Initialize assignment count for each TSV
        for tsv in my_list:
            tsv_assignment_count[tsv] = 0
        
        # Shuffle routers for randomization while maintaining balance
        router_indices = list(range(nodes_per_layer))
        random.shuffle(router_indices)
        
        for i in router_indices:
            # Get valid TSVs (south-or-due-east) for this router - Rule B1
            valid_tsv_locals = get_valid_tsvs_for_router(i, tsv_base_indices, num_cols, num_rows)
            valid_tsvs_global = [start_index + t for t in valid_tsv_locals]
            
            # If no valid TSVs, use pivot - Rule B2
            if not valid_tsvs_global:
                valid_tsvs_global = [start_index + pivot_tsv_local]
            
            # Apply load balancing among valid TSVs
            available_tsvs = [tsv for tsv in valid_tsvs_global if tsv_assignment_count.get(tsv, 0) < max_assignments_per_tsv]
            
            if not available_tsvs:
                selected_tsv = random.choice(valid_tsvs_global)
            else:
                selected_tsv = random.choice(available_tsvs)
            
            # Apply Rule B3 (defensive — no-op in pillar model)
            selected_tsv_local = selected_tsv - start_index
            selected_tsv_local = apply_rule_b3(selected_tsv_local, i, pivot_tsv_local, num_cols)
            selected_tsv = start_index + selected_tsv_local
            
            tsv_assignment[start_index + i] = selected_tsv
            tsv_assignment_count[selected_tsv] = tsv_assignment_count.get(selected_tsv, 0) + 1

    print("Deadlock-free TSV assignment complete (REDELF Ruleset B: B1+B2+B3 applied)")
    return tsv_assignment, tsv_placements_flat

'''#for elevator-1st assignment    
def router_id_to_coordinates(router_id, num_rows, num_cols):
    x = router_id % num_cols
    y = (router_id // num_cols) % num_rows
    return (x, y)

def generate_tsv_assignment(n, num_layers, num_rows, num_cols, core_to_router):
    nodes_per_layer = num_rows * num_cols
    tsv_assignment = [0] * n

    # Generate TSV placement
    if nodes_per_layer <= 6:
        num_tsvs=1
    else:
        max_tsvs_25_percent = max(1, nodes_per_layer // 4)
        upper_bound = min(nodes_per_layer - 1, max_tsvs_25_percent)
        num_tsvs=random.randint(2,upper_bound)
    tsv_placements_flat, tsv_placements_2d, valid = generate_tsv_placements_2d(num_rows, num_cols, num_tsvs)

    if not valid:
        print("Failed to generate valid TSV placements. Retrying...")
        tsv_placements_flat, tsv_placements_2d, valid = generate_tsv_placements_2d(num_rows, num_cols, num_tsvs)

    print(f"TSV Placement Array (1D): {tsv_placements_flat}")
    print(f"TSV Placement Grid (2D):\n{tsv_placements_2d}")

    # Build layer-wise TSV router list
    layer_tsv_routers = {}
    for layer in range(num_layers):
        base = layer * nodes_per_layer
        layer_tsv_routers[layer] = [base + i for i, val in enumerate(tsv_placements_flat) if val == 1]

    print(f"Layer TSV Routers Dictionary: {layer_tsv_routers}")

    # Elevator-first assignment
    for layer in range(num_layers):
        base = layer * nodes_per_layer
        for offset in range(nodes_per_layer):
            router_id = base + offset
            router_coord = router_id_to_coordinates(router_id, num_rows, num_cols)

            # Find the nearest TSV in this layer
            min_dist = float('inf')
            nearest_tsv = None
            for tsv_id in layer_tsv_routers[layer]:
                tsv_coord = router_id_to_coordinates(tsv_id, num_rows, num_cols)
                dist = abs(router_coord[0] - tsv_coord[0]) + abs(router_coord[1] - tsv_coord[1])
                if dist < min_dist:
                    min_dist = dist
                    nearest_tsv = tsv_id

            # Fallback in case no TSV was found (shouldn't happen with valid placement)
            if nearest_tsv is None:
                nearest_tsv = random.choice(layer_tsv_routers[layer])

            tsv_assignment[router_id] = nearest_tsv

    return tsv_assignment, tsv_placements_flat
'''
# Generate valid edges from adjacency matrix
def generate_valid_edges(adj_matrix, is_symmetric):
    valid_edges = []
    n = adj_matrix.shape[0]
    for i in range(n):
        if is_symmetric:
            column_range = range(i + 1, n)
        else:
            column_range = range(n)

        for j in column_range:
            if i == j:
                continue
            if adj_matrix[i][j] != float('inf') and adj_matrix[i][j] != 0:
                valid_edges.append((i, j, adj_matrix[i][j]))
    return valid_edges


def get_router_from_coordinates(coord):
        """ Helper function to get the router index from coordinates """
        x, y, z = coord
        start_index = z * num_rows * num_cols
        return start_index + y * num_cols + x

def calculate_manhattan_distance(coord1, coord2):
        """ Calculate Manhattan distance between two coordinates. """
        return abs(coord1[0] - coord2[0]) + abs(coord1[1] - coord2[1]) + abs(coord1[2] - coord2[2])


def hop(path, source, destination, tsv_assignment, router_coordinates, num_rows, num_cols):

    # Find the indices of source and destination in the path
    if source not in path or destination not in path:
        raise ValueError("Source or destination not found in the path.")

    source_index = path.index(source)
    destination_index = path.index(destination)



    # Get coordinates for the source and destination indices
    source_vertex = source_index
    destination_vertex = destination_index




    source_coord = router_coordinates[source_vertex]
    destination_coord = router_coordinates[destination_vertex]

    if source_coord[2] == destination_coord[2]:
      total_hops = 0
      total_hops=calculate_manhattan_distance(source_coord,destination_coord)
      return total_hops

    total_hops = 0

    # Hop from source to its TSV router
    source_tsv_router = tsv_assignment[source_vertex]
    source_tsv_coord = router_coordinates[source_tsv_router]
    total_hops += calculate_manhattan_distance(source_coord, source_tsv_coord)
    tsv_coord = source_tsv_coord
    tsv_router = source_tsv_router
    # Traverse layers from source layer to destination layer
    current_layer = source_coord[2]
    while current_layer != destination_coord[2]:
        next_layer = current_layer + 1 if destination_coord[2] > current_layer else current_layer - 1
        next_layer_coord = (source_tsv_coord[0], source_tsv_coord[1], next_layer)
        next_layer_router = get_router_from_coordinates(next_layer_coord)

        if next_layer_router >= len(tsv_assignment):
            continue

        tsv_router = tsv_assignment[next_layer_router]

        if tsv_router >= len(router_coordinates):
            continue

        tsv_coord = router_coordinates[tsv_router]
        total_hops+=1
        if(next_layer!=destination_coord[2] ):
            total_hops += calculate_manhattan_distance(next_layer_coord, tsv_coord)

           # Each vertical hop costs 1
        source_tsv_coord = tsv_coord
        current_layer = next_layer

    # Hop from TSV router in the destination layer to destination
    #dest_tsv_router = tsv_assignment[destination_vertex]
    #dest_tsv_coord = router_coordinates[dest_tsv_router]
    #dest_tsv_router = tsv_assignment[tsv_router]
    #dest_tsv_coord = router_coordinates[dest_tsv_router]
    total_hops += calculate_manhattan_distance(next_layer_coord, destination_coord)

    return total_hops

# Calculate the cost using TSV placement
def cost_with_tsv(path,source, destination, tsv_assignment, valid_edges, router_coordinates, num_rows, num_cols,hops):
    if source == destination:
        return 0

    if source not in router_coordinates or destination not in router_coordinates:
        return float('inf')

    base_cost = adj_matrix[source][destination]                                                              #next((weight for (u, v, weight) in valid_edges if u == source and v == destination), float('inf'))# 2d array
    if base_cost == float('inf'):
        return float('inf')

    # return base_cost * hop(path,source, destination, tsv_assignment, router_coordinates, num_rows, num_cols)
    return base_cost * hops

# Particle creation
def create_particle(n, adj_matrix, num_layers, num_rows, num_cols, population_size):
    print(f"Creating {population_size} particles...")
    try:
        # Generate a list of core-to-router permutations
        permutations_list = []

        for _ in range(population_size):
    	    array = np.arange(n)  # Create an array of [0, 1, 2, ..., n-1]
    	    np.random.shuffle(array)  # Shuffle the array in place
    	    permutations_list.append(list(array))

        particles = []
        for core_to_router in permutations_list:
            # Generate TSV assignment for each permutation
            tsv_assignment, tsv_placements_flat = generate_tsv_assignment(n, num_layers, num_rows, num_cols, core_to_router, valid_edges, router_coordinates)

            particles.append({
                'core_to_router': core_to_router,
                'tsv_placements_flat': tsv_placements_flat,
                'tsv_assignment': tsv_assignment
            })

        return particles

    except Exception as e:
        print(f"Error in creating particle: {e}")
        raise
# Generate neighbors for tabu search
def generate_neighbors(path):
    neighbors = []
    num_iterations = len(path) // 3

    for _ in range(num_iterations):
        # Generate random indices i and j
        i = random.randint(0, len(path) - 1)  # index from 0 to len(path)-1
        j = random.randint(0, len(path) - 1)  # index from 0 to len(path)-1
        
        # Ensure i and j are different
        while j == i:
            j = random.randint(0, len(path) - 1)

        # Create a new path with the swapped elements
        new_path = path[:]
        new_path[i], new_path[j] = new_path[j], new_path[i]
        neighbors.append(new_path)

    return neighbors

# Calculate path cost
def calculate_path_cost(path, tsv_assignment,tsv_placements_flat, adj_matrix, router_coordinates, num_rows, num_cols):
    total_cost = 0
    total_hops = 0
    tsv_traffic_cost_record = []
    #valid_edges = generate_valid_edges(adj_matrix)
    #print("*************")
    #print(path)
    #print(tsv_assignment)
    #print(valid_edges)
    #print("*************")
    for i, (source, destination, _) in enumerate(valid_edges):
        if np.all(tsv_assignment == 0):
          continue  # Skip to the next iteration
        hops = hop(path,source, destination, tsv_assignment, router_coordinates, num_rows, num_cols)
        cost = cost_with_tsv(path,source, destination, tsv_assignment, valid_edges, router_coordinates, num_rows, num_cols,hops)
        # hops = hop(path,source, destination, tsv_assignment, router_coordinates, num_rows, num_cols)
        total_cost += cost
        total_hops += hops


    tsv_traffic_cost_record = create_tsv_router_pairs(tsv_assignment, path, tsv_placements_flat, len(router_coordinates) // (num_rows * num_cols), num_rows, num_cols, router_coordinates, valid_edges, len(router_coordinates))
    avg_tsv_comm_cost = find_avg_tsv_comm_cost(tsv_traffic_cost_record,tsv_placements_flat)
    up_variance, down_variance = find_particle_variance_array(tsv_traffic_cost_record, avg_tsv_comm_cost,tsv_placements_flat)

    #variance_1=float(np.max(variance))
    return total_cost, total_hops, up_variance, down_variance

# Tabu search algorithm

def tabu_search(n, adj_matrix, initial_path, num_iterations, tsv_assignment, router_coordinates, num_rows, num_cols,placements,A,B):
    #valid_edges = generate_valid_edges(adj_matrix)
    current_path = initial_path
    best_path = initial_path
    tabu_list = []
    best_effective_cost=0
    best_cost, best_hops, best_up_variance, best_down_variance = calculate_path_cost(best_path, tsv_assignment,placements, adj_matrix, router_coordinates, num_rows, num_cols)
    best_variance = max(best_up_variance, best_down_variance)
    # Initialize effective_cost and best_comb_norm_var with the initial best values
    best_effective_cost = (W_factor *(best_cost/A)) + ((1-W_factor) *(best_variance/pow(B,2)))
    # effective_cost = (best_cost / A) if A > 0 else float('inf')
    # best_comb_norm_var = (np.max([best_up_variance, best_down_variance]) / pow(B, 2)) if B > 0 else 0
    best_comb_norm_var = (best_variance/pow(B,2))
    tabu_list.append(best_path)

    # Variables to store the best TSV assignment and placement
    best_tsv_assignment = tsv_assignment[:]
    best_tsv_placements_flat = placements
    
    # ---------------- Early stopping parameters ----------------
    patience = 100                 # stop if no improvement for these many iterations
    no_improve_iters = 0
    last_best_effective_cost = best_effective_cost
    # -----------------------------------------------------------

    for iteration in range(num_iterations):
        #print(f"\nIteration {iteration + 1}:")
        #print(f"Current Path (Core-to-Router Mapping): {current_path}")
        #print(f"TSV Assignment: {tsv_assignment}")

        neighbors = generate_neighbors(current_path)
        neighbor_costs = []

        for neighbor in neighbors:
            if neighbor not in tabu_list:
                cost, hops, up_var, down_var = calculate_path_cost(neighbor, tsv_assignment, placements,adj_matrix, router_coordinates, num_rows, num_cols)
                variance = max(up_var, down_var)
                effective_cost = (W_factor *(cost/A)) + ((1-W_factor) *(variance/pow(B,2)))
                neighbor_costs.append((neighbor, cost, hops, up_var, down_var, effective_cost))

        if not neighbor_costs:
            print("No valid neighbors found.")
            break

        # Get the next best path from neighbors
        next_path, next_cost, next_hops, next_up_variance, next_down_variance, next_effective_cost = min(neighbor_costs, key=lambda x: x[5])
        next_variance = max(next_up_variance, next_down_variance)
        next_effective_cost = (W_factor *(next_cost/A)) + ((1-W_factor) *(next_variance/pow(B,2)))
        if next_effective_cost < best_effective_cost:
            best_path = next_path
            best_cost = next_cost
            best_hops = next_hops
            best_up_variance = next_up_variance
            best_down_variance = next_down_variance
            # effective_cost= (W_factor *(np.sum(best_cost)/A)) + ((1-W_factor) *(np.max([best_up_variance, best_down_variance])/pow(B,2)))
            best_effective_cost = next_effective_cost
            # best_comb_norm_var = (np.max([best_up_variance, best_down_variance])/pow(B,2))
            best_comb_norm_var = (next_variance/pow(B,2))
            #print(f"Effective Cost: {effective_cost}")

            # Update best TSV assignment and placement
            best_tsv_assignment = tsv_assignment[:]
            best_tsv_placements_flat = placements

        tabu_list.append(next_path)
        if len(tabu_list) > 1000:  # Limit the size of the tabu list
            tabu_list.pop(0)

        current_path = next_path
        
        # ---------------- Early stopping check ----------------
        if best_effective_cost < last_best_effective_cost - 1e-9:
            # Improvement happened
            no_improve_iters = 0
            last_best_effective_cost = best_effective_cost
        else:
            # No improvement in this iteration
            no_improve_iters += 1

        if no_improve_iters >= patience:
            print(f"Early stopping Tabu at iteration {iteration + 1} "
                  f"after {patience} iterations without improvement.")
            break
        # ------------------------------------------------------

    print(f"\nBest Path: {best_path}")
    print(f"\nBest Cost: {best_cost}")
    print(f"\nBest Hops: {best_hops}")
    print(f"\nBest TSV Assignment: {best_tsv_assignment}")
    print(f"\nBest Up Variance: {best_up_variance}")
    print(f"Best Down Variance: {best_down_variance}")
    print(f"\nBest TSV Placement (1D): {best_tsv_placements_flat}")

    # Return the best path, cost, hops, TSV assignment, and placement
    return best_path, best_cost, best_hops, best_tsv_assignment, best_tsv_placements_flat, best_effective_cost, best_up_variance, best_down_variance, best_comb_norm_var



## VARIANCE
def create_tsv_router_pairs(tsv_assignment, path, tsv_placements_flat, num_layers, num_rows, num_cols, router_coordinates, valid_edges, n):
    
    nodes_per_layer = num_rows * num_cols

    # --- 1. Build mapping router_id -> index in traffic_list ---
    tsv_base_indices = [i for i, val in enumerate(tsv_placements_flat) if val == 1]

    traffic_list = []
    router_to_traffic_idx = {}

    traffic_idx = 0
    for layer in range(num_layers):
        for base_idx in tsv_base_indices:
            router_in_layer = layer * nodes_per_layer + base_idx
            router_to_traffic_idx[router_in_layer] = traffic_idx
            traffic_list.append([0, 0])  # [upward, downward] load for this TSV router
            traffic_idx += 1

    # --- 2. Process each edge and distribute load over all vertical links used ---
    for source, destination, weight in valid_edges:
        if source not in path or destination not in path:
            print("create_tsv_router_pairs:out of bounds for router_coordinates ")
            sys.exit(1)

        source_index = path.index(source)
        destination_index = path.index(destination)

        if source_index >= len(router_coordinates) or destination_index >= len(router_coordinates):
            print("create_tsv_router_pairs:out of bounds for router_coordinates ")
            sys.exit(1)

        source_coord = router_coordinates[source_index]
        destination_coord = router_coordinates[destination_index]

        a = source_coord[2]  # source layer
        b = destination_coord[2]  # dest layer

        # Only vertical traffic contributes to TSV load
        if a == b:
            continue

        # -----------------------------
        # Start at source's assigned TSV
        # -----------------------------
        if source_index >= len(tsv_assignment):
            # Defensive: shouldn't happen
            print("create_tsv_router_pairs:out of bounds for router_coordinates ")
            sys.exit(1)

        current_tsv_router = tsv_assignment[source_index]
        if current_tsv_router >= len(router_coordinates):
            print("create_tsv_router_pairs:out of bounds for router_coordinates ")
            sys.exit(1)

        current_tsv_coord = router_coordinates[current_tsv_router]
        current_layer = a

        # Move towards destination layer one boundary at a time
        direction = 1 if b > a else -1

        while current_layer != b:
            next_layer = current_layer + direction

            # Vertical link from (current_tsv_coord at current_layer)
            # to (same x,y at next_layer)
            x_tsv, y_tsv, _ = current_tsv_coord
            # Represent this link by the TSV router in the LOWER layer
            # lower_layer = min(current_layer, next_layer)
            router_id_for_link = current_layer * nodes_per_layer + (y_tsv * num_cols + x_tsv)

            if router_id_for_link in router_to_traffic_idx:
                idx = router_to_traffic_idx[router_id_for_link]
                if direction == 1:
                    # moving up
                    traffic_list[idx][0] += weight
                else:
                    # moving down
                    traffic_list[idx][1] += weight
            else:
                # This pillar should exist according to placement;
                # if not, we skip to avoid crashing.
                print("create_tsv_router_pairs:out of bounds for router_coordinates ")
                sys.exit(1)

            # Now step to that footprint in the next layer
            next_layer_coord = (x_tsv, y_tsv, next_layer)
            next_layer_router = get_router_from_coordinates(next_layer_coord)
            if next_layer_router >= len(tsv_assignment):
                print("create_tsv_router_pairs:out of bounds for router_coordinates ")
                sys.exit(1)

            # At the new layer, we may switch to a different pillar
            new_tsv_router = tsv_assignment[next_layer_router]
            if new_tsv_router >= len(router_coordinates):
                print("create_tsv_router_pairs:out of bounds for router_coordinates ")
                sys.exit(1)

            current_tsv_router = new_tsv_router
            current_tsv_coord = router_coordinates[current_tsv_router]
            current_layer = next_layer

    return traffic_list

def find_no_of_tsvs(tsv_placements_flat):
    tsv_list = [i for i, val in enumerate(tsv_placements_flat) if val == 1]
    num_tsvs = len(tsv_list)
    up_tsvs=(num_tsvs)*(num_layers - 1) # Each TSV has (num_layers - 1) links going up
    down_tsvs=(num_tsvs)*(num_layers - 1)
    return [up_tsvs, down_tsvs]

def find_avg_tsv_comm_cost(tsv_traffic_cost_record, tsv_placements_flat):
    if not tsv_traffic_cost_record:
        return [0, 0]
    sum_up = sum(traffic[0] for traffic in tsv_traffic_cost_record)
    sum_down = sum(traffic[1] for traffic in tsv_traffic_cost_record)
    no_of_tsvs = find_no_of_tsvs(tsv_placements_flat)
    avg_up = sum_up / no_of_tsvs[0] if no_of_tsvs[0] > 0 else 0
    avg_down = sum_down / no_of_tsvs[1] if no_of_tsvs[1] > 0 else 0
    return [avg_up, avg_down]

def find_particle_variance_array(tsv_traffic_cost_record, avg_tsv_comm_cost, tsv_placements_flat):
    if not tsv_traffic_cost_record:
        return 0, 0
    
    # Identify how many active TSVs we have
    num_tsvs = sum(1 for x in tsv_placements_flat if x == 1)
    if num_tsvs == 0: return 0, 0

    # Total entries in traffic record = num_layers * num_tsvs
    total_entries = len(tsv_traffic_cost_record)
    num_layers = total_entries // num_tsvs
    
    variance_up_sum = 0
    variance_down_sum = 0
    
    # Iterate through the traffic record
    # The record is structured as: [Layer0_TSV1, Layer0_TSV2..., Layer1_TSV1, Layer1_TSV2...]
    
    for idx, traffic in enumerate(tsv_traffic_cost_record):
        # Determine which layer this entry belongs to
        # idx // num_tsvs gives the layer index (0 to num_layers-1)
        layer_idx = idx // num_tsvs
        
        # UP VARIANCE LOGIC:
        # Ignore entries from the Top Layer (layer_idx == num_layers - 1)
        if layer_idx < num_layers - 1:
            variance_up_sum += (traffic[0] - avg_tsv_comm_cost[0]) ** 2

        # DOWN VARIANCE LOGIC:
        # Ignore entries from the Bottom Layer (layer_idx == 0)
        if layer_idx > 0:
            variance_down_sum += (traffic[1] - avg_tsv_comm_cost[1]) ** 2

    # Get divisors (Total number of valid links)
    no_of_links = find_no_of_tsvs(tsv_placements_flat)
    
    # Calculate final variance
    variance_up = variance_up_sum / no_of_links[0] if no_of_links[0] > 0 else 0
    variance_down = variance_down_sum / no_of_links[1] if no_of_links[1] > 0 else 0

    return variance_up, variance_down

def findNormalizationForBandwidth(valid_edges, num_layers, num_rows,num_cols,n):
    # Sort the edge list based on the third element of each tuple (which is the weight)
    valid_edges.sort(key=lambda edge: edge[2], reverse=True)

    # Find the max weight (after sorting, the first element will have the max weight)
    maxWeight = valid_edges[0][2]
    print(f"Max weight after sorting: {maxWeight}")

    # Calculate the factor for hop bandwidth using the formula
    factor_for_hop_Bandwith = (((num_cols - 1 + num_rows - 1) * num_layers) + num_layers - 1) * maxWeight * n

    # Calculate the factor for variance by summing up the weights of all edges
    factor_for_variance = sum(edge[2] for edge in valid_edges)

    return factor_for_hop_Bandwith, factor_for_variance


def see():
  print(valid_edges)
  print(adj_matrix)
  print(num_rows)
  print(num_cols)
  print(n)

#READ ARGUMENTS FROM COMMAND LINE
if len(sys.argv) < 5:
    print("Error: Please provide all required arguments.")
    print("Usage: python3 new.py <filename> <population_size> <iterations> <w_factor>")
    sys.exit(1)

filename = sys.argv[1]
population_size = int(sys.argv[2]) # Read population size
num_iterations = int(sys.argv[3])  # Read number of iterations
W_factor = float(sys.argv[4])

#START TIMERS AND PARSE THE INPUT FILE
start_time = time.time()
usage_start=resource.getrusage(resource.RUSAGE_SELF)
n, adj_matrix, graph_is_symmetric = parse_input_file(filename)

file=filename
FileName = ''.join([char for char in file if char.isalpha()])
choice = int(''.join([char for char in file if char.isdigit()]))

#2Layer Dimensions
if choice == 3:
    # Graph with 3 routers per side; 2×2 grid (8 routers)
    num_routers = 8
    num_rows = 2
    num_cols = 2
    num_cores = 8

elif choice in [2, 6, 7, 14, 5]:
    # Graphs requiring 12 routers arranged as 3×2 grid
    num_routers = 12
    num_rows = 3
    num_cols = 2
    num_cores = 12

elif choice in [1, 8, 9, 10, 15]:
    # Graphs requiring 16 routers arranged as 4×2 grid
    num_routers = 16
    num_rows = 4
    num_cols = 2
    num_cores = 16

elif choice in [4, 13]:
    # Graphs requiring 32 routers arranged as 4×4 grid
    num_routers = 32
    num_rows = 4
    num_cols = 4
    num_cores = 32

elif choice == 12:
    # Graph requiring 24 routers arranged as 4×3 grid
    num_routers = 24
    num_rows = 4
    num_cols = 3
    num_cores = 24

# Old 13‑router case (3×5 grid), kept as reference (commented out)
# elif choice == 13:
#     num_routers = 30
#     num_rows = 5
#     num_cols = 3
#     num_cores = 30

elif choice in [17, 18, 19, 20, 21, 22, 23, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72]:
    # Graphs requiring 64 routers arranged as 8×4 grid
    num_routers = 64
    num_rows = 8
    num_cols = 4
    num_cores = 64

elif choice in [25, 26, 27, 28, 29, 30]:
    # Graphs requiring 128 routers arranged as 8×8 grid
    num_routers = 128
    num_rows = 8
    num_cols = 8
    num_cores = 128
    
'''
#4Layer Dimensions
if choice in [1, 8, 9, 10, 15]:
    # Graphs requiring 16 routers arranged as 2×2 grid
    num_routers = 16
    num_rows = 2
    num_cols = 2
    num_cores = 16

elif choice in [4, 13]:
    # Graphs requiring 32 routers arranged as 4×2 grid
    num_routers = 32
    num_rows = 4
    num_cols = 2
    num_cores = 32

elif choice == 12:
    # Graph requiring 24 routers arranged as 3×2 grid
    num_routers = 24
    num_rows = 3
    num_cols = 2
    num_cores = 24

elif choice in [17, 18, 19, 20, 21, 22, 23, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72]:
    # Graphs requiring 64 routers arranged as 4×4 grid
    num_routers = 64
    num_rows = 4
    num_cols = 4
    num_cores = 64

elif choice in [25, 26, 27, 28, 29, 30]:
    # Graphs requiring 128 routers arranged as 8×4 grid
    num_routers = 128
    num_rows = 8
    num_cols = 4
    num_cores = 128
'''

# Calculate the number of layers and routers per layer
num_layers = num_routers // (num_rows * num_cols)
num_routers_in_layer = num_cols * num_rows
#file_path = 'Graph3_Particle.txt'
router_coordinates = generate_coordinates(num_layers, num_rows, num_cols)
n=num_layers*num_rows*num_cols
initial_path = list(range(n))  # Initial path as a list of node indices
#num_iterations = 500  # Number of iterations for tabu search
valid_edges=generate_valid_edges(adj_matrix, graph_is_symmetric)
see()
A,B =findNormalizationForBandwidth(valid_edges, num_layers, num_rows,num_cols,n)
print(A,B)

print("\n" + "-"*20)
print("Normalization Factors from Formula:")
print(f"α (alpha - Worst-case Comm Cost): {A}")
print(f"β (beta - Worst-case Variance): {B}")
print(f"β² (beta squared): {pow(B, 2)}")
print("-"*20 + "\n")

particles = create_particle(n, adj_matrix, num_layers, num_rows, num_cols, population_size)

gb_best_path=[]
gb_best_cost=float('inf')
gb_best_effective_cost = float('inf')
gb_best_hops=0
gb_effective_cost=0
gb_best_up_variance = 0
gb_best_down_variance = 0
gb_best_tsv_placements_flat=[]
gb_best_tsv_assignment=[]
gb_best_comb_norm_var=0
iteration=1
for particle in particles:
    tsv_assignment = particle['tsv_assignment']
    print(f"Particle TSV Assignment: {tsv_assignment}")
    
    placements = particle['tsv_placements_flat']
    main_path=particle['core_to_router']
    best_path, best_cost, best_hops, best_tsv_assignment, best_tsv_placements_flat, effective_cost, best_up_variance, best_down_variance, best_comb_norm_var = tabu_search(n, adj_matrix, initial_path, num_iterations,tsv_assignment,router_coordinates, num_rows, num_cols, placements, A, B)
    
    
    print(f"no of solutions: {iteration}")
    iteration+=1
    print(f"Best Path: {best_path}, Best Cost: {best_cost}, Best Hops: {best_hops}, Net value: {effective_cost}")
    
    if effective_cost < gb_best_effective_cost:
        gb_best_path = best_path
        gb_best_tsv_placements_flat=best_tsv_placements_flat
        gb_best_tsv_assignment=best_tsv_assignment
        gb_best_cost = best_cost
        gb_best_hops = best_hops
        gb_best_effective_cost = effective_cost
        gb_best_up_variance = best_up_variance
        gb_best_down_variance = best_down_variance
        gb_best_comb_norm_var = best_comb_norm_var
	#gb_best_tsv_placements_flat=best_tsv_placements_flat


# tsv_pairs, traffic_list, pair_to_id = create_tsv_router_pairs(
#     gb_best_tsv_assignment, gb_best_path,gb_best_tsv_placements_flat, num_layers, num_rows, num_cols, router_coordinates, valid_edges, n
# )
print("\n" + "-"*20)
print("Global Best Solution Found:")
print(f"Global solution: {list(map(int, gb_best_path))} {gb_best_tsv_placements_flat} {gb_best_tsv_assignment}")
print(f"  Global Best Hops: {gb_best_hops}")
print(f"  Global Best Cost: {gb_best_cost}")
print(f"  Global Best Up Variance: {gb_best_up_variance}")
print(f"  Global Best Down Variance: {gb_best_down_variance}")
print(f"  Global Best Norm_Variance: {gb_best_comb_norm_var}")
print(f"  Global Best Net_value: {gb_best_effective_cost}")
print("-"*20 + "\n")

usage_end=resource.getrusage(resource.RUSAGE_SELF)
end_time = time.time()
real_time = end_time - start_time
user_time = usage_end.ru_utime - usage_start.ru_utime
sys_time = usage_end.ru_stime - usage_start.ru_stime

print(f"Real time: {real_time:.2f} seconds")
print(f"User time: {user_time:.2f} seconds")
print(f"System time: {sys_time:.2f} seconds")
