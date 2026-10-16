from copy import deepcopy

import pytest

from altru_redalert.combat import Military
from altru_redalert.core import Controller
from altru_redalert.model import View, distance
from redalert_bot_tests.test_adversarial import actor, commands, snapshot
from redalert_bot_tests.test_v24_integration import accepted, legal_batch, mapped


def home_state(now, army, enemies=(), buildings=None):
    raw = snapshot(now, units=deepcopy(army), enemies=deepcopy(enemies),
                   buildings=buildings if buildings is not None else [actor(1, "fact", 20, 20)])
    raw["observation"]["base_center"] = [20, 20]
    raw["legal_actions"]["enemy_base"] = [90, 80]
    return raw


def remote_army():
    return [actor(10+i, "3tnk", 70+i % 2, 60+i // 2) for i in range(19)]


def raiders(count=4):
    return [actor(100+i, "e1", 23, 20+i % 3) for i in range(count)]


def step(bot, raw):
    batch = commands(bot.decide(raw, mapped()))
    legal_batch(raw, mapped(), batch)
    accepted(bot, batch)
    return batch


@pytest.mark.parametrize("main_deadline", [0, 999])
def test_defenders_crossing_nine_cells_do_not_recharge_and_refuge_stays_home(main_deadline):
    military = Military()
    military.retreat_until = main_deadline
    military.withdraw_goal = (90, 90)
    enemies = [actor(100+i, "e1", 25, 20+i % 2) for i in range(6)]
    goals = []
    for now, x in [(300, 17), (303, 15), (306, 17), (309, 12), (312, 15)]:
        army = [actor(10+i, "e1", x, 20+i) for i in range(2)]
        view = View(home_state(now, army, enemies), mapped())
        intents, assigned = military._defense(view, army, enemies)
        assert assigned == {10, 11}
        assert not any(i.order["cmd"] == "attack_move" for i in intents)
        goals.append(tuple(military.defense_posts[1]["withdraw_goal"]))
        assert distance(goals[-1], (20, 20)) <= 10
        assert military.withdraw_goal == (90, 90)
        assert military.retreat_until == main_deadline
        military.mark_sent([i.order for i in intents], now)
    assert len(set(goals)) == 1


def test_distant_rescue_survives_threshold_and_fog_but_one_scout_cannot_renew_it():
    army, bot = remote_army(), Controller()
    ids = {a["id"] for a in army}
    first = step(bot, home_state(400, army, raiders()))
    assert {uid for o in first for uid in o.get("units", [])} == ids
    deadline = bot.military.defense_posts[1]["recall_until"]
    for now, enemies in [(403, raiders(3)), (406, []), (409, raiders(1)), (411, raiders(1))]:
        batch = step(bot, home_state(now, army, enemies))
        assert bot.military.mode == "defend"
        assert bot.military.defense_posts[1]["guards"] == ids
        assert bot.military.defense_posts[1]["recall_until"] == deadline
        assert all(o.get("target") is None for o in batch)  # no fog id attacks
        assert all(distance(o["to"], (20, 20)) < 10 for o in batch if "to" in o)
    released = step(bot, home_state(deadline+1, army, raiders(1)))
    assert bot.military.mode == "pressure"
    assert any(o["cmd"] == "attack_move" and o["to"][0] > 70 for o in released)


def test_distant_rescue_releases_when_all_protected_assets_are_gone():
    army, bot = remote_army(), Controller()
    step(bot, home_state(400, army, raiders()))
    batch = step(bot, home_state(403, army, buildings=[]))
    assert not bot.military.defense_posts
    assert bot.military.mode == "pressure"
    assert any(o.get("to", [0])[0] > 70 for o in batch)


@pytest.mark.parametrize("leading_x", [49, 52])
def test_staggered_rescue_does_not_release_travelling_peers_of_one_leading_tank(leading_x):
    army, bot = remote_army(), Controller()
    enemies = [actor(100+i, "e3", 23, 20+i % 3) for i in range(6)]
    step(bot, home_state(400, army, enemies))
    ids = {a["id"] for a in army}
    assert bot.military.defense_posts[1]["guards"] == ids
    army[0].update(x=leading_x, y=20)
    for now, visible in [(403, enemies[:3]), (406, [])]:
        batch = step(bot, home_state(now, army, visible))
        assert bot.military.mode == "defend"
        assert bot.military.defense_posts[1]["guards"] == ids
        assert all(distance(o["to"], (20, 20)) < 10 for o in batch if "to" in o)


def test_fresh_major_threat_renews_rescue_and_asset_handoff_preserves_it():
    army, bot = remote_army(), Controller()
    structures = [actor(1, "proc", 20, 20), actor(2, "fact", 18, 20)]
    step(bot, home_state(400, army, raiders(), structures))
    assert set(bot.military.defense_posts) == {1}
    original = next(iter(bot.military.defense_posts.values()))["recall_until"]
    step(bot, home_state(403, army, raiders(3), [structures[1]]))
    assert set(bot.military.defense_posts) == {2}
    assert bot.military.defense_posts[2]["recall_until"] == original
    step(bot, home_state(410, army, raiders(8), [structures[1]]))
    assert bot.military.defense_posts[2]["recall_until"] > original
    assert bot.military.defense_posts[2]["guards"] == {a["id"] for a in army}


def test_new_threat_at_old_refuge_changes_refuge_without_leaving_home():
    military = Military()
    army = [actor(10+i, "e1", 17, 20+i) for i in range(2)]
    enemies = [actor(100+i, "e1", 25, 20+i % 2) for i in range(6)]
    first = View(home_state(300, army, enemies), mapped())
    orders, _ = military._defense(first, army, enemies)
    old = military.defense_posts[1]["withdraw_goal"]
    military.mark_sent([o.order for o in orders], 300)
    reinforced = enemies + [actor(200, "3tnk", *old)]
    second = View(home_state(303, army, reinforced), mapped())
    military._defense(second, army, reinforced)
    new = military.defense_posts[1]["withdraw_goal"]
    assert new != old
    assert distance(new, old) > 4.75
    assert distance(new, (20, 20)) <= 10


def test_defender_already_at_refuge_cancels_its_old_attack_order():
    military = Military()
    army = [{**actor(10, "e1", 12, 20), "idle": False},
            {**actor(11, "e1", 17, 21), "idle": False}]
    enemies = [actor(100+i, "e1", 25, 20+i % 2) for i in range(6)]
    military.mark_sent([{"cmd": "attack", "units": [10, 11], "target": 100}], 299)
    intents, _ = military._defense(View(home_state(300, army, enemies), mapped()), army, enemies)
    assert military.defense_posts[1]["withdraw_goal"] == [12, 20]
    cancelled = {uid for i in intents if i.order["cmd"] == "move" for uid in i.order["units"]}
    assert cancelled == {10, 11}


def test_existing_scout_can_be_recalled_and_cannot_overwrite_rescue_in_fog():
    army = remote_army()
    army[0]["type"] = "e1"
    military = Military()
    military.scout_id = army[0]["id"]
    military.scout_goal = [90, 80]
    first = military.propose(View(home_state(400, army, raiders()), mapped()))
    assert army[0]["id"] in military.defense_posts[1]["guards"]
    assert not any("scout" in (i.key or "") for i in first)
    military.mark_sent([i.order for i in first], 400)
    second = military.propose(View(home_state(403, army), mapped()))
    assert military.scout_losses == 0
    assert not any("scout" in (i.key or "") for i in second)
    assert {uid for i in second for uid in i.order.get("units", [])} == {a["id"] for a in army}


def test_defensive_withdrawal_ends_after_real_local_reinforcements():
    military = Military()
    weak = [actor(10+i, "e1", 17, 20+i) for i in range(2)]
    enemies = [actor(100+i, "e1", 25, 20+i % 2) for i in range(6)]
    first, _ = military._defense(View(home_state(300, weak, enemies), mapped()), weak, enemies)
    military.mark_sent([i.order for i in first], 300)
    reinforced = weak + [actor(30+i, "apc", 18, 19+i % 3) for i in range(3)]
    later, _ = military._defense(View(home_state(307, reinforced, enemies), mapped()), reinforced, enemies)
    assert "withdraw_goal" not in military.defense_posts[1]
    assert any(i.order["cmd"] in {"attack", "attack_move"} for i in later)


def test_clear_opening_still_uses_a_scout():
    army = [actor(10+i, "e1", 20, 20+i) for i in range(4)]
    military = Military()
    orders = military.propose(View(home_state(50, army), mapped()))
    assert military.scout_id in {a["id"] for a in army}
    assert any(i.key == "military:scout:0" for i in orders)
