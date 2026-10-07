"""Small integration checks: python -m unittest test_pso_with_ql."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pso_with_ql as hybrid
import run_pipeline
from native_3d_mesh import run_all_mesh_graphs as batch

ROOT = Path(__file__).resolve().parent


class HybridTests(unittest.TestCase):
    def test_bellman_update(self):
        learner = hybrid.QLearningController()
        state = learner.observe(1.0, 0.5, 0)
        learner.choose(state, 1.0, 0.5)
        action = learner.previous[1]
        learner.observe(0.8, 0.4, 0, terminal=True)
        self.assertAlmostEqual(learner.table[state][action], 0.35 * 0.3)
        self.assertEqual(learner.updates, 1)

    def test_pipeline_and_batch_registration(self):
        self.assertEqual(run_pipeline._normalize_algorithm('pso_with_ql'), 'PSO_WITH_QL')
        command = batch.build_command('PSO_WITH_QL', Path('Graph1.txt'), batch.dims_for_core_count(16))
        self.assertIn('--pso-workers', command)

    def test_parallel_cache_and_modes(self):
        outputs = []
        for workers, mode, cache in ((1, 0, True), (2, 0, True), (1, 0, False), (2, 1, True)):
            with tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                graph = work / 'Graph1.txt'
                graph.write_text('16\n' + '\n'.join(' '.join('0' if i == j else str(1 + (i+j) % 5) for j in range(16)) for i in range(16)))
                command = [sys.executable, str(ROOT / 'pso_with_ql.py'), str(graph),
                           '2', '2', '2', '2', '1', '1', '4', '6', str(mode),
                           '--seed', '10', '--parallel-workers', str(workers)]
                if not cache:
                    command.append('--no-fitness-cache')
                result = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                output = json.loads(next((work / 'Particles').glob('*.txt')).read_text())
                self.assertEqual(output['algorithm'], 'pso_with_ql')
                self.assertEqual(output['q_learning']['updates'], 4)
                self.assertEqual(sum(output['q_learning']['action_counts']), 4)
                self.assertTrue(math.isfinite(output['effective_fitness']))
                mapping = [r for chip in output['chiplets'] for r in chip['core_to_router']]
                self.assertEqual(sorted(mapping), list(range(16)))
                output.pop("graph")  # Temporary input paths differ between runs.
                outputs.append(output)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])


if __name__ == '__main__':
    unittest.main()
