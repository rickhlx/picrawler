import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "examples"))

import seeker  # noqa: E402


class FakeCrawler:
    """Records the turns and steps a Seeker asks for."""

    class MoveList:
        angle = 30

    def __init__(self):
        self.move_list = self.MoveList()
        self.actions = []

    def do_action(self, name, step=1, speed=50):
        self.actions.append((name, self.move_list.angle))


class Eyes:
    """Sees the target only on the nth frame it is shown."""

    def __init__(self, on_frame=None, position="center", size="small", note=""):
        self.on_frame = on_frame
        self.position = position
        self.size = size
        self.note = note
        self.frames = 0

    def __call__(self, image, target):
        self.frames += 1
        found = self.on_frame is not None and self.frames >= self.on_frame
        return seeker.Sighting(found=found, position=self.position,
                               size=self.size, note=self.note)


def build(eyes, **kwargs):
    crawler = FakeCrawler()
    return crawler, seeker.Seeker(crawler, lambda: "frame.jpg", eyes, **kwargs)


class ScanTests(unittest.TestCase):
    def test_finds_it_straight_away_without_turning(self):
        crawler, s = build(Eyes(on_frame=1, note="junto al sillón"))
        scan = s.scan("el perro")
        self.assertTrue(scan.found)
        self.assertEqual(scan.turned, 0)
        self.assertEqual(scan.note, "junto al sillón")
        self.assertEqual(crawler.actions, [])

    def test_reports_how_far_it_turned_to_see_it(self):
        crawler, s = build(Eyes(on_frame=4))     # seen on the fourth frame
        scan = s.scan("el perro")
        self.assertTrue(scan.found)
        self.assertEqual(scan.turned, 90)        # three 30 deg turns
        self.assertEqual(crawler.actions, [("turn left angle", 30)] * 3)

    def test_gives_up_after_a_full_sweep(self):
        crawler, s = build(Eyes(on_frame=None))
        scan = s.scan("el perro")
        self.assertFalse(scan.found)
        self.assertEqual(scan.turned, 360)
        self.assertEqual(len(crawler.actions), 12)

    def test_restores_the_move_list_angle(self):
        crawler, s = build(Eyes(on_frame=2))
        s.scan("el perro")
        self.assertEqual(crawler.move_list.angle, 30)

    def test_scan_never_walks(self):
        crawler, s = build(Eyes(on_frame=2, size="small"))
        s.scan("el perro")
        self.assertEqual([a for a, _ in crawler.actions], ["turn left angle"])

    def test_blind_eyes_do_not_crash_the_sweep(self):
        def broken(image, target):
            raise RuntimeError("no camera")
        crawler, s = build(broken)
        self.assertFalse(s.scan("el perro").found)


class BearingTests(unittest.TestCase):
    def bearing(self, turned, position="center"):
        return seeker.Scan(True, turned, position).bearing

    def test_ahead(self):
        self.assertEqual(self.bearing(0), 0)

    def test_nudged_by_where_it_sits_in_the_frame(self):
        self.assertEqual(self.bearing(60, "left"), 75)
        self.assertEqual(self.bearing(60, "right"), 45)

    def test_wraps_around(self):
        self.assertEqual(self.bearing(350, "left"), 5)


class SeekStillWalksTests(unittest.TestCase):
    def test_seek_approaches_after_the_sweep(self):
        crawler, s = build(Eyes(on_frame=2, size="large"))
        result = s.seek("la pelota")
        self.assertTrue(result.found)
        self.assertTrue(result.near)

    def test_seek_reports_nothing_found(self):
        crawler, s = build(Eyes(on_frame=None))
        self.assertFalse(s.seek("la pelota").found)


if __name__ == "__main__":
    unittest.main()
