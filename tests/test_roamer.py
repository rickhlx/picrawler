import os
import random
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "examples"))

import roamer  # noqa: E402


class FakeCrawler:
    """Records the steps and turns a Roamer asks for."""

    def __init__(self):
        self.moves = []

    def do_action(self, name, step=1, speed=50):
        self.moves.append(name)

    def turn_angle(self, degrees=90, side="left", step=30, speed=60):
        self.moves.append(f"turn {side} {degrees}")
        return degrees


class Eyes:
    """Returns the scripted views in order, then the last one forever."""

    def __init__(self, *views):
        self.views = list(views) or [roamer.View()]
        self.targets = []

    def __call__(self, image, target):
        self.targets.append(target)
        return self.views.pop(0) if len(self.views) > 1 else self.views[0]


class NeverRandom(random.Random):
    """No random veers, and "left" whenever a side is picked at random."""

    def random(self):
        return 1.0

    def choice(self, seq):
        return seq[0]


def build(eyes, **kwargs):
    crawler = FakeCrawler()
    kwargs.setdefault("rng", NeverRandom())
    return crawler, roamer.Roamer(crawler, lambda: "frame.jpg", eyes, **kwargs)


class RoamTests(unittest.TestCase):
    def test_walks_while_the_way_is_clear(self):
        crawler, r = build(Eyes(roamer.View(note="la sala")), max_stops=2, steps=3)
        tour = r.roam()
        self.assertEqual(crawler.moves, ["forward"] * 6)
        self.assertEqual([s.note for s in tour.stops], ["la sala", "la sala"])
        self.assertEqual(tour.reason, "done")

    def test_turns_away_from_a_wall_instead_of_walking(self):
        crawler, r = build(Eyes(roamer.View()), distance=lambda: 20, max_stops=1)
        r.roam()
        self.assertEqual(crawler.moves, ["turn left 90"])

    def test_turns_toward_the_open_side_when_blocked(self):
        crawler, r = build(Eyes(roamer.View(clear="right")), distance=lambda: 10, max_stops=1)
        r.roam()
        self.assertEqual(crawler.moves, ["turn right 90"])

    def test_a_hazard_blocks_even_with_the_sonar_clear(self):
        crawler, r = build(Eyes(roamer.View(hazard=True)), distance=lambda: 200, max_stops=1)
        r.roam()
        self.assertNotIn("forward", crawler.moves)

    def test_veers_toward_open_floor_then_walks(self):
        crawler, r = build(Eyes(roamer.View(clear="left")), max_stops=1, steps=1)
        r.roam()
        self.assertEqual(crawler.moves, ["turn left 45", "forward"])

    def test_stops_walking_when_something_comes_up_mid_stride(self):
        readings = iter([100, 100, 100, 20])   # _move's check, then one per step
        crawler, r = build(Eyes(roamer.View()), distance=lambda: next(readings),
                           max_stops=1, steps=5)
        r.roam()
        self.assertEqual(crawler.moves, ["forward", "forward"])

    def test_stops_when_the_target_is_found(self):
        eyes = Eyes(roamer.View(note="pasillo"), roamer.View(note="las llaves en la mesa", found=True))
        crawler, r = build(eyes, max_stops=10)
        tour = r.roam(target="las llaves")
        self.assertTrue(tour.found)
        self.assertEqual(tour.reason, "found")
        self.assertEqual(len(tour.stops), 2)
        self.assertEqual(eyes.targets, ["las llaves", "las llaves"])

    def test_halt_ends_the_tour_with_its_reason(self):
        calls = iter([None, "battery"])
        crawler, r = build(Eyes(roamer.View()), halt=lambda: next(calls), max_stops=10)
        tour = r.roam()
        self.assertEqual(tour.reason, "battery")
        self.assertEqual(len(tour.stops), 1)

    def test_out_of_time_before_the_first_stop(self):
        crawler, r = build(Eyes(roamer.View()))
        tour = r.roam(minutes=0)
        self.assertEqual(tour.reason, "time")
        self.assertEqual(crawler.moves, [])

    def test_blind_eyes_turn_instead_of_walking(self):
        def broken(image, target):
            raise RuntimeError("no camera")
        crawler, r = build(broken, max_stops=2)
        tour = r.roam()
        self.assertEqual(crawler.moves, ["turn left 90", "turn left 90"])
        self.assertEqual(len(tour.stops), 2)

    def test_heading_tracks_nominal_turns(self):
        eyes = Eyes(roamer.View(clear="none"), roamer.View(clear="none"), roamer.View())
        crawler, r = build(eyes, max_stops=3, steps=0)
        tour = r.roam()
        self.assertEqual([s.heading for s in tour.stops], [0, 90, 180])


class PhotoTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.frame = os.path.join(self.dir, "frame.jpg")
        with open(self.frame, "wb") as f:
            f.write(b"jpeg")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def build(self, eyes, **kwargs):
        crawler = FakeCrawler()
        return roamer.Roamer(crawler, lambda: self.frame, eyes, rng=NeverRandom(),
                             photo_dir=os.path.join(self.dir, "tour"), **kwargs)

    def test_keeps_a_copy_of_every_frame(self):
        tour = self.build(Eyes(roamer.View()), max_stops=3).roam()
        self.assertEqual([os.path.basename(s.image) for s in tour.stops], ["00.jpg", "01.jpg", "02.jpg"])
        self.assertTrue(all(os.path.exists(s.image) for s in tour.stops))

    def test_photos_are_the_notable_ones(self):
        eyes = Eyes(roamer.View(), roamer.View(notable=True, note="el gato"), roamer.View())
        tour = self.build(eyes, max_stops=3).roam()
        self.assertEqual([os.path.basename(p) for p in tour.photos], ["01.jpg"])

    def test_photos_fall_back_to_the_last_frame(self):
        tour = self.build(Eyes(roamer.View()), max_stops=2).roam()
        self.assertEqual([os.path.basename(p) for p in tour.photos], ["01.jpg"])

    def test_no_photo_dir_no_photos(self):
        crawler, r = build(Eyes(roamer.View(notable=True)), max_stops=1)
        self.assertEqual(r.roam().photos, [])


if __name__ == "__main__":
    unittest.main()
