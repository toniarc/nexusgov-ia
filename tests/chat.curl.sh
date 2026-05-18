#!/usr/bin/env bash
# Testes do endpoint /api/v1/chat via curl (SSE streaming + thinking).
# Uso: copie e cole bloco por bloco no terminal.

NEXUSGOV_API="http://45.79.207.184:8080"
NEXUSGOV_IA="http://localhost:8000"

############################################
# 1. Login no nexusgov-api → exporta TOKEN
############################################
TOKEN=$(curl -s -X POST "$NEXUSGOV_API/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"dre@teste.com","senha":"admin123"}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("token") or d.get("accessToken") or "")')

echo "TOKEN=$TOKEN"

############################################
# 2. Chat sem informar contrato — deve pedir contrato
############################################
curl -N -X POST "$NEXUSGOV_IA/api/v1/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"mensagem":"me fale sobre o contrato 2025/10?"}'

############################################
# 3. Informa contrato — sessão deve lembrar
############################################
curl -N -X POST "$NEXUSGOV_IA/api/v1/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"mensagem":"quais os postos incluidos neste atesto?"}'

############################################
# 4. Pergunta sobre contrato ativo (sem mencionar número)
############################################
curl -N -X POST "$NEXUSGOV_IA/api/v1/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"mensagem":"Mostre todos os colaboradores cadastrados e a categoria dos seus respectivos postos"}'

############################################
# 5. Troca de contrato durante conversa
############################################
curl -N -X POST "$NEXUSGOV_IA/api/v1/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"mensagem":"agora quero ver o contrato 2023/5"}'

############################################
# 6. Pergunta financeira sobre novo contrato ativo
############################################
curl -N -X POST "$NEXUSGOV_IA/api/v1/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"mensagem":"Quais ordens de serviço foram emitidas e quais os valores?"}'

############################################
# 7. Contrato inexistente — resposta amigável, não 4xx/5xx
############################################
curl -N -X POST "$NEXUSGOV_IA/api/v1/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"mensagem":"quero ver o contrato 2099/999"}'

############################################
# 8. Token inválido — deve retornar 401
############################################
curl -i -N -X POST "$NEXUSGOV_IA/api/v1/chat" \
  -H "Authorization: Bearer token.invalido.aqui" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"mensagem":"Qual o valor mensal?"}'

############################################
# 9. Token ausente — deve retornar 403
############################################
curl -i -N -X POST "$NEXUSGOV_IA/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"mensagem":"Qual o valor mensal?"}'
