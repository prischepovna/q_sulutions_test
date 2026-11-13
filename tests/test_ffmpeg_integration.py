
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apply_zoom  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def _make_video(path: Path, seconds: int = 6):
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=640x360:rate=25", "-t", str(seconds),
         "-c:v", "libvpx-vp9", "-b:v", "500k", "-deadline", "realtime",
         str(path)],
        check=True)


def _probe(path: Path) -> list[str]:
    ffprobe = shutil.which("ffprobe")
    out = subprocess.run(
        [ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,nb_read_frames",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return out.split(",")


def _sidecar(path: Path, events):
    path.write_text(json.dumps({
        "viewport": {"width": 640, "height": 360}, "fps": 25,
        "zoom_factor": 2.0, "ramp_sec": 0.5, "events": events}))


def test_zoom_pair_renders_and_keeps_resolution(tmp_path):
    video = tmp_path / "a.webm"
    _make_video(video)
    _sidecar(tmp_path / "a.zoom.json", [
        {"t": 1, "x": 100, "y": 80, "type": "in"},
        {"t": 3, "x": 100, "y": 80, "type": "out"}])
    apply_zoom.main(["--video", str(video), "--ffmpeg", FFMPEG])
    out = tmp_path / "a_zoomed.webm"
    assert out.exists()
    w, h, frames = _probe(out)
    assert (w, h) == ("640", "360")
    assert int(frames) == 150


def test_open_ended_zoom_renders(tmp_path):
    video = tmp_path / "b.webm"
    _make_video(video)
    _sidecar(tmp_path / "b.zoom.json", [
        {"t": 2, "x": 630, "y": 350, "type": "in"}])
    apply_zoom.main(["--video", str(video), "--ffmpeg", FFMPEG])
    assert (tmp_path / "b_zoomed.webm").exists()


def test_multiple_pairs_render(tmp_path):
    video = tmp_path / "c.webm"
    _make_video(video)
    _sidecar(tmp_path / "c.zoom.json", [
        {"t": 0.5, "x": 100, "y": 100, "type": "in"},
        {"t": 2, "x": 100, "y": 100, "type": "out"},
        {"t": 3, "x": 500, "y": 300, "type": "in"},
        {"t": 4.5, "x": 500, "y": 300, "type": "out"}])
    apply_zoom.main(["--video", str(video), "--ffmpeg", FFMPEG])
    assert (tmp_path / "c_zoomed.webm").exists()


def test_filter_has_no_undefined_variable():
    pairs = apply_zoom.pair_events([{"t": 1, "x": 5, "y": 5, "type": "in"}])
    vf = apply_zoom.build_filter(pairs, 25, 2.0, 0.5, 100, 640, 360)
    assert "between(n," not in vf
    assert "between(in," in vf
