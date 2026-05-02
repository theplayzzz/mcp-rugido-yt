"""Playlist tools — read-only.

Tools de escrita (create_playlist, add_to_playlist, remove_from_playlist) foram
removidas: dependiam do escopo restricted `youtube` que exige Verificação
Google. Ver auth.py:SCOPES.
"""

from mcp_rugido_yt.server import auth, mcp, quota


@mcp.tool()
def youtube_list_playlists(
    channel_id: str | None = None,
    mine: bool = False,
    max_results: int = 25,
) -> dict:
    """List playlists for a channel.

    Args:
        channel_id: Channel ID to list playlists from
        mine: If True, list the authenticated user's playlists
        max_results: Number of playlists to return (max 50)
    """
    quota.consume("list")
    youtube = auth.build_youtube_service()

    params = {"part": "snippet,contentDetails", "maxResults": min(max_results, 50)}
    if mine:
        params["mine"] = True
    elif channel_id:
        params["channelId"] = channel_id
    else:
        return {"error": "Provide channel_id or set mine=True"}

    response = youtube.playlists().list(**params).execute()

    playlists = []
    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        playlists.append({
            "id": item["id"],
            "title": snippet.get("title"),
            "description": snippet.get("description", "")[:200],
            "published_at": snippet.get("publishedAt"),
            "video_count": item.get("contentDetails", {}).get("itemCount", 0),
            "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url"),
        })

    return {"playlists": playlists, "total": len(playlists)}
