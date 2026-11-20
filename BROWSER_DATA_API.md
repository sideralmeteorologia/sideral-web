# Publicação de dados meteorológicos para o navegador

Cada execução concluída com sucesso na branch `main` de um workflow de produto é processada por `.github/workflows/publish-model-releases.yml`.

São incluídos os workflows WRF (CBR, CIM, METBR, Sudeste, TARC e Brasil, em todas as resoluções/variantes/fontes existentes), Global NWP e Sideral Multimodels.

## Dois destinos com finalidades diferentes

- **GitHub Release público:** downloads e arquivo versionado, com tag estável `sideral-data-<produto>-latest`.
- **Branch raw por produto:** leitura direta via JavaScript `fetch()`, sem token, em `raw.githubusercontent.com`. A branch tem o mesmo nome da tag e mantém apenas o snapshot mais recente daquele produto.

Os dois destinos usam os mesmos dados e manifesto. Os arquivos são divididos em partes de até 45 MiB. O manifesto lista o nome original, tamanho, SHA-256, MIME type e URLs das partes. Nomes de arquivo publicados são seguros para Windows; os timestamps WRF originais permanecem preservados no conteúdo.

## Descobrir todos os produtos no navegador

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

Para ler um arquivo, localize o registro em `manifest.files`. Para arquivos não divididos, baixe `file.parts[0].url`. Para arquivos divididos, baixe todas as URLs de `file.parts` em ordem crescente de `part` e concatene os bytes.

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

O publicador testa, a cada atualização, que o manifesto foi servido com HTTP 200 e `Access-Control-Allow-Origin: *`. A API REST do GitHub é usada para descobrir Releases; os dados meteorológicos em si são lidos do branch raw, não do endpoint de download de Release assets.

## Retenção

Artifacts do Actions continuam sendo transporte temporário entre etapas. O produto final é preservado na Release pública e a versão atual é mantida no branch raw específico do produto.
