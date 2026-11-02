"""Behavior and concurrency checks for the two threaded PSO variants."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext, redirect_stdout
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

    def manual_stack(self, model, levels=2, stacks=1):
        layout, total = model.build_topology(2, 2, 1, levels, 0, stacks)
        coordinates = model.assign_router_coordinates(total)
        state = []
        for chip in layout:
            start, end = chip["range"]
            assignment = [start + 4*z + t for z in range(levels) for t in (0, 0, 3, 3)]
            state.append([list(range(start, end+1)), [1, 0, 0, 1], assignment, 3])
        return layout, coordinates, state

    def edge_file(self, edges):
        path = Path("manual_edges.txt")
        path.write_text("".join(f"{a} {b} {bw}\n" for a, b, bw in edges), encoding="utf-8")
        return str(path)

    def test_hand_calculated_up_and_down_population_variances(self):
        for model in (plain, dp):
            with self.subTest(model=model.__name__):
                layout, coords, state = self.manual_stack(model)
                edges = self.edge_file([(0, 5, 2), (3, 7, 4), (5, 0, 3), (7, 3, 9)])
                # Upward loads [2,4] => 1; downward loads [3,9] => 9.
                self.assertEqual(model.tsv_variance_3p5d(state, layout, coords, edges), (1, 9))

    def test_all_interfaces_and_unused_links_enter_variance(self):
        for model in (plain, dp):
            with self.subTest(model=model.__name__):
                layout, coords, state = self.manual_stack(model, levels=4)
                edges = self.edge_file([(0, 12, 8), (12, 0, 4), (1, 2, 100)])
                # Three interfaces: loads [8,0]*3 up and [4,0]*3 down.
                # Same-layer traffic does not use TSV links.
                self.assertEqual(model.tsv_variance_3p5d(state, layout, coords, edges), (16, 4))

    def test_destination_ascent_uses_attachment_instead_of_reversed_descent(self):
        for model in (plain, dp):
            with self.subTest(model=model.__name__):
                layout, coords, state = self.manual_stack(model, stacks=2)
                edges = self.edge_file([(0, 12, 2), (1, 15, 4)])
                # Both packets enter at router 11 and cross 11->15. Across
                # four upward links the loads are [0,0,0,6], variance 6.75.
                self.assertEqual(model.tsv_variance_3p5d(state, layout, coords, edges), (6.75, 0))

    def test_native_intra_routing_rereads_assignment_at_each_xy_hop(self):
        for model in (plain, dp):
            with self.subTest(model=model.__name__):
                layout, total = model.build_topology(3, 3, 1, 2, 0, 1)
                coords = model.assign_router_coordinates(total)
                assignment = [2, 2, 2, 2, 8, 2, 8, 8, 8]
                state = [[list(range(total)), [0,0,1,0,0,0,0,0,1],
                          assignment + [a+9 for a in assignment], 0]]
                edges = self.edge_file([(4, 9, 2)])
                # 4 initially selects 8, but XY neighbor 5 selects TSV 2.
                # Actual path: 4->5->2->11->10->9, five hops * bandwidth 2.
                self.assertEqual(model.cost_function_3p5d(state, layout, edges), 10)
                self.assertEqual(model.tsv_variance_3p5d(state, layout, coords, edges), (1, 0))

    def test_dp_recurrence_reuses_intermediate_suffix_states(self):
        layout, coords, state = self.manual_stack(dp, levels=4)
        assignment = dp.build_global_tsv_assignment(state, layout)
        cache = {}
        first = dp._native_vertical_route(0, 3, layout[0], assignment, cache=cache)
        count = len(cache)
        suffix = dp._native_vertical_route(4, 3, layout[0], assignment, cache=cache)
        self.assertEqual(len(cache), count)
        self.assertEqual(first[0], suffix[0] + dp.VL_LATENCY)
        self.assertEqual(first[2][1:], suffix[2])
        self.assertTrue(all(len(key) == 3 for key in cache))

    def test_dp_cache_cannot_reuse_fitness_for_different_traffic(self):
        layout, coords, edges, particles = self.population(dp, 1)
        cache = {}
        dp.evaluate_particles_cached(particles, layout, coords, [(0, 1, 2)], cache)
        first = particles[0].cost
        dp.evaluate_particles_cached(particles, layout, coords, [(0, 1, 4)], cache)
        self.assertEqual(particles[0].cost, first * 2)
        self.assertEqual(len(cache), 2)

    def test_disabling_dp_fitness_cache_evaluates_duplicate_particles(self):
        layout, coords, edges, particles = self.population(dp, 1)
        particles.append(particles[0].clone())
        with patch.object(dp, "evaluate_particle_state", wraps=dp.evaluate_particle_state) as evaluate:
            dp.evaluate_particles_cached(particles, layout, coords, dp.load_edge_list(edges), None)
            self.assertEqual(evaluate.call_count, 2)

    def test_base_and_dp_match_seeded_search_after_all_updates(self):
        for mode in (0, 1):
            with self.subTest(mode=mode):
                results = []
                for model in (plain, dp):
                    with redirect_stdout(io.StringIO()):
                        result = model.run_pso_3p5d("Graph3", 2,2,1,2,1,1, 5,8,mode,seed=10)
                    data = json.loads(Path(model.particle_output_path("Graph3")).read_text())
                    results.append((result, data["effective_fitness"], data["variance_up"], data["variance_down"]))
                self.assertEqual(results[0], results[1])

    def test_base_evaluates_initial_population_and_every_update_once(self):
        with patch.object(plain, "evaluate_particle_state", wraps=plain.evaluate_particle_state) as evaluate:
            with redirect_stdout(io.StringIO()):
                plain.run_pso_3p5d("Graph3", 2,2,1,2,1,1, 3,4,0,seed=10)
            self.assertEqual(evaluate.call_count, 16)

    def test_assignment_repair_has_no_cycles_and_tsvs_select_themselves(self):
        for model in (plain, dp):
            layout, total = model.build_topology(3, 3, 1, 4, 0, 1)
            coords = model.assign_router_coordinates(total)
            edges = self.edge_file([])
            for mode in (0, 1):
                model.TSV_ASSIGNMENT_MODE = mode
                for seed in range(10):
                    model.random.seed(seed)
                    particle = model.Particle3p5d(layout, coords, edges, list(range(total)), evaluate_initial=False)
                    placement, assignment = particle.state[0][1:3]
                    for z in range(4):
                        self.assertFalse(model._assignment_has_cycle(assignment, 0, z*9, 9))
                        for pos, bit in enumerate(placement):
                            if bit:
                                self.assertEqual(assignment[z*9+pos], z*9+pos)

    def test_q_budget_is_truncation_and_state_stays_particle_hash(self):
        with patch.object(ql, "q_update_value", wraps=ql.q_update_value) as update:
            with redirect_stdout(io.StringIO()):
                ql.run_pso_3p5d("Graph3", 2,2,1,2,1,1, 2,4,0,seed=10,parallel_workers=1)
            self.assertEqual(update.call_count, 8)
            for call in update.call_args_list:
                self.assertEqual(len(call.args[1]), 64)
                self.assertFalse(call.kwargs.get("terminal", False))
        action = ()
        table = {"next": {action: -2}}
        value = ql.q_update_value(table, "state", action, 1, "next", alpha=1, gamma=.9, next_action_count=1)
        self.assertAlmostEqual(value, -.8)

    def test_separate_batch_entry_points_use_existing_framework(self):
        from native_3d_mesh import run_all_mesh_graphs as runner
        from native_3d_mesh import run_all_graphs_pso_3p5d as base_batch
        from native_3d_mesh import run_all_graphs_pso_dp_3p5d as dp_batch
        from native_3d_mesh import run_all_graphs_pso_ql_3p5d as ql_batch
        graph_count = len(list((ROOT / "Graphs").glob("Graph*.txt")))
        for batch, algorithm in ((base_batch, "PSO"), (dp_batch, "PSO_DP"), (ql_batch, "PSO_QL")):
            with self.subTest(algorithm=algorithm):
                with patch.object(runner, "ALGORITHMS", []), patch.object(runner, "DRY_RUN", True), \
                     patch.object(runner, "batch_lock", return_value=nullcontext()), \
                     patch.object(runner, "build_command", wraps=runner.build_command) as build, \
                     patch.object(sys, "argv", ["batch", "--results-start-time", "20261028_120000"]), \
                     redirect_stdout(io.StringIO()):
                    batch.main()
                    self.assertEqual(build.call_count, graph_count)
                    self.assertEqual({call.args[0] for call in build.call_args_list}, {algorithm})
        self.assertIs(run_pipeline.run_pso_dp_3p5d, dp.run_pso_3p5d)
        self.assertIs(run_pipeline.run_pso_ql_3p5d, ql.run_pso_3p5d)

    def test_native_2p5d_attachment_matches_optimizer_corner(self):
        import generate_yaml
        from native_3d_mesh.generate_yaml_mesh import _build_mesh_graph_native_3d
        layout, total = plain.build_topology(2,2,2,2,1,1)
        coords = plain.assign_router_coordinates(total)
        particle = plain.Particle3p5d(layout, coords, self.edge_file([]), list(range(total)), evaluate_initial=False)
        plain.write_particle_file("particle.json", "Graph3", 2,2,2,2,1,1,
                                   particle.state, layout, 0,0,0,0,0)
        data = json.loads(Path("particle.json").read_text())
        for build in (_build_mesh_graph_native_3d, generate_yaml._build_mesh_graph):
            _, _, base, _, meshes, links = build(data)
            attachments = []
            for link in links:
                child = meshes[link["child"]]
                parent = meshes[link["parent"]]
                if link["parent"] != base and parent["dim_x"] > 2 and child["dim_z"] == 1:
                    attachments.append(link["child_router"])
            self.assertEqual(attachments, [3, 3])

    def test_dense_graph_cost_is_bounded_by_normalizer(self):
        for model in (plain, dp):
            with self.subTest(model=model.__name__):
                layout, coords, state = self.manual_stack(model)
                edges = self.edge_file([(a, b, 1) for a in range(8) for b in range(a+1, 8)])
                model.init_normalization_terms("Graph3", edges, 2)
                cost = model.cost_function_3p5d(state, layout, edges)
                self.assertLessEqual(cost, model.MAX_COMM_COST)
                self.assertEqual(model.VAR_COMM_SQ, 28**2)

    def test_single_layer_has_no_tsv_variance_and_capacity_is_checked(self):
        for model in (plain, dp):
            with self.subTest(model=model.__name__):
                layout, capacity = model.build_topology(1,1,1,1,0,1)
                coords = model.assign_router_coordinates(capacity)
                edges = self.edge_file([])
                particle = model.Particle3p5d(layout, coords, edges, list(range(capacity)))
                self.assertEqual(particle.variance, 0)
                self.assertEqual(particle.state[0][1], [0])
                with self.assertRaisesRegex(ValueError, "more cores"):
                    model.init_normalization_terms("Graph3", edges, 1)

    def test_tsv_repair_has_a_guaranteed_fallback(self):
        for model in (plain, dp):
            layout, total = model.build_topology(2,2,1,2,0,1)
            coords = model.assign_router_coordinates(total)
            with patch.object(model, "TSV_REBUILD_ATTEMPTS", 0), \
                 patch.object(model.random, "choice", side_effect=lambda options: options[0]), \
                 patch.object(model.random, "shuffle", side_effect=lambda values: None):
                placement = model._validate_tsv_placement_single_3d([1,1,1,1], coords, 0, 4)
            indices = [i for i, enabled in enumerate(placement) if enabled]
            self.assertEqual(len(indices), 2)
            a, b = indices
            self.assertGreater(abs(a % 2 - b % 2) + abs(a // 2 - b // 2), 1)


if __name__ == "__main__":
    unittest.main()
