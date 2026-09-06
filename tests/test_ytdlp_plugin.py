"""Tests for the rewritten yt_dlp plugin's helper logic.

No network: yt-dlp itself is stubbed. What is worth pinning down is the
part around it, because the plugin this replaced failed on exactly these
points - it invented yt-dlp options, imported the wrong module, and would
have written wherever it was told.

Two properties matter most:

* Output stays inside the configured root. The url and output path both
  come from a model, so a path that escapes is how a download tool becomes
  an arbitrary file writer.
* Options are real yt-dlp keys. The previous version passed
  `force_it_to_be_mp3` and `preferredtemplate`, neither of which exists,
  so audio extraction could never have worked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from usr.plugins.yt_dlp.helpers import downloader as d


# ------------------------------------------------------------------
# URL validation
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/win.ini",
        "file://localhost/etc/passwd",
        "ftp://example.com/x",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "",
        None,
    ],
)
def test_non_http_urls_are_refused(url):
    """yt-dlp accepts file:// and other local protocols, which would turn a
    download tool into an arbitrary local-file reader."""
    with pytest.raises(d.DownloadError):
        d.validate_url(url)


@pytest.mark.parametrize(
    "url",
    ["http://example.com/v", "https://youtube.com/watch?v=x", "  https://a.b/c  "],
)
def test_http_urls_are_accepted_and_trimmed(url):
    assert d.validate_url(url).startswith(("http://", "https://"))
    assert d.validate_url(url) == url.strip()


# ------------------------------------------------------------------
# Output confinement
# ------------------------------------------------------------------

def test_default_output_is_the_root(tmp_path, monkeypatch):
    monkeypatch.setattr(d.files, "get_abs_path", lambda *p: str(tmp_path / "dl"))
    assert d.resolve_output_dir(None) == (tmp_path / "dl").resolve()


def test_relative_path_becomes_a_subfolder(tmp_path, monkeypatch):
    monkeypatch.setattr(d.files, "get_abs_path", lambda *p: str(tmp_path / "dl"))
    out = d.resolve_output_dir("music/live")
    assert out == (tmp_path / "dl" / "music" / "live").resolve()
    assert out.is_dir()


@pytest.mark.parametrize(
    "escape",
    ["../outside", "../../outside", "music/../../outside", "music/../.."],
)
def test_traversal_out_of_the_root_is_refused(tmp_path, monkeypatch, escape):
    monkeypatch.setattr(d.files, "get_abs_path", lambda *p: str(tmp_path / "dl"))
    with pytest.raises(d.DownloadError):
        d.resolve_output_dir(escape)


def test_absolute_path_outside_the_root_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(d.files, "get_abs_path", lambda *p: str(tmp_path / "dl"))
    with pytest.raises(d.DownloadError):
        d.resolve_output_dir(str(tmp_path / "elsewhere"))


def test_absolute_path_inside_the_root_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(d.files, "get_abs_path", lambda *p: str(tmp_path / "dl"))
    inside = tmp_path / "dl" / "sub"
    assert d.resolve_output_dir(str(inside)) == inside.resolve()


# ------------------------------------------------------------------
# Option building
# ------------------------------------------------------------------

def _opts(tmp_path, **kw):
    return d.build_options(tmp_path, kw.pop("limits", d.Limits()), **kw)


def test_only_real_ytdlp_options_are_emitted(tmp_path):
    """Guards the specific failure of the previous plugin: every key must
    appear in yt-dlp's own documented option list."""
    import inspect

    import yt_dlp

    doc = inspect.getdoc(yt_dlp.YoutubeDL) or ""
    for key in _opts(tmp_path):
        assert key in doc, f"{key!r} is not a documented yt-dlp option"


def test_the_previously_invented_options_are_gone(tmp_path):
    emitted = str(_opts(tmp_path))
    assert "force_it_to_be_mp3" not in emitted
    assert "preferredtemplate" not in emitted


def test_without_ffmpeg_the_format_needs_no_merge(tmp_path, monkeypatch):
    """bestvideo+bestaudio downloads fine and then dies in post-processing
    when ffmpeg is missing, which looks like a working request until the
    end. A progressive format avoids that entirely."""
    monkeypatch.setattr(d, "ffmpeg_available", lambda: False)
    assert _opts(tmp_path)["format"] == d.PROGRESSIVE_FORMAT
    assert "+" not in _opts(tmp_path)["format"]


def test_with_ffmpeg_the_better_merged_format_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "ffmpeg_available", lambda: True)
    assert _opts(tmp_path)["format"] == d.MERGED_FORMAT


def test_audio_only_is_refused_up_front_without_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "ffmpeg_available", lambda: False)
    with pytest.raises(d.DownloadError) as exc:
        _opts(tmp_path, audio_only=True)
    assert "ffmpeg" in str(exc.value)


def test_audio_only_uses_the_real_postprocessor_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "ffmpeg_available", lambda: True)
    post = _opts(tmp_path, audio_only=True)["postprocessors"][0]
    assert post["key"] == "FFmpegExtractAudio"
    # These are the parameter names FFmpegExtractAudioPP actually takes.
    import inspect

    from yt_dlp.postprocessor import FFmpegExtractAudioPP

    accepted = set(inspect.signature(FFmpegExtractAudioPP.__init__).parameters)
    assert set(post) - {"key"} <= accepted


def test_explicit_format_id_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "ffmpeg_available", lambda: True)
    assert _opts(tmp_path, format_id="137")["format"] == "137"


def test_playlists_are_opt_in(tmp_path):
    assert _opts(tmp_path)["noplaylist"] is True
    assert _opts(tmp_path, limits=d.Limits(allow_playlist=True))["noplaylist"] is False


def test_size_limit_is_expressed_in_bytes(tmp_path):
    assert _opts(tmp_path, limits=d.Limits(max_filesize_mb=10))["max_filesize"] == (
        10 * 1024 * 1024
    )


def test_zero_disables_the_size_limit(tmp_path):
    assert "max_filesize" not in _opts(tmp_path, limits=d.Limits(max_filesize_mb=0))


def test_output_template_is_length_bounded(tmp_path):
    """Windows paths cap around 260 characters, and video titles can be
    far longer than the filesystem allows."""
    assert ".150B" in _opts(tmp_path)["outtmpl"]


# ------------------------------------------------------------------
# Result reporting
# ------------------------------------------------------------------

def test_download_reports_the_files_that_appeared(tmp_path, monkeypatch):
    """Reported names come from diffing the directory, not from
    prepare_filename, which gives the pre-postprocessing extension."""
    monkeypatch.setattr(d.files, "get_abs_path", lambda *p: str(tmp_path / "dl"))

    class FakeYDL:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            (tmp_path / "dl" / "Song [abc].mp3").write_bytes(b"x" * 2048)
            return {"title": "Song"}

    monkeypatch.setattr(d, "_ydl", lambda options: FakeYDL())
    result = d.download("https://example.com/v")
    assert result["files"] == ["Song [abc].mp3"]
    assert result["bytes"] == 2048
    assert result["title"] == "Song"


def test_download_ignores_files_that_were_already_there(tmp_path, monkeypatch):
    monkeypatch.setattr(d.files, "get_abs_path", lambda *p: str(tmp_path / "dl"))
    (tmp_path / "dl").mkdir(parents=True)
    (tmp_path / "dl" / "old.mp4").write_bytes(b"old")

    class FakeYDL:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            (tmp_path / "dl" / "new.mp4").write_bytes(b"new")
            return {"title": "New"}

    monkeypatch.setattr(d, "_ydl", lambda options: FakeYDL())
    assert d.download("https://example.com/v")["files"] == ["new.mp4"]


def test_list_formats_drops_storyboards_and_flags_progressive(monkeypatch):
    """Storyboards are thumbnail sheets rather than media, and whether a
    format is progressive decides if it plays without ffmpeg."""
    class FakeYDL:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            return {
                "formats": [
                    {"format_id": "sb0", "ext": "mhtml", "format_note": "storyboard"},
                    {"format_id": "18", "ext": "mp4", "vcodec": "h264",
                     "acodec": "aac", "filesize": 5 * 1024 * 1024},
                    {"format_id": "137", "ext": "mp4", "vcodec": "h264",
                     "acodec": "none", "filesize": None},
                ]
            }

    monkeypatch.setattr(d, "_ydl", lambda options: FakeYDL())
    rows = d.list_formats("https://example.com/v")
    assert [r["format_id"] for r in rows] == ["137", "18"]
    assert {r["format_id"]: r["progressive"] for r in rows} == {"18": True, "137": False}
    assert next(r for r in rows if r["format_id"] == "18")["filesize_mb"] == 5.0
