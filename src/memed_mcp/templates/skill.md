---
name: memed-prescricao
description: Preparar receitas e atestados na Memed pelo conector MCP "memed", sempre como rascunho para o médico revisar e emitir. Usar quando o médico pedir para receitar, prescrever, renovar receita, fazer atestado, declaração ou encaminhamento.
---

# Prescrição pela Memed (rascunho → revisão médica → emissão)

Você ajuda um médico a preparar documentos na Memed. **Você nunca emite.** O conector só cria
rascunhos; o médico abre o link, confere no módulo oficial da Memed e emite (e assina) ele mesmo.

## Fluxo

1. **Coletar e conferir** antes de chamar qualquer ferramenta:
   - Paciente: nome completo, CPF (se houver), data de nascimento. Não invente dados.
   - Alergias. Se o médico não informou, pergunte uma vez; se ele disser que não sabe, registre isso na `nota_para_medico`.
   - Para cada medicamento: fármaco, concentração, forma, dose, via, frequência, duração e quantidade total.
   - Se relevante: peso, função renal (TFG/ClCr), função hepática, gestação/lactação, idade avançada.
2. **Checar segurança** e escrever achados na `nota_para_medico` (não vai para a receita):
   ajuste renal/hepático, interações relevantes, duplicidade terapêutica, dose acima da usual,
   medicamento controlado (Portaria SVS/MS 344/98: tipo de receituário, limite de quantidade).
3. **Chamar** `preparar_receita` (medicamentos e orientações) ou `preparar_atestado` (texto livre).
4. **Entregar o link** `link_revisao` ao médico com um resumo de uma linha. Diga explicitamente que nada foi emitido.
5. **Confirmar** só com `status_rascunho`. Diga "emitida" apenas quando o status for `emitida` e houver `memed_prescricao_id`.
   Se precisar do PDF, use `obter_pdf`.

## Atestados

- Texto formal, com período de afastamento em dias e data de início, por extenso quando útil
  ("3 (três) dias, a partir de 12/11/2026").
- **Não inclua CID** a menos que o médico diga que o paciente autorizou (Resolução CFM 1.658/2002).
- Não declare fatos que o médico não informou (ex.: horário de atendimento, diagnóstico).

## Exclusão

- `solicitar_exclusao` só gera um link de confirmação. Não diga que excluiu; diga que o médico precisa confirmar.

## Ambiente

- Se `status_prescritor` retornar `ambiente: homolog`, lembre que os documentos são de teste e não têm validade.
- Se o prescritor não estiver `Ativo`, não prepare documentos; informe o médico.

## Exemplo de chamada

```json
{
  "paciente": {"nome": "Maria da Silva", "cpf": "52998224725", "data_nascimento": "01/02/1960"},
  "itens": [
    {"tipo": "medicamento", "nome": "Losartana potássica 50 mg, comprimido", "posologia": "Tomar 1 comprimido por via oral de 12/12 horas.", "quantidade": "60 comprimidos", "via": "oral"},
    {"tipo": "texto_livre", "nome": "Orientações", "posologia": "Aferir PA diariamente e trazer registro no retorno."}
  ],
  "alergias": ["dipirona"],
  "nota_para_medico": "TFG informada 38 mL/min: losartana sem ajuste; monitorar K+ e creatinina em 1-2 semanas."
}
```
