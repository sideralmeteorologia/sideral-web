# Estado da operação WRF

Atualizado em: 2026-11-21.

## G0 — conformidade e ambiente

- Repositório público, não arquivado, branch default `main`, permissão `ADMIN`.
- Token autenticado como `sideralmeteorologia`; escopos: `repo`, `workflow`, `read:org`, `gist`.
- Actions habilitado; permissão padrão: `read`.
- Secret configurado: `GH_DISPATCH_TOKEN`.
- Watchdog: `disabled_manually`.
- Cache ativo: 31 caches, 2.187.920 bytes.
- Artifacts que casam com prefixos WRF/modelo: 104 registros, 232.512.839.676 bytes (232,5 GB).

Fontes oficiais consultadas em 2026-11-21:
- https://docs.github.com/en/actions/reference/limits
- https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- https://docs.github.com/en/actions/concepts/billing-and-usage
- https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#actions

Conclusão: uso do GitHub-hosted Actions para operar WRF associado ao projeto é compatível com os termos vigentes, desde que siga os limites e não crie carga desproporcional. RISCO-CONFORMIDADE: nenhum material identificado. Runner público confirmado: 4 vCPU, 16 GB RAM, 14 GB SSD.

## G1 — diagnóstico real

Cobertura: 47 workflows operacionais previstos.

Achados:
- CBR: falha determinística em `Pré-validar CBR antes de downloads`, com script esperado ausente.
- CIM 5 km: falha determinística ao restaurar `cim4-namelist.input`/checkpoint.
- METBR GFS: falha determinística por geodata ausente (`topo_gmted2010_5m/index`).
- TARC GFS: WRF reinicia com sucesso, mas o checkpoint falha por `OUTPUT_DIR` não definido.
- Sudeste: 12 clones tinham o passo `Restore WRF runtime` concatenado ao próximo step, invalidando o YAML.

## Correções desta etapa

- Reordenado `OUTPUT_DIR` no checkpoint TARC.
- Tornado o restore CIM4 tolerante a um namelist já normalizado.
- Atualizados os scripts embutidos TARC/CIM4 em 26 workflows.
- Reparada a concatenação de steps nos 12 workflows Sudeste.
- Criados auditor estático e codemod.
- YAML de todos os `.github/workflows/*.yml` validado pelo PyYAML.

## Portões

- G0: PROVADO parcialmente — ambiente/conformidade/artefatos confirmados; plano privado não aplicável ao repo público.
- G1: EM ANDAMENTO — tabela de 47 workflows gerada.
- G2: EM ANDAMENTO.
- G3: NÃO CONCLUÍDO — faltam fontes WRF/WPS/ECMWF específicas.
- G4-G7: NÃO INICIADOS.
