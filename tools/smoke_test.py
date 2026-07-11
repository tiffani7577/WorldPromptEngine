#!/usr/bin/env python3
"""Offline smoke tests for WorldPromptEngine pure-Python paths (no Unreal required)."""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "Plugins", "WorldPromptEngine", "Content", "Python")
)
sys.path.insert(0, ROOT)

import art_engine  # noqa: E402
import prompt_matrix  # noqa: E402


def test_prompt_parse() -> None:
    result = prompt_matrix.parse_prompt("misty alpine peaks at golden hour")
    assert "archetype" in result or "name" in result or isinstance(result, dict), result
    print("parse_prompt OK:", {k: result.get(k) for k in list(result)[:6]})


def test_png_write() -> None:
    w = h = 32
    pixels = [((x + y) * 1000) % 65536 for y in range(h) for x in range(w)]
    path = os.path.join(tempfile.gettempdir(), "wpe_smoke.png")
    ok = art_engine.write_png_16bit_grayscale(path, w, h, pixels)
    assert ok and os.path.isfile(path) and os.path.getsize(path) > 64
    print("png write OK:", path, os.path.getsize(path), "bytes")


def test_noise() -> None:
    n = art_engine.PerlinNoise2D(42)
    v = n.fbm(10.0, 20.0, octaves=4, frequency=0.05)
    assert -1.5 <= v <= 1.5
    print("perlin fbm OK:", round(v, 5))


def main() -> int:
    test_noise()
    test_png_write()
    test_prompt_parse()
    print("All offline smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
