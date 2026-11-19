# Runners meteorológicos Sideral

## Entradas independentes no GitHub Actions

- `.github/workflows/wrf2-runner.yml`: execução WRF2; a fonte global é selecionada separadamente.
- `.github/workflows/icon-runner.yml`: fonte ICON.
- `.github/workflows/gfs-runner.yml`: fonte GFS.
- `.github/workflows/ecmwf-runner.yml`: fonte ECMWF.

Cada entrada permite selecionar o domínio. Os domínios existentes continuam como motores reutilizáveis e preservam segmentos/checkpoints. As entradas WRF2 são limitadas aos domínios onde essa variante já estava implementada.

## Código-fonte dos executores

Scripts Shell, Python, Vtables e catálogos antes embutidos em Base64 ficam versionados em `runners/<domínio>/<modelo>/`: `icon/`, `gfs/`, `ecmwf/`, `wrf2/` e `shared/`. Os workflows copiam os arquivos para o diretório de execução `wrf/`, mantendo os caminhos usados pelos scripts existentes.

O pacote Python multimodelo global foi retirado do YAML e versionado em `runners/multimodels-05/engine.zip`.

## Perfis de parâmetros WRF

Os parâmetros numéricos são carregados no início de cada job a partir de `runners/parameters/`. Sudeste tem perfis distintos para 4 km e 5 km. Os valores foram preservados dos workflows existentes; não foram recalculados nesta refatoração.
