"""Route regressions for the observed isolated-waypoint failure."""
from types import SimpleNamespace
from unittest.mock import patch

from altru_redalert.ground_routes import GroundRoutes


def view(rows, origin=(0, 0), bounds=None, map_id="route-fixture"):
    if bounds is None:
        bounds = (*origin, len(rows[0]) if rows else 0, len(rows))
    return SimpleNamespace(map_info={"layout": {"rows": rows, "origin": list(origin)}},
                           bounds=bounds, map_id=map_id)


def test_isolated_passable_goal_cannot_trap_group_in_nearest_cell_projection():
    # Same failure class as Sidestep [43,60]: passable rough in an eight-cell cage.
    routes = GroundRoutes(view([".........", ".^^T.....", ".^,T.....",
                                ".^T^.....", "........."]))
    assert not routes.reachable((7, 2), (2, 2))
    point = routes.waypoint((7, 2), (2, 2), 6)
    assert point != [2, 2]
    assert routes.reachable((7, 2), point)


def test_short_waypoint_follows_route_around_wall_even_when_away_from_goal():
    routes = GroundRoutes(view([".........", "...^.....", "...^.....",
                                "...^.....", "...^.....", "...^.....", "........."]))
    point = routes.waypoint((2, 3), (5, 3), 2)
    assert routes.reachable((2, 3), point)
    assert point[0] <= 2 and point[1] != 3
    current = (2, 3)
    for _ in range(15):
        current = tuple(routes.waypoint(current, (5, 3), 2))
        if current == (5, 3):
            break
    assert current == (5, 3)


def test_conservative_diagonals_do_not_cut_two_blocked_corners():
    routes = GroundRoutes(view([".^", "^."]))
    assert not routes.reachable((0, 0), (1, 1))
    assert routes.waypoint((0, 0), (1, 1)) == [0, 0]


def test_open_diagonals_obey_path_distance_budget():
    routes = GroundRoutes(view(["...."] * 4))
    assert routes.waypoint((0, 0), (3, 3), 2) == [1, 1]
    assert routes.waypoint((0, 0), (3, 3), 5) == [3, 3]


def test_reverse_field_reused_for_many_units_and_updates_with_same_goal():
    routes = GroundRoutes(view(["." * 20] * 20))
    with patch.object(routes, "_build_field", wraps=routes._build_field) as build:
        for tick in range(100):
            assert routes.reachable((tick % 15, tick % 10),
                                    routes.waypoint((tick % 15, tick % 10), (19, 19)))
        assert build.call_count == 1


def test_layout_identity_includes_late_and_changed_map_content():
    initial = view(["...", "..."])
    routes = GroundRoutes(initial)
    assert routes.matches(view(["...", "..."]))
    assert not routes.matches(view([".^.", "..."]))
    assert not routes.matches(view(["...", "..."], origin=(2, 3)))
    assert not routes.matches(view(["...", "..."], map_id="other"))


def test_missing_or_malformed_map_does_not_invent_connectivity():
    malformed = [None, {}, {"rows": ["..", "."], "origin": [0, 0]},
                 {"rows": ["..", None], "origin": [0, 0]},
                 {"rows": [".."], "origin": [True, 0]}]
    for layout in malformed:
        raw = SimpleNamespace(map_info={"layout": layout}, bounds=(0, 0, 2, 2), map_id="x")
        routes = GroundRoutes(raw)
        assert routes.waypoint((0, 0), (1, 1)) is None
        assert not routes.reachable((0, 0), (1, 1))


def test_origin_and_playable_bounds_are_applied():
    routes = GroundRoutes(view(["....."] * 4, origin=(10, 20), bounds=(11, 21, 3, 2)))
    assert routes.reachable((11, 21), (13, 22))
    assert routes.waypoint((10, 20), (13, 22)) is None
    assert routes.waypoint((11, 21), (100, 100), 20) == [13, 22]


def test_unknown_symbols_and_mines_are_not_treated_as_open_terrain():
    routes = GroundRoutes(view([".M?.", ".~^." ]))
    assert not routes.reachable((0, 0), (3, 0))
    assert routes.waypoint((1, 0), (3, 0)) is None


def test_unknown_unit_position_requires_caller_fallback():
    routes = GroundRoutes(view(["...", ".^.", "..."]))
    assert routes.waypoint((1, 1), (2, 2)) is None
    assert routes.waypoint(None, (2, 2)) is None
    assert routes.waypoint((0, 0), None) is None


def test_layout_input_size_is_bounded():
    routes = GroundRoutes(view(["." * 257] * 257))
    assert routes.waypoint((0, 0), (20, 20)) is None


def test_available_distinguishes_missing_map_from_an_unknown_source():
    routes = GroundRoutes(view([".^", ".."] ))
    assert routes.available
    assert routes.waypoint((1, 0), (0, 0)) is None
    assert not GroundRoutes(view(["^^", "^^"])).available
    assert not GroundRoutes(SimpleNamespace(map_info={}, bounds=[0, 0, 2, 2])).available


def test_large_budget_endpoint_avoids_route_field_construction():
    routes = GroundRoutes(view([".....", ".^^^.", "....."]))
    with patch.object(routes, "_build_field", wraps=routes._build_field) as build:
        assert routes.waypoint((0, 0), (4, 2), 10000) == [4, 2]
        assert build.call_count == 0
