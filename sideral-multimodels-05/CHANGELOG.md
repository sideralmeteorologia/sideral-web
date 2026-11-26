# Histórico de alterações

## 0.1.2 — 2026-10-27

- Corrige `RuntimeError: Nenhuma variável reconhecida em f000.grib2` no ICON: a grade global
  do ICON é icosaédrica/não estruturada e o GRIB2 de cada campo não traz latitude/longitude
  (`ecCodes provides no latitudes/longitudes for gridType='unstructured_grid'`), então nenhum
  campo era reconhecido e o processamento falhava mesmo com os arquivos baixados corretamente.
- O downloader do ICON agora também baixa, uma única vez por rodada, as coordenadas nativas
  CLAT/CLON publicadas pelo DWD (`.../icon/grib/<ciclo>/clat|clon/`) e as reaproveita para
  todos os leads daquela rodada.
- `process_run`/`_read_fields` usam essas coordenadas como referência quando o GRIB do campo
  não traz lat/lon, mantendo a interpolação por vizinho mais próximo (`cKDTree`) que já existia
  para grades irregulares.

## 0.1.1 — 2026-10-26

- Respeita o horizonte operacional do ICON Global: F120 nos ciclos 06Z/18Z e F180 nos ciclos 00Z/12Z.
- Calcula o horizonte de saída compatível com `minimum_models_per_cell`; com a configuração padrão de dois modelos, ciclos 06Z/18Z terminam em F144.
- Leads do ICON posteriores ao horizonte nativo são ignorados sem abortar o download do consenso.
- Adiciona testes unitários para seleção do horizonte comum e proteção contra tentativa de download em F126+ do ICON nos ciclos curtos.
