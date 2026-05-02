# MCP Rugido YT

MCP server multi-tenant para YouTube Data API v3, Analytics API e Reporting API. Cada usuário se conecta com seu próprio canal via OAuth Google e recebe um `session_id` (`ymp_xxx`) que cola no Authorization header do cliente MCP.

**30 tools** focadas em **read + analytics**: dados de canal/vídeo, todas as métricas Analytics (performance, audiência, retenção, receita, demographics, geography), search/SEO, transcripts, listagem de playlists e comentários, bulk reporting.

Tools de write (upload, post_comment, create_playlist, etc) foram removidas: dependem de escopos `restricted` que exigem Verificação Google + Security Assessment.

## Modelo de uso

```
Usuário → /oauth/connect → Consent Google → /oauth/callback → recebe session_id
                                                                      ↓
       cola no Claude Desktop/Code com Authorization: Bearer ymp_...
                                                                      ↓
                  todas as tools rodam em nome do canal autorizado
```

## Configuração no cliente MCP

Após pegar o `session_id` em `https://<seu-host>/oauth/connect`:

```json
{
  "mcpServers": {
    "rugido-yt": {
      "url": "https://<seu-host>/mcp",
      "headers": { "Authorization": "Bearer ymp_..." }
    }
  }
}
```

## Deploy

Ver [DEPLOYMENT.md](DEPLOYMENT.md) para o passo a passo completo (Google Cloud + Dokploy + GitHub).

## Desenvolvimento local

```bash
cp .env.example .env
# preencha GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, FERNET_KEY
docker compose up --build
```

Servidor sobe em `http://localhost:8000` (mas o OAuth Google só funciona com `MCP_PUBLIC_BASE_URL` HTTPS — para teste local use ngrok ou similar).

Rodar testes:

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest
```

## Tools expostas (30 tools — read + analytics)

### Auth/Status (1)
- `youtube_auth_status` — canal vinculado, escopos, quota usada

### Channel & Video (3)
- `youtube_get_channel`, `youtube_list_videos`, `youtube_get_video`

### Search & SEO (4)
- `youtube_search`, `youtube_search_suggestions`, `youtube_trending`, `youtube_get_categories`

### Transcripts (2)
- `youtube_get_transcript`, `youtube_list_captions`

### Analytics (13)
- `youtube_analytics_overview`, `youtube_analytics_top_videos`, `youtube_analytics_top_shorts`, `youtube_analytics_video_detail`
- `youtube_analytics_traffic_sources`, `youtube_analytics_demographics`, `youtube_analytics_geography`
- `youtube_analytics_daily`, `youtube_analytics_day_of_week`, `youtube_analytics_content_type_breakdown`
- `youtube_analytics_revenue`, `youtube_analytics_revenue_by_video`, `youtube_analytics_retention`

### Playlists (1)
- `youtube_list_playlists`

### Comments (1)
- `youtube_list_comments`

### Bulk Reporting (5)
- `youtube_reporting_list_types`, `youtube_reporting_create_job`, `youtube_reporting_list_jobs`, `youtube_reporting_list_reports`, `youtube_reporting_download`

### Tools removidas (precisam de escopos restricted + Verificação Google)

Estas existiam no upstream mas foram desabilitadas para o app rodar em
Production sem Verificação. Pra reativar: passar pela Verificação Google
(Privacy Policy + demo video; pra `youtube.upload`/`youtube.force-ssl`
também Security Assessment de US$ 4-15k), e re-adicionar `youtube` e
`youtube.upload` em `auth.py:SCOPES`.

- Publishing: `youtube_upload_video`, `youtube_update_video`, `youtube_set_thumbnail`, `youtube_delete_video`
- Comments write: `youtube_post_comment`, `youtube_reply_to_comment`
- Playlists write: `youtube_create_playlist`, `youtube_add_to_playlist`, `youtube_remove_from_playlist`

## Quota

A YouTube Data API tem 10.000 units/dia por projeto. **Esse limite é compartilhado entre todos os usuários** do mesmo OAuth client. Cada sessão tem seu próprio contador interno (campo `quota_used` no DB) que pode ser ajustado via `DAILY_QUOTA_LIMIT`. Operações custosas:

- Search: 100 units
- Demais reads: 1 unit

## Origem

Fork de [pauling-ai/youtube-mcp-server](https://github.com/pauling-ai/youtube-mcp-server), refatorado para servir multi-tenant via streamable-http com persistência de sessão em Postgres.

## Licença

MIT
