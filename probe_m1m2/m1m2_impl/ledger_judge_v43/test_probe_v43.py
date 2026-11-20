import unittest

from probe_v43 import apply, alias_pairs, stage_docids


def stage(number, names=(), credit=(), strict=False):
    items = None if names is None else [
        {"main_name": name, "status": status, "sought_condition": condition}
        for name, status, condition in names
    ]
    return {
        "trajectory_id": "synthetic", "stage_id": number, "items": items,
        "C_new": list(credit), "labels": {"strict_repeat": strict, "semantic_repeat": True,
                                         "invalid": items is None, "F_new": number == 2},
        "semantic_repeat_distances": [999],
    }


def named(name, condition="none"):
    return name, "correct", condition


class ReturnedDocumentsTest(unittest.TestCase):
    def test_fed_search_and_open_ids_only(self):
        def event(hits, opened=None, **extra):
            return {"status": "ok", "fed_to_model": True, "returned_docids": [
                {"docid": hit} for hit in hits], "opened_docid": opened, **extra}

        discarded = event(["unfed"])
        discarded["fed_to_model"] = False
        failed = event(["failed"])
        failed["status"] = "fail"
        old = event([], "open")
        old["visible_to_actor"] = old.pop("fed_to_model")
        native = {"tool_events": [event(["old", "same"]), event(["same"]), old, discarded, failed]}
        self.assertEqual(stage_docids(native), {"old", "same", "open"})

    def test_prefix_counts_and_frozen_labels_with_parallel_items(self):
        rows = [
            stage(1, [named("River Oak"), named("River Oak")]),
            stage(2, [named("RIVER-OAK", "k2"), named("Pine Hill")]),
            stage(3, [named("River Oak", "k3")]),
            stage(4, [named("River Oak", "k4")], credit=["k4"]),
            stage(5, [named("River Oak")], strict=True),
            stage(6, [named("Pine Hill")]),
        ]
        docs = [{"a"}, {"a"}, {"a", "b"}, {"b"}, {"b"}, {"a", "b"}]
        result = apply(rows, docs, set())
        self.assertEqual([(r["new_docids"], r["seen_docids"]) for r in result],
                         [(1, 0), (0, 1), (1, 1), (0, 1), (0, 1), (0, 2)])
        self.assertEqual([r["labels"]["semantic_repeat"] for r in result],
                         [False, True, False, False, False, True])
        self.assertEqual([r["semantic_repeat_distances"] for r in result], [[], [1], [], [], [], [4]])
        self.assertTrue(result[1]["labels"]["F_new"])
        self.assertTrue(result[4]["labels"]["strict_repeat"])
        self.assertEqual(result[2]["items"][0]["sought_condition"], "k3")
        self.assertTrue(rows[0]["labels"]["semantic_repeat"])

    def test_frozen_aliases_and_explicit_nameless_searches(self):
        aliases = alias_pairs([{"result": "yes", "names": {"A": "River Oak", "B": "Old Grove"}},
                               {"result": "no", "names": {"A": "River Oak", "B": "Young Grove"}}])
        absent = ("none", "none", "k2")
        rows = [
            stage(1, None), stage(2, [absent]), stage(3, [named("River Oak")]),
            stage(4, [named("Old Grove"), absent]), stage(5, [named("Young Grove")]),
            stage(6, [absent]), stage(7), stage(8, [("ordinary phrase", "non_proper_name", "none")]),
            stage(9, [absent], strict=True), stage(10, [absent], credit=["k2"]),
        ]
        result = apply(rows, [{"a"}, {"a"}, {"a"}, {"a"}, {"a"}, set(), {"a"}, {"a"}, {"a"}, {"a"}], aliases)
        self.assertEqual([r["stage_id"] for r in result if r["labels"]["semantic_repeat"]], [4])
        self.assertEqual([r["stage_id"] for r in result if r["labels"]["stale_return"]], [2])
        self.assertTrue(result[0]["labels"]["invalid"])
        self.assertEqual(result[0]["new_docids"], 1)
