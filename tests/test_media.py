"""Real local synthetic media and FFmpeg merging; not platform download PASS."""
import shutil
import subprocess

import pytest
from yt_dlp.postprocessor.ffmpeg import FFmpegMergerPP

from app.worker import SafeYoutubeDL, probe_media


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg/ffprobe required')
def test_lossless_merge_keeps_real_resolution_audio_and_duration(tmp_path):
    video, audio, merged = [tmp_path / name for name in ('video.mp4', 'audio.m4a', 'merged.mp4')]
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=25:d=1',
                    '-c:v', 'mpeg4', '-an', str(video)], check=True, timeout=30)
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                    '-c:a', 'aac', str(audio)], check=True, timeout=30)
    with SafeYoutubeDL({'quiet': True}) as ydl:
        FFmpegMergerPP(ydl).run({'filepath': str(merged), '__files_to_merge': [str(video), str(audio)],
                               'requested_formats': [{'vcodec': 'mpeg4', 'acodec': 'none', 'ext': 'mp4', 'protocol': 'https'},
                                                     {'vcodec': 'none', 'acodec': 'aac', 'ext': 'm4a', 'protocol': 'https'}]})
    measured = probe_media(merged)
    assert (measured['width'], measured['height']) == (320, 180)
    assert measured['has_audio'] and measured['vcodec'] == 'mpeg4' and measured['acodec'] == 'aac'
    assert abs(measured['duration'] - 1) < 0.1
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(merged), '-f', 'null', '-'], check=True, timeout=30)


def test_ffprobe_rejects_non_video(tmp_path):
    if not shutil.which('ffprobe'):
        pytest.skip('ffprobe required')
    from app.downloader import DownloadError
    bad = tmp_path / 'fake.mp4'
    bad.write_text('<html>Access denied</html>')
    with pytest.raises(DownloadError) as error:
        probe_media(bad)
    assert error.value.code == 'invalid_media'


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg/ffprobe required')
def test_worker_native_download_and_merge_with_synthetic_transport(tmp_path, monkeypatch):
    """Actual media bytes/merger, mocked platform metadata and network transport."""
    from yt_dlp.networking import Response
    from app import worker
    video, audio = tmp_path / 'input.mp4', tmp_path / 'input.m4a'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=25:d=1',
                    '-c:v', 'mpeg4', '-an', str(video)], check=True, timeout=30)
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                    '-c:a', 'aac', str(audio)], check=True, timeout=30)
    media = {'https://media.example/video.mp4': video, 'https://media.example/audio.m4a': audio}

    def response(self, request):
        url = request.url if hasattr(request, 'url') else request
        path = media[url]
        return Response(path.open('rb'), url, {'Content-Length': str(path.stat().st_size)}, status=200)

    info = {'id': 'synthetic', 'title': 'Synthetic media', 'duration': 1,
            'formats': [{'format_id': 'video', 'url': 'https://media.example/video.mp4', 'ext': 'mp4',
                         'protocol': 'https', 'vcodec': 'mpeg4', 'acodec': 'none', 'width': 320, 'height': 180},
                        {'format_id': 'audio', 'url': 'https://media.example/audio.m4a', 'ext': 'm4a',
                         'protocol': 'https', 'vcodec': 'none', 'acodec': 'aac'}]}
    monkeypatch.setattr(worker, 'install_socket_guard', lambda: None)
    monkeypatch.setattr(SafeYoutubeDL, 'extract_info', lambda *args, **kwargs: info)
    monkeypatch.setattr(SafeYoutubeDL, 'urlopen', response)
    monkeypatch.setattr(worker.FFmpegFD, 'real_download', worker.FFmpegFD.real_download)
    output = tmp_path / 'output'
    output.mkdir()
    result = worker.run_task({'mode': 'download', 'url': 'https://youtu.be/synthetic',
                              'quality': 'best', 'directory': str(output), 'max_bytes': 1024 * 1024})
    assert (output / result['path']).is_file()
    assert result['info']['has_audio'] and result['info']['width'] == 320
    assert result['info']['watermark_status'] == 'unverified'
