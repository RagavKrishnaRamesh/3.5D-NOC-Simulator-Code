import subprocess
import sys
import os

INITIAL_POPULATION = 1000
ITERATIONS = 500
W_FACTOR = 0.5

SCRIPT_TO_RUN = "TABU_4L_RAN_ES_sym_asym.py"
LOGS_DIRECTORY = "Logs"
# GRAPH_NUMBERS= [1,2,3,4,5,6,7,8,9,10,12,13,14,15,17, 18, 19, 20, 21, 22, 23,25, 26, 27, 28, 29, 30, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72]
GRAPH_NUMBERS = [1, 4, 8, 9, 10, 12, 13, 15,17, 18, 19, 20, 21, 22, 23, 25, 26, 27, 28, 29, 30, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65]
#GRAPH_NUMBERS = [8,4,22, 23]
# Create the Logs directory if it doesn't already exist
os.makedirs(LOGS_DIRECTORY, exist_ok=True)

# --- Main Loop ---
# Updated the print statement to include the W_factor.
print(f"--- Starting Batch Job (Pop: {INITIAL_POPULATION}, Iter: {ITERATIONS}, W_factor: {W_FACTOR}) ---")
print(f"--- Output will be saved in the '{LOGS_DIRECTORY}' folder. ---")

for i, num in enumerate(GRAPH_NUMBERS):
    graph_file_name = f"Graph{num}.txt"
    filename_with_path = os.path.join("Graphs", graph_file_name)
    
    # Define the name and path for the log file for this specific run
    log_file_name = f"Graph{num}_log.txt"
    log_file_path = os.path.join(LOGS_DIRECTORY, log_file_name)
    
    print(f"\n--- ({i+1}/{len(GRAPH_NUMBERS)}) Running for {filename_with_path} ---")
    
    try:
        # Added W_FACTOR to the command sent to the child script.
        command = [
            "python3", SCRIPT_TO_RUN, filename_with_path, 
            str(INITIAL_POPULATION), str(ITERATIONS), str(W_FACTOR)
        ]
        
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        
        # Write the successful output to the log file
        with open(log_file_path, 'w') as log_file:
            log_file.write(f"--- Log for {filename_with_path} ---\n\n")
            log_file.write(result.stdout)
            if result.stderr:
                log_file.write("\n--- Warnings ---\n")
                log_file.write(result.stderr)
                
        print(f"--- Finished. Log saved to '{log_file_path}' ---")
        if result.stderr:
            print(f"--- Warnings were generated (see log file for details) ---")

    except subprocess.CalledProcessError as e:
        error_message = f"!!! ERROR in script for {filename_with_path} !!!\n--- Stderr ---\n{e.stderr}\n--- Stdout ---\n{e.stdout}"
        print(error_message)
        # Write the error message to the log file
        with open(log_file_path, 'w') as log_file:
            log_file.write(error_message)
            
    except Exception as e:
        error_message = f"!!! An unexpected error occurred for {filename_with_path}: {e} !!!"
        print(error_message)
        # Write the error message to the log file
        with open(log_file_path, 'w') as log_file:
            log_file.write(error_message)

print("\n--- Batch Job Finished ---")
