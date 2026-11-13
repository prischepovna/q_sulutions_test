
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apply_zoom import smoothstep, pair_events, compute_frame_params, build_filter



class TestSmoothstep:
    def test_zero(self):
        assert smoothstep(0.0) == 0.0

    def test_one(self):
        assert smoothstep(1.0) == 1.0

    def test_half(self):
        assert smoothstep(0.5) == pytest.approx(0.5)

    def test_quarter(self):
        # 3*(0.25)^2 - 2*(0.25)^3 = 3*0.0625 - 2*0.015625 = 0.15625
        assert smoothstep(0.25) == pytest.approx(0.15625)

    def test_monotonic_increasing(self):
        prev = 0.0
        for i in range(1, 101):
            val = smoothstep(i / 100)
            assert val >= prev
            prev = val

    def test_clamp_below_zero(self):
        assert smoothstep(-0.5) == 0.0

    def test_clamp_above_one(self):
        assert smoothstep(1.5) == 1.0

    def test_symmetry(self):
        for i in range(101):
            t = i / 100
            assert smoothstep(t) + smoothstep(1.0 - t) == pytest.approx(1.0)



class TestPairEvents:
    def test_single_pair(self):
        events = [
            {"t": 3.0, "x": 640, "y": 360, "type": "in"},
            {"t": 8.0, "x": 640, "y": 360, "type": "out"},
        ]
        pairs = pair_events(events)
        assert len(pairs) == 1
        assert pairs[0][0]["type"] == "in"
        assert pairs[0][1]["type"] == "out"

    def test_open_ended_zoom(self):
        events = [
            {"t": 3.0, "x": 640, "y": 360, "type": "in"},
        ]
        pairs = pair_events(events)
        assert len(pairs) == 1
        assert pairs[0][0]["t"] == 3.0
        assert pairs[0][1] is None

    def test_multiple_pairs(self):
        events = [
            {"t": 1.0, "x": 100, "y": 100, "type": "in"},
            {"t": 3.0, "x": 100, "y": 100, "type": "out"},
            {"t": 5.0, "x": 500, "y": 300, "type": "in"},
            {"t": 7.0, "x": 500, "y": 300, "type": "out"},
            {"t": 9.0, "x": 200, "y": 200, "type": "in"},
            {"t": 11.0, "x": 200, "y": 200, "type": "out"},
        ]
        pairs = pair_events(events)
        assert len(pairs) == 3
        for in_ev, out_ev in pairs:
            assert in_ev["type"] == "in"
            assert out_ev["type"] == "out"
            assert out_ev["t"] > in_ev["t"]

    def test_no_type_backward_compat(self):
        events = [
            {"t": 3.0, "x": 640, "y": 360},
            {"t": 8.0, "x": 640, "y": 360},
        ]
        pairs = pair_events(events)
        assert len(pairs) == 1
        assert pairs[0][0]["type"] == "in"
        assert pairs[0][1]["type"] == "out"

    def test_empty_events(self):
        assert pair_events([]) == []

    def test_orphan_out_skipped(self):
        events = [
            {"t": 1.0, "x": 100, "y": 100, "type": "out"},
            {"t": 3.0, "x": 640, "y": 360, "type": "in"},
            {"t": 5.0, "x": 640, "y": 360, "type": "out"},
        ]
        pairs = pair_events(events)
        assert len(pairs) == 1
        assert pairs[0][0]["t"] == 3.0

    def test_last_in_without_out(self):
        events = [
            {"t": 1.0, "x": 100, "y": 100, "type": "in"},
            {"t": 3.0, "x": 100, "y": 100, "type": "out"},
            {"t": 5.0, "x": 500, "y": 300, "type": "in"},
        ]
        pairs = pair_events(events)
        assert len(pairs) == 2
        assert pairs[0][1] is not None
        assert pairs[1][1] is None



class TestComputeFrameParams:
    FPS = 25
    ZF = 2.0
    RAMP = 0.5
    W, H = 1280, 720

    def _pairs(self, events):
        return pair_events(events)


    def test_no_zoom_events(self):
        z, x, y = compute_frame_params(
            0, [], self.FPS, self.ZF, self.RAMP, self.W, self.H)
        assert z == 1.0
        assert x == 0.0 and y == 0.0


    def test_ramp_in_start(self):
        pairs = self._pairs([
            {"t": 2.0, "x": 640, "y": 360, "type": "in"},
            {"t": 5.0, "x": 640, "y": 360, "type": "out"},
        ])
        z, _, _ = compute_frame_params(50, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert z == pytest.approx(1.0, abs=0.01)

    def test_ramp_in_end(self):
        pairs = self._pairs([
            {"t": 2.0, "x": 640, "y": 360, "type": "in"},
            {"t": 5.0, "x": 640, "y": 360, "type": "out"},
        ])
        frame = int((2.0 + 0.5 - 0.01) * self.FPS)
        z, _, _ = compute_frame_params(frame, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert z == pytest.approx(self.ZF, abs=0.05)

    def test_ramp_in_midpoint(self):
        pairs = self._pairs([
            {"t": 2.0, "x": 640, "y": 360, "type": "in"},
            {"t": 5.0, "x": 640, "y": 360, "type": "out"},
        ])
        frame = int((2.0 + 0.25) * self.FPS)  # t = 2.25
        z, _, _ = compute_frame_params(frame, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert 1.0 < z < self.ZF

    # ── hold ──

    def test_hold_phase(self):
        pairs = self._pairs([
            {"t": 2.0, "x": 640, "y": 360, "type": "in"},
            {"t": 5.0, "x": 640, "y": 360, "type": "out"},
        ])
        z, _, _ = compute_frame_params(75, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert z == pytest.approx(self.ZF, abs=0.01)


    def test_ramp_out_start(self):
        pairs = self._pairs([
            {"t": 2.0, "x": 640, "y": 360, "type": "in"},
            {"t": 5.0, "x": 640, "y": 360, "type": "out"},
        ])
        z, _, _ = compute_frame_params(125, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert z == pytest.approx(self.ZF, abs=0.05)

    def test_after_ramp_out(self):
        pairs = self._pairs([
            {"t": 2.0, "x": 640, "y": 360, "type": "in"},
            {"t": 5.0, "x": 640, "y": 360, "type": "out"},
        ])
        z, _, _ = compute_frame_params(139, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert z == pytest.approx(1.0, abs=0.01)


    def test_open_ended_holds_forever(self):
        pairs = self._pairs([
            {"t": 2.0, "x": 640, "y": 360, "type": "in"},
        ])
        for frame in [100, 250, 500, 1000]:
            z, _, _ = compute_frame_params(frame, pairs, self.FPS, self.ZF,
                                           self.RAMP, self.W, self.H)
            assert z == pytest.approx(self.ZF, abs=0.01)


    def test_clamp_top_left(self):
        pairs = self._pairs([
            {"t": 2.0, "x": 0, "y": 0, "type": "in"},
            {"t": 5.0, "x": 0, "y": 0, "type": "out"},
        ])
        z, x, y = compute_frame_params(75, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert z == pytest.approx(self.ZF)
        assert x == 0.0
        assert y == 0.0

    def test_clamp_bottom_right(self):
        pairs = self._pairs([
            {"t": 2.0, "x": 1280, "y": 720, "type": "in"},
            {"t": 5.0, "x": 1280, "y": 720, "type": "out"},
        ])
        z, x, y = compute_frame_params(75, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert x == pytest.approx(self.W - self.W / self.ZF, abs=1)
        assert y == pytest.approx(self.H - self.H / self.ZF, abs=1)

    def test_center_zoom_position(self):
        pairs = self._pairs([
            {"t": 2.0, "x": 640, "y": 360, "type": "in"},
            {"t": 5.0, "x": 640, "y": 360, "type": "out"},
        ])
        z, x, y = compute_frame_params(75, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        crop_w = self.W / z
        crop_h = self.H / z
        assert x == pytest.approx(640 - crop_w / 2, abs=1)
        assert y == pytest.approx(360 - crop_h / 2, abs=1)


    def test_three_pairs_hold_values(self):
        events = [
            {"t": 1.0, "x": 100, "y": 100, "type": "in"},
            {"t": 3.0, "x": 100, "y": 100, "type": "out"},
            {"t": 5.0, "x": 500, "y": 300, "type": "in"},
            {"t": 7.0, "x": 500, "y": 300, "type": "out"},
            {"t": 9.0, "x": 200, "y": 200, "type": "in"},
            {"t": 11.0, "x": 200, "y": 200, "type": "out"},
        ]
        pairs = self._pairs(events)

        z, _, _ = compute_frame_params(50, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert z == pytest.approx(self.ZF, abs=0.01)

        z, _, _ = compute_frame_params(100, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert z == pytest.approx(1.0, abs=0.01)

        z, _, _ = compute_frame_params(150, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert z == pytest.approx(self.ZF, abs=0.01)

        z, _, _ = compute_frame_params(250, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert z == pytest.approx(self.ZF, abs=0.01)

        z, _, _ = compute_frame_params(300, pairs, self.FPS, self.ZF,
                                       self.RAMP, self.W, self.H)
        assert z == pytest.approx(1.0, abs=0.01)


    def test_zero_ramp_sec(self):
        pairs = self._pairs([
            {"t": 2.0, "x": 640, "y": 360, "type": "in"},
            {"t": 5.0, "x": 640, "y": 360, "type": "out"},
        ])
        z, _, _ = compute_frame_params(49, pairs, self.FPS, self.ZF,
                                       0.0, self.W, self.H)
        assert z == pytest.approx(1.0)

        z, _, _ = compute_frame_params(50, pairs, self.FPS, self.ZF,
                                       0.0, self.W, self.H)
        assert z == pytest.approx(self.ZF)



class TestBuildFilter:
    def test_single_pair_returns_string(self):
        pairs = pair_events([
            {"t": 3.0, "x": 640, "y": 360, "type": "in"},
            {"t": 8.0, "x": 640, "y": 360, "type": "out"},
        ])
        filt = build_filter(pairs, 25, 2.0, 0.5, 300, 1280, 720)
        assert filt is not None
        assert filt.startswith("zoompan=")
        assert "d=1" in filt
        assert "s=1280x720" in filt
        assert "fps=25" in filt

    def test_empty_pairs_returns_none(self):
        assert build_filter([], 25, 2.0, 0.5, 300, 1280, 720) is None

    def test_open_ended_produces_filter(self):
        pairs = pair_events([
            {"t": 3.0, "x": 640, "y": 360, "type": "in"},
        ])
        filt = build_filter(pairs, 25, 2.0, 0.5, 300, 1280, 720)
        assert filt is not None
        assert "zoompan=" in filt

    def test_multiple_pairs_all_segments(self):
        pairs = pair_events([
            {"t": 1.0, "x": 100, "y": 100, "type": "in"},
            {"t": 3.0, "x": 100, "y": 100, "type": "out"},
            {"t": 5.0, "x": 500, "y": 300, "type": "in"},
            {"t": 7.0, "x": 500, "y": 300, "type": "out"},
        ])
        filt = build_filter(pairs, 25, 2.0, 0.5, 300, 1280, 720)
        assert filt is not None
        assert filt.count("between(in,") >= 4  # at least ramp-in, hold for 2 pairs

    def test_filter_contains_zoom_factor(self):
        pairs = pair_events([
            {"t": 3.0, "x": 640, "y": 360, "type": "in"},
            {"t": 8.0, "x": 640, "y": 360, "type": "out"},
        ])
        filt = build_filter(pairs, 25, 3.0, 0.5, 300, 1280, 720)
        assert "3.0" in filt

    def test_filter_contains_clip(self):
        pairs = pair_events([
            {"t": 3.0, "x": 640, "y": 360, "type": "in"},
            {"t": 8.0, "x": 640, "y": 360, "type": "out"},
        ])
        filt = build_filter(pairs, 25, 2.0, 0.5, 300, 1280, 720)
        assert "clip(" in filt


class TestDryRun:
    def test_dry_run_prints_command(self, tmp_path, capsys):
        from apply_zoom import main
        dummy_video = tmp_path / "test.webm"
        dummy_video.write_bytes(b"dummy")
        sidecar = tmp_path / "test.zoom.json"
        import json
        sidecar.write_text(json.dumps({
            "viewport": {"width": 1280, "height": 720},
            "fps": 25,
            "zoom_factor": 2.0,
            "ramp_sec": 0.5,
            "events": [{"t": 1.0, "x": 640, "y": 360, "type": "in"}]
        }), encoding="utf-8")

        main(["--video", str(dummy_video), "--dry-run"])
        out, _ = capsys.readouterr()
        assert "ffmpeg" in out
        assert "zoompan=" in out
        assert "test_zoomed.webm" in out
