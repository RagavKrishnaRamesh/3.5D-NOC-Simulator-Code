# edge_set_creation_new.py

def create_edge_set(graph_file, output_file):
    
    edge_set = []

    with open(graph_file, 'r') as file:
        # Read the number of cores (first line)
        Graph_cores = int(file.readline().strip())

        # Loop through the remaining lines for the graph matrix
        lines = file.readlines()

        for i, line in enumerate(lines):
                values = line.split()

                for j, value in enumerate(values):
                    # Only consider elements in the upper triangular part (j > i)
                    if j > i:    #Modify for Parsec and Splash(comment this)
                    
                        if value != "INF" and float(value) != 0:
                           edge_set.append((i, j, float(value)))  # Store as (source, destination, cost)
                    
                    # For Parsec and Splash uncomment below and comment above
                    # if value != "INF" and float(value) != 0:
                    #        edge_set.append((i, j, float(value)))  # Store as (source, destination, cost)
    # Write the edge set to a file
    with open(output_file, 'w') as file:
        for edge in edge_set:
            file.write(f"{edge[0]} {edge[1]} {edge[2]}\n")

    print(f"Edge set created and saved to {output_file}.")
    print(f"Graph cores: {Graph_cores}")

# The example usage code that was here has been removed.
