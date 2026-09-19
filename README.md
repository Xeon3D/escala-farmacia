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
e ninguém apaga a própria conta. Qualquer pessoa muda a sua palavra-passe no botão
*Palavra-passe*, ao lado do nome.

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
`escala.db-shm`) com o servidor parado. No separador **Turnos → Dados** também há
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

## Regras implementadas

- **Turnos**: entradas às 9h, 10h e 11h (8 h de trabalho + 1 h de almoço) e noite de
  serviço das 19:00 às 07:00. Tudo editável no separador *Turnos*.
- **Almoço**: 60 min, a começar entre as 12:00 e as 15:00 (termina até às 16:00),
  desencontrado entre colegas.
- **Horas a dobrar**: entre as 22:00 e as 09:00 cada hora conta a dobrar. Na noite de
  serviço, das 19:00 às 22:00 conta normal e das 22:00 às 07:00 conta a dobrar:
  12 h de presença = 21 h a pagar.
- **Plantão**: um dia por semana, a recuar um dia por semana. A semana de referência e
  o dia são configuráveis.
- **Descanso**: mínimo de 11 h entre o fim de um turno e o início do seguinte.
- **Balcão**: mínimo de pessoas presentes em cada meia hora de abertura, já a descontar
  os almoços.
