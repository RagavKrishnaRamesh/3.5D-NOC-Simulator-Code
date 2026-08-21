# (C) Copyright 2025 CEA LIST. All Rights Reserved.
# Contributor(s): Rim El Cheikh (rim.el_cheikh@limos.fr), Davy Million (davy.million@cea.fr)

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds
import time
import math

def milp_compute(R_x, R_y, LinksCoordinates, rho, silent_mode=True):
    start_time = time.time()
    R = R_x * R_y
    V = len(LinksCoordinates)
    T = 1.0 / R  # Traffic rate for each router
    l_avg_cst = 1/V
    max_MD = R-1  # Maximum Manhattan distance (topology agnostic)
    #chiplet = False

    RoutersCoordinates = np.array([[x, y] for x in range(0, R_x) for y in range(0, R_y)])
    
    num_dvars = R * V    + V     + 1    + 3 * V                        + 5 * R * V          + R * V             + V
              # U[r][v], l_v[v], l_avg, dev_pos[v], dev_neg[v], L_v[v], ManhattanDist[r][v], DistanceCost[r][v] , D_v[v]
    
    # Decision variables bounds (_l,_u) (binary for U, non-negative for others)
    lower_bounds = [0] * (R * V) + [0] * (V + 1 + 3 * V + 5 * R * V + R * V + V)
    upper_bounds = [1] * (R * V) + [np.inf] * (V + 1 + 3 * V + 5 * R * V + R * V + V)
    
    # Correct Bounds format
    bounds = Bounds(lower_bounds, upper_bounds)
    
    # Constraints (_A)
    constraints = []
    
    # Each router is assigned to exactly one vertical link
    for r in range(R):
        coeffs = np.zeros(num_dvars)
        for v in range(V):
            coeffs[r * V + v] = 1  # U[r][v]
        constraints.append(LinearConstraint(coeffs, 1, 1))  # _b_l = _b_u = 1 (exactly one)
    
    
    # Load definition for each router
    for v in range(V):
        coeffs = np.zeros(num_dvars)
        for r in range(R):
            coeffs[r * V + v] = T  # T * U[r][v]
        coeffs[R * V + v] = -1  # l_v[v]
        constraints.append(LinearConstraint(coeffs, 0, 0))  # -l_v[v] + sum(r)(T * U[r][v]) = 0, for each v
    
    
    # Average load constraint
    coeffs = np.zeros(num_dvars)
    for v in range(V):
        coeffs[R * V + v] = 1  # l_v[v]
    coeffs[R * V + V] = -V  # l_avg * |V|
    constraints.append(LinearConstraint(coeffs, 0, 0))  # -card(V)*l_avg + sum(v)(l_v[v]) = 0
    
    
    # Load deviation constraints
    for v in range(V):
        coeffs_dev_pos = np.zeros(num_dvars)
        coeffs_pos = np.zeros(num_dvars)
        coeffs_dev_neg = np.zeros(num_dvars)
        coeffs_neg = np.zeros(num_dvars)
        coeffs_total = np.zeros(num_dvars)
        
        coeffs_pos[R * V + v] = 1  # l_v[v]
        coeffs_pos[R * V + V] = -1  # -l_avg
        coeffs_pos[R * V + V + 1 + v] = -1  # -deviation_pos[v] (L_v[v])
        # deviation_pos[v] >= l_v[v] - l_avg
        # l_v[v] - l_avg - deviation_pos[v]  <= 0
        constraints.append(LinearConstraint(coeffs_pos, -np.inf , 0))
    
    
        coeffs_dev_pos[R * V + V + 1 + v] = 1   # -deviation_pos[v] (L_v[v])
        constraints.append(LinearConstraint(coeffs_dev_pos, 0, np.inf))
    
        
        coeffs_neg[R * V + v] = -1  # -l_v[v]
        coeffs_neg[R * V + V] = 1  # l_avg
        coeffs_neg[R * V + V + 1 + V + v] = -1  # -deviation_neg[v] (L_v[v])
        # deviation_neg[v] >= l_avg - l_v[v]
        # - l_v[v] + l_avg - deviation_neg[v] <= 0
        constraints.append(LinearConstraint(coeffs_neg, -np.inf, 0))
        
        
        coeffs_dev_neg[R * V + V + 1 + V + v] = 1
        constraints.append(LinearConstraint(coeffs_dev_neg, 0, np.inf))
    
        
        coeffs_total[R * V + V + 1 + v] = 1  # deviation_pos[v]
        coeffs_total[R * V + V + 1 + V + v] = 1  # deviation_neg[v]
        coeffs_total[R * V + V + 1 + V + V + v] = -1*l_avg_cst  # L_v[v]
        constraints.append(LinearConstraint(coeffs_total, 0, 0))
    
    
    # Manhattan distance constraints
    for r in range(R):
        for v in range(V):
            coeffs_x_p = np.zeros(num_dvars)
            coeffs_x_n = np.zeros(num_dvars)
            coeffs_y_p = np.zeros(num_dvars)
            coeffs_y_n = np.zeros(num_dvars)
            coeffs_MD_total = np.zeros(num_dvars)
            
            x_diff = RoutersCoordinates[r][0] - LinksCoordinates[v][0]
            y_diff = RoutersCoordinates[r][1] - LinksCoordinates[v][1]
            
            start = R * V + V + 1 + 3 * V  
            
            coeffs_x_p[start + 0 * R * V + r * V + v] = 1  # ManhattanDist_x_p[r][v]
            constraints.append(LinearConstraint(coeffs_x_p, x_diff, np.inf))
            constraints.append(LinearConstraint(coeffs_x_p, 0, np.inf))
            
            
            coeffs_x_n[start + 1 * R * V + r * V + v] = 1  # ManhattanDist_x_n[r][v]
            constraints.append(LinearConstraint(coeffs_x_n, -x_diff, np.inf))
            constraints.append(LinearConstraint(coeffs_x_n, 0, np.inf))
            
            
            coeffs_y_p[start + 2 * R * V + r * V + v] = 1  # ManhattanDist_y_p[r][v]
            constraints.append(LinearConstraint(coeffs_y_p, y_diff, np.inf))
            constraints.append(LinearConstraint(coeffs_y_p, 0, np.inf))
            
            
            coeffs_y_n[start + 3 * R * V + r * V + v] = 1  # ManhattanDist_y_n[r][v]
            constraints.append(LinearConstraint(coeffs_y_n, -y_diff, np.inf))
            constraints.append(LinearConstraint(coeffs_y_n, 0, np.inf))
            
            
            coeffs_total[start + 0 * R * V + r * V + v] = 1  # ManhattanDist_x_p[r][v]
            coeffs_total[start + 1 * R * V + r * V + v] = 1  # ManhattanDist_x_n[r][v]
            coeffs_total[start + 2 * R * V + r * V + v] = 1  # ManhattanDist_y_p[r][v]
            coeffs_total[start + 3 * R * V + r * V + v] = 1  # ManhattanDist_y_n[r][v]
            coeffs_total[start + 4 * R * V + r * V + v] = -1  # ManhattanDist[r][v]
            constraints.append(LinearConstraint(coeffs_total, 0, 0))
            #ManhattanDist[r][v] = ManhattanDist_x_p[r][v] + ManhattanDist_x_n[r][v] + ManhattanDist_y_p[r][v] + ManhattanDist_y_n[r][v];
    
    
    
    # Distance Cost constraints (DistanceCost = D_v_r*U_r_v )
    for r in range(R):
        for v in range(V):
            start = R * V + V + 1 + 3 * V + 4 * R * V
    
            coeffs = np.zeros(num_dvars)      
            coeffs[start + r * V + v] = -1 # ManhattanDist[r][v]
            coeffs[start + R * V + r * V + v] = 1 #DistanceCost[r][v]
            # DistanceCost[r][v] <= ManhattanDist[r][v]
            # DistanceCost[r][v] - ManhattanDist[r][v] <= 0
            constraints.append(LinearConstraint(coeffs, -np.inf, 0)) 
            
            
            coeffs = np.zeros(num_dvars)      
            coeffs[start + R * V + r * V + v] = 1 #DistanceCost[r][v]
            # DistanceCost[r][v] >= 0
            constraints.append(LinearConstraint(coeffs, 0, np.inf)) 
    
    
            coeffs = np.zeros(num_dvars)      
            coeffs[start + R * V + r * V + v] = 1/max_MD #DistanceCost[r][v]
            coeffs[r * V + v] = -1  #U[r][v]
            # DistanceCost[r][v] <= max_MD * U[r][v]
            # DistanceCost[r][v]/max_MD - U[r][v] <= 0
            constraints.append(LinearConstraint(coeffs, -np.inf, 0)) 
            
            
            coeffs = np.zeros(num_dvars)      
            coeffs[start + R * V + r * V + v] = 1/max_MD #DistanceCost[r][v]
            coeffs[start + r * V + v] = -1/max_MD  #ManhattanDist[r][v]
            coeffs[r * V + v] = -1  #U[r][v]
            # DistanceCost[r][v] >= ManhattanDist[r][v] - (1 - U[r][v]) * max_MD
            # DistanceCost[r][v]/max_MD - ManhattanDist[r][v]/max_MD - U[r][v] >= -1 
            constraints.append(LinearConstraint(coeffs, -1, np.inf)) 
    
    
    # Distance cost for each link
    for v in range(V):
        coeffs = np.zeros(num_dvars)
        for r in range(R):      
            coeffs[R * V + V + 1 + 3 * V + 5 * R * V + r * V + v] = 1 #DistanceCost[r][v]
        coeffs[R * V + V + 1 + 3 * V + 5 * R * V + R * V + v] = -1 #D_v[v]
        
        constraints.append(LinearConstraint(coeffs, 0, 0)) 

    # Objective function
    c = np.zeros(num_dvars)
    for v in range(V):
        c[R * V + V + 1 + 3 * V + 5 * R * V + R * V + v] = rho  # rho * D_v[v]
        c[R * V + V + 1 + 2 * V + v] = 1  # L_v[v]
    
    # Solve MILP
    res = milp(c=c, constraints=constraints, bounds=bounds, options={'presolve':True}, 
               integrality=[1] * (R * V) + [0] * (V + 1 + 3 * V + 5 * R * V + R * V + V))
    end_time = time.time()
    
    U_r_v = np.round(res.x[:R*V].reshape((R,V))**2,2)
    L_v = res.x[R*V+V+1+2*V:R*V+V+1+2*V+V]
    D_v = res.x[-V:]
    l_avg = res.x[R*V+V]

    if not silent_mode:
        print(f'U={U_r_v} \n ----------------------- \n',
              f'l_avg={l_avg} \n ----------------------- \n',
              f'L_v={L_v} \n ----------------------- \n',
              f'D_v={D_v} \n ----------------------- \n')

    return end_time - start_time, U_r_v, sum(D_v), sum(L_v), l_avg


if __name__ == "__main__":
    R_x, R_y = 4, 4  # Number of routers
    rho = 0.01  # Weight for distance constraint in objective fn
    
    chiplet = False

    LinksCoordinates = None
    if chiplet:
        LinksCoordinates = np.array([[0, 1], 
                                     [0, 2], 
                                     [3, 1], 
                                     [3, 2]])
    else:
        LinksCoordinates = np.array([[0, 0], 
                                     [0, 1], 
                                     [1, 0], 
                                     [1, 1]])

    end_time, U_r_v, sum_D_v, sum_L_v, l_avg = milp_compute(R_x, R_y, LinksCoordinates, rho, silent_mode=False)

