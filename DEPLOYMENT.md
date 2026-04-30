# Deploy do MCP Rugido YT no Dokploy

Passo a passo, do zero até o servidor rodando em `https://mcp-rugido-yt.gruporugido.com` (ou outro subdomínio).

## Visão geral

```
GitHub (theplayzzz/mcp-rugido-yt)
   │ push main
   ▼
Dokploy (dokploy.gruporugido.com) ── auto-deploy via GitHub App
   │ build Dockerfile
   ▼
Container app + service Postgres
   │ HTTPS via Traefik + Let's Encrypt
   ▼
mcp-rugido-yt.gruporugido.com  →  acessível pelos colegas
```

## Pré-requisitos

- [x] Repo criado no GitHub: `theplayzzz/mcp-rugido-yt`
- [ ] Dokploy atualizado (versão recente, com API exposta)
- [ ] DNS apontando o subdomínio escolhido pro IP do servidor Dokploy **antes** de adicionar o domínio no Dokploy
- [ ] Email pra Let's Encrypt configurado em **Web Server > Traefik** no Dokploy

## 1. Google Cloud — criar OAuth Web App

1. Acesse https://console.cloud.google.com → crie um projeto novo (ex: "MCP Rugido YT") ou reuse um existente.

2. Em **APIs & Services > Library**, habilite:
   - YouTube Data API v3
   - YouTube Analytics API
   - YouTube Reporting API

3. **OAuth consent screen** (APIs & Services > OAuth consent screen):
   - User Type: **External** (Workspace não disponível)
   - App name: `MCP Rugido YT`
   - Support email + Developer contact
   - Authorized domains: `gruporugido.com`
   - Scopes: adicione todos os do YouTube e Analytics que estão em `src/mcp_rugido_yt/auth.py:SCOPES`
   - **Publish app** → muda pra "In Production". Sem verificação ainda — usuários verão tela "App não verificado" no primeiro consent (clicar em "Avançado" → "Continuar"). É inofensivo. Verificação só vale se for distribuir externamente.

4. **Credentials > Create credentials > OAuth client ID**:
   - Type: **Web application**
   - Name: `MCP Rugido YT Web`
   - Authorized redirect URIs: **`https://mcp-rugido-yt.gruporugido.com/oauth/callback`** (substitua pelo seu domínio final — tem que bater EXATAMENTE com `MCP_PUBLIC_BASE_URL` + `/oauth/callback`)
   - Salve o **Client ID** e o **Client Secret**

## 2. Gerar Fernet key

Localmente, na máquina de dev:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Guarde o output em local seguro. Se essa chave for perdida, todos os tokens criptografados no Postgres viram ilegíveis e os usuários têm que refazer o consent.

## 3. Dokploy — criar Postgres service

1. Login em https://dokploy.gruporugido.com
2. Abrir o projeto (ou criar um novo, ex: `mcp-rugido-yt`)
3. **Add Service > Postgres**
   - Image: `postgres:16-alpine`
   - Database name: `mcp_rugido_yt`
   - User: `rugido`
   - Password: gere uma forte e guarde
4. Iniciar o service. Anote o **internal connection string** que o Dokploy mostra (algo como `postgresql://rugido:<senha>@<service-name>:5432/mcp_rugido_yt`).
5. Para o app vai usar `postgresql+asyncpg://...` (mesma string, só troca o driver).

## 4. Dokploy — criar a aplicação

1. **Add Application > Git**
2. Source:
   - Provider: GitHub (autorize a GitHub App do Dokploy se ainda não fez)
   - Repository: `theplayzzz/mcp-rugido-yt`
   - Branch: `main`
3. Build Type: **Dockerfile** (auto-detect deve pegar o `Dockerfile` na raiz)
4. **Environment Variables**:
   ```
   DATABASE_URL=postgresql+asyncpg://rugido:<senha>@<service-name>:5432/mcp_rugido_yt
   MCP_HOST=0.0.0.0
   MCP_PORT=8000
   MCP_PUBLIC_BASE_URL=https://mcp-rugido-yt.gruporugido.com
   GOOGLE_CLIENT_ID=<copiado do step 1>
   GOOGLE_CLIENT_SECRET=<copiado do step 1>
   FERNET_KEY=<gerado no step 2>
   DAILY_QUOTA_LIMIT=10000
   ```
5. **Deploy** — primeira build vai rodar (clone + build da imagem + start). Acompanhe os logs.
6. Após build OK, o entrypoint vai esperar o Postgres + rodar `alembic upgrade head` automaticamente, criando a tabela `yt_mcp_sessions`.

## 5. Dokploy — domínio + HTTPS

1. **General > Domains > Add Domain**
2. Host: `mcp-rugido-yt.gruporugido.com`
3. Container port: `8000`
4. HTTPS: ✅
5. CertResolver: `letsencrypt`
6. **Save**. Traefik gera o cert via HTTP-01 challenge (precisa que o DNS já esteja apontado).

Aguarde ~30s. Acesse `https://mcp-rugido-yt.gruporugido.com/health` — deve responder `{"status":"ok"}`.

## 6. Auto-deploy

1. **General > Auto Deploy**: toggle ON
2. Dokploy mostra a Webhook URL — adicione no GitHub: **Settings > Webhooks > Add webhook**
   - Payload URL: a URL que o Dokploy mostrou
   - Content type: `application/json`
   - Events: `Just the push event`
3. Daí em diante, todo `git push origin main` dispara um redeploy.

> Alternativa via GitHub App (mais confiável): em Dokploy **Settings > Git > GitHub > Install GitHub App**, autoriza no repo, aí o auto-deploy é nativo, sem precisar webhook manual.

## 7. Teste end-to-end

1. Abra `https://mcp-rugido-yt.gruporugido.com/oauth/connect` no browser
2. Logue com a conta Google que possui o canal YouTube
3. Aceite o consent (vai aparecer "App não verificado" — clique em "Avançado > Continuar")
4. Página final mostra o `session_id`. Copie.
5. Adicione no `claude_desktop_config.json` (ou na config do Claude Code):
   ```json
   {
     "mcpServers": {
       "rugido-yt": {
         "url": "https://mcp-rugido-yt.gruporugido.com/mcp",
         "headers": { "Authorization": "Bearer ymp_..." }
       }
     }
   }
   ```
6. Reinicie o cliente MCP. As 40 tools devem aparecer.

## Troubleshooting

| Problema | Causa provável |
|---|---|
| `redirect_uri_mismatch` no Google | URI cadastrada no Google ≠ `MCP_PUBLIC_BASE_URL`+`/oauth/callback` |
| `400 State mismatch` | Cookie bloqueado (usuário usou abas diferentes ou bloqueador de cookies) |
| `Quota exhausted` | Usuário já consumiu 10k units do dia. Reset à meia-noite UTC. |
| Cert Let's Encrypt não gerado | DNS ainda não propagou; aguarde ou recriar o domínio no Dokploy |
| `id_token ausente` | Faltou `openid email` no `OAuth consent screen > Scopes` |
| Tools retornam 401 sem motivo | session_id revogado (alguém autorizou a mesma conta de novo, o que invalida sessões antigas) |

## Rotação de chaves

- **Google client_secret**: pode rotacionar em **APIs & Services > Credentials**. Atualize a env var no Dokploy e redeploy. **Tokens existentes seguem válidos**, porque eles dependem do refresh_token, não do client_secret diretamente — mas refresh do access_token vai começar a falhar se o client_secret mudar e o user precisar reautenticar.
- **FERNET_KEY**: NUNCA rotacione sem migração. Se rotacionar, todos os refresh_tokens viram lixo e users precisam refazer consent. Para fazer rotação certa: armazenar a versão da chave junto com o ciphertext e suportar múltiplas chaves durante a transição.

## Backup

O Dokploy tem backup nativo pra Postgres em **Service > Backup**. Configure pelo menos diário. O conteúdo crítico é a tabela `yt_mcp_sessions` — sem ela, todos os usuários precisam refazer consent.
