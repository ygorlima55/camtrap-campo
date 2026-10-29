# CamTrap Campo

Programa para tratar os dados das armadilhas fotográficas **do cartão SD até a análise**, no Windows, **sem internet**.
As câmeras continuam com o firmware de fábrica; tudo acontece no computador.

> Estado: **Etapa 1 (importação e organização) pronta.** Próximas: 4 (diagnóstico das câmeras), 2 (IA), 3 (análises).

## Instalação (uma vez só)
1. Baixe a pasta do programa (botão verde **Code → Download ZIP** no GitHub) e descompacte, por exemplo, em
   `Documentos\camtrap-campo`. **Não use uma pasta dentro do OneDrive** (ele trava arquivos do programa).
2. Dê dois cliques em **`install.bat`**.
   - Se aparecer "Feche esta janela e rode install.bat de novo", faça isso (foi instalado o `uv`).
   - Ele pergunta se quer instalar **ExifTool**, **FFmpeg** e **Tesseract**. Responda **S** aos três (recomendado).
     O Windows pode pedir permissão de administrador para algum deles.
3. Pronto.

## Uso
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
