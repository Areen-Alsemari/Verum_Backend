"""Random streams of the sensor chain: separate per tag and per purpose, and independent of order.

Each continuous tag draws its noise and its dropout from separate named streams, and the engine
detector uses its own. No two names are equal and their keys are distinct, and drawing from one
stream never changes another, whatever the order. The checks are structural and use no statistics.

See D30.
"""

from __future__ import annotations

import numpy as np

from verum.rng import RandomStreams, stream_key
from verum.sensors import adapter, chain, load_sensor_config

CFG = load_sensor_config()
CONTINUOUS = [t for t, s in CFG.tags.items() if s.kind == "continuous"]


def names() -> list[str]:
    out = [f"sensor/{t}/{purpose}" for t in CONTINUOUS for purpose in ("noise", "dropout")]
    return [*out, *[f"detector/TK-10{k}" for k in (1, 2, 3)], "demand"]


def test_no_two_tags_or_purposes_share_a_stream() -> None:
    """No two tags or purposes share a stream name or a stream key. Independent: yes, because the
    check counts distinct names and keys.
    """
    assert len(CONTINUOUS) == 14
    assert len(set(names())) == len(names()) == 14 * 2 + 3 + 1
    assert len({stream_key(n) for n in names()}) == len(names())


def test_noise_and_dropout_of_a_tag_are_separate_streams() -> None:
    """Drawing the dropout stream of a tag first leaves its noise stream unchanged, and the two
    streams differ. Independent: yes, because equality of arrays is the property.
    """
    fresh = RandomStreams(11).stream("sensor/LT-101/noise").standard_normal(500)
    streams = RandomStreams(11)
    streams.stream("sensor/LT-101/dropout").random(10_000)  # the dropout stream is used first
    assert np.array_equal(streams.stream("sensor/LT-101/noise").standard_normal(500), fresh)
    other = RandomStreams(11).stream("sensor/LT-101/dropout").random(500)
    assert not np.array_equal(other, fresh)


def test_the_order_in_which_tags_are_processed_changes_nothing() -> None:
    """Processing the tags in a different order gives the same observations. Independent: yes,
    because equality of outputs is the property.
    """
    nodes = chain.Nodes(np.array([0.0, 600.0]), np.array([5.0, 5.0]), np.array([False] * 2))

    def run(order: list[str], seed: int) -> dict[str, list[dict[str, object]]]:
        streams = RandomStreams(seed)
        return {
            tag: adapter._continuous(CFG, CFG.tags[tag], nodes, streams, "EP-T", 600.0).observations
            for tag in order
        }

    forward = run(CONTINUOUS, 3)
    backward = run(list(reversed(CONTINUOUS)), 3)
    assert forward == backward
    subset = run(["PT-001", "LT-101"], 3)  # a tag set without the others
    assert subset["PT-001"] == forward["PT-001"] and subset["LT-101"] == forward["LT-101"]
