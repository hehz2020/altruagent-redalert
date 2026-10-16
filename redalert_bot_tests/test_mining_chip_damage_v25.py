"""Mining safety under chip damage and different observation cadences."""

from altru_redalert.mining import MiningManager
from redalert_bot_tests.test_economy_v2 import actor
from redalert_bot_tests.test_mining_v24 import commands, mining_view


def chip_view(now, hp, *, x=21, y=20, enemies=True):
    raiders = [actor(50, "jeep", 24, 20), actor(51, "jeep", 24, 22)] if enemies else []
    return mining_view(now, units=[actor(10, "harv", x, y, hp=hp, idle=False)],
                       enemies=raiders)


def test_sustained_raid_retreat_does_not_depend_on_observation_frequency():
    destinations = []
    for times in ([0, 8], [frame / 5 for frame in range(41)]):
        manager = MiningManager()
        issued = []
        for now in times:
            issued.extend(commands(manager, chip_view(now, 100 - int(now))))
        assert len(issued) == 1
        assert issued[0]["cmd"] == "move"
        assert issued[0]["units"] == [10]
        destinations.append(issued[0]["to"])
    assert destinations[0] == destinations[1]


def test_chip_damage_can_reveal_a_threat_missing_from_visible_enemy_list():
    manager = MiningManager()
    for now in range(8):
        assert commands(manager, chip_view(now, 100 - now, enemies=False)) == []
    result = commands(manager, chip_view(8, 92, enemies=False))
    assert len(result) == 1 and result[0]["cmd"] == "move"
    assert result[0]["to"][0] < 21


def test_old_damage_does_not_delay_safe_mining_recovery():
    manager = MiningManager()
    for now in range(9):
        result = commands(manager, chip_view(now, 100 - now))
    refuge = result[0]["to"]
    assert commands(manager, chip_view(10, 92, x=refuge[0], y=refuge[1], enemies=False)) == []
    assert commands(manager, chip_view(12, 92, x=refuge[0], y=refuge[1], enemies=False)) == [
        {"cmd": "harvest", "units": [10], "to": [21, 20]}]


def test_scattered_small_hits_do_not_accumulate_into_a_false_alarm():
    manager = MiningManager()
    for now, hp in ((0, 100), (1, 96), (8, 96), (10, 92), (17, 92)):
        assert commands(manager, chip_view(now, hp, enemies=False)) == []


def test_repaired_damage_is_not_counted_against_a_new_small_hit():
    manager = MiningManager()
    for now, hp in ((0, 100), (2, 95), (3, 100), (4, 96)):
        assert commands(manager, chip_view(now, hp, enemies=False)) == []
