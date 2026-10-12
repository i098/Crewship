"""herdr-patch: the fill filter, the graphics capture and half-blocks, the channel,
the computer's side, and how the arguments choose between them.

These tests also run on Python 3.9, the version macOS ships.
"""

import base64
import importlib.machinery
import importlib.util
import re
import os
import select
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import zlib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "tools/herdr-patch/herdr-patch"
loader = importlib.machinery.SourceFileLoader("herdr_patch", str(SCRIPT))
spec = importlib.util.spec_from_loader("herdr_patch", loader)
mosh = importlib.util.module_from_spec(spec)
loader.exec_module(mosh)

FILL = mosh.fill_colors("1e1e1e,232136")


def run(*chunks: bytes, fill=FILL, gfx=None) -> bytes:
    gfx = gfx or mosh.Graphics(120, 40)
    out, held = b"", b""
    for chunk in chunks:
        written, held = mosh.feed(held, chunk, fill, gfx)
        out += written
    return out + held


@pytest.mark.parametrize(
    "bg",
    [b"48;2;30;30;30", b"48;2;35;33;54", b"48:2:30:30:30", b"48:2::30:30:30", b"48:2:0:30:30:30"],
)
def test_fill_background_becomes_default(bg):
    assert run(b"\x1b[" + bg + b"m  x") == b"\x1b[49m  x"


@pytest.mark.parametrize(
    "seq",
    [
        b"\x1b[38;2;30;30;30m",  # fill RGB as a foreground
        b"\x1b[58;2;30;30;30m",  # as an underline color
        b"\x1b[38:2::30:30:30m",
        b"\x1b[48;5;234m",  # indexed background
        b"\x1b[48;2;33;32;46m",  # a truecolor background off the list
        b"\x1b[48;2;30;30m",  # a truncated group
        b"\x1b[48:2::30:30m",
    ],
)
def test_other_colors_stay_byte_identical(seq):
    assert run(seq + b"x") == seq + b"x"


def test_mixed_sgr_keeps_its_other_parameters_in_order():
    assert run(b"\x1b[0;1;38;2;224;222;244;48;2;35;33;54;4m") == b"\x1b[0;1;38;2;224;222;244;49;4m"


def test_group_values_are_never_read_as_a_background():
    # The B of a foreground and the N of an indexed color can be 48, followed
    # by `2` (dim) and the fill digits: no background in either sequence.
    for seq in (b"\x1b[38;2;1;1;48;2;30;30;30m", b"\x1b[38;5;48;2;30;30;30m"):
        assert run(seq) == seq


@pytest.mark.parametrize("cut", range(1, len(b"\x1b[48;2;30;30;30m")))
def test_a_sequence_split_across_two_reads(cut):
    seq = b"ab\x1b[48;2;30;30;30mcd"
    assert run(seq[: cut + 2], seq[cut + 2 :]) == b"ab\x1b[49mcd"


def test_non_sgr_sequences_pass_byte_identical():
    stream = (
        b"\x1b[?2026h\x1b[3;7H\x1b[2K\x1b]11;rgb:1e1e/1e1e/1e1e\x07\x1b]0;48;2;30;30;30\x1b\\"
        b"\x1b[>4;2m\x1b[48;2;30;30;30 q\x1bP+q544e\x1b\\\x1b7\x1b8\r\n48;2;30;30;30"
    )
    assert run(stream) == stream
    assert run(*(stream[i : i + 1] for i in range(len(stream)))) == stream


def test_empty_fill_changes_nothing():
    seq = b"\x1b[48;2;30;30;30m\x1b[48:2::35:33:54m"
    assert run(seq, fill=mosh.fill_colors("")) == seq


def test_fill_list_parses_hex_with_or_without_hash():
    assert mosh.fill_colors(" #1E1E1E , 232136,") == {(30, 30, 30), (35, 33, 54)}


# A 2x2 RGBA image: red, green on top; blue, white below.
PIXELS = bytes([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255])
CELLS = b"\x1b[38;2;255;0;0;48;2;0;0;255m\xe2\x96\x80\x1b[38;2;0;255;0;48;2;255;255;255m\xe2\x96\x80"


def transmit(image: int, data: bytes = PIXELS, chunk: int = 8) -> bytes:
    """herdr's transmit: raw RGBA in base64, cut into m=1 chunks."""
    b64 = base64.b64encode(data)
    parts = [b64[i : i + chunk] for i in range(0, len(b64), chunk)]
    keys = b"a=t,t=d,f=32,s=2,v=2,i=%d,q=2," % image
    return b"".join(
        b"\x1b_G%sm=%d;%s\x1b\\" % (keys if n == 0 else b"", n < len(parts) - 1, part) for n, part in enumerate(parts)
    )


def place(image: int, p: int, row: int, col: int) -> bytes:
    return b"\x1b[%d;%dH\x1b_Ga=p,i=%d,p=%d,c=2,r=1,z=0,C=1,q=2,w=2,h=2\x1b\\" % (row, col, image, p)


def delete(image: int, p: int) -> bytes:
    return b"\x1b_Ga=d,d=i,i=%d,p=%d,q=2\x1b\\" % (image, p)


def burst(*commands: bytes) -> bytes:
    return b"\x1b7" + b"".join(commands) + b"\x1b8"


# herdr writes a CUP before each text run, also after a burst.
SHOWN = b"ab" + burst(transmit(1), place(1, 7, 3, 5)) + b"\x1b[9;1Hcd"
PAINTED = b"ab\x1b7\x1b[3;5H\x1b[3;5H" + CELLS + b"\x1b[3;5H\x1b8\x1b[9;1Hcd"


@pytest.mark.parametrize("cut", range(1, len(SHOWN)))
def test_graphics_leave_the_stream_as_half_blocks_across_any_read_split(cut):
    gfx = mosh.Graphics(120, 40)
    assert run(SHOWN[:cut], SHOWN[cut:], gfx=gfx) == PAINTED
    assert gfx.places[(1, 7)][:2] == (3, 5)
    assert gfx.painted == {3: {5: (1, 7), 6: (1, 7)}}


def test_graphics_split_into_single_bytes():
    assert run(*(SHOWN[i : i + 1] for i in range(len(SHOWN)))) == PAINTED


def test_an_unterminated_apc_waits_for_its_end():
    out, held = mosh.feed(b"", b"x\x1b_Ga=t,m=1;AAAA", FILL, mosh.Graphics())
    assert (out, held) == (b"x", b"\x1b_Ga=t,m=1;AAAA")


def test_a_move_blanks_only_the_old_cells_herdr_did_not_write_again():
    gfx = mosh.Graphics(120, 40)
    run(burst(transmit(1), place(1, 7, 3, 5)), gfx=gfx)
    run(b"\x1b[3;5HX", gfx=gfx)  # herdr writes the first old cell again
    out = run(burst(delete(1, 7), place(1, 8, 6, 5)), gfx=gfx)
    # Only (3, 6) becomes blank; then the cursor goes back to where herdr left it.
    assert out.startswith(b"\x1b7\x1b[0m\x1b[3;6H \x1b[3;6H")
    assert b"\x1b[3;5H " not in out
    assert list(gfx.places) == [(1, 8)]
    assert gfx.painted == {6: {5: (1, 8), 6: (1, 8)}}


def test_an_erase_from_herdr_stops_the_blanking():
    gfx = mosh.Graphics(120, 40)
    run(burst(transmit(1), place(1, 7, 3, 5)), gfx=gfx)
    run(b"\x1b[2J", gfx=gfx)
    assert run(burst(delete(1, 7)), gfx=gfx) == b"\x1b7\x1b8"


def test_text_after_a_wide_character_forgets_the_rest_of_the_row():
    gfx = mosh.Graphics(120, 40)
    run(burst(transmit(1), place(1, 7, 3, 5)), gfx=gfx)
    run("\x1b[3;1H\u4e2d".encode(), gfx=gfx)
    assert gfx.painted == {}


def test_delete_all_and_delete_with_free():
    gfx = mosh.Graphics(120, 40)
    run(burst(transmit(1), transmit(2), place(1, 7, 3, 5), place(2, 1, 5, 5)), gfx=gfx)
    run(burst(b"\x1b_Ga=d,d=I,i=2\x1b\\"), gfx=gfx)
    assert list(gfx.images) == [1] and list(gfx.places) == [(1, 7)]
    run(burst(b"\x1b_Ga=d,d=A\x1b\\"), gfx=gfx)
    assert gfx.images == {} and gfx.places == {} and gfx.painted == {}


def test_a_placement_past_the_right_edge_is_cut_not_wrapped():
    gfx = mosh.Graphics(6, 40)
    out = run(burst(transmit(1), place(1, 7, 3, 6)), gfx=gfx)
    assert out.count("\u2580".encode()) == 1
    assert gfx.painted == {3: {6: (1, 7)}}


def test_outside_a_burst_the_paint_saves_and_restores_the_cursor():
    gfx = mosh.Graphics(120, 40)
    assert run(transmit(1) + place(1, 7, 3, 5), gfx=gfx) == b"\x1b[3;5H\x1b7\x1b[3;5H" + CELLS + b"\x1b[3;5H\x1b8"


def test_half_blocks_average_each_half_cell():
    # 2x4 pixels in one cell: the top half averages rows 0-1, the bottom half rows 2-3.
    data = bytes([10, 20, 30, 255] * 2 + [30, 40, 50, 255] * 2 + [0, 0, 0, 255] * 2 + [100, 200, 50, 255] * 2)
    img = mosh.Image(2, 4, 4, data, b"")
    assert img.halfblocks(0, 0, 2, 4, 1, 1) == [b"\x1b[38;2;20;30;40;48;2;50;100;25m\xe2\x96\x80"]


def test_the_cost_of_a_placement_does_not_grow_with_the_image():
    class Counting(bytes):
        reads = 0

        def __getitem__(self, key):
            type(self).reads += 1
            return super().__getitem__(key)

    def reads(side: int) -> int:
        Counting.reads = 0
        mosh.Image(side, side, 4, Counting(side * side * 4), b"").halfblocks(0, 0, side, side, 20, 10)
        return Counting.reads

    assert reads(1200) == reads(120) == 20 * 10 * 2 * mosh.SAMPLES**2


def png(width: int, height: int, color: int, pixels: bytes, deflated: bytes = b"") -> bytes:
    """A PNG that uses the five row filters in turn."""
    bpp = 3 if color == 2 else 4
    stride = width * bpp
    raw, prev = b"", bytes(stride)
    for r in range(height):
        row, kind = pixels[r * stride : (r + 1) * stride], r % 5
        out = bytearray()
        for i, v in enumerate(row):
            a, b, c = (row[i - bpp] if i >= bpp else 0), prev[i], (prev[i - bpp] if i >= bpp else 0)
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            guess = [0, a, b, (a + b) // 2, a if pa <= pb and pa <= pc else b if pb <= pc else c][kind]
            out.append((v - guess) & 255)
        raw += bytes([kind]) + bytes(out)
        prev = row

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    head = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    idat = deflated or zlib.compress(raw)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_a_png_that_inflates_past_its_header_is_declined():
    bomb = png(2, 2, 6, PIXELS, zlib.compress(bytes(10 << 20)))
    assert mosh.png_pixels(bomb) is None


def test_an_o_z_transmit_is_inflated_only_up_to_its_size():
    def transmit_z(data: bytes) -> mosh.Graphics:
        gfx = mosh.Graphics(120, 40)
        payload = base64.b64encode(zlib.compress(data))
        run(b"\x1b_Ga=t,t=d,f=32,o=z,s=2,v=2,i=1,q=2;%s\x1b\\" % payload, gfx=gfx)
        return gfx

    assert transmit_z(PIXELS).images[1].pixels == PIXELS
    assert transmit_z(PIXELS + b"x").images == {}
    assert transmit_z(bytes(10 << 20)).images == {}


@pytest.mark.parametrize("color", [2, 6])
def test_png_pixels_undoes_every_row_filter(color):
    bpp = 3 if color == 2 else 4
    pixels = bytes((i * 37 + i * i) & 255 for i in range(4 * 6 * bpp))
    assert mosh.png_pixels(png(4, 6, color, pixels)) == (4, 6, bpp, pixels)


def test_png_pixels_declines_other_forms():
    assert mosh.png_pixels(b"not a png") is None
    gray = png(2, 2, 2, bytes(12))
    assert mosh.png_pixels(gray.replace(b"\x08\x02", b"\x08\x00", 1)) is None  # color type 0
    assert mosh.png_pixels(gray[:-20]) is None  # cut short


def test_a_png_over_the_size_cap_goes_to_the_channel_whole_and_unpainted(monkeypatch):
    sent = []
    gfx = mosh.Graphics(120, 40, sent.append)
    data = png(2, 2, 6, PIXELS)
    command = b"\x1b_Ga=t,t=d,f=100,i=1,q=2;%s\x1b\\" % base64.b64encode(data)
    assert run(burst(command, place(1, 7, 3, 5)), gfx=gfx) == b"\x1b7\x1b[3;5H\x1b[3;5H" + CELLS + b"\x1b[3;5H\x1b8"
    monkeypatch.setattr(mosh, "PNG_MAX", 3)
    sent.clear()
    assert run(burst(command, place(1, 7, 3, 5)), gfx=gfx) == b"\x1b7\x1b[3;5H\x1b8"
    assert base64.b64decode(sent[0][3:-2].split(b";")[1]) == data


def test_a_png_placement_is_painted_and_sent_whole_to_the_channel():
    sent = []
    gfx = mosh.Graphics(120, 40, sent.append)
    data = png(2, 2, 6, PIXELS)
    command = b"\x1b_Ga=t,t=d,f=100,i=1,q=2;%s\x1b\\" % base64.b64encode(data)
    out = run(burst(command, place(1, 7, 3, 5)), gfx=gfx)
    assert out == b"\x1b7\x1b[3;5H\x1b[3;5H" + CELLS + b"\x1b[3;5H\x1b8"
    assert base64.b64decode(sent[0][3:-2].split(b";")[1]) == data


def test_a_png_that_the_server_cannot_decode_still_goes_to_the_channel_unpainted():
    sent = []
    gfx = mosh.Graphics(120, 40, sent.append)
    data = b"\x89PNG\r\n\x1a\n" + bytes(40)
    command = b"\x1b_Ga=t,t=d,f=100,i=1,q=2;%s\x1b\\" % base64.b64encode(data)
    assert run(burst(command, place(1, 7, 3, 5)), gfx=gfx) == b"\x1b7\x1b[3;5H\x1b8"
    assert base64.b64decode(sent[0][3:-2].split(b";")[1]) == data


def test_no_channel_means_no_compression():
    gfx = mosh.Graphics(120, 40)
    run(burst(transmit(1)), gfx=gfx)
    assert gfx.images[1].wire == b""


def test_malformed_commands_never_stop_the_text():
    out = run(b"\x1b[3;5H\x1b_Ga=p,i=x\x1b\\\x1b_Ga=t,f=32,s=9,v=9,i=3;!!\x1b\\ok")
    assert out == b"\x1b[3;5Hok"


def test_the_channel_gets_a_compressed_transmit_and_positioned_placements():
    sent = []
    gfx = mosh.Graphics(120, 40, sent.append)
    run(burst(transmit(1), place(1, 7, 3, 5)), gfx=gfx)
    keys, payload = sent[0][3:-2].split(b";")
    assert keys == b"a=t,f=32,o=z,s=2,v=2,i=1,q=2,m=0"
    assert zlib.decompress(base64.b64decode(payload)) == PIXELS
    assert sent[1] == place(1, 7, 3, 5)
    assert gfx.snapshot() == b"\x1b_Ga=d,d=A,q=2\x1b\\" + sent[0] + sent[1]


TOKEN = "abcdefghijklmnop_-012345"


@pytest.fixture
def runtime(monkeypatch):
    """A short RUNTIME: a unix socket path must fit in about 100 bytes."""
    folder = Path(tempfile.mkdtemp(dir="/tmp"))
    monkeypatch.setattr(mosh, "RUNTIME", str(folder))
    yield folder
    shutil.rmtree(folder)


@pytest.mark.parametrize("token", ["short", "../../etc/passwd-token", "a" * 65, "with space in the token"])
def test_a_channel_token_has_a_fixed_form(token):
    with pytest.raises(ValueError):
        mosh.channel_path(token)


def test_the_channel_directory_must_be_private(runtime):
    folder = runtime / f"herdr-patch-{os.getuid()}"
    folder.mkdir()
    folder.chmod(0o755)
    with pytest.raises(PermissionError):
        mosh.channel_path(TOKEN)
    folder.rmdir()
    (runtime / "elsewhere").mkdir(mode=0o700)
    folder.symlink_to(runtime / "elsewhere")
    with pytest.raises(PermissionError):
        mosh.channel_path(TOKEN)


def test_a_reader_of_the_token_gets_the_snapshot_then_live_graphics(runtime, capfd):
    path = mosh.channel_path(TOKEN)
    channel = mosh.Channel(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
    with pytest.raises(FileNotFoundError):  # another token finds no socket
        socket.socket(socket.AF_UNIX).connect(mosh.channel_path("x" * 16))
    reader = threading.Thread(target=mosh.read_channel, args=(TOKEN,))
    reader.start()
    assert select.select([channel.listener], [], [], 5)[0]
    channel.accept(b"snapshot;")
    channel.send(b"live")
    channel.close()
    reader.join(5)
    assert capfd.readouterr().out == "snapshot;live"
    assert not os.path.exists(path)


def test_reading_a_missing_channel_fails_cleanly(runtime):
    assert mosh.read_channel(TOKEN) == 1


@pytest.mark.parametrize(
    "argv, side",
    [
        ([], ("serve", [])),
        (["--session", "lab"], ("serve", ["--session", "lab"])),
        (["--channel", TOKEN, "--session", "lab"], ("serve", ["--channel", TOKEN, "--session", "lab"])),
        (["--read", TOKEN], ("read_channel", TOKEN)),
        (["user@host"], ("connect", "user@host", [])),
        (["host", "--session", "lab"], ("connect", "host", ["--session", "lab"])),
    ],
)
def test_a_first_argument_without_a_dash_is_the_host(monkeypatch, argv, side):
    for name in ("serve", "read_channel", "connect"):
        monkeypatch.setattr(mosh, name, lambda *a, name=name: (name, *a))
    assert mosh.main(["herdr-patch", *argv]) == side


def test_help_needs_no_terminal():
    done = subprocess.run([sys.executable, str(SCRIPT), "--help"], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=10)
    assert done.returncode == 0 and done.stdout.startswith("herdr over mosh")


# The computer's side: the channel's graphics state and where they go into mosh's output.

CHANNEL_TRANSMIT = b"\x1b_Ga=t,f=32,o=z,s=2,v=2,i=1,q=2,m=1;AAAA\x1b\\\x1b_Gm=0;AAAA\x1b\\"


def channel_place(p, row, col=5, image=1):
    return b"\x1b[%d;%dH\x1b_Ga=p,i=%d,p=%d,c=2,r=1,C=1,q=2\x1b\\" % (row, col, image, p)


def channel_delete(keys):
    return b"\x1b_Ga=d," + keys + b",q=2\x1b\\"


STREAM = (
    CHANNEL_TRANSMIT + channel_place(7, 3) + channel_delete(b"d=i,i=1,p=7") + channel_place(8, 6)
)


@pytest.mark.parametrize("cut", range(len(STREAM) + 1))
def test_the_channel_state_does_not_depend_on_read_splits(cut):
    images = mosh.Images()
    images.feed(STREAM[:cut])
    images.feed(STREAM[cut:])
    assert images.places == {(b"1", b"8"): channel_place(8, 6)}
    assert images.take() == b"\x1b7" + STREAM + b"\x1b8"


def test_deletes_by_image_and_all():
    images = mosh.Images()
    images.feed(channel_place(1, 3) + channel_place(2, 4) + channel_place(1, 5, image=2))
    images.feed(channel_delete(b"d=i,i=1"))
    assert list(images.places) == [(b"2", b"1")]
    images.feed(channel_delete(b"d=A"))
    assert images.places == {}


def test_restore_sends_every_placement_after_the_queue():
    images = mosh.Images()
    images.feed(channel_place(1, 3) + channel_place(2, 4))
    images.take()
    assert images.take() == b""
    images.feed(channel_delete(b"d=i,i=1,p=2"))
    restored = images.take(restore=True)
    assert restored == b"\x1b7" + channel_delete(b"d=i,i=1,p=2") + channel_place(1, 3) + b"\x1b8"


@pytest.mark.parametrize(
    "data, erased",
    [
        (b"\x1b[K", True),
        (b"\x1b[3X", True),
        (b"\x1b[2J", True),
        (b"\x1b[1;24r", True),
        (b"\x1b[2L", True),
        (b"ab\x1b[0;1m\x1b[3;4H\xe2\x96\x80\x1b]0;title\x07", False),
    ],
)
def test_erases_are_found_and_complete_output_is_safe_to_its_end(data, erased):
    assert mosh.Splicer().scan(data) == (len(data), erased)


def test_an_open_sequence_is_never_split():
    splicer = mosh.Splicer()
    assert splicer.scan(b"ab\x1b[12;") == (2, False)
    assert splicer.scan(b"5Hcd\x1b") == (4, False)
    assert splicer.scan(b"[K") == (2, True)


def test_an_open_utf8_character_is_never_split():
    splicer = mosh.Splicer()
    assert splicer.scan(b"x\xe2\x96") == (1, False)
    assert splicer.scan(b"\x80y\xf0\x9f\x98") == (2, False)
    assert splicer.scan(b"\x80") == (1, False)


def test_a_long_osc_has_no_safe_point_inside():
    splicer = mosh.Splicer()
    assert splicer.scan(b"a\x1b]0;tit") == (1, False)
    assert splicer.scan(b"le more") == (None, False)
    assert splicer.scan(b"\x07b") == (2, False)


def test_an_unknown_escape_does_not_block_later_output():
    data = b"\x1b\x01xyz\x1b[K"
    assert mosh.Splicer().scan(data) == (len(data), True)


def test_after_an_erase_the_placements_go_in_at_the_safe_point():
    images, splicer = mosh.Images(), mosh.Splicer()
    images.feed(channel_place(1, 3))
    images.take()
    out = splicer.splice(b"\x1b[3;1H\x1b[K\x1b[1", images)
    assert out == b"\x1b[3;1H\x1b[K\x1b7" + channel_place(1, 3) + b"\x1b8\x1b[1"
    assert splicer.splice(b"0;", images) == b"0;"  # still inside the CSI: nothing goes in
    assert splicer.splice(b"4Hx", images) == b"4Hx"  # nothing waits any more


def test_a_restore_waits_for_a_safe_point():
    images, splicer = mosh.Images(), mosh.Splicer()
    images.feed(channel_place(1, 3))
    images.take()
    assert splicer.splice(b"\x1b]0;a", images) == b"\x1b]0;a"
    splicer.restore = True  # a resize
    assert splicer.splice(b"b", images) == b"b"
    assert splicer.splice(b"\x07", images) == b"\x07\x1b7" + channel_place(1, 3) + b"\x1b8"


OLD_TOKEN = re.compile(
    rb"\x1b\[(\d*)(?:;(\d*))?[Hf]|\x1b\[[0-?]*[ -/]*([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    rb"|\x1b([78])|\x1b[ -/]*[0-Z\\^-~]?|([^\x1b]+)"
)
OLD_PIECE = re.compile(
    rb"\x1b\[[0-?]*[ -/]*([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[P_^X][^\x1b]*\x1b\\"
    rb"|\x1b[ -/]*[0-OQ-WYZ\\`-~]|[^\x1b]+"
)


def forms(b: int) -> list[bytes]:
    c = bytes([b])
    return [b"\x1b[" + c, b"\x1b[1;2" + c, b"\x1b[1;2 " + c, b"\x1b" + c, b"\x1b " + c, b"\x1b[ " + c, b"\x1b[" + c + b"m"]


def test_escape_regex_ranges_match_the_old_ones_for_every_byte():
    for b in range(256):
        for seq in forms(b):
            for old, new in ((OLD_TOKEN, mosh.TOKEN), (OLD_PIECE, mosh.PIECE)):
                assert [m.span() for m in old.finditer(seq)] == [m.span() for m in new.finditer(seq)], seq
                assert [m.groups() for m in old.finditer(seq)] == [m.groups() for m in new.finditer(seq)], seq


def test_escape_regex_samples_and_rejects_out_of_range_bytes():
    for seq in (b"\x1b[5;7H", b"\x1b[1;31m", b"\x1b]0;t\x07", b"\x1b7", b"\x1b8",):
        assert mosh.TOKEN.match(seq).group(0) == seq
        assert mosh.PIECE.match(seq).group(0) == seq
    assert mosh.PIECE.match(b"\x1b_Gi=1;AAAA\x1b\\").group(0) == b"\x1b_Gi=1;AAAA\x1b\\"
    assert mosh.TOKEN.match(b"\x1b[1\x80").group(0) == b"\x1b"  # not a CSI final byte
    assert mosh.PIECE.match(b"\x1b\x7f") is None  # DEL is not an ESC final byte
