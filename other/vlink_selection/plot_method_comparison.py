# (C) Copyright 2025 CEA LIST. All Rights Reserved.
# Contributor(s): Davy Million (davy.million@cea.fr)

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
import argparse
import math
import numpy as np
from io import StringIO

def create_plot(csv_data, output_file):
    data = pd.read_csv(StringIO(csv_data))

    speed_up_data = []

    for i, network_size in enumerate(data['Network Size'].unique()):
        milp_time = data[(data['Network Size'] == network_size) & (data['Method'] == 'MILP')]['End Time'].values[0]
        rexhaustive_time = None
        if i < 5:
            rexhaustive_time = data[(data['Network Size'] == network_size) & (data['Method'] == 'RExhaustive')]['End Time'].values[0]
        else:
            rexhaustive_time = np.nan

        speed_up = rexhaustive_time / milp_time
        print(speed_up, rexhaustive_time, milp_time)
        speed_up_data.append({'Network Size': network_size, 'Speed-up': speed_up, 'MILP Time': milp_time, 'RExhaustive Time': rexhaustive_time})

    speed_up_df = pd.DataFrame(speed_up_data)

    #speed_up_df = speed_up_df.sort_values(by='Network Size')
     
    mpl.rcParams.update({'lines.linewidth': 5})
    mpl.rcParams.update({'lines.markersize': 12})
    fig, ax1 = plt.subplots(1, 1, figsize=(12, 4))

    ax1.set_ylabel('Execution Time (s)', color='tab:blue', fontsize=25)
    ax1.plot(speed_up_df['Network Size'], speed_up_df['MILP Time'], marker='o', linestyle='-', color='tab:red', label='MILP')
    ax1.plot(speed_up_df['Network Size'], speed_up_df['RExhaustive Time'], marker='o', linestyle='-', color='tab:purple', label='Ex. Search')
    ax1.set_yscale('log')
    ax1.tick_params(axis='y', labelcolor='tab:blue', labelsize=18)

    ax1.set_xlabel('Problem Size (Mesh Dim X * Dim Y - #VLs)', fontsize=25)
    ax1.tick_params(axis='x', labelsize=20)

    for i, row in speed_up_df.iterrows():
        if i < 5:
            ax1.text(row['Network Size'], row['MILP Time']+ (row['MILP Time'] * 7), f"{row['MILP Time']:.2f}s", color='tab:red', ha='center', va='top', fontsize=19)
            if i > 1:
                ax1.text(row['Network Size'], row['MILP Time'] + (row['MILP Time'] * 9), f"~{math.ceil(row['Speed-up'])}x", color='tab:green', ha='center', va='bottom', fontsize=19)
            else:
                ax1.text(row['Network Size'], row['MILP Time'] + (row['MILP Time'] * 9), f"~{row['Speed-up']:.2f}x", color='tab:green', ha='center', va='bottom', fontsize=19)
        else:
            ax1.text(row['Network Size'], row['MILP Time'] +(row['MILP Time'] * 2) , f"{row['MILP Time']:.2f}s", color='tab:red', ha='center', va='bottom', fontsize=19)

    for i, row in speed_up_df.iterrows():
        if i == 0 or i == 2:
            ax1.text(row['Network Size'], row['RExhaustive Time']+(row['RExhaustive Time']*8/10), f"{row['RExhaustive Time']:.2f}s", color='tab:purple', ha='center', va='bottom', fontsize=19)
        elif i == 1:
            ax1.text(row['Network Size'], row['RExhaustive Time']-(row['RExhaustive Time']*0.9), f"{row['RExhaustive Time']:.2f}s", color='tab:purple', ha='center', va='bottom', fontsize=19)
        elif i == 3:
            ax1.text(row['Network Size'], row['RExhaustive Time']-(row['RExhaustive Time']*0.9), f"{row['RExhaustive Time']:.2f}s", color='tab:purple', ha='left', va='bottom', fontsize=19)
        elif i == 4:
            ax1.text(row['Network Size'], row['RExhaustive Time']-(row['RExhaustive Time']*0.6), f"{row['RExhaustive Time']:.2f}s", color='tab:purple', ha='left', va='center', fontsize=19)

    ax1.set_xticks(range(len(speed_up_df['Network Size'])))
    ax1.set_xticklabels(speed_up_df['Network Size'])

    ax1.legend(loc='upper left', fontsize=20, title='Methods:', title_fontsize=20)

    plt.tight_layout(pad=0.5)
    plt.grid()
    plt.savefig(output_file, format='pdf', bbox_inches='tight')

    plt.show()

def parse_arguments():
    parser = argparse.ArgumentParser(description='Create a plot from CSV data and export it to PDF.')
    parser.add_argument('input_file', type=str, help='Path to the input CSV file.')
    parser.add_argument('output_file', type=str, help='Path to the output PDF file.')
    return parser.parse_args()

def main():
    args = parse_arguments()

    with open(args.input_file, 'r') as file:
        csv_data = file.read()
        
    create_plot(csv_data, args.output_file)

if __name__ == '__main__':
    main()

