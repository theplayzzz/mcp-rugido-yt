"""Comment tools — read-only.

Tools de escrita (post_comment, reply_to_comment) foram removidas: dependiam
do escopo restricted `youtube`/`youtube.force-ssl` que exige Verificação
Google. Ver auth.py:SCOPES.
"""

from mcp_rugido_yt.server import auth, mcp, quota


@mcp.tool()
def youtube_list_comments(
    video_id: str,
    max_results: int = 20,
    order: str = "relevance",
) -> dict:
    """List top-level comments on a video.

    Args:
        video_id: YouTube video ID
        max_results: Number of comment threads to return (max 100)
        order: Sort order: "relevance" or "time"
    """
    quota.consume("list")
    youtube = auth.build_youtube_service()

    response = (
        youtube.commentThreads()
        .list(
            part="snippet",
            videoId=video_id,
            maxResults=min(max_results, 100),
            order=order,
        )
        .execute()
    )

    comments = []
    for item in response.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "comment_id": item["snippet"]["topLevelComment"]["id"],
            "thread_id": item["id"],
            "author": top.get("authorDisplayName"),
            "text": top.get("textDisplay"),
            "likes": top.get("likeCount", 0),
            "published_at": top.get("publishedAt"),
            "reply_count": item["snippet"].get("totalReplyCount", 0),
        })

    return {
        "video_id": video_id,
        "comments": comments,
        "total": len(comments),
    }
