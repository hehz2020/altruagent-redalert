from altru_redalert.economy import Economy, _reserved
from altru_redalert.model import View
from redalert_bot_tests.test_development_v22 import development_view, purchases, purchase_cost
from redalert_bot_tests.test_economy_v2 import actor, view


def air_view(seconds=150, cash=1100, enemies=None, allied=False, defenders=(), pending=()):
    if enemies is None:
        enemies = [actor(90, "yak", 31, 12)]
    initial = development_view(seconds=seconds, cash=cash, harvesters=2,
                               refineries=2, vehicle=False, enemies=enemies, pending=pending)
    initial.raw["observation"]["units"] += list(defenders)
    if allied:
        initial.raw["legal_actions"]["train"] = ["harv", "2tnk", "e1", "e3"]
    return View(initial.raw, initial.config, list(pending))


def test_aircraft_counter_precedes_optional_third_harvester():
    v = air_view()
    result = purchases(v)
    assert {"cmd": "train", "item": "ftrk"} in result
    assert any(order["item"] == "e3" for order in result)
    assert all(order["item"] not in {"harv", "proc", "fix"} for order in result)


def test_faction_without_flak_vehicle_buys_real_aa_instead_of_ground_tank():
    result = purchases(air_view(allied=True, cash=850))
    assert any(order["item"] == "e3" for order in result)
    assert all(order["item"] not in {"harv", "2tnk", "fix"} for order in result)


def test_small_bank_releases_development_savings_for_available_counter():
    assert purchases(air_view(cash=300)) == [{"cmd": "train", "item": "e3"}]


def test_short_air_contact_loss_keeps_response_but_memory_expires():
    policy = Economy()
    purchases(air_view(cash=0), policy)
    assert any(order["item"] == "ftrk" for order in purchases(air_view(170, enemies=[]), policy))
    assert purchases(air_view(186, enemies=[]), policy) == [{"cmd": "train", "item": "harv"}]


def test_existing_aa_force_releases_economic_development():
    troops = [actor(100 + i, "e3") for i in range(4)]
    assert purchases(air_view(defenders=troops)) == [{"cmd": "train", "item": "harv"}]


def test_distant_or_crippled_aa_does_not_hide_an_exposed_home_air_gap():
    for defenders in ([actor(100 + i, "ftrk", 90, 60) for i in range(3)],
                      [actor(100 + i, "ftrk", hp=10) for i in range(3)]):
        result = purchases(air_view(defenders=defenders))
        assert {"cmd": "train", "item": "ftrk"} in result


def test_unpowered_air_defense_does_not_count_as_live_coverage():
    v = air_view()
    v.buildings.append(actor(100, "sam", 29, 12, powered=False))
    assert {"cmd": "train", "item": "ftrk"} in purchases(v)


def test_unarmed_transport_does_not_freeze_development():
    assert purchases(air_view(enemies=[actor(90, "tran", 31, 12)])) == [
        {"cmd": "train", "item": "harv"}]


def test_pending_flak_and_rockets_count_toward_coverage_without_double_spending():
    pending = [{"cmd": "train", "item": "ftrk"}, {"cmd": "train", "item": "e3", "count": 2}]
    v = air_view(cash=2300, pending=pending)
    result = purchases(v)
    assert not any(order["cmd"] == "train" for order in result)
    assert purchase_cost(v, result) + _reserved(v) <= v.funds


def test_two_approaching_tanks_release_optional_economy_before_contact():
    enemies = [actor(90 + i, "2tnk", 31, 10 + i) for i in range(2)]
    v = development_view(cash=1100, harvesters=2, refineries=2, vehicle=False, enemies=enemies)
    result = purchases(v)
    assert any(order["item"] == "e3" for order in result)
    assert all(order["item"] not in {"harv", "fix", "proc"} for order in result)


def siege_view(*, cash=1500, tanks=3, tank_hp=100, artillery=0, pending=(), enemies=(), layout=None):
    units = [actor(20 + i, "harv", idle=False) for i in range(4)]
    units += [actor(40 + i, "2tnk", hp=tank_hp) for i in range(tanks)]
    units += [actor(60 + i, "arty") for i in range(artillery)]
    initial = view(cash=cash, units=units, train=["2tnk", "arty", "e1", "e3", "harv"],
                   build=[], pending=pending, enemies=enemies)
    initial.raw["observation"]["visible_enemy_buildings"] = [actor(90, "tsla", 75, 20)]
    if layout is not None:
        initial.config["rules"]["maps"] = {"test": {"layout": {"origin": [0, 0], "rows": layout}}}
    return View(initial.raw, initial.config, list(pending))


def test_observed_static_defense_gets_guarded_siege_without_five_rifles():
    result = purchases(siege_view())
    assert {"cmd": "train", "item": "arty"} in result


def test_siege_does_not_replace_three_healthy_frontline_tanks():
    for tanks, hp in ((2, 100), (3, 50)):
        assert not any(order["item"] == "arty" for order in purchases(siege_view(tanks=tanks, tank_hp=hp)))


def test_queued_siege_counts_toward_escort_ratio_and_escrow():
    v = siege_view(cash=2000, pending=[{"cmd": "train", "item": "arty"}])
    result = purchases(v)
    assert not any(order["item"] == "arty" for order in result)
    assert purchase_cost(v, result) + _reserved(v) <= v.funds


def test_second_siege_requires_six_live_tanks():
    assert not any(order["item"] == "arty" for order in purchases(siege_view(artillery=1)))
    assert {"cmd": "train", "item": "arty"} in purchases(siege_view(tanks=6, artillery=1))


def test_local_armor_pressure_precedes_siege_investment():
    enemies = [actor(100 + i, "2tnk", 20, 10 + i) for i in range(3)]
    assert not any(order["item"] == "arty" for order in purchases(siege_view(enemies=enemies)))


def test_static_target_across_wide_water_does_not_trigger_unusable_siege():
    rows = ["." * 30 + "~" * 31 + "." * 59 for _ in range(70)]
    assert not any(order["item"] == "arty" for order in purchases(siege_view(layout=rows)))


def test_refinery_placement_chooses_reachable_ore_over_nearer_island():
    rows = [["."] * 120 for _ in range(70)]
    for row in rows:
        row[12] = "~"
    rows[10][14] = "$"
    rows[18][6] = "$"
    v = view()
    v.map_info = {"layout": {"origin": [0, 0], "rows": ["".join(row) for row in rows]}}
    policy = Economy()
    policy._refresh(v)
    assert policy._ore(v, (10, 10)) == (6, 18)


def test_siege_requires_a_cash_margin_and_time_to_join_the_front():
    assert not any(order["item"] == "arty" for order in purchases(siege_view(cash=1099)))
    v = siege_view()
    v.remaining = 70
    assert not any(order["item"] == "arty" for order in purchases(v))
