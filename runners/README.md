# Runners meteorológicos Sideral

## Entradas independentes no GitHub Actions

- `.github/workflows/wrf2-runner.yml`: WRF2; fonte global selecionada separadamente.
- `.github/workflows/icon-runner.yml`: WRF principal com fonte ICON.
- `.github/workflows/gfs-runner.yml`: WRF principal com fonte GFS.
- `.github/workflows/ecmwf-runner.yml`: WRF principal com fonte ECMWF.

Cada runner tem disparo manual, seleção de domínio e cronogramas próprios. Os cronogramas antigos foram transferidos para essas quatro entradas; os motores de domínio não selecionam mais modelo por horário ou por `SOURCE_MODEL` padrão de schedule. A entrada WRF2 roteia seus ciclos para a fonte ICON, GFS ou ECMWF de acordo com o cronograma original e permite escolher a fonte no disparo manual.

## Motores reutilizáveis e código-fonte

Os sete workflows de domínio são chamados por `workflow_call` e preservam segmentos/checkpoints. Scripts Shell/Python, catálogos e Vtables estão versionados em `runners/<domínio>/<modelo>/`, separados em `icon/`, `gfs/`, `ecmwf/`, `wrf2/` e `shared/`. Os workflows apenas copiam esses arquivos para os caminhos de execução que os motores já usam.

O pacote Python multimodelo 0.5 também fica versionado em `runners/multimodels-05/engine.zip`, fora do YAML.

## Perfis WRF

Os parâmetros físicos de cada domínio ficam em `runners/parameters/`. Há perfis separados para Sudeste 4 km e 5 km. Os executores consomem os parâmetros do perfil e mantêm os valores antigos apenas como fallback quando uma variável não estiver definida.

Perfis incluídos: CBR 4 km, CIM 5 km, CIM 8 km, METBR 4 km, Brasil 21 km, Sudeste 4/5 km e TARC 3 km.
