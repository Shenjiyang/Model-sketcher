import json
import importlib.util
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "plan_layout_elk.py"
EXAMPLE = ROOT / "assets" / "elk-layout-problem-example.json"
BRANCHING = ROOT / "assets" / "elk-layout-branching-example.json"
QKV = ROOT / "assets" / "elk-layout-qkv-example.json"
MOE = ROOT / "assets" / "elk-layout-moe-example.json"

MODULE_SPEC = importlib.util.spec_from_file_location("plan_layout_elk", SCRIPT)
ELK_ADAPTER = importlib.util.module_from_spec(MODULE_SPEC)
sys.path.insert(0, str(ROOT / "scripts"))
MODULE_SPEC.loader.exec_module(ELK_ADAPTER)
from audit_drawio import orthogonal_segments_conflict


def overlaps(first, second):
    return not (
        first["x"] + first["w"] <= second["x"]
        or second["x"] + second["w"] <= first["x"]
        or first["y"] + first["h"] <= second["y"]
        or second["y"] + second["h"] <= first["y"]
    )


def port_point(box, port):
    if port["side"] == "north":
        return box["x"] + box["w"] * port["position"], box["y"]
    if port["side"] == "south":
        return box["x"] + box["w"] * port["position"], box["y"] + box["h"]
    if port["side"] == "west":
        return box["x"], box["y"] + box["h"] * port["position"]
    return box["x"] + box["w"], box["y"] + box["h"] * port["position"]


def route_points(layout, problem, edge_id):
    edge = problem["edges"][edge_id]
    route = layout["edges"][edge_id]
    return [
        port_point(layout["nodes"][edge["source"]], route["source_port"]),
        *[tuple(point) for point in route["waypoints"]],
        port_point(layout["nodes"][edge["target"]], route["target_port"]),
    ]


def segment_hits_interior(first, second, box, epsilon=0.01):
    left, right = box["x"] + epsilon, box["x"] + box["w"] - epsilon
    top, bottom = box["y"] + epsilon, box["y"] + box["h"] - epsilon
    if math.isclose(first[0], second[0], abs_tol=epsilon):
        low, high = sorted((first[1], second[1]))
        return left < first[0] < right and max(low, top) < min(high, bottom)
    if math.isclose(first[1], second[1], abs_tol=epsilon):
        low, high = sorted((first[0], second[0]))
        return top < first[1] < bottom and max(low, left) < min(high, right)
    raise AssertionError(f"non-orthogonal route segment: {first} -> {second}")


class ElkLayoutTests(unittest.TestCase):
    def test_repository_bundles_pinned_offline_elk_runtime(self):
        runtime = ROOT / "vendor/elk/runtime/elk.bundled.js"
        metadata = json.loads((runtime.parent / "package.json").read_text())
        self.assertTrue(runtime.is_file())
        self.assertEqual(metadata["name"], "elkjs")
        self.assertEqual(metadata["version"], "0.12.0")

    def test_multiple_state_writes_reserve_separate_route_shelves(self):
        data = {"project": {"typography": {"edge_label_font": 20}},
                "regions": {"r": {}},
                "nodes": {n: {"region": "r", "kind": "state" if n == "s" else "operator"}
                          for n in ["a", "b", "c", "s"]},
                "edges": {n: {"source": n, "target": "s", "kind": "tensor"}
                          for n in ["a", "b", "c"]}}
        problem = ELK_ADAPTER.problem_from_region(data, "r", {n: (100,50) for n in data["nodes"]})
        self.assertAlmostEqual(problem["spacing"]["edge"], 56)
        del data["edges"]["c"]
        ordinary = ELK_ADAPTER.problem_from_region(data, "r", {n: (100,50) for n in data["nodes"]})
        self.assertAlmostEqual(ordinary["spacing"]["edge"], 22)

    def test_edge_clearance_applies_between_layers_too(self):
        problem = json.loads(EXAMPLE.read_text())
        problem.setdefault("spacing", {})["edge"] = 30
        options = ELK_ADAPTER.elk_graph(problem)["layoutOptions"]
        self.assertEqual(float(options["elk.spacing.edgeEdge"]), 30)
        self.assertEqual(float(options["elk.layered.spacing.edgeEdgeBetweenLayers"]), 30)

    def test_project_region_labeled_chain_has_compact_dependency_gap(self):
        data = {
            "project": {"typography": {"edge_label_font": 20}},
            "regions": {"detail": {"operator_sequences": [{"nodes": ["a", "b"]}]}},
            "nodes": {nid: {"region": "detail", "kind": "operator"} for nid in ("a", "b")},
            "edges": {"ab": {"source": "a", "target": "b", "kind": "tensor", "label": "[N,D]"}},
        }
        problem = ELK_ADAPTER.problem_from_region(data, "detail", {"a": (180, 64), "b": (180, 64)})
        layout = ELK_ADAPTER.layout_problem(problem, ROOT / "scripts/elk_runner.cjs", "node")
        a, b = layout["nodes"]["a"], layout["nodes"]["b"]
        gap = a["y"] - b["y"] - b["h"]
        self.assertGreaterEqual(gap, 64)
        # Include the visible flanks and renderer label-background reserve.
        self.assertLessEqual(gap, 110)

    def test_collinear_cleanup_preserves_visible_reversal(self):
        points = [(0, 0), (0, 20), (0, 10), (20, 10)]
        self.assertEqual(ELK_ADAPTER._drop_collinear(points), points)
        self.assertEqual(ELK_ADAPTER._drop_collinear([(0, 0), (0, 10), (0, 20)]),
                         [(0, 0), (0, 20)])

    def test_engine_execution_has_bounded_timeout(self):
        with patch.object(ELK_ADAPTER.subprocess, "run", side_effect=subprocess.TimeoutExpired("node", 45)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                ELK_ADAPTER.layout_problem(json.loads(EXAMPLE.read_text()), ROOT / "scripts/elk_runner.cjs", "node")
            self.assertEqual(run.call_args.kwargs["timeout"], 45)

    def test_endpoint_direction_rejects_tangent_and_inward_stubs(self):
        for points in ([(0, 100), (20, 100), (20, 0)],
                       [(0, 100), (0, 120), (20, 120), (20, 0)]):
            with self.assertRaisesRegex(ValueError, "source approach"):
                ELK_ADAPTER._validate_endpoint_direction(points, "north", "south", "bad")
        ELK_ADAPTER._validate_endpoint_direction([(0, 100), (0, 0)], "north", "south", "good")

    def test_label_search_avoids_other_labels_and_routes(self):
        label = {"x": -50, "y": 90, "width": 100, "height": 20}
        obstacle = {"x": -50, "y": 90, "w": 100, "h": 20}
        _, box = ELK_ADAPTER._label_position("label", [(0, 200), (0, 0)], label, 0,
                                            [obstacle], [[(-100, 50), (100, 50)]])
        self.assertFalse(overlaps(box, obstacle))
        self.assertFalse(segment_hits_interior((-100, 50), (100, 50), box))
        with self.assertRaisesRegex(ValueError, "no straight segment"):
            ELK_ADAPTER._label_position("label", [(0, 200), (0, 0)], label, 0,
                                        [{"x": -120, "y": -10, "w": 240, "h": 220}])

    def test_fixtures_have_no_crossings_or_shared_segments(self):
        for fixture in (EXAMPLE, BRANCHING, QKV, MOE):
            with self.subTest(fixture=fixture.name):
                layout = self.run_fixture(fixture)
                problem = json.loads(fixture.read_text())
                paths = {edge_id: route_points(layout, problem, edge_id) for edge_id in problem["edges"]}
                pairs = list(paths.items())
                for index, (left_id, left) in enumerate(pairs):
                    for right_id, right in pairs[index + 1:]:
                        for a, b in zip(left, left[1:]):
                            for c, d in zip(right, right[1:]):
                                self.assertFalse(orthogonal_segments_conflict(a, b, c, d),
                                                 f"{left_id}/{right_id}: {a,b}/{c,d}")

    def run_fixture(self, fixture=EXAMPLE):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "layout.json"
            result = subprocess.run(
                ["python3", str(SCRIPT), str(fixture), str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(output.read_text(encoding="utf-8"))

    def assert_no_edge_penetrates_unrelated_node(self, layout, fixture):
        problem = json.loads(fixture.read_text(encoding="utf-8"))
        for edge_id, edge in problem["edges"].items():
            points = route_points(layout, problem, edge_id)
            for node_id, box in layout["nodes"].items():
                if node_id in {edge["source"], edge["target"]}:
                    continue
                for first, second in zip(points, points[1:]):
                    self.assertFalse(
                        segment_hits_interior(first, second, box),
                        f"{edge_id} penetrates unrelated node {node_id}",
                    )

    def test_mla_decode_main_chain_is_vertical_and_non_overlapping(self):
        layout = self.run_fixture()
        main = ["input", "q_split", "wuk", "insert", "attention", "wuv", "output"]
        for source, target in zip(main, main[1:]):
            self.assertGreater(layout["nodes"][source]["y"], layout["nodes"][target]["y"])
        boxes = list(layout["nodes"].values())
        for index, first in enumerate(boxes):
            for second in boxes[index + 1 :]:
                self.assertFalse(overlaps(first, second))

    def test_ports_are_finite_and_boundary_normalized(self):
        layout = self.run_fixture()
        for route in layout["edges"].values():
            for name in ("source_port", "target_port"):
                port = route[name]
                self.assertIn(port["side"], {"north", "south", "east", "west"})
                self.assertTrue(math.isfinite(port["position"]))
                self.assertGreaterEqual(port["position"], 0.0)
                self.assertLessEqual(port["position"], 1.0)

    def test_port_conversion_fails_closed(self):
        box = {"x": 10.0, "y": 20.0, "w": 100.0, "h": 60.0}
        with self.assertRaisesRegex(ValueError, "away from its declared north boundary"):
            ELK_ADAPTER._port_from_point(box, (60.0, 24.0), "north", "bad-boundary")
        with self.assertRaisesRegex(ValueError, "out-of-range north port position"):
            ELK_ADAPTER._port_from_point(box, (115.0, 20.0), "north", "bad-position")

    def test_simple_main_chain_does_not_gain_bends(self):
        layout = self.run_fixture()
        main_edges = [
            "e_input_split",
            "e_split_wuk",
            "e_wuk_insert",
            "e_insert_attention",
            "e_attention_wuv",
            "e_wuv_output",
        ]
        for edge_id in main_edges:
            self.assertEqual(layout["edges"][edge_id]["waypoints"], [])
        self.assertLessEqual(len(layout["edges"]["e_cache_attention"]["waypoints"]), 2)

    def test_cache_is_a_side_lane_with_fixed_ports_and_clear_routes(self):
        layout = self.run_fixture()
        main = ["input", "q_split", "wuk", "insert", "attention", "wuv", "output"]
        main_right = max(layout["nodes"][node_id]["x"] + layout["nodes"][node_id]["w"] for node_id in main)
        self.assertGreater(layout["nodes"]["cache"]["x"], main_right)
        route = layout["edges"]["e_cache_attention"]
        self.assertEqual(route["source_port"]["side"], "west")
        self.assertEqual(route["target_port"]["side"], "east")
        self.assert_no_edge_penetrates_unrelated_node(layout, EXAMPLE)

    def test_edge_labels_participate_in_layout_without_node_overlap(self):
        layout = self.run_fixture()
        self.assertEqual(set(layout["edge_label_boxes"]), {"e_insert_attention", "e_cache_attention"})
        for edge_id, label_box in layout["edge_label_boxes"].items():
            for node_id, node_box in layout["nodes"].items():
                self.assertFalse(overlaps(label_box, node_box), f"{edge_id} label overlaps {node_id}")
            position = layout["edges"][edge_id]["label_position"]
            self.assertGreaterEqual(position["x"], -1.0)
            self.assertLessEqual(position["x"], 1.0)
            self.assertLessEqual(abs(position["y"]), 160.0)
            self.assertLessEqual(label_box["x"] + label_box["w"], layout["canvas"]["width"])
            self.assertLessEqual(label_box["y"] + label_box["h"], layout["canvas"]["height"])
        labels = list(layout["edge_label_boxes"].values())
        for index, first in enumerate(labels):
            for second in labels[index + 1:]:
                self.assertFalse(overlaps(first, second))

    def test_fork_join_and_residual_use_distinct_ordered_ports(self):
        layout = self.run_fixture(BRANCHING)
        self.assertEqual(layout["nodes"]["gate"]["y"], layout["nodes"]["up"]["y"])
        fork_ports = {
            layout["edges"]["e_norm_gate"]["source_port"]["position"],
            layout["edges"]["e_norm_up"]["source_port"]["position"],
        }
        merge_ports = {
            layout["edges"]["e_silu_mul"]["target_port"]["position"],
            layout["edges"]["e_up_mul"]["target_port"]["position"],
        }
        self.assertEqual(len(fork_ports), 2)
        self.assertEqual(len(merge_ports), 2)
        residual = layout["edges"]["e_residual_skip"]
        self.assertEqual(residual["source_port"]["side"], "west")
        self.assertEqual(residual["target_port"]["side"], "west")
        self.assertLessEqual(len(residual["waypoints"]), 2)
        self.assert_no_edge_penetrates_unrelated_node(layout, BRANCHING)

    def test_layout_is_deterministic(self):
        first = self.run_fixture()
        self.assertEqual(first, self.run_fixture())
        self.assertEqual(first["engine"], {"name": "elk-layered", "elkjsVersion": "0.12.0"})

    def test_missing_elk_dependency_fails_instead_of_falling_back(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            runner = temp / "elk_runner.cjs"
            shutil.copy2(ROOT / "scripts" / "elk_runner.cjs", runner)
            output = temp / "result.json"
            environment = os.environ.copy()
            environment["ELKJS_MODULE"] = str(temp / "missing-elkjs.cjs")
            result = subprocess.run(
                ["node", str(runner), str(EXAMPLE), str(output)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unable to load elkjs", result.stderr)
            self.assertFalse(output.exists())

    def test_packed_qkv_fork_and_multi_input_attention_are_clear(self):
        layout = self.run_fixture(QKV)
        self.assertEqual(
            layout["edges"]["e_split_k"]["waypoints"], [],
            "near-axis split lane should be snapped to a straight route",
        )
        split_ports = {
            layout["edges"][edge_id]["source_port"]["position"]
            for edge_id in ("e_split_q", "e_split_k", "e_split_v")
        }
        qk_ports = {
            layout["edges"][edge_id]["target_port"]["position"]
            for edge_id in ("e_q_qk", "e_k_qk")
        }
        self.assertEqual(len(split_ports), 3)
        self.assertEqual(len(qk_ports), 2)
        self.assertEqual(layout["edges"]["e_v_av"]["source_port"]["side"], "west")
        self.assertEqual(layout["edges"]["e_v_av"]["target_port"]["side"], "east")
        self.assert_no_edge_penetrates_unrelated_node(layout, QKV)
        for label_box in layout["edge_label_boxes"].values():
            for node_box in layout["nodes"].values():
                self.assertFalse(overlaps(label_box, node_box))

    def test_routed_and_shared_experts_remain_parallel_until_aggregation(self):
        layout = self.run_fixture(MOE)
        self.assertNotEqual(layout["nodes"]["router"]["x"], layout["nodes"]["shared_experts"]["x"])
        source_ports = {
            layout["edges"]["e_input_router"]["source_port"]["position"],
            layout["edges"]["e_input_shared"]["source_port"]["position"],
        }
        target_ports = {
            layout["edges"]["e_combine_aggregate"]["target_port"]["position"],
            layout["edges"]["e_shared_aggregate"]["target_port"]["position"],
        }
        self.assertEqual(len(source_ports), 2)
        self.assertEqual(len(target_ports), 2)
        self.assert_no_edge_penetrates_unrelated_node(layout, MOE)


if __name__ == "__main__":
    unittest.main()
