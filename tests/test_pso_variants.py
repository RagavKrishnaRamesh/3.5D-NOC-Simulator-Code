"""Behavior and concurrency checks for the two threaded PSO variants."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import random
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pso_3p5d as plain
import pso_with_only_dp as dp
import pso_with_only_ql as ql
import run_pipeline


class PsoVariantTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.previous_cwd = Path.cwd()
        os.chdir(self.temporary.name)
        Path("Graphs").mkdir()
        shutil.copyfile(ROOT / "tests/fixtures/Graph3.txt", "Graphs/Graph3.txt")

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temporary.cleanup()

    def population(self, model, count=8):
        model.random.seed(29)
        model.TSV_ASSIGNMENT_MODE = 0
        layout, total = model.build_topology(2, 2, 1, 2, 1, 1)
        edge_file = model.edge_set_output_path("Graph3")
        with redirect_stdout(io.StringIO()):
            model.create_edge_set("Graphs/Graph3.txt", edge_file)
        coordinates = model.assign_router_coordinates(total)
        model.init_normalization_terms("Graph3", edge_file, 2)
        particles = [model.Particle3p5d(layout, coordinates, edge_file, list(range(total)), evaluate_initial=False)
                     for _ in range(count)]
        return layout, coordinates, edge_file, particles

    def test_threaded_fitness_matches_serial_when_jobs_overlap(self):
        for model in (plain, dp):
            with self.subTest(model=model.__name__):
                layout, coordinates, edges, particles = self.population(model)
                expected = [model.evaluate_particle_state(p.state, layout, coordinates, edges) for p in particles]
                barrier = threading.Barrier(4)
                entered = threading.local()
                calculate_count = model.calculate_count

                def overlap(src, dst):
                    if not getattr(entered, "ready", False):
                        entered.ready = True
                        barrier.wait(timeout=10)
                    return calculate_count(src, dst)

                with patch.object(model, "calculate_count", overlap), ThreadPoolExecutor(max_workers=4) as pool:
                    actual = list(pool.map(lambda p: model.evaluate_particle_state(p.state, layout, coordinates, edges), particles))
                self.assertEqual(actual, expected)

    def test_dp_metrics_match_plain_evaluator_and_cache_reuses_states(self):
        layout, coordinates, edges, particles = self.population(dp)
        self.population(plain)
        for particle in particles:
            self.assertEqual(dp.evaluate_particle_state(particle.state, layout, coordinates, edges),
                             plain.evaluate_particle_state(particle.state, layout, coordinates, edges))
        duplicates = [particles[0], particles[0].clone()]
        cache = {}
        with patch.object(dp, "evaluate_particle_state", wraps=dp.evaluate_particle_state) as evaluate:
            with ThreadPoolExecutor(max_workers=2) as pool:
                dp.evaluate_particles_cached(duplicates, layout, coordinates, dp.load_edge_list(edges), cache, executor=pool)
                dp.evaluate_particles_cached(duplicates, layout, coordinates, dp.load_edge_list(edges), cache, executor=pool)
            self.assertEqual(evaluate.call_count, 1)
        self.assertEqual(duplicates[0].fitness_value, duplicates[1].fitness_value)

    def test_ql_evaluates_duplicates_without_memoization(self):
        layout, coordinates, edges, particles = self.population(plain, 2)
        particles[1] = particles[0].clone()
        with patch.object(plain, "evaluate_particle_state", wraps=plain.evaluate_particle_state) as evaluate:
            with ThreadPoolExecutor(max_workers=2) as pool:
                ql.evaluate_particles(particles, layout, coordinates, edges, pool)
                ql.evaluate_particles(particles, layout, coordinates, edges, pool)
            self.assertEqual(evaluate.call_count, 4)

    def test_hash_includes_the_entire_particle(self):
        state = [[[0, 1, 2, 3], [1, 0], [0, 0, 2, 2], 0]]
        original = ql.q_state_key(state)
        self.assertEqual(len(original), 64)
        self.assertEqual(original, ql.q_state_key(copy.deepcopy(state)))
        for component in range(4):
            changed = copy.deepcopy(state)
            if component == 3:
                changed[0][component] = 1
            else:
                changed[0][component][0] += 1
            self.assertNotEqual(original, ql.q_state_key(changed))

    def test_ordered_swaps_preserve_permutation_and_tsv_count(self):
        state = [[[0, 1, 2, 3], [1, 0, 1, 0], [0, 0, 2, 2], 0]]
        layout = [{"type": "3d", "no_routers": 4}]
        action = (("mapping", -1, 0, 1), ("mapping", -1, 1, 2), ("tsv", 0, 0, 1))
        changed = ql.apply_swap_action(state, action, layout)
        self.assertEqual(changed[0][0], [1, 2, 0, 3])
        self.assertEqual(sum(changed[0][1]), sum(state[0][1]))
        self.assertEqual(ql.apply_swap_action(changed, tuple(reversed(action)), layout), state)
        self.assertEqual(state[0][0], [0, 1, 2, 3])
        with self.assertRaises(ValueError):
            ql.apply_swap_action(state, (("mapping", -1, 0, 99),), layout)

    def test_bellman_update_and_epsilon_greedy_use_concrete_sequences(self):
        action = (("mapping", -1, 0, 1), ("mapping", -1, 1, 2))
        other = (("mapping", -1, 0, 2),)
        table = {"next": {other: 2.0}, "state": {action: 0.5}}
        value = ql.q_update_value(table, "state", action, 1.0, "next", alpha=0.2, gamma=0.9)
        self.assertAlmostEqual(value, 0.96)
        self.assertEqual(ql.q_choose_action(table, "state", [action, other], epsilon=0, rng=random.Random(10)), action)
        terminal = ql.q_update_value(table, "terminal", action, 1.0, "next", alpha=1, gamma=0.9, terminal=True)
        self.assertEqual(terminal, 1.0)

    def test_candidate_sequences_are_bounded_and_replayable(self):
        layout, coordinates, edges, particles = self.population(plain, 2)
        particles[0].mapping_velocity = [(0, 1), (1, 2)]
        actions = ql.build_swap_actions(particles[0], particles[1], particles[1], layout, max_swaps=2)
        self.assertIn((), actions)
        self.assertTrue(any(len(action) > 1 for action in actions))
        for action in actions:
            self.assertLessEqual(len(action), 2)
            ql.validate_swap_action(particles[0].state, action)
            changed = ql.apply_swap_action(particles[0].state, action, layout)
            self.assertEqual(sorted(plain.flatten_particle_mapping(changed)),
                             sorted(plain.flatten_particle_mapping(particles[0].state)))

    def test_seeded_optimizers_match_with_one_or_four_workers(self):
        for variant, mode in ((dp, 0), (dp, 1), (ql, 0), (ql, 1)):
            with self.subTest(variant=variant.__name__, mode=mode):
                results = []
                tables = []
                for workers in (1, 4):
                    with redirect_stdout(io.StringIO()):
                        state, cost = variant.run_pso_3p5d("Graph3", 2, 2, 1, 2, 1, 1, 5, 8,
                                                          tsv_assignment_mode=mode, seed=10, parallel_workers=workers)
                    data = json.loads(Path(variant.particle_output_path("Graph3")).read_text())
                    self.assertEqual(data["optimizer"]["backend"], "threads")
                    results.append((state, cost, data["effective_fitness"]))
                    if variant is ql:
                        self.assertFalse(data["optimizer"]["dp"])
                        self.assertFalse(data["optimizer"]["fitness_cache"])
                        self.assertEqual(data["optimizer"]["q_updates"], 40)
                        table = json.loads(Path(data["optimizer"]["q_table_file"]).read_text())
                        tables.append(table)
                        self.assertTrue(any(entry["value"] != 0 for row in table["states"].values() for entry in row))
                    else:
                        self.assertFalse(data["optimizer"]["q_learning"])
                        self.assertGreater(data["optimizer"]["cache_hits"], 0)
                self.assertEqual(results[0], results[1])
                if tables:
                    self.assertEqual(tables[0], tables[1])

    def test_pipeline_names_and_output_files_are_distinct(self):
        self.assertEqual(run_pipeline._normalize_algorithm("PSO+DP"), "PSO_DP")
        self.assertEqual(run_pipeline._normalize_algorithm("PSO+QL"), "PSO_QL")
        self.assertNotEqual(dp.particle_output_path("Graph3"), ql.particle_output_path("Graph3"))
        self.assertNotEqual(dp.particle_output_path("Graph3"), plain.particle_output_path("Graph3"))


if __name__ == "__main__":
    unittest.main()
