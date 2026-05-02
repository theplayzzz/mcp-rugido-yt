"""Tests for comment tools with mocked YouTube API."""

from unittest.mock import MagicMock, patch


class TestListComments:
    @patch("mcp_rugido_yt.tools.comments.auth")
    @patch("mcp_rugido_yt.tools.comments.quota")
    def test_list(self, mock_quota, mock_auth):
        from mcp_rugido_yt.tools.comments import youtube_list_comments

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.commentThreads().list().execute.return_value = {
            "items": [{
                "id": "thread1",
                "snippet": {
                    "topLevelComment": {
                        "id": "comment1",
                        "snippet": {
                            "authorDisplayName": "User1",
                            "textDisplay": "Great video!",
                            "likeCount": 5,
                            "publishedAt": "2025-06-01T00:00:00Z",
                        },
                    },
                    "totalReplyCount": 2,
                },
            }]
        }

        result = youtube_list_comments("vid1")
        assert result["video_id"] == "vid1"
        assert len(result["comments"]) == 1
        assert result["comments"][0]["text"] == "Great video!"
        assert result["comments"][0]["reply_count"] == 2
        mock_quota.consume.assert_called_once_with("list")
