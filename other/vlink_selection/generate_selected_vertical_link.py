# (C) Copyright 2025 CEA LIST. All Rights Reserved.
# Contributor(s): Davy Million (davy.million@cea.fr)

import argparse
import os

from milp import *
from ruamel.yaml import YAML

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)

def parse_yaml(file_path):
    with open(file_path, 'r') as file:
        data = yaml.load(file)
    return data

def flat_id_to_yx(flat_id, dim_x):
    return [flat_id // dim_x, flat_id % dim_x]

def yx_to_flat_id(y, x, dim_x):
    return y * dim_x + x

def findOptimalVLSelection(vlink_placement):
    # Extract the source of the link and transform it in X/Y Coordinates
    vlink_pos = [flat_id_to_yx(vlink_id[0], dim_x) for vlink_id in vlink_placement]
    v = np.array(vlink_pos)
    _, U_r_v, _, _, _ = milp_compute(dim_x, dim_y, v, rho)
    # Extract the VL selected and flatten the X/Y coordinates to a local id
    l = []
    for router_i, vl_vector in enumerate(U_r_v):
        vl_selected_idx = list(vl_vector).index(1)
        vl_yx = v[vl_selected_idx]
        vl_flat_id = yx_to_flat_id(vl_yx[0], vl_yx[1], dim_x)
        # NOTE: int() conversion otherwise yaml fails to dump the data
        l.append((router_i, int(vl_flat_id)))
        print(f"{spacing*4}- [{router_i}, {vl_flat_id}]")
    return l


spacing = 2*" "
rho = 0.01

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse a YAML file.")
    parser.add_argument('yaml_file', type=str, help="Path to the YAML file")
    args = parser.parse_args()
    # Parse the YAML content
    data = parse_yaml(args.yaml_file)
    filename = os.path.basename(args.yaml_file)

    # Access mesh component one by one
    for mesh in data['multi_mesh']:
        mesh_data = data['multi_mesh'][mesh]
        dim_x = mesh_data['dim_x']
        dim_y = mesh_data['dim_y']
        dim_z = mesh_data['dim_z']
        n_virtual_channels = mesh_data['n_virtual_channels']

        print(f"{mesh}:")
        print(f"{spacing}vertical_link_selection:")

        for vl_dir in mesh_data['vertical_links_placement']:
            print(f"{spacing*2}{vl_dir}:")

            if vl_dir == "up":
                for chip_dst in mesh_data['vertical_links_placement'][vl_dir]:
                    print(f"{spacing*3}{chip_dst}:")
                    l = findOptimalVLSelection(mesh_data['vertical_links_placement'][vl_dir][chip_dst])
                    if not 'vertical_links_selection' in mesh_data:
                        mesh_data['vertical_links_selection'] = {}
                    if not f"{vl_dir}" in mesh_data['vertical_links_selection']:
                        mesh_data['vertical_links_selection'][vl_dir] = {}
                    if not f"{chip_dst}" in mesh_data['vertical_links_selection'][vl_dir]:
                        mesh_data['vertical_links_selection'][vl_dir][chip_dst] = l
            else: # vl_dir == "down"
                l = findOptimalVLSelection(mesh_data['vertical_links_placement'][vl_dir])
                if not 'vertical_links_selection' in mesh_data:
                    mesh_data['vertical_links_selection'] = {}
                if not f"{vl_dir}" in mesh_data['vertical_links_selection']:
                    mesh_data['vertical_links_selection'][vl_dir] = l

    with open(os.getcwd() + '/' + filename, 'w') as file:
        yaml.dump(data, file)

