#!/usr/bin/env bash
# Configuração guiada do memed-mcp. Rode dentro da pasta do repositório:
#   bash setup.sh
# Cria o arquivo .env (permissão 600), constrói a imagem, cadastra o
# prescritor na Memed (homologação por padrão) e sobe o serviço.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ask() { # ask VAR "Pergunta" [padrão]
  local var=$1 prompt=$2 def=${3:-} val
  if [ -n "$def" ]; then read -r -p "$prompt [$def]: " val; val=${val:-$def}; else read -r -p "$prompt: " val; fi
  printf -v "$var" '%s' "$val"
}
ask_secret() { local var=$1 prompt=$2 val; read -r -s -p "$prompt: " val; echo; printf -v "$var" '%s' "$val"; }

command -v docker >/dev/null || { echo "Docker não encontrado. Instale com: curl -fsSL https://get.docker.com | sh"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Plugin 'docker compose' não encontrado."; exit 1; }

if [ -f .env ]; then
  read -r -p ".env já existe. Sobrescrever? (s/N): " r
  [[ "$r" =~ ^[sS]$ ]] || { echo "Mantendo .env atual."; SKIP_ENV=1; }
fi

if [ -z "${SKIP_ENV:-}" ]; then
  say "1/3 Chaves da Memed (homologação: copie de doc.memed.com.br > Primeiros passos)"
  ask MEMED_ENV "Ambiente (homolog ou prod)" "homolog"
  ask_secret MEMED_API_KEY "api-key"
  ask_secret MEMED_SECRET_KEY "secret-key"

  say "2/3 Seus dados de prescritor"
  ask NOME "Primeiro nome"
  ask SOBRENOME "Sobrenome"
  ask CPF "CPF (só números)"
  ask NASC "Data de nascimento (dd/mm/aaaa)"
  ask CRM "Número do CRM"
  ask UF "UF do CRM" "SP"
  ask EMAIL "E-mail"
  ask TEL "Celular (só números)"
  ask SEXO "Sexo (M/F)"
  ask CIDADE "Cidade" "São Paulo"
  ask ESPEC "Especialidade" "Nefrologia"
  EXT_ID="crm-$(echo "$UF" | tr '[:upper:]' '[:lower:]')-$CRM"

  say "3/3 Rede"
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  ask HOSTIP "IP ou nome deste servidor na sua rede" "${IP:-127.0.0.1}"
  TOKEN=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')

  umask 077
  cat > .env <<EOF
MEMED_ENV=$MEMED_ENV
MEMED_API_KEY=$MEMED_API_KEY
MEMED_SECRET_KEY=$MEMED_SECRET_KEY
MEMED_PRESCRIBER_EXTERNAL_ID=$EXT_ID
MEMED_PRESCRIBER_NOME=$NOME
MEMED_PRESCRIBER_SOBRENOME=$SOBRENOME
MEMED_PRESCRIBER_CPF=$CPF
MEMED_PRESCRIBER_DATA_NASCIMENTO=$NASC
MEMED_PRESCRIBER_CRM=$CRM
MEMED_PRESCRIBER_UF=$UF
MEMED_PRESCRIBER_EMAIL=$EMAIL
MEMED_PRESCRIBER_TELEFONE=$TEL
MEMED_PRESCRIBER_SEXO=$SEXO
MEMED_PRESCRIBER_CIDADE=$CIDADE
MEMED_PRESCRIBER_ESPECIALIDADE=$ESPEC
PUBLIC_BASE_URL=http://$HOSTIP:8765
MCP_AUTH_TOKEN=$TOKEN
ALLOWED_HOSTS=$HOSTIP:8765,localhost:8765,127.0.0.1:8765
HOST=0.0.0.0
PORT=8765
DATA_DIR=/data
EOF
  chmod 600 .env
  echo ".env criado (só o seu usuário consegue ler)."
fi

say "Construindo a imagem..."
docker compose build

say "Verificando o cadastro na Memed..."
if ! docker compose run --rm memed-mcp status; then
  say "Prescritor ainda não cadastrado. Cadastrando..."
  docker compose run --rm memed-mcp registrar-prescritor
  docker compose run --rm memed-mcp status
fi

say "Subindo o serviço..."
docker compose up -d
sleep 3
. ./.env
curl -fsS "http://127.0.0.1:${PORT:-8765}/healthz" >/dev/null && echo "Serviço no ar."

say "Pronto. Para conectar o Claude Code (no seu computador), rode:"
echo "claude mcp add --transport http memed ${PUBLIC_BASE_URL}/mcp --header \"Authorization: Bearer ${MCP_AUTH_TOKEN}\""
echo
echo "Guarde esse token: ele dá acesso ao conector. Para vê-lo de novo: grep MCP_AUTH_TOKEN .env"
