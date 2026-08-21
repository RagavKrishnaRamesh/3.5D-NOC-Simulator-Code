# (C) Copyright 2025 CEA LIST. All Rights Reserved.
# Contributor(s): Davy Million (davy.million@cea.fr)

import copy
import time

class Point2D(object):
    def __init__(self, x: int, y: int):
        self._x = x
        self._y = y

class Router(Point2D):
    def __init__(self, x: int, y: int):
        super().__init__(x, y)

class vLink(Point2D):
    def __init__(self, x: int, y: int):
        super().__init__(x, y)

class Topology(object):
    def __init__(self, mesh_dim_x: int, mesh_dim_y: int):
        self.dim_x = mesh_dim_x
        self.dim_y = mesh_dim_y
        self.routers = [Router(x, y) for x in range(0, self.dim_x) for y in range(0, self.dim_y)]

# This function generates all the possible values of U_r_v by emulating an
# addition in base 4
def gen_possibilities(t: Router, vertical_links):
    U_r_v = [1 for r in range(len(t.routers))]

    BASE_VALUE = len(U_r_v)-1
    line_counter = BASE_VALUE
    carry = 0
    loop = True

    yield U_r_v # yield first possibility
    while (loop):
        if carry:
            idx = U_r_v[line_counter]
            if line_counter == 0 and idx == len(vertical_links):
                loop = False
            
            # Carry is applied to [1, 2, ..., len(vertical_links)-1]
            if idx < len(vertical_links):
                U_r_v[line_counter] += 1
                yield U_r_v
                line_counter = BASE_VALUE
                carry = 0
            # Carry is applied to len(vertical_links), which generates a new carry to the upper context
            else:
                U_r_v[line_counter] = 1
                line_counter -= 1
        else: #!carry
            for V_j in range(len(vertical_links)):
                if V_j < len(vertical_links)-1:
                    U_r_v[line_counter] += 1
                    yield U_r_v
                else:
                    U_r_v[line_counter] = 1
                    line_counter -= 1
                    carry = 1

def exhaustive_search(R_x, R_y, vertical_links, rho):
    start_time = time.time()
    t = Topology(R_x, R_y)

    min_C_s = None
    min_D_v = None
    min_L_v = None
    min_set_s = None
    min_l_avg = None
    nb_min = 0

    # Iterate over all the possible U_r^v
    for enum_i, set_s in enumerate(gen_possibilities(t, vertical_links)):
        l_avg = 0
        # (1) Compute l_v / l_avg
        l_v_list = []
        for vlink in range(len(vertical_links)):
            l_v = 0
            for i in range(len(t.routers)):
                # NOTE: set_s in {1, 2, 3, 4}
                if vlink+1 == set_s[i]:
                    l_v += 1
            l_v = l_v / (R_x * R_y)
            l_avg += l_v
            l_v_list.append(l_v)
        l_avg = l_avg / len(vertical_links)

        # (2) Compute L_v
        L_v = []
        for vlink in range(len(vertical_links)):
            L_v.append(abs((l_v_list[vlink] - l_avg)/l_avg))
        
        D_v = [0 for vlink in range(len(vertical_links))]

        for R_i in range(len(t.routers)):
            curr_vlink = vertical_links[set_s[R_i]-1]
            vlink_x, vlink_y = curr_vlink._x, curr_vlink._y
            curr_router_x, curr_router_y = t.routers[R_i]._x, t.routers[R_i]._y
            D_v[set_s[R_i]-1] += abs(curr_router_x - vlink_x) + abs(curr_router_y - vlink_y)

        C_s = 0
        for vlink in range(len(vertical_links)):
            C_s += (rho * D_v[vlink]) + L_v[vlink]

        # First case
        if min_C_s is None:
            min_C_s = C_s
            min_D_v = copy.deepcopy(D_v)
            min_L_v = copy.deepcopy(L_v)
            min_set_s = copy.deepcopy(set_s)
            min_l_avg = l_avg

        # Testing min
        if C_s < min_C_s:
            min_C_s = C_s
            min_D_v = copy.deepcopy(D_v)
            min_L_v = copy.deepcopy(L_v)
            min_set_s = copy.deepcopy(set_s)
            min_l_avg = l_avg

    print("U_r_v:", min_set_s)
    print("D_v:"  , min_D_v)
    print("L_v:"  , min_L_v)
    print("l_avg:", min_l_avg)

    end_time = time.time()
    return end_time - start_time, min_set_s, sum(min_D_v), sum(min_L_v), min_l_avg


if __name__ == "__main__":
    R_x = 2
    R_y = 2

    # Generate all the vertical links
    vertical_links = [vLink(0, 0),
                      vLink(0, 1),
                      vLink(1, 0),
                      vLink(1, 1)]

    _ = exhaustive_search(R_x, R_y, vertical_links, 0.01)

