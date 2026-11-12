from app.platforms import detect_platform, extract_url


def test_detect_youtube():
    assert detect_platform("https://www.youtube.com/watch?v=abc")["key"] == "youtube"
    assert detect_platform("https://youtu.be/abc")["key"] == "youtube"


def test_detect_tiktok():
    assert detect_platform("https://www.tiktok.com/@user/video/123")["key"] == "tiktok"


def test_detect_xiaohongshu():
    assert detect_platform("http://xhslink.com/abc")["key"] == "xiaohongshu"


def test_extract_url_from_share_text():
    text = "分享一个视频 https://v.douyin.com/xxxx/ 复制链接"
    assert extract_url(text) == "https://v.douyin.com/xxxx/"


def test_unknown_returns_none():
    assert detect_platform("https://example.com/video/1") is None
