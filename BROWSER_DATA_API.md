# Publicação de dados meteorológicos para o navegador

Cada execução concluída com sucesso na branch `main` de um workflow de produto é processada por `.github/workflows/publish-model-releases.yml`.

São incluídos os workflows WRF de CBR, CIM, METBR, Sudeste, TARC e Brasil (todas as resoluções, variantes WRF/WRF2 e fontes existentes), o Global NWP e o Sideral Multimodels.

## Dois destinos com finalidades diferentes

- **GitHub Release público:** download e arquivo dos dados, com tag estável `sideral-data-<produto>-latest`.
- **Branch raw por produto:** leitura direta via JavaScript `fetch()`, sem token, em `raw.githubusercontent.com`. A branch tem o mesmo nome da tag e mantém apenas o snapshot mais recente daquele produto.

Os dois destinos usam os mesmos dados e manifesto. Os arquivos são divididos em partes de até 45 MiB. O manifesto lista o nome original, tamanho, SHA-256, MIME type e URLs das partes. Os nomes publicados são seguros para Windows; timestamps WRF originais permanecem preservados dentro dos arquivos.

## Descobrir os produtos no navegador

A lista de Releases públicos pode ser obtida pela API pública do GitHub:

```js
const releases = await fetch(
  "https://api.github.com/repos/sideralmeteorologia/sideral-web/releases?per_page=100"
).then(response => {
  if (!response.ok) throw new Error(`GitHub API: ${response.status}`);
  return response.json();
});

const products = releases
  .filter(release => /^sideral-data-.+-latest$/.test(release.tag_name))
  .map(release => ({
    tag: release.tag_name,
    manifestUrl:
      `https://raw.githubusercontent.com/sideralmeteorologia/sideral-web/${release.tag_name}/manifest.json`
  }));

const manifests = await Promise.all(
  products.map(product =>
    fetch(product.manifestUrl).then(response => {
      if (!response.ok) throw new Error(`Manifesto indisponível: ${product.tag}`);
      return response.json();
    })
  )
);
```

Para ler um produto, localize o registro em `manifest.files`. Para arquivos não divididos, baixe `file.parts[0].url`. Para arquivos divididos, baixe todas as URLs em `file.parts` em ordem crescente de `part` e concatene os bytes.

```js
async function fetchModelFile(file) {
  const chunks = await Promise.all(
    [...file.parts].sort((a, b) => a.part - b.part).map(async part => {
      const response = await fetch(part.url);
      if (!response.ok) throw new Error(`Download falhou: ${part.name}`);
      return response.arrayBuffer();
    })
  );

  const size = chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
  const result = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(new Uint8Array(chunk), offset);
    offset += chunk.byteLength;
  }
  return result;
}
```

A cada publicação, o publicador testa o acesso ao manifesto em `raw.githubusercontent.com` com HTTP 200 e `Access-Control-Allow-Origin: *`. A API de Releases é usada para descobrir produtos; os dados meteorológicos são lidos do branch raw, não do endpoint de download dos Release assets.

## Retenção

Artifacts do Actions continuam sendo transporte temporário entre jobs. Os produtos finais são preservados no Release público e a versão atual permanece no branch raw específico do produto.
