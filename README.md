# memed-mcp

Servidor MCP, independente do cliente LLM, para **preparar** receitas e atestados na
[Memed](https://memed.com.br). O LLM nunca emite: ele cria um rascunho e devolve um link.
O médico abre o link, confere e emite no módulo oficial da Memed, onde também faz a assinatura digital.

## Por que esse desenho

A API REST da Memed não emite prescrições. A emissão acontece no módulo web
(Sinapse Prescrição), com ação do médico. Este servidor aproveita isso e acrescenta proteções:

- O LLM só cria rascunhos (`preparar_receita`, `preparar_atestado`).
- A página de revisão mostra o que o LLM propôs, abre o módulo da Memed já preenchido e
  registra a emissão quando a Memed dispara o evento `prescricaoImpressa`.
- O servidor só marca como `emitida` depois de confirmar a prescrição na API da Memed.
- A exclusão também passa por uma página, com confirmação do médico (`solicitar_exclusao`).
- As credenciais ficam em variáveis de ambiente, e o token do prescritor nunca é gravado nem devolvido ao LLM.

```
LLM ──MCP (HTTP + Bearer)──▶ memed-mcp ──REST──▶ API Memed (prescritor, consulta, PDF, exclusão)
                                │
                                └─ link de revisão ─▶ navegador do médico ─▶ módulo Memed (emitir/assinar)
                                                          └─ evento "prescricaoImpressa" ─▶ memed-mcp confirma na API
```

## Ferramentas MCP

| Ferramenta | O que faz | Efeito externo |
|---|---|---|
| `status_prescritor` | Verifica cadastro/status do médico na Memed | leitura |
| `preparar_receita` | Cria rascunho com medicamentos e textos livres | nenhum (local) |
| `preparar_atestado` | Cria rascunho de atestado/declaração (texto livre) | nenhum (local) |
| `status_rascunho` / `listar_rascunhos` | Mostra se o médico já emitiu | leitura local |
| `listar_prescricoes_memed` / `obter_pdf` | Consulta prescrições emitidas e PDF | leitura |
| `solicitar_exclusao` | Gera link para o médico confirmar a exclusão | nenhum até o médico confirmar |

Há também o prompt MCP `fluxo_prescricao` e a skill [`skills/memed-prescricao`](skills/memed-prescricao/SKILL.md),
com as regras clínicas: conferir alergias e doses, não colocar CID sem autorização e nunca afirmar emissão sem confirmação.

## Credenciais

A integração usa **chaves de parceiro** (`api-key` e `secret-key`), que são diferentes do login de médico no site da Memed.

1. **Homologação:** a documentação da Memed publica chaves de teste fixas
   (doc.memed.com.br > Primeiros passos). Os documentos de homologação não têm validade legal.
   Esse ambiente fica indisponível das 0h às 6h em dias úteis e nos fins de semana.
2. **Produção:** a Memed libera as chaves pelo formulário de credenciais de produção,
   depois de avaliar a integração (doc.memed.com.br > Credenciais de produção).

## Instalação no dev-docker (Proxmox)

```bash
git clone <este repositório> memed-mcp && cd memed-mcp
cp .env.example .env
# preencha .env (chaves de homologação, MEMED_PRESCRIBER_*, PUBLIC_BASE_URL, ALLOWED_HOSTS)
openssl rand -hex 32   # cole em MCP_AUTH_TOKEN
docker compose build

# 1) cadastrar você como prescritor no ambiente escolhido (uma vez)
docker compose run --rm memed-mcp registrar-prescritor
# 2) conferir
docker compose run --rm memed-mcp status
# 3) subir
docker compose up -d
```

O endpoint MCP fica em `http://<host>:8765/mcp` (Streamable HTTP) e exige
`Authorization: Bearer <MCP_AUTH_TOKEN>`. As páginas de revisão ficam em `/rascunhos/<id>`.

**Rede:** mantenha a porta só na LAN ou na VPN (WireGuard/Tailscale). Para acesso externo, use um proxy
reverso com TLS (Caddy/Traefik/nginx) e restrinja as rotas `/rascunhos` e `/exclusoes` com autenticação
do proxy, porque essas páginas carregam o token do prescritor para o módulo da Memed.

## Conectar um cliente LLM

Qualquer cliente compatível com MCP por HTTP funciona. Exemplos:

**Claude Code**
```bash
claude mcp add --transport http memed http://dev-docker.lan:8765/mcp \
  --header "Authorization: Bearer $MCP_AUTH_TOKEN"
```

**Clientes que só falam stdio** (usam o `mcp-remote` como ponte):
```json
{
  "mcpServers": {
    "memed": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://dev-docker.lan:8765/mcp", "--allow-http",
               "--header", "Authorization: Bearer ${MCP_AUTH_TOKEN}"],
      "env": {"MCP_AUTH_TOKEN": "..."}
    }
  }
}
```

**Claude.ai e apps na nuvem:** precisam alcançar o servidor por HTTPS público, então exigem proxy reverso com TLS
(Cloudflare Tunnel, por exemplo). Avalie com cuidado antes de expor o servidor.

## Pontos a validar na homologação

O site de documentação da Memed não permitiu leitura automatizada de todas as páginas técnicas.
Antes de usar em produção, confira estes itens contra doc.memed.com.br:

- [ ] URLs base da API e do script por ambiente (`config.py`, `DEFAULTS`)
- [ ] Caminhos REST (`memed_client.py`, `PATHS`) e o formato do cadastro de prescritor
- [ ] Nomes e campos dos comandos `setPaciente`, `setAllergy` e `addItem` e o formato do evento
      `prescricaoImpressa` (`templates/revisao.html`, bloco "Integração com o módulo frontend")
- [ ] Como a Memed trata atestados enviados por `addItem` com texto livre (ou se existe um comando
      próprio para documentos)

## Desenvolvimento

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Ao alterar a skill, copie `skills/memed-prescricao/SKILL.md` para `src/memed_mcp/templates/skill.md`
(um teste verifica se as duas cópias estão iguais).

## Aviso

Este software prepara documentos médicos. A responsabilidade pelo conteúdo emitido é do médico que
revisa e assina. Os rascunhos guardam dados de pacientes no volume `/data`, então trate esse volume
como dado sensível (LGPD): mantenha disco criptografado, backup e acesso restrito.
