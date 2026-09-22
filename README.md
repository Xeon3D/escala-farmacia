# Escala da Farmácia

Aplicação web para gerir a equipa, os turnos e as horas de uma farmácia.
Base de dados SQLite, servidor em Python sem dependências externas.

## Arrancar

```bash
python server.py
```

Abre `http://localhost:8765` no navegador. Em Windows podes fazer duplo clique em `start.bat`.

Opções:

```bash
python server.py --port 9000 --host 0.0.0.0 --no-browser --db C:\caminho\escala.db
```

`--host 0.0.0.0` deixa outros computadores da rede local abrir a aplicação. Não há
autenticação, por isso só o faças numa rede de confiança.

## Contas e permissões

Na primeira vez que abres a aplicação, ela pede para criares a conta de
administrador. Não há contas nem palavras-passe predefinidas.

| Papel | O que pode fazer |
|---|---|
| **Administrador** | Tudo: escala, equipa, turnos, regras, importar dados e gerir utilizadores |
| **Ver apenas** | Consultar o horário, as horas e a equipa. Não altera nada |

O separador **Utilizadores** (só para administradores) cria contas, muda o papel,
define palavras-passe e apaga contas. Tem de ficar sempre pelo menos um administrador,
e ninguém apaga a própria conta. O ícone no canto superior direito abre o menu da conta:
**Imagem de perfil** (a partir de um ficheiro ou de um endereço; a imagem é recortada ao
centro e reduzida para 96 px), **Mudar a palavra-passe** e **Sair**.

Detalhes: as palavras-passe são guardadas com PBKDF2-SHA256 (240 000 iterações e sal
por conta); a sessão é um cookie `HttpOnly` com validade de 30 dias, guardado na base de
dados apenas como resumo; mudar a palavra-passe fecha as outras sessões; oito tentativas
falhadas seguidas bloqueiam o login dessa conta durante um minuto.

Se perderes a palavra-passe de administrador, recupera-a na máquina do servidor:

```bash
python server.py --reset-admin o-teu-utilizador
```

O comando pede a nova palavra-passe, cria a conta se não existir, promove-a a
administrador e fecha as sessões abertas. Em Docker:

```bash
docker exec -it escala-farmacia python server.py --reset-admin o-teu-utilizador
```

## Definições

O separador **Definições** junta o que diz respeito à instalação e não à escala:

- **Aparência**: título, subtítulo e logótipo mostrados no cabeçalho e no separador do
  navegador. O logótipo (PNG, JPG, WebP ou SVG) é reduzido para 128 px e fica guardado na
  base de dados. Sem subtítulo, o cabeçalho mostra a **frase do dia**, tirada de
  `public/frases.txt` (piadas separadas por uma linha `--`, podem ter várias linhas; linhas com `#` são ignoradas): muda à meia-noite e, ao clicar, troca por outra ao acaso. Edita o ficheiro à vontade.
- **Versão da aplicação** (administradores): ver abaixo.
- **Dados**: exportar e importar uma cópia em JSON.

## Atualizar sem recriar o contentor

O separador **Definições** tem, para administradores, o painel *Versão da aplicação*:

1. **Procurar atualizações** — lê o ficheiro `VERSION` do repositório e compara com a
   versão a correr.
2. **Atualizar e reiniciar** — descarrega o código do repositório, guarda-o em
   `/data/app/versions/<versão>` e reinicia o processo do servidor dentro do mesmo
   contentor. A base de dados, as contas e as sessões não são tocadas.
3. **Reverter** — volta à versão anterior (ou à que vem na imagem) e reinicia.
4. **Verificar automaticamente** — nunca, de 6 em 6 h, de 12 em 12 h, todos os dias,
   todas as semanas (por omissão) ou todos os meses. O servidor faz a verificação em
   segundo plano; quando encontra uma versão nova, os administradores veem um aviso no
   topo da página com o botão **Ver detalhes**, que leva às Definições com a versão e as
   novidades já à vista.

Como o código fica no volume `/data`, a atualização sobrevive a reinícios do contentor.
Se uma versão instalada não arrancar três vezes seguidas, o arranque volta sozinho à
versão da imagem e avisa nos registos.

Do pacote descarregado só são aceites o `server.py`, o `VERSION` e a pasta `public/`, e o
`server.py` é compilado antes de ser instalado. Só administradores podem atualizar.
Variáveis: `ESCALA_UPDATE_REPO` (por omissão `Xeon3D/escala-farmacia`),
`ESCALA_UPDATE_REF` (ramo ou etiqueta, por omissão `main`), `ESCALA_APP_DIR` e
`ESCALA_UPDATES=0` para desligar a funcionalidade.

Para lançar uma versão nova: sobe `APP_VERSION` no `server.py` **e** o ficheiro
`VERSION` (têm de ser iguais), acrescenta uma entrada `## <versão> — <data>` com a
lista de novidades no topo do `CHANGELOG.md`, faz commit e push. Quem tiver a aplicação
instalada passa a ver a atualização disponível, com as novidades das versões que lhe
faltam.

## Docker

```bash
docker build -t escala-farmacia .
docker run -d --name escala-farmacia -p 8765:8765 -v escala-data:/data escala-farmacia
```

A base de dados fica no volume `/data`. Variáveis: `ESCALA_DB`, `ESCALA_HOST`,
`ESCALA_PORT`. Há também `docker-compose.yml` pronto a usar.

### Instalar no CasaOS

1. No CasaOS: **App Store → Custom Install** (o `+` no canto superior direito).
2. Preenche:
   - **Docker Image**: `<utilizador>/escala-farmacia:latest`
   - **Web UI Port**: `8765` (container) mapeado para o porto que quiseres no host
   - **Volume**: host `/DATA/AppData/escala-farmacia` → container `/data`
   - **Network**: bridge
3. Instala e abre. A base de dados é criada no primeiro arranque, com a equipa inicial.

Em alternativa, importa o `docker-compose.yml` em **Custom Install → Import** e muda só
a linha `image`.

### Publicar no Docker Hub (GitHub Actions)

O workflow `.github/workflows/docker.yml` constrói e publica a imagem `linux/amd64`
a cada push para `main` e em cada tag `v*`. No repositório do GitHub, em
**Settings → Secrets and variables → Actions**, cria:

| Secret | Valor |
|---|---|
| `DOCKERHUB_USERNAME` | o teu utilizador do Docker Hub |
| `DOCKERHUB_TOKEN` | um *access token* criado em Docker Hub → Account settings → Personal access tokens (permissão *Read & Write*) |

Usa um token, nunca a palavra-passe da conta. Para lançar uma versão:

```bash
git tag v1.0.0 && git push --tags
```

## Ficheiros

| Ficheiro | O que é |
|---|---|
| `server.py` | Servidor HTTP + API REST + acesso ao SQLite |
| `public/app.html` | A aplicação (interface completa, sem dependências) |
| `escala.db` | Base de dados SQLite, criada no primeiro arranque |
| `start.bat` | Atalho para arrancar em Windows |
| `Dockerfile`, `docker-compose.yml` | Imagem e serviço para CasaOS ou qualquer Docker |
| `.github/workflows/docker.yml` | Build e publicação automática no Docker Hub |

## Base de dados

Tabelas: `employees`, `shifts`, `assignments` (um registo por pessoa/dia),
`settings` (regras em JSON). Podes inspecionar com qualquer cliente SQLite:

```bash
python -c "import sqlite3;print([r for r in sqlite3.connect('escala.db').execute('select * from assignments limit 5')])"
```

Cópias de segurança: basta copiar `escala.db` (e, se existirem, `escala.db-wal` e
`escala.db-shm`) com o servidor parado. No separador **Definições → Dados** também há
exportação e importação em JSON.

## API

| Método | Caminho | Efeito |
|---|---|---|
| GET | `/api/state` | Tudo: regras, turnos, equipa e escalas |
| GET | `/api/export` | O mesmo, como ficheiro para descarregar |
| PUT | `/api/employees/<id>` | Cria ou atualiza um funcionário |
| DELETE | `/api/employees/<id>` | Apaga o funcionário e os turnos dele |
| PUT | `/api/weeks/<segunda-feira>` | Substitui a escala dessa semana |
| PUT | `/api/config` | Guarda turnos e regras |
| POST | `/api/import` | Substitui tudo por uma cópia em JSON |

## Banco de horas, férias e postos

- **Mínimo semanal**: cada pessoa tem de chegar às horas da semana (40 h por omissão,
  com valor próprio na ficha para quem faz part-time). As horas descontadas do banco
  contam para esse mínimo; quem ficar abaixo aparece nos alertas da semana. **O que
  passar do mínimo são horas extra e entram no banco de horas**, para gastar depois. O
  banco só conta o que já foi efetivamente trabalhado: movimentos de dias futuros aparecem
  como «previstos» no relatório e as horas extra de uma semana só entram quando a semana
  termina.
- **Dia de plantão**: em cada turno desse dia escolhes, no menu da célula, se as horas
  são **pagas** ou vão para o **banco de horas**. Só as horas normais vão para o banco:
  as horas entre as 22:00 e as 09:00 são sempre pagas à parte (a dobrar) e nunca entram
  no banco.
- **Noite de serviço**: das 19:00 às 09:00 nos dias úteis (quem já tinha a noite a terminar
  às 07:00 é atualizado automaticamente para as 09:00, uma única vez) e a começar mais cedo ao fim de
  semana (18:00 por omissão, na regra *Noite ao fim de semana começa às*). Quem faz a noite
  fica obrigatoriamente de folga no dia seguinte
  (um turno nesse dia aparece como conflito). Se a noite calhar a sábado ou domingo, a
  pessoa tem direito a uma **folga extra do plantão**, sempre depois da noite e nunca
  antes: a geração marca-a na semana seguinte, no primeiro dia livre a seguir à folga
  obrigatória, como célula própria («Folga extra do plantão»; também se marca à mão no
  menu da célula). Desconta um «dia completo» (8 h por omissão) ao mínimo dessa semana;
  enquanto não estiver marcada, a semana avisa que está em dívida.
- **Saldo inicial**: a ficha de cada funcionário tem *Banco de horas já acumulado*, para
  lançares as horas de antes de usares a aplicação. Pode ser negativo.
- **Descontar horas**: no menu da célula escolhes −2 h, −4 h, −6 h ou um dia inteiro.
  Descontar o equivalente a um dia (8 h por omissão) transforma o dia numa folga paga
  pelo banco. A aplicação avisa se o saldo não chega.
- **Férias**: marcam-se dia a dia no menu da célula, ou de uma vez no botão *Férias* da
  ficha, indicando o período. Dias de férias não recebem turnos na geração automática e
  descontam um dia ao mínimo dessa semana.
- **Bloquear**: no menu da célula, «Bloquear» fixa o que lá está (turno, folga, férias…):
  nada a altera — nem gerar, nivelar, distribuir almoços, copiar a semana anterior ou
  limpar a semana, nem edições à mão — até ser desbloqueada. Aparece com 🔒.
- **Balcão e backoffice**: cada turno atribuído pode estar ao *balcão* ou em
  *backoffice*. O gráfico de presença e o mínimo ao balcão só contam quem está ao
  balcão; quem está em backoffice aparece numa linha própria e serve de reforço nas
  horas de ponta. Por omissão são 3 ao balcão e 1 em backoffice por dia. O backoffice
  não trabalha ao sábado nem ao domingo.
- **Backoffice por defeito**: na ficha, marca quem trabalha sempre em backoffice. Os
  turnos dessa pessoa entram logo nesse posto e ela não é escalada ao fim de semana.
  Quem está marcado como backoffice faz **sempre o horário de backoffice** (a geração não
  lhe dá turnos de balcão) e almoça sempre à hora fixa, com a duração mínima.
  O horário de backoffice vem definido como um turno próprio — **Backoffice, 09:00–18:00
  com almoço das 12:00 às 13:00** — marcado em *Turnos* com a opção **Backoffice** (nunca
  é usado ao balcão nem cortado ao horário de abertura). Na ficha, aplica-o de segunda a
  sexta com o botão *Aplicar de seg. a sex.*
- **Extras**: na ficha, marca quem é *extra*. Não tem turnos nem mínimo semanal e a
  geração automática não a escala; em cada dia indicas no menu da célula quantas horas
  fez e, se quiseres, a que horas entrou (para contar no gráfico do balcão). As horas
  contam nos totais da semana e do mês.
- **Horas a menos**: se alguém chegou mais tarde ou saiu mais cedo, no menu da célula
  tiras −0,5, −1, −2, −4 h ou outro valor ao turno. As horas saem primeiro das normais
  e só depois das que contam a dobrar.
- **Baixa médica**: marca-se dia a dia no menu da célula ou por período no botão
  *Férias / baixa* da ficha. Tal como as férias, não recebe turnos e desconta um dia ao
  mínimo da semana; aparece em coluna própria no separador *Horas*.
- **Períodos com outro mínimo ao balcão**: em *Turnos → Almoço, balcão…* podes definir
  faixas horárias em que o mínimo é diferente (ex.: das 12:00 às 16:00 chegam 2
  pessoas). Fora dessas faixas vale o mínimo geral.

## Balcão

O separador **Balcão** mostra, para a semana escolhida, uma tabela hora a hora com quem está
ao balcão em cada dia: nomes com a cor de cada pessoa, quem está a almoçar nessa hora
(riscado, ou 🍴 se o almoço apanha só parte da hora), quem está em backoffice (tracejado,
não conta para o mínimo), a contagem face ao mínimo dessa hora e, na última linha, quem
faz a noite de serviço no dia de plantão.

## Horário da farmácia

No separador **Turnos → Horário da farmácia** defines, para cada dia da semana, a hora de
abertura e de fecho, ou marcas o dia como **fechado** (o encerramento semanal). Efeitos:

- Nos dias fechados só se atribui o turno de plantão (a noite de serviço); um turno de
  dia marcado à mão aparece como conflito.
- Os turnos são cortados ao horário de abertura: um turno das 09:00 às 18:00 num sábado
  que fecha às 13:00 faz 09:00–13:00 (4 h, sem almoço). Um turno que nem apanhe o
  horário de abertura não é pedido nesse dia.
- O gráfico «Ao balcão» e o mínimo de pessoas cobrem só o horário de abertura desse dia.
- **Plantão ao fim de semana**: quando o plantão calha a sábado ou domingo, esse dia abre
  desde a hora normal de abertura **até à hora a que entra a noite de serviço** (09:00–18:00
  por omissão) e o domingo, normalmente fechado, abre. A noite segue daí até de manhã
  (09:00). Nesses dias valem as «Pessoas ao sábado» (2) como número escalado e mínimo ao
  balcão; se precisares de mais alguém num período (por exemplo de manhã), acrescenta-o à
  mão na escala. Durante o intervalo de almoço o mínimo do fim de semana conta menos uma
  pessoa — é normal ficar só uma ao balcão enquanto a outra almoça.
- A coluna «Cobertura dos turnos» avisa se os turnos definidos deixam parte do horário
  de abertura sem ninguém.

## Regras implementadas

- **Turnos**: entradas às 9h, 10h e 11h (8 h de trabalho + 1 h de almoço) e noite de
  serviço das 19:00 às 07:00. Tudo editável no separador *Turnos*.
- **Almoço**: duração entre um mínimo e um máximo (1 h a 2 h por omissão), a começar
  dentro do intervalo definido (12:00–16:00) e desencontrado entre colegas. A duração de
  cada dia escolhe-se no menu da célula; a geração usa almoços mais longos para acertar as
  horas da semana, em vez de tirar um dia de trabalho a quem fica acima do alvo. **Quem
  está em backoffice almoça sempre à mesma hora** (13:00 por omissão), com a duração
  mínima (12:00–13:00 por omissão).
- **Horas nocturnas**: as horas entre as 22:00 e as 09:00 **não entram nas horas
  trabalhadas** — ficam à parte, na coluna «horas nocturnas», e pagam-se a dobrar. Na
  noite de serviço das 19:00 às 07:00 só as 3 h das 19:00 às 22:00 contam como
  trabalhadas; as 9 h restantes são horas nocturnas.
- **Geração**: não há quotas por turno. O gerador rege-se por três ideias:
  1. **Segunda a sexta** — toda a gente (menos os extras) trabalha os dias precisos para as
     suas horas semanais (40 h por omissão) e, em cada dia, os turnos são distribuídos para
     que o número de pessoas ao balcão seja o mais parecido possível ao longo da abertura
     (nivelamento automático, sem descer do mínimo de cada faixa).
  2. **Sábado** — só abre de manhã e escala apenas as «Pessoas ao sábado» (2 por omissão),
     a rodar por quem fez menos sábados.
  3. **Domingo** — fechado; quando o plantão calha ao domingo, abre das 09:00 às 18:00 com
     as mesmas pessoas do sábado, mais a noite de serviço.
  Em cada cabeçalho de dia há um botão ↻ **«gerar a partir daqui»**: os dias anteriores
  ficam como estão e a escala é refeita desse dia até domingo.
  O plantão é sempre o primeiro a ser atribuído (a rodar por quem fez menos noites). Quando
  alguém não chega às horas (dias indisponíveis, folgas obrigatórias), a semana avisa.
- **Plantão**: um dia por semana, a recuar um dia por semana. A semana de referência e
  o dia são configuráveis.
- **Descanso**: mínimo de 11 h entre o fim de um turno e o início do seguinte.
- **Balcão**: mínimo de pessoas presentes em cada meia hora de abertura, já a descontar
  os almoços.
