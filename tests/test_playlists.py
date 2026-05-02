"""Tests for playlist tools with mocked YouTube API."""

from unittest.mock import MagicMock, patch


class TestListPlaylists:
    @patch("mcp_rugido_yt.tools.playlists.auth")
    @patch("mcp_rugido_yt.tools.playlists.quota")
    def test_list_mine(self, mock_quota, mock_auth):
        from mcp_rugido_yt.tools.playlists import youtube_list_playlists

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.playlists().list().execute.return_value = {
            "items": [{
                "id": "PL123",
                "snippet": {
                    "title": "My Playlist",
                    "description": "A playlist",
                    "publishedAt": "2025-01-01T00:00:00Z",
                    "thumbnails": {"high": {"url": "https://example.com/thumb.jpg"}},
                },
                "contentDetails": {"itemCount": 5},
            }]
        }

        result = youtube_list_playlists(mine=True)
        assert len(result["playlists"]) == 1
        assert result["playlists"][0]["title"] == "My Playlist"
        assert result["playlists"][0]["video_count"] == 5

    @patch("mcp_rugido_yt.tools.playlists.auth")
    @patch("mcp_rugido_yt.tools.playlists.quota")
    def test_list_no_args(self, mock_quota, mock_auth):
        from mcp_rugido_yt.tools.playlists import youtube_list_playlists

        result = youtube_list_playlists()
        assert "error" in result
