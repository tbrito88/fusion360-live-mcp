# Correções aplicadas neste fork

Derivado de [faust-machines/fusion360-mcp-server](https://github.com/faust-machines/fusion360-mcp-server),
commit `ba8560f` (2026-09-16), adaptado ao **Autodesk Fusion 2704.1.53**.

| | |
|---|---|
| Ferramentas expostas | **92** (eram 93; +`delete_body` em 2026-09-22) |
| Testes | **491 de 491 passam** — todos os bugs desta seção foram achados por teste real, nenhum por auditoria estática |
| Executado dentro do Fusion | sim — várias rodadas de teste ao vivo (CAM, modelagem) |

### Renomeação (2026-09-27)

Para o fork poder ser instalado junto com o original sem colisão, todos os
identificadores globais foram renomeados. O restante deste documento já usa os
nomes novos.

| Onde | Original (upstream) | Neste fork |
|---|---|---|
| Pacote / comando / nome do servidor MCP | `fusion360-mcp-server` | `fusion360-live-mcp` |
| Módulo Python | `fusion360_mcp` | `fusion360_live_mcp` |
| Add-in do Fusion (pasta, `.py`, `.manifest`) | `Fusion360MCP` | `Fusion360LiveMCP` |
| `id` do manifest | UUID do upstream | UUID novo |
| CustomEvent do add-in | `Fusion360MCP_BridgeEvent` | `Fusion360LiveMCP_BridgeEvent` |
| Logger / arquivo de log | `fusion360mcp` / `~/fusion360mcp.log` | `fusion360livemcp` / `~/fusion360livemcp.log` |
| Variáveis de ambiente | `FUSION_MCP_*` | `FUSION360_LIVE_MCP_*` |

Mantidos de propósito: a porta padrão `9876` e o esquema de URI
`fusion360://` (este é isolado por servidor no cliente MCP).

---

## 1. Correção de método — leia antes do resto

As primeiras rodadas deste fork verificaram o código contra os **stubs**
(`API/Python/defs`). Em 2026-09-19 ficou provado que os stubs são uma visão
**filtrada**: omitem membros aposentados que continuam existindo no **módulo de
runtime** (`%LOCALAPPDATA%\Autodesk\webdeploy\production\<hash>\API\Python\packages\adsk\`),
que é o que o Fusion executa.

Consequência: parte do que foi chamado de "bug" aqui era API aposentada que
funciona. A reavaliação, agora contra o runtime:

| Função | Veredito real | Situação |
|---|---|---|
| `add_joint` | **bug real** — `createByPoint` aceita 1 arg, recebia 2 | corrigido |
| `draft_faces` | **bug real** — 4 args, aceita 2..3 | corrigido |
| `scale_body` | **bug real** — 5 args, aceita 3 | corrigido |
| `shell` | **bug real** — `facesToRemove` não existe | corrigido |
| `patch_surface` | **bug real** — `boundaryContinuity` não existe | corrigido |
| `measure_distance` | **bug real** — `pointOnEntityOne/Two` não existem | corrigido |
| `create_section_analysis` | **bug real** — `Component.analyses` não existe | corrigido |
| `extrude`, "parametric box" | não era bug — `setDistanceExtent` existe em runtime | migrado para API atual |
| `fillet` | não era bug | migrado |
| `chamfer` | não era bug | migrado |
| `move_body` | não era bug | migrado |
| `create_ucs` | **não era erro de digitação** — `UserCoordinateSystemGeometry_createByPoint` é alias estático gerado pelo SWIG | migrado para a forma de classe |

**7 bugs reais, 6 modernizações.** As modernizações ficam: a forma atual é a
documentada e sobrevive a uma remoção futura da API aposentada.

---

## 2. Rosca, chapa metálica e CAM

### Rosca — `create_thread`: **reescrita, reabilitada**

Estava quebrada, mas não pelo motivo registrado antes (`threadDataQuery` existe).
O defeito real: passava o `ThreadDataQuery` — objeto de **consulta** — onde a API
espera um `ThreadInfo`, e **ignorava** `thread_designation`, `thread_class` e
`is_internal`. Mesmo rodando, não faria a rosca pedida.

Reescrita no padrão do exemplo oficial da Autodesk (`Python/Samples/Bolt/Bolt.py`):
consulta → `createThreadInfo` → `createInput(faces, info)`.

Agora **valida** contra os dados de rosca instalados e devolve as opções válidas
no erro. Os padrões (`ISO Metric profile` / `M10x1.5` / `6g`) foram conferidos
no XML instalado (`ISOMetricprofile.xml`). Atenção: `6g` é classe **externa**; com
`is_internal=True` use `6H`.

### Pós-processamento CAM — `cam_post_process`: **testado de ponta a ponta em 2026-09-20, G-code real gerado**

Foi desabilitada por engano na análise original. Tudo confere em runtime:
`PostProcessInput.create` (4 args), `CAM.postProcess(operações, input)`,
unidades, `isOpenInEditor`, `genericPostFolder`. Ressalva que persiste: usa API
**aposentada** — funciona hoje, pode sumir numa atualização. A migração, se
precisar, é para `NCPrograms` (padrão no exemplo oficial
`Python/Samples/ManufacturingWorkflowAPISample`).

**Um sexto bug real, achado só na execução de verdade dentro do Fusion — nenhuma
auditoria estática pegaria isto:**

| Bug | Sintoma | Causa | Correção |
|---|---|---|---|
| `program_name` | `RuntimeError: Program number 'NaN' is out of range` | `PostProcessInput.create(setup_name, ...)` passava o **nome do setup** (ex. `"Setup1 (2)"`) como número do programa NC. Posts com `programNameIsInteger=true` (fanuc e a maioria) exigem inteiro puro | novo parâmetro `program_name` (padrão `"1001"`), documentado na ferramenta |

**O verdadeiro bloqueio da trajetória não era bug nenhum**: a operação criada por
`cam_create_operation` nasce com uma ferramenta **genérica calculada por
fórmula** (ex. "fresa de topo 50mm"), nunca vinculada a uma ferramenta real de
biblioteca (fornecedor, com GUID e dados de corte). O motor de CAM aceita a
chamada silenciosamente mas nunca despacha o cálculo — `isGenerationCompleted`
fica preso em `"Generation not started"` para sempre, mesmo com `doEvents()`
correto e minutos de espera real. Isso só foi descoberto porque o usuário
testou manualmente na interface, viu a caixa "Selecionar ferramenta" (biblioteca
vazia para "Biblioteca do Fusion", mas com ferramentas reais em
"Fornecedor > BitsBits"), atribuiu uma ferramenta real, e a partir daí **tanto a
geração manual quanto via `cam_generate_toolpath` funcionaram**.

Consequência prática: `cam_create_operation` **não atribui ferramenta real** por
si só. Para gerar trajetória de verdade é preciso primeiro ter uma ferramenta de
biblioteca (de fornecedor, ou de uma biblioteca local com ferramentas) importada
no documento — isso hoje só é possível pela interface do Fusion, nenhuma
ferramenta deste fork faz a seleção/importação de biblioteca via API.

**Teste real executado**: peça de 6×4×2 cm, operação de facejamento, ferramenta
BitsBits 1/16" (SRB4-062LR), post `fanuc.cps` do próprio Fusion. Resultado:
arquivo `1001.nc`, 68.852 bytes, cabeçalho `O1001`, mais de 16.300 linhas,
terminando em `M30` — G-code Fanuc válido e completo.

### Segunda rodada de teste real (2026-09-20): peça projetada + 4 bugs novos

Teste com peça representativa do projeto: chapa 8×6×1 cm com dois furos de 3 mm
(`create_hole`), estoque com margens de 0,2 cm lateral e 0,1 cm no topo.
Resultado: `1002.nc`, 105.562 bytes, `O1002`, terminando em `M30`.

Quatro bugs reais encontrados **só porque o teste foi executado de verdade** —
nenhuma auditoria estática pegaria nenhum deles:

| Bug | Sintoma | Causa | Correção |
|---|---|---|---|
| `render_view` quebra após qualquer `cam_*` | `'CAM' object has no attribute 'rootComponent'` | `_orient_camera` usava `app.activeProduct`, que devolve o produto CAM quando a workspace Manufacture está ativa | usa `self._design()`, o helper que já existe no arquivo exatamente para isso |
| nome da operação ignorado | pedia "Facejamento", vinha "Face6" | `OperationInput` **não tem** propriedade `name` — o SWIG aceita a atribuição em silêncio, sem efeito | nome setado em `op.name` (de `OperationBase`) **depois** do `add()` |
| estratégias 2D/3D rejeitadas | `Unknown strategy: 2d_contour` | os nomes documentados na ferramenta não são os identificadores internos do Fusion (`contour2d`, `pocket2d`, `adaptive2d`…), lidos de `operations.compatibleStrategies` | mapa de tradução em `cam_create_operation` |
| margem lateral do estoque ignorada | pedia 0,2 cm, ficava no padrão 1 mm | `job_stockOffsetMode` é `'simple'`, e nesse modo o parâmetro ativo é `job_stockOffsetSides`, não `job_stockOffset` que o código escrevia | escreve os dois nomes |

### Lacuna de escopo — seleção de geometria (corrigida em 2026-09-20)

`cam_create_operation` **não selecionava geometria**. Isso não impedia a
estratégia `face`, que tem um padrão sensato (topo do estoque), mas impedia
todas as estratégias baseadas em cadeias de arestas — `contour2d`, `pocket2d`,
`adaptive2d`, `drill`, `bore`.

Sintoma: a operação era criada, ficava `is_valid: True`, aceitava ferramenta, o
`cam_generate_toolpath` retornava sucesso — e `has_toolpath` permanecia
`False`, sem erro. Os parâmetros denunciavam: `geometryType: 'chains'` com
`contours: 'false'`, ou seja, nenhuma cadeia selecionada.

Investigado e descartado no caminho: filtro de diâmetro da ferramenta
(`tool_minDiameter`/`tool_maxDiameter` ficam com o padrão 5–10 mm e **não** são
atualizados ao atribuir `op.tool` via API — corrigir isso era necessário, mas
não suficiente).

**Correção**: novo parâmetro `geometry_face_index` em `cam_create_operation`.
Seleciona uma face do corpo do setup e usa seu laço externo como cadeia —
equivalente a clicar na face na UI do Fusion para um contorno 2D.

Implementação (`_apply_contour2d_geometry`, em `command_handler.py`):

1. Localiza o parâmetro de geometria **por tipo**, não por nome — não existe
   lista pública dos nomes de parâmetro por estratégia, e não é sempre
   `"geometry"`. Percorre `op.parameters` e usa
   `adsk.cam.CadContours2dParameterValue.cast(p.value)`; o primeiro parâmetro
   cujo `cast` não é `None` é o de geometria (classe confirmada no módulo de
   runtime, `getCurveSelections()`/`applyCurveSelections()`).
2. `curveSelections.createNewChainSelection()` + `chain.inputGeometry =
   <arestas do laço externo>`. **Minha primeira versão passava a face direto e
   estava errada** — o teste ao vivo devolveu `3 : Chosen geometry is not
   compatible with input type`. Embora a UI deixe clicar numa face, a API quer
   as arestas: `face.loops` → o laço com `isOuter == True` → `.edges`. Usar o
   laço externo (e não todos) exclui os furos, que é o que clicar no contorno
   da face faz na UI.
3. `geometry_param.applyCurveSelections(curveSelections)` **depois** de
   `setup.operations.add()` — a docstring do próprio tipo avisa que o contorno
   só é ajustado automaticamente "if used on Operations, not OperationInputs";
   aplicar no `OperationInput` antes do `add()` não teria efeito.

Cobre seleção por face (laço externo). Seleção por aresta avulsa ou múltiplas
faces fica para depois, se surgir necessidade real.

### Atribuição de ferramenta — a outra metade do problema

O teste ao vivo mostrou que geometria sozinha não basta: uma operação criada via
API continuava sem toolpath. Causa: **`tool_number` só escreve um parâmetro**,
não anexa ferramenta nenhuma — `op.tool` fica `None` e o filtro de busca fica no
padrão de fábrica 5–10 mm.

E o modo de falha é grave. Gerar uma operação sem ferramenta **não** devolve erro
de API: o Fusion abre um **diálogo modal** ("Falha ao criar percurso; nenhuma
ferramenta selecionada") na thread principal. Essa thread é a mesma que serve o
socket do add-in — a ponte inteira morre, `ping` inclusive, até alguém clicar OK
na janela do Fusion. Aconteceu duas vezes antes de eu diagnosticar; a segunda vez
só foi resolvida porque o usuário mandou print da tela.

Duas correções:

| O quê | Onde |
|---|---|
| Novo parâmetro `tool_from_operation` — reusa a ferramenta real de outra operação e **sincroniza o filtro** (`tool_exactDiameter`/`min`/`max`/`tool_type`) a partir do `tool_diameter`/`tool_type` dela | `_copy_tool_from_operation` |
| `cam_generate_toolpath` recusa gerar se alguma operação do escopo tem `op.tool is None`, com erro claro, em vez de deixar o Fusion abrir o modal e travar a ponte | `_guard_toolless` |

As duas metades são necessárias: atribuir `op.tool` sozinho funciona (a
propriedade aceita e relê a ferramenta certa) mas deixa o filtro em 10 mm, e o
Fusion segue recusando construir percurso para uma fresa de 1,5875 mm.

A biblioteca local (`toollibraryroot://Local/Library`) está **vazia** nesta
instalação, por isso "outra operação" é a fonte prática de ferramenta real.
Puxar direto de biblioteca da nuvem não foi implementado.

### Validação ao vivo (2026-09-20) — artefatos reais

| Arquivo | O que prova |
|---|---|
| `1003.nc` (1.145 bytes, 59 linhas) | geometria aplicada pela nova rotina numa operação com ferramenta atribuída à mão → `has_toolpath: True` → G-code real com `T1 D=1.587 CR=0.794`, terminando em `M30` |
| `1004.nc` (1.148 bytes, 59 linhas) | operação **criada 100% via API** — geometria + ferramenta + filtro, sem toque humano na UI — gerando G-code equivalente |

Post processor: o `fanuc.cps` **não** está no cache do usuário
(`.../CAM/cache/posts/` só tem `index.json`); está empacotado na instalação, em
`.../webdeploy/production/<hash>/Applications/CAM360/Data/Posts/`. Passar o
caminho completo em `post_processor` funciona.

Bug extra encontrado e corrigido no caminho: o branch de timeout do
`_wait_future` lia `future.numberOfCompleted`/`numberOfOperations` sem a mesma
proteção que `isGenerationCompleted` já tinha. Quando a geração nunca chega a
iniciar, esses dois lançam exatamente o mesmo `RuntimeError` — e o resultado era
um crash não tratado no lugar da mensagem de timeout que o código pretendia dar.

### Chapa metálica — **fluxo novo, 3 ferramentas novas + 1 reescrita**

A API do Fusion **não expõe** criação de flange, unfold nem regra de chapa
(`FlangeFeatures`, `UnfoldFeatures`, `SheetMetalRules` são só leitura, também em
runtime). É limitação da plataforma. O caminho que a API oferece:

| Passo | Ferramenta | API |
|---|---|---|
| 1. modelar a forma | `extrude` + `shell` (as paredes viram as abas) | já existentes |
| 2. virar chapa | **`convert_to_sheet_metal`** (nova) | `BRepBody.convertToSheetMetal` |
| 3. dobrar | **`fold_sheet_metal`** (nova) | `FoldFeatures` + `bendLines.add` |
| 4. planificar | **`flat_pattern`** (reescrita) | `Component.createFlatPattern` |
| 5. exportar para corte | **`export_flat_pattern_dxf`** (nova) | `ExportManager.createDXFFlatPatternExportOptions` |

A espessura da chapa **sai da geometria**, não da regra — o `convertToSheetMetal`
copia a regra e troca a espessura pela medida da face base.

Detalhe de implementação que importa: o `_select_faces("top")` do projeto pega
toda face que **toca** o topo — numa chapa, isso inclui as faces de borda, que a
API rejeita. As ferramentas de chapa usam um seletor próprio: a **maior face plana**.

Todos os 36 membros de API usados (22 de chapa + 14 de rosca) foram conferidos
**no runtime**.

O prompt `sheet-metal-enclosure` foi reescrito com esse fluxo (o antigo mandava
usar `create_flange`). O `model-threaded-bolt` voltou.

---

## 3. Continuam desabilitadas

| Ferramenta | Motivo |
|---|---|
| `create_flange` | sem API de criação — substituída por modelar + `convert_to_sheet_metal` |
| `create_bend` | `bendFeatures` não existe — substituída por `fold_sheet_metal` |
| `unfold` | sem API de criação — `flat_pattern` cobre a necessidade de fabricação |
| `trim_surface` | bug real (aridade) com semântica diferente; superfícies, fora do escopo |
| `ruled_surface` | superfícies, fora do escopo; **possivelmente recuperável** — em runtime o `createInput` aceita a chamada, não investigado a fundo |

---

## 4. Não tocado

- **Socket sem autenticação** e **`execute_code` sem sandbox**: design do projeto
  original. Risco a aceitar ou não.
- ~~3 falhas de teste "sem relação"~~ — **eu estava errado ao chamá-las assim.**
  Eram o SDK `mcp` 2.2.0, que o `pyproject` deles (`mcp>=1.0`) deixava instalar.
  A 2.x removeu `Server.list_tools()` e **derrubava o servidor na partida** — ele
  nunca teria funcionado. Resolvido travando `mcp>=1.26,<2` (o `uv.lock` deles usa
  1.26.0) e instalando num ambiente isolado. Suíte inteira passa.

## 5. Limites

- Estado **antes** dos testes ao vivo: a verificação das seções 1 a 4 foi de
  nome e aridade, não de tipo nem de comportamento. `fold_sheet_metal`, sem
  exemplo oficial, foi escrita só a partir das assinaturas e docstrings do
  runtime. As seções 6 a 12 registram a execução real dentro do Fusion.

## 6. Teste real dirigido — flange de acoplamento (2026-09-20)

Peça mecânica real (acopla eixos de TDP/redutor) construída **do
zero, só com ferramentas MCP**, escolhida para forçar o uso de esboço,
revolução, furo, padrão circular, chanfro, rosca, medição, interferência e
exportação — o conjunto mais comum/crítico do fluxo de modelagem. Cada etapa
foi conferida contra cálculo analítico independente (volume, massa), não só
contra o "sucesso" que a ferramenta reportou.

Perfil: cubo raio 2cm altura 3cm + flange raio 5cm espessura 1cm, revolvido
360° em torno do eixo Z. Volume previsto 116,2389 cm³ — `revolve` bateu em 5
casas decimais (116,23893). Todas as etapas seguintes (furo central, furo de
fixação, medição de massa) também bateram com a matemática, exceto pelos bugs
abaixo.

### Bugs reais encontrados e corrigidos

**`fillet`/`chamfer` com `edge_selection: "vertical"` corrompia a peça em
silêncio.** `_select_edges` testava só "mesmo X e mesmo Y entre início e fim
da aresta" para decidir "vertical" — mas uma aresta circular **fechada** (a
borda de um furo) tem início e fim no mesmo ponto, então também passa nesse
teste. Resultado: as 10 bordas de furo de uma chapa 12×8×0,6cm com 5 furos
foram tratadas como "verticais" junto com os 4 cantos reais, e o arredondamento
removeu 25,5 dos 53,4 cm³ — quase metade do material — retornando **sucesso**.
Corrigido exigindo variação real em Z entre os vértices, não só X/Y iguais.

**`undo` retornava `{"undone": True}` sem checar se algo foi desfeito.**
`commandDefinitions.itemById("UndoCommand").execute()` só enfileira um comando
de UI — na prática, o que ele desfez no teste foi uma mudança de câmera, não a
feature de arredondamento com bug, que continuou no timeline. Se eu tivesse
confiado no retorno, teria seguido o teste inteiro em cima de uma peça
corrompida achando que tinha revertido. Corrigido: agora compara
`design.timeline.count` antes/depois e só reporta `undone: True` quando o
timeline realmente encolheu; caso contrário devolve aviso explícito
recomendando `suppress_feature` (determinístico) no lugar.

**`circular_pattern` só padronizava o CORPO inteiro, nunca um feature.** A
descrição da ferramenta ("Pattern a body") era literalmente verdadeira e a
implementação (`circularPatternFeatures.createInput(bodies, axis)`) é API real
do Fusion — mas isso torna a ferramenta inútil para o caso mais comum, um
círculo de parafusos: padronizar um corpo com 1 furo em 6 cópias criou **6
corpos inteiros sobrepostos** (cada um com o furo girado 60° a mais), não uma
peça com 6 furos. Confirmado com `check_interference` depois de corrigido este
e o de baixo. Corrigido com novo parâmetro `feature_name`: quando passado,
padroniza o FEATURE (ex.: o furo), o que o Fusion suporta nativamente passando
uma coleção de `Feature` em vez de `BRepBody` no mesmo `createInput()`.
Validado ao vivo: 6 furos, 1 corpo só, volume bateu com a matemática em 8 casas
decimais (100,65662862).

**`check_interference` nunca encontrava nada em documento de peça única.** Só
buscava em `root.allOccurrences` (componentes de montagem); num documento Part
com vários corpos direto em `root.bRepBodies` — o caso comum deste projeto —
nenhuma ocorrência bate o nome de um corpo, e a ferramenta falhava sempre com
"Need at least 2 components with bodies", **mesmo com nomes de corpo válidos**.
Corrigido com fallback: se não achar por ocorrência, procura por corpo em
`root.bRepBodies`. Validado ao vivo nos dois sentidos — negativo (dois corpos
sem sobreposição, `count: 0`) e positivo (cilindro de teste cruzando a flange
de propósito, interferência calculada em **0,7853981634 cm³** contra os
0,785398 previstos à mão).

**`export_step` sempre falhava para corpo na raiz do documento.**
`createSTEPExportOptions(file_path, body)` passa um `BRepBody` direto — mas o
próprio docstring do módulo de runtime diz que o argumento `geometry` só aceita
um `Component`. Erro real, ao vivo: `3 : invlid argument geometry`, sempre, em
todo corpo de nível raiz — de novo, o caso comum deste projeto (peça única, sem
sub-componentes). Já existia um contorno funcional para corpos dentro de uma
ocorrência de sub-componente (esconder os irmãos, exportar a ocorrência);
apliquei a mesma estratégia para o corpo de raiz — esconder os corpos irmãos,
exportar `rootComponent` (que é mesmo um `Component`), restaurar a
visibilidade no `finally`. Validado: STEP de 30.798 bytes com exatamente **1**
`MANIFOLD_SOLID_BREP`, os outros 3 corpos do documento ficaram de fora, e a
visibilidade original foi restaurada depois.

## 7. Segunda rodada de teste real — suporte de mancal bipartido (2026-09-20)

Segunda peça real, desta vez em **montagem com componentes** (`create_component`,
não corpos soltos na raiz), para cobrir ferramentas ainda não tocadas:
parâmetro/expressão paramétrica, `sweep`, `mirror`, `rectangular_pattern`,
`move_body`, `boolean_operation`, `draft_faces`, `set_color`/`set_appearance`,
`measure_angle`, `create_section_analysis`, `render_view`, `create_rigid_group`,
`export_stl`.

**Truque operacional novo**: em vez de pedir para reiniciar o add-in inteiro a
cada correção, descobri que dá para recarregar o módulo **por dentro**, via
`execute_code` (que roda no mesmo processo Python do add-in):
`importlib.reload()` no módulo `command_handler` + reatribuir
`handler.__class__` à classe recarregada, usando o `_handler` global do módulo
de entrada do add-in. Não precisa mais de intervenção manual na UI a cada
patch — só quando o processo trava de verdade (ex.: o diálogo modal do CAM).

### Bugs reais encontrados e corrigidos

**`draft_faces` — tipo de coleção errado.** `DraftFeatures.createInput` é
tipado `std::vector<Ptr<BRepFace>>` no binding SWIG, não `ObjectCollection`
como quase toda outra API de feature deste arquivo (edgeSetInputs,
curveSelections...). Passar o `ObjectCollection` de `_select_faces` estourava
`TypeError: Wrong number or type of arguments`. Corrigido convertendo para
lista Python só dentro de `draft_faces` (sem tocar em `_select_faces`, usado
por outros handlers que precisam do `ObjectCollection`). Validado ao vivo com
matemática: placa 10×6×2cm com rascunho de 3° a partir do plano inferior —
volume previsto por integração da área da seção transversal, **116,675199**,
medido **116,67519892939877**.

**`get_object_info`, `get_scene_info`, `measure_angle`, `check_interference`,
`export_step` — o mesmo padrão, encontrado 5 vezes.** Todos buscavam objetos
só em `root.bRepBodies`/`root.sketches`, nunca em `root.allOccurrences` — ou
seja, qualquer corpo/esboço dentro de um sub-componente (o padrão normal de
montagem via `create_component`) era invisível para eles. Confirmado ao vivo
de forma decisiva: `get_bounding_box` (que já percorre ocorrências, como
`_body_by_name`) achava `PlacaBase` sem problema, enquanto `get_object_info` e
`get_scene_info`, chamados no mesmo instante, devolviam "não encontrado" ou
simplesmente omitiam o corpo da lista — para um corpo que **demonstravelmente
existia**. Corrigidos todos para também percorrer `root.allOccurrences`.

**`measure_angle` — dois bugs a mais, além do de cima.** (1) Sempre pegava
`faces.item(0)` — a PRIMEIRA face do corpo, sem parâmetro nenhum para escolher
qual — o que inutiliza o uso mais natural da ferramenta (comparar duas faces
específicas, como verificar um ângulo de rascunho). Corrigido com
`face_index_one`/`face_index_two` novos, mesmo padrão já usado em
`geometry_face_index` do CAM e no `face_index` de `create_thread`. (2) Depois
de corrigido, uma chamada real travou com
`'<' not supported between instances of 'str' and 'int'` — os índices
chegaram como string, não int (o dispatcher `handler(**params)` não faz
nenhuma coerção de tipo). Corrigido com `int(face_index)` defensivo dentro do
handler. Validado ao vivo: ângulo entre a base (face 5) e uma face com
rascunho de 3° (face 0) de `PlacaBase` — previsto 87° (90−3), medido
**87,00000000000001°**.

**`create_section_analysis` — `ValueInput` onde o runtime quer `float` puro.**
`SectionAnalyses.createInput(cutPlaneEntity, distance: "float")` — ao
contrário de quase todo outro parâmetro de distância da API do Fusion, este
**não** é um `ValueInput`; é um `float` cru em cm. Envolver em
`ValueInput.createByReal()` estourava
`TypeError: ... argument 3 of type 'double'`. Corrigido passando `float(offset)`
direto. Confirmado ao vivo, antes e depois.

**`set_appearance` — não é bug de lógica, mas o exemplo do próprio schema
nunca funciona.** O código busca corretamente por correspondência exata na
biblioteca certa (com fallback de nome de biblioteca já funcionando). O
problema real: nesta instalação (Fusion em pt-BR), a biblioteca se chama
"Biblioteca de aparência do Fusion" e **todos os 172 nomes de aparência estão
em português** ("Aço - Acetinado", não "Steel - Satin" — o exemplo que o
próprio schema da ferramenta sugere). Não dá para mapear inglês↔português de
forma confiável aqui, então a correção foi: (1) adicionar correspondência
case-insensitive como rede de segurança para diferenças de maiúscula, e (2)
reescrever o erro para nomear a biblioteca real, o total de entradas, e listar
correspondências parciais ou uma amostra real — em vez de um "not found" sem
contexto. Descrição do parâmetro no schema também corrigida para avisar sobre
a localização.

### Falso alarme (registrado pela honestidade do processo)

Suspeitei de `mirror` ao ver Y/Z do corpo espelhado "diferentes" do original —
mas o erro era meu: eu tinha assumido errado onde a varredura (`sweep`)
original tinha ficado no espaço (mesma pegadinha de mapeamento de eixo local
de plano de esboço já documentada para o plano XZ, desta vez no plano YZ).
Conferindo as duas bounding boxes lado a lado, Y e Z eram **idênticos** entre
original e espelho, e X estava perfeitamente invertido — `mirror` sempre
esteve correto.

## 8. Terceira rodada — volante (união de primitivas geométricas diferentes, 2026-09-20)

Peça pedida explicitamente para unir **formas geométricas diferentes**: um
volante de manobra — aro toroidal (`create_torus`), cubo cilíndrico
(`create_cylinder`), 4 raios em cruz (`create_cylinder` × 4, eixos X/Y),
tampa esférica (`create_sphere`) — tudo unido em um corpo só via
`boolean_operation`. Cobriu as últimas primitivas do TemporaryBRepManager
ainda não testadas nesta sessão.

### Bugs reais encontrados e corrigidos

**`create_torus` — o argumento `center` é ignorado pelo próprio motor do
Fusion.** Todos os volumes bateram exatos com a matemática (2π²Rr²), o que
escondeu o problema por várias chamadas — só apareceu ao checar a
**posição** (`get_bounding_box`), quando um torus pedido em `(60,0,0)`
apareceu centrado em `(0,0,0)`. Isolei fora do nosso wrapper, chamando
`TemporaryBRepManager.createTorus()` cru via `execute_code` com um centro
bem longe da origem `(200,50,10)`: o torus nasceu na origem mesmo assim.
`createSphere()`, testado lado a lado com o mesmíssimo padrão de argumento
`center`, posiciona corretamente — o defeito é específico de `createTorus`,
não da API `TemporaryBRepManager` como um todo. Como não dá para corrigir a
chamada em si (ela já segue a assinatura documentada à risca), a correção
foi contornar: mover o corpo temporário com
`TemporaryBRepManager.transform(body, matriz_de_translação)` **antes** de
adicioná-lo ao documento. Validado: torus pedido em `(200,50,10)` agora sai
com bounding box `[196.5,46.5,9.5]` a `[203.5,53.5,10.5]` — exato.

**`boolean_operation` com `join` de corpos que não se tocam apaga o corpo-
ferramenta em silêncio.** Esse foi o bug que mais custou a diagnosticar: 6
uniões encadeadas construindo o volante retornaram "OK" em todas, cada uma
criando uma feature real no timeline com `healthState` saudável e sem
mensagem de erro — mas o resultado final tinha **exatamente** o volume, área,
contagem de faces (1) e bounding box do torus sozinho, como se nada tivesse
sido unido. Isolado com dois testes diretos: (1) dois cilindros que
realmente se sobrepõem — a união funcionou perfeitamente e bateu com a
matemática (interseção de círculos), inclusive **encadeando uma segunda
união** no mesmo corpo já unido, também correta; (2) duas caixas propositalmente
**sem se tocar** — o corpo-ferramenta simplesmente sumiu do documento
(consumido, como o normal) mas seu volume nunca chegou ao alvo. Isso não é
um erro de como chamamos a API — é o comportamento real do `Combine` do
Fusion para sólidos não conectados, e uma vez que a primeira união de uma
cadeia é assim, **todas as uniões seguintes na mesma cadeia também silenciam**,
mesmo as que genuinamente se tocam. (A causa raiz no meu volante era o bug
do `create_torus` acima: o torus mal-posicionado nunca chegava perto do
cubo/raios.) Corrigido com uma checagem antes do `join`:
`measureManager.measureMinimumDistance(target, tool)` — se a distância real
for maior que uma tolerância mínima, recusa com erro claro em vez de deixar
a perda de geometria passar como sucesso. Escopo só em `join`; `cut`/
`intersect` de corpos disjuntos são no-ops legítimos (cortar nada / interseção
vazia) e ficaram sem essa guarda.

**`export_step` (corpo de raiz) ainda vazava corpos de outros
sub-componentes.** A correção da seção 7 resolveu o vazamento de corpos
irmãos na raiz, mas exportar `root` como `Component` continua trazendo a
**árvore inteira** do design — corpos dentro de OUTROS componentes
(`Base`, `Tampa`) nunca eram escondidos. Confirmado ao vivo: o STEP do
`Volante` (corpo de raiz) trazia também `PlacaBase` (componente `Base`) e
`TampaCorpo` (componente `Tampa`) como entidades `MANIFOLD_SOLID_BREP`
próprias. Corrigido escondendo também os corpos de `root.allOccurrences`
antes de exportar. Validado: o STEP corrigido só contém `Volante`.

### Achado registrado, não corrigido — não é bug nosso

O STEP do `Volante` (mesmo corrigido) ainda traz **2** entradas
`MANIFOLD_SOLID_BREP` chamadas "Volante". Verificado ao vivo que o corpo é
geometricamente **1 lump, 1 shell** — uma peça genuinamente conectada, sem
partes soltas. A duplicação parece ser um artefato do próprio tradutor STEP
do Fusion para corpos com histórico de múltiplas base features + combinar
(fora do nosso controle, já que chamamos a API de export exatamente como
documentado).

### Truque de depuração que valeu a pena registrar

Quando um corpo tem features paramétricas dependentes dele no timeline
(mesmo "quebradas", como as 6 uniões sem efeito desta rodada), `deleteMe()`
retorna `True` mas **não apaga o corpo** — ele continua aparecendo em
buscas seguintes. Não persegui a causa raiz disso (provavelmente Fusion
recusa apagar algo com dependentes downstream, silenciosamente); o caminho
prático foi renomear o corpo problemático para tirá-lo do caminho, em vez de
insistir em apagá-lo.

## 9. Projeto real — roda aro 17 estilo BBS RS (2026-09-20)

Pedido do usuário: reproduzir uma roda BBS RS real (foto anexada) em aro 17,
escala verdadeira. Perfil do barril torneado por `revolve` (perfil de 9
pontos, conferido pelo teorema de Pappus: previsto 9373,292744, medido
9373,29274449218 — 8+ casas decimais), cavidade anular cortada, cubo com
furo central e 5 furos de fixação (PCD 114,3mm), 10 raios por `sweep` +
`circular_pattern`, calota central, tudo unido por `boolean_operation`.

### Bug real gravíssimo encontrado e corrigido

**`revolve` (e por extensão `extrude`) com `operation: cut` corta QUALQUER
corpo ao alcance geomético da ferramenta, não só o corpo pretendido — e
sem aviso nenhum.** O corte anular da cavidade da roda (raio até 17,3cm,
360° em torno do eixo Z na origem) **cortou também dois corpos de teste
completamente não relacionados** (`Corpo7` e `Corpo8`, de sessões de teste
muito anteriores) só porque estavam dentro do raio de alcance da revolução,
mesmo fisicamente distantes da roda. Confirmado ao vivo: os dois ganharam
uma face cilíndrica de raio exatamente 17,3cm na mesma origem — a
"assinatura" do corte da roda — e seus volumes ficaram permanentemente
errados até eu diagnosticar e reparar.

Causa raiz: `RevolveFeatureInput`/`ExtrudeFeatureInput`/`SweepFeatureInput`/
`LoftFeatureInput` têm todos a propriedade `participantBodies`, com a MESMA
documentação de risco: *"se não for definida, o comportamento padrão é que
TODO corpo tocado pela ferramenta participa"*. `create_hole` já se protegia
disso corretamente (`hole_input.participantBodies = [body]`); `extrude` e
`revolve` nunca fizeram isso.

Corrigido: novo parâmetro opcional `target_body_name` em `extrude` e
`revolve` — quando informado (e a operação é cut/intersect), restringe
`participantBodies` ao corpo pretendido, replicando a proteção que
`create_hole` já tinha. `sweep`/`loft` têm a mesma exposição documentada e
ficaram sem correção por ora (não usados com `cut` neste projeto até
agora) — registrado como lacuna conhecida.

**Reparo do dano**: apaguei a feature de corte quebrada
(`target.entity.deleteMe()` no timeline), o que reverteu `Corpo7`/`Corpo8`
aos valores originais exatos (47,85862833058845 e 53,44838530828092) —
confirmando que o recompute do Fusion desfaz corretamente o estrago quando a
causa raiz é removida. Refiz o corte com `target_body_name="AroBBS"`;
validado que `Corpo7`/`Corpo8` permaneceram intocados desta vez.

### Consequência estrutural do meu próprio projeto (não bug)

O corte anular que desenhei (removendo TODO material entre r=8 e r=17,3)
desconectou completamente o cubo do aro — sem nenhuma ponte de material
entre eles. O Fusion, corretamente, separou isso em **dois corpos
distintos** (`AroBBS` e um `AroBBS (1)` automático) em vez de manter um
objeto multi-lump inválido. Isso não é bug — é o comportamento certo diante
de um corte que desconecta um sólido — mas me custou uma boa investigação
até perceber que os furos de fixação, colocados na peça errada (`AroBBS`
em vez do cubo real, `AroBBS (1)`), tinham ido parar no lugar errado.
Corrigido renomeando o cubo (`CuboBBS`) e recolocando os furos nele; os
raios (peças avulsas de `sweep`+`circular_pattern`) fizeram a ponte real
entre cubo e aro via `boolean_operation`, com a proteção de distância
mínima (seção 9) impedindo qualquer união sem contato real.

### Validação final

- Perfil do aro: Pappus bate em 8+ casas decimais
- Corpo final: **1 lump** (peça geometricamente conectada de verdade)
- Centro de massa: X≈−1,5×10⁻⁸, Y≈9,0×10⁻¹⁰ (deveriam ser exatamente 0 pela
  simetria de 10 raios) — confirma simetria geométrica perfeita
- STEP exportado: 124.298 bytes, sem vazamento de outros corpos/componentes
- **Nota para o usuário**: o material físico ficou "Aço" (só a aparência
  visual foi trocada para "Alumínio - Acetinado") — 60,6kg é peso de roda de
  aço; uma roda de liga leve real pesa ~8-12kg. Trocar a densidade/material
  real exigiria `set_parameter`/edição de material, não coberto aqui.

### Achado que NÃO é bug — rosca cosmética muda o volume relatado

Aplicar rosca M20×2,5 interna com `is_modeled: false` (cosmética, sem cortar
geometria) fez o `volume` relatado do corpo **subir** de 98,11194 para
101,07135 cm³, apesar de faces/arestas/vértices ficarem idênticos antes e
depois (confirmando que nenhum B-Rep foi cortado). Isso é comportamento
documentado do próprio Fusion: propriedades físicas (massa/volume) de rosca
cosmética são estimadas **como se a rosca estivesse modelada**, mesmo a
geometria visível não mudando — não é um bug deste MCP, é uma pegadinha real
para quem usar a ferramenta e não souber disso.

## 10. Refinamento dos raios + bug do `export_step` para corpo em ocorrência (2026-09-20)

Pedido: trocar os 10 raios retos por uma malha cruzada (estilo BBS RS real).
Cortei a região dos raios antigos, construí dois conjuntos de raios finos
inclinados em ±12° (12 de cada, 24 no total) via `sweep` + `circular_pattern`,
uni tudo de volta com `boolean_operation` (a proteção de distância mínima da
seção 9 funcionou normalmente durante todo o processo, sem incidentes).
Validado: centro de massa em X/Y ~10⁻⁷ (deveria ser exatamente 0 pela simetria
de 24 raios).

### Bug real encontrado e corrigido

**`export_step` — mesmo bug da seção 7, mas no ramo de OCORRÊNCIA, nunca
exercitado antes.** A correção anterior tratou corpo de raiz (`root` como
`Component`) e vazamento entre sub-componentes, mas o ramo para corpo **dentro**
de uma ocorrência de sub-componente ainda passava `occ` (uma `Occurrence`)
direto para `createSTEPExportOptions`, que só aceita `Component` — o mesmo
erro `3 : invlid argument geometry` de antes. Só apareceu agora porque esta
foi a primeira vez que exportei um corpo que vive dentro de uma ocorrência
real (o resultado da importação do STEP anterior, que virou um sub-componente
"(Não salvo) (1)" em vez de ficar na raiz). Corrigido passando `occ.component`
em vez de `occ`. Confirma o padrão da sessão inteira: **um caminho de código
só é validado de verdade quando algo genuíno passa por ele** — a auditoria
estática nunca teria notado essa distinção Occurrence-vs-Component.

## 11. Reconstrução da roda como BBS RS real + filtro de arestas por Z + auto-start (2026-09-22)

Pedido: refinar cubo e raios, que estavam "brutos". Em vez de raios como
cilindros soltos unidos um a um (40+ `boolean_operation`), reconstruí a face
do jeito que uma roda de malha é modelada de verdade: **um disco revolucionado
com janelas vazadas**. Um setor de 18° tem 3 janelas (triângulo interno,
losango, triângulo externo), calculadas como polígonos deslocados de ±w/2 das
linhas dos raios (20 raízes no cubo, cada uma abrindo em V até as raízes
vizinhas; cruzamento em r = 11,6 cm). Cada janela foi cortada com `extrude`
+ `target_body_name` e repetida com `circular_pattern(feature_name=...)`.
Tudo conferido pelo Δ de massa: área × espessura × 7,85 bateu em cada corte
(14,59 / 235,66 / 187,5 g) e em cada padrão (19 × o original). Cubo 4x100
(como na foto de referência), furo central de 73,1 mm, rebaixos das porcas,
calota por interseção esfera ∩ cilindro, 20 parafusos sextavados no anel
externo (extrude join + padrão de feature). Resultado: 1 lump, 988 faces,
3751,9 cm³ (≈ 10,1 kg em alumínio).

### Limitação real encontrada e corrigida

**`fillet`/`chamfer` não conseguiam selecionar arestas em cota intermediária.**
`edge_selection="top"` pega só as arestas na cota máxima do *corpo*. Com o
cubo elevado (Z=−1,2), "top" seria a face do cubo, e nunca a frente dos raios
(Z=−2,4). Adicionados os parâmetros `z_min`/`z_max` (novo helper
`_filter_edges_z`): mantém só arestas cuja bounding box cabe na faixa, e dá
erro claro se o filtro esvaziar a seleção. Validado ao vivo: chanfro de
0,15 cm com `z_min=-2.45, z_max=-2.35` selecionou exatamente 402 arestas
(20 setores × 20 arestas de janela + 2 círculos de transição).

### Auto-start do Fusion (código pronto, NÃO ativado)

`src/fusion360_live_mcp/autolaunch.py`: se o `connect()` falhar em localhost e
não houver processo Fusion360.exe rodando, o servidor liga `runOnStartup` para
*este* add-in em `%APPDATA%/Autodesk/Autodesk Fusion 360/*/JSLoadedScriptsinfo`
(é o Fusion que regrava esse arquivo ao fechar, por isso o patch é feito a cada
lançamento), abre o Fusion pelo atalho do Menu Iniciar (o hash do webdeploy
muda a cada atualização) e espera a porta 9876 abrir. Não reinicia um Fusion
já aberto (risco de perder trabalho). Pode ser desligado com
`FUSION360_LIVE_MCP_AUTOLAUNCH=0`. Os testes forçam o desligamento via
`tests/conftest.py`, e há testes próprios em `tests/test_autolaunch.py`. O manifest
agora tem `runOnStartup: true`. Validado: 365 testes passando, ruff limpo
(incluindo um E501 antigo em um comentário do `chamfer`).

**Armadilha de ambiente:** `uv run pytest` com o servidor MCP rodando dispara
um `uv sync` (as dependências de dev não estavam instaladas) que falha no
meio porque o servidor trava `.pyd`/`.dll` do `.venv`, e deixa o ambiente
**sem metade dos pacotes** (inclusive `fusion360_live_mcp`). O servidor em memória
continua funcionando, mas não sobe de novo. Para testar com o servidor ativo,
use um ambiente separado:
`UV_PROJECT_ENVIRONMENT=<pasta temporária> uv run --dev pytest`.

### Teste de ponta a ponta do auto-start (Fusion fechado pelo usuário)

Primeiro teste real: o auto-start abriu o Fusion e o add-in conectou. Mas
apareceram 4 problemas, todos corrigidos e retestados:

1. **Sem documento aberto.** Aberto sem ninguém na frente, o Fusion fica na
   tela inicial e toda ferramenta falhava com "No active design". Agora
   `_design()` cria um design em branco **só quando não há nenhum documento
   aberto** (um desenho ou outro documento aberto continua dando erro, sem ser
   substituído).
2. **Add-in carregado duas vezes.** `API/AddIns/Fusion360LiveMCP` é uma junction
   para `addon/`, então o Fusion lista o add-in por dois caminhos e inicia os
   dois (confirmado: dois módulos `command_handler` no mesmo processo). Tentei
   desligar a entrada duplicada no `JSLoadedScriptsinfo`, mas **o Fusion regrava
   o arquivo ao iniciar** a partir do manifest compartilhado (mtime do arquivo
   no segundo da inicialização), então essa correção foi removida. A solução
   ficou em `Fusion360LiveMCP.run()`: a primeira cópia se registra em
   `sys._fusion360livemcp_owner`, e a segunda sai sem abrir diálogo (um diálogo
   modal travaria o Fusion). Retestado: só um módulo carregado.
3. **Auto-start só uma vez por sessão.** A marca "já tentei" nunca era
   zerada, então um Fusion fechado de novo não era reaberto. Agora ela é zerada
   a cada conexão bem-sucedida.
4. **O primeiro comando após o Fusion reiniciar falhava** (WinError 10053),
   porque o socket guardado estava morto e comandos que alteram o modelo não
   são repetidos. `send_command` agora checa `_peer_closed()` (select + peek)
   **antes de enviar**, e nesse momento reconectar é seguro, porque nada chegou
   ao add-in.

Validação final (script com o código novo): conectado → Fusion fechado →
`execute_code` no mesmo objeto de conexão → detectou o socket morto, reabriu o
Fusion, criou o design e executou em 29 s, sem erro. 366 testes, ruff limpo.

## 12. Correções achadas num teste de grande porte (2026-09-22 a 2026-09-24)

Um modelo de montagem com mais de 400 corpos e uma linha do tempo de milhares
de features expôs os bugs e lacunas abaixo. Todos foram corrigidos e
validados ao vivo dentro do Fusion.

| Ferramenta | O que acontecia | Correção |
|---|---|---|
| `revolve` | com eixo alinhado a x/y/z, descartava `axis_origin` sem avisar e girava em torno do eixo **global** | eixo de construção só quando a origem é (0,0,0); senão, linha de construção no esboço |
| `revolve` | eixo no lugar errado em esboços XZ/YZ (`addByTwoPoints` recebia coordenadas do modelo) | `sketch.modelToSketchSpace()` nos pontos do eixo |
| `revolve` | "invalid profile(s) for Revolve Feature": o perfil era obtido antes de desenhar o eixo | busca o perfil de novo depois de criar o eixo |
| `delete_body` | reportava sucesso, mas um corpo gerado por feature paramétrica continuava no modelo | usa `removeFeatures.add(body)` e confere que o corpo saiu antes de reportar |
| ponte de eventos | a mensagem de timeout não distinguia um comando que já tinha começado (e ia terminar) | marca `started` e avisa que o comando vai terminar; manda conferir o estado antes de repetir |
| ponte de eventos | espera fixa de 30 s perdia o resultado de comandos longos legítimos | `timeout_s` (até 600 s) respeitado pela ponte e pelo cliente; resultados que chegam depois do limite ficam guardados e são lidos com `late_results()` no `execute_code` |
| mocks | `suppress_feature`/`unsuppress_feature`/`move_body` devolviam formato diferente do handler real | espelham o formato real |
| primitivas e features que criam corpos | não devolviam o nome do corpo criado, embora os mocks prometessem | devolvem `body_name` e `bodies` |
| `rectangular_pattern` / `circular_pattern` / `mirror` | não informavam os nomes das cópias | devolvem `new_bodies` (e `new_body_name` no `mirror`) |
| `sweep` / `loft` | corte sem `participantBodies` atingia qualquer corpo ao alcance (ver seção 9) | `target_body_name` |
| `sweep` | usava só a primeira curva do caminho quando as curvas não compartilhavam pontos de esboço, e ainda reportava sucesso | usa todas as curvas do esboço (`path_curve_index` mantém o comportamento antigo); devolve `path_curves`, `path_length` e `path_warning` |
| `sweep` | perfil fora do perpendicular ao caminho passava despercebido | devolve `profile_tilt_deg` e avisa acima de 1° |
| `shell` | `top`/`bottom` removiam também as paredes laterais | só faces planas voltadas para ±Z; novos `up_facing`/`down_facing` com `z_min`/`z_max` |
| `create_thread` | só aceitava `face_index`, inacessível em peças com milhares de faces | `near_x/near_y/near_z` escolhe a face cilíndrica cujo eixo passa mais perto do ponto |
| `create_thread` | o Fusion redimensiona o cilindro para o diâmetro normalizado da rosca, sem aviso | devolve `diameter_before`/`diameter_after` |
| `create_thread` | `is_internal=False` por padrão pedia rosca externa num furo | deduzido da face; valor contraditório é recusado com mensagem clara |
| `execute_code` | abrir outro documento transformava uma execução bem-sucedida em erro | tolera o design fechado, relê o ativo e devolve `note` |
| deltas | numa troca de documento, "126 → 0 corpos" parecia uma exclusão em massa | os deltas trazem `document_changed` e o servidor avisa |
| `suppress_feature` em lote | o Fusion não recalculava ao restaurar o marcador da linha do tempo | `design.computeAll()` depois de restaurar |
| `rename_body` | devolvia o nome pedido, não o que o Fusion gravou (ex.: com " (1)") | devolve o nome efetivo, com `warning` quando difere |
| `fillet` / `chamfer` | misturar arestas côncavas e convexas falhava (`ASM_BL_CANNOT_REORDER`); a seleção só filtrava por Z | parâmetro `convexity` (`any`/`concave`/`convex`) e janela `x_min/x_max/y_min/y_max` |

### Capacidades novas

- `suppress_feature`/`unsuppress_feature` em lote (`feature_names`), com um
  único recálculo da linha do tempo; o retorno lista `bodies_appeared` e
  `bodies_removed`.
- `move_body` com rotação (`angle`, `axis`, `pivot_x/y/z`).
- `delete_body` (destrutiva): o `undo` não desfaz features criadas pela API.
- `create_cylinder` em qualquer direção (`direction_x/y/z`) e como cone
  (`top_radius`).
- A descrição de `create_box` avisa que `center_z` é a **base**, não o centro.

### Observação sobre `check_interference`

Pares parafuso/furo roscados acusam uma sobreposição igual a
π·(r_haste² − r_furo²)·L. É a zona de engrenamento dos filetes (o Fusion
redimensiona os dois cilindros), não uma colisão.
