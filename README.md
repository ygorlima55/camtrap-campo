# CamTrap Campo

Programa para tratar os dados das armadilhas fotográficas **do cartão SD até a análise**, no Windows, **sem internet**.
As câmeras continuam com o firmware de fábrica; tudo acontece no computador.

> Estado: **todas as etapas prontas** — 1 (importação), 4 (diagnóstico e gestão), 2 (IA) e 3 (análises e exportações).
> IA validada com o SpeciesNet real (modelo 4.0.3a) em fotos de uma MINI400: ~7 s por foto num i5 sem placa de vídeo.

## Instalação (uma vez só)
1. Baixe a pasta do programa (botão verde **Code → Download ZIP** no GitHub) e descompacte, por exemplo, em
   `Documentos\camtrap-campo`. **Não use uma pasta dentro do OneDrive** (ele trava arquivos do programa).
2. Dê dois cliques em **`install.bat`**.
   - Se aparecer "Feche esta janela e rode install.bat de novo", faça isso (foi instalado o `uv`).
   - Ele pergunta se quer instalar **ExifTool**, **FFmpeg** e **Tesseract**. Responda **S** aos três (recomendado).
     O Windows pode pedir permissão de administrador para algum deles.
3. Pronto.

## Uso
> Passo a passo completo, do campo à análise: menu **Guia** dentro do programa (`http://127.0.0.1:8765/guia`).

1. Dê dois cliques em **`run.bat`**. O navegador abre com o programa (endereço `http://127.0.0.1:8765`).
   A janela preta precisa ficar aberta enquanto você usa.
2. Conecte o cartão SD (ou a câmera pelo cabo USB). Ele aparece em **Início** em até 5 segundos.
3. Clique em **Importar este cartão**, informe **câmera** (P4, P7…), **ponto** e **campanha** e clique em
   **Copiar e organizar**. Na próxima vez, o programa sugere o último ponto e campanha daquela câmera.
4. Ao terminar, a página mostra os **alertas** e a lista de arquivos.

### O que a importação faz
- Copia **tudo** do cartão (fotos, vídeos e arquivos ocultos) para `Dados\<campanha>\<ponto>\<camera>\`.
- Confere cada cópia pelo **SHA-256**. **Nunca apaga nada do cartão.**
- Renomeia fotos e vídeos como `<campanha>_<ponto>_<camera>_<AAAAMMDD>_<HHMMSS>_<seq>.<ext>`
  (o nome original fica guardado). Outros arquivos vão para `_cartao_original\` com o nome de origem.
- Descobre o padrão de nomes da câmera pelos próprios arquivos (ex.: Bushnell `10200007.JPG`, genéricas `DSCF0001.JPG`).
- Não duplica: reimportar o mesmo cartão não copia de novo o que já foi importado.
- Lê o **EXIF**, a **faixa do rodapé** (data, hora, temperatura, nome da câmera — exige Tesseract) e os **vídeos**
  (duração, quadros, data — completo com FFmpeg). Mostra quando EXIF e rodapé discordam.

### Alertas
| Alerta | Significado |
|---|---|
| Arquivo "._" de Mac sem a foto | o cartão foi lido num Mac e a foto original não está mais lá |
| Cartão vazio | nenhuma foto ou vídeo |
| Dias sem registros | buraco maior que 48 h entre fotos |
| Relógio resetado / data no futuro | datas antes de 2012 ou depois de hoje — use a correção de horário |
| Data do EXIF difere do rodapé | relógio ou leitura inconsistente; confira a foto |

### Correção de horário
Na página da importação, escolha uma foto cuja hora real você sabe (ex.: a foto do relógio do celular tirada na
instalação) e informe essa hora. A diferença é aplicada a todas as fotos e vídeos daquele cartão; a hora original
fica guardada no banco.

## IA: filtro e identificação (opcional)
1. **Instalar uma vez:** dois cliques em **`instalar_ia.bat`** (baixa ~1 GB: PyTorch, SpeciesNet e modelos).
   Depois a IA funciona sem internet. Usa a placa de vídeo NVIDIA se houver; senão, o processador (mais lento).
2. Na página da importação, clique em **Rodar IA**. O **SpeciesNet** (Google) roda o **MegaDetector v5a**
   (animal, pessoa, veículo) em todas as fotos e em 1 quadro por segundo dos vídeos, e sugere a espécie com
   **filtro geográfico para o Brasil**. Acompanhe em **Tarefas** (pode pausar e retomar; fechar o programa não perde
   o progresso).
3. Clique em **Revisar identificações**: aparecem só as sequências com detecção acima do limiar (padrão 0,2;
   ajuste em **Espécies**), com a caixa da detecção.

| Tecla | Ação |
|---|---|
| Enter | confirmar espécie e ir para a próxima |
| 1–9 | escolher espécie da lista de atalhos (sugestão da IA + últimas usadas) |
| / | buscar espécie pelo nome |
| V / P / X / I | vazio (falso disparo) / pessoa / veículo / indeterminado |
| + / − | número de indivíduos |
| C / D | comportamento / "boa para divulgação" |
| ← → / ↑ ↓ | sequência anterior/próxima / foto da sequência |

- **Espécies** (menu): lista editável (nome científico + popular), começando com fauna da Mata Atlântica e Cerrado.
- **Extrair áudio dos vídeos**: salva um WAV por vídeo em `_audio\` (para futura identificação de cantos de aves e
  anuros). Precisa do FFmpeg.

## Diagnóstico e gestão das câmeras
- **Ao conectar** (botão **Diagnóstico** no cartão): modelo provável (pelo EXIF, pasta e nomes), câmera provável
  (pelos arquivos já importados), última foto com a data e quantas mídias são **novas**.
- **Câmera com a tela apagada**: clique em *Começar teste*, desconecte, ligue a câmera e provoque disparos, reconecte e
  clique em *Verificar*. Se surgirem mídias novas: "processador e gravação OK — defeito provável na tela (cabo flat ou
  luz de fundo)". Se não: o programa mostra os próximos passos. O resultado entra no histórico da câmera.
- **Câmeras** (menu): dias com registro, período e lacunas de cada câmera; histórico de instalação, retirada, troca de
  pilhas (marca e tipo), falhas e observações, com fotos de campo.
- **Roteiros às cegas** (menu): cadastre, por modelo, a sequência de botões de cada ajuste partindo do reset de fábrica e
  imprima o passo a passo. O programa não inventa sequências: confirme numa câmera com tela funcionando.
- **Checklist de campo** (Cadastros → campanha → *Checklist de campo*): versão para imprimir com os cuidados
  (pilhas iguais e novas, cartão formatado na câmera, foto do relógio…) e uma tabela por ponto.

## Validação por espécie, planilha e relatório fotográfico
Menu **Validação**: as sequências analisadas pela IA ficam agrupadas por espécie (filtro por campanha ou câmera). Sugestões com
80% de confiança ou mais já vêm marcadas; **Enter** valida as marcadas do grupo, **C** corrige para outra espécie (ou pessoa,
veículo, vazio, indeterminado), **Espaço** marca/desmarca, **A** marca o grupo, **Z** amplia. Nada é gravado sem a pessoa validar.
- A página de cada câmera lista as espécies registradas por ela (validadas e aguardando).
- **Planilha das espécies (Excel)**: resumo por espécie e um registro por linha, com a sugestão da IA e se ela acertou.
- **Relatório fotográfico**: até 4 fotos por espécie (primeiro as "boas para divulgação"), para imprimir ou salvar em PDF.

## Análises e exportações
Menu **Análises** → escolha a campanha e o intervalo de independência (padrão 30 min). Só entram as identificações
**confirmadas na Revisão** (sugestões da IA não revisadas ficam de fora).
- **Registros independentes**: por espécie e ponto, um novo registro só conta se vier mais de N minutos depois do último
  registro independente.
- **Esforço** em câmeras-dia: da instalação à retirada (eventos da página de cada câmera), descontando os dias de
  **falha** (registre a falha com a data de *Até*). Sem eventos, usa a primeira e a última mídia e avisa.
- **Taxa de captura** (registros / 100 câmeras-dia), riqueza por ponto e **mapa** simples dos pontos (sem mapa de fundo,
  não usa internet).
- **Padrão de atividade** em hora solar (6 h = nascer, 18 h = pôr do sol, calculados pelas coordenadas do ponto),
  densidade circular de kernel e **sobreposição Δ** entre pares de espécies (Δ̂1 com menos de 75 registros, Δ̂4 a partir
  disso; mínimo de 10 registros por espécie).
- **Curva de acumulação** de espécies (média de 200 ordens aleatórias dos dias).
- **Relatório para imprimir/PDF**: página única, sem dependências (no navegador: Ctrl+P → Salvar como PDF).
- **Exportar tudo** (ZIP, também salvo em `Dados\_exportacoes\`): pacote **Camtrap DP 1.0** (GBIF/Wildlife Insights),
  Excel com todas as tabelas, CSVs, tabelas no formato do **camtrapR** (`CTtable` e `recordTable`) e o relatório.

Ainda não há intervalos de confiança (bootstrap) para Δ; para publicação, confira os números no pacote `overlap` do R.

## Privacidade
O programa só funciona neste computador (`127.0.0.1`) e não envia nada para a internet.

## Problemas
- **"uv não é reconhecido"**: rode `install.bat` de novo depois de fechar a janela.
- **Rodapé "Tesseract não instalado"**: instale o Tesseract (passo 2) e reinicie o `run.bat`.
- **Porta ocupada**: o programa escolhe outra sozinho; o endereço aparece na janela preta.

## Para desenvolvedores
```bash
uv sync
uv run pytest
uv run camtrap-campo --sem-navegador
```
Código em `src/camtrap_campo/` (`importacao/`, `metadados/`, `web/`, `db.py`). Testes usam só cartões sintéticos
(`camtrap_campo.amostras`).
