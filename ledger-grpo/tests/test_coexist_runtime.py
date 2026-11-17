from types import SimpleNamespace

from coexist_runtime import actor_fractions, transition_actors


def test_actor_fractions_keep_declared_first_c_attempt_and_one_adjustment():
    assert actor_fractions("A", False) == [.75] * 4
    assert actor_fractions("B", False) == [.75] * 2
    assert actor_fractions("C", False) == [.45] * 4
    assert actor_fractions("C", True) == [.45, .37, .45, .45]


def test_sleep_leaves_admission_closed_until_successful_wake(tmp_path):
    calls = []
    def cohort(function):
        return [function(SimpleNamespace(
            post=lambda route: calls.append(route), get=lambda _route: {"is_sleeping": calls[-1].startswith("/sleep")}))]
    gate = tmp_path / "actor-gate"
    actors = SimpleNamespace(gate=gate, all=cohort)
    transition_actors(actors, sleeping=True)
    assert gate.is_file()
    transition_actors(actors, sleeping=False)
    assert not gate.exists()
    assert calls == ["/sleep?level=1&mode=wait", "/wake_up"]
