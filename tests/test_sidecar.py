
import json
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apply_zoom import parse_sidecar, pair_events


class TestParseSidecar:
    def _write(self, data, tmp_path):
        p = tmp_path / "test.zoom.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return str(p)

    def test_full_sidecar(self, tmp_path):
        data = {
            "viewport": {"width": 1280, "height": 720},
            "fps": 25,
            "zoom_factor": 2.0,
            "ramp_sec": 0.5,
            "events": [
                {"t": 3.0, "x": 640, "y": 360, "type": "in"},
                {"t": 8.0, "x": 640, "y": 360, "type": "out"},
            ],
        }
        sc = parse_sidecar(self._write(data, tmp_path))
        assert sc["fps"] == 25
        assert sc["zoom_factor"] == 2.0
        assert len(sc["events"]) == 2

    def test_defaults_for_missing_fields(self, tmp_path):
        """Optional top-level keys fall back to defaults."""
        data = {"events": [{"t": 1.0, "x": 100, "y": 200, "type": "in"}]}
        sc = parse_sidecar(self._write(data, tmp_path))
        assert sc["fps"] == 25
        assert sc["zoom_factor"] == 2.0
        assert sc["ramp_sec"] == 0.5
        assert sc["viewport"] == {"width": 1280, "height": 720}

    def test_empty_events_list(self, tmp_path):
        sc = parse_sidecar(self._write({"events": []}, tmp_path))
        assert sc["events"] == []

    def test_missing_t_raises(self, tmp_path):
        data = {"events": [{"x": 100, "y": 200}]}
        with pytest.raises(ValueError, match="missing 't'"):
            parse_sidecar(self._write(data, tmp_path))

    def test_missing_x_raises(self, tmp_path):
        data = {"events": [{"t": 1.0, "y": 200}]}
        with pytest.raises(ValueError, match="missing 'x'"):
            parse_sidecar(self._write(data, tmp_path))

    def test_missing_y_raises(self, tmp_path):
        data = {"events": [{"t": 1.0, "x": 200}]}
        with pytest.raises(ValueError, match="missing 'y'"):
            parse_sidecar(self._write(data, tmp_path))

    def test_no_type_field_backward_compat(self, tmp_path):
        data = {
            "events": [
                {"t": 3.0, "x": 640, "y": 360},
                {"t": 8.0, "x": 640, "y": 360},
            ]
        }
        sc = parse_sidecar(self._write(data, tmp_path))
        pairs = pair_events(sc["events"])
        assert len(pairs) == 1
        assert pairs[0][0]["type"] == "in"
        assert pairs[0][1]["type"] == "out"

    def test_custom_zoom_factor(self, tmp_path):
        data = {"zoom_factor": 4.0, "events": [{"t": 1.0, "x": 0, "y": 0, "type": "in"}]}
        sc = parse_sidecar(self._write(data, tmp_path))
        assert sc["zoom_factor"] == 4.0

    def test_custom_ramp_sec(self, tmp_path):
        data = {"ramp_sec": 1.5, "events": [{"t": 1.0, "x": 0, "y": 0, "type": "in"}]}
        sc = parse_sidecar(self._write(data, tmp_path))
        assert sc["ramp_sec"] == 1.5


class TestNoEventsPath:

    def test_empty_events_means_no_zoom(self):
        from apply_zoom import build_filter
        pairs = pair_events([])
        filt = build_filter(pairs, 25, 2.0, 0.5, 300, 1280, 720)
        assert filt is None

    def test_main_no_sidecar_copies_unchanged(self, tmp_path):
        from apply_zoom import main
        dummy_video = tmp_path / "sample.webm"
        dummy_video.write_bytes(b"dummy webm content")
        out_video = tmp_path / "sample_zoomed.webm"

        main(["--video", str(dummy_video), "--output", str(out_video)])
        assert out_video.exists()
        assert out_video.read_bytes() == b"dummy webm content"

    def test_main_empty_events_copies_unchanged(self, tmp_path):
        from apply_zoom import main
        dummy_video = tmp_path / "sample.webm"
        dummy_video.write_bytes(b"dummy webm content")
        sidecar = tmp_path / "sample.zoom.json"
        sidecar.write_text(json.dumps({"events": []}), encoding="utf-8")
        out_video = tmp_path / "sample_zoomed.webm"

        main(["--video", str(dummy_video), "--output", str(out_video)])
        assert out_video.exists()
        assert out_video.read_bytes() == b"dummy webm content"
