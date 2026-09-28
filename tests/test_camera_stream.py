import os
import sys
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "examples"))

import camera_stream  # noqa: E402


class Camera:
    def __init__(self, frame=b"\xff\xd8jpeg\xff\xd9"):
        self.frame = frame
        self.grabs = 0

    def __call__(self):
        self.grabs += 1
        return self.frame


class FrameSourceTests(unittest.TestCase):
    def test_viewers_share_a_grab_within_the_interval(self):
        camera = Camera()
        source = camera_stream.FrameSource(camera, fps=0.001)
        self.assertEqual(source.latest(), camera.frame)
        source.latest()
        self.assertEqual(camera.grabs, 1)

    def test_grabs_again_once_the_frame_is_stale(self):
        camera = Camera()
        source = camera_stream.FrameSource(camera, fps=1e9)
        source.latest()
        source.latest()
        self.assertEqual(camera.grabs, 2)

    def test_a_failing_camera_gives_no_frame(self):
        def broken():
            raise RuntimeError("busy")
        self.assertIsNone(camera_stream.FrameSource(broken).latest())


class ServerTests(unittest.TestCase):
    def serve(self, camera):
        server = camera_stream.CameraServer(camera, port=0, fps=50)
        server.start()
        self.addCleanup(server.stop)
        return f"http://127.0.0.1:{server.port}"

    def test_snapshot(self):
        url = self.serve(Camera())
        with urllib.request.urlopen(url + "/snapshot.jpg", timeout=5) as r:
            self.assertEqual(r.headers["Content-Type"], "image/jpeg")
            self.assertEqual(r.read(), b"\xff\xd8jpeg\xff\xd9")

    def test_snapshot_with_the_camera_off(self):
        url = self.serve(Camera(frame=None))
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url + "/snapshot.jpg", timeout=5)
        e.exception.close()
        self.assertEqual(e.exception.code, 503)

    def test_page_embeds_the_stream(self):
        url = self.serve(Camera())
        with urllib.request.urlopen(url + "/", timeout=5) as r:
            self.assertIn(b'src="/mjpg"', r.read())

    def test_mjpg_streams_frames(self):
        url = self.serve(Camera())
        with urllib.request.urlopen(url + "/mjpg", timeout=5) as r:
            self.assertIn("multipart/x-mixed-replace", r.headers["Content-Type"])
            chunk = r.read(200)
        self.assertGreaterEqual(chunk.count(b"--frame\r\n"), 2)

    def test_unknown_path(self):
        url = self.serve(Camera())
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url + "/etc/passwd", timeout=5)
        e.exception.close()
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
