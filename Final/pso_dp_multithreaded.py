#!/usr/bin/env python3
"""Run the DP optimizer with concurrent particle fitness evaluation."""

from functools import partial

import pso_with_only_dp as dp


run_pso_3p5d = partial(dp.run_pso_3p5d, threaded=True)
particle_output_path = partial(dp.particle_output_path, threaded=True)


if __name__ == "__main__":
    dp.main(threaded=True)
