# (C) Copyright 2025 CEA LIST. All Rights Reserved.
# Contributor(s): Davy Million (davy.million@cea.fr)

from exhaustive_search import *
from milp import *
import csv

test_case = [
    {
        'R_x': 2,
        'R_y': 2,
        'vertical_links': np.array([[0, 0], [0, 1], [1, 0], [1, 1]])
    },
    {
        'R_x': 2,
        'R_y': 3,
        'vertical_links': np.array([[0, 2], [0, 2], [1, 0], [1, 2]])
    },
    {
        'R_x': 3,
        'R_y': 3,
        'vertical_links': np.array([[0, 0], [0, 2], [1, 1], [2, 0], [2, 2]])
    },
    {
        'R_x': 3,
        'R_y': 4,
        'vertical_links': np.array([[0, 0], [0, 3], [1, 1], [2, 2]])
    },
    {
        'R_x': 4,
        'R_y': 4,
        'vertical_links': np.array([[1, 1], [1, 4], [2, 2], [3, 3]])
    },
    {
        'R_x': 5,
        'R_y': 5,
        'vertical_links': np.array([[1, 1], [1, 4], [2, 2], [3, 3], [4, 1], [2, 4], [3, 2], [1, 3]])
    },
    {
        'R_x': 7,
        'R_y': 7,
        'vertical_links': np.array([[1, 1], [1, 4], [2, 2], [3, 3], [4, 1], [2, 4], [3, 2], [1, 3], [1, 2], [1, 5], [5, 5], [5, 6], [6, 1], [3, 4], [5, 2], [1, 5]])
    },
    {
        'R_x': 11,
        'R_y': 11,
        'vertical_links': np.array([[1, 1], [1, 4], [2, 2], [3, 3], [4, 1], [2, 4], [3, 2], [1, 3], [1, 2], [1, 5], [5, 5], [5, 6], [6, 1], [3, 4], [5, 2], [1, 5],
                                    [7, 1], [7, 4], [8, 2], [9, 3], [10, 1], [8, 4], [9, 2], [7, 3], [7, 7], [6, 5], [9, 0], [9, 9], [10, 10], [10, 5], [8, 9], [7, 0]])
    }
]

filename = 'milp_vs_rexhaustive.csv'
headers = ['Variation', 'Method', 'Network Size', 'End Time', 'Sum D_v', 'Sum L_v', 'l_avg']
results = []

rho = 0.01  # Weight for distance constraint in objective fn

if __name__ == "__main__":
    for i, params in enumerate(test_case):
        R_x = params['R_x']
        R_y = params['R_y']
        vertical_links = params['vertical_links']

        print(f"\nVariation {i+1}:")
        print(f"R_x: {R_x}, R_y: {R_y}, rho: {rho}")
        print("Vertical Links:")
        print(vertical_links)

        end_time_milp, U_r_v, sum_D_v_milp, sum_L_v_milp, l_avg_milp = milp_compute(R_x, R_y, vertical_links, rho, False)
        results.append([i+1, 'MILP', f"{R_x}x{R_y}-{len(vertical_links)}", end_time_milp, sum_D_v_milp, sum_L_v_milp, l_avg_milp])

        if i < 5:
            v = np.array([vLink(x, y) for x, y in vertical_links])
            end_time_exhaustive, U_r_v, sum_D_v_exhaustive, sum_L_v_exhaustive, l_avg_exhaustive = exhaustive_search(R_x, R_y, v, rho)
            results.append([i+1, 'RExhaustive', f"{R_x}x{R_y}-{len(vertical_links)}", end_time_exhaustive, sum_D_v_exhaustive, sum_L_v_exhaustive, l_avg_exhaustive])

    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(results)

